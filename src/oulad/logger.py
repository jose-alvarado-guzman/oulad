import os
import sys
import logging
from pathlib import Path

def get_logger(dir_name:str) -> logging.Logger:
    """Format and retrieve the logger.

    Patameters
    ----------
    dir_name : str
        The full path of the directory where to store the import log.

    Returns
    -------
    logging.Logger
        The logger to use for logging the import events.
    """
    console_handler = logging.StreamHandler(sys.stdout)
    log_dir = os.path.join(dir_name, 'Logs')
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = os.path.join(log_dir,'import.log')
    logger = logging.getLogger('OULAD')
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger
