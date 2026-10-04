"""Membership-day and FTE computations (PRD §3.4), including the dual variants."""
import pytest

from test_helpers import (
    create_active_enrollment,
    create_enrollment_payload,
    create_student,
    create_student_with_enrollment,
    get_enrollment,
    setup_base,
    validate_success,
    withdraw_enrollment,
)


def test_membership_days_full_year_and_mid_year_entry(api, registrar_headers):
    """PRD §3.4: "The current segment's effective start is the later of the
    enrollment's `entry_date` and the year's `start_date`; its effective end is the
    earlier of the `exit_date` — or the year's `end_date` while no exit exists — and
    the year's `end_date`. The segment contributes the whole calendar days in that
    half-open span, never fewer than zero, and `membership_days` is the sum of
    `prior_segment_days` and those current-segment days."

    Design: Corner/calculations/membership_days_full_year_and_mid_year_entry
    """
    district, spec, year = setup_base()
    student_a, enrollment_a = create_student_with_enrollment(
        district["id"], year["id"])
    student_b = create_student(
        district["id"], student_number="S002", first_name="Bo", last_name="Reyes",
        birth_date="2013-09-09T00:00:00Z", entry_grade_level="KG")
    enrollment_b = create_active_enrollment(
        student_b["id"], year["id"], grade_level="KG",
        entry_date="2026-11-01T00:00:00Z")

    fetched_a = validate_success(api.get_enrollment(enrollment_a["id"], registrar_headers), 200)
    fetched_b = validate_success(api.get_enrollment(enrollment_b["id"], registrar_headers), 200)
    # Half-open [2026-08-01, 2027-06-01) is 304 whole calendar days.
    assert fetched_a["membership_days"] == 304
    # Half-open [2026-11-01, 2027-06-01) is 212 whole calendar days.
    assert fetched_b["membership_days"] == 212


def test_fte_count_date_exit_exactly_on_count_date_is_ineligible(api, registrar_headers):
    """PRD §3.4: "when the enrollment spans the year's `count_date` — `entry_date` on
    or before the count date, and either no `exit_date` or an `exit_date` strictly
    after it — the value is `program_weight` capped at 1.0 and rounded half-up to
    three decimals, so that same 100-day enrollment spanning the count date yields
    1.000; when the enrollment does not span the count date, the value is 0.0."

    Design: Corner/calculations/fte_count_date_exit_exactly_on_count_date_is_ineligible
    """
    district, spec, year = setup_base()
    student_a, enrollment_a = create_student_with_enrollment(
        district["id"], year["id"])
    student_b, enrollment_b = create_student_with_enrollment(
        district["id"], year["id"],
        student_overrides={"student_number": "S002", "first_name": "Bo",
                           "last_name": "Reyes", "birth_date": "2013-09-09T00:00:00Z",
                           "entry_grade_level": "KG"},
        enrollment_overrides={"grade_level": "KG"},
    )

    # Exit exactly on the count date 2026-10-01: NOT strictly after it.
    withdraw_enrollment(enrollment_a["id"], "2026-10-01T00:00:00Z")
    # Exit one day later spans the count date.
    withdraw_enrollment(enrollment_b["id"], "2026-10-02T00:00:00Z")

    fetched_a = validate_success(api.get_enrollment(enrollment_a["id"], registrar_headers), 200)
    fetched_b = validate_success(api.get_enrollment(enrollment_b["id"], registrar_headers), 200)
    assert fetched_a["fte_count_date"] == pytest.approx(0.0, abs=1e-9), \
        "exit_date == count_date is not strictly after it, so the snapshot is 0.0"
    assert fetched_b["fte_count_date"] == pytest.approx(1.0, abs=1e-9), \
        "exit_date 2026-10-02 > count_date 2026-10-01, so the snapshot is weight 1.0"


def test_fte_precision_round_half_up_three_decimals(api, registrar_headers):
    """PRD §2.6: "`fte_adm` and `fte_count_date` are rounded half-up to exactly three
    decimal places, and neither can exceed the cap of 1.0."
    PRD §3.4: "`fte_adm` prorates membership: `membership_days` divided by the year's
    `instructional_days`, multiplied by `program_weight`, capped at 1.0, and rounded
    half-up to three decimal places".

    Design: Corner/calculations/fte_precision_round_half_up_three_decimals
    """
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(
        district["id"], year["id"],
        enrollment_overrides={"program_code": "GT"},
    )
    withdraw_enrollment(enrollment["id"], "2026-09-15T00:00:00Z")

    fetched = validate_success(api.get_enrollment(enrollment["id"], registrar_headers), 200)
    assert fetched["program_weight"] == pytest.approx(1.25, abs=1e-9)
    # Half-open [2026-08-01, 2026-09-15) is 45 days.
    assert fetched["membership_days"] == 45
    # 45/180 * 1.25 = 0.3125 exactly; round-half-up to three decimals is 0.313
    # (round-half-even would give 0.312).
    assert fetched["fte_adm"] == pytest.approx(0.313, abs=1e-9)


