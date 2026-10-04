"""Calculation modules: routing, quality scoring, matching, claims, cost share."""
from decimal import Decimal, ROUND_HALF_UP

from db import db, _parse_dt
from errors import fail

COST_ESCALATION_THRESHOLD_CENTS = 500000
W_OUTCOME = Decimal("0.5")
W_COST = Decimal("0.3")
W_ACCESS = Decimal("0.2")
QUALITY_VOLUME_THRESHOLD = 30
NETWORK_MEAN_QUALITY = Decimal("70.0")
OON_NETWORK_FACTOR = Decimal("0.8")
COINSURANCE_RATE = Decimal("0.2")
OON_COINSURANCE_RATE = Decimal("0.4")
EMO_MIN_RECORDS = 3
PROVIDER_DAILY_CAPACITY = 8


def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def intake_routing(question_type, acuity, estimated_cost_cents, relationship):
    if question_type == "CLINICAL":
        if acuity == "HIGH":
            return "PHYSICIAN"
        if relationship == "CHILD":
            return "PHYSICIAN"
        return "NURSE"
    if question_type == "BENEFIT":
        return "ADVOCATE"
    # COST
    return "NURSE" if estimated_cost_cents >= COST_ESCALATION_THRESHOLD_CENTS else "ADVOCATE"


def provider_quality_score(outcome, cost_eff, access, claims_volume):
    raw = W_OUTCOME * Decimal(str(outcome)) + W_COST * Decimal(str(cost_eff)) + W_ACCESS * Decimal(str(access))
    if claims_volume >= QUALITY_VOLUME_THRESHOLD:
        composite = raw
    else:
        frac = Decimal(claims_volume) / Decimal(QUALITY_VOLUME_THRESHOLD)
        composite = frac * raw + (1 - frac) * NETWORK_MEAN_QUALITY
    return round_half_up_2dp(composite)


def provider_matches(member_id, specialty):
    """Ranked match list; raises ERR_NO_PROVIDER_MATCH when empty."""
    candidates = []
    for p in db.providers.values():
        if p["specialty"] != specialty:
            continue
        snaps = [s for s in db.quality_snapshots.values() if s["provider_id"] == p["id"]]
        if not snaps:
            continue
        latest = max(snaps, key=lambda s: _parse_dt(s["period_end"]))
        candidates.append((p, latest))
    if not candidates:
        fail("ERR_NO_PROVIDER_MATCH", "no providers with snapshots for the requested specialty")
    rows = []
    for p, snap in candidates:
        factor = Decimal("1.0") if p["network_status"] == "IN_NETWORK" else OON_NETWORK_FACTOR
        match_score = round_half_up_2dp(Decimal(str(snap["composite_quality_score"])) * factor)
        rows.append({
            "provider_id": p["id"],
            "provider_name": p["name"],
            "specialty": p["specialty"],
            "network_status": p["network_status"],
            "composite_quality_score": snap["composite_quality_score"],
            "network_factor": float(factor),
            "match_score": match_score,
            "_period_end": snap["period_end"],
            "_provider_created_at": p["created_at"],
        })
    rows.sort(key=lambda r: (
        -Decimal(str(r["match_score"])),
        -_parse_dt(r["_period_end"]).timestamp(),
        _parse_dt(r["_provider_created_at"]).timestamp(),
    ))
    from common import now_iso
    import uuid
    for i, r in enumerate(rows):
        r["rank"] = i + 1
        r["id"] = str(uuid.uuid4())
        r["created_at"] = now_iso()
        del r["_period_end"]
        del r["_provider_created_at"]
    return rows


def claim_repricing(lines):
    total = 0
    for line in lines:
        flag = line.get("error_flag")
        if flag == "DUPLICATE":
            total += 0
        elif flag == "UPCODING":
            total += round_half_up_cents(Decimal(str(line["billed_cents"])) * Decimal(str(line["schedule_rate"])))
        else:
            total += int(line["billed_cents"])
    return total


def deductible_application(member, allowed_amount_cents):
    remaining = max(0, member["deductible_limit_cents"] - member["deductible_used_cents"])
    deductible_applied = min(remaining, allowed_amount_cents)
    coinsurance = round_half_up_cents(COINSURANCE_RATE * Decimal(allowed_amount_cents - deductible_applied))
    member_resp = deductible_applied + coinsurance
    return deductible_applied, member_resp


def cost_share_estimate(member, provider, allowed_amount_cents):
    """Returns (member_resp, deductible_portion, coinsurance_portion, oop_capped)."""
    if provider["network_status"] == "OUT_OF_NETWORK":
        resp = round_half_up_cents(OON_COINSURANCE_RATE * Decimal(allowed_amount_cents))
        return resp, 0, resp, False
    remaining = max(0, member["deductible_limit_cents"] - member["deductible_used_cents"])
    deductible_portion = min(remaining, allowed_amount_cents)
    coinsurance_portion = round_half_up_cents(COINSURANCE_RATE * Decimal(allowed_amount_cents - deductible_portion))
    uncapped = deductible_portion + coinsurance_portion
    room = max(0, member["oop_max_cents"] - member["oop_used_cents"])
    resp = min(uncapped, room)
    return resp, deductible_portion, coinsurance_portion, resp < uncapped
