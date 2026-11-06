# ADR 003: Cómo se entera Don Chuy de los pedidos nuevos

- **Estado:** Aceptado
- **Fecha:** 5 de noviembre de 2026
- **Autor:** Alejandro Padilla

## 1. Contexto

Hoy el agente toma el pedido, lo guarda en DynamoDB y le confirma al cliente con su folio (por ejemplo, `DC-0004`). Pero **Don Chuy no se entera**: para saber que hay un pedido tendría que entrar a la consola de AWS. Un pedido que nadie surte es peor que no tener agente.

Además, Don Chuy necesita poder preguntar **qué pedidos tiene pendientes** y **cuánto vendió** en la semana o en el mes, sin abrir AWS.

Reglas de Telegram que afectan la decisión:
- **Un bot no puede escribirle primero a nadie** (como un firewall stateful: solo responde a conversaciones que la otra persona inició).
- **Paso de instalación (una sola vez):** Don Chuy le escribe al bot para que Telegram permita que el bot le avise después. Con eso obtenemos su `chat_id` (su "número de cliente" dentro de Telegram). La tienda funciona aunque no lo haga; lo único que no funciona es el aviso.
- **Los clientes no hacen nada especial:** al abrir el bot por primera vez, el botón "Iniciar" manda el `/start` por ellos.
- Don Chuy ya usa Telegram todos los días; es el lugar natural para el aviso.

## 2. Requisitos

| # | Requisito | Peso |
|---|---|---|
| R1 | **Aviso en segundos** cuando se confirma un pedido, con folio, productos, total, dirección y forma de pago. | Muy alto |
| R2 | **Si el aviso falla, el pedido no se pierde ni se duplica** y el cliente no se entera del problema. | Muy alto |
| R3 | **Sin avisos dobles** del mismo pedido. | Medio |
| R4 | **Consultas del dueño:** pedidos pendientes, ventas de la semana y del mes, y marcar un pedido como entregado. | Alto |
| R5 | **Números exactos** en las consultas (nada inventado). | Muy alto |
| R6 | **Costo:** centavos; sin costo fijo. | Alto |
| R7 | **Fácil de crecer:** mañana el aviso podría ir también por correo o WhatsApp. | Bajo |

## 3. Opciones para el aviso

### A. Directo: el agente le escribe a Don Chuy justo después de confirmar
"El mismo empleado que toma el pedido le grita al dueño".
- **A favor:** la más sencilla; unas líneas de código.
- **En contra:** mezcla dos trabajos en la Lambda del agente. Si el aviso falla, o se ignora el error (y Don Chuy no se entera) o la Lambda falla y la fila reintenta **toda la plática del cliente**. No cumple bien R2.

### B. Avisar con EventBridge
"El agente publica en un tablero de anuncios: 'pedido confirmado'; quien esté suscrito actúa".
- **A favor:** separa el aviso del agente y es muy fácil de crecer (correo, WhatsApp, reportes).
- **En contra:** el agente tiene que hacer **dos escrituras**: guardar el pedido y publicar el anuncio. Si la primera sale bien y la segunda falla, el pedido existe pero nadie avisa. Es una pieza más para un solo suscriptor.

### C. DynamoDB Streams + una Lambda "avisadora"
"Un **puerto espejo (SPAN)** en la tabla": cada cambio que se guarda en la tabla se copia a una salida aparte, y una Lambda escucha ahí **sin tocar el tráfico principal**.
- **A favor:** el aviso nace **del pedido ya guardado**, no de una segunda escritura: si el pedido existe, el aviso sale. El agente no cambia nada. Si el aviso falla, se reintenta solo, sin repetir la plática del cliente. Con un **filtro**, la avisadora solo despierta cuando se **crea** un pedido (no con cada mensaje de la plática).
- **En contra:** una Lambda más; el "espejo" entrega **al menos una vez**, así que hay que evitar avisos dobles (R3).

### D. SNS con correo o SMS
- **En contra:** Don Chuy no vive en el correo; los SMS en México cuestan y requieren registro. Telegram ya lo tiene en la mano.

## 4. Decisión del aviso

**Opción C: DynamoDB Streams + Lambda avisadora, con filtro "solo pedidos nuevos".**

Si mañana se necesitan más destinos (correo, WhatsApp), la salida del espejo se conecta a EventBridge con **EventBridge Pipes**, sin tocar al agente (R7).

## 5. Decisión de las consultas del dueño

