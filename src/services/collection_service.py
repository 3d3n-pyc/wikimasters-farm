import json
import logging
import threading
import time
from typing import List, Set, Dict
from pathlib import Path

from src.config import TARGET_COLLECTION_FILE
from src.models.card import UserCard
from src.api.client import WikiMastersClient

logger = logging.getLogger(__name__)


class CollectionService:
    _lock = threading.Lock()

    def __init__(self, target_collection_path: Path = TARGET_COLLECTION_FILE):
        self.target_collection_path = target_collection_path
        self._target_owned_ids: Set[str] = self._load_target_collection()

    def _load_target_collection(self) -> Set[str]:
        if not self.target_collection_path.exists():
            return set()
        try:
            with open(self.target_collection_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
                elif isinstance(data, dict):
                    return set(data.get("owned_card_ids", []))
        except Exception as e:
            logger.warning(f"Could not load target collection file: {e}")
        return set()

    def save_target_collection(self) -> None:
        try:
            if self.target_collection_path.exists():
                try:
                    with open(self.target_collection_path, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                        existing_ids = (
                            set(existing) if isinstance(existing, list)
                            else set(existing.get("owned_card_ids", []))
                        )
                        self._target_owned_ids.update(existing_ids)
                except Exception:
                    pass

            temp_path = self.target_collection_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "count": len(self._target_owned_ids),
                        "owned_card_ids": sorted(list(self._target_owned_ids)),
                    },
                    f,
                    indent=2,
                )
            temp_path.replace(self.target_collection_path)
        except Exception as e:
            logger.error(f"Failed to save target collection: {e}")

    def get_target_owned_ids(self) -> Set[str]:
        with self._lock:
            return set(self._target_owned_ids)

    def add_target_owned_ids(self, card_ids: List[str]) -> None:
        with self._lock:
            self._target_owned_ids.update(card_ids)
            self.save_target_collection()

    def fetch_full_collection(self, client: WikiMastersClient) -> List[UserCard]:
        all_cards: List[UserCard] = []
        page = 0
        consecutive_errors = 0
        while True:
            data = client.get_my_collection(page=page, stats=0)
            items = data.get("collection", [])
            if not items:
                if consecutive_errors < 2:
                    consecutive_errors += 1
                    time.sleep(1.0)
                    continue
                break
            consecutive_errors = 0
            for item in items:
                all_cards.append(UserCard.from_dict(item))
            if len(items) < 50:
                break
            page += 1
            time.sleep(0.15)
        return all_cards

    def sync_target_collection(self, target_client: WikiMastersClient) -> int:
        logger.info(f"{target_client.account.prefix} Refreshing main collection cache...")
        cards = self.fetch_full_collection(target_client)
        new_ids = {c.card_id for c in cards if c.card_id}
        with self._lock:
            self._target_owned_ids = new_ids
            self.save_target_collection()

        rarity_counts: Dict[str, int] = {}
        for c in cards:
            r = c.rarity
            rarity_counts[r] = rarity_counts.get(r, 0) + 1

        summary = ", ".join(f"{rarity_counts.get(r, 0)} {r}" for r in ["L", "UR", "SR", "R", "PC", "C"] if rarity_counts.get(r, 0) > 0)
        logger.info(f"{target_client.account.prefix} Target collection synced: {len(new_ids)} cards ({summary}).")
        return len(new_ids)
