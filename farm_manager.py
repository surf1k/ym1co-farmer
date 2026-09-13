import ctypes
import glob
import json
import os
import random
import re
import string
import subprocess
import sys
import threading
import time

import psutil
import requests
from html.parser import HTMLParser
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

CONFIG_FILE = "config.json"
ACCOUNTS_FILE = "accounts.txt"
POOL_ACCOUNTS_FILE = "accounts_pool.txt"
ACTIVE_POOL_FILE = "active_pool.json"
DONE_FILE = "done.txt"
BOT_IDS_FILE = "bot_ids.json"
ERRORS_FILE = "errors.json"
IGNORED_ACCOUNTS_FILE = "ignored_accounts.json"

file_lock = threading.Lock()
farm_enabled = threading.Event()
farm_enabled.set()


def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"[-] Файл {CONFIG_FILE} не найден!")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


CFG = load_config()


def random_string(length=10):
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def load_json(file_path, default):
    with file_lock:
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return default
        return default


def save_json(file_path, data):
    with file_lock:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)


def set_farm_enabled(enabled: bool):
    if enabled:
        farm_enabled.set()
    else:
        farm_enabled.clear()


def is_farm_enabled() -> bool:
    return farm_enabled.is_set()


# Трекинг количества последовательных ошибок подряд для каждого аккаунта
account_fail_counts = {}


def get_failure_count(username: str) -> int:
    if not username:
        return 0
    return account_fail_counts.get(username.strip().lower(), 0)


def reset_failure_count(username: str):
    """Сбрасывает счетчик последовательных ошибок при успешном подключении и игре."""
    if not username:
        return
    u_lower = username.strip().lower()
    if account_fail_counts.get(u_lower, 0) > 0:
        account_fail_counts[u_lower] = 0
    clear_error(username)


def record_failure(username: str, password: str, error_text: str, user_id=None, threshold=5):
    """Учитывает ошибку аккаунта.
    В errors.json (и в GUI) аккаунт попадает ТОЛЬКО если сбой повторился более 5 раз подряд (fails > threshold).
    """
    if not username:
        return
    u_lower = username.strip().lower()
    current_fails = account_fail_counts.get(u_lower, 0) + 1
    account_fail_counts[u_lower] = current_fails

    print(
        f"[FARM] [!] Сбой у бота {username} (Попытка {current_fails}/{threshold}): {error_text}"
    )

    if current_fails > threshold:
        print(
            f"[FARM] [🚨 ПОРОГ ПРЕВЫШЕН] Аккаунт {username} упал более {threshold} раз подряд ({current_fails})! Помещаем в errors.json..."
        )
        record_error(username, password, f"[{current_fails} сбоев подряд] {error_text}", user_id)


def record_error(username, password, error_text, user_id=None):
    """Записывает ошибку бота, сохраняя логин и пароль для немедленного отображения в GUI."""
    try:
        errors = load_json(ERRORS_FILE, [])
        errors = [e for e in errors if e.get("username") != username]
        errors.insert(
            0,
            {
                "username": username,
                "password": password or "",
                "error": str(error_text),
                "userId": user_id,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "time": time.time(),
            },
        )
        save_json(ERRORS_FILE, errors[:50])
    except Exception as e:
        print(f"[ERROR_RECORDER] Ошибка записи в {ERRORS_FILE}: {e}")


def clear_error(username):
    """Удаляет ошибку аккаунта из списка активных ошибок при успешной работе."""
    try:
        errors = load_json(ERRORS_FILE, [])
        errors = [e for e in errors if e.get("username") != username]
        save_json(ERRORS_FILE, errors)
        if username:
            account_fail_counts.pop(username.strip().lower(), None)
    except Exception:
        pass


