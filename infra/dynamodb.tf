# Tabla única del agente de pedidos. Diseño completo en docs/adr/001-base-de-datos.md
#
#  Ítem                  PK                   SK
#  Plática y carrito     CLIENTE#<chat_id>    PLATICA          (se borra sola a las 24 h)
#  Pedido                CLIENTE#<chat_id>    PEDIDO#<folio>
#  Contador de folios    CONTADOR             FOLIO
#  Ventas de la semana   VENTAS               SEMANA#2026-W44
#  Ventas del mes        VENTAS               MES#2026-10
resource "aws_dynamodb_table" "pedidos" {
  name         = var.nombre_tabla
  billing_mode = "PAY_PER_REQUEST" # bajo demanda: se paga por uso, sin costo fijo

  hash_key  = "PK" # la carpeta
  range_key = "SK" # la hoja dentro de la carpeta

  # Solo se declaran las columnas que son llaves (de la tabla o del índice).
  # Lo demás (productos, total, dirección...) se guarda libre en cada ítem.
  attribute {
    name = "PK"
    type = "S" # S = texto
  }
  attribute {
    name = "SK"
    type = "S"
  }
  attribute {
    name = "GSI1PK"
    type = "S"
  }
  attribute {
    name = "GSI1SK"
    type = "S"
  }

  # Índice de pedidos nuevos: GSI1PK = ESTADO#nuevo, GSI1SK = <fecha y hora>#<folio>
  # Solo los pedidos pendientes llevan estas etiquetas (índice "disperso").
  # (El provider de AWS 6.x pide "key_schema" para las llaves del índice; hash_key/range_key ahí están obsoletos.)
  global_secondary_index {
    name            = "GSI1"
    projection_type = "ALL"

    key_schema {
      attribute_name = "GSI1PK"
      key_type       = "HASH" # la carpeta del índice
    }
    key_schema {
      attribute_name = "GSI1SK"
      key_type       = "RANGE" # el orden dentro de la carpeta
    }
  }

  # Borrado automático: los ítems con el atributo "expira" (las pláticas) se borran solos.
  ttl {
    attribute_name = "expira"
    enabled        = true
  }

  # Respaldo continuo: permite regresar la tabla a cualquier momento de los últimos 35 días.
  # Cuesta según el tamaño de la tabla (centavos para una tiendita).
  point_in_time_recovery {
    enabled = true
  }

  # En producción se activa para que nadie la borre por error.
  # En desarrollo lo dejamos apagado para poder destruir y volver a crear mientras aprendo.
  deletion_protection_enabled = false
}
