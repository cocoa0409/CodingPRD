"""Validation-ladder priority pairs observed in both orders.

Each test below translates exactly one designed instance; the `Design:` line at
the end of every docstring names the instance it comes from.
"""

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_cents, assert_collection, assert_error, assert_is_none
from test_helpers.constants import (
    CapDecisionOutcome,
    CapStatus,
    DeterminationOutcome,
    NqtlType,
    PlanYearStatus,
    RegulatorRequestStatus,
    RemedyType,
    StringencyFinding,
    SubClassification,
)
from test_helpers.test_users import make_sponsor_headers


COLLIDING_PERIOD = {
    "sub_classification": SubClassification.OFFICE_VISITS,
    "measurement_period_start": "2026-06-01",
    "measurement_period_end": "2026-08-31",
}


def _control_and_frozen_plan_years(api):
    """Two identically classified plan years, one of them under regulator review.

    Both already carry an OUTPATIENT / IN_NETWORK / OFFICE_VISITS classification
    for 2026-01-01..2026-06-30, so the same follow-up payload collides on either
    of them; only the second has been frozen by a regulator request.
    """
    admin = fx.register_administrator(api)
    control = fx.open_plan_year(api, admin["id"], plan_year_label="2026-CONTROL")
    fx.create_classification(
        api, control["id"], sub_classification=SubClassification.OFFICE_VISITS
    )
    frozen = fx.open_plan_year(api, admin["id"], plan_year_label="2026-FROZEN")
    frozen_classification = fx.create_classification(
        api, frozen["id"], sub_classification=SubClassification.OFFICE_VISITS
    )
    request = fx.open_regulator_request(
        api,
        frozen["id"],
        requested_nqtl_types=[NqtlType.PRIOR_AUTHORIZATION],
        request_reference="DOL-EBSA-2026-00512",
    )
    return fx.Scenario(
        admin_id=admin["id"],
        control_id=control["id"],
        frozen_id=frozen["id"],
        frozen_classification_id=frozen_classification["id"],
        regulator_request_id=request["id"],
        sponsor_headers=make_sponsor_headers(),
    )


def test_the_frozen_plan_year_reports_its_state_failure_before_the_period_overlap(api):
    """The same colliding payload reports overlap on one plan year and state on the other.

    Run against the still-OPEN control the payload genuinely trips the
    measurement-period rule, so the temporal failure is real rather than merely
    unobserved.  Run against the frozen plan year the state check at rung 15 wins
    over the temporal check at rung 28.

    PRD: "When a request would fail more than one rule, the server reports the
    first failure in the following order and stops."

    Design: Difficulty/priority_pair_validation_conflict/state_priority_15_beats_temporal_priority_28_on_classification_create
    """
    scenario = _control_and_frozen_plan_years(api)

    assert_error(
        api.create_classification(
            scenario.control_id,
            f.classification_payload(**COLLIDING_PERIOD),
            scenario.sponsor_headers,
        ),
        ApiErrorId.MEASUREMENT_PERIOD_OVERLAP,
    )
    assert_error(
        api.create_classification(
            scenario.frozen_id,
            f.classification_payload(**COLLIDING_PERIOD),
            scenario.sponsor_headers,
        ),
        ApiErrorId.PLAN_YEAR_NOT_OPEN,
    )


def test_neither_refused_classification_reached_the_frozen_plan_years_design_surface(api):
    """The refusals left both plan years exactly as the regulator request found them.

    The frozen plan year is still UNDER_REGULATOR_REVIEW behind an OPEN request,
    and its classification list still holds the single row created before the
    freeze.

    PRD: "Opening a request is exclusive to the `Regulator` role. It stamps
    `opened_at` from the logical clock, sets `response_due_at` to `opened_at`
    advanced by 30 calendar days, writes `status` `OPEN` and `regulator_round` 0,
    leaves `completeness_score` and `response_sufficient` null until the first
    response, and — because the analyses produced must describe a fixed plan
    design — moves the plan year from `OPEN` to `UNDER_REGULATOR_REVIEW`,
    refreshing its `updated_at` and incrementing its `version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/state_priority_15_beats_temporal_priority_28_on_classification_create
    """
    scenario = _control_and_frozen_plan_years(api)
    api.create_classification(
        scenario.frozen_id, f.classification_payload(**COLLIDING_PERIOD), scenario.sponsor_headers
    )

    assert (
        fx.read_plan_year(api, scenario.frozen_id)["status"]
        == PlanYearStatus.UNDER_REGULATOR_REVIEW
    )
    assert (
        fx.read_regulator_request(api, scenario.regulator_request_id)["status"]
        == RegulatorRequestStatus.OPEN
    )
    rows, _ = assert_collection(
        api.list_plan_year_classifications(
            scenario.frozen_id, None, scenario.sponsor_headers
        ),
        1,
        1,
        False,
    )
    assert rows[0]["id"] == scenario.frozen_classification_id


