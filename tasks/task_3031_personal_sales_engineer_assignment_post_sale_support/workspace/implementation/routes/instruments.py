"""Bench setup, inspection and shipment of serialized instruments.

PRD §3.4.
"""

from db import DB, iso
from errors import ApiError, Err
from middleware import guard
from response import (as_int, as_num, as_str, body, created_obj, ensure_known,
                      ok_obj, page)
from services import calc, core

UNIT_ROLES = ["PlatformAdmin", "SalesEngineerOps", "SetupTechnician",
              "SupportAgent"]
SETUP_ROLES = ["SetupTechnician"]


def register(app):
    @app.route("/instrument-units", methods=["POST"])
    def create_unit():
        guard(["SetupTechnician", "SalesEngineerOps"])
        data = body()
        ensure_known(data, ["quote_line_id", "serial_number", "model_code"])
        line = core.fetch("quote_lines", as_str(data, "quote_line_id", required=True),
                          Err.REFERENCED_RESOURCE_NOT_FOUND)
        serial = as_str(data, "serial_number", required=True)
        if core.lookup("instrument_units", serial_number=serial) is not None:
            raise ApiError(Err.SERIAL_ALREADY_REGISTERED)
        row = core.new_row(
            "instrument_units",
            quote_line_id=line["id"],
            serial_number=serial,
            model_code=as_str(data, "model_code", required=True),
            setup_status="PENDING_SETUP",
            setup_technician_id=None,
            action_height_mm=None,
            relief_mm=None,
            intonation_offset_cents=None,
            inspection_overall="PASS",
            modified_since_setup=False,
            shipped_at=None,
        )
        # Registering a unit against a line of an already-counted quote changes
        # the owning customer's purchase history (§1.1).
        quote = DB.get("quotes", line["quote_id"])
        if quote is not None:
            core.refresh_purchased_count(quote["customer_id"])
        return created_obj(core.public(row))

    @app.route("/instrument-units", methods=["GET"])
    def list_units():
        guard(UNIT_ROLES)
        return page(core.all_rows("instrument_units"), filters=(
            ("quote_line_id", "quote_line_id", None),
            ("setup_status", "setup_status", None),
        ))

    @app.route("/instrument-units/<ident>", methods=["GET"])
    def get_unit(ident):
        guard(UNIT_ROLES)
        return ok_obj(core.public(core.fetch("instrument_units", ident,
                                             Err.INSTRUMENT_UNIT_NOT_FOUND)))

    @app.route("/instrument-units/<ident>/start-setup", methods=["POST"])
    def start_setup(ident):
        user_id, role = guard(SETUP_ROLES)
        unit = core.fetch("instrument_units", ident, Err.INSTRUMENT_UNIT_NOT_FOUND)
        core.require_state(unit, ("PENDING_SETUP",), field="setup_status")
        line, quote = core.unit_quote(unit)
        if quote is None or quote["status"] != "RESERVED":
            raise ApiError(Err.INVALID_STATE,
                           "The owning quote is not RESERVED.")
        unit["setup_technician_id"] = user_id
        unit["inspection_overall"] = "PASS"
        unit["modified_since_setup"] = False
        unit["setup_status"] = "IN_SETUP"
        core.touch(unit)
        return ok_obj(core.public(unit))

    @app.route("/instrument-units/<ident>/complete-setup", methods=["POST"])
    def complete_setup(ident):
        guard(SETUP_ROLES)
        data = body()
        ensure_known(data, ["action_height_mm", "relief_mm",
                            "intonation_offset_cents"])
        unit = core.fetch("instrument_units", ident, Err.INSTRUMENT_UNIT_NOT_FOUND)
        core.require_state(unit, ("IN_SETUP",), field="setup_status")
        core.blend_measurements(
            unit,
            as_num(data, "action_height_mm", required=True),
            as_num(data, "relief_mm", required=True),
            as_int(data, "intonation_offset_cents", required=True),
        )
        unit["setup_status"] = "SETUP_COMPLETE"
        core.recompute_inspection_verdict(unit, "preliminary")
        return ok_obj(core.public(unit))

    @app.route("/instrument-units/<ident>/record-inspection", methods=["POST"])
    def record_inspection(ident):
        guard(SETUP_ROLES)
        unit = core.fetch("instrument_units", ident, Err.INSTRUMENT_UNIT_NOT_FOUND)
        core.require_state(unit, ("SETUP_COMPLETE",), field="setup_status")
        unit["setup_status"] = "INSPECTED"
        core.recompute_inspection_verdict(unit, "final")
        unit["modified_since_setup"] = False
        core.touch(unit)
        return ok_obj(core.public(unit))

    @app.route("/instrument-units/<ident>/restart-setup", methods=["POST"])
    def restart_setup(ident):
        guard(SETUP_ROLES)
        unit = core.fetch("instrument_units", ident, Err.INSTRUMENT_UNIT_NOT_FOUND)
        if unit["setup_status"] in core.TERMINAL_STATUSES:
            raise ApiError(Err.ALREADY_TERMINAL)
        if unit["setup_status"] not in ("SETUP_COMPLETE", "INSPECTED"):
            raise ApiError(Err.INVALID_STATE,
                           "setup_status is %s." % unit["setup_status"])
        unit["setup_status"] = "IN_SETUP"
        unit["inspection_overall"] = "PASS"
        unit["modified_since_setup"] = False
        core.touch(unit)
        return ok_obj(core.public(unit))

    @app.route("/instrument-units/<ident>/ship", methods=["POST"])
    def ship_unit(ident):
        guard(["SetupTechnician", "SalesEngineerOps"])
        unit = core.fetch("instrument_units", ident, Err.INSTRUMENT_UNIT_NOT_FOUND)
        core.require_state(unit, ("INSPECTED",), field="setup_status")
        # priority 6: the documentation itself blocks shipment.
        if unit.get("inspection_overall") not in ("PASS", "CONDITIONAL") \
                or unit.get("modified_since_setup"):
            raise ApiError(Err.INSPECTION_NOT_PASSED)
        line, quote = core.unit_quote(unit)
        # priority 17: status moved on, so the quote is no longer RESERVED.
        if quote is None or quote["status"] != "RESERVED":
            raise ApiError(Err.QUOTE_NOT_RESERVED)

        unit["setup_status"] = "SHIPPED"
        unit["shipped_at"] = iso(DB.now())
        unit["modified_since_setup"] = False
        core.touch(unit)

        core.refresh_purchased_count(quote["customer_id"])
        # The final commission variant is stored only once EVERY line of the
        # quote has a shipped instrument; a partially shipped quote keeps the
        # provisional value it stored at submission (PRD §3.3).
        lines = core.quote_lines(quote["id"])
        if lines and all(core.line_is_shipped(item) for item in lines):
            final = core.quote_final_commission(quote, lines)
            if final is not None:
                quote["_commission_cents"] = final
                quote["_commission_variant"] = "final"
                core.touch(quote)
        core.recompute_lifetime_commission(quote["engineer_id"])
        return ok_obj(core.public(unit))