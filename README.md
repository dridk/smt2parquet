# smt2parquet

Convertit les terminologies médicales du portail [**SMT**](https://smt.esante.gouv.fr/) (Serveur Multi-Terminologies, eSanté France) — fichiers RDF — vers du **Parquet** en préservant la hiérarchie via le [**modèle d'imbrication d'ensembles**](https://fr.wikipedia.org/wiki/Imbrication_d%27ensembles) (*nested set*).

Le résultat : un Parquet par terminologie avec, pour chaque concept, les colonnes `code`, `label`, `path`, et le triplet `left`/`right`/`depth` qui permettent de requêter ancêtres et descendants par une simple comparaison d'intervalles.

## Terminologies supportées

| Nom | Fichier RDF attendu | Sortie |
|---|---|---|
| `cim10` | `rdf/terminologie-cim-10-<version>.rdf` | `parquet/cim10-<version>.parquet` |
| `ccam` | `rdf/terminologie-ccam-<version>.rdf` | `parquet/ccam-<version>.parquet` |

La `<version>` est celle du nom de fichier (`2025-01-01` pour la CIM10, `v82.00` pour la CCAM…) — elle est également écrite dans les **métadonnées du Parquet** (`terminology`, `version`, `source_file`, `generated_at`).

Récupérez les fichiers RDF depuis le portail [SMT](https://smt.esante.gouv.fr/) et placez-les dans `rdf/`.

## Installation

```bash
uv sync
```

Python ≥ 3.13. Dépendances : `polars`, `rdflib`, `pyarrow`.

## Utilisation

```bash
uv run python -m smt2parquet cim10
uv run python -m smt2parquet ccam
```

Le CLI résout le glob `rdf/terminologie-<nom>-*.rdf`, extrait la version du nom de fichier, et écrit `parquet/<nom>-<version>.parquet`.

## Schéma de sortie

Colonnes communes à toutes les terminologies :

| Colonne | Type | Description |
|---|---|---|
| `code` | `str` | Code du concept (`skos:notation`) |
| `label` | `str` | Libellé (`rdfs:label`) |
| `depth` | `i64` | Profondeur dans l'arbre (0 = racine réelle) |
| `left` | `i64` | Borne gauche du nested set |
| `right` | `i64` | Borne droite du nested set |
| `path` | `str` | Chaîne des codes des ancêtres, ex. `I/A00-A09/A00/A00.0` |
| `synonymes` | `list[str]` | `skos:altLabel` dédupliqués |
| `inclusion_note` | `str?` | `xkos:inclusionNote` |

Colonnes spécifiques :

- **CIM10** : `type` (`chapter` / `block` / `category`)
- **CCAM** : `exclusion_note`, `definition`, `topographie`, `type_acte`, `mode_acces`, `action`

Les nœuds avec plusieurs parents (DAG) sont **dupliqués** : chaque occurrence sous un parent différent reçoit son propre `left`/`right`/`depth`/`path`.

## Pourquoi nested set ?

Avec `parent_code` ou un `path` listé, retrouver tous les descendants d'un nœud demande une jointure récursive (CTE). Avec `left`/`right`, un simple `BETWEEN` suffit, et c'est indexable.

```
Pour tout nœud P, ses descendants sont les lignes où left ∈ ]P.left, P.right[
                  ses ancêtres   sont les lignes où left < P.left ET right > P.right
```

## Exemples avec DuckDB

[DuckDB](https://duckdb.org/) lit directement le Parquet sans import. Les requêtes ci-dessous tournent dans le CLI DuckDB ou via la lib Python.

### Charger et lister les chapitres

```sql
-- Affiche les chapitres CIM10 (depth = 0)
SELECT code, label, "left", "right"
FROM 'parquet/cim10-2025-01-01.parquet'
WHERE depth = 0
ORDER BY "left";
```

> Les colonnes `left` et `right` sont des mots-clés SQL — DuckDB les accepte entre guillemets doubles.

### Tous les descendants d'un chapitre

```sql
-- Toutes les lignes sous le chapitre I "Certaines maladies infectieuses et parasitaires"
WITH chapitre AS (
    SELECT "left" AS l, "right" AS r
    FROM 'parquet/cim10-2025-01-01.parquet'
    WHERE code = 'I'
)
SELECT code, label, depth
FROM 'parquet/cim10-2025-01-01.parquet', chapitre
WHERE "left" BETWEEN chapitre.l AND chapitre.r
ORDER BY "left";
```

### Tous les ancêtres d'un code

```sql
-- Remonter la hiérarchie depuis le code A00.0
WITH cible AS (
    SELECT "left" AS l, "right" AS r
    FROM 'parquet/cim10-2025-01-01.parquet'
    WHERE code = 'A00.0'
)
SELECT code, label, depth
FROM 'parquet/cim10-2025-01-01.parquet', cible
WHERE cible.l BETWEEN "left" AND "right"
ORDER BY depth;
```

### Compter les codes par chapitre

```sql
SELECT
    chap.code        AS chapitre,
    chap.label       AS titre,
    COUNT(*) - 1     AS nb_descendants  -- on retire le chapitre lui-même
FROM 'parquet/cim10-2025-01-01.parquet' AS chap
JOIN 'parquet/cim10-2025-01-01.parquet' AS sub
  ON sub."left" BETWEEN chap."left" AND chap."right"
WHERE chap.depth = 0
GROUP BY chap.code, chap.label
ORDER BY chap.code;
```

### Filtrer la CCAM par topographie

```sql
-- Tous les actes CCAM avec topographie "Os de la main"
SELECT code, label, path
FROM 'parquet/ccam-v82.00.parquet'
WHERE topographie = 'Os de la main'
LIMIT 20;
```


### En Python avec DuckDB

```python
import duckdb

con = duckdb.connect()

# Charger en table (optionnel — DuckDB peut lire le parquet directement)
con.execute("""
    CREATE TABLE cim10 AS
    SELECT * FROM 'parquet/cim10-2025-01-01.parquet'
""")

# Descendants d'un nœud, classiquement
descendants = con.execute("""
    WITH t AS (SELECT "left", "right" FROM cim10 WHERE code = 'A00')
    SELECT c.code, c.label, c.depth
    FROM cim10 c, t
    WHERE c."left" BETWEEN t."left" AND t."right"
    ORDER BY c."left"
""").pl()  # → DataFrame Polars

print(descendants)
```

### Lire les métadonnées du fichier

```python
import pyarrow.parquet as pq

md = pq.read_metadata("parquet/cim10-2025-01-01.parquet").metadata
print({k.decode(): v.decode() for k, v in md.items() if not k.startswith(b"ARROW")})
# {'terminology': 'cim10', 'version': '2025-01-01',
#  'source_file': 'terminologie-cim-10-2025-01-01.rdf',
#  'generated_at': '2026-05-11T...'}
```

## Ajouter une nouvelle terminologie

1. Créer `smt2parquet/<nom>.py` qui expose :
   - `BASE_URI`, `RDF_FILENAME_PREFIX`, `TERMINOLOGY_NAME`,
   - `EDGES_QUERY` et `ATTRS_QUERY` (SPARQL),
   - `convert(rdf_path, out_path)`.
2. Ajouter une entrée dans `TERMINOLOGIES` de `smt2parquet/__main__.py`.

`smt2parquet/core.py` ne devrait pas avoir à bouger. Voir `smt2parquet/cim10.py` et `smt2parquet/ccam.py` pour deux exemples — la CCAM montre comment intégrer des concepts liés (`topographie`, `type_acte`…) via `OPTIONAL { ?concept ccam:topographie ?x . ?x rdfs:label ?topographie }`.

## Licence

MIT
