"""Proxy editor shared by login and application settings."""
import asyncio
import tkinter as tk
import customtkinter as ctk
from entry_clipboard import enable_paste
from proxy_settings import ProxySettings, check_connection


class ProxyDialog(tk.Toplevel):
    def __init__(self, parent, loop, api_id, api_hash):
        super().__init__(parent)
        self.withdraw()
        self.title('Прокси Telegram')
        self.geometry('570x410')
        self.resizable(False, False)
        self.configure(bg='#0c2033')
        self.transient(parent)
        self.loop, self.api_id, self.api_hash = loop, api_id, api_hash
        self.task = None
        self.closed = False
        ctk.CTkLabel(self, text='Прокси Telegram', font=('Segoe UI', 22, 'bold')).pack(pady=(24, 16))
        self.switch = ctk.CTkSwitch(self, text='Использовать MTProto-прокси', command=self.toggle)
        self.switch.pack(anchor='w', padx=28)
        ctk.CTkLabel(self, text='Ссылка на прокси', anchor='w').pack(fill='x', padx=28, pady=(18, 4))
        self.value = tk.StringVar(self)
        self.entry = ctk.CTkEntry(self, textvariable=self.value, height=42,
            placeholder_text='https://t.me/proxy?server=…', border_width=1,
            corner_radius=8, fg_color='#0e253b', border_color='#36546e')
        self.entry.pack(fill='x', padx=28)
        enable_paste(self.entry)
        ctk.CTkLabel(self, text='Вход, чтение каналов, «Избранное» и отправка ботом.\nГосПромт использует отдельное соединение.',
            justify='left', anchor='w', text_color='#9ab3cf').pack(fill='x', padx=28, pady=12)
        self.status = ctk.CTkLabel(self, text='', wraplength=510, height=65,
                                  anchor='w', justify='left', text_color='#9ab3cf')
        self.status.pack(fill='x', padx=28)
        actions = ctk.CTkFrame(self, fg_color='transparent')
        actions.pack(fill='x', padx=28, pady=12)
        self.save = ctk.CTkButton(actions, text='Сохранить', command=self.submit, width=160)
        self.save.pack(side='right')
        try:
            settings = ProxySettings.load()
            self.value.set(settings.link())
            if settings.enabled:
                self.switch.select()
        except ValueError as error:
            self.status.configure(text=str(error))
        self.toggle()
        self.protocol('WM_DELETE_WINDOW', self.destroy)
        from window_position import center_dialog
        center_dialog(self, parent)
        self.deiconify()
        self.grab_set()

    def toggle(self):
        self.entry.configure(state='normal' if self.switch.get() else 'disabled')

    def submit(self):
        if self.task is not None and not self.task.done():
            return
        try:
            settings = ProxySettings.from_link(self.value.get()) if self.switch.get() else ProxySettings()
        except ValueError as error:
            self.status.configure(text=str(error))
            return
        self.task = self.loop.create_task(self.run(settings))

    async def run(self, settings):
        self.save.configure(state='disabled')
        self.switch.configure(state='disabled')
        self.entry.configure(state='disabled')
        try:
            if settings.enabled:
                self.status.configure(text='Проверяю подключение к Telegram…')
                await check_connection(settings, self.api_id, self.api_hash)
            settings.save()
            self.status.configure(text='Сохранено. Полностью закройте приложение и запустите заново. В основном окне выход — через трей.')
        except (ValueError, OSError) as error:
            self.status.configure(text=str(error) if isinstance(error, ValueError) else 'Не удалось сохранить настройки прокси.')
        finally:
            if not self.closed:
                self.save.configure(state='normal')
                self.switch.configure(state='normal')
                self.toggle()

    def destroy(self):
        self.closed = True
        if self.task is not None and not self.task.done():
            self.task.cancel()
        super().destroy()
