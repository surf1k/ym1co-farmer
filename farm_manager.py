import base64
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
BLOCKED_PAIRS_FILE = "blocked_pairs.json"
FUNPAY_UPLOADED_FILE = "funpay_uploaded.json"
FUNPAY_SOLD_FILE = "funpay_sold.txt"

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


def extract_user_info_from_line(line: str):
    """Извлекает username и (если есть) userId из любой строки (FunPay done, CSV, pool, user:pass:cookie:id)."""
    uname = ""
    uid = None
    line = line.strip()
    if not line:
        return "", None

    # 1. Формат FunPay / done.txt: name: User | pass: Password или name: User pass: Password
    m_name = re.search(r'(?:name|login|логин):\s*([^\s,|]+)', line, re.IGNORECASE)
    if m_name:
        uname = m_name.group(1).strip()
        m_id = re.search(r'id:\s*(\d+)', line, re.IGNORECASE)
        if m_id:
            uid = m_id.group(1).strip()
        return uname, uid

    # 2. Формат Real BloxGen CSV: timestamp, username, userId, ...
    if "," in line and not line.startswith("{"):
        pts = [p.strip() for p in line.split(",")]
        if len(pts) >= 2 and pts[0].isdigit():
            uname = pts[1]
            if len(pts) >= 3 and pts[2].isdigit():
                uid = pts[2]
            return uname, uid

    # 3. Формат username:password:cookie:userId или username:::userId или username:password
    if ":" in line:
        pts = [p.strip() for p in line.split(":")]
        uname = pts[0]
        if len(pts) >= 4 and pts[3].isdigit():
            uid = pts[3]
        return uname, uid

    return line, None


