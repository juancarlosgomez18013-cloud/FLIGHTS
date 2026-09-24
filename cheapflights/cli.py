"""Interfaz de línea de comandos.

  python -m cheapflights buscar --tipo nacional       # busca, guarda y avisa 🔥 al instante
  python -m cheapflights buscar --zona "Costa Caribe"
  python -m cheapflights resumen                      # ☀️ resumen diario (🔥 y 👍)
  python -m cheapflights plan                         # 📅 plan semanal por zona
  python -m cheapflights probar                       # ✅ mensaje de prueba al canal
  python -m cheapflights zonas                        # qué se busca y con qué precios
  python -m cheapflights ver BGA-CTG                  # viajes más baratos guardados

  --dry-run: no envía, imprime.  --mock: no consulta Google (pruebas).
"""

from __future__ import annotations

import logging
import random
import sys
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import click

from . import __version__
from .config import KIND_LABEL, Config, Zone, load_config
from .history import History
from .levels import SUPER, Verdict, best_per_destination, classify, classify_trip, enrich, trip_fares
from .messages import (
    BAGS_TEXT,
    fmt_nights,
    fmt_price,
    fmt_trip_short,
    format_alerts_packed,
    format_plan,
    format_summary,
    format_test,
)
from .notify import Notifier, build_notifier, is_real
from .search import (
    Backoff,
    RateLimited,
    Route,
    RouteResult,
    Searcher,
    SearchJob,
    date_window,
    google_searcher,
    nights_between,
    search_routes,
    window_around,
)
from .summary import plan_rows, sample_verdict, summary_data

log = logging.getLogger("cheapflights")

KIND_ALIASES = {
    "nacional": "domestic", "domestic": "domestic",
    "internacional": "international", "international": "international",
    "todo": "all", "all": "all",
}
LEVEL_ICON = {SUPER: "🔥", "barato": "👍", None: ""}
FEEDER_LABEL = "🔗 Conexión desde casa"


def mock_searcher(seed: int = 0) -> Searcher:
    """Precios inventados pero estables, para probar todo sin tocar Google."""

    def search(route: Route, from_date: date, to_date: date) -> RouteResult:
        rnd = random.Random(f"{seed}:{route.pair}:{route.one_way}")
        domestic = "BGA" in (route.origin, route.destination)
        base = rnd.uniform(150_000, 700_000) if domestic else rnd.uniform(500_000, 4_500_000)
        if route.bags:
            base *= 1.35  # la maleta encarece
        if route.one_way:
            base *= 0.5  # un tramo cuesta más o menos la mitad del viaje
        fares = {}
        d = from_date
        while d <= to_date:
            for n in range(route.nights[0], route.nights[1] + 1):
                fares[(d.isoformat(), (d + timedelta(days=n)).isoformat())] = round(base * rnd.uniform(0.6, 1.6), -3)
            d += timedelta(days=1)
        return RouteResult(route=route, fares=fares, currency="COP")

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
    requests: int = 0  # búsquedas hechas (cada una son varias peticiones a Google)

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


def _bags_note(v: Verdict) -> str:
    if v.other_bag_price is None:
        return ""
    return f" · {BAGS_TEXT[1 - v.bags]} {fmt_price(v.other_bag_price, v.currency)}"


