variable "aws_region" {
  type        = string
  description = "Deployment region; only used during separately approved AWS work."
  default     = "ap-south-1"
}

variable "aws_account_id" {
  type        = string
  description = "Expected AWS account; prevents an approved plan from targeting another account."
  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "Use the intended 12-digit AWS account ID."
  }
}

variable "environment" {
  type        = string
  default     = "dev"
  description = "Short lowercase environment suffix for all resource names."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,15}$", var.environment))
    error_message = "Environment must start with a lowercase letter and contain at most 16 lowercase letters, digits, or hyphens."
  }
}

variable "availability_zones" {
  type        = list(string)
  description = "Exactly two AZs in the selected region; verify account availability before deployment."
  default     = ["ap-south-1a", "ap-south-1b"]
  validation {
    condition = length(var.availability_zones) == 2 && length(distinct(var.availability_zones)) == 2 && alltrue([
      for zone in var.availability_zones : startswith(zone, var.aws_region)
    ])
    error_message = "Supply two distinct availability zones in aws_region."
  }
}

variable "kubernetes_version" {
  type        = string
  description = "Explicit EKS version. Choose one in standard support at the AWS deployment review."
  validation {
    condition     = can(regex("^1[.][0-9]+$", var.kubernetes_version))
    error_message = "Use an explicit Kubernetes version such as 1.35; its availability must be reviewed before AWS work."
  }
}

variable "cluster_admin_principal_arn" {
  type        = string
  description = "Existing administrator IAM user or role ARN, not root or an STS session ARN."
  validation {
    condition     = can(regex("^arn:aws:iam::${var.aws_account_id}:(user|role)/.+$", var.cluster_admin_principal_arn))
    error_message = "Use an existing IAM user or role ARN in the intended AWS account; root and STS session ARNs are not EKS access-entry principals."
  }
}

variable "eks_public_access_cidrs" {
  type        = list(string)
  description = "Explicit administrator/CI public IPv4 CIDRs for EKS API access. No all-internet access."
  validation {
    condition = length(var.eks_public_access_cidrs) > 0 && alltrue([
      for cidr in var.eks_public_access_cidrs : can(cidrnetmask(cidr)) && try(tonumber(split("/", cidr)[1]) >= 24, false)
    ])
    error_message = "Supply explicit IPv4 CIDRs of /24 or narrower; use your administrator egress /32 where possible."
  }
}

variable "node_instance_type" {
  type        = string
  default     = "t3.small"
  description = "Small x86 development worker; validate capacity and pricing before deployment."
}

variable "db_instance_class" {
  type        = string
  default     = "db.t4g.micro"
  description = "Small development PostgreSQL instance, not a production sizing recommendation."
}

variable "cover_bucket_name" {
  type        = string
  description = "Globally unique, private cover bucket name."
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.cover_bucket_name))
    error_message = "Use 3-63 lowercase letters, numbers, and hyphens, starting/ending with a letter or number."
  }
}

variable "protect_data" {
  type        = bool
  default     = true
  description = "Deletion protection for RDS and DynamoDB. Changing this is a separately approved cloud mutation."
}

variable "ses_sender" {
  type        = string
  description = "Verified SES sender identity used by the notification Lambda."
  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.ses_sender))
    error_message = "Supply a verified email address for SES."
  }
}
