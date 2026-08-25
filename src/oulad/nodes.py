"""Module responsible for processing and loading all node labels.

Functions
---------
def prepare_node_data(
        data_frames: Dict[str, pd.DataFrame],
        nodes_config: Dict[str, Any],
        logger: logging.Logger,
        defaults: Dict[str, Any] = None
    ) -> Dict[str, pd.DataFrame]
    Prepare the data for all node labels.
def load_nodes(
        graph: Neo4jInstance,
        nodes_data: Dict[str, pd.DataFrame],
        nodes_config: Dict[str, Any],
        logger: logging.Logger,
        database: str = None,
        defaults: Dict[str, Any] = None
    ) -> None
    Load all nodes to Neo4j.
"""
import os
import logging
import pandas as pd
from typing import Dict, Any, List
from pathlib import Path
from pyneoinstance import Neo4jInstance
from pyneoinstance.util.functions import get_file_name

def prepare_node_data(
        data_frames: Dict[str, pd.DataFrame],
        nodes_config: Dict[str, Any],
        logger: logging.Logger,
        defaults: Dict[str, Any] = None
    ) -> Dict[str, pd.DataFrame]:
    """Responsible for preparing all nodes labels data frames.

    Parameters
    ----------
    data_frames : Dict[str, DataFrame]
        Dictionary containing the all the datasources.
    nodes_config : Dict[str, Any]
        Dictionary where the key is the node label and the value is the
        corresponding information (cypher query, data file name, etc.)
    logger : Logger
        Logger use to log the pipeline progress.
    defaults : Dict[str, Any], optional
        Settings applied to labels that do not override them, read from
        cypher.load.defaults.nodes in the configuration.

    Returns
    -------
    Dict[str, DataFrame]
        Dictionary where the key is the node label and the value is a DataFrame
        with the corresponding data.
    """
    defaults = defaults or {}
    nodes_data = {}
    for label, node_info in nodes_config.items():
        columns = node_info['columns']
        dataset = node_info['dataframe']
        how = node_info.get('dropna', defaults.get('dropna', 'all'))
        nodes_data[label] = data_frames[dataset][
            columns].drop_duplicates(
            ).dropna(how=how).reset_index(
                drop=True)
        logger.info(f'Completed processing the data for node label {label}')
    return nodes_data

def load_nodes(
        graph: Neo4jInstance,
        nodes_data: Dict[str, pd.DataFrame],
        nodes_config: Dict[str, Any],
        logger: logging.Logger,
        database: str = None,
        defaults: Dict[str, Any] = None
    ) -> None:
    """Responsible for loading all node labels to Neo4j.

    Parameters
    ----------
    graph : Neo4jInstance
        Connection to Neo4j.
    nodes_data: Dict[str, DataFrame]
        Dictionary where the key is the node label and the value is the
        corresponding DataFrame.
    nodes_config: Dict[str: Any]
        Dictionary where the key is the node label and the value is the
        corresponding configuration, included the cypher to load the data.
    logger : Logger
        Logger use to log the pipeline progress.
    database : str, optional
        Database to write to. Passed on so the load and the quality check both
        target the same database.
    defaults : Dict[str, Any], optional
        Settings applied to labels that do not override them, read from
        cypher.load.defaults.nodes in the configuration.
    """
    defaults = defaults or {}
    load_results = []
    for label, node_info in nodes_config.items():
        node_result = {}
        data = nodes_data[label]
        query = node_info['cql']
        kwargs = {
            'parallel': node_info.get(
                'parallel', defaults.get('parallel', True))
        }
        batch_size = node_info.get('batch-size', defaults.get('batch-size'))
        if batch_size:
            kwargs['batchSize'] = batch_size
        results = graph.execute_write_query_with_data(
            query,
            data,
            database=database,
            **kwargs
        )
        node_result['nodeLabel'] = label
        node_result['nodesCreated'] = results.get('nodes_created') or 0
        node_result['nodesToLoad'] = data.shape[0]
        load_results.append(node_result)
        logger.info(f'Loaded node {label} with results: {results}')
    load_nodes_qa(graph, load_results, logger, database)

def load_nodes_qa(
    graph: Neo4jInstance,
    load_results: List[Dict[str, int]],
    logger: logging.Logger,
    database: str = None) -> None:
    """Responsible for performing the quality check of the nodes loaded.

    Parameter
    ---------
    graph: Neo4jInstance
        Connection to Neo4j.
    load_results: List[Dict[str, int]]
        Results of the node load.
    logger : Logger
        Logger use to log the pipeline progress.
    database : str, optional
        Database the nodes were written to.
    """
    node_freq = graph.get_node_label_freq(
        database=database).drop(
            columns=['relativeFrequency']).rename(
                columns={'frequency':'postNodeCount'})
    load_results_df = pd.DataFrame(load_results)
    qa_df = pd.merge(node_freq, load_results_df, on='nodeLabel', how='right')
    # A label missing from the frequency table holds no nodes at all. Without
    # this the arithmetic below propagates NaN, so the one case qaFlag most
    # needs to report, a label where nothing landed, would come out blank.
    qa_df['postNodeCount'] = qa_df['postNodeCount'].fillna(0).astype(int)
    qa_df['priorNodeCount'] = qa_df['postNodeCount'] - qa_df['nodesCreated']
    qa_df['qaFlag'] = qa_df['nodesToLoad'] - qa_df['postNodeCount']
    qa_file_name = get_file_name('csv',['node','qa','results'])
    dir_name = Path(__file__).resolve().parent.parent.parent
    result_dir = os.path.join(dir_name, 'Result')
    Path(result_dir).mkdir(parents=True, exist_ok=True)
    qa_file_path = os.path.join(result_dir, qa_file_name)
    columns = [
        'nodeLabel',
        'priorNodeCount',
        'nodesCreated',
        'postNodeCount',
        'nodesToLoad',
        'qaFlag']
    qa_df = qa_df[columns]
    qa_df.to_csv(qa_file_path, index=False)
    logger.info(
        f"""Completed the node load quality check with the following results:
        {qa_df.to_string()}
        """
    )
