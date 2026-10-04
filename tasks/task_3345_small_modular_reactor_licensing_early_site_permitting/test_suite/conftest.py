"""Pytest wiring for the SMR Licensing & Early Site Permitting suite.

The harness restarts the API server before each test, so every test starts
against an empty database and builds the world it needs through the public
API. The base URL is injected into the environment by the runner, so the
client is constructed with no arguments.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS


@pytest.fixture()
def api() -> ApiClient:
    """A client aimed at the server under test."""
    return ApiClient()


@pytest.fixture()
def applicant_headers():
    return TEST_USERS["dca_applicant"]


@pytest.fixture()
def reviewer_headers():
    return TEST_USERS["nrc_reviewer"]


@pytest.fixture()
def doe_headers():
    return TEST_USERS["doe_program"]


@pytest.fixture()
def scm_headers():
    return TEST_USERS["supply_chain_manager"]


@pytest.fixture()
def auditor_headers():
    return TEST_USERS["vendor_auditor"]


@pytest.fixture()
def permit_applicant_headers():
    return TEST_USERS["site_permit_applicant"]


@pytest.fixture()
def intervenor_headers():
    return TEST_USERS["public_intervenor"]


@pytest.fixture()
def coordinator_headers():
    return TEST_USERS["workforce_coordinator"]
