"""Per-user Windows startup, pointing to this installation."""
import subprocess
import sys
from pathlib import Path
import winreg

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'TelegramSummaryAgent'


def startup_command():
    executable = Path(sys.executable).resolve()
    if getattr(sys, 'frozen', False):
        args = [str(executable), '--autostart']
    else:
        executable = executable.with_name('pythonw.exe')
        entry = Path(__file__).resolve().with_name('desktop_entry.py')
        if not executable.is_file() or not entry.is_file():
            raise OSError('Не найден файл для фонового запуска приложения.')
        args = [str(executable), str(entry), '--autostart']
    return subprocess.list2cmdline(args)


def is_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, kind = winreg.QueryValueEx(key, VALUE_NAME)
        return kind == winreg.REG_SZ and value == startup_command()
    except FileNotFoundError:
        return False


def set_enabled(enabled):
    if enabled:
        command = startup_command()
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
