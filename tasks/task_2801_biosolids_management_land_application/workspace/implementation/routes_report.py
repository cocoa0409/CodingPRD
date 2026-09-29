"""Annual report endpoints (PRD 3.12)."""

from decimal import Decimal

from flask import Blueprint, g

import store
from auth import roles
from envelope import object_response
from errors import fail
from listing import emit_list
from store import D, now, now_iso, parse_dt, public, r2, r3, touch
from validate import (get_body, present, qenum, qint, qstr, resolve_fks, vint, vstr)

bp = Blueprint("reports", __name__, url_prefix="/api/v1/annual-reports")

REPORT_STATUSES = ("DRAFT", "SUBMITTED", "AMENDED")
OUTLET_TYPES = ("COMPOST", "LANDFILL", "THERMAL")
READ_ROLES = ("ComplianceOfficer", "PublicLiaison", "FacilityOperator", "Agronomist")
OPEN_EVENT_STATUSES = ("SCHEDULED", "WEATHER_HOLD", "DEFERRED", "IN_PROGRESS")


def get_report(report_id):
    report = store.reports.get(report_id)
    if report is None:
        fail("ERR_REPORT_NOT_FOUND", "Annual report %s does not exist." % report_id)
    return report


def _year_of(value):
    parsed = parse_dt(value) if value else None
    return parsed.year if parsed is not None else None


def compute_rollup(report):
    facility_id = report["facility_id"]
    year = report["report_year"]

    land_applied = Decimal(0)
    site_ids = set()
    for event in store.events.values():
        if event["status"] != "COMPLETED":
            continue
        site = store.sites.get(event["site_id"])
        if site is None or site["facility_id"] != facility_id:
            continue
        if _year_of(event["window_start"]) != year:
            continue
        land_applied += D(event["applied_dry_tons"])
        site_ids.add(event["site_id"])

    diverted_by_type = {}
    for outlet_type in OUTLET_TYPES:
        diverted_by_type[outlet_type] = Decimal(0)
    for order in store.orders.values():
        if order["status"] != "SETTLED":
            continue
        if _year_of(order.get("settled_at")) != year:
            continue
        batch = store.batches.get(order["batch_id"])
        if batch is None or batch["facility_id"] != facility_id:
            continue
        outlet = store.outlets.get(order["outlet_id"])
        if outlet is None:
            continue
        diverted_by_type[outlet["outlet_type"]] += D(order["dry_tons"])
    diverted_by_type = {k: r3(v) for k, v in diverted_by_type.items()}

    denominator = 0
    numerator = 0
    for batch in store.batches.values():
        if batch["facility_id"] != facility_id:
            continue
        if batch["process_status"] != "DEWATERED":
            continue
        if _year_of(batch["created_at"]) != year:
            continue
        denominator += 1
        vsr = batch.get("vsr_pct_van_kleeck")
        if vsr is not None and D(vsr) >= Decimal("38.00"):
            numerator += 1
    if denominator == 0:
        vsr_rate = r2(0)
    else:
        vsr_rate = r2(Decimal(numerator) / Decimal(denominator) * Decimal(100))

    exceedances = 0
    for result in store.lab_results.values():
        if not result["exceeds_ceiling"]:
            continue
        batch = store.batches.get(result["batch_id"])
        if batch is None or batch["facility_id"] != facility_id:
            continue
        if _year_of(result["analyzed_at"]) != year:
            continue
        exceedances += 1

    report["total_dry_tons_land_applied"] = r3(land_applied)
    report["diverted_dry_tons_by_outlet_type"] = diverted_by_type
    report["total_dry_tons_diverted"] = r3(sum(diverted_by_type.values(), Decimal(0)))
    report["vsr_compliance_rate_pct"] = vsr_rate
    report["ceiling_exceedance_count"] = exceedances
    report["sites_reported_count"] = len(site_ids)


