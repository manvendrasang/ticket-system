"""
ShopWave Autonomous Support Resolution Agent
Entry point — processes all tickets concurrently with bounded semaphore.

Usage:
    python -m app.main
    python -m app.main --tickets TKT-008 TKT-018   # specific tickets
    python -m app.main --max-concurrent 3           # override concurrency
"""

import asyncio
import os
import sys
import time
import argparse
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
)
from rich import print as rprint
from rich.text import Text

from app.ingestion.loader import load_tickets, load_tickets_by_ids
from app.agents.resolver import process_ticket

console = Console()

MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_TICKETS", "5"))


async def process_all_tickets(
    tickets: list[dict], max_concurrent: int = MAX_CONCURRENT
) -> list[dict]:
    """
    Process all tickets concurrently with a bounded semaphore.
    Uses asyncio.TaskGroup for structured concurrency (Python 3.11+).
    """
    sem = asyncio.Semaphore(max_concurrent)
    results = []
    results_lock = asyncio.Lock()

    async def run_with_sem(ticket: dict) -> None:
        async with sem:
            tid = ticket["ticket_id"]
            console.log(f"[cyan]→ Starting[/cyan] {tid}: {ticket['subject'][:50]}")
            try:
                result = await process_ticket(ticket)
                async with results_lock:
                    results.append(result)

                # Pretty status line
                outcome = result.get("outcome", "unknown")
                escalated = result.get("escalated", False)
                duration = result.get("processing_duration_ms", 0)
                tool_count = len(result.get("tool_calls", []))

                if escalated:
                    status = "[yellow]↑ ESCALATED[/yellow]"
                elif outcome == "refund_issued":
                    status = "[green]✓ REFUND ISSUED[/green]"
                elif outcome == "error":
                    status = "[red]✗ ERROR[/red]"
                else:
                    status = f"[green]✓ {outcome.upper().replace('_', ' ')}[/green]"

                console.log(f"{status} {tid} | {tool_count} tools | {duration}ms")
            except Exception as e:
                console.log(f"[red]✗ FAILED[/red] {tid}: {e}")
                async with results_lock:
                    results.append(
                        {
                            "ticket_id": tid,
                            "outcome": "error",
                            "error": str(e),
                            "escalated": True,
                            "tool_calls": [],
                        }
                    )

    async with asyncio.TaskGroup() as tg:
        for ticket in tickets:
            tg.create_task(run_with_sem(ticket))

    return results


def print_summary(results: list[dict], elapsed: float) -> None:
    """Print a rich summary table of all processed tickets."""
    table = Table(title="ShopWave Agent — Processing Summary", show_lines=True)
    table.add_column("Ticket", style="bold")
    table.add_column("Outcome", justify="center")
    table.add_column("Tools", justify="right")
    table.add_column("Tier")
    table.add_column("Confidence", justify="right")
    table.add_column("ms", justify="right")
    table.add_column("Escalated", justify="center")

    outcome_counts = {}

    for r in sorted(results, key=lambda x: x.get("ticket_id", "")):
        outcome = r.get("outcome", "unknown")
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        escalated = r.get("escalated", False)
        confidence = r.get("confidence") or 0.0
        tool_count = len(r.get("tool_calls", []))
        duration = r.get("processing_duration_ms", 0)
        tier = r.get("customer_tier") or "—"

        if outcome == "refund_issued":
            outcome_style = "[green]refund_issued[/green]"
        elif outcome == "escalated":
            outcome_style = "[yellow]escalated[/yellow]"
        elif outcome == "error":
            outcome_style = "[red]error[/red]"
        else:
            outcome_style = f"[cyan]{outcome}[/cyan]"

        table.add_row(
            r.get("ticket_id", "?"),
            outcome_style,
            str(tool_count),
            tier,
            f"{confidence:.2f}",
            str(duration),
            "⚠️" if escalated else "✓",
        )

    console.print()
    console.print(table)

    # Stats panel
    total = len(results)
    escalated_count = sum(1 for r in results if r.get("escalated"))
    resolved = total - escalated_count
    avg_tools = sum(len(r.get("tool_calls", [])) for r in results) / max(total, 1)

    stats = (
        f"[bold]Total tickets:[/bold] {total}  |  "
        f"[green]Auto-resolved:[/green] {resolved}  |  "
        f"[yellow]Escalated:[/yellow] {escalated_count}  |  "
        f"[cyan]Avg tools/ticket:[/cyan] {avg_tools:.1f}  |  "
        f"[dim]Wall time:[/dim] {elapsed:.1f}s  |  "
        f"[dim]Max concurrent:[/dim] {MAX_CONCURRENT}"
    )

    console.print(Panel(stats, title="Run Statistics", border_style="blue"))
    console.print(
        f"\n[dim]Audit log written to:[/dim] [bold]logs/audit_log.json[/bold]"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ShopWave Autonomous Support Agent")
    parser.add_argument(
        "--tickets",
        nargs="+",
        metavar="TICKET_ID",
        help="Process specific tickets only (e.g., TKT-008 TKT-018)",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=MAX_CONCURRENT,
        help=f"Max concurrent tickets (default: {MAX_CONCURRENT})",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    console.print(
        Panel(
            "[bold blue]ShopWave Autonomous Support Resolution Agent[/bold blue]\n"
            "[dim]Python + Anthropic Claude + Async Concurrency[/dim]",
            border_style="blue",
        )
    )

    # Load tickets
    if args.tickets:
        tickets = load_tickets_by_ids(args.tickets)
        console.print(
            f"[bold]Loaded {len(tickets)} specific ticket(s):[/bold] {', '.join(args.tickets)}"
        )
    else:
        tickets = load_tickets()
        console.print(
            f"[bold]Loaded {len(tickets)} tickets[/bold] from data/tickets.json"
        )

    if not tickets:
        console.print("[red]No tickets to process.[/red]")
        return

    failure_sim = os.environ.get("FAILURE_SIMULATION", "true").lower() == "true"
    console.print(
        f"[dim]Max concurrent: {args.max_concurrent} | Failure simulation: {failure_sim}[/dim]\n"
    )

    t0 = time.monotonic()
    results = await process_all_tickets(tickets, max_concurrent=args.max_concurrent)
    elapsed = time.monotonic() - t0

    print_summary(results, elapsed)


if __name__ == "__main__":
    asyncio.run(main())
