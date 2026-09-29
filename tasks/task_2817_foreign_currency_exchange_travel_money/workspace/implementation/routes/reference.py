"""Clock control plus the static furniture: branches, currencies, wholesale rates,
travel corridors and armored routes."""
from datetime import timedelta

from flask import Blueprint

import calc
from core import (
    D,
    S,
    all_rows,
    body,
    clock,
    endpoint,
    fail,
    listing,
    need,
    need_currency,
    new_row,
    now_str,
    ok,
    opt_bool,
    opt_dt,
    opt_enum,
    opt_int,
    opt_str,
    parse_dt,
    public,
    qs,
    req_dt,
    req_enum,
    req_int,
    req_list,
    req_str,
    set_clock,
    sort_created_asc,
    store,
    touch,
)

bp = Blueprint("reference", __name__)

STAFF = ("PlatformAdmin", "TreasuryOfficer", "BranchManager", "BranchTeller", "ComplianceOfficer")
OPS = ("PlatformAdmin", "TreasuryOfficer", "BranchManager")


# ==========================================================================
# The logical trading clock
# ==========================================================================
@bp.post("/_clock/set_current_utc")
@endpoint(["PlatformAdmin"])
def set_current_utc():
    b = body()
    raw = req_dt(b, "current_utc")
    set_clock(parse_dt(raw))
    now = clock()
    expired = 0
    branches = {}
    for contract in sort_created_asc(all_rows("BuybackContract")):
        if contract["status"] not in ("ISSUED", "PARTIALLY_REDEEMED"):
            continue
        if D(contract["rate_lock_expires_at"]) >= now:
            continue
        contract["status"] = "EXPIRED"
        contract["liability_usd_cents"] = 0
        touch(contract)
        expired += 1
        branches[contract["branch_id"]] = True
    for branch_id in branches:
        branch = S["Branch"].get(branch_id)
        if branch is not None:
            calc.reconcile_branch_liability(branch)
    return ok({"current_utc": raw, "expired_contract_count": expired})


# ==========================================================================
# Branches
# ==========================================================================
@bp.post("/branches")
@endpoint(["PlatformAdmin"])
def create_branch():
    b = body()
    code = req_str(b, "code", max_len=16)
    name = req_str(b, "name")
    region_code = req_str(b, "region_code")
    vault_limit = req_int(b, "vault_limit_usd_cents", minimum=100000)
    home_currency_code = opt_str(b, "home_currency_code", default="USD")
    status = opt_enum(b, "status", ("ACTIVE", "SUSPENDED", "CLOSED"), default="ACTIVE")
    for other in all_rows("Branch"):
        if other["code"] == code:
            fail("ERR_DUPLICATE_BRANCH_CODE")
    row = new_row("Branch")
    row["code"] = code
    row["name"] = name
    row["region_code"] = region_code
    row["home_currency_code"] = home_currency_code
    row["vault_limit_usd_cents"] = vault_limit
    row["status"] = status
    row["posture"] = "OPEN"
    row["vault_usd_equivalent_cents"] = 0
    row["vault_utilization_bps"] = 0
    row["buyback_liability_usd_cents"] = 0
    row["repatriation_pending"] = False
    store(row)
    return ok(public(row), 201)


@bp.get("/branches/<branch_id>")
@endpoint(STAFF)
def read_branch(branch_id):
    return ok(public(need("Branch", branch_id)))


@bp.get("/branches")
@endpoint(["PlatformAdmin", "TreasuryOfficer", "BranchManager", "ComplianceOfficer"])
def list_branches():
    return listing(
        "Branch",
        {"region_code": "region_code", "status": "status", "posture": "posture"},
    )


