# Entity serializers — public representations with derived fields resolved.
import derive
from timeutil import fmt_iso


def _common(entity):
    return {
        "id": entity["id"],
        "created_at": fmt_iso(entity["created_at"]),
        "updated_at": fmt_iso(entity["updated_at"]),
        "version": entity["version"],
    }


def _dt(value):
    return fmt_iso(value) if value is not None else None


def part_public(p):
    out = {
        "part_number": p["part_number"],
        "description": p["description"],
        "package_family": p["package_family"],
        "process_technology": p["process_technology"],
        "automotive_grade": p["automotive_grade"],
        "lifecycle_status": p["lifecycle_status"],
        "demand_rate_units_per_week": p["demand_rate_units_per_week"],
        "buffer_multiple": p["buffer_multiple"],
        "on_hand_units": p["on_hand_units"],
        "reserved_units": derive.part_reserved_units(p["id"]),
        "posture": derive.coverage_and_posture(p)[1],
    }
    out.update(_common(p))
    return out


def customer_public(c):
    out = {
        "name": c["name"],
        "tier": c["tier"],
        "channel": c["channel"],
        "credit_limit_cents": c["credit_limit_cents"],
        "discount_pct": c["discount_pct"],
        "open_exposure_cents": derive.customer_open_exposure(c["id"]),
        "at_risk_design_win_count": derive.customer_at_risk_count(c["id"]),
    }
    out.update(_common(c))
    return out


def pricing_schedule_public(s):
    out = {
        "part_id": s["part_id"],
        "effective_from": _dt(s["effective_from"]),
        "tiers": [dict(t) for t in s["tiers"]],
        "status": s["status"],
        "published_at": _dt(s["published_at"]),
    }
    out.update(_common(s))
    return out


def order_line_public(line):
    out = {
        "order_id": line["order_id"],
        "part_id": line["part_id"],
        "quantity": line["quantity"],
        "unit_price_cents": line["unit_price_cents"],
        "line_total_cents": line["line_total_cents"],
        "awarded_units": line["awarded_units"],
        "allocation_run_id": line["allocation_run_id"],
        "allocation_rank": line["allocation_rank"],
        "allocation_priority_score": line["allocation_priority_score"],
    }
    out.update(_common(line))
    return out


def order_public(order):
    out = {
        "customer_id": order["customer_id"],
        "channel": order["channel"],
        "status": order["status"],
        "subtotal_cents": order["subtotal_cents"],
        "service_fee_cents": order["service_fee_cents"],
        "total_cents": order["total_cents"],
        "submitted_at": _dt(order["submitted_at"]),
        "lines": [order_line_public(l) for l in derive.order_lines_of(order["id"])],
    }
    out.update(_common(order))
    return out


def capacity_pool_public(pool):
    out = {
        "site_name": pool["site_name"],
        "process_technology": pool["process_technology"],
        "period_start": _dt(pool["period_start"]),
        "period_end": _dt(pool["period_end"]),
        "total_units": pool["total_units"],
        "allocated_units": pool["allocated_units"],
        "status": derive.pool_status(pool),
        "qualified_for_automotive": derive.site_qualified_for_automotive(pool["site_name"]),
    }
    out.update(_common(pool))
    return out


def allocation_run_public(run):
    out = {
        "period_label": run["period_label"],
        "status": run["status"],
        "shortage_part_ids": list(run["shortage_part_ids"]),
        "awards": [dict(a) for a in run["awards"]],
    }
    out.update(_common(run))
    return out


def eol_notice_public(notice):
    out = {
        "part_id": notice["part_id"],
        "notice_date": _dt(notice["notice_date"]),
        "last_order_date": _dt(notice["last_order_date"]),
        "last_ship_date": _dt(notice["last_ship_date"]),
        "reason": notice["reason"],
        "status": notice["status"],
    }
    out.update(_common(notice))
    return out


def lifetime_buy_public(buy):
    out = {
        "eol_notice_id": buy["eol_notice_id"],
        "part_id": buy["part_id"],
        "customer_id": buy["customer_id"],
        "quantity": buy["quantity"],
        "unit_price_cents": buy["unit_price_cents"],
        "ltb_value_cents": buy["ltb_value_cents"],
        "status": buy["status"],
    }
    out.update(_common(buy))
    return out


def site_qualification_public(q):
    out = {
        "site_name": q["site_name"],
        "segment": q["segment"],
        "status": q["status"],
        "qualified_at": _dt(q["qualified_at"]),
        "validity_months": q["validity_months"],
    }
    out.update(_common(q))
    return out


def reference_design_public(rd):
    out = {
        "title": rd["title"],
        "featured_part_number": rd["featured_part_number"],
        "status": rd["status"],
        "published_at": _dt(rd["published_at"]),
    }
    out.update(_common(rd))
    return out


def design_win_public(win):
    ramped, flat, canonical = derive.recognized_revenue(win)
    out = {
        "reference_design_id": win["reference_design_id"],
        "customer_id": win["customer_id"],
        "part_id": win["part_id"],
        "expected_lifetime_revenue_cents": win["expected_lifetime_revenue_cents"],
        "annual_volume_units": win["annual_volume_units"],
        "start_date": _dt(win["start_date"]),
        "status": win["status"],
        "at_risk": derive.win_at_risk(win),
        "recognized_ramped_cents": ramped,
        "recognized_flat_cents": flat,
        "recognized_revenue_cents": canonical,
    }
    out.update(_common(win))
    return out
