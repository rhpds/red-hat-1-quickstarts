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
a different revision. The role follows `saw_enabled` when explicitly supplied;
otherwise it follows `ocp4_workload_gitops_bootstrap_helm_values.saw.enabled`.
When neither is present, it remains disabled. This keeps the role aligned with
AgnosticV's effective chart configuration without requiring a second catalog PR.

The virtualization chart enables `EnableVirtioFsConfigVolumes` through the
`kubevirt.kubevirt.io/jsonpatch` annotation on HyperConverged. This appends to
HCO's generated feature gates and survives operator reconciliation. OpenShift
Virtualization 4.20 does not expose this gate in the HCO spec; the annotation is
an unsupported HCO override and can trigger `UnsupportedHCOModification`.
It is required by the vendored SAW VM's config-volume mounts in this workshop.
Review/remove this override when upgrading to a version where the feature is GA.
See the [HCO configuration documentation](https://github.com/kubevirt/hyperconverged-cluster-operator/blob/main/docs/cluster-configuration.md).

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

### Managed workshop Vault

By default, `saw_prepare` bootstraps the dedicated single-node workshop Vault
before running SSH provisioning. It initializes only an uninitialized Vault,
saves the initialization response in `vault/saw-vault-bootstrap` under
`init.json`, unseals it, enables KV v2 at `secret/`, and configures Kubernetes
auth at `hub` with role `hub-role`. That role grants the External Secrets service
account read access to `secret/data/hub/*`. Vault uses its rotating pod service
account token for Kubernetes TokenReview. External Secrets connects to the
internal Vault service with the injected OpenShift service CA.

The bootstrap also writes the public ingress CA at `hub/cluster-ingress-ca`
and creates `vault/saw-vault-writer` with a token scoped to read/write
`secret/data/hub/*`. The writer has a 32-day requested TTL, subject to Vault's
configured maximum; rerunning preparation replaces an expired token. Existing
valid writer tokens, SSH keys, provider credentials and unrelated Vault data
are preserved. Supply inference/web-search API keys through the existing seed
mechanism or your secret provisioning; bootstrap does not invent provider keys
or create Keycloak users.

This is workshop bootstrap, not production auto-unseal: the initial root token
and one unseal key are retained in the bootstrap Kubernetes Secret. Restrict
access to the `vault` namespace and back up this Secret together with the PVC.
The Job can only read/update the two named Secrets, and its RoleBinding is
removed after the run. Credentials are never passed in Job arguments or printed
in logs. The Job uses TLS verification for both APIs.

On a subsequent run, preparation reuses the saved credentials and unseals Vault
if needed. A Vault pod restart requires rerunning preparation; no continuous
unseal controller is installed. If Vault is already initialized but the bootstrap
Secret is missing, preparation stops rather than reinitializing or deleting
storage. An interruption between initialization and saving its response requires
operator recovery; never delete the PVC as an automatic retry. An initializer
lock with no saved response also fails closed for a different Job: inspect the
previous Job and Vault status before clearing the `saw.redhat.com/initializer`
annotation. Keep a single cluster provisioning run active at a time.

For an externally managed, already initialized Vault, set
`saw_prepare_vault_bootstrap: false` and supply the existing writer Secret or
`saw_vault_writer_token` through AgnosticV secrets. Providing that token disables
automatic bootstrap by default. In this mode, configure unsealing, KV v2,
Kubernetes auth, the ingress CA and policies yourself. Bootstrap is designed for
the default Vault/External Secrets chart names; keep role variables and chart
values aligned if overriding their names or service account identities.

### Existing clusters

Merging the PR updates the GitOps-managed HyperConverged and External Secrets
configuration after synchronization. It does **not** rerun AgnosticV's Ansible
workloads. For an already provisioned cluster, rerun
`rhpds.quickstarts.saw_prepare` with the updated collection and the same cluster
variables, then retry failed SAW Application syncs. New provisions use the updated
role automatically when the collection revision points at `main`.

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

For LB2142, the tenant bootstrap can seed the tenant's existing LiteLLM
virtual key into `hub/saw-<user>/inference`. Set `saw.inferenceHost` to the
LiteLLM HTTPS hostname and `saw.inferenceSeed.enabled` to true, with
`secretData.api_key`, `url` (ending in `/v1`) and `model`. Set the same host in
the cluster's `saw.governance.customInference.host`. The resulting workspace
uses the custom-inference profile, exposes its OpenClaw UI, and disables web
search rather than requiring a nonexistent Brave key. Each user has a separate
Vault path; the shared SSH and ingress CA paths remain unchanged.

Set `saw.account.enabled` and `saw.account.password` to create the matching
OpenShell Keycloak account. Use a stable, unique password satisfying the
OpenShell realm policy and provide it to that user through workshop user data.
For new LB2142 tenants the catalog uses the same 12-character workshop
password for the OpenShift console and OpenClaw. The LB2142 OpenShell realm
sets its password policy to `length(12)` for this purpose.
On retry, account provisioning verifies the existing password before assigning
the `openshell-user` and `openshell-admin` roles; it does not reset an existing
account. The admin role applies to any SAW gateway that trusts the shared realm;
this grants participants platform administrator access beyond their own workspace.
Vault seeding and account
creation use sync Jobs, so failures make provisioning fail instead of leaving an
unusable VM. The Jobs mount the Vault writer and Keycloak admin credentials only
in their respective namespaces. Both the inference key and account password are
in the tenant Argo Application's Helm values and Kubernetes Secrets: restrict
access to the Application, `vault`, and `saw-keycloak` namespaces.

The LB2142 catalog needs its companion cluster and tenant configuration changes
as well as this repository's chart changes. Existing tenants require a resync
after both changes are published; changing the catalog does not rerun a tenant's
provisioning automatically.

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

### Keycloak callback and owner resolution

The cluster bootstrap fixes Keycloak's frontend URL to its public HTTPS route.
Both automation clients attach the built-in `kc-admin-api` scope when the server
provides it. New Keycloak releases require this scope and its Admin API audience
in addition to the existing realm-management roles. Without it, the redirect
registrar and owner resolver receive HTTP 401: browser sign-in reports
`Invalid parameter: redirect_uri`, and sandbox setup cannot resolve its owner.
See the [Keycloak upgrade guidance](https://www.keycloak.org/docs/26.8.2/upgrading/#_admin_api_audience).
Older servers without the scope retain their existing behavior.

On an existing cluster, synchronize `saw-keycloak`; the script checksum restarts
both controllers and reruns their bootstrap. Confirm that the registrar reports
registered callbacks and that each tenant's `saw-owner-subject` ConfigMap has a
`subject`. Restart the guest's `saw-apply.service` after the owner resolves if it
is still retrying. A realm import does not update existing user accounts: create
the exact `saw.userName` in the `openshell` realm and assign `openshell-user`.
Use a password meeting that realm's policy, and complete the same profile fields
as the import template. The shared OpenShift workshop password may not satisfy
the OpenShell password policy.

`update-saw.py` reapplies the reviewed compatibility changes listed in
`saw-patches.json`. It fails when an upstream edit no longer matches the expected
patch location so the next vendor refresh cannot silently drop these fixes.
Local additions live under
`automation/gitops/tenant/saw-additions/`, outside the replaced vendor tree.
The refresh copies this directory as a unit and refuses to overwrite a different
upstream file at the same path. Edit the local source, then refresh its vendored copy.
Existing files
use the manifest's `old`/`new` patches.

To check the pinned refresh against a local upstream checkout:

```sh
SAW_UPSTREAM_SOURCE=/path/to/secure-agent-workspace python3 -m unittest \
  automation.gitops.tests.test_saw.SawRefreshTests
```


## Shared personal-assistant demo

The demo keeps each participant's existing SAW login and private inference
credential. All workspaces read the same synthetic Mailpit inbox, Mattermost
team and Radicale calendar. This is the shared source account discussed in
the workshop; do not connect personal accounts to these services.

Add to the **cluster** bootstrap values alongside the existing SAW settings:

```yaml
saw:
  demo:
    enabled: true
    calendarEnabled: true
    provisioningEnabled: true
    passwordSecret: saw-demo-password
```

Provision `vault/saw-demo-password` with a `password` key through AgnosticV's
secret mechanism before sync. For a manual lab setup, read the password from
a private file instead of putting it in command arguments or Git:

```sh
oc -n vault create secret generic saw-demo-password --from-file=password=/path/to/private/demo-password
```

The password must satisfy Mattermost's password policy. Keep it stable on
resync; setup verifies an existing account and never resets its password.
Provide username `saw-rh1` and this shared password in workshop access details.
Mailpit and Radicale use their upstream synthetic, credential-free configuration.
Their HTTPS routes reach the services directly; backend network policies allow
the ingress controller and the setup job. SMTP is not exposed to the assistant.

One infrastructure sync job, `vault/saw-demo-seed`, initializes the synthetic
administrator, creates the source account/team, populates and verifies all three
sources, and publishes only the non-admin Mattermost session to
`secret/data/hub/saw-demo/mattermost` in Vault. Administrator and session recovery
state stay in `vault/saw-demo-state`; neither is printed. A failed seed or Vault
write fails the job and can be retried. The upstream services use ephemeral
storage, so resync setup after a backend pod loses its data.

Add to the **tenant** bootstrap values:

```yaml
saw:
  demo:
    enabled: true
    provisioningEnabled: true
```

This selects the demo profile, attaches the three approved providers and routes,
and syncs the shared chat credential into the namespace credential proxy.
Inference stays at `hub/saw-<user>/inference`; no demo credential is written to
that private path. Source readers use the existing HarnessBundle contract with
one `governanceProfile` per service. The local notes server provides the fixed
report writer and an upload operation denied by the existing tool-action gate.
The demo skill prepares briefings on demand; it does not create a schedule.

For local seed-script development, use port-forwards and run
`automation/gitops/infra/bootstrap/files/seed-demo.py seed`, `verify`, `challenge`
or `reset`. Initial population needs `MATTERMOST_ADMIN_TOKEN` and
`SAW_DEMO_PASSWORD` in the operator environment. Retain its private state file;
subsequent actions can reuse the non-admin session. Reset removes only the
selected demo's generated records. The checked-in fixture set is
`infra/bootstrap/files/demo-data.json` relative to `automation/gitops/`.

For an installation of the previous per-tenant demo branch, resync the cluster
and tenant Applications. Shared setup adopts the existing administrator from
`openshell-agents/saw-demo-admin` before creating its recovery state; keep that
Secret until the shared setup succeeds. Because pruning is disabled, explicitly remove the old
`saw-demo-mailpit-access` and `saw-demo-radicale-access` Deployments/Services,
`saw-demo-admin` Job/account/RBAC and the old `saw-<user>-demo-seed` jobs/RBAC after
confirming the shared setup succeeded and routes target the direct services.
Retire their unused input/state Secrets only after any needed recovery data is
saved. Resync child service Applications too: a parent sync alone does not prove
the Routes changed. Existing sandbox tool settings managed by the older demo
are restored on installer apply; unrelated operator settings are preserved.
Keep per-tenant inference, SAW account and workspace resources.

Before presenting the module, verify the three live reads, a saved report and
a matching tool-denial audit event. A direct upload check verifies the gate;
it does not prove the malicious source message induced the action. The upstream
on-cluster demo also shows network and provider-admission denials; only claim
those layers when the corresponding executed operation and logs establish them.
