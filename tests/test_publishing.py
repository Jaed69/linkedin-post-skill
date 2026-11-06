"""CLI tests for connections, draft, publish, status and delete against a fake Publora."""

import hashlib
import json
import os
import re
import unittest

from helpers import API_KEY, PLATFORM, CliTestCase, make_image, sha256_file

TEXT = "Hola, esto es mi post.\n\nSegunda linea con detalles."


def expected_token(draft_id, text, image_hashes):
    return hashlib.sha256((draft_id + text + "".join(image_hashes)).encode()).hexdigest()[:12]


class DraftHelpers:
    def make_draft(self, text=TEXT, n_images=2):
        text_file = self.write_text(text)
        images = [make_image(self.path(f"img{i}.png" if i % 2 else f"img{i}.jpg"),
                             color=["red", "blue", "green"][i % 3]) for i in range(n_images)]
        args = ["draft", "--text", text_file]
        for img in images:
            args += ["--image", img]
        proc = self.run_cli(*args)
        return proc, images

    def draft_id_and_token(self, proc):
        draft_id = re.search(r"Draft created: (\S+)", proc.stdout).group(1)
        token = re.search(r"Confirmation token: ([0-9a-f]{12})", proc.stdout).group(1)
        return draft_id, token


class DraftTest(DraftHelpers, CliTestCase):
    def test_draft_happy_path_requests_manifest_and_preview(self):
        proc, images = self.make_draft()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        seq = [(r["method"], r["path"].split("/")[1] if r["path"].startswith("/upload/")
                else r["path"]) for r in self.fake.requests]
        self.assertEqual(seq, [
            ("POST", "/api/v1/create-post"),
            ("POST", "/api/v1/get-upload-url"), ("PUT", "upload"),
            ("POST", "/api/v1/get-upload-url"), ("PUT", "upload"),
        ])
        create = self.fake.requests[0]
        self.assertEqual(create["headers"]["x-publora-key"], API_KEY)
        self.assertEqual(create["headers"]["content-type"], "application/json")
        self.assertEqual(json.loads(create["body"]), {"content": TEXT, "platforms": [PLATFORM]})
        draft_id = next(iter(self.fake.posts))
        for i, (req, put) in enumerate(zip(self.fake.calls("POST", "/api/v1/get-upload-url"),
                                           self.fake.calls("PUT", "/upload/"))):
            body = json.loads(req["body"])
            ctype = "image/png" if i % 2 else "image/jpeg"
            self.assertEqual(body, {"fileName": os.path.basename(images[i]), "contentType": ctype,
                                    "postGroupId": draft_id, "type": "image"})
            self.assertEqual(req["headers"]["x-publora-key"], API_KEY)
            self.assertNotIn("x-publora-key", put["headers"])
            self.assertEqual(put["headers"]["content-type"], ctype)
            with open(images[i], "rb") as fh:
                self.assertEqual(put["body"], fh.read())

        hashes = [sha256_file(p) for p in images]
        with open(self.manifest_path(draft_id)) as fh:
            manifest = json.load(fh)
        self.assertEqual(manifest["draft_id"], draft_id)
        self.assertEqual(manifest["platform"], PLATFORM)
        self.assertEqual(manifest["text_sha256"], hashlib.sha256(TEXT.encode()).hexdigest())
        self.assertEqual(manifest["image_sha256"], hashes)
        self.assertIn("created_at", manifest)

        got_id, token = self.draft_id_and_token(proc)
        self.assertEqual(got_id, draft_id)
        self.assertEqual(token, expected_token(draft_id, TEXT, hashes))
        self.assertIn(TEXT, proc.stdout)
        self.assertIn(f"Characters: {len(TEXT)} / 3000", proc.stdout)
        self.assertIn(images[0], proc.stdout)
        self.assertIn(f"lipost publish {draft_id} --confirm {token}", proc.stdout)

    def test_preview_shows_210_character_fold(self):
        text = "a" * 210 + "TAIL"
        proc, _ = self.make_draft(text=text, n_images=0)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        fold = proc.stdout.split('"See more" fold')[1]
        self.assertIn("a" * 210 + "\n", fold)
        self.assertNotIn("TAIL", fold.split("---")[1])

    def test_validation_limits_exit_2_and_send_nothing(self):
        img = make_image(self.path("ok.jpg"))
        gif = make_image(self.path("anim.gif"))
        cases = {
            "empty": (["--text", self.write_text("  \n\n", "e.txt")], "empty"),
            "too long": (["--text", self.write_text("x" * 3001, "l.txt")], "3,000"),
            "too many": (["--text", self.write_text("ok", "m.txt")] + ["--image", img] * 11, "10"),
            "gif": (["--text", self.write_text("ok", "g.txt"), "--image", gif], "JPEG or PNG"),
            "missing image": (["--text", self.write_text("ok", "n.txt"), "--image",
                               self.path("nope.jpg")], "not found"),
        }
        for name, (args, needle) in cases.items():
            with self.subTest(name):
                proc = self.run_cli("draft", *args)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertIn(needle, proc.stderr)
        self.assertEqual(self.fake.requests, [])

    def test_text_at_exact_limit_is_accepted(self):
        proc, _ = self.make_draft(text="x" * 3000, n_images=0)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Characters: 3000 / 3000", proc.stdout)


