"""Fail CI when an Actions workflow lacks explicit permissions or immutable action pins."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"^[0-9a-f]{40}$")


def check(path: Path) -> list[str]:
    errors = []
    try:
        workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    except (OSError, yaml.YAMLError) as exc:
        return [f"{path.name}: invalid workflow YAML: {exc}"]
    if not isinstance(workflow, dict):
        return [f"{path.name}: workflow root must be a mapping"]
    if not isinstance(workflow.get("permissions"), dict):
        errors.append(f"{path.name}: define explicit least-privilege workflow permissions")
    jobs = workflow.get("jobs") or {}
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict) or "uses" not in step:
                continue
            ref = str(step["uses"])
            if ref.startswith("./"):
                continue
            owner_repo, sep, pin = ref.rpartition("@")
            if not sep or not owner_repo or not SHA.fullmatch(pin):
                errors.append(f"{path.name}: {job_name} uses mutable action reference {ref!r}; pin a full 40-character commit SHA")
        perms = job.get("permissions")
        if perms is not None and not isinstance(perms, dict):
            errors.append(f"{path.name}: {job_name} permissions must be an explicit mapping")
    return errors


def main() -> int:
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    errors = [error for path in workflows for error in check(path)]
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"workflow integrity: {len(workflows)} files have explicit permissions and immutable action pins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
