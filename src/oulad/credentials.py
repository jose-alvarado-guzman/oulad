"""Module responsible for resolving the credentials used by the project.

Secrets are read from the Google Colab secrets store when the code runs inside
a Colab notebook and from a .env file when it runs locally. Resolved values are
placed in os.environ so the rest of the package can keep reading them with
os.getenv.

Precedence, highest first: the existing process environment, the Colab secrets
store, the .env file.

There are two groups of required credentials. ETL_SECRETS are what the loading
pipeline needs to reach Neo4j, and are what load_credentials enforces by
default. AGA_SECRETS are what Aura Graph Analytics needs to run against the
graph once it is loaded; the ETL never reads them, so analytics code has to ask
for them with load_credentials(logger, required=AGA_SECRETS). Every known
secret is resolved into os.environ on any call, whichever group is enforced.

Functions
---------
def in_colab() -> bool
    Report whether the code is running inside a Google Colab notebook.
def get_secret(name:str, logger:logging.Logger, default:str=None) -> str
    Retrieve a single secret from the process environment or Colab.
def load_credentials(logger:logging.Logger, env_file:str=None,
                     required:List[str]=None, names:List[str]=None) -> str
    Populate os.environ with the credentials and describe their source.

Exceptions
----------
MissingCredentialsError
    Raised when a required credential could not be resolved.
"""

import os
import logging
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv, find_dotenv

# Required to run the ETL pipeline.
ETL_SECRETS = ['NEO4J_URI', 'NEO4J_USERNAME', 'NEO4J_PASSWORD']
# Required to run Aura Graph Analytics against the loaded graph. The ETL never
# reads these, so a load can succeed while they are absent.
AGA_SECRETS = ['AURA_CLIENT_SECRET', 'AURA_CLIENT_ID', 'AURA_PROJECT_ID']
# Required by neither group. NEO4J_DATABASE falls back to the neo4j default in
# the post-load QA queries, but is worth setting explicitly for the analytics.
OPTIONAL_SECRETS = ['NEO4J_DATABASE']
ALL_SECRETS = ETL_SECRETS + AGA_SECRETS + OPTIONAL_SECRETS
SECRET_GROUPS = {'ETL': ETL_SECRETS, 'Aura Graph Analytics': AGA_SECRETS}
PACKAGE_ENV_FILE = Path(__file__).resolve().parent.parent / '.env'

class MissingCredentialsError(Exception):
    """Raised when a required credential could not be resolved."""

def _colab_userdata():
    """Retrieve the Colab secrets module when running inside Colab.

    Returns
    -------
    module or None
        The google.colab.userdata module, or None when the code is not running
        inside a Colab notebook.
    """
    try:
        from google.colab import userdata
    except ImportError:
        return None
    return userdata

def in_colab() -> bool:
    """Report whether the code is running inside a Google Colab notebook.

    Returns
    -------
    bool
        True when the Colab secrets store is available.
    """
    return _colab_userdata() is not None

def _read_colab_secret(
        userdata,
        name: str,
        logger: logging.Logger,
        level: int = logging.WARNING
    ) -> Optional[str]:
    """Read a single secret from the Colab secrets store.

    Parameters
    ----------
    userdata : module
        The google.colab.userdata module.
    name : str
        Name of the secret to read.
    logger : Logger
        Logger use to log the pipeline progress.
    level : int, optional
        Level used to log an unreadable secret. Secrets outside the group being
        enforced are logged below warning, so an absent one does not read as a
        failure of the task at hand.

    Returns
    -------
    str or None
        The secret value, or None when it is undefined, empty or the notebook
        was not granted access to it.
    """
    try:
        value = userdata.get(name)
    except Exception as error:
        # Colab raises SecretNotFoundError when the secret is undefined and
        # NotebookAccessError when the notebook was not granted access to it.
        # Neither type is importable outside Colab, so they are handled here by
        # name to keep a missing secret from aborting the whole lookup.
        logger.log(
            level,
            f'Could not read the Colab secret {name}: {type(error).__name__}'
        )
        return None
    return value or None