class PublishTest(DraftHelpers, CliTestCase):
    def setUp(self):
        super().setUp()
        proc, _ = self.make_draft()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.draft_id, self.token = self.draft_id_and_token(proc)
        self.fake.requests.clear()

    def assert_refused(self, proc, needle):
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(needle, proc.stderr)
        self.assertEqual(self.fake.calls("PUT", "/api/v1/update-post/"), [])
        self.assertEqual(self.fake.posts[self.draft_id]["status"], "draft")

    def test_publish_happy_path_sends_publish_now(self):
        proc = self.run_cli("publish", self.draft_id, "--confirm", self.token)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        seq = [(r["method"], r["path"]) for r in self.fake.requests]
        self.assertEqual(seq, [("GET", f"/api/v1/get-post/{self.draft_id}"),
                               ("PUT", f"/api/v1/update-post/{self.draft_id}")])
        update = self.fake.requests[1]
        self.assertEqual(json.loads(update["body"]), {"publishNow": True})
        self.assertEqual(update["headers"]["x-publora-key"], API_KEY)
        self.assertIn("scheduled", proc.stdout)

    def test_api_calls_send_lipost_user_agent(self):
        # Cloudflare in front of Publora rejects Python's default User-Agent (error 1010).
        proc = self.run_cli("publish", self.draft_id, "--confirm", self.token)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for request in self.fake.requests:
            self.assertRegex(request["headers"].get("user-agent", ""), r"^lipost/\d")

    def test_publish_refused_on_wrong_token(self):
        proc = self.run_cli("publish", self.draft_id, "--confirm", "000000000000")
        self.assert_refused(proc, "token")
        self.assertEqual(proc.returncode, 2)

    def test_publish_refused_when_server_text_changed(self):
        self.fake.posts[self.draft_id]["content"] = TEXT + " edited"
        proc = self.run_cli("publish", self.draft_id, "--confirm", self.token)
        self.assert_refused(proc, "text")

    def test_publish_refused_when_media_count_changed(self):
        self.fake.posts[self.draft_id]["media"].pop()
        proc = self.run_cli("publish", self.draft_id, "--confirm", self.token)
        self.assert_refused(proc, "media")

    def test_publish_refused_on_missing_manifest(self):
        os.remove(self.manifest_path(self.draft_id))
        proc = self.run_cli("publish", self.draft_id, "--confirm", self.token)
        self.assert_refused(proc, "no local manifest")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(self.fake.requests, [])

    def test_publish_refused_when_not_draft(self):
        self.fake.posts[self.draft_id]["status"] = "scheduled"
        proc = self.run_cli("publish", self.draft_id, "--confirm", self.token)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not a draft", proc.stderr)
        self.assertEqual(self.fake.calls("PUT", "/api/v1/update-post/"), [])

    def test_publish_refused_when_manifest_tampered(self):
        path = self.manifest_path(self.draft_id)
        with open(path) as fh:
            manifest = json.load(fh)
        manifest["text"] = "something else"
        with open(path, "w") as fh:
            json.dump(manifest, fh)
        proc = self.run_cli("publish", self.draft_id, "--confirm", self.token)
        self.assert_refused(proc, "token")

    def test_publish_refused_when_target_account_changed(self):
        self.fake.posts[self.draft_id]["platforms"] = ["linkedin-SomeoneElse"]
        proc = self.run_cli("publish", self.draft_id, "--confirm", self.token)
        self.assert_refused(proc, "account")
        self.assertEqual(proc.returncode, 2)

    def test_publish_refused_cleanly_on_incomplete_manifest(self):
        path = self.manifest_path(self.draft_id)
        with open(path) as fh:
            manifest = json.load(fh)
        del manifest["image_sha256"]
        with open(path, "w") as fh:
            json.dump(manifest, fh)
        proc = self.run_cli("publish", self.draft_id, "--confirm", self.token)
        self.assert_refused(proc, "manifest")
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_publish_refused_when_manifest_belongs_to_other_draft(self):
        path = self.manifest_path(self.draft_id)
        with open(path) as fh:
            manifest = json.load(fh)
        manifest["draft_id"] = "other-draft"
        with open(path, "w") as fh:
            json.dump(manifest, fh)
        before = sha256_file(path)
        other_token = expected_token("other-draft", manifest["text"], manifest["image_sha256"])
        proc = self.run_cli("publish", self.draft_id, "--confirm", other_token)
        self.assert_refused(proc, "manifest")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(sha256_file(path), before)

    def test_status_prints_remote_state(self):
        proc = self.run_cli("status", self.draft_id)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Status: draft", proc.stdout)
        self.assertIn("Media: 2", proc.stdout)
        self.assertIn("Local manifest: yes", proc.stdout)

    def test_delete_draft_removes_remote_and_manifest(self):
        proc = self.run_cli("delete", self.draft_id)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self.fake.calls("DELETE", f"/api/v1/delete-post/{self.draft_id}")), 1)
        self.assertFalse(os.path.exists(self.manifest_path(self.draft_id)))

    def test_delete_refuses_non_draft(self):
        self.fake.posts[self.draft_id]["status"] = "scheduled"
        proc = self.run_cli("delete", self.draft_id)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a draft", proc.stderr)
        self.assertEqual(self.fake.calls("DELETE"), [])


