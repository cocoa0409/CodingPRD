"""StateContract, BenefitProgram, allotment runs, data deliveries."""
import calendar
import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint

from errors import ApiError
from state import DB
from domain import (
    new_entity, touch, post_entry, ser_contract, ser_program, ser_retailer,
    ser_delivery, case_purses,
)
from util import (
    authed, body, req_str, opt_int, ok_object, list_response, sort_created,
    parse_iso_date, query_filter,
)
import util

bp = Blueprint("contracts", __name__, url_prefix="/ebt")

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
BENEFIT_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# (field, default, min, max)
CONTRACT_CONFIG = [
    ("default_posting_modulus", 10, 1, 28),
    ("default_availability_hour_utc", 6, 0, 23),
    ("default_expungement_inactivity_days", 90, 31, None),
    ("expungement_notice_lead_days", 30, 1, None),
    ("default_disaster_expiry_days", 30, 1, None),
    ("default_replacement_fee_cents", 250, 0, None),
    ("free_replacements_per_365d", 1, 0, None),
    ("pin_max_failures", 3, 1, None),
    ("claim_window_days", 60, 1, None),
    ("provisional_credit_delay_days", 10, 1, None),
    ("provisional_credit_cap_cents", 50000, 0, None),
    ("skimming_suspend_threshold", 3, 1, None),
    ("dispute_window_days", 15, 1, None),
    ("acquirer_fee_basis_points", 75, 0, None),
    ("cash_withdrawal_daily_limit_cents", 50000, 0, None),
    ("cash_withdrawal_multiple_cents", 500, 1, None),
    ("settlement_cutoff_hour_utc", 0, 0, 23),
    ("card_mail_delay_hours", 24, 0, None),
]


def _floor_cutoff(now, cutoff_hour):
    candidate = now.replace(hour=cutoff_hour, minute=0, second=0, microsecond=0)
    if candidate > now:
        candidate -= timedelta(days=1)
    return candidate


def _month_start(now):
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _get_contract(cid):
    c = DB.contracts.get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "contract not found")
    return c


@bp.post("/contracts")
def create_contract():
    authed(["StateAdmin"])
    b = body()
    state_code = req_str(b, "state_code")
    c = new_entity()
    c["contract_status"] = "CONFIGURING"
    c["state_code"] = state_code
    for field, default, lo, hi in CONTRACT_CONFIG:
        val = opt_int(b, field, default)
        if lo is not None and val < lo:
            raise ApiError("ERR_INVALID_REQUEST", f"{field} must be >= {lo}")
        if hi is not None and val > hi:
            raise ApiError("ERR_INVALID_REQUEST", f"{field} must be <= {hi}")
        c[field] = val
    if not STATE_CODE_RE.match(state_code):
        raise ApiError("ERR_INVALID_REQUEST", "state_code must be two uppercase letters")
    now = util.now_dt()
    c["_last_cutoff"] = _floor_cutoff(now, c["settlement_cutoff_hour_utc"])
    c["_last_month"] = _month_start(now)
    DB.contracts[c["id"]] = c
    return ok_object(ser_contract(c), 201)


@bp.get("/contracts/<cid>")
def get_contract(cid):
    authed(["StateAdmin", "CardholderServices"])
    return ok_object(ser_contract(_get_contract(cid)))


@bp.post("/contracts/<cid>/status")
def contract_status(cid):
    authed(["StateAdmin"])
    c = _get_contract(cid)
    b = body()
    to = req_str(b, "to")
    if to not in ("CONFIGURING", "ACTIVE", "SUSPENDED", "CLOSED"):
        raise ApiError("ERR_INVALID_REQUEST", "unknown target status")
    cur = c["contract_status"]
    allowed = {
        ("CONFIGURING", "ACTIVE"),
        ("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE"),
        ("ACTIVE", "CLOSED"), ("SUSPENDED", "CLOSED"),
    }
    if (cur, to) not in allowed:
        raise ApiError("ERR_INVALID_STATE", f"cannot transition contract {cur} -> {to}")
    if cur == "CONFIGURING" and to == "ACTIVE":
        if not any(p["contract_id"] == c["id"] for p in DB.programs.values()):
            raise ApiError("ERR_INVALID_STATE",
                           "at least one BenefitProgram must exist to activate")
    if to == "CLOSED":
        if any(cs["contract_id"] == c["id"] and cs["account_status"] != "CLOSED"
               for cs in DB.cases.values()):
            raise ApiError("ERR_CONTRACT_HAS_OPEN_OBLIGATIONS",
                           "contract has non-CLOSED cases")
        if any(bt["contract_id"] == c["id"] and bt["batch_status"] in ("CUTOFF", "DISPUTED")
               for bt in DB.batches.values()):
            raise ApiError("ERR_CONTRACT_HAS_OPEN_OBLIGATIONS",
                           "contract has unsettled batches")
        case_ids = {cs["id"] for cs in DB.cases.values() if cs["contract_id"] == c["id"]}
        if any(cl["case_account_id"] in case_ids
               and cl["investigation_status"] in ("FILED", "UNDER_INVESTIGATION")
               for cl in DB.claims.values()):
            raise ApiError("ERR_CONTRACT_HAS_OPEN_OBLIGATIONS",
                           "contract has open claims")
    c["contract_status"] = to
    touch(c)
    if cur == "CONFIGURING" and to == "ACTIVE":
        for p in DB.programs.values():
            if p["contract_id"] == c["id"] and p["program_status"] == "DRAFT":
                p["program_status"] = "ACTIVE"
                touch(p)
    return ok_object(ser_contract(c))


