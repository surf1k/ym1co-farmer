#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COOKIE GRABBER - Автоматический логин и получение .ROBLOSECURITY для аккаунтов Real / BloxGen.
Разработано специально для ym1co farmer.

Поддерживает:
1. Авто-сканирование локального хранилища Real (%LOCALAPPDATA%/Real) на наличие аккаунтов BloxGen.
2. Чтение из файлов: accounts_raw.txt, real_accounts.txt, txt.txt, CSV от BloxGen.
3. Ввод пар username:password из буфера обмена или консоли.
4. Фоновый автоматический вход через Playwright Chromium без рутинных действий руками.
5. Авто-запись готовых строк формата username:password:cookie:userId в accounts.txt.
"""

import os
import sys
import re
import json
import time
import glob
import subprocess
from typing import List, Dict, Tuple, Optional

ACCOUNTS_FILE = "accounts.txt"
REAL_ACCOUNTS_INPUT = "real_accounts.txt"


def ensure_playwright_installed():
    """Проверяет наличие Playwright и браузера Chromium. При отсутствии скачивает автоматически."""
    try:
        import playwright
    except ImportError:
        print("[*] Установка библиотеки playwright...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])

    # Проверка Chromium
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
    except Exception as e:
        print("[*] Загрузка браузера Chromium для Playwright...")
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])


def scan_real_local_storage() -> List[Dict[str, str]]:
    """
    Сканирует локальные файлы Real (%LOCALAPPDATA%/Real) на Windows,
    включая LevelDB хранилище WebView2 и JSON файлы BloxGen.
    """
    found_accounts = []
    seen_users = set()

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    app_data = os.environ.get("APPDATA", "")

    candidate_dirs = [
        os.path.join(local_app_data, "Real"),
        os.path.join(app_data, "Real"),
        r"C:\Users\DDDen\AppData\Local\Real",
    ]

    for c_dir in candidate_dirs:
        if not c_dir or not os.path.isdir(c_dir):
            continue

        # 1. Поиск в JSON файлах
        for json_path in glob.glob(os.path.join(c_dir, "**", "*.json"), recursive=True):
            try:
                with open(json_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    matches = re.finditer(
                        r'["\']?username["\']?\s*[:=]\s*["\']([a-zA-Z0-9_]{3,20})["\'].*?["\']?password["\']?\s*[:=]\s*["\']([^"\'\s]{6,50})["\']',
                        content,
                        re.IGNORECASE | re.DOTALL,
                    )
                    for m in matches:
                        u = m.group(1).strip()
                        p = m.group(2).strip()
                        if u.lower() not in seen_users:
                            seen_users.add(u.lower())
                            found_accounts.append({"username": u, "password": p})
            except Exception:
                pass

        # 2. Поиск в LevelDB файлах WebView2 (Local Storage / IndexedDB)
        leveldb_patterns = [
            os.path.join(c_dir, "EBWebView", "Default", "Local Storage", "leveldb", "*.*"),
            os.path.join(c_dir, "EBWebView", "Default", "IndexedDB", "**", "*.*"),
        ]
        for pat in leveldb_patterns:
            for ldb_path in glob.glob(pat, recursive=True):
                if not os.path.isfile(ldb_path):
                    continue
                try:
                    with open(ldb_path, "rb") as f:
                        raw = f.read()
                    text = raw.decode("utf-8", errors="ignore")
                    matches = re.finditer(
                        r'["\']?username["\']?\s*[:=]\s*["\']([a-zA-Z0-9_]{3,20})["\'].*?["\']?password["\']?\s*[:=]\s*["\']([^"\'\s]{6,50})["\']',
                        text,
                        re.IGNORECASE | re.DOTALL,
                    )
                    for m in matches:
                        u = m.group(1).strip()
                        p = m.group(2).strip()
                        if u.lower() not in seen_users:
                            seen_users.add(u.lower())
                            found_accounts.append({"username": u, "password": p})
                except Exception:
                    pass

    return found_accounts


def parse_raw_accounts_file(file_path: str) -> List[Dict[str, str]]:
    """Парсит файл с аккаунтами (поддерживает username:password, CSV от BloxGen, разделение пробелом/табом)."""
    if not os.path.exists(file_path):
        return []

    accounts = []
    seen = set()

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("generatedAt,"):
            continue

        # Формат: username:password[:anything...]
        if ":" in line:
            parts = line.split(":")
            u = parts[0].strip()
            p = parts[1].strip() if len(parts) > 1 else ""
            if u and p and u.lower() not in seen:
                seen.add(u.lower())
                accounts.append({"username": u, "password": p})
                continue

        # Формат: username password
        parts = line.split()
        if len(parts) >= 2:
            u = parts[0].strip()
            p = parts[1].strip()
            if u and p and u.lower() not in seen:
                seen.add(u.lower())
                accounts.append({"username": u, "password": p})

    return accounts


def get_existing_usernames(accounts_file: str = ACCOUNTS_FILE) -> set:
    """Возвращает список уже имеющихся в accounts.txt пользователей в нижнем регистре."""
    existing = set()
    if os.path.exists(accounts_file):
        try:
            with open(accounts_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parts = line.strip().split(":")
                    if parts and parts[0].strip():
                        existing.add(parts[0].strip().lower())
        except Exception:
            pass
    return existing


def login_and_get_cookie(username: str, password: str, headless: bool = True) -> Tuple[bool, Optional[str], Optional[int], str]:
    """
    Выполняет вход в Roblox через Playwright и извлекает .ROBLOSECURITY и userId.
    Возвращает: (success, cookie, userId, message)
    """
    from playwright.sync_api import sync_playwright
    import requests

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

            # Ожидание авторизации или ошибки
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

                # Проверка сообщений об ошибках
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
                return False, None, None, "Куки не получена (возможно, потребовалась капча или неверный пароль)"

            # Получаем реальный UserId через официальный API Roblox
            user_id = None
            try:
                s = requests.Session()
                s.cookies[".ROBLOSECURITY"] = cookie_found
                res = s.get("https://users.roblox.com/v1/users/authenticated", timeout=8)
                if res.status_code == 200:
                    user_id = res.json().get("id")
            except Exception:
                pass

            return True, cookie_found, user_id, "Успешно"

    except Exception as e:
        return False, None, None, f"Исключение Playwright: {e}"


def run_grabber_batch(accounts: List[Dict[str, str]], headless: bool = True, output_file: str = ACCOUNTS_FILE) -> int:
    """
    Пакетный запуск получения куки для переданного списка аккаунтов.
    Записывает успешные аккаунты сразу в output_file и accounts_pool.txt.
    """
    ensure_playwright_installed()
    existing = get_existing_usernames(output_file)

    total = len(accounts)
    success_count = 0

    print(f"\n[COOKIE GRABBER] Начинаем пакетную обработку {total} аккаунтов...")
    print(f"[COOKIE GRABBER] Режим браузера: {'Фоновый (Headless)' if headless else 'Видимое окно'}\n")

    for idx, acc in enumerate(accounts, start=1):
        uname = acc["username"].strip()
        pwd = acc["password"].strip()

        if uname.lower() in existing:
            print(f"[{idx}/{total}] ⏩ {uname}: Уже есть в {output_file}, пропускаем.")
            continue

        print(f"[{idx}/{total}] 🔄 {uname}: Вход в Roblox...")
        ok, cookie, uid, msg = login_and_get_cookie(uname, pwd, headless=headless)

        if ok and cookie:
            uid_str = str(uid) if uid else "0"
            line = f"{uname}:{pwd}:{cookie}:{uid_str}"

            with open(output_file, "a", encoding="utf-8") as out_f:
                out_f.write(line + "\n")

            # Также добавляем в accounts_pool.txt для мгновенного подхвата фермой
            try:
                with open("accounts_pool.txt", "a", encoding="utf-8") as pf:
                    pf.write(line + "\n")
            except Exception:
                pass

            existing.add(uname.lower())
            success_count += 1
            print(f"[{idx}/{total}] ✅ {uname}: Куки получена! (UserId: {uid_str})")
        else:
            print(f"[{idx}/{total}] ❌ {uname}: Не удалось войти ({msg})")

        time.sleep(1)

    print(f"\n[COOKIE GRABBER] Завершено! Успешно получено куки: {success_count}/{total}")
    print(f"[COOKIE GRABBER] Аккаунты добавлены в {output_file} и готовы к запуску на ферме!\n")
    return success_count


def main():
    print("=" * 65)
    print("   👑 ym1co farmer - Автоматический сборщик куки (BloxGen / Real)")
    print("=" * 65)

    accounts_to_process = []

    # 1. Проверяем аргументы командной строки
    if len(sys.argv) > 1:
        target_path = sys.argv[1]
        if os.path.isfile(target_path):
            print(f"[*] Загрузка аккаунтов из переданного файла: {target_path}")
            accounts_to_process = parse_raw_accounts_file(target_path)

    # 2. Проверяем real_accounts.txt или accounts_raw.txt
    if not accounts_to_process:
        for cand in [REAL_ACCOUNTS_INPUT, "accounts_raw.txt"]:
            if os.path.exists(cand):
                print(f"[*] Найден файл {cand}, загружаем аккаунты...")
                accounts_to_process = parse_raw_accounts_file(cand)
                if accounts_to_process:
                    break

    # 3. Сканируем локальное хранилище Real
    if not accounts_to_process:
        print("[*] Поиск сгенерированных аккаунтов в локальном хранилище Real...")
        real_alts = scan_real_local_storage()
        if real_alts:
            print(f"[+] Найдено {len(real_alts)} аккаунтов из Real Local Storage!")
            accounts_to_process = real_alts

    # 4. Если всё ещё пусто — интерактивный ввод
    if not accounts_to_process:
        print("\n[?] Нет готовых файлов. Введите аккаунты в формате 'username:password' (пустая строка для завершения):")
        while True:
            try:
                line = input("> ").strip()
                if not line:
                    break
                if ":" in line:
                    u, p = line.split(":", 1)
                    accounts_to_process.append({"username": u.strip(), "password": p.strip()})
                elif " " in line:
                    parts = line.split()
                    accounts_to_process.append({"username": parts[0].strip(), "password": parts[1].strip()})
            except (EOFError, KeyboardInterrupt):
                break

    if not accounts_to_process:
        print("[!] Аккаунты для обработки не найдены. Выход.")
        return

    run_grabber_batch(accounts_to_process, headless=True)


if __name__ == "__main__":
    main()