def delete_account_completely(username: str, user_id=None, also_done: bool = False):
    """ПОЛНАЯ ЗАЧИСТКА АККАУНТА ОТО ВСЮДА С ПК:
    Вызывается после отправки аккаунта на FunPay / достижения 100 lvl:
    1. Исключает из accounts.txt.
    2. Исключает из accounts_pool.txt.
    3. Исключает из txt.txt (Real CSV / ферма), real_accounts.txt, accounts_raw.txt.
    4. Исключает из всех копий AccountData.json (Roblox Account Manager RAM).
    5. Заносит в ignored_accounts.json (чтобы больше НИКОГДА не возвращался в пул/cookie grabber).
    6. Удаляет из errors.json.
    7. Удаляет из mm2_farm_stats.txt.
    8. Удаляет из bot_ids.json.
    9. Удаляет файлы статистики stats_{userId}.json и stats_{username}.json из воркспейсов Real/Xeno.
    10. Завершает процесс игры (если бот ещё запущен) и убирает из active_pool.json.
    11. Если also_done=True (аккаунт залит на FunPay) — удаляет строку и из done.txt!
    """
    if not username:
        return
    u_lower = username.strip().lower()
    uid_str = str(user_id).strip() if user_id is not None else ""
    print(f"[PURGE] Полная зачистка аккаунта {username} (ID: {uid_str or '?'}) отовсюду с ПК...")

    def get_candidate_paths(base_name):
        return list(dict.fromkeys([
            base_name,
            os.path.join(os.path.dirname(os.path.abspath(__file__)), base_name),
            os.path.join(os.getcwd(), base_name),
        ]))

    # 1. Заносим в ignored_accounts.json (защита от повторного авто-импорта)
    try:
        ignored = load_json(IGNORED_ACCOUNTS_FILE, [])
        if u_lower not in [str(x).lower() for x in ignored]:
            ignored.append(username)
            save_json(IGNORED_ACCOUNTS_FILE, ignored)
    except Exception as e:
        print(f"[PURGE] Ошибка записи в {IGNORED_ACCOUNTS_FILE}: {e}")

    # 2. Удаляем из errors.json
    clear_error(username)

    # 3. Вырезаем из accounts_pool.txt
    for p_file in get_candidate_paths(POOL_ACCOUNTS_FILE):
        if os.path.exists(p_file):
            try:
                with file_lock:
                    with open(p_file, "r", encoding="utf-8") as f:
                        lines = [l for l in f if l.strip()]
                    new_lines = []
                    for l in lines:
                        p = parse_account_line(l)
                        if p and (p.get("username", "").strip().lower() == u_lower or (uid_str and str(p.get("userId", "")).strip() == uid_str)):
                            continue
                        new_lines.append(l)
                    with open(p_file, "w", encoding="utf-8") as f:
                        for l in new_lines:
                            f.write(l.strip() + "\n")
            except Exception as e:
                print(f"[PURGE] Ошибка очистки {p_file}: {e}")

    # 4. Вырезаем из accounts.txt
    for a_file in get_candidate_paths(ACCOUNTS_FILE):
        if os.path.exists(a_file):
            try:
                with file_lock:
                    with open(a_file, "r", encoding="utf-8") as f:
                        lines = [l for l in f if l.strip()]
                    new_lines = []
                    for l in lines:
                        p = parse_account_line(l)
                        if p and (p.get("username", "").strip().lower() == u_lower or (uid_str and str(p.get("userId", "")).strip() == uid_str)):
                            continue
                        new_lines.append(l)
                    with open(a_file, "w", encoding="utf-8") as f:
                        for l in new_lines:
                            f.write(l.strip() + "\n")
            except Exception as e:
                print(f"[PURGE] Ошибка очистки {a_file}: {e}")

    # 5. Вырезаем из txt.txt, real_accounts.txt, accounts_raw.txt
    for raw_name in ["txt.txt", "real_accounts.txt", "accounts_raw.txt"]:
        for t_file in get_candidate_paths(raw_name):
            if os.path.exists(t_file):
                try:
                    with file_lock:
                        with open(t_file, "r", encoding="utf-8") as f:
                            lines = [l for l in f if l.strip()]
                        new_lines = []
                        for l in lines:
                            p = parse_account_line(l)
                            if p and (p.get("username", "").strip().lower() == u_lower or (uid_str and str(p.get("userId", "")).strip() == uid_str)):
                                continue
                            if "," in l:
                                pts = [x.strip() for x in l.split(",")]
                                if len(pts) >= 2 and pts[1].lower() == u_lower:
                                    continue
                                if len(pts) >= 3 and uid_str and pts[2] == uid_str:
                                    continue
                            new_lines.append(l)
                        with open(t_file, "w", encoding="utf-8") as f:
                            for l in new_lines:
                                f.write(l.strip() + "\n")
                except Exception:
                    pass

    # 6. Вырезаем из всех копий AccountData.json (RAM)
    try:
        remove_account_from_ram(username, user_id=user_id)
    except Exception as e:
        print(f"[PURGE] Ошибка удаления из RAM: {e}")

    # 7. Вырезаем из mm2_farm_stats.txt
    for s_file in get_candidate_paths(MM2_STATS_FILE):
        if os.path.exists(s_file):
            try:
                with file_lock:
                    with open(s_file, "r", encoding="utf-8") as f:
                        lines = [l for l in f if l.strip()]
                    new_lines = [l for l in lines if not re.search(rf"\bUser:\s*{re.escape(username)}\b", l, re.IGNORECASE)]
                    with open(s_file, "w", encoding="utf-8") as f:
                        for l in new_lines:
                            f.write(l.strip() + "\n")
            except Exception:
                pass

    # 8. Удаляем из bot_ids.json
    for b_file in get_candidate_paths("bot_ids.json"):
        if os.path.exists(b_file):
            try:
                b_ids = load_json(b_file, {})
                changed = False
                for k in list(b_ids.keys()):
                    if k.lower() == u_lower or (uid_str and str(b_ids[k]).strip() == uid_str):
                        del b_ids[k]
                        changed = True
                if changed:
                    save_json(b_file, b_ids)
            except Exception:
                pass

    # 9. Удаляем локальные файлы статистики из воркспейсов Real и Xeno
    try:
        cand_ws = [
            find_executor_workspace_path(),
            os.path.expandvars(r"%LOCALAPPDATA%\Real\workspace"),
            os.path.expandvars(r"%LOCALAPPDATA%\Xeno\workspace"),
            r"C:\Users\DDDen\AppData\Local\Real\workspace",
            r"C:\Users\DDDen\AppData\Local\Xeno\workspace",
        ]
        for ws_dir in set(cand_ws):
            if not ws_dir or not os.path.isdir(ws_dir):
                continue
            for fname in [f"stats_{uid_str}.json", f"stats_{username}.json", f"stats_{u_lower}.json"]:
                if not fname or fname.startswith("stats_."):
                    continue
                f_path = os.path.join(ws_dir, fname)
                if os.path.exists(f_path):
                    try:
                        os.remove(f_path)
                    except Exception:
                        pass
    except Exception:
        pass

    # 10. Завершаем активный процесс игры (если бот ещё в игре) и убираем из active_pool.json
    try:
        active_pool = load_json(ACTIVE_POOL_FILE, [])
        for b in active_pool:
            if b.get("username", "").strip().lower() == u_lower or (uid_str and str(b.get("userId", "")).strip() == uid_str):
                pid = b.get("pid")
                if pid:
                    kill_pid(pid)
        active_pool = [
            b for b in active_pool
            if b.get("username", "").strip().lower() != u_lower
            and (not uid_str or str(b.get("userId", "")).strip() != uid_str)
        ]
        save_json(ACTIVE_POOL_FILE, active_pool)
    except Exception as e:
        print(f"[PURGE] Ошибка очистки {ACTIVE_POOL_FILE}: {e}")

    # 11. Если also_done=True (аккаунт залит на FunPay) — удаляем и из done.txt!
    if also_done:
        for d_file in get_candidate_paths(DONE_FILE):
            if os.path.exists(d_file):
                try:
                    with file_lock:
                        with open(d_file, "r", encoding="utf-8") as f:
                            lines = [l for l in f if l.strip()]
                        new_lines = [
                            l for l in lines
                            if not re.search(rf"\bname:\s*{re.escape(username)}\b", l, re.IGNORECASE)
                            and not l.lower().startswith(u_lower + ":")
                            and not ("," in l and len(l.split(",")) >= 2 and l.split(",")[1].strip().lower() == u_lower)
                        ]
                        with open(d_file, "w", encoding="utf-8") as f:
                            for l in new_lines:
                                f.write(l.strip() + "\n")
                except Exception:
                    pass

    print(f"[PURGE] [✓] Аккаунт {username} успешно удалён отовсюду с ПК!")


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

        lvl = max(stats.get("level", 0), b.get("max_level", 0))
        bag = stats.get("bag", 0)
        max_bag = stats.get("maxBag", 40)
        coins = max(stats.get("coins", 0), b.get("max_coins", 0))
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

    cur_cfg = load_json(CONFIG_FILE, CFG)
    farm_cfg = cur_cfg.get("farm", {})
    return {
        "farm_enabled": farm_enabled.is_set(),
        "bots": bots_data,
        "errors": errors,
        "done_count": done_count,
        "pool_count": pool_count,
        "total_coins": total_farmed_coins,
        "active_bots_count": len(bots_data),
        "max_bots": cur_cfg.get("hardware_limits", {}).get("absolute_max_bots_safety_cap", 50),
        "target_level": farm_cfg.get("target_level", 100),
        "target_coins": farm_cfg.get("target_coins", 40000),
        "goal_mode": farm_cfg.get("goal_mode", "both"),
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


def remove_account_from_ram(username, user_id=None):
    candidates = [
        find_ram_account_data_path(),
        r"C:\Users\DDDen\Desktop\farm\RAM\AccountData.json",
        r"C:\Users\DDDen\Desktop\RAM\AccountData.json",
        os.path.expandvars(r"%USERPROFILE%\Desktop\farm\RAM\AccountData.json"),
        os.path.expandvars(r"%USERPROFILE%\Desktop\RAM\AccountData.json"),
        os.path.expandvars(r"%USERPROFILE%\Downloads\RAM\AccountData.json"),
        os.path.join(os.getcwd(), "RAM", "AccountData.json"),
        os.path.join(os.getcwd(), "AccountData.json"),
    ]
    for d in glob.glob(r"C:\Users\*\Desktop\*\RAM\AccountData.json"):
        candidates.append(d)
    for d in glob.glob(r"C:\Users\*\Desktop\RAM\AccountData.json"):
        candidates.append(d)

    u_lower = username.strip().lower() if username else ""
    uid_str = str(user_id).strip() if user_id is not None else ""

    with file_lock:
        for ram_path in set(candidates):
            if not ram_path or not os.path.isfile(ram_path):
                continue
            try:
                with open(ram_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    orig_len = len(data)
                    new_data = [
                        item
                        for item in data
                        if (item.get("Username") or "").strip().lower() != u_lower
                        and (item.get("Name") or "").strip().lower() != u_lower
                        and (not uid_str or str(item.get("UserId", "")).strip() != uid_str)
                    ]
                    if len(new_data) != orig_len:
                        with open(ram_path, "w", encoding="utf-8") as f:
                            json.dump(new_data, f, indent=4)
                        print(f"[RAM] [-] Аккаунт {username} вычищен из RAM ({ram_path}).")
                elif isinstance(data, dict):
                    to_del = [
                        k for k, item in data.items()
                        if isinstance(item, dict) and (
                            (item.get("Username") or "").strip().lower() == u_lower
                            or (uid_str and str(item.get("UserId", "")).strip() == uid_str)
                        )
                    ]
                    if to_del:
                        for k in to_del:
                            del data[k]
                        with open(ram_path, "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=4)
                        print(f"[RAM] [-] Аккаунт {username} вычищен из RAM ({ram_path}).")
            except Exception:
                pass


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


def extract_uid_from_cookie(cookie: str) -> int:
    """Извлекает userId прямо из base64 protobuf полезной нагрузки куки .ROBLOSECURITY без запросов к сети."""
    try:
        if not cookie or "_|" not in cookie:
            return 0
        raw = cookie.split("|_")[-1].split(".")[0]
        raw += "=" * ((4 - len(raw) % 4) % 4)
        decoded = base64.b64decode(raw)
        m = re.search(rb"uid\x12\x0b(\d{6,})", decoded) or re.search(rb"uid\x12\x0c(\d{6,})", decoded) or re.search(rb"uid[^\d]*(\d{6,})", decoded)
        if m:
            return int(m.group(1).decode())
    except Exception:
        pass
    return 0


def load_blocked_pairs() -> set:
    data = load_json(BLOCKED_PAIRS_FILE, [])
    if isinstance(data, list):
        return set(data)
    return set()


def save_blocked_pairs(pairs: set):
    save_json(BLOCKED_PAIRS_FILE, sorted(list(pairs)))


# ==================== МОМЕНТАЛЬНАЯ БЛОКИРОВКА ПРИ ВСТРЕЧЕ (ИДЕАЛЬНЫЙ CSRF) ====================
def get_all_known_bot_credentials():
    """Собирает карту {UserId: cookie} и {Username_lower: cookie} со всех файлов пула и аккаунтов."""
    cookie_by_id = {}
    cookie_by_name = {}
    all_ids = set()
    all_names = set()

    files = [ACTIVE_POOL_FILE, POOL_ACCOUNTS_FILE, ACCOUNTS_FILE, "txt.txt"]
    for fn in files:
        if not os.path.exists(fn):
            continue
        try:
            if fn.endswith(".json"):
                data = load_json(fn, [])
                for b in data:
                    c = b.get("cookie")
                    uid = b.get("userId") or (extract_uid_from_cookie(c) if c else 0)
                    u = (b.get("username") or "").strip().lower()
                    if uid:
                        all_ids.add(int(uid))
                        if c: cookie_by_id[int(uid)] = c
                    if u:
                        all_names.add(u)
                        if c: cookie_by_name[u] = c
            else:
                with open(fn, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parsed = parse_account_line(line)
                        if parsed:
                            u = (parsed.get("username") or "").strip().lower()
                            c = parsed.get("cookie") or ""
                            uid = parsed.get("userId") or (extract_uid_from_cookie(c) if c else 0)
                            if uid:
                                all_ids.add(int(uid))
                                if c: cookie_by_id[int(uid)] = c
                            if u:
                                all_names.add(u)
                                if c: cookie_by_name[u] = c
        except Exception:
            pass

    return cookie_by_id, cookie_by_name, sorted(list(all_ids)), sorted(list(all_names))


def sync_bot_ids(user_id=None):
    """Синхронизирует bot_ids.json и bot_names.json во все возможные воркспейсы всех экзекуторов."""
    _, _, all_ids, all_names = get_all_known_bot_credentials()
    existing_ids = load_json(BOT_IDS_FILE, [])
    for eid in existing_ids:
        if eid not in all_ids:
            all_ids.append(eid)
    if user_id and user_id not in all_ids:
        all_ids.append(user_id)

    save_json(BOT_IDS_FILE, all_ids)
    save_json("bot_names.json", all_names)

    ws_targets = set()
    ws_main = get_workspace_path()
    if ws_main:
        ws_targets.add(ws_main)
    for c in get_candidate_workspace_paths():
        if os.path.isdir(c):
            ws_targets.add(c)

    for ws_path in ws_targets:
        try:
            target_ids = os.path.join(ws_path, "bot_ids.json")
            target_names = os.path.join(ws_path, "bot_names.json")
            with file_lock:
                with open(target_ids, "w", encoding="utf-8") as f:
                    json.dump(all_ids, f)
                with open(target_names, "w", encoding="utf-8") as f:
                    json.dump(all_names, f)
        except Exception as e:
            pass


def block_user(cookie, target_id, session=None, csrf=None):
    """
    Официальный безопасный REST API метод блокировки пользователя в Roblox.
    Не использует браузер, не триггерит капчи и выполняется мгновенно.
    """
    try:
        if not target_id or int(target_id) <= 0:
            return False
            
        if session is None:
            session = requests.Session()
            
        clean_cookie = cookie.strip().strip('"').strip("'")
        session.cookies[".ROBLOSECURITY"] = clean_cookie
        session.cookies["RBXEventTrackerV2"] = "browserid=1789324524369004"
        session.cookies["rbx-ip2"] = "1"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Origin": "https://www.roblox.com",
            "Referer": "https://www.roblox.com/"
        }

        if not csrf:
            r_csrf = session.post("https://auth.roblox.com/v2/logout", headers=headers, timeout=8)
            csrf = r_csrf.headers.get("x-csrf-token")
            if not csrf:
                return False

        headers["X-CSRF-TOKEN"] = csrf
        headers["Content-Type"] = "application/json"
        url = f"https://apis.roblox.com/user-blocking-api/v1/users/{target_id}/block-user"
        res = session.post(url, headers=headers, json={}, timeout=8)
        
        # 200 = успешно заблокирован, 400 с телом "1" или "already" = уже заблокирован
        if res.status_code == 200:
            return True
        t_clean = res.text.strip()
        if res.status_code == 400 and (t_clean == "1" or "already" in t_clean.lower() or '"code":1' in t_clean.replace(" ", "")):
            return True
        elif res.status_code == 429:
            time.sleep(3.0)
            res2 = session.post(url, headers=headers, json={}, timeout=8)
            t2 = res2.text.strip()
            if res2.status_code == 200 or (res2.status_code == 400 and (t2 == "1" or "already" in t2.lower())):
                return True
        return False
    except Exception:
        return False


def ensure_mutual_blocks_for_bot(bot_entry):
    """
    Гарантирует, что данный бот взаимно заблокировал всех остальных ботов фермы
    ДО захода на сервер MM2, исключая попадание в один матчмейкинг.
    """
    my_cookie = bot_entry.get("cookie", "").strip()
    if not my_cookie:
        return
    
    my_uid = bot_entry.get("userId") or extract_uid_from_cookie(my_cookie)
    if not my_uid:
        return
    bot_entry["userId"] = my_uid

    cookie_by_id, cookie_by_name, all_ids, all_names = get_all_known_bot_credentials()
    blocked_pairs = load_blocked_pairs()
    changed = False

    other_uids = [uid for uid in all_ids if uid and uid != my_uid]
    if not other_uids:
        return

    session_me = requests.Session()
    session_me.cookies[".ROBLOSECURITY"] = my_cookie
    session_me.cookies["RBXEventTrackerV2"] = "browserid=1789324524369004"
    session_me.cookies["rbx-ip2"] = "1"
    headers_me = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Origin": "https://www.roblox.com",
        "Referer": "https://www.roblox.com/"
    }
    r_csrf = session_me.post("https://auth.roblox.com/v2/logout", headers=headers_me, timeout=8)
    csrf_me = r_csrf.headers.get("x-csrf-token", "")

    blocked_now = 0
    for target_id in other_uids:
        pair_key = f"{my_uid}:{target_id}"
        if pair_key in blocked_pairs:
            continue
            
        if block_user(my_cookie, target_id, session=session_me, csrf=csrf_me):
            blocked_pairs.add(pair_key)
            changed = True
            blocked_now += 1
            time.sleep(0.5)

    # Взаимная блокировка от других ботов к этому боту
    for target_id in other_uids:
        pair_rev = f"{target_id}:{my_uid}"
        if pair_rev in blocked_pairs:
            continue
            
        target_cookie = cookie_by_id.get(target_id)
        if target_cookie:
            if block_user(target_cookie, my_uid):
                blocked_pairs.add(pair_rev)
                changed = True
                time.sleep(0.5)

    if changed:
        save_blocked_pairs(blocked_pairs)
        
    if blocked_now > 0:
        print(f"[BLOCK] [✓] Бот {bot_entry.get('username')} успешно взаимно заблокировал {blocked_now} ботов перед входом в MM2.")


def auto_pool_blocker_worker():
    """
    Фоновый воркер, который непрерывно поддерживает взаимную блокировку всей фермы.
    Сверяет всех ботов из базы и пула с blocked_pairs.json.
    Работает тихо в фоне, не нагружает CPU, защищен от рейт-лимитов и капчи.
    """
    time.sleep(3)
    while True:
        try:
            if farm_enabled.is_set():
                cookie_by_id, cookie_by_name, all_ids, all_names = get_all_known_bot_credentials()
                blocked_pairs = load_blocked_pairs()
                changed = False

                for my_uid in all_ids:
                    if not my_uid or not farm_enabled.is_set():
                        continue
                    my_cookie = cookie_by_id.get(my_uid)
                    if not my_cookie:
                        continue

                    other_uids = [u for u in all_ids if u and u != my_uid and f"{my_uid}:{u}" not in blocked_pairs]
                    if not other_uids:
                        continue

                    session = requests.Session()
                    session.cookies[".ROBLOSECURITY"] = my_cookie
                    session.cookies["RBXEventTrackerV2"] = "browserid=1789324524369004"
                    session.cookies["rbx-ip2"] = "1"
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                        "Origin": "https://www.roblox.com",
                        "Referer": "https://www.roblox.com/"
                    }
                    try:
                        r_csrf = session.post("https://auth.roblox.com/v2/logout", headers=headers, timeout=8)
                        csrf = r_csrf.headers.get("x-csrf-token", "")
                    except Exception:
                        csrf = ""

                    if not csrf:
                        continue

                    for target_uid in other_uids:
                        pair_key = f"{my_uid}:{target_uid}"
                        if pair_key in blocked_pairs:
                            continue

                        url = f"https://apis.roblox.com/user-blocking-api/v1/users/{target_uid}/block-user"
                        headers["X-CSRF-TOKEN"] = csrf
                        headers["Content-Type"] = "application/json"
                        try:
                            res = session.post(url, headers=headers, json={}, timeout=8)
                            t_clean = res.text.strip()
                            if res.status_code == 200 or (res.status_code == 400 and (t_clean == "1" or "already" in t_clean.lower())):
                                blocked_pairs.add(pair_key)
                                save_blocked_pairs(blocked_pairs)
                                time.sleep(0.8)
                            elif res.status_code == 403 and "moderated" in t_clean.lower():
                                # Аккаунт в капче ('User is moderated'), переходим к следующему
                                break
                            elif res.status_code == 429:
                                time.sleep(15.0)
                                break
                        except Exception:
                            pass
        except Exception:
            pass
        time.sleep(60)


def block_queue_worker():
    """Читает запросы на бан от Lua-скрипта и моментально банит столкнувшихся ботов"""
    ws = get_workspace_path()
    if not ws:
        return
    queue_file = os.path.join(ws, "block_queue.txt")

    print("[*] Обработчик мгновенных банов при столкновении запущен...")

    while True:
        try:
            # Периодически обновляем списки ботов для всех воркспейсов
            sync_bot_ids()

            if os.path.exists(queue_file):
                with file_lock:
                    with open(queue_file, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    # Очищаем файл после чтения
                    open(queue_file, "w").close()

                if lines:
                    cookie_by_id, cookie_by_name, _, _ = get_all_known_bot_credentials()
                    blocked_pairs = load_blocked_pairs()
                    bp_changed = False

                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            req = json.loads(line)
                            me_id = req.get("me")
                            target_id = req.get("target")
                            me_name = (req.get("meName") or "").strip().lower()
                            target_name = (req.get("targetName") or "").strip().lower()

                            cookie_me = cookie_by_id.get(me_id) or cookie_by_name.get(me_name)
                            cookie_target = cookie_by_id.get(target_id) or cookie_by_name.get(target_name)

                            # Взаимный бан через официальный API Roblox
                            if cookie_me and target_id:
                                if block_user(cookie_me, target_id):
                                    print(f"[БАН] [✓] Бот {me_name or me_id} забанил {target_name or target_id}!")
                                    blocked_pairs.add(f"{me_id}:{target_id}")
                                    bp_changed = True
                            if cookie_target and me_id:
                                if block_user(cookie_target, me_id):
                                    print(f"[БАН] [✓] Бот {target_name or target_id} забанил {me_name or me_id}!")
                                    blocked_pairs.add(f"{target_id}:{me_id}")
                                    bp_changed = True
                        except Exception as e:
                            pass
                    if bp_changed:
                        save_blocked_pairs(blocked_pairs)
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
    if not line or line.startswith("#"):
        return None

    # Поддержка CSV экспорта от Real / BloxGen:
    # generatedAt,username,robloxId,type,cost,region,createdAt,source,flagged
    if line.startswith("generatedAt,"):
        return None
    if "," in line and ":" not in line:
        c_parts = [p.strip() for p in line.split(",")]
        if len(c_parts) >= 3 and c_parts[2].isdigit():
            u = c_parts[1]
            uid = int(c_parts[2])
            return {
                "username": u,
                "password": "",
                "cookie": "",
                "userId": uid,
            }

    # Форматы с двоеточием:
    # 1) username:password:cookie:userid
    # 2) username:password:cookie
    # 3) username:cookie
    # 4) username:::userid
    # 5) username:password
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
    if not uid and cookie:
        uid = extract_uid_from_cookie(cookie)

    if not u:
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
    0. Real Storage (%LOCALAPPDATA%/Real — авто-куки на полном автомате)
    1. Roblox Account Manager (AccountData.json)
    2. accounts.txt
    3. accounts_pool.txt
    Гарантирует, что все незавершенные аккаунты (не 100 lvl) находятся в очереди пула.
    """
    try:
        import cookie_grabber
        cookie_grabber.scan_real_storage_for_all_accounts()
    except Exception:
        pass

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
    cookie = bot_entry.get("cookie", "").strip()
    ticket = get_auth_ticket(cookie) if cookie else None
    if not ticket and bot_entry.get("password"):
        print(f"[FARM] [*] Куки {bot_entry['username']} истекла или отсутствует. Авто-получение новой куки через Playwright...")
        try:
            import cookie_grabber
            ok, new_c, new_uid, _ = cookie_grabber.login_and_get_cookie(bot_entry["username"], bot_entry["password"], headless=True)
            if ok and new_c:
                bot_entry["cookie"] = new_c
                if new_uid:
                    bot_entry["userId"] = new_uid
                ticket = get_auth_ticket(new_c)
                print(f"[FARM] [✓] Новая куки для {bot_entry['username']} получена и активирована!")
        except Exception:
            pass

    if not ticket:
        err_msg = "Ошибка авторизации: нет куки или не удалось получить auth-тикет (Запустите '⚡ АВТО-КУКИ ВСЕГО')"
        print(
            f"[FARM] [-] Запуск отменён: у {bot_entry['username']} отсутствует валидная куки. Запустите '⚡ АВТО-КУКИ ВСЕГО'!"
        )
        record_failure(bot_entry["username"], bot_entry.get("password", ""), err_msg, bot_entry.get("userId"), threshold=5)
        return None

    # Гарантированная взаимная блокировка со всеми остальными ботами фермы в фоне (не задерживая запуск):
    try:
        threading.Thread(target=ensure_mutual_blocks_for_bot, args=(bot_entry,), daemon=True).start()
    except Exception as e:
        print(f"[BLOCK] [!] Предупреждение при запуске фоновой блокировки для {bot_entry.get('username')}: {e}")

    place_id = CFG["farm"].get("place_id", 142823291)
    exe_path = find_roblox_executable()

    if not exe_path or not os.path.exists(exe_path):
        print(f"[FARM] [-] Ошибка: исполняемый файл Roblox не найден: {exe_path}")
        return None

    # Получаем СВЕЖИЙ auth-тикет СТРОГО перед самым вызовом Popen (срок жизни тикета в Roblox всего 15-30с)
    fresh_ticket = get_auth_ticket(cookie) or ticket
    if not fresh_ticket:
        print(f"[FARM] [-] Не удалось обновить auth-тикет прямо перед запуском {bot_entry['username']}.")
        return None

    job_id = get_distinct_public_server(place_id, used_server_jobs)
    if job_id:
        join_url = f"https://assetgame.roblox.com/game/PlaceLauncher.ashx?request=RequestGameJob&placeId={place_id}&gameId={job_id}"
        print(f"[FARM] [*] Выделен отдельный публичный сервер {job_id[:8]}... (исключаем коллизии)")
    else:
        join_url = f"https://assetgame.roblox.com/game/PlaceLauncher.ashx?request=RequestGame&placeId={place_id}"

    cmd = [exe_path, "--app", "-t", fresh_ticket, "-j", join_url]

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
    target_lvl = CFG.get("farm", {}).get("target_level", 100)
    target_coins = CFG.get("farm", {}).get("target_coins", 40000)
    safety_cap = CFG.get("hardware_limits", {}).get("absolute_max_bots_safety_cap", 50)
    check_interval = int(CFG.get("farm", {}).get("check_stats_interval_sec", 10))
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
                bot_coins = 0
                stats_status = None

                if os.path.exists(stats_file):
                    try:
                        with open(stats_file, "r", encoding="utf-8") as sf:
                            st = json.load(sf)
                            bot_lvl = st.get("level", 0)
                            bot_coins = st.get("coins", 0)
                            stats_status = st.get("status")
                    except Exception:
                        pass

                # Обновляем максимальные значения для сессии
                bot_lvl = max(bot_lvl, bot.get("max_level", 0))
                bot["max_level"] = bot_lvl
                bot_coins = max(bot_coins, bot.get("max_coins", 0))
                bot["max_coins"] = bot_coins

                cur_cfg = load_json(CONFIG_FILE, CFG)
                farm_cfg = cur_cfg.get("farm", {})
                target_lvl = farm_cfg.get("target_level", 100)
                target_coins = farm_cfg.get("target_coins", 40000)
                goal_mode = str(farm_cfg.get("goal_mode", "both")).strip().lower()

                # Проверяем цель согласно настройке режима:
                # 1. "level" / "только по лвл"
                # 2. "coins" / "price" / "только по цене / монетам"
                # 3. "both" / "оба" (уровень И монеты)
                if goal_mode in ("level", "lvl", "уровень", "лвл", "только по лвл"):
                    goal_reached = (bot_lvl >= target_lvl)
                    goal_desc = f"{bot_lvl}/{target_lvl} lvl (Режим: Только по ЛВЛ)"
                elif goal_mode in ("coins", "price", "money", "монеты", "цена", "только по цене", "только по монетам"):
                    goal_reached = (bot_coins >= target_coins)
                    goal_desc = f"{bot_coins:,}/{target_coins:,} coins (Режим: Только по ЦЕНЕ/МОНЕТАМ)"
                else:  # "both", "оба"
                    goal_reached = (bot_lvl >= target_lvl and bot_coins >= target_coins) if target_coins > 0 else (bot_lvl >= target_lvl)
                    goal_desc = f"{bot_lvl}/{target_lvl} lvl & {bot_coins:,}/{target_coins:,} coins (Режим: ОБА)"

                if goal_reached:
                    print(
                        f"\n[FARM] [★] ГОТОВ К ПРОДАЖЕ: {bot['username']} | {goal_desc}"
                    )
                    clear_error(bot["username"])

                    with file_lock:
                        with open(DONE_FILE, "a", encoding="utf-8") as df:
                            # Формат строго для FunPay: name: nick | pass: password (без лишних запятых и пометок, чтобы покупатели не путались)
                            df.write(
                                f"name: {bot['username']} | pass: {bot['password']}\n"
                            )

                    # Полная зачистка аккаунта отовсюду с ПК (из пула, accounts.txt, txt.txt, RAM, стат), кроме done.txt
                    delete_account_completely(bot["username"], user_id=user_id, also_done=False)
                    print(f"[FARM] [-] Аккаунт {bot['username']} зачищен из пула и отправлен в {DONE_FILE}. Слот свободен.")

                    # АВТОМАТИЧЕСКАЯ ЗАЛИВКА НА FUNPAY: ВЫКИНУЛО -> ПРОВЕРИЛО -> ЕСЛИ ДА СНЕСЛО -> ЕСЛИ НЕТ ДИАГНОСТИКА
                    print(f"[FARM] [⚡] Запуск мгновенной авто-выгрузки готового аккаунта {bot['username']} на FunPay...")
                    threading.Thread(target=sync_and_verify_funpay_lot, daemon=True).start()
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

            # Запись файла активного прогресса: ник, лвл, баланс монет и объективный трекинг мешка
            active_lines = []
            for b in updated_pool:
                uid = b.get("userId")
                uname = b.get("username")
                sf = find_stats_file(uid)
                lvl = b.get("max_level", 0)
                coins = b.get("max_coins", 0)
                bag = 0
                max_bag = 40
                if sf and os.path.exists(sf):
                    try:
                        with open(sf, "r", encoding="utf-8") as _f:
                            st = json.load(_f)
                            lvl = max(lvl, st.get("level", 0))
                            coins = max(coins, st.get("coins", 0))
                            bag = st.get("bag", 0)
                            max_bag = st.get("maxBag", 40)
                    except Exception:
                        pass
                active_lines.append(f"User: {uname} | Level: {lvl} | Coins: {coins:,} | Bag: {bag}/{max_bag}\n")

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
    """Считывает уникальные строки готовых аккаунтов (100 lvl) из done.txt во всех возможных папках, исключая уже залитые на FunPay или проигнорированные."""
    candidates = list(dict.fromkeys([
        DONE_FILE,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), DONE_FILE),
        os.path.join(os.getcwd(), DONE_FILE),
    ]))
    uploaded_history = [str(x).strip().lower() for x in load_json(FUNPAY_UPLOADED_FILE, [])]
    ignored = [str(x).strip().lower() for x in load_json(IGNORED_ACCOUNTS_FILE, [])]
    blacklisted = set(uploaded_history + ignored)

    all_lines = []
    for c in candidates:
        if os.path.exists(c):
            cleaned_file = False
            valid_file_lines = []
            try:
                with file_lock:
                    with open(c, "r", encoding="utf-8") as df:
                        for l in df:
                            ls = l.strip()
                            if not ls:
                                continue
                            u_name, _ = extract_user_info_from_line(ls)
                            if u_name and u_name.lower() in blacklisted:
                                # Аккаунт уже был выгружен/продан на FunPay - удаляем из done.txt
                                cleaned_file = True
                                continue
                            valid_file_lines.append(ls)
                            if ls not in all_lines:
                                all_lines.append(ls)
                    if cleaned_file:
                        with open(c, "w", encoding="utf-8") as df:
                            for vl in valid_file_lines:
                                df.write(vl + "\n")
            except Exception:
                pass
    return all_lines


def format_funpay_error(res_json, raw_text: str) -> str:
    """Форматирует ошибки FunPay в понятный диагностический текст на русском."""
    if not res_json:
        lower = raw_text.lower()
        if "login" in lower:
            return "Сессия истекла (FunPay требует повторного логина)."
        if "captcha" in lower or "g-recaptcha" in lower or "cf-mitigated" in lower:
            return "FunPay заблокировал запрос капчей или Cloudflare защитой."
        if "phone" in lower or "телефон" in lower or "sms" in lower:
            return "FunPay требует привязки или подтверждения номера телефона / 2FA."
        return f"Неизвестный ответ сервера (HTTP): {raw_text[:200]}"

    err = res_json.get("error")
    errs = res_json.get("errors")
    msg = res_json.get("msg")

    reasons = []
    if isinstance(err, str) and err:
        reasons.append(err)
    if isinstance(msg, str) and msg:
        reasons.append(msg)
    if isinstance(errs, list):
        for e in errs:
            if isinstance(e, str):
                reasons.append(e)
            elif isinstance(e, dict):
                reasons.extend(str(v) for v in e.values() if v)
    elif isinstance(errs, dict):
        for k, v in errs.items():
            if isinstance(v, list):
                reasons.append(f"{k}: {', '.join(str(x) for x in v)}")
            else:
                reasons.append(f"{k}: {v}")

    if reasons:
        return " | ".join(reasons)
    return "FunPay отклонил сохранение лота без детальной ошибки."


funpay_sync_lock = threading.Lock()
funpay_last_status = {"status": "IDLE", "msg": "Модуль готов к работе", "timestamp": 0}


def sync_and_verify_funpay_lot(session=None, cur_cfg=None):
    """
    ПОЛНЫЙ АВТОМАТ ВЫГРУЗКИ, ВЕРИФИКАЦИИ И ЗАЧИСТКИ FUNPAY:
    1. Автоматически берет аккаунты из done.txt.
    2. Выгружает на FunPay в поле secrets лота с автовыдачей.
    3. ПРОВЕРЯЕТ: повторно запрашивает лот и верифицирует, что аккаунты РЕАЛЬНО там есть.
    4. ЕСЛИ ДА — СНЕСЛО: аккаунты полностью вычищаются отовсюду с ПК (done.txt, RAM, pool, txt, stats).
    5. ЕСЛИ НЕТ — ПРОВЕРЯЕТ ПОЧЕМУ НЕТ: глубокая диагностика причин сбоя, аккаунты сохраняются в done.txt!
    """
    global funpay_last_status

    if not funpay_sync_lock.acquire(timeout=15):
        return False, "Синхронизация с FunPay уже выполняется другим процессом."

    try:
        done_accounts = get_done_accounts()
        if not done_accounts:
            funpay_last_status = {"status": "OK", "msg": "Нет новых готовых аккаунтов в done.txt", "timestamp": time.time()}
            return True, "done.txt пуст."

        if cur_cfg is None:
            cur_cfg = load_json(CONFIG_FILE, CFG)
        cur_fp = cur_cfg.get("funpay", {})

        if not cur_fp.get("enabled", False):
            msg = (
                f"[FUNPAY] [⚠️ ВНИМАНИЕ] В done.txt найдено {len(done_accounts)} готовых аккаунтов, "
                f"но модуль FunPay выключен (\"enabled\": false) в config.json! "
                f"Зачистка отменена, данные сохранены в done.txt."
            )
            print(msg)
            funpay_last_status = {"status": "DISABLED", "msg": msg, "timestamp": time.time()}
            return False, msg

        golden_key = cur_fp.get("golden_key", "").strip()
        if not golden_key or golden_key in ("ВАШ_GOLDEN_KEY", "YOUR_FUNPAY_GOLDEN_KEY"):
            msg = (
                f"[FUNPAY] [❌ ДИАГНОСТИКА: НЕ ЗАДАН GOLDEN_KEY] В config.json не указан golden_key! "
                f"FunPay не может принять {len(done_accounts)} аккаунтов. "
                f"Зачистка отменена, данные в безопасности в done.txt."
            )
            print(msg)
            funpay_last_status = {"status": "ERROR_AUTH", "msg": msg, "timestamp": time.time()}
            return False, msg

        lot_id = cur_fp.get("lot_id")
        if not lot_id or str(lot_id) in ("0", "12345678"):
            msg = (
                f"[FUNPAY] [❌ ДИАГНОСТИКА: НЕ ЗАДАН LOT_ID] В config.json не указан действительный ID лота! "
                f"Зачистка отменена, {len(done_accounts)} аккаунтов в done.txt."
            )
            print(msg)
            funpay_last_status = {"status": "ERROR_CONFIG", "msg": msg, "timestamp": time.time()}
            return False, msg

        # Создаем или используем существующую сессию
        if session is None:
            session = requests.Session()
            session.headers.update({
                "User-Agent": cur_fp.get(
                    "user_agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            })
        session.cookies.set("golden_key", golden_key, domain=".funpay.com")

        # ШАГ 1: Проверка сессии и авторизации на FunPay
        try:
            r_auth = session.get("https://funpay.com/", timeout=10)
            if r_auth.status_code in (403, 503):
                msg = (
                    f"[FUNPAY] [❌ ДИАГНОСТИКА: CLOUDFLARE БЛОК] FunPay вернул HTTP {r_auth.status_code}. "
                    f"Защита Cloudflare заблокировала запрос. Зачистка отменена, аккаунты сохранены в done.txt."
                )
                print(msg)
                funpay_last_status = {"status": "CLOUDFLARE", "msg": msg, "timestamp": time.time()}
                return False, msg

            if "/account/login" in r_auth.url or (
                "logout" not in r_auth.text and "user-link" not in r_auth.text and "data-app-data" not in r_auth.text
            ):
                msg = (
                    f"[FUNPAY] [❌ ДИАГНОСТИКА: СЕССИЯ НЕ АВТОРИЗОВАНА] Токен golden_key недействителен или протух! "
                    f"FunPay требует входа в аккаунт. Обновите golden_key в config.json. "
                    f"Зачистка отменена, {len(done_accounts)} аккаунтов в безопасности в done.txt."
                )
                print(msg)
                funpay_last_status = {"status": "ERROR_TOKEN", "msg": msg, "timestamp": time.time()}
                return False, msg
        except Exception as e:
            msg = f"[FUNPAY] [❌ ДИАГНОСТИКА: ОШИБКА СЕТИ] Не удалось связаться с FunPay: {e}. Зачистка отменена."
            print(msg)
            funpay_last_status = {"status": "ERROR_NET", "msg": msg, "timestamp": time.time()}
            return False, msg

        # ШАГ 2: Загрузка формы лота offerEdit
        edit_url = f"https://funpay.com/lots/offerEdit?offer={lot_id}"
        try:
            r_edit = session.get(edit_url, timeout=10)
        except Exception as e:
            msg = f"[FUNPAY] [❌ ДИАГНОСТИКА: СЕТЕВОЙ ТАЙМАУТ] Не удалось открыть форму лота #{lot_id}: {e}"
            print(msg)
            funpay_last_status = {"status": "ERROR_NET", "msg": msg, "timestamp": time.time()}
            return False, msg

        if r_edit.status_code != 200:
            if r_edit.status_code == 404:
                msg = f"[FUNPAY] [❌ ДИАГНОСТИКА: ЛОТ НЕ НАЙДЕН] Лот #{lot_id} не существует (HTTP 404)! Проверьте lot_id."
            elif r_edit.status_code == 403:
                msg = f"[FUNPAY] [❌ ДИАГНОСТИКА: НЕТ ПРАВ] У вашего аккаунта FunPay нет прав на лот #{lot_id} (HTTP 403)!"
            else:
                msg = f"[FUNPAY] [❌ ДИАГНОСТИКА: СБОЙ СЕРВЕРА] FunPay вернул HTTP {r_edit.status_code} при открытии лота #{lot_id}."
            print(msg)
            funpay_last_status = {"status": "ERROR_LOT", "msg": msg, "timestamp": time.time()}
            return False, msg

        if "offerEdit" not in r_edit.url and "offerSave" not in r_edit.text:
            msg = f"[FUNPAY] [❌ ДИАГНОСТИКА: РЕДИРЕКТ ЛОТА] FunPay перенаправил на страницу: {r_edit.url}. Возможно, лот заблокирован."
            print(msg)
            funpay_last_status = {"status": "ERROR_LOT", "msg": msg, "timestamp": time.time()}
            return False, msg

        parser = FunPayFormParser()
        parser.feed(r_edit.text)
        post_data = dict(parser.inputs)

        form_csrf_val = post_data.get("csrf_token")
        if not form_csrf_val:
            m_csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', r_edit.text)
            if m_csrf:
                form_csrf_val = m_csrf.group(1)
                post_data["csrf_token"] = form_csrf_val

        category_url = cur_fp.get("category_url", "https://funpay.com/lots/925/")
        m_node = re.search(r'/lots/(\d+)/?', category_url)
        node_id = m_node.group(1) if m_node else post_data.get("node_id", "925")

        # ЦЕНА ЛОТА: НЕ МЕНЯЕТСЯ АВТОМАТИЧЕСКИ (УСТАНАВЛИВАЕТСЯ ТОЛЬКО ЧЕЛОВЕКОМ ВРУЧНУЮ)
        # Сохраняем оригинальную цену, которая уже выставлена на лоте:
        target_price = post_data.get("price", "0")

        existing_secrets = post_data.get("secrets", "")
        existing_lines = [l.strip() for l in existing_secrets.splitlines() if l.strip()]

        # Объединяем секреты: сохраняем уже имеющиеся на FunPay и добавляем новые из done.txt
        merged_secrets = list(existing_lines)
        uploaded_history = [str(x).strip().lower() for x in load_json(FUNPAY_UPLOADED_FILE, [])]
        ignored = [str(x).strip().lower() for x in load_json(IGNORED_ACCOUNTS_FILE, [])]
        blacklisted = set(uploaded_history + ignored)

        accounts_to_push = []
        for acc in done_accounts:
            u_acc, _ = extract_user_info_from_line(acc)
            if u_acc and u_acc.lower() in blacklisted:
                print(f"[FUNPAY] [🛡️ ЗАЩИТА] Аккаунт {u_acc} УЖЕ БЫЛ ВЫГРУЖЕН / ПРОДАН на FunPay! Повторная заливка заблокирована!")
                continue

            already_in_funpay = False
            for ex in merged_secrets:
                u_ex, _ = extract_user_info_from_line(ex)
                if u_acc and u_ex and u_acc.lower() == u_ex.lower():
                    already_in_funpay = True
                    break
                if acc.lower() == ex.lower():
                    already_in_funpay = True
                    break
            if not already_in_funpay:
                merged_secrets.append(acc)
                accounts_to_push.append(acc)

        if not accounts_to_push:
            print("[FUNPAY] [i] Нет новых аккаунтов для добавления в лот (все уже выставлены или ранее проданы).")
            funpay_last_status = {"status": "OK", "msg": "Все готовые аккаунты уже на FunPay или проданы", "timestamp": time.time()}
            return True, "Нет новых аккаунтов для добавления"

        total_count = len(merged_secrets)
        post_data["offer_id"] = str(lot_id)
        post_data["node_id"] = str(node_id)
        post_data["price"] = str(target_price)
        post_data["amount"] = str(total_count)
        post_data["auto_delivery"] = "on"
        post_data["secrets"] = "\n".join(merged_secrets)
        if total_count > 0:
            post_data["active"] = "on"
        else:
            post_data.pop("active", None)

        # ШАГ 3: Отправка offerSave на FunPay
        save_h = {"X-Requested-With": "XMLHttpRequest"}
        if form_csrf_val:
            save_h["X-CSRF-Token"] = form_csrf_val

        print(
            f"[FUNPAY] [↑] Заливка {len(accounts_to_push)} аккаунтов в лот #{lot_id} на FunPay... "
            f"(Всего товаров в лоте: {total_count} шт., Цена: {target_price} {cur_fp.get('currency', 'USD')})"
        )

        try:
            r_save = session.post(
                "https://funpay.com/lots/offerSave",
                data=post_data,
                headers=save_h,
                timeout=12
            )
        except Exception as e:
            msg = f"[FUNPAY] [❌ ДИАГНОСТИКА: ТАЙМАУТ СОХРАНЕНИЯ] Ошибка при сохранении лота #{lot_id}: {e}. Зачистка отменена."
            print(msg)
            funpay_last_status = {"status": "ERROR_NET", "msg": msg, "timestamp": time.time()}
            return False, msg

        if r_save.status_code != 200:
            err_diag = format_funpay_error(None, r_save.text)
            msg = (
                f"[FUNPAY] [❌ ДИАГНОСТИКА: СБОЙ offerSave (HTTP {r_save.status_code})] {err_diag}. "
                f"Зачистка отменена, данные сохранены в done.txt."
            )
            print(msg)
            funpay_last_status = {"status": "ERROR_SAVE", "msg": msg, "timestamp": time.time()}
            return False, msg

        res_json = None
        try:
            res_json = r_save.json()
        except Exception:
            err_diag = format_funpay_error(None, r_save.text)
            msg = (
                f"[FUNPAY] [❌ ДИАГНОСТИКА: НЕ JSON ОТВЕТ] Сервер вернул неожиданный ответ: {err_diag}. "
                f"Зачистка отменена, аккаунты сохранены."
            )
            print(msg)
            funpay_last_status = {"status": "ERROR_SAVE", "msg": msg, "timestamp": time.time()}
            return False, msg

        if not res_json.get("done"):
            err_diag = format_funpay_error(res_json, r_save.text)
            msg = (
                f"[FUNPAY] [❌ ДИАГНОСТИКА: FUNPAY ОТКЛОНИЛ ВЫСТАВЛЕНИЕ ЛОТА] Причина: {err_diag}. "
                f"Зачистка отменена, аккаунты сохранены в done.txt!"
            )
            print(msg)
            funpay_last_status = {"status": "REJECTED", "msg": msg, "timestamp": time.time()}
            return False, msg

        # ШАГ 4: КОНТРОЛЬНАЯ ПРОВЕРКА (ВЕРИФИКАЦИЯ: ПРОВЕРИЛО ВЫСТАВИЛОСЬ ИЛИ НЕТ!)
        print(f"[FUNPAY] [🔍] Контрольная проверка выставления лота #{lot_id} на сервере FunPay...")
        time.sleep(1.0)  # Даем FunPay 1 секунду на сохранение записи в БД

        try:
            r_verify = session.get(f"https://funpay.com/lots/offerEdit?offer={lot_id}", timeout=10)
            if r_verify.status_code != 200:
                msg = (
                    f"[FUNPAY] [⚠️ СБОЙ ПРОВЕРКИ] Не удалось загрузить лот для верификации (HTTP {r_verify.status_code})! "
                    f"Зачистка отложена для безопасности данных."
                )
                print(msg)
                funpay_last_status = {"status": "VERIFY_FAILED", "msg": msg, "timestamp": time.time()}
                return False, msg

            p_verify = FunPayFormParser()
            p_verify.feed(r_verify.text)
            verified_secrets_raw = p_verify.inputs.get("secrets", "")
            verified_secrets_lines = [l.strip() for l in verified_secrets_raw.splitlines() if l.strip()]
            verified_active = p_verify.inputs.get("active") == "on"
            verified_amount = int(p_verify.inputs.get("amount", len(verified_secrets_lines)) or 0)

            # Сверяем: каждый ли аккаунт РЕАЛЬНО появился в секретах
            missing_accounts = []
            confirmed_accounts = []
            for acc in accounts_to_push:
                u_name, _ = extract_user_info_from_line(acc)
                found = False
                for v_line in verified_secrets_lines:
                    v_name, _ = extract_user_info_from_line(v_line)
                    if u_name and v_name and u_name.lower() == v_name.lower():
                        found = True
                        break
                    if acc.lower() == v_line.lower():
                        found = True
                        break
                if found:
                    confirmed_accounts.append(acc)
                else:
                    missing_accounts.append(acc)

            if missing_accounts:
                msg = (
                    f"[FUNPAY] [❌ ДИАГНОСТИКА: АККАУНТЫ НЕ СОХРАНИЛИСЬ В СЕКРЕТАХ!] "
                    f"FunPay ответил success, но при проверке лота #{lot_id} {len(missing_accounts)} "
                    f"аккаунтов отсутствуют в поле secrets на сервере! "
                    f"Не найдены: {[extract_user_info_from_line(a)[0] for a in missing_accounts]}. "
                    f"Зачистка неполных аккаунтов отменена, они сохранены в done.txt!"
                )
                print(msg)
                # Если часть всё же подтвердилась - зачищаем подтвержденные
                if confirmed_accounts:
                    print(f"[FUNPAY] [🗑️] Зачищаем {len(confirmed_accounts)} подтвержденных в FunPay аккаунтов...")
                    for c_acc in confirmed_accounts:
                        c_name, c_id = extract_user_info_from_line(c_acc)
                        if c_name:
                            delete_account_completely(c_name, user_id=c_id, also_done=True)
                funpay_last_status = {"status": "PARTIAL", "msg": msg, "timestamp": time.time()}
                return False, msg

            if not verified_active and total_count > 0:
                print(f"[FUNPAY] [⚠️ ПРЕДУПРЕЖДЕНИЕ] Аккаунты сохранены в секретах, но лот неактивен (active!=on). Проверьте настройки лота на FunPay.")

            print(
                f"[FUNPAY] [✓✓✓] ПРОВЕРКА ПРОЙДЕНА УСПЕШНО! "
                f"Все {len(accounts_to_push)} аккаунтов реально выставлены на FunPay в лоте #{lot_id}! "
                f"(В наличии: {verified_amount} шт., автовыдача: ВКЛ)"
            )

        except Exception as e:
            msg = f"[FUNPAY] [⚠️ ОШИБКА ПРОВЕРКИ]: {e}. Зачистка отменена для защиты данных."
            print(msg)
            funpay_last_status = {"status": "VERIFY_ERROR", "msg": msg, "timestamp": time.time()}
            return False, msg

        # ШАГ 5: ЕСЛИ ДА — СНЕСЛО! (ТОТАЛЬНАЯ ЗАЧИСТКА СО ВСЕГО ПК)
        print(f"[FUNPAY] [🗑️] Контрольная проверка пройдена: начинаем зачистку {len(accounts_to_push)} аккаунтов отовсюду с ПК...")
        
        # Навсегда фиксируем в базе выгруженных аккаунтов
        try:
            up_list = load_json(FUNPAY_UPLOADED_FILE, [])
            for c_acc in confirmed_accounts:
                c_name, _ = extract_user_info_from_line(c_acc)
                if c_name and c_name.lower() not in [str(x).lower() for x in up_list]:
                    up_list.append(c_name)
            save_json(FUNPAY_UPLOADED_FILE, up_list)

            with open(FUNPAY_SOLD_FILE, "a", encoding="utf-8") as sf:
                for c_acc in confirmed_accounts:
                    sf.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {c_acc}\n")
        except Exception as e_up:
            print(f"[FUNPAY] [!] Ошибка записи в {FUNPAY_UPLOADED_FILE}: {e_up}")

        purged_count = 0
        for d_line in accounts_to_push:
            u_name, u_id = extract_user_info_from_line(d_line)
            if u_name:
                delete_account_completely(u_name, user_id=u_id, also_done=True)
                purged_count += 1

        success_msg = (
            f"[FUNPAY] [✓✓✓] Зачищено {purged_count} аккаунтов отовсюду с ПК "
            f"(из done.txt, accounts.txt, RAM, pool, CSV, воркспейсов и стат). "
            f"Они теперь ТОЛЬКО на FunPay в лоте #{lot_id}!"
        )
        print(success_msg)
        funpay_last_status = {"status": "SUCCESS", "msg": success_msg, "timestamp": time.time()}
        return True, success_msg

    finally:
        funpay_sync_lock.release()


def update_funpay_lot_price(session, cur_cfg):
    """
    Автоматическое изменение цены отключено.
    Цену на FunPay устанавливает и меняет только человек вручную.
    """
    return


# ==================== МОДУЛЬ FUNPAY (АВТОВЫДАЧА И АВТОПОДНЯТИЕ) ====================
def funpay_worker():
    print("[*] Модуль FunPay запущен (авто-выгрузка, проверка и зачистка)...")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    next_raise_time = 0
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
            category_url = cur_fp.get("category_url", "https://funpay.com/lots/925/")
            check_interval = int(cur_fp.get("check_interval_sec", 40))

            if not golden_key or golden_key in ("ВАШ_GOLDEN_KEY", "YOUR_FUNPAY_GOLDEN_KEY"):
                time.sleep(check_interval)
                continue

            session.cookies.set("golden_key", golden_key, domain=".funpay.com")

            now = time.time()

            # 1. Вечный онлайн (каждые 45-60 секунд)
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

            # 2. Авто-поднятие лотов (проверяем кулдаун)
            if now >= next_raise_time:
                try:
                    trade_url = category_url.rstrip("/") + "/trade"
                    r_trade = session.get(trade_url, timeout=10)
                    if r_trade.status_code == 200:
                        c_token = ""
                        m_csrf = re.search(r'data-app-data="([^"]+)"', r_trade.text)
                        if m_csrf:
                            try:
                                ap = json.loads(m_csrf.group(1).replace("&quot;", '"'))
                                c_token = ap.get("csrf-token", "")
                            except Exception:
                                pass

                        m_game = re.search(r'data-game="(\d+)"', r_trade.text)
                        game_id = m_game.group(1) if m_game else "141"
                        m_node = re.search(r'data-node="(\d+)"', r_trade.text)
                        node_id = m_node.group(1) if m_node else "925"

                        raise_headers = {"X-Requested-With": "XMLHttpRequest"}
                        if c_token:
                            raise_headers["X-CSRF-Token"] = c_token
                        r_raise = session.post(
                            "https://funpay.com/lots/raise",
                            data={"game_id": game_id, "node_id": node_id},
                            headers=raise_headers,
                            timeout=10
                        )
                        if r_raise.status_code == 200:
                            try:
                                r_json = r_raise.json()
                                msg = r_json.get("msg", "")
                                wait_sec = r_json.get("wait", 3600)
                                next_raise_time = now + max(300, int(wait_sec))
                                if msg:
                                    print(f"[FUNPAY] [↑] Поднятие лотов: {msg} (Следующее через {int(wait_sec // 60)} мин)")
                            except Exception:
                                next_raise_time = now + 3600
                except Exception:
                    next_raise_time = now + 600

            # 3. АВТО-ВЫГРУЗКА, ВЕРИФИКАЦИЯ И ЗАЧИСТКА АККАУНТОВ:
            done_accounts = get_done_accounts()
            if len(done_accounts) != last_reported_count:
                last_reported_count = len(done_accounts)
                if done_accounts:
                    print(f"[FUNPAY] [★] Найдено {len(done_accounts)} готовых аккаунтов в done.txt! Запуск авто-заливки...")

            if done_accounts:
                # ВЫКИНУЛО НА ФП -> ПРОВЕРИЛО ВЫСТАВИЛОСЬ ИЛИ НЕТ -> ЕСЛИ ДА СНЕСЛО -> ЕСЛИ НЕТ ДИАГНОСТИКА
                sync_and_verify_funpay_lot(session=session, cur_cfg=cur_cfg)

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
    t_pool_block = threading.Thread(target=auto_pool_blocker_worker, daemon=True)
    t_mem = threading.Thread(target=crash_dialog_watcher_worker, daemon=True)
    t_funpay = threading.Thread(target=funpay_worker, daemon=True)

    t_farm.start()
    t_block.start()
    t_pool_block.start()
    t_mem.start()
    t_funpay.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] Остановка...")
        sys.exit(0)
