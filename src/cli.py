"""CLI entry point. Run: python -m src.cli --help"""
from __future__ import annotations

from datetime import date, time
from pathlib import Path

import typer
from rich import print

from config import settings
from .data import kaggle_loader, feather_loader, storage
from .backtest import engine
from .backtest.strategy import Action, Leg, OptType, RiskRule, Selection, StrategySpec, Unit

app = typer.Typer(add_completion=False, help="Options backtest platform")


@app.command()
def info():
    """Show config + database status."""
    print(f"[bold]Alice Blue ready:[/bold] {settings.alice_ready}")
    print(f"[bold]DB:[/bold] {settings.db_path}")
    storage.init_db()
    for tbl, st in storage.verify().items():
        print(f"[bold]{tbl}[/bold]: {st['rows']:,} rows  {st['ts_min']} -> {st['ts_max']}  {st['by_underlying']}")


@app.command()
def initdb():
    """Create the database + tables if missing."""
    storage.init_db()
    print(f"[green]db ready[/green] {settings.db_path}")


@app.command()
def dedupe():
    """Remove duplicate-key option rows (keep highest volume/oi per key)."""
    storage.init_db()
    n = storage.dedupe_options()
    print(f"[green]deduped[/green] {n:,} duplicate-key rows")


@app.command()
def verify():
    """Integrity + coverage report (nulls, duplicates, ts range)."""
    storage.init_db()
    rep = storage.verify()
    ok = True
    for tbl, st in rep.items():
        bad = st["null_keys"] or st["dup_keys"]
        ok = ok and not bad
        tag = "[red]FAIL[/red]" if bad else "[green]OK[/green]"
        print(f"{tag} [bold]{tbl}[/bold] rows={st['rows']:,} "
              f"null_keys={st['null_keys']} dup_keys={st['dup_keys']}")
        print(f"     ts {st['ts_min']} -> {st['ts_max']}  by_underlying={st['by_underlying']}")
    print(("[green]integrity OK[/green]" if ok else "[red]integrity issues found[/red]"))


@app.command("kaggle-spot")
def kaggle_spot(
    slug: str = typer.Argument(..., help="kaggle dataset slug, e.g. debashis74017/nifty-50-minute-data"),
    underlying: str = typer.Option("NIFTY"),
    csv: str = typer.Option("", help="specific CSV filename in the dataset (else first .csv)"),
):
    """Download a Kaggle spot dataset and load 1-min candles into the lake."""
    settings.ensure_dirs()
    folder = kaggle_loader.download(slug)
    target = Path(folder) / csv if csv else next(Path(folder).rglob("*.csv"))
    n = kaggle_loader.load_spot_csv(target, underlying)
    print(f"[green]loaded[/green] {n} spot rows for {underlying} from {target.name}")


@app.command("ingest-options")
def ingest_options(
    underlying: str = typer.Argument(..., help="NIFTY or BANKNIFTY"),
    limit: int = typer.Option(0, help="max feather files (0 = all)"),
):
    """Load per-day NFO option feather files into the lake."""
    n = feather_loader.ingest(underlying.upper(), limit=limit or None)
    print(f"[green]ingested[/green] {n:,} option rows for {underlying.upper()}")


@app.command("ingest-spot")
def ingest_spot(
    csv: str = typer.Argument(..., help="path to spot 1-min CSV"),
    underlying: str = typer.Option(..., help="NIFTY or BANKNIFTY"),
):
    """Load a spot/index 1-min CSV into the database."""
    settings.ensure_dirs()
    removed = storage.clear_spot(underlying.upper())
    if removed:
        print(f"  cleared {removed:,} existing spot rows for {underlying.upper()}")
    n = kaggle_loader.load_spot_csv(Path(csv), underlying.upper())
    print(f"[green]loaded[/green] {n:,} spot rows for {underlying.upper()}")


@app.command()
def backtest(
    underlying: str = typer.Option("NIFTY"),
    start: str = typer.Option(..., help="YYYY-MM-DD"),
    end: str = typer.Option(..., help="YYYY-MM-DD"),
    entry: str = typer.Option("09:20", help="entry HH:MM"),
    exit_: str = typer.Option("15:15", "--exit", help="exit HH:MM"),
    sl: float = typer.Option(30.0, help="per-leg stoploss %% of entry premium (0 = none)"),
    target: float = typer.Option(0.0, help="per-leg target %% of entry premium (0 = none)"),
    offset: int = typer.Option(0, help="expiry offset (0 = nearest weekly)"),
    lots: int = typer.Option(1),
):
    """ATM short straddle backtest over a date range (auto weekly expiry)."""
    eh, em = map(int, entry.split(":"))
    xh, xm = map(int, exit_.split(":"))
    leg_sl = RiskRule(sl, Unit.PERCENT) if sl else None
    leg_tp = RiskRule(target, Unit.PERCENT) if target else None
    spec = StrategySpec(
        underlying=underlying.upper(),
        legs=[
            Leg(Action.SELL, OptType.CE, Selection.ATM, 0, lots, tp=leg_tp, sl=leg_sl),
            Leg(Action.SELL, OptType.PE, Selection.ATM, 0, lots, tp=leg_tp, sl=leg_sl),
        ],
        entry_time=time(eh, em),
        exit_time=time(xh, xm),
        expiry_offset=offset,
    )
    res = engine.run_range(spec, date.fromisoformat(start), date.fromisoformat(end))
    s = res.stats
    reasons: dict[str, int] = {}
    for t in res.trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
    print(f"[bold cyan]{underlying.upper()} short straddle[/bold cyan] {start}->{end}")
    print(f"[bold]trades[/bold] {s.trades}  [bold]win%[/bold] {s.win_rate:.1%}  exits {reasons}")
    print(f"[bold]net PnL[/bold] {s.net_pnl:,.0f}  [bold]expectancy/trade[/bold] {s.expectancy:,.0f}")
    print(f"[bold]avg win[/bold] {s.avg_win:,.0f}  [bold]avg loss[/bold] {s.avg_loss:,.0f}")
    print(f"[bold]maxDD[/bold] {s.max_drawdown:,.0f}  [bold]Sharpe[/bold] {s.sharpe:.2f}")


@app.command()
def record(symbols: str = typer.Option("NIFTY,BANKNIFTY")):
    """Start live 1-min recorder (needs approved API + creds)."""
    from .data import recorder
    recorder.run(symbols.split(","))


if __name__ == "__main__":
    app()
