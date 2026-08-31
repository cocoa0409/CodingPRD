"""Composite setup helpers.

Every test starts against an empty database, so each fixture builds its whole
precondition chain from PRD-declared endpoints only.  The helpers are layered:
single-record creators first, then the multi-step pipelines that most of the
interesting claims need (receive a core, quote the order, inspect and accept
it, schedule and deliver it, put it into service, fail it and claim it).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import FOUR_BANDS, ONE_BAND, TEST_DEFAULTS
from .factories import (
    asset_payload, bench_payload, bench_reservation_payload,
    clearance_standard_payload, core_unit_payload, customer_payload,
    inspection_payload, installation_payload, manual_credit_note_payload,
    measurement_payload, part_line_payload, rebuild_order_payload,
    vibration_reading_payload, warranty_claim_payload,
)
from .test_users import (
    ADMIN_1, ENG_1, PLANNER_1, make_customer_headers, make_inspector_headers,
    make_reliability_engineer_headers, make_shop_admin_headers,
)

CANONICAL_MEASUREMENTS = (
    ("BORE", 85), ("JOURNAL", 58), ("HOUSING_FIT", 44), ("END_PLAY", 160),
)


# --------------------------------------------------------------------------
# Tier 0: single-record creators and reads
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the logical shop clock. Every system-stamped instant follows it."""
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN_1))


def create_customer(**overrides) -> dict:
    return get_success_data(api.create_customer(customer_payload(**overrides), ADMIN_1))


def create_asset(customer_id, **overrides) -> dict:
    return get_success_data(
        api.create_asset(customer_id, asset_payload(**overrides), ADMIN_1)
    )


def create_standard(**overrides) -> dict:
    return get_success_data(
        api.create_clearance_standard(clearance_standard_payload(**overrides), ADMIN_1)
    )


def create_bench(**overrides) -> dict:
    return get_success_data(api.create_bench(bench_payload(**overrides), ADMIN_1))


def create_core(customer_id, standard_id, **overrides) -> dict:
    return get_success_data(
        api.create_core_unit(core_unit_payload(customer_id, standard_id, **overrides), ADMIN_1)
    )


def create_order(customer_id, core_id, asset_id, **overrides) -> dict:
    return get_success_data(
        api.create_rebuild_order(
            rebuild_order_payload(customer_id, core_id, asset_id, **overrides), PLANNER_1
        )
    )


def read_customer(customer_id) -> dict:
    return get_success_data(api.get_customer(customer_id, ADMIN_1))


def read_asset(asset_id) -> dict:
    return get_success_data(api.get_asset(asset_id, ADMIN_1))


def read_core(core_id) -> dict:
    return get_success_data(api.get_core_unit(core_id, ADMIN_1))


def read_order(order_id) -> dict:
    return get_success_data(api.get_rebuild_order(order_id, PLANNER_1))


def read_quote(order_id) -> dict:
    return get_success_data(api.get_quote(order_id, PLANNER_1))


def read_bench(bench_id) -> dict:
    return get_success_data(api.get_bench(bench_id, PLANNER_1))


def read_inspection(inspection_id) -> dict:
    return get_success_data(api.get_inspection(inspection_id, ADMIN_1))


def read_installation(installation_id) -> dict:
    return get_success_data(api.get_installation(installation_id, ADMIN_1))


def read_claim(claim_id) -> dict:
    return get_success_data(api.get_warranty_claim(claim_id, ADMIN_1))


def read_credit_note(note_id) -> dict:
    return get_success_data(api.get_credit_note(note_id, ADMIN_1))


def order_version(order_id) -> int:
    return read_order(order_id)["version"]


def customer_version(customer_id) -> int:
    return read_customer(customer_id)["version"]


def asset_version(asset_id) -> int:
    return read_asset(asset_id)["version"]


# --------------------------------------------------------------------------
# Tier 1: state progression on a single record
# --------------------------------------------------------------------------

def add_part_line(order_id, expected_order_version=None, **overrides) -> dict:
    """Propose a part line, reading the order's current version when the
    caller does not pin one explicitly."""
    version = (expected_order_version if expected_order_version is not None
               else order_version(order_id))
    return get_success_data(
        api.create_part_line(order_id, part_line_payload(version, **overrides), PLANNER_1)
    )


def submit_part_line(part_line_id) -> dict:
    return get_success_data(
        api.advance_part_line(part_line_id, {"action": "SUBMIT"}, PLANNER_1)
    )


