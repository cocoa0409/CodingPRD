"""Per-test world builders.

The server is relaunched with an empty database before every individual test, so
nothing here may rely on state surviving between tests: each builder constructs
everything it needs from scratch through the declared endpoints.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import validate_success

from . import factories as f
from .constants import SERVER_START_CLOCK_UTC
from .test_users import (
    admin_headers,
    make_car_hire_accountant_headers,
    make_fleet_owner_headers,
    make_interchange_clerk_headers,
    make_repair_billing_agent_headers,
)


class World:
    """Identifiers and header builders for one test's fixture graph."""

    def __init__(self, api):
        self.api = api
        self.admin = admin_headers()
        self.roads: Dict[str, str] = {}
        self.car_types: Dict[str, str] = {}
        self.junctions: Dict[str, str] = {}
        self.cars: Dict[str, str] = {}
        self.events: List[str] = []
        self.clock: str = SERVER_START_CLOCK_UTC

    # ------------------------------------------------------------- headers
    def clerk(self, road_id: str) -> Dict[str, str]:
        return make_interchange_clerk_headers(road_id)

    def accountant(self, road_id: str) -> Dict[str, str]:
        return make_car_hire_accountant_headers(road_id)

    def repair(self, road_id: str) -> Dict[str, str]:
        return make_repair_billing_agent_headers(road_id)

    def owner(self, road_id: str) -> Dict[str, str]:
        return make_fleet_owner_headers(road_id)

    # ---------------------------------------------------------- shortcuts
    @property
    def bn(self) -> str:
        return self.roads["BN"]

    @property
    def cx(self) -> str:
        return self.roads["CX"]

    @property
    def ns(self) -> str:
        return self.roads["NS"]

    @property
    def xm(self) -> str:
        return self.car_types["XM"]

    @property
    def jct(self) -> str:
        return self.junctions["JCT-CHI"]

    @property
    def car(self) -> str:
        return self.cars["CX 100001"]


def set_clock(api, instant: str, world: Optional[World] = None) -> Dict[str, Any]:
    """Move the logical clock, the only source of "now" in the system."""
    data = validate_success(api.set_clock(instant, admin_headers()))
    if world is not None:
        world.clock = instant
    return data


def register_railroad(api, mark: str, world: Optional[World] = None, **kwargs) -> str:
    data = validate_success(
        api.create_railroad(f.railroad_payload(mark, **kwargs), admin_headers()), 201
    )
    if world is not None:
        world.roads[mark] = data["id"]
    return data["id"]


def register_car_type(api, world: Optional[World] = None, payload=None, **overrides) -> str:
    body = payload if payload is not None else f.car_type_payload(**overrides)
    data = validate_success(api.create_car_type(body, admin_headers()), 201)
    if world is not None:
        world.car_types[body["car_type_code"]] = data["id"]
    return data["id"]


def register_junction(api, code: str, road_a_id: str, road_b_id: str,
                      world: Optional[World] = None, **kwargs) -> str:
    data = validate_success(
        api.create_junction(
            f.junction_payload(code, road_a_id, road_b_id, **kwargs), admin_headers()
        ),
        201,
    )
    if world is not None:
        world.junctions[code] = data["id"]
    return data["id"]


def register_car(api, car_mark: str, car_type_id: str, owner_road_id: str,
                 initial_handling_road_id: Optional[str] = None,
                 world: Optional[World] = None, **kwargs) -> str:
    data = validate_success(
        api.create_car(
            f.car_payload(car_mark, car_type_id, owner_road_id,
                          initial_handling_road_id=initial_handling_road_id, **kwargs),
            make_fleet_owner_headers(owner_road_id),
        ),
        201,
    )
    if world is not None:
        world.cars[car_mark] = data["id"]
    return data["id"]


def capture_delivery(api, car_id: str, junction_id: str, delivering_road_id: str,
                     receiving_road_id: str, interchange_at: str, odometer_miles: int,
                     load_status: str = "LOADED", acting_road_id: Optional[str] = None,
                     world: Optional[World] = None) -> Dict[str, Any]:
    """Capture an INTERCHANGE_DELIVERY, closing one segment and opening the next."""
    acting = acting_road_id or delivering_road_id
    data = validate_success(
        api.create_interchange_event(
            f.delivery_event_payload(car_id, junction_id, delivering_road_id,
                                     receiving_road_id, interchange_at,
                                     odometer_miles, load_status),
            make_interchange_clerk_headers(acting),
        ),
        201,
    )
    if world is not None:
        world.events.append(data["id"])
    return data


