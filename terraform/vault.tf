# Vault PKI engine — Consul Connect's upstream CA.
#
# This produces a root CA in Vault and configures a role Consul will use to
# request its intermediate signing certificate. The actual handoff (Consul
# pulling its CA bundle from Vault) happens in consul.tf.

resource "vault_mount" "pki_root" {
  path        = "pki_root"
  type        = "pki"
  description = "Smolagents demo root CA"

  default_lease_ttl_seconds = 60 * 60 * 24      # 1d
  max_lease_ttl_seconds     = 60 * 60 * 24 * 30 # 30d
}

resource "vault_pki_secret_backend_root_cert" "root" {
  backend     = vault_mount.pki_root.path
  type        = "internal"
  common_name = var.pki_common_name
  ttl         = "720h"
  format      = "pem"
}

resource "vault_pki_secret_backend_config_urls" "config" {
  backend                 = vault_mount.pki_root.path
  issuing_certificates    = ["${var.vault_address}/v1/pki_root/ca"]
  crl_distribution_points = ["${var.vault_address}/v1/pki_root/crl"]
}

# Intermediate mount that Consul Connect will use as its own signing CA.
resource "vault_mount" "pki_int" {
  path                      = "pki_int"
  type                      = "pki"
  description               = "Consul Connect intermediate"
  default_lease_ttl_seconds = 60 * 60 * 24
  max_lease_ttl_seconds     = 60 * 60 * 24 * 7
}

resource "vault_pki_secret_backend_intermediate_cert_request" "int_csr" {
  backend     = vault_mount.pki_int.path
  type        = "internal"
  common_name = "Consul Connect Intermediate"
}

resource "vault_pki_secret_backend_root_sign_intermediate" "int_signed" {
  backend     = vault_mount.pki_root.path
  csr         = vault_pki_secret_backend_intermediate_cert_request.int_csr.csr
  common_name = "Consul Connect Intermediate"
  ttl         = "720h"
  format      = "pem"
}

resource "vault_pki_secret_backend_intermediate_set_signed" "int_set" {
  backend     = vault_mount.pki_int.path
  certificate = vault_pki_secret_backend_root_sign_intermediate.int_signed.certificate
}

# Vault role Consul authenticates as when requesting Connect leaf signing.
# In production this would be bound to a service-account JWT; here we use a
# simple token for brevity.
resource "vault_policy" "consul_connect" {
  name = "consul-connect"

  policy = <<-EOT
    path "pki_int/*" {
      capabilities = ["create", "read", "update", "delete", "list", "sudo"]
    }
    path "sys/mounts/pki_int" {
      capabilities = ["read"]
    }
  EOT
}

resource "vault_token" "consul_connect" {
  policies = [vault_policy.consul_connect.name]
  ttl      = "720h"
  no_parent = true
}

output "consul_connect_token" {
  value     = vault_token.consul_connect.client_token
  sensitive = true
}
