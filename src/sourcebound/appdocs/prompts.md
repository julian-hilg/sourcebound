---
title: Prompts
order: 1
---

# Prompts: what to tell the agent

You work with a coding agent (Claude Code in a terminal, or the *Assistant* panel of this app).
It follows Sourcebound's playbooks: **research-study** for a study, **content-desk** for a desk.
Write in any language; the examples below are ready to copy. Words in angle brackets are yours.
Each prompt names Sourcebound, so an agent in any folder knows which tool and which playbook to
use; in a project's folder, or here in the app, the context is clear anyway.

## Start a project

A **study** answers one question: brief, hypotheses frozen before the analysis, a paper at the end.

```prompt
Use Sourcebound (research-study playbook) to set up a new study on <topic>: <the question in one sentence>. Language: German. Create it with sb new in my projects folder and ask me what you need for the project card.
```

A **desk** follows a topic and produces pieces (posts, notes, briefings) along the way.

```prompt
Use Sourcebound (content-desk playbook) to set up a new desk for LinkedIn posts on <topic>: German, channel linkedin. Create it with sb new --kind desk in my projects folder and ask me what you need for the project card.
```

The agent runs `sb new <slug> --kind study|desk`, asks for what it cannot know (title, language,
channels, audience) and fills in the project card. **You decide**: the data root and the projects
folder (`sb init`), approving the brief (G1), the hypotheses before the freeze (G2), and
publishing (G3). The agent never does these for you.

## Work in a study

```prompt
In Sourcebound, continue the study <slug>: run sb status, tell me where we stand and what the next step is.
```

```prompt
In the Sourcebound study <slug>, draft the brief (research/brief.md) and show it to me before anything else.
```

```prompt
In the Sourcebound study <slug>, write the paper sections from the recorded results, then run sb check and the verifier.
```

## Make a post from a file

```prompt
Use Sourcebound to make a LinkedIn post about <path to the file> in my LinkedIn desk: register the file with sb doc, cite the original sources it rests on, render it and open it in the web view.
```

The agent registers the file as a source (`sb doc`), writes the text and the slides, checks and
renders them, and opens this app on the post (*Post studio*: the slides large, the assistant
beside them).

## Change a post

Select a slide in *Slides* and say what to change, to the Assistant here or in the terminal:

```prompt
Sourcebound post <id>, slide 3: a shorter title, and the bars sorted by size. Render it again.
```

```prompt
Sourcebound post <id>: make the first line of the text shorter, under 140 characters.
```

```prompt
Render the Sourcebound post <id> as PowerPoint as well (sb template list shows the pptx template).
```

Every change is rendered again and appears here by itself. Approving, scheduling and posting
stay yours: nothing in Sourcebound posts anywhere.

## Figures

```prompt
In the Sourcebound project <slug>, make a figure of <what> from the recorded results with sb figure, in the project's design, sized for the report.
```

The agent writes `figures/<name>.yaml` and runs `sb figure render`. A figure from a PDF:

```prompt
In Sourcebound, cut the chart on page 4 of source W-0007 out with sb figure crop and use it as the image on slide 2 of post <id>.
```

## Save and export

```prompt
Save the Sourcebound post <id> to the standard folder with sb piece export.
```

This is *Save as…* under *Text*, *Output*: post text, carousel PDF, slide images and a
PowerPoint render, in a folder named after the posting day.
