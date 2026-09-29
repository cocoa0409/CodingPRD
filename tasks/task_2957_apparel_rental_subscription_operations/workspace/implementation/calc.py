"""The fourteen calculation rules and every computed field derivation."""
from datetime import timedelta
from decimal import Decimal

import core
from core import (BAND_ELEVATED_MAX, BAND_LOW_MAX, CHANNEL_FEE_PCT,
                  CHANNEL_HANDLING_CENTS, CLEANING_COST_CENTS, DAYS_PER_PLANNING_MONTH,
                  DB, FIT_BASELINE, FIT_DELTA, KEEP_INTENT_BONUS, LATE_FEE_CAP_CENTS,
                  LATE_FEE_PER_DAY_CENTS, MARKDOWN_STEP_PCT, MIN_NET_RECOVERY_CENTS,
                  PHOTOGRAPHY_COST_CENTS, PROJECTED_SERVICING_PER_TURN_CENTS,
                  RECONDITION_BUFFER_DAYS, REFERENCE_REVENUE_PER_TURN_CENTS,
                  REPAIR_COST_CENTS, REPLENISH_TRIGGER_UNITS, RESALE_RATE_BY_GRADE,
                  RESIDUAL_RATE_BY_GRADE, RETURN_GRACE_DAYS, SEVERITY_BASE_CENTS,
                  SEVERITY_PCT, SEVERITY_WEIGHT, TIER_HIGH_FLOOR_CENTS,
                  TIER_MID_FLOOR_CENTS, W_CLAIM_RATE, W_LATE, W_SEVERITY,
                  ceil_div, date_add, date_diff, rhu)

HOLDING_STATES_EXCLUDED = {"RELEASED", "CANCELLED", "SUPERSEDED"}
UNITS_OUT_STATES = {"MATCHED", "SHIPPED", "IN_POSSESSION", "RETURN_INITIATED"}
INACTIVE_UNIT_STATES = {"RETIRED", "SOLD"}


# ---------------------------------------------------------------------------
# Small query helpers
# ---------------------------------------------------------------------------
def units_of_style(style_id):
    return [u for u in DB["rental_units"].values() if u["style_id"] == style_id]


def reservations_of_member(member_id):
    return [r for r in DB["reservations"].values() if r["member_id"] == member_id]


def reservations_of_style(style_id):
    return [r for r in DB["reservations"].values() if r["style_id"] == style_id]


def reservations_holding_unit(unit_id):
    return [r for r in DB["reservations"].values()
            if r["allocated_unit_id"] == unit_id
            and r["state"] not in HOLDING_STATES_EXCLUDED]


def jobs_of_unit(unit_id):
    return [j for j in DB["reverse_logistics_jobs"].values()
            if j["rental_unit_id"] == unit_id]


def inspections_of_job(job_id):
    rows = [i for i in DB["inspections"].values() if i["job_id"] == job_id]
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def feedback_of_member(member_id):
    return [f for f in DB["fit_feedbacks"].values() if f["member_id"] == member_id]


def feedback_of_style(style_id):
    return [f for f in DB["fit_feedbacks"].values() if f["style_id"] == style_id]


def claims_of_member(member_id):
    return [c for c in DB["damage_claims"].values() if c["member_id"] == member_id]


def ledger_of_member(member_id):
    rows = [e for e in DB["fee_ledger_entries"].values() if e["member_id"] == member_id]
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def listings_of_unit(unit_id):
    return [l for l in DB["resale_listings"].values() if l["rental_unit_id"] == unit_id]


# ---------------------------------------------------------------------------
# 1. availability_match_selector
# ---------------------------------------------------------------------------
def interval_collision(unit_id, start, end, ignore_reservation_id=None):
    for r in reservations_holding_unit(unit_id):
        if ignore_reservation_id is not None and r["id"] == ignore_reservation_id:
            continue
        buffered_end = date_add(r["requested_end_date"], RECONDITION_BUFFER_DAYS)
        if start < buffered_end and end > r["requested_start_date"]:
            return True
    return False


def unit_base_eligible(unit, style, size, freed_unit_id=None):
    avail_ok = unit["availability_state"] == "IN_STOCK" or (
        freed_unit_id is not None and unit["id"] == freed_unit_id
        and unit["availability_state"] == "RESERVED")
    return (unit["style_id"] == style["id"]
            and unit["size"] == size
            and avail_ok
            and unit["condition_state"] == "FLOOR_READY"
            and not unit["quarantine_hold"]
            and unit["turns_completed"] < style["expected_rental_turns_per_unit"])


