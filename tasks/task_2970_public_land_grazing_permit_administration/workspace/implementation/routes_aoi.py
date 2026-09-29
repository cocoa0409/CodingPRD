"""Annual operating instructions and pasture use records (PRD 3.4 and 3.5)."""

from datetime import timedelta

from flask import Blueprint, request

import auth
import calc
import constants as K
import derive
import envelope
from errors import ApiError
import find
import gates
import services
import store
from validate import bad, date_range, field, json_body, parse_body

bp = Blueprint("aoi", __name__)

AOI_FIELDS = [
    field("permit_id", "str"),
    field("grazing_year", "int", min=2020, max=2060),
    field("authorized_aums", "int", min=1),
    field("season_start_date", "date"),
    field("season_end_date", "date"),
]

USE_RECORD_FIELDS = [
    field("pasture_id", "str"),
    field("planned_entry_date", "date"),
    field("planned_exit_date", "date"),
    field("planned_head_count", "int", min=1),
    field("livestock_kind", "enum", values=K.LIVESTOCK_KIND),
]

NONUSE_FIELDS = [
    field("nonuse_aums", "int", min=0),
    field("nonuse_reason", "enum", values=K.NONUSE_REASON),
]

ACTUAL_FIELDS = [
    field("actual_entry_date", "date"),
    field("actual_exit_date", "date"),
    field("actual_head_count", "int", min=1),
]

VOID_FIELDS = [
    field("void_reason", "str", required=False, nullable=True, default=None),
]


def aoi_state(message):
    raise ApiError("ERR_AOI_STATE_INVALID", message)


def day(text):
    return store.parse_instant(text + "T00:00:00Z").date()


def owner_of_use_record(record):
    aoi = store.get("aois", record["aoi_id"])
    return derive.permittee_of_aoi(aoi) if aoi else None


@bp.post("/annual-operating-instructions")
def create_aoi():
    body = parse_body(json_body(), AOI_FIELDS)
    date_range(body["season_start_date"], body["season_end_date"], False,
               "season_start_date must be on or before season_end_date")
    auth.authenticate(["RangeSpecialist", "AuthorizedOfficer"])
    permit = find.need("permits", body["permit_id"])
    if permit["permit_status"] != "ISSUED":
        gates.state("ERR_PERMIT_STATE_INVALID",
                    "the permit must be ISSUED to carry an operating instruction")
    allotment = derive.allotment_of_permit(permit)
    gates.closed(allotment)
    for other in store.rows("aois"):
        if other["permit_id"] == permit["id"] \
                and other["grazing_year"] == body["grazing_year"] \
                and other["aoi_status"] != "VOIDED":
            raise ApiError("ERR_DUPLICATE_AOI_FOR_YEAR",
                           "this permit already has an instruction for that year")
    window_start, window_end = gates.season_window(allotment, body["grazing_year"])
    if body["season_start_date"] < window_start \
            or body["season_end_date"] > window_end:
        gates.season("the declared season falls outside the allotment's season of use")
    gates.debt(permit["permittee_id"])
    gates.capacity(allotment, body["authorized_aums"])
    record = store.insert("aois", {
        "permit_id": permit["id"],
        "grazing_year": body["grazing_year"],
        "authorized_aums": body["authorized_aums"],
        "authorized_aums_at_issue": body["authorized_aums"],
        "nonuse_aums": 0,
        "nonuse_reason": None,
        "season_start_date": body["season_start_date"].isoformat(),
        "season_end_date": body["season_end_date"].isoformat(),
        "aoi_status": "DRAFT",
        "void_reason": None,
    })
    return envelope.created(derive.aoi_json(record))


