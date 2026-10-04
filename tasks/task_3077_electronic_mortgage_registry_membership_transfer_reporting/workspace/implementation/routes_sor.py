"""System-of-record reconciliation runs and exceptions (PRD §3.8)."""
from decimal import Decimal
from flask import Blueprint, request

from db import store
from domain import (
    INACTIVE_LOAN_STATUSES, base_record, err, find_exception, find_run,
    get_body, maybe_complete_run, new_exception, paginate, round4,
    sorted_items, touch,
)
from middleware import require_member_active, require_role
from response import success
from views import exception_view, run_view

bp = Blueprint("sor", __name__)


@bp.post("/sor-reconciliation-runs")
def create_run():
    body = get_body()
    user_id, _role = require_role("MemberRep")
    records = body.get("records")
    if not isinstance(records, list):
        raise err("ERR_INVALID_REQUEST", "records must be an array")
    member = store.members.get(user_id)
    if member is None:
        raise err("ERR_MEMBER_NOT_FOUND", "Acting member does not exist")
    require_member_active(member)

    # Supersede any prior OPEN run for this member.
    for run in store.runs.values():
        if run["member_id"] == member["id"] and run["status"] == "OPEN":
            for exc in store.exceptions.values():
                if exc["run_id"] == run["id"] and exc["status"] == "OPEN":
                    exc["status"] = "RESOLVED"
                    exc["detail"] = (exc["detail"] + " (superseded)") if exc["detail"] else "superseded"
                    touch(exc)
            run["status"] = "CANCELLED"
            touch(run)

    rec = base_record()
    rec.update({
        "member_id": member["id"],
        "total_records": len(records),
        "matched_count": 0,
        "registry_only_count": 0,
        "platform_only_count": 0,
        "field_mismatch_count": 0,
        "match_rate": 0.0,
        "status": "OPEN",
    })
    store.runs[rec["id"]] = rec

    submitted_mins = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("min"), str):
            raise err("ERR_INVALID_REQUEST",
                      "each record must carry a min string")
        min_value = record["min"]
        submitted_mins.add(min_value)
        loan = next((l for l in store.loans.values() if l["min"] == min_value), None)
        if loan is None or loan["status"] in INACTIVE_LOAN_STATUSES:
            rec["platform_only_count"] += 1
            new_exception(rec["id"], None, "PLATFORM_ONLY",
                          f"MIN {min_value} is unknown to the registry or has left it")
            continue
        servicer = store.members.get(loan["current_servicer_id"])
        investor = store.members.get(loan["current_investor_id"])
        if (record.get("servicer_org_id") != (servicer["org_id"] if servicer else None)
                or record.get("investor_org_id") != (investor["org_id"] if investor else None)):
            rec["field_mismatch_count"] += 1
            new_exception(rec["id"], loan["id"], "FIELD_MISMATCH",
                          f"Servicer/investor disagree with the registry for MIN {min_value}")
        else:
            rec["matched_count"] += 1

    # Registry-side sweep over the member's live portfolio.
    portfolio = [l for l in store.loans.values()
                 if l["status"] in ("ACTIVE", "FORECLOSING")
                 and (l["current_servicer_id"] == member["id"]
                      or l["current_investor_id"] == member["id"])]
    portfolio.sort(key=lambda l: l["serial"])
    for loan in portfolio:
        if loan["min"] not in submitted_mins:
            rec["registry_only_count"] += 1
            new_exception(rec["id"], loan["id"], "REGISTRY_ONLY",
                          f"Loan {loan['min']} is on the registry but absent from the platform records")

    denominator = max(1, rec["total_records"] + rec["registry_only_count"])
    rec["match_rate"] = round4(Decimal(rec["matched_count"]) / Decimal(denominator))

    exception_count = (rec["platform_only_count"] + rec["field_mismatch_count"]
                       + rec["registry_only_count"])
    if exception_count == 0:
        rec["status"] = "COMPLETED"
    return success(run_view(rec), status=201)


@bp.get("/sor-reconciliation-runs")
def list_runs():
    require_role("RegistryAdmin", "MemberRep", "QAAuditor")
    items = sorted_items(store.runs)
    for field in ("member_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [r for r in items if r[field] == value]
    page, meta = paginate(items)
    return success([run_view(r) for r in page], is_list=True, pagination=meta)


@bp.get("/sor-reconciliation-runs/<runId>")
def get_run(runId):
    require_role("RegistryAdmin", "MemberRep", "QAAuditor")
    return success(run_view(find_run(runId)))


@bp.get("/sor-exceptions")
def list_exceptions():
    require_role("RegistryAdmin", "MemberRep", "QAAuditor")
    items = sorted_items(store.exceptions)
    for field in ("run_id", "loan_id", "exception_type", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [e for e in items if e[field] == value]
    page, meta = paginate(items)
    return success([exception_view(e) for e in page], is_list=True, pagination=meta)


@bp.get("/sor-exceptions/<exceptionId>")
def get_exception(exceptionId):
    require_role("RegistryAdmin", "MemberRep", "QAAuditor")
    return success(exception_view(find_exception(exceptionId)))


@bp.post("/sor-exceptions/<exceptionId>/resolve")
def resolve_exception(exceptionId):
    body = get_body()
    user_id, _role = require_role("MemberRep")
    exc = find_exception(exceptionId)
    run = find_run(exc["run_id"])
    if run["member_id"] != user_id:
        raise err("ERR_NOT_SANCTION_PARTY",
                  "Only the run's owning member may resolve its exceptions")
    if run["status"] != "OPEN":
        raise err("ERR_RUN_NOT_OPEN", "The parent reconciliation run is not OPEN")
    if exc["status"] != "OPEN":
        raise err("ERR_EXCEPTION_NOT_OPEN", "The exception is not OPEN")
    note = body.get("resolution_note")
    if note is not None:
        if not isinstance(note, str):
            raise err("ERR_INVALID_REQUEST", "resolution_note must be a string")
        exc["detail"] = (exc["detail"] + " | " + note) if exc["detail"] else note
    exc["status"] = "RESOLVED"
    touch(exc)
    maybe_complete_run(run)
    return success(exception_view(exc))
