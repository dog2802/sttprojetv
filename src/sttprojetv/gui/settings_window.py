"""Окно настроек (tkinter): словарь терминов, микрофон, хоткей, модель, режим вставки.

Все поля сохраняются автоматически при изменении - отдельной кнопки "Сохранить" нет.
"""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from pynput import mouse as pynput_mouse
from pynput.mouse import Button as MouseButton

from .. import config as config_module
from ..hotkey import MOUSE_PREFIX

logger = logging.getLogger(__name__)

MODEL_OPTIONS = ["auto", "tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]

MODEL_DESCRIPTIONS = {
    "auto": "Подобрать автоматически под ваше железо (рекомендуется)",
    "tiny": "Самая быстрая и неточная. Для слабых ПК без видеокарты",
    "base": "Быстрая, точность выше tiny. Для ПК без видеокарты",
    "small": "Баланс скорости и точности. CPU или GPU от ~2 ГБ VRAM",
    "medium": "Высокая точность. Нужна GPU от ~3-4 ГБ VRAM",
    "large-v3": "Максимальная точность, но медленнее turbo. GPU от ~6 ГБ VRAM",
    "large-v3-turbo": "Точность как large-v3, но быстрее. GPU от ~6 ГБ VRAM (RTX 4060 Ti и мощнее)",
}

# Индикатор статуса (правый верхний угол окна) - совмещает статус записи/распознавания
# (как в трее) и статус применения настроек, приоритет отдаётся последнему.
_STATUS_COLORS = {
    "idle": "#2ecc71",
    "listening": "#e74c3c",
    "processing": "#e67e22",
    "applying": "#f1c40f",
}
_STATUS_LABELS = {
    "idle": "Готово к работе",
    "listening": "Идёт запись...",
    "processing": "Распознаю речь...",
    "applying": "Применяю новые настройки...",
}

_HELP_TEXTS = {
    "dictionary": (
        "Список слов, которые Whisper часто слышит неправильно (игровой жаргон, редкие "
        "термины). Распознанный текст сверяется с этим списком, похожие искажения "
        "заменяются на точную форму. Каждый .txt файл в папке dictionaries/ — отдельный "
        "список терминов. Можно завести несколько (например, под разные игры) и "
        "переключаться между ними здесь."
    ),
    "model": (
        "Модель распознавания речи. «auto» сама подбирает модель под ваше железо "
        "(рекомендуется). Чем больше модель — тем точнее, но медленнее и требовательнее "
        "к видеопамяти."
    ),
    "output_clipboard": (
        "Текст копируется в буфер обмена (как Ctrl+C). Вставить его в нужное место нужно "
        "вручную (Ctrl+V)."
    ),
    "output_paste": (
        "После распознавания программа сама нажимает Ctrl+V в активном окне. Не сработает "
        "там, где программная вставка из буфера заблокирована."
    ),
    "output_type": (
        "Программа печатает текст, эмулируя настоящие нажатия клавиш — работает и там, "
        "где вставка из буфера блокируется (например, в некоторых играх)."
    ),
}

_LIGHT_PALETTE = {
    "bg": "#f0f0f0",
    "fg": "#000000",
    "field_bg": "#ffffff",
    "select_bg": "#0078d7",
    "select_fg": "#ffffff",
    "muted_fg": "#666666",
    "tooltip_bg": "#ffffff",
    "tooltip_fg": "#000000",
    "icon_fg": "#000000",
}
_DARK_PALETTE = {
    "bg": "#2b2b2b",
    "fg": "#e6e6e6",
    "field_bg": "#3c3c3c",
    "select_bg": "#0078d7",
    "select_fg": "#ffffff",
    "muted_fg": "#a0a0a0",
    "tooltip_bg": "#454545",
    "tooltip_fg": "#ffffff",
    "icon_fg": "#ffffff",
}

# Tkinter keysym -> имя клавиши в формате pynput (см. hotkey.parse_key).
_KEYSYM_TO_PYNPUT = {
    "Control_L": "ctrl_l",
    "Control_R": "ctrl_r",
    "Alt_L": "alt_l",
    "Alt_R": "alt_r",
    "Shift_L": "shift_l",
    "Shift_R": "shift_r",
    "Caps_Lock": "caps_lock",
    "Escape": "esc",
    "Return": "enter",
    "Tab": "tab",
    "space": "space",
    "Prior": "page_up",
    "Next": "page_down",
    "Home": "home",
    "End": "end",
    "Insert": "insert",
    "Delete": "delete",
    "Up": "up",
    "Down": "down",
    "Left": "left",
    "Right": "right",
    "Num_Lock": "num_lock",
    "Scroll_Lock": "scroll_lock",
    "Pause": "pause",
}

# Кнопки мыши, которые можно назначить хоткеем (боковые - основной сценарий использования;
# left/right намеренно не включены, иначе клик по самому диалогу настроек будет их перехватывать).
_MOUSE_BUTTON_NAMES = {
    MouseButton.x1: f"{MOUSE_PREFIX}x1",
    MouseButton.x2: f"{MOUSE_PREFIX}x2",
    MouseButton.middle: f"{MOUSE_PREFIX}middle",
}

_HOTKEY_DISPLAY_NAMES = {
    f"{MOUSE_PREFIX}x1": "Мышь: боковая кнопка 1 (Back)",
    f"{MOUSE_PREFIX}x2": "Мышь: боковая кнопка 2 (Forward)",
    f"{MOUSE_PREFIX}middle": "Мышь: средняя кнопка",
}


def _keysym_to_pynput_name(keysym: str) -> str:
    if keysym in _KEYSYM_TO_PYNPUT:
        return _KEYSYM_TO_PYNPUT[keysym]
    return keysym.lower()


def _mouse_button_to_name(button: MouseButton) -> str | None:
    return _MOUSE_BUTTON_NAMES.get(button)


def _hotkey_display_name(name: str) -> str:
    return _HOTKEY_DISPLAY_NAMES.get(name, name)


def _fix_mojibake(name: str) -> str:
    """PyAudio на Windows иногда декодирует имена устройств как cp1251 вместо UTF-8,
    из-за чего кириллица превращается в кракозябры. Если строка похожа на такой случай,
    прогоняем её через cp1251->utf-8 обратно; если не получается - возвращаем как есть."""
    try:
        return name.encode("cp1251").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def _attach_dropdown_hover(
    combobox: ttk.Combobox, options: list[str], descriptions: dict[str, str], description_var: tk.StringVar
) -> None:
    """При наведении на пункт в открытом списке показывает его описание в description_var.
    Использует недокументированный внутренний виджет попдауна ttk.Combobox - если механизм
    недоступен на какой-то версии Tk, просто молча ничего не делает (не критично для работы)."""

    def on_motion(y: str) -> None:
        try:
            popdown = combobox.tk.eval(f"ttk::combobox::PopdownWindow {combobox}")
            listbox = f"{popdown}.f.l"
            index = int(combobox.tk.call(listbox, "nearest", y))
            if 0 <= index < len(options):
                description_var.set(descriptions.get(options[index], ""))
        except Exception:
            pass

    def on_open(event: tk.Event | None = None) -> None:
        try:
            popdown = combobox.tk.eval(f"ttk::combobox::PopdownWindow {combobox}")
            listbox = f"{popdown}.f.l"
            tcl_cb = combobox.register(on_motion)
            combobox.tk.call("bind", listbox, "<Motion>", f"{tcl_cb} %y")
        except Exception:
            logger.debug("Hover-подсказки для выпадающего списка недоступны", exc_info=True)

    combobox.bind("<Button-1>", lambda e: combobox.after(50, on_open))


def _set_titlebar_dark(window: tk.Toplevel, dark: bool) -> None:
    """Красит системный заголовок окна (который рисует сама Windows, не Tkinter) в тёмный
    цвет через DWM API. Недокументированная для Tkinter, но стандартная для Win32 фича -
    если недоступна (не Windows, старая сборка ОС) - молча ничего не делает."""
    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE: 20 (новые Win10/11), 19 (старые)
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
            if result == 0:
                break
    except Exception:
        logger.debug("Не удалось затемнить заголовок окна", exc_info=True)


def _attach_static_tooltip(
    widget: tk.Widget, text: str, get_colors: Callable[[], tuple[str, str]]
) -> None:
    """Простая всплывающая подсказка с фиксированным текстом по наведению на widget.
    get_colors возвращает (фон, текст) в цветах текущей темы на момент показа."""
    state: dict[str, tk.Toplevel | None] = {"tip": None}

    def show(event: tk.Event) -> None:
        if state["tip"] is not None:
            return
        bg, fg = get_colors()
        tip = tk.Toplevel(widget)
        tip.wm_overrideredirect(True)
        x = widget.winfo_rootx()
        y = widget.winfo_rooty() + widget.winfo_height() + 4
        tip.wm_geometry(f"+{x}+{y}")
        ttk.Label(
            tip,
            text=text,
            relief="solid",
            borderwidth=1,
            padding=(6, 4),
            wraplength=280,
            justify="left",
            background=bg,
            foreground=fg,
        ).pack()
        state["tip"] = tip

    def hide(event: tk.Event) -> None:
        if state["tip"] is not None:
            state["tip"].destroy()
            state["tip"] = None

    widget.bind("<Enter>", show)
    widget.bind("<Leave>", hide)


def _list_input_microphones() -> list[tuple[int, str]]:
    try:
        import pyaudio
    except ImportError:
        return []

    devices: list[tuple[int, str]] = []
    pa = pyaudio.PyAudio()
    try:
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                raw_name = str(info.get("name", f"Устройство {i}"))
                devices.append((i, _fix_mojibake(raw_name)))
    finally:
        pa.terminate()
    return devices


class _ThemeSwitch:
    """Маленький переключатель-ползунок светлая/тёмная тема (рисуется на Canvas)."""

    _WIDTH = 40
    _HEIGHT = 20

    def __init__(self, parent: tk.Widget, is_dark: bool, on_toggle: Callable[[bool], None]) -> None:
        self._is_dark = is_dark
        self._on_toggle = on_toggle
        self.canvas = tk.Canvas(
            parent, width=self._WIDTH, height=self._HEIGHT, highlightthickness=0, cursor="hand2"
        )
        self.canvas.bind("<Button-1>", self._on_click)
        self._redraw()

    def _redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        track = "#5a5a5a" if self._is_dark else "#cfcfcf"
        knob = "#f1c40f" if self._is_dark else "#ffffff"
        r = self._HEIGHT / 2
        c.create_oval(0, 0, self._HEIGHT, self._HEIGHT, fill=track, outline="")
        c.create_oval(self._WIDTH - self._HEIGHT, 0, self._WIDTH, self._HEIGHT, fill=track, outline="")
        c.create_rectangle(r, 0, self._WIDTH - r, self._HEIGHT, fill=track, outline="")
        knob_x = self._WIDTH - self._HEIGHT if self._is_dark else 0
        c.create_oval(knob_x + 2, 2, knob_x + self._HEIGHT - 2, self._HEIGHT - 2, fill=knob, outline="")

    def _on_click(self, event: tk.Event) -> None:
        self._is_dark = not self._is_dark
        self._redraw()
        self._on_toggle(self._is_dark)

    def set_bg(self, color: str) -> None:
        self.canvas.configure(bg=color)


class SettingsWindow:
    """Держит config Application'а по ссылке и правит его на месте - изменения сразу видны
    работающему инстансу. Каждое поле сохраняется на диск сразу при изменении (без отдельной
    кнопки "Сохранить"). on_config_changed вызывается при каждом таком изменении, чтобы
    Application пересобрал STT-движок/хоткей, если модель, микрофон или хоткей поменялись -
    без перезапуска программы."""

    def __init__(
        self, config: dict[str, Any], on_config_changed: Callable[[], None] | None = None
    ) -> None:
        self._config = config
        self._on_config_changed = on_config_changed
        self._toplevel: tk.Toplevel | None = None
        self._status_canvas: tk.Canvas | None = None
        self._status_oval: int | None = None
        self._status_tooltip: tk.Toplevel | None = None
        self._recording_status = "idle"
        self._applying = False
        self._theme_switch: _ThemeSwitch | None = None
        self._current_palette = _LIGHT_PALETTE
        self._help_icons: list[ttk.Label] = []
        self._themed_comboboxes: list[ttk.Combobox] = []

    def show(self, parent: tk.Tk) -> None:
        if self._toplevel is not None and self._toplevel.winfo_exists():
            self._toplevel.lift()
            self._toplevel.focus_force()
            return

        win = tk.Toplevel(parent)
        win.title("STTProjetV - настройки")
        win.resizable(False, False)
        self._toplevel = win

        self._build_theme_switch(win)
        self._build_status_indicator(win)
        self._build_terms_section(win)
        self._build_options_section(win)
        self._apply_theme(self._config.get("theme", "light") == "dark")

    # --- тема ---

    def _build_theme_switch(self, win: tk.Toplevel) -> None:
        frame = ttk.Frame(win)
        frame.grid(row=0, column=0, sticky="nw", padx=10, pady=(8, 0))
        is_dark = self._config.get("theme", "light") == "dark"
        ttk.Label(frame, text="☀").pack(side=tk.LEFT, padx=(0, 3))
        self._theme_switch = _ThemeSwitch(frame, is_dark, self._on_theme_toggle)
        self._theme_switch.canvas.pack(side=tk.LEFT)
        ttk.Label(frame, text="🌙").pack(side=tk.LEFT, padx=(3, 0))

    def _on_theme_toggle(self, is_dark: bool) -> None:
        self._config["theme"] = "dark" if is_dark else "light"
        config_module.save_config(self._config)
        self._apply_theme(is_dark)

    def _make_help_icon(self, parent: tk.Widget, text: str) -> ttk.Label:
        icon = ttk.Label(parent, text="❔", foreground=self._current_palette["icon_fg"], cursor="question_arrow")
        _attach_static_tooltip(
            icon, text, lambda: (self._current_palette["tooltip_bg"], self._current_palette["tooltip_fg"])
        )
        self._help_icons.append(icon)
        return icon

    def _apply_theme(self, is_dark: bool) -> None:
        palette = _DARK_PALETTE if is_dark else _LIGHT_PALETTE
        self._current_palette = palette
        assert self._toplevel is not None

        style = ttk.Style(self._toplevel)
        style.theme_use("clam")
        for widget_class in ("TFrame", "TLabelframe", "TLabelframe.Label", "TLabel", "TCheckbutton", "TRadiobutton", "TButton"):
            style.configure(widget_class, background=palette["bg"], foreground=palette["fg"])
        style.configure("TEntry", fieldbackground=palette["field_bg"], foreground=palette["fg"])
        style.configure(
            "TCombobox",
            fieldbackground=palette["field_bg"],
            foreground=palette["fg"],
            background=palette["bg"],
        )
        style.map("TCombobox", fieldbackground=[("readonly", palette["field_bg"])])
        style.map("TButton", background=[("active", palette["select_bg"])])
        # Без этого при наведении/фокусе clam-тема подставляет свой светлый hover-фон,
        # и тёмный текст на нём становится нечитаемым (или наоборот в тёмной теме).
        for widget_class in ("TRadiobutton", "TCheckbutton"):
            style.map(
                widget_class,
                background=[("active", palette["bg"])],
                foreground=[("active", palette["fg"])],
            )

        self._toplevel.configure(bg=palette["bg"])
        _set_titlebar_dark(self._toplevel, is_dark)
        self._terms_listbox.configure(
            bg=palette["field_bg"],
            fg=palette["fg"],
            selectbackground=palette["select_bg"],
            selectforeground=palette["select_fg"],
        )
        if self._status_canvas is not None:
            self._status_canvas.configure(bg=palette["bg"])
        if self._theme_switch is not None:
            self._theme_switch.set_bg(palette["bg"])
        self._model_description_label.configure(foreground=palette["muted_fg"])
        for icon in self._help_icons:
            icon.configure(foreground=palette["icon_fg"])
        for combobox in self._themed_comboboxes:
            self._theme_combobox_popdown(combobox, palette)

    def _theme_combobox_popdown(self, combobox: ttk.Combobox, palette: dict[str, str]) -> None:
        """Красит выпадающий список ttk.Combobox - это отдельный внутренний Tcl-виджет,
        не подчиняющийся обычным ttk.Style. Если механизм недоступен - молча пропускаем."""
        try:
            popdown = combobox.tk.eval(f"ttk::combobox::PopdownWindow {combobox}")
            listbox = f"{popdown}.f.l"
            combobox.tk.call(
                listbox,
                "configure",
                "-background",
                palette["field_bg"],
                "-foreground",
                palette["fg"],
                "-selectbackground",
                palette["select_bg"],
                "-selectforeground",
                palette["select_fg"],
            )
        except Exception:
            logger.debug("Не удалось покрасить выпадающий список комбобокса", exc_info=True)

    # --- индикатор статуса (запись/распознавание/применение настроек) ---

    def _build_status_indicator(self, win: tk.Toplevel) -> None:
        frame = ttk.Frame(win)
        frame.grid(row=0, column=1, sticky="ne", padx=10, pady=(8, 0))
        ttk.Label(frame, text="Статус:").pack(side=tk.LEFT, padx=(0, 4))
        self._status_canvas = tk.Canvas(frame, width=16, height=16, highlightthickness=0)
        self._status_canvas.pack(side=tk.LEFT)
        self._status_oval = self._status_canvas.create_oval(
            2, 2, 14, 14, fill=_STATUS_COLORS["idle"], outline=""
        )
        self._status_canvas.bind("<Enter>", self._show_status_tooltip)
        self._status_canvas.bind("<Leave>", self._hide_status_tooltip)

    def _current_status_key(self) -> str:
        return "applying" if self._applying else self._recording_status

    def _refresh_status_indicator(self) -> None:
        key = self._current_status_key()
        color = _STATUS_COLORS.get(key, _STATUS_COLORS["idle"])
        if self._status_canvas is not None and self._toplevel is not None and self._toplevel.winfo_exists():
            self._status_canvas.itemconfig(self._status_oval, fill=color)
        if self._status_tooltip is not None and self._status_tooltip.winfo_exists():
            for child in self._status_tooltip.winfo_children():
                child.configure(text=_STATUS_LABELS.get(key, ""))

    def _show_status_tooltip(self, event: tk.Event) -> None:
        if self._status_tooltip is not None or self._toplevel is None:
            return
        tip = tk.Toplevel(self._toplevel)
        tip.wm_overrideredirect(True)
        x = self._status_canvas.winfo_rootx()
        y = self._status_canvas.winfo_rooty() + self._status_canvas.winfo_height() + 4
        tip.wm_geometry(f"+{x}+{y}")
        ttk.Label(
            tip,
            text=_STATUS_LABELS.get(self._current_status_key(), ""),
            relief="solid",
            borderwidth=1,
            padding=(4, 2),
            background=self._current_palette["tooltip_bg"],
            foreground=self._current_palette["tooltip_fg"],
        ).pack()
        self._status_tooltip = tip

    def _hide_status_tooltip(self, event: tk.Event) -> None:
        if self._status_tooltip is not None:
            self._status_tooltip.destroy()
            self._status_tooltip = None

    def _schedule_on_ui_thread(self, fn: Callable[[], None]) -> None:
        if self._toplevel is not None and self._toplevel.winfo_exists():
            self._toplevel.after(0, fn)

    def set_recording_status(self, status: str) -> None:
        """Вызывается Application'ом при смене статуса записи/распознавания -
        "idle"/"listening"/"processing" (как в трее)."""
        if status not in ("idle", "listening", "processing"):
            return
        self._recording_status = status
        self._schedule_on_ui_thread(self._refresh_status_indicator)

    def set_apply_status(self, status: str) -> None:
        """Вызывается Application'ом при старте/завершении применения настроек -
        "applying" / "ready"."""
        if status not in ("applying", "ready"):
            return
        self._applying = status == "applying"
        self._schedule_on_ui_thread(self._refresh_status_indicator)

    # --- словарь терминов ---

    def _build_terms_section(self, win: tk.Toplevel) -> None:
        frame = ttk.LabelFrame(win)
        frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

        header = ttk.Frame(frame)
        header.grid(row=0, column=0, columnspan=2, padx=5, pady=(5, 0), sticky="w")
        ttk.Label(header, text="Словарь терминов", font=("", 9, "bold")).pack(side=tk.LEFT)
        self._make_help_icon(header, _HELP_TEXTS["dictionary"]).pack(side=tk.LEFT, padx=(4, 0))

        # Модульные словари: каждый .txt файл в папке dictionaries/ - отдельный список.
        # Достаточно скопировать туда свой .txt файл - он сразу появится в списке ниже.
        self._active_dictionary_name = config_module.get_active_dictionary(self._config)
        self._dictionary_var = tk.StringVar(value=self._active_dictionary_name)
        self._dictionary_combo = ttk.Combobox(
            frame, textvariable=self._dictionary_var, state="readonly", width=30
        )
        self._dictionary_combo.grid(row=1, column=0, columnspan=2, padx=5, pady=(5, 0), sticky="ew")
        self._themed_comboboxes.append(self._dictionary_combo)
        self._refresh_dictionary_list()
        # Список файлов обновляем перед каждым открытием - чтобы новые .txt, подложенные
        # в папку вручную, сразу появлялись без перезапуска программы.
        self._dictionary_combo.bind("<Button-1>", lambda e: self._refresh_dictionary_list())
        self._dictionary_combo.bind("<<ComboboxSelected>>", lambda e: self._on_dictionary_selected())

        list_row = ttk.Frame(frame)
        list_row.grid(row=2, column=0, columnspan=2, padx=5, pady=5)

        self._terms_listbox = tk.Listbox(list_row, height=8, width=30)
        self._terms_listbox.pack(side=tk.LEFT, fill=tk.Y)
        scrollbar = ttk.Scrollbar(list_row, orient=tk.VERTICAL, command=self._terms_listbox.yview)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)
        self._terms_listbox.configure(yscrollcommand=scrollbar.set)
        self._load_terms_into_listbox()

        self._term_entry = ttk.Entry(frame, width=24)
        self._term_entry.grid(row=3, column=0, padx=5, pady=(0, 5))
        self._term_entry.bind("<Return>", lambda e: self._add_term())

        ttk.Button(frame, text="Добавить", command=self._add_term).grid(
            row=3, column=1, padx=5, pady=(0, 5), sticky="ew"
        )
        ttk.Button(frame, text="Удалить выбранное", command=self._remove_selected_term).grid(
            row=4, column=0, columnspan=2, padx=5, pady=(0, 5), sticky="ew"
        )

    def _refresh_dictionary_list(self) -> None:
        names = config_module.list_dictionaries()
        if not names:
            names = [self._active_dictionary_name]
        self._dictionary_combo["values"] = names

    def _on_dictionary_selected(self) -> None:
        self._active_dictionary_name = self._dictionary_var.get()
        self._config["active_dictionary"] = self._active_dictionary_name
        config_module.save_config(self._config)
        self._load_terms_into_listbox()

    def _load_terms_into_listbox(self) -> None:
        self._terms_listbox.delete(0, tk.END)
        for term in config_module.load_terms(self._active_dictionary_name):
            self._terms_listbox.insert(tk.END, term)

    def _add_term(self) -> None:
        term = self._term_entry.get().strip()
        if term:
            self._terms_listbox.insert(tk.END, term)
            self._term_entry.delete(0, tk.END)
            self._save_terms()

    def _remove_selected_term(self) -> None:
        selected = self._terms_listbox.curselection()
        if not selected:
            return
        for index in reversed(selected):
            self._terms_listbox.delete(index)
        self._save_terms()

    def _save_terms(self) -> None:
        config_module.save_terms(
            self._active_dictionary_name, list(self._terms_listbox.get(0, tk.END))
        )

    # --- остальные настройки ---

    def _build_options_section(self, win: tk.Toplevel) -> None:
        frame = ttk.LabelFrame(win, text="Настройки")
        frame.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")

        ttk.Label(frame, text="Микрофон:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self._mic_devices = _list_input_microphones()
        mic_names = ["Системный по умолчанию"] + [name for _, name in self._mic_devices]
        self._mic_var = tk.StringVar(value=self._current_mic_name(mic_names))
        self._mic_combo = ttk.Combobox(
            frame, textvariable=self._mic_var, values=mic_names, state="readonly", width=32
        )
        self._mic_combo.grid(row=0, column=1, padx=5, pady=5)
        self._mic_combo.bind("<<ComboboxSelected>>", lambda e: self._on_field_changed())
        self._themed_comboboxes.append(self._mic_combo)

        model_label_row = ttk.Frame(frame)
        model_label_row.grid(row=1, column=0, sticky="w", padx=5, pady=5)
        ttk.Label(model_label_row, text="Модель Whisper:").pack(side=tk.LEFT)
        self._make_help_icon(model_label_row, _HELP_TEXTS["model"]).pack(side=tk.LEFT, padx=(4, 0))
        self._model_var = tk.StringVar(value=self._config.get("model", "auto"))
        self._model_combo = ttk.Combobox(
            frame, textvariable=self._model_var, values=MODEL_OPTIONS, state="readonly", width=32
        )
        self._model_combo.grid(row=1, column=1, padx=5, pady=5)
        self._themed_comboboxes.append(self._model_combo)

        self._model_description_var = tk.StringVar(
            value=MODEL_DESCRIPTIONS.get(self._model_var.get(), "")
        )
        self._model_description_label = ttk.Label(
            frame, textvariable=self._model_description_var, foreground="#666666", wraplength=260
        )
        self._model_description_label.grid(row=2, column=0, columnspan=2, sticky="w", padx=5)

        def on_model_selected(event: tk.Event) -> None:
            self._model_description_var.set(MODEL_DESCRIPTIONS.get(self._model_var.get(), ""))
            self._on_field_changed()

        self._model_combo.bind("<<ComboboxSelected>>", on_model_selected)
        _attach_dropdown_hover(
            self._model_combo, MODEL_OPTIONS, MODEL_DESCRIPTIONS, self._model_description_var
        )

        ttk.Label(frame, text="Хоткей (push-to-talk):").grid(
            row=3, column=0, sticky="w", padx=5, pady=5
        )
        self._hotkey_var = tk.StringVar(value=self._config.get("hotkey", "ctrl_r"))
        self._hotkey_display_var = tk.StringVar(value=_hotkey_display_name(self._hotkey_var.get()))
        hotkey_row = ttk.Frame(frame)
        hotkey_row.grid(row=3, column=1, sticky="w", padx=5, pady=5)
        ttk.Entry(hotkey_row, textvariable=self._hotkey_display_var, width=24, state="readonly").pack(
            side=tk.LEFT
        )
        ttk.Button(hotkey_row, text="Записать...", command=self._capture_hotkey).pack(
            side=tk.LEFT, padx=(5, 0)
        )

        # Три взаимоисключающих режима доставки текста - радиокнопки, а не независимые
        # флажки, чтобы нельзя было включить сразу несколько.
        self._output_mode_var = tk.StringVar(value=self._config.get("output_mode", "clipboard"))

        clipboard_row = ttk.Frame(frame)
        clipboard_row.grid(row=4, column=0, columnspan=2, sticky="w", padx=5, pady=(5, 0))
        ttk.Radiobutton(
            clipboard_row,
            text="Только в буфер обмена",
            variable=self._output_mode_var,
            value="clipboard",
            command=self._on_field_changed,
        ).pack(side=tk.LEFT)
        self._make_help_icon(clipboard_row, _HELP_TEXTS["output_clipboard"]).pack(side=tk.LEFT, padx=(4, 0))

        paste_row = ttk.Frame(frame)
        paste_row.grid(row=5, column=0, columnspan=2, sticky="w", padx=5)
        ttk.Radiobutton(
            paste_row,
            text="Вставлять напрямую (Ctrl+V)",
            variable=self._output_mode_var,
            value="paste",
            command=self._on_field_changed,
        ).pack(side=tk.LEFT)
        self._make_help_icon(paste_row, _HELP_TEXTS["output_paste"]).pack(side=tk.LEFT, padx=(4, 0))

        type_row = ttk.Frame(frame)
        type_row.grid(row=6, column=0, columnspan=2, sticky="w", padx=5, pady=(0, 5))
        ttk.Radiobutton(
            type_row,
            text="Печатать напрямую (эмуляция нажатий клавиш)",
            variable=self._output_mode_var,
            value="type",
            command=self._on_field_changed,
        ).pack(side=tk.LEFT)
        self._make_help_icon(type_row, _HELP_TEXTS["output_type"]).pack(side=tk.LEFT, padx=(4, 0))

    def _current_mic_name(self, mic_names: list[str]) -> str:
        current_index = self._config.get("microphone_index")
        if current_index is None:
            return mic_names[0]
        for index, name in self._mic_devices:
            if index == current_index:
                return name
        return mic_names[0]

    def _capture_hotkey(self) -> None:
        assert self._toplevel is not None
        prompt = tk.Toplevel(self._toplevel)
        prompt.title("Назначение хоткея")
        prompt.resizable(False, False)
        ttk.Label(
            prompt,
            text="Нажмите клавишу или боковую кнопку мыши...",
            padding=20,
        ).pack()
        prompt.grab_set()
        prompt.focus_force()

        mouse_listener: pynput_mouse.Listener | None = None

        def finish(name: str) -> None:
            if mouse_listener is not None:
                mouse_listener.stop()
            self._hotkey_var.set(name)
            self._hotkey_display_var.set(_hotkey_display_name(name))
            if prompt.winfo_exists():
                prompt.destroy()
            self._on_field_changed()

        def on_key(event: tk.Event) -> None:
            finish(_keysym_to_pynput_name(event.keysym))

        def on_mouse_click(x: int, y: int, button: MouseButton, pressed: bool) -> None:
            if not pressed:
                return
            name = _mouse_button_to_name(button)
            if name is None:
                return
            prompt.after(0, lambda: finish(name))

        def on_close() -> None:
            if mouse_listener is not None:
                mouse_listener.stop()
            prompt.destroy()

        prompt.bind("<KeyPress>", on_key)
        prompt.protocol("WM_DELETE_WINDOW", on_close)
        mouse_listener = pynput_mouse.Listener(on_click=on_mouse_click)
        mouse_listener.start()

    # --- автосохранение ---

    def _on_field_changed(self) -> None:
        mic_name = self._mic_var.get()
        microphone_index = None
        for index, name in self._mic_devices:
            if name == mic_name:
                microphone_index = index
                break

        self._config["model"] = self._model_var.get()
        self._config["hotkey"] = self._hotkey_var.get()
        self._config["microphone_index"] = microphone_index
        self._config["output_mode"] = self._output_mode_var.get()
        config_module.save_config(self._config)

        if self._on_config_changed is not None:
            self._on_config_changed()
