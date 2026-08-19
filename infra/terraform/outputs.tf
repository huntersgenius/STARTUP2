output "database_endpoint" {
  value     = aws_db_instance.main.endpoint
  sensitive = true
}

output "database_secret_arn" {
  description = "Secrets Manager ARN holding the rotated master password."
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
  sensitive   = true
}

output "cache_endpoint" {
  value     = aws_elasticache_replication_group.main.primary_endpoint_address
  sensitive = true
}

output "backend_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "web_repository_url" {
  value = aws_ecr_repository.web.repository_url
}
