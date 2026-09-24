# ✈️ FLIGHTS — viajes baratos con avisos al celular

Rastreador personal de viajes baratos **de ida y vuelta** desde **Bucaramanga**. Busca precios en
Google Flights cada pocas horas, guarda el historial y te escribe por **Telegram** (o WhatsApp)
cuando hay algo barato. Corre gratis en GitHub Actions: no necesita servidor ni PC encendida.

## Qué te llega al celular

| Mensaje | Cuándo | Qué trae |
|---|---|---|
| 🔥 **Súper barato** | Apenas lo encuentra (Colombia cada 6 h, internacional cada mañana) | Ruta, precio ida y vuelta, fechas de ida y regreso, precio con y sin maleta, si cae en puente, cuánto ahorras y enlace para ver el viaje |
| ☀️ **Resumen del día** | 7:30 a. m. | Todo lo 🔥 súper barato y 👍 barato de hoy, nacional e internacional |
| 📅 **Plan de viajes** | Lunes 8:07 a. m. | Lo más barato de cada zona y el mes en que en general es más barato viajar |

Precios **ida y vuelta, 1 adulto, por persona**. Cada ruta se consulta **sin maleta** (tarifa
básica) y **con 1 maleta facturada**, y el aviso muestra los dos precios. De 10 p. m. a 6 a. m.
los avisos llegan sin sonido.

Ejemplo de aviso:

```
🔥 SÚPER BARATO · 🌴 Islas del Caribe
Bogotá ⇄ Aruba
💰 $750.000 ida y vuelta · con maleta facturada
🎒 Sin maleta: $500.000
🗓️ jueves 25 de febrero → miércoles 3 de marzo de 2027 · 6 noches
➕ Bucaramanga ⇄ Bogotá: $150.000 (mié 24 feb → jue 4 mar 2027)
🧾 Total desde Bucaramanga: $900.000
📊 Cerca de esa fecha suele costar unos $1.350.000 (ahorras 44 %)
📅 Mismo precio saliendo en 3 fechas más: jue 4 mar 2027, jue 11 mar 2027, jue 18 mar 2027
👉 Ver en Google Flights
```

Si hay 3 o más ofertas a la vez, llegan juntas en una lista corta. Si el viaje incluye un festivo
de Colombia, el aviso lo dice: `🎉 Puente festivo: lun 2 nov (Todos los Santos)`.

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
| 🐠 San Andrés | San Andrés (3 a 7 noches) |
| ☕ Eje Cafetero | Pereira, Armenia, Manizales |
| 💃 Cali y el suroccidente | Cali, Quibdó, Popayán, Pasto |
| 🌄 Cúcuta y los Llanos | Cúcuta, Arauca, Yopal, Villavicencio |
| ⛰️ Tolima, Huila y Caquetá | Ibagué, Neiva, Florencia |
| 🌳 Amazonas | Leticia |

**Internacional, desde Bogotá o Medellín** (el aviso suma la conexión Bucaramanga ⇄ Bogotá o
Medellín, ida y vuelta, en las fechas del viaje):

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
precios por ciudad, cambiar noches o maleta por zona, o cambiar las horas de silencio. Está
comentado en español.

## Noches y maleta

- **Noches.** Cada zona tiene un rango de noches: Colombia **2 a 5** (fines de semana y puentes),
  internacional **6 a 14** (una o dos semanas). Google devuelve en una sola consulta todas las
  combinaciones de fecha de ida y de regreso dentro del rango, así que el aviso siempre trae el
  viaje completo más barato y un rango amplio no cuesta más búsquedas. Se cambia con `nights`
  (general o por zona).
- **Maleta.** Cada ruta se consulta sin maleta y con 1 maleta facturada. Cuál de los dos precios
  decide si algo es 🔥 o 👍 se elige con `bags`: en Colombia decide el precio **sin maleta**
  (escapada corta) y en internacional el precio **con maleta**. El otro precio se consulta solo
  alrededor de la oferta encontrada y se muestra como referencia.
- **Conexión desde Bucaramanga.** Para los internacionales se busca Bucaramanga ⇄ Bogotá y
  Bucaramanga ⇄ Medellín, ida y vuelta, y se suma el tramo que encaja con las fechas: sale el mismo
  día o el anterior y vuelve el mismo día o el siguiente.
