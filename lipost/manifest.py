"""Local draft manifests and the confirmation token that gates publishing."""

import hashlib
import json
import os
from datetime import datetime, timezone


def state_dir(env):
    base = env.get("XDG_STATE_HOME") or os.path.join(env.get("HOME", "~"), ".local", "state")
    return os.path.join(os.path.expanduser(base), "lipost", "drafts")


def manifest_path(env, draft_id):
    if not draft_id or "/" in draft_id or draft_id.startswith("."):
        raise ValueError(f"invalid draft id: {draft_id!r}")
    return os.path.join(state_dir(env), f"{draft_id}.json")


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def confirmation_token(draft_id, text, image_hashes):
    payload = draft_id + text + "".join(image_hashes)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def build(draft_id, platform, text, images, image_hashes):
    return {
        "draft_id": draft_id,
        "platform": platform,
        "text": text,
        "text_sha256": sha256_text(text),
        "images": list(images),
        "image_sha256": list(image_hashes),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def save(env, manifest):
    path = manifest_path(env, manifest["draft_id"])
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w",
              encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def load(env, draft_id):
    """Return the manifest dict, or None when it does not exist."""
    path = manifest_path(env, draft_id)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def remove(env, draft_id):
    path = manifest_path(env, draft_id)
    if os.path.exists(path):
        os.remove(path)
