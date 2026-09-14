"""Small application menus shared by selectors and clipboard actions."""
import tkinter as tk
import customtkinter as ctk
from visual_assets import icon


class Popup(ctk.CTkFrame):
    """An overlay inside its owner window: no native focus or mouse capture."""
    def __init__(self, owner, items, x, y, width=250, selected=None):
        self.host = owner.winfo_toplevel()
        previous = getattr(self.host, '_summary_popup', None)
        if previous is not None and previous.winfo_exists():
            previous.close()
        super().__init__(self.host, fg_color='#0e253b', corner_radius=8,
                         border_width=1, border_color='#36546e')
        self.host._summary_popup = self
        self.owner = owner
        self.items = items
        self._bindings = []
        self.index = next((i for i, item in enumerate(items) if item[0] == selected), 0)
        self.buttons = []
        for index, (label, command) in enumerate(items):
            button = ctk.CTkButton(self, text=label, anchor='w', height=36,
                corner_radius=6, fg_color='transparent', hover_color='#163b5e',
                text_color='#f1f5f9', font=ctk.CTkFont(size=14),
                command=lambda i=index: self.choose(i))
            button.pack(fill='x', padx=6, pady=3)
            self.buttons.append(button)
        self.highlight()
        self.update_idletasks()
        height = self.winfo_reqheight()
        width = max(width, self.winfo_reqwidth())
        x = max(0, min(x - self.host.winfo_rootx(), self.host.winfo_width() - width))
        y = max(0, min(y - self.host.winfo_rooty(), self.host.winfo_height() - height))
        # Tk place uses physical pixels; CTk's wrapper would scale these twice.
        tk.Place.place(self, x=x, y=y, width=width, height=height)
        self.lift()
        self.after_idle(self.install_bindings)

    def install_bindings(self):
        if not self.winfo_exists():
            return
        for sequence, callback in (
            ('<Button-1>', self.outside), ('<Button-3>', self.outside),
            ('<Escape>', lambda e: self.close()),
            ('<Up>', lambda e: self.move(-1)), ('<Down>', lambda e: self.move(1)),
            ('<Return>', lambda e: self.choose(self.index)),
            ('<Unmap>', self.host_unmapped), ('<FocusOut>', self.focus_changed)):
            binding = tk.Misc.bind(self.host, sequence, callback, add='+')
            self._bindings.append((sequence, binding))

    def highlight(self):
        for i, button in enumerate(self.buttons):
            button.configure(fg_color='#163b5e' if i == self.index else 'transparent')

    def move(self, step):
        self.index = (self.index + step) % len(self.items)
        self.highlight()
        return 'break'

    def choose(self, index):
        command = self.items[index][1]
        self.close()
        command()
        return 'break'

    def outside(self, event):
        if not str(event.widget).startswith(str(self) + '.') and event.widget is not self:
            self.close()

    def host_unmapped(self, event):
        if event.widget is self.host:
            self.close()

    def focus_changed(self, event):
        self.after_idle(self.check_focus)

    def check_focus(self):
        if self.winfo_exists():
            focused = self.focus_get()
            if focused is None or focused.winfo_toplevel() is not self.host:
                self.close()

    def close(self):
        self.destroy()

    def destroy(self):
        for sequence, binding in self._bindings:
            try:
                tk.Misc.unbind(self.host, sequence, binding)
            except tk.TclError:
                pass
        self._bindings.clear()
        if getattr(self.host, '_summary_popup', None) is self:
            self.host._summary_popup = None
        super().destroy()


class Select(ctk.CTkButton):
    def __init__(self, master, values, command=None, **kwargs):
        for key in ('button_color', 'button_hover_color', 'dropdown_fg_color',
                    'dropdown_hover_color', 'dropdown_font'):
            kwargs.pop(key, None)
        kwargs.update(corner_radius=8, border_width=1, border_color='#36546e',
                      hover_color='#163b5e', anchor='w')
        self.values = values
        self.on_select = command
        self.value = values[0]
        self.popup = None
        super().__init__(master, text=self.value, command=self.open, **kwargs)
        arrow = ctk.CTkLabel(self, text='', width=28, height=24,
                            image=icon('chevron_down', 18, '#9ab3cf'), fg_color='transparent')
        arrow.place(relx=1, rely=.5, x=-8, anchor='e')
        arrow.bind('<Button-1>', lambda e: self.open())
        self.bind('<space>', lambda e: self.open())
        self.bind('<Return>', lambda e: self.open())

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        self.configure(text=value)

    def choose(self, value):
        self.set(value)
        if self.on_select:
            self.on_select(value)

    def open(self):
        if self.cget('state') == 'disabled':
            return
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.close()
            return
        self.popup = Popup(self, [(v, lambda v=v: self.choose(v)) for v in self.values],
            self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + 4,
            width=self.winfo_width(), selected=self.value)
