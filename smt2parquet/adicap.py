"""ADICAP terminology conversion."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from smt2parquet import core

# Racine org réelle (subClassOf owl:Thing). Avec include_root=False (défaut),
# le DFS part de ses enfants : les dictionnaires D1..D8 sont à depth 0.
BASE_URI = "https://data.esante.gouv.fr/adicap/ADICAP"
RDF_FILENAME_PREFIX = "terminologie-adicap-"
TERMINOLOGY_NAME = "adicap"

# subClassOf direct. Pas de filtre blank node : ADICAP est un arbre propre.
# L'arête `ADICAP subClassOf owl:Thing` est inoffensive (owl:Thing jamais visité).
EDGES_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?parent ?child WHERE {
    ?child rdfs:subClassOf ?parent .
}
"""

# `j.1:` dans le RDF source = namespace ADICAP. anatomy pointe vers un autre
# concept ADICAP dont on résout notation + label (pattern CCAM topographie).
ATTRS_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX adicap: <https://data.esante.gouv.fr/adicap/>
SELECT ?concept ?code ?label ?dictionary_code ?anatomy_code ?anatomy_label WHERE {
    ?concept skos:notation ?code .
    ?concept rdfs:label ?label .
    OPTIONAL { ?concept adicap:dictionaryCode ?dictionary_code . }
    OPTIONAL {
        ?concept adicap:anatomy ?anat_uri .
        OPTIONAL { ?anat_uri skos:notation ?anatomy_code . }
        OPTIONAL { ?anat_uri rdfs:label   ?anatomy_label . }
    }
}
"""


def convert(rdf_path: Path, out_path: Path) -> None:
    version = core.extract_version(rdf_path, RDF_FILENAME_PREFIX)
    graph = core.load_graph(rdf_path)

    edges_df = core.dataframe_from_sparql(graph, EDGES_QUERY)
    attrs_df = core.dataframe_from_sparql(graph, ATTRS_QUERY)

    attrs_agg = attrs_df.group_by("concept").agg(
        pl.col("code").first(),
        pl.col("label").first(),
        pl.col("dictionary_code").first(),
        pl.col("anatomy_code").first(),
        pl.col("anatomy_label").first(),
    )

    code_of = dict(
        zip(attrs_agg["concept"].to_list(), attrs_agg["code"].to_list())
    )

    nested = core.build_nested_set(
        edges_df.iter_rows(),
        root=BASE_URI,
        code_of=code_of,
    )

    joined = nested.join(
        attrs_agg, left_on="node", right_on="concept", how="left"
    )
    df = (
        joined.select(
            "code",
            "label",
            "dictionary_code",
            "depth",
            "lft",
            "rgt",
            "path",
            "anatomy_code",
            "anatomy_label",
            core.keywords_expr(joined, ["label", "anatomy_label"], code="code"),
        )
        .sort("lft")
    )

    metadata = {
        "terminology": TERMINOLOGY_NAME,
        "version": version,
        "source_file": rdf_path.name,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    core.write_parquet_with_metadata(df, out_path, metadata)
