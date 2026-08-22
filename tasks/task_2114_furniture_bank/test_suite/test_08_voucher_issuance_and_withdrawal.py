"""Voucher issuance guards, withdrawal and the safety-before-expiry precedence."""

from test_helpers import (
    ADMIN,
    WAREHOUSE,
    ApiErrorId,
    allocate,
    cancel_voucher,
    create_agency,
    create_approved_referral,
    create_client,
    create_referral,
    create_truck,
    donation_item_payload,
    issue_voucher,
    list_voucher_lines,
    make_case_manager_headers,
    record_outcome,
    review_referral,
    set_clock,
    setup_agency_and_household,
    setup_dispatched_run,
    submit_referral,
    supply_clean_stock,
    validate_error,
    validate_paginated,
    validate_success,
    voucher_line_payload,
    voucher_payload,
)


def _confirmed_bed_bug_household_with_a_second_expired_referral():
    """Referral A is delivered out and refused with a live pest at the door, so
    the household turns CONFIRMED; referral B has meanwhile run past its expiry."""
    set_clock("2026-08-04T09:00:00Z")
    base = setup_agency_and_household(
        agency_county="CENTRAL", quota=5, household_size=4,
        client_county="CENTRAL", agency_name="Bellwood Family Support",
    )
    agency_id = base["agency"]["id"]
    client_id = base["client"]["id"]

    referral_a = create_approved_referral(agency_id, client_id,
                                          requested_categories=["BED"])
    voucher_a = issue_voucher(agency_id, referral_a["id"],
                              [voucher_line_payload("BED", 1, "B")])
    referral_b = create_approved_referral(agency_id, client_id,
                                          requested_categories=["DRESSER"])
    voucher_b = issue_voucher(agency_id, referral_b["id"],
                              [voucher_line_payload("DRESSER", 1, "B")])

    truck = create_truck(label="BOX-7", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)
    supply_clean_stock(
        truck["id"], [donation_item_payload("BED", "B", False, 30.0)],
        donor_name="Yusuf Demir", donor_phone="555-0199",
    )
    allocate(voucher_a["id"], voucher_a["version"])

    booked = setup_dispatched_run(truck["id"], voucher_a["id"], county="CENTRAL",
                                  volunteer_name="Nia Prescott")
    outcome = record_outcome(booked["stop"]["id"], "REFUSED",
                             pest_observed_at_residence=True)

    set_clock("2026-09-25T09:00:00Z")
    return {
        "agency": base["agency"], "client": base["client"],
        "referral_a": referral_a, "referral_b": referral_b,
        "voucher_a": voucher_a, "voucher_b": voucher_b,
        "truck": truck, "outcome": outcome, "run": booked["run"],
    }


# ─── Corner: issuance guards ───────────────────────────────────────────

def test_voucher_cannot_be_issued_against_a_draft_referral(api):
    """PRD §3.3: "Issuance requires the referral to be in `APPROVED`, otherwise
    `ERR_REFERRAL_NOT_APPROVED`; requires that no voucher already exists for
    that referral, otherwise `ERR_VOUCHER_ALREADY_EXISTS`; requires the referral
    not to have expired, otherwise `ERR_REFERRAL_EXPIRED`; and requires the
    household's `bed_bug_status` not to be `CONFIRMED`, otherwise
    `ERR_CLIENT_BED_BUG_BLOCK`."

    Design: Corner/validations/corner_voucher_issue_against_draft_referral_rejected
    """
    agency = create_agency(name="Larkspur Care Alliance", county="CENTRAL",
                           quarterly_voucher_quota=4)
    household = create_client(agency["id"], household_size=4, county="CENTRAL")
    referral = create_referral(agency["id"], household["id"],
                               requested_categories=["BED"])

    response = api.create_voucher(
        voucher_payload(referral["id"], [voucher_line_payload("BED", 1, "B")]),
        make_case_manager_headers(agency["id"]),
    )
    validate_error(response, ApiErrorId.ERR_REFERRAL_NOT_APPROVED.value, 409)

    referral_now = validate_success(api.get_referral(referral["id"], ADMIN))
    assert referral_now["status"] == "DRAFT"
    rows, meta = validate_paginated(
        api.list_vouchers(ADMIN, {"referral_id": referral["id"]})
    )
    assert rows == [] and meta["total_count"] == 0


