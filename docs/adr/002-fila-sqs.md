# ADR 002: Cómo llegan los mensajes de Telegram al agente sin perderse ni duplicarse

- **Estado:** Aceptado
- **Fecha:** 3 de noviembre de 2026
- **Autor:** Alejandro Padilla

## 1. Contexto

En AWS, Telegram avisa de cada mensaje nuevo con un **webhook**: le manda el mensaje a una dirección de API Gateway, que despierta una Lambda.

El agente tarda varios segundos en contestar (Claude piensa, usa herramientas, lee y escribe en DynamoDB). En ese tiempo pueden pasar cosas:
- **Algo falla a la mitad** (Bedrock tarda, se corta la red, un error en el código). Si Telegram ya recibió "ok", **el mensaje se pierde**.
- **Telegram reintenta** si no recibe respuesta a tiempo. Si el primer intento sí había avanzado, el mismo mensaje se procesa **dos veces** (por ejemplo, un pedido duplicado).
- **El cliente escribe dos mensajes seguidos** ("quiero tortillas" y "mejor que sean 3"). Si se procesan al mismo tiempo, el segundo puede terminar antes que el primero y el carrito queda mal.

## 2. Requisitos

| # | Requisito | Peso |
|---|---|---|
| R1 | **Ningún mensaje se pierde** aunque algo falle. | Muy alto |
| R2 | **Ningún mensaje se procesa dos veces** (sobre todo, ningún pedido duplicado). | Muy alto |
| R3 | **Orden por cliente:** los mensajes de un mismo chat se atienden en el orden en que llegaron, uno a la vez. | Alto |
| R4 | **Clientes distintos en paralelo:** un cliente lento no detiene a los demás. | Medio |
| R5 | **Lo que falla varias veces se aparta** para revisarlo, sin trabar a los demás. | Alto |
| R6 | **Costo:** centavos; sin costo fijo. | Alto |
| R7 | **Respuesta rápida a Telegram**, para que no reintente sin necesidad. | Medio |

## 3. Opciones consideradas

### A. Directo: el webhook llama a una sola Lambda que hace todo
"El que recibe la carta la atiende ahí mismo".
- **A favor:** la más sencilla; una sola Lambda.
- **En contra:** si falla a la mitad, el mensaje se pierde o Telegram reintenta y se duplica; no garantiza orden; Telegram espera mientras Claude piensa. No cumple R1, R2 ni R3.

### B. Lambda que se llama a sí misma en segundo plano (como el Agente Investigador)
"Recibir, contestar 'recibido' y atender después".
- **A favor:** responde rápido a Telegram; Lambda reintenta 2 veces y puede mandar lo que falla a un destino.
- **En contra:** **no garantiza orden** ni evita duplicados; para el Investigador no importaba (cada tema es independiente), aquí sí (la plática tiene orden). No cumple R2 ni R3.

### C. Fila SQS estándar
"Bandeja de pendientes, sin orden".
- **A favor:** casi ilimitada, barata, con reintentos y fila de mensajes muertos (DLQ).
- **En contra:** **puede entregar un mensaje más de una vez y en desorden.** No cumple R3 y deja R2 todo al código.

### D. Fila SQS FIFO + DLQ
"Bandeja de pendientes con fila por cliente".
- **A favor:** **orden garantizado por grupo** (el grupo es el chat del cliente) y **elimina duplicados** que lleguen en una ventana de 5 minutos; clientes distintos se atienden en paralelo; reintentos y DLQ incluidos.
- **En contra:** menos capacidad que la estándar (de sobra para una tiendita); la ventana contra duplicados es de solo 5 minutos.

### E. Kinesis o EventBridge
"Herramientas para millones de eventos o para repartir eventos a muchos sistemas".
- **En contra:** más complejas y caras de lo que pide el caso. EventBridge se evalúa en el ADR 003 para avisar al dueño.

## 4. Decisión

**Opción D: fila SQS FIFO con su fila de mensajes muertos (DLQ), más una marca de "ya procesado" en DynamoDB.**

## 5. Cómo funciona

```
Telegram → API Gateway → Lambda de recepción → Fila SQS FIFO → Lambda del agente → Telegram
                                                    ↓ (si falla 3 veces)
                                               Fila DLQ (FIFO)
```

