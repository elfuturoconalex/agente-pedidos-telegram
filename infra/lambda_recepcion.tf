# Lambda de RECEPCIÓN + API Gateway: la puerta de entrada (ADR 002).
#
#   Telegram ──(POST /telegram + clave secreta)──► API Gateway ──► Lambda de recepción ──► fila SQS FIFO

# ---------- 1. El paquete ----------
data "archive_file" "recepcion" {
  type        = "zip"
  source_file = "${path.module}/../lambdas/recepcion/app.py"
  output_path = "${path.module}/build/recepcion.zip"
}

# ---------- 2. El gafete y sus permisos mínimos ----------
resource "aws_iam_role" "recepcion" {
  name = "agente-pedidos-recepcion"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "recepcion" {
  name = "permisos-minimos-recepcion"
  role = aws_iam_role.recepcion.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EscribirSusLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.recepcion.arn}:*"
      },
      {
        Sid      = "LeerSoloLaClaveDelWebhook"
        Effect   = "Allow"
        Action   = "ssm:GetParameter"
        Resource = aws_ssm_parameter.webhook_secret.arn
      },
      {
        Sid      = "SoloMeterMensajesASuFila" # no puede leer ni borrar: solo meter
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.mensajes.arn
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "recepcion" {
  name              = "/aws/lambda/agente-pedidos-recepcion"
  retention_in_days = 14
}

# ---------- 3. La Lambda ----------
resource "aws_lambda_function" "recepcion" {
  function_name = "agente-pedidos-recepcion"
  role          = aws_iam_role.recepcion.arn
  runtime       = "python3.12"
  architectures = ["arm64"]
  handler       = "app.handler"
  timeout       = 10  # solo revisa y mete a la fila: milisegundos
  memory_size   = 128 # la más chica

  filename         = data.archive_file.recepcion.output_path
  source_code_hash = data.archive_file.recepcion.output_base64sha256

  environment {
    variables = {
      URL_FILA                  = aws_sqs_queue.mensajes.url
      PARAMETRO_SECRETO_WEBHOOK = aws_ssm_parameter.webhook_secret.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.recepcion, aws_iam_role_policy.recepcion]
}

# ---------- 4. API Gateway: la dirección pública ----------
resource "aws_apigatewayv2_api" "webhook" {
  name          = "agente-pedidos-webhook"
  protocol_type = "HTTP" # la versión sencilla y barata de API Gateway
}

resource "aws_apigatewayv2_integration" "recepcion" {
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY" # pasa la petición completa a la Lambda
  integration_uri        = aws_lambda_function.recepcion.invoke_arn
  payload_format_version = "2.0"
}

# Una sola puerta: POST /telegram. Cualquier otra ruta responde "no existe".
resource "aws_apigatewayv2_route" "telegram" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /telegram"
  target    = "integrations/${aws_apigatewayv2_integration.recepcion.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.webhook.id
  name        = "$default"
  auto_deploy = true

  # Freno contra abusos (como el CIR/Bc de un enlace): 10 peticiones por segundo, ráfagas de 20.
  default_route_settings {
    throttling_rate_limit  = 10
    throttling_burst_limit = 20
  }
}

# Permiso para que API Gateway (y solo esta API) despierte a la Lambda.
resource "aws_lambda_permission" "api_a_recepcion" {
  statement_id  = "PermitirAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.recepcion.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*/telegram"
}
