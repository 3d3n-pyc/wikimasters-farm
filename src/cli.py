import argparse
from src.logger import setup_logging, print_banner
from src.orchestrator import BotOrchestrator
from src.api.client import WikiMastersClient


def main() -> None:
    parser = argparse.ArgumentParser(description="WikiMasters farming bot.")
    parser.add_argument("--limit", "-l", type=int, default=None, help="Limit execution to N farm accounts.")
    parser.add_argument("--accounts", "-a", nargs="+", default=None, help="Filter execution to specific account emails.")
    parser.add_argument("--skip-packs", action="store_true", help="Skip opening booster packs.")
    parser.add_argument("--skip-trades", action="store_true", help="Skip proposing and accepting trades.")
    parser.add_argument("--accept-only", action="store_true", help="Only accept incoming trades on the target account.")
    parser.add_argument("--sync-target", action="store_true", help="Only refresh the main target collection cache.")
    parser.add_argument("--concurrency", "-c", type=int, default=3, help="Number of farm accounts to process concurrently.")
    parser.add_argument("--force-trade", action="store_true", help="Force trade execution even if already completed today.")
    parser.add_argument("--debug", action="store_true", help="Enable detailed debug logging.")

    args = parser.parse_args()
    setup_logging(debug=args.debug)
    print_banner()

    orchestrator = BotOrchestrator()

    if args.sync_target:
        with WikiMastersClient(orchestrator.target_account, orchestrator.session_manager) as client:
            count = orchestrator.collection_service.sync_target_collection(client)
            print(f"Target collection synced: {count} cards.")
        return

    if args.accept_only:
        with WikiMastersClient(orchestrator.target_account, orchestrator.session_manager) as client:
            accepted = orchestrator.trade_service.accept_incoming_trades(
                target_client=client,
                allowed_user_ids=orchestrator.known_user_ids,
                allowed_usernames=orchestrator.known_usernames,
            )
            print(f"Accepted {accepted} trade(s).")
        return

    orchestrator.run_pipeline(
        account_limit=args.limit,
        selected_emails=args.accounts,
        skip_packs=args.skip_packs,
        skip_trades=args.skip_trades,
        concurrency=args.concurrency,
        force_trade=args.force_trade,
    )


if __name__ == "__main__":
    main()
