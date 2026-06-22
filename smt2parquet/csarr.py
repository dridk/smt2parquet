"""CSARR (Catalogue Specifique des Actes de Reeducation et Readaptation).

Contrairement aux autres terminologies, le CSARR n'est pas publie sur le portail
SMT : l'ATIH le diffuse sous forme d'un classeur Excel. La hierarchie + les actes
feuilles vivent dans l'onglet `CSARR_FINAL`, une liste ordonnee top-down qui
melange :

- les noeuds de hierarchie : codes dotes `^\\d{2}(\\.\\d{2})*$` (12 chapitres `01`..`12`,
  puis 2 a 4 segments). Parent = code prive de son dernier segment ; un chapitre
  (1 segment) a pour parent la racine virtuelle ;
- les actes feuilles : codes `^[A-Z]{3}\\+\\d{3}$` (ex. `GKQ+190`). Parent = le
  dernier code dote rencontre en descendant la liste ;
- les lignes de note : code vide + texte (« Cet acte comprend : … ») rattachees
  au dernier noeud enregistre, agregees dans `inclusion_note` ;
- du bruit : ligne d'en-tete (`Hierarchie - Code`) et legende des codes
  d'extension en bas de feuille (`ZV`, `ME`, `P3`…) — ni dote ni acte, ignore.

On reconstruit donc les aretes en Python (pas de SPARQL) puis on reutilise les
briques generiques de core (`build_nested_set`, `keywords_expr`,
`write_parquet_with_metadata`).
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from smt2parquet import core

# Racine virtuelle (jamais une entite reelle) : include_root=False la masque, et
# les 12 chapitres passent a depth 0.
BASE_URI = "CSARR"
TERMINOLOGY_NAME = "csarr"
SOURCE = "CSARR"
# Classeur Excel publie directement par l'ATIH (pas dans le SMT).
SOURCE_URL = "https://www.atih.sante.fr/sites/default/files/public/content/4902/csarr_liste_analytique_2025_versioncorrigee.xls"
LICENSE = "ATIH"

SHEET_NAME = "CSARR_FINAL"

_DOTTED = re.compile(r"^\d{2}(\.\d{2})*$")
_ACT = re.compile(r"^[A-Z]{3}\+\d{3}$")


def extract_version(source_path: Path) -> str:
    """Millesime a 4 chiffres du nom de fichier (le CSARR est annuel).

    `csarr_liste_analytique_2025_versioncorrigee.xls` -> `2025`. Version `YYYY`
    et non `YYYY-MM-DD` (acceptable : CCAM produit deja `v82.00`).
    """
    match = re.search(r"(19|20)\d{2}", source_path.stem)
    if match is None:
        raise ValueError(f"No year found in CSARR filename {source_path.stem!r}")
    return match.group(0)


def _parse_rows(
    rows: list[tuple[str | None, ...]],
) -> tuple[list[tuple[str, str]], list[dict[str, object]]]:
    """Parcourt la liste top-down et produit (edges, attrs).

    `edges` : tuples `(parent_code, child_code)`. `attrs` : un dict par noeud
    (`code, label, type, inclusion_note, extensions`).
    """
    edges: list[tuple[str, str]] = []
    attrs: list[dict[str, object]] = []
    by_code: dict[str, dict[str, object]] = {}
    current_dotted: str | None = None
    last_node: dict[str, object] | None = None

    for code, raw_label, _c2, ext in rows:
        code = (code or "").strip()
        # 137 cellules d'actes empaquettent `<titre>\n\n<qualificatif>` (« Avec
        # ou sans : … », « A l'exclusion de : … ») : la 1re ligne est le libelle,
        # le reste est une note descriptive amorcant inclusion_note.
        title, _, rest = (raw_label or "").partition("\n")
        label = title.strip() or None
        seed_note = rest.strip() or None

        if _DOTTED.match(code):
            parent = code.rsplit(".", 1)[0] if "." in code else BASE_URI
            node_type = "chapitre" if "." not in code else "rubrique"
            node = {
                "code": code,
                "label": label,
                "type": node_type,
                "inclusion_note": seed_note,
                "extensions": [],
            }
            edges.append((parent, code))
            attrs.append(node)
            by_code[code] = node
            current_dotted = code
            last_node = node
        elif _ACT.match(code):
            if current_dotted is None:
                continue  # acte avant tout chapitre : ne devrait pas arriver
            tokens = [t.strip() for t in (ext or "").split(";") if t.strip()]
            node = {
                "code": code,
                "label": label,
                "type": "acte",
                "inclusion_note": seed_note,
                "extensions": tokens,
            }
            edges.append((current_dotted, code))
            attrs.append(node)
            by_code[code] = node
            last_node = node
        elif not code and label and last_node is not None:
            # Ligne de note : rattachee au dernier noeud enregistre.
            note = last_node["inclusion_note"]
            last_node["inclusion_note"] = f"{note}\n{label}" if note else label
        # sinon : en-tete / legende d'extension / separateur vide -> ignore

    return edges, attrs


def convert(source_path: Path, out_path: Path) -> None:
    version = extract_version(source_path)

    # has_header=False : la 1re ligne du classeur est du texte d'intro, pas un
    # en-tete utile. On nomme les colonnes par position.
    raw = pl.read_excel(
        source_path, sheet_name=SHEET_NAME, has_header=False
    )
    cols = raw.columns
    raw = raw.rename(
        {cols[0]: "code", cols[1]: "label", cols[2]: "c2", cols[3]: "ext"}
    ).select("code", "label", "c2", "ext")

    edges, attrs = _parse_rows(list(raw.iter_rows()))

    attrs_df = pl.DataFrame(
        attrs,
        schema={
            "code": pl.String,
            "label": pl.String,
            "type": pl.String,
            "inclusion_note": pl.String,
            "extensions": pl.List(pl.String),
        },
    )

    # Les noeuds sont deja leurs propres codes -> code_of vide (chaque noeud se
    # code lui-meme via le defaut de build_nested_set).
    nested = core.build_nested_set(edges, root=BASE_URI, code_of={})

    joined = nested.join(attrs_df, left_on="node", right_on="code", how="left")
    df = (
        joined.with_columns(pl.col("node").alias("code"))
        .select(
            "code",
            "label",
            "type",
            "depth",
            "lft",
            "rgt",
            "path",
            "inclusion_note",
            "extensions",
            core.keywords_expr(joined, ["label"], code="node"),
        )
        .sort("lft")
    )

    metadata = {
        "terminology": TERMINOLOGY_NAME,
        "version": version,
        "source_file": source_path.name,
        "source": SOURCE,
        "url": SOURCE_URL,
        "license": LICENSE,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    core.write_parquet_with_metadata(df, out_path, metadata)
