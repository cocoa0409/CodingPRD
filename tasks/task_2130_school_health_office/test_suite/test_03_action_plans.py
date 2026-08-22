"""Chronic-condition action plans: the draft-to-active walk, the revision ceiling,
the supersede cascade and system-driven expiry."""

import pytest

from test_helpers import *  # noqa: F401,F403


def _supersede_scenario():
    """An ACTIVE plan with a verified order and one PREPARED dose, plus a replacement
    plan sitting at PENDING_PROVIDER that names the first plan as its predecessor."""
    school = create_school(name="Edison Elementary", building_code="EDI06")
    nurse = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    create_coverage(nurse["id"], school["id"], weekday="MON", start_minute=480, end_minute=960)
    student = create_student(school["id"], full_name="Hana Ito", grade_level=8,
                             date_of_birth="2012-11-30T00:00:00Z", allergy_severity="ANAPHYLAXIS",
                             chronic_condition_codes=["ASTHMA"], immunization_status="COMPLIANT")
    lot = create_lot(school["id"], medication_code="ALBUTEROL", lot_number="ALB-EDI-1",
                     is_stock_protocol=False, initial_quantity=5)
    plan_one = create_active_plan(student["id"], nurse["id"], condition_code="ASTHMA",
                                  severity_score=3, effective_from="2026-08-01T00:00:00Z")
    order = create_ready_order(student["id"], nurse["id"], action_plan_id=plan_one["id"],
                               medication_code="ALBUTEROL", schedule_type="PRN",
                               prn_min_interval_minutes=240, max_doses_per_day=4)
    set_clock(MONDAY_0900)
    visit = open_visit(student["id"], school["id"], nurse["id"], complaint_code="CHRONIC_CARE")
    assess_visit(visit["id"], nurse["id"], "Peak flow below baseline")
    record = prepare_dose(visit["id"], order["id"], nurse["id"], units=1)
    plan_two = create_plan(student["id"], nurse["id"], condition_code="ASTHMA", severity_score=4,
                           self_carry_requested=True, effective_from="2026-08-03T00:00:00Z",
                           supersedes_action_plan_id=plan_one["id"])
    submit_plan(plan_two["id"], nurse["id"])
    guardian_consent_plan(plan_two["id"], student["id"])
    return {"school": school, "nurse": nurse, "student": student, "lot": lot,
            "plan_one": plan_one, "plan_two": plan_two, "order": order,
            "visit": visit, "record": record}


def test_approving_a_replacement_plan_supersedes_suspends_and_voids_down_the_chain(api, admin_headers):
    """PRD §3.3: "If the approved plan named a `supersedes_action_plan_id` and that predecessor is
    `ACTIVE`, the predecessor moves `ACTIVE` → `SUPERSEDED`, and each subsequent hop is caused by
    the hop before it rather than by the approval itself."
    PRD §3.3: "Hop 2 follows because the predecessor is now superseded: every medication order
    hanging off it — that is, every order whose `action_plan_id` names it — whose `clinical_status`
    is `VERIFIED` moves to `SUSPENDED`."
    PRD §3.3: "Hop 3 follows because those orders are now suspended: every administration record
    referencing them that is still `PREPARED` moves to `VOIDED`, and each such record releases its
    reservation, returning its `units` from the lot's `quantity_reserved` to the lot's
    `quantity_on_hand`."

    Design: Difficulty/transitive_cascade/action_plan_supersede_four_hop_cascade
    """
    ctx = _supersede_scenario()

    approved = decide_plan(ctx["plan_two"]["id"], "APPROVE", note="Revised asthma plan signed")
    assert approved["status"] == "ACTIVE"

    assert validate_success(api.get_action_plan(ctx["plan_one"]["id"], admin_headers))["status"] == "SUPERSEDED"

    order = validate_success(api.get_medication_authorization(ctx["order"]["id"], admin_headers))
    assert order["clinical_status"] == "SUSPENDED"
    assert order["consent_status"] == "CONSENT_GRANTED", "the consent dimension is untouched"
    assert order["dispensable"] is False

    record = validate_success(api.get_administration_record(ctx["record"]["id"], admin_headers))
    assert record["status"] == "VOIDED"

    visit = validate_success(api.get_health_visit(ctx["visit"]["id"], admin_headers))
    assert visit["pending_administration_count"] == 0

    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["quantity_reserved"] == 0
    assert lot["quantity_on_hand"] == 5
    assert_lot_unit_conservation(lot)


