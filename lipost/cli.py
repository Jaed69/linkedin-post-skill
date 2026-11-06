"""lipost command line: prepare photos and publish LinkedIn posts.

Exit codes: 0 success, 1 runtime/API failure, 2 usage or validation error.
"""

import argparse
import hmac
import os
import sys

from . import config, manifest, photos
from .ports import PublisherError

MAX_CHARS = 3000
MAX_IMAGES = 10
FOLD_CHARS = 210

_secrets = set()


class UsageError(Exception):
    """Usage or validation error (exit code 2)."""


def _redact(text):
    for secret in _secrets:
        text = text.replace(secret, "***")
    return text


def out(text=""):
    print(_redact(str(text)))


def err(text):
    print(_redact(f"lipost: {text}"), file=sys.stderr)


def make_publisher(env):
    """Build the configured publisher adapter. Commands only see the port."""
    from .publora import DEFAULT_BASE_URL, PubloraPublisher

    creds = config.load_credentials(env)
    _secrets.add(creds["PUBLORA_API_KEY"])
    base = env.get("LIPOST_PUBLORA_BASE_URL") or DEFAULT_BASE_URL
    try:
        publisher = PubloraPublisher(creds["PUBLORA_API_KEY"], base_url=base)
    except ValueError as exc:
        raise UsageError(f"LIPOST_PUBLORA_BASE_URL: {exc}") from None
    return publisher, creds


# --- commands ---------------------------------------------------------------

def cmd_connections(args, env):
    publisher, _ = make_publisher(env)
    connections = publisher.list_connections()
    if not connections:
        out("No LinkedIn accounts connected.")
    for c in connections:
        out(f"{c.platform_id}\t{c.display_name}")
    return 0


def cmd_photos(args, env):
    src, dst = os.path.realpath(args.src_dir), os.path.realpath(args.out)
    if not os.path.isdir(src):
        raise UsageError(f"source directory not found: {args.src_dir}")
    if src == dst:
        raise UsageError("--out must differ from the source directory; originals are never modified")
    written, had_gps, skipped = photos.process_dir(src, dst)
    out(f"Wrote {len(written)} stripped, auto-oriented copies to {args.out}")
    if had_gps:
        out(f"GPS found in {len(had_gps)} original(s) (removed from the copies):")
        for name in had_gps:
            out(f"  {name}")
    else:
        out("No GPS metadata found in the originals.")
    out("Outputs verified: no GPS metadata.")
    if skipped:
        out(f"Skipped (not JPEG/PNG): {', '.join(skipped)}")
    if args.sheet and written:
        photos.contact_sheet(written, args.sheet)
        out(f"Contact sheet: {args.sheet}")
    return 0


def _parse_point(raw):
    try:
        x, y = raw.split(",")
        return int(x), int(y)
    except ValueError:
        raise UsageError(f"bad polygon point {raw!r}; expected X,Y integers") from None


def cmd_blur(args, env):
    if not os.path.isfile(args.input):
        raise UsageError(f"input not found: {args.input}")
    if os.path.realpath(args.input) == os.path.realpath(args.output):
        raise UsageError("output must differ from input; the input is never overwritten")
    if os.path.exists(args.output) and not args.force:
        raise UsageError(f"{args.output} already exists; pass --force to replace it")
    if os.path.splitext(args.output)[1].lower() not in (".jpg", ".jpeg", ".png"):
        raise UsageError("output must end in .jpg, .jpeg or .png")
    points = [_parse_point(p) for p in args.polygon]
    if len(points) < 3:
        raise UsageError("--polygon needs at least 3 points")
    photos.blur_polygon(args.input, args.output, points)
    out(f"Blurred copy written to {args.output}")
    return 0


def _read_post_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read().rstrip()
    except OSError as exc:
        raise UsageError(f"cannot read text file {path}: {exc.strerror}") from None
    except UnicodeDecodeError:
        raise UsageError(f"text file {path} is not valid UTF-8") from None
    if not text.strip():
        raise UsageError("post text is empty")
    if len(text) > MAX_CHARS:
        raise UsageError(f"post text has {len(text)} characters; LinkedIn allows at most 3,000")
    return text


