import logging
import time
from typing import Set, List
from src.config import BULK_DISCARD_CHUNK_SIZE
from src.models.card import UserCard
from src.api.client import WikiMastersClient
from src.services.collection_service import CollectionService

logger = logging.getLogger(__name__)


class DiscardService:
    def __init__(self, collection_service: CollectionService):
        self.collection_service = collection_service

    def discard_excess_cards(self, client: WikiMastersClient, target_owned_ids: Set[str]) -> int:
        if client.account.is_target:
            return 0

        all_cards = self.collection_service.fetch_full_collection(client)
        if not all_cards:
            return 0

        first_page = client.get_my_collection(page=0, stats=0)
        pending_ids = set(first_page.get("pendingTradeCardIds", []))

        discard_ids: List[str] = []
        seen_r_card_ids: Set[str] = set()
        c_count = 0
        pc_count = 0
        r_count = 0

        for card in all_cards:
            if card.id in pending_ids or card.starred:
                if card.rarity == "R" and card.card_id:
                    seen_r_card_ids.add(card.card_id)
                continue

            if card.rarity in ("C", "PC"):
                discard_ids.append(card.id)
                if card.rarity == "C":
                    c_count += 1
                else:
                    pc_count += 1
            elif card.rarity == "R":
                is_target_owned = card.card_id in target_owned_ids if target_owned_ids else False
                is_duplicate = card.card_id in seen_r_card_ids

                if is_target_owned or is_duplicate:
                    discard_ids.append(card.id)
                    r_count += 1
                else:
                    seen_r_card_ids.add(card.card_id)

        # Ensure at least 1 card remains in inventory for counterparty trade proposals
        if len(discard_ids) >= len(all_cards) and len(discard_ids) > 1:
            discard_ids.pop()

        if not discard_ids:
            return 0

        logger.info(
            f"{client.account.prefix} Discarding {len(discard_ids)} cards "
            f"({c_count} C, {pc_count} PC, {r_count} R duplicates) -> +{len(discard_ids)} WB."
        )

        total_discarded = 0
        chunks = [
            discard_ids[i:i + BULK_DISCARD_CHUNK_SIZE]
            for i in range(0, len(discard_ids), BULK_DISCARD_CHUNK_SIZE)
        ]

        for chunk in chunks:
            res = client.bulk_discard(chunk)
            discarded = res.get("discarded_count", 0)
            total_discarded += discarded
            if "balance" in res:
                client.account.wikibidous_balance = res["balance"]
            time.sleep(0.3)

        return total_discarded
