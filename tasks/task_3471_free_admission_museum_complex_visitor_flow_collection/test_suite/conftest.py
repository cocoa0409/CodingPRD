"""Pytest fixtures exposing the test_helpers infrastructure.

The server is restarted before every test, so there is deliberately no
state-bearing fixture here: the only session-scoped object is the HTTP client.
Everything a test needs is built inside the test through the helpers in
`test_helpers.fixtures`, which go through the public endpoints like any other
client.

The per-role fixtures hand out the shared default identities from TEST_USERS.
Ownership-gated calls (member-priced purchase, docent confirm, curator submit,
organizer cancel, segregation-of-duties decide) must instead build headers from
the resource's own ids via the `make_<role>_headers` builders in
`test_helpers.test_users` — the shared constants intentionally do not own
anything.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The HTTP client, one method per declared operation. Server lifecycle is
    managed by the runner; tests assume it is reachable."""
    return api_client


@pytest.fixture
def platform_admin() -> dict:
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def visitor_services() -> dict:
    return TEST_USERS["visitor_services_headers"]


@pytest.fixture
def security_screener() -> dict:
    return TEST_USERS["security_screener_headers"]


@pytest.fixture
def exhibition_manager() -> dict:
    return TEST_USERS["exhibition_manager_headers"]


@pytest.fixture
def program_coordinator() -> dict:
    return TEST_USERS["program_coordinator_headers"]


@pytest.fixture
def docent() -> dict:
    """Fallback Docent identity that owns nothing — only for probes where
    ownership is irrelevant. For confirms, use make_docent_headers(docent_id)."""
    return TEST_USERS["docent_headers"]


@pytest.fixture
def public() -> dict:
    return TEST_USERS["public_headers"]


@pytest.fixture
def public_2() -> dict:
    """A second Public caller, for multi-organizer scenarios."""
    return TEST_USERS["public_2_headers"]


@pytest.fixture
def member() -> dict:
    """Fallback Member identity that owns nothing — only for probes where
    ownership is irrelevant. For purchases, use make_member_headers(member_id)."""
    return TEST_USERS["member_headers"]


@pytest.fixture
def loans_officer() -> dict:
    return TEST_USERS["loans_officer_headers"]


@pytest.fixture
def borrower_rep() -> dict:
    return TEST_USERS["borrower_rep_headers"]


@pytest.fixture
def registrar() -> dict:
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def curator() -> dict:
    return TEST_USERS["curator_headers"]


@pytest.fixture
def curator_2() -> dict:
    """A second curator identity, for submit-ownership scenarios."""
    return TEST_USERS["curator_2_headers"]


@pytest.fixture
def committee_chair() -> dict:
    return TEST_USERS["committee_chair_headers"]


@pytest.fixture
def committee_chair_2() -> dict:
    """A second chair identity; segregation of duties needs a chair whose
    X-User-ID differs from the review's submitting curator."""
    return TEST_USERS["committee_chair_2_headers"]


@pytest.fixture
def finance_officer() -> dict:
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def scholar() -> dict:
    return TEST_USERS["scholar_headers"]


@pytest.fixture
def scholar_2() -> dict:
    return TEST_USERS["scholar_2_headers"]
