# ✈️ FLIGHTS — viajes baratos con avisos al celular

Rastreador personal de viajes baratos **de ida y vuelta** desde **Bucaramanga**. Busca precios en
Google Flights cada pocas horas, guarda el historial y te escribe por **Telegram** (o WhatsApp)
cuando hay algo barato. Corre gratis en GitHub Actions: no necesita servidor ni PC encendida.

## Qué te llega al celular

| Mensaje | Cuándo | Qué trae |
|---|---|---|
| 🔥 **Súper barato** | Apenas lo encuentra (cada ruta de Colombia se revisa cada 6 h; internacional cada 24 h) | Ruta, precio ida y vuelta, fechas de ida y regreso, precio con y sin maleta, si cae en puente, cuánto ahorras y enlace para ver el viaje |
| 🔥 **Súper barato · viaje armado** | Igual | Ida barata y regreso barato comprados por separado, aunque sean de aerolíneas distintas |
| 🔥 **Súper barato · solo ida** | Igual | Un tramo solo ida muy barato |
| ☀️ **Resumen del día** | 7:30 a. m. (llega entre 7:30 y 8:00) | Todo lo 🔥 súper barato y 👍 barato de hoy, nacional e internacional |
| 📅 **Plan de viajes** | Lunes, junto con el resumen | Lo más barato de cada zona y el mes en que en general es más barato viajar |
| ⚠️ **Algo falló** | Solo si una tarea falla | Qué falló y el enlace al registro. Se vuelve a intentar sola en su próximo horario |

Precios **ida y vuelta, 1 adulto, por persona**. Cada ruta se consulta **sin maleta** (tarifa
básica) y **con 1 maleta facturada**, y el aviso muestra los dos precios. De 10 p. m. a 6 a. m.
los avisos llegan sin sonido.

Ejemplo de aviso:

```
🔥 SÚPER BARATO
🏖️ Cartagena · $170.000 ida y vuelta
Normalmente $320.000 · ahorras 47 %

📅 sáb 31 oct → mar 3 nov · 3 noches
🎉 Puente: lun 2 nov, Todos los Santos
🎒 Sin maleta · con maleta: $290.000
👉 Ver vuelo
```

En los internacionales se agrega de dónde sale y el total sumando la conexión desde
Bucaramanga. Si hay 3 o más ofertas a la vez, llegan juntas en una lista corta, una línea por
vuelo: `🏖️ Cartagena $170.000 · 31 oct–3 nov 🎉 · −47 %`.

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
- **Viaje armado.** Además del ida y vuelta, se buscan tramos solo ida en los dos sentidos
  (ej. Bucaramanga → Cartagena y Cartagena → Bucaramanga, o Bogotá → Madrid y Madrid → Bogotá).
  Para cada destino se combina la ida más barata con el regreso más barato en cualquier fecha que
  cuadre con las noches, aunque sean de aerolíneas distintas, y se compara con el ida y vuelta
  normal. Te llega un solo aviso por destino, con lo más barato de los dos:

  ```
  🔥 SÚPER BARATO · VIAJE ARMADO
  🏖️ Cartagena · $118.000 ida y regreso
  Normalmente $320.000 · ahorras 63 %

  🛫 Ida: vie 30 oct · $52.000
  🛬 Regreso: lun 2 nov · $66.000 (3 noches)
  🎉 Puente: lun 2 nov, Todos los Santos
  🎒 Sin maleta
  ℹ️ Son dos tiquetes separados: pueden ser de aerolíneas distintas.
  👉 Ver ida · Ver regreso
  ```

  Si solo un tramo está súper barato, llega un aviso "🔥 solo ida". Se activa o desactiva con
  `one_way` en `config.yaml` (general o por zona).
- **Puentes.** Los festivos de Colombia se calculan solos (incluida la Ley Emiliani y la Semana
  Santa) y el aviso marca los viajes que caen en uno.

## Cómo decide qué es barato (modo muy estricto)

Para cada ruta se toma el viaje más barato que sale cada día. "Normalmente" es lo que suele
costar salir por esas fechas (la mediana de esos precios, a ±30 días de la oferta).

- 🔥 **Súper barato:** al menos **45 %** bajo lo normal **y** ese precio aparece en máximo el
  **3 %** de las fechas. Solo gangas de verdad: promos fuertes o errores de tarifa. Pueden pasar
  días sin ningún 🔥; es lo esperado.
- 👍 **Barato:** al menos 20 % bajo lo normal. Incluye la tarifa promo que se repite en muchas
  fechas. Solo sale en el resumen diario, no te despierta el celular.
- **Con el tiempo (automático):** cuando una ruta lleva 14 días y 20 búsquedas, además compara con
  lo que ha costado en esas semanas. 🔥 si está en el 10 % más barato de lo visto, al menos 20 %
  bajo lo que suele costar y el precio es raro.
- **Más o menos estricto:** en `config.yaml`, `super_below_normal` (45) y `super_max_share` (3).
  Para recibir más 🔥, prueba 35 y 5.
- **Tus precios (opcional):** por ciudad, a partir de qué precio quieres 🔥 o 👍 (ida y vuelta).
  Ej.: `CTG: {ciudad: Cartagena, super_barato: 180000, barato: 230000}`.
- **Sin repetir:** cada oferta se avisa una vez. Vuelve a avisar si baja otro 5 %, o si desaparece
  y después vuelve.

## Horarios (hora Colombia)

