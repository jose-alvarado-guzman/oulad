"""Module resposible for processing and loading all node labels.

Functions
---------
def prepare_node_data(
        data_frames: Dict[str, pd.DataFrame],
        nodes_config: Dict[str, Any],
        logger: logging.Logger
    ) -> Dict[str, pd.DataFrame]
    Prepare the data for all node labels.
def load_nodes(
        nodes_data: Dict[str, pd.DataFrame],
        nodes_config: Dict[str, Any],
        logger: logging.Logger
    ) -> None:
    Load all node to Neo4j.
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
        logger: logging.Logger
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

    Returns
    -------
    Dict[str, DataFrame]
        Dictionary where the key is the node label and the value is a DataFrame
        with the corresponding data.
    """
    nodes_data = {}
    for label, node_info in nodes_config.items():
        columns = nodes_config[label]['columns']
        dataset = nodes_config[label]['dataframe']
        nodes_data[label] = data_frames[dataset][
            columns].drop_duplicates(
            ).dropna(how='all').reset_index(
                drop=True)
        logger.info(f'Completed processing the data for node label {label}')
    return nodes_data

def load_nodes(
        nodes_data: Dict[str, pd.DataFrame],
        nodes_config: Dict[str, Any],
        logger: logging.Logger
    ) -> None:
    """Responsible for loading all node labels to Neo4j.

    Parameters
    ----------
    nodes_data: Dict[str, DataFrame]
        Dictionary where the key is the node label and the value is the
        corresponding DataFrame.
    nodes_config: Dict[str: Any]
        Dictionary where the key is the node label and the value is the
        corresponding configuration, included the cypher to load the data.
    logger : Logger
        Logger use to log the pipeline progress.
    """
    graph = Neo4jInstance(
        os.getenv('NEO4J_URI'),
        os.getenv('NEO4J_USERNAME'),
        os.getenv('NEO4J_PASSWORD')
    )
    load_results = []
    for label, node_info in nodes_config.items():
        node_result = {}
        data = nodes_data[label]
        query = nodes_config[label]['cql']
        results = graph.execute_write_query_with_data(
            query,
            data,
            parallel=True
        )
        node_result['nodeLabel'] = label
        node_result['nodesCreated'] = results.get('nodes_created') or 0
        node_result['nodesToLoad'] = data.shape[0]
        load_results.append(node_result)
        logger.info(f'Loaded node {label} with results: {results}')
    load_nodes_qa(graph, load_results, logger)

def load_nodes_qa(
    graph: Neo4jInstance,
    load_results: Dict[str, int],
    logger: logging.Logger) -> None:
    """Responsible for performing the quality check of the nodes loaded.

    Parameter
    ---------
    graph: Neo4jInstance
        Connection to Neo4j.
    load_results: List[Dict[str, int]]
        Results of the node load.
    logger : Logger
        Logger use to log the pipeline progress.
    """
    database = os.getenv('NEO4J_DATABASE') or 'neo4j'
    node_freq = graph.get_node_label_freq(
        database=database).drop(
            columns=['relativeFrequency']).rename(
                columns={'frequency':'postNodeCount'})
    load_results_df = pd.DataFrame(load_results)
    qa_df = pd.merge(node_freq, load_results_df, on='nodeLabel', how='right')
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
