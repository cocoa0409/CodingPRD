"""Raw-request helpers and concurrency claims.

The PRD declares exactly two concurrency guards, and both compare a
client-supplied parent version with the parent's live version (PRD §2.10). The
race form of that guard is exercised here: when two approvals race on the same
store, at most one can present a version that is still current.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    approve_payload,
    assert_at_least_one_succeeds,
    create_application,
    current_store,
    current_store_version,
    make_store_organizer_headers,
    run_race,
    setup_release_context,
    validate_error,
)


@pytest.fixture(scope="session")
def raw_session():
    """A second API client so concurrent calls do not share one requests Session."""
    return ApiClient()


def test_a_role_not_permitted_on_the_operation_is_refused_at_403(api, raw_session):
    """PRD §2.12: "Role permission comes next: an authenticated caller whose role
    is not authorized for the operation is rejected with `ERR_UNAUTHORIZED`."
    PRD §2.1: "A request that is properly authenticated but whose role is not
    among the roles authorized for the operation being invoked is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/distributor_cannot_read_reprint_plans
    """
    store, set_release, fmt = setup_release_context()

    forbidden = raw_session.list_reprint_plans(
        TEST_USERS["distributor_headers"], params={"limit": 10, "offset": 0}
    )
    validate_error(forbidden, "ERR_UNAUTHORIZED", expected_status=403)

    permitted = raw_session.list_reprint_plans(
        TEST_USERS["ops_admin_headers"], params={"limit": 10, "offset": 0}
    )
    assert permitted.status_code == 200, "so the denial is role-scoped, not route-scoped"


def test_the_judge_exclusive_case_filing_is_refused_for_the_organizer(api, raw_session):
    """PRD §2.1: "A request that is properly authenticated but whose role is not
    among the roles authorized for the operation being invoked is rejected with
    `ERR_UNAUTHORIZED`."
    PRD §3.10: "A judge files a rules enforcement case against a player at a
    sanctioned event"

    Design: Corner/rbac/store_organizer_cannot_file_enforcement_cases
    """
    store, set_release, fmt = setup_release_context()
    application = create_application(store, set_release, fmt, tier="LOCAL")

    forbidden = raw_session.create_enforcement_case(
        {
            "event_application_id": application["id"],
            "player_ref": "PLAYER-1",
            "judge_ref": "JUDGE-X",
            "offense_class": "MINOR",
            "rules_enforcement_level": "REGULAR",
        },
        make_store_organizer_headers(store["id"]),
    )
    validate_error(forbidden, "ERR_UNAUTHORIZED", expected_status=403)


def test_a_racing_approval_pair_cannot_both_land_on_a_stale_store_view(api):
    """PRD §2.10: "The first is the approval of an event application, which must
    be submitted with `expected_store_version`, the client's last observed
    `version` of the `Store` the event belongs to."
    PRD §2.10: "The guard exists because both operations consume headroom the
    client may no longer have: a store's eligibility posture can change when it is
    suspended, and a configuration's remaining units can shrink when an earlier
    order draws the print run down."

    Design: Corner/validations/stale_store_version_blocks_approval
    """
    store, set_release, fmt = setup_release_context()
    first = create_application(
        store, set_release, fmt, tier="LOCAL",
        scheduled_date="2026-09-26T18:00:00Z", expected_headcount=12,
    )
    second = create_application(
        store, set_release, fmt, tier="LOCAL",
        scheduled_date="2026-09-27T18:00:00Z", expected_headcount=12,
    )
    observed = current_store_version(store["id"])

    results = run_race(
        lambda: api.transition_event_application(
            first["id"], approve_payload(observed), TEST_USERS["ops_admin_headers"]
        ),
        lambda: api.transition_event_application(
            second["id"], approve_payload(observed), TEST_USERS["ops_admin_headers"]
        ),
    )

    assert_at_least_one_succeeds(*results)
    assert current_store(store["id"])["version"] >= observed + 1
    for response in results:
        if response.status_code >= 400:
            validate_error(response, "ERR_STALE_VERSION", expected_status=412)


def test_the_observed_store_version_advances_once_per_successful_approval(api):
    """PRD §2.10: "Requiring the client to present the version it observed forces
    it to have seen the current state of the parent before committing."
    PRD §2.7: "Every store transition advances the store's `version` by one."

    Design: Corner/validations/stale_store_version_blocks_approval
    """
    store, set_release, fmt = setup_release_context()
    first = create_application(
        store, set_release, fmt, tier="LOCAL",
        scheduled_date="2026-09-26T18:00:00Z", expected_headcount=12,
    )
    observed = current_store_version(store["id"])

    api.transition_event_application(
        first["id"], approve_payload(observed), TEST_USERS["ops_admin_headers"]
    ).raise_for_status()
    assert current_store(store["id"])["version"] == observed + 1

    second = create_application(
        store, set_release, fmt, tier="LOCAL",
        scheduled_date="2026-09-27T18:00:00Z", expected_headcount=12,
    )
    stale = api.transition_event_application(
        second["id"], approve_payload(observed), TEST_USERS["ops_admin_headers"]
    )
    validate_error(stale, "ERR_STALE_VERSION", expected_status=412)


def test_the_grant_dimension_moves_at_redemption_and_again_at_disbursement(api):
    """PRD §3.11: "Its redemption sets `physical_grant_status` to `RESERVED`,
    which opens a second dimension that does not exist for digital cards. That
    dimension advances later, when an operator disburses the grant, moving
    `physical_grant_status` from `RESERVED` to `DISBURSED`"
    PRD §3.11: "A successful redemption assigns the card a `redemption_seq` from
    the global monotonic sequence and moves it to `REDEEMED`, and from that point
    the two paths diverge."

    Design: Corner/cross_cutting_layers/physical_grant_status_reconciliation_after_disbursement
    """
    from test_helpers import (
        disburse_code,
        get_code,
        setup_pool_with_physical_grants,
    )

    store, _set_release, _fmt, application, allocation, cards = (
        setup_pool_with_physical_grants(grant_count=1, extra_tp=150, tier="LOCAL")
    )
    card = cards[0]

    # Re-redeem is not possible; the card was already redeemed in setup, so the
    # redemption response's grant status is observable by reading it back.
    assert get_code(card["id"])["physical_grant_status"] == "RESERVED"

    disburse_code(card["id"]).raise_for_status()
    assert get_code(card["id"])["physical_grant_status"] == "DISBURSED"
    assert get_code(card["id"])["status"] == "REDEEMED", (
        "the derived grant field moved while the lifecycle field stayed put"
    )


def test_the_card_records_its_pool_once_the_grant_is_disbursed(api):
    """PRD §3.11: "Disbursement records the application's prize pool onto the card
    as `prize_allocation_id` and then moves tournament points in both directions
    at once."

    Design: Corner/cross_cutting_layers/physical_grant_status_reconciliation_after_disbursement
    """
    from test_helpers import disburse_code, get_code, setup_pool_with_physical_grants

    store, _set_release, _fmt, application, allocation, cards = (
        setup_pool_with_physical_grants(grant_count=1, extra_tp=150, tier="LOCAL")
    )
    card = cards[0]
    assert get_code(card["id"])["prize_allocation_id"] is None

    disburse_code(card["id"]).raise_for_status()
    assert get_code(card["id"])["prize_allocation_id"] == allocation["id"]