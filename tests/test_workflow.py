import http.cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import server


class WorkflowIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        server.DB_PATH = Path(cls.temp_dir.name) / "workflow.sqlite3"
        server.init_db()
        server.seed_demo()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}/api"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)
        cls.temp_dir.cleanup()

    def client(self):
        cookies = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
        return opener

    def request(self, client, path, method="GET", payload=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            with client.open(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def login(self, email, password):
        client = self.client()
        status, data = self.request(client, "/auth/login", "POST", {"email": email, "password": password})
        self.assertEqual(status, 200, data)
        return client, data["user"]

    def test_citizen_admin_resolver_lifecycle(self):
        citizen, citizen_info = self.login("citizen@onebridge.local", "CitizenDemo!2026")
        admin, _ = self.login("admin@onebridge.local", "AdminDemo!2026")
        resolver, resolver_info = self.login("resolver@onebridge.local", "ResolverDemo!2026")

        status, created = self.request(citizen, "/reports", "POST", {
            "title": "Broken crossing signal",
            "category": "Street lighting",
            "location": "East gate crossing",
            "description": "The pedestrian crossing signal is not lighting up after dark.",
            "evidence_note": "Observed yesterday evening.",
        })
        self.assertEqual(status, 201, created)
        report_id = created["id"]

        status, _ = self.request(admin, f"/reports/{report_id}/review", "POST", {
            "status": "SUPPORTED_BY_EVIDENCE", "note": "Details are complete; reviewer supports routing this issue.",
        })
        self.assertEqual(status, 200)
        status, assignment = self.request(admin, "/demo/resolver")
        self.assertEqual(status, 200)
        self.assertEqual(assignment["id"], resolver_info["id"])
        status, _ = self.request(admin, f"/reports/{report_id}/assign", "POST", {"resolver_id": assignment["id"]})
        self.assertEqual(status, 200)

        status, _ = self.request(resolver, f"/reports/{report_id}/progress", "POST", {"note": "Site visit is scheduled."})
        self.assertEqual(status, 200)
        status, _ = self.request(resolver, f"/reports/{report_id}/resolve", "POST", {
            "note": "Signal hardware was replaced and tested at the crossing.",
        })
        self.assertEqual(status, 200)
        status, _ = self.request(citizen, f"/reports/{report_id}/confirm", "POST", {})
        self.assertEqual(status, 200)

        status, report = self.request(citizen, f"/reports/{report_id}")
        self.assertEqual(status, 200)
        self.assertEqual(report["report"]["status"], "RESOLVED")
        self.assertEqual(citizen_info["role"], "citizen")
        self.assertGreaterEqual(len(report["report"]["timeline"]), 5)

    def test_role_permissions_and_private_report_access(self):
        citizen, _ = self.login("citizen@onebridge.local", "CitizenDemo!2026")
        other_citizen = self.client()
        status, data = self.request(other_citizen, "/auth/register", "POST", {
            "name": "New Community Member", "email": "new-member@onebridge.local",
            "password": "NewMemberPassword2026!",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["user"]["role"], "citizen")
        status, data = self.request(other_citizen, "/reports", "POST", {
            "title": "A damaged public footpath",
            "category": "Accessibility",
            "location": "North entrance",
            "description": "The public footpath surface is cracked and difficult to navigate.",
            "latitude": 91,
        })
        self.assertEqual(status, 400)
        self.assertIn("coordinate", data["error"])

        status, created = self.request(citizen, "/reports", "POST", {
            "title": "Public walkway surface damage",
            "category": "Accessibility",
            "location": "North entrance",
            "description": "A section of the public walkway is cracked and hard to navigate.",
        })
        self.assertEqual(status, 201)
        status, data = self.request(other_citizen, f"/reports/{created['id']}")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
