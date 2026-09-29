"""The gates a relocation must pass: eligibility, data residency and the risk ceiling."""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_classification_for,
    classification_decision_payload,
    draft_classification,
    get_success_data,
    list_all,
    read_employee,
    read_relocation,
    record_security,
    record_tax,
    register_employee,
    relocation_decision_payload,
    relocation_request_payload,
    setup_cycle_team_employee,
    setup_relocation_request,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import HRBP, MANAGER, WPO

CORE_TEAM = {
    "team_code": "T1-CORE",
    "expected_days_in_office_per_week": 3,
    "core_collaboration_days": ["TUE", "WED", "THU"],
    "headcount_planned": 12,
    "signal_corroboration_required": False,
}


def _restricted_pair():
    """One remote employee with two restricted-tier requests, reviewed identically.

    Brazil and New York share the reviews — three licensing gaps, three control
    gaps and a nexus cost sitting exactly on the per-request budget — so the only
    difference between the two rows is the jurisdiction.
    """
    scenario = setup_relocation_request(
        jurisdiction_code="BR",
        data_classification_tier="RESTRICTED",
        eligibility_class="FULLY_REMOTE",
        cycle_overrides={"cycle_label": "FY27-PP3"},
        team_overrides=dict(CORE_TEAM),
        employee_overrides={"employee_number": "E-1001"},
    )
    scenario["new_york"] = get_success_data(
        api_client.create_relocation_request(
            relocation_request_payload(
                scenario["employee"]["id"],
                jurisdiction_code="US_NY",
                data_classification_tier="RESTRICTED",
            ),
            HRBP,
        )
    )
    for request_id in (scenario["request"]["id"], scenario["new_york"]["id"]):
        record_tax(
            request_id, "CLEARED", licensing_gap_count=3,
            tax_nexus_registration_cost_cents=5000000,
        )
        record_security(request_id, "CLEARED", control_gap_count=3)
    scenario["brazil"] = read_relocation(scenario["request"]["id"])
    scenario["new_york"] = read_relocation(scenario["new_york"]["id"])
    return scenario


def _sixty_and_fifty_nine():
    """Two identical New York requests parted by a single nexus-cost step."""
    scenario = setup_relocation_request(
        jurisdiction_code="US_NY",
        data_classification_tier="CONFIDENTIAL",
        eligibility_class="HYBRID",
        cycle_overrides={"cycle_label": "FY27-BP2"},
        team_overrides=dict(CORE_TEAM),
        employee_overrides={"employee_number": "E-1001"},
    )
    scenario["under"] = scenario["request"]
    scenario["at_ceiling"] = get_success_data(
        api_client.create_relocation_request(
            relocation_request_payload(
                scenario["employee"]["id"],
                jurisdiction_code="US_NY",
                data_classification_tier="CONFIDENTIAL",
            ),
            HRBP,
        )
    )
    record_tax(
        scenario["under"]["id"], "CLEARED", licensing_gap_count=2,
        tax_nexus_registration_cost_cents=1500000,
    )
    record_security(scenario["under"]["id"], "CLEARED", control_gap_count=1)
    record_tax(
        scenario["at_ceiling"]["id"], "CLEARED", licensing_gap_count=2,
        tax_nexus_registration_cost_cents=1750000,
    )
    record_security(scenario["at_ceiling"]["id"], "CLEARED", control_gap_count=1)
    scenario["under"] = read_relocation(scenario["under"]["id"])
    scenario["at_ceiling"] = read_relocation(scenario["at_ceiling"]["id"])
    return scenario


def _three_classification_states():
    """Three employees on one team: undecided, approved onsite, approved hybrid."""
    base = setup_cycle_team_employee(
        cycle_overrides={"cycle_label": "FY27-CE1"},
        team_overrides=dict(CORE_TEAM),
        employee_overrides={"employee_number": "E-1001"},
    )
    onsite = approve_classification_for(
        register_employee(base["team"]["id"], employee_number="E-1002"),
        "ONSITE_REQUIRED",
    )["employee"]
    hybrid = approve_classification_for(
        register_employee(base["team"]["id"], employee_number="E-1003"),
        "HYBRID",
    )["employee"]
    pending = draft_classification(
        base["employee"],
        requested_class="FULLY_REMOTE",
        justification_code="TALENT_RETENTION",
        effective_from="2026-09-01",
    )
    pending = validate_success(api_client.submit_classification(pending["id"], HRBP))
    return {
        "undecided_employee": read_employee(base["employee"]["id"]),
        "undecided_classification": pending,
        "onsite": onsite,
        "hybrid": hybrid,
    }


