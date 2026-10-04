"""Endangered-species bulletin window semantics and the logical clock:
closed-set month overlap with wraparound, per-county scoping, lift terminality,
monotonicity, and the pinned four-step sweep (PRD §2.4, §3.6).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    apply_state_registration,
    assert_bulletin,
    assert_iso_instant_equal,
    create_bulletin,
    create_certification,
    create_manual_review_case,
    create_registered_product,
    get_review_case,
    get_state_registration,
    get_product,
    grant_state_registration,
    lift_bulletin,
    make_bulletin_payload,
    make_clock_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRANT = TEST_USERS["registrant_alice_headers"]
REVIEWER = TEST_USERS["reviewer_1_headers"]
STATE_AGENCY = TEST_USERS["state_agency_headers"]
CERT_AUTHORITY = TEST_USERS["certification_authority_headers"]


def _get_certification(certification_id):
    rows, _ = validate_paginated(api_client.list_certifications(ADMIN))
    return [c for c in rows if c["id"] == certification_id][0]


def test_bulletin_closed_month_window_sharing(api):
    """PRD §3.6: "Two bulletins of the same product and county that would both be
    `IN_EFFECT` may not share a calendar month; an overlapping publication is
    rejected with `ERR_BULLETIN_WINDOW_OVERLAP` (HTTP 409)."
    PRD §3.6: "the window is the closed set of months from start to end, wrapping
    past December"

    Design: Difficulty/resource_temporal_overlap/bulletin_closed_month_window_sharing
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    bul_a = create_bulletin(product_id, REVIEWER, county_fips="06037",
                            restriction_code="SEASONAL_WINDOW",
                            window_start_month=3, window_end_month=8,
                            consultation_reference="USFWS-BO-2026-114")
    assert_bulletin(bul_a)

    # Months 5-9 share {5,6,7,8} with the IN_EFFECT 3-8 window.
    resp = api_client.create_bulletin(
        make_bulletin_payload(product_id, "06037", "SEASONAL_WINDOW", 5, 9,
                              consultation_reference="USFWS-BO-2026-121"),
        REVIEWER)
    validate_error(resp, ApiErrorId.ERR_BULLETIN_WINDOW_OVERLAP)

    # Months 9-12 share nothing with {3,4,5,6,7,8}.
    bul_b = create_bulletin(product_id, REVIEWER, county_fips="06037",
                            restriction_code="SEASONAL_WINDOW",
                            window_start_month=9, window_end_month=12,
                            consultation_reference="USFWS-BO-2026-122")
    assert bul_b["status"] == "IN_EFFECT"

    rows, _ = validate_paginated(api_client.list_product_bulletins(
        product_id, ADMIN))
    by_id = {row["id"]: row for row in rows}
    assert by_id[bul_a["id"]]["status"] == "IN_EFFECT"


