# Quickstarts infrastructure Ansible collection

The `rhpds.quickstarts.saw_prepare` workload bootstraps the dedicated workshop
Vault, configures its Kubernetes authentication, seeds the ingress CA and SSH
key, and mirrors the digest-pinned SAW golden image into the cluster registry.
AgnosticV invokes it after creating the infrastructure Application.

Enablement follows `saw_enabled` or, when absent, the effective bootstrap Helm
value `saw.enabled`. See `automation/gitops/tenant/saw/README.md` for credential
storage, recovery, externally managed Vault, and existing-cluster rerun steps.
