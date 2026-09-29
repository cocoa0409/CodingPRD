"""CohortDefinition and CohortMember routes."""
from flask import Blueprint

from auth import actor, require_roles
from db import (COHORT_TYPES, ENTRY_STATUSES, EXCLUSION_CODES, OUTCOMES,
                READ_ROLES, public, stamp_new, store, touch)
from errors import fail
from response import created, filter_eq, ok, paginate
from svc_cohort import (cascade_exclusion_decision, rate_divergence_pp,
                        recompute_cohort)
from svc_common import get_cohort, get_cycle, get_member, members_of
from svc_cycle import require_not_archived, require_not_frozen
from validation import get_body, opt_enum, opt_string, req_enum, req_string

bp = Blueprint("cohorts", __name__)


def serialize_cohort(row):
    return public(row)


def serialize_member(row):
    return public(row)


@bp.post("/reporting-cycles/<cycle_id>/cohorts")
def create_cohort(cycle_id):
    require_roles("RegistrarOfficer")
    body = get_body()
    cohort_type = req_enum(body, "cohort_type", COHORT_TYPES)
    entry_term = req_string(body, "entry_term", 3, 32)
    publication_metric_key = req_string(body, "publication_metric_key", 3, 64)
    cycle = get_cycle(cycle_id)
    require_not_frozen(cycle)
    for peer in store.cohorts.values():
        if (peer["cycle_id"] == cycle_id and peer["cohort_type"] == cohort_type
                and peer["entry_term"] == entry_term):
            fail("ERR_DUPLICATE_COHORT",
                 "a cohort of this type already exists for the entry term")
    row = {
        "cycle_id": cycle_id,
        "cohort_type": cohort_type,
        "entry_term": entry_term,
        "publication_metric_key": publication_metric_key,
        "status": "DRAFT",
        "initial_count": 0,
        "exclusion_count": 0,
        "adjusted_count": 0,
        "completers_count": 0,
        "retained_count": 0,
        "federal_rate_pct": None,
        "ranking_rate_pct": None,
        "locked_at": None,
    }
    stamp_new(row)
    store.cohorts[row["id"]] = row
    return created(serialize_cohort(row))


@bp.get("/cohorts/<cohort_id>")
def read_cohort(cohort_id):
    require_roles(*READ_ROLES)
    return ok(serialize_cohort(get_cohort(cohort_id)))