@bp.get("/annual-operating-instructions")
def list_aois():
    envelope.page_params()
    actor = auth.any_operational()
    records = envelope.sort_default(store.rows("aois"))
    records = auth.scope_permittee_rows(actor, records, derive.permittee_of_aoi)
    allotment_id = request.args.get("allotment_id")
    if allotment_id:
        records = [row for row in records
                   if (derive.allotment_of_aoi(row) or {}).get("id") == allotment_id]
    records = find.apply_filters(records, [
        ("permit_id", "permit_id", "str"),
        ("grazing_year", "grazing_year", "int"),
        ("aoi_status", "aoi_status", "str"),
        ("nonuse_reason", "nonuse_reason", "str"),
    ])
    return envelope.paginate(records, derive.aoi_json)


@bp.get("/annual-operating-instructions/<aoi_id>")
def get_aoi(aoi_id):
    actor = auth.any_operational()
    aoi = find.need("aois", aoi_id)
    auth.require_own(actor, derive.permittee_of_aoi(aoi))
    return envelope.ok(derive.aoi_json(aoi))


@bp.post("/annual-operating-instructions/<aoi_id>/use-records")
def create_use_record(aoi_id):
    body = parse_body(json_body(), USE_RECORD_FIELDS)
    date_range(body["planned_entry_date"], body["planned_exit_date"], True,
               "planned_entry_date must be strictly before planned_exit_date")
    auth.authenticate(["RangeSpecialist", "AuthorizedOfficer"])
    aoi = find.need("aois", aoi_id)
    permit = store.get("permits", aoi["permit_id"])
    if permit is not None and body["livestock_kind"] != permit["livestock_kind"]:
        bad("livestock_kind must equal the permit's livestock_kind")
    pasture = find.need("pastures", body["pasture_id"])
    if aoi["aoi_status"] != "DRAFT":
        aoi_state("use records may only be scheduled on a DRAFT instruction")
    allotment = derive.allotment_of_permit(permit)
    gates.closed(allotment)
    if allotment is None or pasture["allotment_id"] != allotment["id"]:
        raise ApiError("ERR_PASTURE_NOT_IN_ALLOTMENT",
                       "the pasture belongs to another allotment")
    season_start = day(aoi["season_start_date"])
    season_end = day(aoi["season_end_date"])
    if body["planned_entry_date"] < season_start \
            or body["planned_exit_date"] > season_end + timedelta(days=1):
        gates.season("the planned window falls outside the instruction's season")
    planned_aums = calc.forage_aums(
        body["planned_head_count"], body["livestock_kind"],
        calc.whole_days(body["planned_entry_date"], body["planned_exit_date"]))
    if services.pasture_scheduled_conflict(
            pasture, None, aoi, body["planned_entry_date"],
            body["planned_exit_date"], planned_aums):
        raise ApiError("ERR_PASTURE_CAPACITY_EXCEEDED",
                       "the pasture would exceed its concurrent AUM capacity")
    record = store.insert("use_records", {
        "aoi_id": aoi["id"],
        "pasture_id": pasture["id"],
        "planned_entry_date": body["planned_entry_date"].isoformat(),
        "planned_exit_date": body["planned_exit_date"].isoformat(),
        "planned_head_count": body["planned_head_count"],
        "livestock_kind": body["livestock_kind"],
        "planned_aums": planned_aums,
        "actual_entry_date": None,
        "actual_exit_date": None,
        "actual_head_count": None,
        "actual_aums": None,
        "record_status": "SCHEDULED",
    })
    return envelope.created(derive.use_record_json(record))


@bp.get("/pasture-use-records")
def list_use_records():
    envelope.page_params()
    actor = auth.any_operational()
    records = envelope.sort_default(store.rows("use_records"))
    records = auth.scope_permittee_rows(actor, records, owner_of_use_record)
    records = find.apply_filters(records, [
        ("aoi_id", "aoi_id", "str"),
        ("pasture_id", "pasture_id", "str"),
        ("record_status", "record_status", "str"),
    ])
    return envelope.paginate(records, derive.use_record_json)


@bp.get("/pasture-use-records/<use_record_id>")
def get_use_record(use_record_id):
    actor = auth.any_operational()
    record = find.need("use_records", use_record_id)
    aoi = store.get("aois", record["aoi_id"])
    auth.require_own(actor, derive.permittee_of_aoi(aoi) if aoi else None)
    return envelope.ok(derive.use_record_json(record))


