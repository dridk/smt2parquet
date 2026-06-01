"""CIM10 (ICD-10) terminology conversion."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from smt2parquet import core

BASE_URI = "http://data.esante.gouv.fr/atih/cim10"
RDF_FILENAME_PREFIX = "terminologie-cim-10-"
TERMINOLOGY_NAME = "cim10"
SOURCE = "CIM-10 FR PMSI"
SOURCE_URL = "https://smt.esante.gouv.fr/terminologie-cim-10/"
LICENSE = "CC BY-NC-ND 3.0 IGO"

EDGES_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?parent ?child WHERE {
    ?child rdfs:subClassOf ?parent .
}
"""

ATTRS_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX xkos: <http://rdf-vocabulary.ddialliance.org/xkos#>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX atih-cim10: <http://data.esante.gouv.fr/atih-cim10#>
SELECT ?concept ?code ?label ?type ?synonyme ?inclusion_note
       ?exclusion_note ?exclusion_code WHERE {
    ?concept skos:notation ?code .
    ?concept rdfs:label ?label .
    ?concept dc:type ?type .
    OPTIONAL { ?concept skos:altLabel ?synonyme . }
    OPTIONAL { ?concept xkos:inclusionNote ?inclusion_note . }
    OPTIONAL { ?concept xkos:exclusionNote ?exclusion_note . }
    OPTIONAL { ?concept atih-cim10:exclusion [ skos:notation ?exclusion_code ] . }
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
        pl.col("synonyme").drop_nulls().unique().alias("synonymes"),
        pl.col("inclusion_note").first(),
        pl.col("exclusion_note").first(),
        pl.col("exclusion_code").drop_nulls().unique().sort().alias("exclusion_codes"),
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
            "depth",
            "lft",
            "rgt",
            "path",
            "synonymes",
            "inclusion_note",
            "exclusion_note",
            "exclusion_codes",
            core.keywords_expr(joined, ["label", "synonymes"], code="code"),
        )
        .sort("lft")
    )

    metadata = {
        "terminology": TERMINOLOGY_NAME,
        "version": version,
        "source_file": rdf_path.name,
        "source": SOURCE,
        "url": SOURCE_URL,
        "license": LICENSE,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    core.write_parquet_with_metadata(df, out_path, metadata)
