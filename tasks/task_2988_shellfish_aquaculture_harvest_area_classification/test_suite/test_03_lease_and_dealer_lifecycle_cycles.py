"""Two lifecycles that return to a state they already occupied (PRD §3.4, §3.7).

A lease resubmission re-enters `UNDER_REVIEW` but not the configuration it left,
and a dealer reinstatement returns to `LISTED` carrying a counter the cycle does
not reset. In both cases traversing the cycle is not a state reset.
"""
from test_helpers import (
    api_client,
    confirm_payload,
    create_growing_area,
    create_lease_under_review,
    design_world,
    DEALER_SUSPENSION_STRIKE_THRESHOLD,
    dw_area_payload,
    dw_lease_payload_overrides,
    DW_CLOCK,
    get_success_data,
    MAX_REVISION_ROUNDS,
    OPERATOR_USER_ID,
    reinstate_payload,
    REVIEWER_B_USER_ID,
    REVIEWER_USER_ID,
    review_payload,
    set_clock,
    submit_lease_payload,
    suspend_payload,
    TEST_USERS,
    to_millis,
    traceback_payload,
    validate_success,
)

AUTHORITY = TEST_USERS["authority_headers"]
OPERATOR = TEST_USERS["operator_headers"]
NAV_REVIEWER = TEST_USERS["reviewer_headers"]
ENV_REVIEWER = TEST_USERS["reviewer_b_headers"]


def _lease_in_revision_after_environmental_objection():
    """Submit a lease, clear the navigation leg, then record an environmental
    objection -- the branch that additionally resets the navigation leg."""
    set_clock(DW_CLOCK)
    area = create_growing_area(dw_area_payload())
    lease = create_lease_under_review(
        area["id"], OPERATOR, dw_lease_payload_overrides())
    get_success_data(api_client.navigation_review(
        lease["id"], review_payload("CLEARED"), NAV_REVIEWER))
    return get_success_data(api_client.environmental_review(
        lease["id"], review_payload("OBJECTION",
                                   review_note="footprint overlaps SAV"),
        ENV_REVIEWER))


def test_environmental_objection_erases_the_navigation_clearance_it_found():
    """The asymmetric branch: an environmental objection writes
    `environmental_clearance` OBJECTION with its own reviewer identity **and**
    resets `navigation_clearance` to PENDING with `navigation_reviewer_user_id`
    null, so the recorded navigation CLEARED is already gone before any
    resubmission, while `revision_round` is still 0.

    Design: Difficulty/non_linear_state_machine/lease_revision_cycle_returns_to_under_review_with_cleared_flags_reset
    """
    lease = _lease_in_revision_after_environmental_objection()

    assert lease["status"] == "REVISION_REQUESTED"
    assert lease["navigation_clearance"] == "PENDING"
    assert lease["navigation_reviewer_user_id"] is None
    assert lease["environmental_clearance"] == "OBJECTION"
    assert lease["environmental_reviewer_user_id"] == REVIEWER_B_USER_ID
    assert lease["revision_round"] == 0


def test_resubmission_returns_to_under_review_with_both_legs_reset():
    """A successful resubmission increments `revision_round` by 1, resets both
    clearance legs to PENDING with both reviewer identities null -- so the
    recorded environmental OBJECTION and its reviewer identity are erased by the
    re-entry -- and moves `status` back to UNDER_REVIEW.

    Design: Difficulty/non_linear_state_machine/lease_revision_cycle_returns_to_under_review_with_cleared_flags_reset
    """
    lease = _lease_in_revision_after_environmental_objection()

    resubmitted = validate_success(api_client.submit_lease(
        lease["id"],
        submit_lease_payload(submission_note="footprint moved 40 m east"),
        OPERATOR))

    assert resubmitted["status"] == "UNDER_REVIEW"
    assert resubmitted["revision_round"] == 1
    assert resubmitted["navigation_clearance"] == "PENDING"
    assert resubmitted["environmental_clearance"] == "PENDING"
    assert resubmitted["navigation_reviewer_user_id"] is None
    assert resubmitted["environmental_reviewer_user_id"] is None


def test_the_second_entry_into_under_review_is_not_the_first_entry():
    """The lease occupies UNDER_REVIEW twice, but the two occupations are
    distinguishable: `revision_round` reads 0 on the first and 1 on the second,
    and `MAX_REVISION_ROUNDS` 3 caps how often the cycle may be traversed.
    Nothing else about the application moves -- `decided_at` stays null and
    `operator_user_id` still names the drafting operator.

    Design: Difficulty/non_linear_state_machine/lease_revision_cycle_returns_to_under_review_with_cleared_flags_reset
    """
    lease = _lease_in_revision_after_environmental_objection()
    before = lease["revision_round"]

    resubmitted = validate_success(api_client.submit_lease(
        lease["id"],
        submit_lease_payload(submission_note="footprint moved 40 m east"),
        OPERATOR))

    assert before == 0
    assert resubmitted["revision_round"] == before + 1
    assert resubmitted["revision_round"] < MAX_REVISION_ROUNDS
    assert resubmitted["decided_at"] is None
    assert resubmitted["operator_user_id"] == OPERATOR_USER_ID
    assert resubmitted["navigation_reviewer_user_id"] != REVIEWER_USER_ID


