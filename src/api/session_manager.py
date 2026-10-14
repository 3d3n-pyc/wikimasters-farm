import base64
import json
import logging
import threading
import time
from typing import Dict, Optional, Any, Tuple
from pathlib import Path

import httpx

from src.config import (
    SESSIONS_FILE,
    LOGIN_URL,
    PULLS_URL,
    API_WIKIBIDOUS,
    DEFAULT_USER_AGENT,
    HEADLESS,
)
from src.models.account import Account

logger = logging.getLogger(__name__)


def extract_session_user(cookies: Dict[str, str]) -> Tuple[Optional[str], Optional[str]]:
    c0 = cookies.get("sb-cyrxjeppjqsxxjayfrur-auth-token.0", "")
    c1 = cookies.get("sb-cyrxjeppjqsxxjayfrur-auth-token.1", "")
    if not c0:
        c0 = cookies.get("sb-cyrxjeppjqsxxjayfrur-auth-token", "")
    raw = (c0 + c1).replace("base64-", "")
    if not raw:
        return None, None
    try:
        raw += "=" * (-len(raw) % 4)
        data = json.loads(base64.b64decode(raw).decode("utf-8"))
        uid = data.get("user", {}).get("id")
        username = data.get("user", {}).get("user_metadata", {}).get("username")
        return uid, username
    except Exception:
        return None, None


def extract_session_token(cookies: Dict[str, str]) -> Optional[str]:
    c0 = cookies.get("sb-cyrxjeppjqsxxjayfrur-auth-token.0", "")
    c1 = cookies.get("sb-cyrxjeppjqsxxjayfrur-auth-token.1", "")
    if not c0:
        c0 = cookies.get("sb-cyrxjeppjqsxxjayfrur-auth-token", "")
    raw = (c0 + c1).replace("base64-", "")
    if not raw:
        return None
    try:
        raw += "=" * (-len(raw) % 4)
        data = json.loads(base64.b64decode(raw).decode("utf-8"))
        return data.get("access_token")
    except Exception:
        return None


