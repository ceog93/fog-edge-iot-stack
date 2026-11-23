# Simulador ESP32 virtual — Fases 1 y 2

Simulador independiente de nodos ESP32/MQ-2 con backend Python 3.12+, FastAPI,
Paho MQTT 2.1 y panel HTML/CSS/JavaScript con Chart.js 4.6.1 servido localmente.
No necesita la infraestructura principal.

Al iniciar la API se crean 10 nodos con ubicación e identificador propios, pero
la simulación queda **detenida** hasta llamar a `POST /simulation/start`.
Cada nodo tiene un cliente MQTT y un hilo de red independientes. Publica una
lectura cada 2 segundos mientras está conectado. La primera ronda es inmediata;
si todavía no hay conexión, esa lectura se descarta y se prueba en la próxima ronda.

## Ejecutar todo con Docker

Desde `simulator/esp32-virtual/`, con Docker Engine/Desktop y Compose disponibles:

```powershell
docker compose up -d --build
docker compose logs -f frontend backend mqtt-test
```

Abre el **panel en http://localhost:8085**. Esto conserva el nombre de proyecto
Compose `esp32-virtual-phase1` para mantener la continuidad con la Fase 1.
El backend está en `http://127.0.0.1:8000` y el broker en `127.0.0.1:1884`.
El panel consulta `/api/status` cada segundo, configura e inicia con
`/api/simulation/start` y detiene con `/api/simulation/stop`. Nginx elimina
`/api/` y envía la solicitud a `backend:8000` en la red Docker. El navegador
solo usa rutas del mismo origen: no necesita resolver `backend` ni configurar CORS.
El backend usa `mqtt-test:1883`. No se usan redes, volúmenes,
servicios ni configuraciones del stack principal.

El panel muestra estado de ejecución, conexiones MQTT, mensajes enviados, errores
y las últimas lecturas por nodo. Sus campos se bloquean mientras la simulación
está iniciando, ejecutándose o deteniéndose. La probabilidad se introduce como
porcentaje (10 % equivale a `0.1` en la API). Ante fallos de API conserva los
últimos datos, los marca como desactualizados, deshabilita controles y reintenta.
Los cambios escritos en un formulario detenido se conservan entre consultas;
no se aplican hasta pulsar **Iniciar simulación**.

Abrir o recargar la página solo hace consultas GET. No reinicia ni detiene el
backend y no borra sus datos. Para reconstruir únicamente la interfaz:

```powershell
docker compose up -d --build --no-deps frontend
```

Los datos viven en memoria del backend. **Recrear o reiniciar su contenedor sí
los pierde**, incluido al instalar por primera vez el código nuevo de la Fase 2.
Actualizar solo el frontend conserva el proceso del backend.

## Monitoreo e identidad visual

El encabezado usa un símbolo de terminal `>_`, fondo `#0F172A` y el nombre
**ESP32 Virtual**. Azul `#2563EB` identifica controles y conexiones activas;
verde identifica lecturas normales, rojo alarmas y gris nodos desconectados o
sin lectura. Configuración, controles, tabla y proxy Nginx–FastAPI se conservan.
Esta actualización no necesita cambios en el backend ni en MQTT.

Entre los indicadores y la tabla se incluyen tres gráficas Chart.js:

- **Lecturas ADC:** selector de dispositivo y hasta 60 lecturas distintas
  observadas por nodo, con hora UTC del mensaje, puntos verdes/rojos según su
  estado publicado y línea roja discontinua del umbral **actual**. El eje muestra
  las horas en la zona local del navegador. No se recalifica el estado histórico
  al cambiar el umbral. MQTT conectado/desconectado se indica por separado.
- **Tráfico MQTT:** `(contador actual − contador anterior) / segundos reales
  transcurridos`, usando `performance.now()` entre consultas GET correctas.
  La primera consulta solo establece la referencia; no inventa una tasa inicial.
  Se conservan hasta 60 puntos, incluidas separaciones por datos ausentes.
- **Estados de dispositivos:** dona con nodos normales, en alarma y sin lectura,
  basada en el último `estado` ADC recibido. Un nodo desconectado puede seguir
  figurando como normal o en alarma. La leyenda también presenta las cantidades
  como texto para no depender del color ni del canvas.

El polling continúa cada segundo y nunca genera lecturas ficticias. Se ignoran
timestamps repetidos o atrasados; dos timestamps distintos en el mismo
milisegundo se conservan. Los datos se guardan solo en memoria de esta pestaña:
recargar la página borra el historial del navegador, sin alterar el backend;
la primera consulta recupera la última lectura que el backend conserve.
Retirar un dispositivo de la configuración elimina su curva local para limitar
la memoria; la configuración del backend sigue conservando sus propios datos.

