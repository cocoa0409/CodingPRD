"""District reads and writes (PRD 3.1, 3.2 lifecycle)."""
from decimal import Decimal

from flask import Blueprint

import config
import envelope
import serialize
import store
import validate
from auth import authenticate
from errors import fail
from routes.common import ADMIN, AUDITOR, BOARD, DMO, EVERY_ROLE, HEARING, OPERATOR, VIEWER, narrow
from services import core, plans as planservice
from store import put, set_if_changed, touch

bp = Blueprint("districts", __name__)


def _zones(body, required=True, default=None):
    raw = validate.array(body, "included_zones", required=required, default=None, min_len=1)
    if raw is None:
        return default
    for zone in raw:
        if not isinstance(zone, str) or zone not in config.INCLUDABLE_ZONES:
            fail("ERR_INVALID_REQUEST",
                 "included_zones must be a non-empty subset of %s."
                 % ", ".join(config.INCLUDABLE_ZONES))
    if len(set(raw)) != len(raw):
        fail("ERR_INVALID_REQUEST", "included_zones may not repeat a zone code.")
    return list(raw)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
@bp.get("/districts")
def list_districts():
    authenticate(EVERY_ROLE, public=True)
    status = envelope.enum_filter("status", config.DISTRICT_STATUSES)
    records = narrow(list(store.state.districts.values()), status=status)
    return envelope.paginate(records, serialize.district)


@bp.get("/districts/<district_id>")
def read_district(district_id):
    authenticate(EVERY_ROLE, public=True)
    return envelope.ok(serialize.district(validate.district(district_id)))


@bp.get("/districts/<district_id>/financial-summary")
def financial_summary(district_id):
    authenticate([VIEWER, ADMIN, BOARD, AUDITOR], public=True)
    district = validate.district(district_id)
    fiscal_year = envelope.int_filter("fiscal_year")

    statements = core.statements_of_district(district["id"])
    if fiscal_year is not None:
        prefix = "FY%d" % fiscal_year
        statements = [s for s in statements
                      if core.period_of_statement(s)["period_label"].startswith(prefix)]

    data = {
        "district_id": district["id"],
        "fiscal_year": fiscal_year if fiscal_year is not None else district["current_fiscal_year"],
        "billed_total_cents": sum(s["effective_assessment_cents"] for s in statements),
        "collected_to_date_cents": sum(
            s["interest_paid_cents"] + s["penalty_paid_cents"]
            + s["principal_paid_cents"] + s["credit_balance_cents"] for s in statements),
        "delinquent_charges_cents": sum(
            s["penalty_cents"] + s["interest_cents"] for s in statements),
        "outstanding_total_cents": sum(s["total_due_cents"] for s in statements),
        "credit_total_cents": sum(s["credit_balance_cents"] for s in statements),
        "statement_count": len(statements),
        "delinquent_statement_count": len(
            [s for s in statements if s["payment_status"] == "DELINQUENT"]),
        "lodging_tax_match_committed_cents": district["lodging_tax_match_committed_cents"],
    }
    return envelope.ok(data)


@bp.get("/districts/<district_id>/lodging-businesses")
def list_district_businesses(district_id):
    authenticate([ADMIN, BOARD, AUDITOR, HEARING])
    district = validate.district(district_id)
    status = envelope.enum_filter("status", config.BUSINESS_STATUSES)
    zone = envelope.enum_filter("boundary_zone", config.ZONES)
    records = narrow(core.businesses_of_district(district["id"]),
                     status=status, boundary_zone=zone)
    return envelope.paginate(records, serialize.business)


@bp.get("/districts/<district_id>/petition-drives")
def list_district_drives(district_id):
    authenticate([ADMIN, BOARD, AUDITOR, VIEWER], public=True)
    district = validate.district(district_id)
    drive_type = envelope.enum_filter("drive_type", config.DRIVE_TYPES)
    status = envelope.enum_filter("status", config.DRIVE_STATUSES)
    records = narrow(core.drives_of_district(district["id"]),
                     drive_type=drive_type, status=status)
    return envelope.paginate(records, serialize.drive)


@bp.get("/districts/<district_id>/assessment-periods")
def list_district_periods(district_id):
    authenticate([ADMIN, BOARD, AUDITOR])
    district = validate.district(district_id)
    status = envelope.enum_filter("status", config.PERIOD_STATUSES)
    records = narrow(core.periods_of_district(district["id"]), status=status)
    # The one documented exception to created_at ordering (PRD 2.3).
    return envelope.paginate(records, serialize.period,
                            sort_key=lambda r: (r["period_start"], r["_seq"]))


@bp.get("/districts/<district_id>/annual-work-plans")
def list_district_plans(district_id):
    authenticate([ADMIN, BOARD, AUDITOR, DMO, VIEWER], public=True)
    district = validate.district(district_id)
    fiscal_year = envelope.int_filter("fiscal_year")
    status = envelope.enum_filter("status", config.WORK_PLAN_STATUSES)
    records = narrow(core.plans_of_district(district["id"]),
                     fiscal_year=fiscal_year, status=status)
    return envelope.paginate(records, serialize.plan)


