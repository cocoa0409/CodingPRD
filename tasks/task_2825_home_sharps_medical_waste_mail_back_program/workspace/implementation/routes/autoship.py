"""The replacement-container auto-ship checkpoint and the logical clock (PRD 3.9, 2.4)."""
from datetime import timedelta

from flask import Blueprint

import clock
import constants
import db
import response
import validate
from errors import ERR_KIT_AUTHORIZATION_EXHAUSTED, ERR_PER_KIT_ALLOWANCE_EXCEEDED, fail
from middleware import endpoint
from routes.common import page
from services import calc, kits as kit_svc, lookup
from validate import Field

bp = Blueprint("autoship", __name__)

RUN_SCHEMA = [Field("as_of_date", "date", default=None)]
CLOCK_SCHEMA = [Field("to_iso8601", "instant", required=True)]

OUT_OF_SCOPE_ENROLLMENT_STATUSES = ("REJECTED", "TERMINATED")


def _refresh_all_risk_scores():
    for patient in db.ordered("patients"):
        live = [
            e
            for e in lookup.patient_enrollments(patient["id"])
            if e["status"] not in OUT_OF_SCOPE_ENROLLMENT_STATUSES
        ]
        if not live:
            continue
        calc.refresh_screening_score(patient)
        calc.refresh_audit_score(patient)
        db.touch(patient)


@bp.post("/sharps/auto-ship-runs")
@endpoint(["ProgramAdmin"])
def create_run():
    body, _provided = validate.parse_body(RUN_SCHEMA)
    as_of_iso = body["as_of_date"] or clock.now_date_iso()
    as_of_date = clock.parse_date(as_of_iso)

    _refresh_all_risk_scores()

    run = db.create_row(
        "autoship_runs",
        {
            "as_of_date": as_of_iso,
            "run_at": clock.now_iso(),
            "enrollments_evaluated": 0,
            "kits_created": 0,
            "kits_skipped_not_due": 0,
            "kits_skipped_unfilled": 0,
            "kits_skipped_risk": 0,
            "kits_skipped_funding": 0,
            "created_kit_ids": [],
        },
        common=False,
    )

    enrollments = db.ordered("enrollments", lambda e: e["status"] == "ACTIVE")
    run["enrollments_evaluated"] = len(enrollments)

    for enrollment in enrollments:
        due = enrollment["next_autoship_due_date"]
        if due is None or due > as_of_iso:
            run["kits_skipped_not_due"] += 1
            continue
        patient = lookup.enrollment_patient(enrollment)
        if patient is None:
            run["kits_skipped_not_due"] += 1
            continue
        if patient["audit_risk_score"] >= constants.RISK_SUSPEND_THRESHOLD:
            run["kits_skipped_risk"] += 1
            continue
        latest = kit_svc.most_recent_kit(enrollment["id"])
        if latest is not None and latest["status"] in kit_svc.OPEN_KIT_STATUSES:
            run["kits_skipped_unfilled"] += 1
            continue

        program = lookup.enrollment_program(enrollment)
        state_rule = lookup.patient_state_rule(patient)
        plan = kit_svc.plan_kit(
            enrollment, patient, state_rule, enrollment["requested_container_size"]
        )
        provisional = plan[2]
        if kit_svc.non_voided_kit_count(enrollment["id"]) >= enrollment["kits_authorized"]:
            fail(ERR_KIT_AUTHORIZATION_EXHAUSTED)
        if provisional > program["per_kit_allowance_cents"]:
            fail(ERR_PER_KIT_ALLOWANCE_EXCEEDED)
        if program["available_cents"] < provisional:
            run["kits_skipped_funding"] += 1
            continue

        kit = kit_svc.issue_kit(
            enrollment,
            program,
            plan,
            as_of_date,
            auto_ship_run_id=run["id"],
            supersedes_override=True,
            supersedes_kit_id=latest["id"] if latest is not None else None,
            check_pool=False,
        )
        run["kits_created"] += 1
        run["created_kit_ids"].append(kit["id"])

    return response.created(response.view("autoship_run", run))


@bp.get("/sharps/auto-ship-runs/<run_id>")
@endpoint(["ProgramAdmin"], mutating=False)
def get_run(run_id):
    row = lookup.require("autoship_run", run_id)
    return response.ok(response.view("autoship_run", row))


@bp.get("/sharps/auto-ship-runs")
@endpoint(["ProgramAdmin"], mutating=False)
def list_runs():
    limit, offset = validate.pagination()
    as_of_date = validate.qs_date("as_of_date")
    rows = db.ordered("autoship_runs")
    if as_of_date is not None:
        rows = [r for r in rows if r["as_of_date"] == as_of_date]
    return page("autoship_run", rows, limit, offset)


# ---- the logical clock --------------------------------------------------

@bp.post("/_clock/set_current_utc")
@endpoint(["ProgramAdmin"], mutating=False)
def set_clock():
    body, _provided = validate.parse_body(CLOCK_SCHEMA)
    clock.clock.set(clock.parse_instant(body["to_iso8601"]))
    return response.ok({})
