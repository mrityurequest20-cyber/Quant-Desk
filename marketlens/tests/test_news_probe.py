"""News P0 probe: reports, never raises, never prints the key."""
from marketlens.news import probe as P


def test_key_check_without_a_key_reports_and_does_not_raise(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert P.key_check() == {"ok": False, "why": "ANTHROPIC_API_KEY is not set in this job"}


def test_key_check_never_echoes_the_key(monkeypatch):
    secret = "sk-ant-test-" + "x" * 40
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")        # nothing listens: a connection error
    out = P.key_check()
    assert out["ok"] is False and secret not in repr(out)
