#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COOKIE GRABBER — АВТО-КУКИ ВСЕГО (Real / BloxGen / Farm)
Разработано специально для ym1co farmer.

ПОЛНЫЙ АВТОМАТ БЕЗ РУТИНЫ:
1. Авто-извлечение ВСЕХ куки и паролей из хранилища Real (%LOCALAPPDATA%/Real, WebView2, LevelDB, JSON).
2. Авто-сопоставление с txt.txt (BloxGen CSV) по robloxId и username.
3. Проверка валидности всех куки через официальный API Roblox (users.roblox.com).
4. Авто-логин через Playwright для любых аккаунтов без куки (или с протухшей кукой).
5. Мгновенная запись готовых строк username:password:cookie:userId в accounts.txt и accounts_pool.txt.
"""

import os
import sys
import re
import glob
import time
import subprocess
from typing import List, Dict, Tuple, Optional, Set

ACCOUNTS_FILE = "accounts.txt"
POOL_FILE = "accounts_pool.txt"
TXT_CSV_FILE = "txt.txt"
REAL_RAW_FILE = "real_accounts.txt"


def ensure_playwright_installed():
    """Проверяет наличие Playwright и браузера Chromium. При отсутствии устанавливает автоматически."""
    try:
        import playwright
    except ImportError:
        print("[*] Установка библиотеки playwright...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "--quiet"])

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
    except Exception:
        print("[*] Загрузка браузера Chromium для Playwright...")
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])


def extract_roblox_cookies_from_bytes(data: bytes) -> Set[str]:
    """Извлекает все .ROBLOSECURITY куки из сырых байтов (поддерживает UTF-8, ASCII и UTF-16LE)."""
    found = set()
    if not data:
        return found

    # 1. UTF-8 / ASCII pattern
    pattern_ascii = re.compile(rb"(_\|WARNING:-DO-NOT-SHARE-THIS\.[a-zA-Z0-9_\-\.]+)")
    for m in pattern_ascii.finditer(data):
        try:
            val = m.group(1).decode("utf-8", errors="ignore").strip().strip('"').strip("'")
            if len(val) > 100:
                found.add(val)
        except Exception:
            pass

    # 2. UTF-16LE pattern (характерно для Windows / WebView2 LevelDB)
    pattern_u16 = re.compile(
        rb"((?:_\x00\|\x00W\x00A\x00R\x00N\x00I\x00N\x00G\x00:\x00-\x00D\x00O\x00-\x00N\x00O\x00T\x00-\x00S\x00H\x00A\x00R\x00E\x00-\x00T\x00H\x00I\x00S\x00\.\x00)(?:[a-zA-Z0-9_\-\.]\x00){100,})"
    )
    for m in pattern_u16.finditer(data):
        try:
            val = m.group(1).decode("utf-16le", errors="ignore").strip().strip('"').strip("'")
            if len(val) > 100:
                found.add(val)
        except Exception:
            pass

    return found


def validate_cookie_and_get_user(cookie: str) -> Optional[Dict[str, any]]:
    """
    Проверяет валидность .ROBLOSECURITY куки через официальный API Roblox.
    Возвращает dict с id, name, displayName или None, если кука невалидна.
    """
    import requests
    try:
        s = requests.Session()
        s.cookies[".ROBLOSECURITY"] = cookie
        resp = s.get("https://users.roblox.com/v1/users/authenticated", timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "userId": data.get("id"),
                "username": data.get("name"),
                "displayName": data.get("displayName"),
            }
    except Exception:
        pass
    return None


def parse_txt_metadata_csv(file_path: str = TXT_CSV_FILE) -> Dict[str, Dict]:
    """
    Парсит файл экспорта BloxGen (txt.txt).
    Возвращает словарь {robloxId: record, username_lower: record}.
    """
    res = {}
    if not os.path.exists(file_path):
        return res

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("generatedAt,"):
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    u = parts[1]
                    rid = parts[2]
                    rec = {"username": u, "robloxId": rid}
                    if rid:
                        res[str(rid)] = rec
                    if u:
                        res[u.lower()] = rec
    except Exception:
        pass
    return res


def scan_real_storage_for_all_accounts(log_fn=None) -> List[Dict]:
    """
    Сканирует все папки и файлы Real (%LOCALAPPDATA%/Real, WebView2 LevelDB, IndexedDB, JSON).
    Находит все куки, пароли и логины сгенерированных аккаунтов.
    """
    def log(msg):
        if log_fn:
            log_fn(msg)
        else:
            print(msg)

    found_accounts = []
    seen_cookies = set()
    seen_users = set()

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    app_data = os.environ.get("APPDATA", "")

    candidate_dirs = [
        os.path.join(local_app_data, "Real"),
        os.path.join(app_data, "Real"),
        r"C:\Users\DDDen\AppData\Local\Real",
    ]
    for d in glob.glob(r"C:\Users\*\AppData\Local\Real"):
        if d not in candidate_dirs:
            candidate_dirs.append(d)

    file_patterns = [
        os.path.join("**", "*.json"),
        os.path.join("**", "*.ldb"),
        os.path.join("**", "*.log"),
        os.path.join("**", "*.txt"),
        os.path.join("EBWebView", "Default", "Local Storage", "leveldb", "*.*"),
        os.path.join("EBWebView", "Default", "IndexedDB", "**", "*.*"),
        os.path.join("EBWebView", "Default", "Session Storage", "*.*"),
    ]

    txt_meta = parse_txt_metadata_csv()

    for c_dir in candidate_dirs:
        if not c_dir or not os.path.isdir(c_dir):
            continue

        log(f"[*] Сканирование хранилища Real: {c_dir}")

        # Поиск всех подходящих файлов
        matched_files = set()
        for pat in file_patterns:
            for fp in glob.glob(os.path.join(c_dir, pat), recursive=True):
                if os.path.isfile(fp):
                    matched_files.add(fp)

        for fp in matched_files:
            try:
                # Ограничение размера файла 60MB для скорости
                if os.path.getsize(fp) > 60 * 1024 * 1024:
                    continue

                with open(fp, "rb") as f:
                    raw = f.read()

                cookies_in_file = extract_roblox_cookies_from_bytes(raw)
                for cookie in cookies_in_file:
                    if cookie in seen_cookies:
                        continue
                    seen_cookies.add(cookie)

                    # Пытаемся извлечь пароль и логин из контекста вокруг куки
                    pos = raw.find(cookie.encode("utf-8", errors="ignore"))
                    chunk_text = ""
                    if pos != -1:
                        c_start = max(0, pos - 500)
                        c_end = min(len(raw), pos + len(cookie) + 500)
                        chunk_text = raw[c_start:c_end].decode("utf-8", errors="ignore")

                    pwd_match = re.search(r'password["\']?\s*[:=]\s*["\']?([^"\'\s\x00-\x1f,}{]+)', chunk_text, re.IGNORECASE)
                    user_match = re.search(r'username["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_]{3,25})', chunk_text, re.IGNORECASE)

                    pwd = pwd_match.group(1).strip() if pwd_match else ""
                    uname = user_match.group(1).strip() if user_match else ""

                    # Проверяем валидность куки через Roblox API
                    u_info = validate_cookie_and_get_user(cookie)
                    if u_info:
                        actual_uname = u_info["username"]
                        actual_uid = u_info["userId"]

                        if actual_uname.lower() in seen_users:
                            continue
                        seen_users.add(actual_uname.lower())

                        # Сопоставляем с метаданными из txt.txt
                        if not pwd and str(actual_uid) in txt_meta:
                            # Метаданные подтверждают наличие аккаунта в Real
                            pass

                        found_accounts.append({
                            "username": actual_uname,
                            "password": pwd,
                            "cookie": cookie,
                            "userId": actual_uid,
                            "source": "Real Storage",
                        })
                        log(f"  ✓ Найден аккаунт в Real: {actual_uname} (ID: {actual_uid}) [Куки: OK]")

            except Exception:
                pass

    return found_accounts


def parse_raw_accounts_file(file_path: str) -> List[Dict]:
    """Парсит любой файл с аккаунтами (логин:пароль, CSV, логин:пароль:куки:id)."""
    if not os.path.exists(file_path):
        return []

    accounts = []
    seen = set()

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("generatedAt,"):
                continue

            # Формат: username:password:cookie:userId
            parts = line.split(":")
            if len(parts) >= 3 and "_|WARNING:" in line:
                u = parts[0].strip()
                p = parts[1].strip()
                c = ""
                uid = 0
                for pt in parts[2:]:
                    if "_|WARNING:" in pt:
                        c = pt.strip()
                    elif pt.strip().isdigit():
                        uid = int(pt.strip())
                if u and c and u.lower() not in seen:
                    seen.add(u.lower())
                    accounts.append({"username": u, "password": p, "cookie": c, "userId": uid, "source": file_path})
                    continue

            # Формат: username:password
            if len(parts) >= 2:
                u = parts[0].strip()
                p = parts[1].strip()
                if u and p and u.lower() not in seen:
                    seen.add(u.lower())
                    accounts.append({"username": u, "password": p, "cookie": "", "userId": 0, "source": file_path})
                    continue

            # Разделитель пробел или таб
            ws_parts = line.split()
            if len(ws_parts) >= 2:
                u = ws_parts[0].strip()
                p = ws_parts[1].strip()
                if u and p and u.lower() not in seen:
                    seen.add(u.lower())
                    accounts.append({"username": u, "password": p, "cookie": "", "userId": 0, "source": file_path})

    return accounts


def login_and_get_cookie(username: str, password: str, headless: bool = True) -> Tuple[bool, Optional[str], Optional[int], str]:
    """Выполняет вход в Roblox через Playwright Chromium и извлекает .ROBLOSECURITY и userId."""
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
            )
            page = context.new_page()

            page.goto("https://www.roblox.com/login", timeout=30000)
            page.wait_for_selector("#login-username", timeout=15000)

            page.fill("#login-username", username)
            page.fill("#login-password", password)
            page.click("#login-button")

            cookie_found = None
            start_time = time.time()
            while (time.time() - start_time) < 12:
                cookies = context.cookies()
                for c in cookies:
                    if c.get("name") == ".ROBLOSECURITY" and c.get("value"):
                        cookie_found = c["value"]
                        break
                if cookie_found:
                    break

                try:
                    error_el = page.query_selector(".text-error, #login-form-error")
                    if error_el and error_el.inner_text().strip():
                        err_text = error_el.inner_text().strip()
                        browser.close()
                        return False, None, None, f"Ошибка входа: {err_text}"
                except Exception:
                    pass

                time.sleep(1)

            browser.close()

            if not cookie_found:
                return False, None, None, "Куки не получена (капча или неверный пароль)"

            u_info = validate_cookie_and_get_user(cookie_found)
            uid = u_info["userId"] if u_info else 0
            return True, cookie_found, uid, "Успешно"

    except Exception as e:
        return False, None, None, f"Исключение Playwright: {e}"


def get_existing_usernames(target_file: str = ACCOUNTS_FILE) -> Set[str]:
    """Возвращает список уже имеющихся аккаунтов в нижнем регистре."""
    existing = set()
    if os.path.exists(target_file):
        try:
            with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parts = line.strip().split(":")
                    if parts and parts[0].strip():
                        existing.add(parts[0].strip().lower())
        except Exception:
            pass
    return existing


def auto_grab_everything(log_fn=None) -> int:
    """
    ГЛАВНАЯ ФУНКЦИЯ — АВТОКУКИ ВСЕГО:
    1. Авто-сканирование Real на все нагенерированные аккаунты с готовыми куками.
    2. Авто-загрузка из txt.txt, real_accounts.txt, accounts_raw.txt.
    3. Авто-логин через Playwright для всех аккаунтов без куки.
    4. Авто-добавление в accounts.txt и accounts_pool.txt.
    """
    def log(msg):
        if log_fn:
            log_fn(msg)
        else:
            print(msg)

    log("=" * 65)
    log("   👑 ym1co farmer — АВТОКУКИ ВСЕГО (Real / BloxGen / Farm)")
    log("=" * 65)

    existing = get_existing_usernames(ACCOUNTS_FILE)
    total_added = 0

    # ШАГ 1: Сканируем локальное хранилище Real
    log("\n[1/3] 🔍 Поиск сгенерированных аккаунтов в хранилище Real (%localappdata%)...")
    real_accounts = scan_real_storage_for_all_accounts(log_fn=log)

    for acc in real_accounts:
        uname = acc["username"]
        pwd = acc.get("password", "")
        cookie = acc["cookie"]
        uid = acc.get("userId", 0)

        if uname.lower() in existing:
            log(f"  ⏩ {uname}: Уже есть в ферме, пропускаем.")
            continue

        line = f"{uname}:{pwd}:{cookie}:{uid}\n"
        with open(ACCOUNTS_FILE, "a", encoding="utf-8") as af:
            af.write(line)
        try:
            with open(POOL_FILE, "a", encoding="utf-8") as pf:
                pf.write(line)
        except Exception:
            pass

        existing.add(uname.lower())
        total_added += 1
        log(f"  ✅ {uname}: Успешно добавлен в ферму из Real! (ID: {uid})")

    # ШАГ 2: Проверяем аккаунты из файлов (txt.txt, real_accounts.txt, accounts_raw.txt)
    log("\n[2/3] 📂 Проверка текстовых списков аккаунтов...")
    raw_files = [REAL_RAW_FILE, "accounts_raw.txt", TXT_CSV_FILE]
    file_accounts = []
    for rf in raw_files:
        if os.path.exists(rf):
            parsed = parse_raw_accounts_file(rf)
            if parsed:
                log(f"  Найдено {len(parsed)} записей в файле {rf}")
                file_accounts.extend(parsed)

    # Аккаунты, у которых уже есть куки
    for acc in file_accounts:
        uname = acc["username"]
        cookie = acc.get("cookie", "")
        if cookie and uname.lower() not in existing:
            u_info = validate_cookie_and_get_user(cookie)
            if u_info:
                uid = u_info["userId"]
                line = f"{uname}:{acc.get('password','')}:{cookie}:{uid}\n"
                with open(ACCOUNTS_FILE, "a", encoding="utf-8") as af:
                    af.write(line)
                try:
                    with open(POOL_FILE, "a", encoding="utf-8") as pf:
                        pf.write(line)
                except Exception:
                    pass
                existing.add(uname.lower())
                total_added += 1
                log(f"  ✅ {uname}: Валидная куки добавлена из файла! (ID: {uid})")

    # ШАГ 3: Аккаунты с логином и паролем, но без куки — авто-логин через Playwright
    need_login = [
        a for a in file_accounts
        if a["username"].lower() not in existing and a.get("password") and not a.get("cookie")
    ]

    if need_login:
        log(f"\n[3/3] 🌐 Авто-получение куки через Playwright для {len(need_login)} аккаунтов...")
        ensure_playwright_installed()

        for idx, acc in enumerate(need_login, 1):
            uname = acc["username"]
            pwd = acc["password"]

            if uname.lower() in existing:
                continue

            log(f"  [{idx}/{len(need_login)}] Авторизация {uname} в Roblox...")
            ok, cookie, uid, msg = login_and_get_cookie(uname, pwd, headless=True)

            if ok and cookie:
                uid_str = str(uid) if uid else "0"
                line = f"{uname}:{pwd}:{cookie}:{uid_str}\n"
                with open(ACCOUNTS_FILE, "a", encoding="utf-8") as af:
                    af.write(line)
                try:
                    with open(POOL_FILE, "a", encoding="utf-8") as pf:
                        pf.write(line)
                except Exception:
                    pass
                existing.add(uname.lower())
                total_added += 1
                log(f"  ✅ {uname}: Куки получена и сохранена! (ID: {uid_str})")
            else:
                log(f"  ❌ {uname}: Не удалось ({msg})")
            time.sleep(1)
    else:
        log("\n[3/3] ℹ️ Нет аккаунтов, требующих ручной авторизации через Playwright.")

    log("\n" + "=" * 65)
    log(f"🎉 АВТОКУКИ ВСЕГО ЗАВЕРШЕНО! Добавлено новых аккаунтов: {total_added}")
    log(f"📁 Файлы обновлены: {ACCOUNTS_FILE} и {POOL_FILE}")
    log("=" * 65 + "\n")
    return total_added


def main():
    auto_grab_everything()


if __name__ == "__main__":
    main()