**Lambda de recepción** (hace muy poco, en milisegundos):
1. Revisa la clave secreta del webhook (que el mensaje venga de Telegram).
2. Mete el mensaje a la fila con dos etiquetas:
   - **Grupo (`MessageGroupId`) = `chat_id`**: los mensajes de un mismo cliente van en fila, uno detrás de otro.
   - **Identificador anti-duplicados (`MessageDeduplicationId`) = `update_id` de Telegram**: si Telegram manda el mismo mensaje dos veces en 5 minutos, la fila se queda con uno.
3. Le contesta "ok" a Telegram. A partir de aquí, **el mensaje ya está seguro en la fila**.

**Lambda del agente** (hace el trabajo pesado):
1. Toma **un mensaje a la vez** de la fila.
2. Revisa en DynamoDB si ese `update_id` **ya se procesó**. Si sí, lo descarta sin hacer nada.
3. Atiende el mensaje como hoy en la Mac (Claude, herramientas, DynamoDB) y le contesta al cliente.
4. Guarda la marca "ya procesado" (`MENSAJE#<update_id>`, se borra sola a las 24 horas).
5. Si todo salió bien, el mensaje sale de la fila. **Si algo falla, el mensaje regresa a la fila y se reintenta.**
6. **Después de 3 intentos fallidos**, se mueve a la **DLQ** para revisarlo a mano, y el siguiente mensaje de ese cliente puede seguir.

## 6. Por qué también la marca en DynamoDB

La fila FIFO evita duplicados solo durante **5 minutos**, y un reintento puede repetir un mensaje que ya iba a la mitad. Por eso el agente se protege a sí mismo (**idempotencia**: hacer lo mismo dos veces da el mismo resultado):
- **Marca "ya procesado"** por `update_id`, guardada con una escritura condicional ("solo si no existe").
- **Agregar al pedido "deja en N"**, no suma (lección del examen de la Fase 1).
- **Confirmar el pedido vacía el carrito** en la misma transacción (ADR 001): si se repitiera, el carrito ya está vacío y no se crea un segundo pedido.

## 7. Ajustes

| Ajuste | Valor | Por qué |
|---|---|---|
| Tipo de fila | FIFO (principal y DLQ) | Orden por cliente y anti-duplicados |
| Mensajes por vuelta del agente | 1 | Más simple; un fallo no afecta a otros mensajes |
| Intentos antes de la DLQ | 3 | Suficiente para fallas pasajeras (red, Bedrock ocupado) |
| Tiempo máximo de la Lambda del agente | 60 segundos | Una plática con varias herramientas cabe de sobra |
| Tiempo de invisibilidad de la fila | 6 minutos | AWS recomienda al menos 6 veces el tiempo de la Lambda, para que un mensaje en proceso no se entregue a otra |
| Cuánto guarda la DLQ | 14 días | Tiempo para revisar y corregir |
| Cifrado | El de SQS por defecto | Sin costo extra |

## 8. Consecuencias

- **Gano:** ningún mensaje perdido, ningún pedido duplicado, cada plática en orden y clientes distintos en paralelo.
- **Costo:** SQS incluye un millón de peticiones gratis al mes; para una tiendita es prácticamente cero.
- **Más piezas:** dos Lambdas y dos filas en lugar de una Lambda. Las crea Terraform.
- **Un mensaje en la DLQ es una falla real:** hace falta enterarse. Siguiente paso: una alarma de CloudWatch cuando la DLQ tenga mensajes (y, a futuro, avisarle al cliente que hubo un problema).
- **Permisos mínimos:** la Lambda de recepción solo puede **meter** mensajes a la fila; la del agente solo puede **leer y borrar** de la fila, y usar la tabla, el parámetro del token y Claude en Bedrock.

## 9. Seguimiento

- Crear con Terraform: las dos filas, las dos Lambdas, sus roles y la conexión fila → Lambda.
- Probar a propósito: el mismo `update_id` dos veces (debe procesarse una), dos mensajes seguidos del mismo chat (deben salir en orden) y un error forzado (debe llegar a la DLQ después de 3 intentos).
- ADR 003: cómo avisarle al dueño cuando entra un pedido.
