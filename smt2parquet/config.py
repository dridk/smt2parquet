"""Centralized configuration for smt2parquet."""
from __future__ import annotations

from typing import TypedDict


class TerminologyConfig(TypedDict):
    """Configuration for a single terminology."""

    module: str
    rdf_glob: str
    out_dir: str
    filename_prefix: str


TERMINOLOGIES: dict[str, TerminologyConfig] = {
    "cim10": {
        "module": "smt2parquet.cim10",
        "rdf_glob": "terminologie-cim-10-*.rdf",
        "out_dir": "parquet",
        "filename_prefix": "terminologie-cim-10-",
    },
    "ccam": {
        "module": "smt2parquet.ccam",
        "rdf_glob": "terminologie-ccam-*.rdf",
        "out_dir": "parquet",
        "filename_prefix": "terminologie-ccam-",
    },
}
