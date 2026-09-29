"""The futures book: opening and closing hedge positions."""
import calc
import derive
import guards
import serialize
from envelope import ok, ok_list
from errors import fail
from routes import bp
from shape import enum_param, page, pagination, require_auth, take
from store import db, new_row, touch
from util import rhu

COMMODITIES = ["CORN", "ETHANOL", "NATGAS"]
DIRECTIONS = ["LONG", "SHORT"]
POSITION_STATUSES = ("OPEN", "PARTIALLY_CLOSED", "CLOSED")

POSITION_SPEC = {
    "position_code": {"type": "string", "required": True},
    "commodity": {"type": "enum", "required": True, "values": COMMODITIES},
    "direction": {"type": "enum", "required": True, "values": DIRECTIONS},
    "contract_month": {"type": "month", "required": True},
    "contracts": {"type": "int", "required": True, "gt": 0},
    "entry_price": {"type": "dec", "required": True, "gt": 0, "places": 2},
}
CLOSE_SPEC = {
    "contracts_to_close": {"type": "int", "required": True},
    "exit_price": {"type": "dec", "required": True, "gt": 0, "places": 2},
}


@bp.route("/hedge-positions", methods=["POST"])
def create_position():
    require_auth(["RiskManager"])
    body = take(POSITION_SPEC)
    guards.unique(db.positions, "position_code", body["position_code"])
    position = new_row({
        "position_code": body["position_code"],
        "commodity": body["commodity"],
        "direction": body["direction"],
        "contract_month": body["contract_month"],
        "contracts": body["contracts"],
        "entry_price": rhu(body["entry_price"], 2),
        "status": "OPEN",
        "contracts_closed": 0,
        "realized_pnl_cents": 0,
        # PRD 3.9: a new position opens with both profit-and-loss figures at 0.
        "unrealized_pnl_cents": 0,
        "opened_at": db.clock,
        "closed_at": None,
    })
    db.positions[position["id"]] = position
    return ok(serialize.position_out(position), 201)


@bp.route("/hedge-positions/<position_id>", methods=["GET"])
def get_position(position_id):
    require_auth(["PlantManager", "RiskManager"])
    position = guards.get_position(position_id)
    return ok(serialize.position_out(position))


@bp.route("/hedge-positions", methods=["GET"])
def list_positions():
    require_auth(["PlantManager", "RiskManager"])
    commodity = enum_param("commodity", COMMODITIES)
    direction = enum_param("direction", DIRECTIONS)
    status = enum_param("status", POSITION_STATUSES)
    limit, offset = pagination()
    rows = list(db.positions.values())
    if commodity is not None:
        rows = [r for r in rows if r["commodity"] == commodity]
    if direction is not None:
        rows = [r for r in rows if r["direction"] == direction]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    window = page(rows, limit, offset)
    return ok_list([serialize.position_out(r) for r in window],
                   limit, offset, len(rows))


@bp.route("/hedge-positions/<position_id>/close", methods=["POST"])
def close_position(position_id):
    require_auth(["RiskManager"])
    body = take(CLOSE_SPEC)
    position = guards.get_position(position_id)
    if position["status"] not in ("OPEN", "PARTIALLY_CLOSED"):
        fail("ERR_INVALID_POSITION_STATE",
             "Position is %s and may not be closed" % position["status"])
    contracts_open = int(position["contracts"]) - int(position["contracts_closed"])
    to_close = int(body["contracts_to_close"])
    if to_close < 1 or to_close > contracts_open:
        fail("ERR_CLOSE_EXCEEDS_OPEN_CONTRACTS",
             "Only %d contracts remain open on this position" % contracts_open)
    slice_pnl = calc.hedge_slice_pnl(position["direction"], position["commodity"],
                                     position["entry_price"], body["exit_price"],
                                     to_close)
    position["realized_pnl_cents"] = int(position["realized_pnl_cents"]) + slice_pnl
    position["contracts_closed"] = int(position["contracts_closed"]) + to_close
    if int(position["contracts_closed"]) == int(position["contracts"]):
        position["status"] = "CLOSED"
        position["closed_at"] = db.clock
    else:
        position["status"] = "PARTIALLY_CLOSED"
    derive.reprice_position(position)
    touch(position)
    return ok(serialize.position_out(position))