def candidate_units(style, size, start, end, ignore_reservation_id=None,
                    freed_unit_id=None):
    out = []
    for unit in units_of_style(style["id"]):
        if not unit_base_eligible(unit, style, size, freed_unit_id):
            continue
        if interval_collision(unit["id"], start, end, ignore_reservation_id):
            continue
        out.append(unit)
    return out


def rank_candidates(candidates):
    """turns_completed DESC, then created_at ASC. id is never a tie-breaker."""
    return sorted(candidates,
                  key=lambda u: (-u["turns_completed"], u["created_at"], u["_seq"]))


# ---------------------------------------------------------------------------
# 2. style_depth_requirement
# ---------------------------------------------------------------------------
def style_depth(style):
    units = units_of_style(style["id"])
    floor_ready = 0
    active = 0
    for u in units:
        if u["availability_state"] not in INACTIVE_UNIT_STATES:
            active += 1
        if (u["availability_state"] == "IN_STOCK"
                and u["condition_state"] == "FLOOR_READY"):
            floor_ready += 1
    committed_days = style["forecast_monthly_requests"] * (style["avg_rental_days"]
                                                           + RECONDITION_BUFFER_DAYS)
    required = ceil_div(committed_days, DAYS_PER_PLANNING_MONTH)
    gap = max(0, required - active)
    return {
        "floor_ready_unit_count": floor_ready,
        "active_unit_count": active,
        "required_depth_units": required,
        "depth_gap_units": gap,
        "replenishment_flag": gap >= REPLENISH_TRIGGER_UNITS,
    }


# ---------------------------------------------------------------------------
# 3. style_demand_score
# ---------------------------------------------------------------------------
def style_demand_score(style):
    total = 0
    for r in reservations_of_style(style["id"]):
        if r["state"] != "SUPERSEDED":
            total += 4
    for f in feedback_of_style(style["id"]):
        if f["keep_intent"]:
            total += 3
        total += f["occasion_match_score"]
    return min(100, total)


# ---------------------------------------------------------------------------
# 4. member_fit_confidence
# ---------------------------------------------------------------------------
def member_fit_confidence(member_id):
    rows = feedback_of_member(member_id)
    raw = FIT_BASELINE
    for f in rows:
        raw += 6 * (f["occasion_match_score"] - 3)
        if f["keep_intent"]:
            raw += KEEP_INTENT_BONUS
        raw -= 8 * abs(FIT_DELTA[f["fit_rating"]])
    return max(0, min(100, raw))


def personalization(member):
    rows = feedback_of_member(member["id"])
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    counts = {}
    earliest = {}
    keep = 0
    for f in rows:
        counts[f["fit_rating"]] = counts.get(f["fit_rating"], 0) + 1
        if f["fit_rating"] not in earliest:
            earliest[f["fit_rating"]] = (f["created_at"], f["_seq"])
        if f["keep_intent"]:
            keep += 1
    dominant = None
    if counts:
        top = max(counts.values())
        tied = [k for k, v in counts.items() if v == top]
        dominant = min(tied, key=lambda k: earliest[k])
    return {
        "member_id": member["id"],
        "fit_confidence_score": member_fit_confidence(member["id"]),
        "feedback_count": len(rows),
        "keep_intent_count": keep,
        "dominant_fit_rating": dominant,
        "preferred_categories": list(member["preferred_categories"]),
        "size_profile": member["size_profile"],
    }


