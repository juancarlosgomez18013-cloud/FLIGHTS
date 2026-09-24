# ✈️ FLIGHTS — vuelos baratos con avisos al celular

Rastreador personal de vuelos baratos desde **Bucaramanga**. Busca precios en Google Flights
cada pocas horas, guarda el historial y te escribe por **Telegram** (o WhatsApp) cuando hay algo
barato. Corre gratis en GitHub Actions: no necesita servidor ni PC encendida.

## Qué te llega al celular

| Mensaje | Cuándo | Qué trae |
|---|---|---|
| 🔥 **Súper barato** | Apenas lo encuentra (Colombia cada 6 h, internacional cada mañana) | Ruta, precio, fecha, cuánto ahorras frente a otras fechas y enlace para ver el vuelo |
| ☀️ **Resumen del día** | 7:30 a. m. | Todo lo 🔥 súper barato y 👍 barato de hoy, nacional e internacional |
| 📅 **Plan de viajes** | Lunes 8:07 a. m. | Lo más barato de cada zona y el mes en que en general es más barato viajar |

Precios **solo ida, 1 adulto, sin maleta**. De 10 p. m. a 6 a. m. los avisos llegan sin sonido.

Ejemplo de aviso:

```
🔥 SÚPER BARATO · 🌴 Islas del Caribe
Bogotá → Aruba
💰 $416.067 · jueves 25 de febrero de 2027
➕ Bucaramanga → Bogotá: $124.000 (mié 24 feb 2027)
🧾 Total desde Bucaramanga: $540.067
📊 Cerca de esa fecha suele costar unos $1.153.000 (ahorras 64 %)
📅 Mismo precio en 22 fechas más: jue 4 mar 2027, jue 11 mar 2027…
👉 Ver en Google Flights
```

Si hay 3 o más ofertas a la vez, llegan juntas en una lista corta.

## Configurar Telegram (5 minutos)

**En el celular:**

1. Busca **@BotFather** en Telegram, ábrelo y toca *Iniciar*.
2. Escríbele `/newbot`. Ponle un nombre (ej. `Vuelos Baratos`) y un usuario que termine en `bot`
   (ej. `vuelos_juan_bot`).
3. Te responde con un **token** (algo como `8123456789:AAH…`). Cópialo. No lo compartas.
4. Toca el enlace `t.me/…` de ese mensaje y dale **Iniciar** a tu bot. Sin esto no puede escribirte.
5. Busca **@userinfobot**, dale *Iniciar* y copia tu **Id** (un número).

**En GitHub:**

6. Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:
   - `TELEGRAM_BOT_TOKEN` = el token del paso 3
   - `TELEGRAM_CHAT_ID` = tu Id del paso 5
7. **Actions** → **Probar avisos** → **Run workflow**. En un minuto te llega un mensaje de prueba.
   Si falla, el registro de esa corrida dice exactamente qué revisar.

