"""Module resposible for processing and loading all relationships.

Functions
---------
def prepare_rela_data(
        data_frames: Dict[str, pd.DataFrame],
        relas_config: Dict[str, Any],
        logger: logging.Logger
    ) -> Dict[str, pd.DataFrame]
    Prepare the data for all relationships.
def load_relationships(
        relas_data: Dict[str, pd.DataFrame],
        relas_config: Dict[str, Any],
        logger: logging.Logger
    ) -> None:
    Load all node to Neo4j.
"""

import os
import logging
import pandas as pd
from typing import Dict, Any
from pathlib import Path
from pyneoinstance import Neo4jInstance
from pyneoinstance.util.functions import get_file_name

def prepare_rela_data(
        data_frames: Dict[str, pd.DataFrame],
        relas_config: Dict[str, Any],
        logger: logging.Logger
    ) -> Dict[str, pd.DataFrame]:
    """Responsible for preparing all relationship types data frames.

    Parameters
    ----------
    data_frames : Dict[str, DataFrame]
        Dictionary containing the all the datasources.
    relas_config : Dict[str, Any]
        Dictionary where the key is the relationship type and the value is the
        corresponding information (cypher query, data file name, etc.)
    logger : Logger
        Logger use to log the pipeline progress.

    Returns
    -------
    Dict[str, DataFrame]
        Dictionary where the key is the relationship type and the value is a DataFrame
        with the corresponding data.
    """
    relas_data = {}
    for rela_type, rela_info in relas_config.items():
        dataframes = rela_info['dataframes']
        if len(dataframes) == 1:
            dataset = list(dataframes.keys())[0]
            column_list = dataframes[dataset]
            if column_list == None:
                columns = list(data_frames[dataset].columns)
            else:
                columns = column_list
            dataframe = data_frames[dataset][columns]
            if 'groupby' in rela_info:
                dataframe = dataframe.groupby(
                    rela_info['groupby']['group-cols']).agg(
                        {rela_info['groupby']['value-col']: rela_info['groupby']['functions']}
                    ).reset_index()
                dataframe.columns = rela_info['groupby']['group-cols'] + rela_info['groupby']['functions']
            else:
                dataframe = data_frames[dataset][
                    columns].drop_duplicates().reset_index(drop=True)
        elif len(dataframes) == 2:
            dataset1 = list(dataframes.keys())[0]
            dataset2 = list(dataframes.keys())[1]
            columns1 = dataframes[dataset1]
            columns2 = dataframes[dataset2]
            keys = relas_config[rela_type]['key']
            dataframe1 = data_frames[dataset1][columns1]
            dataframe2 = data_frames[dataset2][columns2]
            dataframe = pd.merge(
                dataframe1,
                dataframe2,
                on=keys).drop_duplicates().reset_index(drop=True)
        how = 'any' if rela_type=='IN_DEPRAVATION_GROUP' else 'all'
        dataframe = dataframe.dropna(how=how).reset_index(drop=True)
        relas_data[rela_type] = dataframe.sort_values(
            relas_config[rela_type]['sort-key']
        )
        msg = f'Completed processing the data for relationship {rela_type}'
        logger.info(msg)
    return relas_data

def load_relationships(
        relas_data: Dict[str, pd.DataFrame],
        relas_config: Dict[str, Any],
        logger: logging.Logger
    ) -> None:
    """Responsible for preparing all relationship data frames.

    Parameters
    ----------
    data_frames : Dict[str, DataFrame]
        Dictionary containing the all the datasources.
    relas_config : Dict[str, Any]
        Dictionary where the key is the relationship type and the value is the
        corresponding information (cypher query, data file name, etc.)
    logger : Logger
        Logger use to log the pipeline progress.

    Returns
    -------
    Dict[str, DataFrame]
        Dictionary where the key is the relationship type and the value is the
        correspinding DataFrame.
    """
    graph = Neo4jInstance(
        os.getenv('NEO4J_URI'),
        os.getenv('NEO4J_USERNAME'),
        os.getenv('NEO4J_PASSWORD')
    )
    load_results = []
    for rela_type, rela_info in relas_config.items():
        rela_result = {}
        parallel = False if rela_type == 'REVIEWED_MATERIAL' else True
        data = relas_data[rela_type]
        query = relas_config[rela_type]['cql']
        results = graph.execute_write_query_with_data(
            query,
            data,
            parallel=parallel,
            batchSize=200000
        )
        rela_result['relationshipType'] = rela_type
        rela_result['relasCreated'] = results.get('relationships_created') or 0
        rela_result['relasToLoad'] = data.shape[0]
        load_results.append(rela_result)
        logger.info(f'Loaded relationship {rela_type} with results: {results}')
    load_relas_qa(graph, load_results, logger)

def load_relas_qa(
    graph: Neo4jInstance,
    load_results: Dict[str, int],
    logger: logging.Logger) -> None:
    """Responsible for performing the quality check of the relationships loaded.

    Parameter
    ---------
    graph: Neo4jInstance
        Connection to Neo4j.
    load_results: List[Dict[str, int]]
        Results of the relationship load.
    logger : Logger
        Logger use to log the pipeline progress.
    """
    database = os.getenv('NEO4J_DATABASE') or 'neo4j'
    node_freq = graph.get_rela_type_freq(
        database=database).drop(
            columns=['relativeFrequency']).rename(
                columns={'frequency':'postRelaCount'})
    load_results_df = pd.DataFrame(load_results)
    qa_df = pd.merge(node_freq, load_results_df, on='relationshipType', how='right')
    qa_df['priorRelaCount'] = qa_df['postRelaCount'] - qa_df['relasCreated']
    qa_df['qaFlag'] = qa_df['relasToLoad'] - qa_df['postRelaCount']
    qa_file_name = get_file_name('csv',['relationships','qa','results'])
    dir_name = Path(__file__).resolve().parent.parent.parent
    result_dir = os.path.join(dir_name, 'Result')
    Path(result_dir).mkdir(parents=True, exist_ok=True)
    qa_file_path = os.path.join(result_dir, qa_file_name)
    columns = [
        'relationshipType',
        'priorRelaCount',
        'relasCreated',
        'postRelaCount',
        'relasToLoad',
        'qaFlag']
    qa_df = qa_df[columns]
    qa_df.to_csv(qa_file_path, index=False)
    logger.info(
        f"""Completed the relationship load quality check with the following results:
        {qa_df.to_string()}
        """
    )
