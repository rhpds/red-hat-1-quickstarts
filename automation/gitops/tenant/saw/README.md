# Secure Agent Workspace GitOps integration

The charts in `charts/` and `image-builders/` are imported from the commit in
`source.json`. Refresh deliberately, then review the changes and image digests:

```sh
python3 automation/gitops/update-saw.py --ref <commit-or-tag>
```

The refresh clones upstream, copies the charts, preserves this integration's
chart paths and pins the reviewed default images. New image tags in a refreshed
revision need review. The VP Vault and External Secrets charts under
`automation/gitops/infra/saw/` are separately vendored as versions 0.1.11 and
0.0.4. Optional APF and image-build profiles have their own image and credential
requirements. The cluster must provide a published credential-proxy image.

## Cluster bootstrap

Set these Helm values in the agnosticv cluster's
`ocp4_workload_gitops_bootstrap_helm_values` (replace the example references
with deployer variables):

```yaml
saw:
  enabled: true
  clusterDomain: cluster.example.com # no apps. prefix
  keycloak:
    postgresPassword: "{{ common_password }}"
  inferenceSeed:
    enabled: true
    vaultPath: hub/inference
    secretData:
      provider: custom-inference
      api_key: "{{ saw_inference_api_key }}"
      url: "{{ saw_inference_url }}"
      model: "{{ saw_inference_model }}"
  governance:
    customInference:
      host: model.example.com # exact host from the URL
      port: 443
```

The cluster bootstrap creates the External Secrets, OpenShift Virtualization,
and RHBK subscriptions, and applications for Vault, External Secrets,
HyperConverged, Keycloak, and governance. It assumes these operators and
namespaces are not already managed by another installation. The cluster needs
virtualization-capable nodes and persistent storage. Other OpenShift AI and
GitOps installation remains the responsibility of agnosticv.

Agnosticv installs `rhpds.quickstarts` from this repository's
`automation/gitops/infra/ansible` and runs `rhpds.quickstarts.saw_prepare`
after starting the infrastructure bootstrap. The same repository revision must
contain both the collection and charts; set `saw_ansible_revision` when testing
a different revision. SAW remains disabled until `saw_enabled` is true.

The role generates an Ed25519 SSH key in memory and writes it to the Vault KV v2
path `secret/data/hub/ssh` only if no key exists. It preserves existing keys,
uses a create-only Vault write to handle concurrent provisioning, and fails if
the existing key is incomplete. The upstream ExternalSecrets copy the public
key **and private key** into workspace Kubernetes Secrets; restrict access to
workspace namespaces accordingly.

The role also mirrors `saw_golden_image_source` by digest into the internal
registry in `openshell-agents`. It verifies TLS and preserves and checks the
digest; a matching existing image is reused. The OpenShift registry did not
accept the source's signatures, so the mirror omits them; verify source
signatures before approving a new digest. The default source is the pinned
upstream gateway image. When changing the source, pass the same value to both
cluster and tenant deployments: the tenant derives its registry URL from that
digest. For a private source, create a Docker config Secret in
`openshell-agents` and set `saw_mirror_source_secret` to its name. The role
uses a dedicated service account with image-builder and nonroot permissions.
It does not create or build the separate credential-proxy image.

**Vault initialization is not automated by these charts.** Initialize and
unseal Vault, configure KV v2 at `secret/`, configure Kubernetes authentication
at `hub` with role `hub-role` for the External Secrets service account, and
load the SSH keys, ingress CA, and any Keycloak user passwords described by the
upstream pattern. Provision `saw-vault-writer` in the `vault` namespace with a
`token` key containing a Vault token scoped to read and create/update
`secret/data/hub/ssh`, and, when inference seeding is enabled, to write the
configured inference path. Alternatively supply `saw_vault_writer_token` via
agnosticv's secret mechanism; the role creates that Kubernetes Secret without
logging the value. The optional seed Job uses the same token to write the
inference Secret to Vault. The role does not initialize or unseal Vault,
configure Vault auth, or create users. Those steps must be completed before
the workspace can become ready.

`secretData` is rendered as a Kubernetes Secret, but its contents are also
present in the Argo CD Application's Helm values. Restrict access to that
Application. To avoid passing the key in GitOps values, omit `secretData` and
create a Secret named by `sourceSecret` in `vault` with `api_key` and optional
`provider`, `model`, and `url` keys. The loader runs during a sync; after
rotating the source Secret, resync the bootstrap to reload Vault. Values in
agnosticv must be supplied through its secret mechanism, never committed.

The existing tenant workload creates `litellm_virtual_key` per tenant, not
in the cluster workload. A shared key may be supplied to the cluster as above;
per-tenant keys must be written to separate Vault paths by tenant provisioning.
The lb2142 agnosticv configuration selects the `data-science` profile and
defaults its inference provider to `nvidia`. That profile uses NVIDIA's native
`https://integrate.api.nvidia.com/v1` endpoint and needs an NVIDIA API key;
its model comes from `saw_inference_model`. The `saw_inference_url` value does
not change the native NVIDIA endpoint. The `saw_inference_provider` override
must match the selected profile's provider.
For an OpenAI-compatible LiteLLM endpoint, use the upstream `custom-inference`
profile and configure the exact allowed endpoint host under governance. The
endpoint and model must match the user's inference Secret. Keyed external URLs
are limited by the upstream provider to HTTPS on port 443.

## Tenant bootstrap

Add a `saw` entry to the tenant bootstrap values. User names must begin with a
letter, be DNS labels, and be at most 19 characters; using `user-<guid>` also
works when a GUID begins with a digit.

```yaml
saw:
  userName: user-7kzmd
  clusterDomain: cluster.example.com
  inferenceHost: model.example.com
  credentialProxyImage: registry.example.com/credential-proxy@sha256:<64-hex-digest>
  vmSource:
    registryURL: docker://image-registry.openshift-image-registry.svc:5000/openshell-agents/openshell-gateway@sha256:<64-hex-digest>
  values:
    defaults:
      profiles: [custom-inference]
```

The inference host is added to the VM's egress allowlist; it must match the
governance host and the URL loaded into Vault. Agnosticv normally derives the
registry URL from `saw_golden_image_source`; an existing `vmSource.dataSource`
can be used instead. The generated `saw-users-<tenant>` application creates the user's
namespace and separate Secret, BOM, and VM applications, all referencing this
repository and the same revision. Pre-create the named Keycloak account; the
owner resolver binds the workspace to its subject. By default, removing a
user does not delete their VM or namespace. This integration does not install
the optional RHDH self-service portal or its pipelines.
