"""Tests unitaires de core.keywords_expr (normalisation texte, hors RDF)."""
from __future__ import annotations

import polars as pl

from smt2parquet import core


def _keywords(df: pl.DataFrame, columns: list[str]) -> list[str]:
    return df.with_columns(core.keywords_expr(df, columns))["keywords"].to_list()


def test_concat_str_and_list():
    """Concatène une colonne str et une colonne list[str] (synonymes)."""
    df = pl.DataFrame(
        {"label": ["Diabete"], "synonymes": [["sucre", "glycemie"]]},
        schema={"label": pl.String, "synonymes": pl.List(pl.String)},
    )
    assert _keywords(df, ["label", "synonymes"]) == ["diabete glycemie sucre"]


def test_lowercase_and_accents():
    """Minuscules + suppression des accents et des ligatures (œ -> oe)."""
    df = pl.DataFrame({"label": ["Côlon Œsophage Cœur Tête"]})
    assert _keywords(df, ["label"]) == ["coeur colon oesophage tete"]


def test_token_dedup():
    """Un token partagé entre label et synonyme n'apparaît qu'une fois."""
    df = pl.DataFrame(
        {"label": ["cancer du colon"], "synonymes": [["tumeur colon"]]},
        schema={"label": pl.String, "synonymes": pl.List(pl.String)},
    )
    assert _keywords(df, ["label", "synonymes"]) == ["cancer colon du tumeur"]


def test_all_null_sources_give_empty_string():
    """Aucune source -> chaîne vide (pas de null, pas de 'None')."""
    df = pl.DataFrame(
        {"label": [None], "synonymes": [None]},
        schema={"label": pl.String, "synonymes": pl.List(pl.String)},
    )
    result = _keywords(df, ["label", "synonymes"])
    assert result == [""]


def test_punctuation_becomes_separator():
    """La ponctuation est transformée en séparateur de tokens."""
    df = pl.DataFrame({"label": ["foie/rate (lobe)"]})
    assert _keywords(df, ["label"]) == ["foie lobe rate"]
