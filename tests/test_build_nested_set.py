"""Tests unitaires de core.build_nested_set (logique nested set, hors RDF)."""
from __future__ import annotations

import polars as pl
import pytest

from smt2parquet import core


def test_schema_columns(sample_tree):
    edges, code_of, root = sample_tree
    df = core.build_nested_set(edges, root=root, code_of=code_of)
    assert df.columns == ["node", "lft", "rgt", "depth", "path"]
    assert df.schema["lft"] == pl.Int64
    assert df.schema["rgt"] == pl.Int64


def test_exact_bounds_and_paths(sample_tree):
    """Vérifie les valeurs lft/rgt/depth/path calculées par le DFS."""
    edges, code_of, root = sample_tree
    df = core.build_nested_set(edges, root=root, code_of=code_of).sort("lft")

    expected = {
        # node: (lft, rgt, depth, path)
        "A": (1, 6, 0, "A"),
        "A1": (2, 3, 1, "A/A1"),
        "A2": (4, 5, 1, "A/A2"),
        "B": (7, 10, 0, "B"),
        "B1": (8, 9, 1, "B/B1"),
    }
    assert df.height == len(expected)
    got = {
        r["node"]: (r["lft"], r["rgt"], r["depth"], r["path"])
        for r in df.iter_rows(named=True)
    }
    assert got == expected


def test_nested_set_invariants(sample_tree):
    """Invariants génériques : rgt > lft, bornes uniques, descendants par BETWEEN."""
    edges, code_of, root = sample_tree
    df = core.build_nested_set(edges, root=root, code_of=code_of).sort("lft")

    assert (df["rgt"] > df["lft"]).all()
    # 2N nœuds visités → bornes = 1..2N toutes distinctes.
    bornes = df["lft"].to_list() + df["rgt"].to_list()
    assert sorted(bornes) == list(range(1, 2 * df.height + 1))

    # Descendants de A via l'intervalle ]lft, rgt[ : A1 et A2.
    a = df.filter(pl.col("node") == "A").row(0, named=True)
    descendants = df.filter(
        (pl.col("lft") > a["lft"]) & (pl.col("lft") < a["rgt"])
    )
    assert set(descendants["node"]) == {"A1", "A2"}
    # nb descendants = (rgt - lft - 1) / 2
    assert (a["rgt"] - a["lft"] - 1) // 2 == descendants.height


def test_include_root_exposes_root(sample_tree):
    edges, code_of, root = sample_tree
    without = core.build_nested_set(edges, root=root, code_of=code_of)
    with_root = core.build_nested_set(
        edges, root=root, code_of=code_of, include_root=True
    )
    assert "R" not in without["node"].to_list()
    assert "R" in with_root["node"].to_list()
    # La racine englobe tout l'arbre.
    r = with_root.filter(pl.col("node") == "R").row(0, named=True)
    assert r["lft"] == 1
    assert r["rgt"] == with_root["rgt"].max()


def test_multi_parent_node_is_duplicated():
    """Un nœud à plusieurs parents (DAG) apparaît une fois par parent."""
    edges = [("R", "A"), ("R", "B"), ("A", "C"), ("B", "C")]
    code_of = {"A": "A", "B": "B", "C": "C"}
    df = core.build_nested_set(edges, root="R", code_of=code_of)
    c = df.filter(pl.col("node") == "C")
    assert c.height == 2
    # Chaque occurrence a ses propres bornes / chemin.
    assert set(c["path"]) == {"A/C", "B/C"}


def test_cycle_raises():
    edges = [("R", "A"), ("A", "B"), ("B", "A")]
    code_of = {"A": "A", "B": "B"}
    with pytest.raises(ValueError, match="Cycle detected"):
        core.build_nested_set(edges, root="R", code_of=code_of)
