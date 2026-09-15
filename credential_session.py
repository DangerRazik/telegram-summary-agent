"""Telegram auth state in the current user's Windows Credential Manager."""
import ctypes
from ctypes import wintypes
import hashlib
from pathlib import Path

import app_paths
from telethon.sessions import StringSession


class CredentialError(ValueError):
    pass


class Credential(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
                ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
                ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD),
                ('Attributes', ctypes.c_void_p), ('TargetAlias', wintypes.LPWSTR),
                ('UserName', wintypes.LPWSTR)]


class CredentialStore:
    def __init__(self, target=None):
        # Keep the source checkout and installed EXE's accounts separate.
        directory = str(Path(app_paths.DATA_DIR).resolve()).casefold()
        self.target = target or 'TelegramSummaryAgent/Session/' + hashlib.sha256(directory.encode()).hexdigest()[:24]
        self.api = ctypes.WinDLL('advapi32', use_last_error=True)
        self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                       ctypes.POINTER(ctypes.POINTER(Credential))]
        self.api.CredReadW.restype = wintypes.BOOL
        self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        self.api.CredWriteW.restype = wintypes.BOOL
        self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.api.CredDeleteW.restype = wintypes.BOOL
        self.api.CredFree.argtypes = [ctypes.c_void_p]
        self.api.CredFree.restype = None

    def read(self):
        pointer = ctypes.POINTER(Credential)()
        if not self.api.CredReadW(self.target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise CredentialError('Не удалось прочитать сессию из хранилища Windows.')
        try:
            return ctypes.string_at(pointer.contents.CredentialBlob,
                                    pointer.contents.CredentialBlobSize).decode('ascii')
        except UnicodeError:
            raise CredentialError('Запись сессии в хранилище Windows повреждена.') from None
        finally:
            self.api.CredFree(pointer)

    def write(self, value):
        blob = value.encode('ascii')
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = Credential()
        credential.Type = 1  # Generic credential, accessible to this Windows user.
        credential.TargetName = self.target
        credential.UserName = 'TelegramSummaryAgent'
        credential.Comment = 'Telegram session for Summary Agent'
        credential.Persist = 2  # Local machine persistence; no roaming.
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = buffer
        if not self.api.CredWriteW(ctypes.byref(credential), 0):
            raise CredentialError('Не удалось сохранить сессию в хранилище Windows. Файловая копия не создаётся.')
        if self.read() != value:
            raise CredentialError('Windows не подтвердила сохранение сессии.')

    def delete(self):
        if not self.api.CredDeleteW(self.target, 1, 0) and ctypes.get_last_error() != 1168:
            raise CredentialError('Не удалось сбросить сессию в хранилище Windows.')


class CredentialSession(StringSession):
    def __init__(self, store=None, value=None):
        self.store = store or CredentialStore()
        saved = self.store.read() if value is None else value
        try:
            super().__init__(saved or '')
        except Exception:
            raise CredentialError('Сессия в хранилище Windows повреждена. Не удалось выполнить вход.') from None
        self._saved = saved

    def save(self):
        value = StringSession.save(self)
        # A DC switch temporarily clears the auth key; retain the last usable key.
        if value and value != self._saved:
            self.store.write(value)
            self._saved = value
        return value

    def delete(self):
        self.store.delete()
        self._saved = None
        self.auth_key = None
        return True

    def clone(self, to_instance=None):
        # Temporary CDN clients must never overwrite the main account credential.
        return super().clone(to_instance if to_instance is not None else StringSession())