class _Runner:
    """Ejecuta las búsquedas de una corrida y va guardando el historial."""

    def __init__(self, config: Config, history: History, searcher: Searcher, delay: float, now: datetime, report: RunReport):
        self.config, self.history, self.searcher, self.delay, self.now, self.report = config, history, searcher, delay, now, report
        self.today = config.local_today(now)

    def search(self, jobs: list[SearchJob], partial: bool = False) -> list[RouteResult]:
        """Busca y guarda. Con `RateLimited`, guarda lo alcanzado y deja constancia en el reporte."""
        if not jobs or self.report.rate_limited:
            return []
        try:
            results = search_routes(jobs, self.searcher, delay_seconds=self.delay,
                                    on_error=lambda r, e: self.report.failures.append(f"{r}: {e}"))
        except RateLimited as exc:
            results = list(getattr(exc, "partial", []) or [])
            self.report.rate_limited = str(exc)
            click.secho(f"✖ {exc}. Se detiene para no empeorar el bloqueo.", fg="red")
        for r in results:
            self.history.record(r, self.now, partial=partial)
        self.report.requests += len(results)
        return results

    def feeders(self) -> None:
        """Conexiones casa ⇄ hub (ida y vuelta), para poder sumar el total de los internacionales."""
        routes = self.config.feeder_searches()
        if not routes:
            return
        start, end = date_window(self.config.feeder_months, self.config.search.max_days_ahead, self.today)
        click.echo(f"\n{FEEDER_LABEL} · {len(routes)} búsqueda(s) · {start} → {end}")
        for r in self.search([(r, start, end) for r in routes]):
            name = f"{self.config.city(r.route.origin)} ⇄ {self.config.city(r.route.destination)} ({BAGS_TEXT[r.route.bags]})"
            best = r.cheapest
            click.echo(f"   {name}: " + (f"desde {fmt_price(best[2], r.currency)} · {fmt_trip_short(best[0], best[1], self.today)}" if best else "sin precios"))

    def zone(self, zone: Zone) -> list[Verdict]:
        """Busca una zona: ida y vuelta, tramos solo ida (si aplica) y la otra maleta alrededor de cada oferta."""
        start, end = date_window(zone.months_ahead, self.config.search.max_days_ahead, self.today)
        routes = zone.routes()
        lo, hi = zone.nights
        extra = " · + solo ida" if zone.one_way else ""
        click.echo(f"\n{zone.label} · {len(routes)} ruta(s) · {lo}-{hi} noches · {BAGS_TEXT[zone.bags]}{extra} · {start} → {end}")
        results = self.search([(r, start, end) for r in routes])
        one_way_results = self.search([(r, start, end) for r in zone.one_way_routes()])
        verdicts: list[Verdict] = []
        # El viaje a cada destino: el ida y vuelta normal o, si sale más barato, armado con dos tramos solo ida.
        for r in routes:
            if zone.one_way:
                combo = replace(r, combo=True)
                v = classify_trip(zone, r, self.history, self.config.levels, self.history.runs(combo.key), self.today)
                if v:
                    fares, _ = trip_fares(self.history, r)
                    self.history.record(RouteResult(combo, fares, v.currency), self.now, store_fares=False)
            else:
                result = next((x for x in results if x.route == r), None)
                v = None
                if result:
                    past = self.history.runs_before_current_fares(r.key)
                    v = classify(r, result.fares, result.currency, zone, self.config.levels, past, self.today)
            if v:
                verdicts.append(v)
        # La otra opción de maleta solo se consulta en una ventana alrededor de cada oferta normal:
        # así el aviso trae los dos precios sin duplicar todas las peticiones a Google.
        if self.config.search.both_bag_prices:
            jobs = [(v.route.base.other_bags, *window_around(v.out, zone.nights, start, end)) for v in verdicts if not v.armado]
            self.search(jobs, partial=True)
        for result in one_way_results:
            if result.route.origin not in zone.origins:
                continue  # un regreso suelto (ej. San Andrés → Bucaramanga) solo sirve dentro de un viaje armado
            past = self.history.runs_before_current_fares(result.route.key)
            v = classify(result.route, result.fares, result.currency, zone, self.config.levels, past, self.today)
            if v:
                verdicts.append(v)
        enriched = [enrich(v, self.history, self.config, self.today) for v in verdicts]
        for v in enriched:
            arrow = "→" if v.one_way else "⇄"
            name = f"{self.config.city(v.origin)} {arrow} {self.config.city(v.destination)}" + (" (solo ida)" if v.one_way else "")
            when = fmt_trip_short(v.out, v.back, self.today) + ("" if v.one_way else f" ({fmt_nights(v.nights)})")
            how = f" · armado: ida {fmt_price(v.legs[0], v.currency)} + regreso {fmt_price(v.legs[1], v.currency)}" if v.armado else ""
            click.echo(f"   {name}: {fmt_price(v.price, v.currency)} · {when}{_bags_note(v)}{how} {LEVEL_ICON[v.level]}".rstrip())
        found = {(v.origin, v.destination, v.one_way) for v in enriched}
        for r in routes + zone.outbound_one_way_routes():
            if (r.origin, r.destination, r.one_way) not in found:
                arrow = "→" if r.one_way else "⇄"
                click.echo(f"   {self.config.city(r.origin)} {arrow} {self.config.city(r.destination)}{' (solo ida)' if r.one_way else ''}: sin precios")
        self.history.save()  # por zona: un corte a mitad de camino no pierde lo ya buscado
        return enriched


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
    runner = _Runner(config, history, searcher, delay, now, report)
    candidates: list[Verdict] = []
    searched_keys: set[str] = set()

    if any(z.kind == "international" for z in zones):
        runner.feeders()
        history.save()
    for zone in zones:
        if report.rate_limited:
            break
        for v in runner.zone(zone):
            searched_keys.add(v.alert_key)
            if v.level == SUPER:
                candidates.append(v)

    supers = best_per_destination(candidates)
    # Un tramo solo ida que ya va dentro de un viaje armado 🔥 no se avisa dos veces.
    in_trips = {(v.route.base.outbound.pair, v.out) for v in supers if v.armado}
    in_trips |= {(v.route.base.inbound.pair, v.back) for v in supers if v.armado}
    supers = [v for v in supers if not (v.one_way and (v.pair, v.out) in in_trips)]
    super_keys = {v.alert_key for v in supers}
    # Avisos viejos de regresos sueltos (antes se avisaban): se olvidan.
    hubs = {o for z in config.zones for o in z.origins}
    for key in [k for k in history.data["alerts"] if k.startswith("solo-ida:") and k.split(":", 1)[1].split("-")[0] not in hubs]:
        history.clear_alert(key)
    for key in searched_keys - super_keys:
        history.clear_alert(key)  # la oferta ya no está: si vuelve, se avisa otra vez
    to_send = [v for v in supers if history.should_alert(v.alert_key, v.price, config.alerts.repeat_if_drops_percent)]
    report.already_alerted = len(supers) - len(to_send)
    if to_send:
        for text, verdicts in format_alerts_packed(config, to_send, today):
            ok = notifier.send(text)
            report.sent_total += 1
            report.sent_ok += int(ok)
            if ok and is_real(notifier):  # sin canal real no se "gastan" los avisos
                for v in verdicts:
                    history.mark_alerted(v.alert_key, v.price, v.out, v.back, v.key, now)
                    report.alerted.append(v)
    history.save()
    if report.already_alerted:
        click.echo(f"🔕 {report.already_alerted} 🔥 ya avisado(s) y sin bajar más: no se repiten")
    return report