@bp.get("/branches/<branch_id>/rate-board")
@endpoint(["PlatformAdmin", "TreasuryOfficer", "BranchManager", "BranchTeller", "Customer"])
def read_rate_board(branch_id):
    branch = need("Branch", branch_id)
    wanted = qs("currency_code")
    now = clock()
    lines = []
    for card in sort_created_asc(all_rows("RateCard")):
        if card["branch_id"] != branch["id"] or card["status"] != "PUBLISHED":
            continue
        if wanted is not None and card["currency_code"] != wanted:
            continue
        if not calc.card_covers(card, now):
            continue
        lines.append(
            {
                "currency_code": card["currency_code"],
                "rate_card_id": card["id"],
                "board_display_label": card["board_display_label"],
                "buy_rate_micros": card["buy_rate_micros"],
                "sell_rate_micros": card["sell_rate_micros"],
                "commission_schedule_code": card["commission_schedule_code"],
                "disclosure_text_version": card["disclosure_text_version"],
                "effective_from": card["effective_from"],
                "effective_to": card["effective_to"],
            }
        )
    lines.sort(key=lambda l: l["currency_code"])
    return ok(
        {
            "branch_id": branch["id"],
            "as_of": now_str(),
            "line_count": len(lines),
            "min_disclosure_text_version": min(
                [l["disclosure_text_version"] for l in lines], default=0
            ),
            "lines": lines,
        }
    )


# ==========================================================================
# Currency profiles
# ==========================================================================
@bp.post("/currencies")
@endpoint(["PlatformAdmin"])
def create_currency():
    b = body()
    iso_code = req_str(b, "iso_code")
    if len(iso_code) != 3 or not iso_code.isalpha() or not iso_code.isupper():
        fail("ERR_INVALID_REQUEST", "iso_code must be exactly three uppercase letters.")
    display_name = req_str(b, "display_name")
    minor_unit_digits = req_int(b, "minor_unit_digits", minimum=0, maximum=4)
    currency_class = req_enum(b, "currency_class", ("MAJOR", "EXOTIC", "RESTRICTED"))
    denominations = req_list(b, "standard_denominations")
    if len(denominations) > 8:
        fail("ERR_INVALID_REQUEST", "standard_denominations accepts at most eight values.")
    previous = None
    for value in denominations:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            fail("ERR_INVALID_REQUEST", "standard_denominations entries must be integers >= 1.")
        if previous is not None and value <= previous:
            fail("ERR_INVALID_REQUEST", "standard_denominations must be strictly ascending.")
        previous = value
    export_limit = opt_int(b, "export_limit_minor_units", minimum=1)
    if currency_class == "RESTRICTED" and export_limit is None:
        fail(
            "ERR_INVALID_REQUEST",
            "export_limit_minor_units is required for a RESTRICTED currency.",
        )
    if currency_class != "RESTRICTED" and export_limit is not None:
        fail(
            "ERR_INVALID_REQUEST",
            "export_limit_minor_units must be null unless currency_class is RESTRICTED.",
        )
    buyback_eligible = opt_bool(b, "buyback_eligible", default=False)
    recovery_bps = opt_int(b, "damaged_note_recovery_bps", default=6500, minimum=0, maximum=10000)
    for other in all_rows("CurrencyProfile"):
        if other["iso_code"] == iso_code:
            fail("ERR_INVALID_REQUEST", "iso_code is already registered.")
    row = new_row("CurrencyProfile", audited=False)
    row["iso_code"] = iso_code
    row["display_name"] = display_name
    row["minor_unit_digits"] = minor_unit_digits
    row["currency_class"] = currency_class
    row["standard_denominations"] = list(denominations)
    row["export_limit_minor_units"] = export_limit
    row["buyback_eligible"] = buyback_eligible
    row["damaged_note_recovery_bps"] = recovery_bps
    store(row)
    return ok(public(row), 201)


@bp.get("/currencies/<code>")
@endpoint(STAFF + ("Customer",))
def read_currency(code):
    return ok(public(need_currency(code)))


@bp.get("/currencies")
@endpoint(STAFF + ("Customer",))
def list_currencies():
    return listing(
        "CurrencyProfile",
        {"currency_class": "currency_class"},
        {"buyback_eligible": "buyback_eligible"},
    )


# ==========================================================================
# Wholesale rates
# ==========================================================================
@bp.post("/wholesale-rates")
@endpoint(["TreasuryOfficer"])
def create_wholesale_rate():
    b = body()
    currency_code = req_str(b, "currency_code")
    need_currency(currency_code)
    mid = req_int(b, "mid_rate_micros", minimum=1)
    effective_at = req_dt(b, "effective_at")
    source_code = req_enum(b, "source_code", ("REUTERS_MID", "INTERBANK_CLOSE"))
    row = new_row("WholesaleRate", audited=False)
    row["currency_code"] = currency_code
    row["mid_rate_micros"] = mid
    row["effective_at"] = effective_at
    row["source_code"] = source_code
    store(row)
    return ok(public(row), 201)


