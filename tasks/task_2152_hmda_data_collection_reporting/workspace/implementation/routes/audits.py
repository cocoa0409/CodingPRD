"""The data scrub: audit sampling, findings and defect rates (PRD 3.8)."""

from flask import Blueprint

import calc
import constants as C
import serializers as S
import store
from auth import authenticate
from errors import fail
from response import array_response, object_response
from validate import (Field, check, enum_filter, json_body, lookup, paginate,
                      pagination)

bp = Blueprint("audits", __name__)

BACK_OFFICE_READ_ROLES = ["SystemAdmin", "InstitutionAdmin", "ComplianceAnalyst",
                          "ComplianceOfficer", "Examiner"]

SAMPLE_FIELDS = [
    Field("institution_id", "string", required=True),
    Field("method", "string", required=True, enum=C.AUDIT_METHODS),
    Field("period_start", "datetime", required=True),
    Field("period_end", "datetime", required=True),
    Field("fields_reviewed_per_record", "integer", required=True, minimum=1),
]

FINDING_FIELDS = [
    Field("audit_sample_id", "string", required=True),
    Field("application_id", "string", required=True),
    Field("field_name", "string", required=True),
    Field("recorded_value", "string", required=True),
    Field("source_document_value", "string", required=True),
    Field("severity", "string", required=True, enum=C.AUDIT_SEVERITIES),
    Field("remediation_start", "datetime", required=True),
    Field("remediation_end", "datetime", required=True),
]

CLOSE_FIELDS = [Field("defect_rate_basis", "string", required=True, enum=C.DEFECT_RATE_BASES)]


def _recompute_sample_defects(sample):
    findings = [f for f in store.audit_findings.values()
                if f["audit_sample_id"] == sample["id"] and f["is_defect"]]
    sample["defect_count"] = len(findings)
    sample["records_with_defect_count"] = len(set(f["application_id"] for f in findings))