@bp.get("/cohorts")
def list_cohorts():
    require_roles(*READ_ROLES)
    rows = sorted(store.cohorts.values(),
                  key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    rows = filter_eq(rows, {"cycle_id": "cycle_id", "cohort_type": "cohort_type",
                            "status": "status"})
    return paginate(rows, serialize_cohort)


@bp.post("/cohorts/<cohort_id>/lock")
def lock_cohort(cohort_id):
    require_roles("RegistrarOfficer")
    cohort = get_cohort(cohort_id)
    cycle = get_cycle(cohort["cycle_id"])
    require_not_archived(cycle)
    if cohort["status"] != "DRAFT":
        fail("ERR_COHORT_LOCKED", "the cohort roster is already locked")
    members = members_of(cohort_id)
    if any(m["exclusion_status"] == "CLAIMED" for m in members):
        fail("ERR_UNRESOLVED_EXCLUSION_CLAIM",
             "every exclusion claim must be reviewed before the roster is locked")
    recompute_cohort(cohort)
    if cohort["initial_count"] < 1:
        fail("ERR_EMPTY_COHORT", "the cohort has no members")
    if cohort["adjusted_count"] < 1:
        fail("ERR_EMPTY_COHORT_DENOMINATOR",
             "the adjusted denominator of the cohort is zero")
    cohort["status"] = "LOCKED"
    cohort["locked_at"] = store.now_iso()
    touch(cohort)
    return ok(serialize_cohort(cohort))


@bp.get("/cohorts/<cohort_id>/rate-summary")
def rate_summary(cohort_id):
    require_roles(*READ_ROLES)
    cohort = get_cohort(cohort_id)
    return ok({
        "federal_rate_pct": cohort.get("federal_rate_pct"),
        "ranking_rate_pct": cohort.get("ranking_rate_pct"),
        "rate_divergence_pp": rate_divergence_pp(cohort),
        "initial_count": cohort["initial_count"],
        "adjusted_count": cohort["adjusted_count"],
        "exclusion_count": cohort["exclusion_count"],
        "completers_count": cohort["completers_count"],
        "retained_count": cohort["retained_count"],
    })


# ---------------------------------------------------------------- CohortMember


@bp.post("/cohorts/<cohort_id>/members")
def create_member(cohort_id):
    require_roles("RegistrarOfficer")
    body = get_body()
    student_local_id = req_string(body, "student_local_id", 3, 32)
    entry_status = req_enum(body, "entry_status", ENTRY_STATUSES)
    outcome = opt_enum(body, "outcome", OUTCOMES)
    cohort = get_cohort(cohort_id)
    cycle = get_cycle(cohort["cycle_id"])
    require_not_frozen(cycle)
    if cohort["status"] != "DRAFT":
        fail("ERR_COHORT_LOCKED", "the cohort roster is locked")
    for peer in members_of(cohort_id):
        if peer["student_local_id"] == student_local_id:
            fail("ERR_DUPLICATE_MEMBER", "this student is already on the cohort roster")
    row = {
        "cohort_id": cohort_id,
        "student_local_id": student_local_id,
        "entry_status": entry_status,
        "outcome": outcome if outcome is not None else "STILL_ENROLLED",
        "exclusion_status": "NONE",
        "exclusion_code": None,
        "exclusion_evidence_note": None,
        "exclusion_claimed_by_user_id": None,
        "exclusion_reviewed_by_user_id": None,
        "review_note": None,
    }
    stamp_new(row)
    store.members[row["id"]] = row
    recompute_cohort(cohort)
    touch(cohort)
    return created(serialize_member(row))


@bp.get("/cohort-members/<member_id>")
def read_member(member_id):
    require_roles(*READ_ROLES)
    return ok(serialize_member(get_member(member_id)))


@bp.get("/cohort-members")
def list_members():
    require_roles(*READ_ROLES)
    rows = sorted(store.members.values(),
                  key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    rows = filter_eq(rows, {"cohort_id": "cohort_id",
                            "exclusion_status": "exclusion_status",
                            "outcome": "outcome"})
    return paginate(rows, serialize_member)


@bp.patch("/cohort-members/<member_id>")
def record_outcome(member_id):
    require_roles("RegistrarOfficer")
    body = get_body()
    outcome = req_enum(body, "outcome", OUTCOMES)
    member = get_member(member_id)
    cohort = get_cohort(member["cohort_id"])
    cycle = get_cycle(cohort["cycle_id"])
    require_not_frozen(cycle)
    if cohort["status"] != "DRAFT":
        fail("ERR_COHORT_LOCKED", "the cohort roster is locked")
    member["outcome"] = outcome
    touch(member)
    recompute_cohort(cohort)
    touch(cohort)
    return ok(serialize_member(member))


@bp.post("/cohort-members/<member_id>/exclusion-claim")
def exclusion_claim(member_id):
    require_roles("RegistrarOfficer")
    body = get_body()
    exclusion_code = req_string(body, "exclusion_code", 1, None)
    note = req_string(body, "exclusion_evidence_note", 10, 500)
    member = get_member(member_id)
    cohort = get_cohort(member["cohort_id"])
    cycle = get_cycle(cohort["cycle_id"])
    require_not_archived(cycle)
    if member["exclusion_status"] not in ("NONE", "DENIED"):
        fail("ERR_INVALID_EXCLUSION_STATE",
             "only an unclaimed or denied exclusion can be filed")
    if exclusion_code not in EXCLUSION_CODES:
        fail("ERR_INVALID_EXCLUSION_CODE",
             "the exclusion code is outside the federal allowable list")
    member["exclusion_status"] = "CLAIMED"
    member["exclusion_code"] = exclusion_code
    member["exclusion_evidence_note"] = note
    member["exclusion_claimed_by_user_id"] = actor()
    touch(member)
    return ok(serialize_member(member))


@bp.post("/cohort-members/<member_id>/exclusion-review")
def exclusion_review(member_id):
    require_roles("IRDirector")
    body = get_body()
    decision = req_enum(body, "decision", ("APPROVE", "DENY"))
    note = opt_string(body, "review_note", 1, 500)
    member = get_member(member_id)
    cohort = get_cohort(member["cohort_id"])
    cycle = get_cycle(cohort["cycle_id"])
    require_not_archived(cycle)
    if decision == "APPROVE":
        if member["exclusion_status"] != "CLAIMED":
            fail("ERR_INVALID_EXCLUSION_STATE", "only a CLAIMED exclusion can be approved")
    elif member["exclusion_status"] not in ("CLAIMED", "APPROVED"):
        fail("ERR_INVALID_EXCLUSION_STATE",
             "only a CLAIMED or APPROVED exclusion can be denied")
    was_approved = member["exclusion_status"] == "APPROVED"
    member["exclusion_status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    member["exclusion_reviewed_by_user_id"] = actor()
    if note is not None:
        member["review_note"] = note
    touch(member)
    recompute_cohort(cohort)
    touch(cohort)
    if decision == "APPROVE" or was_approved:
        cascade_exclusion_decision(cohort)
    return ok(serialize_member(member))
