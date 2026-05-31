"""Generic helpers for SMT terminology -> Parquet conversion."""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import rdflib

log = logging.getLogger(__name__)


def load_graph(path: Path) -> rdflib.Graph:
    log.info("Loading RDF graph from %s", path)
    g = rdflib.Graph()
    g.parse(path.absolute())
    log.info("Loaded %d triples", len(g))
    return g


def extract_version(rdf_path: Path, prefix: str) -> str:
    stem = rdf_path.stem
    if not stem.startswith(prefix):
        raise ValueError(
            f"RDF filename {stem!r} does not start with prefix {prefix!r}"
        )
    version = stem[len(prefix):]
    if not version:
        raise ValueError(f"Empty version extracted from {stem!r}")
    return version


def dataframe_from_sparql(graph: rdflib.Graph, sparql: str) -> pl.DataFrame:
    log.info("Running SPARQL query (%d chars)", len(sparql))
    records = graph.query(sparql)
    if records is None or records.vars is None:
        raise ValueError(f"No records from SPARQL query: {sparql}")
    columns = [str(v) for v in records.vars]
    rows: list[dict[str, str | None]] = []
    for rec in records:
        if not isinstance(rec, tuple):
            raise TypeError(
                f"Expected tuple rows from SELECT, got {type(rec).__name__}"
            )
        row: dict[str, str | None] = {}
        for i, val in enumerate(rec):
            row[columns[i]] = None if val is None else str(val)
        rows.append(row)
    schema = {c: pl.String for c in columns}
    if not rows:
        return pl.DataFrame(schema=schema)
    df = pl.DataFrame(rows, schema=schema)
    log.info("Got %d rows", len(df))
    return df


def build_nested_set(
    edges: Iterable[tuple[str, ...]],
    root: str,
    code_of: Mapping[str, str],
    *,
    include_root: bool = False,
    path_sep: str = "/",
) -> pl.DataFrame:
    children: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        parent, child = edge[0], edge[1]
        children[parent].append(child)

    children_sorted: dict[str, list[str]] = {
        parent: sorted(kids, key=lambda u: code_of.get(u, u))
        for parent, kids in children.items()
    }

    rows: list[dict[str, object]] = []
    counter = [0]
    active: set[str] = set()
    path_stack: list[str] = []

    def dfs(node: str, depth: int) -> None:
        if node in active:
            raise ValueError(f"Cycle detected at node {node!r}")
        active.add(node)
        counter[0] += 1
        lft = counter[0]
        node_code = code_of.get(node, node)
        path_stack.append(node_code)

        for child in children_sorted.get(node, []):
            dfs(child, depth + 1)

        counter[0] += 1
        rgt = counter[0]
        rows.append({
            "node": node,
            "lft": lft,
            "rgt": rgt,
            "depth": depth,
            "path": path_sep.join(path_stack),
        })
        path_stack.pop()
        active.discard(node)

    if include_root:
        dfs(root, 0)
    else:
        for child in children_sorted.get(root, []):
            dfs(child, 0)

    log.info("Built nested set with %d rows", len(rows))
    return pl.DataFrame(
        rows,
        schema={
            "node": pl.String,
            "lft": pl.Int64,
            "rgt": pl.Int64,
            "depth": pl.Int64,
            "path": pl.String,
        },
    )


def write_parquet_with_metadata(
    df: pl.DataFrame, out_path: Path, metadata: dict[str, str]
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table = df.to_arrow()
    existing = dict(table.schema.metadata or {})
    encoded = {k.encode(): v.encode() for k, v in metadata.items()}
    existing.update(encoded)
    table = table.replace_schema_metadata(existing)
    pq.write_table(table, out_path)
    log.info("Wrote %s (%d rows)", out_path, len(df))
