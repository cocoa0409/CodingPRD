"""The error catalogue: per-entity not-found codes and the already-billed guard.

PRD 2.7 gives every entity its own not-found identifier rather than one generic
code, and PRD 2.8 priority 5 resolves path identifiers before anything else
happens. PRD 2.8 priority 39, restated in PRD 3.7, closes a `BILL_ACCEPTED`
timesheet to both a second billing decision and a nurse correction, and PRD 2.12
requires the case's `billed_units_to_date` to be credited exactly once.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_AUTHORIZATION_NOT_FOUND,
    ERR_CASE_NOT_FOUND,
    ERR_COMPETENCY_NOT_FOUND,
    ERR_DISPUTE_NOT_FOUND,
    ERR_INCIDENT_NOT_FOUND,
    ERR_NURSE_NOT_FOUND,
    ERR_PLAN_OF_CARE_NOT_FOUND,
    ERR_SHIFT_NOT_FOUND,
    ERR_TIMESHEET_ALREADY_BILLED,
    ERR_TIMESHEET_NOT_FOUND,
)
from test_helpers.assertions import assert_units
from test_helpers.test_users import (
    AGENCY_ADMIN,
    CASE_MANAGER,
    CLINICAL_SUPERVISOR,
    SCHEDULER,
)
from test_helpers.types import BillingDecision, TimesheetStatus

#: A Wednesday shift of ISO week 32 of 2026, worked end to end.
SHIFT_START = "2026-08-05T08:00:00Z"
SHIFT_END = "2026-08-05T16:00:00Z"


def test_each_unknown_read_path_reports_the_code_of_its_own_entity(api):
    """PRD 2.7 lists a distinct 404 identifier per entity and resolves path
    identifiers strictly left to right, so nine reads that differ only in their
    route - every one of them addressing the same never-minted identifier -
    produce nine different `error_id` values: `ERR_PLAN_OF_CARE_NOT_FOUND`,
    `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_NURSE_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_TIMESHEET_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND` and
    `ERR_DISPUTE_NOT_FOUND`, each with HTTP 404 per PRD section 5.

    Design: Corner/errors/every_path_parameter_reports_its_own_not_found_code
    """
    fx.set_clock(api)

    checks = (
        (
            "GET /pdn/plans-of-care/{id}",
            api.get_plan_of_care(C.UNKNOWN_UUID, CASE_MANAGER),
            ERR_PLAN_OF_CARE_NOT_FOUND,
        ),
        (
            "GET /pdn/authorizations/{id}",
            api.get_authorization(C.UNKNOWN_UUID, CASE_MANAGER),
            ERR_AUTHORIZATION_NOT_FOUND,
        ),
        (
            "GET /pdn/nurses/{id}",
            api.get_nurse(C.UNKNOWN_UUID, AGENCY_ADMIN),
            ERR_NURSE_NOT_FOUND,
        ),
        (
            "GET /pdn/cases/{id}",
            api.get_case(C.UNKNOWN_UUID, CASE_MANAGER),
            ERR_CASE_NOT_FOUND,
        ),
        (
            "GET /pdn/shifts/{id}",
            api.get_shift(C.UNKNOWN_UUID, SCHEDULER),
            ERR_SHIFT_NOT_FOUND,
        ),
        (
            "GET /pdn/shift-assignments/{id}",
            api.get_assignment(C.UNKNOWN_UUID, SCHEDULER),
            ERR_ASSIGNMENT_NOT_FOUND,
        ),
        (
            "GET /pdn/timesheets/{id}",
            api.get_timesheet(C.UNKNOWN_UUID, SCHEDULER),
            ERR_TIMESHEET_NOT_FOUND,
        ),
        (
            "GET /pdn/incident-reports/{id}",
            api.get_incident_report(C.UNKNOWN_UUID, CLINICAL_SUPERVISOR),
            ERR_INCIDENT_NOT_FOUND,
        ),
        (
            "GET /pdn/authorization-disputes/{id}",
            api.get_dispute(C.UNKNOWN_UUID, CASE_MANAGER),
            ERR_DISPUTE_NOT_FOUND,
        ),
    )

    for route, response, error_id in checks:
        assert response.status_code == 404, f"{route}: {response.status_code} {response.text}"
        validate_error(response, error_id, 404)

    assert len({error_id for _route, _response, error_id in checks}) == 9


def test_an_unknown_competency_on_the_revoke_path_reports_its_own_code(api):
    """PRD 2.7 applies the same left-to-right path resolution to a write route
    and gives `NurseCompetency` its own identifier, so revoking a competency that
    was never minted answers `ERR_COMPETENCY_NOT_FOUND` (404) - the path check of
    PRD 2.8 priority 5 fires before the request-shape check of priority 7, and
    the `revoked_reason` supplied here is well formed in any case.

    Design: Corner/errors/every_path_parameter_reports_its_own_not_found_code
    """
    fx.set_clock(api)

    response = api.revoke_competency(
        C.UNKNOWN_UUID,
        f.revoke_competency_payload("targeting a competency that does not exist"),
        CLINICAL_SUPERVISOR,
    )

    validate_error(response, ERR_COMPETENCY_NOT_FOUND, 404)


def _accepted_timesheet(api):
    """A GPS-verified 480-minute visit on 2026-08-05, submitted and accepted:
    480 capped minutes give 32 gross units, no deduction applies and no late
    start is recorded, so `net_billable_units` is 32 (PRD 3.7)."""
    base = fx.setup_baseline(api)
    shift = fx.publish_shift(api, base.case_id, SHIFT_START, SHIFT_END)
    assignment = fx.assign_nurse(api, shift["id"], base.nurse_id)
    captured = fx.work_shift(
        api,
        shift["id"],
        base.nurse_id,
        assignment["id"],
        clock_in_at=SHIFT_START,
        clock_out_at=SHIFT_END,
    )
    accepted = fx.submit_and_accept_timesheet(api, captured["id"], base.payer_id)
    assert_units(accepted, "net_billable_units", 32)
    return base, accepted


def test_a_second_billing_decision_on_an_accepted_timesheet_is_refused(api):
    """PRD 2.8 priority 39 requires that a timesheet has not already reached
    `BILL_ACCEPTED` or `VOIDED` when a billing decision is recorded, so the
    payer's second look answers `ERR_TIMESHEET_ALREADY_BILLED` (409). Nothing
    moves: the row keeps `status` `BILL_ACCEPTED` with its 32
    `net_billable_units`, and because the `REJECT` never landed,
    `rejection_reason` stays null as PRD 3.7 requires of any timesheet not
    rejected.

    Design: Corner/errors/an_accepted_timesheet_refuses_a_second_decision_and_any_edit
    """
    base, accepted = _accepted_timesheet(api)

    response = api.billing_decision(
        accepted["id"],
        f.billing_decision_payload(
            BillingDecision.REJECT.value, "second look by the payer"
        ),
        base.payer_headers,
    )
    validate_error(response, ERR_TIMESHEET_ALREADY_BILLED, 409)

    reread = fx.refresh_timesheet(api, accepted["id"])
    assert reread["status"] == TimesheetStatus.BILL_ACCEPTED.value, reread
    assert_units(reread, "net_billable_units", 32)
    assert reread["rejection_reason"] is None, reread


def test_a_nurse_correction_of_an_accepted_timesheet_reports_the_same_code(api):
    """PRD 3.7 states outright that a timesheet which has already reached
    `BILL_ACCEPTED` or `VOIDED` cannot be corrected and that the attempt is
    `ERR_TIMESHEET_ALREADY_BILLED` (409), which is why PRD 2.8 priority 39
    governs the correction route rather than the `CAPTURED`-or-`BILL_REJECTED`
    edit rule. The patched `clock_out_at` is discarded: `gross_billable_units`
    and `net_billable_units` are still 32 and `edit_reason` is still null, the
    value PRD 3.7 pins before any correction has been made.

    Design: Corner/errors/an_accepted_timesheet_refuses_a_second_decision_and_any_edit
    """
    base, accepted = _accepted_timesheet(api)

    response = api.correct_timesheet(
        accepted["id"],
        f.correct_timesheet_payload(
            "nurse left early, correcting after the fact",
            clock_out_at="2026-08-05T15:30:00Z",
        ),
        base.nurse_headers,
    )
    validate_error(response, ERR_TIMESHEET_ALREADY_BILLED, 409)

    reread = fx.refresh_timesheet(api, accepted["id"])
    assert reread["status"] == TimesheetStatus.BILL_ACCEPTED.value, reread
    assert_units(reread, "gross_billable_units", 32)
    assert_units(reread, "net_billable_units", 32)
    assert reread["edit_reason"] is None, reread


def test_the_refused_decision_credits_the_case_units_only_once(api):
    """PRD 2.12 conserves accepted billable units: a case's
    `billed_units_to_date` equals the sum of `net_billable_units` over its
    `BILL_ACCEPTED` timesheets. One acceptance of a 32-unit visit therefore
    credits 32, and neither the refused second billing decision nor the refused
    nurse correction may add to or rewrite that figure.

    Design: Corner/errors/an_accepted_timesheet_refuses_a_second_decision_and_any_edit
    """
    base, accepted = _accepted_timesheet(api)

    validate_error(
        api.billing_decision(
            accepted["id"],
            f.billing_decision_payload(
                BillingDecision.REJECT.value, "second look by the payer"
            ),
            base.payer_headers,
        ),
        ERR_TIMESHEET_ALREADY_BILLED,
        409,
    )
    validate_error(
        api.correct_timesheet(
            accepted["id"],
            f.correct_timesheet_payload(
                "nurse left early, correcting after the fact",
                clock_out_at="2026-08-05T15:30:00Z",
            ),
            base.nurse_headers,
        ),
        ERR_TIMESHEET_ALREADY_BILLED,
        409,
    )

    case = validate_success(api.get_case(base.case_id, CASE_MANAGER))
    assert_units(case, "billed_units_to_date", 32)
