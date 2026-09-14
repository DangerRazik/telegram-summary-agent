"""Windows tray: callbacks queue commands; only Tk's thread touches the UI."""
from queue import SimpleQueue
from threading import Event

import pystray
from PIL import Image
from visual_assets import artwork


class SingleInstance:
    """A second launch brings the existing window back instead of collecting twice."""
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateMutexW.restype = wintypes.HANDLE
        self.api.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateEventW.restype = wintypes.HANDLE
        for name in ('SetEvent', 'CloseHandle'):
            getattr(self.api, name).argtypes = [wintypes.HANDLE]
            getattr(self.api, name).restype = wintypes.BOOL
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.WaitForSingleObject.restype = wintypes.DWORD
        self.mutex = self.api.CreateMutexW(None, False, 'Local\\TelegramSummaryAgent')
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        self.primary = ctypes.get_last_error() != 183
        self.event = self.api.CreateEventW(None, False, False, 'Local\\TelegramSummaryAgentOpen')
        if not self.event:
            self.api.CloseHandle(self.mutex)
            raise ctypes.WinError(ctypes.get_last_error())

    def request_open(self):
        self.api.SetEvent(self.event)

    def open_requested(self):
        return self.api.WaitForSingleObject(self.event, 0) == 0

    def close(self):
        self.api.CloseHandle(self.event)
        self.api.CloseHandle(self.mutex)


class Tray:
    def __init__(self):
        self.commands = SimpleQueue()
        self.ready = Event()
        image = artwork('logo').resize((64, 64), Image.Resampling.LANCZOS)
        self.icon = pystray.Icon('telegram_summary_agent', image, 'Summary Agent', pystray.Menu(
            pystray.MenuItem('Открыть', lambda: self.commands.put('open'), default=True),
            pystray.MenuItem('Собрать сейчас', lambda: self.commands.put('collect')),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Выйти полностью', lambda: self.commands.put('exit'))))

    def start(self):
        def setup(icon):
            icon.visible = True
            self.ready.set()
        self.icon.run_detached(setup)

    def stop(self):
        self.icon.stop()
