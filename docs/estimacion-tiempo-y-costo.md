# Estimación de tiempo y costo · Agente #3

*Preliminar, 18 de octubre de 2026. Se compara contra lo real al terminar cada fase.*

## Tiempo: ~16 sesiones de 60–90 minutos

| Fase | Sesiones | Qué incluye |
|---|---|---|
| **1. Local (mi Mac)** | 5 | Crear el bot y guardar su token de forma segura · loop del agente con un catálogo ficticio · memoria de la conversación y confirmación del pedido · guardar en una base de datos local · primer examen de conversaciones |
| **2. AWS con Terraform** | 7.5 | Terraform sin llaves · ADR 001: base de datos y sus llaves (PK/SK) · base de datos y secretos · Lambdas con permisos mínimos · API Gateway + webhook seguro de Telegram · ADR 002: fila SQS FIFO + DLQ (orden, reintentos, sin duplicados) · ADR 003: eventos o directo |
| **3. Lista para producción** | 4 | Esquema del pedido y validación · corrección automática y errores claros · examen de 20–30 conversaciones · README, diagrama final y bitácora |
| **Total** | **~16.5** | ~17–20 horas |

## Costo durante el desarrollo: ~5–10 USD

| Servicio | Costo aproximado |
|---|---|
| Telegram Bot API | Gratis |
| Claude Haiku en Bedrock | ~0.02–0.05 USD por pedido completo (varios mensajes de ida y vuelta) · ~150 conversaciones de prueba ≈ 3–7 USD |
| DynamoDB (bajo demanda) | Centavos |
| Lambda y API Gateway | Dentro de la capa gratuita o centavos |
| Parameter Store (estándar) | Gratis |
| SQS (FIFO + DLQ) | Gratis (primer millón de mensajes al mes) |
| EventBridge (si se usa) | Centavos |
| CloudWatch Logs | Centavos |

## Costo en uso real (referencia)

Con **1,000 pedidos al mes**: ~20–50 USD en Claude más centavos de lo demás. Un pedido cuesta más que una pregunta del Agente #2 porque es una **conversación de varios mensajes** y cada mensaje vuelve a leer el historial.

> Los precios son aproximados y cambian. Validar en la AWS Pricing Calculator y en Billing antes de cotizar.

## Estimado vs. real

*Cierre de la Fase 3, 24 de noviembre de 2026. Costos de AWS confirmados en Billing (Cost Explorer, por día).*

| Fase | Sesiones estimadas | Sesiones reales | Costo real |
|---|---|---|---|
| 1 | 5 | 4 | ~US$1 (API de Anthropic directo, fuera de AWS) |
| 2 | 7.5 | 6 | US$0.27 (Billing) |
| 3 | 4 | 3 | US$14.40 (Billing) |
| **Total** | **16.5** | **13** | **~US$15.70** |

### Lo que dice Billing

- **Claude Haiku 4.5 en Bedrock es prácticamente todo el costo:** US$14.67 del Agente 3. DynamoDB, Lambda, API Gateway, SQS, SNS, CloudWatch y Parameter Store juntos sumaron **US$0.01**: todo cupo en la capa gratuita.
- **La Fase 3 costó 50 veces más que la Fase 2, y fue a propósito:** el dinero se fue en los exámenes de 30 a 33 casos × 3 vueltas (~US$1.90 cada uno, 6 exámenes grandes más las corridas de 15 casos). El día más caro fue el cierre de la Sesión 13: US$7.73 en 4 exámenes.
- El gasto de octubre en Bedrock (US$0.35) es de los agentes anteriores; la Fase 1 de este agente usó la API de Anthropic directo.

### Por qué el costo de desarrollo salió arriba del estimado (~US$15.70 contra 5–10)

- **El costo por plática sí salió como se estimó:** ~US$0.007 por mensaje y ~US$0.02–0.04 por pedido completo.
- **Lo que se subestimó fue cuántas pláticas de prueba hacían falta:** el estimado decía ~150; solo los exámenes de la Fase 3 sumaron más de 750. Correr cada caso 3 veces fue lo que encontró los errores graves (prometer una cosa y guardar otra), así que es un gasto que vale la pena.
- **Lección para cotizar:** en un agente, la evaluación cuesta más que la infraestructura. Hay que presupuestarla aparte.

### Costo en uso real, revisado

Con lo medido, **1,000 pedidos al mes ≈ US$20–40 en Claude** más centavos de lo demás (sin costo fijo). Queda dentro del rango del estimado (20–50 USD).
