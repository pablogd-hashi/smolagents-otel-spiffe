#!/usr/bin/env bash
# Wait for Vault dev mode to be ready, then enable the KV engine and seed
# any non-Terraform-managed setup. The PKI engines themselves are created by
# `terraform apply` (terraform/vault.tf).

set -euo pipefail

VAULT_ADDR="${VAULT_ADDR:-http://localhost:8200}"
VAULT_TOKEN="${VAULT_DEV_ROOT_TOKEN_ID:-root}"

echo "Waiting for Vault at $VAULT_ADDR ..."
for _ in $(seq 1 30); do
  if curl -fs "$VAULT_ADDR/v1/sys/health?standbyok=true" > /dev/null; then
    echo "Vault is up."
    break
  fi
  sleep 1
done

export VAULT_ADDR VAULT_TOKEN

# Health check
curl -fsS -H "X-Vault-Token: $VAULT_TOKEN" "$VAULT_ADDR/v1/sys/mounts" \
  > /dev/null || { echo "Vault not reachable with token"; exit 1; }

echo "Vault ready. Run 'task vault:pki' to apply PKI Terraform."
