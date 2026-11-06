# Secretos del agente, guardados cifrados en AWS Systems Manager Parameter Store.
#
# Por qué Parameter Store y no Secrets Manager:
#   - Parámetros estándar: gratis. Secrets Manager cobra por secreto al mes.
#   - No necesitamos rotación automática (el token de Telegram se cambia a mano en @BotFather).
#
# Por qué el valor real NO está aquí:
#   - Este código se sube a GitHub, y lo que Terraform guarda también queda en su libreta (el state).
#   - Terraform crea el "cajón" con un valor de relleno, y el token real se pega a mano en la consola.
#   - "ignore_changes" le dice a Terraform: no vuelvas a tocar el valor, aunque sea distinto al de aquí.
#
# La llave de Claude ya no hace falta: en AWS se usa Claude a través de Bedrock con el rol de la Lambda.
resource "aws_ssm_parameter" "telegram_token" {
  name        = "/agente-pedidos/telegram/bot-token"
  description = "Token del bot de Telegram. El valor real se pega en la consola; no esta en el codigo ni en GitHub."
  type        = "SecureString" # cifrado con la llave de AWS para Parameter Store (sin costo)
  value       = "CAMBIAR-EN-LA-CONSOLA"

  lifecycle {
    ignore_changes = [value]
  }
}

# Clave secreta del webhook: Telegram la manda en cada mensaje y la Lambda de recepción la revisa.
# Así, aunque alguien descubra la dirección de API Gateway, no puede meter mensajes falsos.
#
# Esta clave la INVENTA Terraform (no viene de fuera como el token), por eso su valor sí queda en el
# state. Es una razón más por la que el state nunca se sube a GitHub.
resource "random_password" "webhook" {
  length  = 48
  special = false # Telegram solo acepta letras, números, "_" y "-"
}

resource "aws_ssm_parameter" "webhook_secret" {
  name        = "/agente-pedidos/telegram/webhook-secret"
  description = "Clave secreta del webhook de Telegram (la genera Terraform)."
  type        = "SecureString"
  value       = random_password.webhook.result
}

# El chat_id de Don Chuy: a dónde manda sus avisos la Lambda avisadora (ADR 003).
# No es secreto (por eso es "String", no "SecureString"), pero tampoco va en GitHub:
# se pone a mano después de que Don Chuy le escribe al bot por primera vez.
resource "aws_ssm_parameter" "dueno_chat_id" {
  name        = "/agente-pedidos/dueno/chat-id"
  description = "chat_id de Telegram del dueno. Se pone a mano; no esta en el codigo ni en GitHub."
  type        = "String"
  value       = "CAMBIAR-EN-LA-CONSOLA"

  lifecycle {
    ignore_changes = [value]
  }
}
