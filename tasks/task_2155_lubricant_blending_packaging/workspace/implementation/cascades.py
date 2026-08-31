"""Shared side-effect machinery: cascade A, cascade B, derived counters, pricing."""
from decimal import Decimal

import calc
import store
from core import D, now, rhu


# --------------------------------------------------------------------------
# Derived counters
# --------------------------------------------------------------------------
def refresh_retain_count(batch):
    batch["retain_count"] = len([
        r for r in store.where("RetainSample", blend_batch_id=batch["id"])
        if r["status"] == "HELD"])
    return batch["retain_count"]


def refresh_scheduled_run_count(line):
    line["scheduled_run_count"] = len([
        r for r in store.where("PackagingRun", packaging_line_id=line["id"])
        if r["status"] in ("SCHEDULED", "RUNNING")])
    return line["scheduled_run_count"]


def refresh_component_count(recipe):
    recipe["component_count"] = len(calc.recipe_components(recipe["id"]))
    return recipe["component_count"]


# --------------------------------------------------------------------------
# Cascade A - links 3 and 4
# --------------------------------------------------------------------------
def hold_lines_for_config(config):
    """Cascade A link 4: OPEN lines quoting a de-activated configuration go HOLD."""
    for line in store.where("OrderLine", package_configuration_id=config["id"]):
        if line["status"] != "OPEN":
            continue
        line["status"] = "HOLD"
        store.touch(line)
        order = store.get("Order", line["order_id"])
        if order is not None and order["status"] == "CONFIRMED":
            order["status"] = "HOLD"
            order["hold_reason"] = "CLAIM_BLOCKED_LINE"
            store.touch(order)


def block_configs_for_claim(claim):
    """Cascade A link 3: ACTIVE configurations printing this claim code go CLAIM_BLOCKED."""
    for config in store.where("PackageConfiguration",
                              product_spec_id=claim["product_spec_id"]):
        if config["status"] != "ACTIVE":
            continue
        if claim["claim_code"] not in (config["claim_codes"] or []):
            continue
        config["status"] = "CLAIM_BLOCKED"
        store.touch(config)
        hold_lines_for_config(config)


def supersede_configs(new_config):
    """A newly activated configuration displaces the current one on the same triple."""
    for config in store.all_rows("PackageConfiguration"):
        if config["id"] == new_config["id"]:
            continue
        if config["status"] != "ACTIVE":
            continue
        if (config["product_spec_id"] != new_config["product_spec_id"]
                or config["package_type"] != new_config["package_type"]
                or config["customer_id"] != new_config["customer_id"]):
            continue
        config["status"] = "SUPERSEDED"
        config["superseded_by_id"] = new_config["id"]
        store.touch(config)
        hold_lines_for_config(config)


def unblock_configs_for_spec(spec_id):
    """ApprovalClaim SUBMITTED -> ACTIVE repairs whole claim sets."""
    active_codes = set(
        c["claim_code"] for c in store.where("ApprovalClaim", product_spec_id=spec_id)
        if c["status"] == "ACTIVE")
    for config in store.where("PackageConfiguration", product_spec_id=spec_id):
        if config["status"] != "CLAIM_BLOCKED":
            continue
        codes = config["claim_codes"] or []
        if all(code in active_codes for code in codes):
            config["status"] = "ACTIVE"
            store.touch(config)


def suspend_claim(claim, reason):
    """ACTIVE -> SUSPENDED plus link 3/4."""
    claim["status"] = "SUSPENDED"
    claim["requires_recertification"] = True
    claim["suspension_reason"] = reason
    store.touch(claim)
    block_configs_for_claim(claim)


# --------------------------------------------------------------------------
# Cascade A - full run from a spec revision advance
# --------------------------------------------------------------------------
def spec_revision_advanced(spec):
    """Links 2 through 5 after ProductSpec.revision has been bumped."""
    for claim in store.where("ApprovalClaim", product_spec_id=spec["id"]):
        pinned = claim["pinned_spec_revision"]
        if claim["status"] == "ACTIVE" and pinned is not None and pinned < spec["revision"]:
            suspend_claim(claim, "SPEC_REVISION_ADVANCED")
    for recipe in store.where("BlendRecipe", product_spec_id=spec["id"]):
        if (recipe["status"] == "ACTIVE"
                and recipe["spec_revision_pinned"] < spec["revision"]):
            recipe["status"] = "RETIRED"
            store.touch(recipe)


