from __future__ import annotations

from dataclasses import replace
import tkinter as tk
from tkinter import messagebox

from ..config import AppConfig


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, config: AppConfig, on_save):
        super().__init__(parent)
        self.title("Settings")
        self.resizable(True, True)
        self.configure(bg="#f4f1ea")
        self.transient(parent)
        self.grab_set()

        self.config = replace(config)
        self.on_save = on_save
        self.entries: dict[str, tk.Entry] = {}
        self.think_var = tk.BooleanVar(value=self.config.think)

        self.build_ui()
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.wait_visibility()
        self.focus_set()

    def build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        body = tk.Frame(self, bg="#f4f1ea", padx=14, pady=14)
        body.grid(row=0, column=0, sticky="nsew")
        body.grid_columnconfigure(1, weight=1)

        row = 0
        self.entries["model"] = self.add_entry(body, row, "Model", self.config.model)
        row += 1

        tk.Label(body, text="System prompt", bg="#f4f1ea", fg="#2f2a20").grid(
            row=row, column=0, sticky="nw", pady=(6, 2)
        )
        self.system_prompt_text = tk.Text(
            body,
            height=5,
            width=52,
            wrap="word",
            bg="#fffdf7",
            fg="#222222",
            relief="solid",
            bd=1,
            padx=8,
            pady=6,
            font=("Segoe UI", 9),
        )
        self.system_prompt_text.insert("1.0", self.config.system_prompt)
        self.system_prompt_text.grid(row=row, column=1, sticky="ew", pady=(6, 2))
        row += 1

        fields = [
            ("temperature", "Temperature", self.config.temperature),
            ("top_p", "Top P", self.config.top_p),
            ("top_k", "Top K", self.config.top_k),
            ("num_ctx", "Num Context", self.config.num_ctx),
            ("num_predict", "Num Predict", self.config.num_predict),
            ("seed", "Seed", self.config.seed),
            ("repeat_penalty", "Repeat Penalty", self.config.repeat_penalty),
            ("repeat_last_n", "Repeat Last N", self.config.repeat_last_n),
            ("min_p", "Min P", "" if self.config.min_p is None else self.config.min_p),
            ("max_tool_rounds", "Max Tool Rounds", self.config.max_tool_rounds),
            (
                "python_runner_timeout_seconds",
                "Python Timeout Seconds",
                self.config.python_runner_timeout_seconds,
            ),
            ("max_python_code_chars", "Max Python Code Chars", self.config.max_python_code_chars),
            ("max_python_output_chars", "Max Python Output Chars", self.config.max_python_output_chars),
        ]
        for key, label, value in fields:
            self.entries[key] = self.add_entry(body, row, label, str(value))
            row += 1

        think = tk.Checkbutton(
            body,
            text="Think",
            variable=self.think_var,
            bg="#f4f1ea",
            fg="#2f2a20",
            selectcolor="#f4f1ea",
            activebackground="#f4f1ea",
            activeforeground="#2f2a20",
        )
        think.grid(row=row, column=1, sticky="w", pady=(6, 2))
        row += 1

        buttons = tk.Frame(body, bg="#f4f1ea")
        buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(14, 0))

        tk.Button(buttons, text="Reset defaults", command=self.reset_defaults, width=14).grid(
            row=0, column=0, padx=(0, 8)
        )
        tk.Button(buttons, text="Cancel", command=self.cancel, width=10).grid(row=0, column=1, padx=(0, 8))
        tk.Button(
            buttons,
            text="Save",
            command=self.save,
            width=10,
            bg="#2b2b2b",
            fg="#fff7d6",
            activebackground="#444444",
            activeforeground="#fff7d6",
            relief="flat",
        ).grid(row=0, column=2)

    def add_entry(self, parent, row: int, label: str, value: str) -> tk.Entry:
        tk.Label(parent, text=label, bg="#f4f1ea", fg="#2f2a20").grid(
            row=row, column=0, sticky="w", pady=2, padx=(0, 10)
        )
        entry = tk.Entry(parent, bg="#fffdf7", fg="#222222", relief="solid", bd=1, font=("Segoe UI", 9))
        entry.insert(0, value)
        entry.grid(row=row, column=1, sticky="ew", pady=2)
        return entry

    def reset_defaults(self) -> None:
        defaults = AppConfig.defaults()
        self.entries["model"].delete(0, "end")
        self.entries["model"].insert(0, defaults.model)
        self.system_prompt_text.delete("1.0", "end")
        self.system_prompt_text.insert("1.0", defaults.system_prompt)
        for key in (
            "temperature",
            "top_p",
            "top_k",
            "num_ctx",
            "num_predict",
            "seed",
            "repeat_penalty",
            "repeat_last_n",
            "min_p",
            "max_tool_rounds",
            "python_runner_timeout_seconds",
            "max_python_code_chars",
            "max_python_output_chars",
        ):
            self.entries[key].delete(0, "end")
            value = getattr(defaults, key)
            self.entries[key].insert(0, "" if value is None else str(value))
        self.think_var.set(defaults.think)

    def save(self) -> None:
        try:
            new_config = replace(
                self.config,
                model=self.entries["model"].get().strip() or AppConfig.defaults().model,
                system_prompt=self.system_prompt_text.get("1.0", "end").strip(),
                temperature=self.parse_float("temperature", 0, 2),
                top_p=self.parse_float("top_p", 0, 1),
                top_k=self.parse_int("top_k", minimum=1),
                num_ctx=self.parse_int("num_ctx", minimum=1024),
                num_predict=self.parse_num_predict(),
                seed=self.parse_int("seed"),
                repeat_penalty=self.parse_float("repeat_penalty", minimum=0),
                repeat_last_n=self.parse_int("repeat_last_n", minimum=0),
                min_p=self.parse_optional_float("min_p", 0, 1),
                max_tool_rounds=self.parse_int("max_tool_rounds", minimum=0),
                python_runner_timeout_seconds=self.parse_int("python_runner_timeout_seconds", minimum=1),
                max_python_code_chars=self.parse_int("max_python_code_chars", minimum=100),
                max_python_output_chars=self.parse_int("max_python_output_chars", minimum=100),
                think=self.think_var.get(),
            )
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc), parent=self)
            return

        if not new_config.system_prompt:
            messagebox.showerror("Invalid settings", "System prompt cannot be blank.", parent=self)
            return

        self.on_save(new_config)
        self.destroy()

    def cancel(self) -> None:
        self.destroy()

    def parse_float(self, key: str, minimum: float | None = None, maximum: float | None = None) -> float:
        raw = self.entries[key].get().strip()
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"{self.label_for(key)} must be a number.") from exc
        if minimum is not None and value < minimum:
            raise ValueError(f"{self.label_for(key)} must be at least {minimum}.")
        if maximum is not None and value > maximum:
            raise ValueError(f"{self.label_for(key)} must be at most {maximum}.")
        return value

    def parse_optional_float(self, key: str, minimum: float, maximum: float) -> float | None:
        raw = self.entries[key].get().strip()
        if not raw:
            return None
        value = self.parse_float(key, minimum, maximum)
        return value

    def parse_int(self, key: str, minimum: int | None = None) -> int:
        raw = self.entries[key].get().strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{self.label_for(key)} must be an integer.") from exc
        if minimum is not None and value < minimum:
            raise ValueError(f"{self.label_for(key)} must be at least {minimum}.")
        return value

    def parse_num_predict(self) -> int:
        value = self.parse_int("num_predict")
        if value != -1 and value < 1:
            raise ValueError("Num Predict must be -1 or at least 1.")
        return value

    def label_for(self, key: str) -> str:
        labels = {
            "temperature": "Temperature",
            "top_p": "Top P",
            "top_k": "Top K",
            "num_ctx": "Num Context",
            "num_predict": "Num Predict",
            "seed": "Seed",
            "repeat_penalty": "Repeat Penalty",
            "repeat_last_n": "Repeat Last N",
            "min_p": "Min P",
            "max_tool_rounds": "Max Tool Rounds",
            "python_runner_timeout_seconds": "Python Timeout Seconds",
            "max_python_code_chars": "Max Python Code Chars",
            "max_python_output_chars": "Max Python Output Chars",
        }
        return labels.get(key, key)
