"""Operational endpoints: the logical clock and the periodic sweep.

Both live under the `/_` namespace because they drive time and batch state
rather than modelling a marketplace resource. They are declared endpoints of
the contract, not back doors: the clock endpoint is the only way the logical
clock moves, and the sweep is the only thing that advances sections through
their automatic transitions.
"""

from datetime import timedelta

from flask import Blueprint

from core import auth, clock, constants as C, envelope, store
from core.errors import fail
from services import calc, cascades, views

from .common import api

bp = Blueprint("ops", __name__)


# ---------------------------------------------------------------------------
# POST /outschool/_clock/set_current_utc
# ---------------------------------------------------------------------------
@bp.post("/outschool/_clock/set_current_utc")
@api(["PlatformAdmin"])
def set_current_utc(role, user_id):
    data = auth.body()
    auth.require_fields(data, ["to_iso8601"])
    instant = clock.try_parse_datetime(data["to_iso8601"])
    if instant is None:
        fail("ERR_INVALID_TIME_WINDOW", "to_iso8601 must be an ISO 8601 instant")
    clock.CLOCK.set_current(instant)
    return {"current_utc": clock.fmt(clock.now())}


# ---------------------------------------------------------------------------
# POST /outschool/_ops/run
# ---------------------------------------------------------------------------
def _escalate_stale_reports():
    """OPEN reports older than REPORT_SLA_PERIODS periods move to UNDER_REVIEW."""
    escalated = []
    for report in store.all_of("reports"):
        if report["status"] != "OPEN":
            continue
        opened = report["_internal"].get("open_period_index", 0)
        if clock.period() - opened > C.REPORT_SLA_PERIODS:
            report["status"] = "UNDER_REVIEW"
            store.touch(report)
            escalated.append(report["id"])
    return escalated


def _expire_reviewer_sla():
    """SAMPLE_PENDING applications whose bound reviewer ran out of time are rejected."""
    expired = []
    for application in store.all_of("applications"):
        if application["status"] != "SAMPLE_PENDING":
            continue
        bound = application.get("reviewer_bound_period_index")
        if bound is None or application.get("reviewed_by_user_id") is None:
            continue
        if clock.period() < bound + C.REVIEWER_SLA_PERIODS:
            continue
        application["decision"] = "REJECT"
        application["decision_reason_code"] = "INCOMPLETE_MATERIALS"
        application["revision_count"] = application.get("revision_count", 0) + 1
        if application["revision_count"] >= C.APPLICATION_MAX_REVISIONS:
            application["status"] = "REJECTED"
        else:
            application["status"] = "SAMPLE_REJECTED"
        store.touch(application)
        expired.append(application["id"])
    return expired


def _release_reservations(section):
    """Reserved seats lapse when the section reaches its start instant."""
    released = []
    for enrollment in calc.enrollments_of_section(section["id"]):
        if enrollment["status"] != "RESERVED":
            continue
        learner = store.find("learners", enrollment["learner_id"])
        enrollment["status"] = "RELEASED"
        cascades.write_refund(enrollment, learner, "NONE", "platform")
        released.append(enrollment["id"])
    return released


def _sweep_sections():
    """Auto-cancellation, reservation release and completion."""
    cancelled, completed, released = [], [], []
    current = clock.now()
    for section in store.all_of("sections"):
        status = section["status"]

        if status in ("SCHEDULED", "OPEN_FOR_ENROLLMENT"):
            cutoff = section["start_utc_dt"] - timedelta(hours=C.AUTO_CANCEL_CUTOFF_HOURS)
            projected = section.get("expected_learners")
            if projected is None:
                projected = section["min_learners"]
            if current >= cutoff and projected < section["min_learners"]:
                cascades.cancel_section_and_enrollments(
                    section,
                    "AUTO_CANCELLED_MIN_ENROLLMENT",
                    "platform",
                    "RELEASED",
                    "FULL",
                )
                cancelled.append(section["id"])
                continue
            if current >= section["start_utc_dt"]:
                released.extend(_release_reservations(section))
            continue

        if status == "MIN_ENROLLMENT_MET":
            if current < section["start_utc_dt"]:
                continue
            if not calc.occupancy(section)["settled"]:
                continue
            section["status"] = "COMPLETED"
            if section["outcome"] is None:
                section["outcome"] = "HELD"
            store.touch(section)
            completed.append(section["id"])

    return cancelled, completed, released


def _sweep_teacher_earnings():
    """Re-derive every teacher's tax-document standing.

    The standing is a pure function of lifetime net earnings, so it is already
    correct on every read; touching the teacher here keeps the teacher's own
    version advancing when a batch recompute changes its standing.
    """
    suspended = []
    for teacher in store.all_of("teachers"):
        lifetime = calc.lifetime_net_earnings(teacher["id"])
        standing = calc.tax_document_status(lifetime)
        if standing != teacher.get("_internal", {}).get("last_tax_document_status"):
            teacher["_internal"]["last_tax_document_status"] = standing
            store.touch(teacher)
        if (
            teacher["status"] == "ACTIVE"
            and calc.risk_scores(teacher["id"])["actionable_risk_score"]
            >= C.RISK_SUSPENSION_THRESHOLD
        ):
            cascades.apply_risk_cascade(teacher)
            suspended.append(teacher["id"])
    return suspended


@bp.post("/outschool/_ops/run")
@api(["PlatformAdmin"])
def run_ops(role, user_id):
    escalated = _escalate_stale_reports()
    expired = _expire_reviewer_sla()
    cancelled, completed, released = _sweep_sections()
    suspended = _sweep_teacher_earnings()
    return {
        "cancelled_section_ids": cancelled,
        "completed_section_ids": completed,
        "released_enrollment_ids": released,
        "escalated_report_ids": escalated,
        "expired_application_ids": expired,
        "suspended_teacher_ids": suspended,
    }
