# Terraform glue between Vault PKI (the upstream CA) and Consul Connect (the
# downstream consumer). The prior repo `pablogd-hashi/agentic-ai-spiffe-demo`
# does the production-grade SPIFFE workload-identity wiring; this file is the
# minimal version sufficient for the demo dashboards.

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    vault = {
      source  = "hashicorp/vault"
      version = "~> 4.0"
    }
    consul = {
      source  = "hashicorp/consul"
      version = "~> 2.20"
    }
  }
}

provider "vault" {
  address = var.vault_address
  token   = var.vault_token
}

provider "consul" {
  address = var.consul_address
  scheme  = "http"
}
