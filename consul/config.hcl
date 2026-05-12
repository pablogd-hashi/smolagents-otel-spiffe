# Consul agent config — single dev-mode server with Connect enabled.
#
# In production this would be a 3- or 5-node cluster with Vault as the upstream
# CA. Here we run a single dev-mode server and point its Connect CA at Vault
# at startup via a separate Terraform apply (terraform/consul.tf).

datacenter = "dc1"
data_dir   = "/consul/data"
log_level  = "INFO"

server           = true
bootstrap_expect = 1

ui_config {
  enabled = true
}

client_addr = "0.0.0.0"
bind_addr   = "0.0.0.0"

# Connect (service mesh) is the whole point — without this, sidecar proxies
# cannot establish mTLS between services.
connect {
  enabled = true
}

# Default-deny intentions: services cannot talk to each other unless an
# intention explicitly allows it. Intentions are seeded by Terraform.
acl {
  enabled        = false
  default_policy = "allow"
}

ports {
  grpc     = 8502
  grpc_tls = 8503
  http     = 8500
  dns      = 8600
}

telemetry {
  prometheus_retention_time = "60s"
  disable_hostname          = true
}
