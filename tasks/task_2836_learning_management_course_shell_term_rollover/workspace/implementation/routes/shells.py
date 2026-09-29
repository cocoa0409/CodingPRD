"""Course shells -- PRD 3.3 (provisioning, sandbox governance, archival tail)."""

from decimal import Decimal

from flask import Blueprint, request

import lookup
from db import by_created, db, mark, new_record, now, set_field
from errors import require
from middleware import (INSTRUCTOR, LMS_ADMIN, REGISTRAR, STUDENT, as_enum,
                        as_int, as_str, body)
from routes.common import apply_filters, arg, created, guard, listing, ok
from services import access, cascade, compute
from util import add_days, q2

bp = Blueprint("shells", __name__)

SHELL_TYPES = ("OFFICIAL", "SANDBOX", "DEV")
PROVISIONING_STATES = ("REQUESTED", "PROVISIONED", "PUBLISHED", "REJECTED",
                       "MERGED", "CONCLUDED", "ARCHIVED", "PURGED")
DEFAULT_BASE_SEAT_CAP = 25
ENROLLABLE_STATES = ("PROVISIONED", "PUBLISHED")


def sandbox_expiry(term, shell_type):
    if shell_type in ("SANDBOX", "DEV"):
        return add_days(term["term_end_at"], compute.SANDBOX_EXPIRY_DAYS)
    return None


@bp.post("/course-shells")
def create_shell():
    guard(LMS_ADMIN)
    payload = body()
    term = lookup.fk(payload, "term_id", "terms")
    owner = lookup.fk(payload, "owner_person_id", "people")
    if term is None:
        as_str(payload, "term_id", required=True)
    if owner is None:
        as_str(payload, "owner_person_id", required=True)
    section_code = as_str(payload, "sis_section_code", required=True)
    shell_type = as_enum(payload, "shell_type", SHELL_TYPES, required=True)
    base_seat_cap = as_int(payload, "base_seat_cap", default=DEFAULT_BASE_SEAT_CAP,
                           low=1, high=2000)

    if shell_type == "OFFICIAL":
        for other in lookup.shells_of_term(term["id"]):
            if (other["shell_type"] == "OFFICIAL"
                    and other["sis_section_code"] == section_code
                    and other["provisioning_state"] not in ("REJECTED", "PURGED")):
                require(False, "ERR_DUPLICATE_SECTION_CODE",
                        "sis_section_code '%s' already exists in this term."
                        % section_code)
    if shell_type in ("SANDBOX", "DEV"):
        live = [s for s in db.shells.values()
                if s["owner_person_id"] == owner["id"]
                and s["shell_type"] in ("SANDBOX", "DEV")
                and s["provisioning_state"] not in ("REJECTED", "PURGED")]
        require(len(live) < compute.MAX_LIVE_SANDBOX_SHELLS,
                "ERR_SANDBOX_QUOTA_EXCEEDED",
                "This person already owns %d live sandbox or dev shells."
                % len(live))

    shell = new_record(
        _kind="shell",
        term_id=term["id"],
        owner_person_id=owner["id"],
        sis_section_code=section_code,
        shell_type=shell_type,
        provisioning_state="REQUESTED",
        base_seat_cap=base_seat_cap,
        effective_seat_cap=base_seat_cap,
        active_enrollment_count=0,
        waitlisted_enrollment_count=0,
        seat_utilization_pct=q2(Decimal(0)),
        overflow_flag=False,
        storage_mb=q2(Decimal(0)),
        merged_into_shell_id=None,
        absorbed_child_count=0,
        content_item_count=0,
        total_points_possible=q2(Decimal(0)),
        blocked_placement_count=0,
        publish_readiness=True,
        sandbox_expires_at=sandbox_expiry(term, shell_type),
        reject_reason=None,
        unpublish_reason=None,
    )
    shell["effective_seat_cap"] = compute.frozen_seat_cap(shell, term)
    db.shells[shell["id"]] = shell
    compute.recompute_rollover_pct(term)
    return created(shell)


@bp.get("/course-shells")
def list_shells():
    guard(LMS_ADMIN, REGISTRAR, INSTRUCTOR)
    records = apply_filters(db.shells.values(), {
        "term_id": "term_id",
        "owner_person_id": "owner_person_id",
        "merged_into_shell_id": "merged_into_shell_id",
        "shell_type": "shell_type",
        "provisioning_state": "provisioning_state",
    })
    # Soft-delete semantics: a PURGED shell disappears from listings unless the
    # caller explicitly filters on that state (PRD 3.3).
    if arg("provisioning_state") != "PURGED":
        records = [r for r in records if r["provisioning_state"] != "PURGED"]
    return listing(records)


@bp.get("/course-shells/<shell_id>")
def read_shell(shell_id):
    guard(LMS_ADMIN, REGISTRAR, INSTRUCTOR, STUDENT)
    shell = lookup.shell(shell_id)
    access.student_gate(db.terms.get(shell["term_id"]))
    return ok(shell)