def decide_part_line(part_line_id, customer_id, decision="APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(
        api.decide_part_line(part_line_id, payload, make_customer_headers(customer_id))
    )


def add_approved_part_line(order_id, customer_id, **overrides) -> dict:
    """Propose a line, put it in front of the account and have it approved."""
    line = add_part_line(order_id, **overrides)
    submit_part_line(line["id"])
    return decide_part_line(line["id"], customer_id, "APPROVE")


def order_action(order_id, action) -> dict:
    return get_success_data(
        api.advance_rebuild_order(order_id, {"action": action}, PLANNER_1)
    )


def create_reading(asset_id, **overrides) -> dict:
    return get_success_data(
        api.create_vibration_reading(vibration_reading_payload(asset_id, **overrides), ENG_1)
    )


def open_inspection(order_id, user_id="insp-1", **overrides) -> dict:
    return get_success_data(
        api.create_inspection(inspection_payload(order_id, **overrides),
                              make_inspector_headers(user_id))
    )


def add_measurement(inspection_id, feature_code, measured_um, user_id="insp-1") -> dict:
    return get_success_data(
        api.create_measurement(inspection_id,
                               measurement_payload(feature_code, measured_um),
                               make_inspector_headers(user_id))
    )


def submit_inspection(inspection_id, user_id="insp-1", **overrides) -> dict:
    payload = {"action": "SUBMIT"}
    payload.update(overrides)
    return get_success_data(
        api.advance_inspection(inspection_id, payload, make_inspector_headers(user_id))
    )


def accept_inspection(inspection_id, user_id="insp-2") -> dict:
    return get_success_data(
        api.advance_inspection(inspection_id, {"action": "ACCEPT"},
                               make_inspector_headers(user_id))
    )


def return_inspection(inspection_id, return_reason="re-shoot the bore at temperature",
                      user_id="eng-1") -> dict:
    return get_success_data(
        api.advance_inspection(inspection_id,
                               {"action": "RETURN", "return_reason": return_reason},
                               make_reliability_engineer_headers(user_id))
    )


def reopen_inspection(inspection_id, user_id="insp-1") -> dict:
    return get_success_data(
        api.advance_inspection(inspection_id, {"action": "REOPEN"},
                               make_inspector_headers(user_id))
    )


def reserve_bench(order_id, bench_id, window_start_at, window_end_at, **overrides) -> dict:
    return get_success_data(
        api.create_bench_reservation(
            bench_reservation_payload(order_id, bench_id, window_start_at,
                                      window_end_at, **overrides),
            PLANNER_1,
        )
    )


def confirm_reservation(reservation_id) -> dict:
    return get_success_data(
        api.advance_bench_reservation(reservation_id, {"action": "CONFIRM"}, PLANNER_1)
    )


def release_reservation(reservation_id) -> dict:
    return get_success_data(
        api.advance_bench_reservation(reservation_id, {"action": "RELEASE"}, PLANNER_1)
    )


def install_unit(core_id, asset_id, order_id, expected_asset_version=None) -> dict:
    version = (expected_asset_version if expected_asset_version is not None
               else asset_version(asset_id))
    return get_success_data(
        api.create_installation(
            installation_payload(core_id, asset_id, order_id, version), ADMIN_1
        )
    )


def record_hours(installation_id, run_hours_delta) -> dict:
    return get_success_data(
        api.advance_installation(installation_id,
                                 {"action": "RECORD_HOURS",
                                  "run_hours_delta": run_hours_delta}, ADMIN_1)
    )


def fail_installation(installation_id) -> dict:
    return get_success_data(
        api.advance_installation(installation_id, {"action": "FAIL"}, ADMIN_1)
    )


def remove_installation(installation_id) -> dict:
    return get_success_data(
        api.advance_installation(installation_id, {"action": "REMOVE"}, ADMIN_1)
    )


def file_claim(installation_id, customer_id, **overrides) -> dict:
    return get_success_data(
        api.create_warranty_claim(warranty_claim_payload(installation_id, **overrides),
                                  make_customer_headers(customer_id))
    )


