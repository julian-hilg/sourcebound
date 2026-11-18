# sourcebound-pptx

A Sourcebound plugin. It turns a piece (`pieces/<id>/` with `text.md` and `slides.yaml`) into one
PowerPoint file in a template's master: one slide per deck slide, in a registered corporate
design. Titles, kpis, bullets, tables, comments, sources and source lines are PowerPoint text that
can be edited. Charts are images, drawn by `sourcebound.charts` in the design's chart style. The
layout is measured before anything is written; what does not fit stops the render.

```sh
uv pip install -e plugins/linkedin -e plugins/pptx --python .venv/bin/python   # in the Sourcebound checkout
sb plugin list                                       # pptx: renders pptx
```

It needs python-pptx and matplotlib (installed with it) and the slides plugin
(`sourcebound-linkedin`), whose deck format and checks it shares. It needs no browser and no
PowerPoint.

## Commands

| Command | Does |
| --- | --- |
| `sb template new ID --kind pptx [--design ID]` | writes a starting template into the registry: `template.yaml` and `master.pptx`, built from the design |
| `sb render PIECE --template ID [--design ID]` | `<prefix>.pptx`, `charts/<prefix>_s<n>_<k>.png` (the chart images), `layout.json` in `pieces/<id>/render/<template>/` |

The deck is the same `slides.yaml` as for the slides plugin, with the same blocks, results,
sources and non-breaking spaces (see `plugins/linkedin/README.md`). A deck renders in both kinds of
template without change.

## The template

A folder in the registry (or in a pack) with `template.yaml` and a master file:

```yaml
kind: pptx
design: firm
master: master.pptx           # the master: layouts and placeholders
width: 1080                   # px of a slide; must have the master's proportions
height: 1350                  # 1 px = 0.75 pt on a master 28.575 cm wide
scale: 3                      # chart image pixels per px
layouts:
  cover:
    name: Cover               # the layout's name in the master
    placeholders: {eyebrow: Eyebrow, title: Title, sub: Subtitle, note: Note}
    stack: [title, sub]       # set from the bottom of the subtitle's box upwards
  content:
    name: Content
    placeholders: {tracker: Tracker, title: Title, body: Body, page: Page, meta: Source}
panel: true                   # exhibits on a panel in charts.panel (or colors.surface)
numbering: {figure: {de: "Abb. ", en: "Figure "}, table: {de: "Tabelle ", en: "Table "}, separator: " – "}
tracker: {prefix: "/", prefix_font: bold, prefix_color: accent}
page: {separator: " / ", separator_color: accent, digits: 2}
styles:                       # text roles; only what differs from the defaults
  caption: {color: caption}
spacing: {block_gap: 40}
```

The master holds the look: backgrounds, pictures, rules, fixed text such as an address. The
renderer fills placeholders by role and adds text boxes, shapes, tables and pictures in the body
area. Placeholders a slide does not use are removed, so no prompt text is left.

| Role | Layout | Filled with |
| --- | --- | --- |
| `title` | both | the slide's title; on a content slide the box shrinks to the title's lines and the body follows it |
| `tracker`, `page` | content | `deck.tracker`; the page number ("02 / 08", not on a one-slide deck) |
| `body` | content | not filled: its width and bottom are the body area |
| `meta` | content | the note and source line of a slide without an exhibit (else below its last block) |
| `eyebrow`, `sub`, `note` | cover | the cover's fields |

**Styles.** Every text the renderer writes has a role with a font role (`body`, `bold`, `serif`),
a size in px, a colour key of the design, a line height and letter spacing:
`tracker`, `title`, `eyebrow`, `cover_title`, `cover_sub`, `cover_note`, `caption`, `unit`,
`source`, `body`, `kpi_n`, `kpi_t`, `comment_head`, `comment`, `callout_n`, `callout`, `quote`,
`quote_by`, `table_head`, `table`, `table_key`, `source_no`, `source_item`, `source_where`, `page`,
and `chart` (the label size of chart images). The defaults follow the standard slides template.
Fonts come from the design: `body` is the first of `fonts.body`, `bold` the first of
`fonts.heading` when that is a face of its own (`Firm-Bold`; never a bold flag on it), else `body`
set bold, `serif` the first of `fonts.serif`. Every run names its font, size and colour, so the
master's own text styles do not change what was measured.

