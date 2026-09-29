"""Transfer approval re-reads the receiving club's posture at decision time.

The request is filed while the destination is healthy, and the destination then fails an
inspection. Nothing about the request itself changed, but the decision is refused until a
remediation waiver puts the receiving club back into service.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    api_client,
    create_member,
    file_transfer_request,
    inspect_club,
    make_club_manager_headers,
    read_agreement,
    read_club,
    read_franchisee,
    read_transfer_request,
    setup_two_franchise_clubs,
    sign_active_agreement,
    transfer_decision_payload,
    waive_remediation,
)


def _cross_franchise_request_into_a_club_that_then_failed() -> dict:
    """A cross-franchise transfer standing REQUESTED, whose destination has since scored 51
    and been suspended."""
    setup = setup_two_franchise_clubs()
    releasing = setup["first"]
    receiving = setup["second"]
    member = create_member(
        releasing["club"]["id"],
        full_name="Anselm Okoro",
        email="anselm.okoro@example.com",
    )
    agreement = sign_active_agreement(
        member["id"],
        releasing["club"]["id"],
        setup["plan_template"]["id"],
        multi_club_access=False,
    )
    request = file_transfer_request(
        agreement["id"],
        releasing["club"]["id"],
        receiving["club"]["id"],
        reason="Member relocated across town",
    )
    inspection = inspect_club(receiving["club"]["id"], "2026-07-15", 60, 60, 60, 60)
    return {
        "releasing": releasing,
        "receiving": receiving,
        "member": member,
        "agreement": agreement,
        "request": request,
        "inspection": inspection,
    }


def _decide(setup: dict, decision: str = "APPROVE"):
    return api_client.decide_transfer_request(
        setup["request"]["id"],
        transfer_decision_payload(decision),
        make_club_manager_headers(setup["receiving"]["club"]["id"]),
    )


def test_approval_is_refused_when_the_receiving_club_has_since_been_suspended():
    """The transfer edge itself is legal — a REQUESTED request, the receiving manager, a
    CURRENT membership — yet the destination's posture is re-checked and refuses it.

    PRD 3.6: "Approval re-checks the destination's posture at decision time, because weeks
    may have passed: the receiving club must still be `OPEN` and must not be `NON_COMPLIANT`,
    otherwise `ERR_CLUB_NOT_OPERATIONAL`, and the agreement's `dues_status` must still be
    `CURRENT` or `PAST_DUE`, otherwise `ERR_TRANSFER_BLOCKED_BY_ARREARS`."

    Design: Difficulty/cross_entity_state_dependency/transfer_approval_gated_on_receiving_club_compliance_state
    """
    setup = _cross_franchise_request_into_a_club_that_then_failed()
    assert setup["agreement"]["dues_status"] == "CURRENT"
    receiving_club = read_club(setup["receiving"]["club"]["id"])
    assert receiving_club["equipment_compliance_state"] == "NON_COMPLIANT"
    assert receiving_club["status"] == "SUSPENDED"

    validate_error(_decide(setup), ApiErrorId.ERR_CLUB_NOT_OPERATIONAL.value)


def test_the_refused_decision_leaves_the_request_unpinned_and_undecided():
    """A refused approval pins nothing: the request is still awaiting a decision with no fee
    and no decider recorded.

    PRD 3.6: "The request is created in `REQUESTED` with `transfer_fee_cents`, `effective_on`
    and `decided_by_user_id` all null, and it increments the agreement's `version` by 1 —
    which is why two transfer attempts in a row need two separate reads of the agreement."

    Design: Difficulty/cross_entity_state_dependency/transfer_approval_gated_on_receiving_club_compliance_state
    """
    setup = _cross_franchise_request_into_a_club_that_then_failed()
    _decide(setup)

    request = read_transfer_request(setup["request"]["id"])
    assert request["status"] == "REQUESTED"
    assert request["transfer_fee_cents"] is None
    assert request["effective_on"] is None
    assert request["decided_by_user_id"] is None


def test_the_same_decision_succeeds_and_pins_the_cross_franchise_fee_after_the_waiver():
    """Once the waiver returns the destination to service the identical call is approved, and
    only then is the fee — 2500 plus half of 4500 — pinned onto the request.

    PRD 3.6: "When the two clubs belong to different franchisees, the fee is a base of 2500
    cents plus half of the agreement's pinned `effective_monthly_dues_cents`, where that
    percentage component is rounded half up to whole cents before the base is added."

    Design: Difficulty/cross_entity_state_dependency/transfer_approval_gated_on_receiving_club_compliance_state
    """
    setup = _cross_franchise_request_into_a_club_that_then_failed()
    validate_error(_decide(setup), ApiErrorId.ERR_CLUB_NOT_OPERATIONAL.value)
    waive_remediation(
        setup["inspection"]["id"],
        auditor_id="auditor-2",
        reason="Strength floor replacement scheduled for next month",
    )
    restored = read_club(setup["receiving"]["club"]["id"])
    assert restored["equipment_compliance_state"] == "WATCH"
    assert restored["status"] == "OPEN"

    approved = validate_success(_decide(setup))
    assert approved["status"] == "APPROVED"
    assert approved["transfer_fee_cents"] == 4750
    assert approved["decided_by_user_id"] == setup["receiving"]["club"]["id"]


def test_approval_alone_moves_no_membership_and_charges_nothing():
    """The decision only pins terms; the member is still billed by the releasing club and the
    transfer has not been counted.

    PRD 3.6: "Approval moves the request `REQUESTED → APPROVED`, stamps `decided_by_user_id`
    with the deciding club's identifier, pins `transfer_fee_cents`, and increments the
    request's `version`."

    Design: Difficulty/cross_entity_state_dependency/transfer_approval_gated_on_receiving_club_compliance_state
    """
    setup = _cross_franchise_request_into_a_club_that_then_failed()
    waive_remediation(setup["inspection"]["id"], auditor_id="auditor-2")
    validate_success(_decide(setup))

    agreement = read_agreement(setup["agreement"]["id"])
    assert agreement["home_club_id"] == setup["releasing"]["club"]["id"]
    assert agreement["effective_monthly_dues_cents"] == 4500
    assert agreement["transfer_count"] == 0
    assert agreement["outstanding_balance_cents"] == 0


def test_the_failing_inspection_docks_the_receiving_franchisee_without_demoting_it():
    """The destination's own operator carries the consequence of its inspection — one failure,
    20 points — which is not enough to put it on probation.

    PRD 3.9: "Scoring writes `scored_by_user_id` from the `X-User-ID` header and then sets off
    the cascade described in §2.10, in order."

    Design: Difficulty/cross_entity_state_dependency/transfer_approval_gated_on_receiving_club_compliance_state
    """
    setup = _cross_franchise_request_into_a_club_that_then_failed()

    receiving_franchisee = read_franchisee(setup["receiving"]["franchisee"]["id"])
    assert receiving_franchisee["inspection_fail_streak"] == 1
    assert receiving_franchisee["compliance_score"] == 80
    assert receiving_franchisee["status"] == "ACTIVE"
    releasing_franchisee = read_franchisee(setup["releasing"]["franchisee"]["id"])
    assert releasing_franchisee["compliance_score"] == 100
    assert releasing_franchisee["inspection_fail_streak"] == 0
