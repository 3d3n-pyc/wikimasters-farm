import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from src.config import DATA_DIR

CUSTOM_THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "critical": "bold white on red",
    "success": "bold green",
    "dim": "dim",
    "highlight": "bold magenta",
})

console = Console(theme=CUSTOM_THEME)
LOG_FILE = DATA_DIR / "bot.log"


def setup_logging(debug: bool = False, log_file: Optional[Path] = LOG_FILE) -> logging.Logger:
    level = logging.DEBUG if debug else logging.INFO

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    rich_handler = RichHandler(
        console=console,
        show_time=True,
        omit_repeated_times=False,
        show_level=True,
        show_path=debug,
        markup=False,
        rich_tracebacks=True,
        tracebacks_show_locals=debug,
    )
    rich_handler.setLevel(level)
    rich_handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
    root_logger.addHandler(rich_handler)

    if log_file:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)-7s] [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
            )
            root_logger.addHandler(file_handler)
        except Exception as e:
            console.print(f"[warning]Warning: could not configure log file {log_file}: {e}[/warning]")

    noisy_loggers = [
        "httpx",
        "httpcore",
        "urllib3",
        "camoufox",
        "playwright",
        "asyncio",
    ]
    for name in noisy_loggers:
        logging.getLogger(name).setLevel(logging.DEBUG if debug else logging.WARNING)

    return root_logger


def print_banner(version: str = "2.0") -> None:
    banner_text = Text()
    banner_text.append(" WikiMasters Farm ", style="bold cyan")
    banner_text.append(f"v{version}", style="bold magenta")
    console.print(Panel(banner_text, border_style="cyan", padding=(0, 2)))


def print_phase(phase_num: int, title: str) -> None:
    console.print()
    console.rule(f"[bold cyan]Phase {phase_num}: {title}[/bold cyan]", style="cyan")


def print_summary_table(
    report_data: List[Dict[str, Any]],
    summary_stats: Dict[str, Any],
) -> None:
    table = Table(
        title="Pipeline Execution Summary",
        title_style="bold cyan",
        header_style="bold magenta",
        border_style="dim",
        show_footer=True,
    )

    table.add_column("Account", style="cyan", footer="Total")
    table.add_column("Packs", justify="center", footer=str(summary_stats.get("total_packs_opened", 0)))
    table.add_column("Discarded", justify="center", footer=f"+{summary_stats.get('total_cards_discarded', 0)} WB")
    table.add_column("Transfer", justify="right", footer=f"{summary_stats.get('total_cards_sent', 0)} c. + {summary_stats.get('total_wb_sent', 0)} WB")
    table.add_column("Status", justify="center")

    for r in report_data:
        email = r.get("email", "-")
        packs = str(r.get("packs", 0))
        discarded = str(r.get("discarded", "-"))
        transfer = str(r.get("transfer", "-"))
        status = r.get("status", "OK")

        if "ok" in status.lower() or "succès" in status.lower() or "terminé" in status.lower():
            status_styled = f"[green]✓ {status}[/green]"
        elif "limit" in status.lower() or "limite" in status.lower() or "attente" in status.lower():
            status_styled = f"[yellow]⏳ {status}[/yellow]"
        elif "erreur" in status.lower() or "error" in status.lower():
            status_styled = f"[red]✗ {status}[/red]"
        else:
            status_styled = status

        table.add_row(email, packs, discarded, transfer, status_styled)

    console.print()
    console.print(table)

    duration = summary_stats.get("duration_seconds", 0)
    final_cards = summary_stats.get("final_target_collection_count", 0)
    accepted = summary_stats.get("total_trades_accepted", 0)
    target_packs = summary_stats.get("target_packs_opened", 0)

    stats_text = (
        f"[bold]Duration:[/bold] {duration}s  •  "
        f"[bold]Target Packs:[/bold] {target_packs}  •  "
        f"[bold]Trades Accepted:[/bold] {accepted}  •  "
        f"[bold]Target Collection:[/bold] [bold green]{final_cards:,}[/bold green] cards"
    )
    console.print(Panel(stats_text, title="Main Target Status", border_style="green", padding=(0, 2)))
    console.print()
