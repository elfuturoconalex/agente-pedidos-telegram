variable "region" {
  description = "Región de AWS donde vive todo el proyecto"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Perfil de la AWS CLI (aws configure sso) con el que entra Terraform"
  type        = string
  default     = "personal"
}

variable "nombre_tabla" {
  description = "Nombre de la tabla de DynamoDB (ADR 001)"
  type        = string
  default     = "pedidos-don-chuy"
}
