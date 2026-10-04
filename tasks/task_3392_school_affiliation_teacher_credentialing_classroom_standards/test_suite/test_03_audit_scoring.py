"""Classroom audit scoring: immutability of the audit record, the ratio,
work-period, multi-age and materials checks at their exact boundaries, and
the verdict aggregation with its fixed failed_checks ordering.
"""

import pytest

from test_helpers import (
    CONSULTANT_USER_ID,
    assert_audit_verdict_consistency,
    assert_classroom_audit,
    create_active_catalog,
    create_classroom,
    create_classroom_audit_payload,
    create_school,
    expected_materials_score,
    file_classroom_audit,
    make_consultant_headers,
    reset_clock,
    validate_success,
)

FULL_MATERIALS = [{"domain": "PRACTICAL_LIFE", "required_count": 10, "present_count": 10}]
ROUNDING_GROUPS = [
    {"domain": "PRACTICAL_LIFE", "required_count": 9, "present_count": 8},
    {"domain": "SENSORIAL", "required_count": 9, "present_count": 8},
    {"domain": "LANGUAGE", "required_count": 9, "present_count": 8},
    {"domain": "MATH", "required_count": 1, "present_count": 1},
]


def _school_with_room():
    create_active_catalog()
    school = create_school()
    room = create_classroom(school["id"])
    return school, room


def test_audit_entity_is_immutable_without_version_field(api):
    """PRD section 2.4: "A `ClassroomAudit` and a `CECreditEntry` each carry
    only `id` and `created_at`; both `updated_at` and `version` are absent from
    them, because an audit is immutable once filed and a credit entry's only
    mutation is the void transition." PRD section 2.6: "Each `ClassroomAudit`
    records, in its `catalog_id`, the edition it was scored against — the
    school's pinned edition when one is set, otherwise the catalog that is
    `ACTIVE` at audit time."

    Design: Corner/entities/audit_entity_is_immutable_without_version_field
    """
    reset_clock()
    catalog = create_active_catalog()
    school = create_school(name="Imm School", display_name="Imm Schoolhouse")
    room = create_classroom(school["id"], name="C1", enrolled_student_count=20)

    resp = api.create_classroom_audit(
        create_classroom_audit_payload(
            room["id"],
            students_present=20,
            adults_present=2,
            observed_uninterrupted_minutes=180,
            materials_groups=FULL_MATERIALS,
        ),
        headers=make_consultant_headers(CONSULTANT_USER_ID),
    )
    data = validate_success(resp, 201)
    assert_classroom_audit(data)
    assert "version" not in data, "audit must not carry version"
    assert "updated_at" not in data, "audit must not carry updated_at"
    assert data["catalog_id"] == catalog["id"]
    assert data["verdict"] == "COMPLIANT"
    assert data["failed_checks"] == []


def test_work_period_exact_minimum_passes(api):
    """PRD section 3.3: "The work-period check sets `work_period_pass` when
    `observed_uninterrupted_minutes` is at least the catalog's
    `min_uninterrupted_work_minutes_by_level` minimum — sitting exactly on the
    minimum passes."

    Design: Corner/calculations/work_period_exact_minimum_passes_one_minute_under_fails
    """
    reset_clock()
    _, room = _school_with_room()
    audit = file_classroom_audit(
        room["id"],
        students_present=20,
        adults_present=2,
        observed_uninterrupted_minutes=180,
        materials_groups=FULL_MATERIALS,
    )
    assert audit["work_period_pass"] is True
    assert audit["verdict"] == "COMPLIANT"
    assert_audit_verdict_consistency(audit)


def test_work_period_one_minute_under_fails(api):
    """PRD section 3.3: "The work-period check sets `work_period_pass` when
    `observed_uninterrupted_minutes` is at least the catalog's
    `min_uninterrupted_work_minutes_by_level` minimum — sitting exactly on the
    minimum passes." PRD section 3.3: "`failed_checks` names the failed
    components drawn from `RATIO`, `WORK_PERIOD`, `MATERIALS`, `MULTI_AGE`,
    kept in that fixed order and empty for a compliant audit."

    Design: Corner/calculations/work_period_exact_minimum_passes_one_minute_under_fails
    """
    reset_clock()
    _, room = _school_with_room()
    audit = file_classroom_audit(
        room["id"],
        students_present=20,
        adults_present=2,
        observed_uninterrupted_minutes=179,
        materials_groups=FULL_MATERIALS,
    )
    assert audit["work_period_pass"] is False
    assert audit["verdict"] == "NONCOMPLIANT"
    assert audit["failed_checks"] == ["WORK_PERIOD"]