@bp.get("/wholesale-rates/<rate_id>")
@endpoint(OPS)
def read_wholesale_rate(rate_id):
    return ok(public(need("WholesaleRate", rate_id)))


@bp.get("/wholesale-rates")
@endpoint(OPS)
def list_wholesale_rates():
    def order(rows):
        return sorted(rows, key=lambda r: (D(r["effective_at"]), r["created_at"], r["_seq"]), reverse=True)

    return listing(
        "WholesaleRate",
        {"currency_code": "currency_code", "source_code": "source_code"},
        order=order,
    )


# ==========================================================================
# Travel corridors
# ==========================================================================
def _country_code(b, name):
    value = req_str(b, name)
    if len(value) != 2 or not value.isalpha() or not value.isupper():
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 3166-1 alpha-2 code." % name)
    return value


@bp.post("/travel-corridors")
@endpoint(["TreasuryOfficer"])
def create_corridor():
    b = body()
    code = req_str(b, "code")
    origin = _country_code(b, "origin_country_code")
    destination = _country_code(b, "destination_country_code")
    destination_currency_code = req_str(b, "destination_currency_code")
    need_currency(destination_currency_code)
    season = req_enum(b, "season", ("SPRING", "SUMMER", "AUTUMN", "WINTER"))
    season_start = req_dt(b, "season_start_date")
    season_end = req_dt(b, "season_end_date")
    if parse_dt(season_end) <= parse_dt(season_start):
        fail("ERR_INVALID_REQUEST", "season_end_date must be strictly after season_start_date.")
    demand_index_bps = req_int(b, "demand_index_bps", minimum=1, maximum=50000)
    for other in all_rows("TravelCorridor"):
        if other["code"] == code:
            fail("ERR_INVALID_REQUEST", "code is already registered.")
    row = new_row("TravelCorridor", audited=False)
    row["code"] = code
    row["origin_country_code"] = origin
    row["destination_country_code"] = destination
    row["destination_currency_code"] = destination_currency_code
    row["season"] = season
    row["season_start_date"] = season_start
    row["season_end_date"] = season_end
    row["demand_index_bps"] = demand_index_bps
    store(row)
    return ok(public(row), 201)


@bp.get("/travel-corridors/<corridor_id>")
@endpoint(OPS)
def read_corridor(corridor_id):
    return ok(public(need("TravelCorridor", corridor_id)))


@bp.get("/travel-corridors")
@endpoint(OPS)
def list_corridors():
    return listing(
        "TravelCorridor",
        {"season": "season", "destination_currency_code": "destination_currency_code"},
    )


# ==========================================================================
# Armored routes
# ==========================================================================
@bp.post("/armored-routes")
@endpoint(["PlatformAdmin"])
def create_route():
    b = body()
    code = req_str(b, "code")
    carrier_name = req_str(b, "carrier_name")
    region_code = req_str(b, "region_code")
    capacity = req_int(b, "daily_capacity_usd_cents", minimum=1)
    status = opt_enum(b, "status", ("ACTIVE", "SUSPENDED"), default="ACTIVE")
    for other in all_rows("ArmoredRoute"):
        if other["code"] == code:
            fail("ERR_INVALID_REQUEST", "code is already registered.")
    row = new_row("ArmoredRoute", audited=False)
    row["code"] = code
    row["carrier_name"] = carrier_name
    row["region_code"] = region_code
    row["daily_capacity_usd_cents"] = capacity
    row["status"] = status
    store(row)
    return ok(public(row), 201)


@bp.get("/armored-routes/<route_id>")
@endpoint(OPS)
def read_route(route_id):
    return ok(public(need("ArmoredRoute", route_id)))


@bp.get("/armored-routes")
@endpoint(OPS)
def list_routes():
    return listing("ArmoredRoute", {"region_code": "region_code", "status": "status"})
