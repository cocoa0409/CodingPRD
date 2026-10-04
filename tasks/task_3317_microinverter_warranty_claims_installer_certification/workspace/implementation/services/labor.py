"""compute_labor_reimbursement: the level/rate/age snapshot and the two
rounding variants (PRD 3.8 and the calculation table).

The persisted amount is the per-component figure; the single-rounding variant is
surfaced only on the read-only quote and is never paid.
"""

from services import common
from respond import CLOCK, parse_iso


def snapshot(level, claimed_hours, system, at=None):
    """Compute every derived field of a labor reimbursement at filing time."""
    at = at or CLOCK.now()
    level = level if level in common.LEVELS else "CERTIFIED"

    base_rate_cents = common.LEVEL_BASE_RATE_CENTS[level]
    level_factor = common.LEVEL_FACTOR[level]
    cap_hours = common.LEVEL_CAP_HOURS[level]
    diagnostic_fee_cents = common.DIAGNOSTIC_FEE_CENTS_BY_LEVEL[level]

    age_months = common.system_age_months(system, at)
    age_factor = common.age_factor_for_months(age_months)

    claimed = common.dec(claimed_hours).quantize(common.Decimal("0.01"),
                                                 rounding=common.ROUND_HALF_UP)
    allowed_hours = min(claimed, cap_hours)
    cap_applied = claimed > cap_hours

    labor_raw = allowed_hours * common.dec(base_rate_cents) * level_factor * age_factor
    diagnostic_raw = common.dec(diagnostic_fee_cents) * age_factor

    labor_component_cents = common.money(labor_raw)
    diagnostic_component_cents = common.money(diagnostic_raw)
    net_amount_cents = labor_component_cents + diagnostic_component_cents

    blended_raw = labor_raw + diagnostic_raw
    blended_total_cents = common.money(blended_raw)

    hourly_rate_cents = common.money(
        common.dec(base_rate_cents) * level_factor * age_factor
    )

    return {
        "level_used": level,
        "system_age_months": age_months,
        "age_factor": float(age_factor),
        "level_factor": float(level_factor),
        "base_rate_cents": base_rate_cents,
        "cap_hours": float(cap_hours),
        "claimed_hours": float(claimed),
        "allowed_hours": common.hours2(allowed_hours),
        "cap_applied": cap_applied,
        "hourly_rate_cents": hourly_rate_cents,
        "labor_component_cents": labor_component_cents,
        "diagnostic_component_cents": diagnostic_component_cents,
        "net_amount_cents": net_amount_cents,
        "blended_total_cents": blended_total_cents,
    }


def recompute_for_reimbursement(reimbursement):
    """Read-only recompute: the claim's system and the level captured at filing."""
    claim = common.db.DB.claims.get(reimbursement.get("claim_id"))
    system = None
    if claim is not None:
        unit = common.db.DB.units.get(claim.get("unit_id"))
        if unit is not None:
            system = common.db.DB.systems.get(unit.get("system_id"))

    level = reimbursement.get("level_at_filing")
    if level is None and claim is not None:
        level = claim.get("installer_level_at_claim")
    if level is None:
        level = "CERTIFIED"

    at = CLOCK.now()
    if reimbursement.get("filed_at"):
        at = parse_iso(reimbursement["filed_at"])
    return snapshot(level, reimbursement.get("claimed_hours", 0), system, at)