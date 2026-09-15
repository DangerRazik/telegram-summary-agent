"""MTProxy configuration; tests use a separate in-memory Telegram session."""
import asyncio
import base64
import json
import re
from dataclasses import dataclass, asdict
from urllib.parse import urlparse, parse_qs, urlencode

from app_paths import data_path


@dataclass
class ProxySettings:
    enabled: bool = False
    server: str = ''
    port: int = 443
    secret: str = ''

    @classmethod
    def from_link(cls, link):
        url = urlparse(link.strip())
        if not ((url.scheme == 'tg' and url.netloc == 'proxy' and url.path in ('', '/'))
                or (url.scheme == 'https' and url.netloc.lower() in ('t.me', 'telegram.me')
                    and url.path.rstrip('/') == '/proxy')):
            raise ValueError('Вставьте ссылку tg://proxy?... или https://t.me/proxy?...')
        query = parse_qs(url.query)
        if any(len(query.get(key, [])) != 1 for key in ('server', 'port', 'secret')):
            raise ValueError('В ссылке должны быть server, port и secret.')
        try:
            result = cls(True, query['server'][0], int(query['port'][0]), query['secret'][0])
        except ValueError:
            raise ValueError('Порт должен быть числом от 1 до 65535.') from None
        result.validate()
        return result

    def validate(self):
        if type(self.enabled) is not bool:
            raise ValueError('Неверное состояние прокси.')
        if not self.enabled:
            return
        if not isinstance(self.server, str) or not re.fullmatch(r'[A-Za-z0-9.:-]+', self.server):
            raise ValueError('Неверный адрес сервера прокси.')
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError('Порт должен быть числом от 1 до 65535.')
        if not isinstance(self.secret, str):
            raise ValueError('Неверный секрет прокси.')
        try:
            if re.fullmatch(r'[0-9a-fA-F]+', self.secret) and len(self.secret) % 2 == 0:
                raw = bytes.fromhex(self.secret)
            else:
                raw = base64.b64decode(self.secret + '=' * (-len(self.secret) % 4), altchars=b'-_', validate=True)
        except ValueError:
            raise ValueError('Неверный секрет прокси.') from None
        if len(raw) > 16 and raw[0] == 0xee:
            try:
                domain = raw[17:].decode('ascii')
            except UnicodeDecodeError:
                raise ValueError('В ключе Fake TLS указан неверный домен.') from None
            if not 1 <= len(domain) <= 253 or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in domain.split('.')):
                raise ValueError('В ключе Fake TLS отсутствует или повреждён домен.')
        elif not (len(raw) == 16 or (len(raw) == 17 and raw[0] == 0xdd)):
            raise ValueError('Неверный ключ MTProxy: поддерживаются обычный, dd и ee (Fake TLS).')
        self.secret = raw.hex()

    def client_options(self):
        self.validate()
        if not self.enabled:
            return {}
        if self.secret.startswith('ee') and len(self.secret) > 34:
            from mtproxy_tls import ConnectionTcpMTProxyFakeTLS
            return {'connection': ConnectionTcpMTProxyFakeTLS,
                    'proxy': (self.server, self.port, self.secret)}
        from telethon.network.connection import ConnectionTcpMTProxyRandomizedIntermediate
        return {'connection': ConnectionTcpMTProxyRandomizedIntermediate,
                'proxy': (self.server, self.port, 'dd' + self.secret[-32:])}

    def link(self):
        if not self.server:
            return ''
        return 'https://t.me/proxy?' + urlencode({'server': self.server, 'port': self.port, 'secret': self.secret})

    def save(self):
        self.validate()
        path = data_path('proxy_settings.json')
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)

    @classmethod
    def load(cls):
        path = data_path('proxy_settings.json')
        if not path.exists():
            return cls()
        try:
            result = cls(**json.loads(path.read_text(encoding='utf-8')))
            result.validate()
            return result
        except (ValueError, TypeError, OSError):
            raise ValueError('Не удалось прочитать настройки прокси. Откройте «Прокси Telegram» и сохраните их заново.') from None


async def check_connection(settings, api_id, api_hash):
    from telethon import TelegramClient
    from telethon.sessions import MemorySession
    from telethon.tl.functions.help import GetConfigRequest
    probe = TelegramClient(MemorySession(), int(api_id), api_hash,
                           **settings.client_options(), connection_retries=0, request_retries=0,
                           timeout=8, auto_reconnect=False)
    try:
        async def check():
            await probe.connect()
            await probe(GetConfigRequest())
        await asyncio.wait_for(check(), timeout=20)
    except asyncio.CancelledError:
        raise
    except Exception:
        raise ValueError('Не удалось подключиться к Telegram через этот прокси. Проверьте ссылку, интернет или другой сервер.') from None
    finally:
        await probe.disconnect()
