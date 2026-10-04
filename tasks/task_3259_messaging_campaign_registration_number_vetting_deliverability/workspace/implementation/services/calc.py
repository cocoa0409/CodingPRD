"""Calculation rules: identity scoring, throughput, segments/fees, snapshots."""
import math
import re
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    GSM7_BASIC,
    MESSAGE_FEE_PER_SEGMENT_CENTS,
    CARRIER_FEE_PER_SEGMENT_CENTS,
    LONG_MESSAGE_SURCHARGE_CENTS,
    TOLL_FREE_MIN_SCORE,
    BLOCK_PENALTY_BPS,
    SPAM_PENALTY_BPS,
    GOOD_DAY_MIN_ATTEMPTED,
    TRUST_SCORE_DEFAULT,
    SHORT_CODE_MPS,
    TOLL_FREE_MPS,
)

_EIN_RE = re.compile(r"^\d{2}-\d{7}$")
_POSTAL_RES = {
    "US": re.compile(r"^\d{5}$"),
    "CA": re.compile(r"^[A-Z]\d[A-Z]\d[A-Z]\d$"),
    "GB": re.compile(r"^[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$"),
}


def clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


def identity_score(brand):
    """Weighted identity score per PRD 3.2. Additive terms in listed order,
    clamp last."""
    base = 50
    if isinstance(brand.get("website_url"), str) and brand["website_url"].strip():
        base += 10
    bt = brand.get("business_type")
    if bt == "PUBLIC_PROFIT":
        base += 10
    if bt == "NON_PROFIT":
        base += 5
    if bt == "SOLE_PROPRIETOR":
        base -= 20
    if isinstance(brand.get("tax_id"), str) and _EIN_RE.match(brand["tax_id"]):
        base += 10
    postal = brand.get("postal_code")
    cc = brand.get("country_code")
    if isinstance(postal, str) and cc in _POSTAL_RES and _POSTAL_RES[cc].match(postal):
        base += 10
    if brand.get("opt_in_mechanism") in ("WEB_FORM", "POINT_OF_SALE"):
        base += 5
    return clamp(base)


def compute_segments(body):
    """GSM-7 iff every char in GSM7_BASIC; else UCS-2. ceil(len/160 or /70), min 1."""
    if not isinstance(body, str) or len(body) == 0:
        return 1
    if all(ch in GSM7_BASIC for ch in body):
        segs = math.ceil(len(body) / 160)
    else:
        segs = math.ceil(len(body) / 70)
    return max(1, segs)


def message_fee_cents(segments):
    fee = segments * MESSAGE_FEE_PER_SEGMENT_CENTS
    if segments > 3:
        fee += LONG_MESSAGE_SURCHARGE_CENTS
    return fee


def carrier_fee_cents(segments, carrier_code):
    return segments * CARRIER_FEE_PER_SEGMENT_CENTS[carrier_code]


def initial_trust_score(campaign, brand):
    if campaign["path_kind"] == "TEN_DLC":
        return brand["identity_score"]
    return TRUST_SCORE_DEFAULT


def compute_allocated_mps(campaign):
    """Throughput allocation; re-derived on reads. SHORT_CODE/TOLL_FREE flat,
    TEN_DLC tiered on trust_score with inclusive boundaries."""
    pk = campaign["path_kind"]
    if pk == "SHORT_CODE":
        return SHORT_CODE_MPS
    if pk == "TOLL_FREE":
        return TOLL_FREE_MPS
    ts = campaign.get("trust_score", 0)
    if ts >= 75:
        return 10
    if ts >= 50:
        return 3
    if ts >= 25:
        return 1
    return 0


def recompute_trust_from_snapshot(trust_score, snapshot):
    """Penalties before good-day bonus; clamp last."""
    raw = trust_score
    if snapshot["block_rate_bps"] >= BLOCK_PENALTY_BPS:
        raw -= 5
    if snapshot["spam_rate_bps"] >= SPAM_PENALTY_BPS:
        raw -= 15
    if snapshot["attempted"] >= GOOD_DAY_MIN_ATTEMPTED and snapshot["spam_rate_bps"] < SPAM_PENALTY_BPS:
        raw += 2
    return clamp(raw)


def snapshot_rates(attempted, delivered, blocked, spam):
    if attempted == 0:
        return 0, 0, 0
    pct = Decimal(100 * delivered) / Decimal(attempted)
    delivery_rate_pct = float(pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    block_rate_bps = (10000 * blocked) // attempted
    spam_rate_bps = (10000 * spam) // attempted
    return delivery_rate_pct, block_rate_bps, spam_rate_bps
