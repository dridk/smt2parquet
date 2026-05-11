"""CCAM (Classification Commune des Actes Medicaux) terminology conversion."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from smt2parquet import core

BASE_URI = "http://data.esante.gouv.fr/cnam/ccam/Acte"
RDF_FILENAME_PREFIX = "terminologie-ccam-"
TERMINOLOGY_NAME = "ccam"

# Direct subClassOf edges, restricted to nodes with a notation (skips OWL
# blank-node restrictions like <rdfs:subClassOf rdf:nodeID="..."/>).
EDGES_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?parent ?child WHERE {
    ?child rdfs:subClassOf ?parent .
    ?child skos:notation ?_c .
    FILTER (!isBlank(?parent))
}
"""

ATTRS_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX xkos: <http://rdf-vocabulary.ddialliance.org/xkos#>
PREFIX ccam: <http://data.esante.gouv.fr/cnam/ccam/>
SELECT ?concept ?code ?label ?synonyme ?inclusion_note ?exclusion_note
       ?definition ?topographie ?type_acte ?mode_acces ?action WHERE {
    ?concept skos:notation ?code .
    ?concept rdfs:label ?label .
    OPTIONAL { ?concept skos:altLabel ?synonyme . }
    OPTIONAL { ?concept xkos:inclusionNote ?inclusion_note . }
    OPTIONAL { ?concept xkos:exclusionNote ?exclusion_note . }
    OPTIONAL { ?concept skos:definition ?definition . }
    OPTIONAL { ?concept ccam:topographie ?t_uri . ?t_uri rdfs:label ?topographie . }
    OPTIONAL { ?concept ccam:typeActe    ?ta_uri . ?ta_uri rdfs:label ?type_acte . }
    OPTIONAL { ?concept ccam:modeAcces   ?ma_uri . ?ma_uri rdfs:label ?mode_acces . }
    OPTIONAL { ?concept ccam:action      ?a_uri . ?a_uri rdfs:label ?action . }
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
        pl.col("synonyme").drop_nulls().unique().alias("synonymes"),
        pl.col("inclusion_note").first(),
        pl.col("exclusion_note").first(),
        pl.col("definition").first(),
        pl.col("topographie").first(),
        pl.col("type_acte").first(),
        pl.col("mode_acces").first(),
        pl.col("action").first(),
    ).with_columns(
        # Source-data quirk: chapters Categorie_13..Categorie_18 have
        # skos:notation = "Categorie_NN" instead of just "NN".
        pl.col("code").str.replace(r"^Categorie_", "")
    )

    code_of = dict(
        zip(attrs_agg["concept"].to_list(), attrs_agg["code"].to_list())
    )

    nested = core.build_nested_set(
        edges_df.iter_rows(),
        root=BASE_URI,
        code_of=code_of,
    )

    df = (
        nested.join(attrs_agg, left_on="node", right_on="concept", how="left")
        .select(
            "code",
            "label",
            "depth",
            "left",
            "right",
            "path",
            "synonymes",
            "inclusion_note",
            "exclusion_note",
            "definition",
            "topographie",
            "type_acte",
            "mode_acces",
            "action",
        )
        .sort("left")
    )

    metadata = {
        "terminology": TERMINOLOGY_NAME,
        "version": version,
        "source_file": rdf_path.name,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    core.write_parquet_with_metadata(df, out_path, metadata)
