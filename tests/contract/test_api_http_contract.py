from __future__ import annotations

import json
import os
from http.server import ThreadingHTTPServer
import pathlib
import sys
import threading
import unittest
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from server import Handler, SESSION_HASH_STORE  # noqa: E402

LIVEKIT_ENV_NAMES = (
    "LIVEKIT_REQUIRED",
    "LIVEKIT_URL",
    "LIVEKIT_INTERNAL_URL",
    "LIVEKIT_PUBLIC_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
)


class ApiHttpContractTest(unittest.TestCase):
    def setUp(self) -> None:
        SESSION_HASH_STORE.clear()
        self._old_livekit_env = {name: os.environ.get(name) for name in LIVEKIT_ENV_NAMES}
        for name in self._old_livekit_env:
            os.environ.pop(name, None)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host = self.server.server_address[0]
        port = self.server.server_address[1]
        self.base_url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        SESSION_HASH_STORE.clear()
        for name, value in self._old_livekit_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def _post(self, path: str, payload: bytes = b'{"role":"candidate"}') -> tuple[int, str]:
        req = urllib.request.Request(
            self.base_url + path,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status, res.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def test_create_session_routes_return_public_tokens_and_store_hashes_only(self) -> None:
        for path in ("/sessions", "/api/sessions"):
            with self.subTest(path=path):
                SESSION_HASH_STORE.clear()
                status, body = self._post(path)
                self.assertEqual(status, 201)
                public = json.loads(body)
                session_token = public["sessionToken"]
                report_token = public["reportToken"]
                self.assertNotEqual(session_token, report_token)
                self.assertEqual(public["livekit"]["tokenStatus"], "not_configured")
                self.assertEqual(public["livekit"]["deferredReason"], "livekit_credentials_missing")
                self.assertEqual(public["livekit"]["publicUrl"], None)
                self.assertNotIn("Hash", body)
                self.assertNotIn("hash", body)

                self.assertEqual(set(SESSION_HASH_STORE), {public["sessionId"]})
                stored_json = json.dumps(next(iter(SESSION_HASH_STORE.values())), sort_keys=True)
                self.assertIn("sessionTokenHash", stored_json)
                self.assertIn("reportTokenHash", stored_json)
                self.assertNotIn(session_token, stored_json)
                self.assertNotIn(report_token, stored_json)

    def test_create_session_accepts_safe_interview_id_for_room_binding(self) -> None:
        status, body = self._post("/api/sessions", b'{"role":"candidate","interviewId":"local-demo"}')
        self.assertEqual(status, 201)
        public = json.loads(body)
        self.assertEqual(public["sessionId"], "local-demo")
        self.assertEqual(public["roomName"], "giljob-session-local-demo")
        self.assertEqual(set(SESSION_HASH_STORE), {"local-demo"})

    def test_create_session_rejects_unsafe_interview_id(self) -> None:
        status, body = self._post("/api/sessions", b'{"role":"candidate","interviewId":"../local-demo"}')
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "invalid_session_id")

    def test_invalid_json_returns_400(self) -> None:
        status, body = self._post("/sessions", b"{bad-json")
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"], "invalid_json")

    def test_internal_session_route_stays_hidden(self) -> None:
        status, body = self._post("/api/internal/sessions")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "not_found")


if __name__ == "__main__":
    unittest.main()