# ---------------------------------------------------------------------------
# 5. member_damage_risk_score
# ---------------------------------------------------------------------------
def damage_risk(member, variant="LIFETIME"):
    scope = []
    for r in reservations_of_member(member["id"]):
        if r["state"] != "CLOSED":
            continue
        if variant == "ROLLING_12M":
            returned = r.get("returned_at")
            if not returned:
                continue
            dt = core.parse_instant(returned)
            lower = core.now_dt() - timedelta(days=365)
            if not (lower <= dt < core.now_dt()):
                continue
        scope.append(r)
    scope_ids = set(r["id"] for r in scope)
    claims = [c for c in claims_of_member(member["id"])
              if c["reservation_id"] in scope_ids and c["state"] in ("CHARGED", "WAIVED")]
    late_count = sum(1 for r in scope if r["late_days"] > 0)

    n = max(1, len(scope))
    claim_rate = Decimal(len(claims)) / Decimal(n)
    severity_points = sum(SEVERITY_WEIGHT[c["severity"]] for c in claims)
    severity_index = Decimal(severity_points) / Decimal(max(1, len(claims)))
    late_rate = Decimal(late_count) / Decimal(n)
    capped_severity = min(Decimal("1.0"), severity_index / Decimal("4.0"))
    raw = Decimal(100) * (W_CLAIM_RATE * claim_rate
                          + W_SEVERITY * capped_severity
                          + W_LATE * late_rate)
    score = rhu(raw)
    if score <= BAND_LOW_MAX:
        band = "LOW"
    elif score <= BAND_ELEVATED_MAX:
        band = "ELEVATED"
    else:
        band = "HIGH"
    return {
        "member_id": member["id"],
        "variant": variant,
        "closed_reservation_count": len(scope),
        "claim_count": len(claims),
        "severity_points": severity_points,
        "late_return_count": late_count,
        "damage_risk_score": score,
        "damage_risk_band": band,
    }


# ---------------------------------------------------------------------------
# 6. damage_fee_assessment
# ---------------------------------------------------------------------------
def damage_fee(style, unit, severity, member, plan, coverage_used):
    residual = rhu(Decimal(style["retail_price_cents"])
                   * RESIDUAL_RATE_BY_GRADE[unit["condition_grade"]])
    if severity == "LOSS":
        severity_base = residual
    else:
        severity_base = SEVERITY_BASE_CENTS[severity]
    pct_component = rhu(Decimal(residual) * SEVERITY_PCT[severity])
    gross = min(max(severity_base, pct_component), residual)
    remaining = max(0, plan["waiver_coverage_cents"] - coverage_used)
    waiver_applied = min(gross, remaining) if member["waiver_active"] else 0
    return {
        "residual_value_cents": residual,
        "gross_fee_cents": gross,
        "waiver_applied_cents": waiver_applied,
        "net_fee_cents": gross - waiver_applied,
    }


DOWNGRADE = {"LOSS": "SEVERE", "SEVERE": "MODERATE", "MODERATE": "MINOR", "MINOR": "MINOR"}


# ---------------------------------------------------------------------------
# 7. resale_pricing
# ---------------------------------------------------------------------------
def price_tier(base_price_cents):
    if base_price_cents < TIER_MID_FLOOR_CENTS:
        return "LOW"
    if base_price_cents < TIER_HIGH_FLOOR_CENTS:
        return "MID"
    return "HIGH"


def resale_pricing(style, unit, channel, markdown_step):
    # Step 1
    base = rhu(Decimal(style["retail_price_cents"])
               * RESALE_RATE_BY_GRADE[unit["condition_grade"]]
               * (Decimal(1) - MARKDOWN_STEP_PCT * Decimal(markdown_step)))
    # Step 2 — tier frozen from base_price, never re-derived
    tier = price_tier(base)
    # Step 3
    fee_pct = CHANNEL_FEE_PCT[channel][tier]
    handling = CHANNEL_HANDLING_CENTS[channel]
    # Step 4/5
    channel_fee = rhu(Decimal(base) * fee_pct)
    provisional_net = base - channel_fee - handling
    # Step 6 — at most one corrective pass
    if provisional_net < MIN_NET_RECOVERY_CENTS:
        list_price = rhu((Decimal(MIN_NET_RECOVERY_CENTS) + Decimal(handling))
                         / (Decimal(1) - fee_pct))
        floor_adjusted = True
    else:
        list_price = base
        floor_adjusted = False
    # Step 7
    channel_fee = rhu(Decimal(list_price) * fee_pct)
    net_recovery = list_price - channel_fee - handling
    return {
        "base_price_cents": base,
        "list_price_cents": list_price,
        "channel_fee_cents": channel_fee,
        "net_recovery_cents": net_recovery,
        "floor_adjusted": floor_adjusted,
        "tier": tier,
        "fee_pct": fee_pct,
    }


def resale_sale_math(channel, fee_pct, sale_price_cents):
    handling = CHANNEL_HANDLING_CENTS[channel]
    channel_fee = rhu(Decimal(sale_price_cents) * fee_pct)
    return {
        "channel_fee_cents": channel_fee,
        "net_recovery_cents": sale_price_cents - channel_fee - handling,
    }


