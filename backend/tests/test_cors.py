import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.controller.middleware.cors import configure_cors

FRONTEND = "https://silent-terror.andylabs.site"


class CorsTests(unittest.TestCase):
    # Frontend Vercel dan backend beda origin: preflight PUT simpan skin harus lolos (dulu 400).
    def test_preflight_allows_put_for_skin(self):
        with patch.object(settings, "cors_origins", FRONTEND):
            app = FastAPI()
            configure_cors(app)
            app.put("/api/auth/skin")(lambda: {"skin_id": "sadie"})
            response = TestClient(app).options(
                "/api/auth/skin",
                headers={
                    "Origin": FRONTEND,
                    "Access-Control-Request-Method": "PUT",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("PUT", response.headers["access-control-allow-methods"])


if __name__ == "__main__":
    unittest.main()
