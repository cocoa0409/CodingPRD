"""Market pricing calculations: aging, composite, midpoint, edges, overlap (§3.3-§3.5)."""
from datetime import date, datetime
from decimal import Decimal
from db import store
from errors import no_market_data
from services.common import (
    ESCALATION_RATE, PERCENTILE_FACTOR, DEFAULT_MAX_OVERLAP_PCT,
    DEFAULT_MIN_PROGRESSION_PCT, round_cents, round4,
)


def _to_date(value) -> date:
    """Parse an ISO date or datetime string into a date."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    v = str(value).strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(v).date()
    except ValueError:
        return date.fromisoformat(v[:10])


def whole_months_between(from_date: date, to_date: date) -> int:
    """Whole calendar months, floor; partial month never counts."""
    months = (to_date.year - from_date.year) * 12 + (to_date.month - from_date.month)
    if to_date.day < from_date.day:
        months -= 1
    return max(0, months)


def aged_p50(cut: dict, pricing_date: date) -> int:
    months = whole_months_between(_to_date(cut["effective_date"]), pricing_date)
    factor = Decimal(1) + ESCALATION_RATE * Decimal(months) / Decimal(12)
    return round_cents(Decimal(cut["p50_cents"]) * factor)


def candidate_cuts(band: dict, variant: str):
    """Return list of qualifying MarketCut rows for the band."""
    profile_for_cut = {}
    out = []
    for cut in store.market_cuts.values():
        profile = store.job_profiles.get(cut["job_profile_id"])
        if profile is None:
            continue
        if profile["job_family_id"] != band["job_family_id"]:
            continue
        if profile["job_level_id"] != band["job_level_id"]:
            continue
        if cut["geo_zone_id"] != band["geo_zone_id"]:
            continue
        if cut.get("excluded_from_composite"):
            continue
        survey = store.market_surveys.get(cut["market_survey_id"])
        if survey is None:
            continue
        if variant == "OFFICIAL":
            if profile["status"] != "APPROVED":
                continue
            if survey["status"] != "ACCEPTED":
                continue
        else:  # PROVISIONAL
            if survey["status"] not in ("SUBMITTED", "ACCEPTED"):
                continue
        out.append((cut, profile, survey))
    return out


def market_composite(band: dict, variant: str, pricing_date: date):
    """Return (composite_cents, cut_count) or raise ERR_NO_MARKET_DATA."""
    candidates = candidate_cuts(band, variant)
    if not candidates:
        raise no_market_data()
    if variant == "PROVISIONAL":
        total = sum(Decimal(c["p50_cents"]) for c, _, _ in candidates)
        composite = round_cents(total / Decimal(len(candidates)))
    else:
        num = Decimal(0)
        den = Decimal(0)
        for cut, _, _ in candidates:
            aged = aged_p50(cut, pricing_date)
            num += Decimal(aged) * Decimal(cut["sample_size"])
            den += Decimal(cut["sample_size"])
        composite = round_cents(num / den)
    return composite, len(candidates)


def build_band_values(band: dict, composite_cents: int, geo_ratio: Decimal):
    """3-step midpoint construction with rounding after every step; then edges."""
    pct_factor = PERCENTILE_FACTOR[band["target_percentile"]]
    step1 = round_cents(Decimal(composite_cents) * pct_factor)
    step2 = round_cents(Decimal(step1) * geo_ratio)
    midpoint = round_cents(Decimal(step2) * Decimal(str(band.get("policy_adjustment_factor", 1.0))))
    spread = Decimal(str(band["spread_pct"]))
    min_cents = round_cents(Decimal(midpoint) * (Decimal(1) - spread / Decimal(2)))
    max_cents = round_cents(Decimal(midpoint) * (Decimal(1) + spread / Decimal(2)))
    return midpoint, min_cents, max_cents


def price_band(band: dict, variant: str, pricing_date: date):
    """Full pricing pipeline. Mutates band in place (caller bumps version)."""
    composite, count = market_composite(band, variant, pricing_date)
    zone = store.geo_zones[band["geo_zone_id"]]
    geo_ratio = Decimal(str(zone["effective_ratio"]))
    midpoint, min_cents, max_cents = build_band_values(band, composite, geo_ratio)
    band["pricing_variant"] = variant
    band["market_composite_cents"] = composite
    band["composite_cut_count"] = count
    band["geo_ratio_snapshot"] = float(geo_ratio)
    band["midpoint_cents"] = midpoint
    band["min_cents"] = min_cents
    band["max_cents"] = max_cents
    band["status"] = "PRICED"


def adjacent_lower_band(band: dict):
    """The adjacent-lower band per §3.5: same program/family/geo, greatest rank
    strictly below candidate's, status COMP_APPROVED or PUBLISHED, latest created_at."""
    cand_level = store.job_levels.get(band["job_level_id"])
    if cand_level is None:
        return None
    cand_rank = cand_level["rank_order"]
    best = None
    best_rank = None
    for other in store.pay_bands.values():
        if other["id"] == band["id"]:
            continue
        if other["comp_program_id"] != band["comp_program_id"]:
            continue
        if other["job_family_id"] != band["job_family_id"]:
            continue
        if other["geo_zone_id"] != band["geo_zone_id"]:
            continue
        if other["status"] not in ("COMP_APPROVED", "PUBLISHED"):
            continue
        olvl = store.job_levels.get(other["job_level_id"])
        if olvl is None:
            continue
        r = olvl["rank_order"]
        if r >= cand_rank:
            continue
        if best is None or r > best_rank or (r == best_rank and other["created_at"] > best["created_at"]):
            best = other
            best_rank = r
    return best


def overlap_figures(band: dict):
    """Return (lower_band_id, overlap_pct_rounded4, progression_pct_rounded4,
    unrounded_overlap, unrounded_progression). Nulls when no adjacent-lower."""
    lower = adjacent_lower_band(band)
    if lower is None:
        return None, None, None, None, None
    a_min = Decimal(lower["min_cents"])
    a_max = Decimal(lower["max_cents"])
    b_min = Decimal(band["min_cents"])
    b_max = Decimal(band["max_cents"])
    raw = min(a_max, b_max) - max(a_min, b_min)
    width = a_max - a_min
    if width == 0:
        unrounded_overlap = Decimal(0)
    else:
        unrounded_overlap = max(Decimal(0), raw) / width
    a_mid = Decimal(lower["midpoint_cents"])
    b_mid = Decimal(band["midpoint_cents"])
    unrounded_prog = (b_mid - a_mid) / a_mid
    return (
        lower["id"],
        float(round4(unrounded_overlap)),
        float(round4(unrounded_prog)),
        unrounded_overlap,
        unrounded_prog,
    )


def policy_for(family_id, from_level_id, to_level_id):
    for p in store.progression_policies.values():
        if (p["job_family_id"] == family_id
                and p["from_level_id"] == from_level_id
                and p["to_level_id"] == to_level_id):
            return p
    return None


def approval_policy_limits(band: dict, lower_band_id):
    """(max_overlap_allowed, min_progression_required) as Decimals."""
    if lower_band_id is None:
        return DEFAULT_MAX_OVERLAP_PCT, DEFAULT_MIN_PROGRESSION_PCT
    lower = store.pay_bands[lower_band_id]
    pol = policy_for(band["job_family_id"], lower["job_level_id"], band["job_level_id"])
    if pol is None:
        return DEFAULT_MAX_OVERLAP_PCT, DEFAULT_MIN_PROGRESSION_PCT
    return Decimal(str(pol["max_overlap_pct"])), Decimal(str(pol["min_midpoint_progression_pct"]))
