"""Offtake agreement routes."""
import db
from errors import raise_err
from helpers import (
    require_auth, payload, req_enum, req_number, opt_number, req_int, req_iso,
    success_obj, success_arr, pagination_args, paginate, now_common, touch,
    iso_from_epoch, dec2,
)
from serializers import offtake_view
from logic import get_project, get_offtake, PRICE_FLOOR

READ_ROLES = ["OriginationManager", "DeveloperAdmin", "TaxCounsel", "Auditor", "PlatformAdmin"]


def register(app):

    @app.post("/api/projects/<pid>/offtake-agreements")
    def create_offtake(pid):
        require_auth(["OriginationManager"])
        p = get_project(pid)
        body = payload()
        buyer_type = req_enum(body, "buyer_type", {"UTILITY", "CORPORATE"})
        price = req_number(body, "base_price_usd_mwh")
        esc = req_number(body, "escalator_pct")
        term = req_int(body, "term_years")
        dsd = req_iso(body, "delivery_start_date")
        # OCC on project version (priority 5)
        if "expected_project_version" not in body or body["expected_project_version"] is None:
            raise_err("ERR_VALIDATION", "expected_project_version is required")
        epv = body["expected_project_version"]
        if isinstance(epv, bool) or not isinstance(epv, int):
            raise_err("ERR_VALIDATION", "expected_project_version must be an integer")
        if epv != p["version"]:
            raise_err("ERR_STALE_VERSION", "Project version has advanced")
        oid = db.new_id()
        o = {
            "id": oid,
            "project_id": pid,
            "buyer_type": buyer_type,
            "base_price_usd_mwh": float(price),
            "escalator_pct": float(esc),
            "term_years": term,
            "delivery_start_date": iso_from_epoch(dsd),
            "status": "NEGOTIATING",
            "counter_count": 0,
        }
        now_common(o)
        db.offtake_agreements[oid] = o
        touch(p)  # creating an offtake increments project version by 1
        return success_obj(offtake_view(o), 201)

    @app.get("/api/projects/<pid>/offtake-agreements")
    def list_offtakes(pid):
        require_auth(READ_ROLES)
        get_project(pid)
        limit, offset = pagination_args()
        items = sorted(
            [o for o in db.offtake_agreements.values() if o["project_id"] == pid],
            key=lambda o: (o["created_at"], o["id"]),
        )
        page, total = paginate(items, limit, offset)
        return success_arr([offtake_view(o) for o in page], limit, offset, total)

    @app.get("/api/offtake-agreements/<oid>")
    def get_offtake_route(oid):
        require_auth(READ_ROLES)
        o = get_offtake(oid)
        return success_obj(offtake_view(o))

    @app.post("/api/offtake-agreements/<oid>/transitions")
    def offtake_transition(oid):
        require_auth(["OriginationManager"])
        o = get_offtake(oid)
        body = payload()
        to = req_enum(body, "to", {"NEGOTIATING", "COUNTERED", "EXECUTED", "EFFECTIVE", "TERMINATED"})
        cur = o["status"]
        new_price = opt_number(body, "base_price_usd_mwh", None)

        if to == "TERMINATED":
            if cur in ("EXPIRED", "TERMINATED"):
                raise_err("ERR_INVALID_STATE", f"Cannot terminate from {cur}")
            o["status"] = "TERMINATED"
            touch(o)
            if cur == "EFFECTIVE":
                p = db.projects.get(o["project_id"])
                if p is not None:
                    touch(p)
            return success_obj(offtake_view(o))

        valid = {
            ("NEGOTIATING", "COUNTERED"),
            ("COUNTERED", "NEGOTIATING"),
            ("NEGOTIATING", "EXECUTED"),
            ("COUNTERED", "EXECUTED"),
            ("EXECUTED", "EFFECTIVE"),
        }
        if (cur, to) not in valid:
            raise_err("ERR_INVALID_STATE", f"Cannot move from {cur} to {to}")

        if to in ("COUNTERED", "NEGOTIATING"):
            o["counter_count"] += 1
            if new_price is not None:
                o["base_price_usd_mwh"] = float(new_price)
            o["status"] = to
            touch(o)
            return success_obj(offtake_view(o))

        if to == "EXECUTED":
            if new_price is not None:
                o["base_price_usd_mwh"] = float(new_price)
            if dec2(o["base_price_usd_mwh"]) < PRICE_FLOOR:
                raise_err("ERR_PRICE_FLOOR_BREACH", "base_price_usd_mwh below 20.00 floor")
            if any(
                x["project_id"] == o["project_id"] and x["id"] != oid
                and x["status"] in ("EXECUTED", "EFFECTIVE")
                for x in db.offtake_agreements.values()
            ):
                raise_err("ERR_ACTIVE_OFFTAKE_EXISTS",
                          "Another offtake of the project is EXECUTED or EFFECTIVE")
            o["status"] = "EXECUTED"
            touch(o)
            p = db.projects.get(o["project_id"])
            if p is not None:
                touch(p)
            return success_obj(offtake_view(o))

        # EFFECTIVE
        o["status"] = "EFFECTIVE"
        touch(o)
        return success_obj(offtake_view(o))
