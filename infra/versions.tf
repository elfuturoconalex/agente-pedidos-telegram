# Qué versión de Terraform y qué "traductor" (provider) usamos.
# El provider de AWS es el que traduce este código a llamadas a AWS.
terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    # Empaca el código de las Lambdas en un .zip
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
    # Genera la clave secreta del webhook
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}
