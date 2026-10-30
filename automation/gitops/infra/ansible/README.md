# Quickstarts infrastructure Ansible collection

The `rhpds.quickstarts.saw_prepare` workload prepares the SSH key in Vault and
mirrors the digest-pinned SAW golden image into the cluster registry. The
agnosticv workload invokes it after creating the infrastructure Application.
See `automation/gitops/tenant/saw/README.md` for configuration and prerequisites.
