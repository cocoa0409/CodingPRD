"""
Shared pytest fixtures for the Label Distribution Recoupment API suite.

The runner puts the task root on ``PYTHONPATH`` and exports ``API_BASE_URL``, so
``ApiClient()`` needs no arguments.

``api`` is function-scoped on purpose. The runner restarts the server before
every individual test, which means every test opens against an empty database
*and* against a brand-new listener; a session-scoped ``requests.Session`` would
carry keep-alive sockets to the previous, now-dead process into the next test.
A fresh client per test cannot.

Every precondition a test needs is therefore built inside that test from an empty
database, through the ``given_*`` composites in ``test_helpers.fixtures``.
"""

import pytest

from test_helpers import ApiClient
from test_helpers.test_users import (
    ANALYST,
    BIZ_AFFAIRS,
    LABEL_ADMIN,
    make_artist_headers,
    make_partner_headers,
)


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the freshly restarted server for this one test."""
    return ApiClient()


@pytest.fixture
def label_admin_headers():
    """LabelAdmin - an opaque operator identifier (PRD Section 2.1)."""
    return LABEL_ADMIN


@pytest.fixture
def analyst_headers():
    """RoyaltyAnalyst - an opaque operator identifier (PRD Section 2.1)."""
    return ANALYST


@pytest.fixture
def biz_affairs_headers():
    """BusinessAffairs - an opaque operator identifier (PRD Section 2.1)."""
    return BIZ_AFFAIRS


@pytest.fixture
def partner_headers_for():
    """Build DistributionPartner headers: "the X-User-ID is the id of the
    Distributor record"."""
    return make_partner_headers


@pytest.fixture
def artist_headers_for():
    """Build Artist headers: "the X-User-ID is the id of the Artist record"."""
    return make_artist_headers