def test_second_voucher_for_the_same_referral_is_refused(api):
    """PRD §3.3: "Issuance requires the referral to be in `APPROVED`, otherwise
    `ERR_REFERRAL_NOT_APPROVED`; requires that no voucher already exists for
    that referral, otherwise `ERR_VOUCHER_ALREADY_EXISTS`; requires the referral
    not to have expired, otherwise `ERR_REFERRAL_EXPIRED`; and requires the
    household's `bed_bug_status` not to be `CONFIRMED`, otherwise
    `ERR_CLIENT_BED_BUG_BLOCK`."

    Design: Corner/validations/corner_second_voucher_for_same_referral_rejected
    """
    agency = create_agency(name="Kelvin Row Charity", county="CENTRAL",
                           quarterly_voucher_quota=4)
    household = create_client(agency["id"], household_size=4, county="CENTRAL")
    referral = create_approved_referral(agency["id"], household["id"],
                                        requested_categories=["BED"])
    voucher = issue_voucher(agency["id"], referral["id"],
                            [voucher_line_payload("BED", 1, "B")])

    response = api.create_voucher(
        voucher_payload(referral["id"], [voucher_line_payload("SOFA", 1, "C")]),
        make_case_manager_headers(agency["id"]),
    )
    validate_error(response, ApiErrorId.ERR_VOUCHER_ALREADY_EXISTS.value, 409)

    rows, meta = validate_paginated(
        api.list_vouchers(ADMIN, {"referral_id": referral["id"]})
    )
    assert len(rows) == 1 and rows[0]["id"] == voucher["id"]
    assert meta["total_count"] == 1

    lines = list_voucher_lines(voucher["id"])
    assert len(lines) == 1 and lines[0]["category"] == "BED", (
        "the refused issuance adds no line"
    )


def test_expired_referral_refuses_a_voucher_before_any_cycle_has_run(api):
    """PRD §3.3: "Issuance requires the referral to be in `APPROVED`, otherwise
    `ERR_REFERRAL_NOT_APPROVED`; requires that no voucher already exists for
    that referral, otherwise `ERR_VOUCHER_ALREADY_EXISTS`; requires the referral
    not to have expired, otherwise `ERR_REFERRAL_EXPIRED`; and requires the
    household's `bed_bug_status` not to be `CONFIRMED`, otherwise
    `ERR_CLIENT_BED_BUG_BLOCK`."
    PRD §2.9: "17. The referral has not expired, meaning now is at or before
    `expires_at` — otherwise `ERR_REFERRAL_EXPIRED` (409). This guards three
    operations: voucher issuance, the allocation round, and stop booking."

    Design: Corner/validations/corner_expired_referral_blocks_voucher_issue
    """
    set_clock("2026-08-04T09:00:00Z")
    agency = create_agency(name="Hazelgrove Partners", county="CENTRAL",
                           quarterly_voucher_quota=4)
    household = create_client(agency["id"], household_size=4, county="CENTRAL")
    referral = create_referral(agency["id"], household["id"],
                               requested_categories=["BED"])
    submit_referral(referral["id"], agency["id"])
    approved = review_referral(referral["id"], "APPROVE")
    assert approved["expires_at"] == "2026-09-18T09:00:00.000Z"

    set_clock("2026-09-19T09:00:00Z")
    response = api.create_voucher(
        voucher_payload(referral["id"], [voucher_line_payload("BED", 1, "B")]),
        make_case_manager_headers(agency["id"]),
    )
    validate_error(response, ApiErrorId.ERR_REFERRAL_EXPIRED.value, 409)

    referral_now = validate_success(api.get_referral(referral["id"], ADMIN))
    assert referral_now["status"] == "APPROVED", (
        "no cycle has run, so the status has not yet flipped"
    )
    rows, meta = validate_paginated(
        api.list_vouchers(ADMIN, {"referral_id": referral["id"]})
    )
    assert rows == [] and meta["total_count"] == 0


def test_cancelling_an_already_cancelled_voucher_is_refused(api):
    """PRD §3.3: "Cancelling from any other fulfilment state is rejected with
    `ERR_VOUCHER_INVALID_STATE`."
    PRD §3.3: "From `ISSUED → CANCELLED` no stock is held, so the effect is
    limited to moving every `VoucherLine` to `CANCELLED`, moving every `WAITING`
    waitlist entry belonging to those lines to `CANCELLED`, and bumping the
    voucher's `version`."

    Design: Corner/state_machines/corner_second_voucher_cancel_rejected_as_invalid_state
    """
    agency = create_agency(name="Lantern Hill Aid", county="CENTRAL",
                           quarterly_voucher_quota=4)
    household = create_client(agency["id"], household_size=3, county="CENTRAL")
    referral = create_approved_referral(agency["id"], household["id"],
                                        requested_categories=["BED"])
    voucher = issue_voucher(agency["id"], referral["id"],
                            [voucher_line_payload("BED", 1, "B")])

    cancelled = cancel_voucher(voucher["id"], agency["id"],
                               reason="Household withdrew the request")
    assert cancelled["status"] == "CANCELLED"

    response = api.cancel_voucher(
        voucher["id"], {"reason": "Duplicate cancel"},
        make_case_manager_headers(agency["id"]),
    )
    validate_error(response, ApiErrorId.ERR_VOUCHER_INVALID_STATE.value, 409)

    voucher_now = validate_success(api.get_voucher(voucher["id"], ADMIN))
    assert voucher_now["status"] == "CANCELLED"
    assert voucher_now["version"] == cancelled["version"], (
        "a refused cancel bumps no version"
    )


