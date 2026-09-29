"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH, so `test_helpers` is importable without any
sys.path manipulation. Every fixture here is a thin bridge: all domain logic
lives in test_helpers.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by
    prd-bench-local-runner."""
    return api_client


@pytest.fixture
def sos_admin_headers():
    """SosAdmin — statutory configuration, clearance, cure periods, batch
    invalidation and reinstatement, round voiding, circulator discipline."""
    return TEST_USERS["sos_admin_headers"]


@pytest.fixture
def elections_examiner_headers():
    """ElectionsExaminer — format review, verification rounds, fraud
    referrals, determinations."""
    return TEST_USERS["elections_examiner_headers"]


@pytest.fixture
def second_examiner_headers():
    """A second ElectionsExaminer identity, for segregation of duties."""
    return TEST_USERS["second_examiner_headers"]


@pytest.fixture
def third_examiner_headers():
    """A third ElectionsExaminer identity: exam-1 tallies, exam-2 opens a
    referral, exam-3 adjudicates it."""
    return TEST_USERS["third_examiner_headers"]


@pytest.fixture
def title_examiner_headers():
    """TitleExaminer — the only role permitted to write a petition's official
    title and summary."""
    return TEST_USERS["title_examiner_headers"]


@pytest.fixture
def proponent_headers():
    """Proponent — files and submits its own petitions."""
    return TEST_USERS["proponent_headers"]


@pytest.fixture
def other_proponent_headers():
    """A second Proponent identity, for ownership checks."""
    return TEST_USERS["other_proponent_headers"]


@pytest.fixture
def challenger_headers():
    """Challenger — files a challenge and escalates it to court review."""
    return TEST_USERS["challenger_headers"]


@pytest.fixture
def other_challenger_headers():
    """A second Challenger identity, for ERR_NOT_CHALLENGE_OWNER."""
    return TEST_USERS["other_challenger_headers"]


@pytest.fixture
def county_clerk_headers():
    """CountyClerk whose X-User-ID matches no County. Only for tests that stop
    before the ownership comparison of §2.1."""
    return TEST_USERS["county_clerk_headers"]


@pytest.fixture
def circulator_agent_headers():
    """CirculatorAgent whose X-User-ID matches no Circulator. Only for tests
    that stop before the ownership comparison of §2.1."""
    return TEST_USERS["circulator_agent_headers"]