@bp.route("/hmda/audit-samples", methods=["POST"])
def create_audit_sample():
    authenticate(["ComplianceAnalyst"])
    body = check(json_body(), SAMPLE_FIELDS)
    inst = lookup(store.institutions, body["institution_id"], "ERR_INSTITUTION_NOT_FOUND")

    # step 14 -- the sampling period is closed
    if body["period_end"] < body["period_start"]:
        fail("ERR_INVALID_WINDOW")

    candidates = [a for a in store.ordered(store.applications.values())
                  if a["institution_id"] == inst["id"]
                  and a["action_taken"] is not None
                  and a["action_taken_date"] is not None
                  and a["action_taken_date"] >= body["period_start"]
                  and a["action_taken_date"] <= body["period_end"]
                  and a["lar_status"] in ("COMPLETE", "EXCEPTION_FLAGGED", "CLEARED")
                  and a["is_superseded"] is False]
    if body["method"] == "STRATIFIED_BY_ACTION":
        candidates = sorted(
            candidates,
            key=lambda a: (C.ACTION_TAKEN_ORDER.get(a["action_taken"], 0), a["_seq"]))

    population_size = len(candidates)
    # step 16 -- the candidate set must be non-empty
    if population_size == 0:
        fail("ERR_EMPTY_SAMPLE_POPULATION")

    sample_size = calc.audit_sample_sizing(population_size)
    selected = calc.systematic_selection(candidates, sample_size)

    inst["_sample_index"] += 1
    row = store.new_row()
    row.update({
        "institution_id": inst["id"],
        "sample_index": inst["_sample_index"],
        "method": body["method"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "fields_reviewed_per_record": body["fields_reviewed_per_record"],
        "population_size": population_size,
        "sample_size": sample_size,
        "selected_application_ids": selected,
        "defect_count": 0,
        "records_with_defect_count": 0,
        "defect_rate_basis": None,
        "defect_rate_pct": None,
        "status": "DRAFT",
    })
    store.audit_samples[row["id"]] = row
    return object_response(S.audit_sample(row), 201)


@bp.route("/hmda/audit-samples/<sample_id>", methods=["GET"])
def get_audit_sample(sample_id):
    authenticate(BACK_OFFICE_READ_ROLES)
    row = lookup(store.audit_samples, sample_id, "ERR_AUDIT_SAMPLE_NOT_FOUND")
    return object_response(S.audit_sample(row))


@bp.route("/hmda/audit-samples/<sample_id>/findings", methods=["GET"])
def list_sample_findings(sample_id):
    authenticate(BACK_OFFICE_READ_ROLES)
    lookup(store.audit_samples, sample_id, "ERR_AUDIT_SAMPLE_NOT_FOUND")
    limit, offset = pagination()
    resolution = enum_filter("resolution", C.FINDING_RESOLUTIONS)
    rows = [f for f in store.ordered(store.audit_findings.values())
            if f["audit_sample_id"] == sample_id
            and (resolution is None or f["resolution"] == resolution)]
    items, total = paginate(rows, limit, offset, S.audit_finding)
    return array_response(items, limit, offset, total)


@bp.route("/hmda/audit-findings", methods=["POST"])
def create_audit_finding():
    authenticate(["ComplianceAnalyst"])
    body = check(json_body(), FINDING_FIELDS)
    sample = lookup(store.audit_samples, body["audit_sample_id"], "ERR_AUDIT_SAMPLE_NOT_FOUND")
    app = lookup(store.applications, body["application_id"], "ERR_APPLICATION_NOT_FOUND")

    # step 8 -- a finding may only be recorded while the sample is still open
    if sample["status"] not in ("DRAFT", "IN_REVIEW"):
        fail("ERR_SAMPLE_NOT_OPEN")

    # step 12 -- the record must be one the sample actually drew
    if app["id"] not in sample["selected_application_ids"]:
        fail("ERR_FINDING_APPLICATION_NOT_IN_SAMPLE")

    # step 14 -- the remediation window is closed
    if body["remediation_end"] < body["remediation_start"]:
        fail("ERR_INVALID_WINDOW")

    # step 15 -- closed windows collide on touching endpoints
    new_start, new_end = body["remediation_start"], body["remediation_end"]
    for existing in store.audit_findings.values():
        if existing["application_id"] != app["id"] or existing["resolution"] != "OPEN":
            continue
        if new_start <= existing["remediation_end"] and existing["remediation_start"] <= new_end:
            fail("ERR_REMEDIATION_WINDOW_OVERLAP")

    row = store.new_row()
    row.update({
        "audit_sample_id": sample["id"],
        "application_id": app["id"],
        "field_name": body["field_name"],
        "recorded_value": body["recorded_value"],
        "source_document_value": body["source_document_value"],
        "is_defect": body["recorded_value"] != body["source_document_value"],
        "severity": body["severity"],
        "remediation_start": new_start,
        "remediation_end": new_end,
        "resolution": "OPEN",
    })
    store.audit_findings[row["id"]] = row

    _recompute_sample_defects(sample)
    if sample["status"] == "DRAFT":
        sample["status"] = "IN_REVIEW"
    store.bump(sample)
    return object_response(S.audit_finding(row), 201)


@bp.route("/hmda/audit-samples/<sample_id>/close", methods=["POST"])
def close_audit_sample(sample_id):
    authenticate(["ComplianceAnalyst"])
    sample = lookup(store.audit_samples, sample_id, "ERR_AUDIT_SAMPLE_NOT_FOUND")
    body = check(json_body(), CLOSE_FIELDS)

    # step 8 -- state precondition
    if sample["status"] not in ("DRAFT", "IN_REVIEW"):
        fail("ERR_SAMPLE_NOT_OPEN")

    basis = body["defect_rate_basis"]
    _recompute_sample_defects(sample)
    sample["defect_rate_basis"] = basis
    if sample["defect_count"] == 0:
        sample["status"] = "CLOSED_CLEAN"
        sample["defect_rate_pct"] = 0.0
    else:
        sample["status"] = "CLOSED_WITH_FINDINGS"
        sample["defect_rate_pct"] = calc.as_float(calc.audit_defect_rate(sample, basis))

    for finding in store.ordered(store.audit_findings.values()):
        if finding["audit_sample_id"] == sample["id"] and finding["resolution"] == "OPEN":
            finding["resolution"] = "ACCEPTED_AS_IS"
            store.bump(finding)

    store.bump(sample)
    return object_response(S.audit_sample(sample))
