"""Routes: logical clock, accounts, PoPs and maintenance windows."""
from datetime import datetime, timezone
from flask import request

from core import (db, body, success, parse_dt, stamp_new, touch,
                  require_roles, req_str, req_int, req_enum,
                  err_invalid, err_duplicate, err_not_found,
                  err_time_range, err_window_overlap,
                  SUPPORT_SLA_HOURS, PLAN_TIERS, sweep_clock,
                  account_out, pop_out)


def register(app):

    @app.post("/api/_clock/set_current_utc")
    def set_clock():
        require_roles("PlatformAdmin")
        data = body()
        raw = data.get("current_utc")
        t = parse_dt(raw)
        if t is None:
            raise err_invalid("Field 'current_utc' must be an ISO 8601 timestamp")
        db.clock_utc = t
        sweep_clock(t)
        return success({"current_utc": raw})

    @app.post("/api/accounts")
    def create_account():
        require_roles("PlatformAdmin")
        data = body()
        company_name = req_str(data, "company_name")
        plan_tier = req_enum(data, "plan_tier", PLAN_TIERS)
        account_email = req_str(data, "account_email")
        acct = stamp_new({
            "company_name": company_name,
            "plan_tier": plan_tier,
            "account_email": account_email,
            "support_response_sla_hours": SUPPORT_SLA_HOURS[plan_tier],
        })
        db.accounts[acct["id"]] = acct
        return success(account_out(acct), 201)

    @app.post("/api/pops")
    def create_pop():
        require_roles("PlatformAdmin")
        data = body()
        code = req_str(data, "code")
        capacity = req_int(data, "capacity_baseline_gbps", minimum=1)
        if any(p["code"] == code for p in db.pops.values()):
            raise err_duplicate(f"A PoP with code '{code}' already exists")
        pop = stamp_new({
            "code": code,
            "capacity_baseline_gbps": capacity,
            "maintenance_windows": [],
            "status": "ACTIVE",
            "effective_capacity_gbps": None,
            "planned_utilization_pct": None,
        })
        db.pops[pop["id"]] = pop
        return success(pop_out(pop), 201)

    @app.get("/api/pops/<pid>")
    def get_pop(pid):
        require_roles("PlatformAdmin", "NetworkPlanner", "ZoneAdmin")
        pop = db.pops.get(pid)
        if pop is None:
            raise err_not_found("PoP not found")
        as_of_raw = request.args.get("as_of_utc")
        reserved_raw = request.args.get("reserved_gbps")
        as_of = parse_dt(as_of_raw) if as_of_raw is not None else None
        reserved = None
        if reserved_raw is not None:
            try:
                reserved = int(reserved_raw)
            except (TypeError, ValueError):
                raise err_invalid("reserved_gbps must be an integer")
        return success(pop_out(pop, as_of=as_of, reserved=reserved))

    @app.post("/api/pops/<pid>/maintenance-windows")
    def add_maintenance_window(pid):
        require_roles("NetworkPlanner")
        pop = db.pops.get(pid)
        if pop is None:
            raise err_not_found("PoP not found")
        data = body()
        start_raw = req_str(data, "start_utc")
        end_raw = req_str(data, "end_utc")
        headroom = req_int(data, "headroom_pct", minimum=1, maximum=99)
        start = parse_dt(start_raw)
        end = parse_dt(end_raw)
        if start is None or end is None:
            raise err_invalid("start_utc and end_utc must be ISO 8601 timestamps")
        if not end > start:
            raise err_time_range()
        for w in pop["maintenance_windows"]:
            ws = parse_dt(w["start_utc"])
            we = parse_dt(w["end_utc"])
            if start < we and ws < end:
                raise err_window_overlap()
        pop["maintenance_windows"].append({
            "start_utc": start_raw,
            "end_utc": end_raw,
            "headroom_pct": headroom,
        })
        touch(pop)
        return success(pop_out(pop), 200)
