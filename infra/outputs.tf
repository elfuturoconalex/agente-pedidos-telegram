output "tabla_nombre" {
  description = "Nombre de la tabla (lo usará la Lambda)"
  value       = aws_dynamodb_table.pedidos.name
}

output "tabla_arn" {
  description = "Identificador completo de la tabla (para los permisos mínimos de la Lambda)"
  value       = aws_dynamodb_table.pedidos.arn
}

output "parametro_token_telegram" {
  description = "Nombre del parámetro donde vive el token de Telegram (lo leerá la Lambda)"
  value       = aws_ssm_parameter.telegram_token.name
}

output "fila_mensajes_url" {
  description = "Dirección de la fila principal (la usará la Lambda de recepción para meter mensajes)"
  value       = aws_sqs_queue.mensajes.url
}

output "fila_mensajes_arn" {
  description = "Identificador de la fila principal (para permisos y para conectarla con la Lambda del agente)"
  value       = aws_sqs_queue.mensajes.arn
}

output "fila_dlq_arn" {
  description = "Identificador de la fila de mensajes muertos (DLQ)"
  value       = aws_sqs_queue.mensajes_dlq.arn
}

output "lambda_agente" {
  description = "Nombre de la Lambda del agente (para ver sus logs)"
  value       = aws_lambda_function.agente.function_name
}

output "webhook_url" {
  description = "Dirección del webhook que se registra en Telegram (no es secreta, pero no la publiques)"
  value       = "${aws_apigatewayv2_api.webhook.api_endpoint}/telegram"
}

output "lambda_avisador" {
  description = "Nombre de la Lambda avisadora (para ver sus logs)"
  value       = aws_lambda_function.avisador.function_name
}

output "parametro_dueno" {
  description = "Nombre del parámetro donde va el chat_id de Don Chuy"
  value       = aws_ssm_parameter.dueno_chat_id.name
}