@bp.get("/contracts/<cid>/programs")
def list_programs(cid):
    authed(["StateAdmin", "CardholderServices"])
    _get_contract(cid)
    rows = sort_created([p for p in DB.programs.values() if p["contract_id"] == cid])
    return list_response(rows, ser_program)


@bp.get("/contracts/<cid>/retailers")
def list_retailers(cid):
    authed(["StateAdmin", "CardholderServices"])
    _get_contract(cid)
    rows = sort_created([r for r in DB.retailers.values() if r["contract_id"] == cid])
    return list_response(rows, ser_retailer)


@bp.get("/contracts/<cid>/data-deliveries")
def list_deliveries(cid):
    authed(["StateAdmin"])
    _get_contract(cid)
    rows = [d for d in DB.deliveries.values() if d["contract_id"] == cid]
    dt = query_filter("delivery_type")
    if dt is not None:
        rows = [d for d in rows if d["delivery_type"] == dt]
    return list_response(sort_created(rows), ser_delivery)


@bp.post("/programs")
def create_program():
    authed(["StateAdmin"])
    b = body()
    contract_id = req_str(b, "contract_id")
    program_type = req_str(b, "program_type")
    contract = DB.contracts.get(contract_id)
    if contract is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "contract_id does not exist")
    if contract["contract_status"] not in ("CONFIGURING", "ACTIVE"):
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE",
                       "program creation requires contract CONFIGURING or ACTIVE")
    if program_type not in ("FOOD", "CASH", "DISASTER"):
        raise ApiError("ERR_INVALID_REQUEST", "program_type must be FOOD, CASH or DISASTER")
    mode = b.get("item_restriction_mode", "STRICT")
    if mode not in ("STRICT", "LENIENT"):
        raise ApiError("ERR_INVALID_REQUEST", "item_restriction_mode must be STRICT or LENIENT")
    posting_modulus = opt_int(b, "posting_modulus", None)
    if posting_modulus is not None and not (1 <= posting_modulus <= 28):
        raise ApiError("ERR_INVALID_REQUEST", "posting_modulus must be 1..28")
    availability_hour = opt_int(b, "availability_hour_utc", None)
    if availability_hour is not None and not (0 <= availability_hour <= 23):
        raise ApiError("ERR_INVALID_REQUEST", "availability_hour_utc must be 0..23")
    expungement_days = opt_int(b, "expungement_inactivity_days", None)
    if expungement_days is not None and expungement_days < 31:
        raise ApiError("ERR_INVALID_REQUEST", "expungement_inactivity_days must be >= 31")
    disaster_expiry = opt_int(b, "disaster_expiry_days", None)
    if disaster_expiry is not None and disaster_expiry < 1:
        raise ApiError("ERR_INVALID_REQUEST", "disaster_expiry_days must be >= 1")
    replacement_fee = opt_int(b, "replacement_fee_cents", None)
    if replacement_fee is not None and replacement_fee < 0:
        raise ApiError("ERR_INVALID_REQUEST", "replacement_fee_cents must be >= 0")
    win_start = b.get("disaster_window_start")
    win_end = b.get("disaster_window_end")
    if program_type == "DISASTER":
        if win_start is None or win_end is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "DISASTER programs require disaster_window_start and disaster_window_end")
        win_start = parse_iso_date(win_start)
        win_end = parse_iso_date(win_end)
        if win_start is None or win_end is None:
            raise ApiError("ERR_INVALID_REQUEST", "disaster window dates must be ISO dates")
        if win_end < win_start:
            raise ApiError("ERR_INVALID_REQUEST", "disaster_window_end must be >= start")
    else:
        if win_start is not None or win_end is not None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "disaster window fields are forbidden for non-DISASTER programs")
    # uniqueness / overlap
    for p in DB.programs.values():
        if p["contract_id"] != contract_id:
            continue
        if program_type in ("FOOD", "CASH") and p["program_type"] == program_type:
            raise ApiError("ERR_PROGRAM_TYPE_DUPLICATE",
                           f"a {program_type} program already exists for the contract")
        if program_type == "DISASTER" and p["program_type"] == "DISASTER":
            from datetime import timedelta as _td
            if (win_start <= p["disaster_window_end"] + _td(days=1)
                    and p["disaster_window_start"] <= win_end + _td(days=1)):
                raise ApiError("ERR_DISASTER_WINDOW_OVERLAP",
                               "DISASTER windows may not touch or overlap")
    prog = new_entity()
    prog.update({
        "contract_id": contract_id,
        "program_type": program_type,
        "program_status": "ACTIVE" if contract["contract_status"] == "ACTIVE" else "DRAFT",
        "item_restriction_mode": mode,
        "posting_modulus": posting_modulus,
        "availability_hour_utc": availability_hour,
        "expungement_inactivity_days": expungement_days,
        "disaster_expiry_days": disaster_expiry,
        "replacement_fee_cents": replacement_fee,
        "disaster_window_start": win_start if program_type == "DISASTER" else None,
        "disaster_window_end": win_end if program_type == "DISASTER" else None,
        "_runs": set(),
    })
    DB.programs[prog["id"]] = prog
    if prog["program_status"] == "ACTIVE":
        for case in DB.cases.values():
            if case["contract_id"] == contract_id and case["account_status"] in (
                    "OPEN", "SUSPENDED", "DORMANT"):
                _create_purse(case["id"], prog["id"])
    return ok_object(ser_program(prog), 201)


