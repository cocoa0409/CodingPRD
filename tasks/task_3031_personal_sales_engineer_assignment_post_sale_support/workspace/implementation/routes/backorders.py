"""Backorder and preorder allocation across engineers' books.

PRD §3.5.
"""

from db import DB, iso, parse_dt
from errors import ApiError, Err, invalid_value
from middleware import guard, require_engineer_owner
from response import (as_int, as_str, body, created_obj, ensure_known, has,
                      ok_obj, page)
from services import calc, core

BACKORDER_ROLES = ["PlatformAdmin", "SalesEngineerOps", "Engineer"]


def _pool(data):
    """pool_units is a mandatory input on both sweep and finalize."""
    if not has(data, "pool_units"):
        raise ApiError(Err.MISSING_REQUIRED_FIELD,
                       "Field pool_units is required.")
    pool_units = as_int(data, "pool_units")
    # priority 30: refused before any waterfall walk begins.
    if pool_units < 0:
        raise ApiError(Err.ALLOCATION_POOL_NEGATIVE)
    return pool_units


def register(app):
    @app.route("/backorders", methods=["POST"])
    def create_backorder():
        guard(["Engineer", "SalesEngineerOps"])
        data = body()
        ensure_known(data, ["quote_line_id", "engineer_id", "units_requested",
                            "variant_bps", "preorder_open_at"],
                     optional=("variant_bps",))
        line = core.fetch("quote_lines", as_str(data, "quote_line_id", required=True),
                          Err.REFERENCED_RESOURCE_NOT_FOUND)
        engineer = core.fetch("engineers", as_str(data, "engineer_id", required=True),
                              Err.ENGINEER_NOT_FOUND)
        units_requested = as_int(data, "units_requested", required=True)
        # priority 14: units_requested == 0 defines an empty candidate set.
        if units_requested <= 0:
            raise ApiError(Err.ZERO_ALLOCATION_REQUEST)
        opened = parse_dt(as_str(data, "preorder_open_at", required=True))
        if opened is None:
            raise invalid_value("preorder_open_at must be an ISO 8601 instant.")

        highest = 0
        for bo in DB.all("backorders"):
            highest = max(highest, int(bo.get("alloc_sequence") or 0))
        row = core.new_row(
            "backorders",
            quote_line_id=line["id"],
            engineer_id=engineer["id"],
            variant_bps=as_int(data, "variant_bps", default=6000),
            preorder_open_at=iso(opened),
            units_requested=units_requested,
            units_filled=0,
            overcommit_estimate_units=0,
            alloc_sequence=highest + 1,
            eta_deadline=None,
            status="PREORDER_PENDING",
        )
        core.recompute_backorder_deadline(row)
        return created_obj(core.public(row))

    @app.route("/backorders", methods=["GET"])
    def list_backorders():
        guard(BACKORDER_ROLES)
        return page(core.all_rows("backorders"), filters=(
            ("engineer_id", "engineer_id", None),
            ("quote_line_id", "quote_line_id", None),
            ("status", "status", None),
        ))

    @app.route("/backorders/<ident>", methods=["GET"])
    def get_backorder(ident):
        guard(BACKORDER_ROLES)
        return ok_obj(core.public(core.fetch("backorders", ident,
                                             Err.BACKORDER_NOT_FOUND)))

    @app.route("/backorders/<ident>/start-sweep", methods=["POST"])
    def start_sweep(ident):
        guard(["SalesEngineerOps"])
        data = body()
        pool_units = _pool(data)
        bo = core.fetch("backorders", ident, Err.BACKORDER_NOT_FOUND)
        core.require_state(bo, ("PREORDER_PENDING", "PARTIALLY_FILLED"))
        deadline = parse_dt(bo.get("eta_deadline"))
        # The window is half-open: at exactly the deadline the sweep is admitted.
        if deadline is not None and DB.now() > deadline:
            raise ApiError(Err.PREORDER_WINDOW_EXPIRED)
        if bo["status"] == "PARTIALLY_FILLED":
            bo["units_filled"] = 0
        bo["status"] = "ALLOCATION_SWEEP"
        bo["_pool_units"] = pool_units
        bo["overcommit_estimate_units"] = calc.overcommit_estimate_units(
            bo["units_requested"], pool_units)
        core.touch(bo)
        return ok_obj(core.public(bo))

    @app.route("/backorders/<ident>/finalize-allocation", methods=["POST"])
    def finalize_allocation(ident):
        guard(["SalesEngineerOps"])
        data = body()
        pool_units = _pool(data)
        bo = core.fetch("backorders", ident, Err.BACKORDER_NOT_FOUND)
        core.require_state(bo, ("ALLOCATION_SWEEP",))

        granted = calc.waterfall_units_filled(core.allocation_siblings(bo), pool_units)
        bo["units_filled"] = granted.get(bo["id"], 0)
        bo["_pool_units"] = pool_units
        bo["overcommit_estimate_units"] = calc.overcommit_estimate_units(
            bo["units_requested"], pool_units)
        core.touch(bo)

        line = DB.get("quote_lines", bo["quote_line_id"])
        quote = DB.get("quotes", line["quote_id"]) if line else None
        if 0 < bo["units_filled"] < bo["units_requested"]:
            bo["status"] = "PARTIALLY_FILLED"
            if quote is not None:
                # Hop 2: the quote loses its full reservation.
                quote["status"] = "SUBMITTED"
                quote["reserved_at"] = None
                core.bump(quote)
                # Hop 3: cancel this quote's still-unallocated claims.
                for other in DB.all("backorders"):
                    if other["id"] == bo["id"]:
                        continue
                    if other["status"] not in ("PREORDER_PENDING", "ALLOCATION_SWEEP"):
                        continue
                    other_line = DB.get("quote_lines", other["quote_line_id"])
                    if other_line is None or other_line["quote_id"] != quote["id"]:
                        continue
                    other["status"] = "CANCELLED"
                    core.touch(other)
        else:
            bo["status"] = "BOARD_FILLED"
        return ok_obj(core.public(bo))

    @app.route("/backorders/<ident>/reset-sweep", methods=["POST"])
    def reset_sweep(ident):
        guard(["SalesEngineerOps"])
        bo = core.fetch("backorders", ident, Err.BACKORDER_NOT_FOUND)
        core.require_state(bo, ("ALLOCATION_SWEEP", "PARTIALLY_FILLED"))
        bo["units_filled"] = 0
        bo["status"] = "PREORDER_PENDING"
        # Recomputed afresh against the pool this claim's group has seen.
        group_pool = max([int(other.get("_pool_units") or 0)
                          for other in core.allocation_siblings(bo)]
                         + [int(bo.get("_pool_units") or 0)])
        bo["overcommit_estimate_units"] = calc.overcommit_estimate_units(
            bo["units_requested"], group_pool)
        core.touch(bo)
        return ok_obj(core.public(bo))

    @app.route("/backorders/<ident>/start-receiving", methods=["POST"])
    def start_receiving(ident):
        guard(["SalesEngineerOps"])
        bo = core.fetch("backorders", ident, Err.BACKORDER_NOT_FOUND)
        core.require_state(bo, ("PARTIALLY_FILLED", "BOARD_FILLED"))
        bo["status"] = "RECEIVING"
        core.touch(bo)
        return ok_obj(core.public(bo))

    @app.route("/backorders/<ident>/ship", methods=["POST"])
    def ship_backorder(ident):
        guard(["SalesEngineerOps"])
        bo = core.fetch("backorders", ident, Err.BACKORDER_NOT_FOUND)
        core.require_state(bo, ("RECEIVING",))
        bo["status"] = "SHIPPED"
        core.touch(bo)
        return ok_obj(core.public(bo))

    @app.route("/backorders/<ident>/cancel", methods=["POST"])
    def cancel_backorder(ident):
        user_id, role = guard(["SalesEngineerOps", "Engineer"])
        bo = core.fetch("backorders", ident, Err.BACKORDER_NOT_FOUND)
        core.require_state(bo, ("PREORDER_PENDING", "ALLOCATION_SWEEP",
                                "PARTIALLY_FILLED", "BOARD_FILLED"))
        require_engineer_owner(user_id, role, bo)
        bo["status"] = "CANCELLED"
        core.touch(bo)
        return ok_obj(core.public(bo))