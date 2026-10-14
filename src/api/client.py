import json
import logging
import time
from typing import Dict, List, Optional, Any
import httpx

from src.config import (
    BASE_URL,
    API_MY_COLLECTION,
    API_MY_STATS,
    API_PROFILE_COLLECTION,
    API_PACKS_OPEN,
    API_BULK_DISCARD,
    API_WIKIBIDOUS,
    API_FRIENDS,
    API_FRIENDS_ACCEPT_ALL,
    API_FRIENDS_SEARCH,
    API_TRADES,
    API_ACHIEVEMENTS_CHECK,
    API_ACHIEVEMENTS_CLAIM,
    DEFAULT_USER_AGENT,
    REQUEST_TIMEOUT,
    SUPABASE_URL,
    SUPABASE_ANON_KEY,
)
from src.models.account import Account
from src.api.session_manager import SessionManager, extract_session_user, extract_session_token

logger = logging.getLogger(__name__)


class WikiMastersClient:
    def __init__(self, account: Account, session_manager: Optional[SessionManager] = None):
        self.account = account
        self.session_manager = session_manager or SessionManager()
        self._client: Optional[httpx.Client] = None
        self._init_client()

    def _init_client(self, force_refresh: bool = False) -> None:
        cookies = self.session_manager.get_cookies(self.account, force_refresh=force_refresh)
        uid, uname = extract_session_user(cookies)
        if uid and not self.account.user_id:
            self.account.user_id = uid
        if uname and not self.account.username:
            self.account.username = uname

        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": f"{BASE_URL}/pulls",
            "Accept": "application/json, text/plain, */*",
            "x-wiki-calendar-tz": "Europe/Paris",
        }
        if self._client:
            self._client.close()
        self._client = httpx.Client(
            cookies=cookies,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )

    def get_auth_token(self) -> Optional[str]:
        cookies = self.session_manager.get_cookies(self.account)
        return extract_session_token(cookies)

    def get_my_profile(self) -> Dict[str, Any]:
        try:
            access_token = self.get_auth_token()
            if not access_token:
                return {}

            headers = {
                "apikey": SUPABASE_ANON_KEY,
                "authorization": f"Bearer {access_token}",
                "content-type": "application/json",
            }
            res = httpx.post(
                f"{SUPABASE_URL}/rest/v1/rpc/get_my_profile",
                headers=headers,
                json={},
                timeout=REQUEST_TIMEOUT,
            )
            if res.status_code == 401:
                self.session_manager.invalidate(self.account.email)
                self._init_client(force_refresh=True)
                new_token = self.get_auth_token()
                if new_token:
                    headers["authorization"] = f"Bearer {new_token}"
                    res = httpx.post(
                        f"{SUPABASE_URL}/rest/v1/rpc/get_my_profile",
                        headers=headers,
                        json={},
                        timeout=REQUEST_TIMEOUT,
                    )

            if res.status_code == 200:
                prof = res.json()
                if prof.get("id"):
                    self.account.user_id = prof["id"]
                if prof.get("username"):
                    self.account.username = prof["username"]
                return prof
        except Exception as e:
            logger.debug(f"{self.account.prefix} Could not fetch profile via Supabase RPC: {e}")
        return {}

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> "WikiMastersClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def _request(self, method: str, url: str, max_retries: int = 3, **kwargs) -> httpx.Response:
        if not self._client:
            self._init_client()

        max_attempts = max_retries
        last_res = None
        for attempt in range(1, max_attempts + 1):
            try:
                res = self._client.request(method, url, **kwargs)
                last_res = res

                if res.status_code == 401:
                    logger.warning(f"{self.account.prefix} Session expired (401). Refreshing...")
                    self.session_manager.invalidate(self.account.email)
                    self._init_client(force_refresh=True)
                    continue

                if res.status_code in (500, 502, 503, 525) and attempt < max_attempts:
                    logger.warning(
                        f"{self.account.prefix} Server error {res.status_code} on {url.split('?')[0]}. Retrying ({attempt}/{max_attempts})..."
                    )
                    time.sleep(attempt * 1.5)
                    continue

                return res
            except (httpx.ConnectError, httpx.ReadTimeout) as e:
                if attempt < max_attempts:
                    logger.warning(f"{self.account.prefix} Network error on {url.split('?')[0]}: {e}. Retrying ({attempt}/{max_attempts})...")
                    time.sleep(attempt * 1.5)
                else:
                    raise e

        return last_res

    def get_my_collection(self, page: int = 0, stats: int = 0) -> Dict[str, Any]:
        url = f"{API_MY_COLLECTION}?page={page}&stats={stats}"
        res = self._request("GET", url)
        if res.status_code == 200:
            return res.json()
        logger.error(f"{self.account.prefix} get_my_collection failed ({res.status_code}): {res.text[:150]}")
        return {}

    def get_my_stats(self) -> Dict[str, Any]:
        res = self._request("GET", API_MY_STATS)
        if res.status_code == 200:
            return res.json()
        return {}

    def get_profile_collection(
        self,
        username: str,
        page: int = 0,
        rarity: Optional[str] = None,
        pending: int = 1,
    ) -> Dict[str, Any]:
        params = [f"page={page}", "stats=0", f"pending={pending}"]
        if rarity:
            params.append(f"rarity={rarity.upper()}")
        url = f"{API_PROFILE_COLLECTION}/{username}/collection?{'&'.join(params)}"
        res = self._request("GET", url)
        if res.status_code == 200:
            return res.json()
        return {}

    def open_pack(self) -> Dict[str, Any]:
        res = self._request("POST", API_PACKS_OPEN)
        try:
            data = res.json()
        except Exception:
            data = {"error": res.text}
        data["_status_code"] = res.status_code
        return data

    def verify_human(self, reason: str = "anti-bot", max_retries: int = 3) -> bool:
        logger.info(f"{self.account.prefix} Human verification required ({reason}), solving Turnstile...")
        success = self.session_manager.solve_turnstile(
            self.account, reason=reason, max_retries=max_retries
        )
        if success:
            self._init_client(force_refresh=False)
        return success

    def bulk_discard(self, user_card_ids: List[str]) -> Dict[str, Any]:
        if not user_card_ids:
            return {"discarded_count": 0, "balance": self.get_wikibidous()}
        res = self._request(
            "POST",
            API_BULK_DISCARD,
            json={"card_ids": user_card_ids},
        )
        if res.status_code == 200:
            return res.json()
        logger.error(f"{self.account.prefix} bulk_discard failed: {res.status_code} {res.text[:150]}")
        return {"error": res.text, "discarded_count": 0}

    def get_wikibidous(self) -> int:
        res = self._request("GET", API_WIKIBIDOUS)
        if res.status_code == 200:
            return res.json().get("balance", 0)
        return 0

    def get_friends(self) -> Dict[str, Any]:
        res = self._request("GET", API_FRIENDS)
        if res.status_code == 200:
            return res.json()
        return {}

    def accept_all_friends(self) -> bool:
        res = self._request("POST", API_FRIENDS_ACCEPT_ALL)
        return res.status_code == 200

    def send_friend_request(self, recipient_id: str) -> bool:
        res = self._request(
            "POST",
            API_FRIENDS,
            json={"recipient_id": recipient_id},
        )
        return res.status_code in (200, 201)

    def search_friends(self, query: str) -> List[Dict[str, Any]]:
        url = f"{API_FRIENDS_SEARCH}?q={query}"
        res = self._request("GET", url)
        if res.status_code == 200:
            return res.json().get("users", [])
        return []

    def get_trades(self, active_only: bool = True) -> List[Dict[str, Any]]:
        url = f"{API_TRADES}?active=1" if active_only else API_TRADES
        res = self._request("GET", url)
        if res.status_code == 200:
            return res.json().get("trades", [])
        return []

    def create_trade(
        self,
        recipient_id: str,
        items: List[Dict[str, str]],
        initiator_wikibidous: int = 0,
        recipient_wikibidous: int = 0,
        retry_on_captcha: bool = True,
    ) -> Dict[str, Any]:
        payload = {
            "recipient_id": recipient_id,
            "items": items,
            "initiator_wikibidous": initiator_wikibidous,
            "recipient_wikibidous": recipient_wikibidous,
        }
        res = self._request("POST", API_TRADES, json=payload)
        try:
            data = res.json()
        except Exception:
            data = {"error": res.text}
        data["_status_code"] = res.status_code

        if retry_on_captcha and (
            res.status_code == 403
            or data.get("human_verification_required")
            or data.get("code") == "human_verification_required"
            or "anti-bot" in str(data.get("error", "")).lower()
        ):
            logger.info(f"{self.account.prefix} Trade proposal requires Turnstile verification. Solving...")
            if self.verify_human(reason="trade_proposal"):
                time.sleep(1.0)
                return self.create_trade(
                    recipient_id=recipient_id,
                    items=items,
                    initiator_wikibidous=initiator_wikibidous,
                    recipient_wikibidous=recipient_wikibidous,
                    retry_on_captcha=False,
                )
            else:
                logger.error(f"{self.account.prefix} Failed to pass Turnstile verification for trade proposal.")

        return data

    def patch_trade(
        self,
        trade_id: str,
        action: str,
        retry_on_captcha: bool = True,
    ) -> Dict[str, Any]:
        url = f"{API_TRADES}/{trade_id}"
        res = self._request("PATCH", url, json={"action": action})
        try:
            data = res.json()
        except Exception:
            data = {"error": res.text}
        data["_status_code"] = res.status_code

        if retry_on_captcha and (
            res.status_code == 403
            or data.get("human_verification_required")
            or data.get("code") == "human_verification_required"
            or "anti-bot" in str(data.get("error", "")).lower()
        ):
            logger.info(f"{self.account.prefix} Trade {action} requires Turnstile verification. Solving...")
            if self.verify_human(reason=f"trade_{action}"):
                time.sleep(1.0)
                return self.patch_trade(trade_id, action, retry_on_captcha=False)
            else:
                logger.error(f"{self.account.prefix} Failed to pass Turnstile verification for trade {action}.")

        return data

    def check_achievements(self) -> Dict[str, Any]:
        res = self._request(
            "POST",
            API_ACHIEVEMENTS_CHECK,
            json={"event": "achievements_sync"},
            max_retries=2,
            timeout=60.0,
        )
        if res is not None and res.status_code == 200:
            try:
                return res.json()
            except Exception:
                return {}
        return {}

    def get_unclaimed_achievements(self) -> List[str]:
        uid = self.account.user_id
        if not uid:
            uid, _ = extract_session_user(self.session_manager.get_cookies(self.account))
            if uid:
                self.account.user_id = uid

        if not uid:
            return []

        token = self.get_auth_token()
        if not token:
            return []

        try:
            res = httpx.get(
                f"{SUPABASE_URL}/rest/v1/user_achievements?user_id=eq.{uid}&claimed_at=is.null&select=achievement_id",
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "authorization": f"Bearer {token}",
                },
                timeout=REQUEST_TIMEOUT,
            )
            if res.status_code == 200:
                data = res.json()
                return [row["achievement_id"] for row in data if isinstance(row, dict) and "achievement_id" in row]
        except Exception as e:
            logger.debug(f"{self.account.prefix} Could not fetch unclaimed achievements: {e}")
        return []

    def claim_achievement(self, achievement_id: str) -> Dict[str, Any]:
        res = self._request(
            "POST",
            API_ACHIEVEMENTS_CLAIM,
            json={"achievement_id": achievement_id},
        )
        if res is None:
            return {"error": "No response from server"}
        try:
            data = res.json()
        except Exception:
            data = {"error": res.text}
        data["_status_code"] = res.status_code
        return data
