"""Module responsible for downloading and processing the OULAD datasource.

Functions
---------
get_data(url:str, data_path:str, logger:logging.Logger) -> None
    Download and decompress the OULAD datasource.
read_data(data_path:str, logger:logging.Logger) -> Dict[str, DataFrame]
    Load all the files to pandas data frames.
"""

import os
import shutil
import zipfile
import logging
import tempfile
import urllib.request
import pandas as pd
from typing import Dict, List

# Seconds a socket operation may stall before the download is abandoned. The
# point of the timeout is that a server which accepts the connection and then
# goes quiet cannot hang the pipeline indefinitely.
DOWNLOAD_TIMEOUT = 60
CHUNK_SIZE = 1024 * 1024

def _csv_files(data_path:str) -> List[str]:
    """List the csv files held in a directory.

    Parameters
    ----------
    data_path : str
        Path of the directory to inspect.

    Returns
    -------
    List[str]
        Sorted names of the csv files, empty when the directory is absent.
    """
    if not os.path.isdir(data_path):
        return []
    return sorted(
        f for f in os.listdir(data_path) if f.lower().endswith('.csv')
    )

def _download(url:str,
              dest_dir:str,
              logger: logging.Logger,
              timeout:int = DOWNLOAD_TIMEOUT
             ) -> str:
    """Stream the source archive into a directory.

    Parameters
    ----------
    url : str
        URL of the archive to fetch.
    dest_dir : str
        Directory to write the archive into.
    logger : Logger
        Logger use to log the pipeline progress.
    timeout : int, optional
        Seconds a socket operation may stall before the download is abandoned.

    Returns
    -------
    str
        Path of the downloaded archive.
    """
    archive = os.path.join(dest_dir, 'oulad.zip')
    with urllib.request.urlopen(url, timeout=timeout) as response:
        with open(archive, 'wb') as handle:
            shutil.copyfileobj(response, handle, CHUNK_SIZE)
    size = os.path.getsize(archive)
    logger.info(f'Downloaded {size:,.0f} bytes from {url}')
    return archive

def get_data(url:str,
             data_path:str,
             logger: logging.Logger
            ) -> None:
    """
    Responsible for downloading and decompressing the source data.

    The download is skipped when the target directory already holds csv files.
    Both the download and the extraction happen in a temporary directory that
    is discarded on failure, so an interrupted run cannot leave a partially
    extracted directory behind for the next run to mistake for a complete one.
    The transfer carries a socket timeout, so a server that stalls mid-stream
    raises rather than hanging the pipeline.

    Parameters
    ----------
    url : str
        URL containing the datasource.
    data_path : str
        Path of the directory to use to stored the decompressed files.
    logger : Logger
        Logger use to log the pipeline progress.
    """
    existing = _csv_files(data_path)
    if existing:
        logger.info(
            f'Skipping the download, {data_path} already holds '
            f'{len(existing)} csv files'
        )
        return
    logger.info('Downloading and extracting files')
    with tempfile.TemporaryDirectory() as work_dir:
        archive = _download(url, work_dir, logger)
        extract_dir = os.path.join(work_dir, 'extracted')
        with zipfile.ZipFile(archive, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        os.makedirs(data_path, exist_ok=True)
        for file_name in os.listdir(extract_dir):
            shutil.move(os.path.join(extract_dir, file_name), data_path)
    logger.info(
        f'Extracted {len(_csv_files(data_path))} csv files to {data_path}'
    )

def read_data(data_path:str,
              logger: logging.Logger
             ) -> Dict[str, pd.DataFrame]:
    """Function responsible for reading all the datafiles.

    Only csv files are read, so an unrelated file in the directory does not
    break the read.

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
        os.path.splitext(f)[0]:pd.read_csv(
            os.path.join(data_path,f)) for f
                  in _csv_files(data_path)
    }
    logger.info('Completed reading all data files with the following results:')
    for file_name, data in oulad_data.items():
        logger.info(f'File {file_name} contains {data.shape[0]:,.0f} records')
    return oulad_data
