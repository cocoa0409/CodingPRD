"""The seven calculations, plus calendar helpers. All money is whole cents and
all rounding is half up at exactly the points the PRD narratives name."""

import datetime
from decimal import Decimal, ROUND_HALF_UP

import store

# ---- trial_endorsement_score ------------------------------------------------
STAKEHOLDER_WEIGHTS = {
    "FACULTY": Decimal("1.5"),
    "GRADUATE": Decimal("1.0"),
    "UNDERGRADUATE": Decimal("0.5"),
    "LIBRARIAN": Decimal("1.25"),
}
ENDORSEMENT_THRESHOLD = Decimal("70.00")
QUORUM_PENALTY_FACTOR = Decimal("0.90")
STAKEHOLDER_QUORUM_GROUPS = 3
MIN_FEEDBACK_ROWS = 3

# ---- member_tier_price_cents -----------------------------------------------
CARNEGIE_FACTORS = {
    "R1": Decimal("1.10"),
    "R2": Decimal("1.00"),
    "MASTERS": Decimal("0.85"),
    "BACCALAUREATE": Decimal("0.75"),
}
FTE_BAND_SMALL_MAX = 5000
FTE_BAND_MEDIUM_MAX = 20000
FTE_FACTOR_SMALL = Decimal("0.60")
FTE_FACTOR_MEDIUM = Decimal("0.85")
FTE_FACTOR_LARGE = Decimal("1.15")
MIN_MEMBER_PRICE_CENTS = 150000
MAX_MEMBER_SHARE_PCT = Decimal("60")

# ---- cost_per_use / renewal_offer_price ------------------------------------
CPU_EXCELLENT_MAX_CENTS = 500
CPU_GOOD_MAX_CENTS = 1500
LOYALTY_CREDIT_PCT = {
    "EXCELLENT": Decimal("0"),
    "GOOD": Decimal("2"),
    "POOR": Decimal("5"),
    "NO_USE": Decimal("0"),
}
OFFER_FLOOR_PCT = Decimal("50")

# ---- access_health_score ---------------------------------------------------
PENALTY_OFF_CAMPUS = 8
PENALTY_ON_CAMPUS = 4
REOPEN_PENALTY = 15
RESOLVE_RECOVERY = 5
DEGRADE_THRESHOLD = 60
SCORE_FLOOR = 0
SCORE_CEILING = 100
SLA_CREDIT_PCT_PER_EVENT = Decimal("2")
SLA_CREDIT_MAX_EVENTS = 3

# ---- archival_coverage_pct -------------------------------------------------
ARCHIVAL_COVERAGE_THRESHOLD_PCT = Decimal("95.00")
ARCHIVAL_DISCREPANCY_TOLERANCE = 5

# ---- global constants ------------------------------------------------------
TRIAL_COOLDOWN_DAYS = 30
MAX_OVERLAPPING_REALM_BINDINGS = 3
MAX_NEGOTIATION_ROUNDS = 3
VOTE_QUORUM_PCT = 60
MIN_ENTITLED_TITLES = 1


