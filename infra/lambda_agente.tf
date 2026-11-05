# Lambda del AGENTE: toma los mensajes de la fila SQS, uno a la vez, y atiende al cliente.
# Código: lambdas/agente/app.py   ·   Diseño: ADR 001 (DynamoDB) y ADR 002 (fila SQS)

data "aws_caller_identity" "yo" {} # el número de cuenta, sin escribirlo en el código

# ---------- 1. El paquete: app.py + catalogo.json en un .zip ----------
data "archive_file" "agente" {
  type        = "zip"
  output_path = "${path.module}/build/agente.zip" # no se sube a GitHub (*.zip en .gitignore)

  source {
    content  = file("${path.module}/../lambdas/agente/app.py")
    filename = "app.py"
  }
  source {
    content  = file("${path.module}/../catalogo.json") # un solo catálogo para todo el proyecto
    filename = "catalogo.json"
  }
}

# ---------- 2. El gafete: el rol con el que trabaja la Lambda ----------
resource "aws_iam_role" "agente" {
  name = "agente-pedidos-agente"

  # Quién puede ponerse este gafete: solo el servicio Lambda.
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Permisos MÍNIMOS: solo lo que el agente necesita, solo sobre SUS recursos.
resource "aws_iam_role_policy" "agente" {
  name = "permisos-minimos-agente"
  role = aws_iam_role.agente.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EscribirSusLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.agente.arn}:*"
      },
      {
        Sid      = "LeerYEscribirSoloSuTabla"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:ConditionCheckItem"]
        Resource = aws_dynamodb_table.pedidos.arn
      },
      {
        Sid      = "LeerSoloElTokenDeTelegram"
        Effect   = "Allow"
        Action   = "ssm:GetParameter"
        Resource = aws_ssm_parameter.telegram_token.arn
      },
      {
        Sid    = "UsarSoloClaudeHaiku"
        Effect = "Allow"
        Action = "bedrock:InvokeModel"
        Resource = [
          "arn:aws:bedrock:*:${data.aws_caller_identity.yo.account_id}:inference-profile/global.anthropic.claude-haiku-4-5*",
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5*"
        ]
      },
      {
        Sid      = "TomarMensajesDeSuFila"
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = aws_sqs_queue.mensajes.arn
      }
    ]
  })
}

# ---------- 3. Los logs: se guardan 14 días (sin esto, CloudWatch los guarda para siempre) ----------
resource "aws_cloudwatch_log_group" "agente" {
  name              = "/aws/lambda/agente-pedidos-agente"
  retention_in_days = 14
}

# ---------- 4. La Lambda ----------
resource "aws_lambda_function" "agente" {
  function_name = "agente-pedidos-agente"
  role          = aws_iam_role.agente.arn
  runtime       = "python3.12"
  architectures = ["arm64"] # procesadores Graviton: más baratos que x86
  handler       = "app.handler"
  timeout       = 60  # ADR 002: la fila esconde el mensaje 6 veces este tiempo (360 s)
  memory_size   = 256 # MB; también define cuánta CPU recibe

  filename         = data.archive_file.agente.output_path
  source_code_hash = data.archive_file.agente.output_base64sha256 # si cambia el código, se vuelve a subir

  environment {
    variables = {
      TABLA           = aws_dynamodb_table.pedidos.name
      PARAMETRO_TOKEN = aws_ssm_parameter.telegram_token.name
      MODELO          = var.modelo
      MODO_PRUEBA     = var.modo_prueba
    }
  }

  depends_on = [aws_cloudwatch_log_group.agente, aws_iam_role_policy.agente]
}

# ---------- 5. La conexión: fila SQS → Lambda ----------
resource "aws_lambda_event_source_mapping" "fila_a_agente" {
  event_source_arn = aws_sqs_queue.mensajes.arn
  function_name    = aws_lambda_function.agente.arn
  batch_size       = 1 # ADR 002: un mensaje por vuelta

  # Freno de costos: como máximo 5 agentes trabajando al mismo tiempo (clientes distintos).
  scaling_config {
    maximum_concurrency = 5
  }
}
