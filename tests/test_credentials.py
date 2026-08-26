"""Tests for credential resolution across Colab and .env."""

import os

import pytest

from oulad import credentials
from oulad.credentials import (
    AGA_SECRETS,
    ETL_SECRETS,
    MissingCredentialsError,
    get_secret,
    in_colab,
    load_credentials,
)

def _env_file(tmp_path, **values):
    """Write a .env file and return its path."""
    path = tmp_path / '.env'
    path.write_text(''.join(f'{k}={v}\n' for k, v in values.items()))
    return str(path)

ETL_VALUES = {
    'NEO4J_URI': 'neo4j+s://example',
    'NEO4J_USERNAME': 'neo4j',
    'NEO4J_PASSWORD': 'from-env',
}

def test_not_in_colab_when_the_module_is_absent(no_colab):
    assert in_colab() is False

def test_in_colab_when_the_secrets_store_imports(colab):
    assert in_colab() is True

def test_resolves_the_etl_group_from_a_dotenv_file(tmp_path, logger, clean_env, no_colab):
    source = load_credentials(logger, env_file=_env_file(tmp_path, **ETL_VALUES))
    assert '.env' in source
    assert os.environ['NEO4J_PASSWORD'] == 'from-env'

def test_empty_values_count_as_missing(tmp_path, logger, clean_env, no_colab):
    """The checked-in template has every key present but blank."""
    blank = _env_file(tmp_path, NEO4J_URI='', NEO4J_USERNAME='', NEO4J_PASSWORD='')
    with pytest.raises(MissingCredentialsError) as excinfo:
        load_credentials(logger, env_file=blank)
    assert 'ETL' in str(excinfo.value)

def test_the_error_names_the_group_that_is_missing(
        tmp_path, logger, clean_env, no_colab):
    """An analytics run should be told about AGA, not about the ETL."""
    with pytest.raises(MissingCredentialsError) as excinfo:
        load_credentials(
            logger,
            env_file=_env_file(tmp_path, **ETL_VALUES),
            required=AGA_SECRETS,
        )
    message = str(excinfo.value)
    assert 'Aura Graph Analytics' in message
    assert 'AURA_CLIENT_SECRET' in message
    assert 'NEO4J_URI' not in message

def test_the_error_names_both_groups_when_both_are_required(
        logger, clean_env, no_colab, missing_env_file):
    with pytest.raises(MissingCredentialsError) as excinfo:
        load_credentials(
            logger,
            env_file=missing_env_file,
            required=ETL_SECRETS + AGA_SECRETS,
        )
    message = str(excinfo.value)
    assert 'ETL' in message and 'Aura Graph Analytics' in message

def test_the_etl_does_not_require_the_aga_group(
        tmp_path, logger, clean_env, no_colab):
    """A load must run in an environment configured only for loading."""
    load_credentials(logger, env_file=_env_file(tmp_path, **ETL_VALUES))
    assert os.getenv('AURA_CLIENT_SECRET') is None

def test_reads_from_the_colab_store(logger, clean_env, colab, missing_env_file):
    colab.store.update(ETL_VALUES | {'NEO4J_PASSWORD': 'from-colab'})
    source = load_credentials(logger, env_file=missing_env_file)
    assert 'Colab secrets' in source
    assert os.environ['NEO4J_PASSWORD'] == 'from-colab'

def test_the_process_environment_outranks_colab(
        monkeypatch, logger, clean_env, colab, missing_env_file):
    colab.store.update(ETL_VALUES)
    monkeypatch.setenv('NEO4J_URI', 'bolt://exported')
    load_credentials(logger, env_file=missing_env_file)
    assert os.environ['NEO4J_URI'] == 'bolt://exported'

def test_colab_outranks_the_dotenv_file(tmp_path, logger, clean_env, colab):
    colab.store['NEO4J_URI'] = 'neo4j+s://from-colab'
    load_credentials(logger, env_file=_env_file(tmp_path, **ETL_VALUES))
    assert os.environ['NEO4J_URI'] == 'neo4j+s://from-colab'
    # the rest of the group still comes from the file
    assert os.environ['NEO4J_PASSWORD'] == 'from-env'

def test_falls_back_per_secret_when_colab_access_is_denied(
        tmp_path, logger, clean_env, colab):
    """One ungranted secret must not cost the whole resolution."""
    colab.store.update({
        'NEO4J_URI': 'neo4j+s://from-colab',
        'NEO4J_USERNAME': 'neo4j',
        'NEO4J_PASSWORD': colab.no_access,
    })
    load_credentials(logger, env_file=_env_file(tmp_path, **ETL_VALUES))
    assert os.environ['NEO4J_URI'] == 'neo4j+s://from-colab'
    assert os.environ['NEO4J_PASSWORD'] == 'from-env'

def test_resolves_the_unenforced_group_too(logger, clean_env, colab, missing_env_file):
    """An ETL run should still leave the AGA keys readable."""
    colab.store.update(ETL_VALUES | {'AURA_CLIENT_ID': 'ci', 'AURA_CLIENT_SECRET': 'cs'})
    load_credentials(logger, env_file=missing_env_file)
    assert os.environ['AURA_CLIENT_ID'] == 'ci'

def test_optional_database_is_never_required(logger, clean_env, colab, missing_env_file):
    colab.store.update(ETL_VALUES)
    load_credentials(logger, env_file=missing_env_file)
    assert os.getenv('NEO4J_DATABASE') is None

def test_get_secret_prefers_the_environment_then_colab_then_default(
        monkeypatch, logger, clean_env, colab):
    monkeypatch.setenv('NEO4J_URI', 'bolt://exported')
    colab.store['AURA_CLIENT_ID'] = 'from-colab'
    assert get_secret('NEO4J_URI', logger) == 'bolt://exported'
    assert get_secret('AURA_CLIENT_ID', logger) == 'from-colab'
    assert get_secret('NOT_A_SECRET', logger, default='fallback') == 'fallback'

def test_the_secret_groups_do_not_overlap():
    assert not set(ETL_SECRETS) & set(AGA_SECRETS)
    assert set(credentials.ALL_SECRETS) == (
        set(ETL_SECRETS) | set(AGA_SECRETS) | set(credentials.OPTIONAL_SECRETS)
    )
