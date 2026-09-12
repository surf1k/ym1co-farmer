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
- Strict Steampunk Rice aesthetics (Emerald #78c45d, Antique Gold #dec07e, Deep Obsidian #080f0a)
"""

import os
import sys
import json
import time
import subprocess
import threading
import tkinter as tk
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
    def __init__(self, parent, width=600, height=12, fill_color=COLOR_EMERALD, bg=COLOR_CARD, **kwargs):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER, **kwargs)
        self.width = width
        self.height = height
        self.fill_color = fill_color
        self.fraction = 0.0

    def set_fraction(self, frac: float):
        self.fraction = max(0.0, min(1.0, frac))
        self.delete("all")
        fill_w = int(self.width * self.fraction)
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
        for f in ["CaskaydiaCove Nerd Font", "JetBrainsMono Nerd Font", "FiraCode Nerd Font", "Consolas"]:
            if f.lower() in [name.lower() for name in root.tk.call("font", "families")]:
                self.font_mono = f
                break

        # Флаги работы фермы
        self.is_running = True
        self.farm_thread = None
        self.block_thread = None
        self.crash_thread = None
        self.funpay_thread = None

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

        # 4. РАЗДЕЛ АКТИВНЫХ БОТОВ MM2
        bots_header = tk.Frame(self.root, bg=COLOR_BG)
        bots_header.pack(fill=tk.X, padx=16, pady=(10, 4))
        tk.Label(bots_header, text="⚙️ АКТИВНЫЕ БОТЫ MM2 В РАБОТЕ", bg=COLOR_BG, fg=COLOR_TEXT_MUTED, font=(self.font_family, 10, "bold")).pack(side=tk.LEFT)

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
        tk.Label(left, text="⚙️ MM2 FARM MANAGER", bg=COLOR_SURFACE, fg=COLOR_BRIGHT_GOLD, font=(self.font_family, 15, "bold")).pack(anchor="w")
        tk.Label(left, text="CLOCKWORK SANCTUARY • EMERALD V5.0", bg=COLOR_SURFACE, fg=COLOR_EMERALD, font=(self.font_family, 9, "bold")).pack(anchor="w")

        # Правая часть (кнопки)
        right = tk.Frame(hdr, bg=COLOR_SURFACE)
        right.pack(side=tk.RIGHT)

        btn_add = tk.Button(right, text="➕ Добавить Аккаунт", bg="#1c2d22", fg=COLOR_TEXT_MAIN, activebackground="#2a4534", activeforeground="#ffffff", font=(self.font_family, 9, "bold"), relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_EMERALD, padx=10, pady=4, cursor="hand2", command=self.on_add_account)
        btn_add.pack(side=tk.LEFT, padx=6)

        btn_done = tk.Button(right, text="★ Готовые (100 Lvl)", bg="#2b231b", fg=COLOR_BRIGHT_GOLD, activebackground="#3d3226", activeforeground="#ffffff", font=(self.font_family, 9, "bold"), relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_GOLD, padx=10, pady=4, cursor="hand2", command=self.on_view_done)
        btn_done.pack(side=tk.LEFT, padx=6)

        btn_ref = tk.Button(right, text="🔄", bg="#1c2d22", fg=COLOR_TEXT_MAIN, font=(self.font_family, 9, "bold"), relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER, padx=8, pady=4, cursor="hand2", command=self.refresh_ui)
        btn_ref.pack(side=tk.LEFT, padx=6)

        # Главная кнопка Включения/Паузы
        self.master_btn = tk.Button(right, text="⚡ ФЕРМА ВКЛЮЧЕНА", bg=COLOR_BTN_ON, fg="#ffffff", activebackground="#3a782e", activeforeground="#ffffff", font=(self.font_family, 10, "bold"), relief="flat", bd=2, highlightthickness=2, highlightbackground=COLOR_EMERALD, padx=14, pady=4, cursor="hand2", command=self.on_master_toggle)
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

            lbl_t = tk.Label(c, text=title, bg=COLOR_SURFACE, fg=COLOR_TEXT_MUTED, font=(self.font_family, 8, "bold"))
            lbl_t.pack(anchor="w")

            lbl_v = tk.Label(c, text=val, bg=COLOR_SURFACE, fg=COLOR_BRIGHT_GOLD, font=(self.font_family, 14, "bold"))
            lbl_v.pack(anchor="w")

            lbl_s = tk.Label(c, text=sub, bg=COLOR_SURFACE, fg=COLOR_EMERALD, font=(self.font_family, 8))
            lbl_s.pack(anchor="w")

            self.metric_widgets.append((lbl_v, lbl_s))

    def create_console_drawer(self):
        c_frame = tk.Frame(self.root, bg=COLOR_BG)
        c_frame.pack(fill=tk.X, padx=14, pady=(2, 4))

        self.show_console = tk.BooleanVar(value=False)
        self.console_btn = tk.Button(c_frame, text="▶ 📜 Журнал работы фермы (Live Console)", bg="#121e16", fg=COLOR_TEXT_MUTED, activebackground="#1a2d21", activeforeground=COLOR_TEXT_MAIN, font=(self.font_family, 8, "bold"), relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER, anchor="w", padx=8, pady=3, cursor="hand2", command=self.toggle_console)
        self.console_btn.pack(fill=tk.X)

        self.console_box = tk.Frame(c_frame, bg=COLOR_BG)

        self.log_text = tk.Text(self.console_box, bg="#080f0a", fg="#98bb6c", font=(self.font_mono, 9), height=7, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER, wrap="char")
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

        self.status_lbl = tk.Label(ftr, text="🌿 ym1co MM2 Farm Manager: Все системы функционируют штатно", bg=COLOR_BG, fg=COLOR_EMERALD, font=(self.font_family, 8))
        self.status_lbl.pack(side=tk.LEFT)

        folder_name = os.path.basename(os.getcwd())
        tk.Label(ftr, text=f"📁 Папка: {folder_name}", bg=COLOR_BG, fg=COLOR_TEXT_MUTED, font=(self.font_family, 8)).pack(side=tk.RIGHT)

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

            # Рендер ошибок с паролями
            self.render_errors(snap.get("errors", []))

            # Рендер карточек активных ботов
            self.render_bots(snap.get("bots", []))

        except Exception as e:
            pass

        self.root.after(1000, self.refresh_ui)

    def render_errors(self, errors):
        for widget in self.error_frame.winfo_children():
            widget.destroy()

        if not errors:
            self.error_frame.pack_forget()
            return

        self.error_frame.pack(fill=tk.X, padx=14, pady=4, before=self.bots_container)

        hdr = tk.Frame(self.error_frame, bg=COLOR_ERROR_BG)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text=f"⚠️ ОШИБКА ПОДКЛЮЧЕНИЯ / ТРЕБУЕТСЯ ВНИМАНИЕ ({len(errors)} АКК.)", bg=COLOR_ERROR_BG, fg=COLOR_ERROR_TEXT, font=(self.font_family, 11, "bold")).pack(side=tk.LEFT)

        for err in errors:
            uname = err.get("username", "Unknown")
            pwd = err.get("password", "—")
            msg = err.get("error", "Кик / Ошибка связи с сервером")
            ts = err.get("timestamp", "")

            card = tk.Frame(self.error_frame, bg="#180d0d", highlightthickness=1, highlightbackground=COLOR_GOLD, padx=10, pady=6)
            card.pack(fill=tk.X, pady=4)

            # Верхняя строка: Ник и Пароль
            r1 = tk.Frame(card, bg="#180d0d")
            r1.pack(fill=tk.X)

            tk.Label(r1, text=f"👤 Аккаунт: {uname}", bg="#180d0d", fg=COLOR_TEXT_MAIN, font=(self.font_family, 10, "bold")).pack(side=tk.LEFT, padx=(0, 10))

            tk.Label(r1, text="🔑 Пароль:", bg="#180d0d", fg=COLOR_GOLD, font=(self.font_family, 10, "bold")).pack(side=tk.LEFT)
            tk.Label(r1, text=f" {pwd} ", bg=COLOR_PASS_BG, fg=COLOR_BRIGHT_GOLD, font=(self.font_mono, 10, "bold"), relief="solid", bd=1).pack(side=tk.LEFT, padx=6)

            # Кнопки действий
            btn_dismiss = tk.Button(r1, text="✕", bg="#2a1818", fg=COLOR_TEXT_MAIN, relief="flat", bd=1, font=(self.font_family, 8, "bold"), cursor="hand2", command=lambda u=uname: (farm_manager.clear_error(u), self.refresh_ui()))
            btn_dismiss.pack(side=tk.RIGHT, padx=4)

            btn_copy_both = tk.Button(r1, text="📋 Логин:Пароль", bg="#2a1818", fg=COLOR_TEXT_MAIN, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER, font=(self.font_family, 8, "bold"), cursor="hand2", command=lambda u=uname, p=pwd: (copy_to_clipboard(self.root, f"{u}:{p}"), self.status_lbl.configure(text=f"✓ Скопировано: {u}:{p}")))
            btn_copy_both.pack(side=tk.RIGHT, padx=4)

            btn_copy_p = tk.Button(r1, text="📋 Скопировать Пароль", bg="#3d2c18", fg=COLOR_BRIGHT_GOLD, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_GOLD, font=(self.font_family, 8, "bold"), cursor="hand2", command=lambda p=pwd: (copy_to_clipboard(self.root, p), self.status_lbl.configure(text="✓ Пароль скопирован в буфер обмена!")))
            btn_copy_p.pack(side=tk.RIGHT, padx=4)

            # Нижняя строка: Причина
            r2 = tk.Frame(card, bg="#180d0d")
            r2.pack(fill=tk.X, pady=(4, 0))
            tk.Label(r2, text=f"🔴 Причина: {msg}  [{ts}]", bg="#180d0d", fg=COLOR_TEXT_MUTED, font=(self.font_family, 8)).pack(side=tk.LEFT)

    def render_bots(self, bots):
        for widget in self.scrollable_bots_frame.winfo_children():
            widget.destroy()

        if not bots:
            empty = tk.Frame(self.scrollable_bots_frame, bg=COLOR_BG, pady=30)
            empty.pack(fill=tk.BOTH, expand=True)
            tk.Label(empty, text="🌿 В данный момент нет активных ботов в игре.", bg=COLOR_BG, fg=COLOR_TEXT_MUTED, font=(self.font_family, 11)).pack()
            return

        for bot in bots:
            card = tk.Frame(self.scrollable_bots_frame, bg=COLOR_SURFACE, highlightthickness=1.5, highlightbackground=COLOR_CARD_BORDER, padx=14, pady=10)
            card.pack(fill=tk.X, pady=4)

            # 1. Заголовок карточки
            r1 = tk.Frame(card, bg=COLOR_SURFACE)
            r1.pack(fill=tk.X)

            tk.Label(r1, text=f"🤖 {bot['username']}", bg=COLOR_SURFACE, fg=COLOR_TEXT_MAIN, font=(self.font_family, 11, "bold")).pack(side=tk.LEFT)

            st = (bot.get("status") or "FARMING").upper()
            st_color = COLOR_ERROR_TEXT if ("KICK" in st or "ERROR" in st) else (COLOR_GOLD if ("WAIT" in st or "LOBBY" in st) else COLOR_EMERALD)
            tk.Label(r1, text=f"  ● {st}  ", bg="#0d1810", fg=st_color, font=(self.font_family, 8, "bold"), relief="solid", bd=1).pack(side=tk.LEFT, padx=10)

            pwd = bot.get("password", "")
            btn_p = tk.Button(r1, text="📋 Pass", bg="#1c2d22", fg=COLOR_GOLD, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER, font=(self.font_family, 8, "bold"), cursor="hand2", command=lambda p=pwd: (copy_to_clipboard(self.root, p), self.status_lbl.configure(text=f"✓ Пароль скопирован: {p}")))
            btn_p.pack(side=tk.RIGHT, padx=4)

            pid_val = bot.get("pid") or "—"
            up_s = bot.get("uptime_sec", 0)
            up_str = f"{up_s // 60}м {up_s % 60}с" if up_s > 0 else "0с"
            tk.Label(r1, text=f"PID: {pid_val}  •  Аптайм: {up_str}", bg=COLOR_SURFACE, fg=COLOR_TEXT_MUTED, font=(self.font_family, 9)).pack(side=tk.RIGHT, padx=10)

            # 2. Прогресс УРОВНЯ MM2 (без мешка в GUI!)
            lvl = bot.get("level", 0)
            lvl_frac = min(1.0, max(0.0, lvl / 100.0))

            r2 = tk.Frame(card, bg=COLOR_SURFACE)
            r2.pack(fill=tk.X, pady=(6, 2))
            tk.Label(r2, text=f"⭐ Прогресс Уровня MM2: {lvl} / 100", bg=COLOR_SURFACE, fg=COLOR_TEXT_MAIN, font=(self.font_family, 9, "bold")).pack(side=tk.LEFT)
            tk.Label(r2, text=f"{int(lvl_frac * 100)}%", bg=COLOR_SURFACE, fg=COLOR_TEXT_MUTED, font=(self.font_family, 9)).pack(side=tk.RIGHT)

            bar = SteampunkProgressBar(card, width=700, height=8, fill_color=COLOR_EMERALD, bg=COLOR_SURFACE)
            bar.pack(fill=tk.X, pady=2)
            bar.set_fraction(lvl_frac)

            # 3. Баланс монет MM2 и быстрое копирование
            coins = bot.get("coins", 0)
            r3 = tk.Frame(card, bg=COLOR_SURFACE)
            r3.pack(fill=tk.X, pady=(6, 0))

            tk.Label(r3, text=f"🪙 Баланс монет MM2: {coins:,}", bg=COLOR_SURFACE, fg=COLOR_BRIGHT_GOLD, font=(self.font_family, 10, "bold")).pack(side=tk.LEFT)

            uname = bot.get("username", "")
            btn_copy_both = tk.Button(r3, text="📋 Логин:Пароль", bg="#1c2d22", fg=COLOR_TEXT_MAIN, relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER, font=(self.font_family, 8, "bold"), cursor="hand2", command=lambda u=uname, p=pwd: (copy_to_clipboard(self.root, f"{u}:{p}"), self.status_lbl.configure(text=f"✓ Скопировано: {u}:{p}")))
            btn_copy_both.pack(side=tk.RIGHT)

    def on_add_account(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Добавить аккаунт в пул")
        dialog.geometry("520x260")
        dialog.configure(bg=COLOR_SURFACE)
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Введите аккаунт в формате:\nлогин:пароль:куки или логин:пароль", bg=COLOR_SURFACE, fg=COLOR_TEXT_MAIN, font=(self.font_family, 10, "bold")).pack(pady=(20, 10))

        entry = tk.Entry(dialog, bg="#0d1810", fg=COLOR_BRIGHT_GOLD, font=(self.font_mono, 9), relief="solid", bd=1, highlightthickness=1, highlightbackground=COLOR_GOLD)
        entry.pack(fill=tk.X, padx=20, pady=10)

        btn_box = tk.Frame(dialog, bg=COLOR_SURFACE)
        btn_box.pack(fill=tk.X, padx=20, pady=15)

        def save():
            val = entry.get().strip()
            if val:
                with open(farm_manager.POOL_ACCOUNTS_FILE, "a", encoding="utf-8") as f:
                    f.write(val + "\n")
                self.status_lbl.configure(text=f"✓ Аккаунт успешно добавлен в {farm_manager.POOL_ACCOUNTS_FILE}")
                self.refresh_ui()
                dialog.destroy()

        tk.Button(btn_box, text="Отмена", bg="#1c2d22", fg=COLOR_TEXT_MAIN, font=(self.font_family, 9, "bold"), relief="flat", padx=10, pady=4, command=dialog.destroy).pack(side=tk.RIGHT, padx=6)
        tk.Button(btn_box, text="Добавить в пул", bg="#3d2c18", fg=COLOR_BRIGHT_GOLD, font=(self.font_family, 9, "bold"), relief="flat", highlightthickness=1, highlightbackground=COLOR_GOLD, padx=12, pady=4, command=save).pack(side=tk.RIGHT, padx=6)

    def on_view_done(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Готовые аккаунты к продаже (100 Lvl)")
        dialog.geometry("620x400")
        dialog.configure(bg=COLOR_SURFACE)
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="★ Аккаунты в done.txt (Формат FunPay)", bg=COLOR_SURFACE, fg=COLOR_BRIGHT_GOLD, font=(self.font_family, 12, "bold")).pack(pady=10)

        content = ""
        if os.path.exists(farm_manager.DONE_FILE):
            try:
                with open(farm_manager.DONE_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
            except Exception:
                pass

        txt = tk.Text(dialog, bg="#080f0a", fg=COLOR_TEXT_MUTED, font=(self.font_mono, 9), relief="flat", bd=1, highlightthickness=1, highlightbackground=COLOR_CARD_BORDER)
        txt.pack(fill=tk.BOTH, expand=True, padx=16, pady=6)
        txt.insert(tk.END, content if content else "Пока нет готовых аккаунтов (все аккаунты ещё фармят).")
        txt.configure(state="disabled")

        b_box = tk.Frame(dialog, bg=COLOR_SURFACE)
        b_box.pack(fill=tk.X, padx=16, pady=10)

        if content:
            tk.Button(b_box, text="📋 Скопировать всё", bg="#3d2c18", fg=COLOR_BRIGHT_GOLD, font=(self.font_family, 9, "bold"), relief="flat", highlightthickness=1, highlightbackground=COLOR_GOLD, padx=10, pady=4, command=lambda: (copy_to_clipboard(self.root, content), self.status_lbl.configure(text="✓ Все готовые аккаунты скопированы!"))).pack(side=tk.LEFT)

        tk.Button(b_box, text="Закрыть", bg="#1c2d22", fg=COLOR_TEXT_MAIN, font=(self.font_family, 9, "bold"), relief="flat", padx=10, pady=4, command=dialog.destroy).pack(side=tk.RIGHT)


if __name__ == "__main__":
    root = tk.Tk()
    app = FarmManagerGUI(root)
    root.mainloop()
