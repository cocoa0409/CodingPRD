"""Difficulty queue: cross-entity state dependencies — one entity's gate
depends on another entity's live state."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    conclude_mediation_payload,
    conciliation_for_charge,
    fail_conciliation,
    issue_rts_as_charging_party,
    make_charging_party_headers,
    make_mediator_headers,
    read_charge,
    review_determination,
    set_clock,
    setup_in_mediation,
    setup_pending_review,
    validate_error,
    validate_ok,
)
from test_helpers import api_client

_DIRECTOR = TEST_USERS["director_headers"]


def test_orphaned_mediation_cannot_settle(api):
    """PRD section 3.4: "Concluding an active mediation is the mediator's call, made with an `outcome` of `SETTLED` or `IMPASSE`, and is gated on the charge still being `IN_MEDIATION` — a mediation orphaned by a right-to-sue issuance (§3.8) can no longer settle, and its conclusion is rejected with `ERR_INVALID_STATE`."
    PRD section 3.8: "From `IN_MEDIATION`, the mediation case is deliberately not touched — an `ACTIVE` or `OFFERED` mediation may be orphaned, and any later attempt to conclude it fails the charge-state gate of §3.4 — while the investigation, which may be sitting in `SUSPENDED_MEDIATION`, is closed with its requests waived."

    Design: Difficulty/cross_entity_state_dependency/orphaned_mediation_cannot_settle
    """
    base = setup_in_mediation(basis_codes=["RACE"], incident_date="2026-06-01")
    charge = base["charge"]
    mediation = base["mediation_case"]

    # 180 days after the 2026-09-01 receipt: the charging-party gate opens and
    # issuance strands the ACTIVE mediation (the cascade does not touch it).
    set_clock("2027-02-28T00:00:00Z")
    issue_rts_as_charging_party(charge)
    assert read_charge(charge["id"])["case_status"] == "RTS_ISSUED"

    # The mediation row's own state is still ACTIVE and would allow conclude;
    # the cross-entity gate on the charge forbids it.
    orphaned = api_client.conclude_mediation(
        mediation["id"],
        conclude_mediation_payload(outcome="SETTLED",
                                   settlement_amount_cents=900_000),
        make_mediator_headers("med-050"),
    )
    validate_error(orphaned, ApiErrorId.ERR_INVALID_STATE)

    still_active = validate_ok(
        api_client.get_mediation_case(mediation["id"], _DIRECTOR)
    )
    assert still_active["status"] == "ACTIVE"

    charge_after = read_charge(charge["id"])
    assert charge_after["case_status"] == "RTS_ISSUED"
    assert charge_after["settled_amount_cents"] == 0  # no partial settlement leaked


def test_rts_blocked_by_active_conciliation(api):
    """PRD section 3.8: "A request made while the charge sits in `CONCILIATION` is rejected with `ERR_CONCILIATION_ACTIVE` — a live conciliation blocks issuance — and a request against a terminal charge is rejected with `ERR_CHARGE_ALREADY_CLOSED`, which outranks the prematurity check."
    PRD section 3.7: "That referral is not the end of the road: `LITIGATION_REFERRED` is a non-terminal state, and a right-to-sue notice may still be requested from it."

    Design: Difficulty/cross_entity_state_dependency/rts_blocked_by_active_conciliation
    """
    base = setup_pending_review(
        outcome="CAUSE",
        cause_components={
            "rationale": "documents",
            "back_pay_cents": 100_000, "front_pay_cents": 0,
            "compensatory_damages_cents": 0, "punitive_damages_cents": 0,
            "harm_start_date": "2026-06-01",
        },
        basis_codes=["RACE"], incident_date="2026-06-01",
        investigator_user_id="inv-009",
    )
    charge = base["charge"]
    party = make_charging_party_headers(charge["complainant_id"])

    # Approve at 2027-03-05: 185 days elapsed, so the 180-day gate passes and
    # only the live-conciliation gate can block the request.
    set_clock("2027-03-05T00:00:00Z")
    review_determination(base["determination"]["id"], "APPROVE",
                         director_user_id="dir-005")
    conciliation = conciliation_for_charge(charge["id"])
    assert conciliation["status"] == "INITIATED"
    assert read_charge(charge["id"])["case_status"] == "CONCILIATION"

    blocked = api_client.issue_right_to_sue(charge["id"], party)
    validate_error(blocked, ApiErrorId.ERR_CONCILIATION_ACTIVE)

    fail_conciliation(conciliation, reason="respondent refused to engage",
                      director_user_id="dir-005")
    assert read_charge(charge["id"])["case_status"] == "LITIGATION_REFERRED"

    # The identical request now succeeds from the non-terminal referral state.
    notice = issue_rts_as_charging_party(charge)
    assert notice["issuance_basis"] == "ELAPSED_180_DAYS"
    assert read_charge(charge["id"])["case_status"] == "RTS_ISSUED"
