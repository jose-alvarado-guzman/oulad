"""Module responsible for setting up the logger.

Functions
---------
def get_logger(dir_name:str) -> logging.Logger
    Format and retrieve the logger.
"""
import os
import sys
import logging
from pathlib import Path

def get_logger(dir_name:str) -> logging.Logger:
    """Format and retrieve the logger.

    Calling this more than once in the same process returns the logger as it
    was already configured. Handlers are only attached the first time, so
    re-entering the pipeline from a notebook cell does not emit every record
    once per call.

    Parameters
    ----------
    dir_name : str
        The full path of the directory where to store the import log.

    Returns
    -------
    logging.Logger
        The logger to use for logging the import events.
    """
    logger = logging.getLogger('OULAD')
    # Keyed on our own marker rather than on whether any handler is attached:
    # pytest, and anything else that captures logs, attaches handlers of its
    # own, and those must not be mistaken for this function's work.
    if getattr(logger, '_oulad_configured', False):
        return logger
    logger.setLevel(logging.INFO)
    # Colab attaches a handler to the root logger, which would print every
    # record a second time if the records were allowed to propagate.
    logger.propagate = False
    log_dir = os.path.join(dir_name, 'Logs')
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = os.path.join(log_dir,'import.log')
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger._oulad_configured = True
    return logger