def test_multi_age_span_exact_minimum_passes_shorter_fails(api):
    """PRD section 3.3: "The multi-age check sets `multi_age_pass` when the
    classroom's `declared_age_span_years` is at least the catalog's
    `min_multi_age_span_years_by_level` entry."

    Design: Corner/calculations/multi_age_span_exact_minimum_passes_shorter_fails
    """
    reset_clock()
    create_active_catalog()
    school = create_school(name="G School", display_name="G Schoolhouse")
    room3 = create_classroom(school["id"], name="C3", declared_age_span_years=3)
    room2 = create_classroom(school["id"], name="C2", declared_age_span_years=2)

    audit3 = file_classroom_audit(
        room3["id"], students_present=20, adults_present=2, materials_groups=FULL_MATERIALS
    )
    audit2 = file_classroom_audit(
        room2["id"], students_present=20, adults_present=2, materials_groups=FULL_MATERIALS
    )
    assert audit3["multi_age_pass"] is True
    assert audit3["verdict"] == "COMPLIANT"
    assert audit2["multi_age_pass"] is False
    assert audit2["verdict"] == "NONCOMPLIANT"
    assert audit2["failed_checks"] == ["MULTI_AGE"]


def test_ratio_exactly_at_cap_passes(api):
    """PRD section 3.3: "The ratio check divides `students_present` by
    `adults_present`, rounds half-up to 2 decimal places into
    `ratio_students_per_adult`, and sets `ratio_pass` when that rounded value is
    at most the catalog's `max_students_per_adult_by_level` cap — equality
    passes."

    Design: Difficulty/boundary_precision_check/ratio_exactly_at_cap_passes_one_student_over_fails
    """
    reset_clock()
    _, room = _school_with_room()
    audit = file_classroom_audit(
        room["id"],
        students_present=30,
        adults_present=2,
        observed_uninterrupted_minutes=180,
        materials_groups=[
            {"domain": "PRACTICAL_LIFE", "required_count": 10, "present_count": 9},
            {"domain": "SENSORIAL", "required_count": 10, "present_count": 9},
        ],
    )
    assert audit["ratio_students_per_adult"] == pytest.approx(15.0)
    assert audit["ratio_pass"] is True, "15.00 equals the cap and passes"
    assert audit["verdict"] == "COMPLIANT"


def test_ratio_one_student_over_cap_fails(api):
    """PRD section 3.3: "sets `ratio_pass` when that rounded value is at most
    the catalog's `max_students_per_adult_by_level` cap — equality passes." PRD
    section 3.3: "The audit's `verdict` is `COMPLIANT` exactly when all four
    pass flags hold, and `NONCOMPLIANT` otherwise".

    Design: Difficulty/boundary_precision_check/ratio_exactly_at_cap_passes_one_student_over_fails
    """
    reset_clock()
    _, room = _school_with_room()
    audit = file_classroom_audit(
        room["id"],
        students_present=31,
        adults_present=2,
        observed_uninterrupted_minutes=180,
        materials_groups=[
            {"domain": "PRACTICAL_LIFE", "required_count": 10, "present_count": 9},
            {"domain": "SENSORIAL", "required_count": 10, "present_count": 9},
        ],
    )
    assert audit["ratio_students_per_adult"] == pytest.approx(15.5)
    assert audit["ratio_pass"] is False
    assert audit["verdict"] == "NONCOMPLIANT"
    assert audit["failed_checks"] == ["RATIO"]


def test_materials_per_group_rounding_order_scores_09175(api):
    """PRD section 3.3: "with groups of 8/9, 8/9, 8/9 and 1/1, the pinned
    per-group-first order yields a mean of 0.9175 and passes a 0.90 threshold,
    whereas the sum of 25 over 28 yields 0.8929 and would fail — the pinned
    order governs."

    Design: Difficulty/combinatorial_formula/materials_score_per_group_rounding_order
    """
    reset_clock()
    _, room = _school_with_room()
    audit = file_classroom_audit(
        room["id"],
        students_present=30,
        adults_present=2,
        observed_uninterrupted_minutes=180,
        materials_groups=ROUNDING_GROUPS,
    )
    assert audit["materials_score"] == pytest.approx(0.9175)
    assert audit["materials_score"] == pytest.approx(
        float(expected_materials_score(ROUNDING_GROUPS))
    )
    assert audit["materials_pass"] is True


def test_materials_pinned_order_flips_verdict_to_compliant(api):
    """PRD section 3.3: "Summing first and rounding once is forbidden" and "the
    pinned per-group-first order yields a mean of 0.9175 and passes a 0.90
    threshold". PRD section 3.3: "The audit's `verdict` is `COMPLIANT` exactly
    when all four pass flags hold, and `NONCOMPLIANT` otherwise".

    Design: Difficulty/combinatorial_formula/materials_score_per_group_rounding_order
    """
    reset_clock()
    _, room = _school_with_room()
    audit = file_classroom_audit(
        room["id"],
        students_present=30,
        adults_present=2,
        observed_uninterrupted_minutes=180,
        materials_groups=ROUNDING_GROUPS,
    )
    assert audit["ratio_pass"] is True
    assert audit["work_period_pass"] is True
    assert audit["multi_age_pass"] is True
    assert audit["materials_pass"] is True
    assert audit["verdict"] == "COMPLIANT"
    assert audit["failed_checks"] == []
    assert_audit_verdict_consistency(audit)
