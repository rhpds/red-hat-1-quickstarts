> **Maintainers:** This template is managed via submodule from
> [rhdp-publishing-house](https://github.com/rhpds/rhdp-publishing-house).
> Do not make changes directly to this repo — all changes should come from
> the Publishing House dev repo.

# [Project Name]

<!-- Replace with your project name and brief description. -->

## Getting Started

1. Install the RHDP Publishing House skills plugin in Claude Code
2. Run `/rhdp-publishing-house` in this directory to start intake
3. Follow the orchestrator's guidance

## Structure

- `content/` — Showroom AsciiDoc content (Antora modules)
- `automation/` — Automation code (Ansible roles, Helm charts)
- `runtime-automation/` — Zero-Touch runtime automation (removed for classic Showroom projects)
- `setup-automation/` — Zero-Touch setup automation (removed for classic Showroom projects)
- `publishing-house/` — Project state (manifest), specs, reviews, decisions
- `site.yml` — Antora playbook (Showroom build config)
- `ui-config.yml` — Showroom UI layout config
