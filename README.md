# ✈️ FLIGHTS — vuelos baratos con alertas al celular

Rastreador personal de vuelos baratos desde Bucaramanga (y desde Bogotá/Medellín para lo
internacional). Corre gratis en GitHub Actions, busca precios en Google Flights, guarda el
historial y te escribe por Telegram o WhatsApp cuando hay una ganga.

No usa APIs de pago. No necesita servidor ni PC encendida.

## Qué hace

- **Doméstico en toda Colombia**: BGA a 26 ciudades, cada 6 horas, 6 meses adelante.
- **Internacional por continente**: Sudamérica, Norteamérica y Caribe, Europa. Desde BOG y MDE,
  una vez al día, 9 meses adelante.
- **Combos**: si lo internacional sale de Bogotá, te suma el BGA→BOG del día anterior o del mismo
  día y te muestra el total real desde Bucaramanga.
- **Alertas al celular** (Telegram, WhatsApp o ntfy) cuando una ruta:
  - 🎯 baja de tu precio objetivo (`target_price` por grupo),
  - 📉 toca su mínimo histórico,
  - 🔻 cae más de un 15 % frente a la corrida anterior.
- **Resumen semanal** (lunes 7 a. m.) con lo más barato por grupo, fecha exacta y mes más barato.
- **Historial** en `data/history.json`: mínimo por fecha de vuelo, mínimo histórico y una
  estadística simple ("solo el 10 % de las veces ha estado más barato") que mejora con el tiempo.

## Puesta en marcha (10 minutos)

### 1. Elige por dónde recibir los avisos

Se pueden activar varios canales a la vez; cada uno son dos secretos en GitHub
(*Settings → Secrets and variables → Actions → New repository secret*).

**Telegram (recomendado: gratis, ilimitado, 2 minutos)**