| Qué | Cuándo |
|---|---|
| Búsqueda (goteo) | Todo el día: una tanda cada ~media hora con las rutas que ya tocan, máximo 6 |
| Cada ruta de Colombia | Se vuelve a buscar cada 6 horas |
| Cada ruta internacional | Se vuelve a buscar cada 24 horas |
| Resumen del día | 7:30 a. m. (llega entre 7:30 y 8:00) |
| Plan de viajes | Lunes, junto con el resumen |

El goteo reparte las búsquedas en el día en vez de hacer pocas corridas grandes: así no hay
ráfagas, que es lo que hace que Google frene. Cada tarea de GitHub dura unas 3-4 horas y hace 7
tandas separadas por 25 minutos, porque el reloj de GitHub se atrasa hasta 3 horas; el horario
de cada hora solo deja lista la siguiente tarea para que arranque apenas termine la anterior. Por
lo mismo, el resumen y el plan no tienen horario propio en GitHub: los manda la primera tanda
después de las 7:30 a. m. Si Google bloquea, la siguiente tanda sigue con lo pendiente; solo te
llega un "⚠️" si pasan 12 horas sin conseguir ningún precio.

Las búsquedas completas (todas las rutas de una vez) se pueden lanzar a mano: **Actions** →
**Vuelos Colombia (completa, a mano)** o **Vuelos internacionales (completa, a mano)** →
**Run workflow**.

## Uso local (opcional)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python -m cheapflights zonas                           # qué se busca, con cuántas noches y qué maleta
python -m cheapflights buscar --tipo nacional --dry-run  # busca de verdad, no envía
python -m cheapflights buscar --zona "Costa Caribe"
python -m cheapflights buscar --goteo --dry-run        # solo las rutas que ya tocan
python -m cheapflights resumen --dry-run               # ☀️ resumen del día
python -m cheapflights plan --dry-run                  # 📅 plan de viajes
python -m cheapflights probar                          # ✅ mensaje de prueba al canal
python -m cheapflights ver BGA-CTG                     # viajes más baratos guardados (con y sin maleta)
python -m cheapflights buscar --mock --dry-run         # prueba sin tocar Google
pytest
```

El historial de precios vive en la rama `datos`. Para usarlo en tu máquina:

```bash
git fetch origin datos && git show FETCH_HEAD:history.json > data/history.json
```

Para enviar desde tu máquina, exporta las mismas variables que los secretos.

## Cómo funciona por dentro

```
config.yaml ─▶ buscar ─▶ search.py (Google Flights: precio de cada ida y vuelta, con/sin maleta)
                           │        conexión Bucaramanga ⇄ Bogotá/Medellín primero (internacional)
                           ▼
                   levels.classify ─▶ 🔥 / 👍 / nada   (+ otra maleta, + conexión, + festivos)
                           │
                   history.record ──▶ data/history.json ──▶ rama `datos` (se reescribe)
                           │
                   🔥 nuevos ───────▶ messages.py ─▶ notify.py (Telegram / WhatsApp / ntfy)
      resumen / plan ─▶ summary.py ─┘
```

Google entrega como máximo unas 200 combinaciones por petición, así que cada ruta se pide en
trozos (45 días de ida para 2-5 noches, 20 días para 6-14) con hasta `parallel_requests`
peticiones a la vez, un tope global de `requests_per_second` y una pausa de
`request_delay_seconds` entre rutas. Si Google responde HTTP 429, la corrida espera
`rate_limit_wait_seconds` y reintenta (hasta `rate_limit_max_waits` veces) antes de rendirse.
Por defecto va a una petición por segundo y sin ráfagas, porque Google frena las ráfagas en
silencio. La corrida internacional tarda unos 50 minutos y la nacional unos 10. Si Google corta
una corrida a mitad de camino, se guarda lo buscado y la siguiente empieza por lo que quedó
pendiente; solo cuenta como falla (y te avisa) si no se consiguió ningún precio.

## Problemas conocidos

- **Google puede bloquear** (HTTP 429/403). La búsqueda espera y reintenta; si el bloqueo sigue,
  se detiene sola y guarda lo alcanzado. Si pasa seguido, baja `requests_per_second` o
  `parallel_requests`, sube `request_delay_seconds`, acorta el rango de noches o quita destinos.
- **No todas las aerolíneas salen en Google Flights.** Avianca, LATAM, Wingo y JetSmart sí. Satena
  y Clic a veces no (por eso Apartadó u Olaya Herrera pueden salir sin precios).
- **Precio por persona, sin silla.** El precio "con maleta" es el que Google calcula sumando la
  tarifa de 1 maleta facturada; confirma en el enlace antes de comprar.
- **Tiquetes separados** en los viajes armados y en la conexión desde Bucaramanga: si un vuelo
  se retrasa y pierdes el otro, la otra aerolínea no responde. Deja margen entre vuelos.
- **El historial** se guarda en la rama `datos` como un solo commit que se reescribe en cada
  búsqueda, así el repositorio no crece con el tiempo.
- **Repo público y activo:** GitHub apaga las tareas programadas de un repo público si pasan
  60 días sin commits. El workflow *Mantener activo* revisa cada domingo y, si hace falta, hace un
  commit pequeño para que las búsquedas sigan solas.
- **Minutos de GitHub Actions:** con el repositorio público son ilimitados. Si es privado, el plan
  gratis trae unos 2.000 minutos al mes y este bot usa cerca de esa cifra; si se acaban, las
  búsquedas se detienen hasta el mes siguiente.
