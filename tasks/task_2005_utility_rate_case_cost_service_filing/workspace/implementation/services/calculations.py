"""Calculation rules (scaffold 1.3 / PRD 3) — exact integer arithmetic."""
from db import db
from services.core import classes_of_case, sort_rows
from util import round_half_up_signed

DEMAND_PCT_NUM = 60    # 0.60
ENERGY_PCT_NUM = 25    # 0.25
CUSTOMER_PCT_NUM = 15  # 0.15
PCT_DEN = 100

RR_MATCH_TOLERANCE_CENTS = 100
GRADUALISM_FACTOR_NUM = 3  # 1.5
GRADUALISM_FACTOR_DEN = 2
DE_MINIMIS_ABS_CENTS = 100000
DE_MINIMIS_PCT_NUM = 5     # 0.005
DE_MINIMIS_PCT_DEN = 1000


# ---------------------------------------------------------------------------
# tiered marginal pricing (present_revenue_by_class / bill_impact)
# ---------------------------------------------------------------------------

def tiered_marginal_cents(kwh: int, tiers) -> int:
    """Walk tiers ascending (null up_to_kwh terminal, infinite width); each
    tier's width*rate_mills/100 is rounded half-up BEFORE summation."""
    total = 0
    floor_kwh = 0
    for tier in tiers:
        cap = tier["up_to_kwh"]
        if cap is None:
            width = kwh - floor_kwh
        else:
            width = max(0, min(kwh, cap) - floor_kwh)
        if width > 0:
            total += round_half_up_signed(width * tier["rate_mills"], 100)
        if cap is None:
            break
        floor_kwh = cap
        if floor_kwh >= kwh:
            break
    return total


def annual_revenue(customer_count, monthly_kwh_per_customer, charge_cents, tiers):
    monthly = charge_cents + tiered_marginal_cents(monthly_kwh_per_customer, tiers)
    return 12 * customer_count * monthly


# ---------------------------------------------------------------------------
# cost of service / rate base / revenue requirement
# ---------------------------------------------------------------------------

def cost_of_service_total(case_id) -> int:
    return sum(
        e["adjusted_amount_cents"]
        for e in db["test_year_entries"].values()
        if e["rate_case_id"] == case_id and e["status"] == "LOCKED"
    )


def rate_base_total(case_id, statuses) -> int:
    return sum(
        i["net_rate_base_cents"]
        for i in db["rate_base_items"].values()
        if i["rate_case_id"] == case_id and i["status"] in statuses
    )


def revenue_requirement(case, variant: str) -> dict:
    """Pinned evaluation order: COS, then rate base, then rounded return."""
    cos = cost_of_service_total(case["id"])
    statuses = ("SUBMITTED", "AUDITED") if variant == "as_filed" else ("AUDITED",)
    rb = rate_base_total(case["id"], statuses)
    ret = round_half_up_signed(rb * case["return_on_rate_base_bp"], 10000)
    return {
        "variant": variant,
        "rate_base_cents": rb,
        "cost_of_service_cents": cos,
        "return_cents": ret,
        "revenue_requirement_cents": cos + ret,
    }


# ---------------------------------------------------------------------------
# class cost allocation (class_cost_allocation)
# ---------------------------------------------------------------------------

def class_cost_allocation(case, method: str):
    classes = sort_rows(classes_of_case(case["id"]))
    cos = cost_of_service_total(case["id"])
    tot_cp = sum(c["coincident_peak_kw"] for c in classes)
    tot_kwh = sum(c["annual_kwh"] for c in classes)
    tot_cust = sum(c["customer_count"] for c in classes)
    lines = []
    for c in classes:
        if method == "COINCIDENT_PEAK":
            d_num, d_den = c["coincident_peak_kw"], tot_cp
        else:  # ENERGY_AVERAGE
            d_num, d_den = c["annual_kwh"], tot_kwh
        demand = round_half_up_signed(cos * DEMAND_PCT_NUM * d_num, PCT_DEN * d_den) if d_den else 0
        energy = round_half_up_signed(cos * ENERGY_PCT_NUM * c["annual_kwh"], PCT_DEN * tot_kwh) if tot_kwh else 0
        customer = round_half_up_signed(cos * CUSTOMER_PCT_NUM * c["customer_count"], PCT_DEN * tot_cust) if tot_cust else 0
        pre = demand + energy + customer
        lines.append({
            "class_id": c["id"],
            "class_code": c["class_code"],
            "demand_component_cents": demand,
            "energy_component_cents": energy,
            "customer_component_cents": customer,
            "allocated_cost_cents": pre,
            "_pre": pre,
            "_cust": c["customer_count"],
            "_created": c["created_at"],
            "_seq": c["_seq"],
        })
    residual = cos - sum(l["_pre"] for l in lines)
    if lines:
        # residual to the largest pre-residual class; tie: larger customer_count,
        # then earlier created_at
        wi = min(
            range(len(lines)),
            key=lambda i: (-lines[i]["_pre"], -lines[i]["_cust"], lines[i]["_created"], lines[i]["_seq"]),
        )
        lines[wi]["allocated_cost_cents"] = lines[wi]["_pre"] + residual
    for l in lines:
        for k in ("_pre", "_cust", "_created", "_seq"):
            l.pop(k, None)
    return {
        "method": method,
        "cost_of_service_cents": cos,
        "residual_cents": residual,
        "lines": lines,
    }


