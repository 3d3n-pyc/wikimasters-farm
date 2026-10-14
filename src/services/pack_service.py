import logging
import time
from datetime import datetime, timezone
from typing import Tuple, Optional, List
from src.api.client import WikiMastersClient
from src.config import PACK_OPEN_DELAY, PACK_429_BACKOFF

logger = logging.getLogger(__name__)


class PackService:
    def is_daily_limit_active(self, client: WikiMastersClient) -> Tuple[bool, Optional[str]]:
        retry_after_str = client.session_manager.get_account_metadata(
            client.account.email, "packs_retry_after"
        )
        if not retry_after_str:
            return False, None

        try:
            ts_clean = retry_after_str.replace("Z", "+00:00")
            retry_dt = datetime.fromisoformat(ts_clean)
            now_dt = datetime.now(timezone.utc)
            if now_dt < retry_dt:
                local_time_str = retry_dt.astimezone().strftime("%H:%M:%S")
                return True, local_time_str
        except Exception:
            pass
        return False, None

    def open_all_packs(self, client: WikiMastersClient, max_packs: int = 15) -> Tuple[int, List[str]]:
        is_active, reset_time = self.is_daily_limit_active(client)
        if is_active:
            logger.info(
                f"{client.account.prefix} Daily pack limit active until {reset_time}. Skipping packs."
            )
            return 0, []

        opened_count = 0
        new_card_ids: List[str] = []
        logger.info(f"{client.account.prefix} Checking and opening available packs...")

        consecutive_429 = 0
        for _ in range(max_packs):
            data = client.open_pack()
            status_code = data.get("_status_code", 200)

            if data.get("human_verification_required"):
                logger.info(f"{client.account.prefix} Turnstile required, solving...")
                if client.verify_human():
                    time.sleep(1.0)
                    continue
                else:
                    logger.error(f"{client.account.prefix} Failed to solve Turnstile.")
                    break

            if status_code == 429:
                error_msg = data.get("error", "")
                if data.get("rate_limit_daily") or "quotidienne" in error_msg.lower():
                    retry_after = data.get("retry_after")
                    reset_info = ""
                    if retry_after:
                        client.session_manager.update_account_metadata(
                            client.account.email, packs_retry_after=retry_after
                        )
                        try:
                            ts_clean = retry_after.replace("Z", "+00:00")
                            retry_dt = datetime.fromisoformat(ts_clean)
                            reset_info = f" (resets at {retry_dt.astimezone().strftime('%H:%M:%S')})"
                        except Exception:
                            reset_info = f" (resets at {retry_after})"

                    logger.info(
                        f"{client.account.prefix} Daily pack limit reached ({error_msg}){reset_info}. Skipping packs."
                    )
                    break

                consecutive_429 += 1
                if consecutive_429 >= 3:
                    logger.warning(f"{client.account.prefix} Pack open rate limit hit {consecutive_429} times. Skipping packs.")
                    break
                wait_time = PACK_429_BACKOFF + (consecutive_429 * 2.0)
                logger.info(f"{client.account.prefix} Pack open cooldown hit ({error_msg}). Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue
            else:
                consecutive_429 = 0

            if status_code == 200 and "cards" in data:
                client.session_manager.update_account_metadata(
                    client.account.email, packs_retry_after=None
                )
                opened_count += 1
                cards = data.get("cards", [])
                for c in cards:
                    cid = c.get("card_id") or c.get("id")
                    if cid:
                        new_card_ids.append(cid)
                remaining = data.get("packs_remaining", 0)
                client.account.packs_remaining = remaining
                logger.info(f"{client.account.prefix} Pack opened (+{len(cards)} cards)! Remaining: {remaining}")
                if remaining <= 0:
                    break
                logger.info(f"{client.account.prefix} Waiting {PACK_OPEN_DELAY:.0f}s before next pack...")
                time.sleep(PACK_OPEN_DELAY)
            else:
                error = data.get("error", "No more packs")
                if "aucun paquet" in error.lower() or status_code == 400:
                    logger.debug(f"{client.account.prefix} No more packs available.")
                else:
                    logger.warning(f"{client.account.prefix} Pack open stopped: {error}")
                break

        return opened_count, new_card_ids
