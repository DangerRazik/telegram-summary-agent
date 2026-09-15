"""Package a PyInstaller build with a launch guide; never include personal data."""
import argparse
from pathlib import Path
import tempfile
import zipfile

from dotenv import dotenv_values, set_key


PROJECT = Path(__file__).resolve().parent
SHARED_KEYS = (
    'TELEGRAM_API_ID', 'TELEGRAM_API_HASH', 'GOSPROMPT_BASE_URL',
    'GOSPROMPT_API_KEY', 'GOSPROMPT_MODEL', 'TELEGRAM_BOT_TOKEN',
)
GUIDE = '''Распакуйте всю папку и запустите TelegramSummaryAgent.exe. Python не нужен.
Не отделяйте EXE от папки _internal.
Для работы нужен согласованный файл .env рядом с EXE. Если его нет в архиве, получите его у автора приложения.
Каждый пользователь входит в свой Telegram и добавляет свои источники.
Для доставки ботом откройте @summaryAgent_bot, нажмите «Запустить» и выберите Telegram-бот в настройках приложения.
Перед обновлением полностью выйдите из приложения через значок в трее.
В архив не включаются личные сессии, базы и настройки.
Если архив содержит .env, передавайте его только согласованным получателям: внутри находятся общие ключи доступа.
'''


def package(build_dir, include_env=False):
    build_dir = Path(build_dir).resolve()
    executable = build_dir / 'TelegramSummaryAgent.exe'
    internal = build_dir / '_internal'
    if not executable.is_file() or not internal.is_dir():
        raise ValueError('Сначала соберите EXE: нужны TelegramSummaryAgent.exe и папка _internal.')
    files = [executable] + sorted(p for p in internal.rglob('*') if p.is_file())
    for path in files:
        name = path.name.lower()
        if (path.is_symlink() or not path.resolve().is_relative_to(build_dir)
                or '.session' in name or name.startswith('.env')
                or path.suffix.lower() in ('.db', '.sqlite', '.sqlite3', '.bak', '.log')
                or name in ('schedule_settings.json', 'proxy_settings.json',
                            'proxy_settings.tmp', 'telegram_login_status.json')):
            raise ValueError('В сборке обнаружен посторонний файл. Пересоберите EXE в чистую папку.')
    config = None
    if include_env:
        source = PROJECT / '.env'
        if not source.is_file():
            raise ValueError('Файл .env не найден в папке проекта.')
        config = dotenv_values(source)
    guide = build_dir / 'Как запустить.txt'
    guide.write_text(GUIDE, encoding='utf-8')
    archive = build_dir.parent / 'TelegramSummaryAgent.zip'
    temporary = archive.with_suffix('.zip.tmp')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for path in files + [guide]:
                bundle.write(path, Path('TelegramSummaryAgent') / path.relative_to(build_dir))
            if config is not None:
                with tempfile.TemporaryDirectory() as folder:
                    env = Path(folder) / '.env'
                    env.touch()
                    for key in SHARED_KEYS:
                        if config.get(key):
                            set_key(str(env), key, config[key])
                    bundle.write(env, 'TelegramSummaryAgent/.env')
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, default=PROJECT / 'dist' / 'TelegramSummaryAgent')
    parser.add_argument('--include-env', action='store_true',
                        help='Include agreed shared API keys from the project .env (company distribution only).')
    args = parser.parse_args()
    try:
        archive = package(args.build_dir, args.include_env)
    except (ValueError, OSError) as error:
        parser.exit(1, f'{error}\n')
    print(f'Архив готов: {archive}')


if __name__ == '__main__':
    main()
