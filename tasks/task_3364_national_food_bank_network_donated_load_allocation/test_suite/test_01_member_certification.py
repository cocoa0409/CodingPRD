"""Member onboarding, standards audits, and certification posture cascades."""
import pytest

from test_helpers import (
    ADMIN_OPERATOR_ID,
    AUDITOR_OPERATOR_ID,
    ApiErrorId,
    assert_audit,
    assert_member,
    assert_store_program,
    complete_audit,
    create_audit,
    create_certified_member,
    create_member,
    create_member_payload,
    create_store_program,
    make_admin_headers,
    make_auditor_headers,
    schedule_pickup,
    validate_error,
    validate_success,
)


def test_create_member_returns_initial_posture_and_system_fields(api, admin_headers):
    """PRD §3.1: "Registration produces a member whose `certification_status` is
    `PENDING_CERTIFICATION` with a zero `share_balance`, a zero `share_reserved`,
    a zero `audit_score`, a zero `active_bid_count` and a null `last_grant_epoch`."
    PRD §2.4: "`version` (integer): a system-managed counter that begins at 1 and
    is incremented by exactly one on every mutation of the resource, whether the
    mutation came from a direct client request or from one of the cascades
    described in §2.8."

    Design: Corner/entities/member_create_returns_initial_posture_and_system_fields
    """
    res = api.create_member(
        create_member_payload(
            name="Harvest Hope Food Bank", state_code="SC",
            food_insecure_population=180_000,
            storage_capacity_lbs=90_000, refrigerated_capacity_lbs=20_000,
            transport_ability="REGIONAL",
        ),
        admin_headers,
    )
    member = validate_success(res, 201)
    assert_member(member)
    assert member["certification_status"] == "PENDING_CERTIFICATION"
    assert member["share_balance"] == 0
    assert member["share_reserved"] == 0
    assert member["audit_score"] == 0
    assert member["active_bid_count"] == 0
    assert member["last_grant_epoch"] is None
    assert member["version"] == 1
    assert member["id"] and member["created_at"] and member["updated_at"]


def test_audit_score_out_of_range_rejected_and_boundary_100_accepted(api, admin_headers):
    """PRD §3.1: "A score outside that band is rejected as
    `ERR_AUDIT_SCORE_OUT_OF_RANGE` before the audit row is created, and a member
    in `SUSPENDED` posture may not be audited at all."

    Design: Corner/entities/audit_score_above_100_returns_400
    """
    member = create_member(api)

    res = api.create_audit(
        {"member_id": member["id"], "audit_type": "STORAGE",
         "storage_score": 101, "distribution_score": 90, "reporting_score": 90},
        make_admin_headers(ADMIN_OPERATOR_ID),
    )
    validate_error(res, ApiErrorId.ERR_AUDIT_SCORE_OUT_OF_RANGE)

    ok = api.create_audit(
        {"member_id": member["id"], "audit_type": "STORAGE",
         "storage_score": 100, "distribution_score": 90, "reporting_score": 90},
        make_admin_headers(ADMIN_OPERATOR_ID),
    )
    audit = validate_success(ok, 201)
    assert_audit(audit)
    assert audit["audit_status"] == "IN_PROGRESS"
    # STORAGE weights storage 60 / distribution 20 / reporting 20.
    assert audit["weighted_score"] == pytest.approx(96.0, abs=0.001)


def test_comprehensive_audit_weighted_score_rounds_half_up(api, admin_headers):
    """PRD §3.1.1: "A `COMPREHENSIVE` audit weights storage at 40 percent,
    distribution at 30 percent and reporting at 30 percent."
    PRD §3.1.1: "Each component is multiplied by its weight and divided by 100,
    the three terms are added, and the sum is rounded half up to one decimal place."

    Design: Corner/calculations/audit_weighted_score_one_decimal_round_half_up
    """
    member = create_member(api)
    res = api.create_audit(
        {"member_id": member["id"], "audit_type": "COMPREHENSIVE",
         "storage_score": 87, "distribution_score": 80, "reporting_score": 90},
        make_admin_headers(ADMIN_OPERATOR_ID),
    )
    audit = validate_success(res, 201)
    # 87*0.4 + 80*0.3 + 90*0.3 = 85.8
    assert audit["weighted_score"] == pytest.approx(85.8, abs=0.001)

    completed = validate_success(
        api.complete_audit(audit["id"], make_auditor_headers(AUDITOR_OPERATOR_ID)), 200
    )
    assert completed["audit_status"] == "PASSED"

    member_after = validate_success(api.get_member(member["id"], admin_headers), 200)
    # audit_score is the floor of the completed audit's weighted score.
    assert member_after["audit_score"] == 85


