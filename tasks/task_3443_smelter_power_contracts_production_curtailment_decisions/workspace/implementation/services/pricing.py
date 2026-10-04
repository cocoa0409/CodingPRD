"""Pricing engine (PRD 3.3, 3.4): power cost variants, settlement, transfer price."""
from datetime import timedelta

from constants import GLOBAL_REGION, INTERRUPTIBLE_DISCOUNT_PCT, LOSS_FACTOR
from db import STORE, logical_clock
from services.core import contract_year_bounds
from util import D, month_start_of, round2_dec


def _observations(instrument, region_code):
    now = logical_clock()
    return [
        o
        for o in STORE["price_observations"].values()
        if o["instrument"] == instrument
        and o["region_code"] == region_code
        and o["observed_at"] <= now
    ]


def latest_observation(instrument, region_code):
    """Greatest observed_at at or before the clock; tie-break created_at DESC."""
    cands = _observations(instrument, region_code)
    if not cands:
        return None
    return max(cands, key=lambda o: (o["observed_at"], o["created_at"]))


def _blend(components):
    f = D(0)
    m_mw = D(0)
    i_mw = D(0)
    total = D(0)
    for c in components:
        v = D(c["volume_mw"])
        total += v
        ctype = c["component_type"]
        if ctype == "FIXED":
            f += v * D(c.get("fixed_price_per_mwh", 0))
        elif ctype == "MARKET_INDEXED":
            m_mw += v
        else:
            i_mw += v
    return f, m_mw, i_mw, total


def _smelter_region(contract):
    smelter = STORE["smelters"].get(contract["smelter_id"])
    return smelter["region_code"] if smelter else None


def forward_cost_per_mwh(contract):
    """FORWARD variant: latest spot only. None when spot required but missing."""
    f, m_mw, i_mw, total = _blend(contract["components"])
    if m_mw + i_mw == 0:
        return round2_dec(f / total)
    spot = latest_observation("POWER_SPOT", _smelter_region(contract))
    if spot is None:
        return None
    s = D(spot["price_usd"])
    cost = (f + m_mw * s + i_mw * s * (1 - INTERRUPTIBLE_DISCOUNT_PCT)) / total
    return round2_dec(cost)


def settled_cost_per_mwh(contract):
    """SETTLED variant: time-weighted replay over the current calendar month."""
    f, m_mw, i_mw, total = _blend(contract["components"])
    if m_mw + i_mw == 0:
        return round2_dec(f / total)
    now = logical_clock()
    ms = month_start_of(now)
    obs = [o for o in _observations("POWER_SPOT", _smelter_region(contract)) if o["observed_at"] >= ms]
    obs.sort(key=lambda o: (o["observed_at"], o["created_at"]))
    if not obs:
        return None
    elapsed_hours = (now - ms).total_seconds() / 3600.0
    if elapsed_hours <= 0:
        tw_avg = D(obs[-1]["price_usd"])
    else:
        weighted = D(0)
        for idx, o in enumerate(obs):
            seg_start = ms if idx == 0 else o["observed_at"]
            seg_end = obs[idx + 1]["observed_at"] if idx + 1 < len(obs) else now
            hours = D((seg_end - seg_start).total_seconds()) / D(3600)
            weighted += D(o["price_usd"]) * hours
        tw_avg = weighted / D(elapsed_hours)
    cost = (f + m_mw * tw_avg + i_mw * tw_avg * (1 - INTERRUPTIBLE_DISCOUNT_PCT)) / total
    return round2_dec(cost)


def month_to_date_settlement(contract):
    """Round-per-hour-then-sum settlement for the current calendar month."""
    components = contract["components"]
    region = _smelter_region(contract)
    has_market = any(
        c["component_type"] in ("MARKET_INDEXED", "INTERRUPTIBLE") for c in components
    )
    now = logical_clock()
    obs_sorted = sorted(
        _observations("POWER_SPOT", region),
        key=lambda o: (o["observed_at"], o["created_at"]),
    )
    if has_market and not obs_sorted:
        return None
    ms = month_start_of(now)
    n_hours = int((now - ms).total_seconds() // 3600)
    total_cost = D(0)
    for k in range(n_hours):
        hour_start = ms + timedelta(hours=k)
        spot_price = None
        if has_market:
            eligible = [o for o in obs_sorted if o["observed_at"] <= hour_start]
            chosen = eligible[-1] if eligible else obs_sorted[0]
            spot_price = D(chosen["price_usd"])
        raw = D(0)
        for c in components:
            v = D(c["volume_mw"])
            ctype = c["component_type"]
            if ctype == "FIXED":
                price = D(c.get("fixed_price_per_mwh", 0))
                loss = D(1)
            elif ctype == "MARKET_INDEXED":
                price = spot_price
                loss = LOSS_FACTOR
            else:
                price = spot_price * (1 - INTERRUPTIBLE_DISCOUNT_PCT)
                loss = LOSS_FACTOR
            raw += v * price * loss
        total_cost += round2_dec(raw)
    return total_cost


def transfer_price(agreement):
    """Internal transfer price (PRD 3.4); None for MARKET_LINKED without an index."""
    if agreement["pricing_model"] == "COST_PLUS":
        return round2_dec(
            D(agreement["base_cost_per_tonne"]) * (1 + D(agreement["markup_pct"]))
        )
    idx = latest_observation("ALUMINA_INDEX", GLOBAL_REGION)
    if idx is None:
        return None
    return round2_dec(D(idx["price_usd"]) * (1 - D(agreement["market_discount_pct"])))


def interruptible_hours_used(contract):
    """Sum of event hours whose start_at falls in the current contract year."""
    year_start, year_end = contract_year_bounds(contract)
    total = 0.0
    for ev in STORE["interrupt_events"].values():
        if ev["contract_id"] == contract["id"] and year_start <= ev["start_at"] < year_end:
            total += ev["hours"]
    return total