# --------------------------------------------------------------------------
# Cascade B - batch quarantine
# --------------------------------------------------------------------------
def cascade_b(batch, quarantine_tank):
    """Links 2, 3 and (conditionally) 4."""
    for run in store.where("PackagingRun", blend_batch_id=batch["id"]):
        if run["status"] not in ("SCHEDULED", "RUNNING"):
            continue
        run["status"] = "CANCELLED"
        run["cancel_reason"] = "BATCH_QUARANTINED"
        store.touch(run)
        line = store.get("PackagingLine", run["packaging_line_id"])
        if line is not None:
            refresh_scheduled_run_count(line)
    if quarantine_tank and batch["blend_tank_id"]:
        tank = store.get("BlendTank", batch["blend_tank_id"])
        if tank is not None and tank["status"] == "CHARGED":
            tank["status"] = "QUARANTINED"
            store.touch(tank)


# --------------------------------------------------------------------------
# Order pricing waterfall
# --------------------------------------------------------------------------
def order_lines(order_id):
    rows = store.where("OrderLine", order_id=order_id)
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def compute_totals(order, open_line_ids=None, run_credit_step=False):
    """Steps 1-3, optionally 4, then 5 - computed without mutating anything."""
    customer = store.get("Customer", order["customer_id"])
    priced = []
    subtotal = 0
    volume = Decimal(0)
    for line in order_lines(order["id"]):
        included = (line["id"] in open_line_ids) if open_line_ids is not None \
            else (line["status"] == "OPEN")
        if not included:
            continue
        config = store.get("PackageConfiguration", line["package_configuration_id"])
        if config is None or customer is None:
            continue
        rate = calc.line_rate(config, customer)
        volume_l = rhu(D(line["quantity_units"]) * D(config["fill_volume_l"]), 2)
        line_total = calc.rhu_int_public(D(volume_l) * rate)
        unit_price = calc.rhu_int_public(D(config["fill_volume_l"]) * rate)
        priced.append((line, volume_l, line_total, unit_price))
        subtotal += line_total
        volume += volume_l
    total_volume = rhu(volume, 2)
    freight = calc.freight_cents(order, subtotal, total_volume)
    pre_credit = subtotal + freight
    applied = order["takeback_credit_applied_cents"]
    if run_credit_step:
        if not order["takeback_linked"] or customer is None:
            applied = 0
        else:
            applied = min(customer["takeback_credit_balance_cents"],
                          calc.credit_cap(pre_credit))
    return {
        "priced": priced,
        "subtotal_cents": subtotal,
        "total_volume_l": total_volume,
        "freight_surcharge_cents": freight,
        "pre_credit_total_cents": pre_credit,
        "takeback_credit_applied_cents": applied,
        "total_cents": pre_credit - applied,
    }


def commit_totals(order, result):
    for line, volume_l, line_total, unit_price in result["priced"]:
        line["volume_l"] = volume_l
        line["line_total_cents"] = line_total
        line["unit_price_cents"] = unit_price
    order["subtotal_cents"] = result["subtotal_cents"]
    order["total_volume_l"] = result["total_volume_l"]
    order["freight_surcharge_cents"] = result["freight_surcharge_cents"]
    order["pre_credit_total_cents"] = result["pre_credit_total_cents"]
    order["takeback_credit_applied_cents"] = result["takeback_credit_applied_cents"]
    order["total_cents"] = result["total_cents"]
    return order


def recompute_line_totals_only(order):
    """Step 1 only - used when a line is added to a DRAFT order."""
    subtotal = 0
    volume = Decimal(0)
    for line in order_lines(order["id"]):
        if line["status"] != "OPEN":
            continue
        subtotal += line["line_total_cents"]
        volume += D(line["volume_l"])
    order["subtotal_cents"] = subtotal
    order["total_volume_l"] = rhu(volume, 2)
    return order


def refresh_customer_balance(customer, stamp_event):
    customer["takeback_credit_balance_cents"] = calc.customer_balance(customer["id"])
    if stamp_event:
        customer["last_credit_event_at"] = now()
    store.touch(customer)
