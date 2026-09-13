#!/usr/bin/env python3
"""
MM2 FARM MANAGER GUI — CLOCKWORK SANCTUARY
Handcrafted Steampunk Rice GUI for MM2 Auto-Farm Bots.
Pure Python / Tkinter (Zero External GUI Dependencies — 100% Native on Windows & Linux).

Features:
- Master ON/OFF Switch for farming engine
- Real-time MM2 telemetry: Levels, Coins, Bot statuses, System RAM/CPU
- Connection Error / Kick Alert Box displaying Account & Password with 1-click clipboard copy
- Add Accounts modal, Ready Accounts (100 Lvl) viewer, Live Console Log drawer
- In-place widget updates & font handle caching to prevent Windows GDI handle leaks / blanking
- Strict Steampunk Rice aesthetics (Emerald #78c45d, Antique Gold #dec07e, Deep Obsidian #080f0a)
"""

import os
import sys
import json
import time
import subprocess
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox

# Обеспечиваем импорт farm_manager из локальной директории
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import farm_manager


# ==================== ПАЛИТРА STEAMPUNK NIRI RICE ====================
COLOR_BG = "#080f0a"             # Глубокий обсидиан
COLOR_SURFACE = "#142218"        # Панель механизма
COLOR_CARD = "#101b13"           # Карточка бота
COLOR_CARD_BORDER = "#2a4231"    # Граница карточки
COLOR_EMERALD = "#78c45d"        # Изумрудный акцент
COLOR_GOLD = "#dec07e"           # Античное золото / латунь
COLOR_BRIGHT_GOLD = "#fed594"    # Яркое золото
COLOR_DARK_GOLD = "#8e6c32"      # Тёмная медь / латунь
COLOR_TEXT_MAIN = "#dce7cf"      # Основной текст
COLOR_TEXT_MUTED = "#98bb6c"     # Приглушённый текст
COLOR_ERROR_BG = "#2b1414"       # Фон ошибки
COLOR_ERROR_BORDER = "#e06c75"   # Рамка ошибки
COLOR_ERROR_TEXT = "#ff7b72"     # Текст ошибки
COLOR_PASS_BG = "#1c0d0d"        # Бейдж пароля
COLOR_BTN_ON = "#2e6324"         # Кнопка Вкл
COLOR_BTN_OFF = "#2b231b"        # Кнопка Выкл


def copy_to_clipboard(root: tk.Tk, text: str):
    """Копирует текст в буфер обмена кроссплатформенно (Windows + Linux)."""
    try:
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
    except Exception:
        pass

    # Для Linux Wayland (wl-copy)
    if sys.platform != "win32":
        try:
            p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"))
        except Exception:
            pass


class SteampunkProgressBar(tk.Canvas):
    """Кастомный плавный прогресс-бар в стиле Clockwork Sanctuary."""
    def __init__(self, parent, height=8, fill_color=COLOR_EMERALD, bg=COLOR_CARD, **kwargs):
        super().__init__(parent, height=height, bg=bg, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER, **kwargs)
        self.height = height
        self.fill_color = fill_color
        self.fraction = 0.0
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        self._redraw(event.width)

    def set_fraction(self, frac: float):
        self.fraction = max(0.0, min(1.0, frac))
        self._redraw(self.winfo_width())

    def _redraw(self, w):
        self.delete("all")
        if w <= 1:
            w = 500
        fill_w = int(w * self.fraction)
        if fill_w > 0:
            self.create_rectangle(0, 0, fill_w, self.height, fill=self.fill_color, outline="")


class FarmManagerGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("MM2 Farm Manager — Clockwork Sanctuary")
        self.root.geometry("1100x780")
        self.root.minsize(960, 680)
        self.root.configure(bg=COLOR_BG)

        # Выбираем лучший доступный моноширинный и экранный шрифт
        self.font_family = "Nunito"
        self.font_mono = "Courier New" if sys.platform == "win32" else "monospace"
        available_families = [name.lower() for name in root.tk.call("font", "families")]
        for f in ["CaskaydiaCove Nerd Font", "JetBrainsMono Nerd Font", "FiraCode Nerd Font", "Consolas"]:
            if f.lower() in available_families:
                self.font_mono = f
                break

        # Кэшируем объекты шрифтов для предотвращения утечки дескрипторов GDI на Windows
        self.font_title = tkfont.Font(family=self.font_family, size=15, weight="bold")
        self.font_header = tkfont.Font(family=self.font_family, size=11, weight="bold")
        self.font_sub = tkfont.Font(family=self.font_family, size=9, weight="bold")
        self.font_metric_val = tkfont.Font(family=self.font_family, size=14, weight="bold")
        self.font_small = tkfont.Font(family=self.font_family, size=8)
        self.font_small_bold = tkfont.Font(family=self.font_family, size=8, weight="bold")
        self.font_mono_pass = tkfont.Font(family=self.font_mono, size=10, weight="bold")
        self.font_mono_log = tkfont.Font(family=self.font_mono, size=9)

        # Флаги работы фермы
        self.is_running = True
        self.farm_thread = None
        self.block_thread = None
        self.crash_thread = None
        self.funpay_thread = None

        # Кэш виджетов для in-place обновлений (никаких пересозданий каждую секунду!)
        self.bot_card_widgets = {}     # username -> dict of widgets
        self.error_card_widgets = {}   # username -> dict of widgets
        self.empty_bots_label = None

        # Запуск рабочих потоков фермы
        self.start_farm_threads()

        # Построение интерфейса
        self.build_ui()

        # Настройка перенаправления stdout в лог-окно
        self.setup_log_redirection()

        # Таймер обновления данных каждую секунду (1000 мс)
        self.root.after(1000, self.refresh_ui)

    def start_farm_threads(self):
        farm_manager.set_farm_enabled(True)
        if not self.farm_thread or not self.farm_thread.is_alive():
            self.farm_thread = threading.Thread(target=farm_manager.farm_worker, daemon=True)
            self.farm_thread.start()

        if not self.block_thread or not self.block_thread.is_alive():
            self.block_thread = threading.Thread(target=farm_manager.block_queue_worker, daemon=True)
            self.block_thread.start()

        if not self.crash_thread or not self.crash_thread.is_alive():
            self.crash_thread = threading.Thread(target=farm_manager.crash_dialog_watcher_worker, daemon=True)
            self.crash_thread.start()

        if not self.funpay_thread or not self.funpay_thread.is_alive():
            self.funpay_thread = threading.Thread(target=farm_manager.funpay_worker, daemon=True)
            self.funpay_thread.start()

    def build_ui(self):
        # 1. ШАПКА / УПРАВЛЕНИЕ
        self.create_header()

        # 2. ПАНЕЛЬ МЕТРИК (Steampunk Gauges)
        self.create_metrics_bar()

        # 3. КРИТИЧЕСКИЙ БЛОК: ОШИБКИ ПОДКЛЮЧЕНИЯ И ПАРОЛИ
        self.error_frame = tk.Frame(self.root, bg=COLOR_ERROR_BG, highlightthickness=2, highlightbackground=COLOR_ERROR_BORDER, padx=12, pady=10)
        self.error_header_label = tk.Label(self.error_frame, text="", bg=COLOR_ERROR_BG, fg=COLOR_ERROR_TEXT, font=self.font_header)
        self.error_header_label.pack(anchor="w", pady=(0, 6))
        self.error_cards_container = tk.Frame(self.error_frame, bg=COLOR_ERROR_BG)
        self.error_cards_container.pack(fill=tk.X)

        # 4. РАЗДЕЛ АКТИВНЫХ БОТОВ MM2
        self.bots_header = tk.Frame(self.root, bg=COLOR_BG)
        self.bots_header.pack(fill=tk.X, padx=16, pady=(10, 4))
        tk.Label(self.bots_header, text="⚙️ АКТИВНЫЕ БОТЫ MM2 В РАБОТЕ", bg=COLOR_BG, fg=COLOR_TEXT_MUTED, font=self.font_sub).pack(side=tk.LEFT)

        # Скроллируемая область ботов
        self.bots_container = tk.Frame(self.root, bg=COLOR_BG)
        self.bots_container.pack(fill=tk.BOTH, expand=True, padx=14, pady=4)

        self.canvas = tk.Canvas(self.bots_container, bg=COLOR_BG, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self.bots_container, orient="vertical", command=self.canvas.yview)
        self.scrollable_bots_frame = tk.Frame(self.canvas, bg=COLOR_BG)

        self.scrollable_bots_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_bots_frame, anchor="nw")
        self.canvas.configure(xscrollcommand=None, yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfig(self.canvas_window, width=event.width))
        self.canvas.bind_all("<MouseWheel>", lambda event: self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units"))

        # 5. КОНСОЛЬНЫЙ ЛОГ (Сворачиваемый)
        self.create_console_drawer()

        # 6. СТАТУС БАР
        self.create_footer()

    def create_header(self):
        hdr = tk.Frame(self.root, bg=COLOR_SURFACE, highlightthickness=2, highlightbackground=COLOR_GOLD, padx=16, pady=10)
        hdr.pack(fill=tk.X, padx=14, pady=(10, 6))

        # Левая часть
        left = tk.Frame(hdr, bg=COLOR_SURFACE)
        left.pack(side=tk.LEFT)
        tk.Label(left, text="⚙️ MM2 FARM MANAGER", bg=COLOR_SURFACE, fg=COLOR_BRIGHT_GOLD, font=self.font_title).pack(anchor="w")
        tk.Label(left, text="CLOCKWORK SANCTUARY • EMERALD V5.0", bg=COLOR_SURFACE, fg=COLOR_EMERALD, font=self.font_sub).pack(anchor="w")

        # Правая часть (кнопки)
        right = tk.Frame(hdr, bg=COLOR_SURFACE)
        right.pack(side=tk.RIGHT)

        btn_add = tk.Button(right, text="➕ Добавить Аккаунт", bg="#1c2d22", fg=COLOR_TEXT_MAIN, activebackground="#2a4534", activeforeground="#ffffff", font=self.font_sub, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_EMERALD, padx=10, pady=4, cursor="hand2", command=self.on_add_account)
        btn_add.pack(side=tk.LEFT, padx=6)

        btn_done = tk.Button(right, text="★ Готовые (100 Lvl)", bg="#2b231b", fg=COLOR_BRIGHT_GOLD, activebackground="#3d3226", activeforeground="#ffffff", font=self.font_sub, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_GOLD, padx=10, pady=4, cursor="hand2", command=self.on_view_done)
        btn_done.pack(side=tk.LEFT, padx=6)

        btn_ref = tk.Button(right, text="🔄", bg="#1c2d22", fg=COLOR_TEXT_MAIN, font=self.font_sub, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER, padx=8, pady=4, cursor="hand2", command=self.refresh_ui)
        btn_ref.pack(side=tk.LEFT, padx=6)

        # Главная кнопка Включения/Паузы
        self.master_btn = tk.Button(right, text="⚡ ФЕРМА ВКЛЮЧЕНА", bg=COLOR_BTN_ON, fg="#ffffff", activebackground="#3a782e", activeforeground="#ffffff", font=self.font_header, relief="flat", bd=2, highlightthickness=2, highlightbackground=COLOR_EMERALD, padx=14, pady=4, cursor="hand2", command=self.on_master_toggle)
        self.master_btn.pack(side=tk.LEFT, padx=8)

    def create_metrics_bar(self):
        m_frame = tk.Frame(self.root, bg=COLOR_BG)
        m_frame.pack(fill=tk.X, padx=14, pady=4)

        self.cards_data = [
            ("Статус системы", "АКТИВНА", "● Процессы запущены"),
            ("Боты в MM2", "0 / 50", "Очередь пула: 0"),
            ("Готово (100 Lvl)", "0 шт.", "Готовы в done.txt"),
            ("Всего монет MM2", "🪙 0", "Суммарный баланс"),
            ("ОЗУ / Память", "0%", "0 / 0 GB"),
        ]

        self.metric_widgets = []
        for i, (title, val, sub) in enumerate(self.cards_data):
            c = tk.Frame(m_frame, bg=COLOR_SURFACE, highlightthickness=1.5, highlightbackground=COLOR_GOLD, padx=12, pady=8)
            c.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)

            lbl_t = tk.Label(c, text=title, bg=COLOR_SURFACE, fg=COLOR_TEXT_MUTED, font=self.font_small_bold)
            lbl_t.pack(anchor="w")

            lbl_v = tk.Label(c, text=val, bg=COLOR_SURFACE, fg=COLOR_BRIGHT_GOLD, font=self.font_metric_val)
            lbl_v.pack(anchor="w")

            lbl_s = tk.Label(c, text=sub, bg=COLOR_SURFACE, fg=COLOR_EMERALD, font=self.font_small)
            lbl_s.pack(anchor="w")

            self.metric_widgets.append((lbl_v, lbl_s))

    def create_console_drawer(self):
        c_frame = tk.Frame(self.root, bg=COLOR_BG)
        c_frame.pack(fill=tk.X, padx=14, pady=(2, 4))

        self.show_console = tk.BooleanVar(value=False)
        self.console_btn = tk.Button(c_frame, text="▶ 📜 Журнал работы фермы (Live Console)", bg="#121e16", fg=COLOR_TEXT_MUTED, activebackground="#1a2d21", activeforeground=COLOR_TEXT_MAIN, font=self.font_small_bold, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER, anchor="w", padx=8, pady=3, cursor="hand2", command=self.toggle_console)
        self.console_btn.pack(fill=tk.X)

        self.console_box = tk.Frame(c_frame, bg=COLOR_BG)

        self.log_text = tk.Text(self.console_box, bg="#080f0a", fg="#98bb6c", font=self.font_mono_log, height=7, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER, wrap="char")
        self.log_scroll = tk.Scrollbar(self.console_box, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=self.log_scroll.set)

        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.insert(tk.END, "⚙️ Ферма готова к работе. Логи выводятся здесь в реальном времени.\n")

    def toggle_console(self):
        if self.show_console.get():
            self.console_box.pack_forget()
            self.console_btn.configure(text="▶ 📜 Журнал работы фермы (Live Console)")
            self.show_console.set(False)
        else:
            self.console_box.pack(fill=tk.X, pady=4)
            self.console_btn.configure(text="▼ 📜 Журнал работы фермы (Live Console)")
            self.show_console.set(True)

    def create_footer(self):
        ftr = tk.Frame(self.root, bg=COLOR_BG)
        ftr.pack(fill=tk.X, padx=16, pady=(2, 6))

        self.status_lbl = tk.Label(ftr, text="🌿 ym1co MM2 Farm Manager: Все системы функционируют штатно", bg=COLOR_BG, fg=COLOR_EMERALD, font=self.font_small)
        self.status_lbl.pack(side=tk.LEFT)

        folder_name = os.path.basename(os.getcwd())
        tk.Label(ftr, text=f"📁 Папка: {folder_name}", bg=COLOR_BG, fg=COLOR_TEXT_MUTED, font=self.font_small).pack(side=tk.RIGHT)

    def on_master_toggle(self):
        self.is_running = not self.is_running
        farm_manager.set_farm_enabled(self.is_running)

        if self.is_running:
            self.master_btn.configure(text="⚡ ФЕРМА ВКЛЮЧЕНА", bg=COLOR_BTN_ON, fg="#ffffff")
            self.metric_widgets[0][0].configure(text="АКТИВНА")
            self.metric_widgets[0][1].configure(text="● Процессы запущены")
            self.status_lbl.configure(text="⚡ Ферма запущена: аккаунты запускаются и контролируются в реальном времени.")
        else:
            self.master_btn.configure(text="⏸ ФЕРМА НА ПАУЗЕ", bg=COLOR_BTN_OFF, fg=COLOR_GOLD)
            self.metric_widgets[0][0].configure(text="ПАУЗА")
            self.metric_widgets[0][1].configure(text="○ Запуск новых окон приостановлен")
            self.status_lbl.configure(text="⏸ Ферма на паузе: новые окна не стартуют.")

        self.refresh_ui()

    def setup_log_redirection(self):
        gui = self
        class Redirector:
            def __init__(self, orig):
                self.orig = orig
            def write(self, s):
                if self.orig:
                    self.orig.write(s)
                clean = s.strip()
                if clean:
                    try:
                        gui.root.after(0, gui.append_log, clean)
                    except Exception:
                        pass
            def flush(self):
                if self.orig:
                    self.orig.flush()

        sys.stdout = Redirector(sys.stdout)

    def append_log(self, text: str):
        try:
            ts = time.strftime("%H:%M:%S")
            self.log_text.insert(tk.END, f"[{ts}] {text}\n")
            self.log_text.see(tk.END)
        except Exception:
            pass

    def refresh_ui(self):
        try:
            snap = farm_manager.get_farm_snapshot()

            # Обновление метрик
            self.metric_widgets[1][0].configure(text=f"{snap['active_bots_count']} / {snap['max_bots']}")
            self.metric_widgets[1][1].configure(text=f"Очередь пула: {snap['pool_count']}")
            self.metric_widgets[2][0].configure(text=f"{snap['done_count']} шт.")
            self.metric_widgets[3][0].configure(text=f"🪙 {snap['total_coins']:,}")
            self.metric_widgets[4][0].configure(text=f"{snap['ram_percent']}%")
            self.metric_widgets[4][1].configure(text=f"{snap['ram_used_gb']} / {snap['ram_total_gb']} GB")

            # Рендер ошибок с паролями (in-place)
            self.render_errors(snap.get("errors", []))

            # Рендер карточек активных ботов (in-place)
            self.render_bots(snap.get("bots", []), target_lvl=snap.get("target_level", 100), target_coins=snap.get("target_coins", 40000))

        except Exception as e:
            print(f"[GUI REFRESH ERROR]: {e}")
        finally:
            self.root.after(1000, self.refresh_ui)

    def dismiss_error(self, uname: str):
        """Полностью и навсегда удаляет проблемный аккаунт из пула фермы по клику на крестик."""
        farm_manager.delete_account_completely(uname)
        if uname in self.error_card_widgets:
            self.error_card_widgets[uname]["frame"].destroy()
            del self.error_card_widgets[uname]
        if not self.error_card_widgets:
            self.error_frame.pack_forget()
        else:
            self.error_header_label.config(text=f"⚠️ ОШИБКА ПОДКЛЮЧЕНИЯ / ТРЕБУЕТСЯ ВНИМАНИЕ ({len(self.error_card_widgets)} АКК.)")
        self.status_lbl.configure(text=f"✓ Аккаунт {uname} навсегда удален из пула фермы и исключен из RAM")

    def render_errors(self, errors):
        """Плавный рендер ошибок без удаления и пересоздания всех виджетов."""
        if not errors:
            if self.error_frame.winfo_ismapped():
                self.error_frame.pack_forget()
            for w in self.error_card_widgets.values():
                w["frame"].destroy()
            self.error_card_widgets.clear()
            return

        if not self.error_frame.winfo_ismapped():
            self.error_frame.pack(fill=tk.X, padx=14, pady=4, before=self.bots_header)

        self.error_header_label.config(text=f"⚠️ ОШИБКА ПОДКЛЮЧЕНИЯ / ТРЕБУЕТСЯ ВНИМАНИЕ ({len(errors)} АКК.)")

        current_unames = set()
        for err in errors:
            uname = err.get("username", "Unknown")
            pwd = err.get("password", "—")
            msg = err.get("error", "Кик / Ошибка связи с сервером")
            ts = err.get("timestamp", "")
            current_unames.add(uname)

            if uname in self.error_card_widgets:
                # Обновляем существующую карточку
                self.error_card_widgets[uname]["lbl_msg"].config(text=f"🔴 Причина: {msg}  [{ts}]")
            else:
                # Создаем карточку ошибки один раз
                card = tk.Frame(self.error_cards_container, bg="#180d0d", highlightthickness=1, highlightbackground=COLOR_GOLD, padx=10, pady=6)
                card.pack(fill=tk.X, pady=3)

                r1 = tk.Frame(card, bg="#180d0d")
                r1.pack(fill=tk.X)

                tk.Label(r1, text=f"👤 Аккаунт: {uname}", bg="#180d0d", fg=COLOR_TEXT_MAIN, font=self.font_header).pack(side=tk.LEFT, padx=(0, 10))

                tk.Label(r1, text="🔑 Пароль:", bg="#180d0d", fg=COLOR_GOLD, font=self.font_sub).pack(side=tk.LEFT)
                tk.Label(r1, text=f" {pwd} ", bg=COLOR_PASS_BG, fg=COLOR_BRIGHT_GOLD, font=self.font_mono_pass, relief="solid", bd=1).pack(side=tk.LEFT, padx=6)

                btn_dismiss = tk.Button(r1, text="✕", bg="#2a1818", fg=COLOR_TEXT_MAIN, relief="flat", bd=1, font=self.font_small_bold, cursor="hand2", command=lambda u=uname: self.dismiss_error(u))
                btn_dismiss.pack(side=tk.RIGHT, padx=4)

                btn_copy_both = tk.Button(r1, text="📋 Логин:Пароль", bg="#2a1818", fg=COLOR_TEXT_MAIN, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER, font=self.font_small_bold, cursor="hand2", command=lambda u=uname, p=pwd: (copy_to_clipboard(self.root, f"{u}:{p}"), self.status_lbl.configure(text=f"✓ Скопировано: {u}:{p}")))
                btn_copy_both.pack(side=tk.RIGHT, padx=4)

                btn_copy_p = tk.Button(r1, text="📋 Скопировать Пароль", bg="#3d2c18", fg=COLOR_BRIGHT_GOLD, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_GOLD, font=self.font_small_bold, cursor="hand2", command=lambda p=pwd: (copy_to_clipboard(self.root, p), self.status_lbl.configure(text="✓ Пароль скопирован в буфер обмена!")))
                btn_copy_p.pack(side=tk.RIGHT, padx=4)

                r2 = tk.Frame(card, bg="#180d0d")
                r2.pack(fill=tk.X, pady=(4, 0))
                lbl_msg = tk.Label(r2, text=f"🔴 Причина: {msg}  [{ts}]", bg="#180d0d", fg=COLOR_TEXT_MUTED, font=self.font_small)
                lbl_msg.pack(side=tk.LEFT)

                self.error_card_widgets[uname] = {
                    "frame": card,
                    "lbl_msg": lbl_msg,
                }

        # Удаляем устраненные ошибки
        for uname in list(self.error_card_widgets.keys()):
            if uname not in current_unames:
                self.error_card_widgets[uname]["frame"].destroy()
                del self.error_card_widgets[uname]

    def render_bots(self, bots, target_lvl=100, target_coins=40000):
        """Плавный in-place рендер ботов (без пересоздания виджетов и потери скролла)."""
        if not bots:
            if not self.empty_bots_label:
                self.empty_bots_label = tk.Label(self.scrollable_bots_frame, text="🌿 В данный момент нет активных ботов в игре.", bg=COLOR_BG, fg=COLOR_TEXT_MUTED, font=self.font_header, pady=30)
                self.empty_bots_label.pack(fill=tk.BOTH, expand=True)
            for b in self.bot_card_widgets.values():
                b["frame"].destroy()
            self.bot_card_widgets.clear()
            return
        else:
            if self.empty_bots_label:
                self.empty_bots_label.destroy()
                self.empty_bots_label = None

        current_bots = set()
        for bot in bots:
            uname = bot.get("username", "Unknown")
            pwd = bot.get("password", "")
            pid_val = bot.get("pid") or "—"
            up_s = bot.get("uptime_sec", 0)
            up_str = f"{up_s // 60}м {up_s % 60}с" if up_s > 0 else "0с"
            lvl = bot.get("level", 0)
            coins = bot.get("coins", 0)
            lvl_frac = min(1.0, max(0.0, lvl / float(target_lvl))) if target_lvl > 0 else 1.0
            coin_frac = min(1.0, max(0.0, coins / float(target_coins))) if target_coins > 0 else 1.0
            total_frac = min(lvl_frac, coin_frac) if target_coins > 0 else lvl_frac
            st = (bot.get("status") or "FARMING").upper()
            st_color = COLOR_ERROR_TEXT if ("KICK" in st or "ERROR" in st) else (COLOR_GOLD if ("WAIT" in st or "LOBBY" in st) else COLOR_EMERALD)

            current_bots.add(uname)

            if uname in self.bot_card_widgets:
                w = self.bot_card_widgets[uname]
                w["lbl_status"].config(text=f"  ● {st}  ", fg=st_color)
                w["lbl_pid_up"].config(text=f"PID: {pid_val}  •  Аптайм: {up_str}")
                w["lbl_lvl"].config(text=f"⭐ Прогресс Уровня MM2: {lvl} / {target_lvl}")
                w["lbl_pct"].config(text=f"{int(total_frac * 100)}%")
                w["bar"].set_fraction(total_frac)
                w["lbl_coins"].config(text=f"🪙 Баланс монет MM2: {coins:,} / {target_coins:,}")
            else:
                card = tk.Frame(self.scrollable_bots_frame, bg=COLOR_SURFACE, highlightthickness=1.5, highlightbackground=COLOR_CARD_BORDER, padx=14, pady=10)
                card.pack(fill=tk.X, pady=4)

                # 1. Заголовок карточки
                r1 = tk.Frame(card, bg=COLOR_SURFACE)
                r1.pack(fill=tk.X)

                tk.Label(r1, text=f"🤖 {uname}", bg=COLOR_SURFACE, fg=COLOR_TEXT_MAIN, font=self.font_header).pack(side=tk.LEFT)
                lbl_status = tk.Label(r1, text=f"  ● {st}  ", bg="#0d1810", fg=st_color, font=self.font_small_bold, relief="solid", bd=1)
                lbl_status.pack(side=tk.LEFT, padx=10)

                btn_p = tk.Button(r1, text="📋 Pass", bg="#1c2d22", fg=COLOR_GOLD, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER, font=self.font_small_bold, cursor="hand2", command=lambda p=pwd: (copy_to_clipboard(self.root, p), self.status_lbl.configure(text=f"✓ Пароль скопирован: {p}")))
                btn_p.pack(side=tk.RIGHT, padx=4)

                lbl_pid_up = tk.Label(r1, text=f"PID: {pid_val}  •  Аптайм: {up_str}", bg=COLOR_SURFACE, fg=COLOR_TEXT_MUTED, font=self.font_sub)
                lbl_pid_up.pack(side=tk.RIGHT, padx=10)

                # 2. Прогресс УРОВНЯ и МОНЕТ MM2
                r2 = tk.Frame(card, bg=COLOR_SURFACE)
                r2.pack(fill=tk.X, pady=(6, 2))
                lbl_lvl = tk.Label(r2, text=f"⭐ Прогресс Уровня MM2: {lvl} / {target_lvl}", bg=COLOR_SURFACE, fg=COLOR_TEXT_MAIN, font=self.font_sub)
                lbl_lvl.pack(side=tk.LEFT)
                lbl_pct = tk.Label(r2, text=f"{int(total_frac * 100)}%", bg=COLOR_SURFACE, fg=COLOR_TEXT_MUTED, font=self.font_sub)
                lbl_pct.pack(side=tk.RIGHT)

                bar = SteampunkProgressBar(card, height=8, fill_color=COLOR_EMERALD, bg=COLOR_CARD)
                bar.pack(fill=tk.X, pady=2)
                bar.set_fraction(total_frac)

                # 3. Баланс монет MM2 и быстрое копирование
                r3 = tk.Frame(card, bg=COLOR_SURFACE)
                r3.pack(fill=tk.X, pady=(6, 0))

                lbl_coins = tk.Label(r3, text=f"🪙 Баланс монет MM2: {coins:,} / {target_coins:,}", bg=COLOR_SURFACE, fg=COLOR_BRIGHT_GOLD, font=self.font_header)
                lbl_coins.pack(side=tk.LEFT)

                btn_copy_both = tk.Button(r3, text="📋 Логин:Пароль", bg="#1c2d22", fg=COLOR_TEXT_MAIN, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER, font=self.font_small_bold, cursor="hand2", command=lambda u=uname, p=pwd: (copy_to_clipboard(self.root, f"{u}:{p}"), self.status_lbl.configure(text=f"✓ Скопировано: {u}:{p}")))
                btn_copy_both.pack(side=tk.RIGHT)

                self.bot_card_widgets[uname] = {
                    "frame": card,
                    "lbl_status": lbl_status,
                    "lbl_pid_up": lbl_pid_up,
                    "lbl_lvl": lbl_lvl,
                    "lbl_pct": lbl_pct,
                    "bar": bar,
                    "lbl_coins": lbl_coins,
                }

        # Удаляем карточки отключенных ботов
        for uname in list(self.bot_card_widgets.keys()):
            if uname not in current_bots:
                self.bot_card_widgets[uname]["frame"].destroy()
                del self.bot_card_widgets[uname]

    def on_add_account(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Добавить аккаунт в пул")
        dialog.geometry("520x260")
        dialog.configure(bg=COLOR_SURFACE)
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="➕ Добавление нового аккаунта в пул", bg=COLOR_SURFACE, fg=COLOR_BRIGHT_GOLD, font=self.font_header).pack(pady=(16, 8))
        tk.Label(dialog, text="Формат: логин:пароль:куки_.ROBLOSECURITY\nили: логин:пароль", bg=COLOR_SURFACE, fg=COLOR_TEXT_MUTED, font=self.font_small).pack(pady=4)

        entry = tk.Entry(dialog, bg="#080f0a", fg=COLOR_TEXT_MAIN, font=self.font_mono_log, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER)
        entry.pack(fill=tk.X, padx=20, pady=12)
        entry.focus_set()

        btn_box = tk.Frame(dialog, bg=COLOR_SURFACE)
        btn_box.pack(fill=tk.X, padx=20, pady=10)

        def save():
            val = entry.get().strip()
            if val:
                with open(farm_manager.POOL_ACCOUNTS_FILE, "a", encoding="utf-8") as f:
                    f.write(val + "\n")
                self.status_lbl.configure(text=f"✓ Аккаунт успешно добавлен в {farm_manager.POOL_ACCOUNTS_FILE}")
                self.refresh_ui()
                dialog.destroy()

        tk.Button(btn_box, text="Отмена", bg="#1c2d22", fg=COLOR_TEXT_MAIN, font=self.font_sub, relief="flat", padx=10, pady=4, command=dialog.destroy).pack(side=tk.RIGHT, padx=6)
        tk.Button(btn_box, text="Добавить в пул", bg="#3d2c18", fg=COLOR_BRIGHT_GOLD, font=self.font_sub, relief="flat", highlightthickness=1, highlightbackground=COLOR_GOLD, padx=12, pady=4, command=save).pack(side=tk.RIGHT, padx=6)

    def on_view_done(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Готовые аккаунты к продаже (100 Lvl)")
        dialog.geometry("620x400")
        dialog.configure(bg=COLOR_SURFACE)
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="★ Аккаунты в done.txt (Формат FunPay)", bg=COLOR_SURFACE, fg=COLOR_BRIGHT_GOLD, font=self.font_title).pack(pady=10)

        content = ""
        if os.path.exists(farm_manager.DONE_FILE):
            try:
                with open(farm_manager.DONE_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
            except Exception:
                pass

        txt = tk.Text(dialog, bg="#080f0a", fg=COLOR_TEXT_MUTED, font=self.font_mono_log, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER)
        txt.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)
        txt.insert(tk.END, content if content else "Пока нет готовых аккаунтов (все аккаунты ещё фармят).")
        txt.configure(state="disabled")

        b_box = tk.Frame(dialog, bg=COLOR_SURFACE)
        b_box.pack(fill=tk.X, padx=16, pady=10)

        if content:
            tk.Button(b_box, text="📋 Скопировать всё", bg="#3d2c18", fg=COLOR_BRIGHT_GOLD, font=self.font_sub, relief="flat", highlightthickness=1, highlightbackground=COLOR_GOLD, padx=10, pady=4, command=lambda: (copy_to_clipboard(self.root, content), self.status_lbl.configure(text="✓ Все готовые аккаунты скопированы!"))).pack(side=tk.LEFT)

        tk.Button(b_box, text="Закрыть", bg="#1c2d22", fg=COLOR_TEXT_MAIN, font=self.font_sub, relief="flat", padx=10, pady=4, command=dialog.destroy).pack(side=tk.RIGHT)


if __name__ == "__main__":
    root = tk.Tk()
    app = FarmManagerGUI(root)
    root.mainloop()
