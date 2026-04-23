"""Evaluation harness.

Runs all tickets in test_tickets/tickets.yaml through the pipeline, scores:
  - Decision accuracy (answer / escalate)
  - Escalation-reason accuracy (for the escalate category)
  - Source precision (for expected-answer tickets with expected_source_any_of)
  - Latency p50 / p95 / mean

Writes eval_report.json with full per-ticket detail and prints a confusion
matrix + summary tables.

Usage:
  python eval.py              # full eval
  python eval.py --verbose    # also dump per-ticket reasoning trace
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

# Force UTF-8 on stdout so rich can print arrows/bullets on Windows cp1251 consoles.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import yaml
from rich import box
from rich.console import Console
from rich.table import Table

from src import pipeline
from src.config import backend, settings

ROOT = Path(__file__).resolve().parent
TICKETS = ROOT / "test_tickets" / "tickets.yaml"
REPORT = ROOT / "eval_report.json"


def load_tickets() -> list[dict]:
    with open(TICKETS, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list):
        raise ValueError("tickets.yaml must be a list")
    return data


def score_ticket(ticket: dict) -> dict:
    t0 = time.perf_counter()
    decision = pipeline.resolve(ticket["text"])
    ms = int((time.perf_counter() - t0) * 1000)

    expected_decision = ticket["expected_decision"]
    expected_reason = ticket.get("expected_reason")
    expected_sources = set(ticket.get("expected_source_any_of", []))

    decision_match = decision.decision == expected_decision

    reason_match: bool | None = None
    if expected_reason is not None:
        reason_match = decision.escalation_reason == expected_reason

    source_match: bool | None = None
    if expected_sources:
        source_match = bool(expected_sources.intersection(decision.sources or []))

    return {
        "id": ticket["id"],
        "category": ticket["category"],
        "text": ticket["text"],
        "expected": {
            "decision": expected_decision,
            "reason": expected_reason,
            "sources_any_of": list(expected_sources),
        },
        "actual": {
            "decision": decision.decision,
            "reason": decision.escalation_reason,
            "sources": decision.sources,
            "confidence": decision.confidence,
        },
        "decision_match": decision_match,
        "reason_match": reason_match,
        "source_match": source_match,
        "latency_ms": ms,
        "trace": [s.model_dump() for s in decision.reasoning_trace],
        "answer": decision.answer,
        "message_to_operator": decision.message_to_operator,
    }


def print_config(console: Console) -> None:
    t = Table(title="Eval configuration", box=box.SIMPLE)
    t.add_column("key")
    t.add_column("value")
    t.add_row("backend", backend())
    t.add_row("embedding_model", settings.embedding_model)
    t.add_row("sim_threshold", f"{settings.sim_threshold}")
    t.add_row("confidence_threshold", f"{settings.confidence_threshold}")
    t.add_row("top_k", f"{settings.top_k}")
    console.print(t)


def print_confusion(console: Console, rows: list[dict]) -> None:
    """Confusion matrix by expected category × actual (decision or reason)."""
    categories = ["answer", "low_retrieval", "high_risk", "out_of_scope"]
    actual_labels = ["answer", "low_retrieval", "high_risk_rg", "high_risk_legal",
                     "high_risk_fraud", "high_risk_selfharm", "out_of_scope",
                     "hallucination", "low_confidence"]

    def actual_label(r: dict) -> str:
        if r["actual"]["decision"] == "answer":
            return "answer"
        return r["actual"]["reason"] or "unknown"

    matrix: dict[str, dict[str, int]] = {c: {a: 0 for a in actual_labels} for c in categories}
    for r in rows:
        matrix[r["category"]][actual_label(r)] += 1

    t = Table(title="Confusion matrix (expected vs actual)", box=box.SIMPLE_HEAVY)
    t.add_column("expected \\ actual")
    for a in actual_labels:
        t.add_column(a, justify="right")
    for c in categories:
        row = [c]
        for a in actual_labels:
            n = matrix[c][a]
            row.append(f"[green]{n}[/green]" if n and a.startswith(c.split("_")[0])
                       else (f"{n}" if n else "."))
        t.add_row(*row)
    console.print(t)


def print_summary(console: Console, rows: list[dict]) -> None:
    n = len(rows)
    decision_correct = sum(1 for r in rows if r["decision_match"])
    reason_correct = sum(1 for r in rows if r["reason_match"] is True)
    reason_applicable = sum(1 for r in rows if r["reason_match"] is not None)
    source_correct = sum(1 for r in rows if r["source_match"] is True)
    source_applicable = sum(1 for r in rows if r["source_match"] is not None)

    latencies = [r["latency_ms"] for r in rows]
    p50 = int(statistics.median(latencies))
    p95 = int(sorted(latencies)[max(0, int(0.95 * len(latencies)) - 1)])
    mean = int(statistics.mean(latencies))

    t = Table(title="Summary", box=box.SIMPLE)
    t.add_column("metric"); t.add_column("value", justify="right")
    t.add_row("tickets", str(n))
    t.add_row("decision accuracy", f"{decision_correct}/{n}  ({100*decision_correct/n:.0f}%)")
    t.add_row("escalation-reason accuracy",
              f"{reason_correct}/{reason_applicable}  "
              f"({100*reason_correct/reason_applicable:.0f}%)" if reason_applicable else "n/a")
    t.add_row("source precision",
              f"{source_correct}/{source_applicable}  "
              f"({100*source_correct/source_applicable:.0f}%)" if source_applicable else "n/a")
    t.add_row("latency p50 / p95 / mean (ms)", f"{p50} / {p95} / {mean}")
    console.print(t)


def print_failures(console: Console, rows: list[dict]) -> None:
    fails = [r for r in rows if not r["decision_match"] or r["reason_match"] is False or r["source_match"] is False]
    if not fails:
        console.print("[bold green]No failures — all tickets passed.[/bold green]")
        return

    t = Table(title="Failures", box=box.SIMPLE_HEAVY, show_lines=True)
    t.add_column("id"); t.add_column("category")
    t.add_column("expected"); t.add_column("actual"); t.add_column("ticket (truncated)")
    for r in fails:
        exp = f"{r['expected']['decision']}" + (f" / {r['expected']['reason']}"
                                                if r['expected']['reason'] else "")
        act = f"{r['actual']['decision']}" + (f" / {r['actual']['reason']}"
                                              if r['actual']['reason'] else "")
        t.add_row(r["id"], r["category"], exp, act, r["text"][:70] + ("..." if len(r["text"]) > 70 else ""))
    console.print(t)


def main(verbose: bool = False) -> int:
    console = Console()
    console.rule("[bold]Eval — AurumPlay support RAG[/bold]")
    print_config(console)

    tickets = load_tickets()
    console.print(f"Running {len(tickets)} tickets…\n")

    rows: list[dict] = []
    for ticket in tickets:
        r = score_ticket(ticket)
        rows.append(r)
        ok = r["decision_match"] and (r["reason_match"] is not False) and (r["source_match"] is not False)
        tag = "[green]PASS[/green]" if ok else "[red]FAIL[/red]"
        console.print(f"  {tag} {r['id']:>3}  {r['latency_ms']:>5} ms  "
                      f"-> {r['actual']['decision']}"
                      f"{' / ' + (r['actual']['reason'] or '') if r['actual']['reason'] else ''}")

    console.print()
    print_confusion(console, rows)
    console.print()
    print_summary(console, rows)
    console.print()
    print_failures(console, rows)

    report = {
        "backend": backend(),
        "sim_threshold": settings.sim_threshold,
        "confidence_threshold": settings.confidence_threshold,
        "embedding_model": settings.embedding_model,
        "results": rows if verbose else [{k: v for k, v in r.items() if k != "trace"} for r in rows],
    }
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"\n[dim]Full report written to {REPORT}[/dim]")

    # Non-zero exit on any hard failure — useful in CI.
    hard_failures = sum(1 for r in rows if not r["decision_match"])
    return 1 if hard_failures else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--verbose", action="store_true",
                   help="Include reasoning_trace in the JSON report.")
    args = p.parse_args()
    sys.exit(main(verbose=args.verbose))
