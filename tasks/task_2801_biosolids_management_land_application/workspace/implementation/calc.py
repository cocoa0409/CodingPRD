"""Pure calculations (PRD sections 2.5, 3.1-3.12)."""

from decimal import Decimal

from store import (D, FUEL_ESCALATOR, HECTARES_PER_ACRE, KG_PER_DRY_TON,
                   MG_KG_TO_LB_PER_DRY_TON, r1, r2, r3, r4)

VOLATILIZATION_FACTOR = {
    "SURFACE": Decimal("0.50"),
    "INCORPORATED": Decimal("0.75"),
    "INJECTED": Decimal("1.00"),
}

MINERALIZATION_FACTOR = {
    "ANAEROBIC_DIGESTION": Decimal("0.20"),
    "COMPOSTED": Decimal("0.10"),
    "LIME_STABILIZED": Decimal("0.30"),
}

SEVERITY_WEIGHT = {"LOW": Decimal(1), "MODERATE": Decimal(3), "SEVERE": Decimal(7)}

SENTINEL_RATE = Decimal("9999.0")


def vsr_van_kleeck(volatile_solids_in_pct, volatile_solids_out_pct):
    vs_in = D(volatile_solids_in_pct) / Decimal(100)
    vs_out = D(volatile_solids_out_pct) / Decimal(100)
    denom = vs_in - (vs_in * vs_out)
    if denom == 0:
        return r2(0)
    return r2((vs_in - vs_out) / denom * Decimal(100))


def vsr_mass_balance(dry_tons_in, volatile_solids_in_pct, dry_tons_out,
                     volatile_solids_out_pct):
    vs_in = D(volatile_solids_in_pct) / Decimal(100)
    vs_out = D(volatile_solids_out_pct) / Decimal(100)
    vs_mass_in = D(dry_tons_in) * vs_in
    vs_mass_out = D(dry_tons_out) * vs_out
    if vs_mass_in == 0:
        return r2(0)
    return r2((vs_mass_in - vs_mass_out) / vs_mass_in * Decimal(100))


def pathogen_class(batch):
    option = batch.get("pathogen_option")
    temp = batch.get("digester_temp_c")
    detention = batch.get("detention_days")
    fecal = batch.get("fecal_coliform_mpn_per_g")
    salmonella = batch.get("salmonella_mpn_per_4g")
    if option == "PFRP_ALT1_TIME_TEMP":
        if temp is None or detention is None or fecal is None or salmonella is None:
            return "NONE"
        if (D(temp) >= Decimal("53.0") and D(detention) >= Decimal("5.0")
                and D(fecal) < Decimal(1000) and D(salmonella) < Decimal(3)):
            return "CLASS_A"
        return "NONE"
    if option == "PSRP_ALT1_TIME_TEMP":
        if temp is None or detention is None:
            return "NONE"
        if D(temp) >= Decimal("35.0") and D(detention) >= Decimal("15.0"):
            return "CLASS_B"
        return "NONE"
    if option == "PSRP_ALT3_FECAL_COLIFORM":
        if fecal is None:
            return "NONE"
        if D(fecal) < Decimal(2000000):
            return "CLASS_B"
        return "NONE"
    return "NONE"


def plant_available_n(batch, application_method):
    volat = VOLATILIZATION_FACTOR[application_method]
    miner = MINERALIZATION_FACTOR.get(batch.get("stabilization_process"), Decimal(0))
    nh4 = D(batch.get("nh4_n_mg_kg") or 0)
    org = D(batch.get("organic_n_mg_kg") or 0)
    nitrate = D(batch.get("nitrate_n_mg_kg") or 0)
    total = (nh4 * volat) + (org * miner) + nitrate
    return r4(total * MG_KG_TO_LB_PER_DRY_TON)


def per_unit_loading(concentration_mg_kg):
    """kg/ha of an analyte per dry ton per acre applied."""
    return (D(concentration_mg_kg) * Decimal("0.000001") * KG_PER_DRY_TON
            / HECTARES_PER_ACRE)


def loading_delta(applied_rate, concentration_mg_kg):
    return r4(D(applied_rate) * per_unit_loading(concentration_mg_kg))


def cost_breakdown(wet_tons, dry_tons, haul_miles, outlet):
    processing = r2(D(wet_tons) * D(outlet["gate_fee_per_wet_ton"]))
    hauling = r2(D(haul_miles) * D(wet_tons)
                 * D(outlet["haul_rate_per_mile_per_wet_ton"]) * FUEL_ESCALATOR)
    subtotal = r2(processing + hauling)
    if subtotal >= Decimal("10000.00"):
        surcharge_pct = Decimal("0.05")
    elif subtotal >= Decimal("2000.00"):
        surcharge_pct = Decimal("0.03")
    else:
        surcharge_pct = Decimal("0.00")
    surcharge_cost = r2(subtotal * surcharge_pct)
    total = r2(subtotal + surcharge_cost)
    cost_per_dry_ton = r2(total / D(dry_tons)) if D(dry_tons) != 0 else r2(0)
    return {
        "processing_cost": processing,
        "hauling_cost": hauling,
        "subtotal_cost": subtotal,
        "surcharge_pct": r2(surcharge_pct),
        "surcharge_cost": surcharge_cost,
        "total_cost": total,
        "cost_per_dry_ton": cost_per_dry_ton,
    }