def test_the_released_reservation_restores_days_of_supply_and_the_plan_pointer(api, admin_headers):
    """PRD §3.3: "Hop 4 follows because those reservations were released: any touched lot sitting
    at `DEPLETED` with a positive `quantity_on_hand` returns to `AVAILABLE`, and then the
    building's `epinephrine_days_of_supply`, `albuterol_days_of_supply` and
    `stock_protocol_status` are recomputed."
    PRD §3.3: "The student's `active_action_plan_id`, `self_carry_authorized` and alert flags are
    recomputed, dropping `NO_ACTIVE_PLAN` and adding `SELF_CARRY` when self-carriage was requested."

    Design: Difficulty/transitive_cascade/action_plan_supersede_four_hop_cascade
    """
    ctx = _supersede_scenario()

    decide_plan(ctx["plan_two"]["id"], "APPROVE", note="Revised asthma plan signed")

    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["days_of_supply"] == pytest.approx(4.17, abs=0.001), "5 units over 1.20 per day"
    assert lot["received_total"] == 5, "received_total never moves across the cascade"

    building = validate_success(api.get_school(ctx["school"]["id"], admin_headers))
    assert building["albuterol_days_of_supply"] == pytest.approx(4.17, abs=0.001)

    student = validate_success(api.get_student(ctx["student"]["id"], admin_headers))
    assert student["active_action_plan_id"] == ctx["plan_two"]["id"]
    assert student["self_carry_authorized"] is True
    assert "SELF_CARRY" in student["alert_flags"]


def test_a_drafted_plan_opens_at_draft_with_no_revisions_and_bumps_the_student(api, admin_headers):
    """PRD §3.3: "On acceptance the plan is created at `DRAFT` with `revision_round` 0,
    `guardian_consent_at` null and `provider_signed_at` null, the student's `version` is
    incremented by one, and the student's alert flags are recomputed — which adds `NO_ACTIVE_PLAN`
    when the student has no in-force plan pointer."

    Design: Corner/state_machines/action_plan_initial_state_is_draft_with_zero_revisions
    """
    school = create_school(name="Bexley Elementary", building_code="BEX30")
    nurse = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    student = create_student(school["id"], full_name="Bo Nguyen", grade_level=4,
                             date_of_birth="2016-02-14T00:00:00Z", allergy_severity="MODERATE",
                             chronic_condition_codes=["SEIZURE"])

    resp = api.create_action_plan(
        {"student_id": student["id"], "condition_code": "SEIZURE", "severity_score": 3,
         "requires_stock_epinephrine": False, "self_carry_requested": False,
         "effective_from": "2026-08-01T00:00:00Z", "expected_student_version": student["version"]},
        make_nurse_headers(nurse["id"]))
    data = validate_success(resp, 201)
    assert_action_plan(data)

    assert data["status"] == "DRAFT"
    assert data["revision_round"] == 0
    assert data.get("guardian_consent_at") is None
    assert data.get("provider_signed_at") is None

    after = validate_success(api.get_student(student["id"], admin_headers))
    assert after["version"] == student["version"] + 1
    assert after.get("active_action_plan_id") is None
    assert "NO_ACTIVE_PLAN" in after["alert_flags"]


