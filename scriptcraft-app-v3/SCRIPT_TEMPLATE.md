# ScriptCraft Manual Script Template

Copy this file as `<your-title>.md` and fill in the bracketed fields. The
delimiters below are exactly what the ScriptCraft parser looks for; do **not**
rename or remove any of the section headers (the lines marked **REQUIRED**).

The web GUI also accepts this template via the "Process Existing Script" tab.

---

## 1. How parsing works (read me first)

| What you want                       | What the parser keys on                         |
| ----------------------------------- | ----------------------------------------------- |
| Script title (used for filenames, curl titles, DaVinci project name) | The **first** `Title:` line at the top of the file. |
| Chapters (one curl pair per chapter) | Each `Heading: Chapter N - ...` line.           |
| Spoken dialogue (HeyGen content)    | Each `**Host:**` block.                         |
| FINAL HOOK (its own curl pair)      | The `**🎯 FINAL HOOK:**` block, terminated by `---`. |
| Visual cue (b-roll generator)       | Each `Visual Cue: ...` line.                    |
| Series wrap-up                      | A `Summary:` block in the final chapter.        |

**Do not put** `Visual Cue:`, `B-Roll:`, `Host:`, `Hook:`, `Summary:`, or
`Heading:` on the very first content line of the file — the title parser
explicitly skips those. Always start the file with `Title:`.

---

## 2. Template (copy from the line below to the end of file)

```
Title: [Your script title goes here — keep it short, this becomes the folder name]

Script Type: Video
Duration: medium
Audience: [beginners | intermediate | advanced]
Tone: [casual | professional | conversational]

**🎯 FINAL HOOK:**

**Host:**

[One paragraph, ~2–4 sentences, that grabs attention in the first 5 seconds.
You can wrap across multiple lines — the parser keeps everything up to the
first blank line as the hook.]

---

Heading: Chapter 1 - [Chapter title]

Visual Cue: [One sentence describing the on-screen visual. Avoid colons mid-line.]

**Host:**

[Spoken dialogue for chapter 1. Write naturally; the parser joins lines into
paragraphs at single newlines and splits paragraphs on blank lines.]

---

Heading: Chapter 2 - [Chapter title]

Visual Cue: [Visual description.]

**Host:**

[Spoken dialogue for chapter 2.]

---

Heading: Chapter 3 - [Chapter title]

Visual Cue: [Visual description.]

**Host:**

[Spoken dialogue for chapter 3.]

Summary: [2–3 sentences wrapping up the entire series. ONLY include this
section on the last chapter.]

---
```

## 3. Rules the parser depends on

1. **One `Title:` line at the very top.** Nothing else (no Visual Cue, no
   FINAL HOOK header) should appear before it.
2. **`**🎯 FINAL HOOK:**` is optional.** If present, place it directly under
   the front-matter block and terminate it with a `---` rule.
3. **Each chapter starts with `Heading: Chapter N - <title>`.** The number
   must be sequential (1, 2, 3, …).
4. **Each chapter has exactly one `**Host:**` block.** Multiple `Host:`
   labels in a single chapter will break the chapter→curl mapping.
5. **`Visual Cue:` lines are single-line.** Put them on their own line; do
   not split a cue across lines.
6. **`Summary:` only appears in the final chapter.**
7. **Use `---` (3+ hyphens on their own line) between every major block.**
   The parser uses `---` as a soft terminator throughout.
8. **No boilerplate intro paragraph.** Older scripts used to ship with a
   `Hi, I'm <Host>'s AI Digital Twin…` paragraph; that block is now stripped
   automatically at processing time, so do not add it manually.

## 4. Smallest valid example

```
Title: Top 5 AI Tools for Consumers

**🎯 FINAL HOOK:**

**Host:**

I used to think I needed every AI app. I was wrong — and the real fix is
picking the one tool that matches the task. Stick with me, because I'll show
you the five to start with.

---

Heading: Chapter 1 - The five tools

Visual Cue: Wide shot of a clean home office desk with a laptop showing five app icons.

**Host:**

Here are the five tools every beginner should start with…

Summary: Pick one tool per task, master it, then expand. That's the entire
strategy.

---
```

That file alone will produce:

- One folder named `Top_5_AI_Tools_for_Consumers`
- One DaVinci project with the same name
- HeyGen curls: `Top 5 AI Tools-hook`, `Top 5 AI Tools-hook-2`,
  `Top 5 AI Tools-Ch1p1`, `Top 5 AI Tools-Ch1p2`
- One b-roll search row for the Visual Cue
