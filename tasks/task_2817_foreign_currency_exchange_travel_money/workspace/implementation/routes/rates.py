"""Rate cards: drafting (a reserve-and-truncate write) and publishing."""
from flask import Blueprint

import calc
from core import (
    MIN_DISCLOSURE_TEXT_VERSION,
    all_rows,
    body,
    endpoint,
    fail,
    listing,
    need,
    need_currency,
    new_row,
    now_str,
    ok,
    opt_dt,
    opt_enum,
    parse_dt,
    public,
    req_dt,
    req_int,
    req_str,
    require_branch_active,
    sort_created_asc,
    store,
    touch,
)

bp = Blueprint("rates", __name__)

READERS = ("PlatformAdmin", "TreasuryOfficer", "BranchManager", "BranchTeller", "ComplianceOfficer")


@bp.post("/rate-cards")
@endpoint(["TreasuryOfficer"])
def create_rate_card():
    b = body()
    # rank 3 - foreign keys in declaration order
    branch = need("Branch", req_str(b, "branch_id"))
    currency_code = req_str(b, "currency_code")
    profile = need_currency(currency_code)
    quote = need("WholesaleRate", req_str(b, "wholesale_rate_id"))
    # rank 4
    buy_spread_bps = req_int(b, "buy_spread_bps", minimum=0, maximum=5000)
    sell_spread_bps = req_int(b, "sell_spread_bps", minimum=0, maximum=5000)
    board_display_label = req_str(b, "board_display_label")
    disclosure_text_version = req_int(b, "disclosure_text_version", minimum=1)
    effective_from = req_dt(b, "effective_from")
    expected_branch_version = req_int(b, "expected_branch_version", minimum=1)
    commission_schedule_code = opt_enum(
        b, "commission_schedule_code", ("STANDARD", "PREMIUM"), default="STANDARD"
    )
    effective_to = opt_dt(b, "effective_to")
    if effective_to is not None and parse_dt(effective_to) <= parse_dt(effective_from):
        fail("ERR_INVALID_REQUEST", "effective_to must be strictly after effective_from.")
    if quote["currency_code"] != currency_code:
        fail(
            "ERR_INVALID_REQUEST",
            "The cited wholesale quote is for a different currency.",
        )
    # rank 6 - optimistic concurrency on the parent branch
    if expected_branch_version != branch["version"]:
        fail("ERR_STALE_BRANCH_VERSION")
    # rank 7 - branch gate
    require_branch_active(branch)

    buy_rate, sell_rate = calc.derive_card_rates(
        quote["mid_rate_micros"], buy_spread_bps, sell_spread_bps
    )
    row = new_row("RateCard")
    row["branch_id"] = branch["id"]
    row["currency_code"] = currency_code
    row["wholesale_rate_id"] = quote["id"]
    row["buy_spread_bps"] = buy_spread_bps
    row["sell_spread_bps"] = sell_spread_bps
    row["buy_rate_micros"] = buy_rate
    row["sell_rate_micros"] = sell_rate
    row["commission_schedule_code"] = commission_schedule_code
    row["board_display_label"] = board_display_label
    row["disclosure_text_version"] = disclosure_text_version
    row["effective_from"] = effective_from
    row["effective_to"] = effective_to
    row["status"] = "DRAFT"
    row["published_at"] = None
    row["superseded_by_rate_card_id"] = None
    store(row)

    # reserve-and-truncate: retire the open-ended incumbent
    for incumbent in sort_created_asc(all_rows("RateCard")):
        if incumbent["id"] == row["id"]:
            continue
        if incumbent["branch_id"] != branch["id"]:
            continue
        if incumbent["currency_code"] != currency_code:
            continue
        if incumbent["status"] != "PUBLISHED" or incumbent["effective_to"] is not None:
            continue
        if parse_dt(effective_from) < parse_dt(incumbent["effective_from"]):
            continue
        incumbent["effective_to"] = effective_from
        incumbent["status"] = "SUPERSEDED"
        incumbent["superseded_by_rate_card_id"] = row["id"]
        touch(incumbent)
    touch(branch)
    return ok(public(row), 201)


@bp.post("/rate-cards/<card_id>/publish")
@endpoint(["TreasuryOfficer"])
def publish_rate_card(card_id):
    card = need("RateCard", card_id)
    # rank 5
    if card["status"] != "DRAFT":
        fail("ERR_RATE_CARD_NOT_DRAFT")
    # rank 10 - half-open window overlap
    start = parse_dt(card["effective_from"])
    end = parse_dt(card["effective_to"]) if card["effective_to"] else None
    for other in all_rows("RateCard"):
        if other["id"] == card["id"] or other["status"] != "PUBLISHED":
            continue
        if other["branch_id"] != card["branch_id"]:
            continue
        if other["currency_code"] != card["currency_code"]:
            continue
        other_start = parse_dt(other["effective_from"])
        other_end = parse_dt(other["effective_to"]) if other["effective_to"] else None
        disjoint = (end is not None and end <= other_start) or (
            other_end is not None and other_end <= start
        )
        if not disjoint:
            fail("ERR_RATE_WINDOW_OVERLAP")
    # rank 11 - disclosure regime
    if card["disclosure_text_version"] < MIN_DISCLOSURE_TEXT_VERSION:
        fail("ERR_DISCLOSURE_VERSION_UNSUPPORTED")
    card["status"] = "PUBLISHED"
    card["published_at"] = now_str()
    touch(card)
    return ok(public(card))


@bp.get("/rate-cards/<card_id>")
@endpoint(READERS)
def read_rate_card(card_id):
    return ok(public(need("RateCard", card_id)))


@bp.get("/rate-cards")
@endpoint(READERS)
def list_rate_cards():
    return listing(
        "RateCard",
        {
            "branch_id": "branch_id",
            "currency_code": "currency_code",
            "wholesale_rate_id": "wholesale_rate_id",
            "superseded_by_rate_card_id": "superseded_by_rate_card_id",
            "status": "status",
        },
    )
