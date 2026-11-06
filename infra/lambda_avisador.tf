# Lambda AVISADORA: le avisa a Don Chuy por Telegram cuando entra un pedido nuevo.
# Código: lambdas/avisador/app.py   ·   Diseño: ADR 003 (DynamoDB Streams, el "papel carbón")

# ---------- 1. El paquete ----------
data "archive_file" "avisador" {
  type        = "zip"
  output_path = "${path.module}/build/avisador.zip"

  source {
    content  = file("${path.module}/../lambdas/avisador/app.py")
    filename = "app.py"
  }
}

# ---------- 2. La fila de avisos fallidos ----------
# Si un aviso falla 3 veces, aquí queda la nota de cuál fue (el pedido sigue en /pendientes).
resource "aws_sqs_queue" "avisos_fallidos" {
  name                      = "agente-pedidos-avisos-fallidos"
  message_retention_seconds = 1209600 # 14 días para revisarlo
  sqs_managed_sse_enabled   = true
}

# ---------- 3. El gafete ----------
resource "aws_iam_role" "avisador" {
  name = "agente-pedidos-avisador"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "avisador" {
  name = "permisos-minimos-avisador"
  role = aws_iam_role.avisador.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EscribirSusLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.avisador.arn}:*"
      },
      {
        Sid      = "LeerElPapelCarbonDeLaTabla"
        Effect   = "Allow"
        Action   = ["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:ListStreams"]
        Resource = "${aws_dynamodb_table.pedidos.arn}/stream/*"
      },
      {
        Sid      = "PonerLaPalomitaDeAvisado"
        Effect   = "Allow"
        Action   = "dynamodb:UpdateItem"
        Resource = aws_dynamodb_table.pedidos.arn
      },
      {
        Sid      = "LeerElTokenYElChatDelDueno"
        Effect   = "Allow"
        Action   = "ssm:GetParameter"
        Resource = [aws_ssm_parameter.telegram_token.arn, aws_ssm_parameter.dueno_chat_id.arn]
      },
      {
        Sid      = "DejarNotaDeAvisosFallidos"
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.avisos_fallidos.arn
      }
    ]
  })
}

# ---------- 4. Los logs ----------
resource "aws_cloudwatch_log_group" "avisador" {
  name              = "/aws/lambda/agente-pedidos-avisador"
  retention_in_days = 14
}

# ---------- 5. La Lambda ----------
resource "aws_lambda_function" "avisador" {
  function_name = "agente-pedidos-avisador"
  role          = aws_iam_role.avisador.arn
  runtime       = "python3.12"
  architectures = ["arm64"]
  handler       = "app.handler"
  timeout       = 10  # solo manda un mensaje
  memory_size   = 128 # lo mínimo; no piensa, solo avisa

  filename         = data.archive_file.avisador.output_path
  source_code_hash = data.archive_file.avisador.output_base64sha256

  environment {
    variables = {
      TABLA           = aws_dynamodb_table.pedidos.name
      PARAMETRO_TOKEN = aws_ssm_parameter.telegram_token.name
      PARAMETRO_DUENO = aws_ssm_parameter.dueno_chat_id.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.avisador, aws_iam_role_policy.avisador]
}

# ---------- 6. La conexión: papel carbón → avisadora, con filtro ----------
resource "aws_lambda_event_source_mapping" "pedidos_a_avisador" {
  event_source_arn  = aws_dynamodb_table.pedidos.stream_arn
  function_name     = aws_lambda_function.avisador.arn
  starting_position = "LATEST" # solo pedidos de aquí en adelante (no avisa los viejos)
  batch_size        = 1

  # Si falla: 3 reintentos; un aviso de más de 1 hora ya no se reintenta (para eso está /pendientes).
  maximum_retry_attempts        = 3
  maximum_record_age_in_seconds = 3600

  # El filtro: solo cuando se CREA un registro cuya SK empieza con PEDIDO#.
  # Lo demás (pláticas, contadores, libretas, la palomita de avisado) no despierta a la Lambda ni cuesta.
  filter_criteria {
    filter {
      pattern = jsonencode({
        eventName = ["INSERT"]
        dynamodb  = { Keys = { SK = { S = [{ prefix = "PEDIDO#" }] } } }
      })
    }
  }

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.avisos_fallidos.arn
    }
  }

  depends_on = [aws_iam_role_policy.avisador]
}
