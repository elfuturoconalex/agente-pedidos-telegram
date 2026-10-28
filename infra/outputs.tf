output "tabla_nombre" {
  description = "Nombre de la tabla (lo usará la Lambda)"
  value       = aws_dynamodb_table.pedidos.name
}

output "tabla_arn" {
  description = "Identificador completo de la tabla (para los permisos mínimos de la Lambda)"
  value       = aws_dynamodb_table.pedidos.arn
}
