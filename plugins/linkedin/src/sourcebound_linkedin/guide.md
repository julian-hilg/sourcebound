# Slides: the content file `slides.yaml`

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