@bp.get("/districts/<district_id>/transparency-records")
def list_district_records(district_id):
    authenticate([VIEWER, ADMIN, BOARD, AUDITOR, OPERATOR], public=True)
    district = validate.district(district_id)
    record_type = envelope.enum_filter("record_type", config.RECORD_TYPES)
    status = envelope.enum_filter("status", config.TRANSPARENCY_STATUSES)
    fiscal_year = envelope.int_filter("fiscal_year")
    records = narrow(core.records_of_district(district["id"]),
                     record_type=record_type, status=status, fiscal_year=fiscal_year)
    return envelope.paginate(records, serialize.record)


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------
@bp.post("/districts")
def create_district():
    authenticate([ADMIN])
    b = validate.body()

    name = validate.text(b, "name", max_len=120)
    if not name.strip():
        fail("ERR_INVALID_REQUEST", "name may not be blank.")
    method = validate.enum(b, "assessment_method", config.ASSESSMENT_METHODS,
                           required=False, default="PCT_OF_ROOM_REVENUE")
    zones = _zones(b, required=False, default=list(config.INCLUDABLE_ZONES))
    formation_pct = validate.ratio(b, "formation_threshold_pct", required=False,
                                   default=config.DEFAULT_FORMATION_THRESHOLD,
                                   minimum=Decimal("0.0001"), maximum=Decimal("1.0000"))
    renewal_pct = validate.ratio(b, "renewal_threshold_pct", required=False,
                                 default=config.DEFAULT_RENEWAL_THRESHOLD,
                                 minimum=Decimal("0.0001"), maximum=Decimal("1.0000"))
    headcount_pct = validate.ratio(b, "renewal_headcount_threshold_pct", required=False,
                                   default=config.DEFAULT_RENEWAL_HEADCOUNT_THRESHOLD,
                                   minimum=Decimal("0.0001"), maximum=Decimal("1.0000"))
    term_years = validate.integer(b, "term_years", required=False,
                                  default=config.DEFAULT_TERM_YEARS, minimum=1, maximum=10)
    fiscal_year = validate.integer(b, "current_fiscal_year", required=False,
                                   default=config.DEFAULT_FISCAL_YEAR,
                                   minimum=2020, maximum=2050)

    rec = store.new_record("district")
    rec.update({
        "name": name,
        "assessment_method": method,
        "included_zones": zones,
        "status": "PROPOSED",
        "formation_threshold_pct": formation_pct,
        "renewal_threshold_pct": renewal_pct,
        "renewal_headcount_threshold_pct": headcount_pct,
        "term_years": term_years,
        "formed_on": None,
        "expiration_date": None,
        "current_fiscal_year": fiscal_year,
        "transparency_standing": "COMPLIANT",
        "dmo_name": None,
        "dmo_agreement_status": "NONE",
        "dmo_contract_cents": 0,
        "public_lodging_tax_offset_cents": 0,
        "lodging_tax_match_pool_cents": 0,
        "lodging_tax_match_committed_cents": 0,
        "collected_to_date_cents": 0,
        "delinquent_charges_cents": 0,
        "assessable_basis_cents": 0,
        "assessable_business_count": 0,
    })
    put("districts", rec)
    return envelope.created(serialize.district(rec))


@bp.post("/districts/<district_id>/boundary-revisions")
def revise_boundary(district_id):
    authenticate([ADMIN])
    b = validate.body()
    zones = _zones(b, required=True)
    validate.instant(b, "effective_on", required=True)
    district = validate.district(district_id)

    district["included_zones"] = zones
    touch(district)

    # One pass over the roll, in created_at order (PRD 3.1).
    for business in store.sorted_records(core.businesses_of_district(district["id"])):
        if business["status"] == "ASSESSABLE" and business["boundary_zone"] not in zones:
            business["status"] = "OUTSIDE_BOUNDARY"
            touch(business)
            core.disqualify_signatures(business, "OUTSIDE_BOUNDARY")
        elif (business["status"] == "OUTSIDE_BOUNDARY"
                and business["boundary_zone"] in zones
                and business["exempt_status"] == "NONE"
                and business["room_count"] >= config.MIN_ROOM_COUNT):
            business["status"] = "ASSESSABLE"
            touch(business)

    core.recompute_district_aggregates(district)
    core.rescore_open_drives(district)
    return envelope.ok(serialize.district(district))


