# sourcebound-word

Word documents for Sourcebound. A piece or a deliverable is rendered into a `.docx` template.
The file keeps its link to the research after a person edited it: numbers can be refreshed,
edits can be listed, and the edited text can be taken back as Markdown.

This is a plugin. Sourcebound works without it.

```sh
uv pip install -e plugins/word --python .venv/bin/python     # in the Sourcebound checkout
sb plugin list                                               # word ... renders: docx; commands: word
```

It needs `python-docx`, which the install brings. Word itself is not needed to render.

## The idea

The text stays where it is: `pieces/<id>/text.md` or the sections of a deliverable. Word is
an output. Three things make the output more than a printout.

1. **Numbers and citations are content controls.** A recorded number `{{result:key}}` becomes a
   plain-text content control with the tag `sb:result:key`. A citation `[@W-0001, p. 3]` becomes
   one with the tag `sb:cite:W-0001|p. 3`. In Word they look like normal text (switch on
   *Developer > Design Mode* to see them). The source list at the end is generated inside one
   block control, `sb:sources`.
2. **The file describes itself.** It carries a manifest as a custom XML part: project, target,
   template, the value every number had, and a fingerprint and the Markdown of every block.
   Renaming, moving or mailing the file does not lose it.
3. **Three commands read that.** `sb word status` lists what a person changed and which numbers
   are out of date. `sb word refresh` updates numbers and the source list and touches nothing
   else. `sb word pull` writes the edited text back as Markdown.

A file a person edited is never overwritten. The next `sb render` writes
`<name>.rendered.docx` next to it and says so.

## Setting up a corporate template (the office walkthrough)

Start from a document or template of the organisation: `.docx`, `.dotx` or `.dotm`.

```sh
sb word inspect "Corporate Report.dotx"
```

This lists the styles of the file and proposes which style plays which role. Styles the
organisation made itself are preferred over Word's built-in ones, and other candidates are shown:

```
proposed mapping (template.yaml, `styles:`):
  title           Cover Title      (or: Title)
  body            Firm Body      (or: Body Text, Normal)
  bullet          Firm Bullet      (or: List Bullet)
  table           Firm Table Standard      (or: Firm Table Compact)
  ...
content marker {{content}}: not in the file: the text is appended at the end.
```

Prepare the file once, in Word:

1. Save a copy. Delete the sample text, keep cover page, header and footer.
2. Type `{{content}}` on a line of its own where the text should start.
3. Optional: type `{{title}}`, `{{subtitle}}`, `{{author}}`, `{{date}}` where the cover shows them.
   Each must be typed in one go, so that Word does not split it into pieces with different formatting.

Register it:

```sh
sb word adopt "Corporate Report.dotx" --id firm-report --design firm --title "Firm report"
```

The file is copied unchanged into `<registry>/templates/firm-report/` with a `template.yaml`
that holds the proposed mapping. Open that file and correct the mapping where the proposal is
wrong. The roles:

| Role | Used for | If left empty |
| --- | --- | --- |
| `title`, `subtitle` | the title line, when the file has no `{{title}}` | no title line is added |
| `heading1` to `heading3` | headings | bold body text |
| `body` | paragraphs | the file's default style |
| `bullet` | bulleted lists | a bullet and a tab are typed |
| `numbered` | numbered lists (each list restarts at 1) | numbers are typed |
| `quote`, `code` | block quotes, code blocks | indented text; a style `SB Code` is added |
| `caption` | captions of figures and tables | body text |
| `figure_caption`, `table_caption`, `table_note`, `table_text` | finer roles | fall back to `caption` |
| `table` | the table style | a style `SB Table` is added (rules above, below and under the header) |
| `source` | entries of the source list | a style `SB Source` is added |

Other keys of `template.yaml`:

```yaml
content_marker: "{{content}}"     # empty: append the text at the end
sources: {style: numbered, heading: ""}   # numbered: [1] | author-year: (Author 2024); heading: default "Sources" / "Quellen"
title_from_text: true             # a first heading that repeats the title is not printed twice
figure_width_cm: 14               # optional; default is the text width
```

`sb render` refuses to render when a mapped style is not in the file, and names it.

To carry the template to another machine, export a pack and install it there:

```sh
sb pack export firm-pack --design firm --template firm-report
sb pack install firm-pack
```

No corporate file yet? `sb template new report --kind docx --design firm` writes a standard
template built from the design: fonts, colours, heading styles, table style, the logo in the
header, page numbers.

## Rendering

```sh
sb render 20261116-my-piece --template firm-report       # a piece
sb render deliverables/paper --template firm-report      # a deliverable (through the handover)
```

What becomes what:

| In the text | In Word |
| --- | --- |
| `# Heading`, paragraphs, `**bold**`, `*italic*`, `` `code` ``, links | the mapped styles; real hyperlinks |
| `- item`, `1. item` (two levels) | list styles; every numbered list starts at 1 |
| `> quote`, fenced code | quote and code style |
| `{{table:name}}` with `: caption {#label}`, pipe tables | a table over the text width, numeric columns flush right, caption above with a `SEQ` field |
| `![caption](figures/x.png){#label}` | the picture at text width, caption below. A PDF figure is converted with `pdftoppm` if it is installed. |
| `{{ref:label}}` | "Table 2", "Figure 1", or the section's title |
| `{{result:key}}`, `[@key]` | content controls (see above) |