def _internal_texas_payload(employee_id):
    return relocation_request_payload(
        employee_id,
        jurisdiction_code="US_TX",
        data_classification_tier="INTERNAL",
    )


def test_01_a_prohibited_jurisdiction_answers_before_the_risk_ceiling():
    """One request breaks two rules and the residency rule is the one that answers.

    PRD 3.7: "An approval of a `RESTRICTED`-tier request is only permitted into the
    three approved residency jurisdictions `US_CA`, `US_TX` and `US_NY`; any other
    jurisdiction is refused with `ERR_DATA_RESIDENCY_PROHIBITED` (409)."
    PRD 3.7: "And an approval whose final risk score reaches the approval ceiling of 60
    points is refused with `ERR_RELOCATION_RISK_CEILING` (409) — the boundary is
    inclusive, so exactly 60 is a refusal and 59 is approvable."
    PRD 2.10: "An approval of a `RESTRICTED`-tier relocation into a prohibited
    jurisdiction reports `ERR_DATA_RESIDENCY_PROHIBITED` (409) even when its final risk
    also breaches the approval ceiling."
    PRD 3.7: "On that particular refusal the request stays `UNDER_REVIEW`, and
    `decision_reason` is not written at all."

    Design: Difficulty/priority_pair_validation_conflict/data_residency_outranks_relocation_risk_ceiling
    """
    scenario = _restricted_pair()
    brazil = scenario["brazil"]
    assert brazil["preliminary_risk_score"] == 60, "thirty for Brazil, thirty for the tier"
    assert brazil["status"] == "UNDER_REVIEW"
    assert brazil["tax_review_status"] == "CLEARED"
    assert brazil["security_review_status"] == "CLEARED"

    validate_error(
        api_client.decide_relocation(
            brazil["id"], relocation_decision_payload("APPROVE"), WPO
        ),
        ApiErrorId.ERR_DATA_RESIDENCY_PROHIBITED.value,
        409,
    )
    unchanged = read_relocation(brazil["id"])
    assert unchanged["status"] == "UNDER_REVIEW", (
        "the residency refusal leaves the row exactly where it stood"
    )
    assert unchanged["decision_reason"] is None
    assert unchanged["final_risk_score"] == 0, (
        "a refused decision scores nothing, so the ceiling was never even consulted"
    )


def test_02_an_allowed_jurisdiction_lets_the_ceiling_answer_and_a_denial_writes_the_score():
    """The same reviews on an approved-residency row surface the other rule entirely.

    PRD 3.7: "The **final** variant, scored only at the join, adds three capped
    penalties on top of the same base: a licensing penalty of 7 points for each
    licensing gap found, capped at 21 points; a control penalty of 9 points for each
    data-security control gap found, capped at 27 points; and a nexus penalty of one
    point for every whole 250,000 cents of estimated registration cost — that is, one
    point per 2,500 dollars, with any remainder discarded rather than rounded — capped
    at 12 points."
    PRD 3.7: "The sum of base and all three penalties is then clamped to the same
    100-point ceiling."
    PRD 3.7: "`final_risk_score` is written on both branches of a decision that is
    actually taken."
    PRD 3.7: "A denial — and equally an approval where either dimension is `BLOCKED` —
    sets `status` to `DENIED`, with `decision_reason` recorded as `REVIEW_BLOCKED` when
    either dimension is `BLOCKED` and as `RISK_CEILING_REACHED` otherwise."
    PRD 3.7: "A request that has already reached the terminal `APPROVED` or `DENIED`
    status accepts no further decision and is refused with
    `ERR_RELOCATION_DECISION_FINAL` (409)."

    Design: Difficulty/priority_pair_validation_conflict/data_residency_outranks_relocation_risk_ceiling
    """
    scenario = _restricted_pair()
    new_york = scenario["new_york"]
    assert new_york["preliminary_risk_score"] == 42, "twelve for New York, thirty for the tier"

    validate_error(
        api_client.decide_relocation(
            new_york["id"], relocation_decision_payload("APPROVE"), WPO
        ),
        ApiErrorId.ERR_RELOCATION_RISK_CEILING.value,
        409,
    )
    assert read_relocation(new_york["id"])["status"] == "UNDER_REVIEW"

    denied = validate_success(
        api_client.decide_relocation(
            scenario["brazil"]["id"], relocation_decision_payload("DENY"), WPO
        )
    )
    assert denied["status"] == "DENIED"
    assert denied["final_risk_score"] == 100, (
        "base 60 plus three capped penalties of 21, 27 and 12 is clamped to 100"
    )
    assert denied["decision_reason"] == "RISK_CEILING_REACHED", (
        "neither dimension was blocked, so the other reason is recorded"
    )

    validate_error(
        api_client.decide_relocation(
            scenario["brazil"]["id"], relocation_decision_payload("DENY"), WPO
        ),
        ApiErrorId.ERR_RELOCATION_DECISION_FINAL.value,
        409,
    )
    assert read_relocation(scenario["brazil"]["id"])["final_risk_score"] == 100


