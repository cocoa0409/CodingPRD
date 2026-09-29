"""Composite setup helpers.

Tests build their world through the public API, because every test starts
against an empty plant. The helpers below are the plant's own vocabulary -
register a product, receive a load, run a clean, start a run, close it - and
each one accepts ``**overrides`` so a test can vary the single figure it cares
about while everything else stays at the standing values.

The centrepiece is :func:`build_world`, which walks the standing chain from an
empty plant to a closed run with nine hundred cases on hold, and stops wherever
the caller asks it to.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import constants as c
from . import factories as f
from .api_client import ApiClient
from .test_users import (
    LINE_OPERATOR_HEADERS,
    PLANT_ADMIN_HEADERS,
    QA_MANAGER_HEADERS,
    QA_TECHNICIAN_HEADERS,
    RECEIVING_CLERK_HEADERS,
    SANITATION_TECH_HEADERS,
    SHIPPING_CLERK_HEADERS,
    USER_QA_MANAGER_B,
    USER_QA_TECH_A,
    USER_SANITATION_TECH_A,
    make_qa_manager_headers,
    make_qa_technician_headers,
    make_sanitation_tech_headers,
)

# ── The stops on the standing chain ────────────────────────────────────────
#
# Each constant names the state of the plant after that many chain steps.
STOP_MASTER_DATA = 5           # product, specification, line, wash system
STOP_LOT_APPROVED = 7          # plus an APPROVED grower lot
STOP_RECEIPT_PENDING = 8       # plus a load awaiting inspection
STOP_RECEIPT_ACCEPTED = 9      # plus that load ACCEPTED with its trim declared
STOP_SANITATION_VALIDATED = 13  # plus a validated clean, so the line is OPEN
STOP_RUN_PLANNED = 14          # plus a run in SETUP
STOP_RUN_RUNNING = 18          # plus that run RUNNING, no pounds consumed yet
STOP_RUN_CONSUMED = 19         # plus thirty thousand pounds consumed
STOP_TWO_READINGS = 21         # plus a mid-run wash-water reading
STOP_CLOCK_AT_CLOSE = 22       # plus the clock advanced to the closing instant
STOP_RUN_CLOSED = 23           # plus the run CLOSED and its cases on hold


class World:
    """The identifiers and payloads the standing chain produced."""

    def __init__(self, api: ApiClient) -> None:
        self.api = api
        self.product: Dict[str, Any] = {}
        self.spec: Dict[str, Any] = {}
        self.line: Dict[str, Any] = {}
        self.wash_system: Dict[str, Any] = {}
        self.grower_lot: Dict[str, Any] = {}
        self.receipt: Dict[str, Any] = {}
        self.sanitation_event: Dict[str, Any] = {}
        self.run: Dict[str, Any] = {}
        self.consumption: Dict[str, Any] = {}
        self.readings: List[Dict[str, Any]] = []
        self.hold: Dict[str, Any] = {}
        self.cases: List[Dict[str, Any]] = []

    # Identifier shorthands, so tests read as domain language.
    @property
    def product_id(self) -> str:
        return self.product["id"]

    @property
    def spec_id(self) -> str:
        return self.spec["id"]

    @property
    def line_id(self) -> str:
        return self.line["id"]

    @property
    def wash_system_id(self) -> str:
        return self.wash_system["id"]

    @property
    def grower_lot_id(self) -> str:
        return self.grower_lot["id"]

    @property
    def receipt_id(self) -> str:
        return self.receipt["id"]

    @property
    def sanitation_event_id(self) -> str:
        return self.sanitation_event["id"]

    @property
    def run_id(self) -> str:
        return self.run["id"]

    @property
    def run_version(self) -> int:
        return self.run["version"]

    @property
    def consumption_id(self) -> str:
        return self.consumption["id"]

    @property
    def hold_id(self) -> str:
        return self.hold["id"]


# ── The logical clock ──────────────────────────────────────────────────────

def set_clock(api: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Advance the plant logical clock to an instant."""
    return get_success_data(api.set_clock(f.clock_payload(current_utc), PLANT_ADMIN_HEADERS))


# ── Master data ────────────────────────────────────────────────────────────

def create_product(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a product."""
    return get_success_data(api.create_product(f.product_payload(**overrides), PLANT_ADMIN_HEADERS))


def create_customer_spec(
    api: ApiClient, product_id: str, expected_product_version: int, **overrides: Any
) -> Dict[str, Any]:
    """Register a customer specification revision against a product."""
    return get_success_data(
        api.create_customer_spec(
            product_id,
            f.customer_spec_payload(expected_product_version, **overrides),
            PLANT_ADMIN_HEADERS,
        )
    )


def create_line(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a processing line."""
    return get_success_data(api.create_line(f.line_payload(**overrides), PLANT_ADMIN_HEADERS))


def create_wash_system(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a wash flume."""
    return get_success_data(
        api.create_wash_system(f.wash_system_payload(**overrides), PLANT_ADMIN_HEADERS)
    )


def changeout_wash_system(api: ApiClient, wash_system_id: str) -> Dict[str, Any]:
    """Dump and recharge a flume, resetting its chemistry."""
    return get_success_data(api.changeout_wash_system(wash_system_id, SANITATION_TECH_HEADERS))


# ── Grower lots and loads ──────────────────────────────────────────────────

def create_grower_lot(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Identify a grower lot with its preharvest evidence."""
    return get_success_data(
        api.create_grower_lot(f.grower_lot_payload(**overrides), QA_TECHNICIAN_HEADERS)
    )


def approve_grower_lot(api: ApiClient, lot_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Adjudicate a lot's preharvest risk."""
    return get_success_data(
        api.approve_grower_lot(lot_id, headers or QA_MANAGER_HEADERS)
    )


def approved_grower_lot(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Identify a lot and adjudicate it in one step."""
    lot = create_grower_lot(api, **overrides)
    return approve_grower_lot(api, lot["id"])


def create_receipt(api: ApiClient, grower_lot_id: str, **overrides: Any) -> Dict[str, Any]:
    """Weigh in a load against a grower lot."""
    return get_success_data(
        api.create_raw_receipt(f.raw_receipt_payload(grower_lot_id, **overrides), RECEIVING_CLERK_HEADERS)
    )


def disposition_receipt(
    api: ApiClient,
    receipt_id: str,
    decision: str = c.DECISION_ACCEPT,
    trim_loss_lb: Optional[float] = c.RECEIPT_TRIM_LOSS_LB,
    override_justification: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Accept or reject a weighed load, declaring its trim loss."""
    return get_success_data(
        api.disposition_raw_receipt(
            receipt_id,
            f.disposition_payload(
                decision,
                trim_loss_lb=trim_loss_lb,
                override_justification=override_justification,
                **overrides,
            ),
            headers or QA_TECHNICIAN_HEADERS,
        )
    )


def accepted_receipt(api: ApiClient, grower_lot_id: str, **overrides: Any) -> Dict[str, Any]:
    """Weigh in a load and accept it with the standing trim loss."""
    receipt = create_receipt(api, grower_lot_id, **overrides)
    return disposition_receipt(api, receipt["id"])


# ── Wash-water readings ────────────────────────────────────────────────────

def create_reading(
    api: ApiClient,
    wash_system_id: str,
    reading_at: str,
    free_chlorine_ppm: float,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Log a wash-water reading on a flume."""
    return get_success_data(
        api.create_antimicrobial_reading(
            wash_system_id,
            f.antimicrobial_reading_payload(reading_at, free_chlorine_ppm, **overrides),
            headers or LINE_OPERATOR_HEADERS,
        )
    )


# ── Sanitation ─────────────────────────────────────────────────────────────

def schedule_sanitation(api: ApiClient, line_id: str, **overrides: Any) -> Dict[str, Any]:
    """Schedule a sanitation event on a line."""
    return get_success_data(
        api.create_sanitation_event(
            line_id, f.sanitation_event_payload(**overrides), SANITATION_TECH_HEADERS
        )
    )


def schedule_changeover(api: ApiClient, line_id: str, **overrides: Any) -> Dict[str, Any]:
    """Schedule the documented allergen changeover clean on a line."""
    return get_success_data(
        api.create_sanitation_event(
            line_id, f.changeover_event_payload(**overrides), SANITATION_TECH_HEADERS
        )
    )


def start_sanitation(
    api: ApiClient, event_id: str, performed_by: str = USER_SANITATION_TECH_A
) -> Dict[str, Any]:
    """Begin the clean, stamping the technician who performs it."""
    return get_success_data(
        api.start_sanitation_event(event_id, make_sanitation_tech_headers(performed_by))
    )


def submit_sanitation(
    api: ApiClient,
    event_id: str,
    performed_by: str = USER_SANITATION_TECH_A,
    **overrides: Any,
) -> Dict[str, Any]:
    """Submit the completed clean with its three measurements."""
    return get_success_data(
        api.submit_sanitation_event(
            event_id,
            f.sanitation_submission_payload(**overrides),
            make_sanitation_tech_headers(performed_by),
        )
    )


def validate_sanitation(
    api: ApiClient,
    event_id: str,
    outcome: str = c.OUTCOME_PASS,
    validated_by: str = USER_QA_TECH_A,
) -> Dict[str, Any]:
    """Validate or fail the clean as a technician other than the performer."""
    return get_success_data(
        api.validate_sanitation_event(
            event_id, f.outcome_payload(outcome), make_qa_technician_headers(validated_by)
        )
    )


def validated_sanitation(
    api: ApiClient,
    line_id: str,
    performed_by: str = USER_SANITATION_TECH_A,
    validated_by: str = USER_QA_TECH_A,
    schedule_overrides: Optional[Dict[str, Any]] = None,
    submit_overrides: Optional[Dict[str, Any]] = None,
    is_allergen_changeover: bool = False,
) -> Dict[str, Any]:
    """Schedule, run, submit and validate one clean, leaving the line OPEN."""
    schedule_kwargs = dict(schedule_overrides or {})
    schedule_kwargs.setdefault("is_allergen_changeover", is_allergen_changeover)
    event = schedule_sanitation(api, line_id, **schedule_kwargs)
    start_sanitation(api, event["id"], performed_by)
    submit_sanitation(api, event["id"], performed_by, **(submit_overrides or {}))
    return validate_sanitation(api, event["id"], c.OUTCOME_PASS, validated_by)


def failed_sanitation(
    api: ApiClient,
    line_id: str,
    performed_by: str = USER_SANITATION_TECH_A,
    validated_by: str = USER_QA_TECH_A,
    **submit_overrides: Any,
) -> Dict[str, Any]:
    """Run a clean that fails validation, firing the failure cascade."""
    event = schedule_sanitation(api, line_id)
    start_sanitation(api, event["id"], performed_by)
    submit_sanitation(api, event["id"], performed_by, **submit_overrides)
    return validate_sanitation(api, event["id"], c.OUTCOME_FAIL, validated_by)


# ── Environmental monitoring and corrective actions ────────────────────────

def create_swab(api: ApiClient, line_id: str, **overrides: Any) -> Dict[str, Any]:
    """Log an environmental swab against a line."""
    return get_success_data(
        api.create_environmental_swab(
            line_id, f.environmental_swab_payload(**overrides), QA_TECHNICIAN_HEADERS
        )
    )


def record_swab_result(
    api: ApiClient, swab_id: str, result: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Record a laboratory result against a swab."""
    return get_success_data(
        api.record_swab_result(
            swab_id, f.swab_result_payload(result), headers or QA_TECHNICIAN_HEADERS
        )
    )


def confirmed_positive_swab(api: ApiClient, line_id: str, **overrides: Any) -> Dict[str, Any]:
    """Walk a swab PENDING to PRESUMPTIVE_POSITIVE to CONFIRMED_POSITIVE."""
    swab = create_swab(api, line_id, **overrides)
    record_swab_result(api, swab["id"], c.SWAB_RESULT_PRESUMPTIVE_POSITIVE)
    return record_swab_result(api, swab["id"], c.SWAB_RESULT_CONFIRMED_POSITIVE)


def list_line_corrective_actions(
    api: ApiClient, line_id: str, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Read a line's corrective actions."""
    return get_success_data(api.list_corrective_actions(line_id, QA_TECHNICIAN_HEADERS, params))


def verified_corrective_action(
    api: ApiClient,
    action_id: str,
    implemented_by: str = USER_QA_TECH_A,
    verified_by: str = USER_QA_MANAGER_B,
) -> Dict[str, Any]:
    """Take ownership of an action, submit the work and verify it."""
    get_success_data(
        api.start_corrective_action(action_id, make_qa_technician_headers(implemented_by))
    )
    get_success_data(
        api.submit_corrective_action_verification(
            action_id,
            f.corrective_action_submission_payload(),
            make_qa_technician_headers(implemented_by),
        )
    )
    return get_success_data(
        api.verify_corrective_action(
            action_id, f.outcome_payload(c.OUTCOME_PASS), make_qa_manager_headers(verified_by)
        )
    )


# ── Processing runs ────────────────────────────────────────────────────────

def plan_run(
    api: ApiClient,
    line_id: str,
    product_id: str,
    customer_spec_id: str,
    wash_system_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Plan a run's occupancy window on a line and a flume."""
    return get_success_data(
        api.create_process_run(
            f.process_run_payload(line_id, product_id, customer_spec_id, wash_system_id, **overrides),
            LINE_OPERATOR_HEADERS,
        )
    )


def start_run(api: ApiClient, run_id: str) -> Dict[str, Any]:
    """Start a planned run, freezing its wash targets."""
    return get_success_data(api.start_process_run(run_id, LINE_OPERATOR_HEADERS))


def consume(
    api: ApiClient,
    run_id: str,
    raw_receipt_id: str,
    expected_process_run_version: int,
    consumed_lb: float = c.CONSUMED_LB,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draw pounds from a received load onto a run."""
    return get_success_data(
        api.create_lot_consumption(
            run_id,
            f.lot_consumption_payload(
                raw_receipt_id, expected_process_run_version, consumed_lb, **overrides
            ),
            LINE_OPERATOR_HEADERS,
        )
    )


def void_consumption(
    api: ApiClient, consumption_id: str, expected_process_run_version: int
) -> Dict[str, Any]:
    """Void a consumption, compensating the load's pound balance in full."""
    return get_success_data(
        api.void_lot_consumption(
            consumption_id, f.void_payload(expected_process_run_version), LINE_OPERATOR_HEADERS
        )
    )


def close_run(api: ApiClient, run_id: str, **overrides: Any) -> Dict[str, Any]:
    """Close a running run with its measured figures."""
    return get_success_data(
        api.close_process_run(run_id, f.close_payload(**overrides), LINE_OPERATOR_HEADERS)
    )


def read_run(api: ApiClient, run_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a run back."""
    return get_success_data(api.get_process_run(run_id, headers or LINE_OPERATOR_HEADERS))


def read_line(api: ApiClient, line_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a line back, including its derived posture."""
    return get_success_data(api.get_line(line_id, headers or QA_TECHNICIAN_HEADERS))


def read_wash_system(
    api: ApiClient, wash_system_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Read a flume back, including its derived chemistry."""
    return get_success_data(api.get_wash_system(wash_system_id, headers or LINE_OPERATOR_HEADERS))


def read_receipt(api: ApiClient, receipt_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a load back, including its remaining pound balance."""
    return get_success_data(api.get_raw_receipt(receipt_id, headers or RECEIVING_CLERK_HEADERS))


def read_grower_lot(api: ApiClient, lot_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a grower lot back, including both risk scores."""
    return get_success_data(api.get_grower_lot(lot_id, headers or QA_TECHNICIAN_HEADERS))


def list_cases(
    api: ApiClient, run_id: str, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Read a run's finished cases in pack order."""
    return get_success_data(api.list_finished_cases(run_id, LINE_OPERATOR_HEADERS, params))


def all_cases(api: ApiClient, run_id: str, cases_produced: int) -> List[Dict[str, Any]]:
    """Page through every case a run packed, a hundred at a time."""
    collected: List[Dict[str, Any]] = []
    offset = 0
    while offset < cases_produced:
        page = list_cases(api, run_id, {"limit": c.MAX_LIMIT, "offset": offset})
        if not page:
            break
        collected.extend(page)
        offset += len(page)
    return collected


# ── Holds and shipping ─────────────────────────────────────────────────────

def open_hold(
    api: ApiClient, run_id: str, reason: str = c.REASON_HOLD_AND_RELEASE_TESTING
) -> Dict[str, Any]:
    """Open a hold on a run directly."""
    return get_success_data(
        api.create_hold_record(run_id, f.hold_record_payload(reason), QA_TECHNICIAN_HEADERS)
    )


def list_holds(
    api: ApiClient, run_id: str, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Read a run's hold records, newest first."""
    return get_success_data(api.list_hold_records(run_id, QA_TECHNICIAN_HEADERS, params))


def submit_sample(
    api: ApiClient,
    hold_id: str,
    latest_test_type: str = c.TEST_APC,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Submit a micro sample against a hold, consuming one test round."""
    return get_success_data(
        api.submit_hold_sample(
            hold_id, f.hold_sample_payload(latest_test_type), headers or QA_TECHNICIAN_HEADERS
        )
    )


def record_result(
    api: ApiClient,
    hold_id: str,
    latest_test_result: str,
    latest_apc_cfu_g: Optional[int] = None,
    resulted_by: str = USER_QA_TECH_A,
) -> Dict[str, Any]:
    """Record a laboratory result against a hold under test."""
    return get_success_data(
        api.record_hold_result(
            hold_id,
            f.hold_result_payload(latest_test_result, latest_apc_cfu_g),
            make_qa_technician_headers(resulted_by),
        )
    )


def release_hold(
    api: ApiClient, hold_id: str, released_by: str = USER_QA_MANAGER_B
) -> Dict[str, Any]:
    """Release a hold as a manager other than the one who resulted it."""
    return get_success_data(api.release_hold(hold_id, make_qa_manager_headers(released_by)))


def reject_hold(
    api: ApiClient, hold_id: str, rejected_by: str = USER_QA_MANAGER_B
) -> Dict[str, Any]:
    """Reject a hold, destroying the product it covers."""
    return get_success_data(api.reject_hold(hold_id, make_qa_manager_headers(rejected_by)))


def clear_hold(
    api: ApiClient,
    hold_id: str,
    latest_apc_cfu_g: int = c.APC_BELOW_MICRO_THRESHOLD,
    resulted_by: str = USER_QA_TECH_A,
    released_by: str = USER_QA_MANAGER_B,
    latest_test_type: str = c.TEST_APC,
) -> Dict[str, Any]:
    """Take a hold through sample, negative result and release in one step."""
    submit_sample(api, hold_id, latest_test_type)
    record_result(api, hold_id, c.RESULT_NEGATIVE, latest_apc_cfu_g, resulted_by)
    return release_hold(api, hold_id, released_by)


def ship_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    """Ship one case."""
    return get_success_data(api.ship_finished_case(case_id, SHIPPING_CLERK_HEADERS))


def read_traceability(
    api: ApiClient, run_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Read a run's traceability view."""
    return get_success_data(api.get_traceability(run_id, headers or QA_TECHNICIAN_HEADERS))


# ── The standing chain ─────────────────────────────────────────────────────

def build_world(
    api: ApiClient,
    stop_after: int = STOP_RUN_CLOSED,
    product_overrides: Optional[Dict[str, Any]] = None,
    spec_overrides: Optional[Dict[str, Any]] = None,
    line_overrides: Optional[Dict[str, Any]] = None,
    wash_overrides: Optional[Dict[str, Any]] = None,
    lot_overrides: Optional[Dict[str, Any]] = None,
    receipt_overrides: Optional[Dict[str, Any]] = None,
    run_overrides: Optional[Dict[str, Any]] = None,
    close_overrides: Optional[Dict[str, Any]] = None,
    consumed_lb: float = c.CONSUMED_LB,
) -> World:
    """Walk the standing chain from an empty plant and stop where asked.

    The chain registers the master data, receives and accepts one load, runs a
    clean so the line opens, plans a run, takes a pre-start wash-water reading,
    starts the run, draws thirty thousand pounds onto it, takes a mid-run
    reading and closes it - producing nine hundred cases on hold behind an
    automatic hold-and-release hold.
    """
    world = World(api)

    set_clock(api, c.CLOCK_MASTER_DATA)
    world.product = create_product(api, **(product_overrides or {}))
    world.spec = create_customer_spec(
        api, world.product_id, world.product["version"], **(spec_overrides or {})
    )
    world.line = create_line(api, **(line_overrides or {}))
    world.wash_system = create_wash_system(api, **(wash_overrides or {}))
    if stop_after <= STOP_MASTER_DATA:
        return world

    world.grower_lot = create_grower_lot(api, **(lot_overrides or {}))
    world.grower_lot = approve_grower_lot(api, world.grower_lot_id)
    if stop_after <= STOP_LOT_APPROVED:
        return world

    world.receipt = create_receipt(api, world.grower_lot_id, **(receipt_overrides or {}))
    if stop_after <= STOP_RECEIPT_PENDING:
        return world

    world.receipt = disposition_receipt(api, world.receipt_id)
    if stop_after <= STOP_RECEIPT_ACCEPTED:
        return world

    world.sanitation_event = validated_sanitation(api, world.line_id)
    if stop_after <= STOP_SANITATION_VALIDATED:
        return world

    world.run = plan_run(
        api,
        world.line_id,
        world.product_id,
        world.spec_id,
        world.wash_system_id,
        **(run_overrides or {}),
    )
    if stop_after <= STOP_RUN_PLANNED:
        return world

    set_clock(api, c.CLOCK_PRE_START)
    world.readings.append(
        create_reading(
            api, world.wash_system_id, c.READING_PRE_START_AT, c.READING_PRE_START_PPM
        )
    )
    set_clock(api, c.CLOCK_START)
    world.run = start_run(api, world.run_id)
    if stop_after <= STOP_RUN_RUNNING:
        return world

    world.consumption = consume(
        api, world.run_id, world.receipt_id, world.run_version, consumed_lb
    )
    world.run = read_run(api, world.run_id)
    if stop_after <= STOP_RUN_CONSUMED:
        return world

    set_clock(api, c.CLOCK_MID_RUN)
    world.readings.append(
        create_reading(api, world.wash_system_id, c.READING_MID_RUN_AT, c.READING_MID_RUN_PPM)
    )
    if stop_after <= STOP_TWO_READINGS:
        return world

    set_clock(api, c.CLOCK_CLOSE)
    if stop_after <= STOP_CLOCK_AT_CLOSE:
        return world

    world.run = close_run(api, world.run_id, **(close_overrides or {}))
    holds = list_holds(api, world.run_id)
    if holds:
        world.hold = holds[0]
    return world


def closed_world(api: ApiClient, **kwargs: Any) -> World:
    """The chain walked all the way to a closed run with cases on hold."""
    return build_world(api, stop_after=STOP_RUN_CLOSED, **kwargs)


def running_world(api: ApiClient, **kwargs: Any) -> World:
    """The chain walked to a running run with its pounds already drawn."""
    return build_world(api, stop_after=STOP_RUN_CONSUMED, **kwargs)


def master_data_world(api: ApiClient, **kwargs: Any) -> World:
    """Only the master data: one product, specification, line and flume."""
    return build_world(api, stop_after=STOP_MASTER_DATA, **kwargs)
