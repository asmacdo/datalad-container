"""Execution profile loading and resolution for containers-run"""

import logging
import os.path as op
from pathlib import Path

import yaml

from datalad.distribution.dataset import Dataset

lgr = logging.getLogger("datalad.containers.profiles")

# Directory where profiles are stored within a dataset
PROFILES_DIR = ".datalad/containers/profiles"


def get_profile_path(ds: Dataset, profile_name: str) -> Path:
    """Convert profile name to file path.

    Parameters
    ----------
    ds : Dataset
        Dataset to look in
    profile_name : str
        Profile name (e.g., 'docker-default')

    Returns
    -------
    Path
        Full path to profile YAML file
    """
    return Path(ds.path) / PROFILES_DIR / f"{profile_name}.yaml"


def load_profile(ds: Dataset, profile_name: str) -> dict:
    """Load a profile YAML file and resolve extends chain.

    Parameters
    ----------
    ds : Dataset
        Dataset containing the profile
    profile_name : str
        Profile name (without .yaml extension)

    Returns
    -------
    dict
        Resolved profile with 'image' and 'exec' keys

    Raises
    ------
    FileNotFoundError
        If profile file doesn't exist
    ValueError
        If profile is invalid or has circular extends
    """
    profile_path = get_profile_path(ds, profile_name)

    if not profile_path.exists():
        raise FileNotFoundError(
            f"Profile '{profile_name}' not found at {profile_path}"
        )

    with open(profile_path) as f:
        profile = yaml.safe_load(f)

    if profile is None:
        raise ValueError(f"Profile '{profile_name}' is empty")

    # Resolve extends chain
    profile = _resolve_extends(profile, ds, seen={profile_name})

    # Add metadata
    profile['_name'] = profile_name
    profile['_source'] = str(profile_path.relative_to(ds.path))

    return profile


def _resolve_extends(profile: dict, ds: Dataset, seen: set) -> dict:
    """Recursively resolve extends chain with clobber semantics.

    Parameters
    ----------
    profile : dict
        Profile data with optional 'extends' key
    ds : Dataset
        Dataset containing profiles
    seen : set
        Profile names already visited (for cycle detection)

    Returns
    -------
    dict
        Resolved profile with parent values clobbered by child
    """
    if 'extends' not in profile:
        return profile

    parent_name = profile['extends']

    if parent_name in seen:
        raise ValueError(
            f"Circular profile inheritance detected: {parent_name} "
            f"already in chain {seen}"
        )

    seen.add(parent_name)

    # Load parent profile
    parent_path = get_profile_path(ds, parent_name)
    if not parent_path.exists():
        raise FileNotFoundError(
            f"Extended profile '{parent_name}' not found at {parent_path}"
        )

    with open(parent_path) as f:
        parent = yaml.safe_load(f)

    if parent is None:
        raise ValueError(f"Extended profile '{parent_name}' is empty")

    # Recursively resolve parent's extends
    parent = _resolve_extends(parent, ds, seen)

    # Clobber: child values completely replace parent values
    resolved = dict(parent)
    for key, value in profile.items():
        if key != 'extends':
            resolved[key] = value

    return resolved


def validate_profile(profile: dict, ds: Dataset) -> None:
    """Validate that a profile's image exists.

    Parameters
    ----------
    profile : dict
        Resolved profile with 'image' key
    ds : Dataset
        Dataset to check image in

    Raises
    ------
    ValueError
        If required keys missing or image doesn't exist
    """
    if 'image' not in profile:
        raise ValueError(
            f"Profile '{profile.get('_name', 'unknown')}' missing required 'image' key"
        )

    if 'exec' not in profile:
        raise ValueError(
            f"Profile '{profile.get('_name', 'unknown')}' missing required 'exec' key"
        )

    # Parse image name:version
    image = profile['image']
    if ':' in image:
        base_name, version = image.split(':', 1)
    else:
        base_name, version = image, 'latest'

    # Check image directory exists
    image_path = Path(ds.path) / '.datalad' / 'containers' / 'images' / base_name / version / 'image'
    if not image_path.exists():
        raise ValueError(
            f"Profile '{profile.get('_name', 'unknown')}' references image "
            f"'{image}' but no image found at {image_path}"
        )


def list_profiles(ds: Dataset) -> list:
    """List available profiles in a dataset.

    Parameters
    ----------
    ds : Dataset
        Dataset to list profiles from

    Returns
    -------
    list of dict
        List of profile info dicts with 'name' and 'path' keys
    """
    profiles_dir = Path(ds.path) / PROFILES_DIR

    if not profiles_dir.exists():
        return []

    profiles = []
    for path in sorted(profiles_dir.glob("*.yaml")):
        profiles.append({
            'name': path.stem,
            'path': str(path.relative_to(ds.path)),
        })

    return profiles