@click.group(help="Rastreador de viajes baratos (ida y vuelta) con avisos por Telegram o WhatsApp.")
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
@click.option("--delay", type=float, default=None, help="Segundos entre búsquedas")
@click.pass_obj
def buscar(obj, kind: str, zone: str | None, dry_run: bool, mock: bool, delay: float | None) -> None:
    """Busca precios de ida y vuelta, guarda el historial y avisa lo 🔥 súper barato."""
    config: Config = obj["config"]
    zones = _select_zones(config, kind, zone)
    searcher = mock_searcher() if mock else google_searcher(
        config.currency, config.country, config.language,
        parallel_requests=config.search.parallel_requests,
        requests_per_second=config.search.requests_per_second,
        backoff=Backoff(config.search.rate_limit_wait_seconds, config.search.rate_limit_max_waits),
    )
    notifier = _notifier(config, dry_run)
    report = run_zones(config, zones, obj["history"], searcher, notifier, delay=0 if mock else delay)
    click.echo(f"\n✔ {len(report.alerted)} aviso(s) 🔥 enviados · {report.requests} búsqueda(s) · {len(report.failures)} con error")
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
    """Lista las zonas, sus destinos, noches, maleta y los precios fijos que tengas (si hay)."""
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
            lo, hi = z.nights
            extra = " · + solo ida en los dos sentidos" if z.one_way else ""
            click.echo(f"  {z.label}  (desde {desde} · {z.months_ahead} meses · {lo}-{hi} noches · 🔥 {BAGS_TEXT[z.bags]}{extra} · {n} rutas)")
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
    feeders = config.feeder_searches()
    if feeders:
        lo, hi = config.feeder_nights
        click.echo(f"\n{FEEDER_LABEL}: " + ", ".join(sorted({f"{config.city(f.origin)} ⇄ {config.city(f.destination)}" for f in feeders}))
                   + f" ({lo}-{hi} noches, para sumar el total de los internacionales)")
    click.echo(f"\nTotal: {total} rutas")


