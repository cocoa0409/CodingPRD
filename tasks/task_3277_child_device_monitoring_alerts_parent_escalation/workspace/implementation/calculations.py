"""Calculation rules from SCAFFOLD section 1.3."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

# --- content_risk_scoring ---
SCORE_CAP = 100
CONTEXT_STEP = Decimal("0.05")
CONTEXT_DEPTH_CAP = 5


def risk_score(signals, thread_depth, variant):
    base = min(SCORE_CAP, sum(int(s["weight"]) for s in signals))
    if variant == "CONTEXTUAL_V2":
        depth = min(int(thread_depth), CONTEXT_DEPTH_CAP)
        factor = Decimal(1) + CONTEXT_STEP * depth
        score = (Decimal(base) * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return int(min(SCORE_CAP, int(score)))
    return base


# --- alert_severity_classification ---
SEVERE_MIN = 85
HIGH_MIN = 60
MODERATE_MIN = 30

LEVEL_TO_SEVERITY = {1: "LOW", 2: "MODERATE", 3: "HIGH", 4: "SEVERE"}


def dominant_category(signals):
    """Max weight; ties break to earliest index."""
    best = None
    best_weight = None
    for s in signals:
        w = int(s["weight"])
        if best is None or w > best_weight:
            best = s
            best_weight = w
    return best["category"] if best else None


def classify_severity(score, signals, age_band, sensitivity):
    if score >= SEVERE_MIN:
        base_level = 4
    elif score >= HIGH_MIN:
        base_level = 3
    elif score >= MODERATE_MIN:
        base_level = 2
    else:
        base_level = 1

    category = dominant_category(signals)

    age_delta = 0
    if age_band == "CHILD_9_UNDER":
        age_delta = 1
    elif age_band == "OLDER_TEEN_16_17" and category == "EXPLICIT":
        age_delta = -1

    sensitivity_delta = {"STRICT": 1, "LENIENT": -1, "STANDARD": 0}.get(sensitivity, 0)

    floor = 3 if category in ("PREDATORY_CONTACT", "SELF_HARM") else 1

    level = max(base_level + age_delta + sensitivity_delta, floor)
    level = max(1, min(4, level))
    return LEVEL_TO_SEVERITY[level], category


# --- excerpt_truncation ---
EXCERPT_CAP_DEFAULT = 140
EXCERPT_CAP_TEEN_LENIENT = 70


def make_excerpt(raw_text, age_band, sensitivity):
    cap = EXCERPT_CAP_DEFAULT
    if age_band == "OLDER_TEEN_16_17" and sensitivity == "LENIENT":
        cap = EXCERPT_CAP_TEEN_LENIENT
    if raw_text is None:
        raw_text = ""
    if len(raw_text) <= cap:
        return raw_text
    head = raw_text[:cap]
    if " " in head:
        head = head[: head.rfind(" ")]
    return head + "…"


# --- subscription_proration ---
MONTHLY_CENTS = {"BASIC": 999, "STANDARD": 1999, "PREMIUM": 2999}
PERIOD_DAYS = 30


def daily_cents(tier):
    return int((Decimal(MONTHLY_CENTS[tier]) / Decimal(PERIOD_DAYS)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def proration_charge(old_tier, new_tier, now, billing_period_end):
    """remaining_days = whole days from now up to (exclusive) period end."""
    delta = billing_period_end - now
    remaining_days = delta.days  # floor toward zero for positive deltas
    if remaining_days < 0:
        remaining_days = 0
    return remaining_days * (daily_cents(new_tier) - daily_cents(old_tier))


# --- device_limit_and_count ---
DEVICE_LIMITS = {"BASIC": 2, "STANDARD": 5, "PREMIUM": 10}


def device_limit_for(tier):
    return DEVICE_LIMITS[tier]


# --- bypass_strike_window ---
STRIKE_WINDOW = timedelta(days=14)
LOCKDOWN_THRESHOLD = 3


def count_strikes(events, now):
    cutoff = now - STRIKE_WINDOW
    n = 0
    for e in events:
        counted = cutoff <= e["_detected_dt"] <= now
        e["counted_in_strikes"] = counted
        if counted:
            n += 1
    return n


def posture_for(count):
    if count >= LOCKDOWN_THRESHOLD:
        return "LOCKDOWN"
    if count >= 1:
        return "BYPASS_WATCH"
    return "NORMAL"


# --- age_band_derivation ---
def age_band_for(birth_year, now):
    age = now.year - int(birth_year)
    if age <= 9:
        return "CHILD_9_UNDER", age
    if age <= 12:
        return "PRETEEN_10_12", age
    if age <= 15:
        return "TEEN_13_15", age
    return "OLDER_TEEN_16_17", age


# --- crisis resource codes ---
CRISIS_CODES = {
    "SELF_HARM": ["CRISIS_TEXT_LINE", "988_LIFELINE"],
    "PREDATORY_CONTACT": ["NCMEC_CYBERTIPLINE"],
    "BULLYING": ["STOPBULLYING_GOV"],
    "EXPLICIT": ["COMMON_SENSE_MEDIA"],
}