- **Puentes.** Los festivos de Colombia se calculan solos (incluida la Ley Emiliani y la Semana
  Santa) y el aviso marca los viajes que caen en uno.

## Cómo decide qué es barato

Cada ruta se compara con **sus propios viajes** (todas las combinaciones de ida y vuelta), así
sirve igual para Bogotá ($150.000) que para Europa ($4.000.000). "Precio normal" = lo que cuesta
la mayoría de sus viajes.

- 👍 **Barato:** 20 % o más bajo el precio normal.
- 🔥 **Súper barato:** 25 % bajo lo normal **y** 15 % bajo los viajes más baratos de siempre. Así la
  tarifa promo que aparece en muchas fechas cuenta como 👍 y no llena el celular de 🔥.
- **Con el tiempo (automático):** cuando una ruta lleva 14 días y 20 búsquedas, también compara con
  lo que ha costado en esas semanas. 🔥 si está en el 10 % más barato de lo visto.
- **Tus precios (opcional):** en `config.yaml` puedes poner, por ciudad, a partir de qué precio
  quieres 🔥 o 👍. Ej.: `CTG: {ciudad: Cartagena, super_barato: 250000, barato: 320000}`.
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

python -m cheapflights zonas                           # qué se busca, con cuántas noches y qué maleta
python -m cheapflights buscar --tipo nacional --dry-run  # busca de verdad, no envía
python -m cheapflights buscar --zona "Costa Caribe"
python -m cheapflights resumen --dry-run               # ☀️ resumen del día
python -m cheapflights plan --dry-run                  # 📅 plan de viajes
python -m cheapflights probar                          # ✅ mensaje de prueba al canal
python -m cheapflights ver BGA-CTG                     # viajes más baratos guardados (con y sin maleta)
python -m cheapflights buscar --mock --dry-run         # prueba sin tocar Google
pytest
```

Para enviar desde tu máquina, exporta las mismas variables que los secretos.

## Cómo funciona por dentro

```
config.yaml ─▶ buscar ─▶ search.py (Google Flights: precio de cada ida y vuelta, con/sin maleta)
                           │        conexión Bucaramanga ⇄ Bogotá/Medellín primero (internacional)
                           ▼
                   levels.classify ─▶ 🔥 / 👍 / nada   (+ otra maleta, + conexión, + festivos)
                           │
                   history.record ──▶ data/history.json (commit automático)
                           │
                   🔥 nuevos ───────▶ messages.py ─▶ notify.py (Telegram / WhatsApp / ntfy)
      resumen / plan ─▶ summary.py ─┘
```

Google entrega como máximo unas 200 combinaciones por petición, así que cada ruta se pide en
trozos (45 días de ida para 2-5 noches, 20 días para 6-14) con hasta `parallel_requests`
peticiones a la vez, un tope global de `requests_per_second` y una pausa de
`request_delay_seconds` entre rutas. Si Google responde HTTP 429, la corrida espera
`rate_limit_wait_seconds` y reintenta (hasta `rate_limit_max_waits` veces) antes de rendirse.
La corrida internacional completa tarda unos 15 a 20 minutos; la nacional, unos 5.

## Problemas conocidos

- **Google puede bloquear** (HTTP 429/403). La búsqueda espera y reintenta; si el bloqueo sigue,
  se detiene sola y guarda lo alcanzado. Si pasa seguido, baja `requests_per_second` o
  `parallel_requests`, sube `request_delay_seconds`, acorta el rango de noches o quita destinos.
- **No todas las aerolíneas salen en Google Flights.** Avianca, LATAM, Wingo y JetSmart sí. Satena
  y Clic a veces no (por eso Apartadó u Olaya Herrera pueden salir sin precios).
- **Precio por persona, sin silla.** El precio "con maleta" es el que Google calcula sumando la
  tarifa de 1 maleta facturada; confirma en el enlace antes de comprar.
- **Tiquetes separados** en los combos internacionales: si pierdes la conexión desde Bucaramanga,
  la aerolínea internacional no responde. El sistema prefiere salir el día anterior cuando es más
  barato o igual.
- **El repo crece** con cada búsqueda (commit de `data/history.json`). Es normal. El historial de
  la versión anterior (solo ida) no es comparable y se descartó al pasar a ida y vuelta.