def claim_action(claim_id, action, headers=None, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return get_success_data(
        api.advance_warranty_claim(claim_id, payload, headers or ADMIN_1)
    )


def adjudicate_claim(claim_id, decision="APPROVE", user_id="admin-1", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(
        api.adjudicate_warranty_claim(claim_id, payload, make_shop_admin_headers(user_id))
    )


def post_manual_note(customer_id, amount_cents, memo="goodwill freight credit",
                     expected_customer_version=None) -> dict:
    version = (expected_customer_version if expected_customer_version is not None
               else customer_version(customer_id))
    return get_success_data(
        api.create_manual_credit_note(
            customer_id, manual_credit_note_payload(amount_cents, version, memo=memo),
            ADMIN_1,
        )
    )


def void_note(note_id, void_reason="issued against the wrong account") -> dict:
    return get_success_data(
        api.void_credit_note(note_id, {"void_reason": void_reason}, ADMIN_1)
    )


def credit_notes(**params):
    """Return (rows, meta) from the filtered ledger list."""
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(api.list_credit_notes(ADMIN_1, params=params or None))


# --------------------------------------------------------------------------
# Tier 2: entity hierarchy - the recurring five-record base
# --------------------------------------------------------------------------

def setup_shop(account_code="NGM-001", customer_name="Northgate Mill",
               asset_tag="CONV-04-GBX", criticality="STANDARD",
               duty_class="CONTINUOUS", model_code=None, feature_bands=ONE_BAND,
               standard_overrides=None, serial_no="SN-77001", rebuild_count=0,
               declared_condition_grade="GRADE_B", labor_hours=None,
               bench_code=None, parallel_slots=1, cleanroom=False,
               with_asset=True, with_order=True) -> dict:
    """Account + machine + reman spec + received core + open work order.

    Returns a mutable world dict keyed customer / asset / standard / core /
    order / bench, which the later pipeline helpers advance in place.
    """
    world = {}
    world["customer"] = create_customer(name=customer_name, account_code=account_code)
    cust_id = world["customer"]["id"]

    if with_asset:
        world["asset"] = create_asset(cust_id, asset_tag=asset_tag,
                                      criticality=criticality, duty_class=duty_class)

    std_kwargs = {"feature_bands": feature_bands}
    if model_code is not None:
        std_kwargs["model_code"] = model_code
    if standard_overrides:
        std_kwargs.update(standard_overrides)
    world["standard"] = create_standard(**std_kwargs)

    if bench_code is not None:
        world["bench"] = create_bench(bench_code=bench_code,
                                      parallel_slots=parallel_slots,
                                      cleanroom=cleanroom)

    world["core"] = create_core(cust_id, world["standard"]["id"], serial_no=serial_no,
                               rebuild_count=rebuild_count,
                               declared_condition_grade=declared_condition_grade)

    if with_order and with_asset:
        order_kwargs = {}
        if labor_hours is not None:
            order_kwargs["labor_hours"] = labor_hours
        world["order"] = create_order(cust_id, world["core"]["id"],
                                      world["asset"]["id"], **order_kwargs)
    return world


def setup_canonical_shop(account_code="NGM-001", criticality="STANDARD",
                         feature_bands=FOUR_BANDS, serial_no="SN-77001",
                         rebuild_count=1, declared_condition_grade="GRADE_D",
                         labor_hours=6.5, bench_code=None, **overrides) -> dict:
    """The recurring canonical fixture: a rebuild_count 1 core declared
    GRADE_D against the four-band spec, on a 6.5-hour order."""
    return setup_shop(account_code=account_code, criticality=criticality,
                      feature_bands=feature_bands, serial_no=serial_no,
                      rebuild_count=rebuild_count,
                      declared_condition_grade=declared_condition_grade,
                      labor_hours=labor_hours, bench_code=bench_code, **overrides)


# --------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# --------------------------------------------------------------------------

def quote_order(world, part_overrides=None) -> dict:
    """Add one approved OEM part line and move the order DRAFT -> QUOTED."""
    order_id = world["order"]["id"]
    line = add_approved_part_line(order_id, world["customer"]["id"],
                                  **(part_overrides or {}))
    world["part_line"] = line
    world["order"] = order_action(order_id, "QUOTE")
    return world


def inspect_order(world, measurements=CANONICAL_MEASUREMENTS,
                  reading_overrides=None, inspection_overrides=None,
                  submitter="insp-1", acceptor="insp-2",
                  submit=True, accept=True, with_reading=True) -> dict:
    """File a route reading, open a bench inspection, capture metrology and
    optionally submit and accept it."""
    order_id = world["order"]["id"]
    insp_kwargs = dict(inspection_overrides or {})
    if with_reading:
        world["reading"] = create_reading(world["asset"]["id"], **(reading_overrides or {}))
        insp_kwargs.setdefault("linked_vibration_reading_id", world["reading"]["id"])

    world["inspection"] = open_inspection(order_id, user_id=submitter, **insp_kwargs)
    insp_id = world["inspection"]["id"]
    world["measurements"] = [
        add_measurement(insp_id, code, um, user_id=submitter) for code, um in measurements
    ]
    if submit:
        world["inspection"] = submit_inspection(insp_id, user_id=submitter)
    if submit and accept:
        world["inspection"] = accept_inspection(insp_id, user_id=acceptor)
    world["order"] = read_order(order_id)
    world["core"] = read_core(world["core"]["id"])
    return world


def schedule_order(world, window_start_at="2026-08-03T08:00:00Z",
                   window_end_at="2026-08-03T12:00:00Z") -> dict:
    """Hold and confirm a bench window, then move QUOTED -> SCHEDULED."""
    if "bench" not in world:
        world["bench"] = create_bench(bench_code="B-1")
    world["reservation"] = reserve_bench(world["order"]["id"], world["bench"]["id"],
                                         window_start_at, window_end_at)
    confirm_reservation(world["reservation"]["id"])
    world["order"] = order_action(world["order"]["id"], "SCHEDULE")
    return world


def run_order_to(world, target="DELIVERED") -> dict:
    """Drive the work dimension SCHEDULED -> IN_PROGRESS -> COMPLETED -> DELIVERED."""
    sequence = ["IN_PROGRESS", "COMPLETED", "DELIVERED"]
    actions = {"IN_PROGRESS": "START", "COMPLETED": "COMPLETE", "DELIVERED": "DELIVER"}
    for state in sequence:
        world["order"] = order_action(world["order"]["id"], actions[state])
        if state == target:
            break
    world["core"] = read_core(world["core"]["id"])
    return world


def setup_delivered_pipeline(account_code="NGM-001", criticality="STANDARD",
                             feature_bands=ONE_BAND,
                             measurements=(("BORE", 85),),
                             standard_overrides=None, inspection_overrides=None,
                             reading_overrides=None, serial_no="SN-77001",
                             rebuild_count=1, labor_hours=6.5,
                             bench_code="B-1", stop_at="DELIVERED") -> dict:
    """Account through to a delivered rebuild: quote, inspect, accept,
    schedule, start, complete and deliver."""
    world = setup_canonical_shop(account_code=account_code, criticality=criticality,
                                 feature_bands=feature_bands, serial_no=serial_no,
                                 rebuild_count=rebuild_count, labor_hours=labor_hours,
                                 bench_code=bench_code,
                                 standard_overrides=standard_overrides)
    quote_order(world)
    inspect_order(world, measurements=measurements,
                  reading_overrides=reading_overrides,
                  inspection_overrides=inspection_overrides)
    schedule_order(world)
    run_order_to(world, target=stop_at)
    return world


# --------------------------------------------------------------------------
# Tier 4: in-service and warranty state
# --------------------------------------------------------------------------

def setup_installed_unit(install_at="2026-08-05T00:00:00Z", run_hours=None, **kwargs) -> dict:
    """A delivered rebuild put into service on its asset at `install_at`."""
    world = setup_delivered_pipeline(**kwargs)
    set_clock(install_at)
    world["installation"] = install_unit(world["core"]["id"], world["asset"]["id"],
                                         world["order"]["id"])
    if run_hours:
        world["installation"] = record_hours(world["installation"]["id"], run_hours)
    return world


def setup_failed_installation(install_at="2026-08-05T00:00:00Z", run_hours=5200,
                              fail_at="2027-02-01T00:00:00Z", **kwargs) -> dict:
    """An in-service unit run for `run_hours` and then failed at `fail_at`."""
    world = setup_installed_unit(install_at=install_at, run_hours=run_hours, **kwargs)
    set_clock(fail_at)
    world["installation"] = fail_installation(world["installation"]["id"])
    return world


def setup_claimed_installation(claimed_reason="outer race spall at 5200 hours",
                               **kwargs) -> dict:
    """A failed in-service unit with its warranty claim filed and frozen."""
    world = setup_failed_installation(**kwargs)
    world["claim"] = file_claim(world["installation"]["id"], world["customer"]["id"],
                                claimed_reason=claimed_reason)
    return world
