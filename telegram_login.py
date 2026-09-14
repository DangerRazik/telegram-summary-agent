"""Interactive Telegram login; network work runs on the existing asyncio loop."""
import asyncio
import re
import time
import math
import unicodedata
import tkinter as tk
import json
from pathlib import Path
from uuid import uuid4
from app_paths import data_path
from entry_clipboard import enable_paste
from visual_assets import icon as ui_icon

import customtkinter as ctk
from telethon import errors
from telethon.tl.functions.auth import ResendCodeRequest


def auth_status(stage, **details):
    # Explicit metadata only: no phone, code, password, hash or raw response.
    safe = {key: value for key, value in details.items()
            if key in ('delivery_type', 'next_type', 'timeout', 'error_type')}
    try:
        data_path('telegram_login_status.json').write_text(
            json.dumps({'stage': stage, **safe}, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


def normalize_phone(value):
    value = unicodedata.normalize('NFKC', value)
    phone = ''.join(str(unicodedata.decimal(ch)) if ch.isdecimal() else ch
                    for ch in value
                    if not ch.isspace() and unicodedata.category(ch) != 'Cf'
                    and ch not in '()-‐‑‒–—−')
    if not phone:
        raise ValueError('Поле номера пустое. Введите номер телефона.')
    if not phone.startswith('+'):
        raise ValueError('Номер должен начинаться с + и кода страны.')
    invalid = next((ch for ch in phone[1:] if ch not in '0123456789'), None)
    if invalid is not None:
        raise ValueError(f'В номере есть лишний символ (U+{ord(invalid):04X}). После + нужны только цифры.')
    if not 8 <= len(phone) - 1 <= 15:
        raise ValueError(f'В номере {len(phone) - 1} цифр. Нужен полный номер с кодом страны (для +7 — 11 цифр).')
    return phone


class LoginFlow:
    def __init__(self, client):
        self.client = client
        self.stage = 'connect'
        self.phone = None
        self.code_hash = None
        self.resend_at = 0
        self.code_length = None
        self.delivery = ''

    def accept_code_request(self, sent):
        self.code_hash = sent.phone_code_hash
        self.code_length = getattr(getattr(sent, 'type', None), 'length', None)
        kind = type(getattr(sent, 'type', None)).__name__
        auth_status('code_response', delivery_type=kind,
                    next_type=type(getattr(sent, 'next_type', None)).__name__,
                    timeout=getattr(sent, 'timeout', None))
        self.delivery = {
            'SentCodeTypeApp': 'в служебный чат Telegram на устройстве, где уже выполнен вход',
            'SentCodeTypeSms': 'по SMS',
            'SentCodeTypeCall': 'голосовым звонком',
            'SentCodeTypeEmailCode': 'на электронную почту для входа в Telegram',
        }.get(kind, 'другим способом доставки Telegram')
        self.resend_at = time.monotonic() + (getattr(sent, 'timeout', None) or 60)
        self.stage = 'code'

    async def resend(self):
        if self.stage != 'code' or not self.phone or not self.code_hash:
            raise ValueError('Сначала укажите номер телефона.')
        remaining = math.ceil(self.resend_at - time.monotonic())
        if remaining > 0:
            raise ValueError(f'Новый код можно запросить через {remaining} сек.')
        sent = await self.client(ResendCodeRequest(self.phone, self.code_hash))
        self.accept_code_request(sent)

    async def submit(self, value=''):
        if self.stage == 'connect':
            await self.client.connect()
            self.stage = 'done' if await self.client.is_user_authorized() else 'phone'
        elif self.stage == 'phone':
            phone = normalize_phone(value)
            if not self.client.is_connected():
                await self.client.connect()
            auth_status('requesting_code')
            sent = await self.client.send_code_request(phone)
            self.phone = phone
            self.accept_code_request(sent)
        elif self.stage == 'code':
            code = ''.join(str(unicodedata.decimal(ch)) if ch.isdecimal() else ch
                           for ch in value if not ch.isspace() and ch not in '\u200b\u200e\u200f\ufeff-')
            if not re.fullmatch(r'[0-9]+', code):
                raise ValueError('Введите код из сообщения Telegram.')
            if self.code_length and len(code) != self.code_length:
                raise ValueError(f'Telegram ожидает код из {self.code_length} цифр.')
            try:
                await self.client.sign_in(phone=self.phone, code=code,
                                          phone_code_hash=self.code_hash)
            except errors.SessionPasswordNeededError:
                self.stage = 'password'
            except errors.PhoneCodeExpiredError:
                self.change_phone()
                raise ValueError('Код истёк. Запросите новый код для своего номера.') from None
            else:
                self.stage = 'done'
        elif self.stage == 'password':
            if not value:
                raise ValueError('Введите пароль двухэтапной проверки.')
            await self.client.sign_in(password=value)
            self.stage = 'done'
        return self.stage

    def change_phone(self):
        self.phone = self.code_hash = None
        self.stage = 'phone'


def login_error(error):
    if isinstance(error, ValueError):
        return str(error)
    if isinstance(error, errors.FloodWaitError):
        return f'Telegram просит подождать {error.seconds} сек. перед новой попыткой.'
    if isinstance(error, errors.PhoneNumberInvalidError):
        return 'Telegram не распознал номер. Проверьте код страны и цифры.'
    if isinstance(error, errors.PhoneNumberBannedError):
        return 'Вход с этим номером ограничен Telegram.'
    if isinstance(error, errors.PhoneCodeInvalidError):
        return 'Telegram отклонил код. Введите код для последнего запроса в этом окне или запросите новый.'
    if isinstance(error, errors.PasswordHashInvalidError):
        return 'Неверный пароль двухэтапной проверки.'
    if isinstance(error, (OSError, asyncio.TimeoutError)):
        return 'Не удалось подключиться к Telegram. Проверьте интернет и повторите попытку.'
    return 'Не удалось войти в Telegram. Повторите попытку. Если ошибка сохраняется, проверьте настройки подключения.'


class LoginFrame(ctk.CTkFrame):
    def __init__(self, master, client, on_success, reset_client=None):
        super().__init__(master, fg_color='#071421')
        self.flow = LoginFlow(client)
        self.on_success = on_success
        self.reset_client = reset_client
        self.task = None
        self.closed = False
        card = ctk.CTkFrame(self, fg_color='#0c2033', corner_radius=18,
                           border_width=1, border_color='#1c3c57')
        card.place(relx=.5, rely=.5, anchor='center')
        self.heading = ctk.CTkLabel(card, text='Вход в Telegram', image=ui_icon('logo', 56),
                                    compound='left', padx=10, font=('Segoe UI', 26, 'bold'))
        self.heading.pack(padx=40, pady=(32, 14))
        self.hint = ctk.CTkLabel(card, text='', width=390, wraplength=390,
                                font=('Segoe UI', 14), text_color='#94a3b8')
        self.hint.pack(padx=32, pady=(0, 20))
        # A StringVar is the single source of truth. Placeholder state must not
        # make a visibly filled CTkEntry return an empty string after disabling.
        self.input_value = tk.StringVar(master=self)
        self.entry = ctk.CTkEntry(card, width=390, height=46,
                                 textvariable=self.input_value)
        self.entry.pack(padx=32)
        self.entry.bind('<Return>', lambda event: self.submit())
        enable_paste(self.entry)
        self.error = ctk.CTkLabel(card, text='', width=390, wraplength=390,
                                 text_color='#ef4444')
        self.error.pack(padx=32, pady=10)
        self.button = ctk.CTkButton(card, text='Подключиться', width=390, height=44,
                                    command=self.submit)
        self.button.pack(padx=32, pady=(0, 12))
        self.resend_button = ctk.CTkButton(card, text='Получить новый код',
                                          fg_color='transparent', command=self.resend)
        self.back = ctk.CTkButton(card, text='Изменить номер',
                                 fg_color='transparent', command=self.change_phone)
        self.reset_button = ctk.CTkButton(card, text='Не приходит код? Начать вход заново',
                                         fg_color='transparent', command=self.reset_login)
        self.render()
        self.timer = self.after(500, self.tick)

    def tick(self):
        if self.closed:
            return
        remaining = max(0, math.ceil(self.flow.resend_at - time.monotonic()))
        busy = self.task and not self.task.done()
        self.resend_button.configure(
            text=f'Новый код через {remaining} сек.' if remaining and self.flow.stage == 'code' else 'Получить новый код',
            state='normal' if self.flow.stage == 'code' and not busy and not remaining else 'disabled')
        self.timer = self.after(500, self.tick)

    def render(self):
        stage = self.flow.stage
        hints = {
            'connect': 'Проверяем сохранённый вход в Telegram…',
            'phone': 'Введите номер вашего аккаунта Telegram с кодом страны.',
            'code': f'Код для {self.flow.phone} отправлен {self.flow.delivery}. Введите его ниже.',
            'password': 'Для аккаунта включена двухэтапная проверка. Введите её пароль.',
        }
        self.hint.configure(text=hints.get(stage, 'Вход выполнен'))
        self.entry.configure(show='•' if stage == 'password' else '',
                             state='disabled' if stage == 'connect' else 'normal')
        self.button.configure(text={'connect': 'Повторить подключение', 'phone': 'Получить код',
                                    'code': 'Продолжить', 'password': 'Войти'}.get(stage, 'Войти'))
        self.back.configure(state='normal' if stage in ('code', 'password') else 'disabled')
        self.resend_button.configure(state='disabled')
        self.resend_button.pack_forget()
        self.back.pack_forget()
        self.reset_button.pack_forget()
        if stage == 'code':
            self.resend_button.pack(padx=32, pady=(0, 8))
        if stage in ('code', 'password'):
            self.back.pack(padx=32, pady=(0, 28))
        if stage == 'code' and self.reset_client is not None:
            self.reset_button.configure(state='normal')
            self.reset_button.pack(padx=32, pady=(0, 20))

    def change_phone(self):
        if self.task and not self.task.done():
            return
        self.flow.change_phone()
        self.input_value.set('')
        self.error.configure(text='')
        self.render()

    def resend(self):
        self.submit(resend=True)

    def reset_login(self):
        self.submit(reset=True)

    def submit(self, resend=False, reset=False):
        if self.closed or (self.task and not self.task.done()):
            return
        value = self.input_value.get()
        self.input_value.set('')
        self.entry.configure(state='disabled')
        self.button.configure(state='disabled', text='Подождите…')
        self.back.configure(state='disabled')
        self.resend_button.configure(state='disabled')
        self.reset_button.configure(state='disabled')
        self.error.configure(text='')
        self.task = self.flow.client.loop.create_task(self.run(value, resend, reset))

    async def run(self, value, resend=False, reset=False):
        previous_stage = self.flow.stage
        failed = False
        try:
            if reset:
                if self.reset_client is None:
                    raise ValueError('Сброс входа недоступен.')
                replacement = await asyncio.wait_for(self.reset_client(), timeout=60)
                self.flow = LoginFlow(replacement)
                self.flow.stage = 'phone'
            else:
                await asyncio.wait_for(self.flow.resend() if resend else self.flow.submit(value), timeout=60)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failed = True
            auth_status('error', error_type=type(error).__name__)
            if isinstance(error, errors.FloodWaitError):
                self.flow.resend_at = time.monotonic() + error.seconds
            if not self.closed:
                self.error.configure(text=login_error(error))
        if self.closed:
            return
        if self.flow.stage == 'done':
            self.on_success()
        else:
            self.button.configure(state='normal')
            self.render()
            if failed and previous_stage == 'phone' and self.flow.stage == 'phone':
                self.input_value.set(value)
            self.entry.focus_set()

    def close(self):
        self.closed = True
        if self.task and not self.task.done():
            self.task.cancel()

    def destroy(self):
        self.closed = True
        if getattr(self, 'timer', None):
            self.after_cancel(self.timer)
        super().destroy()
async def reset_pending_client(client, factory):
    """Rotate only a server-confirmed unauthorised session; retain a backup."""
    if not client.is_connected():
        await client.connect()
    # get_me checks the server instead of relying on the authorization cache.
    if await client.get_me() is not None:
        raise ValueError('Вход уже выполнен. Авторизованная сессия не была сброшена.')
    filename = getattr(client.session, 'filename', None)
    if not filename or filename == ':memory:':
        raise ValueError('Не удалось определить файл сессии. Сброс не выполнен.')
    path = Path(filename).resolve()
    await client.disconnect()
    backup = path.with_name(path.name + '.unfinished-' + uuid4().hex + '.bak')
    moved = False
    try:
        if path.exists():
            path.rename(backup)
            moved = True
        replacement = factory(str(path))
    except Exception:
        if moved and not path.exists():
            backup.rename(path)
        raise
    auth_status('session_reset')
    return replacement
