# smt2parquet

Convertit les terminologies médicales du portail [**SMT**](https://smt.esante.gouv.fr/) (Serveur Multi-Terminologies, eSanté France) — fichiers RDF — vers du **Parquet** en préservant la hiérarchie via le [**modèle d'imbrication d'ensembles**](https://fr.wikipedia.org/wiki/Imbrication_d%27ensembles) (*nested set*).

Le résultat : un Parquet par terminologie avec, pour chaque concept, les colonnes `code`, `label`, `path`, et le triplet `lft`/`rgt`/`depth` qui permettent de requêter ancêtres et descendants par une simple comparaison d'intervalles.

Les fichiers parquets sont directement disponnible pour utilisation sur [data.gouv](https://www.data.gouv.fr/datasets/terminologie-au-format-parquet).

Ces fichiers peuvent être consommer avec de nombreux outils comme [duckdb](https://duckdb.org/), [pola.rs](https://pola.rs/) ou [clickhouse](https://clickhouse.com/).

## Installation

```bash
git clone https://github.com/dridk/smt2parquet.git
cd smt2parquet
uv sync
```

## Générer un Parquet

Le principe est le même pour les trois terminologies :

1. **Télécharger le RDF** depuis le portail [SMT](https://smt.esante.gouv.fr/) (sélectionner la terminologie, puis exporter au format RDF).
2. **Le placer dans `rdf/`** sans renommer — le nom de fichier doit suivre le motif attendu (la version en est extraite automatiquement) :
   - CIM10 → `rdf/terminologie-cim-10-<version>.rdf` (ex. `terminologie-cim-10-2025-01-01.rdf`)
   - CCAM → `rdf/terminologie-ccam-<version>.rdf`
   - ADICAP → `rdf/terminologie-adicap-<version>.rdf` (ex. `terminologie-adicap-2024-10.rdf`)
3. **Lancer la conversion** :
   ```bash
   uv run python -m smt2parquet cim10    # ou ccam, ou adicap
   ```

Les détails (commande, colonnes, exemples) propres à chaque terminologie sont dans les sections ci-dessous.

## Le modèle nested set


Pour tout nœud P, ses descendants sont les lignes où lft ∈ ]P.lft, P.rgt[
                  ses ancêtres   sont les lignes où lft < P.lft ET rgt > P.rgt


Les nœuds avec plusieurs parents (DAG) sont **dupliqués** : chaque occurrence sous un parent différent reçoit son propre `lft`/`rgt`/`depth`/`path`. 

Chaque Parquet embarque aussi des **métadonnées** dans le footer (`terminology`, `version`, `source_file`, `generated_at`) — voir l'exemple de lecture dans chaque section.

---

## CIM10

Classification internationale des maladies, 10ᵉ révision (ICD-10)

```bash
uv run python -m smt2parquet cim10
# rdf/terminologie-cim-10-<version>.rdf  →  parquet/cim10-<version>.parquet
```

### Colonnes

| Colonne | Type | Description |
|---|---|---|
| `code` | `str` | Code du concept (`skos:notation`) |
| `label` | `str` | Libellé (`rdfs:label`) |
| `type` | `str` | `chapter` / `block` / `category` (`dc:type`) |
| `depth` | `i64` | Profondeur dans l'arbre (0 = chapitre) |
| `lft` | `i64` | Borne gauche du nested set |
| `rgt` | `i64` | Borne droite du nested set |
| `path` | `str` | Chaîne des codes des ancêtres, ex. `I/A00-A09/A00/A00.0` |
| `synonymes` | `list[str]` | `skos:altLabel` dédupliqués |
| `inclusion_note` | `str?` | `xkos:inclusionNote` |

### Exemples

```sql
-- Lister les chapitres (depth = 0)
SELECT code, label, lft, rgt
FROM 'parquet/cim10-2025-01-01.parquet'
WHERE depth = 0
ORDER BY lft;
```

```sql
-- Tous les descendants du chapitre I
WITH chapitre AS (
    SELECT lft AS l, rgt AS r
    FROM 'parquet/cim10-2025-01-01.parquet'
    WHERE code = 'I'
)
SELECT code, label, depth
FROM 'parquet/cim10-2025-01-01.parquet', chapitre
WHERE lft BETWEEN chapitre.l AND chapitre.r
ORDER BY lft;
```

```sql
-- Tous les ancêtres du code A00.0
WITH cible AS (
    SELECT lft AS l, rgt AS r
    FROM 'parquet/cim10-2025-01-01.parquet'
    WHERE code = 'A00.0'
)
SELECT code, label, depth
FROM 'parquet/cim10-2025-01-01.parquet', cible
WHERE cible.l BETWEEN lft AND rgt
ORDER BY depth;
```

```python
# En Python avec DuckDB
import duckdb

descendants = duckdb.sql("""
    WITH t AS (SELECT lft, rgt FROM 'parquet/cim10-2025-01-01.parquet' WHERE code = 'A00')
    SELECT c.code, c.label, c.depth
    FROM 'parquet/cim10-2025-01-01.parquet' c, t
    WHERE c.lft BETWEEN t.lft AND t.rgt
    ORDER BY c.lft
""").pl()  # → DataFrame Polars
```

```python
# Lire les métadonnées du fichier
import pyarrow.parquet as pq

md = pq.read_metadata("parquet/cim10-2025-01-01.parquet").metadata
print({k.decode(): v.decode() for k, v in md.items() if not k.startswith(b"ARROW")})
# {'terminology': 'cim10', 'version': '2025-01-01', 'source_file': '...', 'generated_at': '...'}
```

---

## CCAM

Classification commune des actes médicaux — actes techniques. 

```bash
uv run python -m smt2parquet ccam
# rdf/terminologie-ccam-<version>.rdf  →  parquet/ccam-<version>.parquet
```

### Colonnes

| Colonne | Type | Description |
|---|---|---|
| `code` | `str` | Code de l'acte (`skos:notation`) |
| `label` | `str` | Libellé (`rdfs:label`) |
| `depth` | `i64` | Profondeur dans l'arbre |
| `lft` | `i64` | Borne gauche du nested set |
| `rgt` | `i64` | Borne droite du nested set |
| `path` | `str` | Chaîne des codes des ancêtres |
| `synonymes` | `list[str]` | `skos:altLabel` dédupliqués |
| `inclusion_note` | `str?` | `xkos:inclusionNote` |
| `exclusion_note` | `str?` | `xkos:exclusionNote` |
| `definition` | `str?` | `skos:definition` |
| `topographie` | `str?` | Libellé du concept lié `ccam:topographie` |
| `type_acte` | `str?` | Libellé du concept lié `ccam:typeActe` |
| `mode_acces` | `str?` | Libellé du concept lié `ccam:modeAcces` |
| `action` | `str?` | Libellé du concept lié `ccam:action` |

### Exemples

```sql
-- Filtrer par topographie
SELECT code, label, path
FROM 'parquet/ccam-v82.00.parquet'
WHERE topographie = 'Os de la main'
LIMIT 20;
```

```sql
-- Tous les descendants d'un nœud de la hiérarchie
WITH n AS (
    SELECT lft AS l, rgt AS r
    FROM 'parquet/ccam-v82.00.parquet'
    WHERE code = '01'
)
SELECT code, label, type_acte, mode_acces
FROM 'parquet/ccam-v82.00.parquet', n
WHERE lft BETWEEN n.l AND n.r
ORDER BY lft;
```

```python
# En Python avec DuckDB
import duckdb

actes = duckdb.sql("""
    SELECT code, label, topographie, action
    FROM 'parquet/ccam-v82.00.parquet'
    WHERE action IS NOT NULL
""").pl()  # → DataFrame Polars
```

```python
# Lire les métadonnées du fichier
import pyarrow.parquet as pq

md = pq.read_metadata("parquet/ccam-v82.00.parquet").metadata
print({k.decode(): v.decode() for k, v in md.items() if not k.startswith(b"ARROW")})
# {'terminology': 'ccam', 'version': 'v82.00', 'source_file': '...', 'generated_at': '...'}
```

---

## ADICAP

Codes ADICAP (anatomie et cytologie pathologiques). La racine masquée donne 9 dictionnaires (axes D1–D8 + D8L) à `depth 0`.

```bash
uv run python -m smt2parquet adicap
# rdf/terminologie-adicap-<version>.rdf  →  parquet/adicap-<version>.parquet
```

### Colonnes

| Colonne | Type | Description |
|---|---|---|
| `code` | `str` | Code du concept (`skos:notation`) |
| `label` | `str` | Libellé (`rdfs:label`) |
| `dictionary_code` | `str?` | Axe du dictionnaire D1–D8L (`adicap:dictionaryCode`) |
| `depth` | `i64` | Profondeur dans l'arbre (0 = dictionnaire) |
| `lft` | `i64` | Borne gauche du nested set |
| `rgt` | `i64` | Borne droite du nested set |
| `path` | `str` | Chaîne des codes des ancêtres |
| `anatomy_code` | `str?` | `skos:notation` du concept lié `adicap:anatomy` |
| `anatomy_label` | `str?` | `rdfs:label` du concept lié `adicap:anatomy` |

### Exemples

```sql
-- Lister les 9 dictionnaires (depth = 0)
SELECT code, label, dictionary_code, lft, rgt
FROM 'parquet/adicap-2024-10.parquet'
WHERE depth = 0
ORDER BY lft;
```

```sql
-- Tous les concepts d'un dictionnaire donné
WITH dico AS (
    SELECT lft AS l, rgt AS r
    FROM 'parquet/adicap-2024-10.parquet'
    WHERE dictionary_code = 'D1'
)
SELECT code, label, anatomy_label
FROM 'parquet/adicap-2024-10.parquet', dico
WHERE lft BETWEEN dico.l AND dico.r
ORDER BY lft;
```

```python
# En Python avec DuckDB
import duckdb

avec_anatomie = duckdb.sql("""
    SELECT code, label, anatomy_code, anatomy_label
    FROM 'parquet/adicap-2024-10.parquet'
    WHERE anatomy_code IS NOT NULL
""").pl()  # → DataFrame Polars
```

```python
# Lire les métadonnées du fichier
import pyarrow.parquet as pq

md = pq.read_metadata("parquet/adicap-2024-10.parquet").metadata
print({k.decode(): v.decode() for k, v in md.items() if not k.startswith(b"ARROW")})
# {'terminology': 'adicap', 'version': '2024-10', 'source_file': '...', 'generated_at': '...'}
```

---

## CSARR

Catalogue spécifique des actes de rééducation et réadaptation. **Cas particulier : le CSARR n'est pas publié sur le SMT** — l'ATIH le diffuse sous forme d'un classeur **Excel**. La hiérarchie (chapitres → rubriques) et les actes feuilles sont reconstruits depuis l'onglet `CSARR_FINAL`, à partir des codes dotés (`01` → `01.01` → `01.01.01`) et des codes d'actes (`GKQ+190`). La racine virtuelle masquée donne les 12 chapitres à `depth 0`.

1. **Télécharger le `.xls`** depuis l'[ATIH](https://www.atih.sante.fr/sites/default/files/public/content/4902/csarr_liste_analytique_2025_versioncorrigee.xls).
2. **Le placer dans `rdf/`** sans renommer (le nom doit matcher `csarr_*.xls` ; le millésime annuel en est extrait).
3. **Lancer la conversion** :
   ```bash
   uv run python -m smt2parquet csarr
   # rdf/csarr_liste_analytique_<année>_*.xls  →  parquet/csarr-<année>.parquet
   ```

### Colonnes

| Colonne | Type | Description |
|---|---|---|
| `code` | `str` | Code doté (chapitre/rubrique) ou code d'acte (`GKQ+190`) |
| `label` | `str` | Libellé |
| `type` | `str` | `chapitre` / `rubrique` / `acte` (dérivé de la structure) |
| `depth` | `i64` | Profondeur dans l'arbre (0 = chapitre) |
| `lft` | `i64` | Borne gauche du nested set |
| `rgt` | `i64` | Borne droite du nested set |
| `path` | `str` | Chaîne des codes des ancêtres, ex. `01/01.01/01.01.03/GKQ+190` |
| `inclusion_note` | `str?` | Notes descriptives de l'acte (« Cet acte comprend : … », « Avec ou sans : … ») |
| `extensions` | `list[str]` | Codes d'extension documentaire applicables à l'acte (ex. `ZV`, `ME`) |

### Exemples

```sql
-- Lister les 12 chapitres (depth = 0)
SELECT code, label, lft, rgt
FROM 'parquet/csarr-2025.parquet'
WHERE depth = 0
ORDER BY lft;
```

```sql
-- Tous les actes d'un chapitre donné
WITH chap AS (
    SELECT lft AS l, rgt AS r
    FROM 'parquet/csarr-2025.parquet'
    WHERE code = '01'
)
SELECT code, label, path
FROM 'parquet/csarr-2025.parquet', chap
WHERE lft BETWEEN chap.l AND chap.r AND type = 'acte'
ORDER BY lft;
```

```python
# Lire les métadonnées du fichier
import pyarrow.parquet as pq

md = pq.read_metadata("parquet/csarr-2025.parquet").metadata
print({k.decode(): v.decode() for k, v in md.items() if not k.startswith(b"ARROW")})
# {'terminology': 'csarr', 'version': '2025', 'source_file': '...', 'generated_at': '...'}
```

---

## Ajouter une nouvelle terminologie

1. Créer `smt2parquet/<nom>.py` qui expose :
   - `BASE_URI`, `RDF_FILENAME_PREFIX`, `TERMINOLOGY_NAME`,
   - `EDGES_QUERY` et `ATTRS_QUERY` (SPARQL),
   - `convert(rdf_path, out_path)`.
2. Ajouter une entrée dans `TERMINOLOGIES` de `smt2parquet/__main__.py`.

`smt2parquet/core.py` ne devrait pas avoir à bouger. Voir `smt2parquet/cim10.py` (arbre simple), `smt2parquet/ccam.py` (concepts liés via `OPTIONAL { ?concept ccam:topographie ?x . ?x rdfs:label ?topographie }`) et `smt2parquet/adicap.py` (racine réelle masquée + concept lié `anatomy`).

## Licence

Le **code** de `smt2parquet` est distribué sous licence **MIT** (voir [`LICENSE`](LICENSE)).

Les **fichiers Parquet générés** contiennent des terminologies médicales issues du
[**Serveur Multi-Terminologies (SMT)**](https://smt.esante.gouv.fr/) opéré par
l'Agence du Numérique en Santé (ANS) — à l'exception du **CSARR**, diffusé
directement par l'[**ATIH**](https://www.atih.sante.fr/). Ils restent soumis à la
licence de chaque terminologie source :

| Terminologie | Licence | Source |
|---|---|---|
| CIM-10 FR PMSI | CC BY-NC-ND 3.0 IGO | [terminologie-cim-10](https://smt.esante.gouv.fr/terminologie-cim-10/) |
| CCAM | Licence Ouverte v2.0 (Etalab, LOv2) | [terminologie-ccam](https://smt.esante.gouv.fr/terminologie-ccam/) |
| ADICAP | Licence Ouverte v2.0 (Etalab, LOv2) | [terminologie-adicap](https://smt.esante.gouv.fr/terminologie-adicap/) |
| ATC | CC BY-ND 3.0 IGO | [terminologie-atc](https://smt.esante.gouv.fr/terminologie-atc/) |
| CSARR | ATIH (à vérifier) | [ATIH (xls)](https://www.atih.sante.fr/sites/default/files/public/content/4902/csarr_liste_analytique_2025_versioncorrigee.xls) |

Chaque Parquet embarque aussi sa propre licence dans les métadonnées du footer
(clé `license`). Référez-vous au [portail SMT](https://smt.esante.gouv.fr/) (et à
l'[ATIH](https://www.atih.sante.fr/) pour le CSARR) pour les conditions
d'utilisation faisant foi.
