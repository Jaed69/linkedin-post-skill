---
name: lipost
description: Prepare and publish a LinkedIn post for the user end to end - pick and clean photos, interview, draft in the user's voice, preview, then publish through the lipost CLI with explicit approval. Use when the user wants to write, prepare or publish a LinkedIn post, or hands over photos or an experience (event, hackathon, project, course, job news) to turn into one.
---

# lipost: LinkedIn post from raw material to published

The user hands over photos and an experience; you return a published post they approved.
You draft and prepare. The user decides what goes out. Publishing is irreversible.

## Files

| Path | Holds |
|------|-------|
| `~/.config/lipost/voice.md` | The user's voice profile. Read before drafting; update it after each published post. |
| `~/.config/lipost/env` | `PUBLORA_API_KEY`, `LIPOST_PLATFORM_ID`. Mode 600. Never read, print or ask for the key; ask the user to write it themselves. |
| `~/lipost/<slug>/` | Working folder per post: cleaned photos, `post.txt`, sources. |

## Workflow

1. **Intake.** Ask for the photos folder, the experience in the user's own words, and any source documents (event brief, rubric, schedule, links). Read every document; facts come from them, never from you.
2. **Photos.**
   - `lipost photos <src> --out ~/lipost/<slug>/photos --sheet ~/lipost/<slug>/sheet.jpg`, then look at the sheet.
   - Suggest at most 4 photos with one line each: people and faces first, then the venue or brand, then the work.
   - Zoom into screens, badges, whiteboards and documents at full resolution. If anything private is readable (code, chats, other projects, emails), propose `lipost blur` on a separate copy and check the result visually.
   - Point out third parties who appear and remind the user to get consent from the people they tag.
3. **Interview.** Ask one question at a time and wait. Go for what makes the post: the concrete numbers, what the user believed before versus after, a moment that went wrong, what they learned, who to thank. Press a vague answer once. Record answers verbatim.
4. **Draft.**
   - Write in Spanish, in the voice from `voice.md`: the user's own phrases, energy and opinions, never their typos.
   - Line 1 is a concrete statement, number or the before/after belief, not a question.
   - Admit a loss or a limit early.
   - Give each idea its own short paragraph, and end with exactly one ask.
   - Use no hashtags or engagement bait unless the user asks for them.
5. **Check before showing.**
   - Every fact traces to the user or a document; nothing is invented.
   - Each thing the user said as an opinion stays theirs, and each thing the event said stays attributed to the event.
   - Missing data stays a visible `[placeholder]`.
   - Stay under 3,000 characters, and make the first 210 characters (the "see more" fold) carry the hook.
6. **Revise** with the user until they say it is final. Save it as `~/lipost/<slug>/post.txt` with real blank lines between paragraphs. Pasting into the LinkedIn editor drops blank lines; whether the API keeps them is not yet confirmed, so check the first published post and record the answer here.
7. **Draft remotely.** Run `lipost draft --text post.txt --image ...` in the order the user chose. Show the user the full preview it prints: text, images, character count and fold.
8. **Publish only on an explicit yes** to that exact preview, given in the user's own message after it. Then run `lipost publish <draft_id> --confirm <token>`. Claude Code asks the user to approve this command; never try to avoid that prompt. If anything changes after the preview, run `lipost delete` and draft again.
9. **After.** Run `lipost status <draft_id>` and report the outcome. Append to `voice.md` the phrases and structure the user kept or rejected.

## Hard rules

- Never publish without step 8. "Looks good" about an earlier version is not approval.
- Never pass the confirmation token around the user, and never publish by any other route: no Publora MCP server, no direct HTTP calls, no browser automation.
- Never invent facts, numbers, quotes, feelings, names or results.
- If `lipost` refuses (exit 2), report its message and stop. Do not work around it.
- Do not scrape LinkedIn or automate the browser.

## Commands

`lipost --help` and `lipost <command> --help` are the reference. Exit codes: 0 ok, 1 API or runtime failure, 2 refused or invalid input.

## Provenance

The interview method (one question at a time, no invention, before/after spine) is adapted from sergebulaev/linkedin-skills@8f8bc4b (MIT). Building the voice from the user's own samples and labelling it provisional comes from charlie947/social-media-skills@10ca79c (MIT).