def test_each_revision_returns_the_plan_to_draft_and_the_third_is_refused(api, admin_headers):
    """PRD §3.3: "A `decision` of `REQUEST_REVISION` on a `PENDING_PROVIDER` plan whose
    `revision_round` is below 2 increments `revision_round` by one, clears `guardian_consent_at`
    back to null so the guardian must consent afresh, and returns the plan to `DRAFT` — closing the
    cycle `DRAFT` → `PENDING_GUARDIAN` → `PENDING_PROVIDER` → `DRAFT`."
    PRD §3.3: "A third such request, made when `revision_round` already stands at 2, is refused
    with `ERR_REVISION_LIMIT_REACHED` (HTTP 409) at ladder position 44; the plan remains
    `PENDING_PROVIDER` and the physician's remaining option is revocation."

    Design: Corner/state_machines/action_plan_revision_cycle_clears_consent_and_caps_at_two_rounds
    """
    school = create_school(name="Delta Elementary", building_code="DEL32")
    nurse = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    student = create_student(school["id"], full_name="Dara Voss", grade_level=6,
                             date_of_birth="2014-12-01T00:00:00Z", allergy_severity="MILD",
                             chronic_condition_codes=["T1DM"])
    plan = create_plan(student["id"], nurse["id"], condition_code="T1DM", severity_score=3)

    submit_plan(plan["id"], nurse["id"])
    guardian_consent_plan(plan["id"], student["id"])
    first = decide_plan(plan["id"], "REQUEST_REVISION", note="Add rescue glucose dosing")
    assert first["status"] == "DRAFT"
    assert first["revision_round"] == 1
    assert first.get("guardian_consent_at") is None

    submit_plan(plan["id"], nurse["id"])
    guardian_consent_plan(plan["id"], student["id"])
    second = decide_plan(plan["id"], "REQUEST_REVISION", note="Clarify carb ratio")
    assert second["status"] == "DRAFT"
    assert second["revision_round"] == 2

    submit_plan(plan["id"], nurse["id"])
    guardian_consent_plan(plan["id"], student["id"])
    resp = api.decide_action_plan(plan["id"], {"decision": "REQUEST_REVISION", "note": "Third pass"},
                                  TEST_USERS["physician_headers"])
    validate_error(resp, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value, 409)

    final = validate_success(api.get_action_plan(plan["id"], admin_headers))
    assert final["status"] == "PENDING_PROVIDER"
    assert final["revision_round"] == 2
    assert final.get("guardian_consent_at") is not None


def test_deciding_a_plan_still_awaiting_the_guardian_reports_the_plan_state(api, admin_headers):
    """PRD §2.7: "Each record family has its own from-state check, and they sit in this relative
    order: `ActionPlan` (position 7, `ERR_PLAN_INVALID_STATE`), `MedicationAuthorization`
    (position 8, `ERR_AUTHORIZATION_INVALID_STATE`), `HealthVisit` (position 9,
    `ERR_VISIT_INVALID_STATE`), `AdministrationRecord` (position 10,
    `ERR_ADMINISTRATION_INVALID_STATE`), `MedicationStockLot` (position 11,
    `ERR_LOT_INVALID_STATE`), `Screening` (position 12, `ERR_SCREENING_INVALID_STATE`) and
    `DisclosureRequest` (position 13, `ERR_DISCLOSURE_INVALID_STATE`)."
    PRD §3.3: "A `decision` of `APPROVE` requires the plan to be `PENDING_PROVIDER`, requires
    `guardian_consent_at` to be non-null — a missing consent is `ERR_GUARDIAN_CONSENT_MISSING` at
    ladder position 25 — and requires the student to still be `ENROLLED`."

    Design: Corner/validations/guardian_consent_missing_is_masked_by_plan_state_check
    """
    school = create_school(name="Wren Elementary", building_code="WRN51")
    nurse = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    student = create_student(school["id"], full_name="Wynn Tate", grade_level=7,
                             date_of_birth="2013-07-07T00:00:00Z", allergy_severity="ANAPHYLAXIS")
    plan = create_plan(student["id"], nurse["id"], condition_code="ANAPHYLAXIS", severity_score=5,
                       requires_stock_epinephrine=True, self_carry_requested=True)
    submitted = submit_plan(plan["id"], nurse["id"])
    assert submitted["status"] == "PENDING_GUARDIAN"
    assert submitted.get("guardian_consent_at") is None

    resp = api.decide_action_plan(plan["id"], {"decision": "APPROVE"}, TEST_USERS["physician_headers"])
    validate_error(resp, ApiErrorId.ERR_PLAN_INVALID_STATE.value, 409)

    unchanged = validate_success(api.get_action_plan(plan["id"], admin_headers))
    assert unchanged["status"] == "PENDING_GUARDIAN"
    assert unchanged.get("provider_signed_at") is None
    assert validate_success(api.get_student(student["id"], admin_headers)).get("active_action_plan_id") is None


