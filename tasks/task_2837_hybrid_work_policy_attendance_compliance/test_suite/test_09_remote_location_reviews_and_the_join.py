"""Two independent review dimensions on one relocation row, and the join that ends them."""
from test_helpers import (
    ApiErrorId,
    api_client,
    read_relocation,
    record_security,
    record_tax,
    relocation_decision_payload,
    security_review_payload,
    setup_relocation_request,
    tax_review_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import AUDITOR, HRBP, WPO


def _confidential_new_york_request():
    """A hybrid employee's request into New York carrying confidential data."""
    return setup_relocation_request(
        jurisdiction_code="US_NY",
        data_classification_tier="CONFIDENTIAL",
        eligibility_class="HYBRID",
        cycle_overrides={"cycle_label": "FY27-RLR"},
        team_overrides={"team_code": "T1-CORE"},
        employee_overrides={"employee_number": "E-1001"},
    )


def _internal_texas_request():
    """A fully remote employee's request into Texas at the internal data tier."""
    return setup_relocation_request(
        jurisdiction_code="US_TX",
        data_classification_tier="INTERNAL",
        eligibility_class="FULLY_REMOTE",
        cycle_overrides={"cycle_label": "FY27-PAR"},
        team_overrides={"team_code": "T1-CORE"},
        employee_overrides={"employee_number": "E-1001"},
    )


def test_01_the_preliminary_score_is_the_base_alone_and_is_never_rescored():
    """Twelve for New York plus eighteen for confidential, and no penalty ever lands on it.

    PRD 3.7: "A new request lands in `SUBMITTED` status with both `tax_review_status`
    and `security_review_status` at `PENDING`, with `licensing_gap_count`,
    `control_gap_count` and `tax_nexus_registration_cost_cents` at 0, with
    `final_risk_score` at 0 and `decision_reason` null, and with
    `preliminary_risk_score` scored once and never recomputed thereafter."
    PRD 3.7: "Jurisdiction contributes 6 points for `US_TX`, 10 for `US_CA`, 12 for
    `US_NY`, 18 for `IE`, 26 for `IN` and 30 for `BR`."
    PRD 3.7: "Data tier contributes 0 points for `PUBLIC`, 8 for `INTERNAL`, 18 for
    `CONFIDENTIAL` and 30 for `RESTRICTED`."
    PRD 3.7: "The **preliminary** variant is that base alone, clamped to a ceiling of
    100 points, and it deliberately ignores licensing, control and nexus-cost penalties
    because none of them has been verified yet."

    Design: Difficulty/dual_variant_calc/relocation_risk_preliminary_versus_final
    """
    scenario = _confidential_new_york_request()
    request = scenario["request"]
    assert request["status"] == "SUBMITTED"
    assert request["tax_review_status"] == "PENDING"
    assert request["security_review_status"] == "PENDING"
    assert request["licensing_gap_count"] == 0
    assert request["control_gap_count"] == 0
    assert request["tax_nexus_registration_cost_cents"] == 0
    assert request["decision_reason"] is None
    assert request["final_risk_score"] == 0, (
        "the final variant is not scored until the join"
    )
    assert request["preliminary_risk_score"] == 30, (
        "twelve points of jurisdiction and eighteen of data tier, and nothing else"
    )

    after_tax = record_tax(
        request["id"], "CLEARED", licensing_gap_count=2,
        tax_nexus_registration_cost_cents=1500000,
    )
    assert after_tax["licensing_gap_count"] == 2
    assert after_tax["tax_nexus_registration_cost_cents"] == 1500000
    assert after_tax["preliminary_risk_score"] == 30, (
        "verified licensing gaps and nexus cost do not touch the preliminary variant"
    )

    after_security = record_security(request["id"], "CLEARED", control_gap_count=1)
    assert after_security["control_gap_count"] == 1
    assert after_security["preliminary_risk_score"] == 30
    assert after_security["final_risk_score"] == 0, (
        "both dimensions are recorded but nobody has decided yet"
    )


def test_02_the_final_score_adds_three_capped_penalties_only_at_the_join():
    """The same row carries 30 and 59, and only the second figure faces the ceiling.

    PRD 3.7: "The **final** variant, scored only at the join, adds three capped
    penalties on top of the same base: a licensing penalty of 7 points for each
    licensing gap found, capped at 21 points; a control penalty of 9 points for each
    data-security control gap found, capped at 27 points; and a nexus penalty of one
    point for every whole 250,000 cents of estimated registration cost — that is, one
    point per 2,500 dollars, with any remainder discarded rather than rounded — capped
    at 12 points."
    PRD 3.7: "For identical creation inputs the final score is therefore never below
    the preliminary score, and the two differ whenever any gap count or nexus cost is
    non-zero."
    PRD 3.7: "Only the final score is ever compared against the approval ceiling."
    PRD 3.7: "And an approval whose final risk score reaches the approval ceiling of 60
    points is refused with `ERR_RELOCATION_RISK_CEILING` (409) — the boundary is
    inclusive, so exactly 60 is a refusal and 59 is approvable."
    PRD 3.7: "An approval where both dimensions are `CLEARED` sets `status` to
    `APPROVED` and `decision_reason` to `BOTH_REVIEWS_CLEARED`."

    Design: Difficulty/dual_variant_calc/relocation_risk_preliminary_versus_final
    """
    scenario = _confidential_new_york_request()
    request_id = scenario["request"]["id"]
    record_tax(
        request_id, "CLEARED", licensing_gap_count=2,
        tax_nexus_registration_cost_cents=1500000,
    )
    record_security(request_id, "CLEARED", control_gap_count=1)

    decided = validate_success(
        api_client.decide_relocation(
            request_id, relocation_decision_payload("APPROVE"), WPO
        )
    )
    assert decided["status"] == "APPROVED"
    assert decided["decision_reason"] == "BOTH_REVIEWS_CLEARED"
    assert decided["preliminary_risk_score"] == 30, (
        "the creation-time variant survives the join untouched"
    )
    assert decided["final_risk_score"] == 59, (
        "base 30, licensing 14, control 9 and six whole units of nexus cost"
    )
    assert decided["final_risk_score"] - decided["preliminary_risk_score"] == 29
    assert decided["final_risk_score"] < 60, (
        "the approval survived because 59 has not reached the inclusive ceiling"
    )
    assert read_relocation(request_id)["final_risk_score"] == 59


def test_03_recording_one_dimension_leaves_the_other_pending_and_blocks_the_join():
    """The fork lifts the row status once and the join refuses until both sides land.

    PRD 3.7: "It sets `security_review_status` from the outcome, stores that figure,
    moves `status` from `SUBMITTED` to `UNDER_REVIEW` if it has not moved already, and
    leaves `tax_review_status` completely untouched."
    PRD 3.7: "A request with either dimension still at `PENDING` is refused with
    `ERR_REVIEWS_INCOMPLETE` (409) — the fork must join before anyone decides."
    PRD 2.4: "Whenever a field on a row changes, that row's `updated_at` is refreshed to
    the current logical instant and its `version` advances — this applies equally to a
    row the caller addressed directly and to a parent or sibling row a cascade touched."

    Design: Difficulty/non_linear_state_machine/relocation_parallel_dimensions_reverse_order_and_join
    """
    scenario = _internal_texas_request()
    request = scenario["request"]
    assert request["status"] == "SUBMITTED"
    assert request["preliminary_risk_score"] == 14, (
        "six points for Texas and eight for the internal tier"
    )

    after_security = validate_success(
        api_client.record_security_review(
            request["id"], security_review_payload("CLEARED", 0), AUDITOR
        )
    )
    assert after_security["status"] == "UNDER_REVIEW", (
        "either dimension may be the fork point"
    )
    assert after_security["security_review_status"] == "CLEARED"
    assert after_security["tax_review_status"] == "PENDING", (
        "the dimensions advance independently on the same row"
    )
    assert after_security["version"] == request["version"] + 1

    validate_error(
        api_client.decide_relocation(
            request["id"], relocation_decision_payload("APPROVE"), WPO
        ),
        ApiErrorId.ERR_REVIEWS_INCOMPLETE.value,
        409,
    )
    blocked = read_relocation(request["id"])
    assert blocked["status"] == "UNDER_REVIEW", "the refused join moved nothing"
    assert blocked["decision_reason"] is None
    assert blocked["final_risk_score"] == 0


def test_04_the_second_review_is_a_self_loop_and_neither_dimension_repeats():
    """Reviewing in reverse order still joins, and no dimension may be written twice.

    PRD 3.7: "Whichever dimension is written first is the fork point that moves the
    request into `UNDER_REVIEW`; the second one leaves `status` at `UNDER_REVIEW`
    unchanged, which is a genuine self-loop on the overall state while the two
    dimensions evolve independently."
    PRD 3.7: "Recording this dimension sets `tax_review_status` from the outcome,
    stores both figures, moves `status` from `SUBMITTED` to `UNDER_REVIEW` if it has not
    moved already, and leaves `security_review_status` completely untouched."
    PRD 3.7: "Each dimension may be recorded exactly once: an attempt against a
    dimension that has already left `PENDING`, or against a request that has already
    reached `APPROVED` or `DENIED`, is refused with `ERR_REVIEW_ALREADY_RECORDED`
    (409)."
    PRD 3.7: "The **preliminary** variant is that base alone, clamped to a ceiling of
    100 points, and it deliberately ignores licensing, control and nexus-cost penalties
    because none of them has been verified yet."

    Design: Difficulty/non_linear_state_machine/relocation_parallel_dimensions_reverse_order_and_join
    """
    scenario = _internal_texas_request()
    request_id = scenario["request"]["id"]
    record_security(request_id, "CLEARED", control_gap_count=0)

    after_tax = validate_success(
        api_client.record_tax_review(
            request_id, tax_review_payload("CLEARED", 0, 0), HRBP
        )
    )
    assert after_tax["tax_review_status"] == "CLEARED"
    assert after_tax["security_review_status"] == "CLEARED"
    assert after_tax["status"] == "UNDER_REVIEW", (
        "the closing review is a self-loop on the row status"
    )

    joined = validate_success(
        api_client.decide_relocation(
            request_id, relocation_decision_payload("APPROVE"), WPO
        )
    )
    assert joined["status"] == "APPROVED"
    assert joined["decision_reason"] == "BOTH_REVIEWS_CLEARED"
    assert joined["preliminary_risk_score"] == 14
    assert joined["final_risk_score"] == 14, (
        "with every penalty input at zero the two variants coincide"
    )

    validate_error(
        api_client.record_security_review(
            request_id, security_review_payload("BLOCKED", 4), AUDITOR
        ),
        ApiErrorId.ERR_REVIEW_ALREADY_RECORDED.value,
        409,
    )
    unchanged = read_relocation(request_id)
    assert unchanged["security_review_status"] == "CLEARED"
    assert unchanged["control_gap_count"] == 0
    assert unchanged["final_risk_score"] == 14


def test_05_a_decided_request_is_a_one_way_door_for_the_decision_and_both_reviews():
    """After the join nothing reopens: not a second decision, not a re-review.

    PRD 3.7: "A request that has already reached the terminal `APPROVED` or `DENIED`
    status accepts no further decision and is refused with
    `ERR_RELOCATION_DECISION_FINAL` (409)."
    PRD 3.7: "Each dimension may be recorded exactly once: an attempt against a
    dimension that has already left `PENDING`, or against a request that has already
    reached `APPROVED` or `DENIED`, is refused with `ERR_REVIEW_ALREADY_RECORDED`
    (409)."
    PRD 3.7: "The join belongs exclusively to the `WorkplaceProgramOffice`, which
    supplies a `decision` of `APPROVE` or `DENY`."
    PRD 3.7: "Jurisdiction contributes 6 points for `US_TX`, 10 for `US_CA`, 12 for
    `US_NY`, 18 for `IE`, 26 for `IN` and 30 for `BR`."

    Design: Corner/state_machines/relocation_dimensions_join_once_and_the_decision_is_final
    """
    scenario = setup_relocation_request(
        jurisdiction_code="US_TX",
        data_classification_tier="PUBLIC",
        eligibility_class="HYBRID",
        cycle_overrides={"cycle_label": "FY27-CRN26"},
        team_overrides={"team_code": "T-A"},
        employee_overrides={"employee_number": "E-1001"},
    )
    request = scenario["request"]
    assert request["status"] == "SUBMITTED"
    assert request["tax_review_status"] == "PENDING"
    assert request["security_review_status"] == "PENDING"
    assert request["preliminary_risk_score"] == 6, "Texas alone, with a zero data tier"
    assert request["final_risk_score"] == 0

    after_tax = validate_success(
        api_client.record_tax_review(
            request["id"], tax_review_payload("CLEARED", 0, 0), HRBP
        )
    )
    assert after_tax["tax_review_status"] == "CLEARED"
    assert after_tax["status"] == "UNDER_REVIEW"
    assert after_tax["security_review_status"] == "PENDING"

    after_security = validate_success(
        api_client.record_security_review(
            request["id"], security_review_payload("CLEARED", 0), AUDITOR
        )
    )
    assert after_security["security_review_status"] == "CLEARED"
    assert after_security["tax_review_status"] == "CLEARED"
    assert after_security["status"] == "UNDER_REVIEW"

    approved = validate_success(
        api_client.decide_relocation(
            request["id"], relocation_decision_payload("APPROVE"), WPO
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["final_risk_score"] == 6
    assert approved["decision_reason"] == "BOTH_REVIEWS_CLEARED"

    validate_error(
        api_client.decide_relocation(
            request["id"], relocation_decision_payload("DENY"), WPO
        ),
        ApiErrorId.ERR_RELOCATION_DECISION_FINAL.value,
        409,
    )
    still_approved = read_relocation(request["id"])
    assert still_approved["status"] == "APPROVED"
    assert still_approved["decision_reason"] == "BOTH_REVIEWS_CLEARED"

    validate_error(
        api_client.record_tax_review(
            request["id"], tax_review_payload("BLOCKED", 3, 100000), HRBP
        ),
        ApiErrorId.ERR_REVIEW_ALREADY_RECORDED.value,
        409,
    )
    final = read_relocation(request["id"])
    assert final["licensing_gap_count"] == 0, (
        "a decided request cannot have its risk inputs rewritten after the fact"
    )
    assert final["tax_nexus_registration_cost_cents"] == 0
    assert final["final_risk_score"] == 6
