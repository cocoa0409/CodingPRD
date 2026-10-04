"""Routes: migration batches, records, reconciliation."""
from flask import Blueprint, request

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_DUPLICATE_KEY, ERR_UNRESOLVED_RECORDS, ERR_SEGREGATION_OF_DUTIES,
    ERR_RECONCILE_OUT_OF_TOLERANCE,
)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from routes_contracts import get_contract_or_404
from services_common import strip_internal, append_audit, recompute_readiness
from util import new_id, now_ts, touch, require_fields, require_int

bp = Blueprint("migration", __name__)

DOMAINS = ("ACCOUNTS_RECEIVABLE", "PROPERTY_TAX", "COURT_CASES", "LICENSES", "PAYROLL")
ISSUE_CODES = ("DUPLICATE_KEY", "MISSING_REQUIRED_FIELD", "OUT_OF_RANGE_DATE",
               "ORPHAN_REFERENCE", "INVALID_CODE_VALUE")
RESOLUTIONS = ("QUARANTINED", "CORRECTED", "EXCLUDED")

TOLERANCE_CENTS = {
    "PROPERTY_TAX": 0,
    "COURT_CASES": 0,
    "PAYROLL": 0,
    "ACCOUNTS_RECEIVABLE": 100,
    "LICENSES": 50,
}


def get_batch_or_404(bid):
    b = db.get("migration_batches", bid)
    if b is None:
        raise_error(ERR_NOT_FOUND, "migration batch not found")
    return b


@bp.route("/programs/contracts/<contract_id>/migration-batches", methods=["POST"])
def create_batch(contract_id):
    require_roles("DataMigrationLead")
    c = get_contract_or_404(contract_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["domain", "source_system_label",
                             "expected_record_count", "expected_net_value_cents"])
    if payload["domain"] not in DOMAINS:
        raise_error(ERR_INVALID_REQUEST, "invalid domain")
    require_int(payload, "expected_record_count")
    require_int(payload, "expected_net_value_cents")
    now = now_ts()
    batch = {
        "id": new_id(),
        "contract_id": c["id"],
        "domain": payload["domain"],
        "source_system_label": payload["source_system_label"],
        "expected_record_count": payload["expected_record_count"],
        "expected_net_value_cents": payload["expected_net_value_cents"],
        "status": "DEFINED",
        "extracted_at": None,
        "loaded_at": None,
        "last_reconciled_by": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("migration_batches", batch)
    return success_object(strip_internal(batch), 201)


@bp.route("/programs/contracts/<contract_id>/migration-batches", methods=["GET"])
def list_batches(contract_id):
    require_roles("DataMigrationLead", "AgencyProjectManager", "ImplementationManager", "PlatformAdmin")
    c = get_contract_or_404(contract_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("migration_batches", contract_id=c["id"])
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    domain = request.args.get("domain")
    if domain is not None:
        items = [b for b in items if b["domain"] == domain]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(b) for b in page], limit, offset, total)


@bp.route("/programs/migration-batches/<bid>", methods=["GET"])
def get_batch(bid):
    require_roles("DataMigrationLead", "AgencyProjectManager", "ImplementationManager", "PlatformAdmin")
    return success_object(strip_internal(get_batch_or_404(bid)), 200)


@bp.route("/programs/migration-batches/<bid>/records", methods=["POST"])
def ingest_records(bid):
    require_roles("DataMigrationLead")
    b = get_batch_or_404(bid)
    if b["status"] not in ("DEFINED", "EXTRACTED"):
        raise_error(ERR_INVALID_STATE, "batch not DEFINED or EXTRACTED")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["records"])
    records = payload["records"]
    if not isinstance(records, list):
        raise_error(ERR_INVALID_REQUEST, "records must be an array")
    existing_keys = {r["legacy_primary_key"] for r in db.filter_items("migration_records", batch_id=b["id"])}
    seen = set()
    created = []
    for rec in records:
        if not isinstance(rec, dict):
            raise_error(ERR_INVALID_REQUEST, "record must be an object")
        if "legacy_primary_key" not in rec or "field_payload" not in rec:
            raise_error(ERR_INVALID_REQUEST, "record requires legacy_primary_key and field_payload")
        key = rec["legacy_primary_key"]
        if key in existing_keys or key in seen:
            raise_error(ERR_DUPLICATE_KEY, "duplicate legacy_primary_key within batch")
        seen.add(key)
        value = rec.get("signed_value_cents", 0)
        if isinstance(value, bool) or not isinstance(value, int):
            raise_error(ERR_INVALID_REQUEST, "signed_value_cents must be an integer")
        row = {
            "id": new_id(),
            "batch_id": b["id"],
            "legacy_primary_key": key,
            "field_payload": rec["field_payload"],
            "issue_code": None,
            "resolution": None,
            "signed_value_cents": value,
            "loaded": False,
            "created_at": now_ts(),
        }
        db.put("migration_records", row)
        created.append(row)
    limit, offset = parse_pagination(request.args)
    page, total = paginate(created, limit, offset)
    body, _ = success_list([strip_internal(r) for r in page], limit, offset, total)
    return body, 201


