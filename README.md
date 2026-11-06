# lipost

A stdlib-only Python CLI that prepares photos and publishes LinkedIn posts
with a human approval gate. Publishing goes through [Publora](https://docs.publora.com)
today, behind a publisher port so an official LinkedIn API adapter can be added later.

Requirements: Python 3.10+, ImageMagick 7 (`magick`) for `photos` and `blur`.
No third-party Python packages.

Run from the checkout with `bin/lipost`, or `python3 -m lipost`.

## Typical flow

```sh
lipost photos ~/Pictures/event --out ~/lipost/event --sheet ~/lipost/event-sheet.jpg
lipost blur ~/lipost/event/IMG_2.jpg ~/lipost/event/IMG_2-blur.jpg --polygon 120,80 400,80 400,300 120,300
lipost connections
lipost draft --text post.txt --image ~/lipost/event/IMG_1.jpg --image ~/lipost/event/IMG_2-blur.jpg
# review the preview, then:
lipost publish <draft_id> --confirm <token>
lipost status <draft_id>
```

## Commands

| Command | What it does |
|---------|--------------|
| `connections` | Lists connected LinkedIn accounts: platform id and display name. |
| `photos SRC_DIR --out DIR [--sheet PATH]` | Writes auto-oriented copies of each JPEG/PNG with all metadata stripped, reports originals that had GPS, verifies the copies have none. Never modifies originals; `--out` must differ from `SRC_DIR`. `--sheet` writes a labeled contact sheet. |
| `blur IN OUT --polygon X,Y X,Y X,Y... [--force]` | Writes a copy of `IN` with the polygon region blurred. Refuses when `OUT` is `IN`, or when `OUT` exists without `--force`. |
| `draft --text FILE [--image PATH]... [--platform ID]` | Validates (non-empty text, at most 3,000 characters, at most 10 JPEG/PNG images), creates a remote draft, uploads the images, saves a local manifest and prints the preview: full text, images, character count, the first 210 characters ("see more" fold) and a confirmation token. Trailing whitespace of the text file is dropped. |
| `publish DRAFT_ID --confirm TOKEN` | Publishes only if the token matches the local manifest and the remote draft still has the approved text, the approved number of images and status `draft`. Otherwise publishes nothing. |
| `status DRAFT_ID` | Shows remote status, platforms, character and media counts, and whether a local manifest exists. |
| `delete DRAFT_ID` | Deletes a draft remotely and its local manifest. Refuses anything that is not a draft. |

Every command has `--help`.

## Approval gate

`draft` stores a manifest at `$XDG_STATE_HOME/lipost/drafts/<id>.json`
(default `~/.local/state`) with the draft id, platform, text and its sha256, the
image sha256 list and the creation time. The confirmation token is the first 12
hex characters of `sha256(draft_id + text + image hashes)`. `publish` recomputes
it from the manifest, then re-reads the draft from the publisher before sending
`publishNow: true`.

## Credentials

`PUBLORA_API_KEY` and `LIPOST_PLATFORM_ID` are read from the environment, else
from `$XDG_CONFIG_HOME/lipost/env` (default `~/.config/lipost/env`):

```sh
mkdir -p ~/.config/lipost
printf 'PUBLORA_API_KEY=...\nLIPOST_PLATFORM_ID=linkedin-...\n' > ~/.config/lipost/env
chmod 600 ~/.config/lipost/env
```

lipost refuses to read the file when group or others have any access to it.
The key is never printed; it is redacted from any message. Authenticated calls
refuse HTTP redirects and use a 30 second timeout.

`LIPOST_PUBLORA_BASE_URL` overrides the API base URL for testing; plain `http`
is accepted only for loopback hosts.

## Exit codes

`0` success, `1` runtime or API failure, `2` usage or validation error
(including every publish refusal).

## Architecture

- `lipost/ports.py`: the `Publisher` port (list connections, create draft,
  upload image, get draft, publish draft, delete draft) and its value types.
- `lipost/publora.py`: the Publora adapter (`x-publora-key`, `create-post`,
  `get-upload-url` + `PUT uploadUrl`, `get-post`, `update-post`, `delete-post`).
- `lipost/cli.py`: commands; they depend only on the port. `make_publisher`
  is the single place that picks an adapter.
- `lipost/photos.py`, `lipost/manifest.py`, `lipost/config.py`: photo
  processing, manifests and tokens, credentials.

To add an official LinkedIn adapter, implement `Publisher` and select it in
`make_publisher`; commands stay unchanged.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests run Publora as a local fake server on 127.0.0.1 and generate images with
ImageMagick; they make no external network calls.