class ConnectionsAndHttpTest(CliTestCase):
    def test_connections_lists_linkedin_only(self):
        proc = self.run_cli("connections")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(PLATFORM, proc.stdout)
        self.assertIn("Ada Lovelace", proc.stdout)
        self.assertNotIn("twitter-123", proc.stdout)
        req = self.fake.requests[0]
        self.assertEqual((req["method"], req["path"]), ("GET", "/api/v1/platform-connections"))
        self.assertEqual(req["headers"]["x-publora-key"], API_KEY)

    def test_api_error_code_and_message_surface(self):
        self.fake.overrides["/api/v1/platform-connections"] = (
            401, {"error": "Invalid API key", "code": "AUTH_INVALID"}, {})
        proc = self.run_cli("connections")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("401", proc.stderr)
        self.assertIn("AUTH_INVALID", proc.stderr)
        self.assertIn("Invalid API key", proc.stderr)

    def test_redirects_are_refused(self):
        self.fake.overrides["/api/v1/platform-connections"] = (
            302, None, {"Location": f"http://127.0.0.1:{self.fake.port}/elsewhere"})
        proc = self.run_cli("connections")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("redirect", proc.stderr)
        self.assertEqual([r["path"] for r in self.fake.requests], ["/api/v1/platform-connections"])

    def test_plain_http_base_url_refused_for_remote_hosts(self):
        self.env["LIPOST_PUBLORA_BASE_URL"] = "http://api.example.com/api/v1"
        proc = self.run_cli("connections")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("https", proc.stderr)

    def test_key_never_appears_in_any_output(self):
        outputs = [self.run_cli("connections")]
        text_file = self.write_text("hola")
        draft = self.run_cli("draft", "--text", text_file)
        outputs.append(draft)
        draft_id = re.search(r"Draft created: (\S+)", draft.stdout).group(1)
        outputs += [self.run_cli("status", draft_id),
                    self.run_cli("publish", draft_id, "--confirm", "bad"),
                    self.run_cli("delete", draft_id)]
        self.fake.overrides["/api/v1/platform-connections"] = (
            401, {"error": f"Invalid API key {API_KEY}", "code": "AUTH_INVALID"}, {})
        outputs.append(self.run_cli("connections"))
        for proc in outputs:
            self.assertNotIn(API_KEY, proc.stdout + proc.stderr)
        self.assertIn("Invalid API key", outputs[-1].stderr)


class CredentialsTest(CliTestCase):
    def write_env_file(self, mode):
        cfg = os.path.join(self.env["XDG_CONFIG_HOME"], "lipost")
        os.makedirs(cfg)
        path = os.path.join(cfg, "env")
        with open(path, "w") as fh:
            fh.write(f"# comment\nPUBLORA_API_KEY={API_KEY}\nLIPOST_PLATFORM_ID={PLATFORM}\n")
        os.chmod(path, mode)
        del self.env["PUBLORA_API_KEY"], self.env["LIPOST_PLATFORM_ID"]
        return path

    def test_env_file_readable_by_others_is_refused(self):
        path = self.write_env_file(0o644)
        for mode in (0o644, 0o640, 0o604):
            with self.subTest(oct(mode)):
                os.chmod(path, mode)
                proc = self.run_cli("connections")
                self.assertEqual(proc.returncode, 2)
                self.assertIn(f"chmod 600 {path}", proc.stderr)
                self.assertNotIn(API_KEY, proc.stdout + proc.stderr)
        self.assertEqual(self.fake.requests, [])

    def test_env_file_with_600_is_used(self):
        self.write_env_file(0o600)
        proc = self.run_cli("connections")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.fake.requests[0]["headers"]["x-publora-key"], API_KEY)

    def test_missing_key_is_a_usage_error(self):
        del self.env["PUBLORA_API_KEY"]
        proc = self.run_cli("connections")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("PUBLORA_API_KEY", proc.stderr)
        self.assertEqual(self.fake.requests, [])


class HelpTest(CliTestCase):
    use_server = False

    def test_every_command_has_help(self):
        top = self.run_cli("--help")
        self.assertEqual(top.returncode, 0)
        for cmd in ("connections", "photos", "blur", "draft", "publish", "status", "delete"):
            with self.subTest(cmd):
                self.assertIn(cmd, top.stdout)
                proc = self.run_cli(cmd, "--help")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn(f"usage: lipost {cmd}", proc.stdout)

    def test_unknown_command_exits_2(self):
        self.assertEqual(self.run_cli("bogus").returncode, 2)


if __name__ == "__main__":
    unittest.main()
