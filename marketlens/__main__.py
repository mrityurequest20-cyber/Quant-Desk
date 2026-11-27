"""python -m marketlens fetch --dest DIR | build --warehouse DIR --out DIR [--symbols A,B] | site --data DIR --out DIR"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="marketlens")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download the public warehouse tables")
    f.add_argument("--dest", type=Path, required=True)
    b = sub.add_parser("build", help="build the app's JSON data from a warehouse folder")
    b.add_argument("--warehouse", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--symbols", default="")
    s = sub.add_parser("site", help="assemble the static site: the web app plus a data folder")
    s.add_argument("--data", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        from .engine.data import fetch
        print(f"fetched {fetch(a.dest)} files into {a.dest}")
    elif a.cmd == "build":
        from .engine.build import build
        syms = [x.strip() for x in a.symbols.split(",") if x.strip()] or None
        ov = build(a.warehouse, a.out, syms)
        print(f"built {len(ov['screener'])} instruments, as of {ov['asof']}")
    elif a.cmd == "site":
        web = Path(__file__).parent / "web"
        if a.out.exists():
            shutil.rmtree(a.out)
        shutil.copytree(web, a.out)
        shutil.copytree(a.data, a.out / "data")
        print(f"site in {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
