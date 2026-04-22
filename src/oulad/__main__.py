"""This module is the entry point of the package"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from pyneoinstance import load_yaml_file, Neo4jInstance
from oulad.datasource import get_data, read_data
from oulad.nodes import prepare_node_data, load_nodes
from oulad.relationships import prepare_rela_data, load_relationships
from oulad.logger import get_logger

def main():
    load_dotenv()
    dir_name = Path(__file__).resolve().parent.parent.parent
    config_file_path = os.path.join(dir_name, 'config.yaml')
    logger = get_logger(dir_name)

    try:
        config = load_yaml_file(config_file_path)
    except FileNotFoundError:
        logger.error('The config.yaml file was not found')
        sys.exit(1)
    data_info = config['data']
    nodes_info = config['cypher']['load']['nodes']
    relas_info = config['cypher']['load']['relationships']
    pre_load = config['cypher']['pre-load']
    data_path = os.path.join(dir_name,data_info['dir'])
    get_data(data_info['url'], data_path, logger)
    data_frames = read_data(data_path, logger)
    node_data = prepare_node_data(data_frames, nodes_info, logger)
    graph = Neo4jInstance(
        os.getenv('NEO4J_URI'),
        os.getenv('NEO4J_USERNAME'),
        os.getenv('NEO4J_PASSWORD')
    )
    results = graph.execute_write_queries(pre_load)
    logger.info(f'Executed pre-load queries with results: {results}')
    load_nodes(node_data, nodes_info, logger)
    rela_data = prepare_rela_data(data_frames, relas_info, logger)
    load_relationships(rela_data, relas_info, logger)

if __name__ == '__main__':
    main()