# ---------------------------------------------------------------------------
# 8. turn_revenue_attribution
# ---------------------------------------------------------------------------
def turn_revenue(plan, is_swap):
    base = rhu(Decimal(plan["monthly_fee_cents"]) / Decimal(plan["item_slots"]))
    if is_swap:
        return rhu(Decimal(base) / Decimal(2))
    return base


# ---------------------------------------------------------------------------
# 9. servicing_cost_rollup
# ---------------------------------------------------------------------------
def servicing_cost(job):
    inspections = inspections_of_job(job["id"])
    if inspections:
        newest = max(inspections, key=lambda i: i["attempt_index"])
        soil = newest["soil_level"]
        damage = newest["damage_severity"]
    else:
        soil = "NONE"
        damage = "NONE"
    cleaning = CLEANING_COST_CENTS[soil] if job["cleaning_required"] else 0
    repair = REPAIR_COST_CENTS[damage] * max(0, job["repair_attempts"])
    photo = PHOTOGRAPHY_COST_CENTS if job["photographed_at"] else 0
    return cleaning + repair + photo


def unit_cumulative_servicing(unit_id):
    total = 0
    for job in jobs_of_unit(unit_id):
        if job["state"] == "RESTOCKED":
            total += servicing_cost(job)
    return total


# ---------------------------------------------------------------------------
# 10. late_return_fee
# ---------------------------------------------------------------------------
def late_return_fee(reservation, received_date):
    due = date_add(reservation["requested_end_date"], RETURN_GRACE_DAYS)
    late_days = max(0, date_diff(received_date, due))
    fee = min(LATE_FEE_CAP_CENTS, late_days * LATE_FEE_PER_DAY_CENTS)
    return late_days, fee


# ---------------------------------------------------------------------------
# 11. swap_allowance_window
# ---------------------------------------------------------------------------
def swaps_used_current_month(member_id):
    now = core.now_dt()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 12:
        next_start = month_start.replace(year=now.year + 1, month=1)
    else:
        next_start = month_start.replace(month=now.month + 1)
    count = 0
    for r in reservations_of_member(member_id):
        if not r["is_swap"]:
            continue
        created = core.parse_instant(r["created_at"])
        if month_start <= created < next_start:
            count += 1
    return count


# ---------------------------------------------------------------------------
# 12/13. ledger balance + member computed money
# ---------------------------------------------------------------------------
def member_outstanding(member_id):
    total = 0
    for e in ledger_of_member(member_id):
        total += e["amount_cents"]
    return total


def member_waiver_used(member_id):
    total = 0
    for c in claims_of_member(member_id):
        if c["state"] in ("ASSESSED", "DISPUTED", "CHARGED", "WAIVED"):
            total += c["waiver_applied_cents"] or 0
    return total


def member_units_out(member_id):
    return sum(1 for r in reservations_of_member(member_id)
               if r["state"] in UNITS_OUT_STATES)


def member_waitlisted(member_id):
    return sum(1 for r in reservations_of_member(member_id)
               if r["state"] == "WAITLISTED")


def member_late_return_count(member_id):
    return sum(1 for r in reservations_of_member(member_id) if r["late_days"] > 0)


