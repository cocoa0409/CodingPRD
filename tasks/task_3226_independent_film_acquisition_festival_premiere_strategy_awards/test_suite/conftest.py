"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def acq_exec_headers():
    return TEST_USERS["acq_exec_headers"]


@pytest.fixture
def acq_exec_2_headers():
    return TEST_USERS["acq_exec_2_headers"]


@pytest.fixture
def festival_prog_headers():
    return TEST_USERS["festival_prog_headers"]


@pytest.fixture
def dist_exec_headers():
    return TEST_USERS["dist_exec_headers"]


@pytest.fixture
def awards_strat_headers():
    return TEST_USERS["awards_strat_headers"]


@pytest.fixture
def awards_strat_2_headers():
    return TEST_USERS["awards_strat_2_headers"]


@pytest.fixture
def talent_coord_headers():
    return TEST_USERS["talent_coord_headers"]


@pytest.fixture
def part_acct_headers():
    return TEST_USERS["part_acct_headers"]
