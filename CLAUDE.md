# smt2parquet

Convertit les terminologies médicales du portail **SMT** (https://smt.esante.gouv.fr/) — fichiers RDF — vers du **Parquet** en préservant la hiérarchie via le **modèle d'imbrication d'ensembles** (nested set : colonnes `lft`, `rgt`, `depth`, `path`).

## Pourquoi nested set

Les requêtes ancêtres/descendants deviennent triviales et indexables :
```sql
-- tous les descendants d'un nœud P
SELECT * FROM t WHERE lft BETWEEN P.lft AND P.rgt
```
C'est plus efficace qu'un simple `parent_code` (récursion nécessaire) ou qu'un `path` listé (jointures coûteuses).

## Architecture

```
smt2parquet/
├── __main__.py        # CLI : python -m smt2parquet <terminology>
├── core.py            # Helpers génériques réutilisables
├── cim10.py           # Une terminologie = un fichier Python
├── ccam.py
├── adicap.py
└── atc.py
rdf/                   # Fichiers RDF source (non commités, ~85 Mo)
parquet/               # Sorties générées (non commités)
```

### `core.py` — briques réutilisables

- `load_graph(path)` — charge un RDF dans `rdflib.Graph`.
- `extract_version(rdf_path, prefix)` — extrait `YYYY-MM-DD` du nom de fichier (ex. `terminologie-cim-10-2025-01-01.rdf` → `2025-01-01`).
- `dataframe_from_sparql(graph, sparql)` — exécute une requête SPARQL et retourne un `pl.DataFrame` (colonnes en lowercase, `None` polars proprement, pas `"None"` chaîne).
- `build_nested_set(edges, root, code_of, *, include_root=False, path_sep="/")` — DFS récursif qui :
  - assigne `lft`/`rgt` via un compteur partagé (incrémenté à l'entrée *et* à la sortie),
  - calcule `path` via une pile de codes maintenue le long du parcours,
  - **duplique les nœuds multi-parents** (un nœud avec N parents apparaît N fois avec son sous-arbre, chaque occurrence ayant son propre `lft/rgt/depth/path`),
  - détecte les cycles (`ValueError`),
  - exclut par défaut la racine virtuelle (cas CIM10 où la racine `BASE_URI` n'est pas une entité réelle).
- `write_parquet_with_metadata(df, out_path, metadata)` — écrit le Parquet via `pyarrow` en injectant `metadata` dans les key-value metadata du footer.

### `cim10.py` (et autres terminologies)

Chaque terminologie est **autonome** et expose une seule fonction publique :
```python
def convert(rdf_path: Path, out_path: Path) -> None
```
Le contrat : produire un Parquet à `out_path`. À l'intérieur, le module compose librement les briques de `core.py` — pas de classe de base, pas de Protocol, pour éviter l'abstraction prématurée. Les variations custom (concepts liés, colonnes additionnelles) restent locales au fichier.

Pattern typique pour `convert()` :
1. `version = core.extract_version(rdf_path, RDF_FILENAME_PREFIX)`
2. `graph = core.load_graph(rdf_path)`
3. Deux requêtes : `EDGES_QUERY` (arêtes parent-enfant directes) + `ATTRS_QUERY` (attributs).
4. `attrs_agg = attrs_df.group_by("concept").agg(...)` — agrégation polars **spécifique à la terminologie**.
5. `code_of = dict(zip(attrs_agg["concept"], attrs_agg["code"]))`
6. `nested = core.build_nested_set(edges_df.iter_rows(), root=BASE_URI, code_of=code_of)`
7. Jointure `nested.join(attrs_agg, left_on="node", right_on="concept", how="left")`.
8. `core.write_parquet_with_metadata(df, out_path, metadata)`.

## Comment lancer

```bash
uv sync
uv run python -m smt2parquet cim10
# → écrit parquet/cim10-2025-01-01.parquet (version extraite du nom RDF)
```

Le CLI :
- résout `rdf/terminologie-cim-10-*.rdf` (échoue si 0 ou >1 match — pas d'ambiguïté silencieuse),
- calcule `out_path = parquet/<nom>-<version>.parquet`,
- charge dynamiquement le module et appelle `convert(rdf_path, out_path)`.

## Schéma de sortie standard

| Colonne | Type | Origine |
|---|---|---|
| `code` | str | `skos:notation` |
| `label` | str | `rdfs:label` |
| `type` | str | `dc:type` (ex. `chapter`/`block`/`category` pour CIM10) |
| `depth` | i64 | calculé par DFS, racines réelles à `0` |
| `lft` | i64 | nested set (nom court façon Celko, pas de collision SQL) |
| `rgt` | i64 | nested set (nom court façon Celko, pas de collision SQL) |
| `path` | str | chaîne des codes des ancêtres jusqu'au nœud, séparés par `/` (ex. `I/A00-A09/A00/A00.0`) |
| `synonymes` | list[str] | `skos:altLabel` agrégés, dédupliqués |
| `inclusion_note` | str | `xkos:inclusionNote` |
| `keywords` | str | chaîne normalisée pour la recherche plein-texte (voir ci-dessous) |

### Colonne `keywords` (recherche textuelle)

Dernière colonne de chaque sortie : une **chaîne `str` normalisée** concaténant
les champs textuels pertinents du concept, pour requêter une seule colonne en
SQL/DuckDB (`... WHERE keywords LIKE '%oesophage%'`). Normalisation par
`core.keywords_expr` : minuscules → ligatures (`œ`/`æ` → `oe`/`ae`) → NFKD →
suppression des diacritiques → ponctuation transformée en séparateur →
**suppression des stop words français** → **tokens uniques triés** joints par
espace. La recherche est donc insensible à la casse et aux accents ; un concept
sans source produit `""`.

Les stop words proviennent de
[stopwords-iso/stopwords-fr](https://github.com/stopwords-iso/stopwords-fr),
vendus dans `smt2parquet/stopwords_fr.txt`. Ils sont normalisés par le **même**
pipeline que les tokens (les composés `aujourd'hui`, `celle-ci` sont éclatés en
fragments `aujourd`/`hui`/`celle`/`ci`) puis exposés via `core.FRENCH_STOPWORDS`.
Le préfixe code n'est **pas** filtré (ajouté après le tri).

Le **code du concept est préfixé en première position** (argument `code="code"`
de `keywords_expr`) : gardé verbatim, seulement mis en minuscules (la ponctuation
n'est **pas** découpée), il précède les tokens normalisés triés — ce qui permet la
recherche par code exact (`... WHERE keywords LIKE '%a00.0%'`). Un code null
(nœuds ombrelles) est simplement ignoré.

Le **contenu** est choisi par module (chaque `convert()` passe ses colonnes à
`core.keywords_expr(joined, [...])`) :
- **CIM10** : `label`, `synonymes`.
- **CCAM** : `label`, `synonymes`, `topographie`, `type_acte`, `mode_acces`, `action`.
- **ADICAP** : `label`, `anatomy_label`.
- **ATC** : `label`.

Hormis le `code` du concept (préfixé, cf. ci-dessus), les autres codes
(`dictionary_code`, `anatomy_code`) et les notes longues (`inclusion_note`,
`exclusion_note`, `definition`) restent volontairement exclus.

Colonnes spécifiques possibles selon la terminologie :
- **CCAM** : `topographie`, `type_acte`, `mode_acces`, `action` — labels de concepts liés via `ccam:topographie [ rdfs:label ?x ]` etc.
- **ADICAP** : `dictionary_code` (`adicap:dictionaryCode`, l'axe D1–D8L), `anatomy_code` + `anatomy_label` (`adicap:anatomy` pointe vers un autre concept ADICAP dont on résout `skos:notation` + `rdfs:label`). Pas de `type` (absence de `dc:type`), ni `synonymes`/`inclusion_note` (absence de `skos:altLabel`/`xkos:*`).
- **ATC** : `type` = niveau ATC `1`–`5` (`dc:type`) ; `status` = `active`/`inactive` (`adms:status`). Pas de `synonymes` ni de notes (absence de `skos:altLabel`/`xkos:*`). Les nœuds ombrelles (`ATC` + conteneurs « Concept retirés ») ont `type`/`status` nuls.

Le DataFrame est trié par `lft` (ordre DFS préfixe naturel).

## Métadonnées Parquet (footer key-value)

- `terminology` — nom court (ex. `cim10`)
- `version` — `YYYY-MM-DD` extrait du nom de fichier source
- `source_file` — nom du RDF d'origine
- `source` — libellé de la terminologie (ex. `CIM-10 FR PMSI`)
- `url` — page SMT de la terminologie
- `license` — licence de diffusion (ex. `CC BY-NC-ND 3.0 IGO`, `LOv2`)
- `generated_at` — ISO 8601 UTC

`source`/`url`/`license` sont des **constantes par module** (`SOURCE`,
`SOURCE_URL`, `LICENSE`, déclarées à côté de `TERMINOLOGY_NAME`) — chaque
terminologie porte sa propre licence.

Lecture :
```python
import pyarrow.parquet as pq
md = pq.read_metadata("parquet/cim10-2025-01-01.parquet").metadata
md[b"version"]  # b"2025-01-01"
```

## Ajouter une nouvelle terminologie

1. Créer `smt2parquet/<nom>.py` exposant :
   - `BASE_URI` (URI racine, peut être virtuelle),
   - `RDF_FILENAME_PREFIX` (préfixe du nom de fichier pour `extract_version`),
   - `TERMINOLOGY_NAME`, `SOURCE`, `SOURCE_URL`, `LICENSE`,
   - `EDGES_QUERY`, `ATTRS_QUERY` (SPARQL),
   - `convert(rdf_path, out_path)`.
2. Ajouter une entrée dans `TERMINOLOGIES` de `smt2parquet/__main__.py` :
   ```python
   "ccam": {
       "module": "smt2parquet.ccam",
       "rdf_glob": "rdf/terminologie-ccam-*.rdf",
       "out_dir": "parquet",
   },
   ```
3. Lancer `uv run python -m smt2parquet <nom>` et vérifier les invariants nested set.

Aucune modification de `core.py` ne devrait être nécessaire — si c'est le cas pour absorber un cas custom, c'est que le pattern est cassé.

## Pièges et conventions

- **Namespaces SMT** : la CIM10 utilise `xkos:inclusionNote` et **pas** `atih:inclusionNote`. Toujours vérifier les préfixes réels dans le RDF source (`grep -oE '<[a-z-]+:[a-zA-Z]+' file.rdf | sort -u`).
- **Racine virtuelle** : dans CIM10, les chapitres ont `<rdfs:subClassOf rdf:resource=""/>` qui résout à `xml:base = http://data.esante.gouv.fr/atih/cim10`. C'est la racine — pas une entité réelle, donc `include_root=False` (défaut) la masque en sortie.
- **Racine réelle (ADICAP)** : ADICAP a une racine org *réelle* `https://data.esante.gouv.fr/adicap/ADICAP` (`subClassOf owl:Thing`). On la prend comme `BASE_URI` avec `include_root=False` : le DFS part de ses enfants → les 9 dictionnaires (D1–D8 + D8L) sont à `depth 0`, et le nœud `ADICAP` est masqué (même effet que la racine virtuelle CIM10). L'arête `ADICAP subClassOf owl:Thing` est inoffensive (owl:Thing jamais visité). 9 682 lignes en sortie (= 9 683 concepts notés − racine).
- **Double racine (ATC)** : le RDF ATC a *deux* arbres sous `owl:Thing` — `.../whocc/atc/ATC` (la classification vivante) et `.../whocc/atc/Concept_retirés` (arbre administratif des 53 concepts retirés, rangés par année). Pour inclure les deux, `BASE_URI = owl:Thing` (la racine virtuelle, `include_root=False`) : les deux nœuds ombrelles passent à `depth 0` et toute la hiérarchie ATC descend d'un niveau (les 14 groupes de niveau 1 sont à `depth 1`, d'où `depth ≈ dc:type`). 7 055 lignes (tous les nœuds notés). Conséquence : l'`ATTRS_QUERY` rend `skos:notation` **requise** (et label/type/status optionnels) pour que les ombrelles — sans label fr ni `dc:type` — gardent un `code` et donc un `path` propre.
- **Labels bilingues (ATC)** : chaque concept ATC a un `rdfs:label` `@fr` *et* `@en`. Filtrer le français : `OPTIONAL { ?concept rdfs:label ?label . FILTER (lang(?label) = "fr") }`. Les 5 conteneurs « Concept retirés » n'ont pas de label fr → `label` null.
- **Namespace TopBraid (`j.1:`)** : le RDF ADICAP déclare son namespace propre sous le préfixe auto-généré `j.1:` = `https://data.esante.gouv.fr/adicap/`. En SPARQL on le redéclare proprement (`PREFIX adicap: <https://data.esante.gouv.fr/adicap/>`) — ne pas se fier au préfixe `j.1` du fichier.
- **DAG vs arbre** : le modèle nested set ne supporte qu'une arborescence. Notre choix : *duplication* (un nœud multi-parents apparaît plusieurs fois). CIM10 est un arbre pur sur `rdfs:subClassOf` (0 duplication), mais le mécanisme est en place pour SNOMED / CCAM.
- **Requêtes SPARQL** : utiliser le `rdfs:subClassOf` direct (pas `*` ni `+`) pour `EDGES_QUERY` — sinon on récupère la fermeture transitive et le DFS est cassé. L'`ATTRS_QUERY` peut faire des `OPTIONAL` pour les champs absents (synonymes, notes…), polars gérera les nulls.
- **Cartesian product en SPARQL** : si un concept a 2 altLabels et 3 inclusionNotes, l'`ATTRS_QUERY` produit 6 lignes. L'agrégation polars (`drop_nulls().unique()` pour les listes, `.first()` pour les scalaires) doit en tenir compte — attention à ne pas perdre de données avec `.first()` quand plusieurs valeurs distinctes existent.

## Dépendances

- `polars>=1.40.1` — DataFrames + Parquet (lecture).
- `rdflib>=7.6.0` — parsing RDF + SPARQL.
- `pyarrow` — écriture Parquet avec métadonnées key-value (`polars.write_parquet` n'expose pas cette API).

Python ≥ 3.13.

## Conventions de commit

**Ne pas** ajouter de trailer `Co-Authored-By: Claude ...` aux messages de commit.