def dec(value):
    """A Decimal that never inherits binary float noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to `places` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def pct2(value):
    """A two-decimal percentage rendered as a JSON number."""
    return float(rhu(value, 2))


# --------------------------------------------------------------------------- #
# calendar helpers
# --------------------------------------------------------------------------- #
def to_date(text):
    return datetime.date.fromisoformat(text)


def from_date(value):
    return value.isoformat()


def add_days(date_text, days):
    return from_date(to_date(date_text) + datetime.timedelta(days=days))


def add_one_year(date_text):
    value = to_date(date_text)
    try:
        return from_date(value.replace(year=value.year + 1))
    except ValueError:  # 29 February in a non-leap target year
        return from_date(value.replace(year=value.year + 1, day=28))


def month_of(date_text):
    return date_text[:7]


# --------------------------------------------------------------------------- #
# trial_endorsement_score
# --------------------------------------------------------------------------- #
def trial_endorsement_score(trial, variant):
    """`provisional_at_close` counts ACTIVE rows only and never penalises;
    `final_at_evaluation` counts ACTIVE and CLOSED rows and applies the quorum
    penalty when fewer than three distinct stakeholder groups responded."""
    if variant == "provisional_at_close":
        included = ("ACTIVE",)
    else:
        included = ("ACTIVE", "CLOSED")

    rows = [
        row for row in store.feedback_entries.values()
        if row["trial_id"] == trial["id"] and row["submitted_during_status"] in included
    ]

    raw = Decimal("0")
    for criterion in trial["criteria"]:
        matching = [r for r in rows if r["criterion_code"] == criterion["code"]]
        if not matching:
            average = Decimal("0.00")
        else:
            numerator = sum(
                (STAKEHOLDER_WEIGHTS[r["stakeholder_group"]] * dec(r["score"]) for r in matching),
                Decimal("0"),
            )
            denominator = sum(
                (STAKEHOLDER_WEIGHTS[r["stakeholder_group"]] for r in matching),
                Decimal("0"),
            )
            # PINNED: round each criterion average before the criteria combine.
            average = rhu(numerator / denominator, 2)
        raw += average * dec(criterion["weight_pct"]) / Decimal("100")

    score = rhu(raw, 2)
    penalty_applied = False
    if variant == "final_at_evaluation" and trial["distinct_stakeholder_group_count"] < STAKEHOLDER_QUORUM_GROUPS:
        score = rhu(score * QUORUM_PENALTY_FACTOR, 2)
        penalty_applied = True
    return score, penalty_applied


# --------------------------------------------------------------------------- #
# member_tier_price_cents
# --------------------------------------------------------------------------- #
def select_tier_band(tier_bands, participant_count):
    """The single band with the largest min_participants <= participant_count."""
    chosen = None
    for band in tier_bands:
        if band["min_participants"] <= participant_count:
            if chosen is None or band["min_participants"] > chosen["min_participants"]:
                chosen = band
    if chosen is None:
        chosen = tier_bands[0]
    return chosen


def fte_factor(fte_count):
    if fte_count < FTE_BAND_SMALL_MAX:
        return FTE_FACTOR_SMALL
    if fte_count < FTE_BAND_MEDIUM_MAX:
        return FTE_FACTOR_MEDIUM
    return FTE_FACTOR_LARGE


def member_tier_price_cents(member, product, participant_count):
    """Returns (price_cents, applied_discount_pct, participant_count)."""
    band = select_tier_band(product["tier_bands"], participant_count)
    base = dec(product["base_list_price_cents"])
    discount = dec(band["discount_pct"])
    gross = base * fte_factor(member["fte_count"]) * CARNEGIE_FACTORS[member["carnegie_class"]]
    gross = gross * (Decimal("1") - discount / Decimal("100"))
    ceiling = rhu_int(base * MAX_MEMBER_SHARE_PCT / Decimal("100"))
    # Both roundings happen before the clamp; nothing is rounded after it.
    price = max(MIN_MEMBER_PRICE_CENTS, min(rhu_int(gross), ceiling))
    return price, pct2(discount), participant_count


# --------------------------------------------------------------------------- #
# cost_per_use_cents
# --------------------------------------------------------------------------- #
def band_of(cost_per_use):
    if cost_per_use < CPU_EXCELLENT_MAX_CENTS:
        return "EXCELLENT"
    if cost_per_use < CPU_GOOD_MAX_CENTS:
        return "GOOD"
    return "POOR"


def cost_per_use(subscription, as_of_month=None, total_cents=None):
    window_start = month_of(subscription["term_start"])
    window_end = as_of_month if as_of_month else store.clock_month()
    settled_total = subscription["negotiated_price_cents"] if total_cents is None else total_cents

    usage_count = 0
    for row in store.usage_reports.values():
        if row["subscription_id"] != subscription["id"]:
            continue
        if window_start <= row["period_month"] <= window_end:
            usage_count += row["full_text_requests"]

    if usage_count == 0:
        return {
            "usage_count": 0,
            "cost_per_use_cents": None,
            "band": "NO_USE",
            "settled_invoice_total_cents": settled_total,
        }
    cpu = rhu_int(dec(settled_total) / dec(usage_count))
    return {
        "usage_count": usage_count,
        "cost_per_use_cents": cpu,
        "band": band_of(cpu),
        "settled_invoice_total_cents": settled_total,
    }


# --------------------------------------------------------------------------- #
# renewal_offer_price
# --------------------------------------------------------------------------- #
def renewal_offer_price(subscription, decision, product):
    prior_price = subscription["negotiated_price_cents"]
    usage = cost_per_use(subscription, as_of_month=None, total_cents=prior_price)
    band = usage["band"]
    capped = min(dec(decision["vendor_requested_increase_pct"]), dec(product["inflation_cap_pct"]))
    escalated = rhu_int(dec(prior_price) * (Decimal("1") + capped / Decimal("100")))
    loyalty = rhu_int(dec(prior_price) * LOYALTY_CREDIT_PCT[band] / Decimal("100"))
    sla_applied = subscription["sla_credit_cents"]
    floor = rhu_int(dec(prior_price) * OFFER_FLOOR_PCT / Decimal("100"))
    offer = max(floor, escalated - loyalty - sla_applied)
    return {
        "capped_increase_pct": pct2(capped),
        "cost_per_use_cents": usage["cost_per_use_cents"],
        "cost_per_use_band": band,
        "loyalty_credit_cents": loyalty,
        "sla_credit_applied_cents": sla_applied,
        "offer_price_cents": offer,
    }


# --------------------------------------------------------------------------- #
# access_health_score
# --------------------------------------------------------------------------- #
def access_health_score(subscription_id):
    penalty = 0
    for incident in store.access_incidents.values():
        if incident["subscription_id"] != subscription_id:
            continue
        penalty += PENALTY_OFF_CAMPUS if incident["off_campus"] else PENALTY_ON_CAMPUS
        penalty += REOPEN_PENALTY * incident["reopen_count"]
        if incident["status"] == "RESOLVED":
            penalty -= RESOLVE_RECOVERY
    return min(SCORE_CEILING, max(SCORE_FLOOR, 100 - penalty))


# --------------------------------------------------------------------------- #
# archival_coverage_pct
# --------------------------------------------------------------------------- #
def archival_coverage_pct(attested_title_count, entitled_title_count):
    if entitled_title_count == 0:
        return Decimal("0.00")
    return rhu(dec(attested_title_count) / dec(entitled_title_count) * Decimal("100"), 2)


# --------------------------------------------------------------------------- #
# consortium_invoice_allocation
# --------------------------------------------------------------------------- #
def consortium_invoice_allocation(subscription):
    rows = [
        c for c in store.commitments.values()
        if c.get("subscription_id") == subscription["id"] and c["status"] == "CONFIRMED"
    ]
    ordered = sorted(
        rows,
        key=lambda c: (
            store.members[c["member_id"]]["created_at"],
            c["created_at"],
            c["_seq"],
        ),
    )
    total = subscription["negotiated_price_cents"]
    weight_sum = sum(store.members[c["member_id"]]["fte_count"] for c in ordered)

    if not ordered or weight_sum == 0:
        return {
            "total_cents": total,
            "lines": [],
            "residual_cents": total,
            "residual_assigned_commitment_id": None,
        }

    exact = {}
    lines = []
    for commitment in ordered:
        member = store.members[commitment["member_id"]]
        raw = dec(total) * dec(member["fte_count"]) / dec(weight_sum)
        exact[commitment["id"]] = raw
        lines.append({
            "commitment_id": commitment["id"],
            "member_id": member["id"],
            "allocated_cents": rhu_int(raw),
            "fte_weight": member["fte_count"],
        })

    residual = total - sum(line["allocated_cents"] for line in lines)

    winner_index = 0
    best_fraction = None
    for index, commitment in enumerate(ordered):
        raw = exact[commitment["id"]]
        fraction = raw - Decimal(int(raw.to_integral_value(rounding="ROUND_FLOOR")))
        if best_fraction is None or fraction > best_fraction:
            best_fraction = fraction
            winner_index = index

    lines[winner_index]["allocated_cents"] += residual
    return {
        "total_cents": total,
        "lines": lines,
        "residual_cents": residual,
        "residual_assigned_commitment_id": lines[winner_index]["commitment_id"],
    }