**Building a master.** A master is built by a script, not edited by hand.
`sourcebound_pptx.master` has the steps: open an organisation's master, keep two layouts, set
the theme's colours and fonts, replace other fonts, add pictures, rules and placeholders
formatted like the styles. `sb template new --kind pptx` uses it to build the neutral starting
master; a pack's build script uses it on the organisation's real master.

## Charts: the extension point

`sourcebound.charts.render(block, design=..., width_px=..., height_px=..., out=..., lang=...)` draws
one chart block (`bars`, `columns`, `line`, `gantt`, `day`/`timeline`, `windows`) as PNG or SVG.
`charts.check(block)` lists what is wrong with a block. The module knows nothing of decks or
PowerPoint; a Word renderer or a figure file can call it the same way.

The built-in renderer styles a chart from the design: colours, palette, fonts (font files of the
design are used first; `charts.fonts` lists files only for charts), `charts.highlight_one`,
`charts.gridlines`, `charts.panel`. A design may name another renderer:

```yaml
# design.yaml
charts: {renderer: firm}
```

A plugin provides it:

```python
def register(api):
    api.chart_renderer("firm", draw, types=("bars", "columns", "line"))

def draw(block, *, design, width_px, height_px, out, lang, text_px=None, scale=2.0):
    style = sourcebound.charts.style_of(design)        # or a Style of its own: fonts, colours, grid rules
    style.grid = True
    return sourcebound.charts.draw(block, design=design, width_px=width_px, height_px=height_px,
                                   out=out, lang=lang, text_px=text_px, scale=scale, style=style)
```

A renderer may draw everything itself or only change the `Style`. The design stays data: it
names a renderer and never holds code (a pack refuses `.py` files). When the named renderer is
not installed, the built-in one draws and the render says so. A block type the renderer does not
draw (`types`) stops the render before layout: "slide 4: gantt charts are not supported in pptx
yet by chart renderer `firm`".

## Checks

Before layout (`sb render`): the deck's structure, values, results and sources (the slides
plugin's checks), the master file, its layouts and the named placeholders, the slide size against
`width` and `height`, colours of the styles, and chart types the renderer does not draw.

During layout, before a file is written, each of these stops the render:

- a title longer than `limits.title_lines` (3) lines, a cover title longer than 4;
- a word wider than its box;
- the content of a slide taller than the body area, after charts have given up to 30 % of their height;
- a kpi number too wide for its column at 60 % of its size;
- a column of numbers wider than its table allows;
- cover title and subtitle taller than their space.

Notes, which do not stop it (in the output and in `layout.json`): charts made lower to fit, a
body area that is 25 % empty or more (`limits.empty_warn_pct`), fonts that are not on the machine
(text is then measured with a stand-in), fonts the master names that are not on the machine, and
a chart renderer that stood in for the one the design names.

## Limits

- Text is measured with the font files, not by PowerPoint. Line breaks are predicted at spaces
  and after hyphens, with 3 % to spare; PowerPoint may still break one word differently. A box
  has the height of its predicted lines and no autofit, so an extra line runs over the next item.
- Charts are pictures. Their numbers are in the picture's alternative text, not editable.
- Only two layouts (cover and content). No speaker notes, no animation, no transitions.
- A table is set with the master's "No Style, No Grid" style and drawn rules; it does not follow
  a table style of the master.
- Checked by exporting slides with PowerPoint for Windows (Microsoft 365) only.

## Tests

```sh
.venv/bin/pytest plugins/pptx/tests tests/test_charts.py -q
```