@bp.post("/course-shells/<shell_id>/provisioning-decisions")
def decide_provisioning(shell_id):
    guard(LMS_ADMIN)
    shell = lookup.shell(shell_id)
    payload = body()
    decision = as_enum(payload, "decision", ("APPROVE", "REJECT"), required=True)
    reason = as_str(payload, "reason")
    term = db.terms[shell["term_id"]]

    require(shell["provisioning_state"] == "REQUESTED",
            "ERR_INVALID_STATE_TRANSITION",
            "Only a REQUESTED shell awaits a provisioning decision.")
    if decision == "APPROVE":
        require(term["lifecycle_state"] in ("PLANNING", "REGISTRATION_OPEN",
                                           "IN_SESSION"),
                "ERR_INVALID_STATE_TRANSITION",
                "The term is past the provisioning window.")
        owner = db.people.get(shell["owner_person_id"])
        require(owner is not None and owner["access_revoked_at"] is None,
                "ERR_FERPA_BLOCK_ACTIVE",
                "The owner's LMS access has been withdrawn.")
        set_field(shell, "provisioning_state", "PROVISIONED")
        set_field(shell, "effective_seat_cap", shell["base_seat_cap"])
        set_field(shell, "publish_readiness", True)
        set_field(shell, "sandbox_expires_at",
                  sandbox_expiry(term, shell["shell_type"]))
    else:
        set_field(shell, "provisioning_state", "REJECTED")
        set_field(shell, "reject_reason", reason)
        set_field(shell, "storage_mb", q2(Decimal(0)))
        compute.recompute_chargeback(db.people.get(shell["owner_person_id"]))
        compute.recompute_rollover_pct(term)
        compute.recompute_term(term)
    mark(shell)
    return ok(shell)


@bp.post("/course-shells/<shell_id>/publish")
def publish_shell(shell_id):
    guard(LMS_ADMIN, INSTRUCTOR)
    shell = lookup.shell(shell_id)
    body()
    term = db.terms[shell["term_id"]]
    require(shell["provisioning_state"] == "PROVISIONED",
            "ERR_INVALID_STATE_TRANSITION",
            "Only a PROVISIONED shell may be published.")
    require(term["lifecycle_state"] in ("REGISTRATION_OPEN", "IN_SESSION"),
            "ERR_INVALID_STATE_TRANSITION",
            "The term's lifecycle state does not permit publishing.")
    require(shell["merged_into_shell_id"] is None, "ERR_SHELL_ALREADY_MERGED",
            "An absorbed shell has no independent existence.")
    require(term["continuity_posture"] != "CONTINUITY_MODE",
            "ERR_TERM_POSTURE_FROZEN",
            "Authoring is frozen while the term is in CONTINUITY_MODE.")
    require(shell["publish_readiness"], "ERR_SHELL_NOT_PUBLISH_READY",
            "The shell is not publish-ready.")
    require(shell["shell_type"] == "OFFICIAL", "ERR_SANDBOX_NOT_PUBLISHABLE",
            "Sandbox and development shells are never student-visible.")
    set_field(shell, "provisioning_state", "PUBLISHED")
    mark(shell)
    compute.recompute_shell(shell)
    compute.recompute_term(term)
    return ok(shell)


@bp.post("/course-shells/<shell_id>/unpublish")
def unpublish(shell_id):
    guard(LMS_ADMIN, INSTRUCTOR)
    shell = lookup.shell(shell_id)
    payload = body()
    reason = as_str(payload, "reason")
    term = db.terms[shell["term_id"]]
    require(shell["provisioning_state"] == "PUBLISHED",
            "ERR_INVALID_STATE_TRANSITION",
            "Only a PUBLISHED shell may be unpublished.")
    require(term["continuity_posture"] != "CONTINUITY_MODE",
            "ERR_TERM_POSTURE_FROZEN",
            "Manual unpublishing is frozen while the term is in CONTINUITY_MODE.")
    cascade.unpublish_shell(shell, reason)
    mark(shell)
    return ok(shell)


@bp.post("/course-shells/<shell_id>/lifecycle-transitions")
def transition_shell(shell_id):
    guard(REGISTRAR)
    shell = lookup.shell(shell_id)
    payload = body()
    target = as_enum(payload, "target_state", PROVISIONING_STATES, required=True)
    as_str(payload, "reason")
    term = db.terms[shell["term_id"]]
    current = shell["provisioning_state"]

    if target == "CONCLUDED":
        require(current in ("PROVISIONED", "PUBLISHED"),
                "ERR_INVALID_STATE_TRANSITION",
                "%s -> CONCLUDED is not a declared shell transition." % current)
        require(shell["merged_into_shell_id"] is None, "ERR_SHELL_ALREADY_MERGED",
                "An absorbed shell cannot be concluded on its own.")
        cascade.conclude_shell(shell)
    elif target == "ARCHIVED":
        require(current == "CONCLUDED", "ERR_INVALID_STATE_TRANSITION",
                "%s -> ARCHIVED is not a declared shell transition." % current)
        require(term["lifecycle_state"] in ("CLOSED", "ARCHIVED"),
                "ERR_INVALID_STATE_TRANSITION",
                "The shell's term has not reached CLOSED.")
        cascade.archive_shell(shell)
    elif target == "PURGED":
        require(current == "ARCHIVED", "ERR_INVALID_STATE_TRANSITION",
                "%s -> PURGED is not a declared shell transition." % current)
        require(term["retention_class"] != "LEGAL_HOLD",
                "ERR_RETENTION_HOLD_ACTIVE",
                "This shell's term is under legal hold.")
        require(term["retention_purge_at"] is not None
                and now() >= term["retention_purge_at"],
                "ERR_PURGE_NOT_DUE",
                "The retention horizon has not been reached.")
        cascade.purge_shell(shell)
    else:
        require(False, "ERR_INVALID_STATE_TRANSITION",
                "%s -> %s is not a declared shell transition." % (current, target))
    mark(shell)
    return ok(shell)
