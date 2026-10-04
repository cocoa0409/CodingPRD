"""Reviews, receipts, the pass pool, and the aggregate calculations."""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers.fixtures import (
    make_anonymous_headers,
    declare_host,
    declare_sites,
    approve_host,
    setup_basic_scenario,
    setup_confirmed_stay,
    setup_checked_in_stay,
    file_stay,
    confirm_stay,
    declare_patronization_record,
    verify_patronization_record,
    read_host,
    read_member,
    read_stay,
    set_clock,
    host_version,
    make_host_operator_headers,
    make_member_headers,
    make_platform_admin_headers,
)


def test_a_freshly_created_host_and_member_report_a_zero_rating(api):
    """PRD §2.6: "Both properties are zero when their set is empty; a host whose only
    review was withdrawn therefore reports 0.00 rather than a null or a division
    fault."
    PRD §2.6: "`host_rating_average` averages the `rating` of the host's host-author
    reviews that are in `PUBLISHED` status"

    Design: Corner/calculations/empty_review_aggregate_is_zero_point_zero_zero
    """
    host = declare_host()
    member = validate_success(
        api.register_member(
            {"email": "fresh@example.com", "full_name": "Fresh Member",
             "plan_tier": "PLUS", "home_state_code": "TX"},
            make_anonymous_headers(),
        ),
        201,
    )
    assert host["host_rating_average"] == 0.00
    assert member["member_rating_average"] == 0.00
    assert read_host(host["id"])["host_rating_average"] == 0.00
    assert read_member(member["id"])["member_rating_average"] == 0.00

    reviews = validate_success(
        api.list_reviews(make_host_operator_headers(host["id"]),
                         {"host_id": host["id"], "limit": 10, "offset": 0})
    )
    assert reviews == [], "the denominator really is empty"


def test_a_verified_record_rounds_before_the_rollup_sums(api):
    """PRD §2.8: "Two verified receipts of 10050 and 33333 cents therefore contribute
    503 and 1500 cents respectively for a total of 2003"
    PRD §2.8: "the percentage component is rounded half up to zero decimal places"

    Design: Corner/calculations/per_record_rounding_beats_sum_then_round
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(
        site_count=1, arrival_date="2026-06-20", nights=2,
        self_contained_required=True, category="WINERY", state_code="CA",
    )
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]

    for cents in (10050, 33333):
        record = declare_patronization_record(
            host_id, member_id, parts["stay"]["id"], receipt_cents=cents,
            purchase_kind="TASTING",
        )
        verify_patronization_record(host_id, record["id"], record["verification_code"])

    assert read_host(host_id)["patronization_credit_cents"] == 2003


def test_a_verified_record_below_half_a_cent_contributes_nothing(api):
    """PRD §2.8: "The support-the-host credit accrues at a flat five percent of a
    verified receipt's value, converted to a whole number of cents by rounding half
    up"
    PRD §2.12: "the record's `host_credit_cents` stays at zero until it is verified"

    Design: Corner/calculations/per_record_rounding_beats_sum_then_round
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(
        site_count=1, arrival_date="2026-06-20", nights=2,
        self_contained_required=True, category="WINERY", state_code="CA",
    )
    host_id = parts["host"]["id"]
    record = declare_patronization_record(
        host_id, parts["member"]["id"], parts["stay"]["id"],
        receipt_cents=1, purchase_kind="TASTING",
    )
    verified = verify_patronization_record(
        host_id, record["id"], record["verification_code"]
    )
    assert verified["verification_status"] == "VERIFIED"
    assert verified["host_credit_cents"] == 0, (
        "round_half_up(1 * 0.05) is zero, not one"
    )
    assert read_host(host_id)["patronization_credit_cents"] == 0