def test_a_second_plan_for_the_same_condition_needs_a_supersede_pointer(api, admin_headers):
    """PRD §3.3: "No other plan for the same student and the same `condition_code` may currently be
    `ACTIVE`, **unless** `supersedes_action_plan_id` names exactly that plan; a conflict is refused
    with `ERR_ACTIVE_PLAN_CONFLICT` at ladder position 41."

    Design: Corner/errors/error_active_plan_conflict_without_a_supersede_pointer
    """
    school = create_school(name="Quill Elementary", building_code="QLL81")
    nurse = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    student = create_student(school["id"], full_name="Quill Baptiste", grade_level=6,
                             date_of_birth="2014-09-16T00:00:00Z", chronic_condition_codes=["ASTHMA"])
    plan_one = create_active_plan(student["id"], nurse["id"], condition_code="ASTHMA", severity_score=3)
    assert plan_one["status"] == "ACTIVE"

    nurse_headers = make_nurse_headers(nurse["id"])
    body = {"student_id": student["id"], "condition_code": "ASTHMA", "severity_score": 4,
            "requires_stock_epinephrine": False, "self_carry_requested": False,
            "effective_from": "2026-08-02T00:00:00Z",
            "expected_student_version": student_version(student["id"])}
    refused = api.create_action_plan(body, nurse_headers)
    validate_error(refused, ApiErrorId.ERR_ACTIVE_PLAN_CONFLICT.value, 409)

    _, meta = validate_paginated(api.list_action_plans(admin_headers, {"student_id": student["id"]}))
    assert meta["total_count"] == 1

    body["expected_student_version"] = student_version(student["id"])
    body["supersedes_action_plan_id"] = plan_one["id"]
    accepted = validate_success(api.create_action_plan(body, nurse_headers), 201)
    assert accepted["status"] == "DRAFT"
    assert accepted["supersedes_action_plan_id"] == plan_one["id"]
    assert validate_success(api.get_action_plan(plan_one["id"], admin_headers))["status"] == "ACTIVE", \
        "the supersede only fires on approval"


def test_the_daily_checkpoint_expires_an_overdue_plan_and_suspends_its_orders(api, admin_headers):
    """PRD §3.3: "Expiry is the same shape but system-driven: during the daily checkpoint, an
    `ACTIVE` plan whose `review_due_at` is at or before the logical clock becomes `EXPIRED`, every
    linked order at `UNVERIFIED` or `VERIFIED` moves to `SUSPENDED`, and the student's plan
    pointer, self-carry flag and alert flags are recomputed — the flags regaining `NO_ACTIVE_PLAN`."
    PRD §3.3: "On approval `provider_signed_at` is stamped with the clock, `review_due_at` is set
    to 365 days after the plan's `effective_from`, and the plan becomes `ACTIVE`."

    Design: Corner/state_machines/daily_checkpoint_expires_overdue_plan_and_suspends_linked_order
    """
    school = create_school(name="Lark Elementary", building_code="LRK40")
    nurse = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    create_coverage(nurse["id"], school["id"], weekday="MON", start_minute=480, end_minute=960)
    student = create_student(school["id"], full_name="Lena Cardoso", grade_level=5,
                             date_of_birth="2015-09-09T00:00:00Z", chronic_condition_codes=["ASTHMA"])
    plan = create_active_plan(student["id"], nurse["id"], condition_code="ASTHMA", severity_score=2,
                              effective_from="2026-08-01T00:00:00Z")
    assert plan["review_due_at"].startswith("2027-08-01T00:00:00")
    order = create_ready_order(student["id"], nurse["id"], action_plan_id=plan["id"],
                               valid_until="2028-06-30T00:00:00Z")

    set_clock("2027-08-01T00:00:00Z")
    result = validate_success(api.run_daily_checkpoint({"school_id": school["id"]}, admin_headers))

    assert plan["id"] in result["expired_action_plan_ids"]
    assert school["id"] in result["recomputed_school_ids"]

    assert validate_success(api.get_action_plan(plan["id"], admin_headers))["status"] == "EXPIRED"
    refreshed_order = validate_success(api.get_medication_authorization(order["id"], admin_headers))
    assert refreshed_order["clinical_status"] == "SUSPENDED"
    assert refreshed_order["consent_status"] == "CONSENT_GRANTED"
    assert refreshed_order["dispensable"] is False

    student_row = validate_success(api.get_student(student["id"], admin_headers))
    assert student_row.get("active_action_plan_id") is None
    assert "NO_ACTIVE_PLAN" in student_row["alert_flags"]