def _validate_images(paths):
    if len(paths) > MAX_IMAGES:
        raise UsageError(f"{len(paths)} images given; LinkedIn allows at most {MAX_IMAGES}")
    typed = []
    for path in paths:
        if not os.path.isfile(path):
            raise UsageError(f"image not found: {path}")
        ctype = photos.image_type(path)
        if ctype is None:
            raise UsageError(f"{path} is not a JPEG or PNG image")
        typed.append((path, ctype))
    return typed


def cmd_draft(args, env):
    text = _read_post_text(args.text)
    images = _validate_images(args.image or [])
    publisher, creds = make_publisher(env)
    platform = args.platform or creds.get("LIPOST_PLATFORM_ID")
    if not platform:
        raise UsageError("no platform: pass --platform or set LIPOST_PLATFORM_ID "
                         "(see `lipost connections`)")
    hashes = [manifest.sha256_file(p) for p, _ in images]
    draft_id = publisher.create_draft(text, platform)
    try:
        for path, ctype in images:
            publisher.upload_image(draft_id, path, ctype)
    except PublisherError as exc:
        raise PublisherError(f"{exc}\ndraft {draft_id} was created but an upload failed; "
                             f"remove it with: lipost delete {draft_id}") from None
    manifest.save(env, manifest.build(draft_id, platform, text, [p for p, _ in images], hashes))
    token = manifest.confirmation_token(draft_id, text, hashes)

    out(f"Draft created: {draft_id}")
    out(f"Platform: {platform}")
    out(f"Characters: {len(text)} / {MAX_CHARS}")
    out(f"Images ({len(images)}):")
    for i, ((path, _), digest) in enumerate(zip(images, hashes), 1):
        out(f"  {i}. {path}  sha256:{digest[:12]}")
    out("--- Full text ---")
    out(text)
    out(f'--- "See more" fold (first {FOLD_CHARS} characters) ---')
    out(text[:FOLD_CHARS])
    out("---")
    out(f"Confirmation token: {token}")
    out(f"To publish after review: lipost publish {draft_id} --confirm {token}")
    return 0


MANIFEST_FIELDS = ("draft_id", "platform", "text", "text_sha256", "image_sha256")


def _load_manifest(env, draft_id):
    try:
        data = manifest.load(env, draft_id)
    except ValueError as exc:
        raise UsageError(str(exc)) from None
    if data is not None:
        missing = [field for field in MANIFEST_FIELDS if field not in data]
        if missing:
            raise UsageError(f"local manifest for {draft_id} is incomplete "
                             f"(missing: {', '.join(missing)}); nothing published")
    return data


def cmd_publish(args, env):
    local = _load_manifest(env, args.draft_id)
    if local is None:
        raise UsageError(f"no local manifest for draft {args.draft_id}; refusing to publish")
    expected = manifest.confirmation_token(local["draft_id"], local["text"], local["image_sha256"])
    if (manifest.sha256_text(local["text"]) != local["text_sha256"]
            or not hmac.compare_digest(expected, args.confirm)):
        raise UsageError("confirmation token does not match the local manifest; nothing published")
    publisher, _ = make_publisher(env)
    remote = publisher.get_draft(args.draft_id)
    problems = []
    if remote.status != "draft":
        problems.append(f"remote post is not a draft (status: {remote.status})")
    if manifest.sha256_text(remote.text) != local["text_sha256"]:
        problems.append("remote text differs from the approved text")
    if remote.platforms != [local["platform"]]:
        problems.append(f"remote target account {remote.platforms} differs from approved "
                        f"[{local['platform']}]")
    if remote.media_count != len(local["image_sha256"]):
        problems.append(f"remote media count {remote.media_count} differs from approved "
                        f"{len(local['image_sha256'])}")
    if problems:
        raise UsageError("refusing to publish: " + "; ".join(problems))
    result = publisher.publish_draft(args.draft_id)
    group = result.get("postGroup") or {}
    out(f"Publish requested for {args.draft_id}: status {group.get('status', 'unknown')}, "
        f"scheduledTime {result.get('scheduledTime')}")
    out(f"Check delivery with: lipost status {args.draft_id}")
    return 0


def cmd_status(args, env):
    publisher, _ = make_publisher(env)
    remote = publisher.get_draft(args.draft_id)
    out(f"Draft: {remote.draft_id}")
    out(f"Status: {remote.status}")
    out(f"Platforms: {', '.join(remote.platforms)}")
    out(f"Characters: {len(remote.text)}")
    out(f"Media: {remote.media_count}")
    out(f"Local manifest: {'yes' if _load_manifest(env, args.draft_id) else 'no'}")
    return 0


