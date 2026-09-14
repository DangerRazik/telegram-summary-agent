"""Outgoing messages only: no polling and no shared recipient registry."""
import os
import httpx
from app_paths import load_config

BOT_USERNAME = 'summaryAgent_bot'
BOT_URL = 'https://t.me/' + BOT_USERNAME


class BotDeliveryError(RuntimeError):
    pass


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
        raise BotDeliveryError('Не удалось связаться с ботом. Проверьте интернет и повторите попытку.') from None
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
    info = await bot_request('getMe')
    if not isinstance(info, dict) or info.get('username', '').lower() != BOT_USERNAME.lower():
        raise BotDeliveryError('В .env указан токен другого бота. Нужен токен @summaryAgent_bot.')


async def send_bot_message(user_id, text):
    if type(user_id) is not int or user_id <= 0:
        raise BotDeliveryError('Не удалось определить аккаунт получателя. Войдите в Telegram заново.')
    result = await bot_request('sendMessage', chat_id=user_id, text=text,
                               link_preview_options={'is_disabled': True})
    if not isinstance(result, dict) or not result.get('message_id'):
        raise BotDeliveryError('Бот не подтвердил доставку. Сводка осталась в очереди.')