def delete_account_completely(username: str):
    """Полностью и навсегда удаляет аккаунт из фермы:
    1. Добавляет имя в ignored_accounts.json (чтобы он больше НИКОГДА не импортировался из RAM / AccountData.json).
    2. Удаляет из errors.json.
    3. Вырезает строку из accounts_pool.txt.
    4. Вырезает строку из accounts.txt.
    5. Завершает процесс игры (если бот запущен) и удаляет из active_pool.json.
    """
    if not username:
        return
    u_lower = username.strip().lower()
    print(f"[ACCOUNT_DELETE] Навсегда удаляем аккаунт {username} из фермы...")

    # 1. Заносим в ignored_accounts.json
    try:
        ignored = load_json(IGNORED_ACCOUNTS_FILE, [])
        if u_lower not in [str(x).lower() for x in ignored]:
            ignored.append(username)
            save_json(IGNORED_ACCOUNTS_FILE, ignored)
    except Exception as e:
        print(f"[ACCOUNT_DELETE] Ошибка записи в {IGNORED_ACCOUNTS_FILE}: {e}")

    # 2. Удаляем из errors.json
    clear_error(username)

    # 3. Вырезаем из accounts_pool.txt
    if os.path.exists(POOL_ACCOUNTS_FILE):
        try:
            with file_lock:
                with open(POOL_ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    lines = [l for l in f if l.strip()]
                new_lines = []
                for l in lines:
                    p = parse_account_line(l)
                    if p and p.get("username", "").strip().lower() == u_lower:
                        continue
                    new_lines.append(l)
                with open(POOL_ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                    for l in new_lines:
                        f.write(l.strip() + "\n")
        except Exception as e:
            print(f"[ACCOUNT_DELETE] Ошибка очистки {POOL_ACCOUNTS_FILE}: {e}")

    # 4. Вырезаем из accounts.txt
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with file_lock:
                with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    lines = [l for l in f if l.strip()]
                new_lines = []
                for l in lines:
                    p = parse_account_line(l)
                    if p and p.get("username", "").strip().lower() == u_lower:
                        continue
                    new_lines.append(l)
                with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                    for l in new_lines:
                        f.write(l.strip() + "\n")
        except Exception as e:
            print(f"[ACCOUNT_DELETE] Ошибка очистки {ACCOUNTS_FILE}: {e}")

    # 5. Завершаем активный процесс если есть
    try:
        active_pool = load_json(ACTIVE_POOL_FILE, [])
        for b in active_pool:
            if b.get("username", "").strip().lower() == u_lower:
                pid = b.get("pid")
                if pid:
                    kill_pid(pid)
        active_pool = [b for b in active_pool if b.get("username", "").strip().lower() != u_lower]
        save_json(ACTIVE_POOL_FILE, active_pool)
    except Exception as e:
        print(f"[ACCOUNT_DELETE] Ошибка очистки {ACTIVE_POOL_FILE}: {e}")


def get_farm_snapshot():
    """Возвращает полный срез состояния фермы для GUI: боты, статы MM2, системные ресурсы, ошибки."""
    active_pool = load_json(ACTIVE_POOL_FILE, [])
    errors = load_json(ERRORS_FILE, [])

    # Подсчет готовых аккаунтов (100 лвл)
    done_count = 0
    if os.path.exists(DONE_FILE):
        try:
            with open(DONE_FILE, "r", encoding="utf-8") as df:
                done_count = sum(1 for line in df if line.strip())
        except Exception:
            pass

    # Подсчет аккаунтов в очереди пула
    pool_count = 0
    if os.path.exists(POOL_ACCOUNTS_FILE):
        try:
            with open(POOL_ACCOUNTS_FILE, "r", encoding="utf-8") as pf:
                pool_count = sum(1 for line in pf if line.strip())
        except Exception:
            pass

    total_farmed_coins = 0
    bots_data = []

    for b in active_pool:
        uid = b.get("userId")
        uname = b.get("username", "Unknown")
        pwd = b.get("password", "")
        pid = b.get("pid")
        launched_at = b.get("launched_at", 0)
        uptime = int(time.time() - launched_at) if launched_at > 0 else 0

        proc_alive = False
        if pid:
            try:
                proc_alive = psutil.pid_exists(int(pid))
            except Exception:
                proc_alive = False

        # Читаем stats_{uid}.json
        sf = find_stats_file(uid)
        stats = {}
        if sf and os.path.exists(sf):
            try:
                with open(sf, "r", encoding="utf-8") as f:
                    stats = json.load(f)
            except Exception:
                pass

        lvl = stats.get("level", 0)
        bag = stats.get("bag", 0)
        max_bag = stats.get("maxBag", 40)
        coins = stats.get("coins", 0)
        total_farmed_coins += coins
        status = stats.get("status", "LAUNCHING" if proc_alive else "STOPPED")
        error_msg = stats.get("error", "")

        bots_data.append({
            "username": uname,
            "password": pwd,
            "userId": uid,
            "pid": pid,
            "proc_alive": proc_alive,
            "uptime_sec": uptime,
            "level": lvl,
            "bag": bag,
            "max_bag": max_bag,
            "coins": coins,
            "status": status,
            "error": error_msg,
            "updated_at": stats.get("updatedAt", 0),
        })

    # Системные ресурсы
    vm = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=None)

    return {
        "farm_enabled": farm_enabled.is_set(),
        "bots": bots_data,
        "errors": errors,
        "done_count": done_count,
        "pool_count": pool_count,
        "total_coins": total_farmed_coins,
        "active_bots_count": len(bots_data),
        "max_bots": CFG.get("hardware_limits", {}).get("absolute_max_bots_safety_cap", 50),
        "target_level": CFG.get("farm", {}).get("target_level", 100),
        "ram_percent": vm.percent,
        "ram_used_gb": round((vm.total - vm.available) / (1024 ** 3), 1),
        "ram_total_gb": round(vm.total / (1024 ** 3), 1),
        "cpu_percent": cpu_percent,
    }


def dismiss_crash_dialogs():
    """Автоматически закрывает модальные окна фатальных ошибок Windows (#32770), чтобы они не блокировали ферму."""
    if sys.platform != "win32":
        return
    try:
        def enum_windows_proc(hwnd, lParam):
            try:
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                        title = buff.value.lower()
                        crash_keywords = [
                            "fatal error",
                            "unhandled exception",
                            "memory could not be read",
                            "application error",
                            "roblox crash",
                            "an unexpected error occurred",
                        ]
                        if any(k in title for k in crash_keywords):
                            class_buff = ctypes.create_unicode_buffer(256)
                            ctypes.windll.user32.GetClassNameW(hwnd, class_buff, 256)
                            class_name = class_buff.value
                            if class_name == "#32770":
                                WM_CLOSE = 0x0010
                                ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        cb = WNDENUMPROC(enum_windows_proc)
        ctypes.windll.user32.EnumWindows(cb, 0)
    except Exception:
        pass


def disable_quickedit():
    """Отключает QuickEdit Mode в консоли Windows.
    Предотвращает зависание скрипта ('Select ...'), когда пользователь кликает в консоль.
    """
    if sys.platform != "win32":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        h_stdin = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(h_stdin, ctypes.byref(mode)):
            ENABLE_QUICK_EDIT_MODE = 0x0040
            ENABLE_EXTENDED_FLAGS = 0x0080
            new_mode = (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS
            kernel32.SetConsoleMode(h_stdin, new_mode)
    except Exception:
        pass


def trim_roblox_memory(pid):
    """Освобождает неиспользуемую память процесса Roblox через EmptyWorkingSet (Extra RAM)."""
    if sys.platform != "win32":
        return
    try:
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
            False,
            int(pid),
        )
        if handle:
            ctypes.windll.psapi.EmptyWorkingSet(handle)
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        pass


def crash_dialog_watcher_worker():
    """Следит за диалогами фатальных крашей Windows (#32770) и закрывает их,
    а также оптимизирует память окон Roblox через EmptyWorkingSet (Extra RAM Mode).
    """
    print("[*] Модуль контроля краш-окон и сжатия памяти запущен (Extra RAM Mode)...")
    while True:
        try:
            if sys.platform == "win32":
                disable_quickedit()
                dismiss_crash_dialogs()
                now = time.time()
                for proc in psutil.process_iter(["pid", "name", "create_time"]):
                    try:
                        pname = (proc.info.get("name") or "").lower()
                        if pname == "robloxplayerbeta.exe":
                            pid = proc.info["pid"]
                            # Сжимаем память только для процессов старше 40с (уже загрузились в игру)
                            if (now - proc.info.get("create_time", 0)) > 40:
                                trim_roblox_memory(pid)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
        except Exception:
            pass
        time.sleep(20)


def is_roblox_proc_alive(pid):
    """Проверяет, что процесс с данным PID реально существует,
    является именно RobloxPlayerBeta.exe и не является зомби."""
    if not pid:
        return False
    try:
        p = psutil.Process(int(pid))
        if not p.is_running():
            return False
        if p.status() in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
            return False
        name = (p.name() or "").lower()
        if "roblox" not in name:
            return False
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
        return False


def has_visible_roblox_window(pid):
    """Проверяет через WinAPI, есть ли у процесса видимое окно."""
    if sys.platform != "win32" or not pid:
        return True
    has_win = False
    try:
        def enum_win(hwnd, _):
            nonlocal has_win
            try:
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    w_pid = ctypes.c_ulong()
                    ctypes.windll.user32.GetWindowThreadProcessId(
                        hwnd, ctypes.byref(w_pid)
                    )
                    if w_pid.value == int(pid):
                        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                        if length > 0:
                            has_win = True
            except Exception:
                pass
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
        )
        cb = WNDENUMPROC(enum_win)
        ctypes.windll.user32.EnumWindows(cb, 0)
    except Exception:
        return True
    return has_win


def is_window_hung(pid):
    """Проверяет через WinAPI IsHungAppWindow, действительно ли окно 'Не отвечает'."""
    if sys.platform != "win32" or not pid:
        return False
    hung = False
    try:
        def enum_win(hwnd, _):
            nonlocal hung
            try:
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    w_pid = ctypes.c_ulong()
                    ctypes.windll.user32.GetWindowThreadProcessId(
                        hwnd, ctypes.byref(w_pid)
                    )
                    if w_pid.value == int(pid):
                        if ctypes.windll.user32.IsHungAppWindow(hwnd):
                            hung = True
            except Exception:
                pass
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
        )
        cb = WNDENUMPROC(enum_win)
        ctypes.windll.user32.EnumWindows(cb, 0)
    except Exception:
        pass
    return hung


def get_candidate_workspace_paths():
    paths = []
    ws = CFG["farm"].get("executor_workspace_path", "").strip()
    if ws and os.path.isdir(ws):
        paths.append(os.path.abspath(ws))

    # 1. Автопоиск папки запущенного Real / Xeno / Solara
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            pname = (proc.info.get("name") or "").lower()
            if "real" in pname or "xeno" in pname or "solara" in pname:
                pexe = proc.info.get("exe")
                if pexe:
                    pdir = os.path.dirname(pexe)
                    for sub in ["workspace", "Workspace", ""]:
                        cand = os.path.join(pdir, sub) if sub else pdir
                        if os.path.isdir(cand) and cand not in paths:
                            paths.append(os.path.abspath(cand))
        except Exception:
            pass

    # 2. Стандартные пути Real, Xeno, Solara, KRNL и Desktop
    candidates = [
        os.path.join(os.getcwd(), "workspace"),
        os.getcwd(),
        r"C:\Users\DDDen\AppData\Local\Real\workspace",
        os.path.expandvars(r"%LOCALAPPDATA%\Real\workspace"),
        os.path.expandvars(r"%APPDATA%\Real\workspace"),
        os.path.expandvars(r"%USERPROFILE%\Desktop\Real\workspace"),
        r"C:\Users\DDDen\AppData\Local\Xeno\workspace",
        os.path.expandvars(r"%LOCALAPPDATA%\Xeno\workspace"),
        os.path.expandvars(r"%APPDATA%\Xeno\workspace"),
        os.path.expandvars(r"%USERPROFILE%\Desktop\Xeno\workspace"),
        os.path.expandvars(r"%USERPROFILE%\Desktop\farm\workspace"),
        os.path.expandvars(r"%USERPROFILE%\Desktop\farm"),
        os.path.expandvars(r"%USERPROFILE%\Downloads\workspace"),
        os.path.expandvars(r"%USERPROFILE%\Downloads\Solara\workspace"),
        os.path.expandvars(r"%USERPROFILE%\Desktop\Solara\workspace"),
        os.path.expandvars(r"%LOCALAPPDATA%\Solara\workspace"),
        os.path.expandvars(r"%LOCALAPPDATA%\Solara"),
        os.path.expandvars(r"%APPDATA%\Solara\workspace"),
        os.path.expandvars(r"%TEMP%\Solara.Dir\workspace"),
        os.path.expandvars(r"%TEMP%\Solara.Dir"),
        os.path.expandvars(r"%TEMP%\workspace"),
        os.path.expandvars(r"%LOCALAPPDATA%\Temp\Solara.Dir\workspace"),
        os.path.expandvars(r"%LOCALAPPDATA%\Temp\Solara.Dir"),
        os.path.expandvars(r"%LOCALAPPDATA%\Delta\workspace"),
        os.path.expandvars(r"%LOCALAPPDATA%\Wave\workspace"),
        os.path.expandvars(r"%LOCALAPPDATA%\Roblox\workspace"),
        r"C:\workspace",
    ]
    for c in candidates:
        if c and os.path.isdir(c):
            abs_c = os.path.abspath(c)
            if abs_c not in paths:
                paths.append(abs_c)
    return paths


