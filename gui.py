import os
import sys
import asyncio
import time
from schedule import Schedule
from app_paths import data_path, load_config
from summary_modes import SUMMARY_MODES
from bot_delivery import BOT_URL, BotDeliveryError, check_bot, send_bot_message
from entry_clipboard import enable_paste
from datetime import datetime, timezone, timedelta

import customtkinter as ctk
from visual_assets import icon as ui_icon
from styled_controls import Select

from tkinter import messagebox, Toplevel
from telethon.sync import TelegramClient
from telethon.tl.functions.messages import SendMessageRequest

from database import (
    create_database,
    add_channel,
    get_all_channels,
    get_channels,
    delete_channel,
    set_channel_enabled,
    update_last_message,
    save_collected_summary,
    get_pending_delivery,
    mark_delivered
)

from summarizer import summarize_text


# ============================================================
# НАСТРОЙКИ
# ============================================================

load_config()

api_id = os.getenv("TELEGRAM_API_ID")
api_hash = os.getenv("TELEGRAM_API_HASH")

if not api_id or not api_hash:
    raise RuntimeError(
        "Не указаны TELEGRAM_API_ID или TELEGRAM_API_HASH в .env"
    )


client = TelegramClient(
    str(data_path("telegram_summary_session.session")),
    int(api_id),
    api_hash,
    flood_sleep_threshold=0
)


# ============================================================
# ТЕМА
# ============================================================

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ============================================================
# ЦВЕТА
# ============================================================

BG = "#071421"
SIDEBAR = "#091a2b"

CARD = "#0c2033"
CARD_HOVER = "#112b45"

BORDER = "#1c3c57"

BLUE = "#128bff"
BLUE_HOVER = "#0874df"

TEXT = "#f1f5f9"
TEXT_SECONDARY = "#9ab3cf"

GREEN = "#22c98b"
RED = "#ef4444"

BUTTON_DARK = "#0e253b"
BUTTON_DARK_HOVER = "#163b5e"


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def normalize_username(value):
    value = value.strip()

    prefixes = [
        "https://t.me/",
        "http://t.me/",
        "t.me/"
    ]

    for prefix in prefixes:
        if value.startswith(prefix):
            value = value[len(prefix):]

    if value.startswith("@"):
        value = value[1:]

    return value.strip("/")


def prepare_messages_text(name, messages):
    parts = [
        f"Источник: {name}"
    ]

    for message in messages:
        if not message.text:
            continue

        text = message.text.strip()

        if not text:
            continue

        parts.append(
            f"\nДата: {message.date}\n{text}"
        )

    return "\n".join(parts) if len(parts) > 1 else ""


def format_date(value):
    if not value:
        return "Ещё не обрабатывался"

    try:
        date = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        # Older Telegram timestamps without an offset are also UTC.
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        date = date.astimezone(timezone(timedelta(hours=3)))
        return date.strftime("%d.%m.%Y %H:%M")

    except Exception:
        return str(value)


def get_initials(name):
    words = name.split()

    if not words:
        return "?"

    if len(words) == 1:
        return words[0][:2].upper()

    return (
        words[0][0]
        + words[1][0]
    ).upper()


# ============================================================
# ПРИЛОЖЕНИЕ
# ============================================================