def _env_file_path(env_file: Optional[str]) -> Optional[str]:
    """Locate the .env file to use as the fallback credential source.

    Parameters
    ----------
    env_file : str, optional
        Explicit path of the .env file to read. When omitted the file shipped
        next to the package is used, falling back to a search from the current
        working directory.

    Returns
    -------
    str or None
        Path of the .env file, or None when no file was found.
    """
    if env_file:
        return env_file if os.path.isfile(env_file) else None
    if PACKAGE_ENV_FILE.is_file():
        return str(PACKAGE_ENV_FILE)
    return find_dotenv(usecwd=True) or None

def _describe_missing(missing: List[str]) -> str:
    """Describe unresolved credentials by the purpose each one serves.

    Parameters
    ----------
    missing : List[str]
        Names of the credentials that could not be resolved.

    Returns
    -------
    str
        The names grouped under the label of the group they belong to.
    """
    described = []
    grouped = []
    for label, group in SECRET_GROUPS.items():
        names = [name for name in missing if name in group]
        if names:
            described.append(f'{label} ({", ".join(names)})')
            grouped.extend(names)
    ungrouped = [name for name in missing if name not in grouped]
    if ungrouped:
        described.append(', '.join(ungrouped))
    return '; '.join(described)

def get_secret(
        name: str,
        logger: logging.Logger,
        default: Optional[str] = None
    ) -> Optional[str]:
    """Retrieve a single secret from the process environment or Colab.

    Values loaded from a .env file by load_credentials are already part of the
    process environment, so this function sees them too.

    Parameters
    ----------
    name : str
        Name of the secret to retrieve.
    logger : Logger
        Logger use to log the pipeline progress.
    default : str, optional
        Value to return when the secret could not be resolved.

    Returns
    -------
    str or None
        The secret value, or default when it could not be resolved.
    """
    value = os.getenv(name)
    if value:
        return value
    userdata = _colab_userdata()
    if userdata is not None:
        value = _read_colab_secret(userdata, name, logger)
        if value:
            os.environ[name] = value
            return value
    return default

def load_credentials(
        logger: logging.Logger,
        env_file: Optional[str] = None,
        required: Optional[List[str]] = None,
        names: Optional[List[str]] = None
    ) -> str:
    """Populate os.environ with the credentials the caller needs.

    Parameters
    ----------
    logger : Logger
        Logger use to log the pipeline progress.
    env_file : str, optional
        Explicit path of the .env file to use as the fallback source.
    required : List[str], optional
        Names that must be resolved for the caller to proceed. Defaults to
        ETL_SECRETS; pass AGA_SECRETS from analytics code, or the two
        concatenated to enforce both groups at once.
    names : List[str], optional
        Names to resolve into os.environ. Defaults to every known secret, so
        the credentials of the group that is not being enforced are still
        available afterwards.

    Returns
    -------
    str
        Description of the credential source that was used.

    Raises
    ------
    MissingCredentialsError
        When one of the required credentials could not be resolved.
    """
    required = ETL_SECRETS if required is None else required
    names = names or ALL_SECRETS
    userdata = _colab_userdata()
    sources = []
    if userdata is not None:
        resolved = []
        for name in names:
            if os.getenv(name):
                continue
            level = logging.WARNING if name in required else logging.INFO
            value = _read_colab_secret(userdata, name, logger, level)
            if value:
                os.environ[name] = value
                resolved.append(name)
        if resolved:
            sources.append(f'Colab secrets ({", ".join(resolved)})')
    env_path = _env_file_path(env_file)
    if env_path:
        load_dotenv(env_path)
        sources.append(f'the .env file {env_path}')
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        location = (
            'the Secrets panel of the Colab notebook, granting the notebook '
            'access to each one' if userdata is not None
            else f'the .env file {env_path or PACKAGE_ENV_FILE}'
        )
        raise MissingCredentialsError(
            f'Could not resolve the required credentials: '
            f'{_describe_missing(missing)}. Add them to {location}.'
        )
    source = ' then '.join(sources) if sources else 'the process environment'
    logger.info(f'Resolved the pipeline credentials from {source}')
    return source
