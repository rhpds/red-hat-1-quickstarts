# Container SAW Demo Hardening

## Current demo exception

The demo container stack may use broad egress while the container deployment
path is being validated:

    externalCIDRs:
      - 0.0.0.0/0
      - ::/0

This is intentional for the disposable demo cluster. It allows the container
gateway and bootstrap jobs to reach Kubernetes, DNS, Keycloak/OIDC, the
governance interceptor, the credential proxy, and the existing custom-inference
endpoint used by the VM deployment.

The container workspace must continue to use the existing VM inference
configuration:

- profile: \`custom-inference\`
- provider Secret: \`inference\`
- Secret keys: \`api_key\`, \`model\`, and \`url\`
- inference host: \`maas-rhdp.apps.maas.redhatworkshops.io\`

## Hardening backlog

Before using the container path outside the demo cluster:

- [ ] Qualify the deployment on the upstream-supported OpenShift 4.22 or later;
  this demo cluster runs 4.20.
- [ ] Replace the locally built preview governance image with a released,
  validated container-compatible image and review the new boundary.
- [ ] Investigate temporary administrator certificate propagation and repeated
  TLS handshake failures during reconciliation; verify reliable concurrent
  controller and relay sessions.
- [ ] Replace \`0.0.0.0/0\` and \`::/0\` with approved external CIDRs.
- [ ] Restrict gateway egress to the Kubernetes API and cluster DNS.
- [ ] Restrict Keycloak/OIDC traffic to the Keycloak route or service.
- [ ] Restrict governance traffic to the governance interceptor service.
- [ ] Restrict credential-proxy traffic to the per-workspace trusted namespace.
- [ ] Restrict inference traffic to the approved MaaS host and port.
- [ ] Use separate bootstrap and runtime egress policies.
- [ ] Pin every identity, proxy, gateway, policy, and audit chart to a reviewed
  full Git commit SHA.
- [ ] Pin every runtime, supervisor, gateway, proxy, and sandbox image by
  digest.
- [ ] Replace demo automatic-enrollment settings with a reviewed enrollment
  boundary, image, reference, and profile digest.
- [ ] Verify the container site's Keycloak subject binding before creating the
  Argo Application.
- [ ] Verify the \`custom-inference\` provider policy only exposes the required
  Secret key and host.
- [ ] Set a production storage class and retention policy for audit data.
- [ ] Review namespace, NetworkPolicy, AdminNetworkPolicy, and admission-policy
  behavior on a clean cluster.
- [ ] Add an automated test that renders the complete container site and rejects
  broad egress outside an explicitly enabled demo mode.
- [ ] Remove the demo waiver after the restricted policy passes an end-to-end
  RHDH create/delete test.

## Exit criteria

The demo waiver can be removed when a container workspace can be created and
deleted through RHDH using the \`custom-inference\` profile, with no broad
egress, all child Applications synced, and all expected user pods healthy.
