# runtime-automation

This directory is intentionally present but currently holds no `module-*/` stages.

The Showroom runner (`zerotouch-automation`, the `runner` sidecar) requires
`runtime-automation/` to exist before it will start: it answers `/health` with
503 when the directory is missing, and the chart probes `/health` for liveness,
so an absent directory crash-loops the sidecar and the Showroom pod never
becomes Ready.

LB2142's learner-facing solve/validate flow is tracked separately; the
readiness and E2E automation for this lab lives in `../qa-automation/`.