def active_order_of_type(allotment_id, order_type):
    for order in store.rows("closure_orders"):
        if order["allotment_id"] == allotment_id \
                and order["order_type"] == order_type \
                and order["order_status"] == "ACTIVE":
            return True
    return False


def rotation_failure(message):
    raise ApiError("ERR_ROTATION_REQUIREMENT_NOT_MET", message)


@bp.post("/annual-operating-instructions/<aoi_id>/issue")
def issue_aoi(aoi_id):
    auth.authenticate(["AuthorizedOfficer"])
    aoi = find.need("aois", aoi_id)
    if aoi["aoi_status"] != "DRAFT":
        aoi_state("only a DRAFT instruction may be issued")
    permit = store.get("permits", aoi["permit_id"])
    if permit is None or permit["permit_status"] != "ISSUED":
        gates.state("ERR_PERMIT_STATE_INVALID", "the permit is no longer ISSUED")
    if derive.planned_aums_total(aoi) > aoi["authorized_aums"]:
        aoi_state("the schedule plans more forage than the year authorises")
    allotment = derive.allotment_of_permit(permit)
    gates.closed(allotment)
    records = derive.records_of_aoi(aoi["id"])
    if derive.distinct_pasture_count(aoi) \
            < allotment["required_pasture_rotation_count"]:
        rotation_failure("too few distinct pastures for the required rotation")
    for record in records:
        pasture = store.get("pastures", record["pasture_id"])
        if pasture is not None and pasture["rest_required"]:
            rotation_failure("a rested pasture may not be scheduled")
    billable = derive.billable_aums(aoi)
    gates.capacity(allotment, billable)
    aoi["aoi_status"] = "ISSUED"
    aoi["authorized_aums_at_issue"] = aoi["authorized_aums"]
    store.touch(aoi)
    store.touch(allotment)
    if billable > 0:
        services.issue_use_bill(aoi, "PRELIMINARY_USE", billable)
        services.refresh_account_status(permit["permittee_id"])
    return envelope.ok(derive.aoi_json(aoi))


@bp.post("/annual-operating-instructions/<aoi_id>/non-use")
def approve_nonuse(aoi_id):
    body = parse_body(json_body(), NONUSE_FIELDS)
    auth.authenticate(["AuthorizedOfficer"])
    aoi = find.need("aois", aoi_id)
    allotment = derive.allotment_of_aoi(aoi)
    amount = body["nonuse_aums"]
    reason = body["nonuse_reason"]
    allotment_id = allotment["id"] if allotment else None
    if amount < 1 or amount > aoi["authorized_aums"]:
        raise ApiError("ERR_NONUSE_EXCEEDS_AUTHORIZED",
                       "nonuse_aums must be between 1 and the authorized AUMs")
    if reason == "DROUGHT" \
            and not active_order_of_type(allotment_id, "DROUGHT_REDUCTION"):
        raise ApiError("ERR_NONUSE_EXCEEDS_AUTHORIZED",
                       "drought non-use requires an active drought reduction order")
    if reason == "WILDFIRE" \
            and not active_order_of_type(allotment_id, "WILDFIRE_CLOSURE"):
        raise ApiError("ERR_NONUSE_EXCEEDS_AUTHORIZED",
                       "wildfire non-use requires an active wildfire closure order")
    aoi["nonuse_aums"] = amount
    aoi["nonuse_reason"] = reason
    store.touch(aoi)
    services.settle_use_bill(aoi, "REVISED_USE", derive.billable_aums(aoi))
    permit = store.get("permits", aoi["permit_id"])
    if permit is not None:
        services.recompute_consecutive_nonuse_years(permit)
        services.refresh_account_status(permit["permittee_id"])
    return envelope.ok(derive.aoi_json(aoi))


