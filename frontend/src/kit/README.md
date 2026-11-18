# Kit: display elements that do not know this app

Components written for the Sourcebound frontend that any Werkbank app could use. They are
candidates for the framework: nothing in this folder imports from the app (`../data`,
`../tools`) or from a path inside `@werkbank/framework`.

Rules they follow:

- **Props only.** No stores, no fetches, no settings read inside. The app passes data, locale
  and callbacks. A component that needs a menu or a command takes a callback and the app
  wires it to `openContextMenu` or `wb.run`.
- **Tokens only.** Colours come from `--wb-*`; classes are `kit-*` in `kit.css`, building on
  the framework's `wb-*` classes where one exists (`wb-kpis`, `wb-button`, `wb-empty`, `wb-dim`).
  The one exception is data that *is* a colour (`Swatches`), which arrives as a value.
- **Narrow first.** Everything reads in a 300 px panel; `SplitPane` stacks when the panel is
  narrow.
- **Words carry the meaning.** A tone repeats what a word already says; it is never the only cue.

| Component | What it is | Use it for |
| --- | --- | --- |
| `DataGrid` | virtualised grid over rows-as-arrays: sticky header, numeric columns flush right, click-to-sort, a row/cell menu hook | query results, table previews, anything with columns not known in advance |
| `SplitPane` | list and detail in one panel; side by side when wide, stacked when narrow | master/detail inside one panel |
| `PanelBody` | fixed head, scrolling body | the frame of a panel |
| `KeyValue` | label/value pairs in two columns | properties of one selected thing |
| `StatTiles` | headline numbers on the framework's `wb-kpis` | the top of a dashboard |
| `StatusPill`, `StatusDot` | a state as a word (or a dot beside a name) in a tone | status columns, list marks |
| `Section` | heading with count and controls inside a scrolling panel | grouping on a dashboard |
| `EmptyState` | one sentence and at most one action | a panel with nothing to show |
| `CommandLine` | a terminal command with a copy button | telling the person what to run instead of running it |
| `CodeBlock` | wrapped output with optional copy | command output, logs |
| `CopyButton` | copies and confirms | anywhere |
| `ConfirmButton` | a button that asks once more in place ("Really? Yes / No") | actions with an effect outside the app |
| `Agenda` | dated items day by day, empty days included, preferred weekdays marked | publishing schedule, job runs, deadlines |
| `PostPreview` | a feed card: author line, text clamped with "…more", image or page carousel, character count | checking a post before it is published elsewhere |
| `SlideGrid` | rendered slides, large and numbered with their titles; one selectable | talking about single slides ("slide 3 …") with a person or an agent |
| `Swatches` | colours of a palette | showing a design |
| `format.ts` | `bytes`, `number`, `toCsv`, `copy` | — |

What would have to change to move one into the framework: rename `kit-` to `wb-`, move its
block of `kit.css` into the theme sheet, and export it from the package entry. `DataGrid`
would then replace the hand-rolled grids of the starter (`tools/grid.tsx`, the SQL console's
result table).
