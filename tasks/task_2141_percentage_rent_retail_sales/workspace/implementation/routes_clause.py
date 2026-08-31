"""Co-tenancy clauses and events, and kick-out clauses."""

from flask import g, request

import calc
from core import (
    ApiError,
    DB,
    add_days,
    all_of,
    body,
    clock_now,
    endpoint,
    make_record,
    must_get,
    need_enum,
    need_int,
    ok,
    paginate,
    qs_int,
    require_lease_tenant,
    rhu,
    touch,
)
from serializers import ser

RELIEF_TYPES = ("RENT_REDUCTION", "ALTERNATIVE_SALES_RENT")


def _clause_of_event(event):
    return DB["co_tenancy_clauses"][event["clause_id"]]


def _lease_of_event(event):
    return DB["leases"][_clause_of_event(event)["lease_id"]]


def register(app):
    # ------------------------------------------------------- co-tenancy clause

    @app.post("/retail/leases/<lid>/co-tenancy-clauses")
    @endpoint("CenterAdmin")
    def create_co_tenancy_clause(lid):
        lease = must_get("leases", lid)
        payload = body()
        required_anchors = need_int(payload, "required_open_anchor_count", minimum=0)
        required_occupancy = need_int(payload, "required_occupancy_bps", minimum=0, maximum=10000)
        cure_days = need_int(payload, "cure_period_days", minimum=0)
        relief_type = need_enum(payload, "relief_type", RELIEF_TYPES)
        relief_pct = need_int(payload, "relief_pct_bps", minimum=1, maximum=10000)
        termination_days = need_int(payload, "termination_right_after_days", minimum=0)

        clause = make_record(
            "co_tenancy_clauses",
            {
                "lease_id": lease["id"],
                "required_open_anchor_count": required_anchors,
                "required_occupancy_bps": required_occupancy,
                "cure_period_days": cure_days,
                "relief_type": relief_type,
                "relief_pct_bps": relief_pct,
                "termination_right_after_days": termination_days,
                "monitoring_status": "SATISFIED",
            },
        )
        center = DB["centers"].get(lease["center_id"])
        if center is not None:
            calc.run_monitor(center)
        return ok(ser(clause), 201)

    @app.get("/retail/co-tenancy-clauses/<cid>")
    @endpoint("CenterAdmin", "LeaseAdministrator", "OwnershipAnalyst", "TenantUser")
    def get_co_tenancy_clause(cid):
        return ok(ser(must_get("co_tenancy_clauses", cid)))

    @app.get("/retail/co-tenancy-clauses")
    @endpoint("CenterAdmin", "LeaseAdministrator", "OwnershipAnalyst", "TenantUser")
    def list_co_tenancy_clauses():
        rows = all_of("co_tenancy_clauses")
        for key in ("lease_id", "monitoring_status", "relief_type"):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        return paginate(rows, ser)

    # -------------------------------------------------------- co-tenancy event

    @app.get("/retail/co-tenancy-events/<eid>")
    @endpoint("CenterAdmin", "LeaseAdministrator", "OwnershipAnalyst", "TenantUser")
    def get_co_tenancy_event(eid):
        return ok(ser(must_get("co_tenancy_events", eid)))

    @app.get("/retail/co-tenancy-events")
    @endpoint("CenterAdmin", "LeaseAdministrator", "OwnershipAnalyst", "TenantUser")
    def list_co_tenancy_events():
        rows = all_of("co_tenancy_events")
        for key in ("clause_id", "trigger_tenant_id", "event_type", "status"):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        return paginate(rows, ser)

    @app.post("/retail/co-tenancy-events/<eid>/acknowledge")
    @endpoint("LeaseAdministrator")
    def acknowledge_event(eid):
        event = must_get("co_tenancy_events", eid)
        if event["status"] != "OPEN":
            raise ApiError("ERR_CO_TENANCY_EVENT_STATE_INVALID", 409)
        event["status"] = "CURE_PENDING"
        touch(event)
        return ok(ser(event))

    @app.post("/retail/co-tenancy-events/<eid>/activate-relief")
    @endpoint("CenterAdmin")
    def activate_relief(eid):
        event = must_get("co_tenancy_events", eid)
        clause = _clause_of_event(event)
        lease = _lease_of_event(event)
        # step 6 - state
        if event["status"] != "CURE_PENDING":
            raise ApiError("ERR_CO_TENANCY_EVENT_STATE_INVALID", 409)
        if clause["monitoring_status"] != "VIOLATED":
            raise ApiError("ERR_CO_TENANCY_EVENT_STATE_INVALID", 409)
        if lease["status"] != "ACTIVE":
            raise ApiError("ERR_LEASE_STATE_INVALID", 409)
        # step 11 - clock rule
        if clock_now() < event["cure_deadline_at"]:
            raise ApiError("ERR_CURE_PERIOD_NOT_ELAPSED", 409)

        event["status"] = "RELIEF_ACTIVE"
        event["relief_started_at"] = clock_now()
        touch(event)
        calc.co_tenancy_relief(lease, clause)
        lease["status"] = "RELIEF_ACTIVE"
        lease["co_tenancy_status"] = "RELIEF_ACTIVE"
        lease["relief_approved_by_user_id"] = g.user_id
        touch(lease)
        return ok(ser(event))

    @app.post("/retail/co-tenancy-events/<eid>/cure")
    @endpoint("LeaseAdministrator")
    def cure_event(eid):
        event = must_get("co_tenancy_events", eid)
        clause = _clause_of_event(event)
        lease = _lease_of_event(event)
        if event["status"] not in ("CURE_PENDING", "RELIEF_ACTIVE"):
            raise ApiError("ERR_CO_TENANCY_EVENT_STATE_INVALID", 409)
        if clause["monitoring_status"] != "SATISFIED":
            raise ApiError("ERR_CO_TENANCY_EVENT_STATE_INVALID", 409)

        was_relief = event["status"] == "RELIEF_ACTIVE"
        event["status"] = "CURED"
        if was_relief:
            event["relief_ended_at"] = clock_now()
        touch(event)
        if was_relief:
            lease["status"] = "ACTIVE"
            lease["co_tenancy_status"] = "COMPLIANT"
            lease["effective_monthly_rent_cents"] = rhu(lease["annual_base_rent_cents"], 12)
            lease["relief_monthly_credit_cents"] = 0
        else:
            lease["co_tenancy_status"] = "COMPLIANT"
        touch(lease)
        return ok(ser(event))

    @app.post("/retail/co-tenancy-events/<eid>/elect-termination")
    @endpoint("TenantUser")
    def elect_termination(eid):
        event = must_get("co_tenancy_events", eid)
        clause = _clause_of_event(event)
        lease = _lease_of_event(event)
        require_lease_tenant(lease)
        if event["status"] != "RELIEF_ACTIVE":
            raise ApiError("ERR_CO_TENANCY_EVENT_STATE_INVALID", 409)
        ripe_at = add_days(event["relief_started_at"], clause["termination_right_after_days"])
        if clock_now() < ripe_at:
            raise ApiError("ERR_TERMINATION_RIGHT_NOT_RIPE", 409)

        event["status"] = "TERMINATION_ELECTED"
        event["relief_ended_at"] = clock_now()
        touch(event)
        lease["status"] = "TERMINATION_PENDING"
        lease["co_tenancy_status"] = "VIOLATION_OPEN"
        touch(lease)
        return ok(ser(event))

    # --------------------------------------------------------- kick-out clause

    @app.post("/retail/leases/<lid>/kick-out-clauses")
    @endpoint("CenterAdmin")
    def create_kick_out_clause(lid):
        lease = must_get("leases", lid)
        payload = body()
        measurement_year_index = need_int(payload, "measurement_year_index", minimum=1)
        threshold = need_int(payload, "threshold_sales_cents", minimum=1)
        window_days = need_int(payload, "election_window_days", minimum=1)
        consideration = need_int(
            payload, "waiver_consideration_cents", minimum=0, required=False, default=0
        )
        clause = make_record(
            "kick_out_clauses",
            {
                "lease_id": lease["id"],
                "measurement_year_index": measurement_year_index,
                "threshold_sales_cents": threshold,
                "election_window_days": window_days,
                "triggered_at": None,
                "election_deadline_at": None,
                "waiver_consideration_cents": consideration,
                "status": "ARMED",
            },
        )
        return ok(ser(clause), 201)

    @app.get("/retail/kick-out-clauses/<kid>")
    @endpoint("CenterAdmin", "LeaseAdministrator", "OwnershipAnalyst", "TenantUser")
    def get_kick_out_clause(kid):
        return ok(ser(must_get("kick_out_clauses", kid)))

    @app.get("/retail/kick-out-clauses")
    @endpoint("CenterAdmin", "LeaseAdministrator", "OwnershipAnalyst", "TenantUser")
    def list_kick_out_clauses():
        rows = all_of("kick_out_clauses")
        for key in ("lease_id", "status"):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        year_index = qs_int("measurement_year_index")
        if year_index is not None:
            rows = [r for r in rows if r["measurement_year_index"] == year_index]
        return paginate(rows, ser)

    @app.post("/retail/kick-out-clauses/<kid>/exercise")
    @endpoint("TenantUser")
    def exercise_kick_out(kid):
        clause = must_get("kick_out_clauses", kid)
        lease = DB["leases"][clause["lease_id"]]
        require_lease_tenant(lease)
        # step 6 - state
        if clause["status"] != "TRIGGERED":
            raise ApiError("ERR_KICK_OUT_STATE_INVALID", 409)
        if lease["status"] not in ("ACTIVE", "RELIEF_ACTIVE"):
            raise ApiError("ERR_LEASE_STATE_INVALID", 409)
        # step 10 - cross-entity referential
        measurement = next(
            (
                y
                for y in calc.years_of_lease(lease)
                if y["year_index"] == clause["measurement_year_index"]
            ),
            None,
        )
        if measurement is None or measurement["status"] != "RECONCILED":
            raise ApiError("ERR_KICK_OUT_MEASUREMENT_YEAR_NOT_RECONCILED", 409)
        if lease["status"] == "RELIEF_ACTIVE":
            raise ApiError("ERR_RELIEF_ACTIVE_BLOCKS_EXERCISE", 409)
        # step 11 - clock rule
        if clause["election_deadline_at"] is not None and clock_now() > clause["election_deadline_at"]:
            raise ApiError("ERR_KICK_OUT_ELECTION_WINDOW_CLOSED", 409)

        clause["status"] = "EXERCISED"
        touch(clause)
        lease["status"] = "TERMINATION_PENDING"
        touch(lease)
        return ok(ser(clause))

    @app.post("/retail/kick-out-clauses/<kid>/waive")
    @endpoint("CenterAdmin")
    def waive_kick_out(kid):
        clause = must_get("kick_out_clauses", kid)
        lease = DB["leases"][clause["lease_id"]]
        payload = body()
        consideration = need_int(
            payload, "waiver_consideration_cents", minimum=0, required=False, default=None
        )
        if clause["status"] != "TRIGGERED":
            raise ApiError("ERR_KICK_OUT_STATE_INVALID", 409)
        # step 8 - segregation of duties
        if lease["relief_approved_by_user_id"] is not None and (
            g.user_id == lease["relief_approved_by_user_id"]
        ):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403)

        if clause["election_deadline_at"] is not None and clock_now() > clause["election_deadline_at"]:
            clause["status"] = "EXPIRED"
            clause["waiver_consideration_cents"] = 0
            touch(clause)
            return ok(ser(clause))

        clause["status"] = "WAIVED"
        if consideration is not None:
            clause["waiver_consideration_cents"] = consideration
        touch(clause)
        lease["waiver_approved_by_user_id"] = g.user_id
        touch(lease)
        return ok(ser(clause))
