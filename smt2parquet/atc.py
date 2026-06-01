"""ATC (Classification Anatomique, Therapeutique et Chimique) conversion."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from smt2parquet import core

# Le RDF a DEUX racines sous owl:Thing : `.../atc/ATC` (classification vivante)
# et `.../atc/Concept_retirés` (arbre administratif des concepts retirés). On
# prend owl:Thing comme racine virtuelle (include_root=False) pour inclure les
# deux arbres ; les nœuds ombrelles deviennent depth 0.
BASE_URI = "http://www.w3.org/2002/07/owl#Thing"
RDF_FILENAME_PREFIX = "terminologie-atc-"
TERMINOLOGY_NAME = "atc"

# subClassOf direct. Pas de filtre : ATC est un arbre propre (1 parent/nœud).
# Les arêtes `ATC subClassOf owl:Thing` et `Concept_retirés subClassOf owl:Thing`
# sont les racines.
EDGES_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?parent ?child WHERE {
    ?child rdfs:subClassOf ?parent .
}
"""

# Notation requise (pour que les nœuds ombrelles aient un code → path propre).
# Label bilingue dans le source : on ne garde que le fr. type/status optionnels
# (absents sur les nœuds ombrelles ATC/Concept_retirés).
ATTRS_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX dc:   <http://purl.org/dc/elements/1.1/>
PREFIX adms: <http://www.w3.org/ns/adms#>
SELECT ?concept ?code ?label ?type ?status WHERE {
    ?concept skos:notation ?code .
    OPTIONAL { ?concept rdfs:label ?label . FILTER (lang(?label) = "fr") }
    OPTIONAL { ?concept dc:type ?type . }
    OPTIONAL { ?concept adms:status ?status . }
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
        pl.col("type").first(),
        pl.col("status").first(),
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
            "type",
            "status",
            "depth",
            "lft",
            "rgt",
            "path",
            core.keywords_expr(joined, ["label"], code="code"),
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