class App(ctk.CTk):

    def __init__(self):
        super().__init__()

        self.title("Telegram Summary Agent")
        self.geometry("1450x850")
        self.minsize(1150, 700)

        self.configure(
            fg_color=BG
        )

        from telegram_login import LoginFrame
        self._login = LoginFrame(self, client, self._login_complete, self._reset_login_client)
        self._login.pack(fill='both', expand=True)
        self.after(0, self._login.submit)

    async def _reset_login_client(self):
        global client
        from telegram_login import reset_pending_client
        client = await reset_pending_client(client, lambda filename: TelegramClient(
            filename, int(api_id), api_hash, flood_sleep_threshold=0))
        return client

    def _login_complete(self):
        # Defer rebuilding widgets until the login coroutine has returned.
        self.after(0, self._build_main)

    def _build_main(self):
        self._login.destroy()
        self.grid_columnconfigure(
            1,
            weight=1
        )

        self.grid_rowconfigure(
            0,
            weight=1
        )

        create_database()

        self.last_collection_time = None

        self.latest_summary = ""

        self._schedule_path = data_path("schedule_settings.json")
        self._schedule_error = ""
        try:
            self.schedule = Schedule.load(self._schedule_path)
        except (ValueError, OSError) as error:
            self.schedule = Schedule()
            self._schedule_error = str(error)

        self._avatar_cache = {}
        self._avatar_tasks = {}
        self._avatar_slots = asyncio.Semaphore(3)
        self.create_sidebar()
        self.create_pages()
        self.after(1000, self._check_schedule)

        self.refresh_channels()

        self.show_page(
            "sources"
        )
        self.enable_tray()

    # ========================================================
    # SIDEBAR
    # ========================================================

    def create_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=260, corner_radius=0,
                                    fg_color=SIDEBAR, border_width=1, border_color=BORDER)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(9, weight=1)
        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, padx=22, pady=(28, 24), sticky="ew")
        ctk.CTkLabel(brand, text="", image=ui_icon('logo', 78)).pack(anchor="w")
        ctk.CTkLabel(brand, text="Summary Agent", text_color=TEXT,
                     font=ctk.CTkFont(size=25, weight="bold")).pack(anchor="w", pady=(8, 0))
        self.sources_button = self.create_sidebar_button('Источники', lambda: self.show_page('sources'), 3)
        self.summary_button = self.create_sidebar_button('Сводка', lambda: self.show_page('summary'), 4)
        self.settings_button = self.create_sidebar_button('Настройки', lambda: self.show_page('settings'), 5)
    def create_sidebar_button(self, text, command, row):
        kind = {'Источники': 'document', 'Сводка': 'summary', 'Настройки': 'settings'}[text]
        button = ctk.CTkButton(self.sidebar, text=text, image=ui_icon(kind, 30, '#b9d6f7'),
            compound="left", border_spacing=16, command=command, height=58,
            corner_radius=12, anchor="w", font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="transparent", hover_color=BUTTON_DARK_HOVER, text_color=TEXT)
        button.grid(row=row, column=0, padx=18, pady=5, sticky="ew")
        return button

    # ========================================================
    # СТРАНИЦЫ
    # ========================================================

    def create_pages(self):
        self.content = ctk.CTkFrame(
            self,
            fg_color=BG,
            corner_radius=0
        )

        self.content.grid(
            row=0,
            column=1,
            sticky="nsew"
        )

        self.content.grid_rowconfigure(
            0,
            weight=1
        )

        self.content.grid_columnconfigure(
            0,
            weight=1
        )

        self.sources_page = ctk.CTkFrame(
            self.content,
            fg_color=BG
        )

        self.summary_page = ctk.CTkFrame(
            self.content,
            fg_color=BG
        )

        self.settings_page = ctk.CTkFrame(
            self.content,
            fg_color=BG
        )

        self.sources_page.grid(
            row=0,
            column=0,
            sticky="nsew"
        )

        self.summary_page.grid(
            row=0,
            column=0,
            sticky="nsew"
        )

        self.settings_page.grid(
            row=0,
            column=0,
            sticky="nsew"
        )

        self.create_sources_page()
        self.create_summary_page()
        self.create_settings_page()

    # ========================================================
    # ПЕРЕКЛЮЧЕНИЕ
    # ========================================================

    def show_page(self, page):
        self.sources_button.configure(
            fg_color="transparent"
        )

        self.summary_button.configure(
            fg_color="transparent"
        )

        self.settings_button.configure(
            fg_color="transparent"
        )

        if page == "sources":
            self.sources_page.tkraise()

            self.sources_button.configure(
                fg_color="#123963"
            )

        elif page == "summary":
            self.summary_page.tkraise()

            self.summary_button.configure(
                fg_color="#123963"
            )

        elif page == "settings":
            self.settings_page.tkraise()

            self.settings_button.configure(
                fg_color="#123963"
            )

    # ========================================================
    # ИСТОЧНИКИ
    # ========================================================

    def create_sources_page(self):
        page = self.sources_page

        page.grid_columnconfigure(
            0,
            weight=1
        )

        page.grid_rowconfigure(
            5,
            weight=1
        )

        # ----------------------------------------------------
        # HEADER
        # ----------------------------------------------------

        header = ctk.CTkFrame(
            page,
            fg_color="transparent"
        )

        header.grid(
            row=0,
            column=0,
            padx=40,
            pady=(35, 10),
            sticky="ew"
        )

        header.grid_columnconfigure(
            0,
            weight=1
        )

        title = ctk.CTkLabel(
            header,
            text="Источники",
            text_color=TEXT,
            font=ctk.CTkFont(
                size=34,
                weight="bold"
            )
        )

        title.grid(
            row=0,
            column=0,
            sticky="w"
        )

        # ----------------------------------------------------
        # ПОИСК
        # ----------------------------------------------------

        self.search_entry = ctk.CTkEntry(
            header,
            width=300,
            height=44,
            placeholder_text="⌕  Поиск источника...",
            corner_radius=12,
            fg_color=CARD,
            border_color=BORDER
        )

        self.search_entry.grid(
            row=0,
            column=1,
            rowspan=2,
            sticky="e"
        )

        self.search_entry.bind(
            "<KeyRelease>",
            lambda event: self.refresh_channels()
        )

        # ----------------------------------------------------
        # КНОПКИ
        # ----------------------------------------------------

        actions = ctk.CTkFrame(
            page,
            fg_color="transparent"
        )

        actions.grid(
            row=1,
            column=0,
            padx=40,
            pady=(15, 20),
            sticky="ew"
        )

        add_button = ctk.CTkButton(
            actions,
            text="+  Добавить источник",
            width=210,
            height=48,
            corner_radius=12,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            font=ctk.CTkFont(
                size=14,
                weight="bold"
            ),
            command=self.open_add_window
        )

        add_button.pack(
            side="left"
        )

        self.collect_button = ctk.CTkButton(
            actions,
            text="▷  Собрать сообщения",
            width=220,
            height=48,
            corner_radius=12,
            fg_color=BUTTON_DARK,
            hover_color=BUTTON_DARK_HOVER,
            border_width=1,
            border_color="#506176",
            font=ctk.CTkFont(
                size=14,
                weight="bold"
            ),
            command=self.collect_messages
        )

        self.collect_button.pack(
            side="left",
            padx=12
        )

        refresh_button = ctk.CTkButton(
            actions,
            text="Обновить",
            image=ui_icon("refresh", 22, "#c3d9ee"), compound="left",
            width=140,
            height=48,
            corner_radius=12,
            fg_color=BUTTON_DARK,
            hover_color=BUTTON_DARK_HOVER,
            border_width=1,
            border_color="#506176",
            command=self.refresh_channels
        )

        refresh_button.pack(
            side="right"
        )

        # ----------------------------------------------------
        # СТАТИСТИКА
        # ----------------------------------------------------

        self.stats_frame = ctk.CTkFrame(
            page,
            fg_color="transparent"
        )

        self.stats_frame.grid(
            row=2,
            column=0,
            padx=40,
            pady=(0, 20),
            sticky="ew"
        )

        for column in range(4):
            self.stats_frame.grid_columnconfigure(
                column,
                weight=1
            )

        self.total_card = self.create_stat_card(
            self.stats_frame,
            0,
            "0",
            "Всего источников",
            "◉"
        )

        self.active_card = self.create_stat_card(
            self.stats_frame,
            1,
            "0",
            "Активных",
            "✓"
        )

        self.disabled_card = self.create_stat_card(
            self.stats_frame,
            2,
            "0",
            "Отключённых",
            "⊘"
        )

        self.last_card = self.create_stat_card(
            self.stats_frame,
            3,
            "—",
            "Последний сбор",
            "◷"
        )

        # ----------------------------------------------------
        # СПИСОК
        # ----------------------------------------------------

        list_container = ctk.CTkFrame(
            page,
            fg_color=CARD,
            corner_radius=16,
            border_width=1,
            border_color=BORDER
        )

        list_container.grid(
            row=5,
            column=0,
            padx=40,
            pady=(0, 20),
            sticky="nsew"
        )

        list_container.grid_columnconfigure(
            0,
            weight=1
        )

        list_container.grid_rowconfigure(
            1,
            weight=1
        )

        list_title_frame = ctk.CTkFrame(
            list_container,
            height=44,
            fg_color="transparent"
        )
        list_title_frame.pack_propagate(False)

        list_title_frame.grid(
            row=0,
            column=0,
            padx=20,
            pady=(17, 8),
            sticky="ew"
        )

        list_title = ctk.CTkLabel(
            list_title_frame,
            text="Отслеживаемые источники",
            text_color=TEXT,
            font=ctk.CTkFont(
                size=15,
                weight="bold"
            )
        )

        list_title.pack(
            side="left"
        )

        self.channels_frame = ctk.CTkScrollableFrame(
            list_container,
            fg_color="transparent"
        )

        self.channels_frame.grid(
            row=1,
            column=0,
            padx=12,
            pady=(0, 12),
            sticky="nsew"
        )

        self.collection_banner = ctk.CTkFrame(
            list_title_frame, width=1, height=44, fg_color="transparent", corner_radius=8,
            border_width=0, border_color=BLUE
        )
        self.collection_banner.pack_propagate(False)
        self.collection_banner.grid_propagate(False)
        self.collection_banner.grid_columnconfigure(0, weight=1)
        self.collection_banner.grid_rowconfigure(0, weight=1)
        self.collection_banner.pack(side="right", fill="x", expand=True, padx=(20, 0))
        self.sources_status_label = ctk.CTkLabel(
            self.collection_banner, text="", text_color=TEXT, height=26,
            font=ctk.CTkFont(size=12, weight="bold"), anchor="w"
        )
        self.sources_status_label.grid(row=0, column=0, padx=12, pady=6, sticky="ew")
        self.collection_progress = ctk.CTkProgressBar(
            self.collection_banner, height=4, progress_color=BLUE,
            fg_color="#29445f", mode="determinate"
        )
        # Overlay the progress bar at the bottom without shifting the text's centre.
        self.collection_progress.grid(row=0, column=0, sticky="sew", padx=12, pady=(0, 4))
        self.collection_progress.set(0)
        self.collection_progress.grid_remove()

    # ========================================================
    # КАРТОЧКА СТАТИСТИКИ
    # ========================================================

    def create_stat_card(self, parent, column, value, title, icon):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=15,
                           border_width=1, border_color=BORDER, height=100)
        card.grid(row=0, column=column,
                  padx=(0 if column == 0 else 6, 0 if column == 3 else 6), sticky="ew")
        card.grid_propagate(False)
        card.grid_columnconfigure(1, weight=1)
        card.grid_rowconfigure(0, weight=1)
        kinds = ('users', 'active', 'disabled', 'clock')
        colors = ('#369eff', '#29d481', '#f56779', '#a8c9fa')
        ctk.CTkLabel(card, text="", image=ui_icon(kinds[column], 42, colors[column], True)).grid(
            row=0, column=0, padx=(12, 10))
        info = ctk.CTkFrame(card, fg_color="transparent")
        info.grid(row=0, column=1, padx=(0, 12), sticky="ew")
        value_label = ctk.CTkLabel(info, text=value, height=26, anchor="w",
            text_color=TEXT, font=ctk.CTkFont(size=14 if column == 3 else 21, weight="bold"))
        value_label.pack(anchor="w")
        ctk.CTkLabel(info, text=title, height=22, anchor="w", text_color=TEXT_SECONDARY,
                     font=ctk.CTkFont(size=12)).pack(anchor="w")
        card.value_label = value_label
        return card

    # ========================================================
    # ОБНОВЛЕНИЕ СПИСКА
    # ========================================================

    def refresh_channels(self):
        if not hasattr(
            self,
            "channels_frame"
        ):
            return

        self._channel_rows = {}
        for widget in self.channels_frame.winfo_children():
            widget.destroy()

        channels = get_all_channels()

        search = ""

        if hasattr(
            self,
            "search_entry"
        ):
            search = (
                self.search_entry.get()
                .strip()
                .lower()
            )

        filtered = []

        for channel in channels:
            name = channel[1]
            username = channel[2]

            if (
                search
                and search not in name.lower()
                and search not in username.lower()
            ):
                continue

            filtered.append(channel)

        if not filtered:
            empty = ctk.CTkLabel(
                self.channels_frame,
                text="Источники не найдены",
                text_color=TEXT_SECONDARY,
                font=ctk.CTkFont(
                    size=15
                )
            )

            empty.pack(
                pady=50
            )

        else:
            for channel in filtered:
                self.create_channel_row(
                    channel
                )

        self.update_statistics(
            channels
        )

    # ========================================================
    # СТАТИСТИКА
    # ========================================================

    def update_statistics(
        self,
        channels
    ):
        total = len(channels)

        active = sum(
            1
            for channel in channels
            if channel[3] == 1
        )

        disabled = total - active

        self.total_card.value_label.configure(
            text=str(total)
        )

        self.active_card.value_label.configure(
            text=str(active)
        )

        self.disabled_card.value_label.configure(
            text=str(disabled)
        )

        if self.last_collection_time:
            value = self.last_collection_time.strftime(
                "%d.%m %H:%M"
            )

        else:
            value = "—"

        self.last_card.value_label.configure(
            text=value
        )

    # ========================================================
    # СТРОКА ИСТОЧНИКА
    # ========================================================

    def create_channel_row(self, channel):
        channel_id, name, username, enabled, _, last_date = channel
        row = ctk.CTkFrame(self.channels_frame, fg_color=BUTTON_DARK, corner_radius=12,
                          height=90, border_width=1, border_color=BORDER)
        row.pack(fill="x", pady=5, padx=3)
        row.grid_propagate(False)
        row.grid_rowconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=3)
        row.grid_columnconfigure(2, weight=2)
        avatar = ctk.CTkLabel(row, text=get_initials(name), width=46, height=46,
            corner_radius=23, fg_color="#174b76" if enabled else "#26394a",
            text_color=TEXT, font=ctk.CTkFont(size=14, weight="bold"))
        avatar.grid(row=0, column=0, padx=(16, 14))
        info = ctk.CTkFrame(row, fg_color="transparent", width=180, height=54)
        info.pack_propagate(False)
        info.grid(row=0, column=1, padx=(0, 12), sticky="ew")
        title = ctk.CTkLabel(info, text=name, height=25, anchor="w",
            text_color=TEXT if enabled else TEXT_SECONDARY, font=ctk.CTkFont(size=15, weight="bold"))
        title.pack(anchor="w", fill="x")
        handle = ctk.CTkLabel(info, text=f"@{username}", height=22, anchor="w",
            text_color=TEXT_SECONDARY, font=ctk.CTkFont(size=12))
        handle.pack(anchor="w", fill="x", pady=(3, 0))
        # Ellipsis keeps long names from pushing the date and controls out of view.
        def fit_text(event):
            for label, full in ((title, name), (handle, f"@{username}")):
                shown = full
                font = label.cget('font')
                while shown and font.measure(shown + ('…' if shown != full else '')) > event.width - 4:
                    shown = shown[:-1]
                label.configure(text=shown + ('…' if shown != full else ''))
        info.bind('<Configure>', fit_text)
        date = ctk.CTkFrame(row, fg_color="transparent")
        date.grid(row=0, column=2, padx=(10, 16), sticky="w")
        ctk.CTkLabel(date, text="Последнее сообщение · МСК", height=22,
            text_color=TEXT_SECONDARY, font=ctk.CTkFont(size=11)).pack(anchor="w")
        ctk.CTkLabel(date, text=format_date(last_date), height=24,
            text_color=TEXT, font=ctk.CTkFont(size=12)).pack(anchor="w")
        state = ctk.CTkFrame(row, fg_color="transparent", width=90, height=52)
        state.pack_propagate(False)
        state.grid(row=0, column=3, padx=(0, 16))
        switch = ctk.CTkSwitch(state, text="", width=44, progress_color=BLUE,
            fg_color="#36526d", button_color="#e5f2ff", button_hover_color="#ffffff")
        switch.pack(anchor="center")
        if enabled:
            switch.select()
        switch.configure(command=lambda: self.toggle_channel(channel_id, switch))
        status_label = ctk.CTkLabel(state, text="Активен" if enabled else "Отключён", height=22,
            font=ctk.CTkFont(size=11), text_color=GREEN if enabled else TEXT_SECONDARY)
        status_label.pack(pady=(3, 0))
        self._channel_rows[channel_id] = {'status': status_label, 'title': title,
                                         'avatar': avatar, 'username': username}
        self._request_avatar(channel_id, username)
        ctk.CTkButton(row, text="", image=ui_icon('trash', 23, '#aac5e3'),
            width=38, height=38, corner_radius=9, fg_color="#15304a",
            hover_color="#573044", border_width=1, border_color=BORDER,
            command=lambda: self.remove_channel(channel_id, name)).grid(row=0, column=4, padx=(0, 14))

    # ========================================================
    # TOGGLE
    # ========================================================

    def _request_avatar(self, channel_id, username):
        if username in self._avatar_cache:
            self._apply_avatar(channel_id, username)
        elif username not in self._avatar_tasks and hasattr(client, 'download_profile_photo'):
            self._avatar_tasks[username] = client.loop.create_task(self._load_avatar(channel_id, username))

    def _apply_avatar(self, channel_id, username):
        widgets = self._channel_rows.get(channel_id)
        image = self._avatar_cache.get(username)
        if widgets and widgets['username'] == username and image is not None:
            widgets['avatar'].configure(text='', image=image, fg_color='transparent')

    async def _load_avatar(self, channel_id, username):
        from io import BytesIO
        from PIL import Image, ImageOps, ImageDraw
        def decode(raw):
            with Image.open(BytesIO(raw)) as source:
                picture = ImageOps.fit(source.convert('RGBA'), (138, 138))
            mask = Image.new('L', picture.size)
            ImageDraw.Draw(mask).ellipse((0, 0, 137, 137), fill=255)
            picture.putalpha(mask)
            return picture
        try:
            async with self._avatar_slots:
                raw = await asyncio.wait_for(client.download_profile_photo(username, file=bytes), timeout=20)
                picture = await asyncio.to_thread(decode, raw) if raw else None
            self._avatar_cache[username] = ctk.CTkImage(picture, picture, size=(46, 46)) if picture is not None else None
            self._apply_avatar(channel_id, username)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A missing or inaccessible photo must not prevent source collection.
            self._avatar_cache[username] = None
        finally:
            self._avatar_tasks.pop(username, None)

    def toggle_channel(
        self,
        channel_id,
        switch
    ):
        enabled = switch.get()

        set_channel_enabled(
            channel_id,
            enabled
        )

        self.sources_status_label.configure(
            text="● Настройки сохранены"
        )

        widgets = self._channel_rows.get(channel_id)
        if widgets:
            widgets['status'].configure(text="Активен" if enabled else "Отключён",
                                        text_color=GREEN if enabled else TEXT_SECONDARY)
            widgets['title'].configure(text_color=TEXT if enabled else TEXT_SECONDARY)
        channels = get_all_channels()
        self.update_statistics(channels)

    # ========================================================
    # УДАЛЕНИЕ
    # ========================================================

    def remove_channel(
        self,
        channel_id,
        name
    ):
        result = messagebox.askyesno(
            "Удаление источника",
            f"Удалить «{name}»?"
        )

        if not result:
            return

        delete_channel(
            channel_id
        )

        self.refresh_channels()

        self.sources_status_label.configure(
            text="● Источник удалён"
        )

    # ========================================================
    # ДОБАВЛЕНИЕ
    # ========================================================

    def open_add_window(self):
        window = Toplevel(
            self
        )

        window.title(
            "Добавить источник"
        )

        window.geometry(
            "500x310"
        )

        window.resizable(
            False,
            False
        )

        window.configure(bg=BG)

        window.transient(
            self
        )

        window.grab_set()

        title = ctk.CTkLabel(
            window,
            text="Добавить источник",
            text_color=TEXT,
            font=ctk.CTkFont(
                size=24,
                weight="bold"
            )
        )

        title.pack(
            pady=(35, 7)
        )

        subtitle = ctk.CTkLabel(
            window,
            text=(
                "Введите username Telegram-канала,\n"
                "группы или ссылку t.me"
            ),
            text_color=TEXT_SECONDARY
        )

        subtitle.pack()

        entry = ctk.CTkEntry(
            window,
            width=390,
            height=48,
            corner_radius=12,
            placeholder_text="@rian_ru"
        )
        enable_paste(entry)

        entry.pack(
            pady=25
        )

        button = ctk.CTkButton(
            window,
            text="Добавить источник",
            width=200,
            height=45,
            corner_radius=12,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            command=lambda: self.add_new_channel(
                entry.get(),
                window
            )
        )

        button.pack()
        window._add_button = button
        window.bind('<Destroy>', lambda event: self._cancel_add_source(window)
                    if event.widget is window else None, add='+')

    def _cancel_add_source(self, window):
        task = getattr(window, '_add_task', None)
        if task is not None and not task.done() and task is not asyncio.current_task(client.loop):
            task.cancel()

    def add_new_channel(
        self,
        value,
        window
    ):
        task = getattr(self, '_add_source_task', None)
        if task is not None and not task.done():
            return

        async def run():
            window._add_button.configure(state='disabled', text='Проверяю…')
            try:
                await self._add_new_channel(value, window)
            except asyncio.CancelledError:
                raise
            except Exception:
                if window.winfo_exists():
                    messagebox.showerror('Добавление источника', 'Не удалось сохранить источник. Повторите попытку.', parent=window)
            finally:
                if window.winfo_exists():
                    window._add_button.configure(state='normal', text='Добавить источник')

        self._add_source_task = window._add_task = client.loop.create_task(run())

    async def _add_new_channel(self, value, window):
        username = normalize_username(
            value
        )

        if not username:
            messagebox.showwarning(
                "Ошибка",
                "Введите username или ссылку"
            )

            return

        self.sources_status_label.configure(
            text="● Проверяю Telegram..."
        )

        self.update_idletasks()

        try:
            entity = await client.get_entity(
                username
            )

        except Exception as error:
            messagebox.showerror(
                "Ошибка Telegram",
                (
                    "Не удалось получить источник:\n\n"
                    f"{error}"
                )
            )

            self.sources_status_label.configure(
                text="● Ошибка подключения"
            )

            return

        name = getattr(
            entity,
            "title",
            username
        )

        result = add_channel(
            name,
            username
        )

        if not result:
            messagebox.showinfo(
                "Источник существует",
                "Этот источник уже добавлен"
            )

            return

        window.destroy()

        self.refresh_channels()

        self.sources_status_label.configure(
            text=f"● Добавлен: {name}"
        )

    # ========================================================
    # СБОР
    # ========================================================

    def collect_messages(self, automatic=False):
        if getattr(self, "_collecting", False):
            return
        self._collecting = True
        self._automatic_collection = automatic
        self._send_this_collection = True
        self.collection_banner.configure(fg_color="#163455", border_width=1)
        self.collect_button.configure(state="disabled", text="Сбор выполняется…")
        self.collection_progress.grid()
        self.collection_progress.set(0)
        self.sources_status_label.configure(text="Получаю сообщения из Telegram…")
        self._collection_task = client.loop.create_task(self._collect_messages())
        self._collection_task.add_done_callback(self._collection_finished)

    def _collection_finished(self, task):
        self._collecting = False
        if task.cancelled():
            return
        self.collection_banner.configure(fg_color="transparent", border_width=0)
        self.collection_progress.grid_remove()
        self.collect_button.configure(state="normal", text="▷  Собрать сообщения")
        if task.exception() is not None:
            self.sources_status_label.configure(text="Сбор прерван из-за ошибки")
            if not self._automatic_collection:
                messagebox.showerror("Ошибка сбора", str(task.exception()))

    async def _collect_messages(self):
        summary_detail = self.schedule.summary_detail
        delivery_target = self.schedule.delivery_target
        recipient_id = (await client.get_me()).id
        channels = get_channels()

        if not channels:
            self.sources_status_label.configure(text="Нет активных источников")
            if getattr(self, "_send_this_collection", False):
                await self._deliver_pending()
            if not getattr(self, "_automatic_collection", False):
                messagebox.showinfo("Нет источников", "Добавьте хотя бы один активный источник.")
            return

        summaries = []
        errors = []

        processed_sources = 0
        total_messages = 0

        first_run_limit = self.get_first_run_limit()

        # Показываем статус внизу страницы
        self.sources_status_label.configure(
            text="● Собираю сообщения..."
        )



        for source_index, channel in enumerate(channels, 1):
            channel_id = channel[0]
            name = channel[1]
            username = channel[2]
            last_message_id = channel[4]
            self.sources_status_label.configure(
                text=f"Источник {source_index} из {len(channels)} · {name} · Получаю сообщения…"
            )
            self.collection_progress.set((source_index - 1) / len(channels))

            try:
                print()
                print("=" * 70)
                print(f"Источник: {name}")
                print(f"Последний обработанный ID: {last_message_id}")

                # Первый запуск
                if last_message_id == 0:
                    messages = await client.get_messages(
                        username,
                        limit=first_run_limit
                    )

                # Последующие запуски
                else:
                    messages = await client.get_messages(
                        username,
                        limit=None,
                        min_id=last_message_id
                    )

                if not messages:
                    print("Новых сообщений нет.")
                    continue

                # Самое новое полученное сообщение
                newest_fetched = max(messages, key=lambda message: message.id)

                # Оставляем только сообщения с текстом
                text_messages = [
                    message
                    for message in messages
                    if message.text and message.text.strip()
                ]

                # Если были только фото/видео без текста
                if not text_messages:
                    print("Новых текстовых сообщений нет.")

                    update_last_message(
                        channel_id,
                        newest_fetched.id,
                        str(newest_fetched.date)
                    )

                    continue

                # Telethon отдаёт сначала новые сообщения.
                # Переворачиваем: старые -> новые.
                text_messages.sort(key=lambda message: message.id)

                messages_text = prepare_messages_text(
                    name,
                    text_messages
                )

                print(
                    f"Отправляем в ГосПромт: "
                    f"{len(text_messages)} сообщений"
                )

                # Отправляем реальный текст в ГосПромт
                self.sources_status_label.configure(
                    text=f"Источник {source_index} из {len(channels)} · {name} · Формирую сводку…"
                )
                summary = await asyncio.to_thread(summarize_text, messages_text, detail=summary_detail)

                # Только после успешного summary обновляем last_message_id
                save_collected_summary(
                    channel_id,
                    newest_fetched.id,
                    str(newest_fetched.date),
                    delivery_text=(
                        f"Сводка · {datetime.now():%d.%m.%Y %H:%M}\n{name}\n\n{summary}"
                        if getattr(self, "_send_this_collection", False) else None
                    ), target=delivery_target, recipient_id=recipient_id
                )

                summaries.append(f"{name}\n\n{summary}")
                processed_sources += 1
                total_messages += len(text_messages)

                print(
                    f"Успешно. Новый last_message_id: "
                    f"{newest_fetched.id}"
                )

            except Exception as error:
                print(
                    f"Ошибка при обработке {name}: {error}"
                )

                errors.append(
                    f"{name}: {error}"
                )

                # last_message_id здесь НЕ обновляем

        # ========================================================
        # РЕЗУЛЬТАТ
        # ========================================================

        if summaries:
            result = "\n\n".join(summaries)
        else:
            result = "Новых обработанных сообщений нет."

        if errors:
            result += "\n\nОшибки:\n"

            for error in errors:
                result += f"\n• {error}"

        # Сохраняем последнюю сводку
        self.latest_summary = result

        # Выводим в поле Сводка
        self.summary_box.configure(
            state="normal"
        )

        self.summary_box.delete(
            "1.0",
            "end"
        )

        self.summary_box.insert(
            "1.0",
            result
        )

        self.summary_box.configure(
            state="disabled"
        )

        # ========================================================
        # СТАТИСТИКА
        # ========================================================

        now = datetime.now()

        self.summary_date.configure(
            text=now.strftime("%d.%m.%Y %H:%M")
        )

        self.summary_sources.configure(
            text=str(processed_sources)
        )

        self.summary_messages.configure(
            text=str(total_messages)
        )

        self.last_collection_time = now

        # Обновляем список источников
        self.refresh_channels()

        # Возвращаем нормальный статус
        self.sources_status_label.configure(
            text="Сбор завершён с ошибками · Результат во вкладке «Сводка»" if errors else "Сбор завершён · Результат во вкладке «Сводка»"
        )


        self.collection_progress.set(1)

        if getattr(self, "_send_this_collection", False):
            await self._deliver_pending()

    async def _deliver_pending(self):
        pending = get_pending_delivery()
        if not pending:
            return
        try:
            saved_messages = await client.get_input_entity('me')
            account_id = (await client.get_me()).id
            bot_checked = False
            for delivery_id, body, random_id, target, recipient_id in pending:
                if recipient_id is not None and recipient_id != account_id:
                    raise BotDeliveryError('В очереди есть сводки другого аккаунта. Войдите под исходным аккаунтом для их отправки.')
                self.sources_status_label.configure(text="Отправляю сводку через бота…" if target == 'bot' else "Отправляю сводку в Избранное…")
                if target == 'bot':
                    if not bot_checked:
                        await check_bot()
                        bot_checked = True
                    await send_bot_message(recipient_id, body)
                else:
                    await client(SendMessageRequest(
                        peer=saved_messages, message=body, random_id=random_id, no_webpage=True))
                mark_delivered(delivery_id)
        except Exception as error:
            self.sources_status_label.configure(text="Отправка отложена · Сводка сохранена в очереди")
            self.delivery_hint.configure(text=(str(error) if isinstance(error, BotDeliveryError) else "Не удалось отправить. Повтор — при следующем сборе."))
        else:
            self.sources_status_label.configure(text="Сбор завершён · Сводки отправлены")
            self.delivery_hint.configure(text="Последняя отправка: " + datetime.now().strftime("%d.%m.%Y %H:%M"))


    # ========================================================
    # СВОДКА
    # ========================================================

    def create_summary_page(self):
        page = self.summary_page

        page.grid_columnconfigure(
            0,
            weight=1
        )

        page.grid_rowconfigure(
            3,
            weight=1
        )

        title = ctk.CTkLabel(
            page,
            text="Сводка",
            text_color=TEXT,
            font=ctk.CTkFont(
                size=34,
                weight="bold"
            )
        )

        title.grid(
            row=0,
            column=0,
            padx=40,
            pady=(35, 0),
            sticky="w"
        )

        subtitle = ctk.CTkLabel(
            page,
            text=(
                "Результат последнего анализа "
                "Telegram-источников"
            ),
            text_color=TEXT_SECONDARY,
            font=ctk.CTkFont(
                size=14
            )
        )

        subtitle.grid(
            row=1,
            column=0,
            padx=40,
            pady=(5, 20),
            sticky="w"
        )

        # ----------------------------------------------------
        # INFO
        # ----------------------------------------------------

        stats = ctk.CTkFrame(
            page,
            fg_color="transparent"
        )

        stats.grid(
            row=2,
            column=0,
            padx=40,
            sticky="ew"
        )

        for i in range(3):
            stats.grid_columnconfigure(
                i,
                weight=1
            )

        self.summary_date = self.create_summary_info(
            stats,
            0,
            "Дата создания",
            "—"
        )

        self.summary_sources = self.create_summary_info(
            stats,
            1,
            "Источников",
            "0"
        )

        self.summary_messages = self.create_summary_info(
            stats,
            2,
            "Сообщений",
            "0"
        )

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        result_card = ctk.CTkFrame(
            page,
            fg_color=CARD,
            corner_radius=16,
            border_width=1,
            border_color=BORDER
        )

        result_card.grid(
            row=3,
            column=0,
            padx=40,
            pady=25,
            sticky="nsew"
        )

        result_card.grid_columnconfigure(
            0,
            weight=1
        )

        result_card.grid_rowconfigure(
            1,
            weight=1
        )

        result_header = ctk.CTkLabel(
            result_card,
            text="Результат анализа",
            text_color=TEXT,
            font=ctk.CTkFont(
                size=18,
                weight="bold"
            )
        )

        result_header.grid(
            row=0,
            column=0,
            padx=25,
            pady=(20, 10),
            sticky="w"
        )

        self.summary_box = ctk.CTkTextbox(
            result_card,
            fg_color="#101b28",
            border_width=0,
            corner_radius=12,
            text_color=TEXT,
            font=ctk.CTkFont(
                size=14
            ),
            wrap="word"
        )

        self.summary_box.grid(
            row=1,
            column=0,
            padx=20,
            pady=(0, 20),
            sticky="nsew"
        )

        self.summary_box.insert(
            "1.0",
            "Сводка ещё не сформирована."
        )

        self.summary_box.configure(
            state="disabled"
        )

        buttons = ctk.CTkFrame(
            page,
            fg_color="transparent"
        )

        buttons.grid(
            row=4,
            column=0,
            padx=40,
            pady=(0, 30),
            sticky="w"
        )

        copy_button = ctk.CTkButton(
            buttons,
            text="Копировать",
            width=150,
            height=44,
            corner_radius=11,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            command=self.copy_summary
        )

        copy_button.pack(
            side="left"
        )

        send_button = ctk.CTkButton(
            buttons,
            text="Отправить",
            width=150,
            height=44,
            corner_radius=11,
            fg_color=BUTTON_DARK,
            border_width=1,
            border_color=BORDER,
            state="disabled"
        )

        send_button.pack(
            side="left",
            padx=10
        )

    def create_summary_info(self, parent, column, title, value):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14,
                           border_width=1, border_color=BORDER, height=90)
        card.grid(row=0, column=column, padx=6, sticky="ew")
        card.grid_propagate(False)
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(0, weight=1)
        info = ctk.CTkFrame(card, fg_color="transparent")
        info.grid(row=0, column=0, padx=20, pady=16, sticky="w")
        ctk.CTkLabel(info, text=title, height=20, text_color=TEXT_SECONDARY,
                     font=ctk.CTkFont(size=12)).pack(anchor="w")
        value_label = ctk.CTkLabel(info, text=value, height=26, text_color=TEXT,
                                   font=ctk.CTkFont(size=17, weight="bold"))
        value_label.pack(anchor="w", pady=(3, 0))
        return value_label

    # ========================================================
    # COPY
    # ========================================================

    def copy_summary(self):
        if not self.latest_summary:
            return

        self.clipboard_clear()

        self.clipboard_append(
            self.latest_summary
        )

        self.sources_status_label.configure(
            text="● Сводка скопирована"
        )

    # ========================================================
    # НАСТРОЙКИ
    # ========================================================

    def create_settings_page(self):
        page = self.settings_page
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(page, text="Настройки", text_color=TEXT,
            font=ctk.CTkFont(size=34, weight="bold")).grid(
                row=0, column=0, padx=40, pady=(35, 20), sticky="w")
        content = ctk.CTkScrollableFrame(page, fg_color="transparent")
        content.grid(row=1, column=0, padx=30, pady=(0, 5), sticky="nsew")
        content.grid_columnconfigure(0, weight=1)

        def section(row, title, description):
            frame = ctk.CTkFrame(content, fg_color=CARD, corner_radius=16,
                                 border_width=1, border_color=BORDER)
            frame.grid(row=row, column=0, padx=8, pady=(0, 16), sticky="ew")
            frame.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(frame, text=title, text_color=TEXT,
                image=ui_icon({'Автоматический сбор': 'clock', 'Доставка сводок': 'users',
                               'Подробность сводки': 'document'}.get(title, 'settings'), 26),
                compound="left", padx=8,
                font=ctk.CTkFont(size=18, weight="bold")).grid(
                    row=0, column=0, padx=24, pady=(20, 2), sticky="w")
            ctk.CTkLabel(frame, text=description, text_color=TEXT_SECONDARY,
                anchor="w", justify="left").grid(
                    row=1, column=0, columnspan=2, padx=24, pady=(0, 18), sticky="w")
            return frame

        automatic = section(0, "Автоматический сбор", "Новые сводки по вашему расписанию")
        self.schedule_switch = ctk.CTkSwitch(automatic, text="", width=46, progress_color=BLUE,
                                            command=self._update_schedule_fields)
        self.schedule_switch.grid(row=0, column=1, padx=24, pady=(20, 2), sticky="e")
        if self.schedule.enabled:
            self.schedule_switch.select()
        self.schedule_options = ctk.CTkFrame(automatic, fg_color="transparent")
        self.schedule_options.grid(row=2, column=0, columnspan=2, padx=24, pady=(0, 16), sticky="ew")
        self.schedule_options.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.schedule_options, text="Расписание", text_color=TEXT).grid(row=0, column=0, sticky="w")
        self.schedule_mode_border = ctk.CTkFrame(self.schedule_options, corner_radius=12,
            fg_color="transparent", border_width=0)
        self.schedule_mode = Select(self.schedule_mode_border,
            values=["Через равные интервалы", "Ежедневно"], width=250, height=42, corner_radius=10,
            fg_color=BUTTON_DARK, button_color="#254663", button_hover_color="#315a7f",
            dropdown_fg_color=CARD, dropdown_hover_color=BUTTON_DARK_HOVER,
            text_color=TEXT, font=ctk.CTkFont(size=14), dropdown_font=ctk.CTkFont(size=14),
            command=self._update_schedule_fields)
        self.schedule_mode.set("Ежедневно" if self.schedule.mode == "daily" else "Через равные интервалы")
        self.schedule_mode.pack()
        self.schedule_mode_border.grid(row=0, column=1, sticky="e")
        self.interval_row = ctk.CTkFrame(self.schedule_options, fg_color="transparent")
        self.interval_row.grid(row=1, column=0, columnspan=2, pady=(14, 0), sticky="ew")
        self.interval_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.interval_row, text="Повторять каждые", text_color=TEXT).grid(row=0, column=0, sticky="w")
        self.interval_entry = ctk.CTkEntry(self.interval_row, width=90, height=38, corner_radius=8, border_width=1, border_color="#36546e", fg_color=BUTTON_DARK, text_color=TEXT)
        self.interval_entry.insert(0, str(self.schedule.minutes))
        self.interval_entry.grid(row=0, column=1, padx=(0, 10))
        ctk.CTkLabel(self.interval_row, text="минут", text_color=TEXT_SECONDARY).grid(row=0, column=2)
        self.daily_row = ctk.CTkFrame(self.schedule_options, fg_color="transparent")
        self.daily_row.grid(row=2, column=0, columnspan=2, pady=(14, 0), sticky="ew")
        self.daily_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.daily_row, text="Время сбора", text_color=TEXT).grid(row=0, column=0, sticky="w")
        self.daily_entry = ctk.CTkEntry(self.daily_row, width=120, height=38, placeholder_text="09:00", corner_radius=8, border_width=1, border_color="#36546e", fg_color=BUTTON_DARK, text_color=TEXT)
        self.daily_entry.insert(0, self.schedule.daily_time)
        self.daily_entry.grid(row=0, column=1)
        self.schedule_hint = ctk.CTkLabel(automatic, text="", text_color=TEXT_SECONDARY, anchor="w")
        self.schedule_hint.grid(row=3, column=0, columnspan=2, padx=24, pady=(0, 18), sticky="ew")

        delivery = section(1, "Доставка сводок", "После ручного и автоматического сбора")
        ctk.CTkLabel(delivery, text="Получатель", text_color=TEXT).grid(row=2, column=0, padx=24, pady=(0, 20), sticky="w")
        self.delivery_menu_border = ctk.CTkFrame(delivery, corner_radius=12,
            fg_color="transparent", border_width=0)
        self.delivery_menu = Select(self.delivery_menu_border, values=["Избранное в Telegram", "Telegram-бот"], command=self._update_delivery_fields, width=250, height=42, corner_radius=10,
            fg_color=BUTTON_DARK, button_color="#254663", button_hover_color="#315a7f",
            dropdown_fg_color=CARD, dropdown_hover_color=BUTTON_DARK_HOVER,
            text_color=TEXT, font=ctk.CTkFont(size=14), dropdown_font=ctk.CTkFont(size=14))
        self.delivery_menu.pack()
        self.delivery_menu.set("Telegram-бот" if self.schedule.delivery_target == 'bot' else "Избранное в Telegram")
        self.delivery_menu_border.grid(row=2, column=1, padx=24, pady=(0, 20), sticky="e")
        self.bot_options = ctk.CTkFrame(delivery, fg_color='transparent')
        self.bot_options.grid(row=3, column=0, columnspan=2, padx=24, pady=(0, 16), sticky='ew')
        ctk.CTkLabel(self.bot_options, text='Откройте @summaryAgent_bot и нажмите «Запустить» под тем же аккаунтом Telegram.',
                     wraplength=650, justify='left', text_color=TEXT_SECONDARY).pack(anchor='w', pady=(0, 10))
        buttons = ctk.CTkFrame(self.bot_options, fg_color='transparent')
        buttons.pack(anchor='w')
        ctk.CTkButton(buttons, text='Открыть бота', height=40, command=self._open_bot).pack(side='left', padx=(0, 10))
        self.bot_check_button = ctk.CTkButton(buttons, text='Проверить подключение', height=40, command=self._check_bot_connection)
        self.bot_check_button.pack(side='left')
        self.delivery_hint = ctk.CTkLabel(delivery, text="",
                                         text_color=TEXT_SECONDARY, anchor="w", justify='left', wraplength=650)
        self.delivery_hint.grid(row=4, column=0, columnspan=2, padx=24, pady=(0, 18), sticky="ew")
        self._update_delivery_fields()

        summary_options = section(2, "Подробность сводки", "Для ручного и автоматического сбора")
        self.summary_detail_border = ctk.CTkFrame(summary_options, corner_radius=12,
            fg_color="transparent", border_width=0)
        self.summary_detail_menu = Select(self.summary_detail_border,
            values=[item[0] for item in SUMMARY_MODES.values()], width=250, height=42, corner_radius=10,
            fg_color=BUTTON_DARK, button_color="#254663", button_hover_color="#315a7f",
            dropdown_fg_color=CARD, dropdown_hover_color=BUTTON_DARK_HOVER,
            text_color=TEXT, font=ctk.CTkFont(size=14), dropdown_font=ctk.CTkFont(size=14),
            command=self._update_summary_detail_hint)
        self.summary_detail_menu.set(SUMMARY_MODES[self.schedule.summary_detail][0])
        self.summary_detail_menu.pack()
        self.summary_detail_border.grid(row=2, column=0, padx=24, pady=(0, 12), sticky="w")
        self.summary_detail_hint = ctk.CTkLabel(summary_options, text="", text_color=TEXT_SECONDARY,
                                               anchor="w", justify="left", wraplength=650)
        self.summary_detail_hint.grid(row=3, column=0, columnspan=2, padx=24, pady=(0, 20), sticky="w")
        self._update_summary_detail_hint()

        other = section(3, "Работа приложения", "Закрытие окна скрывает приложение в трей рядом с часами Windows.")
        import autostart
        self.autostart_switch = ctk.CTkSwitch(other, text="Запускать вместе с Windows",
            progress_color=BLUE, command=self._toggle_autostart)
        self.autostart_switch.grid(row=4, column=0, columnspan=2, padx=24, pady=(0, 10), sticky="w")
        self.autostart_hint = ctk.CTkLabel(other,
            text="Запуск в трее после входа в Windows. Применяется сразу.",
            text_color=TEXT_SECONDARY, anchor="w")
        self.autostart_hint.grid(row=5, column=0, columnspan=2, padx=24, pady=(0, 20), sticky="w")
        try:
            if autostart.is_enabled():
                self.autostart_switch.select()
        except OSError:
            self.autostart_hint.configure(text="Не удалось проверить автозагрузку Windows.")
        ctk.CTkLabel(other, text="Постов при первом сборе источника", text_color=TEXT).grid(
            row=2, column=0, padx=24, pady=(0, 18), sticky="w")
        self.limit_entry = ctk.CTkEntry(other, width=120, height=38, corner_radius=8, border_width=1, border_color="#36546e", fg_color=BUTTON_DARK, text_color=TEXT)
        self.limit_entry.insert(0, str(self.schedule.first_run_limit))
        for field in (self.limit_entry, self.interval_entry, self.daily_entry):
            enable_paste(field)
        self.limit_entry.grid(row=2, column=1, padx=24, pady=(0, 18), sticky="e")
        ctk.CTkLabel(other, text="Сбор продолжается в фоне. Полный выход — через меню значка в трее.\n"
                     "Время — по часам компьютера. Во время сна или выключения сбор не выполняется.",
                     justify="left", anchor="w", text_color=TEXT_SECONDARY).grid(
                         row=3, column=0, columnspan=2, padx=24, pady=(0, 20), sticky="w")
        ctk.CTkButton(page, text="Сохранить настройки", height=46, width=240, corner_radius=11,
            fg_color=BLUE, hover_color=BLUE_HOVER, font=ctk.CTkFont(size=14, weight="bold"),
            command=self.save_schedule).grid(row=2, column=0, padx=40, pady=(0, 25), sticky="e")
        self._update_schedule_fields()
        self._update_schedule_hint()

    def _toggle_autostart(self):
        import autostart
        enabled = bool(self.autostart_switch.get())
        try:
            autostart.set_enabled(enabled)
        except OSError:
            if enabled:
                self.autostart_switch.deselect()
            else:
                self.autostart_switch.select()
            messagebox.showerror("Автозагрузка", "Не удалось изменить автозагрузку Windows. Повторите попытку.")
            return
        self.autostart_hint.configure(text=(
            "Приложение запустится в трее после входа в Windows." if enabled
            else "Автозагрузка отключена."))

    def _update_delivery_fields(self, _value=None):
        if self.delivery_menu.get() == 'Telegram-бот':
            self.bot_options.grid()
        else:
            self.bot_options.grid_remove()

    def _open_bot(self):
        import webbrowser
        webbrowser.open(BOT_URL)

    def _check_bot_connection(self):
        if getattr(self, '_bot_check_task', None) and not self._bot_check_task.done():
            return
        self.bot_check_button.configure(state='disabled', text='Проверяю…')
        self._bot_check_task = client.loop.create_task(self._test_bot_delivery())

    async def _test_bot_delivery(self):
        try:
            await check_bot()
            me = await client.get_me()
            await send_bot_message(me.id, 'Summary Agent подключён. Сводки будут приходить в этот чат после выбора Telegram-бота и сохранения настроек в приложении.')
            self.delivery_hint.configure(text='Подключено. Тестовое сообщение отправлено. Сохраните настройки, чтобы применить выбор.')
        except Exception as error:
            self.delivery_hint.configure(text=str(error) if isinstance(error, BotDeliveryError) else 'Не удалось проверить подключение. Повторите попытку.')
        finally:
            if self.winfo_exists():
                self.bot_check_button.configure(state='normal', text='Проверить подключение')

    def _update_summary_detail_hint(self, _value=None):
        label = self.summary_detail_menu.get()
        description = next(item[1] for item in SUMMARY_MODES.values() if item[0] == label)
        self.summary_detail_hint.configure(text=description)

    def _update_schedule_fields(self, _value=None):
        if self.schedule_switch.get():
            self.schedule_options.grid()
        else:
            self.schedule_options.grid_remove()
        daily = self.schedule_mode.get() == "Ежедневно"
        if daily:
            self.interval_row.grid_remove()
            self.daily_row.grid()
        else:
            self.daily_row.grid_remove()
            self.interval_row.grid()
        self._update_schedule_hint()

    def _update_schedule_hint(self):
        enabled = bool(self.schedule_switch.get())
        if enabled != self.schedule.enabled:
            text = "Сохраните настройки, чтобы включить автосбор." if enabled else "Сохраните настройки, чтобы выключить автосбор."
        elif self._schedule_error:
            text = self._schedule_error
        elif self.schedule.enabled and self.schedule.next_run is not None:
            text = "Следующий сбор: " + datetime.fromtimestamp(self.schedule.next_run).strftime("%d.%m.%Y %H:%M")
        else:
            text = "Автосбор выключен. Ручной сбор доступен в разделе «Источники»."
        self.schedule_hint.configure(text=text)

    def save_schedule(self):
        try:
            schedule = Schedule(
                enabled=bool(self.schedule_switch.get()),
                mode="daily" if self.schedule_mode.get() == "Ежедневно" else "interval",
                minutes=(int(self.interval_entry.get()) if self.schedule_switch.get() and self.schedule_mode.get() != "Ежедневно" else self.schedule.minutes),
                daily_time=(self.daily_entry.get().strip() if self.schedule_switch.get() and self.schedule_mode.get() == "Ежедневно" else self.schedule.daily_time),
                send_saved=True, first_run_limit=int(self.limit_entry.get()),
                delivery_target='bot' if self.delivery_menu.get() == 'Telegram-бот' else 'saved',
                summary_detail=next(key for key, item in SUMMARY_MODES.items()
                                    if item[0] == self.summary_detail_menu.get()))
            schedule.plan(time.time())
            schedule.save(self._schedule_path)
        except (ValueError, OSError) as error:
            messagebox.showerror("Настройки расписания", str(error))
            return
        self.schedule = schedule
        self._schedule_error = ""
        self._update_schedule_hint()

    def _check_schedule(self):
        try:
            now = time.time()
            if self.schedule.due(now) and not getattr(self, "_collecting", False):
                # Advance before launch: no repeated launches after sleep or slow requests.
                self.schedule.plan(now)
                try:
                    self.schedule.save(self._schedule_path)
                except OSError:
                    self.schedule.enabled = False
                    self.schedule_switch.deselect()
                    self._schedule_error = "Автосбор остановлен: не удалось сохранить расписание."
                else:
                    self.collect_messages(automatic=True)
                self._update_schedule_hint()
        finally:
            self.after(1000, self._check_schedule)

    def get_first_run_limit(self):
        try:
            value = int(
                self.limit_entry.get()
            )

            if value <= 0:
                return 10

            return value

        except ValueError:
            return 10

    def enable_tray(self):
        from tray import Tray
        self._tray = Tray()
        self._tray.start()
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.bind("<Unmap>", self._on_minimize)
        self._startup_hide_pending = '--autostart' in sys.argv
        self.after(100, self._poll_tray)

    def hide_to_tray(self):
        if self._tray.ready.is_set():
            self.withdraw()
        else:
            self.iconify()

    def _on_minimize(self, event):
        if event.widget is self and self.state() == "iconic" and self._tray.ready.is_set():
            self.withdraw()

    def _poll_tray(self):
        from queue import Empty
        if self._startup_hide_pending and self._tray.ready.is_set():
            self._startup_hide_pending = False
            self.withdraw()
        instance = getattr(self, "_instance", None)
        if instance is not None and instance.open_requested():
            self._tray.commands.put("open")
        try:
            while True:
                command = self._tray.commands.get_nowait()
                if command == "open":
                    self.deiconify()
                    self.lift()
                elif command == "collect":
                    self.collect_messages()
                elif command == "exit":
                    self.destroy()
                    return
        except Empty:
            pass
        self.after(100, self._poll_tray)