Al detener se mantienen ADC, estados y curvas; la curva de tráfico deja de
desplazarse tras la muestra final y el indicador de tasa puede mostrar cero
cuando dos consultas confirman que el contador no cambió. Ante una caída de API
se mantienen las gráficas atenuadas, se invalida la referencia de tráfico y se
esperan dos consultas correctas para calcular otra tasa. Un contador que
disminuye (por ejemplo, tras reiniciar el backend) establece otra referencia,
sin tasas negativas; la curva muestra un corte, no datos interpolados del hueco.

El endpoint ofrece solo la última lectura de cada nodo. Si publica más rápido
que el polling de un segundo, la curva **no puede recuperar cada publicación**;
muestra las lecturas observadas, hasta 60 por nodo. La tasa corresponde al
contador local de envíos QoS 0, no a confirmaciones de recepción del broker.

Las instancias Chart.js se reutilizan, se actualizan sin animación y las curvas
ADC/dona solo se redibujan si cambian los datos correspondientes. La librería,
su licencia MIT y la procedencia/integridad se incluyen en `frontend/vendor/`;
no hay llamadas a CDN ni instalación npm para servir el panel. Si Chart.js no
carga, se muestra un aviso y los controles y la tabla siguen disponibles.
Se emplean los mecanismos oficiales de [actualización](https://www.chartjs.org/docs/latest/developers/updates.html)
y [contenedores responsivos](https://www.chartjs.org/docs/latest/configuration/responsive.html).

Pruebas del monitoreo, desde `simulator/esp32-virtual/frontend/`, con Node.js
disponible (solo para pruebas; no requerido en la imagen Nginx):

```powershell
node --test tests/monitoring.test.cjs tests/charts.test.cjs
```

Cubren deduplicación, memoria limitada, selección de dispositivo, tasa con
intervalos reales, reinicios de contador, huecos de API, conservación al detener,
estados ADC independientes de MQTT, estados vacíos, umbral vigente y reutilización
de gráficas. No sustituyen una revisión visual en navegador.

Verificación de esta actualización: **21 pruebas de frontend y 79 de backend
aprobadas**; construcción/actualización exclusiva del frontend con Docker;
recursos de monitoreo y `/api/status` disponibles en 8085; backend y su estado
conservados. La revisión visual de escritorio/móvil queda pendiente porque
el acceso de navegador de la herramienta no estuvo disponible.

El broker local permite clientes anónimos y MQTT TCP sin TLS, tiene persistencia
desactivada y una ACL que solo permite leer/escribir en `simulacion/#`.
Sus puertos publicados están limitados a loopback. Esta configuración es para
pruebas locales; no está preparada para exposición pública.

## Ejecutar Python localmente

También se puede levantar solo el broker:

```powershell
# Desde simulator/esp32-virtual/
docker compose up -d mqtt-test
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
```

En Linux/macOS usa `.venv/bin/python` en lugar de `.\.venv\Scripts\python.exe`.
No levantes a la vez el backend Docker y el local en el mismo puerto.
Sin Docker se puede usar cualquier broker MQTT TCP de pruebas configurando
`MQTT_HOST` y `MQTT_PORT`; la API puede arrancar incluso si el broker no responde.

## API REST

| Método | Ruta | Comportamiento |
| --- | --- | --- |
| GET | `/status` | Estado, configuración no secreta, nodos conectados, contadores y última lectura por nodo. |
| POST | `/simulation/start` | Configura e inicia de forma atómica; cuerpo JSON opcional. |
| POST | `/simulation/stop` | Detiene publicaciones y cierra clientes; idempotente. |
| GET | `/docs` | Swagger UI interactiva. |
| GET | `/openapi.json` | Especificación de la API. |

```powershell
curl.exe http://127.0.0.1:8000/status
curl.exe -X POST http://127.0.0.1:8000/simulation/start
curl.exe http://127.0.0.1:8000/status
curl.exe -X POST http://127.0.0.1:8000/simulation/stop
```

En Linux/macOS usa `curl`. `running: true` significa que el generador está activo,
no que MQTT ya esté conectado: comprueba `connected_nodes` y `nodes[].last_error`.
Errores locales de inicio devuelven HTTP 503 y limpian los clientes ya iniciados.
La API no tiene autenticación y debe mantenerse en un entorno local de pruebas.

Ejemplo de configuración al iniciar desde PowerShell:

```powershell
$simParams = '{"node_count":10,"interval_seconds":2,"alarm_threshold":1500,"alarm_probability":0.1}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/simulation/start -ContentType 'application/json' -Body $simParams
```

Los campos omitidos conservan sus valores actuales. Sin cuerpo (o con `{}`)
se inicia con la configuración vigente. Valores fuera de rango, tipos incorrectos
y campos desconocidos devuelven **422** sin modificar el estado. Cambiar parámetros
durante una ejecución, o iniciar durante una transición, devuelve **409**.
Repetir un inicio con la misma configuración activa es idempotente.
El umbral debe ser entero de 0 a 4094 para dejar al menos un valor posible de
alarma. Esta fase admite de 1 a 100 nodos y un intervalo mayor que cero y hasta
3600 segundos; no está orientada a pruebas masivas.

## Variables de entorno

| Variable | Python local | Compose | Significado |
| --- | --- | --- | --- |
| `MQTT_HOST` | `127.0.0.1` | `mqtt-test` | Host del broker. |
| `MQTT_PORT` | `1884` | `1883` | Puerto TCP del broker visto desde el backend. |
| `MQTT_USERNAME` | vacío | vacío | Usuario opcional. |
| `MQTT_PASSWORD` | vacío | vacío | Contraseña opcional; requiere usuario. |
| `SIM_NODE_COUNT` | `10` | `10` | Cantidad de nodos, entero de 1 a 100. |
| `SIM_INTERVAL_SECONDS` | `2` | `2` | Intervalo finito mayor que cero y hasta 3600 s. |
| `SIM_ALARM_PROBABILITY` | `0.1` | `0.1` | Probabilidad de alarma por lectura, entre 0 y 1. |
| `SIM_ALARM_THRESHOLD` | `1500` | `1500` | Umbral ADC entero de 0 a 4094; alarma estrictamente por encima. |
| `SIM_DEVICE_PREFIX` | `esp32-virtual` | `esp32-virtual` | Prefijo de IDs; letras ASCII, números, `_` y `-`, hasta 64 caracteres. |
| `SIM_LOCATION_PREFIX` | `laboratorio` | `laboratorio` | Prefijo de las ubicaciones. |

Se generan IDs `esp32-virtual-001` … `esp32-virtual-010` y ubicaciones
`laboratorio-001` … `laboratorio-010`. Los `client_id` MQTT usan UUID independientes.
Usa distintos `SIM_DEVICE_PREFIX` para ejecutar varias instancias sin mezclar sus
dispositivos. Ejecuta **un solo worker** de Uvicorn; cada proceso crea su simulación.

Las variables establecen la configuración inicial al arrancar la API. Los cuatro
parámetros del panel pueden cambiarse para la siguiente ejecución sin reiniciar
el proceso; host, credenciales y prefijos siguen siendo configuración de arranque.
Python local lee variables del proceso, no carga `.env`.
Compose sí admite su interpolación habitual desde `.env`, que no debe versionarse.
Ejemplo PowerShell para generar únicamente alarmas, con 3 nodos:

```powershell
$env:SIM_NODE_COUNT = "3"
$env:SIM_ALARM_PROBABILITY = "1"
docker compose up -d --build backend
# O define estas variables antes de ejecutar Uvicorn localmente.
```

`SIM_ALARM_PROBABILITY=0` produce solo lecturas normales; `1` solo alarmas;
un valor intermedio mezcla ambos casos. Son elecciones aleatorias independientes
por nodo y lectura, no episodios de alarma con duración fija.
El broker incluido no configura usuarios: las credenciales opcionales del backend
sirven para un broker de pruebas que sí requiera autenticación.

## Contrato MQTT y verificación

Tópico de telemetría publicado por cada nodo: `simulacion/{device_id}/telemetria`.
MQTT 3.1.1, QoS 0 y `retain=false`. El simulador no se suscribe a comandos ni
publica hacia actuadores. No hay puentes al broker principal.

Cada nodo también publica disponibilidad retenida en `simulacion/{device_id}/estado`,
QoS 1: `conectado` al establecer la sesión MQTT y `desconectado` al detenerse.
No usa LWT: el estado se controla únicamente por el inicio y la parada explícita
de la simulación.

Ejemplo ilustrativo de mensaje:

```json
{
  "device_id": "esp32-virtual-001",
  "ubicacion": "laboratorio-001",
  "adc": 1742,
  "estado": "alarma",
  "timestamp": "2026-11-16T15:30:00.123456Z",
  "simulado": true
}
```

ADC es un entero entre 0 y 4095. `adc <= umbral` implica `estado="normal"`;
`adc > umbral` implica `estado="alarma"` (umbral inicial: 1500). Se usa distribución
uniforme dentro del rango elegido: 0–umbral para normal y umbral+1–4095 para alarma.
El campo `estado` de una última lectura conservada corresponde al umbral con el
que se generó esa lectura. ADC no representa ppm
ni una calibración física del MQ-2. `timestamp` es la hora UTC de generación.

En otra terminal, desde `simulator/esp32-virtual/`, suscríbete antes de iniciar
la simulación para observar los mensajes no retenidos:

```powershell
docker compose exec mqtt-test mosquitto_sub -h 127.0.0.1 -p 1883 -t "simulacion/+/telemetria" -v
```

Con clientes Mosquitto instalados en el equipo anfitrión:

```powershell
mosquitto_sub -h 127.0.0.1 -p 1884 -t "simulacion/+/telemetria" -v
```

Paho reintenta la conexión inicial y las reconexiones con espera creciente de
1 a 30 segundos. Mientras no hay conexión se siguen generando lecturas, se
incrementa `skipped_disconnected` y no se acumula una cola para reproducirlas.
Los errores y conexiones se registran; los logs incluyen el JSON aceptado por
Paho y la confirmación de envío local. `messages_accepted` cuenta aceptaciones
del cliente y `messages_sent` callbacks de envío. **Con QoS 0 estos contadores
no confirman recepción por el broker ni por suscriptores.**

Para comprobar manualmente la recuperación, inicia la simulación, detén el broker
y observa `/status`; luego vuelve a levantarlo:

```powershell
docker compose stop mqtt-test
docker compose start mqtt-test
```

La API sigue disponible durante conexión, publicación y cierre. Al detener la
simulación se espera a la ronda en curso y se cierran los hilos de Paho fuera
del bucle de la API. Los contadores se conservan entre stop/start y se pierden
al reiniciar el proceso. Reducir el número de nodos los retira de la ejecución;
al ampliarlo reaparecen sus identidades, lecturas y contadores. Los indicadores
globales incluyen también el historial de los nodos retirados. No hay
almacenamiento histórico persistente ni garantía de entrega.

## Pruebas automatizadas sin broker

Desde `simulator/esp32-virtual/backend/`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Las pruebas usan clientes MQTT en memoria. Cubren límites ADC, umbral estricto,
mezcla configurable, contrato JSON/UTC, validación de entorno, nodos independientes,
API, inicio/detención/reinicio, desconexión/recuperación, errores de publicación,
limpieza de inicio parcial, cierre sin bloquear `/status` y credenciales ocultas.
Las pruebas de Fase 2 añaden configuración parcial, umbrales personalizados,
validación HTTP 422, conflictos HTTP 409 durante ejecución/transiciones,
conservación del estado al consultar y conservación de nodos al reducir/ampliar.
También se construyen clientes Paho reales y se comprueba el cierre/reinicio de
sus hilos con creación de sockets simulada. No prueban transporte
MQTT real, ACL, autenticación del broker ni temporización bajo carga; usa la
suscripción anterior para la comprobación de integración.

Comprobación manual del panel: edita un parámetro con la simulación detenida y
espera varias actualizaciones (no debe sobrescribirse); inicia y verifica que
los campos se bloquean; recarga y comprueba que continúa ejecutándose; detén y
comprueba que las últimas lecturas permanecen. Prueba también el panel en móvil.
Para comprobar la recuperación de la API en un entorno desechable, detén solo
`backend`: el panel debe mostrar datos desactualizados y deshabilitar controles.
Al volver a arrancarlo debe recuperar las consultas; como es un reinicio del
proceso, en ese caso sus contadores comenzarán de nuevo.

Para finalizar el entorno Docker:

```powershell
docker compose down
```

## Verificación de Fase 2

Se ejecutaron 79 pruebas automatizadas sin broker externo. También se construyó
y levantó el conjunto Docker en un proyecto temporal con puertos distintos,
verificando recursos HTTP, proxy, respuestas 409/422, mensajes MQTT reales,
caída/recuperación HTTP del backend y actualización exclusiva del frontend sin
perder el estado de una simulación activa. El entorno temporal se retiró y el
backend que ya estaba en ejecución se conservó intacto.
La revisión visual en navegador de escritorio y móvil queda pendiente porque
la herramienta de navegador no estuvo disponible y no se autorizó acceso a Chrome.

Quedan fuera de esta fase las pruebas masivas, integración con
Node-RED/Home Assistant/Proxmox y la reproducción exacta del firmware físico.
