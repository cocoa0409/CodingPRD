"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds all of
its preconditions from scratch through the endpoints the PRD declares. Setup
calls go through the lenient `get_success_data` validator so a broken
precondition surfaces as a setup failure rather than as a confusing assertion.

Ownership-gated calls always use the per-instance header builders from
`test_users` — `make_client_owner_headers(vineyard["id"])` for a
countersignature, `make_crew_supervisor_headers(crew["id"])` for a work-order
start, completion or a load dispatch.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import CLOCK_EPOCH
from .test_users import (
    TEST_USERS,
    make_client_owner_headers,
    make_crew_supervisor_headers,
)

VM = TEST_USERS["vineyard_manager_headers"]
VM_ALT = TEST_USERS["vineyard_manager_alt_headers"]
AG = TEST_USERS["agronomist_headers"]
AG_ALT = TEST_USERS["agronomist_alt_headers"]
APP = TEST_USERS["applicator_headers"]
APP_ALT = TEST_USERS["applicator_alt_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CTL = TEST_USERS["controller_headers"]
CTL_ALT = TEST_USERS["controller_alt_headers"]


class Scenario(dict):
    """A dict whose keys are also reachable as attributes."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - debugging aid only
            raise AttributeError(item) from exc

    def __setattr__(self, key, value):
        self[key] = value


# ─── Logical clock ────────────────────────────────────

def set_clock(api, instant: str) -> str:
    """Move the server's logical clock to `instant`."""
    return get_success_data(api.set_clock(instant, VM))


def reset_clock(api) -> str:
    """Return the logical clock to the instant the PRD says it starts at."""
    return set_clock(api, CLOCK_EPOCH)


# ─── Single-resource creators ─────────────────────────

def create_vineyard(api, **overrides) -> dict:
    return get_success_data(api.create_vineyard(f.vineyard_payload(**overrides), VM))


def create_block(api, vineyard_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_block(f.block_payload(vineyard_id, **overrides), VM)
    )


def create_block_b14(api, vineyard_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_block(f.block_payload_b14(vineyard_id, **overrides), VM)
    )


def create_block_b16(api, vineyard_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_block(f.block_payload_b16(vineyard_id, **overrides), VM)
    )


def create_contract(api, vineyard_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_contract(f.contract_payload(vineyard_id, **overrides), VM)
    )


def enroll_block(api, contract_id: str, block_id: str, contracted_acres: float,
                 **overrides) -> dict:
    """Enroll one block. Returns the UPDATED BLOCK, as the PRD specifies."""
    return get_success_data(
        api.enroll_block(
            contract_id,
            f.enroll_block_payload(block_id, contracted_acres, **overrides),
            VM,
        )
    )


def activate_contract(api, contract_id: str, vineyard_id: str, **overrides) -> dict:
    """Countersign as the ranch-owning client (`X-User-ID` is the ranch id)."""
    return get_success_data(
        api.activate_contract(
            contract_id,
            f.activate_contract_payload(**overrides),
            make_client_owner_headers(vineyard_id),
        )
    )


def create_farming_plan(api, block_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_farming_plan(f.farming_plan_payload(block_id, **overrides),
                                headers or VM)
    )


def submit_farming_plan(api, plan_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api.submit_farming_plan(plan_id, f.submit_plan_payload(**overrides),
                                headers or VM)
    )


def approve_farming_plan(api, plan_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api.approve_farming_plan(plan_id, f.approve_plan_payload(**overrides),
                                 headers or CTL)
    )


def return_farming_plan(api, plan_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api.return_farming_plan_for_revision(
            plan_id, f.return_plan_payload(**overrides), headers or CTL
        )
    )


def create_crew(api, **overrides) -> dict:
    return get_success_data(api.create_crew(f.crew_payload(**overrides), VM))


def create_hourly_crew(api, **overrides) -> dict:
    return get_success_data(api.create_crew(f.hourly_crew_payload(**overrides), VM))


def create_work_order(api, block_id, plan_id, crew_id, **overrides) -> dict:
    return get_success_data(
        api.create_work_order(
            f.work_order_payload(block_id, plan_id, crew_id, **overrides), VM
        )
    )


def start_work_order(api, work_order_id: str, crew_id: str) -> dict:
    return get_success_data(
        api.start_work_order(work_order_id, make_crew_supervisor_headers(crew_id))
    )


def complete_work_order(api, work_order_id: str, crew_id: str,
                        actual_vines: int, actual_hours: float) -> dict:
    return get_success_data(
        api.complete_work_order(
            work_order_id,
            f.complete_work_order_payload(actual_vines, actual_hours),
            make_crew_supervisor_headers(crew_id),
        )
    )


def cancel_work_order(api, work_order_id: str, cancel_reason="WEATHER") -> dict:
    return get_success_data(
        api.cancel_work_order(
            work_order_id, f.cancel_work_order_payload(cancel_reason), VM
        )
    )


def advance_payroll(api, work_order_id: str, payroll_action: str,
                    headers=None) -> dict:
    return get_success_data(
        api.advance_payroll(
            work_order_id, f.payroll_payload(payroll_action), headers or CTL
        )
    )


def create_irrigation_event(api, block_id, plan_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_irrigation_event(
            f.irrigation_event_payload(block_id, plan_id, **overrides), headers or VM
        )
    )


def record_irrigation_applied(api, event_id: str, applied_inches: float,
                              headers=None) -> dict:
    return get_success_data(
        api.record_irrigation_applied(
            event_id, f.record_applied_payload(applied_inches), headers or VM
        )
    )


def file_pest_observation(api, block_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_pest_observation(
            block_id, f.pest_observation_payload(**overrides), headers or AG
        )
    )


def create_spray_record(api, block_id, plan_id, observation_id, headers=None,
                        **overrides) -> dict:
    return get_success_data(
        api.create_spray_record(
            f.spray_record_payload(block_id, plan_id, observation_id, **overrides),
            headers or AG,
        )
    )


def apply_spray_record(api, spray_id: str, expected_block_version: int,
                       headers=None, **overrides) -> dict:
    return get_success_data(
        api.apply_spray_record(
            spray_id,
            f.apply_spray_payload(expected_block_version, **overrides),
            headers or APP,
        )
    )


def verify_spray_record(api, spray_id: str, headers=None) -> dict:
    return get_success_data(
        api.verify_spray_record(spray_id, headers or CO, f.verify_spray_payload())
    )


def file_cluster_count_estimate(api, block_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_yield_estimate(
            block_id, f.cluster_count_estimate_payload(**overrides), headers or VM
        )
    )


def file_berry_sample_estimate(api, block_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api.create_yield_estimate(
            block_id, f.berry_sample_estimate_payload(**overrides), headers or VM
        )
    )


def create_delivery_window(api, **overrides) -> dict:
    return get_success_data(
        api.create_delivery_window(f.delivery_window_payload(**overrides), VM)
    )


def book_harvest_load(api, block_id, crew_id, window_id,
                      expected_delivery_window_version, **overrides) -> dict:
    return get_success_data(
        api.create_harvest_load(
            f.harvest_load_payload(
                block_id, crew_id, window_id, expected_delivery_window_version,
                **overrides,
            ),
            VM,
        )
    )


def dispatch_harvest_load(api, load_id: str, crew_id: str,
                          gross_tons_at_dispatch: float = 13.10) -> dict:
    return get_success_data(
        api.dispatch_harvest_load(
            load_id,
            f.dispatch_load_payload(gross_tons_at_dispatch),
            make_crew_supervisor_headers(crew_id),
        )
    )


def receive_harvest_load(api, load_id: str, **overrides) -> dict:
    return get_success_data(
        api.receive_harvest_load(load_id, f.receive_load_payload(**overrides), VM)
    )


def reject_harvest_load(api, load_id: str, rejection_reason="MOG_EXCESS") -> dict:
    return get_success_data(
        api.reject_harvest_load(load_id, f.reject_load_payload(rejection_reason), VM)
    )


def settle_period(api, contract_id: str, settlement_mode: str,
                  period_end_date: str, headers=None) -> dict:
    return get_success_data(
        api.settle_period(
            contract_id,
            f.settle_period_payload(settlement_mode, period_end_date),
            headers or CTL,
        )
    )


# ─── Fresh reads ──────────────────────────────────────

def read_vineyard(api, vineyard_id: str) -> dict:
    return get_success_data(api.get_vineyard(vineyard_id, VM))


def read_block(api, block_id: str) -> dict:
    return get_success_data(api.get_block(block_id, VM))


def read_contract(api, contract_id: str) -> dict:
    return get_success_data(api.get_contract(contract_id, VM))


def read_plan(api, plan_id: str) -> dict:
    return get_success_data(api.get_farming_plan(plan_id, VM))


def read_crew(api, crew_id: str) -> dict:
    return get_success_data(api.get_crew(crew_id, VM))


def read_work_order(api, work_order_id: str) -> dict:
    return get_success_data(api.get_work_order(work_order_id, VM))


def read_irrigation_event(api, event_id: str) -> dict:
    return get_success_data(api.get_irrigation_event(event_id, VM))


def read_spray_record(api, spray_id: str) -> dict:
    return get_success_data(api.get_spray_record(spray_id, VM))


def read_delivery_window(api, window_id: str) -> dict:
    return get_success_data(api.get_delivery_window(window_id, VM))


def read_harvest_load(api, load_id: str) -> dict:
    return get_success_data(api.get_harvest_load(load_id, VM))


def block_version(api, block_id: str) -> int:
    """Re-read the block for the `version` an application must quote back."""
    return read_block(api, block_id)["version"]


def window_version(api, window_id: str) -> int:
    """Re-read the window for the `version` a booking must quote back."""
    return read_delivery_window(api, window_id)["version"]


# ─── Tier 1/2: ranch and block hierarchy ──────────────

def setup_ranch(api, **overrides) -> Scenario:
    """A registered ranch and nothing else."""
    return Scenario(vineyard=create_vineyard(api, **overrides))


def setup_ranch_with_block(api, block_overrides=None, **vineyard_overrides) -> Scenario:
    """A registered ranch carrying one 12.5-acre Cabernet block."""
    s = setup_ranch(api, **vineyard_overrides)
    s.block = create_block(api, s.vineyard["id"], **(block_overrides or {}))
    return s


def setup_enrolled_block(api, contracted_acres=12.5, block_overrides=None,
                         contract_overrides=None, enroll_overrides=None) -> Scenario:
    """Ranch + block + a DRAFT agreement with that block enrolled."""
    s = setup_ranch_with_block(api, block_overrides=block_overrides)
    s.contract = create_contract(api, s.vineyard["id"], **(contract_overrides or {}))
    s.block = enroll_block(api, s.contract["id"], s.block["id"], contracted_acres,
                           **(enroll_overrides or {}))
    s.contract = read_contract(api, s.contract["id"])
    return s


# ─── Tier 3: full lifecycle to an approved plan ────────

def setup_approved_plan(api, contracted_acres=12.5, block_overrides=None,
                        contract_overrides=None, plan_overrides=None,
                        enroll_overrides=None, activate=True, submit=True,
                        approve=True) -> Scenario:
    """The canonical operational preamble.

    Ranch → block → agreement → enrollment → countersignature → plan draft →
    submission → approval. The block's `version` is 3 at the end of the full
    chain: 1 at create, 2 after enrollment, 3 after the approval cascade drives
    it `ESTABLISHING → BEARING`.
    """
    s = setup_enrolled_block(api, contracted_acres=contracted_acres,
                             block_overrides=block_overrides,
                             contract_overrides=contract_overrides,
                             enroll_overrides=enroll_overrides)
    if activate:
        s.contract = activate_contract(api, s.contract["id"], s.vineyard["id"])
    s.plan = create_farming_plan(api, s.block["id"], **(plan_overrides or {}))
    if submit:
        s.plan = submit_farming_plan(api, s.plan["id"])
        if approve:
            s.plan = approve_farming_plan(api, s.plan["id"])
    return s


def setup_operational_block(api, crew_overrides=None, hourly_crew=False,
                            **kwargs) -> Scenario:
    """`setup_approved_plan` plus one registered crew ready to be scheduled."""
    s = setup_approved_plan(api, **kwargs)
    maker = create_hourly_crew if hourly_crew else create_crew
    s.crew = maker(api, **(crew_overrides or {}))
    return s


def setup_three_block_contract(api, plan_overrides=None, contract_overrides=None,
                               activate=True, approve=True) -> Scenario:
    """Three blocks of 12.5, 4.0 and 3.6 contracted acres under one agreement.

    Against a `per_acre_annual_fee` of 950.00 the three contribute 11,875.00,
    3,800.00 and 3,420.00 for a management fee base of 19,095.00, and the
    agreement's `total_contracted_acres` is 20.1. The farming plan is drafted
    and approved on the 12.5-acre block.
    """
    s = setup_ranch(api)
    s.block = create_block(api, s.vineyard["id"])
    s.block_b14 = create_block_b14(api, s.vineyard["id"])
    s.block_b16 = create_block_b16(api, s.vineyard["id"])
    s.contract = create_contract(api, s.vineyard["id"], **(contract_overrides or {}))
    s.block = enroll_block(api, s.contract["id"], s.block["id"], 12.5)
    s.block_b14 = enroll_block(api, s.contract["id"], s.block_b14["id"], 4.0)
    s.block_b16 = enroll_block(api, s.contract["id"], s.block_b16["id"], 3.6)
    if activate:
        s.contract = activate_contract(api, s.contract["id"], s.vineyard["id"])
    else:
        s.contract = read_contract(api, s.contract["id"])
    s.plan = create_farming_plan(api, s.block["id"], **(plan_overrides or {}))
    s.plan = submit_farming_plan(api, s.plan["id"])
    if approve:
        s.plan = approve_farming_plan(api, s.plan["id"])
    return s


# ─── Tier 4: pest scouting and applied sprays ─────────

def setup_recommended_spray(api, s: Scenario, observation_overrides=None,
                            spray_overrides=None) -> Scenario:
    """File a threshold-exceeding observation and a spray recommendation on it."""
    s.observation = file_pest_observation(api, s.block["id"],
                                          **(observation_overrides or {}))
    s.spray = create_spray_record(api, s.block["id"], s.plan["id"],
                                  s.observation["id"], **(spray_overrides or {}))
    return s


def setup_applied_spray(api, s: Scenario, observation_overrides=None,
                        spray_overrides=None, applicator_headers=None) -> Scenario:
    """Recommend and then log an application, quoting the block's live version."""
    s = setup_recommended_spray(api, s, observation_overrides, spray_overrides)
    s.spray = apply_spray_record(api, s.spray["id"], block_version(api, s.block["id"]),
                                 headers=applicator_headers)
    s.block = read_block(api, s.block["id"])
    return s


# ─── Tier 4: yield estimates, windows and loads ───────

def setup_harvest_ready(api, capacity_tons=40.00, estimate_overrides=None,
                        window_overrides=None, **kwargs) -> Scenario:
    """Operational block + a governing cluster-count estimate + an open window.

    The 12.5-acre block's 13,612 frozen vines at 32 clusters per vine and a
    0.42-pound cluster weight give a `governing_estimate_tons` of 91.47.
    """
    s = setup_operational_block(api, **kwargs)
    s.estimate = file_cluster_count_estimate(api, s.block["id"],
                                             **(estimate_overrides or {}))
    s.window = create_delivery_window(api, capacity_tons=capacity_tons,
                                      **(window_overrides or {}))
    s.block = read_block(api, s.block["id"])
    return s


def setup_booked_load(api, s: Scenario, **load_overrides) -> Scenario:
    """Book one load into the scenario's window, quoting its live version."""
    s.load = book_harvest_load(api, s.block["id"], s.crew["id"], s.window["id"],
                               window_version(api, s.window["id"]), **load_overrides)
    return s


def setup_dispatched_load(api, s: Scenario, dispatch_clock="2026-09-14T07:00:00Z",
                          gross_tons_at_dispatch=13.10, **load_overrides) -> Scenario:
    """Book a load, move the clock past the pre-harvest interval, then dispatch."""
    s = setup_booked_load(api, s, **load_overrides)
    if dispatch_clock:
        set_clock(api, dispatch_clock)
    s.load = dispatch_harvest_load(api, s.load["id"], s.crew["id"],
                                   gross_tons_at_dispatch)
    return s


def setup_received_load(api, s: Scenario, receive_overrides=None,
                        **kwargs) -> Scenario:
    """Book, dispatch and then record a winery receipt on one load."""
    s = setup_dispatched_load(api, s, **kwargs)
    s.load = receive_harvest_load(api, s.load["id"], **(receive_overrides or {}))
    return s


# ─── Tier 5: settlement-ready and cascade-ready states ─

def setup_settlement_scenario(api, include_received_load=True) -> Scenario:
    """Three enrolled blocks with a full season of activity on the first one.

    The 12.5-acre block carries 4,343.30 of completed labor, 812.50 of applied
    material and 472.50 of recorded water; the other two blocks carry no
    activity at all and absorb only their overhead share of the 1,000.00 pool.
    The per-block subtotals are therefore 6,250.19, 199.00 and 179.10 for a
    `direct_cost_total` of 6,628.29.

    When `include_received_load` is true a 12.40-net-ton load is received at
    25.1 degrees brix, accruing a 558.00 quality incentive on the agreement.
    """
    s = setup_three_block_contract(api)
    s.crew = create_crew(api)

    # Labor: a 13,000-vine estimate displaced by a 5,200-vine actual of 4,343.30.
    work_order = create_work_order(api, s.block["id"], s.plan["id"], s.crew["id"])
    start_work_order(api, work_order["id"], s.crew["id"])
    s.work_order = complete_work_order(api, work_order["id"], s.crew["id"], 5200, 12.0)

    # Material: an applied spray costing 812.50.
    s = setup_applied_spray(api, s)

    # Water: 0.900 applied inches on 12.5 acres at 42.00 per acre-inch = 472.50.
    event = create_irrigation_event(api, s.block["id"], s.plan["id"])
    s.irrigation = record_irrigation_applied(api, event["id"], 0.900)

    if include_received_load:
        s.estimate = file_cluster_count_estimate(api, s.block["id"])
        s.window = create_delivery_window(api)
        s = setup_received_load(api, s)

    s.block = read_block(api, s.block["id"])
    s.plan = read_plan(api, s.plan["id"])
    s.contract = read_contract(api, s.contract["id"])
    return s


def setup_spray_cascade_scenario(api) -> Scenario:
    """Two scheduled orders on one uncertified crew, poised for a spray sweep.

    The earlier order runs 2026-08-02T14:00Z to 2026-08-03T00:00Z on 13,000
    planned vines over 10.0 hours for an estimate of 10,858.25; the later one
    runs 2026-08-10T14:00Z to 2026-08-10T22:00Z on 3,000 planned vines over 8.0
    hours for an estimate of 2,505.75. The plan therefore stands at a
    `committed_cost` of 13,364.00 and a `remaining_budget` of 1,323.50 before
    any spray is applied. The logical clock is left at 2026-08-02T06:00:00Z so
    an application stamps `rei_clear_at` at 2026-08-05T06:00:00Z.
    """
    s = setup_operational_block(api)
    s.work_order_a = create_work_order(
        api, s.block["id"], s.plan["id"], s.crew["id"],
        task_type="PRUNING",
        scheduled_start="2026-08-02T14:00:00Z",
        scheduled_end="2026-08-03T00:00:00Z",
        planned_vines=13000, planned_hours=10.0,
    )
    s.work_order_b = create_work_order(
        api, s.block["id"], s.plan["id"], s.crew["id"],
        task_type="SUCKERING",
        scheduled_start="2026-08-10T14:00:00Z",
        scheduled_end="2026-08-10T22:00:00Z",
        planned_vines=3000, planned_hours=8.0,
    )
    s.plan = read_plan(api, s.plan["id"])
    set_clock(api, "2026-08-02T06:00:00Z")
    return s
