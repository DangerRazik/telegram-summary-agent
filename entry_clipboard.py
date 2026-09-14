"""Clipboard controls for single-line CTk entries, including Russian layouts."""
import sys
import tkinter as tk


def enable_paste(entry):
    def paste(event=None):
        if entry.cget('state') != 'normal':
            return 'break'
        try:
            text = entry.clipboard_get()
        except tk.TclError:
            return 'break'
        if entry.select_present():
            position = entry.index('sel.first')
            entry.delete('sel.first', 'sel.last')
        else:
            position = entry.index('insert')
        entry.insert(position, text)
        entry.icursor(position + len(text))
        return 'break'

    def select_all(event=None):
        if entry.cget('state') == 'normal':
            entry.select_range(0, 'end')
            entry.icursor('end')
        return 'break'

    def shortcut(event):
        if event.state & 0x0004 and not event.state & 0x0008:
            key = event.keysym.lower()
            physical = event.keycode if sys.platform == 'win32' else None
            if key in ('v', 'cyrillic_em') or physical == 86:
                return paste()
            if key in ('a', 'cyrillic_ef') or physical == 65:
                return select_all()

    def popup(event):
        from styled_controls import Popup
        entry.focus_set()
        if entry.cget('state') == 'normal':
            Popup(entry, [('Вставить', paste), ('Выделить всё', select_all)],
                  event.x_root, event.y_root, width=190)
        return 'break'

    entry.bind('<KeyPress>', shortcut, add=True)
    entry.bind('<<Paste>>', paste, add=True)
    entry.bind('<Shift-Insert>', paste, add=True)
    entry.bind('<Button-3>', popup, add=True)
    return paste, shortcut
