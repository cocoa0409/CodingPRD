"""Transitive cascades that reach three and four levels past their trigger.

Each test below translates exactly one designed instance; the `Design:` line at
the end of every docstring names the instance it comes from.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_collection,
    assert_error,
    assert_index,
    assert_score,
)
from test_helpers.constants import (
    CompliancePosture,
    CooperationStatus,
    DeterminationOutcome,
    EscalationStatus,
    FulfillmentStatus,
    NoticeSource,
    NoticeType,
    NqtlItemStatus,
    PlanYearStatus,
    SubClassification,
)
from test_helpers.test_users import OFFICER_USER_ID


def _item_ready_for_a_violation(api):
    """A PRIOR_AUTHORIZATION item, MH/SUD-only, sitting in ANALYSIS_SUBMITTED.

    Its validated denial-rate evidence publishes a disparity ratio of 3.0000, so
    the recomputed stringency index clamps to 10.00 and a VIOLATION outcome
    agrees with the evidence.
    """
    return fx.item_awaiting_determination(
        api, sub_classification=SubClassification.OFFICE_VISITS
    )


def test_a_violation_determination_cascades_four_levels_to_the_plan_years_status(
    api, officer_headers
):
    """One determination moves the item, mints the notice, re-derives the counters
    and finally moves the plan year.

    The officer names only the NQTL item, yet the request ends with a participant
    notice that did not exist before, a plan year carrying two fresh violation
    counters and a lifecycle status the caller never wrote.

    PRD: "Finally that posture drives the plan year from `OPEN` or
    `UNDER_REGULATOR_REVIEW` into `REMEDIATION`, and the plan year's `version`
    increments by 1."

    Design: Difficulty/transitive_cascade/violation_determination_cascades_four_levels_to_plan_year_status
    """
    scenario = _item_ready_for_a_violation(api)

    item = validate_success(
        api.create_determination(
            scenario.item_id,
            f.violation_determination_payload(
                fx.plan_year_version(api, scenario.plan_year_id),
                rationale=(
                    "Prior authorization is imposed on MH/SUD outpatient visits only and "
                    "denies at three times the medical/surgical rate."
                ),
            ),
            officer_headers,
        ),
        201,
    )

    assert item["status"] == NqtlItemStatus.VIOLATION
    assert item["determination_recorded_by_user_id"] == OFFICER_USER_ID
    assert_index(item["stringency_in_operation_index"], 10.00)
    assert item["stringency_flag"] is True

    notices, _ = assert_collection(
        api.list_participant_notices(scenario.item_id, None, officer_headers), 1, 1, False
    )
    assert notices[0]["notice_type"] == NoticeType.VIOLATION_DISCLOSURE
    assert notices[0]["source"] == NoticeSource.DETERMINATION_CASCADE
    assert notices[0]["recipient_count"] == 1200

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["open_violation_count"] == 1
    assert plan_year["notified_violation_count"] == 1
    assert plan_year["compliance_posture"] == CompliancePosture.VIOLATION
    assert plan_year["status"] == PlanYearStatus.REMEDIATION
    assert_cents(plan_year["remediation_liability_cents"], 0, "remediation_liability_cents")


def test_the_remediation_status_the_cascade_produced_freezes_the_plan_design(api, officer_headers):
    """The fourth level of the cascade is observable, not merely reported.

    A classification create that succeeded before the determination is refused
    afterwards, which proves the plan year really left OPEN rather than only
    reporting a new posture.

    PRD: "Creating a benefit classification or a treatment-limitation level
    additionally requires the owning plan year to be exactly `OPEN`; if it sits in
    `UNDER_REGULATOR_REVIEW` or `REMEDIATION` the write is rejected with
    `ERR_PLAN_YEAR_NOT_OPEN` (HTTP 409)."

    Design: Difficulty/transitive_cascade/violation_determination_cascades_four_levels_to_plan_year_status
    """
    scenario = _item_ready_for_a_violation(api)
    fx.record_determination(
        api,
        scenario.item_id,
        scenario.plan_year_id,
        DeterminationOutcome.VIOLATION,
        headers=officer_headers,
    )

    assert_error(
        api.create_classification(
            scenario.plan_year_id,
            f.classification_payload(
                sub_classification=SubClassification.ALL_OTHER_OUTPATIENT,
                measurement_period_start="2026-07-01",
                measurement_period_end="2026-12-31",
            ),
            scenario.sponsor_headers,
        ),
        ApiErrorId.PLAN_YEAR_NOT_OPEN,
    )


def _request_ripe_for_a_breach(api):
    """An untouched production request whose notice rung has already been used.

    The plan year holds no NQTL item at all, so its posture starts at COMPLIANT
    and any later movement can only have come through the administrator.  The
    clock is left one second past the seven-day grace period that follows
    `due_at`, so the breach rung is ripe.
    """
    scenario = fx.registered_plan(api)
    request = fx.issue_vendor_request(api, scenario.admin_id, scenario.plan_year_id)
    scenario.vendor_request_id = request["id"]

    fx.advance_clock(api, "2026-09-16T00:00:00Z")
    fx.escalate(api, scenario.vendor_request_id)
    fx.advance_clock(api, "2026-09-23T00:00:01Z")
    return scenario


def test_declaring_a_breach_cascades_through_the_administrator_to_its_plan_years(api):
    """The escalate call names one request and ends up rewriting a plan year.

    Before the breach the administrator is merely late, scoring 85.00 and still
    COOPERATIVE, and the plan year is COMPLIANT.  Declaring the breach drops the
    score to 60.00 on both bases, turns the administrator DELINQUENT, and through
    that — an entity the request never named — pushes the plan year to AT_RISK.

    PRD: "Third — because `cooperation_status` has now fallen to `DELINQUENT` or
    `ESCALATED` — the compliance posture of **every** plan year whose
    `administrator_id` is this administrator is recomputed, which by the second
    rung of the posture ladder yields `AT_RISK` for each plan year that has no
    violation of its own, and each such plan year's `version` increments by 1."

    Design: Difficulty/transitive_cascade/breach_declaration_cascades_three_levels_to_plan_year_posture
    """
    scenario = _request_ripe_for_a_breach(api)

    before_admin = fx.read_administrator(api, scenario.admin_id)
    assert_score(before_admin["cooperation_score"], 85.00, "cooperation_score before breach")
    assert before_admin["cooperation_status"] == CooperationStatus.COOPERATIVE
    assert (
        fx.read_plan_year(api, scenario.plan_year_id)["compliance_posture"]
        == CompliancePosture.COMPLIANT
    )

    breached = fx.escalate(api, scenario.vendor_request_id)
    assert breached["escalation_status"] == EscalationStatus.BREACH_DECLARED
    assert breached["fulfillment_status"] == FulfillmentStatus.OPEN

    admin = fx.read_administrator(api, scenario.admin_id)
    assert admin["breach_count"] == 1
    assert admin["late_request_count"] == 1
    assert_score(admin["cooperation_score"], 60.00, "cooperation_score")
    assert_score(
        admin["regulatory_basis_cooperation_score"], 60.00, "regulatory_basis_cooperation_score"
    )
    assert admin["cooperation_status"] == CooperationStatus.DELINQUENT

    assert (
        fx.read_plan_year(api, scenario.plan_year_id)["compliance_posture"]
        == CompliancePosture.AT_RISK
    )


def test_the_breach_cascade_stops_short_of_moving_the_plan_years_status(api):
    """Unlike the determination cascade, this one changes posture but not status.

    The AT_RISK rung of the ladder carries no lifecycle consequence, so the plan
    year stays OPEN and its own violation counters stay at zero — the breach
    reached it entirely through the administrator's cooperation status.

    PRD: "From either `OPEN` or `UNDER_REGULATOR_REVIEW`, a recomputation that
    yields `VIOLATION` sets `compliance_posture` to `VIOLATION` and moves `status`
    to `REMEDIATION`."

    Design: Difficulty/transitive_cascade/breach_declaration_cascades_three_levels_to_plan_year_posture
    """
    scenario = _request_ripe_for_a_breach(api)
    fx.escalate(api, scenario.vendor_request_id)

    plan_year = fx.read_plan_year(api, scenario.plan_year_id)
    assert plan_year["compliance_posture"] == CompliancePosture.AT_RISK
    assert plan_year["status"] == PlanYearStatus.OPEN
    assert plan_year["open_violation_count"] == 0
    assert plan_year["failing_parity_test_count"] == 0
