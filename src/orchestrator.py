import concurrent.futures
import json
import logging
import threading
import time
from typing import List, Optional, Set, Dict, Any
from pathlib import Path

from src.config import (
    ACCOUNTS_FILE,
    KNOWN_ACCOUNTS_FILE,
    DEFAULT_TARGET_USERNAME,
    DEFAULT_TARGET_EMAIL,
    DEFAULT_TARGET_ID,
    MAX_CONCURRENT_CLIENTS,
)
from src.models.account import Account
from src.api.client import WikiMastersClient
from src.api.session_manager import SessionManager
from src.services.collection_service import CollectionService
from src.services.pack_service import PackService
from src.services.discard_service import DiscardService
from src.services.friend_service import FriendService
from src.services.trade_service import TradeService
from src.services.achievement_service import AchievementService
from src.logger import print_phase, print_summary_table

logger = logging.getLogger(__name__)


class BotOrchestrator:
    def __init__(
        self,
        accounts_path: Path = ACCOUNTS_FILE,
        known_accounts_path: Path = KNOWN_ACCOUNTS_FILE,
    ):
        self.accounts_path = accounts_path
        self.known_accounts_path = known_accounts_path
        self.session_manager = SessionManager()

        self.collection_service = CollectionService()
        self.pack_service = PackService()
        self.discard_service = DiscardService(self.collection_service)
        self.friend_service = FriendService()
        self.trade_service = TradeService(self.collection_service)
        self.achievement_service = AchievementService()

        self.accounts: List[Account] = []
        self.target_account: Optional[Account] = None
        self.farm_accounts: List[Account] = []
        self.known_user_ids: Set[str] = set()
        self.known_usernames: Set[str] = set()
        self._lock = threading.Lock()
        self._funnel_limit_hit = False

        self._load_accounts()
        self._load_known_accounts()

    def _load_accounts(self) -> None:
        if not self.accounts_path.exists():
            raise FileNotFoundError(f"Accounts file not found: {self.accounts_path}")

        with open(self.accounts_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        self.accounts = [Account.from_dict(item) for item in raw_data if isinstance(item, dict)]
        for acc in self.accounts:
            if acc.is_target or acc.email.lower() == DEFAULT_TARGET_EMAIL.lower():
                acc.is_target = True
                if not self.target_account:
                    self.target_account = acc
            else:
                self.farm_accounts.append(acc)

        if not self.target_account and self.accounts:
            self.target_account = self.accounts[0]
            self.target_account.is_target = True
            self.farm_accounts = self.accounts[1:]

        logger.info(
            f"Loaded {len(self.accounts)} accounts: Target='{self.target_account.display_name}', "
            f"Farms={len(self.farm_accounts)}"
        )

    def _load_known_accounts(self) -> None:
        if not self.known_accounts_path.exists():
            return
        try:
            with open(self.known_accounts_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.known_user_ids = set(data.get("user_ids", []))
                self.known_usernames = set(data.get("usernames", []))
        except Exception as e:
            logger.warning(f"Could not load known accounts: {e}")

    def register_known_account(self, user_id: Optional[str], username: Optional[str]) -> None:
        with self._lock:
            changed = False
            if user_id and user_id not in self.known_user_ids:
                self.known_user_ids.add(user_id)
                changed = True
            if username and username not in self.known_usernames:
                self.known_usernames.add(username)
                changed = True

            if changed:
                try:
                    temp_path = self.known_accounts_path.with_suffix(".tmp")
                    with open(temp_path, "w", encoding="utf-8") as f:
                        json.dump(
                            {
                                "user_ids": sorted(list(self.known_user_ids)),
                                "usernames": sorted(list(self.known_usernames)),
                            },
                            f,
                            indent=2,
                        )
                    temp_path.replace(self.known_accounts_path)
                except Exception as e:
                    logger.error(f"Failed to save known_accounts: {e}")

    def _process_single_farm(
        self,
        farm_acc: Account,
        idx: int,
        total_farms: int,
        target_uid: str,
        target_username: str,
        target_owned_ids: Set[str],
        skip_packs: bool,
        skip_trades: bool,
        force_trade: bool,
    ) -> Dict[str, Any]:
        logger.info(f"[{idx}/{total_farms}] Starting {farm_acc.prefix}...")
        report = {
            "email": farm_acc.email,
            "packs": 0,
            "discarded": "+0 WB",
            "transfer": "-",
            "status": "OK",
            "packs_count": 0,
            "discarded_count": 0,
            "trades_sent": 0,
            "cards_sent": 0,
            "wb_sent": 0,
        }
        try:
            with WikiMastersClient(farm_acc, self.session_manager) as farm_client:
                farm_uid = farm_acc.user_id or farm_client.account.user_id
                friends_data = farm_client.get_friends()
                if not farm_uid and friends_data.get("user_id"):
                    farm_uid = friends_data.get("user_id")
                farm_acc.user_id = farm_uid

                for f in friends_data.get("friendships", []):
                    for side in ("requester", "addressee"):
                        u = f.get(side, {})
                        if u.get("id") == farm_uid and u.get("username"):
                            farm_acc.username = u.get("username")
                            farm_client.account.username = u.get("username")

                if farm_uid:
                    self.register_known_account(farm_uid, farm_acc.username)

                self.friend_service.ensure_friendship(farm_client, target_username, target_uid)

                if not skip_packs:
                    packs_opened, _ = self.pack_service.open_all_packs(farm_client)
                    report["packs"] = packs_opened
                    report["packs_count"] = packs_opened
                else:
                    report["packs"] = "Ignoré"

                try:
                    self.achievement_service.claim_all_achievements(farm_client)
                except Exception as e:
                    logger.warning(f"{farm_client.account.prefix} Error claiming achievements: {e}")

                discarded = self.discard_service.discard_excess_cards(farm_client, target_owned_ids)
                report["discarded"] = f"+{discarded} WB"
                report["discarded_count"] = discarded

                if skip_trades:
                    report["transfer"] = "Ignoré (--skip-trades)"
                elif self._funnel_limit_hit:
                    report["transfer"] = "Plafond dons atteint"
                else:
                    can_trade, trade_reason = self.trade_service.can_account_trade(
                        farm_acc.email, force=force_trade
                    )
                    if not can_trade:
                        report["transfer"] = trade_reason
                    else:
                        trade_res = self.trade_service.send_farm_trade(
                            farm_client=farm_client,
                            target_username=target_username,
                            target_user_id=target_uid,
                            target_owned_ids=target_owned_ids,
                        )

                        if trade_res.status == "ok":
                            report["trades_sent"] = trade_res.trades_sent
                            report["cards_sent"] = trade_res.cards_sent
                            report["wb_sent"] = trade_res.wb_sent
                            parts = []
                            if trade_res.cards_sent > 0:
                                parts.append(f"{trade_res.cards_sent} c.")
                            if trade_res.wb_sent > 0:
                                parts.append(f"{trade_res.wb_sent} WB")
                            report["transfer"] = " + ".join(parts) if parts else "0"
                            report["status"] = "OK"
                        elif trade_res.status == "trade_funnel_limit":
                            self._funnel_limit_hit = True
                            report["status"] = "Plafond dons"
                            logger.warning(
                                "Target account hit weekly trade_funnel_limit. Skipping further trade proposals for this run."
                            )
                        elif trade_res.status == "empty":
                            report["transfer"] = "Rien à transférer"
                        else:
                            report["status"] = trade_res.error_message or "Erreur trade"

        except Exception as e:
            logger.error(f"Error processing {farm_acc.prefix}: {e}", exc_info=True)
            report["status"] = "Erreur"

        logger.info(f"[{idx}/{total_farms}] Done {farm_acc.prefix}: {report['status']} ({report['transfer']}, {report['discarded']})")
        return report

    def run_pipeline(
        self,
        account_limit: Optional[int] = None,
        selected_emails: Optional[List[str]] = None,
        skip_packs: bool = False,
        skip_trades: bool = False,
        concurrency: int = MAX_CONCURRENT_CLIENTS,
        force_trade: bool = False,
    ) -> Dict[str, Any]:
        start_time = time.time()
        logger.info(f"Starting farming pipeline ({concurrency} workers)")

        farms_to_process = self.farm_accounts
        if selected_emails:
            lower_emails = [e.lower() for e in selected_emails]
            farms_to_process = [a for a in farms_to_process if a.email.lower() in lower_emails]
        if account_limit:
            farms_to_process = farms_to_process[:account_limit]

        target_username = DEFAULT_TARGET_USERNAME
        target_uid = None
        target_packs_opened = 0

        print_phase(1, "Target Account Setup")
        with WikiMastersClient(self.target_account, self.session_manager) as target_client:
            target_uid = target_client.account.user_id or DEFAULT_TARGET_ID
            target_username = None

            try:
                profile = target_client.get_my_profile()
                if profile and profile.get("id"):
                    target_uid = profile["id"]
                    target_username = profile.get("username")
            except Exception:
                pass

            if not target_username or target_username == "3d3nDEV":
                friends_info = target_client.get_friends()
                for f in friends_info.get("friendships", []):
                    for side in ("requester", "addressee"):
                        u = f.get(side, {})
                        if u.get("id") == target_uid and u.get("username") is not None:
                            target_username = u.get("username")
                            break
                    if target_username and target_username != "3d3nDEV":
                        break

            if not target_username:
                target_username = DEFAULT_TARGET_USERNAME

            self.target_account.user_id = target_uid
            self.target_account.username = target_username
            target_client.account.user_id = target_uid
            target_client.account.username = target_username
            self.register_known_account(target_uid, target_username)

            self.friend_service.accept_all_on_target(target_client)

            target_packs_opened = 0
            if not skip_packs:
                target_packs_opened, new_target_card_ids = self.pack_service.open_all_packs(target_client)
                if target_packs_opened > 0:
                    logger.info(f"{target_client.account.prefix} Opened {target_packs_opened} pack(s) on main account.")
                    if new_target_card_ids:
                        self.collection_service.add_target_owned_ids(new_target_card_ids)
                try:
                    self.achievement_service.claim_all_achievements(target_client)
                except Exception as e:
                    logger.warning(f"{target_client.account.prefix} Error claiming achievements on target: {e}")

            target_owned_ids = self.collection_service.get_target_owned_ids()
            if len(target_owned_ids) < 100:
                self.collection_service.sync_target_collection(target_client)
                target_owned_ids = self.collection_service.get_target_owned_ids()
            else:
                logger.info(f"{target_client.account.prefix} Reusing cached collection ({len(target_owned_ids)} unique cards).")

            if self.trade_service.is_target_daily_limit_reached():
                logger.warning(
                    f"{target_client.account.prefix} Daily trade limit reached for today "
                    f"({self.trade_service.get_daily_target_trades()}/50 trades). Farm bots will skip proposing trades."
                )

        logger.info(f"Target initialized: UID={target_uid}, Username='{target_username}', Owned Cards={len(target_owned_ids)}")

        print_phase(2, f"Processing {len(farms_to_process)} Farm Accounts ({concurrency} workers)")
        self._funnel_limit_hit = False

        total_packs_opened = 0
        total_cards_discarded = 0
        total_trades_sent = 0
        total_cards_sent = 0
        total_wb_sent = 0

        reports_by_email: Dict[str, Dict[str, Any]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            future_to_acc = {
                executor.submit(
                    self._process_single_farm,
                    farm_acc,
                    idx,
                    len(farms_to_process),
                    target_uid,
                    target_username,
                    target_owned_ids,
                    skip_packs,
                    skip_trades,
                    force_trade,
                ): farm_acc
                for idx, farm_acc in enumerate(farms_to_process, 1)
            }

            for future in concurrent.futures.as_completed(future_to_acc):
                farm_acc = future_to_acc[future]
                try:
                    reports_by_email[farm_acc.email] = future.result()
                except Exception as e:
                    logger.error(f"Error in thread for {farm_acc.prefix}: {e}", exc_info=True)
                    reports_by_email[farm_acc.email] = {
                        "email": farm_acc.email,
                        "packs": 0,
                        "discarded": "+0 WB",
                        "transfer": "-",
                        "status": "Erreur",
                        "packs_count": 0,
                        "discarded_count": 0,
                        "trades_sent": 0,
                        "cards_sent": 0,
                        "wb_sent": 0,
                    }

        report_data: List[dict] = []
        for farm_acc in farms_to_process:
            rep = reports_by_email.get(farm_acc.email, {
                "email": farm_acc.email,
                "packs": 0,
                "discarded": "+0 WB",
                "transfer": "-",
                "status": "Inconnu",
                "packs_count": 0,
                "discarded_count": 0,
                "trades_sent": 0,
                "cards_sent": 0,
                "wb_sent": 0,
            })
            total_packs_opened += rep.get("packs_count", 0)
            total_cards_discarded += rep.get("discarded_count", 0)
            total_trades_sent += rep.get("trades_sent", 0)
            total_cards_sent += rep.get("cards_sent", 0)
            total_wb_sent += rep.get("wb_sent", 0)
            report_data.append({
                "email": rep["email"],
                "packs": rep["packs"],
                "discarded": rep["discarded"],
                "transfer": rep["transfer"],
                "status": rep["status"],
            })

        print_phase(3, "Target Harvesting Trades")
        accepted_trades_count = 0
        with WikiMastersClient(self.target_account, self.session_manager) as target_client:
            accepted_trades_count = self.trade_service.accept_incoming_trades(
                target_client=target_client,
                allowed_user_ids=self.known_user_ids,
                allowed_usernames=self.known_usernames,
            )
            stats = target_client.get_my_stats()
            final_target_total = stats.get("total", len(self.collection_service.get_target_owned_ids()))

        duration = time.time() - start_time
        summary = {
            "duration_seconds": round(duration, 1),
            "farm_accounts_processed": len(farms_to_process),
            "target_packs_opened": target_packs_opened,
            "total_packs_opened": total_packs_opened,
            "total_cards_discarded": total_cards_discarded,
            "total_trades_sent": total_trades_sent,
            "total_trades_accepted": accepted_trades_count,
            "total_cards_sent": total_cards_sent,
            "total_wb_sent": total_wb_sent,
            "final_target_collection_count": final_target_total,
            "funnel_limit_hit": self._funnel_limit_hit,
            "target_daily_limit_reached": self.trade_service.is_target_daily_limit_reached(),
        }

        print_summary_table(report_data, summary)
        return summary
