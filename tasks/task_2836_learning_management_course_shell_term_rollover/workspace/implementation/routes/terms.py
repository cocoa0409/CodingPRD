"""Academic terms -- PRD 3.1, 3.2 and the posture dimension of 3.9."""

from decimal import Decimal

from flask import Blueprint

import lookup
from db import by_created, db, mark, new_record, now, set_field
from errors import require
from middleware import (ACCESSIBILITY_REVIEWER, INSTRUCTOR, LMS_ADMIN,
                        PRIVACY_REVIEWER, REGISTRAR, STUDENT, actor, as_dt,
                        as_enum, as_int, as_str, bad, body)
from routes.common import (apply_filters, arg, created, guard, listing, ok,
                           plain_ok, term_order)
from services import cascade, compute
from util import add_days, q2

bp = Blueprint("terms", __name__)

LIFECYCLE_STATES = ("PLANNING", "REGISTRATION_OPEN", "IN_SESSION", "FINALS",
                    "GRADING", "CLOSED", "ARCHIVED")
POSTURES = ("NORMAL", "ELEVATED", "CONTINUITY_MODE")
RETENTION_CLASSES = ("STANDARD", "EXTENDED", "LEGAL_HOLD")

DECLARED_LIFECYCLE = {
    ("PLANNING", "REGISTRATION_OPEN"),
    ("REGISTRATION_OPEN", "IN_SESSION"),
    ("IN_SESSION", "FINALS"),
    ("FINALS", "IN_SESSION"),
    ("FINALS", "GRADING"),
    ("GRADING", "CLOSED"),
    ("CLOSED", "ARCHIVED"),
}

DECLARED_POSTURE = {
    ("NORMAL", "ELEVATED"),
    ("ELEVATED", "CONTINUITY_MODE"),
    ("CONTINUITY_MODE", "ELEVATED"),
    ("ELEVATED", "NORMAL"),
}

DEFAULT_ADD_DROP_DAYS = 14
DEFAULT_FINALS_LEAD_DAYS = 7
DEFAULT_GRACE_DAYS = 30


@bp.post("/academic-terms")
def create_term():
    guard(REGISTRAR)
    payload = body()
    term_code = as_str(payload, "term_code", required=True)
    term_start_at = as_dt(payload, "term_start_at", required=True)
    term_end_at = as_dt(payload, "term_end_at", required=True)
    add_drop_deadline_at = as_dt(payload, "add_drop_deadline_at")
    finals_start = as_dt(payload, "finals_window_start_at")
    finals_end = as_dt(payload, "finals_window_end_at")
    grace = as_int(payload, "access_grace_days", default=DEFAULT_GRACE_DAYS,
                   low=0, high=365)
    retention_class = as_enum(payload, "retention_class", RETENTION_CLASSES,
                              default="STANDARD")
    if term_end_at <= term_start_at:
        bad("term_end_at", "must be strictly after term_start_at")
    if finals_end is not None and finals_end > term_end_at:
        bad("finals_window_end_at", "may not fall after term_end_at")

    for existing in db.terms.values():
        require(existing["term_code"] != term_code, "ERR_DUPLICATE_TERM_CODE",
                "term_code '%s' is already registered." % term_code)

    term = new_record(
        _kind="term",
        term_code=term_code,
        lifecycle_state="PLANNING",
        continuity_posture="NORMAL",
        term_start_at=term_start_at,
        term_end_at=term_end_at,
        add_drop_deadline_at=add_drop_deadline_at
        if add_drop_deadline_at is not None
        else add_days(term_start_at, DEFAULT_ADD_DROP_DAYS),
        finals_window_start_at=finals_start
        if finals_start is not None
        else add_days(term_end_at, -DEFAULT_FINALS_LEAD_DAYS),
        finals_window_end_at=finals_end if finals_end is not None else term_end_at,
        access_grace_days=grace,
        retention_class=retention_class,
        student_access_end_at=None,
        retention_purge_at=None,
        rollover_completion_pct=q2(Decimal(100)),
        published_shell_count=0,
        overflow_shell_count=0,
        total_active_enrollments=0,
        open_amendment_count=0,
        sis_sync_epoch=0,
    )
    compute.retention_calendar(term)
    db.terms[term["id"]] = term
    return created(term)


@bp.get("/academic-terms")
def list_terms():
    guard(REGISTRAR, LMS_ADMIN, INSTRUCTOR)
    records = apply_filters(db.terms.values(), {
        "term_code": "term_code",
        "lifecycle_state": "lifecycle_state",
        "continuity_posture": "continuity_posture",
        "retention_class": "retention_class",
    })
    return listing(records, order=term_order)


@bp.get("/academic-terms/<term_id>")
def read_term(term_id):
    guard(REGISTRAR, LMS_ADMIN, INSTRUCTOR, STUDENT)
    return ok(lookup.term(term_id))


@bp.patch("/academic-terms/<term_id>")
def update_term(term_id):
    guard(REGISTRAR)
    term = lookup.term(term_id)
    payload = body()
    grace = as_int(payload, "access_grace_days", low=0, high=365)
    retention_class = as_enum(payload, "retention_class", RETENTION_CLASSES)
    add_drop_deadline_at = as_dt(payload, "add_drop_deadline_at")
    require(term["lifecycle_state"] not in ("CLOSED", "ARCHIVED"),
            "ERR_INVALID_STATE_TRANSITION",
            "A closed term may no longer be amended.")
    if grace is not None:
        set_field(term, "access_grace_days", grace)
    if retention_class is not None:
        set_field(term, "retention_class", retention_class)
    if add_drop_deadline_at is not None:
        set_field(term, "add_drop_deadline_at", add_drop_deadline_at)
    compute.retention_calendar(term)
    mark(term)
    return ok(term)