class SessionManager:
    _lock = threading.Lock()

    def __init__(self, sessions_path: Path = SESSIONS_FILE):
        self.sessions_path = sessions_path
        self._cache: Dict[str, Dict[str, Any]] = self._load_sessions()

    def _load_sessions(self) -> Dict[str, Dict[str, Any]]:
        if not self.sessions_path.exists():
            return {}
        try:
            with open(self.sessions_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning(f"Failed to read sessions file {self.sessions_path}: {e}")
            return {}

    def _save_sessions(self) -> None:
        try:
            temp_path = self.sessions_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.sessions_path)
        except Exception as e:
            logger.error(f"Failed to save sessions file {self.sessions_path}: {e}")

    def is_cookie_valid(self, cookies: Dict[str, str]) -> bool:
        if not cookies:
            return False
        try:
            with httpx.Client(
                cookies=cookies,
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=10.0,
            ) as client:
                res = client.get(API_WIKIBIDOUS)
                return res.status_code == 200
        except Exception:
            return False

    def refresh_session_http(self, cookies: Dict[str, str]) -> Optional[Dict[str, str]]:
        c0 = cookies.get("sb-cyrxjeppjqsxxjayfrur-auth-token.0", "")
        c1 = cookies.get("sb-cyrxjeppjqsxxjayfrur-auth-token.1", "")
        if not c0:
            c0 = cookies.get("sb-cyrxjeppjqsxxjayfrur-auth-token", "")
        raw = (c0 + c1).replace("base64-", "").rstrip("=")
        if not raw:
            return None
        raw += "=" * (-len(raw) % 4)
        try:
            auth_data = json.loads(base64.b64decode(raw).decode("utf-8"))
            rt = auth_data.get("refresh_token")
            if not rt:
                return None

            from src.config import SUPABASE_URL, SUPABASE_ANON_KEY
            res = httpx.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
                headers={"apikey": SUPABASE_ANON_KEY},
                json={"refresh_token": rt},
                timeout=10.0,
            )
            if res.status_code == 200:
                new_data = res.json()
                raw_json = json.dumps(new_data, separators=(",", ":"))
                b64 = "base64-" + base64.b64encode(raw_json.encode("utf-8")).decode("utf-8")
                chunk_size = 3000
                chunks = [b64[i : i + chunk_size] for i in range(0, len(b64), chunk_size)]
                new_cookies = {}
                if len(chunks) == 1:
                    new_cookies["sb-cyrxjeppjqsxxjayfrur-auth-token"] = chunks[0]
                else:
                    for idx, ch in enumerate(chunks):
                        new_cookies[f"sb-cyrxjeppjqsxxjayfrur-auth-token.{idx}"] = ch
                return new_cookies
        except Exception as e:
            logger.debug(f"HTTP session refresh failed: {e}")
        return None

    def get_cookies(self, account: Account, force_refresh: bool = False) -> Dict[str, str]:
        with self._lock:
            cached = self._cache.get(account.email)
            if cached and not force_refresh:
                cookies = cached.get("cookies", {})
                if cookies and self.is_cookie_valid(cookies):
                    logger.debug(f"{account.prefix} Reusing valid cached session.")
                    return cookies

                if cookies:
                    new_cookies = self.refresh_session_http(cookies)
                    if new_cookies and self.is_cookie_valid(new_cookies):
                        logger.info(f"{account.prefix} Refreshed session via HTTP token refresh.")
                        self._cache[account.email]["cookies"] = new_cookies
                        self._cache[account.email]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                        self._save_sessions()
                        return new_cookies

            logger.info(f"{account.prefix} Logging in via Camoufox...")
            cookies = self._login_with_browser(account)
            if cookies:
                self._cache[account.email] = {
                    "cookies": cookies,
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                self._save_sessions()
                logger.info(f"{account.prefix} Login successful.")
                return cookies
            else:
                raise RuntimeError(f"Login failed for {account.email}")

    def invalidate(self, email: str) -> None:
        with self._lock:
            if email in self._cache:
                del self._cache[email]
                self._save_sessions()

    def update_account_metadata(self, email: str, **kwargs) -> None:
        with self._lock:
            if email in self._cache:
                self._cache[email].update(kwargs)
                self._save_sessions()

    def get_account_metadata(self, email: str, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._cache.get(email, {}).get(key, default)

    def _login_with_browser(self, account: Account, max_retries: int = 2) -> Dict[str, str]:
        from camoufox.sync_api import Camoufox

        for attempt in range(1, max_retries + 1):
            try:
                with Camoufox(headless=HEADLESS, geoip=True, humanize=True) as browser:
                    page = browser.new_page()
                    page.goto(LOGIN_URL, timeout=45000)
                    page.wait_for_load_state("domcontentloaded")

                    email_input = page.locator("#email")
                    email_input.wait_for(state="visible", timeout=15000)
                    email_input.fill(account.email)

                    pwd_input = page.locator("#password")
                    pwd_input.fill(account.password)

                    submit_btn = page.locator("button[type='submit']")
                    t0 = time.time()
                    while time.time() - t0 < 25:
                        if submit_btn.is_visible() and not submit_btn.is_disabled():
                            break
                        for frame in page.frames:
                            if "challenges.cloudflare.com" in frame.url or "turnstile" in frame.url:
                                for sel in [
                                    "input[type='checkbox']",
                                    ".ctp-checkbox-label",
                                    "#challenge-stage",
                                    "div[role='checkbox']",
                                    "span.mark",
                                ]:
                                    cb = frame.locator(sel)
                                    if cb.is_visible(timeout=250):
                                        cb.first.click(force=True)
                                        time.sleep(1.0)
                                        break
                        time.sleep(0.5)

                    try:
                        page.evaluate("() => { const b = document.querySelector('button[type=\"submit\"]'); if (b) b.click(); }")
                    except Exception:
                        pwd_input.press("Enter")

                    page.wait_for_url("**/pulls*", timeout=60000)
                    page.wait_for_load_state("networkidle")

                    cookies_list = page.context.cookies()
                    return {c["name"]: c["value"] for c in cookies_list}
            except Exception as e:
                logger.warning(f"{account.prefix} Login attempt {attempt}/{max_retries} failed: {e}")
                if attempt < max_retries:
                    time.sleep(2.0)
                else:
                    raise e
        return {}

    def solve_turnstile(
        self,
        account: Account,
        reason: str = "anti-bot",
        max_retries: int = 3,
    ) -> bool:
        from camoufox.sync_api import Camoufox
        from src.config import HEADLESS, PULLS_URL, TRADES_URL

        is_trade = "trade" in reason.lower()
        target_url = TRADES_URL if is_trade else PULLS_URL

        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                logger.info(f"{account.prefix} Retrying Turnstile (attempt {attempt}/{max_retries})...")
                time.sleep(2.0)

            cookies = self.get_cookies(account)
            cookie_list = [
                {"name": k, "value": v, "domain": ".wiki-masters.com", "path": "/"}
                for k, v in cookies.items()
            ]

            try:
                with Camoufox(headless=HEADLESS, geoip=True, humanize=True) as browser:
                    page = browser.new_page()
                    page.context.add_cookies(cookie_list)

                    human_check_passed = False

                    def handle_response(response):
                        nonlocal human_check_passed
                        if "/api/human-check" in response.url and response.status == 200:
                            human_check_passed = True

                    page.on("response", handle_response)
                    page.goto(target_url, timeout=45000)
                    page.wait_for_load_state("domcontentloaded")
                    time.sleep(1.0)

                    try:
                        if is_trade:
                            trade_btn = page.locator('button:has-text("Accepter"), button:has-text("Refuser"), button:has-text("Échanger")').first
                            if trade_btn.is_visible(timeout=3000):
                                trade_btn.click(force=True)
                        else:
                            pack_btn = page.locator('main button').filter(has=page.locator('img')).first
                            pack_btn.wait_for(state='visible', timeout=15000)
                            pack_btn.click()
                    except Exception:
                        pass

                    t0 = time.time()
                    modal_seen = False
                    last_click_retry = 0.0

                    while time.time() - t0 < 50:
                        if human_check_passed:
                            time.sleep(1.0)
                            updated_cookies = {c["name"]: c["value"] for c in page.context.cookies()}
                            if updated_cookies and account.email in self._cache:
                                self._cache[account.email]["cookies"].update(updated_cookies)
                                self._save_sessions()
                            return True

                        modal = page.locator('text="Vérification rapide"')
                        try:
                            if modal.is_visible():
                                modal_seen = True
                            elif modal_seen:
                                time.sleep(1.0)
                                updated_cookies = {c["name"]: c["value"] for c in page.context.cookies()}
                                if updated_cookies and account.email in self._cache:
                                    self._cache[account.email]["cookies"].update(updated_cookies)
                                    self._save_sessions()
                                return True
                        except Exception:
                            pass

                        if not modal_seen and time.time() - last_click_retry > 3.0:
                            last_click_retry = time.time()
                            try:
                                if is_trade:
                                    tbtn = page.locator('button:has-text("Accepter"), button:has-text("Refuser"), button:has-text("Échanger")').first
                                    if tbtn.is_visible(timeout=500):
                                        tbtn.click(force=True)
                                else:
                                    pbtn = page.locator('main button').filter(has=page.locator('img')).first
                                    if pbtn.is_visible(timeout=500):
                                        pbtn.click()
                            except Exception:
                                pass

                        for frame in page.frames:
                            if "challenges.cloudflare.com" in frame.url or "turnstile" in frame.url:
                                for sel in [
                                    "input[type='checkbox']",
                                    ".ctp-checkbox-label",
                                    "#challenge-stage",
                                    "div[role='checkbox']",
                                    "span.mark",
                                ]:
                                    try:
                                        cb = frame.locator(sel)
                                        if cb.is_visible(timeout=250):
                                            cb.first.click(force=True)
                                            time.sleep(1.0)
                                            break
                                    except Exception:
                                        pass

                        time.sleep(0.5)

                    logger.warning(f"{account.prefix} Turnstile challenge attempt {attempt}/{max_retries} timed out.")
            except Exception as e:
                logger.error(f"{account.prefix} Error solving Turnstile (attempt {attempt}/{max_retries}): {e}")

        logger.error(f"{account.prefix} Turnstile verification failed after {max_retries} attempts.")
        return False
