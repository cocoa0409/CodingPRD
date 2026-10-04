"""Certification projects, samples, construction records, and the decide
endpoint (PRD 3.2-3.4)."""
from flask import Blueprint

import clock
import db
from constants import (
    PROJECT_DECISION_OUTCOMES, ROLE_ENGINEER, ROLE_REP, ROLE_REVIEWER,
    SAMPLE_CONDITIONS, TRIAGE_DECISIONS,
)
from errors import (
    ApiError, ERR_ALREADY_TERMINAL, ERR_CATEGORY_STANDARD_MISMATCH,
    ERR_DUPLICATE_COMPONENT_SLOT, ERR_INVALID_STATE,
    ERR_MANDATORY_PROTOCOL_FAILING, ERR_MANUFACTURER_SUSPENDED,
    ERR_MISSING_REQUIRED_SLOT, ERR_NOT_FOUND, ERR_PROJECT_NOT_EVALUABLE,
    ERR_SAFETY_PROTOCOL_NOT_PASSED, ERR_SAMPLE_NOT_ACCEPTED,
    ERR_SEGREGATION_OF_DUTIES, ERR_STALE_VERSION, ERR_STANDARD_NOT_ACTIVE,
    ERR_UNKNOWN_PROTOCOL_CODE,
)
from middleware import any_authenticated, check_rep_ownership, require_roles
from response import paginated_list, success
from services import calc, lifecycle
from validation import (
    body, opt_int, opt_list, req_enum, req_int, req_list, req_number, req_str,
)
import validation as v

bp = Blueprint("projects", __name__)


def get_project_or_404(project_id):
    project = db.projects.get(project_id)
    if project is None:
        raise ApiError(ERR_NOT_FOUND, "project not found")
    return project


def get_sample_or_404(sample_id):
    sample = db.samples.get(sample_id)
    if sample is None:
        raise ApiError(ERR_NOT_FOUND, "sample not found")
    return sample


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@bp.post("/projects")
@require_roles(ROLE_REP)
def create_project(user_id, role):
    payload = body(required=True)
    factory_id = req_str(payload, "factory_id")
    category_code = req_str(payload, "category_code")
    standard_id = req_str(payload, "standard_id")
    product_model = req_str(payload, "product_model")

    if factory_id not in db.factories:
        raise ApiError(ERR_NOT_FOUND, "factory not found")
    standard = db.standards.get(standard_id)
    if standard is None:
        raise ApiError(ERR_NOT_FOUND, "standard not found")

    manufacturer = db.manufacturers[user_id]  # resolved at authentication
    if manufacturer["status"] != "ACTIVE":
        raise ApiError(ERR_MANUFACTURER_SUSPENDED,
                       "manufacturer is SUSPENDED; cannot open projects")
    if standard["status"] != "ACTIVE":
        raise ApiError(ERR_STANDARD_NOT_ACTIVE,
                       "selected standard is %s" % standard["status"])
    if category_code != standard["category_code"]:
        raise ApiError(ERR_CATEGORY_STANDARD_MISMATCH,
                       "category_code differs from the standard's category_code")

    project = db.new_entity(db.projects, {
        "manufacturer_id": user_id,
        "factory_id": factory_id,
        "category_code": category_code,
        "standard_id": standard_id,
        "product_model": product_model,
        "retest_count": 0,
        "fee_snapshot_cents": None,
        "status": "STANDARD_SELECTED",
        "decided_by": None,
        "decided_on": None,
    })
    return success(project, status=201)


@bp.get("/projects")
@any_authenticated
def list_projects(user_id, role):
    items = db.sorted_items(db.projects)
    for field in ("manufacturer_id", "factory_id", "standard_id", "status"):
        wanted = _query_arg(field)
        if wanted is not None:
            items = [p for p in items if p[field] == wanted]
    page, pagination = paginated_list(items)
    return success(page, pagination=pagination)


def _query_arg(field):
    from flask import request
    return request.args.get(field)


@bp.get("/projects/<project_id>")
@any_authenticated
def get_project(project_id, user_id, role):
    return success(get_project_or_404(project_id))


