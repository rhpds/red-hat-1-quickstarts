# SAW personal assistant demo

The [SAW demo charts](https://github.com/validatedpatterns-sandbox/secure-agent-workspace/tree/demo/demo/charts)
provide shared Mailpit, Mattermost and Radicale services. `source.json` records
the imported commit and local changes. Participant instructions are in
[`module-07-saw-personal-assistant.adoc`](../../../content/modules/ROOT/pages/module-07-saw-personal-assistant.adoc).

## Provisioning

Use the existing [SAW cluster and tenant setup](../tenant/saw/README.md), including
the tenant's Keycloak account, inference Secret and Vault writer. Add these
values to the **cluster** bootstrap:

```yaml
saw:
  demo:
    enabled: true
    calendarEnabled: true
    provisioningEnabled: true
```

Add these values to the **tenant** bootstrap:

```yaml
saw:
  demo:
    enabled: true
    provisioningEnabled: true
```

The infrastructure Job initializes the private Mattermost administrator. The
tenant Job verifies `saw.account.password` against Keycloak, creates a private
Mattermost team, populates all three sources, and writes provider credentials to
`hub/saw-<user>/{mailpit,mattermost,calendar}` in Vault. Session state remains in
the tenant's `vault/saw-<user>-demo-state` Secret. Credentials do not belong in Git,
logs or assistant prompts. The model stays in `saw.inferenceSeed.secretData.model`.

Participants use their assigned lab credentials for all source pages. Mailpit
and Radicale routes pass through a read-only gateway that restricts access to
the authenticated user's data. Mattermost uses its own authentication and a
private team. The workspace attaches all three providers and resolves its
assigned channel automatically.

Resync the tenant bootstrap to rerun its seed hook. Reseeding reuses a valid
session, repairs generated fixtures and preserves unrelated data. These demo
charts use ephemeral storage; after a backend pod loses its data, rerun the
infrastructure and tenant bootstrap hooks.

## File ownership and checks

- `charts/`: imported demo services, image pins and OpenShift route/account adjustments.
- `../infra/bootstrap/`: shared applications, source gateway and administrator Job.
- `../tenant/bootstrap/files/demo-data.json`: synthetic email, chat, calendar and injection content.
- `../tenant/bootstrap/files/seed-demo.py`: the population implementation used by the tenant Job and operator CLI.
- `../tenant/bootstrap/files/saw-demo-provision.py`: tenant identity, session state and Vault writes.
- `../saw-additions/`: canonical local plugin and BOM assets copied into the vendor tree by `../update-saw.py` through `../saw-patches.json`. Edit these source assets and their deployed copies together.
- `../tests/test_saw_demo*.py`, `../tests/test_saw_source_*.py` and `../tests/test_saw_source_readers.mjs`: fixture, provisioning, isolation, installer and tool-policy checks. The source-reader tests stay outside the vendored charts.

Run the focused checks from the repository root:

```sh
python3 -m unittest discover -s automation/gitops/tests -p 'test_saw_demo*.py'
python3 -m unittest discover -s automation/gitops/tests -p 'test_saw_source_*.py'
python3 -m unittest automation.gitops.tests.test_saw.SawRefreshTests
```

The source-reader Python tests also run the Node source-tool and tool-gate suites.
The HTTP tests need localhost socket access. An optional pinned-upstream refresh
check is documented in the SAW integration README. Operators using existing
port-forwards can inspect the standalone fixture CLI with
`python3 automation/gitops/tenant/bootstrap/files/seed-demo.py --help`; its actions are `seed`,
`verify`, `challenge` and `reset`. Keep the private state file outside the checkout.

## Scenario and live acceptance

The GTC Berlin scenario is adapted to synthetic services. The chat reproduces
the visible 14-message excerpt; email bodies are reconstructed from its summaries,
and calendar dates resolve relative to the saved seed date. Benchmark numbers are
fictional. The prepared chat injection asks for a full-summary upload to a fixed
`.invalid` destination through `saw_upload_summary`.

Only the three source readers and fixed-path report writer are allowed. An
actual upload tool call must be denied by the default-deny tool gate before HTTP
execution. A model refusal, printed pseudo-call or DNS error is not a runtime
policy-denial demonstration. Source-triggered denial still needs a real tool call
and matching audit evidence on the target cluster. Keep a direct upload diagnostic
separate, as described in Showroom; never weaken policy to force a demonstration.
