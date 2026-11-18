---
title: Prompts
order: 1
---

# Prompts: what to tell the agent

You work with a coding agent (Claude Code in a terminal, or the *Assistant* panel of this app).
It follows Sourcebound's playbooks: **research-study** for a study, **content-desk** for a desk.
Write in any language; the examples below are ready to copy. Words in angle brackets are yours.

## Start a project

A **study** answers one question: brief, hypotheses frozen before the analysis, a paper at the end.

```prompt
Set up a new study on <topic>: <the question in one sentence>. Language: German.
```

A **desk** follows a topic and produces pieces (posts, notes, briefings) along the way.

```prompt
Set up a desk for LinkedIn posts on <topic>, in German, channel linkedin.
```

The agent runs `sb new <slug> --kind study|desk`, asks for what it cannot know (title, language,
channels, audience) and fills in the project card. **You decide**: the data root and the projects
folder (`sb init`), approving the brief (G1), the hypotheses before the freeze (G2), and
publishing (G3). The agent never does these for you.

## Work in a study

```prompt
Continue the study <slug>: where do we stand, and what is the next step?
```

```prompt
Draft the brief for <slug> and show it to me before anything else.
```

```prompt
Write the paper sections from the recorded results, then run sb check and the verifier.
```

## Make a post from a file

```prompt
Make a LinkedIn post about <path to the file>. Cite the original sources, not the file's author.
```

The agent registers the file as a source (`sb doc`), writes the text and the slides, checks and
renders them, and opens this app on the post (*Post studio*: the slides large, the assistant
beside them).

## Change a post

Select a slide in *Slides* and say what to change, here or in the terminal:

```prompt
Slide 3: a shorter title, and the bars sorted by size.
```

```prompt
Make the first line of the text shorter: under 140 characters.
```

```prompt
Render the post again as PowerPoint as well.
```

Every change is rendered again and appears here by itself. Approving, scheduling and posting
stay yours: nothing in Sourcebound posts anywhere.

## Figures

```prompt
Make a figure of <what> from the recorded results, in the project's design, for the report.
```

The agent writes `figures/<name>.yaml` and runs `sb figure render`. A figure from a PDF:

```prompt
Take the chart on page 4 of W-0007 as a figure for slide 2.
```

## Save and export

```prompt
Save the post <id> to the standard folder.
```

This is *Save as…* under *Text*, *Output*: post text, carousel PDF, slide images and a
PowerPoint render, in a folder named after the posting day.