def get_workspace_path():
    ws = CFG["farm"].get("executor_workspace_path", "").strip()
    if ws and os.path.exists(ws):
        return ws
    for c in get_candidate_workspace_paths():
        if os.path.exists(c) and os.path.isdir(c):
            return c
    local_ws = os.path.join(os.getcwd(), "workspace")
    os.makedirs(local_ws, exist_ok=True)
    return local_ws


def find_stats_file(user_id):
    """Ищет stats_{user_id}.json по всем возможным директориям воркспейсов."""
    filename = f"stats_{user_id}.json"
    for p in get_candidate_workspace_paths():
        if os.path.isdir(p):
            candidate_file = os.path.join(p, filename)
            if os.path.isfile(candidate_file):
                return candidate_file
    ws = get_workspace_path()
    return os.path.join(ws, filename)


# ==================== СИНХРОНИЗАЦИЯ С RAM ====================
def find_ram_account_data_path():
    cfg_ram = CFG.get("farm", {}).get("ram_account_data_path", "").strip()
    candidates = []
    if cfg_ram:
        candidates.append(cfg_ram)

    candidates.extend([
        r"C:\Users\DDDen\Desktop\farm\RAM\AccountData.json",
        r"C:\Users\DDDen\Desktop\RAM\AccountData.json",
        os.path.expandvars(r"%USERPROFILE%\Desktop\farm\RAM\AccountData.json"),
        os.path.expandvars(r"%USERPROFILE%\Desktop\RAM\AccountData.json"),
        os.path.expandvars(r"%USERPROFILE%\Downloads\RAM\AccountData.json"),
        os.path.join(os.getcwd(), "RAM", "AccountData.json"),
        os.path.join(os.getcwd(), "AccountData.json"),
    ])

    for proc in psutil.process_iter(["name", "exe"]):
        try:
            pname = (proc.info.get("name") or "").lower()
            if "account" in pname or "ram" in pname:
                pexe = proc.info.get("exe")
                if pexe:
                    pdir = os.path.dirname(pexe)
                    cand = os.path.join(pdir, "AccountData.json")
                    if cand not in candidates:
                        candidates.append(cand)
        except Exception:
            pass

    for c in candidates:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return cfg_ram