@bp.post("/districts/<district_id>/dmo-coordination")
def coordinate_dmo(district_id):
    authenticate([ADMIN])
    b = validate.body()

    dmo_name = validate.text(b, "dmo_name")
    if not dmo_name.strip():
        fail("ERR_INVALID_REQUEST", "dmo_name may not be blank.")
    agreement = validate.enum(b, "dmo_agreement_status", config.DMO_AGREEMENT_STATUSES)
    contract_cents = validate.cents(b, "dmo_contract_cents")
    pool_cents = validate.cents(b, "lodging_tax_match_pool_cents", required=False)
    offset_cents = validate.cents(b, "public_lodging_tax_offset_cents", required=False)

    district = validate.district(district_id)
    if pool_cents is None:
        pool_cents = district["lodging_tax_match_pool_cents"]
    if offset_cents is None:
        offset_cents = district["public_lodging_tax_offset_cents"]

    committed = district["lodging_tax_match_committed_cents"]
    if pool_cents < committed:
        fail("ERR_LODGING_TAX_MATCH_EXHAUSTED",
             "The pool may not fall below the %d cents already committed." % committed)
    approved = [p for p in core.plans_of_district(district["id"])
                if p["status"] == "APPROVED"
                and p["fiscal_year"] == district["current_fiscal_year"]]
    for plan in approved:
        ceiling = planservice.match_ceiling(plan)
        if committed > ceiling:
            fail("ERR_LODGING_TAX_MATCH_CAP_EXCEEDED",
                 "Committed lodging tax match may not exceed %d cents." % ceiling)

    set_if_changed(district, {
        "dmo_name": dmo_name,
        "dmo_agreement_status": agreement,
        "dmo_contract_cents": contract_cents,
        "lodging_tax_match_pool_cents": pool_cents,
        "public_lodging_tax_offset_cents": offset_cents,
    })
    touch(district)
    return envelope.ok(serialize.district(district))


def _cancel_programs(district, clear_frozen):
    """Disestablishment cascade (PRD 3.2 / 3.8)."""
    touched_plans = []
    for program in core.programs_of_district(district["id"]):
        if program["status"] not in ("PLANNED", "RUNNING", "SUSPENDED_PENDING_AMENDMENT"):
            continue
        program["status"] = "CANCELLED"
        if clear_frozen:
            program["spend_frozen"] = False
        touch(program)
        plan = core.plan_of_program(program)
        if plan["id"] not in [p["id"] for p in touched_plans]:
            touched_plans.append(plan)
    for plan in touched_plans:
        planservice.recompute_committed_program_cents(plan)
    core.recompute_lodging_tax_committed(district)


@bp.post("/districts/<district_id>/lifecycle-advances")
def advance_lifecycle(district_id):
    authenticate([ADMIN])
    b = validate.body()
    to_status = validate.enum(b, "to_status", config.LIFECYCLE_TARGETS)
    validate.instant(b, "effective_on", required=False)
    validate.text(b, "reason", required=False)
    district = validate.district(district_id)

    now = store.clock()
    origin = district["status"]

    if to_status == "ACTIVE":
        if origin != "FORMED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A district may be activated only from FORMED.")
        drive = core.formation_drive(district["id"])
        if drive is None or drive["status"] != "CERTIFIED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The district's FORMATION petition drive must be CERTIFIED.")
        if district["assessable_business_count"] < config.MIN_PETITION_POOL:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The assessable roll must still hold at least %d businesses."
                 % config.MIN_PETITION_POOL)
        district["status"] = "ACTIVE"

    elif to_status == "RENEWAL_PENDING":
        if origin != "ACTIVE":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "Renewal may be opened only on an ACTIVE district.")
        core.transparency_gate(district, require_no_overdue=True)
        expiry = district["expiration_date"]
        window_open = store.add_days(expiry, -config.RENEWAL_WINDOW_DAYS) if expiry else None
        if expiry is None or now < window_open or now >= expiry:
            fail("ERR_RENEWAL_WINDOW_NOT_OPEN",
                 "The renewal window runs from %d whole days before expiration up to it."
                 % config.RENEWAL_WINDOW_DAYS)
        district["status"] = "RENEWAL_PENDING"

    elif to_status == "EXPIRED":
        if origin not in ("ACTIVE", "RENEWAL_PENDING"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A term may lapse only from ACTIVE or RENEWAL_PENDING.")
        if district["expiration_date"] is None or now < district["expiration_date"]:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The logical clock has not yet reached the expiration date.")
        district["status"] = "EXPIRED"
        # Expiry deliberately leaves OPEN assessment periods untouched.
        if origin == "RENEWAL_PENDING":
            core.withdraw_open_drives(district)

    else:
        if origin not in ("ACTIVE", "RENEWAL_PENDING"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A district may be dissolved only from ACTIVE or RENEWAL_PENDING.")
        if any(p["status"] == "OPEN" for p in core.periods_of_district(district["id"])):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "No assessment period of the district may still be OPEN.")
        district["status"] = "DISESTABLISHED"
        core.withdraw_open_drives(district)
        _cancel_programs(district, clear_frozen=(origin == "ACTIVE"))

    touch(district)
    return envelope.ok(serialize.district(district))
