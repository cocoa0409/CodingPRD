"""Material lots: create, read, list, state-machine transitions (incl. the
homogeneity measurement payload), and the three reverse sub-resource lists."""

from flask import Blueprint, request

from db import STORE
from domain import (
    bump,
    make_lot,
    ser_certificate,
    ser_lot,
    ser_method,
    ser_round,
    units_available,
)
from engine import (
    allocation_sweep,
    published_certificate,
    run_homogeneity,
)
from util import (
    ALL_ROLES,
    ERR_INVALID_LOT_STATE,
    ERR_INSUFFICIENT_UNITS,
    ERR_NO_PUBLISHED_CERTIFICATE,
    ERR_OPEN_ORDERS_EXIST,
    auth_context,
    body,
    fail,
    get_clock,
    get_path,
    get_ref,
    list_page,
    ok_object,
    require_role,
    require_target_role,
    v_enum,
    v_int,
    v_num,
    v_num_list,
    v_str,
)

bp = Blueprint("lots", __name__)

LOT_STATES = [
    "SOURCING",
    "HOMOGENEITY_TESTING",
    "VALUE_ASSIGNMENT",
    "CERTIFICATION_PENDING",
    "CERTIFIED",
    "IN_DISTRIBUTION",
    "DISTRIBUTION_HOLD",
    "DEPLETED",
    "WITHDRAWN",
]

# transition-target -> roles permitted to drive it (cascade stage 2)
LOT_TARGET_ROLES = {
    "HOMOGENEITY_TESTING": ["Metrologist"],
    "IN_DISTRIBUTION": ["InventoryManager"],
    "DEPLETED": ["InventoryManager"],
    "WITHDRAWN": ["InventoryManager"],
}

HOMOGENEITY_SOURCES = ("SOURCING", "HOMOGENEITY_TESTING", "VALUE_ASSIGNMENT")
WITHDRAWABLE = (
    "SOURCING",
    "HOMOGENEITY_TESTING",
    "VALUE_ASSIGNMENT",
    "CERTIFICATION_PENDING",
    "CERTIFIED",
    "IN_DISTRIBUTION",
    "DISTRIBUTION_HOLD",
)


@bp.route("/metrology/material-lots", methods=["POST"])
def create_lot():
    _uid, role = auth_context()
    require_role(role, ["ProgramAdmin"])
    b = body()
    data = {
        "program_id": v_str(b, "program_id"),
        "material_code": v_str(b, "material_code"),
        "matrix_description": v_str(b, "matrix_description"),
        "total_units_produced": v_int(b, "total_units_produced", minv=1),
        "allocation_policy": v_enum(
            b, "allocation_policy", ("FIFO", "PRO_RATA"), required=False
        ),
    }
    get_ref(STORE["programs"], data["program_id"], "program")
    if data["allocation_policy"] is None:
        data["allocation_policy"] = "FIFO"
    rec = make_lot(data)
    STORE["lots"][rec["id"]] = rec
    return ok_object(ser_lot(rec), 201)


@bp.route("/metrology/material-lots/<lid>", methods=["GET"])
def get_lot(lid):
    _uid, role = auth_context()
    require_role(role, ALL_ROLES)
    lot = get_path(STORE["lots"], lid, "material lot")
    return ok_object(ser_lot(lot), 200)


