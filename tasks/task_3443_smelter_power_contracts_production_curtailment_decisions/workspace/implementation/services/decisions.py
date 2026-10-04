"""Curtailment margin gate (PRD 3.5): computes the frozen economics_snapshot."""
from constants import (
    ALUMINA_RATIO_T_PER_T,
    GLOBAL_REGION,
    OTHER_CONVERSION_COST_PER_T,
    POWER_INTENSITY_MWH_PER_T,
    RESTART_RESERVE_PER_T,
)
from db import STORE
from errors import raise_err
from services.core import covering_active_contract, potline_restart_class
from services.pricing import forward_cost_per_mwh, latest_observation, transfer_price
from util import D, round2_dec


def _latest_transfer_price(smelter_id):
    """Most recently created agreement's transfer price; ALUMINA_INDEX fallback."""
    agreements = [
        a for a in STORE["alumina_agreements"].values() if a["smelter_id"] == smelter_id
    ]
    if agreements:
        latest = max(agreements, key=lambda a: (a["created_at"], a["id"]))
        return transfer_price(latest)
    idx = latest_observation("ALUMINA_INDEX", GLOBAL_REGION)
    if idx is None:
        return None
    return round2_dec(D(idx["price_usd"]))


def compute_economics_snapshot(potline):
    smelter = STORE["smelters"][potline["smelter_id"]]
    region = smelter["region_code"]
    lme_obs = latest_observation("ALUMINUM_LME", GLOBAL_REGION)
    premium_obs = latest_observation("REGIONAL_PREMIUM", region)
    transfer = _latest_transfer_price(smelter["id"])
    if lme_obs is None or premium_obs is None or transfer is None:
        raise_err(
            "ERR_NO_PRICE_OBSERVATION",
            "A required LME / regional-premium / transfer price observation is missing.",
        )
    contract = covering_active_contract(smelter["id"])
    if contract is None:
        raise_err(
            "ERR_NO_ACTIVE_POWER_CONTRACT",
            "No ACTIVE power contract covers the current logical clock.",
        )
    power = forward_cost_per_mwh(contract)
    if power is None:
        raise_err(
            "ERR_NO_PRICE_OBSERVATION",
            "No POWER_SPOT observation available for the forward power cost.",
        )
    lme = round2_dec(D(lme_obs["price_usd"]))
    premium = round2_dec(D(premium_obs["price_usd"]))
    margin = round2_dec(
        lme
        + premium
        - ALUMINA_RATIO_T_PER_T * transfer
        - POWER_INTENSITY_MWH_PER_T * power
        - OTHER_CONVERSION_COST_PER_T
    )
    shortfall = RESTART_RESERVE_PER_T - margin
    return {
        "lme_price_usd": float(lme),
        "regional_premium_usd": float(premium),
        "transfer_price_per_tonne": float(transfer),
        "power_cost_per_mwh": float(power),
        "margin_per_tonne": float(margin),
        "curtailment_economic": margin < RESTART_RESERVE_PER_T,
        "avoidable_loss_per_tonne": float(shortfall if shortfall > 0 else D(0)),
        "restart_cost_class": potline_restart_class(potline),
    }
