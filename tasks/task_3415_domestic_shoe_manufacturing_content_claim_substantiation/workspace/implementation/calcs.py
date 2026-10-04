"""Calculation rules (scaffold calculations table / PRD 3.2-3.9).

All money math uses Decimal with ROUND_HALF_UP. Rounding order is pinned by
the PRD: per-line extended costs round before summing; percentages compute
last at 2dp; per-pair discounted price rounds before quantity multiplication;
the certified unit cost rounds once, after the surcharge.
"""
from decimal import Decimal, ROUND_HALF_UP

import constants
from errors import ApiError
from state import DB, touch


def D(x):
    return Decimal(str(x))


def rhu_int(x):
    """Round half up to a whole integer."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_2dp(x):
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rhu_1dp(x):
    return D(x).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# fifo_lot_consumption (reserve-materials)
# ---------------------------------------------------------------------------

def _fifo_key(lot):
    # received_at ASC (logical clock), tie-break unit_cost_cents ASC, then
    # creation order for full ties.
    return (lot["received_at"], lot["unit_cost_cents"], lot["_seq"])


def fifo_allocate(run, model):
    """Simulate FIFO consumption against a working copy of lot remaining
    quantities. Returns the consumed_lots entries. Raises the appropriate
    shortage error for the first BOM line that cannot be covered; nothing in
    the store is mutated until apply_consumption runs (atomic reservation)."""
    working = {lid: lot["quantity_remaining"] for lid, lot in DB["lots"].items()}
    entries = []
    for line in model["bom_lines"]:
        required = rhu_int(D(line["quantity_per_pair"]) * D(run["planned_units"]))
        if required <= 0:
            continue
        eligible = [
            lot for lot in DB["lots"].values()
            if lot["component_id"] == line["component_id"]
            and working[lot["id"]] > 0
            and (line["sourcing_requirement"] != "DOMESTIC_REQUIRED" or lot["is_domestic"])
        ]
        if line["sourcing_requirement"] == "DOMESTIC_PREFERRED":
            ordered = sorted([l for l in eligible if l["is_domestic"]], key=_fifo_key) \
                + sorted([l for l in eligible if not l["is_domestic"]], key=_fifo_key)
        else:
            ordered = sorted(eligible, key=_fifo_key)
        need = required
        for lot in ordered:
            if need <= 0:
                break
            take = min(need, working[lot["id"]])
            if take <= 0:
                continue
            working[lot["id"]] -= take
            need -= take
            entries.append({
                "lot_id": lot["id"],
                "component_id": lot["component_id"],
                "units_consumed": take,
                "unit_cost_cents": lot["unit_cost_cents"],
                "is_domestic": lot["is_domestic"],
            })
        if need > 0:
            if line["sourcing_requirement"] == "DOMESTIC_REQUIRED":
                raise ApiError(
                    "ERR_DOMESTIC_MATERIAL_SHORTAGE",
                    "domestic lots cannot cover a DOMESTIC_REQUIRED BOM line",
                )
            raise ApiError(
                "ERR_MATERIAL_SHORTAGE",
                "eligible lots cannot cover a BOM line's required units",
            )
    return entries


def apply_consumption(entries):
    for e in entries:
        lot = DB["lots"][e["lot_id"]]
        lot["quantity_remaining"] -= e["units_consumed"]
        touch(lot)


def release_consumption(run):
    """Compensating release: re-credit every consumed entry, clear the list."""
    for e in run["consumed_lots"]:
        lot = DB["lots"].get(e["lot_id"])
        if lot is not None:
            lot["quantity_remaining"] += e["units_consumed"]
            touch(lot)
    run["consumed_lots"] = []


# ---------------------------------------------------------------------------
# workforce headcount + skill_coverage_score
# ---------------------------------------------------------------------------

def workforce_shortfall(factory_id):
    """Return the operations below the required ACTIVE+CERTIFIED headcount."""
    short = []
    for op in constants.OPERATIONS:
        count = sum(
            1 for w in DB["workers"].values()
            if w["factory_id"] == factory_id and w["status"] == "ACTIVE"
            and any(c["operation"] == op and c["cert_status"] == "CERTIFIED"
                    for c in w["certifications"])
        )
        if count < constants.REQUIRED_WORKERS_PER_RUN[op]:
            short.append(op)
    return short


def skill_coverage(factory):
    """Return (skill_coverage_certified_pct, skill_coverage_pipeline_pct)."""
    in_prod = sum(
        1 for r in DB["runs"].values()
        if r["factory_id"] == factory["id"] and r["status"] == "IN_PRODUCTION"
    )
    cov_cert = {}
    cov_pipe = {}
    for op in constants.OPERATIONS:
        required = constants.REQUIRED_WORKERS_PER_RUN[op] * in_prod
        if required == 0:
            cov_cert[op] = 100
            cov_pipe[op] = 100
            continue
        active_workers = [
            w for w in DB["workers"].values()
            if w["factory_id"] == factory["id"] and w["status"] == "ACTIVE"
        ]
        certified = sum(
            1 for w in active_workers
            if any(c["operation"] == op and c["cert_status"] == "CERTIFIED"
                   for c in w["certifications"])
        )
        pipeline = sum(
            1 for w in active_workers
            if any(e["worker_id"] == w["id"] and e["operation"] == op
                   and e["status"] in ("ENROLLED", "REMEDIATION")
                   for e in DB["enrollments"].values())
        )
        avail_cert = D(certified)
        avail_pipe = D(certified) + constants.PIPELINE_CREDIT * D(pipeline)
        cov_cert[op] = min(100, rhu_int(D(100) * avail_cert / D(required)))
        cov_pipe[op] = min(100, rhu_int(D(100) * avail_pipe / D(required)))
    score_cert = rhu_1dp(sum(D(cov_cert[op]) * constants.OP_WEIGHTS[op]
                             for op in constants.OPERATIONS))
    score_pipe = rhu_1dp(sum(D(cov_pipe[op]) * constants.OP_WEIGHTS[op]
                             for op in constants.OPERATIONS))
    return float(score_cert), float(score_pipe)


# ---------------------------------------------------------------------------
# content_calculation (PROVISIONAL / CERTIFIED, with recompute overrides)
# ---------------------------------------------------------------------------

def compute_report_fields(run, variant, lot_overrides=frozenset(), labor_disputed=False):
    model = DB["models"][run["model_id"]]
    factory = DB["factories"][run["factory_id"]]
    if variant == "PROVISIONAL":
        material = 0
        domestic_material = 0
        for line in model["bom_lines"]:
            # Per-line extended cost rounds half up to integer cents BEFORE summing.
            line_cost = rhu_int(D(line["quantity_per_pair"]) * D(line["planned_unit_cost_cents"]))
            material += line_cost
            if line["planned_is_domestic"]:
                domestic_material += line_cost
        total_minutes = (model["standard_stitching_minutes"]
                         + model["standard_lasting_minutes"]
                         + model["standard_assembly_minutes"])
    else:  # CERTIFIED
        total_actual = sum(e["units_consumed"] * e["unit_cost_cents"]
                           for e in run["consumed_lots"])
        domestic_actual = sum(
            e["units_consumed"] * e["unit_cost_cents"] for e in run["consumed_lots"]
            if e["is_domestic"] and e["lot_id"] not in lot_overrides
        )
        material = rhu_int(D(total_actual) / D(run["planned_units"]))
        domestic_material = rhu_int(D(domestic_actual) / D(run["planned_units"]))
        total_minutes = (run["actual_stitching_minutes"]
                         + run["actual_lasting_minutes"]
                         + run["actual_assembly_minutes"])
    labor = total_minutes * factory["labor_rate_cents_per_minute"]
    overhead = factory["overhead_cents_per_pair"]
    total_cost = material + labor + overhead
    if factory["location_type"] == "DOMESTIC" and not labor_disputed:
        domestic_value = domestic_material + labor + overhead
    else:
        domestic_value = domestic_material
    # Percentage computed last, from the already-rounded components, at 2dp.
    pct = rhu_2dp(D(100 * domestic_value) / D(total_cost)) if total_cost != 0 else Decimal("0.00")
    return {
        "material_cost_cents": material,
        "domestic_material_cost_cents": domestic_material,
        "labor_cost_cents": labor,
        "overhead_cost_cents": overhead,
        "domestic_value_cents": domestic_value,
        "total_cost_cents": total_cost,
        "us_content_pct": float(pct),
        "final_assembly_domestic": factory["location_type"] == "DOMESTIC",
    }


# ---------------------------------------------------------------------------
# run_unit_cost (complete): tiered small-batch surcharge, single rounding
# ---------------------------------------------------------------------------

def run_unit_cost(run):
    factory = DB["factories"][run["factory_id"]]
    total_actual = sum(e["units_consumed"] * e["unit_cost_cents"]
                       for e in run["consumed_lots"])
    material = rhu_int(D(total_actual) / D(run["planned_units"]))
    minutes = (run["actual_stitching_minutes"]
               + run["actual_lasting_minutes"]
               + run["actual_assembly_minutes"])
    base = (material
            + minutes * factory["labor_rate_cents_per_minute"]
            + factory["overhead_cents_per_pair"])
    if run["run_type"] == "GOVERNMENT":
        surcharge = constants.GOVERNMENT_PCT
    else:
        units = run["planned_units"]
        if units < constants.TIER_1_MAX_UNITS:
            surcharge = constants.TIER_1_PCT
        elif units < constants.TIER_2_MAX_UNITS:
            surcharge = constants.TIER_2_PCT
        elif units < constants.TIER_3_MAX_UNITS:
            surcharge = constants.TIER_3_PCT
        else:
            surcharge = Decimal("0")
        if run["run_type"] == "CUSTOM_BATCH":
            surcharge += constants.CUSTOM_BATCH_EXTRA_PCT
    return rhu_int(D(base) * (Decimal("1") + surcharge))


# ---------------------------------------------------------------------------
# custom_order_price (accept): tier keyed on PRE-discount subtotal;
# per-pair rounding BEFORE multiplying by quantity_units.
# ---------------------------------------------------------------------------

def custom_order_price(order, model):
    if model["domestic_price_cents"] is not None:
        base = model["domestic_price_cents"]
    else:
        base = rhu_int(D(model["base_price_cents"]) * constants.CUSTOM_FALLBACK_MARKUP)
    fees = 0
    if order.get("monogram"):
        fees += constants.MONOGRAM_FEE_CENTS
    if order["colorway"] != "STD":
        fees += constants.COLORWAY_FEE_CENTS
    subtotal = base + fees
    if subtotal >= constants.DISCOUNT_TIER_1_MIN_CENTS:
        discount = constants.DISCOUNT_TIER_1_PCT
    elif subtotal >= constants.DISCOUNT_TIER_2_MIN_CENTS:
        discount = constants.DISCOUNT_TIER_2_PCT
    else:
        discount = Decimal("0")
    per_pair = rhu_int(D(subtotal) * (Decimal("1") - discount))
    return per_pair * order["quantity_units"]


# ---------------------------------------------------------------------------
# capacity_waterfall (lock): GOVERNMENT -> CUSTOM_BATCH -> STOCK buckets
# ---------------------------------------------------------------------------

def capacity_waterfall(allocation):
    factory = DB["factories"][allocation["factory_id"]]
    if factory["location_type"] == "OVERSEAS":
        domestic = 0
    else:
        runs = [
            r for r in DB["runs"].values()
            if r["factory_id"] == allocation["factory_id"]
            and r["iso_week"] == allocation["iso_week"]
            and r["status"] in ("PLANNED", "MATERIAL_RESERVED")
        ]
        demand = {b: sum(r["planned_units"] for r in runs if r["run_type"] == b)
                  for b in constants.BUCKET_ORDER}
        remaining = allocation["total_reserved_units"]
        domestic = 0
        for bucket in constants.BUCKET_ORDER:
            take = min(remaining, demand[bucket])
            domestic += take
            remaining -= take
    allocation["domestic_reserved_units"] = domestic
    allocation["import_reserved_units"] = allocation["total_reserved_units"] - domestic


# ---------------------------------------------------------------------------
# cost_differential_pricing (CERTIFIED report on a DOMESTIC run, event-driven)
# ---------------------------------------------------------------------------

def refresh_model_pricing(report):
    run = DB["runs"][report["run_id"]]
    factory = DB["factories"][run["factory_id"]]
    if report["variant"] != "CERTIFIED" or factory["location_type"] != "DOMESTIC":
        return
    model = DB["models"][run["model_id"]]
    model["domestic_unit_cost_cents"] = report["total_cost_cents"]
    model["domestic_price_cents"] = rhu_int(
        D(model["base_price_cents"]) * D(report["total_cost_cents"])
        / D(model["import_cost_basis_cents"])
    )
    touch(model)


# ---------------------------------------------------------------------------
# claim_threshold_check (inclusive thresholds on the stored 2dp percentage)
# ---------------------------------------------------------------------------

def claim_threshold_pass(claim_type, us_content_pct, final_assembly_domestic):
    pct = D(us_content_pct)
    if claim_type == "MADE_IN_USA":
        return final_assembly_domestic and pct >= constants.MADE_IN_USA_MIN_PCT
    if claim_type == "MADE_IN_USA_OF_IMPORTED_MATERIALS":
        return final_assembly_domestic and pct >= constants.MADE_IN_USA_OF_IMPORTED_MIN_PCT
    if claim_type == "ASSEMBLED_IN_USA":
        return final_assembly_domestic and pct >= constants.ASSEMBLED_IN_USA_MIN_PCT
    if claim_type == "IMPORTED":
        return (not final_assembly_domestic) or pct < constants.ASSEMBLED_IN_USA_MIN_PCT
    return False
