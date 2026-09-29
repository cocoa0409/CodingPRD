"""Change records, editorial passes, release-note compilation and publication."""
from flask import Blueprint

import calc
from core import (
    all_of,
    base_record,
    by_seq,
    commit,
    db,
    fail,
    must_get,
    ok,
    ok_list,
    page,
    public,
    public_list,
    snap,
    touch,
)
from validate import (
    authenticate,
    body,
    filters,
    pagination,
    v_id,
    v_int,
    v_str,
    v_str_array,
    v_enum,
)

bp = Blueprint("change_routes", __name__)

SEVERITIES = ("BREAKING", "SECURITY", "MAJOR", "MINOR", "PATCH")
CATEGORIES = ("FEATURE", "FIX", "PERFORMANCE", "SECURITY_PATCH", "DEPRECATION")


@bp.post("/change-records")
def create_change_record():
    caller = authenticate(("DocsLead", "Writer"))
    data = body()
    release_train_id = v_id(data, "release_train_id")
    internal_summary = v_str(data, "internal_summary", 1, 300)
    severity = v_enum(data, "severity", SEVERITIES)
    category = v_enum(data, "category", CATEGORIES)
    affected_component = v_str(data, "affected_component", 1, 60)

    train = must_get("release_trains", release_train_id)

    record = base_record()
    record.update({
        "release_train_id": train["id"],
        "internal_summary": internal_summary,
        "customer_facing_text": None,
        "severity": severity,
        "category": category,
        "affected_component": affected_component,
        "state": "SUBMITTED",
        "submitted_by_user_id": caller.user_id,
        "editorial_by_user_id": None,
        "terminology_blocker_count": 0,
        "rework_count": 0,
        "exclusion_reason": None,
    })
    db.change_records[record["id"]] = record
    return ok(public(record), 201)


@bp.get("/change-records/<record_id>")
def get_change_record(record_id):
    authenticate(("DocsLead", "Writer", "SupportAnalyst"))
    record = must_get("change_records", record_id)
    return ok(public(record))


@bp.get("/change-records")
def list_change_records():
    authenticate(("DocsLead", "Writer", "SupportAnalyst"))
    limit, offset = pagination()
    keys = ("release_train_id", "state", "severity", "category")
    f = filters(*keys)
    rows = all_of("change_records")
    for key in keys:
        if f[key] is not None:
            rows = [r for r in rows if r[key] == f[key]]
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)


@bp.post("/change-records/<record_id>/editorial-pass")
def editorial_pass(record_id):
    caller = authenticate(("DocsLead",))
    data = body()
    customer_facing_text = v_str(data, "customer_facing_text", 10, 300)
    used_terms = v_str_array(data, "used_terms", 0, 200, 1, 60)

    record = must_get("change_records", record_id)
    if record["state"] not in ("SUBMITTED", "REWORK_REQUESTED"):
        fail("ERR_CHANGE_RECORD_NOT_EDITABLE",
             "A change record in state %s cannot be edited." % record["state"])
    if caller.user_id == record["submitted_by_user_id"]:
        fail("ERR_EDITORIAL_SOD_VIOLATION",
             "The editor of a change record may not be its submitter.")

    blockers, _warnings, _violating = calc.terminology_scan(used_terms)
    if blockers == 0:
        record["state"] = "EDITORIALLY_APPROVED"
        record["customer_facing_text"] = customer_facing_text
        record["editorial_by_user_id"] = caller.user_id
        record["terminology_blocker_count"] = 0
    else:
        record["state"] = "REWORK_REQUESTED"
        record["rework_count"] = record["rework_count"] + 1
        record["terminology_blocker_count"] = blockers
    touch(record)
    return ok(public(record))


@bp.post("/change-records/<record_id>/exclude")
def exclude_change_record(record_id):
    authenticate(("DocsLead",))
    data = body()
    exclusion_reason = v_str(data, "exclusion_reason", 5, 200)

    record = must_get("change_records", record_id)
    if record["state"] not in ("SUBMITTED", "REWORK_REQUESTED"):
        fail("ERR_CHANGE_RECORD_NOT_EDITABLE",
             "A change record in state %s cannot be excluded." % record["state"])
    record["state"] = "EXCLUDED"
    record["exclusion_reason"] = exclusion_reason
    touch(record)
    return ok(public(record))


