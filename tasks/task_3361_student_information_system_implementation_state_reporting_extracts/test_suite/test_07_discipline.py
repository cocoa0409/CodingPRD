"""Discipline incidents: severity scoring variants, approve/void cascades, and
terminal lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_discipline_incident,
    create_student_with_enrollment,
    get_enrollment,
    setup_base,
    validate_error,
    validate_success,
    withdraw_enrollment,
)


def test_approve_voided_incident_returns_not_reported(api, registrar_headers):
    """PRD §3.6: "Approval moves a `REPORTED` incident to `APPROVED` (from anything
    else, `ERR_INCIDENT_NOT_REPORTED`)".
    PRD §3.6: "Voiding runs from either `REPORTED` or `APPROVED` to the terminal
    `VOIDED`; an incident already `VOIDED` rejects further transitions with
    `ERR_INCIDENT_ALREADY_VOIDED`."

    Design: Corner/state_machines/approve_voided_incident_returns_not_reported
    """
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(district["id"], year["id"])
    incident = create_discipline_incident(
        student["id"], enrollment["id"],
        raw_offense_code="TARDY", action_type="NONE", action_days=0)
    validate_success(api.void_discipline_incident(incident["id"], registrar_headers), 200)

    res = api.approve_discipline_incident(incident["id"], registrar_headers)
    validate_error(res, ApiErrorId.ERR_INCIDENT_NOT_REPORTED, expected_status=409)

    after = validate_success(
        api.get_discipline_incident(incident["id"], registrar_headers), 200)
    assert after["status"] == "VOIDED"
    enrollment_after = get_enrollment(enrollment["id"])
    assert enrollment_after["absence_weight_sum"] == pytest.approx(0.0, abs=1e-9), \
        "the rejected approve must not apply any absence cascade"


def test_severity_capped_variant_for_oss_action(api, registrar_headers):
    """PRD §3.6: "The raw score is `severity_base` multiplied by `action_days`. For
    the capped variant — actions `NONE`, `ISS`, and `OSS` — the recorded
    `severity_score` is that raw product clipped at 100."
    PRD §3.6: "So a `severity_base` of 25 with 6 `action_days` records 100 for an
    `OSS` incident but 150 for an `EXPULSION`."

    Design: Difficulty/dual_variant_calc/severity_cap_variant_by_action_type
    """
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(district["id"], year["id"])
    incident = create_discipline_incident(
        student["id"], enrollment["id"],
        incident_date="2026-10-05T00:00:00Z",
        raw_offense_code="FIGHT", action_type="OSS", action_days=6)
    assert incident["severity_base"] == 25
    # min(25 * 6, 100) = 100 under the capped variant.
    assert incident["severity_score"] == 100


def test_severity_uncapped_variant_for_expulsion_action(api, registrar_headers):
    """PRD §3.6: "For the uncapped variant — `EXPULSION` — the raw product stands
    unclipped."
    PRD §3.6: "So a `severity_base` of 25 with 6 `action_days` records 100 for an
    `OSS` incident but 150 for an `EXPULSION`."

    Design: Difficulty/dual_variant_calc/severity_cap_variant_by_action_type
    """
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(district["id"], year["id"])
    oss = create_discipline_incident(
        student["id"], enrollment["id"],
        incident_date="2026-10-05T00:00:00Z",
        raw_offense_code="FIGHT", action_type="OSS", action_days=6)
    expulsion = create_discipline_incident(
        student["id"], enrollment["id"],
        incident_date="2026-10-06T00:00:00Z",
        raw_offense_code="FIGHT", action_type="EXPULSION", action_days=6)
    # 25 * 6 = 150 stands unclipped for EXPULSION.
    assert expulsion["severity_score"] == 150
    assert oss["severity_score"] != expulsion["severity_score"], \
        "identical severity_base and action_days diverge across the two variants"


def test_approve_oss_cascades_into_absence_weight(api, registrar_headers):
    """PRD §3.6: "when the incident's `action_type` is `OSS`, the enrollment's
    `absence_weight_sum` grows by the full `action_days`, each day weighing 1.0,
    after which `absence_rate` and `absence_posture` recompute per §3.5."

    Design: Difficulty/transitive_cascade/discipline_approve_absence_cascade_depth2
    """
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(district["id"], year["id"])
    incident = create_discipline_incident(
        student["id"], enrollment["id"],
        incident_date="2026-10-05T00:00:00Z",
        raw_offense_code="FIGHT", action_type="OSS", action_days=9)

    approved = validate_success(
        api.approve_discipline_incident(incident["id"], registrar_headers), 200)
    assert approved["status"] == "APPROVED"

    enrollment_after = get_enrollment(enrollment["id"])
    assert enrollment_after["absence_weight_sum"] == pytest.approx(9.0, abs=1e-9), \
        "the approve, not a direct enrollment write, must add the 9 OSS days"

    # The weight mutation drives the posture recompute on the next recompute point:
    # 9.0 / 80 = 0.1125 >= 0.10 -> CHRONIC.
    withdrawn = withdraw_enrollment(enrollment["id"], "2026-10-20T00:00:00Z")
    assert withdrawn["absence_weight_sum"] == pytest.approx(9.0, abs=1e-9)
    assert withdrawn["absence_posture"] == "CHRONIC"


def test_void_approved_oss_reverses_absence_cascade(api, registrar_headers):
    """PRD §3.6: "Voiding an `APPROVED` out-of-school suspension compensates the
    earlier cascade: the enrollment's `absence_weight_sum` shrinks back by the
    `action_days`, and the rate and posture recompute — one of the paths by which a
    `CHRONIC` posture can fall back to `AT_RISK` or `CLEAR`."

    Design: Difficulty/transitive_cascade/discipline_approve_absence_cascade_depth2
    """
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(district["id"], year["id"])
    incident = create_discipline_incident(
        student["id"], enrollment["id"],
        incident_date="2026-10-05T00:00:00Z",
        raw_offense_code="FIGHT", action_type="OSS", action_days=9)
    validate_success(api.approve_discipline_incident(incident["id"], registrar_headers), 200)
    withdraw_enrollment(enrollment["id"], "2026-10-20T00:00:00Z")
    assert get_enrollment(enrollment["id"])["absence_posture"] == "CHRONIC"

    voided = validate_success(
        api.void_discipline_incident(incident["id"], registrar_headers), 200)
    assert voided["status"] == "VOIDED"

    enrollment_after = get_enrollment(enrollment["id"])
    assert enrollment_after["absence_weight_sum"] == pytest.approx(0.0, abs=1e-9), \
        "the void compensation must reverse the OSS weight"
    assert enrollment_after["absence_posture"] == "CLEAR"
