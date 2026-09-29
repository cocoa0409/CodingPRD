"""Relief programmes, parcels, taxpayer accounts, the ownership registry and
the test-driving clock and registry-injection capabilities (PRD §3.1, §3.2).
"""

from flask import Blueprint

import calc
import db
import enums
import envelope as env
import services
import validate as v
from errors import fail
from validate import endpoint

bp = Blueprint("roll", __name__)


# --------------------------------------------------------------------------
# ReliefProgram
# --------------------------------------------------------------------------
@bp.post("/relief-programs")
@endpoint(["ProgramAdministrator"])
def create_relief_program():
    body = v.body()
    program_code = v.req_enum(body, "program_code", enums.PROGRAM_CODES)
    name = v.req_str(body, "name")
    relief_pct_bps = v.req_int(body, "relief_pct_bps", minimum=1, maximum=10000)
    max_exempt_value_cents = v.req_int(body, "max_exempt_value_cents", minimum=0)
    statutory_lookback_years = v.req_int(body, "statutory_lookback_years", minimum=0, maximum=5)
    penalty_pct_bps = v.req_int(body, "penalty_pct_bps", minimum=0)
    interest_pct_bps_per_year = v.req_int(body, "interest_pct_bps_per_year", minimum=0)
    priority_rank = v.req_int(body, "priority_rank", minimum=1, maximum=99)
    income_limit_cents = v.opt_int(body, "income_limit_cents", None, minimum=0)
    asset_limit_cents = v.opt_int(body, "asset_limit_cents", None, minimum=0)
    requires_income_certification = v.opt_bool(body, "requires_income_certification", False)
    recertification_required = v.opt_bool(body, "recertification_required", False)
    freeze_enabled = v.opt_bool(body, "freeze_enabled", False)

    for existing in db.rows("relief_programs"):
        if existing["program_code"] == program_code:
            fail("ERR_INVALID_REQUEST", "program_code must be unique across relief programmes.")
        if existing["priority_rank"] == priority_rank:
            fail("ERR_INVALID_REQUEST", "priority_rank must be unique across relief programmes.")

    program = db.insert("relief_programs", {
        "program_code": program_code,
        "name": name,
        "relief_pct_bps": relief_pct_bps,
        "max_exempt_value_cents": max_exempt_value_cents,
        "income_limit_cents": income_limit_cents,
        "asset_limit_cents": asset_limit_cents,
        "requires_income_certification": requires_income_certification,
        "recertification_required": recertification_required,
        "freeze_enabled": freeze_enabled,
        "statutory_lookback_years": statutory_lookback_years,
        "penalty_pct_bps": penalty_pct_bps,
        "interest_pct_bps_per_year": interest_pct_bps_per_year,
        "priority_rank": priority_rank,
        "status": "OPEN",
    })
    return env.created(db.public(program))


@bp.get("/relief-programs/<program_id>")
@endpoint(["ProgramAdministrator", "ExemptionsReviewer", "IntakeClerk"])
def read_relief_program(program_id):
    program = db.get("relief_programs", program_id)
    if program is None:
        fail("ERR_PROGRAM_NOT_FOUND")
    return env.ok(db.public(program))


# --------------------------------------------------------------------------
# Parcel
# --------------------------------------------------------------------------
@bp.post("/parcels")
@endpoint(["AssessorAnalyst"])
def create_parcel():
    body = v.body()
    apn = v.req_str(body, "apn")
    situs = v.req_str(body, "situs_address_normalized")
    county_zone = v.req_enum(body, "county_zone", enums.COUNTY_ZONES)
    tax_year = v.req_int(body, "tax_year", minimum=2015, maximum=2100)
    base_year = v.req_int(body, "base_year", minimum=0)
    base_year_value_cents = v.req_int(body, "base_year_value_cents", minimum=0)
    market_value_cents = v.req_int(body, "market_value_cents", minimum=0)
    cap_bps = v.opt_int(body, "assessment_cap_pct_bps", db.DEFAULT_ASSESSMENT_CAP_PCT_BPS,
                        minimum=0, maximum=2000)
    if base_year > tax_year:
        fail("ERR_INVALID_REQUEST", "base_year must not be later than tax_year.")

    for existing in db.rows("parcels"):
        if existing["apn"] == apn:
            fail("ERR_INVALID_REQUEST", "apn must be unique across the parcel roll.")

    parcel = db.insert("parcels", {
        "apn": apn,
        "situs_address_normalized": situs,
        "county_zone": county_zone,
        "tax_year": tax_year,
        "base_year": base_year,
        "base_year_value_cents": base_year_value_cents,
        "market_value_cents": market_value_cents,
        "assessment_cap_pct_bps": cap_bps,
        "capped_value_cents": 0,
        "assessed_value_cents": 0,
        "exempt_value_cents": 0,
        "taxable_value_cents": 0,
        "exemption_status": "UNEXEMPTED",
    })
    calc.decompose(parcel, bump_version=False)
    return env.created(db.public(parcel))


