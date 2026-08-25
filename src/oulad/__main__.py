"""This module is the entry point of the package"""

import os
import sys
import yaml
from pathlib import Path
from pyneoinstance import load_yaml_file, Neo4jInstance
from oulad.datasource import get_data, read_data
from oulad.nodes import prepare_node_data, load_nodes
from oulad.relationships import prepare_rela_data, load_relationships
from oulad.credentials import load_credentials, MissingCredentialsError
from oulad.logger import get_logger

def main():
    dir_name = Path(__file__).resolve().parent.parent.parent
    config_file_path = os.path.join(dir_name, 'config.yaml')
    logger = get_logger(dir_name)

    try:
        load_credentials(logger)
    except MissingCredentialsError as error:
        logger.error(error)
        sys.exit(1)

    try:
        config = load_yaml_file(config_file_path)
    except FileNotFoundError:
        logger.error('The config.yaml file was not found')
        sys.exit(1)
    except yaml.YAMLError as error:
        logger.error(f'The config.yaml file could not be parsed: {error}')
        sys.exit(1)
    data_info = config['data']
    load_info = config['cypher']['load']
    nodes_info = load_info['nodes']
    relas_info = load_info['relationships']
    defaults = load_info.get('defaults', {})
    node_defaults = defaults.get('nodes', {})
    rela_defaults = defaults.get('relationships', {})
    pre_load = config['cypher']['pre-load']
    data_path = os.path.join(dir_name,data_info['dir'])
    # Connect and create the constraints before the download and the reshaping.
    # The constraints do not depend on the data, and doing this first means an
    # unreachable database or a wrong password surfaces in seconds instead of
    # after the dataset has been fetched and the largest frames built.
    # One connection and one database for every write, so the loads and the
    # quality checks that count them cannot end up targeting different ones.
    database = os.getenv('NEO4J_DATABASE') or None
    graph = Neo4jInstance(
        os.getenv('NEO4J_URI'),
        os.getenv('NEO4J_USERNAME'),
        os.getenv('NEO4J_PASSWORD')
    )
    results = graph.execute_write_queries(pre_load, database=database)
    logger.info(f'Executed pre-load queries with results: {results}')
    get_data(data_info['url'], data_path, logger)
    data_frames = read_data(data_path, logger)
    node_data = prepare_node_data(data_frames, nodes_info, logger, node_defaults)
    load_nodes(graph, node_data, nodes_info, logger, database, node_defaults)
    rela_data = prepare_rela_data(data_frames, relas_info, logger, rela_defaults)
    load_relationships(
        graph, rela_data, relas_info, logger, database, rela_defaults)

if __name__ == '__main__':
    main()
