"""Publora adapter for the publisher port (https://docs.publora.com)."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from . import __version__
from .ports import Connection, Publisher, PublisherError, RemoteDraft

DEFAULT_BASE_URL = "https://api.publora.com/api/v1"
TIMEOUT_SECONDS = 30
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PublisherError(f"refusing to follow HTTP {code} redirect from {req.full_url}")


def check_url(url):
    """Allow https anywhere, plain http only on loopback (the test override)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS):
        return url
    raise ValueError(f"refusing non-https URL: {url}")


USER_AGENT = f"lipost/{__version__}"


class PubloraPublisher(Publisher):
    def __init__(self, api_key, base_url=DEFAULT_BASE_URL, timeout=TIMEOUT_SECONDS):
        self._key = api_key
        self._base = check_url(base_url.rstrip("/"))
        self._timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect)

    def _send(self, method, url, body=None, headers=None):
        headers = dict(headers or {})
        # Cloudflare in front of Publora rejects Python's default User-Agent (error 1010).
        headers.setdefault("User-Agent", USER_AGENT)
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as err:
            raise PublisherError(_describe_error(err)) from None
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            reason = getattr(err, "reason", err)
            raise PublisherError(f"network error calling {method} {url}: {reason}") from None
        return raw

    def _api(self, method, path, payload=None):
        headers = {"x-publora-key": self._key, "Accept": "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        raw = self._send(method, self._base + path, body, headers)
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            raise PublisherError(f"Publora returned non-JSON for {method} {path}") from None

    def list_connections(self):
        data = self._api("GET", "/platform-connections")
        return [Connection(c["platformId"], c.get("displayName") or c.get("username") or "")
                for c in data.get("connections", [])
                if str(c.get("platformId", "")).startswith("linkedin-")]

    def create_draft(self, text, platform_id):
        # No scheduledTime and no publishNow: Publora stores the group as a draft.
        data = self._api("POST", "/create-post", {"content": text, "platforms": [platform_id]})
        return data["postGroupId"]

    def upload_image(self, draft_id, path, content_type):
        data = self._api("POST", "/get-upload-url", {
            "fileName": os.path.basename(path), "contentType": content_type,
            "postGroupId": draft_id, "type": "image",
        })
        try:
            upload_url = check_url(data["uploadUrl"])
        except (KeyError, ValueError) as err:
            raise PublisherError(f"unusable uploadUrl from Publora: {err}") from None
        with open(path, "rb") as fh:
            content = fh.read()
        # Pre-signed S3 URL: the API key must not be sent here.
        self._send("PUT", upload_url, content, {"Content-Type": content_type})

    def get_draft(self, draft_id):
        data = self._api("GET", f"/get-post/{urllib.parse.quote(draft_id)}")
        # The group carries no text; each entry in posts[] holds the effective
        # per-platform content (docs: endpoints/get-post, "Per-platform fields").
        posts = data.get("posts") or []
        linkedin = [p for p in posts if p.get("platform") == "linkedin"] or posts
        text = linkedin[0].get("content", "") if linkedin else ""
        return RemoteDraft(draft_id=data.get("postGroupId", draft_id),
                           status=data.get("status", ""), text=text,
                           media_count=len(data.get("media") or []),
                           platforms=list(data.get("platforms") or []))

    def publish_draft(self, draft_id):
        return self._api("PUT", f"/update-post/{urllib.parse.quote(draft_id)}",
                         {"publishNow": True})

    def delete_draft(self, draft_id):
        self._api("DELETE", f"/delete-post/{urllib.parse.quote(draft_id)}")


def _describe_error(err):
    """Format Publora's `{error, code, message}` error bodies."""
    detail = ""
    try:
        body = json.loads(err.read() or b"{}")
    except ValueError:
        body = {}
    if isinstance(body, dict):
        parts = [str(body[k]) for k in ("code", "error", "message") if body.get(k)]
        detail = ": " + " - ".join(parts) if parts else ""
    return f"Publora API error HTTP {err.code}{detail}"
