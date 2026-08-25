"""Tests for the logger setup."""

import logging

import pytest

from oulad.logger import get_logger

OURS = {'FileHandler', 'StreamHandler'}

@pytest.fixture(autouse=True)
def reset_oulad_logger():
    """Undo this module's configuration around each test.

    Only the handlers get_logger installs are removed. Anything a log-capturing
    plugin attached is left alone, since production code has to tolerate those.
    """
    log = logging.getLogger('OULAD')

    def clear():
        for handler in list(log.handlers):
            if type(handler).__name__ in OURS:
                handler.close()
                log.removeHandler(handler)
        log.propagate = True
        if hasattr(log, '_oulad_configured'):
            del log._oulad_configured

    clear()
    yield
    clear()

def test_repeated_calls_configure_once(tmp_path):
    """Re-entering main from a notebook cell must not multiply the output."""
    first = get_logger(str(tmp_path))
    attached = len(first.handlers)
    second = get_logger(str(tmp_path))
    third = get_logger(str(tmp_path))
    assert first is second is third
    assert len(third.handlers) == attached

def test_installs_exactly_one_file_and_one_console_handler(tmp_path):
    log = get_logger(str(tmp_path))
    get_logger(str(tmp_path))
    kinds = [type(handler).__name__ for handler in log.handlers]
    assert kinds.count('FileHandler') == 1
    assert kinds.count('StreamHandler') == 1

def test_a_foreign_handler_does_not_suppress_configuration(tmp_path):
    """The guard used to key on any handler being present."""
    log = logging.getLogger('OULAD')
    log.addHandler(logging.NullHandler())
    try:
        get_logger(str(tmp_path))
        kinds = [type(handler).__name__ for handler in log.handlers]
        assert kinds.count('FileHandler') == 1
    finally:
        for handler in list(log.handlers):
            if isinstance(handler, logging.NullHandler):
                log.removeHandler(handler)

def test_records_do_not_propagate_to_root(tmp_path):
    """Colab puts a handler on the root logger; propagating would double up."""
    assert get_logger(str(tmp_path)).propagate is False

def test_creates_the_log_file(tmp_path):
    log = get_logger(str(tmp_path))
    log.info('a line')
    log_file = tmp_path / 'Logs' / 'import.log'
    assert log_file.is_file()
    assert 'a line' in log_file.read_text()
