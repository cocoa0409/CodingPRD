"""Cargo claims: filing, review rounds, liability and clawback (PRD 3.8)."""

from constants import (
    COMMODITY_LIABILITY_CAP, ESCALATION_THRESHOLD_CENTS, MAX_REVIEW_ROUNDS,
    PRICE_CAP_MULTIPLIER, TRUCKLOAD_WEIGHT_LBS, d, round_half_up,
)
from db import clock_now, db, mint_id, touch
from errors import ApiError
from services.common import get_carrier, get_load, refresh_carrier_score
from services.settlements import restrike  # noqa: F401


def file_claim(body):
    load = get_load(body.get("load_id"))
    carrier = get_carrier(body.get("carrier_id"))

    claimed = body.get("claimed_amount_cents")
    if isinstance(claimed, bool) or not isinstance(claimed, int) or claimed <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "claimed_amount_cents must be strictly positive.")
    if load["status"] in ("DRAFT", "POSTED", "UNCOVERED", "BOOKED", "IN_TRANSIT"):
        raise ApiError("ERR_CLAIM_BEFORE_DELIVERY")
    filed_by_role = body.get("filed_by_role")
    if filed_by_role not in ("SHIPPER", "CARRIER"):
        raise ApiError("ERR_INVALID_REQUEST", "filed_by_role must be SHIPPER or CARRIER.")
    if not body.get("damage_description"):
        raise ApiError("ERR_INVALID_REQUEST", "damage_description is required.")

    expected = body.get("expected_carrier_version")
    if expected is None:
        raise ApiError("ERR_INVALID_REQUEST", "expected_carrier_version is required.")

    if int(expected) != int(carrier["version"]):
        raise ApiError("ERR_STALE_VERSION")

    commodity_cap = COMMODITY_LIABILITY_CAP.get(load["commodity"], 100000000)
    liability_limit = min(int(carrier.get("cargo_coverage_limit_cents") or 0), commodity_cap)

    now = clock_now()
    claim = {
        "id": mint_id(),
        "load_id": load["id"],
        "carrier_id": carrier["id"],
        "claimed_amount_cents": claimed,
        "damage_description": body["damage_description"],
        "filed_by_role": filed_by_role,
        "liability_limit_cents": liability_limit,
        "price_cap_cents": 0,
        "provisional_liability_cents": 0,
        "approved_amount_cents": 0,
        "review_rounds": 0,
        "escalated": False,
        "status": "FILED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.claims[claim["id"]] = claim
    touch(carrier)
    return claim


def write_provisional(claim):
    load = db.loads[claim["load_id"]]
    carrier = db.carriers[claim["carrier_id"]]
    commodity_cap = COMMODITY_LIABILITY_CAP.get(load["commodity"], 100000000)
    liability_limit = min(int(carrier.get("cargo_coverage_limit_cents") or 0), commodity_cap)
    price_cap = round_half_up(d(load["declared_cargo_value_cents"]) * PRICE_CAP_MULTIPLIER)
    claim["liability_limit_cents"] = liability_limit
    claim["price_cap_cents"] = price_cap
    claim["provisional_liability_cents"] = min(
        claim["claimed_amount_cents"], liability_limit, price_cap)
    return claim


def review_claim(claim_id):
    claim = get_load_claim(claim_id)
    status = claim["status"]
    if status in ("APPROVED", "DENIED", "SETTLED", "ESCALATED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status == "FILED":
        if claim["review_rounds"] >= 1:
            raise ApiError("ERR_CLAIM_ALREADY_REVIEWED")
        load = db.loads[claim["load_id"]]
        if load["status"] not in ("DELIVERED", "INVOICED", "PAID"):
            raise ApiError("ERR_CLAIM_BEFORE_DELIVERY")
        write_provisional(claim)
        claim["review_rounds"] += 1
        claim["status"] = "UNDER_REVIEW"
    elif status == "INFO_REQUESTED":
        if claim["review_rounds"] >= MAX_REVIEW_ROUNDS:
            raise ApiError("ERR_CLAIM_REVIEW_ROUNDS_EXHAUSTED")
        write_provisional(claim)
        claim["review_rounds"] += 1
        claim["status"] = "UNDER_REVIEW"
    elif status == "UNDER_REVIEW":
        # A case that already has a review round behind it is not reopened.
        if claim["review_rounds"] >= 1:
            raise ApiError("ERR_CLAIM_ALREADY_REVIEWED")
        write_provisional(claim)
        claim["review_rounds"] += 1
    else:
        raise ApiError("ERR_INVALID_STATE")
    touch(claim)
    return claim


def get_load_claim(claim_id):
    row = db.claims.get(claim_id)
    if row is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND")
    return row


def request_info(claim_id, body):
    claim = get_load_claim(claim_id)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE")
    if claim["review_rounds"] >= MAX_REVIEW_ROUNDS:
        raise ApiError("ERR_CLAIM_REVIEW_ROUNDS_EXHAUSTED")
    if not body.get("note"):
        raise ApiError("ERR_INVALID_REQUEST", "note is required.")
    claim["review_rounds"] += 1
    claim["status"] = "INFO_REQUESTED"
    touch(claim)
    return claim


def approve_claim(claim_id):
    claim = get_load_claim(claim_id)
    if claim["status"] in ("APPROVED", "DENIED", "SETTLED", "ESCALATED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    # ERR_CLAIM_NOT_REVIEWED is the answer for an attempt made before any
    # review round, whatever the case's own status happens to be.
    if claim["review_rounds"] < 1:
        raise ApiError("ERR_CLAIM_NOT_REVIEWED")
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE")
    load = db.loads[claim["load_id"]]
    carrier = db.carriers[claim["carrier_id"]]
    if carrier["status"] not in ("VERIFIED", "SUSPENDED"):
        raise ApiError("ERR_CARRIER_NOT_FOUND")

    weight_basis = min(d(1), d(load["weight_lbs"]) / d(TRUCKLOAD_WEIGHT_LBS))
    approved = round_half_up(d(claim["provisional_liability_cents"]) * weight_basis)
    claim["approved_amount_cents"] = approved
    # The deduction line is the sum over the load's APPROVED and SETTLED claims,
    # so the case must already read APPROVED when the settlement is re-struck.
    claim["status"] = "APPROVED"

    from services.settlements import refresh_live_settlement_for_load
    settled = refresh_live_settlement_for_load(load["id"])
    took_deduction = settled is not None

    touch(claim)
    if took_deduction:
        carrier["claims_clawback_count"] = carrier.get("claims_clawback_count", 0) + 1
    refresh_carrier_score(carrier, bump=True)
    return claim


def deny_claim(claim_id, body):
    claim = get_load_claim(claim_id)
    if claim["status"] in ("APPROVED", "DENIED", "SETTLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if claim["status"] not in ("UNDER_REVIEW", "INFO_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE")
    if claim["review_rounds"] < 1:
        raise ApiError("ERR_CLAIM_NOT_REVIEWED")
    if not body.get("reason_code"):
        raise ApiError("ERR_INVALID_REQUEST", "reason_code is required.")
    claim["status"] = "DENIED"
    claim["approved_amount_cents"] = 0
    touch(claim)
    return claim


def escalate_claim(claim_id):
    claim = get_load_claim(claim_id)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE")
    if claim["provisional_liability_cents"] <= ESCALATION_THRESHOLD_CENTS:
        raise ApiError("ERR_ESCALATION_THRESHOLD_NOT_MET")
    claim["escalated"] = True
    claim["status"] = "ESCALATED"
    touch(claim)
    return claim


def settle_claim(claim_id):
    claim = get_load_claim(claim_id)
    if claim["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")
    carrier = db.carriers[claim["carrier_id"]]
    if carrier["status"] != "VERIFIED":
        raise ApiError("ERR_CARRIER_NOT_COMPLIANT")
    claim["status"] = "SETTLED"
    touch(claim)
    return claim


def claim_list(claims, filters):
    rows = list(claims)
    for field in ("load_id", "carrier_id", "status"):
        value = filters.get(field)
        if value is None or value == "":
            continue
        rows = [row for row in rows if row.get(field) == value]
    rows.sort(key=lambda row: row["created_at"])
    return rows