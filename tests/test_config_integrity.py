"""Checks that config.yaml agrees with itself and with the source CSVs.

These catch a rename, a typo, or a missing column offline, without a database.
The ones touching real data skip themselves when Data/ is absent.
"""

import re

import pytest

from oulad.nodes import prepare_node_data
from oulad.relationships import prepare_rela_data

def test_every_declared_label_has_a_node_key_constraint(config):
    declared = set(config['cypher']['load']['nodes'])
    constrained = set(
        re.findall(r'FOR \(n:(\w+)\)', '\n'.join(config['cypher']['pre-load']))
    )
    assert declared == constrained

def test_cypher_only_matches_declared_labels(config):
    """A renamed label would otherwise MATCH nothing and load zero rows."""
    load = config['cypher']['load']
    declared = set(load['nodes'])
    queries = [item['cql'] for item in load['nodes'].values()]
    queries += [item['cql'] for item in load['relationships'].values()]
    matched = set(re.findall(r'MATCH\(n\d:(\w+)', '\n'.join(queries)))
    assert matched <= declared, matched - declared

def test_the_dataset_url_is_https_and_names_an_archive(config):
    """The previous address redirected to a homepage and served html."""
    url = config['data']['url']
    assert url.startswith('https://')
    assert url.endswith('.zip')

def test_the_deprivation_spelling_is_not_reintroduced(config):
    """imd_band is the Index of Multiple Deprivation, not Depravation."""
    text = str(config)
    assert 'Depravation' not in text
    assert 'DEPRAVATION' not in text
    assert 'MultipleDeprivationIndex' in text

def test_node_sources_and_columns_exist(load_config, frame_columns):
    for label, info in load_config['nodes'].items():
        dataset = info['dataframe']
        assert dataset in frame_columns, f'{label} -> unknown dataframe {dataset}'
        missing = set(info['columns']) - set(frame_columns[dataset])
        assert not missing, f'{label} -> missing columns {missing}'

def test_relationship_sources_and_columns_exist(load_config, frame_columns):
    for rela_type, info in load_config['relationships'].items():
        for dataset, columns in info['dataframes'].items():
            assert dataset in frame_columns, f'{rela_type} -> unknown {dataset}'
            missing = set(columns or []) - set(frame_columns[dataset])
            assert not missing, f'{rela_type} -> missing columns {missing}'

def test_first_by_columns_are_selected(load_config):
    """first-by can only order by columns the frame actually carries."""
    for rela_type, info in load_config['relationships'].items():
        first_by = info.get('first-by')
        if not first_by:
            continue
        selected = set()
        for columns in info['dataframes'].values():
            selected.update(columns or [])
        needed = set(first_by['group-cols']) | set(first_by['order-cols'])
        assert needed <= selected, f'{rela_type} -> {needed - selected}'

def test_every_node_label_prepares_without_error(load_config, frame_columns):
    """Cheap end-to-end check of the node reshaping against real headers."""
    import pandas as pd
    from tests.conftest import DATA_DIR
    frames = {
        name: pd.read_csv(DATA_DIR / f'{name}.csv')
        for name in {info['dataframe'] for info in load_config['nodes'].values()}
    }
    import logging
    log = logging.getLogger('oulad-tests')
    prepared = prepare_node_data(
        frames, load_config['nodes'], log, load_config['defaults']['nodes'])
    assert set(prepared) == set(load_config['nodes'])
    for label, frame in prepared.items():
        assert not frame.empty, label

class TestSourceDataAssumptions:
    """Invariants the graph model depends on, verified against the CSVs."""

    def test_studied_credits_is_consistent_per_student_presentation(self, student_info):
        """StudentRegistration's MERGE key would otherwise lose data."""
        distinct = student_info.groupby(
            ['id_student', 'code_presentation'])['studied_credits'].nunique()
        assert (distinct > 1).sum() == 0

    @pytest.mark.parametrize('column', [
        'gender', 'disability', 'region', 'highest_education', 'imd_band'])
    def test_dimension_attributes_are_single_valued_per_student(
            self, student_info, column):
        distinct = student_info.groupby('id_student')[column].nunique(dropna=False)
        assert (distinct > 1).sum() == 0

    def test_age_band_is_the_one_multi_valued_attribute(self, student_info):
        """72 students crossed a band boundary between presentations."""
        distinct = student_info.groupby('id_student')['age_band'].nunique(dropna=False)
        assert (distinct > 1).sum() > 0

    def test_in_age_group_yields_exactly_one_row_per_student(
            self, student_info, load_config, logger):
        """The reason IN_AGE_GROUP carries a first-by block."""
        spec = {'IN_AGE_GROUP': load_config['relationships']['IN_AGE_GROUP']}
        prepared = prepare_rela_data(
            {'studentInfo': student_info}, spec, logger,
            load_config['defaults']['relationships'])['IN_AGE_GROUP']
        assert len(prepared) == student_info.id_student.nunique()
        assert prepared.groupby('id_student').size().max() == 1

    def test_in_age_group_picks_the_earliest_presentation(
            self, student_info, load_config, logger):
        spec = {'IN_AGE_GROUP': load_config['relationships']['IN_AGE_GROUP']}
        prepared = prepare_rela_data(
            {'studentInfo': student_info}, spec, logger,
            load_config['defaults']['relationships'])['IN_AGE_GROUP']
        expected = (student_info[['id_student', 'code_presentation', 'age_band']]
                    .sort_values(['id_student', 'code_presentation', 'age_band'])
                    .drop_duplicates(subset=['id_student'], keep='first')
                    .set_index('id_student')['age_band'])
        got = prepared.set_index('id_student')['age_band']
        assert got.sort_index().equals(expected.sort_index())

    def test_presentation_codes_sort_chronologically_as_strings(self, student_info):
        """first-by relies on this: fixed 4-digit year, B before J."""
        codes = sorted(student_info.code_presentation.unique())
        as_dates = sorted(
            codes, key=lambda c: (int(c[:4]), {'B': 2, 'J': 10}[c[4]]))
        assert codes == as_dates
