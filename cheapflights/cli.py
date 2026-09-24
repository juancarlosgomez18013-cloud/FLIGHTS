"""Interfaz de línea de comandos.

  python -m cheapflights buscar --tipo nacional       # busca, guarda y avisa 🔥 al instante
  python -m cheapflights buscar --zona "Costa Caribe"
  python -m cheapflights resumen                      # ☀️ resumen diario (🔥 y 👍)
  python -m cheapflights plan                         # 📅 plan semanal por zona
  python -m cheapflights probar                       # ✅ mensaje de prueba al canal
  python -m cheapflights zonas                        # qué se busca y con qué precios
  python -m cheapflights ver BGA-BOG                  # fechas más baratas guardadas

  --dry-run: no envía, imprime.  --mock: no consulta Google (pruebas).
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import click

from . import __version__
from .config import KIND_LABEL, Config, Zone, load_config
from .history import History
from .levels import SUPER, Verdict, best_per_destination, classify, with_feeder
from .messages import fmt_date_short, fmt_price, format_alerts_packed, format_plan, format_summary, format_test
from .notify import Notifier, build_notifier, is_real
from .search import RateLimited, RouteResult, Searcher, date_window, google_searcher, search_routes
from .summary import plan_rows, sample_verdict, summary_data

log = logging.getLogger("cheapflights")

KIND_ALIASES = {
    "nacional": "domestic", "domestic": "domestic",
    "internacional": "international", "international": "international",
    "todo": "all", "all": "all",
}
LEVEL_ICON = {SUPER: "🔥", "barato": "👍", None: ""}


def mock_searcher(seed: int = 0) -> Searcher:
    """Precios inventados pero estables, para probar todo sin tocar Google."""

    def search(origin: str, destination: str, from_date: date, to_date: date) -> RouteResult:
        rnd = random.Random(f"{seed}:{origin}:{destination}")
        domestic = origin == "BGA"
        base = rnd.uniform(80_000, 400_000) if domestic else rnd.uniform(250_000, 2_500_000)
        cal = {}
        d = from_date
        while d <= to_date:
            cal[d.isoformat()] = round(base * rnd.uniform(0.6, 1.6), -3)
            d += timedelta(days=1)
        return RouteResult(origin=origin, destination=destination, calendar=cal, currency="COP")

    return search


def _select_zones(config: Config, kind: str, zone: str | None) -> list[Zone]:
    if zone:
        return [config.zone(zone)]
    kind = KIND_ALIASES[kind]
    if kind == "all":
        return list(config.zones)
    return config.zones_of_kind(kind)


@dataclass
class RunReport:
    failures: list[str] = field(default_factory=list)
    rate_limited: str | None = None
    alerted: list[Verdict] = field(default_factory=list)
    already_alerted: int = 0
    sent_ok: int = 0
    sent_total: int = 0

    @property
    def sent(self) -> tuple[int, int]:
        return self.sent_ok, self.sent_total


def send_all(notifier: Notifier, messages: list[str]) -> tuple[int, int]:
    ok = sum(1 for m in messages if notifier.send(m))
    return ok, len(messages)


def report_sending(notifier: Notifier, ok: int, total: int) -> None:
    if total == 0:
        return
    if not is_real(notifier):
        click.echo(f"📨 {total} mensaje(s) mostrados arriba (no hay canal configurado)")
        return
    if ok == total:
        click.secho(f"📨 {ok}/{total} mensaje(s) enviados por {notifier.name} ✓", fg="green")
    else:
        click.secho(
            f"📨 Solo {ok}/{total} mensaje(s) llegaron por {notifier.name}. Revisa los secretos del canal "
            "(por ejemplo TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID) y que le diste Iniciar al bot.",
            fg="red",
        )


def announce_channel(notifier: Notifier) -> None:
    click.echo(f"📨 Canal de avisos: {notifier.name}")


def run_zones(
    config: Config,
    zones: list[Zone],
    history: History,
    searcher: Searcher,
    notifier: Notifier,
    delay: float | None = None,
    now: datetime | None = None,
) -> RunReport:
    """Busca las zonas dadas, guarda historial y envía los 🔥 que toque avisar."""
    now = now or datetime.now(timezone.utc)
    today = config.local_today(now)
    delay = config.search.request_delay_seconds if delay is None else delay
    report = RunReport()
    candidates: list[Verdict] = []
    searched_destinations: set[str] = set()
    for zone in zones:
        start, end = date_window(zone.months_ahead, config.search.max_days_ahead, today)
        routes = zone.routes()
        click.echo(f"\n{zone.label} · {len(routes)} ruta(s) · {start} → {end}")
        try:
            results = search_routes(
                routes, searcher, start, end, delay_seconds=delay,
                on_error=lambda r, e: report.failures.append(f"{r}: {e}"),
            )
        except RateLimited as exc:
            results = list(getattr(exc, "partial", []) or [])
            report.rate_limited = str(exc)
            click.secho(f"✖ {exc}. Se detiene para no empeorar el bloqueo.", fg="red")
        for result in results:
            past = history.runs(result.route)
            verdict = classify(result.origin, result.destination, result.calendar, result.currency,
                               zone, config.levels, past, today)
            history.record(result, now)
            searched_destinations.add(result.destination)
            name = f"{config.city(result.origin)} → {config.city(result.destination)}"
            if verdict is None:
                click.echo(f"   {name}: sin precios")
                continue
            icon = LEVEL_ICON[verdict.level]
            click.echo(f"   {name}: {fmt_price(verdict.price, verdict.currency)} · {fmt_date_short(verdict.date, today)} {icon}".rstrip())
            if verdict.level == SUPER:
                candidates.append(verdict)
        history.save()  # por zona: un corte a mitad de camino no pierde lo ya buscado
        if report.rate_limited:
            break

    supers = best_per_destination([with_feeder(v, history, config.home, today) for v in candidates])
    super_dests = {v.destination for v in supers}
    for dest in searched_destinations - super_dests:
        history.clear_alert(dest)  # la oferta ya no está: si vuelve, se avisa otra vez
    to_send = [v for v in supers if history.should_alert(v.destination, v.price, config.alerts.repeat_if_drops_percent)]
    report.already_alerted = len(supers) - len(to_send)
    if to_send:
        for text, verdicts in format_alerts_packed(config, to_send, today):
            ok = notifier.send(text)
            report.sent_total += 1
            report.sent_ok += int(ok)
            if ok and is_real(notifier):  # sin canal real no se "gastan" los avisos
                for v in verdicts:
                    history.mark_alerted(v.destination, v.price, v.date, v.route, now)
                    report.alerted.append(v)
    history.save()
    if report.already_alerted:
        click.echo(f"🔕 {report.already_alerted} 🔥 ya avisado(s) y sin bajar más: no se repiten")
    return report


@click.group(help="Rastreador de vuelos baratos con avisos por Telegram o WhatsApp.")
@click.version_option(__version__)
@click.option("--config", "config_path", default="config.yaml", show_default=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--history", "history_path", default="data/history.json", show_default=True)
@click.option("-v", "--verbose", is_flag=True)
@click.pass_context
def cli(ctx: click.Context, config_path: str, history_path: str, verbose: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ctx.obj = {"config": load_config(config_path), "history": History.load(Path(history_path))}


def _notifier(config: Config, dry_run: bool) -> Notifier:
    notifier = build_notifier(dry_run=dry_run, quiet_hours=config.alerts.quiet_hours)
    announce_channel(notifier)
    return notifier


def _finish(notifier: Notifier, sent: tuple[int, int]) -> None:
    report_sending(notifier, *sent)
    if is_real(notifier) and sent[0] < sent[1]:
        sys.exit(3)


@cli.command("buscar")
@click.option("--tipo", "kind", type=click.Choice(sorted(KIND_ALIASES)), default="todo", show_default=True)
@click.option("--zona", "zone", default=None, help="Nombre de una zona de config.yaml")
@click.option("--dry-run", is_flag=True, help="No envía; imprime los mensajes")
@click.option("--mock", is_flag=True, help="No consulta Google; usa precios inventados")
@click.option("--delay", type=float, default=None, help="Segundos entre rutas")
@click.pass_obj
def buscar(obj, kind: str, zone: str | None, dry_run: bool, mock: bool, delay: float | None) -> None:
    """Busca precios, guarda el historial y avisa lo 🔥 súper barato."""
    config: Config = obj["config"]
    zones = _select_zones(config, kind, zone)
    searcher = mock_searcher() if mock else google_searcher(config.currency, config.country, config.language)
    notifier = _notifier(config, dry_run)
    report = run_zones(config, zones, obj["history"], searcher, notifier, delay=0 if mock else delay)
    click.echo(f"\n✔ {len(report.alerted)} aviso(s) 🔥 enviados · {len(report.failures)} ruta(s) con error")
    for f in report.failures:
        click.secho(f"   ⚠ {f}", fg="yellow")
    if not is_real(notifier) and report.sent_total and not dry_run:
        click.secho("⚠ Sin canal configurado: los 🔥 no se marcan como avisados y se enviarán cuando lo configures.", fg="yellow")
    _finish(notifier, report.sent)
    total_routes = sum(len(z.routes()) for z in zones)
    if report.rate_limited:
        click.secho("Google bloqueó la búsqueda: se guardó lo que alcanzó a buscar.", fg="red")
        sys.exit(2)
    if report.failures and len(report.failures) >= max(1, total_routes // 2):
        click.secho("La mayoría de rutas fallaron: revisa la red o un bloqueo de Google.", fg="red")
        sys.exit(2)


@cli.command("resumen")
@click.option("--dry-run", is_flag=True, help="No envía; imprime el mensaje")
@click.pass_obj
def resumen(obj, dry_run: bool) -> None:
    """☀️ Resumen diario: lo 🔥 súper barato y 👍 barato de hoy."""
    config: Config = obj["config"]
    now = datetime.now(timezone.utc)
    by_kind, stale = summary_data(config, obj["history"], now)
    messages = format_summary(config, by_kind, config.local_today(now), stale)
    notifier = _notifier(config, dry_run)
    _finish(notifier, send_all(notifier, messages))


@cli.command("plan")
@click.option("--dry-run", is_flag=True, help="No envía; imprime el mensaje")
@click.pass_obj
def plan(obj, dry_run: bool) -> None:
    """📅 Plan semanal: lo más barato por zona y el mes más barato para viajar."""
    config: Config = obj["config"]
    now = datetime.now(timezone.utc)
    messages = format_plan(config, plan_rows(config, obj["history"], now), config.local_today(now))
    notifier = _notifier(config, dry_run)
    _finish(notifier, send_all(notifier, messages))


@cli.command("probar")
@click.option("--dry-run", is_flag=True, help="No envía; imprime el mensaje")
@click.pass_obj
def probar(obj, dry_run: bool) -> None:
    """✅ Envía un mensaje de prueba para confirmar que el canal funciona."""
    config: Config = obj["config"]
    now = datetime.now(timezone.utc)
    notifier = _notifier(config, dry_run)
    if not is_real(notifier) and not dry_run:
        click.secho(
            "No hay canal configurado. Crea los secretos TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID "
            "(Settings → Secrets and variables → Actions).",
            fg="red",
        )
    messages = format_test(config, sample_verdict(config, obj["history"], now), config.local_today(now))
    sent = send_all(notifier, messages)
    report_sending(notifier, *sent)
    if not is_real(notifier) and not dry_run:
        sys.exit(4)
    if is_real(notifier) and sent[0] < sent[1]:
        sys.exit(3)


@cli.command("zonas")
@click.pass_obj
def zonas(obj) -> None:
    """Lista las zonas, sus destinos y los precios fijos que tengas (si hay)."""
    config: Config = obj["config"]
    total = 0
    for kind in ("domestic", "international"):
        zones = config.zones_of_kind(kind)
        if not zones:
            continue
        click.echo(f"\n{KIND_LABEL[kind].upper()}")
        for z in zones:
            n = len(z.routes())
            total += n
            desde = ", ".join(config.city(o) for o in z.origins)
            click.echo(f"  {z.label}  (desde {desde} · {z.months_ahead} meses · {n} rutas)")
            cities = []
            for d in z.destinations:
                sup, cheap = z.fixed_prices(d)
                fixed = []
                if sup is not None:
                    fixed.append(f"🔥 hasta {fmt_price(sup)}")
                if cheap is not None:
                    fixed.append(f"👍 hasta {fmt_price(cheap)}")
                cities.append(config.city(d) + (f" ({', '.join(fixed)})" if fixed else ""))
            click.echo("     " + ", ".join(cities))
    click.echo(f"\nTotal: {total} rutas")


@cli.command("ver")
@click.argument("route")
@click.option("--top", default=15, show_default=True)
@click.pass_obj
def ver(obj, route: str, top: int) -> None:
    """Muestra las fechas más baratas guardadas de una ruta, ej. BGA-BOG."""
    config: Config = obj["config"]
    history: History = obj["history"]
    route = route.upper()
    if not history.has_route(route):
        raise click.ClickException(f"No hay historial para {route}. Rutas: {', '.join(history.routes()) or 'ninguna'}")
    origin, destination = route.split("-")
    today = config.local_today()
    click.echo(f"{config.city(origin)} → {config.city(destination)}")
    best, last = history.best(route), history.last(route)
    cur = history.currency(route)
    if best:
        click.echo(f"Mínimo histórico: {fmt_price(best['price'], cur)} · {fmt_date_short(best['date'], today)} (visto {best['seen_at'][:10]})")
    if last:
        pct = history.price_percentile(route, last["price"])
        extra = f" · percentil {pct:.0f}" if pct is not None else ""
        click.echo(f"Última búsqueda: {fmt_price(last['price'], cur)} · {fmt_date_short(last['date'], today)}{extra}")
    click.echo(f"Búsquedas guardadas: {len(history.runs(route))}\n")
    upcoming = {d: p for d, p in history.calendar(route).items() if d >= today.isoformat()}
    for day, price in sorted(upcoming.items(), key=lambda kv: (kv[1], kv[0]))[:top]:
        click.echo(f"  {fmt_date_short(day, today):<16} {fmt_price(price, cur)}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