def test_03_a_final_score_of_exactly_sixty_reaches_the_ceiling():
    """A nexus cost 250,000 cents higher buys one point, and that point is fatal.

    PRD 3.7: "And an approval whose final risk score reaches the approval ceiling of 60
    points is refused with `ERR_RELOCATION_RISK_CEILING` (409) — the boundary is
    inclusive, so exactly 60 is a refusal and 59 is approvable."
    PRD 3.7: "The **final** variant, scored only at the join, adds three capped
    penalties on top of the same base: a licensing penalty of 7 points for each
    licensing gap found, capped at 21 points; a control penalty of 9 points for each
    data-security control gap found, capped at 27 points; and a nexus penalty of one
    point for every whole 250,000 cents of estimated registration cost — that is, one
    point per 2,500 dollars, with any remainder discarded rather than rounded — capped
    at 12 points."
    PRD 3.7: "On that particular refusal the request stays `UNDER_REVIEW`, and
    `decision_reason` is not written at all."
    PRD 3.7: "The **preliminary** variant is that base alone, clamped to a ceiling of
    100 points, and it deliberately ignores licensing, control and nexus-cost penalties
    because none of them has been verified yet."

    Design: Difficulty/boundary_precision_check/relocation_final_risk_exactly_sixty_is_refused
    """
    scenario = _sixty_and_fifty_nine()
    assert scenario["under"]["preliminary_risk_score"] == 30
    assert scenario["at_ceiling"]["preliminary_risk_score"] == 30, (
        "the preliminary variant cannot tell the two rows apart at all"
    )
    assert scenario["under"]["final_risk_score"] == 0
    assert scenario["at_ceiling"]["final_risk_score"] == 0
    assert scenario["at_ceiling"]["tax_nexus_registration_cost_cents"] == 1750000

    validate_error(
        api_client.decide_relocation(
            scenario["at_ceiling"]["id"], relocation_decision_payload("APPROVE"), WPO
        ),
        ApiErrorId.ERR_RELOCATION_RISK_CEILING.value,
        409,
    )
    refused = read_relocation(scenario["at_ceiling"]["id"])
    assert refused["status"] == "UNDER_REVIEW"
    assert refused["decision_reason"] is None


