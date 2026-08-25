"""Tests for the post-load quality check.

qaFlag is the only automated signal that the graph holds what the dataframes
contained, so the case where nothing landed has to be the loudest one.
"""

import pandas as pd
import pytest

from oulad.nodes import load_nodes_qa
from oulad.relationships import load_relas_qa
from tests.conftest import RESULT_DIR

class FakeGraph:
    """Stands in for Neo4jInstance, returning a canned frequency table."""

    def __init__(self, frame):
        self._frame = frame

    def get_node_label_freq(self, database=None):
        return self._frame.copy()

    def get_rela_type_freq(self, database=None):
        return self._frame.copy()

def _newest_result(pattern):
    return max(RESULT_DIR.glob(pattern), key=lambda p: p.stat().st_mtime)

def test_a_label_that_landed_nothing_reports_the_full_count(
        logger, clean_result_dir):
    """This used to come out as NaN, hiding a total failure."""
    freq = pd.DataFrame({
        'nodeLabel': ['Student'],
        'frequency': [28785],
        'relativeFrequency': [1.0],
    })
    load_nodes_qa(FakeGraph(freq), [
        {'nodeLabel': 'Student', 'nodesCreated': 28785, 'nodesToLoad': 28785},
        {'nodeLabel': 'Course', 'nodesCreated': 0, 'nodesToLoad': 22},
    ], logger)
    qa = pd.read_csv(_newest_result('node_qa_results_*.csv')).set_index('nodeLabel')
    assert qa.loc['Course', 'qaFlag'] == 22
    assert qa.loc['Course', 'postNodeCount'] == 0
    assert qa.loc['Student', 'qaFlag'] == 0

def test_the_node_qa_columns_stay_integers(logger, clean_result_dir):
    """A NaN anywhere used to turn every count into a float."""
    freq = pd.DataFrame({
        'nodeLabel': ['Student'],
        'frequency': [10],
        'relativeFrequency': [1.0],
    })
    load_nodes_qa(FakeGraph(freq), [
        {'nodeLabel': 'Student', 'nodesCreated': 10, 'nodesToLoad': 10},
        {'nodeLabel': 'Absent', 'nodesCreated': 0, 'nodesToLoad': 5},
    ], logger)
    qa = pd.read_csv(_newest_result('node_qa_results_*.csv'))
    assert not qa.isna().any().any()
    for column in ['priorNodeCount', 'nodesCreated', 'postNodeCount',
                   'nodesToLoad', 'qaFlag']:
        assert pd.api.types.is_integer_dtype(qa[column]), column

def test_a_relationship_type_that_landed_nothing_reports_the_full_count(
        logger, clean_result_dir):
    freq = pd.DataFrame({
        'relationshipType': ['WAS_REGISTERED'],
        'frequency': [31512],
        'relativeFrequency': [1.0],
    })
    load_relas_qa(FakeGraph(freq), [
        {'relationshipType': 'WAS_REGISTERED', 'relasCreated': 31512,
         'relasToLoad': 31512},
        {'relationshipType': 'HAS_MATERIAL', 'relasCreated': 0,
         'relasToLoad': 6364},
    ], logger)
    qa = pd.read_csv(
        _newest_result('relationships_qa_results_*.csv')
    ).set_index('relationshipType')
    assert qa.loc['HAS_MATERIAL', 'qaFlag'] == 6364
    assert qa.loc['WAS_REGISTERED', 'qaFlag'] == 0
    assert not qa.isna().any().any()

def test_prior_counts_reflect_an_already_populated_graph(logger, clean_result_dir):
    """Re-running against a loaded graph should show prior, not created."""
    freq = pd.DataFrame({
        'nodeLabel': ['Student'],
        'frequency': [28785],
        'relativeFrequency': [1.0],
    })
    load_nodes_qa(FakeGraph(freq), [
        {'nodeLabel': 'Student', 'nodesCreated': 0, 'nodesToLoad': 28785},
    ], logger)
    qa = pd.read_csv(_newest_result('node_qa_results_*.csv')).set_index('nodeLabel')
    assert qa.loc['Student', 'priorNodeCount'] == 28785
    assert qa.loc['Student', 'qaFlag'] == 0
