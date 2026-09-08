"""Interfaz de línea de comandos.

  python -m cheapflights run --kind domestic        # busca y avisa
  python -m cheapflights run --group "Sudamérica"
  python -m cheapflights digest                     # resumen por continente
  python -m cheapflights show BGA-BOG               # calendario de una ruta
  --dry-run: no envía WhatsApp, imprime.  --mock: no consulta Google (pruebas).
"""

from __future__ import annotations

import logging
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import click

from . import __version__
from .alerts import Alert, evaluate
from .config import Config, Group, load_config
from .digest import build_digest
from .history import History
from .notify import ConsoleNotifier, build_notifier, fmt_date, fmt_price, format_alerts_batch
from .search import RateLimited, RouteResult, Searcher, date_window, google_searcher, search_routes

log = logging.getLogger("cheapflights")


def mock_searcher(seed: int = 0) -> Searcher:
    """Precios inventados pero estables, para probar todo sin tocar Google."""

    def search(origin: str, destination: str, from_date: date, to_date: date) -> RouteResult:
        rnd = random.Random(f"{seed}:{origin}:{destination}")
        base = rnd.uniform(90_000, 400_000) if len({origin, destination} & {"BGA", "BOG", "MDE"}) == 2 else rnd.uniform(150_000, 2_500_000)
        cal = {}
        d = from_date
        while d <= to_date:
            cal[d.isoformat()] = round(base * rnd.uniform(0.7, 1.6), -3)
            d += timedelta(days=1)
        return RouteResult(origin=origin, destination=destination, calendar=cal, currency="COP")

    return search


def _select_groups(config: Config, kind: str | None, group: str | None) -> list[Group]:
    if group:
        return [config.group(group)]
    if kind and kind != "all":
        return config.groups_of_kind(kind)
    return list(config.groups)


def run_groups(
    config: Config,
    groups: list[Group],
    history: History,
    searcher: Searcher,
    notifier,
    delay: float | None = None,
) -> tuple[list[Alert], list[str]]:
    """Ejecuta la búsqueda de los grupos dados, guarda historial y envía alertas."""
    all_alerts: list[Alert] = []
    failures: list[str] = []
    delay = config.search.request_delay_seconds if delay is None else delay
    for group in groups:
        start, end = date_window(group.months_ahead, config.search.max_days_ahead)
        routes = group.routes()
        click.echo(f"▶ {group.name}: {len(routes)} rutas, {start} → {end}")
        try:
            results = search_routes(
                routes, searcher, start, end, delay_seconds=delay,
                on_error=lambda r, e: failures.append(f"{r}: {e}"),
            )
        except RateLimited as exc:
            failures.append(f"{group.name}: {exc}")
            click.secho(f"✖ {exc}. Se detiene la corrida para no empeorar el bloqueo.", fg="red")
            break
        for result in results:
            previous = history.record(result)
            cheapest = result.cheapest
            if cheapest:
                click.echo(f"   {result.route}: min {fmt_price(cheapest[1], result.currency)} el {fmt_date(cheapest[0])}")
            else:
                click.echo(f"   {result.route}: sin precios")
            all_alerts.extend(evaluate(result, previous, group, config.alerts, history))
    history.save()

    if all_alerts:
        for message in format_alerts_batch(all_alerts, config.language, config.country):
            notifier.send(message)
    return all_alerts, failures


@click.group()
@click.version_option(__version__)
@click.option("--config", "config_path", default="config.yaml", show_default=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--history", "history_path", default="data/history.json", show_default=True)
@click.option("-v", "--verbose", is_flag=True)
@click.pass_context
def cli(ctx: click.Context, config_path: str, history_path: str, verbose: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ctx.obj = {"config": load_config(config_path), "history": History.load(Path(history_path))}


@cli.command()
@click.option("--kind", type=click.Choice(["domestic", "international", "all"]), default="all", show_default=True)
@click.option("--group", default=None, help="Nombre exacto de un grupo de config.yaml")
@click.option("--dry-run", is_flag=True, help="No envía WhatsApp; imprime los mensajes")
@click.option("--mock", is_flag=True, help="No consulta Google; usa precios inventados")
@click.option("--delay", type=float, default=None, help="Segundos entre rutas (sobrescribe config)")
@click.pass_obj
def run(obj, kind: str, group: str | None, dry_run: bool, mock: bool, delay: float | None) -> None:
    """Busca precios, guarda historial y avisa si hay gangas."""
    config: Config = obj["config"]
    history: History = obj["history"]
    groups = _select_groups(config, kind, group)
    searcher = mock_searcher() if mock else google_searcher(config.currency, config.country, config.language)
    notifier = build_notifier(dry_run=dry_run)
    alerts, failures = run_groups(config, groups, history, searcher, notifier, delay=0 if mock else delay)
    click.echo(f"\n✔ {len(alerts)} alerta(s), {len(failures)} ruta(s) con error")
    for f in failures:
        click.secho(f"   ⚠ {f}", fg="yellow")
    if failures and not alerts and len(failures) >= max(1, sum(len(g.routes()) for g in groups) // 2):
        click.secho("La mayoría de rutas fallaron: revisa red o bloqueo de Google.", fg="red")
        sys.exit(2)


@cli.command()
@click.option("--kind", type=click.Choice(["domestic", "international", "all"]), default="all", show_default=True)
@click.option("--dry-run", is_flag=True, help="No envía WhatsApp; imprime los mensajes")
@click.pass_obj
def digest(obj, kind: str, dry_run: bool) -> None:
    """Envía el resumen de lo más barato por grupo/continente."""
    config: Config = obj["config"]
    history: History = obj["history"]
    kinds = ("domestic", "international") if kind == "all" else (kind,)
    notifier = build_notifier(dry_run=dry_run)
    for message in build_digest(config, history, kinds):
        notifier.send(message)


@cli.command()
@click.argument("route")
@click.option("--top", default=15, show_default=True)
@click.pass_obj
def show(obj, route: str, top: int) -> None:
    """Muestra las fechas más baratas guardadas de una ruta, ej. BGA-BOG."""
    history: History = obj["history"]
    route = route.upper()
    if not history.has_route(route):
        raise click.ClickException(f"No hay historial para {route}. Rutas: {', '.join(history.routes()) or 'ninguna'}")
    entry = history.route(route)
    cur = entry.get("currency", "COP")
    best, last = entry.get("best"), entry.get("last")
    if best:
        click.echo(f"Mínimo histórico: {fmt_price(best['price'], cur)} el {fmt_date(best['date'])} (visto {best['seen_at'][:10]})")
    if last:
        pct = history.price_percentile(route, last["price"])
        extra = f" · percentil {pct:.0f}" if pct is not None else ""
        click.echo(f"Última corrida:  {fmt_price(last['price'], cur)} el {fmt_date(last['date'])}{extra}")
    click.echo(f"Corridas guardadas: {len(entry['runs'])}\n")
    for day, price in sorted(entry["calendar"].items(), key=lambda kv: (kv[1], kv[0]))[:top]:
        click.echo(f"  {fmt_date(day):<18} {fmt_price(price, cur)}")


@cli.command()
@click.pass_obj
def routes(obj) -> None:
    """Lista los grupos y cuántas rutas buscará cada uno."""
    config: Config = obj["config"]
    total = 0
    for g in config.groups:
        n = len(g.routes())
        total += n
        click.echo(f"{g.name:<24} {g.kind:<13} {n:>3} rutas  {g.months_ahead} meses  objetivo {g.target_price}")
    click.echo(f"{'total':<24} {'':<13} {total:>3} rutas")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