# ─── Difficulty: safety gate ahead of the temporal gate ────────────────

def test_bed_bug_block_outranks_referral_expiry_on_the_allocation_round(api):
    """PRD §2.9: "When a request would fail several checks at once, exactly one
    identifier comes back, and which one is fixed. Checks are evaluated top to
    bottom in the order below and the first failure wins."
    PRD §2.9: "13. The household's `bed_bug_status` is not `CONFIRMED` —
    otherwise `ERR_CLIENT_BED_BUG_BLOCK` (422). This guards five operations:
    referral submission, referral approval (the approve decision only), voucher
    issuance, the allocation round, and stop booking."
    PRD §2.9: "17. The referral has not expired, meaning now is at or before
    `expires_at` — otherwise `ERR_REFERRAL_EXPIRED` (409). This guards three
    operations: voucher issuance, the allocation round, and stop booking."

    Design: Difficulty/priority_pair_validation_conflict/safety_bed_bug_check_beats_temporal_referral_expiry_on_allocate
    """
    scenario = _confirmed_bed_bug_household_with_a_second_expired_referral()

    referral_b_now = validate_success(api.get_referral(scenario["referral_b"]["id"], ADMIN))
    assert referral_b_now["expires_at"] == "2026-09-18T09:00:00.000Z", (
        "the clock is now past referral B's expiry, so both gates would fail"
    )

    response = api.allocate_voucher(
        scenario["voucher_b"]["id"],
        {"expected_voucher_version": scenario["voucher_b"]["version"]},
        WAREHOUSE,
    )
    validate_error(response, ApiErrorId.ERR_CLIENT_BED_BUG_BLOCK.value, 422)

    voucher_b_now = validate_success(api.get_voucher(scenario["voucher_b"]["id"], ADMIN))
    assert voucher_b_now["status"] == "ISSUED", "the refused round changes nothing"
    assert voucher_b_now["version"] == 1, "the refused round bumps no version"


def test_pest_at_the_residence_confirms_the_household_without_a_strike(api):
    """PRD §3.8: "**Pest at the residence.** Independently of the outcome
    chosen, if `pest_observed_at_residence` is true on a `DELIVERED` or a
    `REFUSED` stop, the residence itself is quarantined: the household's
    `bed_bug_status` becomes `CONFIRMED`, its `bed_bug_confirmed_at` is stamped
    with the current instant, its `status` becomes `ON_HOLD`, every `WAITING`
    waitlist entry of that household moves to `CANCELLED`, and the truck that
    made the call has its `bed_bug_lockout_until` set to the current instant
    plus 72 hours."
    PRD §3.8: "**A refusal at the door** moves the stop `SCHEDULED → REFUSED`
    and behaves like a no-show in every respect but two: the chargeback is
    computed at the lower refusal rate, and the household's `no_show_strikes` is
    **not** incremented, because a refusal is not an absence."

    Design: Difficulty/priority_pair_validation_conflict/safety_bed_bug_check_beats_temporal_referral_expiry_on_allocate
    """
    scenario = _confirmed_bed_bug_household_with_a_second_expired_referral()

    assert scenario["outcome"]["chargeback_cents"] == 625, (
        "BED 2500 cents times one unit at the 0.25 refusal rate is 625"
    )

    household = validate_success(api.get_client(scenario["client"]["id"], ADMIN))
    assert household["bed_bug_status"] == "CONFIRMED"
    assert household["bed_bug_confirmed_at"] == "2026-08-04T09:00:00.000Z"
    assert household["status"] == "ON_HOLD"
    assert household["no_show_strikes"] == 0, "a refusal is not an absence"

    voucher_a_now = validate_success(api.get_voucher(scenario["voucher_a"]["id"], ADMIN))
    assert voucher_a_now["status"] == "ALLOCATED", (
        "the refused delivery hands the voucher back fully filled"
    )
