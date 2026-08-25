"""Checks on the installed environment rather than on this project's code.

These exist to turn a confusing third-party import failure into a named test
with an explanation.
"""

import pytest

def test_traitlets_supports_a_subscripted_instance():
    """pyneoinstance cannot be imported without this.

    pyneoinstance imports neo4j-viz, whose widget module evaluates
    traitlets.Instance[...] while defining a class, so it runs at import time.
    Subscripting Instance only works from traitlets 5.10. neo4j-viz asks for
    traitlets>=5,<6, which an environment pinned to 5.7 already satisfies, so
    pip leaves it alone and the import dies with
    "type 'Instance' is not subscriptable". Colab pins exactly 5.7.1, which is
    why requirements.txt carries a traitlets>=5.10 floor of its own.
    """
    import traitlets
    try:
        traitlets.Instance[int]
    except TypeError as error:
        pytest.fail(
            f'traitlets {traitlets.__version__} cannot subscript Instance '
            f'({error}). Install traitlets>=5.10; in a notebook the session '
            'has to be restarted afterwards, because the old module is already '
            'loaded.'
        )

def test_pyneoinstance_imports():
    """The failure above surfaces here first in a fresh environment."""
    import pyneoinstance
    assert hasattr(pyneoinstance, 'Neo4jInstance')
