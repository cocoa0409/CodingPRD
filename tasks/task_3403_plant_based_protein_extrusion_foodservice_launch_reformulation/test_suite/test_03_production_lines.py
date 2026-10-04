"""Extrusion line registration, co-manufacturer equivalence audits, the
parallel certification/operational dimensions, and monthly capacity buckets
(PRD section 3.3)."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS,
    validate_error, validate_success,
    create_production_line_payload, certification_audit_payload,
    create_production_run_payload,
    create_owned_line, create_coman_line, post_certification_audit,
    certify_coman_line, move_line_operational,
    create_active_product_with_label, schedule_run,
    current_line_version, fetch_line,
    assert_production_line,
)

_PLANT = TEST_USERS["plant_manager_headers"]
_QM = TEST_USERS["quality_manager_headers"]


def test_line_create_initial_state_depends_on_site_type(api):
    """PRD section 3.3: "an `OWNED` line opens as `CERTIFIED`, while a
    `CO_MAN` line opens as `PENDING` and must earn certification through
    quality-equivalence audits against owned-plant reference metrics", with
    `reserved_capacity_kg` "starting from zero at registration" and the
    operational cycle opening at IDLE.

    Design: Corner/entities/cn_ent_line_create_conditional_initial
    """
    resp_owned = api.create_production_line(
        create_production_line_payload(site_type="OWNED",
                                       line_code="LINE-CI-O",
                                       supported_isolate_types=["PEA"]),
        _PLANT)
    owned = validate_success(resp_owned, 201)
    assert_production_line(owned)
    assert owned["certification_status"] == "CERTIFIED"
    assert owned["operational_status"] == "IDLE"
    assert owned["reserved_capacity_kg"] == 0
    resp_coman = api.create_production_line(
        create_production_line_payload(
            site_type="CO_MAN", line_code="LINE-CI-C",
            coman_partner_name="CoPack Industries",
            monthly_reserved_capacity_kg=5000, hourly_capacity_kg=200,
            supported_isolate_types=["PEA"]),
        _PLANT)
    coman = validate_success(resp_coman, 201)
    assert coman["certification_status"] == "PENDING"
    assert coman["operational_status"] == "IDLE"
    assert coman["coman_partner_name"] == "CoPack Industries"
    assert coman["monthly_reserved_capacity_kg"] == 5000


def test_coman_field_pairing_enforced_both_directions(api):
    """PRD section 3.3: "Co-manufactured capacity carries two contract fields
    — `coman_partner_name` and `monthly_reserved_capacity_kg` — that are
    required exactly when the site type is `CO_MAN` and forbidden on `OWNED`
    lines; getting the pairing wrong is `ERR_INVALID_REQUEST`."

    Design: Corner/entities/cn_ent_line_coman_missing_capacity_returns_invalid_request
    """
    resp_missing = api.create_production_line(
        create_production_line_payload(site_type="CO_MAN",
                                       line_code="LINE-BAD-1",
                                       hourly_capacity_kg=200,
                                       supported_isolate_types=["PEA"]),
        _PLANT)
    validate_error(resp_missing, ApiErrorId.ERR_INVALID_REQUEST)
    resp_forbidden = api.create_production_line(
        create_production_line_payload(site_type="OWNED",
                                       line_code="LINE-BAD-2",
                                       hourly_capacity_kg=200,
                                       supported_isolate_types=["PEA"],
                                       coman_partner_name="CoPack Industries"),
        _PLANT)
    validate_error(resp_forbidden, ApiErrorId.ERR_INVALID_REQUEST)


def test_passing_audit_certifies_without_touching_operations(api):
    """PRD section 3.3: "Independently of certification, each line walks an
    operational cycle" — a passing audit moves the certification dimension
    PENDING -> CERTIFIED while the operational dimension stays put, and a
    later IDLE -> SETUP move leaves certification CERTIFIED.

    Design: Difficulty/non_linear_state_machine/nsm_line_parallel_dimensions
    """
    line = create_coman_line(line_code="LINE-PAR-1",
                             monthly_reserved_capacity_kg=5000,
                             hourly_capacity_kg=200,
                             supported_isolate_types=["PEA"])
    line = post_certification_audit(line["id"], texture_score=90,
                                    moisture_variance_pct=1.0)
    assert line["certification_status"] == "CERTIFIED"
    assert line["operational_status"] == "IDLE"
    line = move_line_operational(line["id"], "SETUP")
    assert line["certification_status"] == "CERTIFIED"
    assert line["operational_status"] == "SETUP"


def test_failing_audit_suspends_certification_only(api):
    """PRD section 3.3: "a failing audit suspends a `CERTIFIED` line" — and
    the audit "applies only to" the certification dimension, so a line sitting
    in SETUP stays in SETUP while certification drops to SUSPENDED.

    Design: Difficulty/non_linear_state_machine/nsm_line_parallel_dimensions
    """
    line = create_coman_line(line_code="LINE-PAR-1",
                             monthly_reserved_capacity_kg=5000,
                             hourly_capacity_kg=200,
                             supported_isolate_types=["PEA"])
    post_certification_audit(line["id"], texture_score=90,
                             moisture_variance_pct=1.0)
    move_line_operational(line["id"], "SETUP")
    line = post_certification_audit(line["id"], texture_score=70,
                                    moisture_variance_pct=1.0)
    assert line["certification_status"] == "SUSPENDED"
    assert line["operational_status"] == "SETUP"


def test_audit_boundary_texture_80_moisture_3_passes(api):
    """PRD section 3.3: "The audit passes when the texture score is at least
    80 and the moisture variance is at most 3.0 percent — both boundaries are
    inclusive, so a texture score of exactly 80 paired with a variance of
    exactly 3.0 passes."

    Design: Difficulty/boundary_precision_check/bpc_texture_80_moisture_30_passes
    """
    line = create_coman_line(line_code="LINE-BP-2",
                             monthly_reserved_capacity_kg=2000,
                             hourly_capacity_kg=200,
                             supported_isolate_types=["PEA"])
    resp = api.create_certification_audit(
        line["id"],
        certification_audit_payload(texture_score=80,
                                    moisture_variance_pct=3.0),
        _QM)
    data = validate_success(resp, 201)
    assert data["certification_status"] == "CERTIFIED"


def test_audit_boundary_scores_are_stored_on_line(api):
    """PRD section 3.3: "Whatever the outcome, the scores are stored as
    `last_audit_texture_score` and `last_audit_moisture_variance_pct`, which
    remain null until the first audit."

    Design: Difficulty/boundary_precision_check/bpc_texture_80_moisture_30_passes
    """
    line = create_coman_line(line_code="LINE-BP-2",
                             monthly_reserved_capacity_kg=2000,
                             hourly_capacity_kg=200,
                             supported_isolate_types=["PEA"])
    assert line["last_audit_texture_score"] is None
    assert line["last_audit_moisture_variance_pct"] is None
    data = validate_success(
        api.create_certification_audit(
            line["id"],
            certification_audit_payload(texture_score=80,
                                        moisture_variance_pct=3.0),
            _QM),
        201)
    assert data["last_audit_texture_score"] == 80
    assert data["last_audit_moisture_variance_pct"] == pytest.approx(3.0)


def test_audit_moisture_3_point_1_suspends_certified_line(api):
    """PRD section 3.3: "the moisture variance is at most 3.0 percent" — 3.1
    exceeds the inclusive maximum even with a perfect texture score, and "a
    failing audit suspends a `CERTIFIED` line".

    Design: Corner/calculations/cn_calc_audit_moisture_31_fails_certified_line
    """
    line = create_coman_line(line_code="LINE-K-16")
    certify_coman_line(line["id"], texture_score=90, moisture_variance_pct=1.0)
    line = post_certification_audit(line["id"], texture_score=95,
                                    moisture_variance_pct=3.1)
    assert line["certification_status"] == "SUSPENDED"
    assert line["last_audit_moisture_variance_pct"] == pytest.approx(3.1)


def test_audit_on_owned_line_is_not_applicable(api):
    """PRD section 3.3: "audits apply only to co-manufactured lines, and
    posting one against an owned line is `ERR_AUDIT_NOT_APPLICABLE`."

    Design: Corner/validations/cn_val_audit_on_owned_line
    """
    line = create_owned_line(line_code="LINE-K-37")
    resp = api.create_certification_audit(
        line["id"],
        certification_audit_payload(texture_score=90,
                                    moisture_variance_pct=1.0),
        _QM)
    validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_APPLICABLE)
    assert fetch_line(line["id"])["certification_status"] == "CERTIFIED"


def test_coman_monthly_capacity_boundary_is_inclusive(api):
    """PRD section 3.3: "the planned kilograms of all of the line's
    `SCHEDULED`, `IN_PROGRESS`, and `COMPLETED` runs whose `scheduled_start`
    falls within the same calendar month as the new run's `scheduled_start`,
    plus the new run's own `planned_quantity_kg`, may not exceed
    `monthly_reserved_capacity_kg`, or the schedule is refused with
    `ERR_CAPACITY_EXCEEDED`." 700 + 300 == 1000 passes; one more kilogram in
    September fails; October opens a fresh bucket.

    Design: Corner/calculations/cn_calc_capacity_exactly_at_cap_passes
    """
    line = create_coman_line(line_code="LINE-K-17",
                             monthly_reserved_capacity_kg=1000,
                             hourly_capacity_kg=200,
                             supported_isolate_types=["PEA"])
    certify_coman_line(line["id"])
    product, label = create_active_product_with_label(
        {"product_code": "PROD-K-17"})
    ctx = {"line": line, "product": product, "label": label}
    schedule_run(ctx, planned_quantity_kg=700,
                 scheduled_start="2026-09-05T08:00:00Z",
                 scheduled_end="2026-09-05T12:00:00Z")
    run_b = schedule_run(ctx, planned_quantity_kg=300,
                         scheduled_start="2026-09-12T08:00:00Z",
                         scheduled_end="2026-09-12T12:00:00Z")
    assert run_b["status"] == "SCHEDULED"
    resp_over = api.create_production_run(
        create_production_run_payload(
            production_line_id=line["id"], product_id=product["id"],
            label_version_id=label["id"],
            expected_line_version=current_line_version(line["id"]),
            planned_quantity_kg=1,
            scheduled_start="2026-09-19T08:00:00Z",
            scheduled_end="2026-09-19T12:00:00Z"),
        _PLANT)
    validate_error(resp_over, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    run_d = schedule_run(ctx, planned_quantity_kg=400,
                         scheduled_start="2026-10-10T08:00:00Z",
                         scheduled_end="2026-10-10T12:00:00Z")
    assert run_d["status"] == "SCHEDULED"
