"""Module responsible for processing and loading all relationships.

Functions
---------
def prepare_rela_data(
        data_frames: Dict[str, pd.DataFrame],
        relas_config: Dict[str, Any],
        logger: logging.Logger,
        defaults: Dict[str, Any] = None
    ) -> Dict[str, pd.DataFrame]
    Prepare the data for all relationships.
def load_relationships(
        graph: Neo4jInstance,
        relas_data: Dict[str, pd.DataFrame],
        relas_config: Dict[str, Any],
        logger: logging.Logger,
        database: str = None,
        defaults: Dict[str, Any] = None
    ) -> None
    Load all relationships to Neo4j.
"""

import os
import logging
import pandas as pd
from typing import Dict, Any, List
from pathlib import Path
from pyneoinstance import Neo4jInstance
from pyneoinstance.util.functions import get_file_name

def _source_columns(
        data_frames: Dict[str, pd.DataFrame],
        dataframes: Dict[str, Any],
        dataset: str
    ) -> List[str]:
    """Resolve the columns to select from one source dataframe.

    Parameters
    ----------
    data_frames : Dict[str, DataFrame]
        Dictionary containing all the datasources.
    dataframes : Dict[str, Any]
        The dataframes block of a relationship type, where a null column list
        means every column of that source.
    dataset : str
        Name of the source to resolve.

    Returns
    -------
    List[str]
        Names of the columns to select.
    """
    columns = dataframes[dataset]
    if columns is None:
        return list(data_frames[dataset].columns)
    return columns

def prepare_rela_data(
        data_frames: Dict[str, pd.DataFrame],
        relas_config: Dict[str, Any],
        logger: logging.Logger,
        defaults: Dict[str, Any] = None
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
    defaults : Dict[str, Any], optional
        Settings applied to relationship types that do not override them, read
        from cypher.load.defaults.relationships in the configuration.

    Returns
    -------
    Dict[str, DataFrame]
        Dictionary where the key is the relationship type and the value is a DataFrame
        with the corresponding data.
    """
    defaults = defaults or {}
    relas_data = {}
    for rela_type, rela_info in relas_config.items():
        dataframes = rela_info['dataframes']
        if len(dataframes) == 1:
            dataset = list(dataframes.keys())[0]
            columns = _source_columns(data_frames, dataframes, dataset)
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
            columns1 = _source_columns(data_frames, dataframes, dataset1)
            columns2 = _source_columns(data_frames, dataframes, dataset2)
            keys = rela_info['key']
            dataframe1 = data_frames[dataset1][columns1]
            dataframe2 = data_frames[dataset2][columns2]
            dataframe = pd.merge(
                dataframe1,
                dataframe2,
                on=keys).drop_duplicates().reset_index(drop=True)
        else:
            raise ValueError(
                f'Relationship {rela_type} lists {len(dataframes)} source '
                'dataframes, but only one or two are supported.'
            )
        how = rela_info.get('dropna', defaults.get('dropna', 'all'))
        dataframe = dataframe.dropna(how=how).reset_index(drop=True)
        first_by = rela_info.get('first-by')
        if first_by:
            group_cols = first_by['group-cols']
            dataframe = dataframe.sort_values(
                group_cols + first_by['order-cols']
            ).drop_duplicates(
                subset=group_cols, keep='first').reset_index(drop=True)
        relas_data[rela_type] = dataframe.sort_values(
            rela_info['sort-key']
        )
        msg = f'Completed processing the data for relationship {rela_type}'
        logger.info(msg)
    return relas_data

def load_relationships(
        graph: Neo4jInstance,
        relas_data: Dict[str, pd.DataFrame],
        relas_config: Dict[str, Any],
        logger: logging.Logger,
        database: str = None,
        defaults: Dict[str, Any] = None
    ) -> None:
    """Responsible for loading all relationships to Neo4j.

    Parameters
    ----------
    graph : Neo4jInstance
        Connection to Neo4j.
    relas_data : Dict[str, DataFrame]
        Dictionary where the key is the relationship type and the value is the
        corresponding DataFrame.
    relas_config : Dict[str, Any]
        Dictionary where the key is the relationship type and the value is the
        corresponding information (cypher query, data file name, etc.)
    logger : Logger
        Logger use to log the pipeline progress.
    database : str, optional
        Database to write to. Passed on so the load and the quality check both
        target the same database.
    defaults : Dict[str, Any], optional
        Settings applied to relationship types that do not override them, read
        from cypher.load.defaults.relationships in the configuration.
    """
    defaults = defaults or {}
    load_results = []
    for rela_type, rela_info in relas_config.items():
        rela_result = {}
        data = relas_data[rela_type]
        query = rela_info['cql']
        kwargs = {
            'parallel': rela_info.get(
                'parallel', defaults.get('parallel', True))
        }
        batch_size = rela_info.get('batch-size', defaults.get('batch-size'))
        if batch_size:
            kwargs['batchSize'] = batch_size
        results = graph.execute_write_query_with_data(
            query,
            data,
            database=database,
            **kwargs
        )
        rela_result['relationshipType'] = rela_type
        rela_result['relasCreated'] = results.get('relationships_created') or 0
        rela_result['relasToLoad'] = data.shape[0]
        load_results.append(rela_result)
        logger.info(f'Loaded relationship {rela_type} with results: {results}')
    load_relas_qa(graph, load_results, logger, database)

def load_relas_qa(
    graph: Neo4jInstance,
    load_results: List[Dict[str, int]],
    logger: logging.Logger,
    database: str = None) -> None:
    """Responsible for performing the quality check of the relationships loaded.

    Parameter
    ---------
    graph: Neo4jInstance
        Connection to Neo4j.
    load_results: List[Dict[str, int]]
        Results of the relationship load.
    logger : Logger
        Logger use to log the pipeline progress.
    database : str, optional
        Database the relationships were written to.
    """
    node_freq = graph.get_rela_type_freq(
        database=database).drop(
            columns=['relativeFrequency']).rename(
                columns={'frequency':'postRelaCount'})
    load_results_df = pd.DataFrame(load_results)
    qa_df = pd.merge(node_freq, load_results_df, on='relationshipType', how='right')
    # A type missing from the frequency table holds no relationships at all.
    # Without this the arithmetic below propagates NaN, so the one case qaFlag
    # most needs to report, a type where nothing landed, would come out blank.
    qa_df['postRelaCount'] = qa_df['postRelaCount'].fillna(0).astype(int)
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