def test_failed_audit_sets_weighted_score_and_member_audit_score_floor(api, admin_headers):
    """PRD §3.1: "A weighted score of 85 or above passes the audit and sets the
    audit to `PASSED`; anything below 85 fails it and sets the audit to `FAILED`."
    PRD §3.1: "The member's `audit_score` is always the floor of the most recently
    completed audit's weighted score, clamped at zero, and it is zero while no
    audit has completed."

    Design: Corner/calculations/audit_weighted_score_one_decimal_round_half_up
    """
    member = create_member(api)
    res = api.create_audit(
        {"member_id": member["id"], "audit_type": "COMPREHENSIVE",
         "storage_score": 81, "distribution_score": 83, "reporting_score": 85},
        make_admin_headers(ADMIN_OPERATOR_ID),
    )
    audit = validate_success(res, 201)
    # 81*0.4 + 83*0.3 + 85*0.3 = 82.8
    assert audit["weighted_score"] == pytest.approx(82.8, abs=0.001)

    completed = validate_success(
        api.complete_audit(audit["id"], make_auditor_headers(AUDITOR_OPERATOR_ID)), 200
    )
    assert completed["audit_status"] == "FAILED"

    member_after = validate_success(api.get_member(member["id"], admin_headers), 200)
    assert member_after["audit_score"] == 82


def test_auditor_cannot_complete_audit_they_opened(api, admin_headers):
    """PRD §3.1: "The completing operator's `X-User-ID` must differ from the
    audit's recorded `opened_by_user_id`, or the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES`; this is enforced even when the caller holds the
    auditor role, and it is the only operation in the system that the auditor
    role may perform."

    Design: Corner/rbac/auditor_cannot_complete_own_audit
    """
    member = create_member(api)
    audit = create_audit(api, member["id"], opened_by=ADMIN_OPERATOR_ID)

    same_operator = api.complete_audit(audit["id"], make_auditor_headers(ADMIN_OPERATOR_ID))
    validate_error(same_operator, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    still_open = validate_success(api.get_member(member["id"], admin_headers), 200)
    assert still_open["audit_score"] == 0
    audits = validate_success(api.list_member_audits(member["id"], admin_headers), 200)
    assert audits[0]["audit_status"] == "IN_PROGRESS"

    different_operator = api.complete_audit(
        audit["id"], make_auditor_headers(AUDITOR_OPERATOR_ID)
    )
    completed = validate_success(different_operator, 200)
    assert completed["audit_status"] == "PASSED"


def test_failed_audit_demotes_certified_member_and_suspends_program(api, admin_headers):
    """PRD §3.1.2: "A completed audit whose weighted score falls below 85 demotes
    a `CERTIFIED` member to `PROBATION`; if the member is already on `PROBATION`,
    the same failure moves it to `SUSPENDED`."
    PRD §3.1.2: "When a member enters `PROBATION`, every one of its `ACTIVE` retail
    programs is suspended, and each of those programs' pickups that is still
    `SCHEDULED` for today or a later date is marked `MISSED`."

    Design: Difficulty/transitive_cascade/audit_failure_cascade_to_program_suspension_and_missed_pickup
    """
    member = create_certified_member(api)
    program = create_store_program(api, member, pickup_frequency="WEEKLY")
    assert program["program_status"] == "ACTIVE"

    audit = create_audit(
        api, member["id"], audit_type="STORAGE",
        storage_score=80, distribution_score=90, reporting_score=90,
    )
    completed = complete_audit(api, audit["id"])
    # STORAGE weighting: 80*0.6 + 90*0.2 + 90*0.2 = 84.0, below the 85 pass mark.
    assert completed["weighted_score"] == pytest.approx(84.0, abs=0.001)
    assert completed["audit_status"] == "FAILED"

    member_after = validate_success(api.get_member(member["id"], admin_headers), 200)
    assert member_after["certification_status"] == "PROBATION"
    assert member_after["audit_score"] == 84

    program_after = validate_success(
        api.get_store_program(program["id"], admin_headers), 200
    )
    assert_store_program(program_after)
    assert program_after["program_status"] == "SUSPENDED"


def test_failed_audit_marks_scheduled_pickup_missed(api, admin_headers):
    """PRD §3.1.2: "When a member enters `PROBATION`, every one of its `ACTIVE`
    retail programs is suspended, and each of those programs' pickups that is
    still `SCHEDULED` for today or a later date is marked `MISSED`."

    Design: Difficulty/transitive_cascade/audit_failure_cascade_to_program_suspension_and_missed_pickup
    """
    member = create_certified_member(api)
    program = create_store_program(api, member, pickup_frequency="WEEKLY")
    pickup = schedule_pickup(
        api, program, member,
        "2026-09-10T00:00:00Z", "2026-09-10T08:00:00Z", "2026-09-10T12:00:00Z",
    )
    assert pickup["pickup_status"] == "SCHEDULED"

    audit = create_audit(
        api, member["id"], audit_type="STORAGE",
        storage_score=80, distribution_score=90, reporting_score=90,
    )
    complete_audit(api, audit["id"])

    pickup_after = validate_success(
        api.list_program_pickups(program["id"], admin_headers), 200
    )
    assert len(pickup_after) == 1
    assert pickup_after[0]["pickup_status"] == "MISSED"
    assert pickup_after[0]["collected_lbs"] == 0
