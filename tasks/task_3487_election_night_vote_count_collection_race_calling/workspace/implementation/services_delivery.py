"""media_invoice_total pricing, ResultDelivery fan-out, and the retract
compensation cascade (SCAFFOLD §1.3 / PRD §3.8)."""
from decimal import Decimal

from clock import now as clock_now
from store import db, next_seq
from util import new_id, money_round

# media_invoice_total constants (SCAFFOLD §1.3)
VOTE_UPDATE_BASE_FEE_CENTS = 999
CALL_BASE_FEE_CENTS = 4999
TIER_MULTIPLIERS = {
    "PREMIUM": Decimal("1.0"),
    "STANDARD": Decimal("0.6"),
    "BASIC": Decimal("0.35"),
}
CALL_TIERS = ("STANDARD", "PREMIUM")


def fee_for(content_type, license_tier):
    """Per-delivery fee pinned at creation: round_half_up(base * multiplier).
    CALL_CREDIT fees are the exact negation of the CALL they compensate."""
    base = (VOTE_UPDATE_BASE_FEE_CENTS if content_type == "VOTE_UPDATE"
            else CALL_BASE_FEE_CENTS)
    return money_round(Decimal(base) * TIER_MULTIPLIERS[license_tier])


def create_delivery(customer_id, contest_id, content_type, fee_cents, status="SENT"):
    rec = {
        "id": new_id(),
        "customer_id": customer_id,
        "contest_id": contest_id,
        "content_type": content_type,
        "fee_cents": fee_cents,
        "status": status,
        "delivered_at": clock_now(),
        "created_at": clock_now(),
        "_seq": next_seq(),
    }
    db["deliveries"][rec["id"]] = rec
    return rec


def fanout_vote_update(contest, county):
    """On VoteReport ACCEPT: one VOTE_UPDATE per customer whose licensed_states
    contains the reporting county's state_code, at every tier."""
    for cust in db["customers"].values():
        if county["state_code"] in cust["licensed_states"]:
            create_delivery(
                cust["id"], contest["id"], "VOTE_UPDATE",
                fee_for("VOTE_UPDATE", cust["license_tier"]),
            )


def fanout_call(contest):
    """On call PUBLISH: one CALL delivery per customer licensed for the
    contest's state at STANDARD or PREMIUM tier."""
    for cust in db["customers"].values():
        if (contest["state_code"] in cust["licensed_states"]
                and cust["license_tier"] in CALL_TIERS):
            create_delivery(
                cust["id"], contest["id"], "CALL",
                fee_for("CALL", cust["license_tier"]),
            )


def compensate_call(contest):
    """On retraction of a PUBLISHED call (desk- or recount-driven): every CALL
    delivery of the contest still SENT flips to STALE, and each flipped
    delivery earns its customer a compensating CALL_CREDIT in SENT whose fee
    is the exact negation of the original."""
    for d in list(db["deliveries"].values()):
        if (d["contest_id"] == contest["id"]
                and d["content_type"] == "CALL"
                and d["status"] == "SENT"):
            d["status"] = "STALE"
            create_delivery(
                d["customer_id"], contest["id"], "CALL_CREDIT", -d["fee_cents"]
            )


def invoice_aggregate(customer_id, period):
    """Deliveries whose delivered_at falls inside the period's UTC calendar
    month — SENT and STALE both billed, CALL_CREDIT counts. Returns
    (delivery_count, total_fee_cents) as a plain integer sum (round-then-sum
    order is pinned: per-delivery rounding already happened at creation)."""
    rows = [
        d for d in db["deliveries"].values()
        if d["customer_id"] == customer_id
        and d["delivered_at"].strftime("%Y-%m") == period
    ]
    return len(rows), sum(d["fee_cents"] for d in rows)
