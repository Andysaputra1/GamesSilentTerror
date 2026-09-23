"""Opt-in QC registrasi pada MySQL lokal. Hanya akun QC buatan tes yang dibersihkan."""

import secrets
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from controller.api.auth import router
from module.mysql_connector import SessionLocal


def main():
    name = "qc_auth_" + secrets.token_hex(6)
    email = name + "@example.com"
    password = secrets.token_urlsafe(24)
    app = FastAPI()
    app.include_router(router)
    try:
        with TestClient(app) as client:
            body = {
                "username": name,
                "email": email,
                "email_confirmation": email,
                "password": password,
                "password_confirmation": password,
            }
            registered = client.post("/api/auth/register", json=body)
            assert registered.status_code == 201, registered.status_code
            token = registered.json()["access_token"]
            assert (
                client.get("/api/auth/me", headers={"Authorization": "Bearer " + token}).status_code
                == 200
            )
            assert client.post("/api/auth/register", json=body).status_code == 409
            assert (
                client.post(
                    "/api/auth/login", json={"username": email, "password": "wrong"}
                ).status_code
                == 401
            )
            logged = client.post("/api/auth/login", json={"username": email, "password": password})
            assert logged.status_code == 200
            headers = {"Authorization": "Bearer " + logged.json()["access_token"]}
            assert client.post("/api/auth/logout", headers=headers).status_code == 204
            assert client.get("/api/auth/me", headers=headers).status_code == 401
            print(
                "PASS real MySQL: register, session, duplicate, wrong password, email login, logout/revocation"
            )
    finally:
        with SessionLocal.begin() as db:
            # Identifikasi tepat username dan email buatan tes; bukan wildcard akun pengguna.
            row = db.execute(
                text(
                    "SELECT u.id FROM user_accounts u JOIN account_identities i ON i.user_id=u.id WHERE u.username=:name AND i.email=:email"
                ),
                {"name": name, "email": email},
            ).scalar()
            if row:
                db.execute(
                    text("DELETE FROM user_accounts WHERE id=:id AND username=:name"),
                    {"id": row, "name": name},
                )
        print("QC account removed; existing accounts preserved.")


if __name__ == "__main__":
    main()