# ---------------------------------------------------------------------------
# 14. unit_economics
# ---------------------------------------------------------------------------
def unit_economics(style, variant="REALIZED"):
    if variant == "PROJECTED":
        turns = style["expected_rental_turns_per_unit"]
        revenue = REFERENCE_REVENUE_PER_TURN_CENTS * turns
        servicing = PROJECTED_SERVICING_PER_TURN_CENTS * turns
        eol = style["planned_eol_value_cents"]
        margin = revenue + eol - style["acquisition_cost_cents"] - servicing
        return {
            "style_id": style["id"],
            "variant": variant,
            "unit_count": 1,
            "avg_acquisition_cost_cents": style["acquisition_cost_cents"],
            "avg_revenue_per_unit_cents": revenue,
            "avg_servicing_cost_per_unit_cents": servicing,
            "avg_eol_value_cents": eol,
            "avg_margin_per_unit_cents": margin,
            "avg_margin_per_turn_cents": rhu(Decimal(margin) / Decimal(max(1, turns))),
        }

    units = units_of_style(style["id"])
    n = len(units)
    if n == 0:
        return {
            "style_id": style["id"],
            "variant": variant,
            "unit_count": 0,
            "avg_acquisition_cost_cents": 0,
            "avg_revenue_per_unit_cents": 0,
            "avg_servicing_cost_per_unit_cents": 0,
            "avg_eol_value_cents": 0,
            "avg_margin_per_unit_cents": 0,
            "avg_margin_per_turn_cents": 0,
        }
    sum_acq = 0
    sum_rev = 0
    sum_serv = 0
    sum_eol = 0
    sum_margin = 0
    sum_mpt = 0
    for u in units:
        revenue = unit_realized_revenue(u["id"])
        recovery = 0
        for c in DB["damage_claims"].values():
            if c["rental_unit_id"] == u["id"] and c["state"] == "CHARGED":
                recovery += c["net_fee_cents"] or 0
        eol = 0
        for l in listings_of_unit(u["id"]):
            if l["state"] == "SOLD":
                eol += l["net_recovery_cents"] or 0
        servicing = unit_cumulative_servicing(u["id"])
        margin = (revenue + recovery + eol - u["acquisition_cost_cents"] - servicing)
        sum_acq += u["acquisition_cost_cents"]
        sum_rev += revenue + recovery
        sum_serv += servicing
        sum_eol += eol
        sum_margin += margin
        sum_mpt += rhu(Decimal(margin) / Decimal(max(1, u["turns_completed"])))
    den = Decimal(n)
    return {
        "style_id": style["id"],
        "variant": variant,
        "unit_count": n,
        "avg_acquisition_cost_cents": rhu(Decimal(sum_acq) / den),
        "avg_revenue_per_unit_cents": rhu(Decimal(sum_rev) / den),
        "avg_servicing_cost_per_unit_cents": rhu(Decimal(sum_serv) / den),
        "avg_eol_value_cents": rhu(Decimal(sum_eol) / den),
        "avg_margin_per_unit_cents": rhu(Decimal(sum_margin) / den),
        "avg_margin_per_turn_cents": rhu(Decimal(sum_mpt) / den),
    }


def unit_realized_revenue(unit_id):
    total = 0
    for r in DB["reservations"].values():
        if r["allocated_unit_id"] == unit_id and r["state"] == "CLOSED":
            total += r["revenue_attributed_cents"] or 0
    return total


def unit_occupied_until(unit_id):
    latest = None
    for r in reservations_holding_unit(unit_id):
        end = r["requested_end_date"]
        if latest is None or end > latest:
            latest = end
    if latest is None:
        return None
    return date_add(latest, RECONDITION_BUFFER_DAYS)


def waitlist_position(reservation):
    if reservation["state"] != "WAITLISTED":
        return None
    peers = [r for r in DB["reservations"].values()
             if r["state"] == "WAITLISTED"
             and r["style_id"] == reservation["style_id"]
             and r["requested_size"] == reservation["requested_size"]]
    peers = sorted(peers, key=lambda r: (r["created_at"], r["_seq"]))
    for idx, r in enumerate(peers):
        if r["id"] == reservation["id"]:
            return idx + 1
    return None


def waitlist_head(style_id, size):
    peers = [r for r in DB["reservations"].values()
             if r["state"] == "WAITLISTED"
             and r["style_id"] == style_id
             and r["requested_size"] == size]
    if not peers:
        return None
    return sorted(peers, key=lambda r: (r["created_at"], r["_seq"]))[0]


def member_waiver_used_excluding(member_id, claim_id):
    total = 0
    for c in claims_of_member(member_id):
        if c["id"] == claim_id:
            continue
        if c["state"] in ("ASSESSED", "DISPUTED", "CHARGED", "WAIVED"):
            total += c["waiver_applied_cents"] or 0
    return total


def ledger_of_claim(claim_id):
    rows = [e for e in DB["fee_ledger_entries"].values()
            if e["damage_claim_id"] == claim_id]
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def claim_ledger_sum(claim_id):
    return sum(e["amount_cents"] for e in ledger_of_claim(claim_id))


def claim_has_unreversed_damage_fee(claim_id):
    flag = False
    for e in ledger_of_claim(claim_id):
        if e["kind"] == "DAMAGE_FEE":
            flag = True
        elif e["kind"] == "DISPUTE_REVERSAL":
            flag = False
    return flag
