"""Provenance (research/provenance.py): a result names the code commit and digests the exact data files it read."""
from quantdesk.research import provenance as P


def test_the_digest_changes_with_the_bytes_and_only_then(tmp_path):
    (tmp_path / "fo_bhav_2024-01.parquet").write_bytes(b"abc")
    (tmp_path / "fo_bhav_2024-02.parquet").write_bytes(b"def")
    a = P.data_digest(tmp_path, ["fo_bhav_*.parquet", "bse_fo_bhav_*.parquet"])
    assert a["fo_bhav_*.parquet"]["files"] == 2 and a["bse_fo_bhav_*.parquet"] == {"files": 0, "digest": None}
    assert P.data_digest(tmp_path, ["fo_bhav_*.parquet"])["fo_bhav_*.parquet"] == a["fo_bhav_*.parquet"]   # stable
    (tmp_path / "fo_bhav_2024-02.parquet").write_bytes(b"deg")
    assert P.data_digest(tmp_path, ["fo_bhav_*.parquet"])["fo_bhav_*.parquet"]["digest"] != a["fo_bhav_*.parquet"]["digest"]


def test_the_stamp_names_a_commit():
    s = P.stamp(P.ROOT, [])
    assert s["code"]["commit"] and len(s["code"]["commit"]) == 12 and isinstance(s["code"]["dirty"], bool)
