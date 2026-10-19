from app import db

from .conftest import login


def test_pages_need_login(client):
    for path in ("/", "/week/1", "/results"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"


def test_wrong_password(client):
    r = login(client, password="nope")
    assert r.status_code == 401
    assert "password don&#39;t match" in r.text


def test_landing_page_is_current_week(client):
    assert login(client).status_code == 303
    r = client.get("/", follow_redirects=False)
    assert r.headers["location"] == "/week/2"
    page = client.get("/week/2")
    assert "Week 2" in page.text and "LAR" in page.text and "Live" in page.text


def test_pick_open_game_and_change_it(client, synced):
    login(client)
    r = client.post("/pick", data={"game_id": "203", "pick": "home"}, headers={"Accept": "application/json"})
    assert r.json()["ok"]
    r = client.post("/pick", data={"game_id": "203", "pick": "away"}, headers={"Accept": "application/json"})
    assert r.json()["ok"]
    with db.session(synced) as conn:
        rows = conn.execute("SELECT pick FROM picks WHERE game_id = '203'").fetchall()
    assert [row["pick"] for row in rows] == ["away"]


def test_started_and_past_games_are_locked(client):
    login(client)
    for game_id in ("101", "202"):  # final, and in progress
        r = client.post("/pick", data={"game_id": game_id, "pick": "home"}, headers={"Accept": "application/json"})
        assert r.status_code == 409 and "locked" in r.json()["error"]


def test_form_post_without_javascript(client):
    login(client)
    r = client.post("/pick", data={"game_id": "203", "pick": "home"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/week/2#game-203"


def test_other_players_pick_is_visible(client):
    login(client, "tomas@example.com", "password-two")
    client.post("/pick", data={"game_id": "203", "pick": "home"})
    client.post("/logout")
    login(client)
    assert "Tomas picked the Sf" in client.get("/week/2").text


def test_results_counts_correct_picks(client, synced):
    # Picks placed directly: in real life they were made before kickoff.
    with db.session(synced) as conn:
        ids = {r["email"]: r["id"] for r in conn.execute("SELECT id, email FROM users")}
        f, t = ids["filip@example.com"], ids["tomas@example.com"]
        rows = [
            (f, "101", "home"), (f, "102", "away"), (f, "103", "home"),  # 2 right, tie is a miss
            (t, "101", "away"), (t, "102", "away"),                       # 1 right, 1 missing
            (f, "201", "home"), (t, "201", "away"),
        ]
        conn.executemany(
            "INSERT INTO picks (user_id, game_id, pick, picked_at) VALUES (?, ?, ?, '2026-01-01')", rows
        )
    from app import picks

    with db.session(synced) as conn:
        table = picks.standings(conn, 2026)
    week1 = table["weeks"][0]
    assert week1["correct"] == {f: 2, t: 1} and week1["graded"] == 3 and week1["leader"] == f
    week2 = table["weeks"][1]
    assert week2["correct"] == {f: 0, t: 1} and week2["graded"] == 1
    assert table["totals"] == {f: 2, t: 2}

    login(client)
    page = client.get("/results")
    assert page.status_code == 200 and "Week 1" in page.text and "Tomas" in page.text
