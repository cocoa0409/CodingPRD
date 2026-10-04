"""Combinatorial formulas: equipment sufficiency gates and audit rounding order."""
import pytest

from test_helpers import (
    COORD,
    ApiErrorId,
    QA,
    open_audit,
    setup_teaching_scenario,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_course_session_payload


class TestEquipmentRatioMultiInputGate:
    def test_instructor_floor_rejects_then_succeeds(self, api):
        """PRD §3.5: "The instructor floor covers the lead plus assistants. The
        requirement is one instructor for the first six students plus one
        additional instructor for every further block of six students, rounded
        up — equivalently, 1 plus the ceiling of (`capacity` minus 6) divided by
        6, with the ceiling treated as no less than zero so a six-student
        session needs only the lead. The supplied `assisting_instructor_count`,
        plus 1 for the primary instructor, must meet that floor."
        PRD §3.5: "failure of any one rejects the create with
        `ERR_EQUIPMENT_RATIO_VIOLATION`."

        Design: Difficulty/combinatorial_formula/equipment_ratio_multi_input_gate
        """
        ctx = setup_teaching_scenario()
        base = create_course_session_payload(
            ctx["center"]["id"], ctx["site"]["id"], ctx["lead"]["id"],
            ctx["guidelines_version"]["id"],
            capacity=7, manikin_count=3, aed_trainer_count=2)

        # Capacity 7: manikins ceil(7/3)=3 OK, AED ceil(7/6)=2 OK, but
        # 1 + 0 assisting < 1 + ceil((7-6)/6) = 2 instructors -> 422.
        payload_fail = dict(base, assisting_instructor_count=0)
        resp = api.create_course_session(payload_fail, COORD)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_RATIO_VIOLATION)

        # Flipping only assisting_instructor_count to 1 satisfies all floors.
        payload_ok = dict(base, assisting_instructor_count=1)
        created = validate_success(
            api.create_course_session(payload_ok, COORD),
            expected_status=201)
        assert created["capacity"] == 7
        assert created["assisting_instructor_count"] == 1
        assert created["seats_available"] == 7
        assert created["status"] == "SCHEDULED"

    def test_manikin_and_aed_floors_each_gate_independently(self, api):
        """PRD §3.5: "For a `CLASSROOM` session the required number of manikins
        is the session's `capacity` divided by 3, rounded up. ... The baseline
        requirement is `capacity` divided by 6, rounded up."
        PRD §3.5: "failure of any one rejects the create with
        `ERR_EQUIPMENT_RATIO_VIOLATION`."

        Design: Difficulty/combinatorial_formula/equipment_ratio_multi_input_gate
        """
        ctx = setup_teaching_scenario()
        base = create_course_session_payload(
            ctx["center"]["id"], ctx["site"]["id"], ctx["lead"]["id"],
            ctx["guidelines_version"]["id"],
            capacity=7, assisting_instructor_count=1)

        # Manikin floor short: ceil(7/3)=3 required, 2 supplied.
        resp = api.create_course_session(
            dict(base, manikin_count=2, aed_trainer_count=2), COORD)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_RATIO_VIOLATION)

        # AED floor short: ceil(7/6)=2 required, 1 supplied.
        resp = api.create_course_session(
            dict(base, manikin_count=3, aed_trainer_count=1), COORD)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_RATIO_VIOLATION)

        # All three floors met.
        created = validate_success(
            api.create_course_session(
                dict(base, manikin_count=3, aed_trainer_count=2), COORD),
            expected_status=201)
        assert created["status"] == "SCHEDULED"


class TestAuditComplianceScoreRoundingOrder:
    def test_repeat_observations_round_per_finding_then_sum(self, api):
        """PRD §3.8: "The rounding order is pinned: round each finding first,
        then sum. Sum-then-round is a forbidden alternative because it produces
        different cents — for instance, two `OBSERVATION` repeat findings each
        contribute 1.88 (1.875 rounded half-up), totalling 3.76; summing the
        raw values first would yield 3.75."

        Design: Difficulty/combinatorial_formula/audit_compliance_score_rounding_order
        """
        ctx = setup_teaching_scenario()
        audit = open_audit(ctx["center"]["id"])

        f1 = validate_success(
            api.create_audit_finding(
                audit["id"],
                {"severity": "OBSERVATION", "is_repeat_offense": True,
                 "description": "Repeat: rosters missing signatures."},
                QA),
            expected_status=201)
        assert f1["deduction_points"] == pytest.approx(1.88, abs=0.001)

        f2 = validate_success(
            api.create_audit_finding(
                audit["id"],
                {"severity": "OBSERVATION", "is_repeat_offense": True,
                 "description": "Repeat: equipment logs incomplete."},
                QA),
            expected_status=201)
        assert f2["deduction_points"] == pytest.approx(1.88, abs=0.001)

        audit_now = validate_success(api.get_quality_audit(audit["id"], QA))
        # 100 - (1.88 + 1.88) = 96.24; sum-then-round would give 96.25.
        assert audit_now["compliance_score"] == pytest.approx(96.24, abs=0.001)
        assert abs(audit_now["compliance_score"] - 96.25) > 0.0001

    def test_mixed_severities_accumulate_and_floor_at_zero(self, api):
        """PRD §3.8: "Each finding's `deduction_points` is computed as the
        severity's base points — 1.25 for `OBSERVATION`, 4.5 for `MINOR`, 12.5
        for `MAJOR`, and 40 for `CRITICAL` — multiplied by 1.5 when
        `is_repeat_offense` is true and by 1.0 otherwise, with the per-finding
        result rounded half-up to two decimal places *before* being summed."
        PRD §3.8: "The audit's `compliance_score` is then 100 minus the total
        deduction, floored at zero so the score never goes negative."

        Design: Difficulty/combinatorial_formula/audit_compliance_score_rounding_order
        """
        ctx = setup_teaching_scenario()
        audit = open_audit(ctx["center"]["id"])

        f = validate_success(
            api.create_audit_finding(
                audit["id"],
                {"severity": "MINOR", "description": "Sign-in sheet gaps."},
                QA),
            expected_status=201)
        assert f["deduction_points"] == pytest.approx(4.5, abs=0.001)
        f = validate_success(
            api.create_audit_finding(
                audit["id"],
                {"severity": "MAJOR", "is_repeat_offense": True,
                 "description": "Repeat: uncalibrated manikins."},
                QA),
            expected_status=201)
        # 12.5 * 1.5 = 18.75.
        assert f["deduction_points"] == pytest.approx(18.75, abs=0.001)

        audit_now = validate_success(api.get_quality_audit(audit["id"], QA))
        # 100 - (4.5 + 18.75) = 76.75.
        assert audit_now["compliance_score"] == pytest.approx(76.75, abs=0.001)