def customer_cost_floor_cents(case, cls) -> int:
    """Anti-subsidy floor: round_half_up(COS * 0.15 * customer_share)."""
    classes = classes_of_case(case["id"])
    tot_cust = sum(c["customer_count"] for c in classes)
    if tot_cust <= 0:
        return 0
    cos = cost_of_service_total(case["id"])
    return round_half_up_signed(cos * CUSTOMER_PCT_NUM * cls["customer_count"], PCT_DEN * tot_cust)


def gradualism_cap_check(case, cls, proposed_revenue_cents: int):
    """Returns None when the tariff passes; raises ERR_GRADUALISM_CAP_EXCEEDED."""
    from errors import raise_error, ERR_GRADUALISM_CAP_EXCEEDED
    classes = classes_of_case(case["id"])
    present_total = sum(c["present_revenue_cents"] for c in classes)
    if present_total <= 0:
        return
    sys_avg_bp = round_half_up_signed(
        10000 * (case["proposed_revenue_requirement_cents"] - present_total), present_total)
    if sys_avg_bp <= 0:
        return  # revenue-decreasing case: cap check skipped entirely
    cap_bp = round_half_up_signed(GRADUALISM_FACTOR_NUM * sys_avg_bp, GRADUALISM_FACTOR_DEN)
    if cls["present_revenue_cents"] <= 0:
        return
    class_inc_bp = round_half_up_signed(
        10000 * (proposed_revenue_cents - cls["present_revenue_cents"]),
        cls["present_revenue_cents"])
    if class_inc_bp > cap_bp:
        raise_error(ERR_GRADUALISM_CAP_EXCEEDED,
                    f"class increase {class_inc_bp} bp exceeds gradualism cap {cap_bp} bp")


# ---------------------------------------------------------------------------
# amortization schedule (floor base installments, remainder to the tail)
# ---------------------------------------------------------------------------

def amortization_amounts(principal_cents: int, months: int):
    monthly_base = principal_cents // months
    final_month = principal_cents - monthly_base * (months - 1)
    return [monthly_base if i < months else final_month for i in range(1, months + 1)]


# ---------------------------------------------------------------------------
# true-up reconciliation (pinned evaluation order; riders never feed back)
# ---------------------------------------------------------------------------

def compute_true_up(actual_revenue_by_class, authorized_rr_cents: int):
    actual_total = sum(l["actual_revenue_cents"] for l in actual_revenue_by_class)
    delta = actual_total - authorized_rr_cents
    threshold = max(
        DE_MINIMIS_ABS_CENTS,
        round_half_up_signed(authorized_rr_cents * DE_MINIMIS_PCT_NUM, DE_MINIMIS_PCT_DEN),
    )
    if abs(delta) <= threshold:
        action = "NONE"
    else:
        action = "REFUND" if delta > 0 else "SURCHARGE"
    lines = []
    for ln in actual_revenue_by_class:
        if actual_total != 0:
            v = round_half_up_signed(delta * ln["actual_revenue_cents"], actual_total)
        else:
            v = 0
        lines.append({"class_code": ln["class_code"], "line_cents": v})
    residual = delta - sum(l["line_cents"] for l in lines)
    if lines:
        # residual to the largest actual-revenue class; tie: class_code ASC
        wi = min(
            range(len(lines)),
            key=lambda i: (-actual_revenue_by_class[i]["actual_revenue_cents"], lines[i]["class_code"]),
        )
        lines[wi]["line_cents"] += residual
    return {
        "actual_total_revenue_cents": actual_total,
        "true_up_delta_cents": delta,
        "true_up_action": action,
        "class_true_up_lines": lines,
    }
