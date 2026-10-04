"""Shipping instructions, container units, multi-day holds — PRD §3.10,
endpoints 70-84, 399-405, 124-129, 78-79.
"""

import db
import core
import services
import calculations as calc
from core import ApiError, D, now_iso, try_iso
from response import ok, page_of
from http_util import (pagination, must_get, must_resolve, get_or_none, body,
                       coerce_int, coerce_num, arg)
from routes._common import route
from models import create

UNIT_CHAIN = ("PENDING", "INGATED", "LOADED", "ON_VESSEL", "DISCHARGED",
              "OFFLOADED", "GATED_OUT")


def register(app):

    # ----------------------------------------------------- shipping instructions

    @route(app, "/api/shipping-instructions", ["POST"], ["BookingClerk"])
    def create_instruction():
        """§3.10: a booking opens as a ShippingInstruction created against a
        run_plan_id with the container_unit_ids to be attached."""
        raw = body()
        unknown = _unknown(raw, ("run_plan_id", "container_unit_ids"))
        if unknown:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % unknown)
        if "run_plan_id" not in raw or "container_unit_ids" not in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "run_plan_id and container_unit_ids are required.")
        run = get_or_none("RunPlan", raw["run_plan_id"])
        if run is None:
            raise ApiError("ERR_RUN_PLAN_NOT_FOUND")
        unit_ids = raw["container_unit_ids"]
        if not isinstance(unit_ids, list):
            raise ApiError("ERR_INVALID_REQUEST", "container_unit_ids must be an array.")
        units = []
        for uid in unit_ids:
            unit = db.get("container_units", uid)
            if unit is None:
                raise ApiError("ERR_REFERENCE_NOT_FOUND")
            units.append(unit)
        row = create("ShippingInstruction", {
            "run_plan_id": run["id"],
            "container_unit_ids": list(unit_ids),
        })
        row["instruction_status"] = "BOOKED"
        for unit in units:
            unit["instruction_id"] = row["id"]
        db.sides["instruction_units"][row["id"]] = [u["id"] for u in units]
        services.recompute_instruction(row)
        services.flush(row)
        return ok(row, 201)

    @route(app, "/api/shipping-instructions", ["GET"], ["Any"])
    def list_instructions():
        limit, offset = pagination()
        return page_of(db.sort_created(db.all_rows("shipping_instructions")), limit, offset)

    @route(app, "/api/shipping-instructions/<rid>", ["GET"], ["Any"])
    def get_instruction(rid):
        instruction = must_get("ShippingInstruction", rid)
        services.recompute_instruction(instruction)
        return ok(instruction)

    @route(app, "/api/shipping-instructions/<rid>/place-holds", ["POST"], ["BookingClerk"])
    def place_holds(rid):
        """§3.10: the instruction must be in BOOKED, every named container must
        belong to this instruction, and each moves PENDING → INGATED while its
        version increments."""
        instruction = must_get("ShippingInstruction", rid)
        raw = body()
        unknown = _unknown(raw, ("container_unit_ids", "expected_instruction_version"))
        if unknown:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % unknown)
        # §2.11 puts the target row's own state ahead of the request-consistency
        # checks, so the BOOKED precondition is evaluated first.
        if instruction.get("instruction_status") != "BOOKED":
            raise ApiError("ERR_INVALID_STATE",
                           "Holds can only be placed on a BOOKED instruction.")
        _check_version(raw, "expected_instruction_version", instruction)
        unit_ids = raw.get("container_unit_ids")
        if not isinstance(unit_ids, list) or not unit_ids:
            raise ApiError("ERR_INVALID_REQUEST", "container_unit_ids must be a non-empty array.")
        owned = set(db.sides["instruction_units"].get(rid, []))
        for uid in unit_ids:
            if uid not in owned:
                raise ApiError("ERR_REFERENCE_NOT_FOUND",
                               "The container does not belong to this instruction.")
        for uid in unit_ids:
            unit = db.get("container_units", uid)
            if unit.get("unit_status") == "PENDING":
                services.mark(unit, "unit_status", "INGATED")
            unit["version"] = int(unit.get("version", 1)) + 1
            unit["updated_at"] = now_iso()
            services.flush(unit)
        services.mark(instruction, "instruction_status", "HOLD_PLACED")
        services.recompute_instruction(instruction)
        db.touch(instruction, now_iso())
        return ok(instruction)

    @route(app, "/api/shipping-instructions/<rid>/cancel-holds", ["POST"], ["BookingClerk"])
    def cancel_holds(rid):
        instruction = must_get("ShippingInstruction", rid)
        raw = body()
        unknown = _unknown(raw, ("container_unit_ids",))
        if unknown:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % unknown)
        if instruction.get("instruction_status") != "HOLD_PLACED":
            raise ApiError("ERR_INVALID_STATE",
                           "Only a HOLD_PLACED instruction can release its holds.")
        unit_ids = raw.get("container_unit_ids")
        if not isinstance(unit_ids, list):
            raise ApiError("ERR_INVALID_REQUEST", "container_unit_ids must be an array.")
        owned = set(db.sides["instruction_units"].get(rid, []))
        for uid in unit_ids:
            if uid not in owned:
                raise ApiError("ERR_REFERENCE_NOT_FOUND")
        for uid in unit_ids:
            unit = db.get("container_units", uid)
            if unit.get("unit_status") == "INGATED":
                services.mark(unit, "unit_status", "PENDING")
            unit["version"] = int(unit.get("version", 1)) + 1
            unit["updated_at"] = now_iso()
            services.flush(unit)
        services.mark(instruction, "instruction_status", "BOOKED")
        services.recompute_instruction(instruction)
        db.touch(instruction, now_iso())
        return ok(instruction)

    @route(app, "/api/shipping-instructions/<rid>/verify-vgm", ["POST"], ["BookingClerk"])
    def verify_vgm(rid):
        """§3.10: each unit's verified_gross_mass_kg must reach at least 100
        kilograms and no container on the instruction may already be OFFLOADED."""
        instruction = must_get("ShippingInstruction", rid)
        raw = body()
        unknown = _unknown(raw, ("expected_instruction_version",))
        if unknown:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % unknown)
        if instruction.get("instruction_status") != "HOLD_PLACED":
            raise ApiError("ERR_INVALID_STATE",
                           "Mass can only be verified on a HOLD_PLACED instruction.")
        _check_version(raw, "expected_instruction_version", instruction)
        units = calc.attached_units(rid)
        if any(u.get("unit_status") == "OFFLOADED" for u in units):
            raise ApiError("ERR_INVALID_STATE",
                           "A container on the instruction is already OFFLOADED.")
        for u in units:
            if D(u.get("verified_gross_mass_kg", 0)) < 100:
                raise ApiError("ERR_VGM_VERIFICATION_FAILED",
                               "A container's verified gross mass is below 100 kg.")
        services.mark(instruction, "instruction_status", "VGM_VERIFIED")
        services.recompute_instruction(instruction)
        db.touch(instruction, now_iso())
        return ok(instruction)

    @route(app, "/api/shipping-instructions/<rid>/complete-carriage", ["POST"],
           ["ComplianceOfficer"])
    def complete_carriage(rid):
        """§3.10: completable from VGM_VERIFIED provided no container on it is in
        OFFLOADED or PENDING."""
        instruction = must_get("ShippingInstruction", rid)
        raw = body()
        _reject_unknown(raw, ())
        if instruction.get("instruction_status") != "VGM_VERIFIED":
            raise ApiError("ERR_INVALID_STATE",
                           "Only a VGM_VERIFIED instruction can complete carriage.")
        for u in calc.attached_units(rid):
            if u.get("unit_status") in ("OFFLOADED", "PENDING"):
                raise ApiError("ERR_INVALID_STATE",
                               "A container on the instruction is OFFLOADED or PENDING.")
        services.mark(instruction, "instruction_status", "CARRIED")
        services.mark(instruction, "booked_line_total_cents",
                      calc.booked_line_total_cents(rid, carried_only=True))
        db.touch(instruction, now_iso())
        return ok(instruction)

    @route(app, "/api/shipping-instructions/<rid>/reject", ["POST"], ["ComplianceOfficer"])
    def reject_instruction(rid):
        """§3.10: an instruction whose holds are not in that condition is refused
        with ERR_HOLD_NOT_ACTIVE."""
        instruction = must_get("ShippingInstruction", rid)
        raw = body()
        unknown = _unknown(raw, ("declined_container_unit_id",))
        if unknown:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % unknown)
        declined = raw.get("declined_container_unit_id")
        if declined is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "declined_container_unit_id is required.")
        if declined not in set(db.sides["instruction_units"].get(rid, [])):
            raise ApiError("ERR_REFERENCE_NOT_FOUND")
        if instruction.get("instruction_status") not in ("HOLD_PLACED", "VGM_VERIFIED"):
            raise ApiError("ERR_HOLD_NOT_ACTIVE",
                           "The instruction's holds are not in an active condition.")
        for u in calc.attached_units(rid):
            if u.get("unit_status") in ("INGATED", "LOADED"):
                services.mark(u, "unit_status", "PENDING")
                u["version"] = int(u.get("version", 1)) + 1
                u["updated_at"] = now_iso()
                services.flush(u)
        services.mark(instruction, "instruction_status", "REJECTED")
        services.mark(instruction, "booked_vgm_kg_sum", D(0))
        db.touch(instruction, now_iso())
        return ok(instruction)

    # --------------------------------------------------------- container units

    @route(app, "/api/container-units", ["POST"], ["TerminalOperator"])
    def create_unit():
        """§3.10: "A ContainerUnit carries its own identity and geometry: an
        instruction_id that is null while the container is unallocated, an ISO 6346
        container_number, a length_feet of 20, 40 or 45, a gross_weight_kg, and a
        verified_gross_mass_kg defaulting to 0."
        """
        raw = body()
        allowed = {"instruction_id", "container_number", "length_feet",
                   "gross_weight_kg", "verified_gross_mass_kg"}
        unknown = _unknown(raw, allowed)
        if unknown:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % unknown)
        for key in ("container_number", "length_feet", "gross_weight_kg"):
            if key not in raw:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Required field '%s' is missing." % key)
        length = coerce_int(raw["length_feet"])
        if length not in (20, 40, 45):
            raise ApiError("ERR_INVALID_REQUEST",
                           "length_feet must be 20, 40 or 45.")
        instruction_id = raw.get("instruction_id")
        if instruction_id is not None:
            instruction = db.get("shipping_instructions", instruction_id)
            if instruction is None:
                raise ApiError("ERR_REFERENCE_NOT_FOUND")
            db.sides["instruction_units"].setdefault(instruction_id, [])
        row = create("ContainerUnit", {
            "instruction_id": instruction_id,
            "container_number": raw["container_number"],
            "length_feet": length,
            "gross_weight_kg": coerce_num(raw["gross_weight_kg"]),
            "verified_gross_mass_kg": coerce_num(raw.get("verified_gross_mass_kg", 0)),
        })
        row["unit_status"] = "PENDING"
        services.mark(row, "unit_rate_cents", calc.container_unit_rate(length))
        services.flush(row)
        return ok(row, 201)

    @route(app, "/api/container-units", ["GET"], ["Any"])
    def list_units():
        limit, offset = pagination()
        rows = db.all_rows("container_units")
        instruction_id = arg("instruction_id")
        if instruction_id:
            rows = [u for u in rows if u.get("instruction_id") == instruction_id]
        return page_of(db.sort_created(rows), limit, offset)

    @route(app, "/api/container-units/<rid>", ["GET"], ["Any"])
    def get_unit(rid):
        return ok(must_get("ContainerUnit", rid))

    @route(app, "/api/container-units/<rid>/gate-in", ["POST"], ["TerminalOperator"])
    def gate_in(rid):
        unit = must_get("ContainerUnit", rid)
        raw = body()
        _reject_unknown(raw, ())
        if unit.get("unit_status") != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "Only a PENDING container can be gated in.")
        services.mark(unit, "unit_status", "INGATED")
        _bump_unit(unit)
        _recompute_owner(unit)
        return ok(unit)

    @route(app, "/api/container-units/<rid>/load", ["POST"], ["TerminalOperator"])
    def load_unit(rid):
        """§3.10: loading requires the owning instruction to be in HOLD_PLACED or
        VGM_VERIFIED."""
        unit = must_get("ContainerUnit", rid)
        raw = body()
        _reject_unknown(raw, ())
        instruction = _instruction_of(unit)
        if unit.get("unit_status") not in ("INGATED", "OFFLOADED"):
            raise ApiError("ERR_INVALID_STATE",
                           "Only an INGATED or OFFLOADED container can be loaded.")
        if instruction is not None and instruction.get("instruction_status") not in (
                "HOLD_PLACED", "VGM_VERIFIED"):
            raise ApiError("ERR_INVALID_STATE",
                           "The owning instruction is not in HOLD_PLACED or VGM_VERIFIED.")
        services.mark(unit, "unit_status", "LOADED")
        _bump_unit(unit)
        _recompute_owner(unit)
        return ok(unit)

    @route(app, "/api/container-units/<rid>/discharge", ["POST"], ["TerminalOperator"])
    def discharge_unit(rid):
        unit = must_get("ContainerUnit", rid)
        raw = body()
        _reject_unknown(raw, ())
        if unit.get("unit_status") != "ON_VESSEL":
            raise ApiError("ERR_INVALID_STATE",
                           "Only an ON_VESSEL container can be discharged.")
        services.mark(unit, "unit_status", "DISCHARGED")
        _bump_unit(unit)
        _recompute_owner(unit)
        return ok(unit)

    @route(app, "/api/container-units/<rid>/offload", ["POST"], ["TerminalOperator"])
    def offload_unit(rid):
        """§3.10: requires the owning instruction not to be CARRIED."""
        unit = must_get("ContainerUnit", rid)
        raw = body()
        _reject_unknown(raw, ())
        instruction = _instruction_of(unit)
        if unit.get("unit_status") != "DISCHARGED":
            raise ApiError("ERR_INVALID_STATE",
                           "Only a DISCHARGED container can be offloaded.")
        if instruction is not None and instruction.get("instruction_status") == "CARRIED":
            raise ApiError("ERR_INVALID_STATE",
                           "A CARRIED instruction has no container left to offload.")
        services.mark(unit, "unit_status", "OFFLOADED")
        _bump_unit(unit)
        _recompute_owner(unit)
        return ok(unit)

    @route(app, "/api/container-units/<rid>/gate-out", ["POST"], ["TerminalOperator"])
    def gate_out_unit(rid):
        unit = must_get("ContainerUnit", rid)
        raw = body()
        _reject_unknown(raw, ())
        if unit.get("unit_status") != "DISCHARGED":
            raise ApiError("ERR_INVALID_STATE",
                           "Only a DISCHARGED container can be gated out.")
        services.mark(unit, "unit_status", "GATED_OUT")
        _bump_unit(unit)
        _recompute_owner(unit)
        return ok(unit)


