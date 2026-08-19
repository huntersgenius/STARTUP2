variable "environment" {
  type        = string
  description = "staging or prod"
  validation {
    condition     = contains(["staging", "prod"], var.environment)
    error_message = "environment must be staging or prod."
  }
}

variable "region" {
  type        = string
  description = <<-EOT
    AWS region. ap-south-1 (Mumbai) is acceptable for staging against synthetic
    data. Production data residency is a legal decision — see docs/adr/0002 —
    and must not be settled by editing this default.
  EOT
  default     = "ap-south-1"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "cache_node_type" {
  type    = string
  default = "cache.t4g.micro"
}
