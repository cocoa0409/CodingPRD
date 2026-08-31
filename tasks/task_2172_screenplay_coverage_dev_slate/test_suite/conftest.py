"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ADMIN,
    BA_APPROVER,
    BA_PAYER,
    EDITOR_APPROVE,
    EDITOR_ASSIGN,
    EXEC_ALPHA,
    EXEC_BETA,
    SUBMITTER,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's business."""
    return api_client


@pytest.fixture
def slate_admin_headers():
    return ADMIN


@pytest.fixture
def story_editor_headers():
    return EDITOR_ASSIGN


@pytest.fixture
def story_editor_approver_headers():
    return EDITOR_APPROVE


@pytest.fixture
def submitter_headers():
    return SUBMITTER


@pytest.fixture
def business_affairs_headers():
    return BA_APPROVER


@pytest.fixture
def business_affairs_payer_headers():
    return BA_PAYER


@pytest.fixture
def development_exec_headers():
    return EXEC_ALPHA


@pytest.fixture
def second_development_exec_headers():
    return EXEC_BETA


@pytest.fixture
def reader_headers():
    return TEST_USERS["reader_headers"]


@pytest.fixture
def writer_headers():
    return TEST_USERS["writer_headers"]


@pytest.fixture
def committee_member_headers():
    return TEST_USERS["committee_member_headers"]
