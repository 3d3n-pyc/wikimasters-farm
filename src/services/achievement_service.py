import logging
from typing import Dict, Any, Optional, List
import httpx

from src.api.client import WikiMastersClient
from src.config import SUPABASE_URL, SUPABASE_ANON_KEY

logger = logging.getLogger(__name__)


class AchievementService:
    _catalog: Optional[Dict[str, Dict[str, Any]]] = None

    @classmethod
    def get_catalog(cls) -> Dict[str, Dict[str, Any]]:
        if cls._catalog is not None:
            return cls._catalog

        catalog: Dict[str, Dict[str, Any]] = {}
        try:
            res = httpx.get(
                f"{SUPABASE_URL}/rest/v1/achievements?select=*",
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "authorization": f"Bearer {SUPABASE_ANON_KEY}",
                },
                timeout=10.0,
            )
            if res.status_code == 200:
                for ach in res.json():
                    if ach.get("id"):
                        catalog[ach["id"]] = ach
                    if ach.get("code"):
                        catalog[ach["code"]] = ach
        except Exception as e:
            logger.warning(f"Failed to fetch achievements catalog: {e}")

        cls._catalog = catalog
        return cls._catalog

    def claim_all_achievements(self, client: WikiMastersClient) -> int:
        catalog = self.get_catalog()

        newly_unlocked = []
        try:
            check_data = client.check_achievements()
            newly_unlocked = check_data.get("unlocked", [])
        except Exception as e:
            logger.warning(f"{client.account.prefix} Achievement check error: {e}")

        candidate_ids: List[str] = []
        for item in newly_unlocked:
            if isinstance(item, dict):
                key = item.get("id") or item.get("code") or item.get("achievement_id")
            else:
                key = str(item)

            meta = catalog.get(key)
            if meta and meta.get("id"):
                candidate_ids.append(meta["id"])
            elif key:
                candidate_ids.append(key)

        try:
            unclaimed = client.get_unclaimed_achievements()
            for ach_id in unclaimed:
                if ach_id not in candidate_ids:
                    candidate_ids.append(ach_id)
        except Exception as e:
            logger.debug(f"{client.account.prefix} Could not fetch unclaimed achievements: {e}")

        if not candidate_ids:
            return 0

        claimed_count = 0
        for ach_id in candidate_ids:
            meta = catalog.get(ach_id, {})
            title = meta.get("title") or ach_id
            expected_reward = meta.get("wikibidous_reward", 0)

            try:
                res = client.claim_achievement(ach_id)
                if res.get("ok") and not res.get("already_claimed"):
                    reward = res.get("amount", expected_reward)
                    claimed_count += 1
                    logger.info(f"{client.account.prefix} Claimed achievement: {title} (+{reward} WB)")
                elif res.get("already_claimed"):
                    logger.debug(f"{client.account.prefix} Achievement already claimed: {title}")
                elif res.get("error"):
                    logger.warning(f"{client.account.prefix} Could not claim achievement {title}: {res.get('error')}")
            except Exception as e:
                logger.warning(f"{client.account.prefix} Error claiming achievement {title}: {e}")

        return claimed_count