def _over_cap_remedy_awaiting_a_decision(api, officer_headers):
    """A violation found by `user-officer-01` and a remedy far above the board's cap.

    The plan year's ceiling is only 100,000 cents while the drafted design change
    freezes 1,655,433 cents, so an approval violates the fiscal rule; the officer
    who recorded the determination also violates approver independence.
    """
    admin = fx.register_administrator(api)
    plan_year = fx.open_plan_year(api, admin["id"], remediation_liability_cap_cents=100000)
    classification = fx.create_classification(
        api, plan_year["id"], sub_classification=SubClassification.OFFICE_VISITS
    )
    scenario = fx.Scenario(
        admin_id=admin["id"],
        plan_year_id=plan_year["id"],
        classification_id=classification["id"],
        sponsor_headers=make_sponsor_headers(),
    )
    item = fx.inventory_item(api, plan_year["id"], classification["id"])
    scenario.item_id = item["id"]
    fx.with_denial_rate_evidence(api, scenario, nqtl_item_id=item["id"])

    analysis = fx.draft_analysis(
        api,
        item["id"],
        stringency_written_finding=StringencyFinding.MORE_STRINGENT_MH,
        stringency_operation_finding=StringencyFinding.MORE_STRINGENT_MH,
    )
    fx.submit_analysis(api, analysis["id"])
    fx.record_determination(
        api,
        item["id"],
        plan_year["id"],
        DeterminationOutcome.VIOLATION,
        headers=officer_headers,
        rationale=(
            "Prior authorization is applied to MH/SUD benefits only and denies at three "
            "times the comparable rate."
        ),
    )
    cap = fx.draft_cap(
        api,
        item["id"],
        headers=scenario.sponsor_headers,
        remedy_type=RemedyType.DESIGN_CHANGE,
        affected_claims_count=1327,
        average_claim_cents=4990,
    )
    scenario.cap_id = cap["id"]
    scenario.cap = cap
    return scenario


def test_approver_independence_is_reported_before_the_liability_cap(api, officer_headers, officer_alt_headers):
    """The same approval fails two rules and reports the earlier one first.

    Approving as the determining officer reports the independence failure at rung
    19 rather than the cap failure at rung 34.  Retrying as an independent officer
    strips the safety failure away and exposes the fiscal one, so the pair is
    observed in both orders.

    PRD: "The liability cap is respected (`ERR_LIABILITY_CAP_EXCEEDED`). This is
    evaluated last, so a corrective plan that would both breach the cap and
    violate approver independence reports the independence failure first."

    Design: Difficulty/priority_pair_validation_conflict/safety_priority_19_beats_fiscal_priority_34_on_corrective_plan_decision
    """
    scenario = _over_cap_remedy_awaiting_a_decision(api, officer_headers)

    assert_error(
        api.decide_corrective_action_plan(
            scenario.cap_id,
            f.cap_decision_payload(
                CapDecisionOutcome.APPROVED,
                decision_note="Approved by the officer who recorded the determination.",
            ),
            officer_headers,
        ),
        ApiErrorId.APPROVER_IS_DETERMINER,
    )
    assert_error(
        api.decide_corrective_action_plan(
            scenario.cap_id,
            f.cap_decision_payload(
                CapDecisionOutcome.APPROVED,
                decision_note="Approved by an independent officer.",
            ),
            officer_alt_headers,
        ),
        ApiErrorId.LIABILITY_CAP_EXCEEDED,
    )


def test_neither_refused_approval_stamped_the_plan_or_booked_the_liability(
    api, officer_headers, officer_alt_headers
):
    """Two refused approvals leave the frozen amount, the status and the ledger alone.

    The plan still reports the liability frozen at its own creation, still sits in
    DRAFT with no approver stamped, and the plan year's ledger has never been
    touched — a refused approval contributes nothing.

    PRD: "Approval moves the plan `DRAFT` to `APPROVED`, stamps
    `approved_by_user_id` from the acting `X-User-ID`, increments the plan's
    `version` by 1, adds exactly the plan's frozen `reprocessing_liability_cents`
    to the plan year's `remediation_liability_cents`, and increments the plan
    year's `version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/safety_priority_19_beats_fiscal_priority_34_on_corrective_plan_decision
    """
    scenario = _over_cap_remedy_awaiting_a_decision(api, officer_headers)
    api.decide_corrective_action_plan(
        scenario.cap_id, f.cap_decision_payload(CapDecisionOutcome.APPROVED), officer_headers
    )
    api.decide_corrective_action_plan(
        scenario.cap_id, f.cap_decision_payload(CapDecisionOutcome.APPROVED), officer_alt_headers
    )

    cap = fx.read_cap(api, scenario.cap_id)
    assert_cents(cap["reprocessing_liability_cents"], 1655433, "reprocessing_liability_cents")
    assert cap["status"] == CapStatus.DRAFT
    assert_is_none(cap["approved_by_user_id"], "approved_by_user_id")

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert_cents(plan_year["remediation_liability_cents"], 0, "remediation_liability_cents")
