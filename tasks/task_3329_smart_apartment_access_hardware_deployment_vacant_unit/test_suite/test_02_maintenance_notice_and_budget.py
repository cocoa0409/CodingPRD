"""Maintenance visits: statutory notice, the energy budget and accrual variants."""

import pytest

from test_helpers import (
    HARDWARE,
    MAINTENANCE,
    MANAGER,
    ApiErrorId,
    certify_visit,
    get_success_data,
    pin_clock,
    provision_property,
    provision_unit,
    read_maintenance_visit,
    read_property,
    request_visit,
    setup_completed_visit,
    setup_visit,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Accrual variants
# ---------------------------------------------------------------------------

def test_certification_accrues_the_provisional_figure_immediately(api):
    """PRD §3.7: "A visit's `accrued_cost_cents` is computed from a base of 2000
    cents, plus an emergency surcharge of 1500 cents when the visit is an
    emergency, plus 700 cents for each hour of work where the hours are the
    visit's `planned_hours` rounded up to a whole number. On certification the
    provisional figure uses the planned hours."

    Design: Corner/consistency_model/certificate_visit_side_effects_visible_in_same_request_response
    """
    pin_clock()
    prop = provision_property()
    unit = provision_unit(prop["id"])
    visit = request_visit(unit["id"], start_at="2026-09-03T10:00:00Z", end_at="2026-09-03T12:00:00Z")

    data = validate_success(
        api.certify_notice(visit["id"], {"notice_mailed_at": "2026-09-01T09:00:00Z"}, MANAGER),
        200,
    )
    assert data["status"] == "NOTICE_CERTIFIED"
    assert data["accrued_cost_cents"] == 3400, "2000 + ceil(2.0) * 700"
    assert read_property(prop["id"])["budget_committed_cents"] == 3400


def test_final_accrual_replaces_the_provisional_figure(api):
    """PRD §3.7: "On certification the provisional figure uses the planned
    hours; on completion the figure is replaced by one that uses the hours
    actually spent, so the provisional number is superseded rather than added
    to."

    Design: Difficulty/dual_variant_calc/maintenance_accrual_provisional_vs_final
    """
    pin_clock()
    prop = provision_property()
    unit = provision_unit(prop["id"])
    visit = request_visit(unit["id"], start_at="2026-09-03T10:00:00Z", end_at="2026-09-03T12:30:00Z")

    certified = validate_success(
        api.certify_notice(visit["id"], {"notice_mailed_at": "2026-09-01T09:00:00Z"}, MANAGER),
        200,
    )
    assert certified["accrued_cost_cents"] == 4100, "2000 + ceil(2.5) * 700"

    completed = validate_success(
        api.complete_maintenance_visit(visit["id"], {"actual_hours": 1.5}, MAINTENANCE),
        200,
    )
    assert completed["status"] == "COMPLETED"
    assert completed["accrued_cost_cents"] == 3400, "2000 + ceil(1.5) * 700"


def test_finalisation_lowers_the_property_committed_budget_by_the_variant_delta(api):
    """PRD §2.8: "`budget_committed_cents` is the sum of `accrued_cost_cents`
    across the property's `MaintenanceVisit` rows whose status is
    `NOTICE_CERTIFIED` or `COMPLETED`."

    Design: Difficulty/dual_variant_calc/maintenance_accrual_provisional_vs_final
    """
    pin_clock()
    prop = provision_property()
    unit = provision_unit(prop["id"])
    visit = request_visit(unit["id"], start_at="2026-09-03T10:00:00Z", end_at="2026-09-03T12:30:00Z")
    certify_visit(visit["id"], notice_mailed_at="2026-09-01T09:00:00Z")
    assert read_property(prop["id"])["budget_committed_cents"] == 4100

    get_success_data(
        api.complete_maintenance_visit(visit["id"], {"actual_hours": 1.5}, MAINTENANCE)
    )

    assert read_property(prop["id"])["budget_committed_cents"] == 3400, (
        "the provisional 4100 is superseded, giving a 700-cent drop"
    )


def test_emergency_surcharge_is_added_to_the_base_accrual(api):
    """PRD §3.7: "A visit's `accrued_cost_cents` is computed from a base of 2000
    cents, plus an emergency surcharge of 1500 cents when the visit is an
    emergency, plus 700 cents for each hour of work where the hours are the
    visit's `planned_hours` rounded up to a whole number."

    Design: Corner/consistency_model/certificate_visit_side_effects_visible_in_same_request_response
    """
    pin_clock()
    _, _, visit = setup_visit(
        notice_certified=False, start_at="2026-09-03T10:00:00Z",
        end_at="2026-09-03T12:00:00Z", is_emergency=True,
    )
    data = validate_success(
        api.certify_notice(visit["id"], {"notice_mailed_at": "2026-09-01T09:00:00Z"}, MANAGER),
        200,
    )
    assert data["accrued_cost_cents"] == 4900, "2000 + 1500 + ceil(2.0) * 700"


# ---------------------------------------------------------------------------
# Cancellation and conservation of committed cents
# ---------------------------------------------------------------------------

def test_cancelling_a_certified_visit_resets_its_accrual_to_zero(api):
    """PRD §3.7: "A `PropertyManager` may instead cancel the visit before any
    work happens by supplying the cancellation flag as `cancelled`; the visit
    moves to `CANCELLED` — a terminal state — and its accrual resets to 0."

    Design: Difficulty/compensating_invariant/property_committed_budget_zero_sum_on_cancel
    """
    pin_clock()
    prop = provision_property()
    unit = provision_unit(prop["id"])
    visit = request_visit(unit["id"], start_at="2026-09-03T10:00:00Z", end_at="2026-09-03T12:30:00Z")

    certified = validate_success(
        api.certify_notice(visit["id"], {"notice_mailed_at": "2026-09-01T09:00:00Z"}, MANAGER),
        200,
    )
    assert certified["accrued_cost_cents"] == 4100

    cancelled = validate_success(
        api.complete_maintenance_visit(visit["id"], {"cancelled": True}, MANAGER), 200
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["accrued_cost_cents"] == 0


def test_certify_then_cancel_leaves_no_residual_accrual_behind(api):
    """PRD §2.8: "Rows that are `CANCELLED` contribute nothing, and cancelling a
    visit resets that visit's own `accrued_cost_cents` to 0 rather than leaving
    a stale accrual behind."

    Design: Difficulty/compensating_invariant/property_committed_budget_zero_sum_on_cancel
    """
    pin_clock()
    prop = provision_property()
    unit = provision_unit(prop["id"])
    visit = request_visit(unit["id"], start_at="2026-09-03T10:00:00Z", end_at="2026-09-03T12:30:00Z")
    certify_visit(visit["id"], notice_mailed_at="2026-09-01T09:00:00Z")

    cancelled = validate_success(
        api.complete_maintenance_visit(visit["id"], {"cancelled": True}, MANAGER), 200
    )

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["accrued_cost_cents"] == 0
    assert read_maintenance_visit(unit["id"], visit["id"])["accrued_cost_cents"] == 0


def test_property_budget_returns_to_zero_after_cancelling_the_only_visit(api):
    """PRD §2.8: "`budget_committed_cents` is the sum of `accrued_cost_cents`
    across the property's `MaintenanceVisit` rows whose status is
    `NOTICE_CERTIFIED` or `COMPLETED`."

    Design: Difficulty/compensating_invariant/property_committed_budget_zero_sum_on_cancel
    """
    pin_clock()
    prop = provision_property()
    unit = provision_unit(prop["id"])
    visit = request_visit(unit["id"], start_at="2026-09-03T10:00:00Z", end_at="2026-09-03T12:30:00Z")
    certify_visit(visit["id"], notice_mailed_at="2026-09-01T09:00:00Z")
    assert read_property(prop["id"])["budget_committed_cents"] == 4100

    get_success_data(
        api.complete_maintenance_visit(visit["id"], {"cancelled": True}, MANAGER)
    )

    assert read_property(prop["id"])["budget_committed_cents"] == 0, (
        "a cancelled visit contributes nothing to the committed total"
    )


# ---------------------------------------------------------------------------
# Completion boundary and state guards
# ---------------------------------------------------------------------------

def test_completion_rejects_zero_actual_hours_and_accepts_a_fraction(api):
    """PRD §3.7: "A `PropertyManager` or `MaintenanceTechnician` completes it by
    supplying `actual_hours`, and completion requires that the actual hours be
    greater than zero; the visit moves to `COMPLETED`, its accrual is restated
    with the actual hours."

    Design: Difficulty/boundary_precision_check/maintenance_complete_rejects_zero_actual_hours
    """
    pin_clock()
    _, _, visit = setup_visit(
        notice_certified=True, start_at="2026-09-03T10:00:00Z",
        end_at="2026-09-03T12:30:00Z",
    )

    rejected = api.complete_maintenance_visit(visit["id"], {"actual_hours": 0}, MAINTENANCE)
    validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST, 400)
    assert read_maintenance_visit(visit["unit_id"], visit["id"])["status"] == "NOTICE_CERTIFIED"

    accepted = api.complete_maintenance_visit(visit["id"], {"actual_hours": 0.5}, MAINTENANCE)
    validate_success(accepted, 200)


def test_completion_above_zero_restates_the_accrual_with_actual_hours(api):
    """PRD §3.7: "on completion the figure is replaced by one that uses the
    hours actually spent."

    Design: Difficulty/boundary_precision_check/maintenance_complete_rejects_zero_actual_hours
    """
    pin_clock()
    _, _, visit = setup_visit(
        notice_certified=True, start_at="2026-09-03T10:00:00Z",
        end_at="2026-09-03T12:30:00Z",
    )

    data = validate_success(
        api.complete_maintenance_visit(visit["id"], {"actual_hours": 0.5}, MAINTENANCE), 200
    )
    assert data["status"] == "COMPLETED"
    assert data["accrued_cost_cents"] == 2700, "2000 + ceil(0.5) * 700"


def test_completion_of_a_requested_visit_is_rejected(api):
    """PRD §3.7: "Completion or cancellation of a visit that is not in
    `NOTICE_CERTIFIED` is refused with `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/maintenance_complete_requires_notice_certified
    """
    pin_clock()
    _, _, visit = setup_visit(notice_certified=False)

    resp = api.complete_maintenance_visit(visit["id"], {"actual_hours": 1.0}, MAINTENANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    stored = read_maintenance_visit(visit["unit_id"], visit["id"])
    assert stored["status"] == "REQUESTED"
    assert stored["accrued_cost_cents"] == 0


def test_completing_an_already_completed_visit_is_already_terminal(api):
    """PRD §2.12: "Sixth, the target resource must not already be in a terminal
    state — otherwise `ERR_ALREADY_TERMINAL` (409)."

    Design: Corner/state_machines/terminal_work_order_has_no_outgoing_transitions
    """
    pin_clock()
    _, _, visit = setup_completed_visit(
        actual_hours=2.0, start_at="2026-09-03T10:00:00Z", end_at="2026-09-03T12:00:00Z"
    )

    resp = api.complete_maintenance_visit(visit["id"], {"actual_hours": 3.0}, MAINTENANCE)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)

    stored = read_maintenance_visit(visit["unit_id"], visit["id"])
    assert stored["status"] == "COMPLETED"
    assert stored["accrued_cost_cents"] == 3400


# ---------------------------------------------------------------------------
# Notice lead time and business hours
# ---------------------------------------------------------------------------

def test_late_notice_is_rejected_for_a_non_emergency_visit(api):
    """PRD §2.6: "The required lead time is 48 hours for an ordinary visit and
    24 hours for an emergency visit ... If notice was served later than the
    required lead time allows, certification is refused with
    `ERR_NOTICE_REQUIREMENT_UNMET` and an HTTP status of 409."

    Design: Corner/errors/notice_lead_time_violated_rejects_certify
    """
    pin_clock()
    _, _, visit = setup_visit(
        notice_certified=False, start_at="2026-09-03T10:00:00Z",
        end_at="2026-09-03T11:00:00Z",
    )

    resp = api.certify_notice(
        visit["id"], {"notice_mailed_at": "2026-09-03T09:00:00Z"}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_NOTICE_REQUIREMENT_UNMET, 409)
    assert read_maintenance_visit(visit["unit_id"], visit["id"])["status"] == "REQUESTED"


def test_emergency_visit_requires_only_twenty_four_hours_of_notice(api):
    """PRD §2.6: "The required lead time is 48 hours for an ordinary visit and
    24 hours for an emergency visit — a visit is flagged as an emergency by its
    `is_emergency` boolean."

    Design: Corner/errors/notice_lead_time_violated_rejects_certify
    """
    pin_clock()
    _, _, visit = setup_visit(
        notice_certified=False, start_at="2026-09-03T10:00:00Z",
        end_at="2026-09-03T11:00:00Z", is_emergency=True,
    )

    data = validate_success(
        api.certify_notice(visit["id"], {"notice_mailed_at": "2026-09-02T09:00:00Z"}, MANAGER),
        200,
    )
    assert data["status"] == "NOTICE_CERTIFIED"


def test_sufficient_notice_still_fails_when_the_start_is_outside_business_hours(api):
    """PRD §2.6: "The visit's `start_at`, taken in its local hour, must fall
    inside the half-open legal window that opens at 08:00 and closes at 20:00 —
    that is, an hour of 08 through 19 is acceptable and an hour of 20 or later
    is not. A visit whose start falls outside that window is refused with
    `ERR_OUTSIDE_NOTICE_WINDOW` and an HTTP status of 422."

    Design: Corner/validations/notice_lead_time_satisfied_then_outside_window_rejected
    """
    pin_clock()
    _, _, visit = setup_visit(
        notice_certified=False, start_at="2026-09-03T21:00:00Z",
        end_at="2026-09-04T00:00:00Z",
    )

    resp = api.certify_notice(
        visit["id"], {"notice_mailed_at": "2026-09-01T09:00:00Z"}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_NOTICE_WINDOW, 422)
    assert read_maintenance_visit(visit["unit_id"], visit["id"])["status"] == "REQUESTED"


# ---------------------------------------------------------------------------
# Budget cap enforcement
# ---------------------------------------------------------------------------

def test_certification_is_refused_when_the_accrual_would_breach_the_daily_cap(api):
    """PRD §2.8: "The platform refuses any operation that would push
    `budget_committed_cents` above `temp_budget_cents_per_day`. The check applies
    when a maintenance visit is certified ... and the refusal carries
    `ERR_BUDGET_EXCEEDED` with an HTTP status of 409."

    Design: Corner/validations/budget_committed_boundary_rejects_visit_that_exceeds_cap
    """
    pin_clock()
    prop = provision_property(temp_budget_cents_per_day=400)
    unit = provision_unit(prop["id"])
    visit = request_visit(unit["id"], start_at="2026-09-03T10:00:00Z", end_at="2026-09-03T13:00:00Z")

    resp = api.certify_notice(
        visit["id"], {"notice_mailed_at": "2026-09-01T09:00:00Z"}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED, 409)

    assert read_property(prop["id"])["budget_committed_cents"] == 0
    assert read_maintenance_visit(unit["id"], visit["id"])["status"] == "REQUESTED"


def test_certification_succeeds_when_the_committed_total_stays_within_the_cap(api):
    """PRD §2.8: "The check applies when a maintenance visit is certified, when
    an installation job is completed, and when an installation job is created,
    and the refusal carries `ERR_BUDGET_EXCEEDED` with an HTTP status of 409."

    Design: Corner/validations/budget_committed_boundary_rejects_visit_that_exceeds_cap
    """
    pin_clock()
    prop = provision_property(temp_budget_cents_per_day=4100)
    unit = provision_unit(prop["id"])
    visit = request_visit(unit["id"], start_at="2026-09-03T10:00:00Z", end_at="2026-09-03T13:00:00Z")

    data = validate_success(
        api.certify_notice(visit["id"], {"notice_mailed_at": "2026-09-01T09:00:00Z"}, MANAGER),
        200,
    )
    assert data["status"] == "NOTICE_CERTIFIED"
    assert read_property(prop["id"])["budget_committed_cents"] == 4100


def test_hardware_technician_cannot_certify_notice(api):
    """PRD §2.1: "The operations reserved to `PropertyManager` alone are resident
    onboarding, resident deactivation, the certification of legal notice on a
    maintenance visit, and the vacant-unit automation run."

    Design: Corner/rbac/hardware_technician_cannot_certify_notice
    """
    pin_clock()
    _, _, visit = setup_visit(notice_certified=False)

    resp = api.certify_notice(
        visit["id"], {"notice_mailed_at": "2026-09-01T09:00:00Z"}, HARDWARE
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
    assert read_maintenance_visit(visit["unit_id"], visit["id"])["status"] == "REQUESTED"


def test_completion_restates_the_accrual_with_a_fractional_hour_boundary(api):
    """PRD §3.7: "completion requires that the actual hours be greater than zero;
    the visit moves to `COMPLETED`, its accrual is restated with the actual
    hours."

    Design: Difficulty/boundary_precision_check/maintenance_complete_rejects_zero_actual_hours
    """
    pin_clock()
    _, _, visit = setup_visit(
        notice_certified=True, start_at="2026-09-03T10:00:00Z",
        end_at="2026-09-03T12:30:00Z",
    )
    data = validate_success(
        api.complete_maintenance_visit(visit["id"], {"actual_hours": 2.25}, MAINTENANCE), 200
    )
    assert data["accrued_cost_cents"] == 4100, "2000 + ceil(2.25) * 700"
    assert data["actual_hours"] == pytest.approx(2.25, abs=0.01)