@bp.route("/programs/migration-batches/<bid>/records", methods=["GET"])
def list_records(bid):
    require_roles("DataMigrationLead", "AgencyProjectManager", "PlatformAdmin")
    b = get_batch_or_404(bid)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("migration_records", batch_id=b["id"])
    issue = request.args.get("issue_code")
    if issue is not None:
        items = [r for r in items if r["issue_code"] == issue]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(r) for r in page], limit, offset, total)


@bp.route("/programs/migration-batches/<bid>/extract", methods=["POST"])
def extract_batch(bid):
    require_roles("DataMigrationLead")
    b = get_batch_or_404(bid)
    if b["status"] != "DEFINED":
        raise_error(ERR_INVALID_STATE, "batch not DEFINED")
    if not db.filter_items("migration_records", batch_id=b["id"]):
        raise_error(ERR_INVALID_STATE, "no records ingested")
    b["status"] = "EXTRACTED"
    b["extracted_at"] = now_ts()
    touch(b)
    return success_object(strip_internal(b), 200)


@bp.route("/programs/migration-batches/<bid>/cleanse", methods=["POST"])
def cleanse_batch(bid):
    require_roles("DataMigrationLead")
    b = get_batch_or_404(bid)
    if b["status"] != "EXTRACTED":
        raise_error(ERR_INVALID_STATE, "batch not EXTRACTED")
    payload = request.get_json(silent=True) or {}
    resolutions = payload.get("resolutions", {})
    if not isinstance(resolutions, dict):
        raise_error(ERR_INVALID_REQUEST, "resolutions must be an object")
    for key, entry in resolutions.items():
        if not isinstance(entry, dict):
            raise_error(ERR_INVALID_REQUEST, "resolution entry must be an object")
        issue = entry.get("issue_code")
        resolution = entry.get("resolution")
        if issue is not None and issue not in ISSUE_CODES:
            raise_error(ERR_INVALID_REQUEST, "invalid issue_code")
        if resolution is not None and resolution not in RESOLUTIONS:
            raise_error(ERR_INVALID_REQUEST, "invalid resolution")
    for rec in db.filter_items("migration_records", batch_id=b["id"]):
        entry = resolutions.get(rec["legacy_primary_key"])
        if entry:
            rec["issue_code"] = entry.get("issue_code")
            rec["resolution"] = entry.get("resolution")
    b["status"] = "CLEANSED"
    touch(b)
    return success_object(strip_internal(b), 200)


@bp.route("/programs/migration-batches/<bid>/load", methods=["POST"])
def load_batch(bid):
    require_roles("DataMigrationLead")
    b = get_batch_or_404(bid)
    if b["status"] != "CLEANSED":
        raise_error(ERR_INVALID_STATE, "batch not CLEANSED")
    for rec in db.filter_items("migration_records", batch_id=b["id"]):
        if rec["issue_code"] is not None and rec["resolution"] is None:
            raise_error(ERR_UNRESOLVED_RECORDS, "flagged record lacks resolution")
    for rec in db.filter_items("migration_records", batch_id=b["id"]):
        rec["loaded"] = rec["resolution"] in (None, "CORRECTED")
    b["status"] = "LOADED"
    b["loaded_at"] = now_ts()
    touch(b)
    return success_object(strip_internal(b), 200)


