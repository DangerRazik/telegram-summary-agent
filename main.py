import os

from dotenv import load_dotenv
from telethon import TelegramClient
from summarizer import summarize_text
from credential_session import CredentialSession

from database import (
    create_database,
    add_channel,
    get_channels,
    get_all_channels,
    update_last_message,
    delete_channel,
    set_channel_enabled
)

load_dotenv()

api_id = os.getenv("TELEGRAM_API_ID")
api_hash = os.getenv("TELEGRAM_API_HASH")

if not api_id or not api_hash:
    print("Не указаны TELEGRAM_API_ID или TELEGRAM_API_HASH")
    raise SystemExit

session = CredentialSession()
client = TelegramClient(
    session,
    int(api_id),
    api_hash
)


def normalize_username(value):
    value = value.strip()

    if value.startswith("https://t.me/"):
        value = value.replace("https://t.me/", "")

    if value.startswith("@"):
        value = value[1:]

    return value


async def check_channel(username):
    try:
        entity = await client.get_entity(username)
        return entity

    except Exception as error:
        print("Не удалось открыть Telegram-источник:")
        print(error)
        return None


async def add_new_channel():
    value = input("Введите ссылку или username канала/группы: ")

    username = normalize_username(value)

    if not username:
        print("Вы ничего не ввели")
        return

    entity = await check_channel(username)

    if entity is None:
        print("Канал не добавлен")
        return

    name = getattr(entity, "title", username)

    added = add_channel(name, username)

    if added:
        print()
        print("Канал успешно добавлен")
        print("Название:", name)
        print("Username:", username)
    else:
        print()
        print("Такой канал уже есть в базе")


def show_channels():
    channels = get_all_channels()

    if not channels:
        print("Список каналов пуст")
        return

    print()
    print("Список каналов:")

    for channel in channels:
        channel_id = channel[0]
        name = channel[1]
        username = channel[2]
        enabled = channel[3]

        status = "включен" if enabled == 1 else "выключен"

        print(
            f"{channel_id}. {name} "
            f"(@{username}) — {status}"
        )


def remove_channel():
    show_channels()

    value = input("Введите ID канала для удаления: ")

    try:
        channel_id = int(value)
    except ValueError:
        print("Нужно ввести число")
        return

    deleted = delete_channel(channel_id)

    if deleted:
        print("Канал удален")
    else:
        print("Канал с таким ID не найден")


def toggle_channel():
    channels = get_all_channels()

    if not channels:
        print("Список каналов пуст")
        return

    show_channels()

    value = input("Введите ID канала: ")

    try:
        channel_id = int(value)
    except ValueError:
        print("Нужно ввести число")
        return

    selected_channel = None

    for channel in channels:
        if channel[0] == channel_id:
            selected_channel = channel
            break

    if selected_channel is None:
        print("Канал с таким ID не найден")
        return

    enabled = selected_channel[3]

    if enabled == 1:
        new_enabled = 0
    else:
        new_enabled = 1

    set_channel_enabled(channel_id, new_enabled)

    if new_enabled == 1:
        print("Канал включен")
    else:
        print("Канал выключен")


def prepare_messages_text(name, messages):
    parts = []

    parts.append(f"Канал: {name}")

    for message in messages:
        text = message.text.strip()

        part = (
            f"\nДата: {message.date}\n"
            f"{text}"
        )

        parts.append(part)

    return "\n".join(parts)


async def menu():
    while True:
        print()
        print("=" * 40)
        print("1 — Показать каналы")
        print("2 — Добавить канал")
        print("3 — Удалить канал")
        print("4 — Включить / выключить канал")
        print("5 — Запустить сбор сообщений")
        print("0 — Выход")

        choice = input("Выберите действие: ")

        if choice == "1":
            show_channels()

        elif choice == "2":
            await add_new_channel()

        elif choice == "3":
            remove_channel()

        elif choice == "4":
            toggle_channel()

        elif choice == "5":
            await collect_messages()

        elif choice == "0":
            print("Выход")
            break

        else:
            print("Неизвестная команда")


async def collect_messages():
    channels = get_channels()

    if not channels:
        print("Нет каналов для отслеживания")
        return

    for channel in channels:
        channel_id = channel[0]
        name = channel[1]
        username = channel[2]
        last_message_id = channel[4]

        print()
        print("=" * 60)
        print("Канал:", name)
        print("Последний обработанный ID:", last_message_id)

        if last_message_id == 0:
            print("Первый запуск — беру последние 100 сообщений")

            messages = await client.get_messages(
                username,
                limit=100
            )

        else:
            print("Получаю только новые сообщения")

            messages = await client.get_messages(
                username,
                min_id=last_message_id
            )

        new_messages = []

        for message in messages:
            if message.text:
                new_messages.append(message)

        if not new_messages:
            print("Новых сообщений нет")
            continue

        new_messages.reverse()

        messages_text = prepare_messages_text(
            name,
            new_messages
        )

        print()
        print("Текст для LLM:")
        print("=" * 60)
        print(messages_text)

        summary = summarize_text(messages_text)

        print()
        print("SUMMARY:")
        print("=" * 60)
        print(summary)

        newest_message = new_messages[-1]

        update_last_message(
            channel_id,
            newest_message.id,
            str(newest_message.date)
        )

        print(
            "Сохранили последний ID:",
            newest_message.id
        )


async def main():
    create_database()
    await menu()


with client:
    client.loop.run_until_complete(main())