@bp.post("")
@roles("ComplianceOfficer", "PublicLiaison")
def create_report():
    body = get_body()
    fks = resolve_fks(body, ("facility_id",))
    facility_id = body.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id.strip():
        fail("ERR_INVALID_REQUEST", "Field 'facility_id' is required.")
    facility = fks["facility_id"]
    report_year = vint(body, "report_year", required=True)
    public_summary = vstr(body, "public_summary", required=False, min_len=1,
                          max_len=1000, default=None)
    for existing in store.reports.values():
        if (existing["facility_id"] == facility["id"]
                and existing["report_year"] == report_year
                and existing["status"] in REPORT_STATUSES):
            fail("ERR_DUPLICATE_RESOURCE",
                 "An annual report for %d already exists." % report_year)
    report = store.new_record({
        "facility_id": facility["id"],
        "report_year": report_year,
        "public_summary": public_summary,
        "status": "DRAFT",
        "amendment_index": 0,
        "total_dry_tons_land_applied": r3(0),
        "total_dry_tons_diverted": r3(0),
        "diverted_dry_tons_by_outlet_type": {},
        "vsr_compliance_rate_pct": r2(0),
        "ceiling_exceedance_count": 0,
        "sites_reported_count": 0,
        "submitted_at": None,
        "submitted_by_user_id": None,
        "amendment_reason": None,
        "updated_at": now_iso(),
        "version": 1,
    })
    store.reports[report["id"]] = report
    return object_response(public(report), 201)


@bp.get("/<report_id>")
@roles(*READ_ROLES)
def read_report(report_id):
    return object_response(public(get_report(report_id)))


@bp.get("")
@roles(*READ_ROLES)
def list_reports():
    facility_id = qstr("facility_id")
    report_year = qint("report_year")
    status = qenum("status", REPORT_STATUSES)
    rows = [r for r in store.reports.values()
            if (facility_id is None or r["facility_id"] == facility_id)
            and (report_year is None or r["report_year"] == report_year)
            and (status is None or r["status"] == status)]
    return emit_list(rows, ("report_year", "created_at"))


@bp.post("/<report_id>/submit")
@roles("ComplianceOfficer")
def submit_report(report_id):
    report = get_report(report_id)
    body = get_body()
    supplied_summary = vstr(body, "public_summary", required=False, min_len=1,
                            max_len=1000, default=None)
    effective_summary = (supplied_summary if supplied_summary is not None
                         else report["public_summary"])
    if effective_summary is None or not str(effective_summary).strip():
        fail("ERR_INVALID_REQUEST",
             "public_summary must be non-blank when the report is submitted.")
    if report["report_year"] > now().year:
        fail("ERR_INVALID_REQUEST",
             "report_year must be at or before the current calendar year.")
    if report["status"] not in ("DRAFT", "AMENDED"):
        fail("ERR_REPORT_INVALID_STATE",
             "Only a DRAFT or AMENDED report may be submitted.")
    year = report["report_year"]
    facility_id = report["facility_id"]
    for event in store.events.values():
        if event["status"] not in OPEN_EVENT_STATUSES:
            continue
        site = store.sites.get(event["site_id"])
        if site is None or site["facility_id"] != facility_id:
            continue
        if _year_of(event["window_start"]) == year:
            fail("ERR_OPEN_EVENTS_EXIST",
                 "The report year still contains unfinished application events.")
    for batch in store.batches.values():
        if batch["facility_id"] != facility_id:
            continue
        if batch["quality_status"] != "PENDING_RESULTS":
            continue
        if _year_of(batch["created_at"]) == year:
            fail("ERR_OPEN_EVENTS_EXIST",
                 "The report year still contains batches awaiting results.")
    if supplied_summary is not None:
        report["public_summary"] = supplied_summary
    compute_rollup(report)
    report["status"] = "SUBMITTED"
    report["submitted_at"] = now_iso()
    report["submitted_by_user_id"] = g.user_id
    touch(report)
    return object_response(public(report))


@bp.post("/<report_id>/amend")
@roles("ComplianceOfficer")
def amend_report(report_id):
    report = get_report(report_id)
    body = get_body()
    supplied_summary = vstr(body, "public_summary", required=False, min_len=1,
                            max_len=1000, default=None)
    amendment_reason = None
    if present(body, "amendment_reason"):
        amendment_reason = vstr(body, "amendment_reason", required=True, min_len=1)
    if report["status"] not in ("SUBMITTED", "AMENDED"):
        fail("ERR_REPORT_INVALID_STATE",
             "Only a SUBMITTED or AMENDED report may be amended.")
    if supplied_summary is not None:
        report["public_summary"] = supplied_summary
    if amendment_reason is not None:
        report["amendment_reason"] = amendment_reason
    compute_rollup(report)
    report["status"] = "AMENDED"
    report["amendment_index"] = report["amendment_index"] + 1
    report["submitted_at"] = now_iso()
    touch(report)
    return object_response(public(report))