def _create_purse(case_id, program_id):
    purse = new_entity()
    purse.update({
        "case_account_id": case_id,
        "program_id": program_id,
        "purse_status": "OPEN",
        "last_activity_at": None,
        "expungement_notice_sent_at": None,
    })
    DB.purses[purse["id"]] = purse
    return purse


@bp.post("/contracts/<cid>/allotment-runs")
def allotment_run(cid):
    authed(["StateAdmin"])
    contract = _get_contract(cid)
    b = body()
    program_id = req_str(b, "program_id")
    benefit_month = req_str(b, "benefit_month")
    prog = DB.programs.get(program_id)
    if prog is None or prog["contract_id"] != cid:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "program_id does not exist on this contract")
    if contract["contract_status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "allotment runs require contract ACTIVE")
    amount_cents = None
    from util import req_int
    amount_cents = req_int(b, "amount_cents")
    if amount_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be > 0")
    if not BENEFIT_MONTH_RE.match(benefit_month):
        raise ApiError("ERR_INVALID_REQUEST", "benefit_month must be YYYY-MM")
    now = util.now_dt()
    cur_month = f"{now.year:04d}-{now.month:02d}"
    ny, nm = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    next_month = f"{ny:04d}-{nm:02d}"
    if benefit_month not in (cur_month, next_month):
        raise ApiError("ERR_POSTING_MONTH_INVALID",
                       "benefit_month must be the current or next calendar month")
    if prog["program_type"] == "DISASTER":
        today = now.date()
        if not (prog["disaster_window_start"] <= today <= prog["disaster_window_end"]):
            raise ApiError("ERR_POSTING_MONTH_INVALID",
                           "DISASTER run outside the disaster window")
    if benefit_month in prog["_runs"]:
        raise ApiError("ERR_DUPLICATE_POSTING_RUN",
                       "an allotment run for this program and month already executed")
    prog["_runs"].add(benefit_month)

    year, month = int(benefit_month[:4]), int(benefit_month[5:7])
    month_first = datetime(year, month, 1, tzinfo=timezone.utc).date()
    days_in_month = calendar.monthrange(year, month)[1]
    modulus = prog["posting_modulus"] if prog["posting_modulus"] is not None \
        else contract["default_posting_modulus"]
    hour = prog["availability_hour_utc"] if prog["availability_hour_utc"] is not None \
        else contract["default_availability_hour_utc"]

    created_ids = []
    skipped = 0
    for purse in sorted((p for p in DB.purses.values() if p["program_id"] == prog["id"]),
                        key=lambda p: p["_seq"]):
        case = DB.cases[purse["case_account_id"]]
        if case["account_status"] not in ("OPEN", "DORMANT") \
                or purse["purse_status"] == "CLOSED":
            skipped += 1
            continue
        bucket = int(case["case_identifier"]) % modulus
        base_date = month_first + timedelta(days=bucket)
        created_date = case["created_at"].date()
        first_month = (created_date.year, created_date.month) == (year, month)
        if first_month:
            available_date = max(base_date, created_date)
        else:
            available_date = base_date
        available_at = datetime(available_date.year, available_date.month,
                                available_date.day, hour, tzinfo=timezone.utc)
        if first_month:
            remaining_days = days_in_month - created_date.day + 1
            from decimal import Decimal, ROUND_HALF_UP
            amt = int((Decimal(amount_cents * remaining_days) / Decimal(days_in_month))
                      .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            prorated = amt != amount_cents
        else:
            amt = amount_cents
            prorated = False
        posting = new_entity()
        posting.update({
            "purse_id": purse["id"],
            "benefit_month": benefit_month,
            "amount_cents": amt,
            "prorated": prorated,
            "scheduled_date": available_date,
            "available_at": available_at,
            "posting_status": "SCHEDULED",
            "resolved_at": None,
            "_reached_available": False,
        })
        DB.postings[posting["id"]] = posting
        post_entry(purse["id"], "POST_CREDIT", amt, posting_id=posting["id"],
                   memo="allotment posting")
        created_ids.append(posting["id"])
    return ok_object({"created_count": len(created_ids), "skipped_count": skipped,
                      "posting_ids": created_ids}, 201)