def _unknown(raw, allowed):
    for key in raw:
        if key not in allowed:
            return key
    return None


def _reject_unknown(raw, allowed):
    key = _unknown(raw, tuple(allowed))
    if key:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field '%s' is not declared for this endpoint." % key)


def _check_version(raw, field, row):
    if field not in raw or raw[field] is None:
        return
    if int(raw[field]) != int(row.get("version", 1)):
        raise ApiError("ERR_STALE_VERSION",
                       "The supplied expected version does not match the current version.")


def _bump_unit(unit):
    """§3.10: each step along the chain increments the unit's version by 1."""
    unit["version"] = int(unit.get("version", 1)) + 1
    unit["updated_at"] = now_iso()
    services.flush(unit)


def _instruction_of(unit):
    return db.get("shipping_instructions", unit.get("instruction_id"))


def _recompute_owner(unit):
    services.mark(unit, "unit_rate_cents", calc.container_unit_rate(unit.get("length_feet")))
    services.flush(unit)
    instruction = _instruction_of(unit)
    if instruction is None:
        return
    services.recompute_instruction(instruction)
    services.flush(instruction)
    run = db.get("run_plans", instruction.get("run_plan_id"))
    if run is not None:
        carrier = services.carrier_of_run(run)
        if carrier is not None:
            services.flush(carrier)