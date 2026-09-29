"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    api_client,
    make_case_manager_headers,
    make_compliance_officer_headers,
    make_program_coordinator_headers,
    make_sped_director_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def case_manager():
    return make_case_manager_headers()


@pytest.fixture
def case_manager_alt():
    return make_case_manager_headers("cm-002")


@pytest.fixture
def program_coordinator():
    return make_program_coordinator_headers()


@pytest.fixture
def sped_director():
    return make_sped_director_headers()


@pytest.fixture
def sped_director_alt():
    return make_sped_director_headers("dir-002")


@pytest.fixture
def compliance_officer():
    return make_compliance_officer_headers()