# ---------------------------------------------------------------------------
# Release notes
# ---------------------------------------------------------------------------
@bp.post("/release-notes")
def compile_release_note():
    authenticate(("DocsLead",))
    data = body()
    doc_set_version_id = v_id(data, "doc_set_version_id")
    expected_version = v_int(data, "expected_doc_set_version_version")

    doc_set = must_get("doc_set_versions", doc_set_version_id)
    if expected_version != doc_set["version"]:
        fail("ERR_STALE_DOC_SET_VERSION",
             "The documentation set has moved on since you last read it.")
    if doc_set["status"] != "PUBLISHED":
        fail("ERR_DOC_SET_NOT_PUBLISHED",
             "A release note compiles only into a published documentation set.")

    train_id = doc_set["release_train_id"]
    included = calc.approved_change_records(train_id)
    if not included:
        fail("ERR_NO_PUBLISHABLE_CHANGES",
             "No change record of this train is editorially approved.")

    for existing in all_of("release_notes"):
        if existing["doc_set_version_id"] == doc_set["id"] and existing["status"] == "COMPILED":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    coverage, score = calc.impact_figures(
        train_id, included, calc.PROVISIONAL_COUNTED_STATUSES)

    note = base_record()
    note.update({
        "release_train_id": train_id,
        "doc_set_version_id": doc_set["id"],
        "status": "COMPILED",
        "included_change_record_ids": calc.ordered_included_ids(included),
        "severity_counts": calc.severity_counts(included),
        "headline_severity": calc.headline_severity(included),
        "coverage_factor_provisional": coverage,
        "coverage_factor_final": None,
        "impact_score_provisional": score,
        "impact_score_final": None,
        "compiled_at": db.now_iso(),
        "published_at": None,
    })
    db.release_notes[note["id"]] = note
    touch(doc_set)
    return ok(public(note), 201)


@bp.get("/release-notes/<note_id>")
def get_release_note(note_id):
    authenticate(("DocsLead", "SupportAnalyst"))
    note = must_get("release_notes", note_id)
    return ok(public(note))


@bp.get("/release-notes")
def list_release_notes():
    authenticate(("DocsLead", "SupportAnalyst"))
    limit, offset = pagination()
    keys = ("release_train_id", "doc_set_version_id", "status")
    f = filters(*keys)
    rows = all_of("release_notes")
    for key in keys:
        if f[key] is not None:
            rows = [r for r in rows if r[key] == f[key]]
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)


@bp.post("/release-notes/<note_id>/publish")
def publish_release_note(note_id):
    authenticate(("DocsLead",))
    body()
    note = must_get("release_notes", note_id)
    if note["status"] == "PUBLISHED":
        fail("ERR_RELEASE_NOTE_ALREADY_PUBLISHED", "This release note is already published.")
    if note["status"] == "SUPERSEDED":
        fail("ERR_RELEASE_NOTE_SUPERSEDED",
             "This release note was superseded by a later compilation.")

    included = []
    for record_id in note["included_change_record_ids"]:
        record = db.change_records.get(record_id)
        if record is not None:
            included.append(record)

    for record in included:
        if record["severity"] != "BREAKING":
            continue
        covered = False
        for notice in db.deprecation_notices.values():
            if (notice["release_train_id"] == note["release_train_id"]
                    and notice["feature_key"] == record["affected_component"]
                    and notice["status"] == "PUBLISHED"):
                covered = True
                break
        if not covered:
            fail("ERR_MIGRATION_GUIDE_NOT_PUBLISHED",
                 "A breaking change has no published migration path.")

    ordered = by_seq(included)
    coverage, score = calc.impact_figures(
        note["release_train_id"], ordered, calc.FINAL_COUNTED_STATUSES)
    note["coverage_factor_final"] = coverage
    note["impact_score_final"] = score
    note["status"] = "PUBLISHED"
    note["published_at"] = db.now_iso()
    touch(note)

    for record in ordered:
        if record["state"] == "EDITORIALLY_APPROVED":
            record["state"] = "PUBLISHED"
            touch(record)
    return ok(public(note))