@cli.command("ver")
@click.argument("route")
@click.option("--top", default=15, show_default=True)
@click.pass_obj
def ver(obj, route: str, top: int) -> None:
    """Muestra los viajes más baratos guardados de una ruta, ej. BGA-CTG."""
    config: Config = obj["config"]
    history: History = obj["history"]
    pair = route.upper()
    keys = history.keys_for_pair(pair) or ([pair] if history.has_route(pair) else [])
    if keys and "-" in pair:  # también el tramo solo ida de regreso
        keys += [k for k in history.keys_for_pair("-".join(reversed(pair.split("-")))) if "/ida/" in k]
    if not keys:
        pairs = sorted({k.split("/")[0] for k in history.routes()})
        raise click.ClickException(f"No hay historial para {pair}. Rutas: {', '.join(pairs) or 'ninguna'}")
    origin, destination = pair.split("-")
    today = config.local_today()
    click.echo(f"{config.city(origin)} ⇄ {config.city(destination)}")
    for key in keys:
        r = history.route_of(key)
        if r is None:
            continue
        if r.one_way:
            click.echo(f"\n{config.city(r.origin)} → {config.city(r.destination)}", nl=False)
        lo, hi = r.nights
        title = f"\n{'solo ida' if r.one_way else f'{lo}-{hi} noches'} · {BAGS_TEXT[r.bags]}"
        if r.combo:
            title += " · mejor viaje (normal o armado con dos tramos)"
        if history.is_partial(key):
            title += " (solo alrededor de la última oferta)"
        click.echo(title)
        best, last = history.best(key), history.last(key)
        cur = history.currency(key)
        if best:
            click.echo(f"  Mínimo histórico: {fmt_price(best['price'], cur)} · {fmt_trip_short(best['out'], best['back'], today)} (visto {best['seen_at'][:10]})")
        if last:
            pct = history.price_percentile(key, last["price"])
            extra = f" · percentil {pct:.0f}" if pct is not None else ""
            click.echo(f"  Última búsqueda: {fmt_price(last['price'], cur)} · {fmt_trip_short(last['out'], last['back'], today)}{extra}")
        if history.runs(key):
            click.echo(f"  Búsquedas guardadas: {len(history.runs(key))}")
        upcoming = {k: p for k, p in history.fares(key).items() if k[0] > today.isoformat()}
        for (out, back), price in sorted(upcoming.items(), key=lambda kv: (kv[1], kv[0]))[:top]:
            trip = fmt_trip_short(out, back, today) + ("" if out == back else f" ({fmt_nights(nights_between(out, back))})")
            click.echo(f"    {trip:<42} {fmt_price(price, cur)}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
