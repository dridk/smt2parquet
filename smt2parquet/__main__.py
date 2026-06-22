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
        "source_glob": "rdf/terminologie-cim-10-*.rdf",
        "out_dir": "parquet",
    },
    "ccam": {
        "module": "smt2parquet.ccam",
        "source_glob": "rdf/terminologie-ccam-*.rdf",
        "out_dir": "parquet",
    },
    "adicap": {
        "module": "smt2parquet.adicap",
        "source_glob": "rdf/terminologie-adicap-*.rdf",
        "out_dir": "parquet",
    },
    "atc": {
        "module": "smt2parquet.atc",
        "source_glob": "rdf/terminologie-atc-*.rdf",
        "out_dir": "parquet",
    },
    # CSARR n'est pas dans le SMT : sa source est un fichier Excel ATIH, pas un
    # RDF. Le module csarr.py définit son propre extract_version (cf. seam plus
    # bas) et lit le .xls via pl.read_excel.
    "csarr": {
        "module": "smt2parquet.csarr",
        "source_glob": "rdf/csarr_*.xls",
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

    source_matches = sorted(Path().glob(spec["source_glob"]))
    if not source_matches:
        print(f"No source file matching {spec['source_glob']!r}", file=sys.stderr)
        return 1
    if len(source_matches) > 1:
        print(
            f"Multiple source files match {spec['source_glob']!r}: "
            f"{[str(p) for p in source_matches]}",
            file=sys.stderr,
        )
        return 1
    source_path = source_matches[0]

    module = importlib.import_module(spec["module"])
    # Seam additif : un module non-RDF (CSARR) expose son propre extract_version
    # (la version n'est pas dérivable par strip-de-préfixe d'un nom de RDF). Les
    # modules RDF restent inchangés et passent par core.extract_version.
    if hasattr(module, "extract_version"):
        version = module.extract_version(source_path)
    else:
        version = core.extract_version(source_path, module.RDF_FILENAME_PREFIX)
    out_path = Path(spec["out_dir"]) / f"{args.terminology}-{version}.parquet"

    module.convert(source_path, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
