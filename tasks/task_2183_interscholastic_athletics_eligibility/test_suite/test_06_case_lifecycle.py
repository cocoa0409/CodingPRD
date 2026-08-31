"""Case intake, the appeal cycle, and promotion to ELIGIBLE."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def _ineligible_case_with_unpaid_fee():
    """A case ruled INELIGIBLE on academics whose 12345-cent fee is untouched."""
    return fx.setup_case_ready_for_evaluation(
        clock="2026-09-10T09:00:00Z",
        student_overrides={"full_name": "Dev Sharma", "birth_date": "2009-04-01",
                           "grade_level": 11, "residency_verified": True,
                           "residency_verified_on": "2026-08-10"},
        academic_overrides={"gpa_prior_period": 1.500, "gpa_current_period": 1.500,
                            "credits_prior_period": 3, "credits_current_period": 3},
    )


def test_appeal_cycle_returns_the_case_to_ineligible_and_counts_both_rounds(api):
    """PRD §3.6: "The athletic director may attach an `appeal_note`, and the case
    moves `INELIGIBLE → UNDER_APPEAL` with `appeal_count` incremented by 1."
    PRD §3.4: "The three starting states behave identically: `INTAKE →
    PROVISIONAL_ELIGIBLE`, `UNDER_REVIEW → PROVISIONAL_ELIGIBLE`, and `UNDER_APPEAL →
    PROVISIONAL_ELIGIBLE` carry the same guards and the same writes, as do `INTAKE →
    INELIGIBLE`, `UNDER_REVIEW → INELIGIBLE`, and `UNDER_APPEAL → INELIGIBLE`."
    PRD §3.6: "Because a re-evaluation from `UNDER_APPEAL` may itself land on
    `INELIGIBLE`, the pair `INELIGIBLE → UNDER_APPEAL → INELIGIBLE` is a real cycle,
    and the appeal cap is the only thing that terminates it."

    Design: Difficulty/non_linear_state_machine/eligibility_case_appeal_cycle_runs_beside_an_independent_fee_axis
    """
    ctx = _ineligible_case_with_unpaid_fee()
    first = fx.evaluate_case(ctx["case"]["id"])
    assert first["status"] == "INELIGIBLE"

    appealed = validate_success(
        api.appeal_case(ctx["case"]["id"],
                        {"appeal_note": "grading-period correction pending"},
                        fx.make_director_headers(ctx["school"]["id"])),
        200,
    )
    reruled = validate_success(api.evaluate_case(ctx["case"]["id"], fx.REVIEWER), 200)

    assert appealed["status"] == "UNDER_APPEAL"
    assert appealed["appeal_count"] == 1
    assert reruled["status"] == "INELIGIBLE"
    assert reruled["ineligibility_reason"] == "ACADEMIC_GPA"
    assert reruled["appeal_count"] == 1
    assert reruled["evaluation_count"] == 2
    assert reruled["effective_gpa"] == pytest.approx(1.500, abs=0.0005)


def test_fee_axis_advances_while_the_status_axis_loops_untouched(api):
    """PRD §3.5: "Money movement never changes `status`, and an eligibility ruling
    never changes `fee_status`."
    PRD §3.5: "A payment that is strictly less than the outstanding balance moves
    the money axis `ASSESSED → PARTIALLY_PAID`."
    PRD §3.5: "Every one of those four payment edges does the same three things: it
    increases `fee_paid_cents` by the amount received, recomputes
    `fee_outstanding_cents` (which lands at exactly 0 on the three settling edges),
    and increases the school's `fee_collected_cents` by the same amount received."

    Design: Difficulty/non_linear_state_machine/eligibility_case_appeal_cycle_runs_beside_an_independent_fee_axis
    """
    ctx = _ineligible_case_with_unpaid_fee()
    fx.evaluate_case(ctx["case"]["id"])

    paid = validate_success(
        api.create_fee_payment(ctx["case"]["id"], {"amount_cents": 5000},
                               fx.make_director_headers(ctx["school"]["id"])),
        200,
    )
    assert paid["fee_status"] == "PARTIALLY_PAID"
    assert paid["status"] == "INELIGIBLE", "a payment must not move the eligibility axis"

    fx.get_success_data(
        api.appeal_case(ctx["case"]["id"], {"appeal_note": "second opinion"},
                        fx.make_director_headers(ctx["school"]["id"]))
    )
    final = validate_success(api.evaluate_case(ctx["case"]["id"], fx.REVIEWER), 200)

    assert final["fee_status"] == "PARTIALLY_PAID", "a ruling must not move the money axis"
    assert final["fee_paid_cents"] == 5000
    assert final["fee_outstanding_cents"] == 7345
    assert fx.read_school(ctx["school"]["id"])["fee_collected_cents"] == 5000


def test_activation_of_an_ineligible_case_reports_the_state_gate(api):
    """PRD §3.6: "A case that is not standing at `PROVISIONAL_ELIGIBLE` is turned
    away first, with `ERR_CASE_NOT_ACTIVATABLE`."
    PRD §2.6: "A practical consequence worth stating: on case activation, a case
    that is not `PROVISIONAL_ELIGIBLE` reports `ERR_CASE_NOT_ACTIVATABLE` before the
    sanction, coach-credential, medical-hold and fee gates are ever consulted, and
    among those four, sanction is reported first, then the coaching gap, then the
    medical hold, then the outstanding fee."

    Design: Difficulty/priority_pair_validation_conflict/activate_state_gate_outranks_the_outstanding_fee_gate
    """
    ctx = fx.setup_case_ready_for_evaluation(
        clock="2026-09-10T09:00:00Z",
        student_overrides={"full_name": "Fay Oduya", "birth_date": "2009-08-09",
                           "grade_level": 11, "residency_verified": True,
                           "residency_verified_on": "2026-08-10"},
        academic_overrides={"gpa_prior_period": 1.400, "gpa_current_period": 3.900,
                            "credits_prior_period": 3, "credits_current_period": 3},
        season_overrides={"required_officials": 1},
    )
    fx.create_cleared_head_coach(ctx["school"]["id"], sport="FOOTBALL")
    ruled = fx.evaluate_case(ctx["case"]["id"])
    assert ruled["status"] == "INELIGIBLE"
    assert ruled["fee_outstanding_cents"] == 12345

    response = api.activate_case(ctx["case"]["id"], fx.REVIEWER)

    validate_error(response, ApiErrorId.ERR_CASE_NOT_ACTIVATABLE.value, 409)


def test_activation_state_gate_pre_empts_the_outstanding_fee_gate(api):
    """PRD §2.6: "The case's `fee_outstanding_cents` is zero — otherwise
    `ERR_FEE_OUTSTANDING` (409)."
    PRD §2.6: "A practical consequence worth stating: on case activation, a case
    that is not `PROVISIONAL_ELIGIBLE` reports `ERR_CASE_NOT_ACTIVATABLE` before the
    sanction, coach-credential, medical-hold and fee gates are ever consulted, and
    among those four, sanction is reported first, then the coaching gap, then the
    medical hold, then the outstanding fee."

    Design: Difficulty/priority_pair_validation_conflict/activate_state_gate_outranks_the_outstanding_fee_gate
    """
    ctx = fx.setup_case_ready_for_evaluation(
        clock="2026-09-10T09:00:00Z",
        student_overrides={"full_name": "Fay Oduya", "birth_date": "2009-08-09",
                           "grade_level": 11, "residency_verified": True,
                           "residency_verified_on": "2026-08-10"},
        academic_overrides={"gpa_prior_period": 1.400, "gpa_current_period": 3.900,
                            "credits_prior_period": 3, "credits_current_period": 3},
        season_overrides={"required_officials": 1},
    )
    fx.create_cleared_head_coach(ctx["school"]["id"], sport="FOOTBALL")
    fx.evaluate_case(ctx["case"]["id"])

    response = api.activate_case(ctx["case"]["id"], fx.REVIEWER)

    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_FEE_OUTSTANDING.value, (
        "the state gate is consulted before the fee gate"
    )
    after = fx.read_case(ctx["case"]["id"])
    assert after["status"] == "INELIGIBLE"
    assert after["fee_outstanding_cents"] == 12345
    assert after["activated_at"] is None


def _case_awaiting_its_head_coach():
    """PROVISIONAL_ELIGIBLE, fee settled, but the head-coach screening is pending."""
    ctx = fx.setup_case_ready_for_evaluation(
        clock="2026-09-10T09:00:00Z",
        season_overrides={"required_officials": 1},
        student_overrides={"full_name": "Hana Ito", "birth_date": "2009-09-15",
                           "grade_level": 11, "residency_verified": True,
                           "residency_verified_on": "2026-08-10"},
        academic_overrides={"gpa_prior_period": 3.200, "gpa_current_period": 3.400,
                            "credits_prior_period": 3, "credits_current_period": 3},
    )
    ctx["credential"] = fx.create_credential(
        ctx["school"]["id"], sport="FOOTBALL", role_title="HEAD_COACH",
        certification_expires_on="2027-06-30",
    )
    ctx["case"] = fx.evaluate_case(ctx["case"]["id"])
    fx.pay_fee(ctx["case"]["id"], ctx["school"]["id"], 12345)
    return ctx


def test_activation_is_refused_while_the_head_coach_screening_is_pending(api):
    """PRD §3.6: "The school must hold at least one coaching credential whose
    `sport` equals the season's `sport`, whose `role_title` is `HEAD_COACH`, whose
    status is `CLEARED`, and whose `certification_expires_on` falls strictly after
    the logical clock's UTC date; if it holds none, the answer is
    `ERR_COACH_NOT_CREDENTIALED`."
    PRD §3.2: "Every new credential begins at `BACKGROUND_PENDING` with no
    `background_check_completed_on` recorded."

    Design: Difficulty/cross_entity_state_dependency/case_activation_is_gated_on_the_schools_head_coach_credential_state
    """
    ctx = _case_awaiting_its_head_coach()
    assert ctx["case"]["status"] == "PROVISIONAL_ELIGIBLE"

    response = api.activate_case(ctx["case"]["id"], fx.REVIEWER)

    validate_error(response, ApiErrorId.ERR_COACH_NOT_CREDENTIALED.value, 409)
    assert fx.read_case(ctx["case"]["id"])["status"] == "PROVISIONAL_ELIGIBLE"


def test_clearing_the_head_coach_lets_the_identical_activation_succeed(api):
    """PRD §3.2: "A `result` of `CLEARED` on a pending credential moves it
    `BACKGROUND_PENDING → CLEARED`, stamps `background_check_completed_on` with the
    logical clock's UTC date, and — when the `role_title` is `HEAD_COACH` — removes
    that `sport` from the school's `credential_gap_sports` and increments the
    school's `version` by 1."
    PRD §3.6: "When all four clear, the case moves `PROVISIONAL_ELIGIBLE →
    ELIGIBLE` and `activated_at` is stamped with the logical clock instant."

    Design: Difficulty/cross_entity_state_dependency/case_activation_is_gated_on_the_schools_head_coach_credential_state
    """
    ctx = _case_awaiting_its_head_coach()
    api.activate_case(ctx["case"]["id"], fx.REVIEWER)

    cleared = fx.clear_credential(ctx["credential"]["id"],
                                  background_check_reference="BGC-90011")
    activated = validate_success(api.activate_case(ctx["case"]["id"], fx.REVIEWER), 200)

    assert cleared["status"] == "CLEARED"
    assert "FOOTBALL" not in fx.read_school(ctx["school"]["id"])["credential_gap_sports"]
    assert activated["status"] == "ELIGIBLE"
    assert activated["activated_at"] is not None
    assert activated["fee_status"] == "PAID"
    assert activated["fee_outstanding_cents"] == 0


def test_case_creation_against_an_unknown_season_is_not_found(api):
    """PRD §2.6: "Every foreign reference supplied in a request body resolves to an
    existing row — otherwise 404 with `ERR_SCHOOL_NOT_FOUND`,
    `ERR_STUDENT_NOT_FOUND`, `ERR_SEASON_NOT_FOUND`, `ERR_CONTEST_NOT_FOUND`, or
    `ERR_OFFICIAL_NOT_FOUND` as appropriate."

    Design: Corner/entities/eligibility_case_creation_against_an_unknown_season_returns_season_not_found
    """
    school = fx.create_school(name="North High")
    student = fx.create_student(school["id"], full_name="Lia Moss",
                                birth_date="2009-05-14", grade_level=10)
    headers = fx.make_director_headers(school["id"])

    response = api.create_eligibility_case(
        {"student_id": student["id"], "sport_season_id": NON_EXISTENT_UUID}, headers
    )

    validate_error(response, ApiErrorId.ERR_SEASON_NOT_FOUND.value, 404)
    rows, _meta = validate_paginated(
        api.list_eligibility_cases(headers, {"student_id": student["id"]})
    )
    assert rows == [], "a rejected intake must not mint an EligibilityCase row"


def test_second_case_for_the_same_athlete_and_season_is_a_duplicate(api):
    """PRD §3.3: "At most one case may exist for a given athlete-and-season pair; a
    second attempt is refused with `ERR_DUPLICATE_ELIGIBILITY_CASE`."

    Design: Corner/validations/second_eligibility_case_for_the_same_student_and_season_is_rejected
    """
    school = fx.create_school(name="North High", fee_cap_cents=20000)
    season = fx.create_season(sport_tier="TIER_A")
    student = fx.create_student(school["id"], full_name="Eve Salas",
                                birth_date="2009-05-14", grade_level=10)
    headers = fx.make_director_headers(school["id"])
    fx.create_case(school["id"], student["id"], season["id"])

    response = api.create_eligibility_case(
        {"student_id": student["id"], "sport_season_id": season["id"]}, headers
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_ELIGIBILITY_CASE.value, 409)
    rows, _meta = validate_paginated(
        api.list_eligibility_cases(headers, {"student_id": student["id"]})
    )
    assert len(rows) == 1


def test_third_appeal_hits_the_appeal_cap(api):
    """PRD §3.6: "Appeals are capped at two per case: an appeal attempted on a case
    whose `appeal_count` has already reached 2 is refused with
    `ERR_APPEAL_LIMIT_REACHED`."

    Design: Corner/errors/third_appeal_returns_appeal_limit_reached
    """
    ctx = fx.setup_case_ready_for_evaluation(
        clock="2026-09-10T09:00:00Z",
        student_overrides={"full_name": "Hal Berger", "residency_verified": True,
                           "residency_verified_on": "2026-08-10"},
        academic_overrides={"gpa_prior_period": 1.100, "gpa_current_period": 1.100,
                            "credits_prior_period": 3, "credits_current_period": 3},
    )
    headers = fx.make_director_headers(ctx["school"]["id"])
    fx.evaluate_case(ctx["case"]["id"])
    for note in ("first appeal", "second appeal"):
        fx.get_success_data(api.appeal_case(ctx["case"]["id"], {"appeal_note": note},
                                            headers))
        fx.evaluate_case(ctx["case"]["id"])

    response = api.appeal_case(ctx["case"]["id"], {"appeal_note": "third appeal"},
                               headers)

    validate_error(response, ApiErrorId.ERR_APPEAL_LIMIT_REACHED.value, 409)
    after = fx.read_case(ctx["case"]["id"])
    assert after["appeal_count"] == 2
    assert after["evaluation_count"] == 3
    assert after["status"] == "INELIGIBLE"
