"""High-level user API for smt2parquet."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import polars as pl

from smt2parquet import core
from smt2parquet.cim10 import convert as _convert_cim10
from smt2parquet.ccam import convert as _convert_ccam


def _resolve_rdf_path(terminology: str, version: Optional[str], rdf_dir: Path) -> Path:
    """Find the RDF file matching the terminology and optional version.
    
    Args:
        terminology: Either 'cim10' or 'ccam'
        version: Optional version string (e.g., '2025-01-01' for CIM10, 'v82.00' for CCAM)
        rdf_dir: Directory to search for RDF files
        
    Returns:
        Path to the matching RDF file
        
    Raises:
        FileNotFoundError: If no matching RDF file is found
        ValueError: If multiple files match and no version specified
    """
    from smt2parquet.__main__ import TERMINOLOGIES
    
    if terminology not in TERMINOLOGIES:
        raise ValueError(f"Unknown terminology: {terminology!r}. Available: {list(TERMINOLOGIES.keys())}")
    
    spec = TERMINOLOGIES[terminology]
    glob_pattern = spec["rdf_glob"]
    # Extract the filename pattern from the glob (e.g., "terminologie-cim-10-*.rdf")
    filename_pattern = glob_pattern.split("/")[-1]
    # Get the prefix (e.g., "terminologie-cim-10-") by removing the * and .rdf
    prefix = filename_pattern.replace("*.rdf", "")
    
    # Expand user home directory if present
    rdf_dir = rdf_dir.expanduser()
    
    # First, try the exact glob pattern in the specified directory
    matches = sorted(rdf_dir.glob(filename_pattern))
    
    # Fallback: try in current directory's rdf/ subdirectory for backward compatibility
    if not matches:
        default_rdf_dir = Path("rdf")
        if default_rdf_dir.exists():
            matches = sorted(default_rdf_dir.glob(filename_pattern))
    
    if not matches:
        raise FileNotFoundError(
            f"Aucun fichier RDF trouvé pour {terminology} dans {rdf_dir.absolute()!r}. "
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
        return exact_matches[0]
    
    # If multiple matches and no version specified, raise error
    if len(matches) > 1:
        available_versions = [
            str(p.stem).replace(prefix, "") 
            for p in matches
        ]
        raise ValueError(
            f"Plusieurs fichiers RDF trouvés pour {terminology} : {available_versions}. "
            f"Précisez une version avec version='...' (ex: version='2025-01-01')"
        )
    
    return matches[0]


def _get_version_from_path(rdf_path: Path, terminology: str) -> str:
    """Extract version from RDF filename."""
    # Get prefix from TERMINOLOGIES config to stay in sync
    from smt2parquet.__main__ import TERMINOLOGIES
    glob_pattern = TERMINOLOGIES[terminology]["rdf_glob"]
    prefix = glob_pattern.split("/")[-1].replace("*.rdf", "")
    
    stem = rdf_path.stem
    if not stem.startswith(prefix):
        raise ValueError(
            f"RDF filename {stem!r} does not start with expected prefix {prefix!r}"
        )
    version = stem[len(prefix):]
    if not version:
        raise ValueError(f"Empty version extracted from {stem!r}")
    return version


def _ensure_parquet(
    terminology: str,
    rdf_path: Path,
    out_dir: Path,
    force: bool = False,
) -> pl.DataFrame:
    """Generate Parquet if needed and return DataFrame.
    
    Args:
        terminology: Either 'cim10' or 'ccam'
        rdf_path: Path to the RDF source file
        out_dir: Output directory for Parquet files
        force: If True, regenerate even if Parquet exists
        
    Returns:
        Polars DataFrame with all concepts
    """
    version = _get_version_from_path(rdf_path, terminology)
    out_path = out_dir / f"{terminology}-{version}.parquet"
    
    # Create output directory if it doesn't exist
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Regenerate if forced or Parquet doesn't exist
    if not out_path.exists() or force:
        if terminology == "cim10":
            _convert_cim10(rdf_path, out_path)
        elif terminology == "ccam":
            _convert_ccam(rdf_path, out_path)
        else:
            raise ValueError(f"Unknown terminology: {terminology!r}")
    
    return pl.read_parquet(out_path)


def cim10(
    version: Optional[str] = None,
    rdf_dir: Path | str = "rdf",
    out_dir: Path | str = "parquet",
    force: bool = False,
) -> pl.DataFrame:
    """Charge la terminologie CIM10 depuis un dossier RDF.
    
    Args:
        version: Version spécifique (ex: "2025-01-01"). Si None, utilise le premier
            fichier trouvé. Si plusieurs fichiers existent, une erreur est levée.
        rdf_dir: Dossier contenant les fichiers RDF. Peut être un chemin relatif,
            absolu, ou utiliser ~ pour le répertoire home (ex: "rdf/", "/data/smt/", "~/data/").
        out_dir: Dossier pour les fichiers Parquet générés. Créé automatiquement.
        force: Si True, regénère le Parquet même s'il existe déjà.
        
    Returns:
        DataFrame Polars avec tous les concepts CIM10.
        
    Raises:
        FileNotFoundError: Si aucun fichier RDF CIM10 n'est trouvé dans rdf_dir.
        ValueError: Si plusieurs fichiers sont trouvés et que version n'est pas spécifié.
        
    Example:
        >>> from smt2parquet import cim10
        >>> df = cim10()  # Cherche dans ./rdf/
        >>> df = cim10(rdf_dir="/chemin/vers/rdf/")
        >>> df = cim10(version="2025-01-01", rdf_dir="~/data/smt/")
    """
    rdf_dir = Path(rdf_dir).expanduser()
    out_dir = Path(out_dir).expanduser()
    
    if not rdf_dir.exists():
        raise FileNotFoundError(f"Le dossier RDF n'existe pas : {rdf_dir.absolute()!r}")
    
    rdf_path = _resolve_rdf_path("cim10", version, rdf_dir)
    return _ensure_parquet("cim10", rdf_path, out_dir, force)


def ccam(
    version: Optional[str] = None,
    rdf_dir: Path | str = "rdf",
    out_dir: Path | str = "parquet",
    force: bool = False,
) -> pl.DataFrame:
    """Charge la terminologie CCAM depuis un dossier RDF.
    
    Args:
        version: Version spécifique (ex: "v82.00"). Si None, utilise le premier
            fichier trouvé. Si plusieurs fichiers existent, une erreur est levée.
        rdf_dir: Dossier contenant les fichiers RDF. Peut être un chemin relatif,
            absolu, ou utiliser ~ pour le répertoire home (ex: "rdf/", "/data/ccam/").
        out_dir: Dossier pour les fichiers Parquet générés. Créé automatiquement.
        force: Si True, regénère le Parquet même s'il existe déjà.
        
    Returns:
        DataFrame Polars avec tous les concepts CCAM.
        
    Raises:
        FileNotFoundError: Si aucun fichier RDF CCAM n'est trouvé dans rdf_dir.
        ValueError: Si plusieurs fichiers sont trouvés et que version n'est pas spécifié.
        
    Example:
        >>> from smt2parquet import ccam
        >>> df = ccam()  # Cherche dans ./rdf/
        >>> df = ccam(rdf_dir="/chemin/vers/rdf/")
        >>> df = ccam(version="v82.00", rdf_dir="~/data/ccam/")
    """
    rdf_dir = Path(rdf_dir).expanduser()
    out_dir = Path(out_dir).expanduser()
    
    if not rdf_dir.exists():
        raise FileNotFoundError(f"Le dossier RDF n'existe pas : {rdf_dir.absolute()!r}")
    
    rdf_path = _resolve_rdf_path("ccam", version, rdf_dir)
    return _ensure_parquet("ccam", rdf_path, out_dir, force)
