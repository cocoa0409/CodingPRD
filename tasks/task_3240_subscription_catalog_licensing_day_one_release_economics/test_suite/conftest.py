"""Pytest fixtures exposing the generated test_helpers infrastructure."""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_subscriber_headers,
    set_clock,
    build_catalog_scenario,
    scenario_with_published_entry,
    scenario_with_subscriber,
    scenario_with_two_published_entries,
    scenario_with_two_subscribers_and_two_entries,
    scenario_with_two_expiring_deals,
    scenario_ready_to_purchase,
    scenario_ready_to_finalize,
    scenario_for_projection_boundary,
    capacity_scenario,
    create_projection,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner owns the server lifecycle."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def subscriber_headers():
    """Shared Subscriber constant — for calls that are not ownership-gated."""
    return TEST_USERS["subscriber_headers"]


@pytest.fixture
def subscriber_headers_for():
    """Returns the per-instance builder for the entity-backed Subscriber role.

    Usage in a test:
        headers = subscriber_headers_for(subscriber["id"])
    """
    return make_subscriber_headers


# ---------------------------------------------------------------------------
# Composite scenario fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def catalog_scenario(api):
    """Region + tier + publisher + title + signed LIVE deal at 2026-09-02."""
    return build_catalog_scenario(api)


@pytest.fixture
def published_catalog(api):
    """The catalogue scenario plus one published CATALOG_ADD entry."""
    return scenario_with_published_entry(api)


@pytest.fixture
def subscriber_with_catalog(api):
    """The published catalogue plus one subscriber on a paid subscription."""
    return scenario_with_subscriber(api)


@pytest.fixture
def two_published_entries(api):
    """One title with two published entries in the same region."""
    return scenario_with_two_published_entries(api)


@pytest.fixture
def two_subscribers_two_entries(api):
    """Two published entries and two paid subscribers, one entry each per subscriber."""
    return scenario_with_two_subscribers_and_two_entries(api)


@pytest.fixture
def two_expiring_deals(api):
    """Two signed deals, both EXPIRING, each with one published entry."""
    return scenario_with_two_expiring_deals(api)


@pytest.fixture
def ready_to_purchase(api):
    """Published catalogue plus a paid subscriber, ready to buy outright."""
    return scenario_ready_to_purchase(api)


@pytest.fixture
def ready_to_finalize(api):
    """Projection plus three COMPLETED purchases for the same title and region."""
    return scenario_ready_to_finalize(api)


@pytest.fixture
def projection_scenario(api):
    """The published catalogue the day-one ladder is read against."""
    return scenario_for_projection_boundary(api)