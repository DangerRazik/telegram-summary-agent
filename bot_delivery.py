"""Outgoing messages only: no polling and no shared recipient registry."""
import os
import asyncio
from dataclasses import replace
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telethon.tl.types import InputPeerUser, UpdateShortSentMessage, Updates, UpdatesCombined
from telethon.tl.functions.messages import SendMessageRequest
from proxy_settings import ProxySettings
import httpx
from app_paths import load_config

BOT_USERNAME = 'summaryAgent_bot'
BOT_URL = 'https://t.me/' + BOT_USERNAME


class BotDeliveryError(RuntimeError):
    pass


_proxy = None
_proxy_error = ''
_bot_session = ''
_bot_identity = None
_mtproto_lock = asyncio.Lock()


def configure_proxy(settings, error=''):
    # Match the user client's startup configuration; edits apply after restart.
    global _proxy, _proxy_error
    _proxy = replace(settings)
    _proxy_error = error


def active_proxy():
    if _proxy_error:
        raise BotDeliveryError(_proxy_error)
    return _proxy if _proxy is not None else ProxySettings.load()


async def mtproto_request(settings, user_id=None, text=None, random_id=None):
    """Reuse bot authorization in memory, never read updates or write a session file."""
    global _bot_session, _bot_identity
    load_config()
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        raise BotDeliveryError('Не указан TELEGRAM_BOT_TOKEN в .env рядом с приложением.')
    try:
        api_id = int(os.getenv('TELEGRAM_API_ID', ''))
        api_hash = os.environ['TELEGRAM_API_HASH']
    except (ValueError, KeyError):
        raise BotDeliveryError('Не указаны корректные TELEGRAM_API_ID и TELEGRAM_API_HASH.') from None
    identity = (api_id, api_hash, token)
    async with _mtproto_lock:
        bot = TelegramClient(StringSession(_bot_session if identity == _bot_identity else ''),
            api_id, api_hash, **settings.client_options(), receive_updates=False,
            connection_retries=0, request_retries=0, auto_reconnect=False,
            flood_sleep_threshold=0, timeout=10)
        async def perform():
            global _bot_session, _bot_identity
            await bot.connect()
            me = await bot.get_me()
            if me is None:
                me = await bot.sign_in(bot_token=token)
            if not getattr(me, 'bot', False) or (me.username or '').lower() != BOT_USERNAME.lower():
                raise BotDeliveryError('В .env указан токен другого бота. Нужен токен @summaryAgent_bot.')
            _bot_session = StringSession.save(bot.session)
            _bot_identity = identity
            if user_id is not None:
                # Telegram permits bots to address users by ID with a zero access hash.
                result = await bot(SendMessageRequest(peer=InputPeerUser(user_id, 0),
                    message=text, random_id=random_id, no_webpage=True))
                if not isinstance(result, (UpdateShortSentMessage, Updates, UpdatesCombined)):
                    raise BotDeliveryError('Бот не подтвердил доставку. Сводка осталась в очереди.')
        try:
            await asyncio.wait_for(perform(), timeout=45)
        except asyncio.CancelledError:
            raise
        except BotDeliveryError:
            raise
        except errors.FloodWaitError:
            raise BotDeliveryError('Telegram ограничил частоту отправки. Повторите позже; сводки остаются в очереди.') from None
        except (errors.UserIsBlockedError, errors.YouBlockedUserError, errors.PeerIdInvalidError, errors.ChatWriteForbiddenError):
            raise BotDeliveryError('Откройте @summaryAgent_bot под тем же аккаунтом Telegram и нажмите «Запустить». Если бот заблокирован — разблокируйте его.') from None
        except (errors.AccessTokenInvalidError, errors.AccessTokenExpiredError):
            raise BotDeliveryError('Токен бота недействителен. Проверьте TELEGRAM_BOT_TOKEN.') from None
        except errors.UnauthorizedError:
            _bot_session = ''
            _bot_identity = None
            raise BotDeliveryError('Сессия бота недействительна. Повторите отправку для нового подключения.') from None
        except Exception:
            raise BotDeliveryError('Не удалось отправить запрос бота через MTProto-прокси. Проверьте прокси и повторите попытку; сводки остаются в очереди.') from None
        finally:
            await bot.disconnect()


async def bot_request(method, **payload):
    load_config()
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        raise BotDeliveryError('Не указан TELEGRAM_BOT_TOKEN в .env рядом с приложением.')
    try:
        async with httpx.AsyncClient(timeout=25) as http:
            response = await http.post(f'https://api.telegram.org/bot{token}/{method}', json=payload)
            data = response.json()
    except (httpx.HTTPError, ValueError):
        raise BotDeliveryError('Не удалось подключиться к Bot API (api.telegram.org). Проверьте интернет или включите MTProto-прокси в приложении и перезапустите его.') from None
    if not isinstance(data, dict) or not data.get('ok'):
        code = data.get('error_code') if isinstance(data, dict) else None
        if code in (400, 403):
            raise BotDeliveryError('Откройте @summaryAgent_bot под тем же аккаунтом Telegram и нажмите «Запустить». Если бот заблокирован — разблокируйте его.')
        if code in (401, 404):
            raise BotDeliveryError('Токен бота недействителен. Проверьте TELEGRAM_BOT_TOKEN.')
        if code == 429:
            raise BotDeliveryError('Telegram ограничил частоту отправки. Повторите позже; сводки остаются в очереди.')
        raise BotDeliveryError('Telegram не подтвердил отправку через бота. Повторите позже.')
    return data.get('result')


async def check_bot():
    settings = active_proxy()
    if settings.enabled:
        await mtproto_request(settings)
        return
    info = await bot_request('getMe')
    if not isinstance(info, dict) or info.get('username', '').lower() != BOT_USERNAME.lower():
        raise BotDeliveryError('В .env указан токен другого бота. Нужен токен @summaryAgent_bot.')


async def send_bot_message(user_id, text, random_id=None):
    if type(user_id) is not int or user_id <= 0:
        raise BotDeliveryError('Не удалось определить аккаунт получателя. Войдите в Telegram заново.')
    settings = active_proxy()
    if settings.enabled:
        await mtproto_request(settings, user_id, text, random_id)
        return
    result = await bot_request('sendMessage', chat_id=user_id, text=text,
                               link_preview_options={'is_disabled': True})
    if not isinstance(result, dict) or not result.get('message_id'):
        raise BotDeliveryError('Бот не подтвердил доставку. Сводка осталась в очереди.')
