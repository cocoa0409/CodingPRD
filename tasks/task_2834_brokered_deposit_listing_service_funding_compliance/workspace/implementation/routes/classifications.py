from flask import Blueprint

import calc
import db
import middleware as mw
import response
import util
from errors import ApiError

bp = Blueprint("classifications", __name__)

READ_ROLES = ("SystemAdmin", "FundingDeskOfficer", "ComplianceReviewer",
              "TreasuryController", "Examiner")
RELIABLE = ("ACKNOWLEDGED", "GRANTED")


@bp.post("/deposit-classifications")
def create_classification():
    user_id, _role = mw.auth("SystemAdmin", "ComplianceReviewer")
    data = mw.body()
    program_id = mw.req_id(data, "program_id")
    expected_version = mw.req_int(data, "expected_program_version")
    rationale_code = mw.req_str(data, "rationale_code")
    relied_exception_id = mw.opt_id(data, "relied_exception_id")

    exception = None
    if relied_exception_id is not None:
        exception = db.exceptions.get(relied_exception_id)
        if exception is None:
            raise ApiError("ERR_EXCEPTION_NOT_FOUND")
    program = db.programs.get(program_id)
    if program is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND")
    if expected_version != program["version"]:
        raise ApiError("ERR_STALE_PROGRAM_VERSION")
    if program["state"] not in ("PENDING_CLASSIFICATION", "RECLASSIFICATION_PENDING"):
        raise ApiError("ERR_PROGRAM_NOT_CLASSIFIABLE")
    if exception is not None:
        if exception["status"] not in RELIABLE:
            raise ApiError("ERR_EXCEPTION_NOT_RELIABLE")
        if (exception["broker_id"] != program.get("broker_id")
                or exception["institution_id"] != program["institution_id"]):
            raise ApiError("ERR_EXCEPTION_COUNTERPARTY_MISMATCH")

    institution = db.institutions.get(program["institution_id"])
    was_reclassification = program["state"] == "RECLASSIFICATION_PENDING"
    previous = db.classifications.get(program.get("governing_classification_id"))
    previous_exception_id = previous.get("relied_exception_id") if previous else None

    determined_class, prong = calc.determine_class(program, institution, exception)
    record = {
        "program_id": program_id,
        "relied_exception_id": relied_exception_id,
        "determined_class": determined_class,
        "deposit_broker_prong": prong,
        "call_report_line": calc.CALL_REPORT_LINE[determined_class],
        "rationale_code": rationale_code,
        "determined_by_user_id": user_id,
        "effective_at": util.now_iso(),
        "program_version_at_determination": expected_version + 1,
    }
    db.stamp_new(record, versioned=False)
    db.classifications[record["id"]] = record

    program["governing_classification_id"] = record["id"]
    program["state"] = "CLASSIFIED"
    db.bump(program)
    as_of = util.clock_date().isoformat()
    cap, _pub = calc.effective_cap(institution, program["tenor_bucket"],
                                   program.get("local_prevailing_rate_bps"),
                                   as_of, require=False)
    program["effective_cap_bps"] = cap

    # reliance accounting — the conserved quantity of PRD 2.11
    if relied_exception_id is not None and relied_exception_id != previous_exception_id:
        exception["reliant_program_count"] += 1
        db.bump(exception)
    if previous_exception_id is not None and previous_exception_id != relied_exception_id:
        superseded = db.exceptions.get(previous_exception_id)
        if superseded is not None:
            superseded["reliant_program_count"] = max(
                0, superseded["reliant_program_count"] - 1)
            db.bump(superseded)

    if was_reclassification:
        for placement in calc.placements_of_program(program_id):
            if placement["funding_status"] != "ACTIVE":
                continue
            placement["classified_as"] = determined_class
            if placement["compliance_status"] == "FLAGGED":
                placement["compliance_status"] = "REMEDIATED"
            db.bump(placement)
        calc.recompute_institution(institution)

    return response.created(db.public(record))


@bp.get("/deposit-classifications/<classification_id>")
def read_classification(classification_id):
    mw.auth(*READ_ROLES)
    record = db.classifications.get(classification_id)
    if record is None:
        raise ApiError("ERR_CLASSIFICATION_NOT_FOUND")
    return response.ok(db.public(record))


@bp.get("/deposit-classifications")
def list_classifications():
    mw.auth(*READ_ROLES)
    limit, offset = mw.page()
    rows = list(db.classifications.values())
    for field in ("program_id", "relied_exception_id", "determined_class"):
        wanted = mw.q(field)
        if wanted is not None:
            rows = [r for r in rows if r.get(field) == wanted]
    superseded = mw.q("superseded")
    if superseded is not None:
        want = superseded.lower() in ("true", "1", "yes")
        governing = {p.get("governing_classification_id") for p in db.programs.values()}
        rows = [r for r in rows if ((r["id"] not in governing) == want)]
    rows.sort(key=lambda r: (r["effective_at"], r["created_at"], r["_seq"]))
    return response.listing(db.public_list(rows), limit, offset)
