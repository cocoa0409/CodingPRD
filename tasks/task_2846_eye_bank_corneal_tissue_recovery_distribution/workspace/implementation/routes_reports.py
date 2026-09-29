"""Adverse reaction reporting and its adjudication."""

from flask import Blueprint, request

import auth
import cascade
import envelope
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("reports", __name__)

REACTION_TYPES = (
    "PRIMARY_GRAFT_FAILURE",
    "ENDOPHTHALMITIS",
    "INFECTIOUS_KERATITIS",
    "REJECTION",
)
SEVERITIES = ("MINOR", "SERIOUS")
REPORT_STATUSES = ("SUBMITTED", "SUBSTANTIATED", "UNSUBSTANTIATED")


def _consumed_allocation_surgeon(tissue_id):
    for allocation in store.by_created(
        [a for a in store.DB["allocations"].values() if a["tissue_id"] == tissue_id]
    ):
        if allocation["status"] == "CONSUMED":
            req = store.DB["requests"].get(allocation["request_id"])
            if req is not None:
                return req["surgeon_id"]
    return None


@bp.post("/eye-bank/adverse-reaction-reports")
def create_report():
    actor = auth.authenticate(("Surgeon",))
    body = auth.body_dict()

    tissue = validate.resolve_fk(body, "tissue_id", "tissues")
    surgeon = validate.resolve_fk(body, "surgeon_id", "surgeons")

    validate.req_str(body, "tissue_id")
    validate.req_str(body, "surgeon_id")
    reaction_type = validate.req_enum(body, "reaction_type", REACTION_TYPES)
    severity = validate.req_enum(body, "severity", SEVERITIES)
    narrative = validate.req_str(body, "narrative", 1, 2000)
    if tissue is None:
        raise ApiError("ERR_INVALID_REQUEST", "tissue_id must reference a tissue.")
    if surgeon is None:
        raise ApiError("ERR_INVALID_REQUEST", "surgeon_id must reference a surgeon.")

    if actor.user_id != surgeon["id"]:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "A surgeon may only report under their own identity."
        )

    if (
        tissue["disposition_status"] != "IMPLANTED"
        or _consumed_allocation_surgeon(tissue["id"]) != surgeon["id"]
    ):
        raise ApiError(
            "ERR_REPORT_TISSUE_NOT_IMPLANTED_BY_SURGEON",
            "This surgeon did not graft this cornea.",
        )

    row = store.base_row()
    row.update(
        {
            "tissue_id": tissue["id"],
            "surgeon_id": surgeon["id"],
            "reaction_type": reaction_type,
            "severity": severity,
            "narrative": narrative,
            "reported_at": store.now(),
            "status": "SUBMITTED",
            "adjudication_note": None,
        }
    )
    store.DB["reports"][row["id"]] = row
    return envelope.ok(serialize.report(row), 201)


@bp.get("/eye-bank/adverse-reaction-reports/<report_id>")
def get_report(report_id):
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector", "Surgeon"))
    row = validate.lookup("reports", report_id)
    return envelope.ok(serialize.report(row))


@bp.get("/eye-bank/adverse-reaction-reports")
def list_reports():
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector", "Surgeon"))
    rows = list(store.DB["reports"].values())
    tissue_id = request.args.get("tissue_id")
    if tissue_id is not None:
        rows = [r for r in rows if r["tissue_id"] == tissue_id]
    surgeon_id = request.args.get("surgeon_id")
    if surgeon_id is not None:
        rows = [r for r in rows if r["surgeon_id"] == surgeon_id]
    status = request.args.get("status")
    if status is not None:
        validate.filter_enum("status", status, REPORT_STATUSES)
        rows = [r for r in rows if r["status"] == status]
    rows = store.sort_desc(rows, lambda r: r["reported_at"])
    return envelope.paginated(rows, serialize.report)


@bp.post("/eye-bank/adverse-reaction-reports/<report_id>/substantiate")
def substantiate(report_id):
    auth.authenticate(("MedicalDirector",))
    report = validate.lookup("reports", report_id)
    body = auth.body_dict()
    note = validate.req_str(body, "adjudication_note", 1, 2000)

    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_STATE_INVALID", "Only a SUBMITTED report may be adjudicated.")

    report["adjudication_note"] = note
    report["status"] = "SUBSTANTIATED"
    store.touch(report)

    surgeon = store.DB["surgeons"].get(report["surgeon_id"])
    if surgeon is not None:
        # Every substantiated report counts, whatever its severity.
        surgeon["substantiated_reaction_count"] = surgeon["substantiated_reaction_count"] + 1
        store.touch(surgeon)

    if report["severity"] == "SERIOUS":
        tissue = store.DB["tissues"].get(report["tissue_id"])
        donor = store.DB["donors"].get(tissue["donor_id"]) if tissue is not None else None
        if donor is not None and not cascade.donor_has_live_investigation(donor["id"]):
            cascade.open_lookback_investigation(donor, "ADVERSE_REACTION", report["id"])

    return envelope.ok(serialize.report(report))


@bp.post("/eye-bank/adverse-reaction-reports/<report_id>/dismiss")
def dismiss(report_id):
    auth.authenticate(("MedicalDirector",))
    report = validate.lookup("reports", report_id)
    body = auth.body_dict()
    note = validate.req_str(body, "adjudication_note", 1, 2000)

    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_STATE_INVALID", "Only a SUBMITTED report may be adjudicated.")

    report["adjudication_note"] = note
    report["status"] = "UNSUBSTANTIATED"
    store.touch(report)
    return envelope.ok(serialize.report(report))