@bp.get("/parcels/<parcel_id>")
@endpoint(["AssessorAnalyst", "ExemptionsReviewer", "IntakeClerk", "FraudInvestigator"])
def read_parcel(parcel_id):
    parcel = db.get("parcels", parcel_id)
    if parcel is None:
        fail("ERR_PARCEL_NOT_FOUND")
    return env.ok(db.public(parcel))


# --------------------------------------------------------------------------
# TaxpayerAccount
# --------------------------------------------------------------------------
@bp.post("/taxpayer-accounts")
@endpoint(["IntakeClerk"])
def create_taxpayer_account():
    body = v.body()
    full_name = v.req_str(body, "full_name")
    date_of_birth = v.req_date(body, "date_of_birth")
    ssn_last4 = v.req_str(body, "ssn_last4")
    if len(ssn_last4) != 4 or not ssn_last4.isdigit():
        fail("ERR_INVALID_REQUEST", "ssn_last4 must be exactly four digits.")
    mailing = v.req_str(body, "mailing_address_normalized")
    rating = v.opt_int(body, "disability_rating_pct_bps", 0, minimum=0, maximum=10000)

    account = db.insert("taxpayer_accounts", {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "ssn_last4": ssn_last4,
        "mailing_address_normalized": mailing,
        "disability_rating_pct_bps": rating,
        "lifetime_refund_cents": 0,
        "lifetime_recovery_collected_cents": 0,
        "net_relief_cents": 0,
        "status": "GOOD_STANDING",
    })
    return env.created(db.public(account))


@bp.get("/taxpayer-accounts/<taxpayer_id>")
@endpoint(["IntakeClerk", "ExemptionsReviewer", "FraudInvestigator", "RecoveryOfficer",
           "Taxpayer"])
def read_taxpayer_account(taxpayer_id):
    account = db.get("taxpayer_accounts", taxpayer_id)
    if account is None:
        fail("ERR_TAXPAYER_NOT_FOUND")
    if v.is_taxpayer() and account["id"] != v.caller_id():
        fail("ERR_NOT_RESOURCE_OWNER")
    return env.ok(db.public(account))