def test_bulletin_same_window_different_county_and_wrap_window_allowed(api):
    """PRD §3.6: "Two bulletins of the same product and county that would both be
    `IN_EFFECT` may not share a calendar month; an overlapping publication is
    rejected with `ERR_BULLETIN_WINDOW_OVERLAP` (HTTP 409)."
    PRD §3.6: "the window is the closed set of months from start to end, wrapping
    past December, so a start of 11 with an end of 2 means the set {11, 12, 1, 2}"

    Design: Corner/validations/bulletin_same_window_different_county_and_wrap_window_allowed
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    create_bulletin(product_id, REVIEWER, county_fips="06037",
                    restriction_code="SEASONAL_WINDOW", window_start_month=3,
                    window_end_month=8, consultation_reference="USFWS-BO-2026-114")

    # The overlap constraint is scoped per (product, county).
    bul_b = create_bulletin(product_id, REVIEWER, county_fips="48101",
                            restriction_code="SEASONAL_WINDOW",
                            window_start_month=3, window_end_month=8,
                            consultation_reference="USFWS-BO-2026-140")
    assert bul_b["status"] == "IN_EFFECT"

    # A wrapping window 11->2 covers {11,12,1,2}, disjoint from {3..8}.
    bul_c = create_bulletin(product_id, REVIEWER, county_fips="06037",
                            restriction_code="SEASONAL_WINDOW",
                            window_start_month=11, window_end_month=2,
                            consultation_reference="USFWS-BO-2026-141")
    assert bul_c["status"] == "IN_EFFECT"

    # Months 2-4 share {3,4} with the first window and {2} with the wrap window.
    resp = api_client.create_bulletin(
        make_bulletin_payload(product_id, "06037", "SEASONAL_WINDOW", 2, 4,
                              consultation_reference="USFWS-BO-2026-142"),
        REVIEWER)
    validate_error(resp, ApiErrorId.ERR_BULLETIN_WINDOW_OVERLAP)


def test_bulletin_lift_twice_returns_not_liftable(api):
    """PRD §3.6: "lifting moves `IN_EFFECT` → `LIFTED`, stamps `lifted_at`, and is
    the bulletin's only transition — lifting one that is not `IN_EFFECT` fails
    `ERR_BULLETIN_NOT_LIFTABLE` (HTTP 409)."

    Design: Corner/state_machines/bulletin_lift_twice_returns_not_liftable
    """
    ctx = create_registered_product()
    bul = create_bulletin(ctx["product"]["id"], REVIEWER, county_fips="06037",
                          restriction_code="SEASONAL_WINDOW", window_start_month=3,
                          window_end_month=8,
                          consultation_reference="USFWS-BO-2026-114")
    lifted = lift_bulletin(bul["id"], REVIEWER)
    assert lifted["status"] == "LIFTED"
    assert_iso_instant_equal(lifted["lifted_at"], "2026-09-01T00:00:00Z",
                             "lifted_at")

    resp = api_client.lift_bulletin(bul["id"], REVIEWER, payload={})
    validate_error(resp, ApiErrorId.ERR_BULLETIN_NOT_LIFTABLE)

    rows, _ = validate_paginated(api_client.list_product_bulletins(
        ctx["product"]["id"], ADMIN))
    bul = [row for row in rows if row["id"] == bul["id"]][0]
    assert bul["status"] == "LIFTED"
    assert_iso_instant_equal(bul["lifted_at"], "2026-09-01T00:00:00Z", "lifted_at")


def test_clock_set_rejects_non_monotonic_jump(api):
    """PRD §2.4: "Before any operator sets it, the logical clock reads exactly
    `2026-09-01T00:00:00Z` — a fixed server default, not the host's wall clock."
    PRD §2.4: "The clock never moves backward. A set call whose `to_iso8601` is
    strictly earlier than the current value fails with `ERR_INVALID_REQUEST`
    (HTTP 400); a value exactly equal to the current clock is an idempotent
    no-op; only a strictly later value advances time."

    Design: Corner/cross_cutting_layers/clock_set_rejects_non_monotonic_jump
    """
    # Setting the default instant exactly is an idempotent no-op.
    data = validate_success(api_client.set_clock(
        make_clock_payload("2026-09-01T00:00:00Z"), ADMIN))
    assert data["current_utc"] == "2026-09-01T00:00:00Z"

    resp = api_client.set_clock(make_clock_payload("2026-08-01T00:00:00Z"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    # The clock never moved, so a forward set from the default succeeds.
    data = validate_success(api_client.set_clock(
        make_clock_payload("2026-09-02T00:00:00Z"), ADMIN))
    assert data["current_utc"] == "2026-09-02T00:00:00Z"


def test_clock_sweep_applies_all_steps_in_one_call(api):
    """PRD §2.4: "Each advance runs a four-step batch sweep, and both the step
    order and the comparison operators are pinned:"
    PRD §2.4: "Every registration review case still `SCHEDULED` whose `opened_at`
    is at or before the new time opens — `SCHEDULED` → `OPEN` — and when the
    case's product is `REGISTERED` the product moves to `UNDER_REVIEW`"
    PRD §2.4: "Every applicator certification in `ACTIVE` whose `certified_until`
    is strictly earlier than the new time flips to `EXPIRED`."
    PRD §2.4: "Every state registration in `GRANTED` whose grace period has fully
    elapsed — the instant exactly thirty days after its `renewal_due_at` is
    strictly earlier than the new time — becomes `LAPSED`."

    Design: Corner/cross_cutting_layers/clock_sweep_applies_all_steps_in_one_call
    """
    ctx = create_registered_product()
    product_id = ctx["product"]["id"]
    case = create_manual_review_case(product_id, "2027-01-05T00:00:00Z",
                                     "2027-07-04T00:00:00Z", REVIEWER)
    cert = create_certification("TX", "2027-01-01T00:00:00Z",
                                applicator_name="W. Fields")
    sreg = apply_state_registration(product_id, "TX", REGISTRANT)
    set_clock("2026-09-15T00:00:00Z")
    grant_state_registration(sreg["id"], agency_headers=STATE_AGENCY)

    # One set fires three sweep steps at once:
    # step 1: case opened_at 2027-01-05 <= now -> OPEN, product -> UNDER_REVIEW;
    # step 3: certified_until 2027-01-01 < now -> EXPIRED;
    # step 4: renewal_due_at 2027-09-15 + 30 days = 2027-10-15 < now -> LAPSED.
    set_clock("2027-10-16T00:00:00Z")

    assert get_review_case(case["id"])["status"] == "OPEN"
    assert get_product(product_id)["status"] == "UNDER_REVIEW"
    assert _get_certification(cert["id"])["status"] == "EXPIRED"
    assert get_state_registration(sreg["id"])["status"] == "LAPSED"
