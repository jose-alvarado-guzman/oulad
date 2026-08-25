"""Tests for downloading and reading the source data."""

import os
import zipfile

import pytest

from oulad import datasource
from oulad.datasource import get_data, read_data

def _stub_download(zip_source):
    """Build a wget.download replacement that copies a prepared archive."""
    import shutil

    def download(url, out=None):
        dest = os.path.join(out, 'oulad.zip')
        shutil.copy(zip_source, dest)
        return dest

    return download

def test_read_data_ignores_non_csv_files(tmp_path, logger):
    """A stray .DS_Store used to reach pd.read_csv and break the run."""
    (tmp_path / '.DS_Store').write_bytes(b'\x00junk')
    (tmp_path / 'notes.txt').write_text('junk')
    (tmp_path / 'courses.csv').write_text('a,b\n1,2\n')
    (tmp_path / 'UPPER.CSV').write_text('a,b\n3,4\n')
    frames = read_data(str(tmp_path), logger)
    assert sorted(frames) == ['UPPER', 'courses']
    assert len(frames['courses']) == 1

def test_read_data_keys_strip_only_the_extension(tmp_path, logger):
    """The keys are the contract config.yaml references dataframes by."""
    (tmp_path / 'studentInfo.csv').write_text('a\n1\n')
    (tmp_path / 'my.data.csv').write_text('a\n1\n')
    frames = read_data(str(tmp_path), logger)
    assert sorted(frames) == ['my.data', 'studentInfo']

def test_get_data_skips_when_csvs_are_present(tmp_path, logger, monkeypatch):
    """An existing Data/ must not trigger a download."""
    (tmp_path / 'courses.csv').write_text('a\n1\n')
    calls = []
    monkeypatch.setattr(
        datasource.wget, 'download', lambda *a, **k: calls.append(a))
    get_data('http://not.used', str(tmp_path), logger)
    assert calls == []

def test_get_data_ignores_a_directory_holding_no_csvs(tmp_path, logger, monkeypatch):
    """The old check trusted the directory's existence alone."""
    target = tmp_path / 'Data'
    target.mkdir()
    (target / 'leftover.txt').write_text('junk')
    archive = tmp_path / 'src.zip'
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr('courses.csv', 'a,b\n1,2\n')
    monkeypatch.setattr(datasource.wget, 'download', _stub_download(archive))
    get_data('http://stub', str(target), logger)
    assert (target / 'courses.csv').is_file()

def test_get_data_extracts_into_the_target(tmp_path, logger, monkeypatch):
    archive = tmp_path / 'src.zip'
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr('courses.csv', 'a,b\n1,2\n')
        zf.writestr('vle.csv', 'a,b\n3,4\n')
    monkeypatch.setattr(datasource.wget, 'download', _stub_download(archive))
    target = tmp_path / 'Data'
    get_data('http://stub', str(target), logger)
    assert sorted(p.name for p in target.glob('*')) == ['courses.csv', 'vle.csv']

def test_a_failed_extract_leaves_no_partial_directory(tmp_path, logger, monkeypatch):
    """An interrupted run must not leave state the next run reads as complete."""
    def bad_download(url, out=None):
        path = os.path.join(out, 'bad.zip')
        with open(path, 'w') as handle:
            handle.write('not a zip file')
        return path

    monkeypatch.setattr(datasource.wget, 'download', bad_download)
    target = tmp_path / 'Data'
    with pytest.raises(zipfile.BadZipFile):
        get_data('http://stub', str(target), logger)
    assert not target.exists()

def test_a_failed_extract_leaves_no_archive_behind(tmp_path, logger, monkeypatch):
    """The download used to land in the working directory and stay there."""
    def bad_download(url, out=None):
        path = os.path.join(out, 'bad.zip')
        with open(path, 'w') as handle:
            handle.write('not a zip file')
        return path

    monkeypatch.setattr(datasource.wget, 'download', bad_download)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(zipfile.BadZipFile):
        get_data('http://stub', str(tmp_path / 'Data'), logger)
    assert list(tmp_path.glob('*.zip')) == []