**Comandos fijos, sin IA**, atendidos por la misma Lambda del agente cuando el mensaje viene del `chat_id` de Don Chuy **y empieza con `/`**:

| Comando | Qué contesta | De dónde sale |
|---|---|---|
| `/pendientes` | Lista de pedidos nuevos, del más viejo al más nuevo | Índice GSI1 (`ESTADO#nuevo`), ya diseñado en el ADR 001 |
| `/ventas` | Total y número de pedidos de esta semana y este mes, y lo más vendido | Libretas `VENTAS` de la semana y del mes |
| `/entregado DC-0004` | Marca el pedido como entregado y lo saca de pendientes | Cambia `GSI1PK` de `ESTADO#nuevo` a `ESTADO#entregado` |

**Por qué sin IA:** son números de dinero; un comando fijo los lee tal cual de la tabla (R5), contesta en milisegundos y no gasta en Bedrock. La IA se queda donde aporta: platicar con el cliente.

**Por qué solo los mensajes con `/`:** así el mismo `chat_id` de Don Chuy puede seguir probando el bot como cliente normal.

## 6. Cómo funciona

```
Cliente confirma → Lambda del agente → DynamoDB (pedido guardado)
                                          ↓ Stream (espejo), filtro: pedido nuevo
                                     Lambda avisadora → Telegram de Don Chuy
                                          ↓ (si falla 3 veces)
                                     Fila de avisos fallidos (SQS)

Don Chuy escribe /pendientes → (misma entrada de siempre) → Lambda del agente
                                → detecta dueño + comando → lee DynamoDB → le contesta
```

**Lambda avisadora:**
1. Recibe el pedido nuevo tal como quedó guardado.
2. **Marca el pedido como avisado** con una escritura condicional ("solo si todavía no está avisado"). Si ya lo estaba, termina sin mandar nada (R3).
3. Le manda a Don Chuy: folio, cliente, productos, total, dirección y forma de pago.
4. Si Telegram falla, quita la marca y la Lambda falla para que se reintente.

**Dónde se guarda el `chat_id` de Don Chuy:** en Parameter Store, como parámetro normal (no es secreto, pero tampoco va en GitHub). Se pega a mano en la consola, igual que el token.

**Red de seguridad:** aunque un aviso se perdiera, el pedido aparece en `/pendientes`. "El aviso es la campanita; la lista de pendientes es la libreta."

## 7. Ajustes

| Ajuste | Valor | Por qué |
|---|---|---|
| Qué copia el espejo | Solo la versión nueva del registro (`NEW_IMAGE`) | Es todo lo que necesita el aviso |
| Filtro | Evento `INSERT` y `SK` que empieza con `PEDIDO#` | No despierta con pláticas, contadores ni libretas |
| Registros por vuelta | 1 | Más simple; un fallo no afecta a otro pedido |
| Reintentos | 3, luego a una fila de avisos fallidos (14 días) | Fallas pasajeras de Telegram |
| Tiempo máximo de la avisadora | 10 segundos | Solo manda un mensaje |
| Permisos de la avisadora | Leer el token y el `chat_id`, actualizar la marca del pedido y mandar a su fila de fallidos | Permisos mínimos |

## 8. Consecuencias

- **Gano:** Don Chuy se entera en segundos; el agente no cambia; un aviso fallido no afecta al cliente; consultas exactas sin abrir AWS.
- **Costo:** leer el espejo desde Lambda **no cuesta**; los registros filtrados no despiertan la Lambda. Por pedido: una invocación de Lambda de milisegundos. Prácticamente cero.
- **Más piezas:** una Lambda, su rol, su fila de fallidos y el espejo encendido en la tabla. Las crea Terraform.
- **Un solo dueño por bot:** suficiente para Don Chuy. Para varios empleados, el parámetro pasaría a ser una lista.
- **Patrón reutilizable:** "reaccionar a lo que se guarda" sirve en el agente 4 (por ejemplo, avisar a un contador cuando llega un documento).

## 9. Seguimiento

- Terraform: encender el espejo (Stream), Lambda avisadora con filtro, fila de fallidos y parámetro del `chat_id`.
- Código: la avisadora y los comandos del dueño en la Lambda del agente.
- Probar: un pedido nuevo (llega un aviso), el mismo registro dos veces (un solo aviso), un error forzado (llega a la fila de fallidos), `/pendientes`, `/ventas` y `/entregado`.
- Alarma de CloudWatch para la DLQ de mensajes y para la fila de avisos fallidos.