def add_account_to_ram(username, password, cookie, user_id):
    ram_path = find_ram_account_data_path()
    if not ram_path:
        return

    with file_lock:
        data = []
        if os.path.exists(ram_path):
            try:
                with open(ram_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = []

        if isinstance(data, list):
            for item in data:
                if item.get("Username") == username or item.get("UserId") == user_id:
                    return

            data.append(
                {
                    "Username": username,
                    "Password": password,
                    "Cookie": cookie,
                    "UserId": int(user_id) if str(user_id).isdigit() else user_id,
                    "Alias": "MM2 Farmer",
                    "Description": "Farm Bot",
                }
            )

            try:
                with open(ram_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
                print(f"[RAM] [+] {username} успешно добавлен в список RAM!")
            except Exception as e:
                print(f"[RAM] [!] Ошибка записи в RAM: {e}")


def remove_account_from_ram(username, user_id):
    ram_path = find_ram_account_data_path()
    if not ram_path or not os.path.exists(ram_path):
        return

    with file_lock:
        try:
            with open(ram_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        if isinstance(data, list):
            new_data = [
                item
                for item in data
                if item.get("Username") != username
                and item.get("UserId") != user_id
                and item.get("UserId") != int(user_id if str(user_id).isdigit() else -1)
            ]

            try:
                with open(ram_path, "w", encoding="utf-8") as f:
                    json.dump(new_data, f, indent=4)
                print(f"[RAM] [-] Аккаунт {username} вычищен из RAM.")
            except Exception as e:
                print(f"[RAM] [!] Ошибка удаления из RAM: {e}")


# ==================== ПРОВЕРКА РЕСУРСОВ ЖЕЛЕЗА (RAM UNLIMITED) ====================
def can_spawn_more_bots():
    """Ограничения ОЗУ сняты: оптимизация достигается отключением 3D в скрипте.
    Защита срабатывает только при критическом исчерпании (<100 МБ свободной памяти).
    """
    try:
        vm = psutil.virtual_memory()
        free_ram_mb = vm.available / (1024 * 1024)
        if free_ram_mb < 100:
            print(
                f"[LIMIT] Критически мало ОЗУ в системе ({int(free_ram_mb)} МБ). Пауза пула..."
            )
            return False
    except Exception:
        pass
    return True


# ==================== МОМЕНТАЛЬНАЯ БЛОКИРОВКА ПРИ ВСТРЕЧЕ (ИДЕАЛЬНЫЙ CSRF) ====================
def sync_bot_ids(user_id):
    ids = load_json(BOT_IDS_FILE, [])
    if user_id not in ids:
        ids.append(user_id)
        save_json(BOT_IDS_FILE, ids)

    ws_path = get_workspace_path()
    if ws_path and os.path.exists(ws_path):
        target = os.path.join(ws_path, "bot_ids.json")
        with file_lock:
            try:
                with open(target, "w", encoding="utf-8") as f:
                    json.dump(ids, f)
            except Exception as e:
                print(f"[!] Ошибка записи bot_ids.json: {e}")


def block_user(cookie, target_id):
    """Самый надежный способ бана в Roblox"""
    try:
        session = requests.Session()
        clean_cookie = cookie.strip().strip('"').strip("'")
        session.cookies[".ROBLOSECURITY"] = clean_cookie

        # 1. Получаем свежий CSRF токен
        r_csrf = session.post("https://auth.roblox.com/v2/logout", timeout=8)
        csrf = r_csrf.headers.get("x-csrf-token")
        if not csrf:
            return False

        # 2. Выдаем бан
        headers = {"X-CSRF-TOKEN": csrf, "Content-Type": "application/json"}
        url = f"https://accountsettings.roblox.com/v1/users/{target_id}/block"
        res = session.post(url, headers=headers, json={}, timeout=8)
        return res.status_code == 200
    except Exception as e:
        return False


def block_queue_worker():
    """Читает запросы на бан от Lua-скрипта и моментально банит столкнувшихся ботов"""
    ws = get_workspace_path()
    if not ws:
        return
    queue_file = os.path.join(ws, "block_queue.txt")

    print("[*] Обработчик мгновенных банов при столкновении запущен...")

    while True:
        try:
            if os.path.exists(queue_file):
                with file_lock:
                    with open(queue_file, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    # Очищаем файл после чтения
                    open(queue_file, "w").close()

                if lines:
                    pool = load_json(ACTIVE_POOL_FILE, [])
                    # Карта: UserId -> Cookie
                    cookie_map = {
                        b.get("userId"): b.get("cookie")
                        for b in pool
                        if b.get("userId")
                    }

                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            req = json.loads(line)
                            me_id = req.get("me")
                            target_id = req.get("target")

                            cookie_me = cookie_map.get(me_id)
                            cookie_target = cookie_map.get(target_id)

                            # Взаимный бан
                            if cookie_me:
                                if block_user(cookie_me, target_id):
                                    print(f"[БАН] Бот {me_id} забанил {target_id}!")
                            if cookie_target:
                                if block_user(cookie_target, me_id):
                                    print(f"[БАН] Бот {target_id} забанил {me_id}!")
                        except Exception as e:
                            pass
        except Exception:
            pass
        time.sleep(1.5)  # Проверяем файл каждые 1.5 секунды


# ==================== АВТОРИЗАЦИЯ И ПРЯМОЙ ЗАПУСК ====================
def get_auth_ticket(cookie):
    cookie = cookie.strip().strip('"').strip("'")
    try:
        session = requests.Session()
        session.cookies[".ROBLOSECURITY"] = cookie

        csrf_res = session.post("https://auth.roblox.com/v2/logout", timeout=8)
        csrf = csrf_res.headers.get("x-csrf-token")
        if not csrf:
            return None

        headers = {
            "X-CSRF-TOKEN": csrf,
            "Referer": "https://www.roblox.com/",
            "Origin": "https://www.roblox.com",
            "Content-Type": "application/json",
        }

        res = session.post(
            "https://auth.roblox.com/v1/authentication-ticket",
            headers=headers,
            json={},
            timeout=8,
        )

        ticket = res.headers.get("rbx-authentication-ticket")
        return ticket
    except Exception as e:
        return None


def parse_account_line(line):
    line = line.strip()
    if not line:
        return None

    # Форматы:
    # 1) username:password:cookie:userid
    # 2) username:password:cookie
    # 3) username:cookie
    # Куки Roblox всегда содержит '_|WARNING:-DO-NOT-SHARE-THIS...' с двоеточием,
    # поэтому обычный split(":") без ограничения длины ломает куки!
    parts = line.split(":", 2)
    if len(parts) < 2:
        return None

    if len(parts) == 2:
        u = parts[0].strip()
        p = ""
        rest = parts[1].strip()
    else:
        u = parts[0].strip()
        p = parts[1].strip()
        rest = parts[2].strip()

    uid = 0
    cookie = rest
    if ":" in rest:
        r_parts = rest.rsplit(":", 1)
        if r_parts[1].strip().isdigit():
            cookie = r_parts[0].strip()
            uid = int(r_parts[1].strip())

    cookie = cookie.strip().strip('"').strip("'")
    if not u or not cookie:
        return None

    return {
        "username": u,
        "password": p,
        "cookie": cookie,
        "userId": uid,
    }


def find_roblox_executable():
    cfg_exe = CFG.get("farm", {}).get("roblox_executable_path", "").strip()
    if cfg_exe and os.path.isfile(cfg_exe):
        return cfg_exe

    candidates = []
    versions_pattern = os.path.expandvars(r"%LOCALAPPDATA%\Roblox\Versions\*\RobloxPlayerBeta.exe")
    found = glob.glob(versions_pattern)
    if found:
        found.sort(key=os.path.getmtime, reverse=True)
        candidates.extend(found)

    hardcoded_candidates = [
        r"C:\Users\DDDen\AppData\Local\Roblox\Versions\version-c5aecda2245e4fae\RobloxPlayerBeta.exe",
        r"C:\Users\DDDen\AppData\Local\Roblox\Versions\version-e7d81637d42c4b23\RobloxPlayerBeta.exe",
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Roblox\Versions\RobloxPlayerBeta.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Roblox\Versions\RobloxPlayerBeta.exe"),
    ]
    for hc in hardcoded_candidates:
        if hc and os.path.isfile(hc) and hc not in candidates:
            candidates.append(hc)

    for c in candidates:
        if os.path.isfile(c):
            return c
    return cfg_exe


def sync_accounts_into_pool():
    """Синхронизирует аккаунты из:
    1. Roblox Account Manager (AccountData.json)
    2. accounts.txt
    3. accounts_pool.txt
    Гарантирует, что все незавершенные аккаунты (не 100 lvl) находятся в очереди пула.
    """
    done_users = set()
    if os.path.exists(DONE_FILE):
        try:
            with open(DONE_FILE, "r", encoding="utf-8") as df:
                for line in df:
                    m = re.search(r"name:\s*(\S+)", line, re.IGNORECASE)
                    if m:
                        done_users.add(m.group(1).strip().lower())
        except Exception:
            pass

    active_pool = load_json(ACTIVE_POOL_FILE, [])
    active_users = {
        b.get("username", "").strip().lower()
        for b in active_pool
        if b.get("username")
    }

    errors_list = load_json(ERRORS_FILE, [])
    error_users = {
        e.get("username", "").strip().lower()
        for e in errors_list
        if e.get("username")
    }

    ignored_list = load_json(IGNORED_ACCOUNTS_FILE, [])
    ignored_users = {
        str(x).strip().lower()
        for x in ignored_list
        if str(x).strip()
    }

    pool_lines = []
    if os.path.exists(POOL_ACCOUNTS_FILE):
        try:
            with open(POOL_ACCOUNTS_FILE, "r", encoding="utf-8") as pf:
                pool_lines = [l.strip() for l in pf if l.strip()]
        except Exception:
            pool_lines = []

    pool_users = set()
    for l in pool_lines:
        parsed = parse_account_line(l)
        if parsed and parsed.get("username"):
            pool_users.add(parsed["username"].lower())

    new_lines_to_add = []

    # 1. Загрузка из Roblox Account Manager (AccountData.json)
    ram_file = find_ram_account_data_path()
    if ram_file and os.path.isfile(ram_file):
        try:
            with open(ram_file, "r", encoding="utf-8") as rf:
                ram_data = json.load(rf)
            acc_list = []
            if isinstance(ram_data, list):
                acc_list = ram_data
            elif isinstance(ram_data, dict):
                acc_list = list(ram_data.values())

            for item in acc_list:
                if not isinstance(item, dict):
                    continue
                u = str(item.get("Username") or item.get("username") or "").strip()
                p = str(item.get("Password") or item.get("password") or "").strip()
                c = str(
                    item.get("Cookie")
                    or item.get("cookie")
                    or item.get("SecurityToken")
                    or item.get(".ROBLOSECURITY")
                    or ""
                ).strip().strip('"').strip("'")
                uid = item.get("UserId") or item.get("userId") or 0

                if u and c:
                    u_lower = u.lower()
                    if (
                        u_lower not in done_users
                        and u_lower not in active_users
                        and u_lower not in pool_users
                        and u_lower not in error_users
                        and u_lower not in ignored_users
                    ):
                        new_lines_to_add.append(f"{u}:{p}:{c}:{uid}")
                        pool_users.add(u_lower)
        except Exception as e:
            print(f"[RAM] [!] Ошибка синхронизации с {ram_file}: {e}")

    # 2. Загрузка из accounts.txt
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as af:
                for line in af:
                    line = line.strip()
                    if not line:
                        continue
                    parsed = parse_account_line(line)
                    if parsed:
                        u = parsed["username"]
                        p = parsed["password"]
                        c = parsed["cookie"]
                        uid = parsed["userId"]
                        u_lower = u.lower()
                        if (
                            u_lower not in done_users
                            and u_lower not in active_users
                            and u_lower not in pool_users
                            and u_lower not in error_users
                            and u_lower not in ignored_users
                        ):
                            new_lines_to_add.append(f"{u}:{p}:{c}:{uid}")
                            pool_users.add(u_lower)
        except Exception:
            pass

    if new_lines_to_add:
        with file_lock:
            with open(POOL_ACCOUNTS_FILE, "a", encoding="utf-8") as pf:
                for nl in new_lines_to_add:
                    pf.write(nl + "\n")
        print(
            f"[POOL] [+] Загружено {len(new_lines_to_add)} аккаунтов в очередь пула (из RAM / accounts.txt)."
        )


def get_account_from_pool():
    sync_accounts_into_pool()
    if not os.path.exists(POOL_ACCOUNTS_FILE):
        print(
            f"[FARM] [!] Файл {POOL_ACCOUNTS_FILE} не найден! Создайте его или добавьте аккаунты в RAM."
        )
        return None

    with file_lock:
        with open(POOL_ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]

        if not lines:
            return None

        chosen_line = lines.pop(0)

        with open(POOL_ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            for l in lines:
                f.write(l + "\n")

    parsed = parse_account_line(chosen_line)
    if not parsed:
        print(f"[FARM] [!] Не удалось распарсить строку из пула: {chosen_line[:35]}...")
        return None

    username = parsed["username"]
    password = parsed["password"]
    cookie = parsed["cookie"]
    user_id = parsed["userId"]

    # Проверяем валидность куки через API Roblox
    try:
        session = requests.Session()
        session.cookies[".ROBLOSECURITY"] = cookie
        r = session.get("https://users.roblox.com/v1/users/authenticated", timeout=8)
        if r.status_code == 200:
            user_id = r.json().get("id", user_id)
            username = r.json().get("name", username)
        elif r.status_code in (401, 403):
            err_msg = f"HTTP {r.status_code}: Сессия устарела (Cookie Expired)"
            print(
                f"[FARM] [!] Ошибка куки для {username}: {err_msg}. Аккаунт: {username}, Пароль: {password}"
            )
            record_failure(username, password, err_msg, user_id, threshold=5)
            if get_failure_count(username) <= 5:
                # Возвращаем в конец очереди пула для повторной попытки
                with file_lock:
                    with open(POOL_ACCOUNTS_FILE, "a", encoding="utf-8") as pf:
                        pf.write(chosen_line + "\n")
            return None
        else:
            print(
                f"[FARM] [i] Roblox API ответил HTTP {r.status_code} для {username}. Пробуем запустить..."
            )
    except Exception as e:
        print(f"[FARM] [i] Проверка API ({e}), запускаем {username} по сохраненным данным...")

    account_entry = {
        "username": username,
        "password": password,
        "cookie": cookie,
        "userId": user_id,
        "launched_at": time.time(),
    }

    with file_lock:
        with open(ACCOUNTS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{username}:{password}:{cookie}:{user_id}\n")

    print(f"[FARM] [+] Бот взят из пула: {username} (ID: {user_id})")

    add_account_to_ram(username, password, cookie, user_id)
    sync_bot_ids(user_id)

    return account_entry


used_server_jobs = set()


def get_distinct_public_server(place_id, used_jobs):
    """Находит свободный публичный сервер MM2 (2-8 игроков), где ещё нет наших ботов."""
    try:
        url = f"https://games.roblox.com/v1/games/{place_id}/servers/Public?limit=100"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            # Серверы с онлайном от 2 до 8 человек
            candidates = [
                s["id"] for s in data
                if s.get("id") and s["id"] not in used_jobs
                and 2 <= s.get("playing", 0) <= 8
            ]
            if candidates:
                chosen = random.choice(candidates)
                used_jobs.add(chosen)
                return chosen
            # Запасной вариант: любой сервер не полный
            fallback = [
                s["id"] for s in data
                if s.get("id") and s["id"] not in used_jobs
                and s.get("playing", 0) < s.get("maxPlayers", 12)
            ]
            if fallback:
                chosen = random.choice(fallback)
                used_jobs.add(chosen)
                return chosen
    except Exception:
        pass
    return None


def launch_roblox_instance(bot_entry):
    ticket = get_auth_ticket(bot_entry["cookie"])
    if not ticket:
        err_msg = "Ошибка авторизации: не удалось получить auth-тикет (Бан, капча или истекшая сессия)"
        print(
            f"[FARM] [-] Запуск отменён: не удалось авторизовать {bot_entry['username']}. Пароль: {bot_entry.get('password')}"
        )
        record_failure(bot_entry["username"], bot_entry.get("password", ""), err_msg, bot_entry.get("userId"), threshold=5)
        return None

    place_id = CFG["farm"].get("place_id", 142823291)
    exe_path = find_roblox_executable()

    if not exe_path or not os.path.exists(exe_path):
        print(f"[FARM] [-] Ошибка: исполняемый файл Roblox не найден: {exe_path}")
        return None

    job_id = get_distinct_public_server(place_id, used_server_jobs)
    if job_id:
        join_url = f"https://assetgame.roblox.com/game/PlaceLauncher.ashx?request=RequestGameJob&placeId={place_id}&gameId={job_id}"
        print(f"[FARM] [*] Выделен отдельный публичный сервер {job_id[:8]}... (исключаем коллизии)")
    else:
        join_url = f"https://assetgame.roblox.com/game/PlaceLauncher.ashx?request=RequestGame&placeId={place_id}"

    cmd = [exe_path, "--app", "-t", ticket, "-j", join_url]

    # Считываем все существующие PID RobloxPlayerBeta до запуска
    existing_pids = set()
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] == "RobloxPlayerBeta.exe":
                existing_pids.add(proc.info["pid"])
        except Exception:
            pass

    print(
        f"[FARM] [*] Прямой запуск {os.path.basename(exe_path)} для {bot_entry['username']}..."
    )
    subprocess.Popen(cmd)

    cooldown = CFG.get("hardware_limits", {}).get("spawn_cooldown_sec", 10)

    # Ищем ИМЕННО НОВЫЙ процесс (которого не было до запуска)
    pid = None
    start_wait = time.time()
    while (time.time() - start_wait) < 30:
        for proc in psutil.process_iter(["pid", "name", "create_time"]):
            try:
                if proc.info["name"] == "RobloxPlayerBeta.exe":
                    p = proc.info["pid"]
                    if p not in existing_pids:
                        pid = p
                        break
            except Exception:
                pass
        if pid:
            break
        time.sleep(1)

    if pid:
        bot_entry["pid"] = pid
        bot_entry["launched_at"] = time.time()

        try:
            p = psutil.Process(pid)
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:
            pass

        print(
            f"[FARM] [+] Окно игры {bot_entry['username']} успешно запущено (PID: {pid})"
        )
        if cooldown > 0:
            print(
                f"[FARM] [*] Задержка {cooldown} сек перед следующим запуском для стабильной прогрузки мира..."
            )
            time.sleep(cooldown)
            print(f"[FARM] [+] Окно {bot_entry['username']} прогружено, продолжаем работу.")
        else:
            print(
                f"[FARM] [+] Окно {bot_entry['username']} запущено (PID: {pid}). Запуск следующего БЕЗ ДЕЛЕЯ!"
            )
    else:
        print(
            f"[FARM] [!] Внимание: новый процесс RobloxPlayerBeta.exe не обнаружен за 30 сек."
        )
        time.sleep(10)
    return pid


# ==================== ОСНОВНОЙ ЦИКЛ ФЕРМЫ ====================
def farm_worker():
    print("[*] Авто-скейлер фермы запущен (RAM Unlimited Mode)...")
    ws = get_workspace_path()
    target_lvl = CFG["farm"].get("target_level", 100)
    safety_cap = CFG.get("hardware_limits", {}).get("absolute_max_bots_safety_cap", 50)
    check_interval = int(CFG["farm"].get("check_stats_interval_sec", 10))
    last_empty_notice = 0
    # На старте синхронизируем уже запущенные окна Roblox
    init_pool = load_json(ACTIVE_POOL_FILE, [])
    live_roblox_pids = set()
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if p.info["name"] == "RobloxPlayerBeta.exe":
                live_roblox_pids.add(p.info["pid"])
        except Exception:
            pass

    assigned_pids = set()
    for b in init_pool:
        uid = b.get("userId")
        sf = find_stats_file(uid)
        stats_alive = False
        if sf and os.path.exists(sf):
            try:
                if (time.time() - os.path.getmtime(sf)) < 45:
                    stats_alive = True
            except Exception:
                pass

        pid = b.get("pid")
        if pid and pid in live_roblox_pids:
            b["session_launched"] = True
            b["hung_ticks"] = 0
            b["launched_at"] = time.time()
            assigned_pids.add(pid)
        elif stats_alive:
            b["session_launched"] = True
            b["hung_ticks"] = 0
            b["launched_at"] = time.time()
            free_pids = live_roblox_pids - assigned_pids
            if free_pids:
                chosen = free_pids.pop()
                b["pid"] = chosen
                assigned_pids.add(chosen)
        else:
            # Бот не запущен при старте скрипта
            b["session_launched"] = False
            b["pid"] = None
            b["hung_ticks"] = 0
            b["launched_at"] = 0

    save_json(ACTIVE_POOL_FILE, init_pool)

    while True:
        try:
            if not farm_enabled.is_set():
                time.sleep(1)
                continue

            active_pool = load_json(ACTIVE_POOL_FILE, [])
            updated_pool = []

            for bot in active_pool:
                user_id = bot["userId"]
                stats_file = find_stats_file(user_id)

                bot_lvl = 0
                stats_status = None

                if os.path.exists(stats_file):
                    try:
                        with open(stats_file, "r", encoding="utf-8") as sf:
                            st = json.load(sf)
                            bot_lvl = st.get("level", 0)
                            stats_status = st.get("status")
                    except Exception:
                        pass

                # Цель достигнута по УРОВНЮ!
                if bot_lvl >= target_lvl:
                    print(
                        f"\n[FARM] [★] ГОТОВ К ПРОДАЖЕ: {bot['username']} | Lvl: {bot_lvl}"
                    )
                    clear_error(bot["username"])

                    with file_lock:
                        with open(DONE_FILE, "a", encoding="utf-8") as df:
                            # Формат строго для FunPay: name: nick pass: password, 100 lvl
                            df.write(
                                f"name: {bot['username']} pass: {bot['password']}, {bot_lvl} lvl\n"
                            )

                    remove_account_from_ram(bot["username"], user_id)

                    pid = bot.get("pid")
                    if pid and psutil.pid_exists(pid):
                        try:
                            psutil.Process(pid).terminate()
                            print(f"[FARM] [-] Процесс {pid} закрыт, слот свободен.")
                        except Exception:
                            pass

                    if os.path.exists(stats_file):
                        try:
                            os.remove(stats_file)
                        except Exception:
                            pass

                    continue

                # Проверка краша процесса или зависания
                pid = bot.get("pid")
                proc_alive = is_roblox_proc_alive(pid)

                time_since_launch = time.time() - bot.get("launched_at", 0)

                # Проверяем файл статистики
                stats_recent = False
                stats_is_current_session = False
                if stats_file and os.path.exists(stats_file):
                    try:
                        mtime = os.path.getmtime(stats_file)
                        # Файл обновлен в рамках текущей сессии этого бота
                        if mtime >= (bot.get("launched_at", 0) - 5):
                            stats_is_current_session = True
                            if (time.time() - mtime) < 90:
                                stats_recent = True
                    except Exception:
                        pass

                # Если бот живой, статистика свежая и нет кика - он успешно фармит!
                # Сбрасываем счетчик последовательных ошибок
                if proc_alive and stats_recent and stats_status != "KICKED_OR_DISCONNECTED":
                    reset_failure_count(bot["username"])

                # 1. Если скрипт зафиксировал кик/дисконнект — перезапускаем процесс
                if stats_status == "KICKED_OR_DISCONNECTED":
                    reason = ""
                    if stats_file and os.path.exists(stats_file):
                        try:
                            with open(stats_file, "r", encoding="utf-8") as sf:
                                reason = json.load(sf).get("error", "")
                        except Exception:
                            pass
                    err_msg = f"KICKED_OR_DISCONNECTED: {reason}" if reason else "KICKED_OR_DISCONNECTED (Код 277 / 268)"
                    print(
                        f"[FARM] [!] Бот {bot['username']} (PID: {pid}) был кикнут или отключен! Пароль: {bot.get('password')}. Перезапуск окна..."
                    )
                    record_failure(bot["username"], bot.get("password", ""), err_msg, user_id, threshold=5)
                    if pid and psutil.pid_exists(pid):
                        try:
                            psutil.Process(int(pid)).kill()
                        except Exception:
                            pass
                    if stats_file and os.path.exists(stats_file):
                        try:
                            os.remove(stats_file)
                        except Exception:
                            pass

                    if get_failure_count(bot["username"]) > 5:
                        print(
                            f"[FARM] [🛑] Бот {bot['username']} превысил лимит сбоев (>5 подряд). Исключен из активных окон."
                        )
                        continue

                    proc_alive = False
                    bot["pid"] = None
                    bot["launched_at"] = 0
                    bot["session_launched"] = False

                # 2. Если окно только запустилось, но за 180с так и не выдало статистику (мир долго грузится или экзекутор не заинжектился)
                elif proc_alive and not stats_is_current_session and time_since_launch > 180:
                    err_msg = f"Таймаут старта ({int(time_since_launch)}с): экзекутор не заинжектился или мир завис"
                    print(
                        f"[FARM] [!] Бот {bot['username']} (PID: {pid}) не выдал статистику за {int(time_since_launch)}с. Пароль: {bot.get('password')}. Перезапуск процесса..."
                    )
                    record_failure(bot["username"], bot.get("password", ""), err_msg, user_id, threshold=5)
                    if pid and psutil.pid_exists(pid):
                        try:
                            psutil.Process(int(pid)).kill()
                        except Exception:
                            pass
                    if stats_file and os.path.exists(stats_file):
                        try:
                            os.remove(stats_file)
                        except Exception:
                            pass

                    if get_failure_count(bot["username"]) > 5:
                        print(
                            f"[FARM] [🛑] Бот {bot['username']} превысил лимит сбоев (>5 подряд). Исключен из активных окон."
                        )
                        continue

                    proc_alive = False
                    bot["pid"] = None
                    bot["launched_at"] = 0
                    bot["session_launched"] = False

                # 3. Если бот уже был в игре (статистика текущей сессии есть), но не обновлял её >90с (завис сервер / дисконнект)
                elif proc_alive and stats_is_current_session and not stats_recent and time_since_launch > 90:
                    err_msg = f"Зависание сессии (>90с без статистики): завис сервер или дисконнект"
                    print(
                        f"[FARM] [!] Бот {bot['username']} (PID: {pid}) не обновляет статистику >90с. Пароль: {bot.get('password')}. Перезапуск процесса..."
                    )
                    record_failure(bot["username"], bot.get("password", ""), err_msg, user_id, threshold=5)
                    if pid and psutil.pid_exists(pid):
                        try:
                            psutil.Process(int(pid)).kill()
                        except Exception:
                            pass
                    if stats_file and os.path.exists(stats_file):
                        try:
                            os.remove(stats_file)
                        except Exception:
                            pass

                    if get_failure_count(bot["username"]) > 5:
                        print(
                            f"[FARM] [🛑] Бот {bot['username']} превысил лимит сбоев (>5 подряд). Исключен из активных окон."
                        )
                        continue

                    proc_alive = False
                    bot["pid"] = None
                    bot["launched_at"] = 0
                    bot["session_launched"] = False

                # 4. Если процесс живой, проверяем не призрак ли он (окно закрылось/упало, а процесс висит без окна)
                elif proc_alive:
                    if not stats_recent and time_since_launch > 300 and not has_visible_roblox_window(pid):
                        print(
                            f"[FARM] [!] Окно бота {bot['username']} (PID: {pid}) исчезло с экрана (процесс-призрак, возраст {int(time_since_launch)}с). Сброс..."
                        )
                        record_failure(bot["username"], bot.get("password", ""), "Окно исчезло с экрана (процесс-призрак)", user_id, threshold=5)
                        try:
                            psutil.Process(int(pid)).kill()
                        except Exception:
                            pass
                        if get_failure_count(bot["username"]) > 5:
                            print(
                                f"[FARM] [🛑] Бот {bot['username']} превысил лимит сбоев (>5 подряд). Исключен из активных окон."
                            )
                            continue
                        proc_alive = False
                        bot["pid"] = None
                        bot["launched_at"] = 0
                        bot["session_launched"] = False
                elif stats_recent:
                    # PID мертв/не совпадает, но файл статистики обновляется прямо сейчас!
                    proc_alive = True
                    for p in psutil.process_iter(["pid", "name"]):
                        try:
                            if "roblox" in (p.info.get("name") or "").lower():
                                cand_pid = p.info["pid"]
                                already_used = any(b.get("pid") == cand_pid for b in active_pool if b != bot)
                                if not already_used:
                                    bot["pid"] = cand_pid
                                    pid = cand_pid
                                    break
                        except Exception:
                            pass

                # Если процесс ЖИВ — проверяем зависание Windows ('Не отвечает')
                if proc_alive:
                    if time_since_launch > 120 and pid and is_window_hung(pid):
                        bot["hung_ticks"] = bot.get("hung_ticks", 0) + 1
                        if bot["hung_ticks"] >= 8:  # 8 проверок по 10с = 80 секунд окно намертво 'Не отвечает'
                            print(
                                f"[FARM] [!] Окно бота {bot['username']} (PID: {pid}) зависло в системе ('Не отвечает'). Перезапуск..."
                            )
                            record_failure(bot["username"], bot.get("password", ""), "Окно зависло ('Не отвечает')", user_id, threshold=5)
                            try:
                                psutil.Process(int(pid)).terminate()
                            except Exception:
                                pass
                            if get_failure_count(bot["username"]) > 5:
                                print(f"[FARM] [🛑] Бот {bot['username']} превысил лимит сбоев (>5 подряд). Исключен из активных окон.")
                                continue
                            time.sleep(2)
                            new_pid = launch_roblox_instance(bot)
                            if new_pid:
                                bot["pid"] = new_pid
                                bot["launched_at"] = time.time()
                                bot["hung_ticks"] = 0
                                bot["session_launched"] = True
                            else:
                                if get_failure_count(bot["username"]) > 5:
                                    print(f"[FARM] [🛑] Бот {bot['username']} превысил лимит сбоев (>5 подряд). Исключен из активных окон.")
                                    continue
                                bot["pid"] = None
                                bot["launched_at"] = 0
                                bot["session_launched"] = False
                    else:
                        bot["hung_ticks"] = 0
                else:
                    # Процесс реально отсутствует
                    if bot.get("session_launched") and time_since_launch < 20:
                        # Ещё в процессе запуска (первые 20 секунд), пропускаем повторный старт
                        updated_pool.append(bot)
                        continue

                    is_initial = not bot.get("session_launched", False)
                    if is_initial:
                        print(
                            f"[FARM] [*] Старт бота {bot['username']} из пула..."
                        )
                    else:
                        print(
                            f"[FARM] [!] Бот {bot['username']} упал/закрыт. Запуск нового чистого окна..."
                        )
                    new_pid = launch_roblox_instance(bot)
                    if new_pid:
                        bot["pid"] = new_pid
                        bot["launched_at"] = time.time()
                        bot["hung_ticks"] = 0
                        bot["session_launched"] = True
                    else:
                        if get_failure_count(bot["username"]) > 5:
                            print(f"[FARM] [🛑] Бот {bot['username']} превысил лимит сбоев (>5 подряд). Исключен из активных окон.")
                            continue
                        bot["pid"] = None
                        bot["launched_at"] = 0
                        bot["session_launched"] = False

                updated_pool.append(bot)

            # Сохраняем полный пул ПОСЛЕ прохода всех ботов
            save_json(ACTIVE_POOL_FILE, updated_pool)

            # Запись файла активного прогресса: ник, лвл и объективный трекинг мешка
            active_lines = []
            for b in updated_pool:
                uid = b.get("userId")
                uname = b.get("username")
                sf = find_stats_file(uid)
                lvl = 0
                bag = 0
                max_bag = 40
                if sf and os.path.exists(sf):
                    try:
                        with open(sf, "r", encoding="utf-8") as _f:
                            st = json.load(_f)
                            lvl = st.get("level", 0)
                            bag = st.get("bag", 0)
                            max_bag = st.get("maxBag", 40)
                    except Exception:
                        pass
                active_lines.append(f"User: {uname} | Level: {lvl} | Bag: {bag}/{max_bag}\n")

            active_lines.sort()
            all_target_dirs = {os.getcwd(), ws}
            for cand in get_candidate_workspace_paths():
                if os.path.isdir(cand):
                    all_target_dirs.add(cand)

            with file_lock:
                for target_d in all_target_dirs:
                    try:
                        f_path = os.path.join(target_d, "mm2_farm_stats.txt")
                        with open(f_path, "w", encoding="utf-8") as f_out:
                            f_out.writelines(active_lines)
                    except Exception:
                        pass

            current_bots = len(updated_pool)
            vm = psutil.virtual_memory()
            print(
                f"[STATUS] Окон: {current_bots} | ОЗУ: {vm.percent}% | Свободно: {int(vm.available / 1024 / 1024)} МБ"
            )

            if current_bots < safety_cap and can_spawn_more_bots():
                new_bot = get_account_from_pool()
                if new_bot:
                    pid = launch_roblox_instance(new_bot)
                    if pid:
                        new_bot["pid"] = pid
                        new_bot["session_launched"] = True
                        updated_pool.append(new_bot)
                        save_json(ACTIVE_POOL_FILE, updated_pool)
                    else:
                        # Запуск не удался
                        with file_lock:
                            if os.path.exists(ACCOUNTS_FILE):
                                try:
                                    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as af:
                                        alines = [l for l in af if not l.startswith(f"{new_bot['username']}:")]
                                    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as af:
                                        af.writelines(alines)
                                except Exception:
                                    pass
                        if get_failure_count(new_bot["username"]) <= 5:
                            line = f"{new_bot['username']}:{new_bot.get('password','')}:{new_bot['cookie']}:{new_bot['userId']}"
                            with file_lock:
                                with open(POOL_ACCOUNTS_FILE, "a", encoding="utf-8") as pf:
                                    pf.write(line + "\n")
                else:
                    now = time.time()
                    if (now - last_empty_notice) >= 45:
                        print(
                            f"[FARM] [i] Слот свободен (Окон: {current_bots}/{safety_cap}, ОЗУ свободно: {int(vm.available / 1024 / 1024)} МБ), но пул пуст (в accounts_pool.txt / RAM нет ожидающих аккаунтов)."
                        )
                        last_empty_notice = now

            time.sleep(check_interval)

        except Exception as e:
            print(f"[FARM] [!] Ошибка цикла фермы: {e}")
            time.sleep(10)


class FunPayFormParser(HTMLParser):
    """Парсер формы редактирования лота FunPay с сохранением всех полей, select и textarea."""
    def __init__(self):
        super().__init__()
        self.inputs = {}
        self.current_tag = None
        self.current_name = None
        self.current_text = ""
        self.current_select = None
        self.select_selected = None

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        self.current_tag = tag
        name = attr_dict.get("name")
        if tag == "input" and name:
            itype = attr_dict.get("type", "text").lower()
            if itype == "checkbox":
                if "checked" in attr_dict:
                    self.inputs[name] = attr_dict.get("value", "on")
            elif itype == "radio":
                if "checked" in attr_dict:
                    self.inputs[name] = attr_dict.get("value", "")
            else:
                self.inputs[name] = attr_dict.get("value", "")
        elif tag == "select" and name:
            self.current_select = name
            self.select_selected = ""
        elif tag == "option" and self.current_select:
            if "selected" in attr_dict:
                self.select_selected = attr_dict.get("value", "")
        elif tag == "textarea" and name:
            self.current_name = name
            self.current_text = ""

    def handle_data(self, data):
        if self.current_tag == "textarea" and self.current_name:
            self.current_text += data

    def handle_endtag(self, tag):
        if tag == "select" and self.current_select:
            self.inputs[self.current_select] = self.select_selected
            self.current_select = None
            self.select_selected = None
        elif tag == "textarea" and self.current_name:
            self.inputs[self.current_name] = self.current_text
            self.current_name = None
        self.current_tag = None


def get_done_accounts():
    """Считывает строки готовых аккаунтов (100 lvl) из done.txt во всех возможных папках."""
    candidates = [
        DONE_FILE,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), DONE_FILE),
        os.path.join(os.getcwd(), DONE_FILE),
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                with file_lock:
                    with open(c, "r", encoding="utf-8") as df:
                        lines = [l.strip() for l in df if l.strip()]
                        if lines:
                            return lines
            except Exception:
                pass
    return []


# ==================== МОДУЛЬ FUNPAY (АВТОВЫДАЧА И АВТОПОДНЯТИЕ) ====================
def funpay_worker():
    print("[*] Модуль FunPay запущен...")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    last_raise_time = 0
    last_online_time = 0
    last_reported_count = -1

    while True:
        try:
            cur_cfg = load_json(CONFIG_FILE, CFG)
            cur_fp = cur_cfg.get("funpay", {})
            if not cur_fp.get("enabled", False):
                time.sleep(10)
                continue

            golden_key = cur_fp.get("golden_key", "").strip()
            user_agent = cur_fp.get(
                "user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            session.headers["User-Agent"] = user_agent
            lot_id = cur_fp.get("lot_id")
            category_url = cur_fp.get("category_url", "https://funpay.com/lots/925/")
            min_price = float(cur_fp.get("min_price_usd", cur_fp.get("min_price", 2.5)))
            undercut_step = float(cur_fp.get("undercut_step_usd", cur_fp.get("undercut_step", 0.01)))
            check_interval = int(cur_fp.get("check_interval_sec", 40))

            if not golden_key or golden_key == "ВАШ_GOLDEN_KEY":
                time.sleep(check_interval)
                continue

            session.cookies.set("golden_key", golden_key, domain=".funpay.com")

            # 1. Читаем готовые аккаунты из done.txt
            done_accounts = get_done_accounts()

            if len(done_accounts) != last_reported_count:
                last_reported_count = len(done_accounts)
                print(f"[FUNPAY] [★] В done.txt готово к продаже на FunPay: {len(done_accounts)} аккаунтов (100 lvl)")
                if done_accounts:
                    print(f"[FUNPAY] Последний готовый: {done_accounts[-1]}")

            now = time.time()

            # 2. Вечный онлайн (каждые 45-60 секунд)
            if now - last_online_time > 45:
                try:
                    resp_main = session.get("https://funpay.com/", timeout=10)
                    csrf_match = re.search(r'data-app-data="([^"]+)"', resp_main.text)
                    csrf_token = ""
                    if csrf_match:
                        try:
                            ap = json.loads(csrf_match.group(1).replace("&quot;", '"'))
                            csrf_token = ap.get("csrf-token", "")
                        except Exception:
                            pass

                    h_runner = {"X-Requested-With": "XMLHttpRequest"}
                    if csrf_token:
                        h_runner["X-CSRF-Token"] = csrf_token

                    payload = {
                        "objects": json.dumps([
                            {"type": "chat_bookmarks", "id": 0, "tag": 0, "data": False},
                            {"type": "chat_node", "id": 0, "tag": 0, "data": False},
                            {"type": "orders_counters", "id": 0, "tag": 0, "data": False}
                        ]),
                        "request": False,
                        "csrf_token": csrf_token
                    }
                    r_runner = session.post("https://funpay.com/runner/", data=payload, headers=h_runner, timeout=10)
                    if r_runner.status_code == 200:
                        last_online_time = now
                except Exception:
                    pass

            # 3. Авто-поднятие лотов (каждый час проверяем кулдаун)
            if now - last_raise_time > 3600:
                try:
                    m_node = re.search(r'/lots/(\d+)/?', category_url)
                    node_id = m_node.group(1) if m_node else "925"

                    r_cat = session.get(category_url, timeout=10)
                    c_token = ""
                    m_csrf = re.search(r'data-app-data="([^"]+)"', r_cat.text)
                    if m_csrf:
                        try:
                            ap = json.loads(m_csrf.group(1).replace("&quot;", '"'))
                            c_token = ap.get("csrf-token", "")
                        except Exception:
                            pass

                    raise_headers = {"X-Requested-With": "XMLHttpRequest"}
                    if c_token:
                        raise_headers["X-CSRF-Token"] = c_token
                    r_raise = session.post(
                        "https://funpay.com/lots/raise",
                        data={"node_id": node_id, "game_id": ""},
                        headers=raise_headers,
                        timeout=10
                    )
                    if r_raise.status_code == 200:
                        last_raise_time = now
                        try:
                            r_json = r_raise.json()
                            if r_json.get("msg"):
                                print(f"[FUNPAY] [↑] Поднятие лотов: {r_json.get('msg')}")
                        except Exception:
                            pass
                except Exception:
                    pass

            # 4. Авто-выставление и обновление лота (с товарами из done.txt в поле secrets)
            if lot_id and str(lot_id) not in ("0", "12345678"):
                try:
                    r_cat = session.get(category_url, timeout=10)
                    lowest = min_price
                    if r_cat.status_code == 200:
                        prices = []
                        for p_match in re.findall(r'data-price="([\d\.]+)"', r_cat.text):
                            try:
                                pv = float(p_match)
                                if pv > 0.5:
                                    prices.append(pv)
                            except ValueError:
                                pass
                        if prices:
                            lowest = min(prices)
                    target_price = max(min_price, round(lowest - undercut_step, 2))

                    edit_url = f"https://funpay.com/lots/offerEdit?offer={lot_id}"
                    r_edit = session.get(edit_url, timeout=10)
                    if r_edit.status_code == 200:
                        parser = FunPayFormParser()
                        parser.feed(r_edit.text)
                        post_data = dict(parser.inputs)

                        form_csrf_val = post_data.get("csrf_token")
                        if not form_csrf_val:
                            m_csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', r_edit.text)
                            if m_csrf:
                                form_csrf_val = m_csrf.group(1)
                                post_data["csrf_token"] = form_csrf_val

                        m_node = re.search(r'/lots/(\d+)/?', category_url)
                        node_id = m_node.group(1) if m_node else "925"

                        post_data["offer_id"] = str(lot_id)
                        post_data["node_id"] = str(node_id)
                        post_data["price"] = str(target_price)
                        post_data["amount"] = str(len(done_accounts))
                        post_data["auto_delivery"] = "on"
                        post_data["secrets"] = "\n".join(done_accounts)

                        if len(done_accounts) > 0:
                            post_data["active"] = "on"
                        else:
                            post_data.pop("active", None)

                        save_h = {"X-Requested-With": "XMLHttpRequest"}
                        if form_csrf_val:
                            save_h["X-CSRF-Token"] = form_csrf_val
                        r_save = session.post(
                            "https://funpay.com/lots/offerSave",
                            data=post_data,
                            headers=save_h,
                            timeout=10
                        )
                        if r_save.status_code == 200:
                            try:
                                res_json = r_save.json()
                                if res_json.get("done"):
                                    print(f"[FUNPAY] [+] Лот #{lot_id} успешно синхронизирован с FunPay! Цена: {target_price} {cur_fp.get('currency', 'USD')} | В наличии: {len(done_accounts)} шт. (Автовыдача обновлена)")
                                else:
                                    err_msg = res_json.get("error") or res_json.get("errors")
                                    print(f"[FUNPAY] [!] Ошибка сохранения лота #{lot_id}: {err_msg}")
                            except Exception:
                                pass
                except Exception as e:
                    print(f"[FUNPAY] [!] Ошибка обновления лота: {e}")

        except Exception as e:
            pass

        time.sleep(check_interval)


# ==================== ЗАПУСК ПОТОКОВ ====================
if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            # Отключаем модальные окна системных ошибок Windows (SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX)
            ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
            disable_quickedit()
        except Exception:
            pass

    print("==================================================")
    print("       MM2 FARM & FUNPAY SELLER (POOL MODE)       ")
    print("==================================================")

    t_farm = threading.Thread(target=farm_worker, daemon=True)
    t_block = threading.Thread(target=block_queue_worker, daemon=True)
    t_mem = threading.Thread(target=crash_dialog_watcher_worker, daemon=True)
    t_funpay = threading.Thread(target=funpay_worker, daemon=True)

    t_farm.start()
    t_block.start()
    t_mem.start()
    t_funpay.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] Остановка...")
        sys.exit(0)
