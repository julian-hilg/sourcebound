import { defineTool, useWerkbank } from "@werkbank/framework";
import { z } from "zod";
import { api, paths, useApi, type SystemReport } from "../data/api";
import { CommandLine, EmptyState, KeyValue, PanelBody, Section, StatTiles, StatusPill, bytes } from "../kit";
import { prefs } from "../prefs";
import { num } from "./lib";

/**
 * What is installed and configured on this machine (`sb doctor --json`). The app shows what
 * is missing and the command that fixes it; it does not run installers.
 */

const stateSchema = z.object({});
type State = z.infer<typeof stateSchema>;

function System() {
  const wb = useWerkbank();
  const entry = useApi<SystemReport>(paths.system, prefs.every.system);
  const s = entry.data;
  if (!s) return <EmptyState>{entry.error ?? "Reading the system…"}</EmptyState>;
  const errors = s.problems.filter((p) => p.level === "error");
  const todo = s.setup.filter((x) => !x.done);
  const stored = s.storage.reduce((sum, x) => sum + (x.bytes ?? 0), 0);
  const open = (toolId: string) => void wb.run("panel.open", { toolId });
  return (
    <PanelBody
      head={
        <div className="wb-toolhead">
          <strong>System</strong>
          <span>
            Sourcebound {s.sourcebound.version} · Python {s.sourcebound.python} · {s.sourcebound.platform}
          </span>
          <span className="kit-grow" />
          <StatusPill tone={errors.length ? "bad" : s.problems.length || todo.length ? "warn" : "good"}>
            {errors.length ? `${errors.length} errors` : s.problems.length + todo.length ? `${s.problems.length + todo.length} things to look at` : "everything in place"}
          </StatusPill>
        </div>
      }
    >
      {s.problems.map((p) => (
        <p key={p.text} className="sb-notice" data-tone={p.level === "error" ? "bad" : "warn"}>
          {p.level === "error" ? "Error" : "Warning"}: {p.text}
          {p.fix && (
            <>
              {" "}
              Fix: <code>{p.fix}</code>
            </>
          )}
        </p>
      ))}
      <StatTiles
        tiles={[
          { label: "Lake tables", value: s.lake.error ? "?" : num(s.lake.tables), hint: s.lake.error ?? `snapshot ${s.lake.snapshot ?? "–"}`, tone: s.lake.error ? "bad" : undefined, onClick: () => open("lake") },
          { label: "Data sources", value: num(s.registry.datasources), hint: `${num(s.registry.contracts)} contracts`, onClick: () => open("connections") },
          { label: "Jobs", value: num(s.registry.jobs), hint: s.registry.jobs_due ? `${s.registry.jobs_due} due` : "none due", tone: s.registry.jobs_due ? "warn" : undefined, onClick: () => open("jobs") },
          { label: "Formats", value: num(s.renderers.length), hint: `${s.plugins.length} plugins`, onClick: () => open("assets") },
          { label: "Designs, templates", value: `${num(s.registry.designs)}, ${num(s.registry.templates)}`, hint: "in the registry", onClick: () => open("assets") },
          { label: "Stored", value: bytes(stored, prefs.locale), hint: "data root" },
        ]}
      />
      <div className="sb-pad">
        <Section title="Setup" count={`${s.setup.filter((x) => x.done).length} of ${s.setup.length}`}>
          <table className="wb-table sb-table">
            <tbody>
              {s.setup.map((x) => (
                <tr key={x.id}>
                  <td>
                    <StatusPill tone={x.done ? "good" : "warn"}>{x.done ? "done" : "to do"}</StatusPill>
                  </td>
                  <td className="sb-wrap">
                    {x.title.replace(/`/g, "")} <span className="wb-dim">{x.detail}</span>
                  </td>
                  <td>{!x.done && <CommandLine command={x.fix} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="wb-hint">The app shows the command; you run it in a terminal.</p>
        </Section>

        <Section title="Configuration">
          <KeyValue
            items={[
              { label: "Configuration file", value: `${s.configuration.file} (${s.configuration.from})` },
              { label: "Checkout", value: s.sourcebound.checkout ?? "not an editable install" },
              { label: "Data root", value: `${s.configuration.data_root} (from ${String(s.configuration.data_root_from)})` },
              { label: "Registry", value: s.configuration.registry },
              { label: "Projects folder", value: s.configuration.projects_dir ?? "not set: projects are found in the hub folder and around the folder sb ui started in" },
              { label: "Catalog", value: s.lake.catalog },
              { label: "Fetcher", value: `${String(s.configuration.user_agent)}; one request per host every ${String(s.configuration.seconds_between_requests)} s (+ up to ${String(s.configuration.jitter_seconds)} s); robots.txt ${s.configuration.respect_robots ? "respected" : "NOT respected"}` },
              { label: "Paper converter", value: (s.configuration.converter as string | null) ?? "none (optional)" },
              { label: "Agent activity log", value: s.activity_log },
              { label: "Python", value: s.sourcebound.executable },
            ]}
          />
        </Section>

        <Section title="Storage" count={bytes(stored, prefs.locale)}>
          <table className="wb-table sb-table">
            <thead>
              <tr>
                <th>What</th>
                <th>Files</th>
                <th>Size</th>
                <th>Folder</th>
              </tr>
            </thead>
            <tbody>
              {s.storage.map((x) => (
                <tr key={x.id}>
                  <td>{x.id}</td>
                  <td className="wb-num">{x.exists ? num(x.files) : "–"}</td>
                  <td className="wb-num">{x.exists ? bytes(x.bytes, prefs.locale) : "not there"}</td>
                  <td className="sb-wrap sb-url">{x.path}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>

        <Section title="Programs" count={`${s.tools.filter((t) => t.installed).length} of ${s.tools.length}`}>
          <table className="wb-table sb-table">
            <thead>
              <tr>
                <th>Program</th>
                <th>State</th>
                <th>Needed for</th>
              </tr>
            </thead>
            <tbody>
              {s.tools.map((t) => (
                <tr key={t.id} title={t.path}>
                  <td>{t.title}</td>
                  <td>
                    <StatusPill tone={t.installed ? "good" : undefined}>{t.installed ? t.version || "installed" : "not installed"}</StatusPill>
                  </td>
                  <td className="sb-wrap">
                    {t.purpose}
                    {!t.installed && <span className="wb-dim"> · get it: {t.get}</span>}
                  </td>
                </tr>
              ))}
              <tr>
                <td>Zotero</td>
                <td>
                  <StatusPill tone={s.zotero.running ? "good" : undefined}>{s.zotero.running ? "running" : "not running"}</StatusPill>
                </td>
                <td className="sb-wrap">
                  Citation keys and the bibliography <span className="wb-dim">· {s.zotero.url}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </Section>

        <Section title="Optional Python packages">
          <table className="wb-table sb-table">
            <tbody>
              {s.modules.map((m) => (
                <tr key={m.id}>
                  <td>
                    <code>{m.id}</code>
                  </td>
                  <td>
                    <StatusPill tone={m.installed ? "good" : undefined}>{m.installed ? "installed" : "not installed"}</StatusPill>
                  </td>
                  <td className="sb-wrap">
                    {m.purpose}
                    {!m.installed && <span className="wb-dim"> · {m.install}</span>}
                  </td>
                </tr>
              ))}
              {Object.entries(s.sourcebound.packages).map(([name, version]) => (
                <tr key={name}>
                  <td>
                    <code>{name}</code>
                  </td>
                  <td>{version ?? <StatusPill tone="bad">missing</StatusPill>}</td>
                  <td className="wb-dim">part of Sourcebound</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>

        <Section title="Plugins and formats" count={s.plugins.length}>
          {s.plugins.length === 0 && <p className="wb-hint">No plugin installed. Word, slides and posts are plugins in the checkout's plugins/ folder: <code>uv pip install -e plugins/&lt;name&gt;</code></p>}
          {s.plugins.map((p) => (
            <p key={p.name} className={p.error ? "wb-warn" : undefined}>
              <strong>{p.name}</strong> {p.version} {p.error ? `did not load: ${p.error}` : `renders ${p.renderers.join(", ") || "nothing"}; commands: ${p.commands.map((c) => `sb ${c}`).join(", ") || "none"}`}
            </p>
          ))}
          <p>
            Formats that can be rendered now:{" "}
            {s.renderers.map((r) => (
              <span key={r.kind} className="wb-badge" title={`${r.title} (${r.plugin})`}>
                {r.kind}
              </span>
            ))}
          </p>
        </Section>
      </div>
    </PanelBody>
  );
}

export const systemTool = defineTool<State>({
  id: "system",
  title: "System",
  glyph: "⚑",
  category: "System",
  version: 1,
  stateSchema,
  defaultState: () => ({}),
  component: System,
  describe: () => {
    const s = api.peek<SystemReport>(paths.system);
    if (!s) return { loaded: false };
    return {
      note: "What is installed and configured. The app does not install anything: `fix` is the command the person runs in a terminal.",
      sourcebound: s.sourcebound, configuration: s.configuration, lake: s.lake, storage: s.storage, registry: s.registry,
      problems: s.problems, setup: s.setup,
      programs: s.tools.map(({ id, installed, version, purpose }) => ({ id, installed, version, purpose })),
      zotero: s.zotero, latex: s.latex, optional_packages: s.modules, plugins: s.plugins, formats: s.renderers,
    };
  },
});
