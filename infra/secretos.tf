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