Otros canales (opcionales, se pueden combinar): WhatsApp con [Whapi.Cloud](https://whapi.cloud)
(`WHAPI_TOKEN`, `WHAPI_PHONE`; API no oficial, sandbox gratis de 150 mensajes/día), CallMeBot
(`CALLMEBOT_PHONE`, `CALLMEBOT_APIKEY`; casi siempre lleno) y ntfy (`NTFY_TOPIC`).

## Qué se busca: zonas

**Colombia, desde Bucaramanga:**

| Zona | Destinos |
|---|---|
| 🏙️ Bogotá | Bogotá |
| 🌸 Medellín y Antioquia | Medellín, Olaya Herrera, Apartadó |
| 🏖️ Costa Caribe | Cartagena, Barranquilla, Santa Marta, Riohacha, Valledupar, Montería |
| 🐠 San Andrés | San Andrés |
| ☕ Eje Cafetero | Pereira, Armenia, Manizales |
| 💃 Cali y el suroccidente | Cali, Quibdó, Popayán, Pasto |
| 🌄 Cúcuta y los Llanos | Cúcuta, Arauca, Yopal, Villavicencio |
| ⛰️ Tolima, Huila y Caquetá | Ibagué, Neiva, Florencia |
| 🌳 Amazonas | Leticia |

**Internacional, desde Bogotá o Medellín** (el aviso suma el vuelo desde Bucaramanga):

| Zona | Destinos |
|---|---|
| 🌎 Panamá y Centroamérica | Panamá, San José, Guatemala, San Salvador |
| 🌴 Islas del Caribe | Aruba, Curazao, Punta Cana, Santo Domingo, San Juan, La Habana |
| 🇲🇽 México | Ciudad de México, Cancún |
| 🗽 Estados Unidos y Canadá | Miami, Fort Lauderdale, Orlando, Nueva York, Los Ángeles, Toronto |
| 🏔️ Perú, Ecuador, Bolivia y Venezuela | Lima, Quito, Guayaquil, La Paz, Caracas |
| 🇧🇷 Brasil | São Paulo, Río de Janeiro |
| 🧉 Chile, Argentina, Uruguay y Paraguay | Santiago, Buenos Aires, Montevideo, Asunción |
| 🏰 Europa | Madrid, Barcelona, Lisboa, París, Ámsterdam, Londres, Roma, Fráncfort, Estambul |

Todo esto se cambia en [`config.yaml`](config.yaml): agregar o quitar destinos, fijar tus propios
precios por ciudad o cambiar las horas de silencio. Está comentado en español.

## Cómo decide qué es barato

Cada ruta se compara con **sus propias fechas**, así sirve igual para Bogotá ($60.000) que para
Europa ($2.000.000). "Precio normal" = lo que cuesta la mayoría de sus fechas.

- 👍 **Barato:** 20 % o más bajo el precio normal. Ej.: Medellín a $85.868 cuando lo normal es
  unos $223.000.
- 🔥 **Súper barato:** 25 % bajo lo normal **y** 15 % bajo las fechas más baratas de siempre. Así la
  tarifa promo que aparece en muchas fechas cuenta como 👍 y no llena el celular de 🔥.
- **Con el tiempo (automático):** cuando una ruta lleva 14 días y 20 búsquedas, también compara con
  lo que ha costado en esas semanas. 🔥 si está en el 10 % más barato de lo visto.
- **Tus precios (opcional):** en `config.yaml` puedes poner, por ciudad, a partir de qué precio
  quieres 🔥 o 👍. Ej.: `CTG: {ciudad: Cartagena, super_barato: 80000, barato: 100000}`.
- **Sin repetir:** cada oferta se avisa una vez. Vuelve a avisar si baja otro 5 %, o si desaparece
  y después vuelve.

## Horarios (hora Colombia)

| Qué | Cuándo |
|---|---|
| Búsqueda nacional | 6:17 a. m., 12:17 p. m., 6:17 p. m., 12:17 a. m. |
| Búsqueda internacional | 6:08 a. m. |
| Resumen del día | 7:30 a. m. |
| Plan de viajes | Lunes 8:07 a. m. |

Cualquiera se puede lanzar a mano: **Actions** → elegir el workflow → **Run workflow**.

## Uso local (opcional)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python -m cheapflights zonas                           # qué se busca y con qué precios
python -m cheapflights buscar --tipo nacional --dry-run  # busca de verdad, no envía
python -m cheapflights buscar --zona "Costa Caribe"
python -m cheapflights resumen --dry-run               # ☀️ resumen del día
python -m cheapflights plan --dry-run                  # 📅 plan de viajes
python -m cheapflights probar                          # ✅ mensaje de prueba al canal
python -m cheapflights ver BGA-CTG                     # fechas más baratas guardadas
python -m cheapflights buscar --mock --dry-run         # prueba sin tocar Google
pytest
```

Para enviar desde tu máquina, exporta las mismas variables que los secretos.

## Cómo funciona por dentro

```
config.yaml ─▶ buscar ─▶ search.py (Google Flights: calendario de precios por fecha)
                           │
                           ▼
                   levels.classify ─▶ 🔥 / 👍 / nada
                           │
                   history.record ──▶ data/history.json (commit automático)
                           │
                   🔥 nuevos ───────▶ messages.py ─▶ notify.py (Telegram / WhatsApp / ntfy)
      resumen / plan ─▶ summary.py ─┘
```

## Problemas conocidos

- **Google puede bloquear** (HTTP 429/403). La búsqueda se detiene sola. Si pasa seguido, sube
  `request_delay_seconds` o quita destinos.
- **No todas las aerolíneas salen en Google Flights.** Avianca, LATAM, Wingo y JetSmart sí. Satena
  y Clic a veces no (por eso Apartadó u Olaya Herrera pueden salir sin precios).
- **Precio base.** Sin maleta ni silla. Confirma en el enlace antes de comprar.
- **Tiquetes separados** en los combos internacionales: si pierdes el vuelo desde Bucaramanga, la
  aerolínea internacional no responde. El sistema prefiere el tramo del día anterior.
- **El repo crece** con cada búsqueda (commit de `data/history.json`). Es normal.
