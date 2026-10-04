"""Programs and the OCC-guarded pricing-update."""

from flask import Blueprint

from db import STORE
from domain import bump, make_program, ser_program
from util import (
    ERR_DUPLICATE_PROGRAM_CODE,
    ERR_STALE_VERSION,
    auth_context,
    body,
    fail,
    get_path,
    ok_object,
    require_role,
    v_int,
    v_str,
)

bp = Blueprint("programs", __name__)

_PRICING_FIELDS = (
    "material_unit_price_cents",
    "discount_pct_federal",
    "discount_pct_accredited_lab",
    "discount_pct_general",
    "handling_fee_threshold_cents",
    "handling_fee_flat_cents",
    "expedite_multiplier_pct",
    "daily_lab_capacity_minutes",
)

_DISCOUNT_FIELDS = (
    "discount_pct_federal",
    "discount_pct_accredited_lab",
    "discount_pct_general",
)


@bp.route("/metrology/programs", methods=["POST"])
def create_program():
    _uid, role = auth_context()
    require_role(role, ["ProgramAdmin"])
    b = body()
    data = {
        "program_code": v_str(b, "program_code"),
        "name": v_str(b, "name"),
        "material_unit_price_cents": v_int(b, "material_unit_price_cents"),
        "discount_pct_federal": v_int(b, "discount_pct_federal", minv=0, maxv=100),
        "discount_pct_accredited_lab": v_int(b, "discount_pct_accredited_lab", minv=0, maxv=100),
        "discount_pct_general": v_int(b, "discount_pct_general", minv=0, maxv=100),
        "handling_fee_threshold_cents": v_int(b, "handling_fee_threshold_cents"),
        "handling_fee_flat_cents": v_int(b, "handling_fee_flat_cents"),
        "expedite_multiplier_pct": v_int(b, "expedite_multiplier_pct"),
        "daily_lab_capacity_minutes": v_int(b, "daily_lab_capacity_minutes"),
    }
    for p in STORE["programs"].values():
        if p["program_code"] == data["program_code"]:
            fail(
                ERR_DUPLICATE_PROGRAM_CODE,
                409,
                "program_code already exists: " + data["program_code"],
            )
    rec = make_program(data)
    STORE["programs"][rec["id"]] = rec
    return ok_object(ser_program(rec), 201)


@bp.route("/metrology/programs/<pid>/pricing-update", methods=["POST"])
def pricing_update(pid):
    _uid, role = auth_context()
    require_role(role, ["ProgramAdmin"])
    b = body()
    expected = v_int(b, "expected_program_version")
    updates = {}
    for key in _PRICING_FIELDS:
        if key in b and b[key] is not None:
            if isinstance(b[key], bool) or not isinstance(b[key], int):
                fail("ERR_INVALID_REQUEST", 400, "field {} must be an integer".format(key))
            if key in _DISCOUNT_FIELDS and not (0 <= b[key] <= 100):
                fail(
                    "ERR_INVALID_REQUEST",
                    400,
                    "field {} must lie between 0 and 100".format(key),
                )
            updates[key] = b[key]
    program = get_path(STORE["programs"], pid, "program")
    if expected != program["version"]:
        fail(
            ERR_STALE_VERSION,
            412,
            "expected_program_version does not match the current program version",
        )
    for key, value in updates.items():
        program[key] = value
    bump(program)
    return ok_object(ser_program(program), 200)