@bp.post("/projects/<project_id>/decide")
@require_roles(ROLE_REVIEWER)
def decide_project(project_id, user_id, role):
    project = get_project_or_404(project_id)
    payload = body(required=True)
    outcome = req_enum(payload, "outcome", PROJECT_DECISION_OUTCOMES)
    validity_months = opt_int(payload, "validity_months", minimum=1)
    permitted_variations = opt_list(payload, "permitted_variations")

    if project["status"] != "EVALUATION":
        raise ApiError(ERR_PROJECT_NOT_EVALUABLE,
                       "project is %s, not EVALUATION" % project["status"])

    # Compliance gate: segregation of duties (all outcomes).
    for sample in db.samples.values():
        if sample["project_id"] != project_id:
            continue
        for result in sample["results"]:
            if result["recorded_by"] == user_id:
                raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                               "deciding reviewer recorded a result on this project")

    standard = db.standards[project["standard_id"]]
    latest = calc.latest_results(project_id)

    if outcome == "APPROVED":
        # Every safety_critical protocol's latest outcome must be PASS.
        for protocol in standard["test_protocols"]:
            if not protocol["safety_critical"]:
                continue
            entry = latest.get(protocol["protocol_code"])
            if entry is None or entry[0]["outcome"] != "PASS":
                raise ApiError(ERR_SAFETY_PROTOCOL_NOT_PASSED,
                               "safety-critical protocol %s has not passed"
                               % protocol["protocol_code"])
        # Every mandatory protocol's latest outcome must be PASS or CONDITIONAL.
        for protocol in standard["test_protocols"]:
            if not protocol["mandatory"]:
                continue
            entry = latest.get(protocol["protocol_code"])
            if entry is None or entry[0]["outcome"] not in ("PASS", "CONDITIONAL"):
                raise ApiError(ERR_MANDATORY_PROTOCOL_FAILING,
                               "mandatory protocol %s is failing"
                               % protocol["protocol_code"])

    if outcome == "APPROVED":
        _issue_certification(project, standard, validity_months, permitted_variations)
        project["status"] = "APPROVED"
    elif outcome == "REJECTED":
        project["status"] = "REJECTED"
    else:  # RETEST: loop back to TESTING, fee recomputed on next entry
        project["retest_count"] += 1
        project["fee_snapshot_cents"] = None
        project["status"] = "TESTING"

    project["decided_by"] = user_id
    project["decided_on"] = clock.now()
    db.mutate(project)
    return success(project)


def _issue_certification(project, standard, validity_months, permitted_variations):
    frozen = calc.frozen_record(project["id"])
    issued_on = clock.now()
    expires_on = (calc.add_months(issued_on, validity_months)
                  if validity_months is not None else None)
    db.new_entity(db.certifications, {
        "project_id": project["id"],
        "manufacturer_id": project["manufacturer_id"],
        "factory_id": project["factory_id"],
        "standard_id": project["standard_id"],
        "construction_record_id": frozen["id"],
        "construction_record_revision": frozen["revision_no"],
        "listing_number": db.mint_listing_number(),
        "permitted_variations": permitted_variations or [],
        "issued_on": issued_on,
        "expires_on": expires_on,
        "status": "ACTIVE",
        "suspension_causes": [],
    })


# ---------------------------------------------------------------------------
# Samples
# ---------------------------------------------------------------------------

@bp.post("/projects/<project_id>/samples")
@require_roles(ROLE_REP)
def submit_sample(project_id, user_id, role):
    project = get_project_or_404(project_id)
    check_rep_ownership(user_id, role, project["manufacturer_id"])
    payload = body(required=True)
    sample = db.new_entity(db.samples, {
        "project_id": project_id,
        "serial_no": req_str(payload, "serial_no"),
        "condition": req_enum(payload, "condition", SAMPLE_CONDITIONS),
        "status": "SUBMITTED",
        "triaged_by": None,
        "results": [],
    })
    return success(sample, status=201)


@bp.get("/projects/<project_id>/samples")
@any_authenticated
def list_samples(project_id, user_id, role):
    get_project_or_404(project_id)
    items = [s for s in db.sorted_items(db.samples) if s["project_id"] == project_id]
    page, pagination = paginated_list(items)
    return success(page, pagination=pagination)


