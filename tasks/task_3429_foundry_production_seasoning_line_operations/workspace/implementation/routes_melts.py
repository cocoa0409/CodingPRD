"""Melt batch endpoints: booking, charging, chemistry, certification, tap, pour (PRD 3.3/3.4)."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import domain
import envelope
import serialize
import store
from authz import ALL_ROLES, authenticate, authorize, check_sod
from errors import err
from validate import paginate_params, parse_body, validate

bp = Blueprint("melts", __name__)

FURNACES = ["FURNACE_A", "FURNACE_B"]

_PCT_FIELDS = [
    "planned_pig_iron_pct",
    "planned_scrap_steel_pct",
    "planned_returns_pct",
    "planned_alloy_pct",
]


@bp.route("/foundry/melt-batches", methods=["POST"])
def create_melt():
    _uid, role = authenticate()
    authorize(role, ["MeltOperator"])
    vals = validate(
        parse_body(),
        [
            {"name": "production_order_id", "kind": "string"},
            {"name": "furnace_id", "kind": "enum", "values": FURNACES},
            {"name": "planned_tap_start", "kind": "datetime"},
            {"name": "planned_tap_end", "kind": "datetime"},
            {"name": "planned_iron_lbs", "kind": "number", "gt": 0},
            {"name": "planned_pig_iron_pct", "kind": "number"},
            {"name": "planned_scrap_steel_pct", "kind": "number"},
            {"name": "planned_returns_pct", "kind": "number"},
            {"name": "planned_alloy_pct", "kind": "number"},
            {"name": "expected_production_order_version", "kind": "integer"},
        ],
    )
    if vals["planned_tap_end"] <= vals["planned_tap_start"]:
        raise err("ERR_INVALID_REQUEST", "planned_tap_end must be > planned_tap_start")
    pct_sum = sum(vals[f] for f in _PCT_FIELDS)
    if abs(pct_sum - Decimal("100")) > Decimal("0.01"):
        raise err("ERR_INVALID_REQUEST", "planned_*_pct fields must sum to 100.0 (+-0.01)")
    order = domain.get_or_404("orders", vals["production_order_id"])
    if order["state"] not in ("MOLDING", "POURING"):
        raise err("ERR_INVALID_STATE_TRANSITION", "order is not in MOLDING or POURING")
    if vals["expected_production_order_version"] != order["version"]:
        raise err("ERR_STALE_ORDER_VERSION", "production order version has advanced")
    _idx, _tier, posture = domain.order_derived(order)
    if posture == "FROZEN":
        raise err("ERR_ORDER_FROZEN", "order posture is FROZEN")
    if domain.permit_type_in_breach("AIR_EMISSIONS"):
        raise err("ERR_EMISSIONS_PERMIT_BREACH", "AIR_EMISSIONS permit is in BREACH")
    s1, e1 = vals["planned_tap_start"], vals["planned_tap_end"]
    for m in store.db["melts"].values():
        if m["furnace_id"] != vals["furnace_id"]:
            continue
        if m["state"] in ("EXHAUSTED", "CANCELLED"):
            continue
        s2, e2 = m["planned_tap_start"], m["planned_tap_end"]
        if s1 < e2 and s2 < e1:
            raise err("ERR_FURNACE_WINDOW_OVERLAP", "furnace tap window overlaps an active batch")

    planned_cost = calc.planned_charge_cost_cents(
        vals["planned_iron_lbs"],
        vals["planned_pig_iron_pct"],
        vals["planned_scrap_steel_pct"],
        vals["planned_returns_pct"],
        vals["planned_alloy_pct"],
    )
    ent = store.make_entity()
    ent.update(
        {
            "production_order_id": order["id"],
            "furnace_id": vals["furnace_id"],
            "planned_tap_start": s1,
            "planned_tap_end": e1,
            "planned_iron_lbs": vals["planned_iron_lbs"],
            "planned_pig_iron_pct": vals["planned_pig_iron_pct"],
            "planned_scrap_steel_pct": vals["planned_scrap_steel_pct"],
            "planned_returns_pct": vals["planned_returns_pct"],
            "planned_alloy_pct": vals["planned_alloy_pct"],
            "state": "CHARGING",
            "state_before_hold": None,
            "adjustment_count": 0,
            "pig_iron_lbs": Decimal("0"),
            "scrap_steel_lbs": Decimal("0"),
            "returns_lbs": Decimal("0"),
            "alloy_lbs": Decimal("0"),
            "planned_charge_cost_cents": planned_cost,
            "actual_charge_cost_cents": 0,
            "carbon_pct": None,
            "silicon_pct": None,
            "manganese_pct": None,
            "sulfur_pct": None,
            "phosphorus_pct": None,
            "bath_temp_f": None,
            "carbon_equivalent": None,
            "chemistry_recorded_by": None,
            "certified_by": None,
            "tapped_temp_f": None,
            "tapped_lbs": None,
            "slag_loss_lbs": None,
            "poured_lbs": Decimal("0"),
            "remaining_iron_lbs": None,
            "returns_credit_lbs": Decimal("0"),
        }
    )
    store.db["melts"][ent["id"]] = ent
    store.touch(order)
    return envelope.success(serialize.melt_batch(ent), status=201)


@bp.route("/foundry/melt-batches", methods=["GET"])
def list_melts():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = paginate_params()
    items = list(store.db["melts"].values())
    order_id = request.args.get("production_order_id")
    state = request.args.get("state")
    if order_id is not None:
        items = [m for m in items if m["production_order_id"] == order_id]
    if state is not None:
        items = [m for m in items if m["state"] == state]
    return envelope.list_payload(items, serialize.melt_batch, limit, offset)


@bp.route("/foundry/melt-batches/<mid>", methods=["GET"])
def get_melt(mid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    m = domain.get_or_404("melts", mid)
    return envelope.success(serialize.melt_batch(m))


@bp.route("/foundry/melt-batches/<mid>/charge", methods=["POST"])
def charge_melt(mid):
    _uid, role = authenticate()
    authorize(role, ["MeltOperator"])
    vals = validate(
        parse_body(),
        [
            {"name": "pig_iron_lbs", "kind": "number", "ge": 0},
            {"name": "scrap_steel_lbs", "kind": "number", "ge": 0},
            {"name": "returns_lbs", "kind": "number", "ge": 0},
            {"name": "alloy_lbs", "kind": "number", "ge": 0},
        ],
    )
    m = domain.get_or_404("melts", mid)
    if m["state"] not in ("CHARGING", "ADJUSTMENT"):
        raise err("ERR_INVALID_STATE_TRANSITION", "batch is not in CHARGING or ADJUSTMENT")
    m["pig_iron_lbs"] = calc.D(m["pig_iron_lbs"]) + vals["pig_iron_lbs"]
    m["scrap_steel_lbs"] = calc.D(m["scrap_steel_lbs"]) + vals["scrap_steel_lbs"]
    m["returns_lbs"] = calc.D(m["returns_lbs"]) + vals["returns_lbs"]
    m["alloy_lbs"] = calc.D(m["alloy_lbs"]) + vals["alloy_lbs"]
    m["actual_charge_cost_cents"] += calc.charge_call_cost_cents(
        vals["pig_iron_lbs"], vals["scrap_steel_lbs"], vals["returns_lbs"], vals["alloy_lbs"]
    )
    m["state"] = "MELTING"
    store.touch(m)
    return envelope.success(serialize.melt_batch(m))


@bp.route("/foundry/melt-batches/<mid>/chemistry-readings", methods=["POST"])
def chemistry_readings(mid):
    uid, role = authenticate()
    authorize(role, ["MeltOperator"])
    vals = validate(
        parse_body(),
        [
            {"name": "carbon_pct", "kind": "number"},
            {"name": "silicon_pct", "kind": "number"},
            {"name": "manganese_pct", "kind": "number"},
            {"name": "sulfur_pct", "kind": "number"},
            {"name": "phosphorus_pct", "kind": "number"},
            {"name": "bath_temp_f", "kind": "number"},
        ],
    )
    m = domain.get_or_404("melts", mid)
    if m["state"] != "MELTING":
        raise err("ERR_INVALID_STATE_TRANSITION", "batch is not MELTING")
    m["carbon_pct"] = vals["carbon_pct"]
    m["silicon_pct"] = vals["silicon_pct"]
    m["manganese_pct"] = vals["manganese_pct"]
    m["sulfur_pct"] = vals["sulfur_pct"]
    m["phosphorus_pct"] = vals["phosphorus_pct"]
    m["bath_temp_f"] = vals["bath_temp_f"]
    m["carbon_equivalent"] = calc.carbon_equivalent(
        vals["carbon_pct"], vals["silicon_pct"], vals["phosphorus_pct"]
    )
    m["chemistry_recorded_by"] = uid
    m["state"] = "CHEMISTRY_CHECK"
    store.touch(m)
    return envelope.success(serialize.melt_batch(m))


@bp.route("/foundry/melt-batches/<mid>/certify-chemistry", methods=["POST"])
def certify_chemistry(mid):
    uid, role = authenticate()
    authorize(role, ["QualityInspector"])
    m = domain.try_get("melts", mid)
    if m is not None:
        check_sod(uid, m["chemistry_recorded_by"])
    vals = validate(
        parse_body(),
        [{"name": "decision", "kind": "enum", "values": ["CERTIFY", "ORDER_ADJUSTMENT"]}],
    )
    if m is None:
        raise err("ERR_RESOURCE_NOT_FOUND", f"melt batch not found: {mid}")
    if m["state"] != "CHEMISTRY_CHECK":
        raise err("ERR_INVALID_STATE_TRANSITION", "batch is not in CHEMISTRY_CHECK")
    if vals["decision"] == "CERTIFY":
        if not calc.chemistry_in_spec(
            m["carbon_equivalent"], m["sulfur_pct"], m["phosphorus_pct"], m["bath_temp_f"]
        ):
            raise err("ERR_CHEMISTRY_OUT_OF_SPEC", "chemistry outside certification spec")
        m["state"] = "CERTIFIED"
        m["certified_by"] = uid
    else:
        m["state"] = "ADJUSTMENT"
        m["adjustment_count"] += 1
    store.touch(m)
    return envelope.success(serialize.melt_batch(m))


@bp.route("/foundry/melt-batches/<mid>/tap", methods=["POST"])
def tap_melt(mid):
    _uid, role = authenticate()
    authorize(role, ["MeltOperator"])
    vals = validate(
        parse_body(),
        [
            {"name": "tapped_temp_f", "kind": "number"},
            {"name": "tapped_lbs", "kind": "number", "gt": 0},
        ],
    )
    m = domain.get_or_404("melts", mid)
    if m["state"] != "CERTIFIED":
        raise err("ERR_INVALID_STATE_TRANSITION", "batch is not CERTIFIED")
    if domain.permit_type_in_breach("AIR_EMISSIONS"):
        raise err("ERR_EMISSIONS_PERMIT_BREACH", "AIR_EMISSIONS permit is in BREACH")
    slag = calc.slag_loss_lbs(vals["tapped_lbs"])
    m["tapped_temp_f"] = vals["tapped_temp_f"]
    m["tapped_lbs"] = vals["tapped_lbs"]
    m["slag_loss_lbs"] = slag
    m["poured_lbs"] = Decimal("0")
    m["remaining_iron_lbs"] = calc.D(vals["tapped_lbs"]) - slag
    m["state"] = "TAPPED"
    store.touch(m)
    return envelope.success(serialize.melt_batch(m))


@bp.route("/foundry/melt-batches/<mid>/pour", methods=["POST"])
def pour_melt(mid):
    _uid, role = authenticate()
    authorize(role, ["MeltOperator"])
    vals = validate(
        parse_body(),
        [
            {"name": "mold_id", "kind": "string"},
            {"name": "unit_count", "kind": "integer", "ge": 1, "le": 48},
            {"name": "pour_weight_per_unit_oz", "kind": "number", "gt": 0},
        ],
    )
    m = domain.get_or_404("melts", mid)
    mold = domain.get_or_404("molds", vals["mold_id"])
    if m["state"] != "TAPPED":
        raise err("ERR_INVALID_STATE_TRANSITION", "batch is not TAPPED")
    if mold["state"] != "PREPARED":
        raise err("ERR_INVALID_STATE_TRANSITION", "mold is not PREPARED")
    order = store.db["orders"][m["production_order_id"]]
    _idx, _tier, posture = domain.order_derived(order)
    if posture == "FROZEN":
        raise err("ERR_ORDER_FROZEN", "order posture is FROZEN")
    if mold["production_order_id"] != m["production_order_id"]:
        raise err("ERR_MOLD_ORDER_MISMATCH", "mold belongs to a different production order")
    pour_total = calc.pour_total_lbs(vals["unit_count"], vals["pour_weight_per_unit_oz"])
    if pour_total > calc.D(m["remaining_iron_lbs"]):
        raise err("ERR_INSUFFICIENT_IRON", "pour exceeds remaining_iron_lbs")

    units = []
    for _ in range(vals["unit_count"]):
        u = store.make_entity()
        u.update(
            {
                "production_order_id": m["production_order_id"],
                "melt_batch_id": m["id"],
                "mold_id": mold["id"],
                "seasoning_batch_id": None,
                "pour_weight_oz": vals["pour_weight_per_unit_oz"],
                "measured_weight_oz": None,
                "measured_diameter_in": None,
                "measured_wall_thickness_in": None,
                "state": "POURED",
                "rework_count": 0,
                "scrap_reason": None,
                "scrapped_after_rework": False,
            }
        )
        store.db["units"][u["id"]] = u
        units.append(u)

    mold["state"] = "POURED"
    store.touch(mold)

    m["poured_lbs"] = calc.D(m["poured_lbs"]) + pour_total
    m["remaining_iron_lbs"] = calc.D(m["remaining_iron_lbs"]) - pour_total
    if m["remaining_iron_lbs"] == 0:
        m["state"] = "EXHAUSTED"
    store.touch(m)

    order["poured_units"] += vals["unit_count"]
    if order["state"] == "MOLDING":
        order["state"] = "POURING"
    store.touch(order)

    return envelope.success(
        [serialize.casting_unit(u) for u in units], response_type="array", status=201
    )