@bp.post("/pasture-use-records/<use_record_id>/report-actual-use")
def report_actual_use(use_record_id):
    body = parse_body(json_body(), ACTUAL_FIELDS)
    date_range(body["actual_entry_date"], body["actual_exit_date"], True,
               "actual_entry_date must be strictly before actual_exit_date")
    actor = auth.authenticate(["Permittee", "RangeSpecialist"])
    record = find.need("use_records", use_record_id)
    aoi = store.get("aois", record["aoi_id"])
    auth.require_own(actor, derive.permittee_of_aoi(aoi) if aoi else None)
    if aoi is None or aoi["aoi_status"] != "ISSUED":
        aoi_state("actual use may only be reported on an ISSUED instruction")
    if record["record_status"] != "SCHEDULED":
        gates.state("ERR_USE_RECORD_STATE_INVALID",
                    "this leg has already been reported")
    if body["actual_entry_date"] < day(aoi["season_start_date"]) \
            or body["actual_exit_date"] > day(aoi["season_end_date"]):
        gates.season("the reported window falls outside the instruction's season")
    actual_aums = calc.forage_aums(
        body["actual_head_count"], record["livestock_kind"],
        calc.whole_days(body["actual_entry_date"], body["actual_exit_date"]))
    pasture = store.get("pastures", record["pasture_id"])
    if pasture is not None and services.pasture_scheduled_conflict(
            pasture, record["id"], aoi, body["actual_entry_date"],
            body["actual_exit_date"], actual_aums):
        raise ApiError("ERR_PASTURE_CAPACITY_EXCEEDED",
                       "the pasture would exceed its concurrent AUM capacity")
    record["actual_entry_date"] = body["actual_entry_date"].isoformat()
    record["actual_exit_date"] = body["actual_exit_date"].isoformat()
    record["actual_head_count"] = body["actual_head_count"]
    record["actual_aums"] = actual_aums
    record["record_status"] = "ACTUAL_REPORTED"
    store.touch(record)
    return envelope.ok(derive.use_record_json(record))


@bp.post("/annual-operating-instructions/<aoi_id>/accept-use-report")
def accept_use_report(aoi_id):
    auth.authenticate(["AuthorizedOfficer"])
    aoi = find.need("aois", aoi_id)
    if aoi["aoi_status"] != "ISSUED":
        aoi_state("only an ISSUED instruction may have its use report accepted")
    records = derive.records_of_aoi(aoi["id"])
    if not records or any(row["record_status"] == "SCHEDULED" for row in records):
        raise ApiError("ERR_ACTUAL_USE_INCOMPLETE",
                       "every scheduled leg must be reported first")
    for row in records:
        if row["record_status"] == "ACTUAL_REPORTED":
            row["record_status"] = "ACCEPTED"
            store.touch(row)
    billed = calc.final_billed_aums(derive.actual_aums_total(aoi),
                                    aoi["authorized_aums"], aoi["nonuse_aums"])
    services.settle_use_bill(aoi, "FINAL_USE", billed, create_if_missing=True)
    aoi["aoi_status"] = "BILLED"
    store.touch(aoi)
    permit = store.get("permits", aoi["permit_id"])
    if permit is not None:
        services.refresh_account_status(permit["permittee_id"])
    return envelope.ok(derive.aoi_json(aoi))


@bp.post("/annual-operating-instructions/<aoi_id>/void")
def void_aoi_route(aoi_id):
    body = parse_body(json_body(), VOID_FIELDS)
    auth.authenticate(["AuthorizedOfficer"])
    aoi = find.need("aois", aoi_id)
    if aoi["aoi_status"] not in ("DRAFT", "ISSUED", "USE_REPORTED"):
        aoi_state("this instruction can no longer be voided")
    for bill in store.rows("bills"):
        if bill["aoi_id"] == aoi["id"] and bill["amount_paid_cents"] > 0:
            aoi_state("an instruction with a paid bill may not be voided")
    services.void_aoi(aoi, body["void_reason"])
    return envelope.ok(derive.aoi_json(aoi))
