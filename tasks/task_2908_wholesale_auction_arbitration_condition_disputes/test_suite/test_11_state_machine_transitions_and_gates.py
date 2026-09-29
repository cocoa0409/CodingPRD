"""Declared transitions and the gates that guard them: the case's initial state,
its two evidence gates, the terminal-state refusals, and the sweep's phases."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_instant_equals,
    assert_ledger_batch_balanced,
    assert_ledger_rows,
    assert_sweep_report,
    assert_unpaginated_meta,
    validate_unpaginated,
)
from test_helpers.constants import (
    ARB_INTAKE_USER_ID,
    CLOCK_DEFAULT,
    FRAME_DAMAGE_POLICY,
    MECHANICAL_POLICY,
    TITLE_BRANDED_POLICY,
)
from test_helpers.factories import (
    build_arbitrator_review_world,
    build_case_world,
    build_negotiation_world,
    build_sale_world,
    build_under_review_world,
    create_buyer,
    create_case,
    create_evidence,
    create_inspection,
    create_sale,
    create_seller,
    decide_case,
    decision_payload,
    seller_response,
    set_clock,
    settle_sale,
    withdraw_case,
)
from test_helpers.test_users import (
    admin_headers,
    buyer_rep_headers,
    deciding_arbitrator_headers,
    inspector_headers,
    intake_arbitrator_headers,
)

SELLER_TIMEOUT_CLOCK = "2026-08-02T00:00:01.000Z"
ROUND_DEADLINE = "2026-08-03T00:00:00.000Z"
PAST_ROUND_DEADLINE = "2026-08-03T00:00:01.000Z"


def test_a_new_claim_lands_in_submitted_with_no_review_side_effects_yet(api):
    """Filing is the only thing that has happened, so the review fields, the
    negotiation counters and the round list are all still at their opening values.

    PRD: "The negotiation and adjudication fields start neutral:
    `current_round_index` 0, `seller_conceded` false, `seller_response_timed_out`
    false, `fault_party` `NONE`, `review_opened_at_utc` null,
    `intake_arbitrator_user_id` null, `latest_verified_estimate_cents` 0 and
    `verified_true_mileage` null."

    Design: Corner/state_machines/a_new_case_starts_in_the_submitted_initial_state
    """
    world = build_sale_world(api, [MECHANICAL_POLICY])

    case = create_case(
        api,
        world["sale"]["id"],
        world["buyer"]["id"],
        defect_class="MECHANICAL",
        claim_amount_cents=60000,
        odometer_at_claim=84100,
        complaint_text="Transmission slips under load",
    )

    assert case["status"] == "SUBMITTED"
    assert case["review_opened_at_utc"] is None
    assert case["intake_arbitrator_user_id"] is None
    assert case["current_round_index"] == 0
    assert case["seller_response_timed_out"] is False
    assert case["seller_conceded"] is False
    assert case["fault_party"] == "NONE"
    assert case["latest_verified_estimate_cents"] == 0
    assert case["verified_true_mileage"] is None
    assert_instant_equals(case["claimed_at_utc"], CLOCK_DEFAULT, "claimed_at_utc")
    assert case["version"] == 1

    rounds, meta = validate_unpaginated(
        api.list_negotiation_rounds(case["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 0)
    assert rounds == []


def test_opening_review_stamps_the_intake_officer_and_the_clock(api):
    """The evidence post already took the case to version 2, so the opening lands
    it at 3 while recording who opened it and when.

    PRD: "A successful opening stamps `review_opened_at_utc` with the current
    logical clock — the moment from which the consignor's `seller_response_hours`
    starts running — records the acting officer's `X-User-ID` as
    `intake_arbitrator_user_id`, and increments the case's `version` by 1."

    Design: Corner/state_machines/open_review_moves_submitted_to_under_review_and_stamps_the_intake_arbitrator
    """
    world = build_case_world(api, [MECHANICAL_POLICY])
    create_evidence(
        api,
        world["case"]["id"],
        world["buyer"]["id"],
        evidence_type="INSPECTION_REPORT",
        repair_estimate_cents=285000,
    )

    opened = validate_success(
        api.open_review(world["case"]["id"], {}, intake_arbitrator_headers()), 200
    )

    assert opened["status"] == "UNDER_REVIEW"
    assert_instant_equals(
        opened["review_opened_at_utc"], CLOCK_DEFAULT, "review_opened_at_utc"
    )
    assert opened["intake_arbitrator_user_id"] == ARB_INTAKE_USER_ID
    assert opened["version"] == 3

    sale = validate_success(api.get_sale(world["sale"]["id"], admin_headers()), 200)
    assert sale["arbitration_status"] == "ACTIVE"
    assert sale["open_case_count"] == 1


def test_a_second_open_review_is_refused_and_the_first_officer_stands(api):
    """Replaying the opening from a different officer is not an overwrite: the
    stored intake identity and the version are exactly as the first call left them.

    PRD: "Opening intake review is an `Arbitrator` action and the case's first
    state transition: `SUBMITTED → UNDER_REVIEW`. A case in any other status is
    refused with `ERR_INVALID_CASE_STATE`."

    Design: Corner/state_machines/a_second_open_review_on_the_same_case_is_rejected
    """
    world = build_under_review_world(api, [MECHANICAL_POLICY])

    response = api.open_review(
        world["case"]["id"], {}, deciding_arbitrator_headers()
    )

    validate_error(response, ApiErrorId.ERR_INVALID_CASE_STATE.value)
    assert response.status_code == 409

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["intake_arbitrator_user_id"] == ARB_INTAKE_USER_ID
    assert case["status"] == "UNDER_REVIEW"
    assert case["version"] == 3


def test_deciding_a_submitted_case_is_refused_by_the_state_gate(api):
    """SUBMITTED is not a from-state for the decision route, and the state gate
    answers before any evidence-sufficiency reasoning could.

    PRD: "The `ArbitrationCase` is in a status from which the requested transition
    is declared in §3 — else `ERR_INVALID_CASE_STATE` (HTTP 409). This guards
    review opening, seller response, escalation, decision, withdrawal, evidence
    filing, transportation-leg recording, countering and accepting."

    Design: Corner/state_machines/a_decision_on_a_submitted_case_is_rejected_as_invalid_from
    """
    world = build_case_world(api, [MECHANICAL_POLICY])

    response = api.create_decision(
        world["case"]["id"],
        decision_payload(
            "CLAIM_DENIED",
            fault_party="BUYER",
            rationale="No supporting evidence on file",
        ),
        deciding_arbitrator_headers(),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_CASE_STATE.value)
    assert response.status_code == 409

    decisions, meta = validate_unpaginated(
        api.list_decision(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 0)
    assert decisions == []

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "SUBMITTED"
    assert case["version"] == 1


def test_withdrawing_from_the_denied_terminal_state_applies_no_second_decrement(api):
    """The counters were already released when the denial landed, so the refused
    withdrawal cannot drive the open counts negative.

    PRD: "Withdrawal is permitted from `SUBMITTED`, `UNDER_REVIEW`, `NEGOTIATION`
    and `COUNTERED`; from any terminal status it is refused with
    `ERR_INVALID_CASE_STATE`, and from another buyer's case with
    `ERR_NOT_CASE_OWNER`."

    Design: Corner/state_machines/withdraw_from_the_denied_terminal_state_is_rejected
    """
    world = build_arbitrator_review_world(api, [MECHANICAL_POLICY])
    decide_case(
        api,
        world["case"]["id"],
        "CLAIM_DENIED",
        fault_party="BUYER",
        rationale="Condition consistent with the light disclosure",
    )

    response = api.withdraw_case(
        world["case"]["id"],
        {"withdraw_reason": "Buyer changed their mind"},
        buyer_rep_headers(world["buyer"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_CASE_STATE.value)
    assert response.status_code == 409

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "DENIED"

    buyer = validate_success(api.get_buyer(world["buyer"]["id"], admin_headers()), 200)
    assert buyer["open_claim_count"] == 0
    assert buyer["lifetime_claim_count"] == 1
    seller = validate_success(api.get_seller(world["seller"]["id"], admin_headers()), 200)
    assert seller["open_claim_count"] == 0


def test_a_diagnostic_scan_does_not_substitute_for_an_inspection_report(api):
    """The only artefact on file is a scan, so the non-title gate fails and the case
    is left in SUBMITTED with the version the evidence post gave it.

    PRD: "For every family other than the two title families — that is, for
    `FRAME_DAMAGE`, `MECHANICAL` and `MILEAGE_DISCREPANCY` — at least one evidence
    row on the case must carry `evidence_type` `INSPECTION_REPORT`, or review
    opening is refused with `ERR_MISSING_INSPECTION_REPORT`."

    Design: Corner/state_machines/open_review_without_an_inspection_report_is_rejected
    """
    world = build_case_world(api, [MECHANICAL_POLICY])
    create_evidence(
        api,
        world["case"]["id"],
        world["buyer"]["id"],
        evidence_type="DIAGNOSTIC_SCAN",
        provider_name="Blue Ridge Diagnostics",
    )

    response = api.open_review(world["case"]["id"], {}, intake_arbitrator_headers())

    validate_error(response, ApiErrorId.ERR_MISSING_INSPECTION_REPORT.value)
    assert response.status_code == 422

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "SUBMITTED"
    assert case["intake_arbitrator_user_id"] is None
    assert case["version"] == 2


def test_a_title_claim_needs_a_title_document_before_the_verification_gate(api):
    """An inspection report is the wrong artefact for a title family, and the title
    gate answers even though the policy's verification gate is also unsatisfied.

    PRD: "For `TITLE_BRANDED` and `TITLE_MISSING` claims that first gate does not
    apply and a different one does: at least one evidence row must carry
    `evidence_type` `TITLE_DOCUMENT`, or the request is refused with
    `ERR_TITLE_CLAIM_REQUIRES_TITLE_EVIDENCE`."

    Design: Corner/state_machines/open_review_of_a_title_claim_without_a_title_document_is_rejected
    """
    world = build_case_world(
        api,
        [TITLE_BRANDED_POLICY],
        case_overrides={
            "defect_class": "TITLE_BRANDED",
            "claim_amount_cents": 0,
            "odometer_at_claim": 84000,
            "complaint_text": "Title came back branded salvage",
        },
    )
    create_evidence(
        api,
        world["case"]["id"],
        world["buyer"]["id"],
        evidence_type="INSPECTION_REPORT",
    )

    response = api.open_review(world["case"]["id"], {}, intake_arbitrator_headers())

    error = validate_error(
        response, ApiErrorId.ERR_TITLE_CLAIM_REQUIRES_TITLE_EVIDENCE.value
    )
    assert response.status_code == 422
    assert (
        error["error_id"]
        != ApiErrorId.ERR_THIRD_PARTY_VERIFICATION_REQUIRED.value
    )

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "SUBMITTED"
    assert case["effective_window_hours"] is None


def test_a_verified_report_alone_fails_the_third_party_verification_gate(api):
    """The report is verified and satisfies the family gate, yet the policy demands
    an independent verifier and nothing on file is one.

    PRD: "Finally, and independently of the family, when the governing policy sets
    `requires_third_party_verification` to true, at least one evidence row must
    have `evidence_type` `THIRD_PARTY_VERIFICATION` **and** `verified` true, or the
    request is refused with `ERR_THIRD_PARTY_VERIFICATION_REQUIRED`."

    Design: Corner/state_machines/open_review_without_third_party_verification_is_rejected
    """
    world = build_case_world(
        api,
        [FRAME_DAMAGE_POLICY],
        case_overrides={
            "defect_class": "FRAME_DAMAGE",
            "claim_amount_cents": 300000,
            "odometer_at_claim": 84500,
            "complaint_text": "Repaired unibody rail found on the lift",
        },
    )
    create_evidence(
        api,
        world["case"]["id"],
        world["buyer"]["id"],
        evidence_type="INSPECTION_REPORT",
        repair_estimate_cents=285000,
    )

    response = api.open_review(world["case"]["id"], {}, intake_arbitrator_headers())

    validate_error(response, ApiErrorId.ERR_THIRD_PARTY_VERIFICATION_REQUIRED.value)
    assert response.status_code == 422

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "SUBMITTED"
    assert case["version"] == 2

    rows, meta = validate_unpaginated(
        api.list_evidence(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert rows[0]["verified"] is True


def test_escalating_a_one_round_negotiation_leaves_the_round_open(api):
    """One round and no timeout is not exhaustion, and the refusal does not
    supersede the standing offer.

    PRD: "Escalation is gated on exhaustion: the case's `current_round_index` must
    have reached 3 rounds or more, **or** its `seller_response_timed_out` flag must
    be true. A case that has neither exhausted the round limit nor been abandoned
    by its consignor is refused with `ERR_NEGOTIATION_NOT_EXHAUSTED`"

    Design: Corner/state_machines/escalate_before_negotiation_is_exhausted_is_rejected
    """
    world = build_negotiation_world(api, seller_offer_cents=100000)

    response = api.escalate_case(
        world["case"]["id"],
        {"escalation_note": "Buyer wants an arbitrator to rule now"},
        intake_arbitrator_headers(),
    )

    validate_error(response, ApiErrorId.ERR_NEGOTIATION_NOT_EXHAUSTED.value)
    assert response.status_code == 409

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "NEGOTIATION"
    assert case["current_round_index"] == 1

    rounds, meta = validate_unpaginated(
        api.list_negotiation_rounds(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert rounds[0]["status"] == "OPEN"
    assert rounds[0]["seller_offer_cents"] == 100000


def test_phase_three_times_out_the_silent_consignor_and_mints_a_closed_round(api):
    """One second past the response deadline the sweep reports exactly one timeout,
    writes the reserved TIMEOUT round and faults the consignor.

    PRD: "Every `ArbitrationCase` whose `status` is `UNDER_REVIEW` and for which the
    clock has passed `review_opened_at_utc` plus the governing policy's
    `seller_response_hours` moves `UNDER_REVIEW → ARBITRATOR_REVIEW`. A
    `NegotiationRound` is minted for it with `response_type` `TIMEOUT`,
    `seller_offer_cents` 0 and `status` `CLOSED`"

    Design: Corner/state_machines/sweep_phase_three_times_out_the_seller_and_opens_arbitrator_review
    """
    world = build_under_review_world(api, [MECHANICAL_POLICY])
    set_clock(api, SELLER_TIMEOUT_CLOCK)

    report = validate_success(api.run_sweep(admin_headers()), 200)
    assert_sweep_report(report, seller_response_timeouts=1)

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "ARBITRATOR_REVIEW"
    assert case["seller_response_timed_out"] is True
    assert case["fault_party"] == "SELLER"

    rounds, meta = validate_unpaginated(
        api.list_negotiation_rounds(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert rounds[0]["response_type"] == "TIMEOUT"
    assert rounds[0]["status"] == "CLOSED"
    assert rounds[0]["round_index"] == 1
    assert rounds[0]["seller_offer_cents"] == 0

    sale = validate_success(api.get_sale(world["sale"]["id"], admin_headers()), 200)
    assert sale["open_case_count"] == 1
    assert sale["arbitration_status"] == "ACTIVE"


def test_phase_two_expires_the_lapsed_offer_and_faults_the_buyer(api):
    """The buyer let a standing offer lapse, so phase 2 runs first and the fault
    lands on the buyer rather than on the silent consignor.

    PRD: "Every `NegotiationRound` whose `status` is `OPEN` and whose
    `response_deadline_utc` the clock has passed **strictly** moves `OPEN →
    EXPIRED`, and its parent case moves `NEGOTIATION → ARBITRATOR_REVIEW` with
    `fault_party` set to `BUYER`, because the buyer is the party who let a standing
    offer lapse."

    Design: Corner/state_machines/sweep_phase_two_expires_an_open_round_and_faults_the_buyer
    """
    world = build_negotiation_world(api, seller_offer_cents=100000)
    assert_instant_equals(
        world["round"]["response_deadline_utc"], ROUND_DEADLINE, "response_deadline_utc"
    )
    set_clock(api, PAST_ROUND_DEADLINE)

    report = validate_success(api.run_sweep(admin_headers()), 200)
    assert_sweep_report(report, rounds_expired=1)

    rounds, meta = validate_unpaginated(
        api.list_negotiation_rounds(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert rounds[0]["status"] == "EXPIRED"

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "ARBITRATOR_REVIEW"
    assert case["fault_party"] == "BUYER"
    assert case["seller_response_timed_out"] is False


def test_withdrawing_a_negotiating_case_supersedes_its_open_round(api):
    """The open round is neither expired nor closed by the withdrawal: it is
    superseded, and no decision is ever written.

    PRD: "every round on it still in `OPEN` or `COUNTERED` becomes `SUPERSEDED` —
    `OPEN → SUPERSEDED` or `COUNTERED → SUPERSEDED` — processed in ascending
    `created_at` order"

    Design: Corner/state_machines/withdraw_supersedes_the_open_round_in_created_at_order
    """
    world = build_negotiation_world(api, seller_offer_cents=100000)

    withdrawn = withdraw_case(
        api,
        world["case"]["id"],
        world["buyer"]["id"],
        reason="Buyer resold the unit as-is",
    )
    assert withdrawn["status"] == "WITHDRAWN"

    rounds, meta = validate_unpaginated(
        api.list_negotiation_rounds(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert rounds[0]["status"] == "SUPERSEDED"
    assert rounds[0]["round_index"] == 1

    decisions, decisions_meta = validate_unpaginated(
        api.list_decision(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(decisions_meta, 0)
    assert decisions == []


def test_completing_an_inspection_twice_keeps_the_first_findings(api):
    """The second filing cannot overwrite the stored array, so the mechanical
    finding survives the attempt to replace it with a frame finding.

    PRD: "An inspection whose `status` is not `REQUESTED` cannot be completed and is
    refused with `ERR_INVALID_INSPECTION_STATE`."

    Design: Corner/state_machines/completing_an_inspection_twice_is_rejected
    """
    seller = create_seller(api)
    buyer = create_buyer(api)
    sale = create_sale(api, seller["id"], buyer["id"], light_channel="YELLOW")
    inspection = create_inspection(api, sale["id"], buyer["id"], program_tier="PREMIUM")
    assert_instant_equals(
        inspection["window_end_utc"], "2026-08-04T00:00:00.000Z", "window_end_utc"
    )
    validate_success(
        api.complete_inspection(
            inspection["id"], {"findings": ["MECHANICAL"]}, inspector_headers()
        ),
        200,
    )

    response = api.complete_inspection(
        inspection["id"], {"findings": ["FRAME_DAMAGE"]}, inspector_headers()
    )

    validate_error(response, ApiErrorId.ERR_INVALID_INSPECTION_STATE.value)
    assert response.status_code == 409

    rows, meta = validate_unpaginated(api.list_sale_inspections(sale["id"], admin_headers()))
    assert_unpaginated_meta(meta, 1)
    assert rows[0]["status"] == "COMPLETED"
    assert rows[0]["findings"] == ["MECHANICAL"]
    assert rows[0]["fee_cents"] == 27500
    assert rows[0]["version"] == 2


def test_reinstating_a_consignor_that_was_never_blocked_is_refused(api):
    """Reinstatement only makes sense on a blocked consignor, and the refusal
    appends no policy action and counts no reinstatement.

    PRD: "The consignor's `policy_tier` must be `BLOCKED`, or the request is refused
    with `ERR_SELLER_NOT_BLOCKED`."

    Design: Corner/state_machines/reinstating_a_seller_that_is_not_blocked_is_rejected
    """
    seller = create_seller(api)

    response = api.reinstate_seller(
        seller["id"],
        {"reinstate_note": "Dealer principal called the office"},
        admin_headers(),
    )

    validate_error(response, ApiErrorId.ERR_SELLER_NOT_BLOCKED.value)
    assert response.status_code == 409

    observed = validate_success(api.get_seller(seller["id"], admin_headers()), 200)
    assert observed["policy_tier"] == "GOOD_STANDING"
    assert observed["reinstated_count"] == 0
    assert observed["version"] == 1

    actions, meta = validate_unpaginated(
        api.list_seller_policy_actions(seller["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 0)
    assert actions == []


def test_settling_a_sale_twice_leaves_exactly_one_balanced_proceeds_pair(api):
    """The refused replay writes no second pair, so the sale's ledger still holds
    two rows summing to zero and the settlement instant is unchanged.

    PRD: "A sale whose `settlement_status` is not `UNSETTLED` is refused with
    `ERR_SALE_ALREADY_SETTLED`, so proceeds cannot be released twice and a reversed
    sale cannot be re-released."

    Design: Corner/state_machines/settling_a_sale_twice_is_rejected
    """
    world = build_sale_world(api, [MECHANICAL_POLICY])
    settle_sale(api, world["sale"]["id"])

    response = api.settle_sale(world["sale"]["id"], {}, admin_headers())

    validate_error(response, ApiErrorId.ERR_SALE_ALREADY_SETTLED.value)
    assert response.status_code == 409

    sale = validate_success(api.get_sale(world["sale"]["id"], admin_headers()), 200)
    assert sale["settlement_status"] == "SETTLED"
    assert_instant_equals(sale["settled_at_utc"], CLOCK_DEFAULT, "settled_at_utc")
    assert sale["version"] == 2

    entries, meta = validate_unpaginated(
        api.list_sale_ledger_entries(world["sale"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 2)
    assert_ledger_batch_balanced(entries, "the single proceeds pair")
    assert_ledger_rows(
        entries,
        [
            {"party": "SELLER", "entry_type": "SALE_PROCEEDS", "amount_signed_cents": 1450000},
            {"party": "BUYER", "entry_type": "SALE_PROCEEDS", "amount_signed_cents": -1450000},
        ],
    )


def test_a_dispute_is_born_closed_and_skips_negotiation_entirely(api):
    """The round never enters haggling: it is written CLOSED with a zero offer and
    no cooldown, and the case jumps straight to arbitrator review.

    PRD: "The round is written with `response_type` `DISPUTE`, `seller_offer_cents`
    0 and `status` `CLOSED` — the status that marks a round which never entered
    haggling — and the case jumps straight `UNDER_REVIEW → ARBITRATOR_REVIEW`."

    Design: Corner/state_machines/a_dispute_response_closes_the_round_and_skips_negotiation_entirely
    """
    world = build_under_review_world(api, [MECHANICAL_POLICY])

    round_row = seller_response(
        api,
        world["case"]["id"],
        world["seller"]["id"],
        "DISPUTE",
        note="No whine present on the block",
    )

    assert round_row["status"] == "CLOSED"
    assert round_row["response_type"] == "DISPUTE"
    assert round_row["seller_offer_cents"] == 0
    assert round_row["round_index"] == 1
    assert round_row["cooldown_until_utc"] is None

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "ARBITRATOR_REVIEW"
    assert case["current_round_index"] == 1
    assert case["seller_conceded"] is False