def cmd_delete(args, env):
    publisher, _ = make_publisher(env)
    remote = publisher.get_draft(args.draft_id)
    if remote.status != "draft":
        raise UsageError(f"{args.draft_id} is not a draft (status: {remote.status}); "
                         "only drafts can be deleted")
    publisher.delete_draft(args.draft_id)
    manifest.remove(env, args.draft_id)
    out(f"Deleted draft {args.draft_id}")
    return 0


# --- parser -----------------------------------------------------------------

ENV_HELP = """Credentials: PUBLORA_API_KEY and LIPOST_PLATFORM_ID from the environment,
else from $XDG_CONFIG_HOME/lipost/env (default ~/.config/lipost/env) as KEY=VALUE
lines; that file must be private (chmod 600). Testing override:
LIPOST_PUBLORA_BASE_URL (plain http allowed only on loopback).

Exit codes: 0 success, 1 runtime/API failure, 2 usage or validation error."""


def build_parser():
    fmt = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(
        prog="lipost", formatter_class=fmt, epilog=ENV_HELP,
        description="Prepare photos and publish LinkedIn posts with a human approval gate.")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    p = sub.add_parser("connections", help="list connected LinkedIn accounts",
                       description="List connected LinkedIn accounts (platform id and name).")
    p.set_defaults(func=cmd_connections)

    p = sub.add_parser("photos", help="write metadata-free copies of photos",
                       description="Write auto-oriented copies of every JPEG/PNG in SRC_DIR with "
                                   "all metadata stripped, report originals that had GPS, and "
                                   "verify the copies have none. Originals are never modified.")
    p.add_argument("src_dir", help="directory with the original photos")
    p.add_argument("--out", required=True, help="output directory (must differ from SRC_DIR)")
    p.add_argument("--sheet", help="also write a labeled contact sheet to this path")
    p.set_defaults(func=cmd_photos)

    p = sub.add_parser("blur", help="blur a polygon region into a new file",
                       description="Write a copy of INPUT with the polygon region blurred. "
                                   "Never overwrites INPUT.")
    p.add_argument("input")
    p.add_argument("output", help="new file (.jpg/.jpeg/.png)")
    p.add_argument("--polygon", nargs="+", required=True, metavar="X,Y",
                   help="at least 3 pixel points, e.g. --polygon 10,10 90,10 90,90")
    p.add_argument("--force", action="store_true", help="replace OUTPUT if it exists")
    p.set_defaults(func=cmd_blur)

    p = sub.add_parser("draft", help="create a remote draft and print the preview",
                       formatter_class=fmt,
                       description="Validate the post (non-empty, at most 3,000 characters, at "
                                   "most 10 JPEG/PNG images), create a draft, upload the "
                                   "images, save a local manifest and print the preview with a "
                                   "confirmation token.")
    p.add_argument("--text", required=True, help="UTF-8 file with the post text")
    p.add_argument("--image", action="append", metavar="PATH", help="image to attach (repeatable)")
    p.add_argument("--platform", help="connection id (default: LIPOST_PLATFORM_ID)")
    p.set_defaults(func=cmd_draft)

    p = sub.add_parser("publish", help="publish an approved draft",
                       description="Publish DRAFT_ID only if --confirm matches the token printed "
                                   "by `lipost draft` and the remote draft still has the "
                                   "approved text, the approved number of images and status "
                                   "draft. Any mismatch publishes nothing and exits non-zero.")
    p.add_argument("draft_id")
    p.add_argument("--confirm", required=True, metavar="TOKEN", help="token from `lipost draft`")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("status", help="show the remote state of a draft",
                       description="Show the remote status, platforms and media of DRAFT_ID.")
    p.add_argument("draft_id")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("delete", help="delete a draft",
                       description="Delete DRAFT_ID remotely and locally. Refuses non-drafts.")
    p.add_argument("draft_id")
    p.set_defaults(func=cmd_delete)
    return parser


def main(argv=None, env=None):
    env = dict(os.environ if env is None else env)
    args = build_parser().parse_args(argv)
    try:
        return args.func(args, env)
    except (UsageError, config.ConfigError) as exc:
        err(exc)
        return 2
    except (PublisherError, photos.PhotoError) as exc:
        err(exc)
        return 1
    except KeyboardInterrupt:
        err("interrupted")
        return 1


if __name__ == "__main__":
    sys.exit(main())
