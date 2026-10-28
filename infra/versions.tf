# Qué versión de Terraform y qué "traductor" (provider) usamos.
# El provider de AWS es el que traduce este código a llamadas a AWS.
terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
