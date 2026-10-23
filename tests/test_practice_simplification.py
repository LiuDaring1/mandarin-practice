"""Short rounds must settle correctly and never submit paid reading requests by default."""
from pth_corpus.prototype_app import PrototypeRuntime
from test_assessment import wav
from test_prototype_app import _make_fixture


def test_local_recording_never_reads_credentials_or_calls_provider(tmp_path, monkeypatch):
    data_root, client, _ = _make_fixture(tmp_path)
    def forbidden(*args):
        raise AssertionError("Local-only practice touched the cloud provider")
    monkeypatch.setattr(client.app.state.assessment, "settings", forbidden)
    monkeypatch.setattr("pth_corpus.assessment.evaluate", forbidden)
    with client:
        status = client.get("/api/assessment/status").json()
        assert status["recording_required"] is True
        assert status["cloud_enabled"] is False
        assert status["available"] is False
        params = dict(attempt_id="attempt-one", session_id="session-one")
        for url in ("/api/reading/attempts/word/t1-00001", "/api/assessment/word/t1-00001"):
            assert client.post(url, params=params, content=wav()).status_code == 503
        assert client.get("/api/reading/session/session-one").json()["submitted"] == 0
    assert not (data_root / "derived/assessment/usage.json").exists()
    assert not list(data_root.rglob("attempt-one.json"))


def test_short_word_round_generates_and_short_tiers_settle(tmp_path):
    _, client, _ = _make_fixture(tmp_path)
    with client:
        home = client.get("/api/home").json()
        assert home["durations"] == [3, 5]
        assert home["default_duration_minutes"] == 3
        session = client.post("/api/sessions", json={"profile_id": "bilabial_focus", "duration_minutes": 3})
        assert session.status_code == 201 and session.json()["items"]
        for ratio, expected in ((1, 360), (.5, 180), (.1, 0)):
            response = client.post("/api/achievement/settle", json={
                "activity": "word", "planned_duration_minutes": 3, "completion_ratio": ratio})
            assert response.status_code == 200
            assert response.json()["total_beads"] == expected
        for completed, expected in ((5, 300), (3, 180), (0, 0)):
            response = client.post("/api/achievement/settle", json={
                "activity": "sentence", "sentence_count": 5, "completed_sentence_count": completed})
            assert response.status_code == 200
            assert response.json()["total_beads"] == expected


def test_formal_pool_does_not_load_published_news(tmp_path, monkeypatch):
    import json
    from test_news_sentences import row
    release = tmp_path / "derived/news-sentence-v1/release.json"
    release.parent.mkdir(parents=True)
    release.write_text(json.dumps({"version": 1, "count": 1, "sentences": [row(1, "news")]}))
    literature = [row(i, "literature") for i in range(10)]
    monkeypatch.setattr("pth_corpus.prototype_app.load_sentence_pool", lambda *a, **k: literature)
    def forbidden(*a, **k):
        raise AssertionError("Formal practice loaded held news")
    monkeypatch.setattr("pth_corpus.news_sentences.load_news_pool", forbidden)
    runtime = PrototypeRuntime(tmp_path)
    assert runtime.sentence_pool() == literature
    assert release.exists()
