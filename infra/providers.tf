# Cómo entra Terraform a AWS: con el perfil de IAM Identity Center (llaves temporales).
# No hay llaves permanentes en este código ni en la Mac.
provider "aws" {
  region  = var.region
  profile = var.aws_profile

  # Etiquetas que se ponen solas a todo lo que cree Terraform.
  # Sirven para saber de qué proyecto es cada cosa y cuánto cuesta.
  default_tags {
    tags = {
      Proyecto  = "agente-pedidos-telegram"
      Ambiente  = "dev"
      CreadoCon = "terraform"
    }
  }
}