1. Escribe a [@BotFather](https://t.me/BotFather) en Telegram: `/newbot`, ponle nombre, copia el token.
2. Escribe a [@userinfobot](https://t.me/userinfobot): te responde tu `Id`.
3. Abre el chat con tu bot nuevo y dale *Start* (si no, el bot no puede escribirte).
4. Secretos: `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.

**WhatsApp con Whapi.Cloud (sandbox gratis permanente, 150 mensajes/día)**

1. Crea cuenta en <https://whapi.cloud>, crea un canal y escanea el QR desde WhatsApp
   (*Dispositivos vinculados*). Puedes usar tu mismo número: te escribirás a ti mismo.
2. Copia el token del canal.
3. Secretos: `WHAPI_TOKEN` y `WHAPI_PHONE` (tu número con indicativo, sin `+`, ej. `573001234567`).

Es una API no oficial de WhatsApp. Para mensajes a ti mismo el riesgo es bajo, pero existe.

**WhatsApp con CallMeBot** (gratis, pero casi siempre "lleno"): si logras registrarte,
secretos `CALLMEBOT_PHONE` y `CALLMEBOT_APIKEY`.

**ntfy (push sin registro)**: instala la app ntfy, suscríbete a un tema con nombre difícil de
adivinar y guarda el secreto `NTFY_TOPIC`.

Sin ningún canal configurado el sistema igual corre, pero imprime los avisos en el log.

### 2. Permisos de Actions

*Settings → Actions → General → Workflow permissions*: marca **Read and write permissions**. Hace
falta para que el bot guarde `data/history.json` en el repo después de cada corrida.

### 3. Primera corrida

*Actions → Vuelos Colombia → Run workflow*. Revisa el log: debe listar cada ruta con su precio
mínimo. Si ves `HTTP 429` o `403`, Google está bloqueando las IPs de GitHub; mira "Problemas" abajo.

La primera corrida solo puede avisar por precio objetivo (aún no hay historial para "mínimo
histórico" ni "bajó fuerte").

## Uso local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python -m cheapflights routes                       # qué se va a buscar
python -m cheapflights run --kind domestic --dry-run  # busca de verdad, no envía WhatsApp
python -m cheapflights run --group "Sudamérica"     # un grupo concreto
python -m cheapflights digest --dry-run             # resumen por continente
python -m cheapflights show BGA-CTG                 # fechas más baratas guardadas
python -m cheapflights run --mock --dry-run         # prueba sin tocar Google
pytest
```

Para enviar de verdad desde tu máquina, exporta las mismas variables que los secretos (por ejemplo `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`).

## Ajustar a tu gusto: `config.yaml`

| Clave | Qué controla |
|---|---|
| `groups[].destinations` | Aeropuertos IATA a vigilar. Agrega o quita libremente |
| `groups[].origins` | Desde dónde buscar ese grupo (`BGA` doméstico, `BOG`/`MDE` internacional) |
| `groups[].target_price` | Precio (COP, solo ida, 1 adulto) por debajo del cual avisa siempre |
| `groups[].months_ahead` | Cuántos meses adelante buscar (máx. ~10, límite de Google) |
| `alerts.drop_percent` | Porcentaje de caída para avisar |
| `alerts.cooldown_hours` | Horas sin repetir el mismo aviso (salvo que baje otro 5 %) |
| `feeders` | Rutas BGA→hub que se suman a los internacionales para el total |
| `search.request_delay_seconds` | Pausa entre rutas. Súbela si Google empieza a bloquear |

Los horarios están en `.github/workflows/*.yml` (cron en UTC; Colombia es UTC−5).

## Cómo funciona por dentro

```
config.yaml ─▶ cli.run ─▶ search (fli → Google Flights, calendario de precios por fecha)
                              │
                              ▼
                         history.record()  ──▶ data/history.json (commit automático)
                              │
                              ▼
                         alerts.evaluate() ──▶ notify (Telegram / WhatsApp / ntfy)
                                   digest ──▶ resumen semanal por grupo
```

- `cheapflights/search.py` es el único módulo que habla con Google. Usa la librería
  [`fli`](https://github.com/punitarani/fli), que consulta el endpoint interno del calendario de
  Google Flights (bloques de 61 días, máximo ~305 días adelante) en COP y mercado Colombia.
- Cada ruta consume unas 3 a 5 peticiones. Doméstico: ~26 rutas por corrida. Internacional: ~76
  rutas al día. Hay una pausa de 2 s entre rutas.

## Problemas conocidos

- **Google bloquea (HTTP 429/403).** La corrida se detiene sola para no empeorarlo. Opciones:
  subir `request_delay_seconds`, reducir destinos, espaciar los cron, o mover la ejecución a la
  capa gratuita de Oracle Cloud con un cron normal (el código es el mismo).
- **Aerolíneas que no salen en Google Flights.** Avianca, LATAM, Wingo y JetSmart sí aparecen.
  Satena, Clic y EasyFly a veces no. Las promos relámpago de las low-cost pueden salir solo en su
  web: revisa Wingo y JetSmart directamente cuando planees.
- **Precio mostrado vs precio final.** Es la tarifa base, solo ida, sin equipaje. Verifica en el
  enlace del aviso antes de comprar.
- **Combos con tiquetes separados.** Si pierdes el BGA→BOG, la aerolínea internacional no
  responde. Deja margen (el sistema prefiere el vuelo del día anterior).
- **El repo crece.** Cada corrida hace un commit con `data/history.json` (~0,5 MB compactos). Es
  normal. Si algún día molesta, se puede borrar el historial y empezar de cero.

## Hoja de ruta

1. ✅ Doméstico + internacional, alertas por WhatsApp, resumen semanal, combos.
2. Segunda fuente de precios (Data API de Aviasales, gratis) para cruzar y cubrir bloqueos.
3. Extraer el indicador de Google de "precio bajo / típico / alto" de la misma respuesta.
4. Página con mapas de calor por ruta para planear mirando.
5. Fuentes de tarifas error (Secret Flying, Fly4Free) integradas al resumen.