@bp.post("/samples/<sample_id>/triage")
@require_roles(ROLE_ENGINEER)
def triage_sample(sample_id, user_id, role):
    sample = get_sample_or_404(sample_id)
    payload = body(required=True)
    decision = req_enum(payload, "decision", TRIAGE_DECISIONS)

    if sample["status"] == "REJECTED":
        raise ApiError(ERR_ALREADY_TERMINAL, "sample is REJECTED (terminal)")
    if sample["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE,
                       "sample is %s, not SUBMITTED" % sample["status"])

    project = db.projects[sample["project_id"]]
    if decision == "ACCEPT" and project["status"] not in ("STANDARD_SELECTED", "TESTING"):
        raise ApiError(ERR_INVALID_STATE,
                       "project is %s; samples cannot be accepted" % project["status"])

    sample["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    sample["triaged_by"] = user_id
    db.mutate(sample)

    if decision == "ACCEPT" and project["status"] == "STANDARD_SELECTED":
        project["status"] = "TESTING"
        db.mutate(project)
    lifecycle.maybe_advance_project(project)
    return success(sample)


@bp.post("/samples/<sample_id>/results")
@require_roles(ROLE_ENGINEER)
def record_result(sample_id, user_id, role):
    sample = get_sample_or_404(sample_id)
    payload = body(required=True)
    protocol_code = req_str(payload, "protocol_code")
    measured_value = req_number(payload, "measured_value")

    if sample["status"] not in ("ACCEPTED", "TESTED"):
        raise ApiError(ERR_SAMPLE_NOT_ACCEPTED,
                       "sample is %s; results require ACCEPTED or TESTED"
                       % sample["status"])

    project = db.projects[sample["project_id"]]
    standard = db.standards[project["standard_id"]]
    protocol = next((p for p in standard["test_protocols"]
                     if p["protocol_code"] == protocol_code), None)
    if protocol is None:
        raise ApiError(ERR_UNKNOWN_PROTOCOL_CODE,
                       "protocol_code %s is not declared in the pinned standard"
                       % protocol_code)

    outcome, margin = calc.determine_outcome(protocol, measured_value, sample["condition"])
    sample["results"].append({
        "protocol_code": protocol_code,
        "measured_value": measured_value,
        "outcome": outcome,
        "margin": margin,
        "recorded_by": user_id,
        "recorded_at": clock.now(),
        "_seq": db.next_seq(),
    })
    if sample["status"] == "ACCEPTED":
        sample["status"] = "TESTED"
    db.mutate(sample)

    lifecycle.maybe_advance_project(project)
    return success(sample, status=201)


# ---------------------------------------------------------------------------
# Construction records
# ---------------------------------------------------------------------------

@bp.post("/projects/<project_id>/construction-records")
@require_roles(ROLE_REP)
def create_construction_record(project_id, user_id, role):
    project = get_project_or_404(project_id)
    check_rep_ownership(user_id, role, project["manufacturer_id"])
    payload = body(required=True)
    components = req_list(payload, "components")
    expected_project_version = req_int(payload, "expected_project_version")

    # OCC (pipeline stage 5): supersedes a record the client may not have seen.
    if expected_project_version != project["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_project_version does not match the project version")

    parsed_components = []
    for entry in components:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "components entries must be objects")
        parsed_components.append({
            "slot": v.req_str(entry, "slot"),
            "component_name": v.req_str(entry, "component_name"),
            "material": v.req_str(entry, "material"),
            "part_number": v.req_str(entry, "part_number"),
            "rating": entry.get("rating"),
        })

    standard = db.standards[project["standard_id"]]
    seen = set()
    duplicates = set()
    for component in parsed_components:
        slot = component["slot"]
        if slot in seen:
            duplicates.add(slot)
        seen.add(slot)
    missing = [slot for slot in standard["construction_requirements"] if slot not in seen]
    if missing:
        raise ApiError(ERR_MISSING_REQUIRED_SLOT,
                       "missing required slot(s): %s" % ", ".join(missing))
    if duplicates:
        raise ApiError(ERR_DUPLICATE_COMPONENT_SLOT,
                       "duplicate slot(s): %s" % ", ".join(sorted(duplicates)))

    record = _create_revision(project, parsed_components)
    lifecycle.maybe_advance_project(project)
    return success(record, status=201)


def _create_revision(project, components):
    """Freeze a new revision for the project; supersede the prior FROZEN one;
    bump the project version (PRD 3.3)."""
    existing = [cr for cr in db.construction_records.values()
                if cr["project_id"] == project["id"]]
    revision_no = 1 + max((cr["revision_no"] for cr in existing), default=0)
    for record in existing:
        if record["status"] == "FROZEN":
            record["status"] = "SUPERSEDED"
            db.mutate(record)
    record = db.new_entity(db.construction_records, {
        "project_id": project["id"],
        "revision_no": revision_no,
        "components": components,
        "status": "FROZEN",
    })
    db.mutate(project)
    return record


@bp.get("/projects/<project_id>/construction-records")
@any_authenticated
def list_construction_records(project_id, user_id, role):
    get_project_or_404(project_id)
    items = [cr for cr in db.sorted_items(db.construction_records)
             if cr["project_id"] == project_id]
    page, pagination = paginated_list(items)
    return success(page, pagination=pagination)
