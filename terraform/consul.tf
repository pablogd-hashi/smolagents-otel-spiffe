# Consul Connect intentions and CA configuration.
#
# Default deny is set with a wildcard "deny *" intention, then specific allow
# intentions name each permitted edge. The dashboards' "allowed vs denied"
# panel relies on this — without explicit denies, every connection is allowed
# and the panel shows nothing interesting.

# Default deny: every edge that isn't explicitly allowed is denied.
resource "consul_config_entry" "default_deny" {
  kind = "service-intentions"
  name = "*"

  config_json = jsonencode({
    Sources = [
      {
        Name   = "*"
        Action = "deny"
      }
    ]
  })
}

# Planner -> Executor is the core agent edge.
resource "consul_config_entry" "planner_to_executor" {
  kind = "service-intentions"
  name = "executor-agent"

  config_json = jsonencode({
    Sources = [
      {
        Name   = "planner-agent"
        Action = "allow"
      }
    ]
  })
}

# Both agents need to reach the OTel Collector for traces/metrics/logs.
resource "consul_config_entry" "agents_to_otel" {
  kind = "service-intentions"
  name = "otel-collector"

  config_json = jsonencode({
    Sources = [
      { Name = "planner-agent",  Action = "allow" },
      { Name = "executor-agent", Action = "allow" }
    ]
  })
}

# Mesh-wide proxy defaults: enable transparent proxying so the agent code can
# treat upstream sidecars as plain localhost ports.
resource "consul_config_entry" "proxy_defaults" {
  kind = "proxy-defaults"
  name = "global"

  config_json = jsonencode({
    Config = {
      protocol = "http"
      envoy_prometheus_bind_addr = "0.0.0.0:19000"
    }
    MeshGateway = { Mode = "local" }
  })
}
