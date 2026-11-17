import { defineTool } from "@werkbank/framework";
import { z } from "zod";
import { api, paths, useApi, type Assets } from "../data/api";
import { CommandLine, EmptyState, PanelBody, Section, StatusPill, Swatches } from "../kit";
import { prefs } from "../prefs";

/**
 * Designs, templates and the plugins that render them. Read-only: a design or a template is
 * made with files and the command line, not in a form here.
 */

const stateSchema = z.object({});
type State = z.infer<typeof stateSchema>;

function AssetsPanel() {
  const entry = useApi<Assets>(paths.assets, prefs.every.system);
  const a = entry.data;
  if (!a) return <EmptyState>{entry.error ?? "Loading…"}</EmptyState>;
  const kinds = new Set(a.renderers.map((r) => r.kind));
  return (
    <PanelBody
      head={
        <div className="wb-toolhead">
          <strong>Assets</strong>
          <span>
            {a.designs.length} designs, {a.templates.length} templates, {a.renderers.length} formats
          </span>
        </div>
      }
    >
      <Section title="Designs" count={a.designs.length}>
        <table className="wb-table sb-table">
          <thead>
            <tr>
              <th>Design</th>
              <th>Colours</th>
              <th>From</th>
            </tr>
          </thead>
          <tbody>
            {a.designs.map((d) => (
              <tr key={d.id} title={d.folder ?? "built into Sourcebound"}>
                <td className="sb-wrap">
                  <strong>{d.name}</strong> <code>{d.id}</code>
                  {d.error && <div className="wb-warn">{d.error}</div>}
                </td>
                <td>
                  <Swatches colors={d.colors} />
                </td>
                <td>{d.origin}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="wb-hint">A design is one file of colours, fonts and logo that every format reads. An organisation keeps its own in a pack outside the checkout.</p>
        <CommandLine command={'sb design new ID --name "Organisation"'} note="a design to edit" />
        <CommandLine command="sb pack install FOLDER" note="designs and templates from a pack" />
      </Section>

      <Section title="Templates" count={a.templates.length}>
        <table className="wb-table sb-table">
          <thead>
            <tr>
              <th>Template</th>
              <th>Format</th>
              <th>Design</th>
              <th>For</th>
              <th>From</th>
            </tr>
          </thead>
          <tbody>
            {a.templates.map((t) => (
              <tr key={t.id} title={t.folder}>
                <td className="sb-wrap">
                  <code>{t.id}</code> {t.title}
                  {t.error && <div className="wb-warn">{t.error}</div>}
                </td>
                <td>
                  <StatusPill tone={kinds.has(t.kind) ? undefined : "warn"} title={kinds.has(t.kind) ? undefined : "No installed plugin renders this format"}>
                    {t.kind}
                    {kinds.has(t.kind) ? "" : " (no renderer)"}
                  </StatusPill>
                </td>
                <td>{t.design || "–"}</td>
                <td>{t.for?.join(", ") || "any"}</td>
                <td>{t.origin}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <CommandLine command="sb template new ID --kind KIND --design ID" note="a starting template written by the format's plugin" />
        <CommandLine command="sb template add FOLDER" note="register a template folder" />
        <CommandLine command="sb render TARGET --template ID" note="a piece or deliverables/<name>" />
      </Section>

      <Section title="Formats" count={a.renderers.length}>
        <table className="wb-table sb-table">
          <tbody>
            {a.renderers.map((r) => (
              <tr key={r.kind}>
                <td>
                  <code>{r.kind}</code>
                </td>
                <td className="sb-wrap">{r.title}</td>
                <td>{r.outputs.join(" ")}</td>
                <td>{r.plugin === "sourcebound" ? "built in" : `plugin ${r.plugin}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {a.plugins.filter((p) => p.error).map((p) => (
          <p key={p.name} className="wb-warn">
            Plugin {p.name} did not load: {p.error}
          </p>
        ))}
        <p className="wb-hint">Further formats (Word, slides and posts) are plugins: separate packages, installed only where they are wanted.</p>
        <CommandLine command="sb plugin list" />
      </Section>
      <p className="wb-hint">Registry: {a.registry}</p>
    </PanelBody>
  );
}

export const assetsTool = defineTool<State>({
  id: "assets",
  title: "Assets",
  glyph: "◈",
  category: "System",
  version: 1,
  stateSchema,
  defaultState: () => ({}),
  component: AssetsPanel,
  describe: () => {
    const a = api.peek<Assets>(paths.assets);
    if (!a) return { loaded: false };
    return {
      note: "Designs and templates are registered from the command line (sb design, sb template, sb pack); a piece is rendered with piece.render.",
      registry: a.registry,
      designs: a.designs.map(({ id, name, origin, colors }) => ({ id, name, origin, colors })),
      templates: a.templates.map(({ id, kind, title, design, origin, ...t }) => ({ id, kind, title, design, for: t.for, origin })),
      formats: a.renderers,
      plugins: a.plugins,
    };
  },
});
