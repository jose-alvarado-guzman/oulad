"""Module resposible for downloading and processing the OULAD datasource.

Functions
---------
get_data(url:str, dir_name:str) -> None
    Download and decompressed the OULAD datasource.
read_data(dir_name:str) -> Dict[str, DataFrame]
    Load all the files to pandas data frames.
"""

import os
import wget
import zipfile
import logging
import pandas as pd
from typing import Dict

def get_data(url:str,
             data_path:str,
             logger: logging.Logger
            ) -> None:
    """
    Resposible for downloading and decompressing the source data.

    Parameters
    ----------
    url : str
        URL containing the datasource.
    data_path : str
        Path of the directory to use to stored the decompressed files.
    logger : Logger
        Logger use to log the pipeline progress.
    """
    if not os.path.isdir(data_path):
        logger.info('Downloading and extracting files')
        filename = wget.download(url)
        with zipfile.ZipFile(filename, "r") as zip_ref:
            zip_ref.extractall(data_path)
        os.remove(filename)

def read_data(data_path:str,
              logger: logging.Logger
             ) -> Dict[str, pd.DataFrame]:
    """Function responsible for reading all the datafiles.

    Parameters
    ----------
    data_path : str
       Path of the directory containing the csv files to read.
    logger : Logger
        Logger use to log the pipeline progress.

    Returns
    -------
    Dict[str, DataFrame]
        Dictionary where the key is the name of the file without the csv
        extension and the value is the corresponding DataFrame.

    """
    oulad_data = {
        f.split('.')[0]:pd.read_csv(
            os.path.join(data_path,f)) for f
                  in os.listdir(data_path)
    }
    logger.info('Completed reading all data files with the following results:')
    for file_name, data in oulad_data.items():
        logger.info(f'File {file_name} contains {data.shape[0]:,.0f} recods')
    return oulad_data
