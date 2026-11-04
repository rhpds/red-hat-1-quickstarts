# Infrastructure bootstrap

This chart creates the cluster GitOps bootstrap marker and declaratively tunes
the OpenShift GitOps `ArgoCD` instance used by the quickstart Applications. The
cluster's agnosticv workloads install OpenShift AI and OpenShift GitOps. The
defaults in `values.yaml` align the repo-server Git command timeout with the
application-controller RPC timeout, and size the controller for the tenant
Applications it reconciles.

The tuning does not replace a reliable Git source: production clusters should
use an internal mirror when their egress path to GitHub is slow or unreliable.

SAW prerequisites are opt-in (`saw.enabled: true`); see [SAW integration](../../tenant/saw/README.md).
