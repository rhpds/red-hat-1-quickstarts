
const fs = require("node:fs");
const path = "/sandbox/.openclaw/openclaw.json";
const cfg = fs.existsSync(path) ? JSON.parse(fs.readFileSync(path, "utf8")) : {};
// A provider token otherwise triggers OpenClaw's automatic npm channel repair
// before any CLI command, including the command that disables the channel.
cfg.channels ??= {};
cfg.channels.mattermost = { ...cfg.channels.mattermost, enabled: false };
cfg.plugins ??= {};
cfg.plugins.entries ??= {};
cfg.plugins.entries.mattermost = { ...cfg.plugins.entries.mattermost, enabled: false };
fs.mkdirSync("/sandbox/.openclaw", { recursive: true });
fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + "\n", { mode: 0o600 });
