import sqlite3
import secrets
from app_paths import data_path

DB_NAME = str(data_path("summary_agent.db"))


def create_database():
    connection = sqlite3.connect(DB_NAME)

    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            enabled INTEGER DEFAULT 1,
            last_message_id INTEGER DEFAULT 0,
            last_message_date TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS delivery_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            body TEXT NOT NULL,
            random_id INTEGER NOT NULL UNIQUE
        )
    """)

    columns = {row[1] for row in cursor.execute('PRAGMA table_info(delivery_outbox)')}
    if 'target' not in columns:
        cursor.execute("ALTER TABLE delivery_outbox ADD COLUMN target TEXT NOT NULL DEFAULT 'saved'")
    if 'recipient_id' not in columns:
        cursor.execute('ALTER TABLE delivery_outbox ADD COLUMN recipient_id INTEGER')
    connection.commit()
    connection.close()


def add_channel(name, username):
    connection = sqlite3.connect(DB_NAME)

    cursor = connection.cursor()

    try:
        cursor.execute("""
            INSERT INTO channels (name, username)
            VALUES (?, ?)
        """, (name, username))

        connection.commit()

        return True

    except sqlite3.IntegrityError:
        return False

    finally:
        connection.close()


def get_channels():
    connection = sqlite3.connect(DB_NAME)

    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, name, username, enabled, last_message_id, last_message_date
        FROM channels
        WHERE enabled = 1
    """)

    channels = cursor.fetchall()

    connection.close()

    return channels


def get_all_channels():
    connection = sqlite3.connect(DB_NAME)

    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, name, username, enabled, last_message_id, last_message_date
        FROM channels
        ORDER BY id
    """)

    channels = cursor.fetchall()

    connection.close()

    return channels


def update_last_message(channel_id, message_id, message_date):
    connection = sqlite3.connect(DB_NAME)
    try:
        with connection:
            cursor = connection.execute("""
                UPDATE channels
                SET last_message_id = ?, last_message_date = ?
                WHERE id = ? AND COALESCE(last_message_id, 0) <= ?
            """, (message_id, message_date, channel_id, message_id))
            if cursor.rowcount != 1:
                raise RuntimeError("Источник удалён или уже обработан другим сбором")
    finally:
        connection.close()

def save_collected_summary(channel_id, message_id, message_date, delivery_text=None,
                           target='saved', recipient_id=None):
    """Commit the checkpoint and optional delivery queue in one transaction."""
    if target not in ('saved', 'bot') or (target == 'bot' and (type(recipient_id) is not int or recipient_id <= 0)):
        raise ValueError('Неверный получатель сводки')
    connection = sqlite3.connect(DB_NAME)
    try:
        with connection:
            cursor = connection.execute("""
                UPDATE channels SET last_message_id=?, last_message_date=?
                WHERE id=? AND COALESCE(last_message_id, 0) <= ?
            """, (message_id, message_date, channel_id, message_id))
            if cursor.rowcount != 1:
                raise RuntimeError("Источник удалён или уже обработан другим сбором")
            if delivery_text:
                # At most 3000 UTF-16 units even for emoji-only content.
                remaining = delivery_text
                while remaining:
                    end = min(1500, len(remaining))
                    if end < len(remaining):
                        boundary = remaining.rfind('\n', 0, end)
                        if boundary > end // 2:
                            end = boundary + 1
                    connection.execute(
                        'INSERT INTO delivery_outbox(body, random_id, target, recipient_id) VALUES (?, ?, ?, ?)',
                        (remaining[:end], secrets.randbits(63), target, recipient_id))
                    remaining = remaining[end:]
    finally:
        connection.close()


def get_pending_delivery():
    connection = sqlite3.connect(DB_NAME)
    try:
        return connection.execute('SELECT id, body, random_id, target, recipient_id FROM delivery_outbox ORDER BY id').fetchall()
    finally:
        connection.close()


def retarget_pending_delivery(account_id, target):
    """Apply the selected transport only to this account's unsent summaries."""
    if type(account_id) is not int or account_id <= 0 or target not in ('saved', 'bot'):
        raise ValueError('Неверный получатель сводки')
    connection = sqlite3.connect(DB_NAME)
    try:
        with connection:
            connection.execute(
                'UPDATE delivery_outbox SET target=? WHERE recipient_id=? AND target<>?',
                (target, account_id, target))
    finally:
        connection.close()


def mark_delivered(delivery_id):
    connection = sqlite3.connect(DB_NAME)
    try:
        with connection:
            connection.execute('DELETE FROM delivery_outbox WHERE id=?', (delivery_id,))
    finally:
        connection.close()


def delete_channel(channel_id):
    connection = sqlite3.connect(DB_NAME)

    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM channels
        WHERE id = ?
    """, (channel_id,))

    connection.commit()

    deleted = cursor.rowcount > 0

    connection.close()

    return deleted


def set_channel_enabled(channel_id, enabled):
    connection = sqlite3.connect(DB_NAME)

    cursor = connection.cursor()

    cursor.execute("""
        UPDATE channels
        SET enabled = ?
        WHERE id = ?
    """, (enabled, channel_id))

    connection.commit()

    changed = cursor.rowcount > 0

    connection.close()

    return changed