@bp.route("/metrology/material-lots", methods=["GET"])
def list_lots():
    _uid, role = auth_context()
    require_role(role, ALL_ROLES)
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = list(STORE["lots"].values())
    if program_id is not None:
        items = [l for l in items if l["program_id"] == program_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return list_page(items, ser_lot)


@bp.route("/metrology/material-lots/<lid>/transitions", methods=["POST"])
def lot_transition(lid):
    uid, role = auth_context()
    require_role(role, ["Metrologist", "InventoryManager"])
    b = body()
    require_target_role(role, b.get("to"), LOT_TARGET_ROLES)
    to = v_enum(b, "to", LOT_STATES)

    # stage 3: target-specific payload schema (before path existence)
    payload = {}
    if to == "HOMOGENEITY_TESTING":
        payload["bottle_means"] = v_num_list(b, "bottle_means", min_len=2)
        payload["within_bottle_std"] = v_num(b, "within_bottle_std", positive=True)
        payload["replicates_per_bottle"] = v_int(b, "replicates_per_bottle", minv=1)

    lot = get_path(STORE["lots"], lid, "material lot")

    if to == "HOMOGENEITY_TESTING":
        if lot["status"] not in HOMOGENEITY_SOURCES:
            fail(
                ERR_INVALID_LOT_STATE,
                409,
                "lot status {} does not permit homogeneity testing".format(
                    lot["status"]
                ),
            )
        if len(payload["bottle_means"]) > units_available(lot):
            fail(
                ERR_INSUFFICIENT_UNITS,
                422,
                "bottle count exceeds the lot's available units",
            )
        verdict = run_homogeneity(
            lot,
            payload["bottle_means"],
            payload["within_bottle_std"],
            payload["replicates_per_bottle"],
        )
        lot["status"] = (
            "VALUE_ASSIGNMENT" if verdict == "PASS" else "HOMOGENEITY_TESTING"
        )
        bump(lot)
        return ok_object(ser_lot(lot), 200)

    if to == "IN_DISTRIBUTION":
        if lot["status"] != "CERTIFIED":
            fail(
                ERR_INVALID_LOT_STATE,
                409,
                "only a CERTIFIED lot may enter distribution",
            )
        cert = published_certificate(lot["id"])
        if (
            cert is None
            or cert["expiration_date"] is None
            or not (cert["expiration_date"] > get_clock())
        ):
            fail(
                ERR_NO_PUBLISHED_CERTIFICATE,
                422,
                "no PUBLISHED, unexpired certificate exists for this lot",
            )
        lot["status"] = "IN_DISTRIBUTION"
        bump(lot)
        return ok_object(ser_lot(lot), 200)

    if to == "DEPLETED":
        if lot["status"] != "IN_DISTRIBUTION" or units_available(lot) != 0:
            fail(
                ERR_INVALID_LOT_STATE,
                409,
                "depletion requires an IN_DISTRIBUTION lot with zero available units",
            )
        lot["status"] = "DEPLETED"
        bump(lot)
        return ok_object(ser_lot(lot), 200)

    if to == "WITHDRAWN":
        if lot["status"] not in WITHDRAWABLE:
            fail(
                ERR_INVALID_LOT_STATE,
                409,
                "lot status {} does not permit withdrawal".format(lot["status"]),
            )
        for o in STORE["sales_orders"].values():
            if o["lot_id"] == lot["id"] and o["status"] == "ALLOCATED":
                fail(
                    ERR_OPEN_ORDERS_EXIST,
                    409,
                    "ALLOCATED sales orders exist for this lot",
                )
        # release and cancel every BACKORDERED order on the lot
        for o in STORE["sales_orders"].values():
            if o["lot_id"] == lot["id"] and o["status"] == "BACKORDERED":
                lot["units_reserved"] -= o["allocated_quantity"]
                o["allocated_quantity"] = 0
                o["status"] = "CANCELLED"
                bump(o)
        lot["status"] = "WITHDRAWN"
        bump(lot)
        return ok_object(ser_lot(lot), 200)

    # any remaining target has no declared manual transition from any state
    fail(
        ERR_INVALID_LOT_STATE,
        409,
        "no declared lot transition from {} to {}".format(lot["status"], to),
    )


@bp.route("/metrology/material-lots/<lid>/value-assignment-methods", methods=["GET"])
def list_lot_methods(lid):
    _uid, role = auth_context()
    require_role(role, ALL_ROLES)
    lot = get_path(STORE["lots"], lid, "material lot")
    items = [m for m in STORE["methods"].values() if m["lot_id"] == lot["id"]]
    return list_page(items, ser_method)


@bp.route("/metrology/material-lots/<lid>/certificates", methods=["GET"])
def list_lot_certificates(lid):
    _uid, role = auth_context()
    require_role(role, ALL_ROLES)
    lot = get_path(STORE["lots"], lid, "material lot")
    items = [c for c in STORE["certificates"].values() if c["lot_id"] == lot["id"]]
    return list_page(items, ser_certificate)


@bp.route("/metrology/material-lots/<lid>/pt-rounds", methods=["GET"])
def list_lot_rounds(lid):
    _uid, role = auth_context()
    require_role(role, ALL_ROLES)
    lot = get_path(STORE["lots"], lid, "material lot")
    items = [r for r in STORE["pt_rounds"].values() if r["lot_id"] == lot["id"]]
    return list_page(items, ser_round)
