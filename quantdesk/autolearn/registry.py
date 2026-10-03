"""The champion / challenger registry: durable, content-addressed, audited, fail-closed.

    registry/models/<model_id>/artifact.json   the fitted pipeline (models.Pipeline.artifact), hashed
    registry/models/<model_id>/card.json       the model card (below)
    registry/events.jsonl                      every register / evaluate / promote / reject / rollback, hash-chained
    registry/state.json                        champion, rollback target, challengers: derived from the events and
                                               rebuildable from them (`rebuild_state`)

A model id is `<name>-<artifact sha[:10]>`, so registering the same fit twice changes nothing. A card holds: model_id,
name, kind, params, code_fingerprint, feature_version, label_version, data_fingerprint, training_window, validation
(fold layout hash, folds, metrics, intervals, gates), lockbox, paper results, status, approval, rollback_target.

Promotion is fail-closed: the artifact must verify, the card must be complete, and every promotion gate must have
passed, or `promote` raises and nothing changes. The champion it replaces becomes the rollback target, and its files
are never pruned while it is one. Retraining only ever adds challengers.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pandas as pd

from .models import ArtifactError, Pipeline
from .store import ChainLog, read_json, write_json

CARD_FIELDS = ("model_id", "name", "kind", "params", "code_fingerprint", "feature_version", "label_version",
               "data_fingerprint", "training_window", "validation", "artifacts", "status")


def code_fingerprint() -> str:
    """The learning code and the feature code a model depends on."""
    root = Path(__file__).resolve().parents[1]
    files = sorted((root / "autolearn").glob("*.py")) + [root / "intraday" / "quant.py"]
    h = hashlib.sha256()
    for p in files:
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


class PromotionRefused(RuntimeError):
    pass


class Registry:
    def __init__(self, root: Path):
        self.root = Path(root) / "registry"
        self.models = self.root / "models"
        self.events = ChainLog(self.root / "events.jsonl")
        self.state_path = self.root / "state.json"

    # ---- state ----------------------------------------------------------------------------------------------------
    def state(self) -> dict:
        st = read_json(self.state_path)
        return st if isinstance(st, dict) else self.rebuild_state()

    def rebuild_state(self) -> dict:
        """Replay the event log (the source of truth) into state.json."""
        st = {"champion": None, "rollback_target": None, "challengers": [], "rejected": [], "retired": [],
              "last_event": None}
        for e in self.events.read():
            mid, ev = e.get("model_id"), e.get("event")
            if ev == "registered" and mid not in st["challengers"] and mid != st["champion"]:
                st["challengers"].append(mid)
            elif ev == "promoted":
                if st["champion"]:
                    st["retired"].append(st["champion"])
                st["rollback_target"] = st["champion"]
                st["champion"] = mid
                st["challengers"] = [m for m in st["challengers"] if m != mid]
            elif ev == "rejected":
                st["challengers"] = [m for m in st["challengers"] if m != mid]
                if mid not in st["rejected"]:
                    st["rejected"].append(mid)
            elif ev == "rolled_back":
                if st["champion"]:
                    st["retired"].append(st["champion"])
                st["champion"], st["rollback_target"] = e.get("to"), e.get("next_rollback_target")
            st["last_event"] = {"seq": e.get("seq"), "event": ev, "at": e.get("at"), "hash": e.get("hash")}
        write_json(self.state_path, st)
        return st

    def _event(self, event: str, model_id: str | None, **kw) -> dict:
        rec = self.events.append({"event": event, "model_id": model_id, "at": str(pd.Timestamp.now(tz="Asia/Kolkata")), **kw})
        self.rebuild_state()
        return rec

    # ---- models ---------------------------------------------------------------------------------------------------
    def card(self, model_id: str) -> dict | None:
        return read_json(self.models / model_id / "card.json")

    def load(self, model_id: str) -> Pipeline:
        """The verified pipeline; raises ArtifactError when anything doesn't check out."""
        card = self.card(model_id)
        art = read_json(self.models / model_id / "artifact.json")
        if not card or not art:
            raise ArtifactError(f"{model_id}: card or artifact missing")
        missing = [k for k in CARD_FIELDS if k not in card]
        if missing:
            raise ArtifactError(f"{model_id}: card incomplete ({', '.join(missing)})")
        return Pipeline.from_artifact(art, expect_sha=card["artifacts"]["artifact.json"])

    def register(self, pipe: Pipeline, card: dict) -> tuple[str, bool]:
        """Store a challenger (idempotent). Returns (model_id, newly registered)."""
        art = pipe.artifact()
        mid = f"{pipe.name}-{art['sha256'][:10]}"
        d = self.models / mid
        if (d / "card.json").exists():
            return mid, False
        card = {**card, "model_id": mid, "name": pipe.name, "kind": pipe.spec["kind"], "params": pipe.spec,
                "artifacts": {"artifact.json": art["sha256"]}, "status": "challenger", "approval": None,
                "rollback_target": None, "paper": card.get("paper") or {}}
        missing = [k for k in CARD_FIELDS if k not in card]
        if missing:
            raise ValueError(f"card for {mid} lacks {missing}")
        write_json(d / "artifact.json", art)
        write_json(d / "card.json", card)
        self._event("registered", mid, gates=card.get("validation", {}).get("passed"))
        return mid, True

    def update_card(self, model_id: str, **fields) -> dict:
        card = self.card(model_id) or {}
        card.update(fields)
        write_json(self.models / model_id / "card.json", card)
        return card

    def champion(self) -> tuple[str | None, Pipeline | None, str | None]:
        """(model_id, pipeline, fault). fault is set when a champion is on record but can't be trusted."""
        mid = self.state().get("champion")
        if not mid:
            return None, None, None
        try:
            return mid, self.load(mid), None
        except (ArtifactError, OSError, ValueError, KeyError) as exc:
            return mid, None, f"champion {mid} failed verification: {exc}"

    def challengers(self) -> list[str]:
        return list(self.state().get("challengers") or [])

    # ---- lifecycle ------------------------------------------------------------------------------------------------
    def promote(self, model_id: str, reason: str, checks: dict) -> dict:
        if not checks or not all(bool(v) for v in checks.values()):
            failed = [k for k, v in (checks or {}).items() if not v] or ["no gate results"]
            self._event("promotion_refused", model_id, reason="gates not all passed", failed=failed)
            raise PromotionRefused(f"{model_id}: gates failed: {', '.join(failed)}")
        st = self.state()
        if model_id not in st.get("challengers", []):
            raise PromotionRefused(f"{model_id} is not a registered challenger")
        try:
            self.load(model_id)
        except ArtifactError as exc:
            self._event("promotion_refused", model_id, reason=str(exc))
            raise PromotionRefused(str(exc)) from exc
        prev = st.get("champion")
        self.update_card(model_id, status="champion", rollback_target=prev,
                         approval={"by": "autolearn promotion gates", "reason": reason, "checks": checks,
                                   "at": str(pd.Timestamp.now(tz="Asia/Kolkata"))})
        if prev:
            self.update_card(prev, status="retired")
        return self._event("promoted", model_id, reason=reason, checks=checks, previous=prev)

    def reject(self, model_id: str, reason: str, detail: dict | None = None) -> dict:
        self.update_card(model_id, status="rejected", approval={"by": "autolearn", "reason": reason, "detail": detail or {}})
        return self._event("rejected", model_id, reason=reason, detail=detail or {})

    def note(self, model_id: str | None, event: str, **kw) -> dict:
        """An audit-only event (an evaluation, a deferral)."""
        return self._event(event, model_id, **kw)

    def rollback(self, reason: str) -> dict:
        """Champion → the previous champion (verified first). Fails closed if there is none or it doesn't verify."""
        st = self.state()
        cur, prev = st.get("champion"), st.get("rollback_target")
        if not prev:
            raise PromotionRefused("no rollback target on record")
        self.load(prev)
        nxt = (self.card(prev) or {}).get("rollback_target")
        self.update_card(prev, status="champion")
        if cur:
            self.update_card(cur, status="retired")
        return self._event("rolled_back", cur, to=prev, next_rollback_target=nxt, reason=reason)

    def verify(self) -> list[str]:
        bad = self.events.verify()
        st = self.rebuild_state() if not bad else self.state()
        for mid in [st.get("champion"), st.get("rollback_target"), *st.get("challengers", [])]:
            if mid:
                try:
                    self.load(mid)
                except (ArtifactError, OSError, ValueError, KeyError) as exc:
                    bad.append(f"{mid}: {exc}")
        return bad

    def prune(self, keep_rejected: int = 20) -> list[str]:
        """Delete the files of old rejected / retired models (never the champion, its rollback target, or challengers)."""
        st = self.state()
        protect = {st.get("champion"), st.get("rollback_target"), *st.get("challengers", [])}
        old = [m for m in st.get("rejected", []) + st.get("retired", []) if m not in protect]
        gone = []
        for mid in old[:-keep_rejected] if keep_rejected else old:
            d = self.models / mid
            if d.exists():
                shutil.rmtree(d)
                gone.append(mid)
        if gone:
            self._event("pruned", None, models=gone)
        return gone
