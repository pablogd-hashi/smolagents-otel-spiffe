service {
  name = "executor-agent"
  id   = "executor-agent-1"
  port = 8000
  tags = ["agent", "smolagents", "executor"]

  meta = {
    framework = "smolagents"
    role      = "executor"
  }

  check {
    id       = "executor-http"
    name     = "Executor /health"
    http     = "http://executor:8000/health"
    method   = "GET"
    interval = "10s"
    timeout  = "2s"
  }

  connect {
    sidecar_service {
      proxy {
        upstreams = [
          {
            destination_name = "otel-collector"
            local_bind_port  = 9002
          }
        ]
      }
    }
  }
}
