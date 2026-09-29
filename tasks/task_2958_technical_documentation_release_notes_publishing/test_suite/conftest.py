"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    DOCS_LEAD_ALT_USER_ID,
    DOCS_LEAD_USER_ID,
    TEST_USERS,
    ApiClient,
    api_client,
    make_docs_lead_headers,
    make_localization_coordinator_headers,
    make_reader_headers,
    make_reviewer_headers,
    make_support_analyst_headers,
    make_writer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def docs_lead_headers() -> dict:
    """Headers for the primary ``DocsLead`` operator identity."""
    return make_docs_lead_headers()


@pytest.fixture
def docs_lead_alt_headers() -> dict:
    """A second ``DocsLead`` identity, for editorial segregation of duties."""
    return make_docs_lead_headers(DOCS_LEAD_ALT_USER_ID)


@pytest.fixture
def localization_coordinator_headers() -> dict:
    return make_localization_coordinator_headers()


@pytest.fixture
def support_analyst_headers() -> dict:
    return make_support_analyst_headers()


@pytest.fixture
def reader_headers() -> dict:
    return make_reader_headers()


@pytest.fixture
def writer_headers_for():
    """Builder for ``Writer`` headers bound to a real ``Writer.id``."""
    return make_writer_headers


@pytest.fixture
def reviewer_headers_for():
    """Builder for ``Reviewer`` headers bound to a real ``Reviewer.id``."""
    return make_reviewer_headers


@pytest.fixture
def docs_lead_user_id() -> str:
    return DOCS_LEAD_USER_ID


@pytest.fixture
def test_users() -> dict:
    return TEST_USERS
