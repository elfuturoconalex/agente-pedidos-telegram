# ADR 001: Base de datos para el agente de pedidos y diseño de sus llaves

- **Estado:** Aceptado
- **Fecha:** 26 de octubre de 2026
- **Autor:** Alejandro Padilla

## 1. Contexto

En la Fase 1 el agente corre en mi Mac sin parar y guarda la plática y el carrito **en memoria (RAM)**. Los pedidos confirmados van a un archivo `salidas/pedidos.json`.

En la Fase 2 el agente pasa a **AWS Lambda**. Una Lambda se prende cuando llega un mensaje, contesta y se apaga, y **al apagarse olvida todo**. Cada mensaje lo puede atender una Lambda distinta. Por eso hace falta una base de datos que funcione como la **nota del cambio de turno**: cualquier Lambda lee cómo iba la plática, contesta y anota lo nuevo.

## 2. Qué le vamos a preguntar a la base de datos

Esto se decide **antes** de elegir y diseñar, porque define cómo se acomodan los datos.

| # | Quién pregunta | Pregunta | Qué tan seguido |
|---|---|---|---|
| P1 | El agente | ¿Cómo iba la plática y el carrito de este chat? | En **cada** mensaje |
| P2 | El agente | Guarda la plática y el carrito actualizados | En **cada** mensaje |
| P3 | El agente | Dame el siguiente folio, sin repetir aunque lleguen dos pedidos al mismo tiempo | Al confirmar |
| P4 | El agente | Guarda este pedido confirmado | Al confirmar |
| P5 | El dueño | ¿Qué pedidos **nuevos** tengo sin atender? | Varias veces al día |
| P6 | El dueño | Marca este pedido como entregado (o cancelado) | Por pedido |
| P7 | El dueño | ¿Cuánto llevo vendido **esta semana**? (en pesos y por producto) | Cuando quiera |
| P8 | El dueño | ¿Cuánto llevo vendido **este mes**? | Cuando quiera |
| P9 | El dueño | Comparar semanas o meses anteriores | De vez en cuando |
| — | A futuro | Historial de un cliente; buscar un pedido solo por su folio | No ahora |

El **catálogo** (precios y existencias) se queda como archivo `catalogo.json` dentro de la Lambda, igual que en la Fase 1: casi no cambia y así evito lecturas a la base de datos. Si en el futuro el dueño quiere cambiar precios sin tocar código, se mueve a la base de datos en otro ADR.

## 3. Requisitos

| # | Requisito | Peso |
|---|---|---|
| R1 | **Costo:** proyecto de aprendizaje y tiendita pequeña. Sin costo fijo mensual aunque nadie escriba. | Muy alto |
| R2 | **Rapidez en P1 y P2:** se hacen en cada mensaje; deben tardar milisegundos. | Alto |
| R3 | **Encajar con Lambda:** sin servidores que administrar ni red privada (VPC) obligatoria. | Alto |
| R4 | **Folios sin repetir** aunque haya pedidos al mismo tiempo. | Alto |
| R5 | **Limpieza automática:** las pláticas viejas no se deben acumular. | Medio |
| R6 | **Reportes sencillos** (semana y mes) sin recorrer todos los pedidos. | Medio |
| R7 | **Aprendizaje:** modelado de datos, relevante para mi carrera de arquitecto. | Medio |

## 4. Opciones consideradas

### A. Amazon DynamoDB (bajo demanda)
"La agenda del celular": buscar por llave es instantáneo, pero hay que preparar desde antes cada búsqueda frecuente.
- **Costo:** se paga por cada lectura y escritura (fracciones de centavo) y por lo guardado. **Sin costo fijo.**
- **A favor:** serverless como Lambda; búsqueda por llave en milisegundos; borrado automático (TTL); escrituras con condición y contadores atómicos para el folio; AWS guarda copias en 3 centros de datos.
- **En contra:** hay que pensar antes las preguntas; los reportes libres ("ventas por colonia") no son su fuerte; no hay SQL ni cruces de tablas.

### B. Amazon RDS (PostgreSQL o MySQL)
"Excel con reglas": cualquier pregunta con SQL, aunque no la hayas planeado.
- **Costo:** un servidor prendido 24/7; **costo fijo mensual** aunque no haya pedidos.
- **A favor:** consultas libres y reportes de cualquier tipo.
- **En contra:** rompe R1; hay que administrar parches, respaldos y una red privada (VPC) para que la Lambda se conecte, con más configuración y conexiones que cuidar.

### C. Amazon Aurora Serverless v2 (PostgreSQL)
"El Excel que se apaga solo".
- **Costo:** escala según el uso y puede pausarse sin tráfico, pero al despertar tarda varios segundos.
- **A favor:** SQL completo sin un servidor fijo.
- **En contra:** la pausa haría que el primer mensaje de la mañana tarde; sigue necesitando VPC; es más compleja de lo que pide una tiendita.

### D. Archivos JSON en S3
"Seguir con el archivo, pero en la nube".
- **Costo:** casi nada.
- **En contra:** si dos Lambdas escriben al mismo tiempo, una puede borrar lo de la otra; no hay folios seguros (R4) ni búsquedas; para leer un pedido hay que bajar todo el archivo.