@bp.post("/academic-terms/<term_id>/lifecycle-transitions")
def transition_term(term_id):
    guard(REGISTRAR)
    term = lookup.term(term_id)
    payload = body()
    target = as_enum(payload, "target_state", LIFECYCLE_STATES, required=True)
    as_str(payload, "reason")
    current = term["lifecycle_state"]

    require((current, target) in DECLARED_LIFECYCLE, "ERR_INVALID_STATE_TRANSITION",
            "%s -> %s is not a declared term transition." % (current, target))
    if (current, target) == ("FINALS", "IN_SESSION"):
        # Legal only during CONTINUITY_MODE (PRD 3.2).
        require(term["continuity_posture"] == "CONTINUITY_MODE",
                "ERR_INVALID_STATE_TRANSITION",
                "FINALS may only reverse to IN_SESSION during CONTINUITY_MODE.")
    if (current, target) == ("CLOSED", "ARCHIVED"):
        require(term["student_access_end_at"] is not None
                and now() >= term["student_access_end_at"],
                "ERR_INVALID_STATE_TRANSITION",
                "Students still hold read rights on this term.")
    if (current, target) == ("FINALS", "GRADING"):
        require(term["continuity_posture"] != "CONTINUITY_MODE",
                "ERR_TERM_POSTURE_FROZEN",
                "The term's posture freezes advancement out of FINALS.")
    if (current, target) == ("GRADING", "CLOSED"):
        require(term["open_amendment_count"] == 0,
                "ERR_OPEN_DISPUTES_BLOCK_CLOSE",
                "A passback of this term is still DISPUTED or AMENDED.")
    if (current, target) == ("PLANNING", "REGISTRATION_OPEN"):
        eligible = compute.eligible_shells(term["id"])
        if not eligible:
            fresh = q2(Decimal(100))
        else:
            targets = set(j["target_shell_id"] for j in db.jobs.values()
                          if j["job_state"] == "COMPLETED")
            done = sum(1 for s in eligible if s["id"] in targets)
            from util import pct as _pct
            fresh = _pct(Decimal(done), Decimal(len(eligible)))
        require(fresh >= Decimal("100.00"), "ERR_ROLLOVER_INCOMPLETE",
                "Rollover completion stands at %s." % fresh)
        set_field(term, "rollover_completion_pct", fresh)

    set_field(term, "lifecycle_state", target)

    if target == "CLOSED":
        for shell in by_created([
            s for s in lookup.shells_of_term(term["id"])
            if s["provisioning_state"] in ("PROVISIONED", "PUBLISHED")
            and s["merged_into_shell_id"] is None
        ]):
            cascade.conclude_shell(shell)
    if target == "ARCHIVED":
        for shell in by_created([
            s for s in lookup.shells_of_term(term["id"])
            if s["provisioning_state"] == "CONCLUDED"
        ]):
            cascade.archive_shell(shell)

    compute.recompute_term(term)
    compute.recompute_rollover_pct(term)
    mark(term)
    return ok(term)


@bp.post("/academic-terms/<term_id>/posture-changes")
def change_posture(term_id):
    guard(LMS_ADMIN)
    term = lookup.term(term_id)
    payload = body()
    target = as_enum(payload, "target_posture", POSTURES, required=True)
    as_str(payload, "reason")
    current = term["continuity_posture"]

    require((current, target) in DECLARED_POSTURE, "ERR_INVALID_STATE_TRANSITION",
            "%s -> %s is not a declared posture step." % (current, target))
    if (current, target) == ("NORMAL", "ELEVATED"):
        require(term["lifecycle_state"] in ("IN_SESSION", "FINALS", "GRADING"),
                "ERR_INVALID_STATE_TRANSITION",
                "Escalation requires an in-session, finals or grading term.")
    open_outages = [w for w in lookup.windows_of_term(term["id"])
                    if w["kind"] == "OUTAGE" and w["window_state"] == "OPEN"]
    if (current, target) == ("ELEVATED", "CONTINUITY_MODE"):
        require(len(open_outages) >= 1, "ERR_INVALID_STATE_TRANSITION",
                "CONTINUITY_MODE requires a live outage window on the record.")
    if (current, target) == ("CONTINUITY_MODE", "ELEVATED"):
        require(not open_outages, "ERR_INVALID_STATE_TRANSITION",
                "An open outage window of this term is still standing.")

    set_field(term, "continuity_posture", target)
    # The capacity rule is re-evaluated for every shell of the term, since the
    # overflow ratio is read straight off the posture (PRD 3.4 / 3.9).
    for shell in by_created([
        s for s in lookup.shells_of_term(term["id"])
        if s["provisioning_state"] not in ("REJECTED", "PURGED")
    ]):
        compute.run_capacity(
            shell, term,
            promote=shell["provisioning_state"] in ("PROVISIONED", "PUBLISHED"))
    compute.recompute_term(term)
    mark(term)
    return ok(term)
