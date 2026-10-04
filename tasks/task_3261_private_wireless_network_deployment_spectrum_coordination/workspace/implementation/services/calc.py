"""Calculation rules per SCAFFOLD §1.3."""

import math
from decimal import Decimal, ROUND_HALF_UP

from db import DB


CELL_BASE = {"EMBB": 900, "URLLC": 300, "MMTC": 60}
EIRP_REF_DBM = 40
ATT_FULL_LOSS_DB = 30
CELL_COVERAGE_SQM = 5000
COORDINATION_RADIUS_M = 1000
FSPL_CONST_DB = 32.44
NEIGHBOR_RADIUS_M = 500
NEIGHBOR_CAP = 3
NEIGHBOR_PENALTY = Decimal("0.95")

ATTENUATION = {"OPEN": 3, "WOOD": 6, "CONCRETE": 12, "STEEL": 18, "MIXED": 10}

SLA_RATES = {"STANDARD": Decimal("0.05"), "ENHANCED": Decimal("0.10"), "MISSION_CRITICAL": Decimal("0.20")}
MONTHLY_FEE_CENTS = 100000


def round_half_up_int(x):
    """Round a number (Decimal-compatible) half-up to integer."""
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def attenuation_for(material_class):
    return ATTENUATION[material_class]


def _capacity_cells(site_id):
    """Cells counted by capacity formulas: PLANNED or CONFIGURED."""
    return [c for c in DB.cells.values()
            if c["site_id"] == site_id and c["status"] in ("PLANNED", "CONFIGURED")]


def capacity_predicted(site_id, attenuation_db):
    """Provisional capacity: optimistic margin, no neighbor penalty."""
    total = 0
    for c in _capacity_cells(site_id):
        base = CELL_BASE["EMBB"]
        eirp_scale = min(Decimal("1"), Decimal(str(c["max_eirp_dbm"])) / Decimal(EIRP_REF_DBM))
        att_scale = Decimal("1") - Decimal(attenuation_db) / Decimal(ATT_FULL_LOSS_DB)
        contribution = Decimal(base) * eirp_scale * att_scale
        total += round_half_up_int(contribution)
    return total


def _cell_distance_m(a, b):
    sa = DB.sites.get(a["site_id"])
    sb = DB.sites.get(b["site_id"])
    if sa is None or sb is None:
        return float("inf")
    lat1 = float(sa["geo_latitude"]) * math.pi / 180.0
    lon1 = float(sa["geo_longitude"]) * math.pi / 180.0
    lat2 = float(sb["geo_latitude"]) * math.pi / 180.0
    lon2 = float(sb["geo_longitude"]) * math.pi / 180.0
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000.0 * 2 * math.asin(math.sqrt(h))


def _on_air_neighbors(cell, radius_m):
    out = []
    for other in DB.cells.values():
        if other["id"] == cell["id"]:
            continue
        if other["status"] != "ON_AIR":
            continue
        d = _cell_distance_m(cell, other)
        if d <= radius_m:
            out.append((d, other))
    return out


def capacity_final(site_id, attenuation_db):
    """Conservative capacity: 5% multiplicative penalty per ON_AIR neighbor
    within 500m, capped at 3 neighbors. Per-cell round half-up, then sum."""
    total = 0
    for c in _capacity_cells(site_id):
        base = CELL_BASE["EMBB"]
        eirp_scale = min(Decimal("1"), Decimal(str(c["max_eirp_dbm"])) / Decimal(EIRP_REF_DBM))
        att_scale = Decimal("1") - Decimal(attenuation_db) / Decimal(ATT_FULL_LOSS_DB)
        n = min(NEIGHBOR_CAP, len(_on_air_neighbors(c, NEIGHBOR_RADIUS_M)))
        penalty = NEIGHBOR_PENALTY ** n
        contribution = Decimal(base) * eirp_scale * att_scale * penalty
        total += round_half_up_int(contribution)
    return total


def required_cell_count(site_area_sqm, attenuation_db):
    factor = max(0.25, 1.0 - attenuation_db / 30.0)
    effective = CELL_COVERAGE_SQM * factor
    n = math.ceil(float(site_area_sqm) / effective)
    return max(1, n)


def interference_report(site_id, center_frequency_mhz):
    """Interference margins against ON_AIR neighbor cells within 1000 m of any
    PLANNED/CONFIGURED cell of this site. Returns dict with 1-dp margins."""
    own_cells = [c for c in DB.cells.values()
                 if c["site_id"] == site_id and c["status"] in ("PLANNED", "CONFIGURED")]
    margins = []
    seen = set()
    for c in own_cells:
        for d, other in _on_air_neighbors(c, COORDINATION_RADIUS_M):
            if other["id"] in seen:
                continue
            seen.add(other["id"])
            dist = max(d, 1e-6)
            path_loss = 20 * math.log10(dist) + 20 * math.log10(float(center_frequency_mhz)) + FSPL_CONST_DB
            received = other["max_eirp_dbm"] - path_loss
            margin = -received - other.get("interference_margin_db", 6)
            margins.append(margin)
    if not margins:
        worst = 99.0
        aggregate = 99.0
    else:
        worst = min(margins)
        aggregate = sum(margins) / len(margins)
    q = Decimal("0.1")
    worst_r = float(Decimal(str(worst)).quantize(q, rounding=ROUND_HALF_UP))
    agg_r = float(Decimal(str(aggregate)).quantize(q, rounding=ROUND_HALF_UP))
    return {
        "aggregate_margin_db": agg_r,
        "worst_case_margin_db": worst_r,
        "neighbor_cells_checked": len(seen),
    }


def sla_credit_cents(sla_tier):
    return int((Decimal(MONTHLY_FEE_CENTS) * SLA_RATES[sla_tier]).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cell_radius_m(height_m, max_eirp_dbm):
    """Propagation model: heuristic radius from antenna height and EIRP."""
    h = max(float(height_m), 1.0)
    e = float(max_eirp_dbm)
    radius = 100.0 * math.sqrt(h) * (10 ** ((e - 30.0) / 20.0))
    return max(1, round_half_up_int(radius))


def mint_imsi():
    DB.imsi_seq += 1
    return "00101%010d" % DB.imsi_seq


def mint_ki_ref():
    import uuid as _uuid
    return "ki_" + _uuid.uuid4().hex


def mint_sas_id():
    import random, string
    return "SAS-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def recompute_site_utilization(site):
    total = 0
    for a in DB.assignments.values():
        if a["status"] != "ACTIVE":
            continue
        cell = DB.cells.get(a["cell_sector_id"])
        if cell is not None and cell["site_id"] == site["id"]:
            total += a["assigned_bandwidth_mhz"]
    site["spectrum_utilization_mhz"] = total
    return total