# ============================================================
# ЗАПУСК
# ============================================================

def start_app():
    from tray import SingleInstance
    instance = SingleInstance()
    if not instance.primary:
        if '--autostart' not in sys.argv:
            instance.request_open()
        instance.close()
        return
    try:
        app = App()
        app._instance = instance
        loop = client.loop

        def pump_network():
            # Tk and Telethon share the main thread; each network tick is nonblocking.
            if not getattr(app, '_tray', None) and instance.open_requested():
                app.deiconify()
                app.lift()
            loop.call_soon(loop.stop)
            loop.run_forever()
            app.after(20, pump_network)

        app.after(0, pump_network)
        app.mainloop()
    finally:
        add_task = getattr(locals().get("app"), '_add_source_task', None)
        if add_task is not None and not add_task.done():
            add_task.cancel()
            client.loop.run_until_complete(asyncio.gather(add_task, return_exceptions=True))
        avatar_tasks = list(getattr(locals().get("app"), "_avatar_tasks", {}).values())
        for avatar_task in avatar_tasks:
            avatar_task.cancel()
        if avatar_tasks:
            client.loop.run_until_complete(asyncio.gather(*avatar_tasks, return_exceptions=True))
        bot_task = getattr(locals().get("app"), "_bot_check_task", None)
        if bot_task is not None and not bot_task.done():
            bot_task.cancel()
            client.loop.run_until_complete(asyncio.gather(bot_task, return_exceptions=True))
        login = getattr(locals().get("app"), "_login", None)
        if login is not None:
            login.close()
            if login.task is not None:
                client.loop.run_until_complete(asyncio.gather(login.task, return_exceptions=True))
        tray = getattr(locals().get("app"), "_tray", None)
        if tray is not None:
            tray.stop()
        task = getattr(locals().get("app"), "_collection_task", None)
        if task is not None and not task.done():
            task.cancel()
            client.loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
        if client.is_connected():
            client.disconnect()
        instance.close()


if __name__ == "__main__":
    start_app()

