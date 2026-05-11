"""CLI entry point: python -m smt2parquet <terminology>."""
from __future__ import annotations

import argparse
import importlib
import logging
import sys
from pathlib import Path

from smt2parquet import core

TERMINOLOGIES: dict[str, dict[str, str]] = {
    "cim10": {
        "module": "smt2parquet.cim10",
        "rdf_glob": "rdf/terminologie-cim-10-*.rdf",
        "out_dir": "parquet",
    },
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smt2parquet")
    parser.add_argument("terminology", choices=sorted(TERMINOLOGIES))
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    spec = TERMINOLOGIES[args.terminology]

    rdf_matches = sorted(Path().glob(spec["rdf_glob"]))
    if not rdf_matches:
        print(f"No RDF file matching {spec['rdf_glob']!r}", file=sys.stderr)
        return 1
    if len(rdf_matches) > 1:
        print(
            f"Multiple RDF files match {spec['rdf_glob']!r}: "
            f"{[str(p) for p in rdf_matches]}",
            file=sys.stderr,
        )
        return 1
    rdf_path = rdf_matches[0]

    module = importlib.import_module(spec["module"])
    version = core.extract_version(rdf_path, module.RDF_FILENAME_PREFIX)
    out_path = Path(spec["out_dir"]) / f"{args.terminology}-{version}.parquet"

    module.convert(rdf_path, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