def _setup_hundred_day_withdrawn_enrollment(api, registrar_headers):
    """Base + one enrollment withdrawn with exit 2026-11-09 (100-day membership
    spanning the 2026-10-01 count date). Returns the enrollment id."""
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(district["id"], year["id"])
    withdraw_enrollment(enrollment["id"], "2026-11-09T00:00:00Z")
    return enrollment["id"]


def test_fte_adm_prorates_membership_for_hundred_day_enrollment(api, registrar_headers):
    """PRD §3.4: "`fte_adm` prorates membership: `membership_days` divided by the
    year's `instructional_days`, multiplied by `program_weight`, capped at 1.0, and
    rounded half-up to three decimal places — a 100-day membership in a 180-day year
    with weight 1.0 yields 0.556."

    Design: Difficulty/dual_variant_calc/fte_adm_vs_count_date_divergence_on_enrollment
    """
    enrollment_id = _setup_hundred_day_withdrawn_enrollment(api, registrar_headers)
    enrollment = validate_success(api.get_enrollment(enrollment_id, registrar_headers), 200)
    assert enrollment["membership_days"] == 100
    assert enrollment["fte_adm"] == pytest.approx(0.556, abs=1e-9)


def test_fte_count_date_snapshot_diverges_from_adm_variant(api, registrar_headers):
    """PRD §3.4: "`fte_count_date` is a binary snapshot: when the enrollment spans
    the year's `count_date` — `entry_date` on or before the count date, and either no
    `exit_date` or an `exit_date` strictly after it — the value is `program_weight`
    capped at 1.0 and rounded half-up to three decimals, so that same 100-day
    enrollment spanning the count date yields 1.000".

    Design: Difficulty/dual_variant_calc/fte_adm_vs_count_date_divergence_on_enrollment
    """
    enrollment_id = _setup_hundred_day_withdrawn_enrollment(api, registrar_headers)
    enrollment = validate_success(api.get_enrollment(enrollment_id, registrar_headers), 200)
    # Entry 2026-08-01 <= count date 2026-10-01 and exit 2026-11-09 > count date.
    assert enrollment["fte_count_date"] == pytest.approx(1.0, abs=1e-9)
    assert enrollment["fte_adm"] != pytest.approx(
        enrollment["fte_count_date"], abs=1e-9), \
        "the ADM and COUNT_DATE variants must diverge on identical data"


def test_fte_weight_cap_interaction_el_weighted_clips_at_cap(api, registrar_headers):
    """PRD §3.4: "`fte_adm` prorates membership: `membership_days` divided by the
    year's `instructional_days`, multiplied by `program_weight`, capped at 1.0, and
    rounded half-up to three decimal places".
    PRD §3.4: "a supplied `program_code` is looked up in the spec's
    `program_code_map`, populating the computed `state_program_code` and setting
    `program_weight` to the map's `weight_factor`."

    Design: Difficulty/combinatorial_formula/fte_weight_cap_interaction_three_inputs
    """
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(
        district["id"], year["id"],
        enrollment_overrides={"program_code": "EL"},
    )
    fetched = validate_success(api.get_enrollment(enrollment["id"], registrar_headers), 200)
    assert fetched["program_weight"] == pytest.approx(1.2, abs=1e-9)
    assert fetched["membership_days"] == 304
    # min(1.0, 304/180 * 1.2) = min(1.0, 2.0266...) clips at the cap.
    assert fetched["fte_adm"] == pytest.approx(1.0, abs=1e-9)


def test_fte_weight_cap_interaction_hdk_weighted_below_cap(api, registrar_headers):
    """PRD §3.4: "`fte_adm` prorates membership: `membership_days` divided by the
    year's `instructional_days`, multiplied by `program_weight`, capped at 1.0, and
    rounded half-up to three decimal places".
    PRD §3.4: "a supplied `program_code` is looked up in the spec's
    `program_code_map`, populating the computed `state_program_code` and setting
    `program_weight` to the map's `weight_factor`."

    Design: Difficulty/combinatorial_formula/fte_weight_cap_interaction_three_inputs
    """
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(
        district["id"], year["id"],
        enrollment_overrides={"program_code": "HDK", "grade_level": "KG"},
        student_overrides={"entry_grade_level": "KG"},
    )
    fetched = validate_success(api.get_enrollment(enrollment["id"], registrar_headers), 200)
    assert fetched["program_weight"] == pytest.approx(0.5, abs=1e-9)
    assert fetched["membership_days"] == 304
    # round_half_up(304/180 * 0.5, 3) = round_half_up(0.84444..., 3) = 0.844.
    assert fetched["fte_adm"] == pytest.approx(0.844, abs=1e-9)
