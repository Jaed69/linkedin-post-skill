# lipost: LinkedIn post workflow skill

Objective: a Claude Code skill plus a stdlib-only Python CLI that takes the user from raw photos and an experience to a published LinkedIn post, publishing through Publora behind a swappable publisher port.
Branch: feat/lipost · Delivery: ask-on-risk · Test runner: `python3 -m unittest discover -s tests`

## Specs

- S1 End-to-end automation. The user asked to automate "todo, desde ayudarme a seleccionar las fotos, hacerme el post y lo más importante, publicarlo por mí" (L1, L2). The skill guides: material intake, photo selection, interview, voice-based draft, preview, publish.
- S2 Publishing goes through Publora first: "Usemos el que va por Publora" (L2). Flow per Publora docs: create draft (no `scheduledTime`) → `POST /get-upload-url` per image → `PUT` file to `uploadUrl` → `PUT /update-post/:postGroupId` with `publishNow: true`. Base URL `https://api.publora.com/api/v1`, header `x-publora-key`. LinkedIn limits: 3,000 characters, up to 10 images, JPEG/PNG.
- S3 Swappable publisher: the user may later "crear un propio acceso" (L2). The CLI depends on a publisher port; Publora is one adapter; an official LinkedIn API adapter must be addable without changing commands.
- S4 Human approval gate enforced outside the model:
  - `draft` prints a preview and a confirmation token derived from the text, the image bytes and the draft id.
  - `publish <draftId> --confirm <token>` re-reads the draft from Publora and refuses (non-zero exit, nothing published) when the token does not match the local manifest or the server text differs from it.
  - Claude Code settings require a human prompt for `lipost publish`.
- S5 Photo privacy: `photos` writes copies auto-oriented with all metadata stripped (GPS removed), reports which originals had GPS, never modifies originals. `blur` writes a separate copy with a polygon region blurred, never overwriting its input.
- S6 Credentials: API key and LinkedIn platform id are read from env vars `PUBLORA_API_KEY` / `LIPOST_PLATFORM_ID` or `~/.config/lipost/env`; the CLI refuses an env file readable by group/others, and never prints the key.
- S7 Writing rules carried from the session test (assumption: derived from what worked on 2026-11-05): Spanish, the user's own voice, never invent facts, placeholders for missing data, one closing ask, check facts against source documents.
- S8 Commands documented in `--help` and README.

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S2 S3 S4 S5 S6 S8 | delegated (context backstop) | pending | |
| T2 | S1 S7 | inline | pending | |
| T3 | S4 | inline (settings via update-config) | pending | |
| T4 | S2 | inline, needs user's Publora key | blocked on user | |

## Log

- L1 (2026-11-05, user): "YA esta, lo psublqieue, , peor not enemso creo una skill, ya dema sproyectos quepuden hacer esto pro mi, tood, desde ayduarme a selecioanr la fotos hacerm el pront y lo mas improtalte, puclibadlo por mi"
- L2 (2026-11-05, user): "Usemos el que va por publra, no sabes si podemos subir y escalar a mas, si funcioan lo de linkeidn, podemos crear un propio acceso, sup agente, o hasta repositorio, no se lo que sea mas facil, para automoatizat todo este proceso"
- L3: Publora is built by Creative Content Crafts, Inc., the same company behind sergebulaev/linkedin-skills (docs.publora.com README). User informed and chose Publora anyway. API keys never expire, so file permissions matter.
- L4: Route: T1 delegated under the long-session backstop; the parent context is long after the repo review and post drafting.
