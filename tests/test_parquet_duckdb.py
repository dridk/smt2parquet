"""Tests DuckDB : les colonnes lft/rgt sont requêtables sans guillemets.

C'est l'objet du renommage left/right -> lft/rgt : éviter la collision avec les
mots-clés SQL LEFT/RIGHT. On le vérifie en lançant `SELECT lft, rgt FROM '...'`
directement (sans quoting) via DuckDB.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from smt2parquet import core

REPO_ROOT = Path(__file__).resolve().parent.parent
PARQUET_DIR = REPO_ROOT / "parquet"
PARQUET_FILES = sorted(PARQUET_DIR.glob("*.parquet")) if PARQUET_DIR.is_dir() else []


@pytest.fixture
def written_parquet(sample_tree, tmp_path) -> Path:
    """Écrit un petit parquet via le pipeline réel (build + write)."""
    edges, code_of, root = sample_tree
    df = core.build_nested_set(edges, root=root, code_of=code_of).sort("lft")
    out = tmp_path / "sample.parquet"
    core.write_parquet_with_metadata(df, out, {"terminology": "sample"})
    return out


def test_select_lft_rgt_unquoted(written_parquet):
    """SELECT lft, rgt sans guillemets fonctionne (pas de collision SQL)."""
    con = duckdb.connect()
    rows = con.execute(
        f"SELECT lft, rgt FROM '{written_parquet.as_posix()}' ORDER BY lft"
    ).fetchall()
    assert rows  # non vide
    # rgt strictement > lft sur chaque ligne.
    assert all(rgt > lft for lft, rgt in rows)


def test_between_query_descendants(written_parquet):
    """Requête nested set typique : descendants via BETWEEN sur lft/rgt."""
    con = duckdb.connect()
    f = written_parquet.as_posix()
    descendants = con.execute(
        f"""
        WITH a AS (SELECT lft, rgt FROM '{f}' WHERE node = 'A')
        SELECT t.node
        FROM '{f}' t, a
        WHERE t.lft BETWEEN a.lft AND a.rgt
        ORDER BY t.lft
        """
    ).fetchall()
    # A et ses descendants A1, A2.
    assert [n for (n,) in descendants] == ["A", "A1", "A2"]


@pytest.mark.skipif(not PARQUET_FILES, reason="aucun parquet généré dans parquet/")
@pytest.mark.parametrize("path", PARQUET_FILES, ids=lambda p: p.name)
def test_produced_parquets_queryable(path):
    """Chaque parquet produit répond à `SELECT lft, rgt` sans guillemets."""
    con = duckdb.connect()
    f = path.as_posix()
    rows = con.execute(f"SELECT lft, rgt FROM '{f}'").fetchall()
    assert rows, f"{path.name} est vide"
    assert all(rgt > lft for lft, rgt in rows), f"{path.name}: rgt <= lft"