def _loaded_records(bid):
    return [r for r in db.filter_items("migration_records", batch_id=bid) if r["loaded"]]


def _compute_reports(batch):
    records = _loaded_records(batch["id"])
    expected_count = batch["expected_record_count"]
    expected_value = batch["expected_net_value_cents"]
    tolerance = TOLERANCE_CENTS[batch["domain"]]

    loaded_count = len(records)
    forward_value = sum(r["signed_value_cents"] for r in records)

    # CHRONOLOGICAL: replay in legacy_primary_key ASC; exclude records whose
    # inclusion would flip the running total's sign relative to the final total.
    ordered = sorted(records, key=lambda r: str(r["legacy_primary_key"]))
    final_total = sum(r["signed_value_cents"] for r in ordered)
    running = 0
    flagged = set()

    def _sign(v):
        return (v > 0) - (v < 0)

    for r in ordered:
        candidate = running + r["signed_value_cents"]
        if _sign(candidate) != 0 and _sign(final_total) != 0 and _sign(candidate) != _sign(final_total):
            flagged.add(r["id"])
        else:
            running = candidate
    chrono_value = sum(r["signed_value_cents"] for r in ordered if r["id"] not in flagged)

    reports = []
    for variant, value in (("FORWARD", forward_value), ("CHRONOLOGICAL", chrono_value)):
        count_delta = loaded_count - expected_count
        value_delta = value - expected_value
        within = (count_delta == 0) and (abs(value_delta) <= tolerance)
        reports.append({
            "id": new_id(),
            "batch_id": batch["id"],
            "run_variant": variant,
            "expected_record_count": expected_count,
            "loaded_record_count": loaded_count,
            "expected_net_value_cents": expected_value,
            "loaded_net_value_cents": value,
            "count_delta": count_delta,
            "value_delta_cents": value_delta,
            "within_tolerance": within,
            "created_at": now_ts(),
        })
    return reports


@bp.route("/programs/migration-batches/<bid>/reconcile", methods=["POST"])
def reconcile_batch(bid):
    user_id, role = require_roles("DataMigrationLead")
    b = get_batch_or_404(bid)
    if b["status"] != "LOADED":
        raise_error(ERR_INVALID_STATE, "batch not LOADED")
    reports = _compute_reports(b)
    for r in reports:
        db.put("reconciliation_reports", r)
    b["last_reconciled_by"] = user_id
    if all(r["within_tolerance"] for r in reports):
        b["status"] = "RECONCILED"
    else:
        b["status"] = "RECONCILE_FAILED"
    touch(b)
    return success_object(strip_internal(b), 200)


@bp.route("/programs/migration-batches/<bid>/reconciliation-reports", methods=["GET"])
def list_reports(bid):
    require_roles("DataMigrationLead", "AgencyProjectManager", "PlatformAdmin")
    b = get_batch_or_404(bid)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("reconciliation_reports", batch_id=b["id"])
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(r) for r in page], limit, offset, total)


@bp.route("/programs/migration-batches/<bid>/recleanse", methods=["POST"])
def recleanse_batch(bid):
    require_roles("DataMigrationLead")
    b = get_batch_or_404(bid)
    if b["status"] != "RECONCILE_FAILED":
        raise_error(ERR_INVALID_STATE, "batch not RECONCILE_FAILED")
    for rec in db.filter_items("migration_records", batch_id=b["id"]):
        rec["loaded"] = False
    b["status"] = "CLEANSED"
    touch(b)
    return success_object(strip_internal(b), 200)


@bp.route("/programs/migration-batches/<bid>/accept", methods=["POST"])
def accept_batch(bid):
    user_id, role = require_roles("AgencyProjectManager")
    b = get_batch_or_404(bid)
    if b["status"] != "RECONCILED":
        raise_error(ERR_INVALID_STATE, "batch not RECONCILED")
    if b.get("last_reconciled_by") == user_id:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "acceptor must differ from reconciler")
    b["status"] = "ACCEPTED"
    touch(b)
    recompute_readiness(b["contract_id"])
    append_audit(b["contract_id"], role, user_id, "POST /programs/migration-batches/{id}/accept",
                 "MigrationBatch", b["id"], "RECONCILED -> ACCEPTED")
    return success_object(strip_internal(b), 200)
