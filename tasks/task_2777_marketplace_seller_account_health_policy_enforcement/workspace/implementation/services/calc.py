"""Every pinned calculation of PRD sections 3.1, 3.4, 3.6 and 3.9."""

from decimal import Decimal, ROUND_HALF_UP

import constants as C

ZERO = Decimal("0")
ZERO2 = Decimal("0.00")
ZERO4 = Decimal("0.0000")
ONE = Decimal("1.00")
HUNDRED = Decimal("100.00")


def q(value, places):
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def q2(value):
    return q(value, 2)


def q4(value):
    return q(value, 4)


def qcents(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _rate(numerator, denominator, fallback=ZERO4):
    if denominator == 0:
        return fallback
    return q4(Decimal(numerator) / Decimal(denominator))


# --- 3.4 health evaluation --------------------------------------------------

def _ratio_over(rate, threshold):
    diff = rate - threshold
    if diff < 0:
        diff = ZERO
    ratio = Decimal(diff) / threshold
    return ratio if ratio <= C.RATIO_CAP else C.RATIO_CAP


def _ratio_under(rate, floor):
    diff = floor - rate
    if diff < 0:
        diff = ZERO
    ratio = Decimal(diff) / floor
    return ratio if ratio <= C.RATIO_CAP else C.RATIO_CAP


def evaluate(snapshots):
    """snapshots: the input set, already ordered window_end DESC / created_at ASC."""
    latest = snapshots[0]
    order_volume_final = sum(s["order_volume"] for s in snapshots)

    odr_provisional = _rate(
        latest["defect_claims_pending"] + latest["defect_claims_substantiated"],
        latest["order_volume"],
    )
    odr_final = _rate(
        sum(s["defect_claims_substantiated"] for s in snapshots),
        sum(s["delivered_or_refunded_volume"] for s in snapshots),
    )
    odr_variant_delta = q4(odr_provisional - odr_final)

    late_shipment_rate = _rate(
        sum(s["late_shipments"] for s in snapshots), order_volume_final
    )
    cancellation_rate = _rate(
        sum(s["pre_fulfillment_cancellations"] for s in snapshots), order_volume_final
    )
    valid_tracking_rate = _rate(
        sum(s["shipments_with_valid_tracking"] for s in snapshots),
        sum(s["shipments_total"] for s in snapshots),
        fallback=Decimal("1.0000"),
    )

    if order_volume_final == 0:
        # PRD 3.4: with no orders in the window all four ratios are zero.
        health_score = HUNDRED
    else:
        penalties = [
            q2(_ratio_over(odr_final, C.ODR_BREACH_RATE) * C.HEALTH_WEIGHT_ODR),
            q2(_ratio_over(late_shipment_rate, C.LATE_SHIPMENT_BREACH_RATE)
               * C.HEALTH_WEIGHT_LATE),
            q2(_ratio_over(cancellation_rate, C.CANCELLATION_BREACH_RATE)
               * C.HEALTH_WEIGHT_CANCELLATION),
            q2(_ratio_under(valid_tracking_rate, C.VALID_TRACKING_MIN_RATE)
               * C.HEALTH_WEIGHT_TRACKING),
        ]
        penalty_total = q2(sum(penalties, ZERO2))
        health_score = q2(HUNDRED - penalty_total)
        if health_score < ZERO2:
            health_score = ZERO2

    breached = []
    if odr_final >= C.ODR_BREACH_RATE:
        breached.append("ORDER_DEFECT_RATE")
    if late_shipment_rate >= C.LATE_SHIPMENT_BREACH_RATE:
        breached.append("LATE_SHIPMENT_RATE")
    if cancellation_rate >= C.CANCELLATION_BREACH_RATE:
        breached.append("CANCELLATION_RATE")
    if valid_tracking_rate < C.VALID_TRACKING_MIN_RATE:
        breached.append("VALID_TRACKING_RATE")
    breached = [m for m in C.BREACH_METRIC_ORDER if m in breached]

    if order_volume_final == 0:
        metric_tier = "EXEMPT"
    elif len(breached) >= C.TIER_BREACH_METRIC_COUNT or health_score < C.TIER_BREACH_SCORE:
        metric_tier = "BREACHING"
    elif len(breached) >= 1 or health_score < C.TIER_AT_RISK_SCORE:
        metric_tier = "AT_RISK"
    else:
        metric_tier = "HEALTHY"

    return {
        "input_snapshot_count": len(snapshots),
        "input_window_start": min(s["window_start"] for s in snapshots),
        "input_window_end": max(s["window_end"] for s in snapshots),
        "odr_provisional": odr_provisional,
        "odr_final": odr_final,
        "odr_variant_delta": odr_variant_delta,
        "late_shipment_rate": late_shipment_rate,
        "cancellation_rate": cancellation_rate,
        "valid_tracking_rate": valid_tracking_rate,
        "order_volume_final": order_volume_final,
        "health_score": health_score,
        "metric_tier": metric_tier,
        "breached_metrics": breached,
    }


# --- 3.6 severity, decay and the ladder ------------------------------------

def repeat_factor(prior_count):
    capped = prior_count if prior_count < C.REPEAT_CAP_COUNT else C.REPEAT_CAP_COUNT
    return ONE + (Decimal(capped) * C.REPEAT_STEP)


def severity_points_applied(base_weight, prior_same_category, ip_rights_owner,
                            tier_breaching):
    running = Decimal(base_weight) * repeat_factor(prior_same_category)
    if ip_rights_owner:
        running = running * C.IP_ESCALATION_MULTIPLIER
    if tier_breaching:
        running = running * C.BREACHING_ESCALATION_MULTIPLIER
    points = q2(running)
    if points < C.SEVERITY_MIN_POINTS:
        points = C.SEVERITY_MIN_POINTS
    if points > C.SEVERITY_MAX_POINTS:
        points = C.SEVERITY_MAX_POINTS
    return points


def decay_factor(action, now):
    if action.get("decay_exempt"):
        return C.DECAY_TIER1_FACTOR
    age_days = (now - action["issued_at"]).days
    if age_days < C.DECAY_TIER1_DAYS:
        return C.DECAY_TIER1_FACTOR
    if age_days < C.DECAY_TIER2_DAYS:
        return C.DECAY_TIER2_FACTOR
    return C.DECAY_TIER3_FACTOR


def decayed_balance(actions, now):
    total = ZERO
    for action in actions:
        if action["state"] not in C.ACTION_LIVE_STATES:
            continue
        total = total + (Decimal(action["severity_points_applied"]) * decay_factor(action, now))
    return q2(total)


def ladder_rung(post_balance, category):
    if post_balance >= C.LADDER_SUSPEND_POINTS:
        rung = "ACCOUNT_SUSPENSION"
    elif post_balance >= C.LADDER_RESTRICT_POINTS:
        rung = "LISTING_REMOVAL"
    else:
        rung = "WARNING"
    if category == "RESTRICTED_PRODUCT" and rung == "WARNING":
        rung = "LISTING_REMOVAL"
    return rung


def repeat_offense_count(appealed_action, seller_actions):
    """PRD 3.8: other live actions of the same seller in the same category,
    issued no later than the appealed action."""
    count = 0
    for other in seller_actions:
        if other["id"] == appealed_action["id"]:
            continue
        if other["policy_category"] != appealed_action["policy_category"]:
            continue
        if other["state"] not in C.ACTION_LIVE_STATES:
            continue
        if other["issued_at"] > appealed_action["issued_at"]:
            continue
        count += 1
    return count


# --- 3.9 funds -------------------------------------------------------------

def risk_tier(seller):
    balance = Decimal(seller["severity_points_balance"])
    if (seller["enforcement_state"] in ("SUSPENDED", "BANNED")
            or balance >= C.LADDER_SUSPEND_POINTS
            or seller.get("metric_tier") == "BREACHING"):
        return "TIER_3"
    if (balance >= C.LADDER_RESTRICT_POINTS
            or seller.get("metric_tier") == "AT_RISK"
            or seller.get("registration_risk_flag")):
        return "TIER_2"
    return "TIER_1"


def reserve_requirement_cents(reserve_basis, tier, seller):
    if reserve_basis == "ROLLING":
        return qcents(Decimal(seller["available_balance_cents"]) * C.RESERVE_ROLLING_PCT[tier])
    if reserve_basis == "CLAIM_EXPOSURE":
        return qcents(
            Decimal(seller["open_defect_claim_units"])
            * C.CLAIM_EXPOSURE_CENTS
            * C.EXPOSURE_MULTIPLIER[tier]
        )
    return 0


# --- 3.1 related-account confidence ---------------------------------------

def confidence(candidate, incumbent):
    """Returns (score, matched_signals) for one candidate/incumbent pair."""
    signals = []
    if candidate["tax_id_hash"] == incumbent["tax_id_hash"]:
        signals.append("TAX_ID")
    if candidate["payout_bank_token"] == incumbent["payout_bank_token"]:
        signals.append("BANK_TOKEN")
    if candidate["address_fingerprint"] == incumbent["address_fingerprint"]:
        signals.append("ADDRESS")
    domain = candidate["email_domain"]
    if (domain
            and domain not in C.PUBLIC_EMAIL_DOMAINS
            and domain == incumbent["email_domain"]):
        signals.append("EMAIL_DOMAIN")
    if (candidate.get("device_fingerprint")
            and candidate["device_fingerprint"] == incumbent.get("device_fingerprint")):
        signals.append("DEVICE")
    ordered = [s for s in C.MATCH_SIGNAL_ORDER if s in signals]
    total = ZERO
    for signal in ordered:
        total = total + C.SIGNAL_WEIGHT[signal]
    if total > ONE:
        total = ONE
    return q2(total), ordered
