"""Lookback investigations: the donor-cohort recall machinery."""

from flask import Blueprint, request

import auth
import calc
import cascade
import envelope
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("lookback", __name__)

INVESTIGATION_STATUSES = ("OPEN", "NOTIFIED", "CLOSED_NO_ACTION", "CLOSED_WITH_RECALL")
RESOLUTIONS = ("NO_ACTION", "RECALL")
CLOSURE_STATUS = {"NO_ACTION": "CLOSED_NO_ACTION", "RECALL": "CLOSED_WITH_RECALL"}


@bp.post("/eye-bank/lookback-investigations")
def create_investigation():
    auth.authenticate(("MedicalDirector",))
    body = auth.body_dict()

    donor = validate.resolve_fk(body, "donor_id", "donors")
    source_report = validate.resolve_fk(body, "source_report_id", "reports")

    validate.req_str(body, "donor_id")
    source_report_id = validate.opt_str(body, "source_report_id")
    if donor is None:
        raise ApiError("ERR_INVALID_REQUEST", "donor_id must reference a donor.")
    if source_report_id is not None and source_report is None:
        raise ApiError("ERR_INVALID_REQUEST", "source_report_id must reference a report.")

    if cascade.donor_has_live_investigation(donor["id"]):
        raise ApiError(
            "ERR_INVESTIGATION_STATE_INVALID",
            "This donor is already under an open or notified investigation.",
        )

    trigger = "ADVERSE_REACTION" if source_report_id is not None else "POSITIVE_RETEST"
    row = cascade.open_lookback_investigation(donor, trigger, source_report_id)
    return envelope.ok(serialize.investigation(row), 201)


@bp.get("/eye-bank/lookback-investigations/<investigation_id>")
def get_investigation(investigation_id):
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector"))
    row = validate.lookup("investigations", investigation_id)
    return envelope.ok(serialize.investigation(row))


@bp.get("/eye-bank/lookback-investigations")
def list_investigations():
    auth.authenticate(("EyeBankCoordinator", "MedicalDirector"))
    rows = list(store.DB["investigations"].values())
    donor_id = request.args.get("donor_id")
    if donor_id is not None:
        rows = [r for r in rows if r["donor_id"] == donor_id]
    source_report_id = request.args.get("source_report_id")
    if source_report_id is not None:
        rows = [r for r in rows if r["source_report_id"] == source_report_id]
    status = request.args.get("status")
    if status is not None:
        validate.filter_enum("status", status, INVESTIGATION_STATUSES)
        rows = [r for r in rows if r["status"] == status]
    rows = store.sort_desc(rows, lambda r: r["opened_at"])
    return envelope.paginated(rows, serialize.investigation)


@bp.post("/eye-bank/lookback-investigations/<investigation_id>/notify")
def notify(investigation_id):
    auth.authenticate(("MedicalDirector",))
    row = validate.lookup("investigations", investigation_id)

    if row["status"] != "OPEN":
        raise ApiError(
            "ERR_INVESTIGATION_STATE_INVALID", "Only an OPEN investigation may be notified."
        )

    row["notified_at"] = store.now()
    row["status"] = "NOTIFIED"
    row["notified_recipient_count"] = calc.lookback_notified_recipient_count(row["donor_id"])
    store.touch(row)
    return envelope.ok(serialize.investigation(row))


@bp.post("/eye-bank/lookback-investigations/<investigation_id>/close")
def close(investigation_id):
    auth.authenticate(("MedicalDirector",))
    row = validate.lookup("investigations", investigation_id)
    body = auth.body_dict()
    resolution = validate.req_enum(body, "resolution", RESOLUTIONS)
    closure_note = validate.req_str(body, "closure_note", 1, 2000)

    if row["status"] != "NOTIFIED":
        raise ApiError(
            "ERR_INVESTIGATION_STATE_INVALID", "Only a NOTIFIED investigation may be closed."
        )

    row["closure_note"] = closure_note
    row["closed_at"] = store.now()
    row["status"] = CLOSURE_STATUS[resolution]
    store.touch(row)

    donor = store.DB["donors"].get(row["donor_id"])
    if donor is not None:
        # A recalled donor is never rehabilitated: the flag stays true forever.
        if resolution == "NO_ACTION":
            donor["lookback_flag"] = False
        store.touch(donor)

    cascade.close_lookback_sweep(row, resolution)

    return envelope.ok(serialize.investigation(row))
