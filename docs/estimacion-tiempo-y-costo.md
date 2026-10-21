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

| Fase | Sesiones estimadas | Sesiones reales | Costo real |
|---|---|---|---|
| 1 | 5 | | |
| 2 | 7.5 | | |
| 3 | 4 | | |
