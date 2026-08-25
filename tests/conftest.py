"""Shared fixtures for the OULAD test suite.

Every test here runs offline: no Neo4j connection and no network access. The
tests that need the real CSVs skip themselves when Data/ is absent, since that
directory is gitignored and only exists once the pipeline has run.
"""

import logging
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / 'Data'
RESULT_DIR = REPO_ROOT / 'Result'

@pytest.fixture
def logger():
    """A logger that discards everything, so tests do not write to Logs/."""
    log = logging.getLogger('oulad-tests')
    log.handlers = [logging.NullHandler()]
    log.propagate = False
    return log

@pytest.fixture(scope='session')
def config():
    """The real config.yaml, parsed."""
    from pyneoinstance import load_yaml_file
    return load_yaml_file(str(REPO_ROOT / 'config.yaml'))

@pytest.fixture(scope='session')
def load_config(config):
    """The cypher.load block of the real configuration."""
    return config['cypher']['load']

@pytest.fixture(scope='session')
def frame_columns():
    """Column names of every source CSV, read without loading any rows."""
    if not DATA_DIR.is_dir():
        pytest.skip('Data/ is gitignored; run the pipeline once to populate it')
    return {
        path.stem: list(pd.read_csv(path, nrows=0).columns)
        for path in sorted(DATA_DIR.glob('*.csv'))
    }

@pytest.fixture(scope='session')
def student_info():
    """The studentInfo source frame, the one every dimension relationship uses."""
    path = DATA_DIR / 'studentInfo.csv'
    if not path.is_file():
        pytest.skip('Data/ is gitignored; run the pipeline once to populate it')
    return pd.read_csv(path)

@pytest.fixture
def clean_result_dir():
    """Remove any QA csv a test caused to be written to Result/."""
    before = set(RESULT_DIR.glob('*.csv')) if RESULT_DIR.is_dir() else set()
    yield
    after = set(RESULT_DIR.glob('*.csv')) if RESULT_DIR.is_dir() else set()
    for path in after - before:
        path.unlink()

@pytest.fixture
def no_colab(monkeypatch):
    """Make the Colab secrets store unimportable, as when running locally."""
    monkeypatch.setitem(sys.modules, 'google.colab', None)

@pytest.fixture
def colab(monkeypatch):
    """Stub the Colab secrets store.

    Returns an object whose ``store`` dict backs ``userdata.get``. Assigning
    ``fake.no_access`` as a value makes that secret raise, standing in for a
    secret the notebook was never granted access to.
    """
    class SecretNotFoundError(Exception):
        pass

    class NotebookAccessError(Exception):
        pass

    fake = types.SimpleNamespace(store={}, no_access=NotebookAccessError)

    def get(name):
        if name not in fake.store:
            raise SecretNotFoundError(name)
        value = fake.store[name]
        if value is NotebookAccessError:
            raise NotebookAccessError(name)
        return value

    userdata = types.ModuleType('google.colab.userdata')
    userdata.get = get
    userdata.SecretNotFoundError = SecretNotFoundError
    userdata.NotebookAccessError = NotebookAccessError
    colab_module = types.ModuleType('google.colab')
    colab_module.userdata = userdata
    google = types.ModuleType('google')
    google.colab = colab_module
    monkeypatch.setitem(sys.modules, 'google', google)
    monkeypatch.setitem(sys.modules, 'google.colab', colab_module)
    monkeypatch.setitem(sys.modules, 'google.colab.userdata', userdata)
    return fake

@pytest.fixture
def clean_env(monkeypatch):
    """Clear every credential from the process environment."""
    from oulad import credentials
    for name in credentials.ALL_SECRETS:
        monkeypatch.delenv(name, raising=False)

@pytest.fixture
def missing_env_file(tmp_path):
    """A path that holds no .env file.

    Passing an explicit path keeps the tests away from the developer's real
    src/.env, which _env_file_path would otherwise find.
    """
    return str(tmp_path / 'absent' / '.env')