def capture_rejection(api, car_id: str, junction_id: str, delivering_road_id: str,
                      receiving_road_id: str, interchange_at: str, odometer_miles: int,
                      load_status: str = "LOADED", acting_road_id: Optional[str] = None,
                      world: Optional[World] = None) -> Dict[str, Any]:
    """Capture an INTERCHANGE_REJECTION, which moves no custody."""
    acting = acting_road_id or receiving_road_id
    data = validate_success(
        api.create_interchange_event(
            f.rejection_event_payload(car_id, junction_id, delivering_road_id,
                                      receiving_road_id, interchange_at,
                                      odometer_miles, load_status),
            make_interchange_clerk_headers(acting),
        ),
        201,
    )
    if world is not None:
        world.events.append(data["id"])
    return data


def find_movements(api, headers: Dict[str, str], **filters) -> List[Dict[str, Any]]:
    """Every hire segment matching the filters, in the API's declared order."""
    data = validate_success(api.list_movements(headers, params=filters))
    return data if isinstance(data, list) else data["items"]


def open_movement_of(api, car_id: str, handling_road_id: str,
                     headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    rows = find_movements(api, headers or admin_headers(), car_id=car_id,
                          handling_road_id=handling_road_id, status="OPEN")
    assert len(rows) == 1, f"expected exactly one OPEN segment, got {len(rows)}"
    return rows[0]


def closed_movement_of(api, car_id: str, handling_road_id: str,
                       headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    rows = find_movements(api, headers or admin_headers(), car_id=car_id,
                          handling_road_id=handling_road_id, status="CLOSED")
    assert len(rows) == 1, f"expected exactly one CLOSED segment, got {len(rows)}"
    return rows[0]


def ledger_entries(api, headers: Optional[Dict[str, str]] = None,
                   **filters) -> List[Dict[str, Any]]:
    data = validate_success(api.list_ledger_entries(headers or admin_headers(), params=filters))
    return data if isinstance(data, list) else data["items"]


BOOTSTRAP_CLOCK = "2026-08-01T00:00:00Z"
DELIVERY_OUT_AT = "2026-08-24T00:00:00Z"
RETURN_AT_11464 = "2026-08-28T00:00:00Z"
AUGUST_MONTH = "2026-08"
AUGUST_END = "2026-09-01T00:00:00Z"


def standard_world(api, extra_roads=(), car_type_payload=None,
                   bootstrap_clock: str = BOOTSTRAP_CLOCK,
                   register_first_car: bool = True) -> World:
    """Two roads, one PER_DIEM rate book, one junction and one CX-owned car."""
    world = World(api)
    set_clock(api, bootstrap_clock, world)
    register_railroad(api, "BN", world)
    register_railroad(api, "CX", world)
    for mark in extra_roads:
        register_railroad(api, mark, world)
    register_car_type(api, world,
                      payload=car_type_payload or f.car_type_payload())
    register_junction(api, "JCT-CHI", world.cx, world.bn, world)
    if register_first_car:
        register_car(api, "CX 100001", world.xm, world.cx, world=world)
    return world


def deliver_out(api, world: World, car_id: str, interchange_at: str, odometer_miles: int,
                load_status: str = "LOADED", junction_id: Optional[str] = None):
    """CX hands the car to BN, closing CX's segment and opening BN's."""
    set_clock(api, interchange_at, world)
    return capture_delivery(api, car_id, junction_id or world.jct, world.cx, world.bn,
                            interchange_at, odometer_miles, load_status, world=world)


def deliver_back(api, world: World, car_id: str, interchange_at: str, odometer_miles: int,
                 load_status: str = "LOADED", junction_id: Optional[str] = None):
    """BN returns the car to its owner CX, closing BN's segment and pricing it."""
    set_clock(api, interchange_at, world)
    return capture_delivery(api, car_id, junction_id or world.jct, world.bn, world.cx,
                            interchange_at, odometer_miles, load_status, world=world)


def open_segment_world(api, interchange_at: str = DELIVERY_OUT_AT,
                       odometer_miles: int = 1000, load_status: str = "LOADED"):
    """One OPEN BN segment on a CX-owned car."""
    world = standard_world(api)
    deliver_out(api, world, world.car, interchange_at, odometer_miles, load_status)
    return world, open_movement_of(api, world.car, world.bn, world.accountant(world.bn))


def closed_segment_world(api, world: Optional[World] = None,
                         out_at: str = DELIVERY_OUT_AT, out_odometer: int = 1000,
                         back_at: str = RETURN_AT_11464, back_odometer: int = 1240,
                         load_status: str = "LOADED"):
    """A single CLOSED BN segment.  The default figures price at 11464 cents."""
    world = world or standard_world(api)
    deliver_out(api, world, world.car, out_at, out_odometer, load_status)
    deliver_back(api, world, world.car, back_at, back_odometer, load_status)
    return world, closed_movement_of(api, world.car, world.bn, world.accountant(world.bn))


AUGUST_BOOTSTRAP = "2026-08-20T00:00:00Z"
OUT_76H = "2026-08-26T06:00:00Z"
BACK_76H = "2026-08-29T10:00:00Z"


def segment_76h_world(api):
    """A CLOSED BN segment of 76.00 elapsed hours pricing at 8775 cents."""
    world = standard_world(api, bootstrap_clock=AUGUST_BOOTSTRAP)
    return closed_segment_world(
        api, world=world, out_at=OUT_76H, out_odometer=12000,
        back_at=BACK_76H, back_odometer=12415,
    )


def bad_order_band_world(api, report_at: str = "2026-08-25T00:00:00Z",
                         release_at: str = "2026-08-26T00:00:00Z"):
    """The 11464 segment carrying a closed 24.00-hour bad-order band."""
    world = standard_world(api)
    deliver_out(api, world, world.car, DELIVERY_OUT_AT, 1000)
    set_clock(api, report_at, world)
    validate_success(api.report_bad_order(world.car, f.bad_order_payload(report_at),
                                          world.clerk(world.bn)))
    set_clock(api, release_at, world)
    validate_success(api.release_to_service(world.car, f.release_payload(release_at),
                                            world.clerk(world.bn)))
    deliver_back(api, world, world.car, RETURN_AT_11464, 1240)
    return world, closed_movement_of(api, world.car, world.bn, world.accountant(world.bn))


def rejection_band_world(api, reject_at: str = "2026-08-25T00:00:00Z",
                         release_at: str = "2026-08-26T00:00:00Z"):
    """The 11464 segment whose bad-order band was opened by a REJECTION event."""
    world = standard_world(api)
    deliver_out(api, world, world.car, DELIVERY_OUT_AT, 1000)
    set_clock(api, reject_at, world)
    rejection = capture_rejection(api, world.car, world.jct, world.bn, world.cx,
                                  reject_at, 1000, "LOADED", world=world)
    set_clock(api, release_at, world)
    validate_success(api.release_to_service(world.car, f.release_payload(release_at),
                                            world.clerk(world.bn)))
    deliver_back(api, world, world.car, RETURN_AT_11464, 1240)
    movement = closed_movement_of(api, world.car, world.bn, world.accountant(world.bn))
    return world, movement, rejection


def hourly_world(api):
    """An HOURLY-rated segment of 54.00 elapsed hours pricing at 7712 cents."""
    world = World(api)
    set_clock(api, BOOTSTRAP_CLOCK, world)
    register_railroad(api, "BN", world)
    register_railroad(api, "CX", world)
    register_car_type(api, world, payload=f.hourly_car_type_payload())
    register_junction(api, "JCT-CHI", world.cx, world.bn, world)
    car_id = register_car(api, "CX 200001", world.car_types["HR"], world.cx, world=world)
    set_clock(api, DELIVERY_OUT_AT, world)
    capture_delivery(api, car_id, world.jct, world.cx, world.bn, DELIVERY_OUT_AT,
                     500, "EMPTY", world=world)
    set_clock(api, "2026-08-26T06:00:00Z", world)
    capture_delivery(api, car_id, world.jct, world.bn, world.cx,
                     "2026-08-26T06:00:00Z", 590, "EMPTY", world=world)
    movement = closed_movement_of(api, car_id, world.bn, world.accountant(world.bn))
    return world, car_id, movement


def three_line_world(api, cars: int = 3, bad_order_car1: bool = False,
                     world: Optional[World] = None):
    """CLOSED BN segments pricing at 8775, 5233 and 4700 cents.

    ``cars=2`` stops after the 8775 and 5233 lines, which is the pair whose
    mileage components round per line to 975 and 533.  ``bad_order_car1`` opens
    and closes a 36.00-hour bad-order band inside car1's segment.
    """
    world = world or standard_world(api, bootstrap_clock=AUGUST_BOOTSTRAP,
                                    register_first_car=False)
    car1 = register_car(api, "CX 100001", world.xm, world.cx, world=world)
    car2 = register_car(api, "CX 100002", world.xm, world.cx, world=world)
    car3 = register_car(api, "CX 100003", world.xm, world.cx, world=world) if cars >= 3 else None
    set_clock(api, OUT_76H, world)
    capture_delivery(api, car1, world.jct, world.cx, world.bn, OUT_76H,
                     12000, "LOADED", world=world)
    capture_delivery(api, car2, world.jct, world.cx, world.bn, OUT_76H,
                     5000, "LOADED", world=world)
    if car3 is not None:
        capture_delivery(api, car3, world.jct, world.cx, world.bn, OUT_76H,
                         3000, "EMPTY", world=world)
    if bad_order_car1:
        set_clock(api, "2026-08-27T00:00:00Z", world)
        validate_success(api.report_bad_order(
            car1, f.bad_order_payload("2026-08-27T00:00:00Z"), world.clerk(world.bn)))
    set_clock(api, "2026-08-27T18:00:00Z", world)
    capture_delivery(api, car2, world.jct, world.bn, world.cx, "2026-08-27T18:00:00Z",
                     5227, "LOADED", world=world)
    if car3 is not None:
        set_clock(api, "2026-08-28T06:00:00Z", world)
        capture_delivery(api, car3, world.jct, world.bn, world.cx,
                         "2026-08-28T06:00:00Z", 3000, "EMPTY", world=world)
    if bad_order_car1:
        set_clock(api, "2026-08-28T12:00:00Z", world)
        validate_success(api.release_to_service(
            car1, f.release_payload("2026-08-28T12:00:00Z"), world.clerk(world.bn)))
    set_clock(api, BACK_76H, world)
    capture_delivery(api, car1, world.jct, world.bn, world.cx, BACK_76H,
                     12415, "LOADED", world=world)
    ids = [car1, car2] + ([car3] if car3 is not None else [])
    movements = {
        car_id: closed_movement_of(api, car_id, world.bn, world.accountant(world.bn))
        for car_id in ids
    }
    return world, tuple(ids), movements


def open_cycle(api, world: World, payer_road_id: Optional[str] = None,
               payee_road_id: Optional[str] = None, period_month: str = AUGUST_MONTH,
               clock: Optional[str] = AUGUST_END) -> Dict[str, Any]:
    """Open a monthly cycle, by default BN paying CX for August 2026."""
    payer = payer_road_id or world.bn
    payee = payee_road_id or world.cx
    if clock is not None:
        set_clock(api, clock, world)
    return validate_success(
        api.create_settlement_cycle(
            f.settlement_cycle_payload(payer, payee, period_month),
            world.accountant(payee),
        ),
        201,
    )


def computed_cycle(api, world: World, payer_road_id: Optional[str] = None,
                   payee_road_id: Optional[str] = None,
                   period_month: str = AUGUST_MONTH, clock: Optional[str] = AUGUST_END,
                   variant: Optional[str] = None):
    """Open and compute a cycle; only the payee road may compute."""
    payee = payee_road_id or world.cx
    cycle = open_cycle(api, world, payer_road_id, payee, period_month, clock)
    payload = {"variant": variant} if variant else {}
    computed = validate_success(
        api.compute_settlement_cycle(cycle["id"], payload, world.accountant(payee))
    )
    return cycle, computed


def exchanged_cycle(api, world: World, payer_road_id: Optional[str] = None,
                    payee_road_id: Optional[str] = None,
                    period_month: str = AUGUST_MONTH, clock: Optional[str] = AUGUST_END):
    """Open, compute and exchange a cycle; exchange opens the dispute window."""
    payee = payee_road_id or world.cx
    cycle, computed = computed_cycle(api, world, payer_road_id, payee, period_month, clock)
    exchanged = validate_success(
        api.exchange_settlement_cycle(cycle["id"], {}, world.accountant(payee))
    )
    return cycle, computed, exchanged


def settled_cycle(api, world: World, payer_road_id: Optional[str] = None,
                  payee_road_id: Optional[str] = None,
                  period_month: str = AUGUST_MONTH, clock: Optional[str] = AUGUST_END):
    """Open, compute, exchange and settle a cycle; only the payer road settles."""
    payer = payer_road_id or world.bn
    payee = payee_road_id or world.cx
    cycle, computed, exchanged = exchanged_cycle(api, world, payer, payee, period_month, clock)
    settled = validate_success(
        api.settle_settlement_cycle(cycle["id"], {}, world.accountant(payer))
    )
    return cycle, computed, exchanged, settled


def file_reclaim(api, world: World, movement: Dict[str, Any], reason: str,
                 window_from: str, window_to: str, road_id: Optional[str] = None,
                 **kwargs) -> Dict[str, Any]:
    """File a reclaim as the segment's handling road, echoing its version."""
    filer = road_id or movement["handling_road_id"]
    return validate_success(
        api.create_reclaim_claim(
            f.reclaim_payload(movement["id"], reason, window_from, window_to,
                              movement["version"], **kwargs),
            world.accountant(filer),
        ),
        201,
    )


def allow_reclaim(api, world: World, claim: Dict[str, Any], payload=None,
                  road_id: Optional[str] = None) -> Dict[str, Any]:
    """Allow a reclaim as the owner road named in ``against_road_id``."""
    decider = road_id or claim["against_road_id"]
    return validate_success(
        api.allow_reclaim_claim(claim["id"], payload or {}, world.accountant(decider))
    )


def bad_order_on_bn_world(api, out_at: str = DELIVERY_OUT_AT, out_odometer: int = 1000,
                          report_at: str = "2026-08-25T00:00:00Z",
                          defect_code: str = "R-114"):
    """A CX-owned car sitting bad-ordered in BN's custody."""
    world = standard_world(api)
    deliver_out(api, world, world.car, out_at, out_odometer)
    set_clock(api, report_at, world)
    car = validate_success(
        api.report_bad_order(world.car, f.bad_order_payload(report_at, defect_code),
                             world.clerk(world.bn))
    )
    return world, car


def draft_repair_bill(api, world: World, car_id: str, billing_road_id: str,
                      defect_class: str, defect_occurred_at: str, labor_hours: float,
                      material_cents: int, defect_code: str = "R-114",
                      **kwargs) -> Dict[str, Any]:
    """Draft a repair bill in the repairing road's own name."""
    return validate_success(
        api.create_repair_bill(
            f.repair_bill_payload(car_id, billing_road_id, defect_code, defect_class,
                                  defect_occurred_at, labor_hours, material_cents,
                                  **kwargs),
            world.repair(billing_road_id),
        ),
        201,
    )


def submitted_repair_bill(api, world: World, car_id: str, billing_road_id: str,
                          defect_class: str, defect_occurred_at: str, labor_hours: float,
                          material_cents: int, **kwargs):
    """Draft and submit a repair bill, which is where responsibility is decided."""
    draft = draft_repair_bill(api, world, car_id, billing_road_id, defect_class,
                              defect_occurred_at, labor_hours, material_cents, **kwargs)
    submitted = validate_success(
        api.submit_repair_bill(draft["id"], {}, world.repair(billing_road_id))
    )
    return draft, submitted


def two_junction_world(api):
    """Two junctions between the same pair of roads, plus two CX-owned cars.

    Both cars are handed to BN at JCT-CHI at 2026-08-24T00:00:00Z with an
    obligation to come back empty at JCT-CHI by 2026-08-27T00:00:00Z, so one can
    honour the prescribed junction and the other can miss it.
    """
    world = standard_world(api, register_first_car=False)
    register_junction(api, "JCT-STL", world.cx, world.bn, world)
    car1 = register_car(api, "CX 100011", world.xm, world.cx, world=world)
    car2 = register_car(api, "CX 100012", world.xm, world.cx, world=world)
    set_clock(api, DELIVERY_OUT_AT, world)
    capture_delivery(api, car1, world.jct, world.cx, world.bn, DELIVERY_OUT_AT,
                     500, "LOADED", world=world)
    capture_delivery(api, car2, world.jct, world.cx, world.bn, DELIVERY_OUT_AT,
                     500, "LOADED", world=world)
    for car_id in (car1, car2):
        validate_success(
            api.issue_empty_routing_obligation(
                car_id,
                f.routing_obligation_payload(world.jct, DELIVERY_OUT_AT,
                                             "2026-08-27T00:00:00Z"),
                world.owner(world.cx),
            )
        )
    return world, car1, car2


def timestamp_amend_world(api, final_clock: str = "2026-08-31T00:00:00Z"):
    """Three segments whose first shared boundary a TIMESTAMP_AMEND will move.

    The bootstrap segment runs from registration at 2026-08-20T00:00:00Z, BN's
    segment from 2026-08-26T06:00:00Z to 2026-08-29T10:00:00Z, and the car's
    second home segment is still OPEN when ``final_clock`` is reached.
    """
    world = standard_world(api, bootstrap_clock=AUGUST_BOOTSTRAP)
    set_clock(api, BACK_76H, world)
    out_event = capture_delivery(api, world.car, world.jct, world.cx, world.bn,
                                 OUT_76H, 12000, "LOADED", world=world)
    capture_delivery(api, world.car, world.jct, world.bn, world.cx,
                     BACK_76H, 12415, "LOADED", world=world)
    set_clock(api, final_clock, world)
    home = closed_movement_of(api, world.car, world.cx, world.accountant(world.cx))
    away = closed_movement_of(api, world.car, world.bn, world.accountant(world.bn))
    return world, out_event, home, away


def void_cascade_world(api):
    """The full five-layer world: a settled cycle resting on a voidable rejection."""
    world, movement, rejection = rejection_band_world(api)
    claim = file_reclaim(api, world, movement, "BAD_ORDER",
                         "2026-08-25T00:00:00Z", "2026-08-26T00:00:00Z")
    allow_reclaim(api, world, claim)
    movement = closed_movement_of(api, world.car, world.bn, world.accountant(world.bn))
    cycle, computed, exchanged, settled = settled_cycle(api, world)
    return world, movement, rejection, claim, settled


def issue_embargo(api, world: World, issuing_road_id: str, junction_id: str,
                  effective_from: str, effective_to: str,
                  car_type_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """File an embargo order in the issuing road's own name."""
    return validate_success(
        api.create_embargo_order(
            f.embargo_payload(issuing_road_id, junction_id, effective_from,
                              effective_to, car_type_id=car_type_id, **kwargs),
            world.clerk(issuing_road_id),
        ),
        201,
    )


def file_dispute(api, world: World, cycle: Dict[str, Any], dispute_reason: str,
                 disputed_amount_cents: int, movement_id: Optional[str] = None,
                 repair_bill_id: Optional[str] = None,
                 filer_road_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """File a dispute as the cycle's payer, echoing the cycle's current version."""
    filer = filer_road_id or cycle["payer_road_id"]
    return validate_success(
        api.create_dispute(
            f.dispute_payload(cycle["id"], dispute_reason, disputed_amount_cents,
                              cycle["version"], movement_id=movement_id,
                              repair_bill_id=repair_bill_id, **kwargs),
            world.accountant(filer),
        ),
        201,
    )


def read_cycle(api, world: World, cycle_id: str,
               road_id: Optional[str] = None) -> Dict[str, Any]:
    return validate_success(
        api.get_settlement_cycle(cycle_id, world.accountant(road_id or world.cx))
    )


def read_movement(api, world: World, movement_id: str,
                  road_id: Optional[str] = None) -> Dict[str, Any]:
    return validate_success(
        api.get_movement(movement_id, world.accountant(road_id or world.bn))
    )


def exposure(api, world: World, road_id: str, variant: Optional[str] = None,
             headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    params = {"variant": variant} if variant else None
    return validate_success(
        api.get_railroad_exposure(road_id, headers or admin_headers(), params=params)
    )


def confirmed_correction(api, world: World, payload: Dict[str, Any],
                         filer_road_id: str, counterparty_road_id: str):
    """File a correction as one road and confirm it as the named counterparty."""
    filed = validate_success(
        api.create_correction_request(payload, world.clerk(filer_road_id)), 201
    )
    confirmed = validate_success(
        api.confirm_correction_request(filed["id"], {}, world.clerk(counterparty_road_id))
    )
    return filed, confirmed
