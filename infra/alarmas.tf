# Alarmas: si algo cae en una fila de fallas, me llega un correo.
# Sin esto, una falla real se queda callada en la fila (como un syslog que nadie lee).
#
#   Fila vigilada                       Qué significa
#   agente-pedidos-mensajes-dlq.fifo    Un mensaje de cliente falló 3 veces (ADR 002)
#   agente-pedidos-avisos-fallidos      Un aviso a Don Chuy falló 3 veces (ADR 003)

# ---------- 1. El "megáfono": un tema de SNS que reparte las alertas ----------
resource "aws_sns_topic" "alertas" {
  name = "agente-pedidos-alertas"
}

# Quién escucha el megáfono: mi correo. AWS manda un correo para CONFIRMAR la suscripción;
# hasta que le doy clic al enlace, no llega ninguna alerta.
resource "aws_sns_topic_subscription" "correo" {
  topic_arn = aws_sns_topic.alertas.arn
  protocol  = "email"
  endpoint  = var.correo_alertas # viene de terraform.tfvars (no se sube a GitHub)
}

# ---------- 2. Las alarmas: una por fila ----------
# "for_each" crea una alarma por cada renglón de esta lista, con la misma receta.
locals {
  filas_vigiladas = {
    mensajes-dlq = {
      fila = aws_sqs_queue.mensajes_dlq.name
      que  = "Un mensaje de cliente fallo 3 veces y esta en la DLQ. Revisar logs del agente."
    }
    avisos-fallidos = {
      fila = aws_sqs_queue.avisos_fallidos.name
      que  = "Un aviso a Don Chuy fallo 3 veces. El pedido sigue en /pendientes. Revisar logs de la avisadora."
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "fila_con_fallas" {
  for_each = local.filas_vigiladas

  alarm_name        = "agente-pedidos-${each.key}"
  alarm_description = each.value.que

  # La medida: cuántos mensajes hay esperando en la fila.
  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"
  dimensions  = { QueueName = each.value.fila }

  # La regla: si en 5 minutos hubo 1 o más, suena.
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching" # sin datos = todo bien (la fila está vacía o dormida)

  alarm_actions = [aws_sns_topic.alertas.arn] # correo cuando suena
  ok_actions    = [aws_sns_topic.alertas.arn] # correo cuando vuelve a la normalidad
}