## 5. Decisión

**Amazon DynamoDB, en modo bajo demanda, con una sola tabla** llamada `pedidos-don-chuy`.

Cumple R1 a R5 de forma directa. R6 se resuelve con **libretas de ventas que se van sumando** (ver abajo). Lo que se pierde (reportes libres) no es necesario hoy, y si se necesita, los datos se pueden exportar después a otra herramienta.

## 6. Diseño de la tabla

Cada dato es un **ítem** con dos etiquetas:
- **PK (llave de partición):** la carpeta.
- **SK (llave de orden):** la hoja dentro de la carpeta.

| Ítem | PK | SK | Qué guarda | Responde |
|---|---|---|---|---|
| Plática | `CLIENTE#<chat_id>` | `PLATICA` | Últimos 20 mensajes, carrito y `expira` (24 h) | P1, P2 |
| Pedido | `CLIENTE#<chat_id>` | `PEDIDO#<folio>` | Fecha, productos, total, dirección, forma de pago, estado | P4, P6 |
| Contador de folios | `CONTADOR` | `FOLIO` | Último número usado | P3 |
| Ventas de la semana | `VENTAS` | `SEMANA#2026-W44` | Total en pesos, número de pedidos, cantidad por producto | P7, P9 |
| Ventas del mes | `VENTAS` | `MES#2026-10` | Lo mismo, por mes | P8, P9 |

**Por qué la carpeta es el `chat_id` y no el nombre:** los nombres se repiten y se pueden cambiar en Telegram. El `chat_id` es un número único que nunca cambia, como el número de celular.

**Índice para los pedidos nuevos (GSI1).** Cada pedido lleva dos etiquetas más:
- `GSI1PK = ESTADO#nuevo`
- `GSI1SK = <fecha y hora>#<folio>`

Así, "¿qué pedidos nuevos tengo?" (P5) es abrir **una sola carpeta**, ordenada del más viejo al más nuevo. Cuando el dueño marca el pedido como entregado, se le quita la etiqueta y sale solo de la lista. Es un índice "disperso": solo contiene los pedidos pendientes, así que siempre es pequeño.

**Libretas de ventas.** Al confirmar un pedido, el código **suma** su total y sus productos a la libreta de la semana y a la del mes. Leer "¿cuánto llevo?" es **una sola lectura**, sin recorrer pedidos, igual que leer los contadores de una interfaz en un switch. El mes lleva su propia libreta porque un mes no son exactamente 4 semanas (hay semanas que cruzan de un mes a otro). Si un pedido se cancela, se **resta**.

## 7. Cómo se usa en cada momento

**En cada mensaje:**
1. Leer `CLIENTE#<chat_id>` / `PLATICA` (una lectura por llave).
2. Claude contesta y usa sus herramientas.
3. Guardar la plática y el carrito actualizados, con `expira` = ahora + 24 horas.

**Al confirmar un pedido:**
1. Sumar 1 al contador de folios de forma **atómica**; DynamoDB regresa el número nuevo y nunca entrega el mismo a dos pedidos.
2. En una sola **transacción** (todo o nada): guardar el pedido, sumar a la libreta de la semana, sumar a la del mes y vaciar el carrito.

## 8. Detalles que no se pueden olvidar

- **Hora de México:** AWS trabaja en UTC (6 horas adelante). La fecha, la semana y el mes se calculan con la hora de **America/Mexico_City**; si no, un pedido del domingo a las 9 de la noche caería en la semana siguiente.
- **Semanas de lunes a domingo**, con el número de semana estándar (ISO 8601).
- **Dinero en números enteros de pesos** (o centavos), nunca con decimales flotantes, para que las sumas cuadren siempre.
- **Borrado automático (TTL)** activado sobre el atributo `expira`. Solo las pláticas lo llevan; los pedidos y las libretas no se borran.
- **Mínimo privilegio:** la Lambda del agente solo puede leer y escribir en esta tabla y en su índice; nada más.
- **Datos personales:** la tabla guarda nombre y dirección de clientes. Va cifrada (DynamoDB cifra por defecto) y nunca se suben datos reales a GitHub.

## 9. Consecuencias

- Las búsquedas frecuentes cuestan centavos y tardan milisegundos.
- Si mañana se agrega otra pregunta frecuente (por ejemplo, "buscar solo por folio" o "historial del cliente"), habrá que agregar un índice o un ítem nuevo y documentarlo.
- Los reportes que no estén en la tabla de la sección 2 requieren exportar los datos.
- El modelo en una sola tabla es más difícil de leer a primera vista que varias tablas; por eso este ADR documenta cada ítem.

## 10. Seguimiento

- Crear la tabla, el índice y el TTL con **Terraform**.
- Probar con el examen de conversaciones (8 casos) ya en AWS.
- Revisar en la factura que el costo de DynamoDB quede en centavos.
- ADR 002 (fila SQS FIFO + DLQ) define cómo evitar procesar dos veces el mismo mensaje de Telegram.
