terraform {
  required_version = ">= 1.9, < 2.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.73"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }
}

# validate and mocked tests do not configure this provider against AWS.
# No backend is configured until the team agrees on state ownership.
provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.aws_account_id]
  default_tags {
    tags = {
      Project     = "digital-library"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

locals {
  name  = "digital-library-${var.environment}"
  zones = { for index, zone in var.availability_zones : zone => index }
}