def test_the_pass_pool_freezes_while_another_stay_is_in_flight(api):
    """PRD §3.3: "On a stay reaching `CHECKED_OUT`, and on any cascade that recomputes
    member state, the platform first asks whether the member has any stay in
    `REQUESTED`, `CONFIRMED` or `CHECKED_IN` status. If they do, the pool is frozen at
    its current value"
    PRD §3.3: "If they do not, the pool is recalculated from scratch as the plan
    allotment minus the member's guest usage so far this calendar year"

    Design: Corner/calculations/guest_pass_allotment_frozen_while_a_stay_is_in_flight
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(
        site_count=2, arrival_date="2026-06-05", nights=1, party_size=3,
        plan_tier="PREMIER",
    )
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    host_headers = make_host_operator_headers(host_id)

    # Arrival is recorded once the clock reaches the stay's occupancy_start.
    set_clock("2026-06-05T14:00:00Z")
    validate_success(api.check_in_stay(parts["stay"]["id"], host_headers))
    set_clock("2026-06-01T00:00:00Z")
    validate_success(
        api.member_subscription_action(
            member_id, {"action": "SET_GUEST_PASSES", "guest_passes_remaining": 1},
            make_platform_admin_headers(),
        )
    )
    # A second, in-flight stay for the same member on the second site.
    second = file_stay(host_id, member_id, parts["vehicle"]["id"],
                       arrival_date="2026-07-01", nights=2)
    assert second["request_status"] == "REQUESTED"

    set_clock("2026-06-06T11:00:00Z")
    out = validate_success(api.check_out_stay(parts["stay"]["id"], host_headers))
    assert out["request_status"] == "CHECKED_OUT"

    member = read_member(member_id)
    assert member["guest_passes_remaining"] == 1, (
        "the pool is frozen because the second stay is still REQUESTED"
    )
    assert member["total_stays_completed"] == 1, (
        "the checkout did register the completed stay"
    )


def test_an_incident_may_be_filed_and_recomputed_against_a_member(api):
    """PRD §2.7: "`standing_score` is a penalty ledger: it starts from a baseline of
    100 points and each non-withdrawn incident subtracts a penalty determined by its
    severity — 5 points for a `MINOR` incident"
    PRD §2.7: "`strike_count` measures something narrower: it counts the member's
    non-withdrawn incidents whose severity is `MAJOR` or `SEVERE`, and it ignores
    `MINOR` incidents completely."

    Design: Corner/cross_cutting_layers/strike_threshold_removal_is_cumulative_not_instantaneous
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=1)
    member_id = parts["member"]["id"]

    incident = validate_success(
        api.create_incident(
            {"member_id": member_id, "host_id": parts["host"]["id"],
             "severity": "MINOR", "narrative": "left the tap running",
             "origin": "MEMBER_REPORT"},
            make_member_headers(member_id),
        ),
        201,
    )
    assert incident["incident_status"] == "OPEN"
    assert incident["waived_days_remaining"] == 0

    member = read_member(member_id)
    assert member["standing_score"] == 95, "a MINOR incident costs 5 points"
    assert member["strike_count"] == 0, (
        "strike_count ignores MINOR incidents completely"
    )


