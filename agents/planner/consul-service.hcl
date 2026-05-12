service {
  name = "planner-agent"
  id   = "planner-agent-1"
  port = 8000
  tags = ["agent", "smolagents", "planner"]

  meta = {
    framework = "smolagents"
    role      = "planner"
  }

  check {
    id       = "planner-http"
    name     = "Planner /health"
    http     = "http://planner:8000/health"
    method   = "GET"
    interval = "10s"
    timeout  = "2s"
  }

  connect {
    sidecar_service {
      proxy {
        upstreams = [
          {
            destination_name   = "executor-agent"
            local_bind_port    = 9001
          },
          {
            destination_name   = "otel-collector"
            local_bind_port    = 9002
          }
        ]
      }
    }
  }
}
