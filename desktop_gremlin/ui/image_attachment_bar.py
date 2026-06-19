from __future__ import annotations

import os
import tkinter as tk


class ImageAttachmentBar(tk.Frame):
    def __init__(self, parent, on_remove=None, on_clear=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.on_remove = on_remove
        self.on_clear = on_clear
        self.paths: list[str] = []
        self.theme = {
            "bg": kwargs.get("bg", "#f4f1ea"),
            "chip_bg": "#ebe5d8",
            "chip_fg": "#2f2a20",
            "remove_bg": "#d9d0bd",
            "button_bg": "#4a4a4a",
            "button_fg": "#fff7d6",
            "active_bg": "#5a5a5a",
        }
        self.configure(bg=kwargs.get("bg", "#f4f1ea"))

    def apply_theme(
        self,
        bg: str,
        chip_bg: str,
        chip_fg: str,
        remove_bg: str,
        button_bg: str,
        button_fg: str,
        active_bg: str,
    ) -> None:
        self.theme = {
            "bg": bg,
            "chip_bg": chip_bg,
            "chip_fg": chip_fg,
            "remove_bg": remove_bg,
            "button_bg": button_bg,
            "button_fg": button_fg,
            "active_bg": active_bg,
        }
        self.configure(bg=bg)
        self.render()

    def set_paths(self, paths: list[str]) -> None:
        self.paths = list(paths)
        self.render()

    def render(self) -> None:
        for child in self.winfo_children():
            child.destroy()

        if not self.paths:
            self.grid_remove()
            return

        self.grid()
        tk.Label(
            self,
            text="Attached images:",
            bg=self.theme["bg"],
            fg=self.theme["chip_fg"],
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 6))

        col = 1
        for index, path in enumerate(self.paths):
            item = tk.Frame(self, bg=self.theme["chip_bg"], relief="flat", bd=1)
            item.grid(row=0, column=col, sticky="w", padx=(0, 6), pady=2)
            tk.Label(
                item,
                text=os.path.basename(path),
                bg=self.theme["chip_bg"],
                fg=self.theme["chip_fg"],
                font=("Segoe UI", 8),
                padx=6,
                pady=3,
            ).grid(row=0, column=0)
            tk.Button(
                item,
                text="x",
                command=lambda i=index: self.remove(i),
                width=2,
                relief="flat",
                bg=self.theme["remove_bg"],
                fg=self.theme["chip_fg"],
                activebackground=self.theme["active_bg"],
                activeforeground=self.theme["button_fg"],
            ).grid(row=0, column=1)
            col += 1

        tk.Button(
            self,
            text="Clear images",
            command=self.clear,
            relief="flat",
            bg=self.theme["button_bg"],
            fg=self.theme["button_fg"],
            activebackground=self.theme["active_bg"],
            activeforeground=self.theme["button_fg"],
            font=("Segoe UI", 8),
        ).grid(row=0, column=col, sticky="w")

    def remove(self, index: int) -> None:
        if self.on_remove is not None:
            self.on_remove(index)

    def clear(self) -> None:
        if self.on_clear is not None:
            self.on_clear()
