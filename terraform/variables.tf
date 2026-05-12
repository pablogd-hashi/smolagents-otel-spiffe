variable "vault_address" {
  description = "Vault server address (dev mode default)."
  type        = string
  default     = "http://localhost:8200"
}

variable "vault_token" {
  description = "Vault root token. Dev-only — never set this in prod."
  type        = string
  default     = "root"
  sensitive   = true
}

variable "consul_address" {
  description = "Consul HTTP API address."
  type        = string
  default     = "localhost:8500"
}

variable "pki_common_name" {
  description = "CN for the root CA issued by Vault."
  type        = string
  default     = "smolagents.local"
}

variable "pki_ttl" {
  description = "Default issued certificate TTL."
  type        = string
  default     = "72h"
}
