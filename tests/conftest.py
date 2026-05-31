"""Fixtures partagées pour la suite de tests."""
from __future__ import annotations

import pytest


@pytest.fixture
def sample_tree() -> tuple[list[tuple[str, str]], dict[str, str], str]:
    """Petit arbre synthétique pour exercer build_nested_set sans RDF.

        R (racine virtuelle, exclue par défaut)
        ├── A
        │   ├── A1
        │   └── A2
        └── B
            └── B1

    Retourne (edges, code_of, root).
    """
    root = "R"
    edges = [
        ("R", "A"),
        ("R", "B"),
        ("A", "A1"),
        ("A", "A2"),
        ("B", "B1"),
    ]
    # R est virtuel (absent de code_of) — comme la racine CIM10.
    code_of = {"A": "A", "B": "B", "A1": "A1", "A2": "A2", "B1": "B1"}
    return edges, code_of, root
