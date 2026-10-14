import json
import logging
import random
import threading
import time
from typing import Dict, List, Optional, Set, Tuple
from pathlib import Path

from src.config import (
    MAX_CARDS_PER_TRADE,
    MAX_WB_PER_TRADE,
    MAX_TRADES_PER_BOT,
    MAX_DAILY_TARGET_TRADES,
    DAILY_RESET_HOUR,
    COUNTERPARTY_PAGES_TO_SCAN,
    VALUABLE_DUPLICATE_RARITIES,
    LAST_TRADE_FILE,
)
from src.models.card import UserCard
from src.models.trade import Trade, TradeResult
from src.api.client import WikiMastersClient
from src.services.collection_service import CollectionService

logger = logging.getLogger(__name__)


class TradeService:
    _lock = threading.Lock()
    _reserved_counterparty_ids: Set[str] = set()

    def __init__(self, collection_service: CollectionService, last_trade_path: Path = LAST_TRADE_FILE):
        self.collection_service = collection_service
        self.last_trade_path = last_trade_path
        self._last_trade_data = self._load_last_trade()

    @staticmethod
    def get_logical_date(offset_hours: int = DAILY_RESET_HOUR) -> str:
        from datetime import datetime, timedelta
        return (datetime.now() - timedelta(hours=offset_hours)).strftime("%Y-%m-%d")

    def _default_state(self) -> Dict:
        return {
            "date": self.get_logical_date(),
            "daily_target_trades": 0,
            "daily_target_cards": 0,
            "daily_target_wikibidous": 0,
            "target_limit_reached": False,
            "accounts": {},
        }

    def _load_last_trade(self) -> Dict:
        today_str = self.get_logical_date()
        if not self.last_trade_path.exists():
            return self._default_state()
        try:
            with open(self.last_trade_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == today_str:
                data.setdefault("daily_target_trades", 0)
                data.setdefault("daily_target_cards", 0)
                data.setdefault("daily_target_wikibidous", 0)
                data.setdefault("target_limit_reached", False)
                data.setdefault("accounts", {})
                return data
            else:
                return self._default_state()
        except Exception:
            return self._default_state()

    def _save_last_trade(self) -> None:
        try:
            temp_path = self.last_trade_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self._last_trade_data, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.last_trade_path)
        except Exception as e:
            logger.error(f"Failed to save last_trade.json: {e}")

    def _check_daily_reset(self) -> None:
        today_str = self.get_logical_date()
        if self._last_trade_data.get("date") != today_str:
            self._last_trade_data = self._default_state()
            self._save_last_trade()

    def is_target_daily_limit_reached(self) -> bool:
        with self._lock:
            self._check_daily_reset()
            if self._last_trade_data.get("target_limit_reached", False):
                return True
            return self._last_trade_data.get("daily_target_trades", 0) >= MAX_DAILY_TARGET_TRADES

    def mark_target_daily_limit_reached(self) -> None:
        with self._lock:
            self._check_daily_reset()
            self._last_trade_data["target_limit_reached"] = True
            self._save_last_trade()
            logger.warning("[Trade] Target daily limit reached. Trade proposals suspended for today.")

    def get_daily_target_trades(self) -> int:
        with self._lock:
            self._check_daily_reset()
            return self._last_trade_data.get("daily_target_trades", 0)

    def can_account_trade(self, email: str, force: bool = False) -> Tuple[bool, str]:
        if force:
            return True, "Forcé"
        with self._lock:
            self._check_daily_reset()
            if self._last_trade_data.get("target_limit_reached", False):
                return False, "Plafond cible atteint (50/j)"
            daily_trades = self._last_trade_data.get("daily_target_trades", 0)
            if daily_trades >= MAX_DAILY_TARGET_TRADES:
                return False, f"Plafond cible atteint ({daily_trades}/{MAX_DAILY_TARGET_TRADES})"

            acc_info = self._last_trade_data.get("accounts", {}).get(email, {})
            acc_trades = acc_info.get("trades_count", 0)
            if acc_trades >= MAX_TRADES_PER_BOT:
                last_time = acc_info.get("last_time", "aujourd'hui")
                return False, f"Déjà fait ({acc_trades}/{MAX_TRADES_PER_BOT} à {last_time})"

            return True, "OK"

    def record_account_trade(
        self,
        email: str,
        trades_sent: int,
        cards_sent: int,
        wikibidous_sent: int = 0,
    ) -> None:
        if trades_sent <= 0 and cards_sent <= 0 and wikibidous_sent <= 0:
            return
        with self._lock:
            self._check_daily_reset()
            self._last_trade_data["daily_target_trades"] = (
                self._last_trade_data.get("daily_target_trades", 0) + trades_sent
            )
            self._last_trade_data["daily_target_cards"] = (
                self._last_trade_data.get("daily_target_cards", 0) + cards_sent
            )
            self._last_trade_data["daily_target_wikibidous"] = (
                self._last_trade_data.get("daily_target_wikibidous", 0) + wikibidous_sent
            )
            self._last_trade_data["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")

            accounts = self._last_trade_data.setdefault("accounts", {})
            acc_entry = accounts.setdefault(email, {
                "trades_count": 0,
                "cards_count": 0,
                "wikibidous_count": 0,
                "first_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            acc_entry["trades_count"] = acc_entry.get("trades_count", 0) + trades_sent
            acc_entry["cards_count"] = acc_entry.get("cards_count", 0) + cards_sent
            acc_entry["wikibidous_count"] = acc_entry.get("wikibidous_count", 0) + wikibidous_sent
            acc_entry["last_time"] = time.strftime("%Y-%m-%d %H:%M:%S")

            if self._last_trade_data["daily_target_trades"] >= MAX_DAILY_TARGET_TRADES:
                self._last_trade_data["target_limit_reached"] = True
                logger.warning(
                    f"[Trade] Target daily trade limit of {MAX_DAILY_TARGET_TRADES} reached. "
                    f"Suspending further trades today."
                )

            self._save_last_trade()

    def release_counterparty_id(self, user_card_id: str) -> None:
        with self._lock:
            self._reserved_counterparty_ids.discard(user_card_id)

    def find_counterparty_card(
        self,
        farm_client: WikiMastersClient,
        target_username: str,
        target_user_id: str,
    ) -> Optional[Dict[str, str]]:
        with self._lock:
            currently_reserved = set(self._reserved_counterparty_ids)

        pending_ids: Set[str] = set()

        for page in range(COUNTERPARTY_PAGES_TO_SCAN):
            data = farm_client.get_profile_collection(
                username=target_username,
                page=page,
                rarity="C",
                pending=1,
            )
            items = data.get("collection", [])
            profile_id = data.get("profileId")
            if target_user_id and profile_id and profile_id != target_user_id:
                break

            for pid in data.get("pendingTradeCardIds", []):
                pending_ids.add(pid)

            available: List[UserCard] = []
            for it in items:
                card = UserCard.from_dict(it)
                if target_user_id and card.user_id and card.user_id != target_user_id:
                    continue
                if (
                    card.rarity == "C"
                    and not card.starred
                    and not card.is_shiny
                    and card.id not in pending_ids
                    and card.id not in currently_reserved
                ):
                    available.append(card)

            with self._lock:
                candidates = [
                    c for c in available
                    if c.id not in self._reserved_counterparty_ids
                ]
                if candidates:
                    picked = random.choice(candidates)
                    self._reserved_counterparty_ids.add(picked.id)
                    return {
                        "user_card_id": picked.id,
                        "card_id": picked.card_id,
                        "offered_by": target_user_id,
                    }

        logger.warning(
            f"{farm_client.account.prefix} No Common (C) found for counterparty. Trying Uncommon (PC)..."
        )
        for page in range(3):
            data = farm_client.get_profile_collection(
                username=target_username,
                page=page,
                rarity="PC",
                pending=1,
            )
            profile_id = data.get("profileId")
            if target_user_id and profile_id and profile_id != target_user_id:
                break

            items = data.get("collection", [])
            for pid in data.get("pendingTradeCardIds", []):
                pending_ids.add(pid)

            available = []
            for it in items:
                card = UserCard.from_dict(it)
                if target_user_id and card.user_id and card.user_id != target_user_id:
                    continue
                if (
                    card.rarity == "PC"
                    and not card.starred
                    and not card.is_shiny
                    and card.id not in pending_ids
                    and card.id not in currently_reserved
                ):
                    available.append(card)

            with self._lock:
                candidates = [
                    c for c in available
                    if c.id not in self._reserved_counterparty_ids
                ]
                if candidates:
                    picked = random.choice(candidates)
                    self._reserved_counterparty_ids.add(picked.id)
                    return {
                        "user_card_id": picked.id,
                        "card_id": picked.card_id,
                        "offered_by": target_user_id,
                    }

        logger.error(f"{farm_client.account.prefix} Could not find any counterparty card from {target_username}.")
        return None

    def select_cards_to_transfer(
        self,
        farm_client: WikiMastersClient,
        target_owned_ids: Set[str],
    ) -> List[UserCard]:
        all_cards = self.collection_service.fetch_full_collection(farm_client)
        if not all_cards:
            return []

        first_page = farm_client.get_my_collection(page=0, stats=0)
        pending_ids = set(first_page.get("pendingTradeCardIds", []))

        available_cards = [c for c in all_cards if c.id not in pending_ids and not c.starred]
        available_cards.sort(key=lambda c: c.rarity_rank, reverse=True)

        missing_cards: List[UserCard] = []
        covered_missing: Set[str] = set()
        valuable_duplicates: List[UserCard] = []
        uncommon_duplicates: List[UserCard] = []

        for card in available_cards:
            cid = card.card_id
            r = card.rarity

            if cid not in target_owned_ids and cid not in covered_missing:
                missing_cards.append(card)
                covered_missing.add(cid)
            elif r in VALUABLE_DUPLICATE_RARITIES:
                valuable_duplicates.append(card)
            elif r == "PC":
                uncommon_duplicates.append(card)

        selected = (missing_cards + valuable_duplicates + uncommon_duplicates)[:MAX_CARDS_PER_TRADE]

        if not selected and farm_client.account.wikibidous_balance > 0 and available_cards:
            selected = [available_cards[0]]

        return selected

    def send_farm_trade(
        self,
        farm_client: WikiMastersClient,
        target_username: str,
        target_user_id: str,
        target_owned_ids: Set[str],
    ) -> TradeResult:
        if farm_client.account.is_target:
            return TradeResult(status="target_account")

        farm_client.account.wikibidous_balance = farm_client.get_wikibidous()

        selected_cards = self.select_cards_to_transfer(farm_client, target_owned_ids)
        wb_to_send = min(farm_client.account.wikibidous_balance, MAX_WB_PER_TRADE)

        if not selected_cards and wb_to_send == 0:
            logger.info(f"{farm_client.account.prefix} Nothing to transfer (0 cards, 0 WB).")
            return TradeResult(status="empty")

        farm_user_id = farm_client.account.user_id
        if not farm_user_id:
            uid, _ = extract_session_user(farm_client.session_manager.get_cookies(farm_client.account))
            farm_user_id = uid
            farm_client.account.user_id = uid

        trade_items = [
            {
                "user_card_id": c.id,
                "card_id": c.card_id,
                "offered_by": farm_user_id or c.user_id,
            }
            for c in selected_cards
        ]

        counterparty_card = self.find_counterparty_card(
            farm_client=farm_client,
            target_username=target_username,
            target_user_id=target_user_id,
        )
        if counterparty_card:
            trade_items.append(counterparty_card)

        missing_count = sum(1 for c in selected_cards if c.card_id not in target_owned_ids)
        logger.info(
            f"{farm_client.account.prefix} Proposing trade to {target_username}: "
            f"{len(selected_cards)} cards ({missing_count} missing), {wb_to_send} WB."
        )

        res = farm_client.create_trade(
            recipient_id=target_user_id,
            items=trade_items,
            initiator_wikibidous=wb_to_send,
            recipient_wikibidous=0,
        )

        status_code = res.get("_status_code")
        if status_code in (200, 201) or "trade" in res or "id" in res:
            logger.info(f"{farm_client.account.prefix} Trade proposal submitted successfully.")
            self.record_account_trade(
                email=farm_client.account.email,
                trades_sent=1,
                cards_sent=len(selected_cards),
                wikibidous_sent=wb_to_send,
            )
            return TradeResult(
                trades_sent=1,
                cards_sent=len(selected_cards),
                wb_sent=wb_to_send,
                status="ok",
            )
        else:
            if counterparty_card:
                self.release_counterparty_id(counterparty_card["user_card_id"])

            error_msg = res.get("error", "Unknown trade error")
            code = res.get("code")

            if code == "trade_funnel_limit" or "don sans contrepartie" in error_msg.lower():
                logger.warning(f"{farm_client.account.prefix} Funnel limit reached: {error_msg}")
                return TradeResult(status="trade_funnel_limit", error_message=error_msg)

            logger.error(f"{farm_client.account.prefix} Trade submission failed: {error_msg}")
            return TradeResult(status="error", error_message=error_msg)

    def accept_incoming_trades(
        self,
        target_client: WikiMastersClient,
        allowed_user_ids: Set[str],
        allowed_usernames: Set[str],
    ) -> int:
        time.sleep(2.0)
        logger.info(f"{target_client.account.prefix} Reviewing incoming trade offers...")
        trades = target_client.get_trades(active_only=True)
        pending_trades = [Trade.from_dict(t) for t in trades if t.get("status") == "pending"]

        if not pending_trades:
            logger.info(f"{target_client.account.prefix} No pending trades to accept.")
            return 0

        target_uid = target_client.account.user_id or target_client.get_friends().get("user_id")
        allowed_names_lower = {n.lower() for n in allowed_usernames if n}

        accepted_count = 0
        for trade in pending_trades:
            initiator_id = trade.initiator_id
            initiator_name = (trade.initiator_username or "").lower()

            is_allowed = (
                (initiator_id and initiator_id in allowed_user_ids)
                or (initiator_name and initiator_name in allowed_names_lower)
            )

            recipient_wb_demanded = trade.recipient_wikibidous
            cards_asked_from_target = [
                item for item in trade.items
                if item.offered_by == target_uid or (trade.recipient_id and item.offered_by == trade.recipient_id)
            ]

            card_check_passed = False
            if len(cards_asked_from_target) == 0:
                card_check_passed = True
            elif is_allowed and len(cards_asked_from_target) <= 1:
                asked_card = cards_asked_from_target[0]
                asked_rarity = (asked_card.card.rarity if asked_card.card else "C").upper()
                if asked_rarity in ("C", "PC"):
                    card_check_passed = True

            if not is_allowed or recipient_wb_demanded > 1 or not card_check_passed:
                reason = (
                    "Unrecognized initiator" if not is_allowed
                    else f"Demanded {recipient_wb_demanded} WB" if recipient_wb_demanded > 1
                    else "Suspicious card demanded"
                )
                logger.warning(
                    f"{target_client.account.prefix} Declining trade {trade.id} from {trade.initiator_username}: {reason}."
                )
                target_client.patch_trade(trade.id, "decline")
                continue

            res = target_client.patch_trade(trade.id, "accept")
            if res.get("_status_code") == 200:
                accepted_count += 1
                logger.info(
                    f"{target_client.account.prefix} Accepted trade {trade.id} from {trade.initiator_username} "
                    f"(+{len(trade.items) - len(cards_asked_from_target)} cards, +{trade.initiator_wikibidous} WB)."
                )
                new_card_ids = [
                    item.card_id for item in trade.items
                    if item.offered_by != target_uid and item.card_id
                ]
                if new_card_ids:
                    self.collection_service.add_target_owned_ids(new_card_ids)
            else:
                error_msg = str(res.get("error", ""))
                code = res.get("code")
                if code == "human_verification_required" or res.get("human_verification_required"):
                    logger.error(
                        f"{target_client.account.prefix} Turnstile verification required to accept trade. Aborting."
                    )
                    break

                logger.warning(
                    f"{target_client.account.prefix} Could not accept trade {trade.id}: {error_msg}. Declining to release escrow..."
                )
                target_client.patch_trade(trade.id, "decline")

                if "limite quotidienne" in error_msg.lower() or "50/jour" in error_msg.lower():
                    logger.warning(f"{target_client.account.prefix} Target daily trade limit reached.")
                    self.mark_target_daily_limit_reached()
                    curr_idx = pending_trades.index(trade)
                    for rem_trade in pending_trades[curr_idx + 1:]:
                        target_client.patch_trade(rem_trade.id, "decline")
                    break

        return accepted_count
