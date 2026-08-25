"""Tests for the relationship reshaping driver.

These use small synthetic frames rather than the real CSVs, so they run fast
and pin the behaviour rather than the dataset.
"""

import pandas as pd
import pytest

from oulad.relationships import prepare_rela_data

DEFAULTS = {'parallel': True, 'batch-size': 200000, 'dropna': 'all'}

@pytest.fixture
def frames():
    return {
        'left': pd.DataFrame({
            'id': [1, 2, 3],
            'key': ['a', 'b', 'c'],
            'value': [10, 20, 30],
        }),
        'right': pd.DataFrame({
            'key': ['a', 'b', 'c'],
            'extra': ['x', 'y', 'z'],
        }),
    }

def test_a_single_source_selects_the_named_columns(frames, logger):
    spec = {'T': {'dataframes': {'left': ['id', 'key']}, 'sort-key': ['key']}}
    out = prepare_rela_data(frames, spec, logger, DEFAULTS)['T']
    assert list(out.columns) == ['id', 'key']

def test_a_null_column_list_means_every_column(frames, logger):
    spec = {'T': {'dataframes': {'left': None}, 'sort-key': ['key']}}
    out = prepare_rela_data(frames, spec, logger, DEFAULTS)['T']
    assert list(out.columns) == ['id', 'key', 'value']

def test_a_null_column_list_works_on_the_two_source_branch(frames, logger):
    """The two-source branch used to index the frame with None."""
    spec = {'T': {
        'dataframes': {'left': None, 'right': ['key', 'extra']},
        'key': ['key'],
        'sort-key': ['key'],
    }}
    out = prepare_rela_data(frames, spec, logger, DEFAULTS)['T']
    assert set(out.columns) == {'id', 'key', 'value', 'extra'}
    assert len(out) == 3

def test_an_unsupported_source_count_names_the_relationship(frames, logger):
    """Three sources used to fail with UnboundLocalError."""
    frames['third'] = pd.DataFrame({'key': ['a']})
    spec = {'ODD_ONE': {
        'dataframes': {'left': None, 'right': None, 'third': None},
        'sort-key': ['key'],
    }}
    with pytest.raises(ValueError) as excinfo:
        prepare_rela_data(frames, spec, logger, DEFAULTS)
    assert 'ODD_ONE' in str(excinfo.value)

def test_dropna_all_keeps_partially_populated_rows(logger):
    frames = {'src': pd.DataFrame({'id': [1, 2], 'band': [None, 'x']})}
    spec = {'T': {'dataframes': {'src': None}, 'sort-key': ['id']}}
    out = prepare_rela_data(frames, spec, logger, DEFAULTS)['T']
    assert len(out) == 2

def test_dropna_any_drops_rows_with_a_null(logger):
    """A student with no imd_band should get no relationship."""
    frames = {'src': pd.DataFrame({'id': [1, 2], 'band': [None, 'x']})}
    spec = {'T': {
        'dataframes': {'src': None},
        'sort-key': ['id'],
        'dropna': 'any',
    }}
    out = prepare_rela_data(frames, spec, logger, DEFAULTS)['T']
    assert out['id'].tolist() == [2]

def test_groupby_aggregates_into_the_named_columns(logger):
    frames = {'src': pd.DataFrame({
        'student': [1, 1, 2],
        'site': [7, 7, 8],
        'date': [1, 1, 2],
        'clicks': [3, 4, 5],
    })}
    spec = {'T': {
        'dataframes': {'src': ['student', 'site', 'date', 'clicks']},
        'groupby': {
            'group-cols': ['student', 'site', 'date'],
            'value-col': 'clicks',
            'functions': ['count', 'sum'],
        },
        'sort-key': ['site'],
    }}
    out = prepare_rela_data(frames, spec, logger, DEFAULTS)['T']
    assert list(out.columns) == ['student', 'site', 'date', 'count', 'sum']
    row = out[out.student == 1].iloc[0]
    assert (row['count'], row['sum']) == (2, 7)

class TestFirstBy:
    """One row per group, chosen by the order columns."""

    SPEC = {'T': {
        'dataframes': {'src': None},
        'sort-key': ['band'],
        'first-by': {'group-cols': ['student'], 'order-cols': ['presentation', 'band']},
    }}

    def test_keeps_the_earliest_presentation(self, logger):
        frames = {'src': pd.DataFrame({
            'student': [1, 1, 2],
            'presentation': ['2014J', '2013B', '2013J'],
            'band': ['35-55', '0-35', '55<='],
        })}
        out = prepare_rela_data(frames, self.SPEC, logger, DEFAULTS)['T']
        assert len(out) == 2
        assert out[out.student == 1]['band'].item() == '0-35'

    def test_one_row_per_group(self, logger):
        frames = {'src': pd.DataFrame({
            'student': [1, 1, 1, 2, 2],
            'presentation': ['2013B', '2013J', '2014J', '2014B', '2014J'],
            'band': ['0-35', '0-35', '35-55', '35-55', '35-55'],
        })}
        out = prepare_rela_data(frames, self.SPEC, logger, DEFAULTS)['T']
        assert out.groupby('student').size().max() == 1

    def test_a_tie_inside_one_group_resolves_deterministically(self, logger):
        """Two bands in the same presentation is contradictory source data."""
        frames = {'src': pd.DataFrame({
            'student': [5, 5],
            'presentation': ['2014J', '2014J'],
            'band': ['35-55', '0-35'],
        })}
        first = prepare_rela_data(frames, self.SPEC, logger, DEFAULTS)['T']
        reversed_input = {'src': frames['src'].iloc[::-1].reset_index(drop=True)}
        second = prepare_rela_data(reversed_input, self.SPEC, logger, DEFAULTS)['T']
        assert first['band'].item() == second['band'].item() == '0-35'

def test_per_relationship_settings_override_the_defaults(logger, load_config):
    """The two behaviours that used to be hardcoded conditionals."""
    relas = load_config['relationships']
    assert relas['REVIEWED_MATERIAL']['parallel'] is False
    assert relas['IN_DEPRIVATION_GROUP']['dropna'] == 'any'
    defaults = load_config['defaults']['relationships']
    assert defaults['parallel'] is True
    assert defaults['dropna'] == 'all'
    assert defaults['batch-size'] == 200000
