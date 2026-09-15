"""Place dialogs over their parent, including on secondary monitors."""
import sys


def center_dialog(window, parent):
    window.update_idletasks()
    parent = parent.winfo_toplevel()
    width, height = window.winfo_width(), window.winfo_height()
    left = parent.winfo_rootx()
    top = parent.winfo_rooty()
    x = left + (parent.winfo_width() - width) // 2
    y = top + (parent.winfo_height() - height) // 2
    bounds = (0, 0, window.winfo_screenwidth(), window.winfo_screenheight())
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes

        class MonitorInfo(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                        ('work', wintypes.RECT), ('flags', wintypes.DWORD)]

        api = ctypes.windll.user32
        api.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        api.MonitorFromWindow.restype = wintypes.HANDLE
        api.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        api.GetMonitorInfoW.restype = wintypes.BOOL
        monitor = api.MonitorFromWindow(parent.winfo_id(), 2)
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if api.GetMonitorInfoW(monitor, ctypes.byref(info)):
            bounds = (info.work.left, info.work.top, info.work.right, info.work.bottom)
    x = max(bounds[0], min(x, bounds[2] - width))
    y = max(bounds[1], min(y, bounds[3] - height - 32))
    # + followed by a signed integer is an absolute coordinate in Tk geometry;
    # a bare '-' would mean distance from the right/bottom screen edge.
    window.geometry(f'{width}x{height}+{x}+{y}')
