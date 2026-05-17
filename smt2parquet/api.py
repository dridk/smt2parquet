"""High-level user API for smt2parquet."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal, Optional

import polars as pl

from smt2parquet import config, core
from smt2parquet.cim10 import convert as _convert_cim10
from smt2parquet.ccam import convert as _convert_ccam

log = logging.getLogger(__name__)

TerminologyType = Literal["cim10", "ccam"]


def _resolve_rdf_path(
    terminology: TerminologyType,
    version: Optional[str],
    rdf_dir: Path,
    allow_fallback: bool = True,
) -> tuple[Path, str]:
    """Find the RDF file matching the terminology and optional version.
    
    Args:
        terminology: Either 'cim10' or 'ccam'
        version: Optional version string (e.g., '2025-01-01' for CIM10, 'v82.00' for CCAM)
        rdf_dir: Directory to search for RDF files (must exist and be resolved)
        allow_fallback: If True, fallback to ./rdf/ if no files found in rdf_dir
        
    Returns:
        Tuple of (Path to the matching RDF file, version string extracted)
        
    Raises:
        FileNotFoundError: If no matching RDF file is found
        ValueError: If multiple files match and no version specified, or terminology unknown
    """
    if terminology not in config.TERMINOLOGIES:
        available = list(config.TERMINOLOGIES.keys())
        raise ValueError(
            f"Unknown terminology: {terminology!r}. Available: {available}"
        )
    
    spec = config.TERMINOLOGIES[terminology]
    filename_pattern = spec["rdf_glob"].split("/")[-1]
    prefix = spec["filename_prefix"]
    
    # Search in the specified directory
    matches = sorted(rdf_dir.glob(filename_pattern))
    
    # Fallback: try in current directory's rdf/ subdirectory for backward compatibility
    if not matches and allow_fallback:
        default_rdf_dir = Path("rdf")
        if default_rdf_dir.exists():
            log.debug("Aucun fichier trouvé dans %s, utilisation du fallback: %s", rdf_dir, default_rdf_dir)
            matches = sorted(default_rdf_dir.glob(filename_pattern))
    
    if not matches:
        raise FileNotFoundError(
            f"Aucun fichier RDF trouvé pour {terminology} dans {rdf_dir!r}. "
            f"Pattern attendu : {filename_pattern}"
        )
    
    # If version is specified, find exact match
    if version is not None:
        expected_filename = f"{prefix}{version}.rdf"
        exact_matches = [p for p in matches if p.name == expected_filename]
        if not exact_matches:
            available_files = [p.name for p in matches]
            raise FileNotFoundError(
                f"Fichier RDF pour {terminology} version '{version}' introuvable. "
                f"Fichiers disponibles : {available_files}"
            )
        return exact_matches[0], version
    
    # If multiple matches and no version specified, raise error
    if len(matches) > 1:
        available_versions = [str(p.stem).replace(prefix, "") for p in matches]
        raise ValueError(
            f"Plusieurs fichiers RDF trouvés pour {terminology} : {available_versions}. "
            f"Précisez une version avec version='...' (ex: version='2025-01-01')"
        )
    
    # Extract version from the single match
    matched_path = matches[0]
    matched_stem = matched_path.stem
    if not matched_stem.startswith(prefix):
        raise ValueError(
            f"RDF filename {matched_stem!r} does not start with expected prefix {prefix!r}"
        )
    version_extracted = matched_stem[len(prefix):]
    if not version_extracted:
        raise ValueError(f"Empty version extracted from {matched_stem!r}")
    
    return matched_path, version_extracted


def _ensure_parquet(
    terminology: TerminologyType,
    rdf_path: Path,
    out_dir: Path,
    force: bool = False,
) -> pl.DataFrame:
    """Generate Parquet if needed and return DataFrame.
    
    Args:
        terminology: Either 'cim10' or 'ccam'
        rdf_path: Path to the RDF source file
        out_dir: Output directory for Parquet files (must exist)
        force: If True, regenerate even if Parquet exists
        
    Returns:
        Polars DataFrame with all concepts
    """
    spec = config.TERMINOLOGIES[terminology]
    version = _get_version_from_path(rdf_path, terminology)
    out_path = out_dir / f"{terminology}-{version}.parquet"
    
    # Regenerate if forced or Parquet doesn't exist
    if force and out_path.exists():
        log.info("Suppression du cache existant : %s", out_path)
        out_path.unlink()
    
    if not out_path.exists():
        log.info("Génération de %s depuis %s", out_path, rdf_path)
        if terminology == "cim10":
            _convert_cim10(rdf_path, out_path)
        elif terminology == "ccam":
            _convert_ccam(rdf_path, out_path)
        else:
            raise ValueError(f"Unknown terminology: {terminology!r}")
    else:
        log.debug("Utilisation du cache : %s", out_path)
    
    return pl.read_parquet(out_path)


def _get_version_from_path(rdf_path: Path, terminology: TerminologyType) -> str:
    """Extract version from RDF filename using centralized config."""
    spec = config.TERMINOLOGIES[terminology]
    prefix = spec["filename_prefix"]
    
    stem = rdf_path.stem
    if not stem.startswith(prefix):
        raise ValueError(
            f"RDF filename {stem!r} does not start with expected prefix {prefix!r}"
        )
    version = stem[len(prefix):]
    if not version:
        raise ValueError(f"Empty version extracted from {stem!r}")
    return version


def cim10(
    version: Optional[str] = None,
    rdf_dir: Path | str = "rdf",
    out_dir: Path | str = "parquet",
    force: bool = False,
    no_fallback: bool = False,
) -> pl.DataFrame:
    """Charge la terminologie CIM10 depuis un dossier RDF.
    
    Args:
        version: Version spécifique (ex: "2025-01-01"). Si None, utilise le premier
            fichier trouvé. Si plusieurs fichiers existent, une erreur est levée.
        rdf_dir: Dossier contenant les fichiers RDF. Peut être un chemin relatif,
            absolu, ou utiliser ~ pour le répertoire home (ex: "rdf/", "/data/smt/", "~/data/").
        out_dir: Dossier pour les fichiers Parquet générés. Créé automatiquement.
            Par défaut utilise la valeur configurée dans config.TERMINOLOGIES.
        force: Si True, regénère le Parquet même s'il existe déjà.
        no_fallback: Si True, désactive le fallback vers ./rdf/ quand aucun fichier
            n'est trouvé dans rdf_dir. Permet de détecter les erreurs de chemin.
        
    Returns:
        DataFrame Polars avec tous les concepts CIM10.
        
    Raises:
        FileNotFoundError: Si aucun fichier RDF CIM10 n'est trouvé dans rdf_dir
            (ou dans ./rdf/ si no_fallback=False), ou si rdf_dir n'existe pas.
        ValueError: Si plusieurs fichiers sont trouvés et que version n'est pas spécifié,
            ou si la terminologie est inconnue.
        
    Example:
        >>> from smt2parquet import cim10
        >>> df = cim10()  # Cherche dans ./rdf/
        >>> df = cim10(rdf_dir="/chemin/vers/rdf/")
        >>> df = cim10(version="2025-01-01", rdf_dir="~/data/smt/")
        >>> df = cim10(rdf_dir="/dossier/inexistant", no_fallback=True)  # Lève FileNotFoundError
    """
    # Normalize and resolve paths
    rdf_dir = Path(rdf_dir).expanduser().resolve()
    
    # Use configured out_dir if not specified
    if out_dir == "parquet":
        out_dir = Path(config.TERMINOLOGIES["cim10"]["out_dir"]).expanduser().resolve()
    else:
        out_dir = Path(out_dir).expanduser().resolve()
    
    if not rdf_dir.is_dir():
        raise FileNotFoundError(f"Le dossier RDF n'existe pas : {rdf_dir!r}")
    
    log.info("Chargement CIM10 depuis %s", rdf_dir)
    rdf_path, resolved_version = _resolve_rdf_path("cim10", version, rdf_dir, allow_fallback=not no_fallback)
    return _ensure_parquet("cim10", rdf_path, out_dir, force)


def ccam(
    version: Optional[str] = None,
    rdf_dir: Path | str = "rdf",
    out_dir: Path | str = "parquet",
    force: bool = False,
    no_fallback: bool = False,
) -> pl.DataFrame:
    """Charge la terminologie CCAM depuis un dossier RDF.
    
    Args:
        version: Version spécifique (ex: "v82.00"). Si None, utilise le premier
            fichier trouvé. Si plusieurs fichiers existent, une erreur est levée.
        rdf_dir: Dossier contenant les fichiers RDF. Peut être un chemin relatif,
            absolu, ou utiliser ~ pour le répertoire home (ex: "rdf/", "/data/ccam/").
        out_dir: Dossier pour les fichiers Parquet générés. Créé automatiquement.
            Par défaut utilise la valeur configurée dans config.TERMINOLOGIES.
        force: Si True, regénère le Parquet même s'il existe déjà.
        no_fallback: Si True, désactive le fallback vers ./rdf/ quand aucun fichier
            n'est trouvé dans rdf_dir. Permet de détecter les erreurs de chemin.
        
    Returns:
        DataFrame Polars avec tous les concepts CCAM.
        
    Raises:
        FileNotFoundError: Si aucun fichier RDF CCAM n'est trouvé dans rdf_dir
            (ou dans ./rdf/ si no_fallback=False), ou si rdf_dir n'existe pas.
        ValueError: Si plusieurs fichiers sont trouvés et que version n'est pas spécifié,
            ou si la terminologie est inconnue.
        
    Example:
        >>> from smt2parquet import ccam
        >>> df = ccam()  # Cherche dans ./rdf/
        >>> df = ccam(rdf_dir="/chemin/vers/rdf/")
        >>> df = ccam(version="v82.00", rdf_dir="~/data/ccam/")
        >>> df = ccam(rdf_dir="/dossier/inexistant", no_fallback=True)  # Lève FileNotFoundError
    """
    # Normalize and resolve paths
    rdf_dir = Path(rdf_dir).expanduser().resolve()
    
    # Use configured out_dir if not specified
    if out_dir == "parquet":
        out_dir = Path(config.TERMINOLOGIES["ccam"]["out_dir"]).expanduser().resolve()
    else:
        out_dir = Path(out_dir).expanduser().resolve()
    
    if not rdf_dir.is_dir():
        raise FileNotFoundError(f"Le dossier RDF n'existe pas : {rdf_dir!r}")
    
    log.info("Chargement CCAM depuis %s", rdf_dir)
    rdf_path, resolved_version = _resolve_rdf_path("ccam", version, rdf_dir, allow_fallback=not no_fallback)
    return _ensure_parquet("ccam", rdf_path, out_dir, force)
