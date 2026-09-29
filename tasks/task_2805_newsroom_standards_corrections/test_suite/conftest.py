"""Shared fixtures for the Newsroom Standards & Corrections test suite.

The harness restarts the API server before each individual test, so the
database is empty at the start of every test function.  Anything a test needs
it therefore builds for itself; the fixtures below only supply the client and
the headers that do not depend on persisted records.

Four of the five roles in PRD §2.1 are entity-backed — the ``X-User-ID`` must
be the identifier of a real ``Journalist`` or of a real ``Reviewer`` — so those
headers are derived from the record a test creates, through the
``make_*_headers`` factories, rather than from a fixed constant.
"""

from typing import Dict

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    constants as C,
    make_bootstrap_exec_headers,
    make_public_editor_headers,
)
from test_helpers import fixtures as W


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The HTTP client, pointed at the server the harness launched."""
    return api_client


@pytest.fixture
def bootstrap_exec_headers() -> Dict[str, str]:
    """The bootstrap-exempt ``ExecutiveEditor`` identity of PRD §2.1."""
    return make_bootstrap_exec_headers()


@pytest.fixture
def public_editor_headers() -> Dict[str, str]:
    """The opaque ``PublicEditor`` operator identity of PRD §2.1."""
    return TEST_USERS["public_editor"]


@pytest.fixture
def alternate_public_editor_headers() -> Dict[str, str]:
    """A second opaque reader-advocate operator identifier."""
    return make_public_editor_headers("reader-advocate-desk")


@pytest.fixture
def desk(api: ApiClient) -> W.Desk:
    """A newsroom on default policy with its executive editor, standards
    editor and lead reporter already on the masthead."""
    return W.build_desk(api)


@pytest.fixture
def reporter_headers(desk: W.Desk) -> Dict[str, str]:
    """Headers for the desk's lead reporter, bound to their own record."""
    return desk.reporter_headers


@pytest.fixture
def standards_editor_headers(desk: W.Desk) -> Dict[str, str]:
    """Headers for the desk's standards editor, bound to their own record."""
    return desk.sed_headers


@pytest.fixture
def executive_editor_headers(desk: W.Desk) -> Dict[str, str]:
    """Headers for the desk's executive editor, bound to their own record."""
    return desk.exec_headers


@pytest.fixture
def legal_reviewer(api: ApiClient, desk: W.Desk) -> Dict[str, str]:
    """A registered ``LEGAL`` reviewer, the record a ``LegalCounsel`` identity
    is bound to."""
    return W.add_legal_reviewer(api, desk)


@pytest.fixture
def clock_epoch() -> str:
    """The instant the logical clock starts at, per PRD §2.5."""
    return C.CLOCK_EPOCH_MS
