# Filas de mensajes (ADR 002: docs/adr/002-fila-sqs.md)
#
#   Telegram → Lambda de recepción → [ fila principal FIFO ] → Lambda del agente
#                                            ↓ si falla 3 veces
#                                     [ fila DLQ FIFO ]  (casos para revisar a mano)
#
# FIFO = "primero en entrar, primero en salir": los mensajes de un mismo cliente
# salen en orden y uno a la vez. En AWS, el nombre de una fila FIFO debe terminar en ".fifo".

# Fila de mensajes muertos (DLQ): aquí caen los mensajes que fallaron 3 veces.
resource "aws_sqs_queue" "mensajes_dlq" {
  name       = "agente-pedidos-mensajes-dlq.fifo"
  fifo_queue = true # la DLQ de una fila FIFO también debe ser FIFO

  message_retention_seconds = 1209600 # 14 días para revisarlos y corregir
  sqs_managed_sse_enabled   = true    # cifrado de SQS, sin costo extra
}

# Fila principal: la "bandeja de pendientes".
resource "aws_sqs_queue" "mensajes" {
  name       = "agente-pedidos-mensajes.fifo"
  fifo_queue = true

  # Contra duplicados usamos el update_id de Telegram (lo manda la Lambda de recepción),
  # no el contenido del mensaje: dos clientes pueden escribir exactamente "hola".
  content_based_deduplication = false

  # Mientras el agente atiende un mensaje, la fila lo "esconde" para que nadie más lo tome.
  # AWS recomienda al menos 6 veces el tiempo máximo de la Lambda (60 s) = 360 s.
  visibility_timeout_seconds = 360

  message_retention_seconds = 345600 # 4 días: si todo se cae, los mensajes esperan
  sqs_managed_sse_enabled   = true

  # Después de 3 intentos fallidos, el mensaje se aparta a la DLQ.
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.mensajes_dlq.arn
    maxReceiveCount     = 3
  })
}