def test_04_fifty_nine_is_approvable_while_the_sixty_row_can_only_be_denied():
    """Seven whole nexus units instead of six is the entire difference between them.

    PRD 3.7: "An approval where both dimensions are `CLEARED` sets `status` to
    `APPROVED` and `decision_reason` to `BOTH_REVIEWS_CLEARED`."
    PRD 3.7: "A denial — and equally an approval where either dimension is `BLOCKED` —
    sets `status` to `DENIED`, with `decision_reason` recorded as `REVIEW_BLOCKED` when
    either dimension is `BLOCKED` and as `RISK_CEILING_REACHED` otherwise."
    PRD 3.7: "For identical creation inputs the final score is therefore never below
    the preliminary score, and the two differ whenever any gap count or nexus cost is
    non-zero."
    PRD 3.7: "`final_risk_score` is written on both branches of a decision that is
    actually taken."

    Design: Difficulty/boundary_precision_check/relocation_final_risk_exactly_sixty_is_refused
    """
    scenario = _sixty_and_fifty_nine()

    approved = validate_success(
        api_client.decide_relocation(
            scenario["under"]["id"], relocation_decision_payload("APPROVE"), WPO
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["final_risk_score"] == 59, (
        "base 30 plus licensing 14, control 9 and six whole nexus units"
    )
    assert approved["decision_reason"] == "BOTH_REVIEWS_CLEARED"
    assert approved["preliminary_risk_score"] == 30

    denied = validate_success(
        api_client.decide_relocation(
            scenario["at_ceiling"]["id"], relocation_decision_payload("DENY"), WPO
        )
    )
    assert denied["status"] == "DENIED"
    assert denied["final_risk_score"] == 60, (
        "the seventh nexus unit is the one point that crossed the line"
    )
    assert denied["decision_reason"] == "RISK_CEILING_REACHED"
    assert denied["final_risk_score"] - approved["final_risk_score"] == 1


def test_05_filing_reads_the_state_and_the_value_of_a_row_in_another_aggregate():
    """A submitted classification is as good as absent; an approved onsite one fails later.

    PRD 3.7: "Two prerequisites are checked against the employee's classification
    record: an employee holding no `APPROVED` classification at all is refused with
    `ERR_NO_APPROVED_CLASSIFICATION` (409), and an employee whose
    `current_eligibility_class` is `ONSITE_REQUIRED` is refused with
    `ERR_CLASS_NOT_REMOTE_ELIGIBLE` (409) — you cannot relocate a role that policy says
    must be on site."
    PRD 3.3: "Every role in the company is eventually classified as one of three
    eligibility classes — `FULLY_REMOTE`, `HYBRID` or `ONSITE_REQUIRED` — and until a
    classification has been approved the employee is treated as `ONSITE_REQUIRED`."
    PRD 3.7: "A new request lands in `SUBMITTED` status with both `tax_review_status`
    and `security_review_status` at `PENDING`, with `licensing_gap_count`,
    `control_gap_count` and `tax_nexus_registration_cost_cents` at 0, with
    `final_risk_score` at 0 and `decision_reason` null, and with
    `preliminary_risk_score` scored once and never recomputed thereafter."

    Design: Difficulty/cross_entity_state_dependency/relocation_requires_approved_and_non_onsite_classification
    """
    scenario = _three_classification_states()
    assert scenario["undecided_classification"]["state"] == "PENDING_MANAGER"
    assert scenario["undecided_employee"]["current_eligibility_class"] == (
        "ONSITE_REQUIRED"
    ), "the documented fallback applies while the classification is undecided"

    validate_error(
        api_client.create_relocation_request(
            _internal_texas_payload(scenario["undecided_employee"]["id"]), HRBP
        ),
        ApiErrorId.ERR_NO_APPROVED_CLASSIFICATION.value,
        409,
    )

    validate_error(
        api_client.create_relocation_request(
            _internal_texas_payload(scenario["onsite"]["id"]), HRBP
        ),
        ApiErrorId.ERR_CLASS_NOT_REMOTE_ELIGIBLE.value,
        409,
    )
    assert scenario["onsite"]["current_eligibility_class"] == "ONSITE_REQUIRED", (
        "this classification is approved, so a different rule refuses the filing"
    )

    filed = get_success_data(
        api_client.create_relocation_request(
            _internal_texas_payload(scenario["hybrid"]["id"]), HRBP
        )
    )
    assert filed["status"] == "SUBMITTED"
    assert filed["tax_review_status"] == "PENDING"
    assert filed["security_review_status"] == "PENDING"
    assert filed["preliminary_risk_score"] == 14

    rows, meta = list_all(
        api_client.list_relocation_requests,
        WPO,
        {"employee_id": scenario["onsite"]["id"]},
    )
    assert meta["total_count"] == 0, "the refused filing created nothing"
    assert rows == []


def test_06_approving_the_other_aggregate_makes_the_identical_filing_succeed():
    """Nothing about the payload changed; a row in a different aggregate moved.

    PRD 3.3: "An `APPROVE` decision moves the row `PENDING_MANAGER → APPROVED`, stores
    `decided_by_user_id`, and sets off four further effects: the classification named by
    `supersedes_classification_id`, when it is not null, transitions `APPROVED →
    SUPERSEDED` and its own `version` advances; the employee's
    `current_eligibility_class` is recomputed; the employee's `non_compliance_pressure`,
    `compliance_state` and `escalation_stage` are recomputed, because the severity
    multiplier that scales shortfall into pressure is keyed on the eligibility class and
    has just changed; and the classification's `version` advances."
    PRD 3.7: "Two prerequisites are checked against the employee's classification
    record: an employee holding no `APPROVED` classification at all is refused with
    `ERR_NO_APPROVED_CLASSIFICATION` (409), and an employee whose
    `current_eligibility_class` is `ONSITE_REQUIRED` is refused with
    `ERR_CLASS_NOT_REMOTE_ELIGIBLE` (409) — you cannot relocate a role that policy says
    must be on site."
    PRD 3.7: "Jurisdiction contributes 6 points for `US_TX`, 10 for `US_CA`, 12 for
    `US_NY`, 18 for `IE`, 26 for `IN` and 30 for `BR`."

    Design: Difficulty/cross_entity_state_dependency/relocation_requires_approved_and_non_onsite_classification
    """
    scenario = _three_classification_states()
    employee_id = scenario["undecided_employee"]["id"]
    payload = _internal_texas_payload(employee_id)

    validate_error(
        api_client.create_relocation_request(payload, HRBP),
        ApiErrorId.ERR_NO_APPROVED_CLASSIFICATION.value,
        409,
    )

    decided = validate_success(
        api_client.decide_classification(
            scenario["undecided_classification"]["id"],
            classification_decision_payload("APPROVE", "remote by design"),
            MANAGER,
        )
    )
    assert decided["state"] == "APPROVED"
    assert read_employee(employee_id)["current_eligibility_class"] == "FULLY_REMOTE"

    filed = get_success_data(api_client.create_relocation_request(payload, HRBP))
    assert filed["status"] == "SUBMITTED", (
        "the byte-identical filing now passes because the blocking row changed state"
    )
    assert filed["employee_id"] == employee_id
    assert filed["preliminary_risk_score"] == 14, (
        "six points for Texas and eight for the internal tier"
    )

    rows, meta = list_all(
        api_client.list_relocation_requests, WPO, {"employee_id": employee_id}
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == filed["id"]


def test_07_every_penalty_term_is_capped_and_a_denial_ignores_the_approval_ceiling():
    """Gap counts past their caps buy nothing, and a denial simply records the score.

    PRD 3.7: "The **final** variant, scored only at the join, adds three capped
    penalties on top of the same base: a licensing penalty of 7 points for each
    licensing gap found, capped at 21 points; a control penalty of 9 points for each
    data-security control gap found, capped at 27 points; and a nexus penalty of one
    point for every whole 250,000 cents of estimated registration cost — that is, one
    point per 2,500 dollars, with any remainder discarded rather than rounded — capped
    at 12 points."
    PRD 3.7: "The sum of base and all three penalties is then clamped to the same
    100-point ceiling."
    PRD 3.7: "A denial — and equally an approval where either dimension is `BLOCKED` —
    sets `status` to `DENIED`, with `decision_reason` recorded as `REVIEW_BLOCKED` when
    either dimension is `BLOCKED` and as `RISK_CEILING_REACHED` otherwise."
    PRD 3.7: "A new request lands in `SUBMITTED` status with both `tax_review_status`
    and `security_review_status` at `PENDING`, with `licensing_gap_count`,
    `control_gap_count` and `tax_nexus_registration_cost_cents` at 0, with
    `final_risk_score` at 0 and `decision_reason` null, and with
    `preliminary_risk_score` scored once and never recomputed thereafter."

    Design: Corner/calculations/relocation_final_score_applies_every_penalty_cap
    """
    scenario = setup_relocation_request(
        jurisdiction_code="IE",
        data_classification_tier="CONFIDENTIAL",
        eligibility_class="FULLY_REMOTE",
        cycle_overrides={"cycle_label": "FY27-CRN43"},
        team_overrides={"team_code": "T-A"},
        employee_overrides={"employee_number": "E-1001"},
    )
    request_id = scenario["request"]["id"]
    assert scenario["request"]["preliminary_risk_score"] == 36, (
        "eighteen for Ireland and eighteen for the confidential tier"
    )
    assert scenario["request"]["final_risk_score"] == 0

    record_tax(
        request_id, "CLEARED", licensing_gap_count=5,
        tax_nexus_registration_cost_cents=3000000,
    )
    record_security(request_id, "BLOCKED", control_gap_count=4)

    denied = validate_success(
        api_client.decide_relocation(
            request_id, relocation_decision_payload("DENY"), WPO
        )
    )
    assert denied["status"] == "DENIED"
    assert denied["final_risk_score"] == 96, (
        "the raw sum of 119 shrinks to 36 plus 21, 27 and 12 once every cap bites"
    )
    assert denied["preliminary_risk_score"] == 36, (
        "the two variants of the same calculation now sit sixty points apart"
    )
    assert denied["decision_reason"] == "REVIEW_BLOCKED", (
        "a blocked dimension names itself even though 96 is far above the ceiling"
    )
    assert denied["licensing_gap_count"] == 5
    assert denied["control_gap_count"] == 4
    assert denied["tax_nexus_registration_cost_cents"] == 3000000

    rows, meta = list_all(
        api_client.list_relocation_requests,
        WPO,
        {"employee_id": scenario["employee"]["id"], "jurisdiction_code": "IE"},
    )
    assert meta["total_count"] == 1
    assert rows[0]["preliminary_risk_score"] == 36
    assert rows[0]["final_risk_score"] == 96
    assert rows[0]["tax_review_status"] == "CLEARED"
    assert rows[0]["security_review_status"] == "BLOCKED"
