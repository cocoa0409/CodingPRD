"""Enrollment submission, the two independent state dimensions and the
chargeback schedule (PRD 2.12, 2.13, 3.6, 3.7)."""

from datetime import timedelta
from decimal import Decimal

import calculations as calc
import core
import db
import middleware
import response
import serializers
from decorators import requires
from errors import ApiError

READ_ROLES = ("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer",
              "CarrierIntegration", "LicensedAgent", "Any")


def register(app):
    @app.post("/enrollments")
    @requires("LicensedAgent")
    def submit_enrollment():
        payload = middleware.body()
        session = middleware.resolve("CallSession",
                                     middleware.require_field(payload, "call_session_id"))
        member = middleware.resolve("Member", middleware.require_field(payload, "member_id"))
        plan = middleware.resolve("Plan", middleware.require_field(payload, "plan_id"))
        agent = middleware.resolve("Agent", middleware.require_field(payload, "agent_id"))
        scope = middleware.resolve("ScopeOfAppointment",
                                   middleware.require_field(payload, "scope_of_appointment_id"))
        agency = db.agencies.get(agent["agency_id"])
        middleware.owner_check("LicensedAgent", middleware.current_user_id(), agent["id"])

        middleware.gate_posture(agency)
        core.require_scope_usable(scope, agent["id"])
        plan_type_discussed = middleware.require_field(payload, "plan_type_discussed", str)
        if plan_type_discussed not in scope["plan_types_authorized"]:
            raise ApiError("ERR_PLAN_TYPE_NOT_AUTHORIZED",
                           "The plan type under discussion is not authorized by the scope.")
        if plan_type_discussed not in calc.PLAN_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", "plan_type_discussed is not a valid plan type.")

        core.require_staffing_authority(agent, plan)
        if member["agency_id"] != agent["agency_id"]:
            raise ApiError("ERR_MEMBER_NOT_IN_AGENCY",
                           "The member does not belong to the agent's agency.")
        if plan["status"] != "ACTIVE" or plan["state_code"] != member["state_code"] \
                or plan["county_code"] != member["county_code"]:
            raise ApiError("ERR_PLAN_NOT_IN_SERVICE_AREA",
                           "The plan is not in the member's service area.")

        effective_date = middleware.as_instant(
            middleware.require_field(payload, "effective_date"), "effective_date")

        if agency["aep_start_date"] <= effective_date <= agency["aep_end_date"] \
                and plan["plan_type"] == "PDP":
            raise ApiError("ERR_AEP_WINDOW_VIOLATION",
                           "A PDP election cannot be submitted inside the AEP window.")

        committed = len([
            row for row in core.agency_enrollments(agency["id"])
            if row["effective_date"].date() == effective_date.date()
            and row["submission_status"] not in ("REJECTED", "WITHDRAWN")
        ])
        if committed >= agency["aep_daily_submission_capacity"]:
            raise ApiError("ERR_AEP_DAILY_SUBMISSION_CAPACITY_EXCEEDED",
                           "The daily submission capacity is already committed.")

        expected_version = middleware.as_int(
            middleware.require_field(payload, "expected_call_session_version"),
            "expected_call_session_version")
        if expected_version != session["version"]:
            raise ApiError("ERR_STALE_VERSION",
                           "expected_call_session_version does not match the call session's version.")

        row = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "created_at": db.now(),
            "updated_at": db.now(),
            "version": 1,
            "call_session_id": session["id"],
            "member_id": member["id"],
            "plan_id": plan["id"],
            "agent_id": agent["id"],
            "agency_id": agent["agency_id"],
            "scope_of_appointment_id": scope["id"],
            "carrier_id": plan["carrier_id"],
            "effective_date": effective_date,
            "submitted_on": db.now(),
            "acknowledged_on": None,
            "effectuated_on": None,
            "submission_status": "SUBMITTED",
            "disenrollment_status": "NOT_APPLICABLE",
            "disenrollment_date": None,
            "disenrollment_reason": None,
            "model_variant": middleware.optional(payload, "model_variant"),
        }
        db.enrollments[row["id"]] = row

        row["provisional_commission_cents"] = core.provisional_for_enrollment(row)
        core.refresh_earned_for_agency(agency["id"])
        core.recompute_member_enrollment_count(member)
        initial = core.post_entry(row, entry_type="INITIAL")
        core.present_entry(initial, period_month=row["submitted_on"].strftime("%Y-%m"))
        core.recompute_balance(agency)
        core.touch(session)
        return response.ok(serializers.serialize("Enrollment", row), status=201)

    @app.get("/enrollments")
    @requires(*READ_ROLES)
    def list_enrollments():
        rows = list(db.enrollments.values())
        for arg, field in (("carrier_id", "carrier_id"), ("plan_id", "plan_id"),
                           ("agent_id", "agent_id"), ("member_id", "member_id"),
                           ("call_session_id", "call_session_id"),
                           ("scope_of_appointment_id", "scope_of_appointment_id"),
                           ("submission_status", "submission_status"),
                           ("disenrollment_status", "disenrollment_status")):
            value = middleware.text_arg(arg)
            if value is not None:
                rows = [row for row in rows if row[field] == value]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("Enrollment", page), limit, offset, total)

    @app.get("/enrollments/<enrollment_id>")
    @requires(*READ_ROLES)
    def get_enrollment(enrollment_id):
        enrollment = middleware.resolve("Enrollment", enrollment_id)
        return response.ok(serializers.serialize("Enrollment", enrollment))

    @app.post("/enrollments/<enrollment_id>/acknowledge")
    @requires("CarrierIntegration")
    def acknowledge(enrollment_id):
        enrollment = middleware.resolve("Enrollment", enrollment_id)
        payload = middleware.body()

        if enrollment["submission_status"] != "SUBMITTED":
            raise ApiError("ERR_ENROLLMENT_NOT_SUBMITTED", "The enrollment is not SUBMITTED.")
        supplied_carrier = middleware.require_field(payload, "carrier_id", str)
        carrier = db.carriers.get(supplied_carrier)
        if carrier is None or carrier["status"] != "ACTIVE":
            raise ApiError("ERR_CARRIER_NOT_FOUND", "The carrier does not resolve or is not ACTIVE.")
        if supplied_carrier != enrollment["carrier_id"]:
            raise ApiError("ERR_CARRIER_MISMATCH",
                           "The supplied carrier_id does not equal the enrollment's carrier.")
        window_end = enrollment["submitted_on"] + timedelta(days=carrier["ack_expected_within_days"])
        if db.now() > window_end:
            raise ApiError("ERR_ACK_WINDOW_EXPIRED", "The acknowledgment window has expired.")

        enrollment["submission_status"] = "ACKNOWLEDGED"
        enrollment["acknowledged_on"] = db.now()
        core.touch(enrollment)
        renewal = core.post_entry(enrollment, entry_type="RENEWAL")
        core.present_entry(
            renewal, period_month=enrollment["submitted_on"].strftime("%Y-%m"))
        core.recompute_balance(db.agencies.get(enrollment["agency_id"]))
        return response.ok(serializers.serialize("Enrollment", enrollment))

    @app.post("/enrollments/<enrollment_id>/effectuate")
    @requires("CarrierIntegration")
    def effectuate(enrollment_id):
        enrollment = middleware.resolve("Enrollment", enrollment_id)
        carrier = db.carriers.get(enrollment["carrier_id"])
        scope = db.scopes.get(enrollment["scope_of_appointment_id"])

        if enrollment["submission_status"] not in ("SUBMITTED", "ACKNOWLEDGED"):
            raise ApiError("ERR_ENROLLMENT_NOT_ACKNOWLEDGED",
                           "The enrollment has not reached an effectuatable status.")
        if enrollment["submission_status"] == "ACKNOWLEDGED":
            window_end = enrollment["acknowledged_on"] + timedelta(
                days=carrier["effectuation_expected_within_days"])
            if db.now() > window_end:
                raise ApiError("ERR_EFFECTUATION_WINDOW_EXPIRED",
                               "The effectuation window has expired.")
        if scope is None or scope["status"] != "CAPTURED":
            raise ApiError("ERR_SCOPE_OF_APPOINTMENT_CONSUMED",
                           "The attached scope of appointment is no longer CAPTURED.")

        enrollment["submission_status"] = "EFFECTUATED"
        enrollment["effectuated_on"] = db.now()
        enrollment["disenrollment_status"] = "ENROLLED"
        core.touch(enrollment)
        scope["status"] = "CONSUMED"
        scope["consumed_by_enrollment_id"] = enrollment["id"]
        core.touch(scope)

        agency = db.agencies.get(enrollment["agency_id"])
        agent = db.agents.get(enrollment["agent_id"])
        plan = db.plans.get(enrollment["plan_id"])
        core.recompute_agent_counts(agent)
        core.recompute_plan_enrolled_count(plan)
        core.refresh_earned_for_agency(agency["id"])
        core.reopen_open_reconciliation(enrollment["carrier_id"], db.now().strftime("%Y-%m"))
        core.recompute_balance(agency)
        return response.ok(serializers.serialize("Enrollment", enrollment))

    @app.post("/enrollments/<enrollment_id>/reject")
    @requires("CarrierIntegration")
    def reject(enrollment_id):
        enrollment = middleware.resolve("Enrollment", enrollment_id)
        if enrollment["submission_status"] not in ("SUBMITTED", "ACKNOWLEDGED"):
            raise ApiError("ERR_ENROLLMENT_NOT_SUBMITTED", "The enrollment cannot be rejected.")
        enrollment["submission_status"] = "REJECTED"
        core.touch(enrollment)
        scope = db.scopes.get(enrollment["scope_of_appointment_id"])
        if scope is not None and scope["status"] == "CONSUMED":
            scope["status"] = "VOIDED"
            core.touch(scope)
        agent = db.agents.get(enrollment["agent_id"])
        core.recompute_agent_counts(agent)
        return response.ok(serializers.serialize("Enrollment", enrollment))

    @app.post("/enrollments/<enrollment_id>/withdraw")
    @requires("LicensedAgent", "ComplianceOfficer")
    def withdraw(enrollment_id):
        enrollment = middleware.resolve("Enrollment", enrollment_id)
        payload = middleware.body()
        agency = db.agencies.get(enrollment["agency_id"])
        middleware.gate_posture(agency)
        current = enrollment["submission_status"]
        if current not in ("SUBMITTED", "ACKNOWLEDGED", "REJECTED"):
            raise ApiError("ERR_ENROLLMENT_NOT_WITHDRAWABLE",
                           "An EFFECTUATED or WITHDRAWN enrollment cannot be withdrawn.")

        enrollment["submission_status"] = "WITHDRAWN"
        enrollment["disenrollment_reason"] = middleware.optional(payload, "reason")
        core.touch(enrollment)
        scope = db.scopes.get(enrollment["scope_of_appointment_id"])
        if scope is not None and scope["status"] == "CONSUMED":
            scope["status"] = "VOIDED"
            core.touch(scope)
        agent = db.agents.get(enrollment["agent_id"])
        agent["chargeback_tier"] += 1
        core.touch(agent)

        if current in ("SUBMITTED", "ACKNOWLEDGED"):
            base = core.reversal_base(enrollment["id"])
            period_month = enrollment["submitted_on"].strftime("%Y-%m")
            reversal = core.post_entry(enrollment, entry_type="REVERSAL",
                                       amount_cents=-calc.r2(base),
                                       period_month=period_month)
            core.present_entry(reversal, period_month=period_month)
            core.recompute_risk_score(agent)
            core.recompute_balance(agency)
        core.recompute_agent_counts(agent)
        return response.ok(serializers.serialize("Enrollment", enrollment))

    @app.post("/enrollments/<enrollment_id>/disenroll")
    @requires("CarrierIntegration")
    def disenroll(enrollment_id):
        enrollment = middleware.resolve("Enrollment", enrollment_id)
        payload = middleware.body()
        agency = db.agencies.get(enrollment["agency_id"])
        middleware.gate_posture(agency)

        if enrollment["submission_status"] != "EFFECTUATED" \
                or enrollment["disenrollment_status"] != "ENROLLED":
            raise ApiError("ERR_ENROLLMENT_NOT_ENROLLED",
                           "The enrollment is not EFFECTUATED and ENROLLED.")

        disenrollment_date = middleware.as_instant(
            middleware.require_field(payload, "disenrollment_date"), "disenrollment_date")
        if disenrollment_date < enrollment["effective_date"]:
            raise ApiError("ERR_INVALID_REQUEST",
                           "disenrollment_date must be on or after effective_date.")

        day_number = db.whole_days(enrollment["effective_date"], disenrollment_date)
        rapid = day_number <= agency["rapid_disenrollment_day_limit"]
        requested_rapid = payload.get("disenrollment_status")
        if requested_rapid == "RAPID_DISENROLLED" and not rapid:
            raise ApiError("ERR_NOT_RAPID_DISENROLLMENT",
                           "The enrollment does not qualify as a rapid disenrollment.")
        if requested_rapid == "STANDARD_DISENROLLED" and rapid:
            raise ApiError("ERR_RAPID_DISENROLLMENT_REQUIRES_CHARGEBACK",
                           "A chargeback is mandatory inside the rapid window.")

        agent = db.agents.get(enrollment["agent_id"])
        plan = db.plans.get(enrollment["plan_id"])
        carrier = db.carriers.get(enrollment["carrier_id"])
        period_month = enrollment["submitted_on"].strftime("%Y-%m")

        if rapid:
            enrollment["disenrollment_status"] = "RAPID_DISENROLLED"
        else:
            enrollment["disenrollment_status"] = "STANDARD_DISENROLLED"
        enrollment["disenrollment_date"] = disenrollment_date
        enrollment["disenrollment_reason"] = middleware.optional(payload, "disenrollment_reason")
        core.touch(enrollment)

        if rapid:
            recent = len([
                row for row in core.agent_complaints(agent["id"])
                if row["status"] in ("SUBSTANTIATED", "APPEALED")
                and row.get("substantiated_on") is not None
                and disenrollment_date - timedelta(days=calc.ESCALATION_COMPLAINT_WINDOW_DAYS)
                <= row["substantiated_on"] <= disenrollment_date
            ])
            pct = calc.selected_chargeback_pct(day_number, agent["chargeback_tier"], recent)
            if pct is None:
                pct = Decimal("1.00")
            # PRD §3.7: the rapid path posts a CHARGEBACK entry in status
            # FINALIZED, whose amount_cents is strictly negative.
            chargeback = core.post_entry(
                enrollment, entry_type="CHARGEBACK",
                amount_cents=calc.chargeback_amount(plan, carrier, pct),
                period_month=period_month, clawback_pct=calc.num(pct),
                status="FINALIZED")
            core.present_entry(chargeback, period_month=period_month)
            agent["chargeback_tier"] += 1
            core.touch(agent)
            core.recompute_loss_ratio(agency)
            for rec in db.reconciliations.values():
                if rec["carrier_id"] == enrollment["carrier_id"] and rec["status"] == "OPEN":
                    rec["status"] = "DISPUTED"
                    core.touch(rec)
            core.recompute_balance(agency)
        else:
            # PRD §3.7: the standard path posts a CHARGEBACK entry in status
            # FINALIZED whose amount_cents is exactly 0.
            chargeback = core.post_entry(
                enrollment, entry_type="CHARGEBACK",
                amount_cents=Decimal("0.00"),
                period_month=period_month, clawback_pct=Decimal("0.00"),
                status="FINALIZED")
            core.present_entry(chargeback, period_month=period_month)

        core.recompute_plan_enrolled_count(plan)
        core.recompute_agent_counts(agent)
        core.recompute_risk_score(agent)
        core.refresh_earned_for_agency(agency["id"])
        return response.ok(serializers.serialize("Enrollment", enrollment))

    @app.post("/enrollments/<enrollment_id>/commission-adjustment")
    @requires("DirectorOfSales")
    def commission_adjustment(enrollment_id):
        enrollment = middleware.resolve("Enrollment", enrollment_id)
        payload = middleware.body()
        period_month = middleware.require_field(payload, "period_month", str)
        reconciliation = middleware.resolve("CarrierReconciliation",
                                            middleware.require_field(payload, "carrier_reconciliation_id"))
        if reconciliation["status"] != "OPEN":
            raise ApiError("ERR_NO_OPEN_RECONCILIATION",
                           "The named reconciliation period is not OPEN.")
        row = core.post_entry(enrollment, entry_type="ADJUSTMENT",
                              period_month=period_month,
                              memo=middleware.optional(payload, "memo"),
                              reconciliation_id=reconciliation["id"])
        core.recompute_reconciliation(reconciliation)
        core.recompute_balance(db.agencies.get(enrollment["agency_id"]))
        return response.ok(serializers.serialize("CommissionLedgerEntry", row), status=201)