# --------------------------------------------------------------------------
# OwnershipRecord
# --------------------------------------------------------------------------
def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval intersection; None end means open-ended."""
    if a_end is not None and b_start >= a_end:
        return False
    if b_end is not None and a_start >= b_end:
        return False
    return True


@bp.post("/ownership-records")
@endpoint(["AssessorAnalyst"])
def create_ownership_record():
    body = v.body()
    parcel_id = v.req_str(body, "parcel_id")
    taxpayer_id = v.req_str(body, "taxpayer_id")
    ownership_pct_bps = v.req_int(body, "ownership_pct_bps", minimum=1, maximum=10000)
    deed_recorded_date = v.req_date(body, "deed_recorded_date")
    occupancy_type = v.req_enum(body, "occupancy_type", enums.OCCUPANCY_TYPES)
    occupancy_start_date = v.req_date(body, "occupancy_start_date")
    source_system = v.req_enum(body, "source_system", enums.SOURCE_SYSTEMS)
    occupancy_end_date = v.opt_date(body, "occupancy_end_date", None)
    if occupancy_end_date is not None and occupancy_end_date <= occupancy_start_date:
        fail("ERR_INVALID_REQUEST", "occupancy_end_date must be strictly after occupancy_start_date.")

    parcel = db.get("parcels", parcel_id)
    if parcel is None:
        fail("ERR_PARCEL_NOT_FOUND")
    taxpayer = db.get("taxpayer_accounts", taxpayer_id)
    if taxpayer is None:
        fail("ERR_TAXPAYER_NOT_FOUND")

    # The open-ended predecessor for this parcel-and-taxpayer pair is truncated by
    # this ingestion, so the geometry checks see it already closed at the new start.
    predecessors = [
        r
        for r in db.rows("ownership_records")
        if r["parcel_id"] == parcel_id
        and r["taxpayer_id"] == taxpayer_id
        and r["occupancy_end_date"] is None
    ]
    truncation_target = None
    if predecessors:
        # Greatest occupancy_start_date wins; the earlier created_at breaks a tie.
        greatest_start = max(r["occupancy_start_date"] for r in predecessors)
        tied = [r for r in predecessors if r["occupancy_start_date"] == greatest_start]
        truncation_target = sorted(tied, key=lambda r: (r["created_at"], r["_seq"]))[0]

    def effective_end(record):
        if truncation_target is not None and record["id"] == truncation_target["id"]:
            return occupancy_start_date
        return record["occupancy_end_date"]

    if occupancy_type == "PRIMARY_RESIDENCE":
        for record in db.rows("ownership_records"):
            if record["occupancy_type"] != "PRIMARY_RESIDENCE":
                continue
            if record["parcel_id"] != parcel_id:
                continue
            if _overlaps(occupancy_start_date, occupancy_end_date,
                         record["occupancy_start_date"], effective_end(record)):
                fail("ERR_OCCUPANCY_INTERVAL_OVERLAP")
        for record in db.rows("ownership_records"):
            if record["occupancy_type"] != "PRIMARY_RESIDENCE":
                continue
            if record["taxpayer_id"] != taxpayer_id or record["parcel_id"] == parcel_id:
                continue
            if _overlaps(occupancy_start_date, occupancy_end_date,
                         record["occupancy_start_date"], effective_end(record)):
                fail("ERR_DUPLICATE_PRIMARY_RESIDENCE")

    status = "VERIFIED" if source_system in ("DEED_REGISTRY", "FIELD_INSPECTION") else "UNVERIFIED"
    record = db.insert("ownership_records", {
        "parcel_id": parcel_id,
        "taxpayer_id": taxpayer_id,
        "ownership_pct_bps": ownership_pct_bps,
        "deed_recorded_date": deed_recorded_date,
        "occupancy_type": occupancy_type,
        "occupancy_start_date": occupancy_start_date,
        "occupancy_end_date": occupancy_end_date,
        "source_system": source_system,
        "status": status,
    })

    if truncation_target is not None:
        truncation_target["occupancy_end_date"] = occupancy_start_date
        truncation_target["status"] = "SUPERSEDED"
        db.touch(truncation_target)
        if occupancy_type in ("SECONDARY", "RENTAL"):
            for grant in db.rows("exemption_grants"):
                if grant["parcel_id"] != parcel_id or grant["taxpayer_id"] != taxpayer_id:
                    continue
                if grant["benefit_status"] != "ACTIVE":
                    continue
                if grant["exemption_type"] == "AGRICULTURAL_USE":
                    continue
                if grant.get("_supporting_ownership_record_id") != truncation_target["id"]:
                    continue
                services.suspend_grant(
                    grant,
                    "OCCUPANCY_LOST",
                    summary="Exemption grant suspended: primary-residence occupancy lost.",
                )

    return env.created(db.public(record))


@bp.get("/ownership-records/<record_id>")
@endpoint(["AssessorAnalyst", "ExemptionsReviewer"])
def read_ownership_record(record_id):
    record = db.get("ownership_records", record_id)
    if record is None:
        fail("ERR_PARCEL_NOT_FOUND")
    return env.ok(db.public(record))


@bp.get("/ownership-records")
@endpoint(["AssessorAnalyst", "ExemptionsReviewer"])
def list_ownership_records():
    limit, offset = v.pagination()
    parcel_id = v.q_str("parcel_id")
    taxpayer_id = v.q_str("taxpayer_id")
    occupancy_type = v.q_enum("occupancy_type", enums.OCCUPANCY_TYPES)
    status = v.q_enum("status", enums.OWNERSHIP_STATUSES)
    items = []
    for record in db.rows("ownership_records"):
        if parcel_id is not None and record["parcel_id"] != parcel_id:
            continue
        if taxpayer_id is not None and record["taxpayer_id"] != taxpayer_id:
            continue
        if occupancy_type is not None and record["occupancy_type"] != occupancy_type:
            continue
        if status is not None and record["status"] != status:
            continue
        items.append(db.public(record))
    return env.listing(items, limit, offset)


# --------------------------------------------------------------------------
# Test-driving capabilities
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@endpoint(["ProgramAdministrator"])
def set_clock():
    body = v.body()
    instant = v.req_instant(body, "to_iso8601")
    db.set_now(instant)
    return env.ok({"current_utc": db.now_iso()})


@bp.post("/_registry-records")
@endpoint(["ProgramAdministrator"])
def inject_registry_record():
    body = v.body()
    taxpayer_id = v.req_str(body, "taxpayer_id")
    source = v.req_enum(body, "source", enums.CHECK_SOURCES)
    record_effective_date = v.req_date(body, "record_effective_date")
    address_normalized = v.opt_str(body, "address_normalized", None)
    reported_income_cents = v.opt_int(body, "reported_income_cents", None, minimum=0)

    if db.get("taxpayer_accounts", taxpayer_id) is None:
        fail("ERR_TAXPAYER_NOT_FOUND")

    record = db.insert("registry_records", {
        "taxpayer_id": taxpayer_id,
        "source": source,
        "record_effective_date": record_effective_date,
        "address_normalized": address_normalized,
        "reported_income_cents": reported_income_cents,
    }, versioned=False)
    return env.created({
        "record_id": record["id"],
        "taxpayer_id": taxpayer_id,
        "source": source,
        "record_effective_date": record_effective_date,
    })