A 13,000-word text (about twenty pages) renders in 0.4 seconds on a laptop.

## After a person edited the file

```sh
sb word status  report.docx      # changes nothing
sb word refresh report.docx      # numbers and source list
sb word pull    report.docx      # the text back as Markdown
```

Run them inside the project, or pass `--project FOLDER`. `--json` prints the report as data.

**status** compares the file with what was rendered:

```
report.docx: rendered 2026-11-16T21:02:21+00:00 from pieces/p1 (template report)
paragraphs: 14 unchanged, 1 changed, 0 added, 0 deleted, 0 moved
changed (1):
   First reason with code
      -> A clearer first reason with code
numbers out of date (sb word refresh updates them) (1):
   move.share: shows 20%, recorded 23%
```

It also reports controls that were typed over, controls that were removed, results that are no
longer recorded and sources that are no longer registered.

**refresh** updates what is out of date and reports each change:

```
number: move.share: 20% -> 23%
citation: W-0002: [2] -> [1]
source list: 2 entries -> 1 entries
```

The rules:

- A number control the person left alone follows the recorded result.
- A control the person **typed over** is theirs. It keeps its text and is reported as
  `kept as typed`. To link it again, type the old value back or render anew.
- A control the person **deleted** is gone. `status` names it.
- Citations are renumbered when one was removed or moved, and the source list is regenerated.
- A source list the person edited by hand is kept. `--sources` regenerates it.
- Nothing else in the file is touched. If nothing is out of date the file is not written.

**pull** writes `<name>.from-word.md` next to the source (`pieces/<id>/` or
`deliverables/<name>/`), in the handover notation. Blocks nobody touched come back exactly as
they were written. Edited blocks are converted from the file, with controls turned back into
`{{result:key}}` and `[@key]`. The source text itself is never written: compare, then take over
what you want. For a piece the command prints a diff against `text.md`.

## PDF

```sh
sb word pdf report.docx                 # report.pdf next to it
sb word pdf report.docx --engine libreoffice --out out/report.pdf
```

On Windows, Microsoft Word converts (hidden; tables of contents and other fields are refreshed
first, which Word does not do by itself when a program drives it). Elsewhere, or with
`--engine libreoffice`, LibreOffice converts; its line breaks can differ from Word's. A Word that
does not answer within three minutes is stopped; an instance the person has open is never
touched.

Fonts installed only as OpenType with PostScript outlines (`.otf`) cannot be embedded by Word: it
draws their text as shapes. The PDF looks right, but that text cannot be searched, selected or
read aloud. The command names such fonts. Installing a TrueType (`.ttf`) version of the font, where
the licence allows it, gives searchable text.

The plugin also registers this as the `.docx -> .pdf` converter that `sb deliver --pdf` uses.

## Limits

- **Tested with Word for Mac only, and only through scripting.** Files rendered here were
  opened, edited and saved by Word for Mac, then checked with `status`, `refresh` and `pull`;
  controls and manifest survived. Word for Windows, Word Online, Google Docs and LibreOffice
  were not tried. Editors other than Word may drop content controls or the custom XML part;
  then `status` says the file carries no manifest.
- **Layout was not checked by eye in Word.** The structure was checked through python-docx and
  a system preview. Look at the first render of a new template and adjust styles in the template.
- **Macros** of a `.dotm` are left out. A rendered file is a plain `.docx`, which cannot hold
  macros. The template file in the registry is not changed.
- **Mathematics** stays text: `$...$` is set in Cambria Math as written, not as a Word equation.
  The manifest counts these (`notes.mathematics_as_text`).
- **Footnotes** (`^[...]`) are not converted and stay as written.
- **Tracked changes** are read as if all were accepted. Rejecting them later changes the text
  again. `status` and `pull` say when a file has tracked changes.
- **Section references** print the section's title, not a number: heading numbers belong to the
  template's styles, and Word computes them.
- **Tables** are compared as a whole. One changed cell makes the table "changed", and `pull`
  then writes it as a pipe table instead of `{{table:name}}`.
- **Pictures a person pasted in** are not pulled; `pull` names them.
- **Fonts** are named, not embedded. A machine without the design's font shows Word's substitute.
- Word turns a one-line source list into a control inside its paragraph when something is typed
  next to it. This case is handled; other restructurings of controls by Word may exist.
- A content control's tag holds 64 characters. Longer keys get a short stand-in tag, and the
  manifest holds what it stands for.

## Tests

```sh
.venv/bin/pytest plugins/word/tests -q
```

Fourteen tests: rendering, the standard template, `.dotx` and `.dotm`, each edit case
(changed, added, deleted, moved, typed over, control removed, tracked changes), refresh, pull,
long keys, a deliverable with sections, figure and appendix, and the render time.