# --------------------------------------------------------------------------
# The dealer listing cycle
# --------------------------------------------------------------------------
INVESTIGATION_REPORTED_AT = "2026-08-10T10:50:00Z"
CONFIRMED_AT = "2026-08-10T11:00:00Z"
SHIPPED_AT = "2026-08-10T10:45:00Z"


def _dealer_with_one_strike_then_suspended():
    """One confirmed recall gives the dealer a single strike -- one short of
    `DEALER_SUSPENSION_STRIKE_THRESHOLD` 2, so the confirmation itself does not
    suspend -- and the authority then suspends it administratively."""
    world = design_world(
        stage="shipped",
        shipment_overrides={"destination_state": "VA"},
        shipped_at=SHIPPED_AT,
    )
    investigation = get_success_data(api_client.create_illness_investigation(
        world["shipment"]["id"],
        {"reported_at": INVESTIGATION_REPORTED_AT, "illness_count": 3,
         "pathogen": "VIBRIO_PARAHAEMOLYTICUS"},
        AUTHORITY))
    get_success_data(api_client.run_traceback(
        investigation["id"], traceback_payload("NARROW"), AUTHORITY))
    world["investigation"] = get_success_data(
        api_client.confirm_illness_investigation(
            investigation["id"], confirm_payload(confirmed_at=CONFIRMED_AT),
            AUTHORITY))
    world["dealer"] = get_success_data(api_client.suspend_dealer(
        world["dealer"]["id"], suspend_payload(
            suspension_note="pending plan review"), AUTHORITY))
    return world


def test_reinstatement_clears_the_suspension_reason_but_not_the_strike():
    """The dealer returns from SUSPENDED to LISTED with `suspension_reason`
    cleared to null, yet `recall_strike_count` stays at 1 rather than 0 -- so the
    reinstated dealer stands one confirmed recall away from re-suspension at the
    inclusive threshold of 2. The supplied `icssl_listed_through` and the
    untouched `certified_through` both read 2027-06-30.

    Design: Difficulty/non_linear_state_machine/dealer_listing_cycle_suspend_then_reinstate_retains_recall_strike
    """
    world = _dealer_with_one_strike_then_suspended()
    assert world["dealer"]["listing_status"] == "SUSPENDED"
    assert world["dealer"]["suspension_reason"] == "AUTHORITY_ACTION"
    assert world["dealer"]["recall_strike_count"] == 1

    reinstated = validate_success(api_client.reinstate_dealer(
        world["dealer"]["id"],
        reinstate_payload(icssl_listed_through="2027-06-30"), AUTHORITY))

    assert reinstated["listing_status"] == "LISTED"
    assert reinstated["suspension_reason"] is None
    assert reinstated["recall_strike_count"] == 1
    assert reinstated["recall_strike_count"] != 0
    assert reinstated["recall_strike_count"] == DEALER_SUSPENSION_STRIKE_THRESHOLD - 1
    assert reinstated["certified_through"] == "2027-06-30"
    assert reinstated["icssl_listed_through"] == "2027-06-30"


def test_reinstatement_does_not_undo_the_recall_that_earned_the_strike():
    """Travelling back to LISTED leaves the recall record intact: the
    investigation stays CONFIRMED with one traced lot and one recalled shipment,
    the lot stays RECALLED, and the shipment stays RECALLED with `recall_reason`
    ILLNESS_TRACEBACK.

    Design: Difficulty/non_linear_state_machine/dealer_listing_cycle_suspend_then_reinstate_retains_recall_strike
    """
    world = _dealer_with_one_strike_then_suspended()
    validate_success(api_client.reinstate_dealer(
        world["dealer"]["id"],
        reinstate_payload(icssl_listed_through="2027-06-30"), AUTHORITY))

    investigation = get_success_data(api_client.get_illness_investigation(
        world["investigation"]["id"], AUTHORITY))
    lot = get_success_data(api_client.get_harvest_lot(
        world["lot"]["id"], AUTHORITY))
    shipment = get_success_data(api_client.get_shipment(
        world["shipment"]["id"], AUTHORITY))

    assert investigation["status"] == "CONFIRMED"
    assert investigation["confirmed_at"] == to_millis(CONFIRMED_AT)
    assert investigation["traced_lot_count"] == 1
    assert investigation["recalled_shipment_count"] == 1
    assert lot["status"] == "RECALLED"
    assert shipment["status"] == "RECALLED"
    assert shipment["recall_reason"] == "ILLNESS_TRACEBACK"
