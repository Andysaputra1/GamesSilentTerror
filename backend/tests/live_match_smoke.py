"""Opt-in integration dengan server+MySQL nyata. Tidak ikut unittest discover.

Run: docker compose exec -T ai-engine python -m tests.live_match_smoke
Membuat empat akun QC unik, membersihkan hanya ID akun milik tes di finally.
Tes ini sengaja membaca snapshot setiap akun untuk menyiapkan skenario role;
client game biasa hanya bisa membaca snapshot akunnya sendiri.
"""

import secrets
import time
import httpx
from sqlalchemy import text
from models.auth_queries import create_account
from module.mysql_connector import SessionLocal
from services.password_service import hash_password


# TEST LIVE: empat sesi terpisah bermain 2 ronde, menguji skill/privasi dan kemenangan.
def main():
    prefix = "qc_" + secrets.token_hex(5)
    accounts = [prefix + "_" + str(i) for i in range(4)]
    password = secrets.token_urlsafe(20)
    ids = []
    clients = {}
    code = None
    try:
        with SessionLocal.begin() as database:
            for name in accounts:
                ids.append(
                    create_account(
                        database,
                        username=name,
                        display_name=name,
                        password_hash=hash_password(password),
                    )
                )
        for name in accounts:
            client = httpx.Client(base_url="http://127.0.0.1:8000", timeout=10)
            clients[name] = client
            login = client.post("/api/auth/login", json={"username": name, "password": password})
            login.raise_for_status()
            client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        owner = clients[accounts[0]]
        code = owner.post("/api/rooms").json()["code"]
        base = "/api/rooms/" + code
        for name in accounts[1:]:
            clients[name].post("/api/rooms/join", json={"code": code}).raise_for_status()
        assert clients[accounts[1]].post(base + "/start", json={}).status_code == 400
        owner.post(base + "/start", json={"quick": True}).raise_for_status()
        states = {
            name: client.get(base + "/game").json()["game"] for name, client in clients.items()
        }
        roles = {state["me"]["role"]: name for name, state in states.items()}
        assert len(roles) == 4
        assert httpx.get("http://127.0.0.1:8000" + base + "/game").status_code == 401
        assert owner.get(base + "/checker").status_code == 403
        print("PASS empat login, create/join/start, privasi dan autentikasi", flush=True)

        def state(name):
            response = clients[name].get(base + "/game")
            response.raise_for_status()
            return response.json()["game"]

        def play(role, target_role, ability=None, expected=200):
            name = roles[role]
            view = state(name)
            result = clients[name].post(
                base + "/play",
                json={
                    "match_id": view["id"],
                    "round_number": view["round"],
                    "phase": view["phase"],
                    "ability": ability,
                    "target": roles[target_role],
                },
            )
            assert result.status_code == expected, (result.status_code, result.text)

        def wait_phase(phase, round_number):
            end = time.monotonic() + 65
            while time.monotonic() < end:
                view = state(accounts[0])
                if view["phase"] == phase and view["round"] == round_number:
                    return view
                time.sleep(0.5)
            raise AssertionError(f"Timer tidak mencapai {phase}/{round_number}")

        play("hitman", "civilian", "gag")
        assert not state(roles["civilian"])["me"]["can_chat"]
        play("hitman", "spy", "gag", expected=400)
        wait_phase("night", 1)
        play("hitman", "civilian", "hostage")
        play("spy", "civilian", "guard")
        play("stalker", "hitman", "peek")
        assert state(roles["stalker"])["me"]["intel"] == []
        wait_phase("tribunal", 1)
        assert state(roles["stalker"])["me"]["intel"][0]["role"] == "hitman"
        for name in accounts:
            view = state(name)
            assert all(set(p) == {"name", "bot", "alive"} for p in view["players"])
        play("civilian", "hitman", expected=400)
        # Tanpa vote ronde 1: tidak ada eksekusi. Guard harus tetap melindungi korban.
        wait_phase("day", 2)
        assert state(roles["civilian"])["me"]["can_chat"]
        play("hitman", "civilian", "gag", expected=400)
        print("PASS Gag/Guard/Peek, resolusi buta, cooldown, no-vote, ronde kedua", flush=True)
        wait_phase("night", 2)
        play("spy", "civilian", "guard", expected=400)
        play("stalker", "hitman", "peek", expected=400)
        play("spy", "spy", "guard")
        play("hitman", "civilian", "hostage")
        wait_phase("tribunal", 2)
        victim = state(roles["civilian"])
        assert (
            victim["me"]["alive"] and not victim["me"]["can_vote"] and not victim["me"]["can_chat"]
        )
        play("civilian", "hitman", expected=400)
        play("spy", "hitman")
        play("spy", "stalker", expected=400)
        play("stalker", "hitman")
        play("hitman", "spy")
        result = wait_phase("finished", 2)
        assert result["winner"] == "civilians"
        assert all("role" in p for p in result["players"])
        assert owner.get(base + "/checker").status_code == 200
        print(
            "PASS Hostage diam/tetap hidup, vote satu kali, eksekusi Hitman, WARGA MENANG. Room "
            + code,
            flush=True,
        )
        for client in clients.values():
            client.post(base + "/leave").raise_for_status()
        code = None
    finally:
        for client in clients.values():
            client.close()
        with SessionLocal.begin() as database:
            for account_id in ids:
                database.execute(
                    text("DELETE FROM user_accounts WHERE id = :id AND username LIKE :prefix"),
                    {"id": account_id, "prefix": prefix + "%"},
                )
        print(
            "CLEANUP: hanya akun QC yang dibuat tes dihapus; akun pengguna tidak diubah.",
            flush=True,
        )
        if code:
            print("Catatan: room QC tersisa di memori sampai restart backend: " + code, flush=True)


if __name__ == "__main__":
    main()
