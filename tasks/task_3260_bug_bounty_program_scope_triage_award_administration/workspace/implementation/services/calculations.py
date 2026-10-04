"""Calculation rules (SCAFFOLD §1.3): severity scoring, bounty amount,
withholding. All money integer cents; severity 1 decimal round-half-up."""
from decimal import Decimal, ROUND_HALF_UP

ENV_FACTOR = {"CRITICAL": "1.2", "HIGH": "1.1", "MEDIUM": "1.0", "LOW": "0.8"}

SEVERITY_BASE = {
    "CRITICAL": 1000000,
    "HIGH": 500000,
    "MEDIUM": 150000,
    "LOW": 30000,
    "NONE": 0,
}
CRIT_MULT = {"CRITICAL": "2.0", "HIGH": "1.5", "MEDIUM": "1.0", "LOW": "0.5"}
TIER_BONUS = {"NOVICE": "0.0", "ESTABLISHED": "0.10", "ELITE": "0.25"}

TAX_BLOCK_THRESHOLD_CENTS = 60000


def _round1(d):
    return d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _round0(d):
    return d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def severity_score(impact, exploitability, affected_scope, criticality, exposure_modifier):
    base = (
        Decimal("0.5") * Decimal(impact)
        + Decimal("0.3") * Decimal(exploitability)
        + Decimal("0.2") * Decimal(affected_scope)
    )
    score_base = _round1(base)
    adjusted = _round1(
        score_base * Decimal(ENV_FACTOR[criticality]) * Decimal(str(exposure_modifier))
    )
    if adjusted >= Decimal("9.0"):
        final = "CRITICAL"
    elif adjusted >= Decimal("7.0"):
        final = "HIGH"
    elif adjusted >= Decimal("4.0"):
        final = "MEDIUM"
    elif adjusted >= Decimal("0.1"):
        final = "LOW"
    else:
        final = "NONE"
    return float(score_base), float(adjusted), final


def bounty_amount(severity_final, criticality, is_first, first_report_bonus_pct,
                  tier_at_validation, available_pool_cents):
    raw_dec = Decimal(SEVERITY_BASE[severity_final]) * Decimal(CRIT_MULT[criticality])
    raw = int(raw_dec)
    combined = Decimal("0")
    if is_first:
        combined += Decimal(str(first_report_bonus_pct))
    combined += Decimal(TIER_BONUS[tier_at_validation])
    bonus = int(_round0(raw_dec * combined))
    uncapped = raw + bonus
    amount = min(uncapped, available_pool_cents)
    capped = amount < uncapped
    return amount, capped


def withholding(amount_cents, tax_document_status, country_code):
    if tax_document_status == "VERIFIED":
        rate = Decimal("0.00") if country_code == "US" else Decimal("0.30")
    else:  # SUBMITTED, or MISSING (allowed only when amount < 60000 by the gate)
        rate = Decimal("0.24")
    withheld = int(_round0(Decimal(amount_cents) * rate))
    return withheld, amount_cents - withheld
