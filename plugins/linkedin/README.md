# sourcebound-linkedin

A Sourcebound plugin. It turns a piece (`pieces/<id>/` with `text.md` and `slides.yaml`) into
slides: one PNG per slide and one carousel PDF, in a registered corporate design. It checks the
layout before it makes an image, and it prepares what a LinkedIn post needs. It does not post.

```sh
uv pip install -e plugins/linkedin --python .venv/bin/python     # in the Sourcebound checkout
sb plugin list                                                   # linkedin: renders slides; command linkedin
```

It needs Jinja2 (installed with it) and any Chromium on the machine: Chrome, Edge, Chromium or
the browser Playwright installed. Nothing is downloaded. `SB_CHROMIUM` names a browser
explicitly. Without a browser only the HTML page is written, unchecked, and the plugin says so.

## Commands

| Command | Does |
| --- | --- |
| `sb template new ID --kind slides [--design ID]` | writes the standard slides template into the registry, to adapt |
| `sb render PIECE --template ID [--design ID]` | HTML, PNG per slide, carousel PDF (two slides or more), `layout.json`, `preview.json` in `pieces/<id>/render/<template>/` |
| `sb linkedin check PIECE` | text length, first line, hashtags, slide count, deck structure, sources, stale renders |
| `sb linkedin bundle PIECE [--template ID] [--out FOLDER]` | a folder to post by hand: `post.txt`, the PNGs, the PDF, `alt-texts.txt`, `README.txt` with the steps (in the deck's language, de or en) |

Posting is manual. Sourcebound holds no LinkedIn credentials, and publishing is the person's
decision (`sb piece set ID --status published --url ...` records it afterwards). An API
publisher would be one more function in `post.py`, called only from a command the person runs.

## The deck: `slides.yaml`

```yaml
deck:
  title: Fat tails in daily EUR/USD returns     # also the tracker line above every title
  lang: de                               # de | en: decimal comma, "Quelle:" / "Source:"
  prefix: tails                             # file names: tails_slide_1.png, tails_carousel.pdf
  width: 1080                            # default from the template (1080 x 1350); 1080 x 1080 and
  height: 1350                           # 1920 x 1080 work too
slides:
  - layout: cover                        # optional first slide
    eyebrow: Market note
    title: ...
    sub: ...
    note: November 2026
  - title: The one statement this slide makes      # at most three lines
    blocks: [...]                                  # see below
    source: "[@W-0008]; @W-0007"                   # required next to an exhibit; `source: false` for own material
    note: optional remark above the source line
```

Text anywhere may hold `{{result:key}}` (a recorded number) and source keys from
`evidence/sources.yaml` or the bibliography. In a `source:` line `[@W-0008]` becomes
"Publisher, Title" and a bare `@W-0008` the publisher alone; elsewhere `[@W-0008]` becomes
"(Publisher year)". A numeric field (`value`, `max`, `pos`, ...) may be a single
`{{result:key}}`: then the recorded value is used.

Spaces that must not break a line are set as non-breaking spaces when the text is filled in:
after "§", "§§", "Art.", "Abs." and "Nr." ("§ 34h"), between a number and its unit ("1.800 €",
"44 %", "5 Mrd. €") and after a currency code before a number ("EUR 20"). Type ordinary spaces.

A deck of one slide is a single-image post: no page counter, no carousel PDF.

Every block takes `name` and `unit` (the exhibit heading), `grow: true` and `push: true` (move
to the bottom). A grown block takes the free height of the slide, and its chart is spread over
it: bar and table rows, the gap between rows and the thickness of bars, the height of columns
and lines, and the size of kpi numbers grow, each up to a limit (a row to 2.2 times its height,
a bar to 1.6 times its thickness). What the limits leave over stays around the chart and counts
as empty (see Checks).

| `type` | Fields |
| --- | --- |
| `kpis` | `items: [{n, t}]`: a number and what it is; up to three side by side (four on a wide slide), four in two rows of two, more in rows of three |
| `bars` | `groups: [{label, rows: [{label, value, text, hi}]}]` or `rows`; `max` (the scale's end), `label_width` |
| `columns` | `items: [{label, value, text, hi}]`, `max`, `height`; at most 12 |
| `line` | `x: [...]`, `series: [{label, values, hi, end_text}]` (null marks a gap), `min`, `max`, `refs: [{y, label}]`, `height`, `gutter`; at most 6 series |
| `gantt` | `ticks: [...]`, `rows: [{label, sub, start, span, ext, hi}]` in whole ticks, `label_width` |
| `day` (or `timeline`) | `events: [{pos, time, what, below, align, accent}]`, `pos` from 0 to 100 |
| `windows` | `months: [...]` (equal periods), `windows: [{label, start, width, dates}]` in percent of the axis |
| `table` | `columns: [...]`, `rows: [[...]]`, `highlight: [row numbers from 0]`, `key: false` for a plain first column |
| `bullets` | `items: [text, ...]` |
| `text` | `text` or `paragraphs` |
| `comments` | `items: [{head, text}]`: short notes under an exhibit, side by side |
| `callout` | `n`, `text` |
| `quote` | `text`, `by` |
| `sources` | `items: [{text, where}]`, or `items: auto` for every source the piece cites |

`hi: true` marks the one series the title is about. A design with `charts.highlight_one` draws
it in the primary colour and everything else in the neutral colour.

## Design and template

The template holds layout only. Every colour and font in its CSS is a variable the renderer
writes from the design (`sb design show ID`): `--c-primary`, `--c-accent`, `--c-ink`,
`--c-ink-soft`, `--c-ink-faint`, `--c-neutral`, `--c-surface`, `--c-paper`, hairlines derived
from them, `--p-1` to `--p-6`, `--f-body`, `--f-heading`, `--w-light`, `--w-regular`,
`--w-medium`, `--logo-h`. So one template works with any design.

Fonts: `fonts.files` lists font files in the design folder; they are embedded. `fonts.faces`
maps weights to files and to the names an installed font answers to
(`{file, weight, local: [...]}`). `fonts.weights` sets the three weights the slides use. A
typeface that is not on the machine falls back along the stack, and the render names it by the
name it is installed under and its weight: `missing fonts: Inter 400, Inter-Bold 700, Source Serif 4`
(every `@font-face` of the design and of the template counts).
`logo.file` is shown bottom right; without `logo.file_inverse` the cover shows the logo in the
paper colour.

## Checks

Before a browser starts (`sb render`, `sb linkedin check`): the deck's structure, required
fields, value ranges, results that were never recorded, sources that are not registered, an
exhibit without a source line, more than one highlighted series where the design allows one.

After the page is laid out, and before any image is made:

- the title runs to more than three lines;
- the content is too tall for the slide, or something is cut off at its edge;
- two labels of a chart overlap or are closer than `charts.min_gap_px`; a label lies on a bar or leaves its exhibit;
- text is smaller than `charts.min_font_px`, or wider than its box or column;
- a colour is in use that the design does not have.

Warnings, which do not stop the render (in the output and in `layout.json`):

- "slide n: about x % of the content area is empty": the space below the last block, inside a
  grown block and above a pushed one, from 25 % on (`empty_warn_pct` in `template.yaml` or
  `charts` of the design changes it). `layout.json` lists the share for every slide (`space`);
- fonts that are missing (see Fonts).

`sb render` prints corrections and warnings once each, as `note:` lines.

Corrections applied first, each listed in the output and in `layout.json`:

- bars: the label column is widened to fit the longest label (up to 45 % of the chart);
  a value that does not fit beside its bar is set inside it;
- timeline: a label that would collide is moved to the other side of the axis or turned;
- windows: a date label that would leave the chart is set to the left of its bar;
- line: end labels are moved apart; x-axis labels that would touch are thinned;
- a grown block: its chart is spread over the block's height (see above).

Anything else stops the render with the slide, the block and what to change. The page that was
measured is stored without its script and is the page that is photographed.

## `preview.json`

Written next to the images, for a frontend that shows the post without knowing this plugin:

```json
{"format": "sourcebound-preview", "version": 1, "channel": "linkedin", "title": "...", "lang": "de",
 "text": "the whole post", "characters": 2689, "limit": 3000,
 "visible": "what shows before 'more'", "more": true, "hashtags": ["#FX"],
 "width": 1080, "height": 1350,
 "slides": [{"file": "t1_slide_1.png", "title": "...", "alt": "..."}],
 "document": "t1_carousel.pdf", "remedies": [{"slide": 6, "block": "windows", "what": "..."}], "browser": "Google Chrome"}
```

`file` and `document` are null when no browser was found. File names are relative to the
folder of `preview.json`.

## Limits

- Layout was checked with Chrome on macOS only. Edge, Windows and Linux use the same command
  line but were not run.
- The cut before "more" (about 210 characters, 140 on a phone) and the 3,000-character limit
  are LinkedIn's behaviour as commonly reported, not an interface the plugin can query.
- Lines of a line chart are not treated as marks: a label can sit on a line. Axis values on
  the y-axis are limited to `refs`.
- Fonts are matched by family name and weight; a font installed under other names needs
  `fonts.faces`.
- No animation, no video, no speaker notes.

## Tests

```sh
.venv/bin/pytest plugins/linkedin/tests -q
```

Tests that lay out a page are skipped when no Chromium is found.