def test_the_removal_edge_is_cumulative_at_the_third_strike(api):
    """PRD §2.7: "`strike_count` measures something narrower: it counts the member's
    non-withdrawn incidents whose severity is `MAJOR` or `SEVERE`, and it ignores
    `MINOR` incidents completely."
    PRD §2.7: "as soon as a recomputation of the conduct ledger leaves `strike_count`
    at 3 or above, the member's `removal_status` flips to `REMOVED` and their
    subscription is set to `CANCELLED` in the same pass."

    Design: Corner/cross_cutting_layers/strike_threshold_removal_is_cumulative_not_instantaneous
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=1)
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]

    validate_success(
        api.conduct_injection(
            member_id, {"severity": "MAJOR", "resolve_as": "UPHOLD",
                        "narrative": "generator curfew"},
            make_platform_admin_headers(),
        )
    )
    validate_success(
        api.conduct_injection(
            member_id, {"severity": "MAJOR", "resolve_as": "UPHOLD",
                        "narrative": "grey water"},
            make_platform_admin_headers(),
        )
    )
    two = read_member(member_id)
    assert two["strike_count"] == 2
    assert two["removal_status"] == "NONE"

    validate_success(
        api.conduct_injection(
            member_id, {"severity": "MAJOR", "resolve_as": "UPHOLD",
                        "narrative": "left the site untidy"},
            make_platform_admin_headers(),
        )
    )
    three = read_member(member_id)
    assert three["strike_count"] == 3
    assert three["removal_status"] == "REMOVED"
    assert three["standing_score"] == 55, "three MAJOR penalties of 15 from a base of 100"

    resp = api.create_stay_request(
        {"host_id": host_id, "member_id": member_id,
         "vehicle_id": parts["vehicle"]["id"], "arrival_date": "2026-07-01",
         "nights": 2, "party_size": 1, "electric_request_code": "NONE",
         "request_depth": 0, "same_day_hold": False},
        make_member_headers(member_id),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ELIGIBLE, 403)


def test_a_verification_rejects_a_code_that_does_not_match(api):
    """PRD §2.12: "Verification requires the host to supply the `verification_code`,
    and a code that does not match the minted one is rejected with
    `ERR_PATRONIZATION_CODE_INVALID` (HTTP 422)."
    PRD §2.12: "A host may also reject a pending receipt outright, leaving its
    `host_credit_cents` at zero permanently."

    Design: Corner/endpoints/patronization_verification_code_and_rejection_paths
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(
        site_count=1, arrival_date="2026-06-20", nights=2,
        self_contained_required=True, category="WINERY", state_code="CA",
    )
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    host_headers = make_host_operator_headers(host_id)

    record = declare_patronization_record(
        host_id, member_id, parts["stay"]["id"], receipt_cents=6000,
        purchase_kind="MEAL",
    )
    assert record["verification_status"] == "PENDING"
    assert record["host_credit_cents"] == 0

    bad = api.verify_patronization_record(
        record["id"], {"action": "VERIFY", "verification_code": "WRONG-CODE"},
        host_headers,
    )
    validate_error(bad, ApiErrorId.ERR_PATRONIZATION_CODE_INVALID, 422)
    assert api.get_patronization_record(record["id"], host_headers).json()["data"][
        "verification_status"
    ] == "PENDING"

    ok = verify_patronization_record(host_id, record["id"], record["verification_code"])
    assert ok["verification_status"] == "VERIFIED"
    assert ok["host_credit_cents"] == 300, "5% of 6000"


def test_a_rejected_receipt_never_moves_the_host_rollup(api):
    """PRD §2.12: "A host may also reject a pending receipt outright, leaving its
    `host_credit_cents` at zero permanently."
    PRD §2.8: "Records still in `PENDING` status or moved to `REJECTED` contribute
    nothing and are excluded from the recomputation entirely."

    Design: Corner/endpoints/patronization_verification_code_and_rejection_paths
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(
        site_count=1, arrival_date="2026-06-20", nights=2,
        self_contained_required=True, category="WINERY", state_code="CA",
    )
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    host_headers = make_host_operator_headers(host_id)

    good = declare_patronization_record(
        host_id, member_id, parts["stay"]["id"], receipt_cents=6000,
        purchase_kind="MEAL",
    )
    verify_patronization_record(host_id, good["id"], good["verification_code"])

    rejected_record = declare_patronization_record(
        host_id, member_id, parts["stay"]["id"], receipt_cents=8000,
        purchase_kind="TICKET",
    )
    rejected = validate_success(
        api.verify_patronization_record(
            rejected_record["id"], {"action": "REJECT"}, host_headers
        )
    )
    assert rejected["verification_status"] == "REJECTED"
    assert rejected["host_credit_cents"] == 0
    assert read_host(host_id)["patronization_credit_cents"] == 300, (
        "only the verified record moved the rollup"
    )