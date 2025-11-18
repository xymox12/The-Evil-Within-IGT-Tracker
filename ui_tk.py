# ui_tk.py

import tkinter as tk

from config import (
    BG_COLOR,
    FG_COLOR,
    FONT_TIME,
    FONT_TITLE,
    FONT_MONO,
    READ_INTERVAL_MS,
)
from controller import TimerController


class TimerWindow:
    def __init__(self) -> None:
        # --- Window setup ---
        self.root = tk.Tk()
        self.root.title("In-Game Time (The Evil Within)")
        self.root.configure(bg=BG_COLOR)

        self.controller = TimerController()

        # 2 columns: [label] [value]
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)

        self._build_widgets()

        # Start polling
        self.root.after(READ_INTERVAL_MS, self.poll)

    def _build_widgets(self) -> None:
        # Row 0: IGT
        tk.Label(
            self.root,
            text="IGT:",
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=FONT_MONO,
        ).grid(row=0, column=0, padx=(10, 4), pady=(10, 2), sticky="w")

        self.label_time = tk.Label(
            self.root,
            text="--:--:--",
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=FONT_TIME,
        )
        self.label_time.grid(row=0, column=1, padx=(0, 10), pady=(10, 2), sticky="w")

        # Row 1: Chapter
        tk.Label(
            self.root,
            text="Chapter:",
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=FONT_MONO,
        ).grid(row=1, column=0, padx=(10, 4), pady=(0, 10), sticky="w")

        self.label_chapter = tk.Label(
            self.root,
            text="--",
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=FONT_TITLE,
        )
        self.label_chapter.grid(row=1, column=1, padx=(0, 10), pady=(0, 10), sticky="w")

        # Row 2: Current segment
        tk.Label(
            self.root,
            text="Current Split:",
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=FONT_MONO,
        ).grid(row=2, column=0, padx=(10, 4), pady=2, sticky="w")

        self.label_current_value = tk.Label(
            self.root,
            text="--:--:--",
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=FONT_MONO,
        )
        self.label_current_value.grid(row=2, column=1, padx=(0, 10), pady=2, sticky="w")

        # Row 3: Previous segment
        tk.Label(
            self.root,
            text="Previous Split:",
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=FONT_MONO,
        ).grid(row=3, column=0, padx=(10, 4), pady=2, sticky="w")

        self.label_last_value = tk.Label(
            self.root,
            text="--:--:--",
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=FONT_MONO,
        )
        self.label_last_value.grid(row=3, column=1, padx=(0, 10), pady=2, sticky="w")

        # Row 4: Since first
        self.label_run_since_first = tk.Label(
            self.root,
            text="Since first segment: --:--:--",
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=FONT_MONO,
        )
        self.label_run_since_first.grid(row=4, column=0, columnspan=2,
                                        padx=10, pady=(4, 10), sticky="w")

        # Row 5: status
        self.label_status = tk.Label(
            self.root,
            text="",
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=FONT_MONO,
        )
        self.label_status.grid(row=5, column=0, columnspan=2,
                               padx=10, pady=(0, 10), sticky="w")

    def poll(self) -> None:
        info = self.controller.tick()

        self.label_time.config(text=info.time_text)
        self.label_chapter.config(text=info.chapter_text)
        self.label_run_since_first.config(text=info.since_first_text)
        self.label_status.config(text=info.status_text)

        # Split the "Current:" / "Previous:" lines into label + value
        current_text = info.current_segment_text
        if current_text.startswith("Current:"):
            current_value = current_text[len("Current:"):].lstrip()
        else:
            current_value = current_text
        self.label_current_value.config(text=current_value)

        last_text = info.last_segment_text
        if last_text.startswith("Previous:"):
            last_value = last_text[len("Previous:"):].lstrip()
        else:
            last_value = last_text
        self.label_last_value.config(text=last_value)

        self.root.after(READ_INTERVAL_MS, self.poll)

    def run(self) -> None:
        self.root.mainloop()
