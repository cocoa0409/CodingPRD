"""Composite setup helpers.

Every fixture builds its preconditions through public API calls only — the
harness restarts the server before every test, so nothing persists between
tests and no helper touches server state directly. Setup calls use the lenient
``get_success_data`` validator so a failed precondition surfaces as
``Setup failed: ...`` rather than a confusing assertion mismatch.

Logical-clock discipline: the clock starts each test at the default instant
2026-09-01T00:00:00Z and only moves forward through explicit
``set_clock`` calls inside the fixtures. Every default date used below is
reachable from that start.

Identity threading: ``DeviceMaker``-role writes always carry the acting maker
entity's id via ``make_device_maker_headers``; opaque roles use the shared
``TEST_USERS`` constants; countersignature and prepayment confirmation default
to the distinct principals ``planner-01`` / ``fin-01`` so the segregation
check passes, and both are overridable.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import TEST_USERS, make_device_maker_headers, make_capacity_planner_headers, make_finance_controller_headers

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["program_manager_headers"]
PLANNER = TEST_USERS["capacity_planner_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]
LEGAL = TEST_USERS["legal_counsel_headers"]

DEFAULT_PLANNER_ID = "planner-01"
DEFAULT_FINANCE_ID = "fin-01"

# Default campaign window: exactly the minimum campaign length of 365 days,
# first meltable day after a tank built at the default clock is commissioned.
CAMPAIGN_START = "2028-03-01T00:00:00Z"
CAMPAIGN_END = "2029-03-01T00:00:00Z"
# Default licensing term and freeze deadline (term spans well over the minimum
# license term; deadline sits strictly after the default clock).
FREEZE_DEADLINE = "2027-03-01T00:00:00Z"
LICENSE_EFFECTIVE = "2027-01-01T00:00:00Z"
LICENSE_EXPIRY = "2028-12-31T00:00:00Z"


# ── Clock and checkpoint ─────────────────────────────────────────────────────

def shift_iso(base_iso: str, days: int = 0, seconds: int = 0) -> str:
    """Return ``base_iso`` shifted forward, rendered as ``...Z``."""
    base = datetime.fromisoformat(base_iso.replace("Z", "+00:00"))
    shifted = base + timedelta(days=days, seconds=seconds)
    return shifted.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock; returns the ``current_utc`` payload."""
    return get_success_data(api_client.set_clock(factories.set_clock_payload(to_iso8601), ADMIN))


def run_checkpoint(as_planner: bool = False) -> Dict[str, Any]:
    """Run the operations checkpoint; returns the five sweep counts."""
    headers = PLANNER if as_planner else ADMIN
    return get_success_data(api_client.ops_checkpoint(headers))


# ── Step fixtures: makers, programs, compositions, qualification ─────────────

def create_device_maker(
    name: str = "Acme Devices",
    region: str = "US",
    standing_tier: Optional[str] = None,
    ip_review_status: Optional[str] = None,
) -> Dict[str, Any]:
    """Register a device maker (PlatformAdmin). Returns the DeviceMaker."""
    payload = factories.create_device_maker_payload(name=name, region=region)
    if standing_tier is not None:
        payload["standing_tier"] = standing_tier
    maker = get_success_data(api_client.create_device_maker(payload, ADMIN))
    if ip_review_status is not None:
        for target in _ip_review_path(maker["ip_review_status"], ip_review_status):
            maker = get_success_data(
                api_client.ip_review_device_maker(maker["id"], factories.ip_review_payload(target), LEGAL)
            )
    return maker


def _ip_review_path(current: str, target: str) -> List[str]:
    """Legal transition sequence from ``current`` to ``target`` posture."""
    if current == target:
        return []
    if current == "CLEAR" and target == "UNDER_REVIEW":
        return ["UNDER_REVIEW"]
    if current == "CLEAR" and target == "CONFIRMED_INFRINGEMENT":
        return ["UNDER_REVIEW", "CONFIRMED_INFRINGEMENT"]
    if current == "UNDER_REVIEW" and target in ("CONFIRMED_INFRINGEMENT", "CLEARED"):
        return [target]
    if current == "CONFIRMED_INFRINGEMENT" and target == "CLEARED":
        return ["CLEARED"]
    raise ValueError(f"no IP-review path {current} -> {target}")


def create_program(
    maker: Dict[str, Any],
    name: str = "Eagle",
    primary_market: str = "CONSUMER_ELECTRONICS",
    confidentiality_tier: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a DRAFT program for ``maker``. Returns the Program."""
    payload = factories.create_program_payload(
        maker["id"], name=name, primary_market=primary_market
    )
    if confidentiality_tier is not None:
        payload["confidentiality_tier"] = confidentiality_tier
    return get_success_data(api_client.create_program(payload, MANAGER))


def execute_nda(program: Dict[str, Any], nda_reference: str = "NDA-001") -> Dict[str, Any]:
    """Execute the program's NDA: DRAFT -> NDA_EXECUTED."""
    return get_success_data(
        api_client.execute_nda(program["id"], factories.execute_nda_payload(nda_reference), MANAGER)
    )


def create_program_with_nda(
    maker: Optional[Dict[str, Any]] = None,
    name: str = "Eagle",
    primary_market: str = "CONSUMER_ELECTRONICS",
    maker_name: str = "Acme Devices",
    maker_region: str = "US",
    **maker_kwargs: Any,
) -> SimpleNamespace:
    """A maker (created if omitted) plus its program past the NDA gate."""
    if maker is None:
        maker = create_device_maker(name=maker_name, region=maker_region, **maker_kwargs)
    program = create_program(maker, name=name, primary_market=primary_market)
    program = execute_nda(program)
    return SimpleNamespace(maker=maker, program=program)


def create_composition(
    program: Dict[str, Any],
    composition_code: str = "GX-100",
    complexity_multiplier: float = 1.0,
) -> Dict[str, Any]:
    """Create an EXPERIMENTAL composition; the program's first one also
    advances the program NDA_EXECUTED -> COMPOSITION_TUNING."""
    payload = factories.create_composition_payload(
        program["id"],
        composition_code=composition_code,
        complexity_multiplier=complexity_multiplier,
    )
    return get_success_data(api_client.create_composition(payload, MANAGER))


def create_qual_cycle(composition: Dict[str, Any], test_plan_ref: str = "TP-1") -> Dict[str, Any]:
    """Submit a qualification cycle (starts SUBMITTED, attempt 1)."""
    payload = factories.create_qual_cycle_payload(composition["id"], test_plan_ref=test_plan_ref)
    return get_success_data(api_client.create_qual_cycle(payload, MANAGER))


def begin_testing(cycle: Dict[str, Any], maker_id: str) -> Dict[str, Any]:
    """SUBMITTED -> IN_TESTING (DeviceMaker, ownership-checked); the first
    begin also tunes an EXPERIMENTAL composition."""
    return get_success_data(
        api_client.begin_testing(cycle["id"], headers=make_device_maker_headers(maker_id))
    )


def record_qual_result(cycle: Dict[str, Any], maker_id: str, outcome: str = "PASSED") -> Dict[str, Any]:
    """IN_TESTING -> PASSED/FAILED (DeviceMaker, ownership-checked); a PASSED
    outcome qualifies a TUNED composition."""
    return get_success_data(
        api_client.record_result(
            cycle["id"], factories.record_result_payload(outcome), make_device_maker_headers(maker_id)
        )
    )


def resubmit_qual_cycle(cycle: Dict[str, Any]) -> Dict[str, Any]:
    """FAILED -> SUBMITTED with attempt_number incremented."""
    return get_success_data(api_client.resubmit_qual_cycle(cycle["id"], MANAGER))


def create_tuned_composition(
    program: Dict[str, Any],
    maker: Dict[str, Any],
    composition_code: str = "GX-100",
    complexity_multiplier: float = 1.0,
) -> SimpleNamespace:
    """Composition driven EXPERIMENTAL -> TUNED (cycle IN_TESTING, no result)."""
    composition = create_composition(program, composition_code, complexity_multiplier)
    cycle = create_qual_cycle(composition)
    cycle = begin_testing(cycle, maker["id"])
    composition = get_success_data(api_client.get_composition(composition["id"], MANAGER))
    return SimpleNamespace(composition=composition, cycle=cycle)


def create_qualified_composition(
    program: Dict[str, Any],
    maker: Dict[str, Any],
    composition_code: str = "GX-100",
    complexity_multiplier: float = 1.0,
) -> SimpleNamespace:
    """Composition driven EXPERIMENTAL -> TUNED -> QUALIFIED."""
    tuned = create_tuned_composition(program, maker, composition_code, complexity_multiplier)
    cycle = record_qual_result(tuned.cycle, maker["id"], "PASSED")
    composition = get_success_data(api_client.get_composition(tuned.composition["id"], MANAGER))
    return SimpleNamespace(composition=composition, cycle=cycle)


def create_locked_composition(
    program: Dict[str, Any],
    maker: Dict[str, Any],
    composition_code: str = "GX-100",
    complexity_multiplier: float = 1.0,
) -> SimpleNamespace:
    """Composition driven to QUALIFIED and then locked (immutable)."""
    qualified = create_qualified_composition(program, maker, composition_code, complexity_multiplier)
    composition = get_success_data(
        api_client.lock_composition(qualified.composition["id"], MANAGER)
    )
    return SimpleNamespace(composition=composition, cycle=qualified.cycle)


# ── Step fixtures: commitments ───────────────────────────────────────────────

def get_program_version(program_id: str) -> int:
    return get_success_data(api_client.get_program(program_id, MANAGER))["version"]


def get_commitment_version(commitment_id: str) -> int:
    return get_success_data(api_client.get_commitment(commitment_id, PLANNER))["version"]


def create_commitment(
    program: Dict[str, Any],
    committed_units: int = 5000,
    required_units: int = 5000,
    prepayment_cents: int = 2500000,
) -> Dict[str, Any]:
    """Propose a commitment (PROPOSED); the program version is re-observed so
    the OCC guard always matches. Creating also bumps the Program's version."""
    payload = factories.create_commitment_payload(
        program["id"],
        expected_program_version=get_program_version(program["id"]),
        committed_units=committed_units,
        required_units=required_units,
        prepayment_cents=prepayment_cents,
    )
    return get_success_data(api_client.create_commitment(payload, MANAGER))


def sign_commitment(commitment: Dict[str, Any], maker: Dict[str, Any]) -> Dict[str, Any]:
    """PROPOSED -> SIGNED; the caller is the commitment's owning maker."""
    return get_success_data(
        api_client.sign_commitment(commitment["id"], headers=make_device_maker_headers(maker["id"]))
    )


def countersign_commitment(
    commitment: Dict[str, Any], planner_id: str = DEFAULT_PLANNER_ID
) -> Dict[str, Any]:
    """SIGNED -> COUNTERSIGNED; records the planner's X-User-ID."""
    return get_success_data(
        api_client.countersign_commitment(
            commitment["id"], headers=make_capacity_planner_headers(planner_id)
        )
    )


def confirm_prepayment(
    commitment: Dict[str, Any], finance_id: str = DEFAULT_FINANCE_ID
) -> Dict[str, Any]:
    """COUNTERSIGNED -> SECURED; stores coverage_tier and effective_units.
    ``finance_id`` must differ from the recorded countersigner (segregation)."""
    return get_success_data(
        api_client.confirm_prepayment(
            commitment["id"], headers=make_finance_controller_headers(finance_id)
        )
    )


def create_secured_commitment(
    program: Dict[str, Any],
    maker: Dict[str, Any],
    committed_units: int = 5000,
    required_units: int = 5000,
    prepayment_cents: int = 2500000,
    planner_id: str = DEFAULT_PLANNER_ID,
    finance_id: str = DEFAULT_FINANCE_ID,
) -> Dict[str, Any]:
    """Full three-party handshake: PROPOSED -> SIGNED -> COUNTERSIGNED ->
    SECURED. Defaults give coverage 1.5 (TIER_A) on a 5000/5000 commitment."""
    commitment = create_commitment(program, committed_units, required_units, prepayment_cents)
    commitment = sign_commitment(commitment, maker)
    commitment = countersign_commitment(commitment, planner_id)
    return confirm_prepayment(commitment, finance_id)


def apply_prepayment(
    commitment: Dict[str, Any],
    amount_cents: int,
    finance_id: str = DEFAULT_FINANCE_ID,
) -> Dict[str, Any]:
    """Move ``amount_cents`` from the remaining bucket to the applied bucket."""
    return get_success_data(
        api_client.apply_prepayment(
            commitment["id"],
            factories.apply_prepayment_payload(amount_cents),
            make_finance_controller_headers(finance_id),
        )
    )


def release_commitment(
    commitment: Dict[str, Any], reason: Optional[str] = None
) -> Dict[str, Any]:
    """Release a non-terminal commitment; refunds the remaining prepayment and
    releases its RESERVED allocations."""
    payload = {"reason": reason} if reason is not None else None
    return get_success_data(api_client.release_commitment(commitment["id"], MANAGER, payload))


# ── Step fixtures: tanks, campaigns, allocations ─────────────────────────────

def create_tank(
    commitment: Dict[str, Any], capacity_units_per_day: int = 1000
) -> Dict[str, Any]:
    """Build a CONSTRUCTING tank funded by a SECURED commitment."""
    payload = factories.create_tank_payload(
        commitment["id"], capacity_units_per_day=capacity_units_per_day
    )
    return get_success_data(api_client.create_tank(payload, PLANNER))


def commission_tank(tank: Dict[str, Any]) -> Dict[str, Any]:
    """Commission a tank: moves the logical clock to the tank's
    construction_ready_date first, so the readiness gate passes regardless of
    when the tank was created."""
    ready = get_success_data(api_client.get_tank(tank["id"], PLANNER))["construction_ready_date"]
    set_clock(ready)
    return get_success_data(api_client.commission_tank(tank["id"], PLANNER))


def create_commissioned_tank(
    commitment: Dict[str, Any], capacity_units_per_day: int = 1000
) -> Dict[str, Any]:
    """Create + commission. Leaves the logical clock at the ready date."""
    return commission_tank(create_tank(commitment, capacity_units_per_day))


def create_campaign(
    tank: Dict[str, Any],
    composition: Dict[str, Any],
    start_date: str = CAMPAIGN_START,
    end_date: str = CAMPAIGN_END,
    planned_units: int = 10000,
) -> Dict[str, Any]:
    """Schedule a SCHEDULED campaign on a COMMISSIONED tank for a composition
    that is at least TUNED."""
    payload = factories.create_campaign_payload(
        tank["id"],
        composition["id"],
        start_date=start_date,
        end_date=end_date,
        planned_units=planned_units,
    )
    return get_success_data(api_client.create_campaign(payload, PLANNER))


def start_campaign(campaign: Dict[str, Any]) -> Dict[str, Any]:
    """SCHEDULED -> RUNNING: moves the logical clock to the campaign's
    start_date first, so the time gate passes."""
    start = get_success_data(api_client.get_campaign(campaign["id"], PLANNER))["start_date"]
    set_clock(start)
    return get_success_data(api_client.start_campaign(campaign["id"], PLANNER))


def create_running_campaign(
    tank: Dict[str, Any],
    composition: Dict[str, Any],
    start_date: str = CAMPAIGN_START,
    end_date: str = CAMPAIGN_END,
    planned_units: int = 10000,
) -> Dict[str, Any]:
    """Schedule + start. Leaves the logical clock at the campaign start."""
    return start_campaign(create_campaign(tank, composition, start_date, end_date, planned_units))


def record_production(
    campaign: Dict[str, Any],
    good_units: int,
    scrap_units: int,
    record_date: str = "2028-06-01T00:00:00Z",
) -> Dict[str, Any]:
    """Record a production tally against a RUNNING campaign."""
    payload = factories.record_production_payload(good_units, scrap_units, record_date)
    return get_success_data(api_client.record_production(campaign["id"], payload, PLANNER))


def create_allocation(
    commitment: Dict[str, Any],
    campaign: Dict[str, Any],
    units: int = 1000,
) -> Dict[str, Any]:
    """Allocate campaign supply to a SECURED/BREACH_WATCH commitment; the
    commitment version is re-observed so the OCC guard always matches."""
    payload = factories.create_allocation_payload(
        commitment["id"],
        campaign["id"],
        expected_commitment_version=get_commitment_version(commitment["id"]),
        units=units,
    )
    return get_success_data(api_client.create_allocation(payload, PLANNER))


def fulfill_allocation(allocation: Dict[str, Any]) -> Dict[str, Any]:
    """RESERVED -> FULFILLED (glass shipped)."""
    return get_success_data(api_client.fulfill_allocation(allocation["id"], PLANNER))


def release_allocation(allocation: Dict[str, Any]) -> Dict[str, Any]:
    """RESERVED -> RELEASED; restores campaign headroom and may drop the
    commitment into BREACH_WATCH with a standing demotion."""
    return get_success_data(api_client.release_allocation(allocation["id"], PLANNER))


# ── Composite: full supply chain ─────────────────────────────────────────────

def setup_supply_chain(
    maker_name: str = "Acme Devices",
    maker_region: str = "US",
    standing_tier: Optional[str] = None,
    primary_market: str = "CONSUMER_ELECTRONICS",
    composition_code: str = "GX-100",
    complexity_multiplier: float = 1.0,
    committed_units: int = 5000,
    required_units: int = 5000,
    prepayment_cents: int = 2500000,
    capacity_units_per_day: int = 1000,
    planned_units: int = 10000,
    start_date: str = CAMPAIGN_START,
    end_date: str = CAMPAIGN_END,
    composition_maturity: str = "QUALIFIED",
) -> SimpleNamespace:
    """The full bootstrap: maker -> program (NDA executed) -> composition ->
    qualification cycle -> SECURED commitment -> COMMISSIONED tank ->
    SCHEDULED campaign.

    ``composition_maturity`` selects how far the composition is driven:
    ``TUNED`` (cycle IN_TESTING, no result), ``QUALIFIED`` (default), or
    ``LOCKED``. Leaves the logical clock at the tank's construction-ready date.
    Returns a namespace with maker, program, composition, cycle, commitment,
    tank, campaign.
    """
    maker = create_device_maker(name=maker_name, region=maker_region, standing_tier=standing_tier)
    program = execute_nda(create_program(maker, primary_market=primary_market))
    if composition_maturity == "TUNED":
        qual = create_tuned_composition(program, maker, composition_code, complexity_multiplier)
    elif composition_maturity == "QUALIFIED":
        qual = create_qualified_composition(program, maker, composition_code, complexity_multiplier)
    elif composition_maturity == "LOCKED":
        qual = create_locked_composition(program, maker, composition_code, complexity_multiplier)
    else:
        raise ValueError(f"unknown composition_maturity {composition_maturity}")
    commitment = create_secured_commitment(program, maker, committed_units, required_units, prepayment_cents)
    tank = create_commissioned_tank(commitment, capacity_units_per_day)
    campaign = create_campaign(tank, qual.composition, start_date, end_date, planned_units)
    return SimpleNamespace(
        maker=maker,
        program=program,
        composition=qual.composition,
        cycle=qual.cycle,
        commitment=commitment,
        tank=tank,
        campaign=campaign,
    )


def setup_supply_chain_with_allocation(
    alloc_units: int = 1000, **overrides: Any
) -> SimpleNamespace:
    """Supply chain plus one RESERVED allocation of ``alloc_units`` units.
    Leaves the clock at the tank's construction-ready date."""
    chain = setup_supply_chain(**overrides)
    chain.allocation = create_allocation(chain.commitment, chain.campaign, alloc_units)
    return chain


def setup_running_supply_chain(**overrides: Any) -> SimpleNamespace:
    """Supply chain with the campaign started: composition must be QUALIFIED
    or LOCKED. Leaves the logical clock at the campaign's start_date."""
    chain = setup_supply_chain(**overrides)
    chain.campaign = start_campaign(chain.campaign)
    return chain


def setup_running_chain_with_allocation(
    alloc_units: int = 1000, **overrides: Any
) -> SimpleNamespace:
    """Running campaign plus one RESERVED allocation. Leaves the clock at the
    campaign's start_date."""
    chain = setup_running_supply_chain(**overrides)
    chain.allocation = create_allocation(chain.commitment, chain.campaign, alloc_units)
    return chain


# ── Step fixtures: licenses and usage reports ────────────────────────────────

def create_license(
    maker: Dict[str, Any],
    program: Dict[str, Any],
    market: str = "CONSUMER_ELECTRONICS",
    effective_date: str = LICENSE_EFFECTIVE,
    expiry_date: str = LICENSE_EXPIRY,
) -> Dict[str, Any]:
    """Create a license (license_status NEGOTIATION, marketing DRAFT)."""
    payload = factories.create_license_payload(
        maker["id"],
        program["id"],
        market=market,
        effective_date=effective_date,
        expiry_date=expiry_date,
    )
    return get_success_data(api_client.create_license(payload, LEGAL))


def activate_license(license_: Dict[str, Any]) -> Dict[str, Any]:
    """NEGOTIATION -> ACTIVE (assumes every precondition already holds)."""
    return get_success_data(api_client.activate_license(license_["id"], LEGAL))


def suspend_license(license_: Dict[str, Any]) -> Dict[str, Any]:
    """ACTIVE -> SUSPENDED with reason MANUAL."""
    return get_success_data(api_client.suspend_license(license_["id"], LEGAL))


def reinstate_license(license_: Dict[str, Any]) -> Dict[str, Any]:
    """SUSPENDED -> ACTIVE; clears suspension_reason to NONE."""
    return get_success_data(api_client.reinstate_license(license_["id"], LEGAL))


def submit_marketing(
    license_: Dict[str, Any], maker: Dict[str, Any], materials_ref: str = "MKT-1"
) -> Dict[str, Any]:
    """Marketing DRAFT/CHANGES_REQUIRED -> IN_REVIEW (DeviceMaker,
    ownership-checked against the license's maker)."""
    return get_success_data(
        api_client.submit_marketing(
            license_["id"],
            factories.submit_marketing_payload(materials_ref),
            make_device_maker_headers(maker["id"]),
        )
    )


def review_marketing(license_: Dict[str, Any], decision: str = "APPROVED") -> Dict[str, Any]:
    """Marketing IN_REVIEW -> APPROVED or CHANGES_REQUIRED."""
    return get_success_data(
        api_client.review_marketing(license_["id"], factories.review_marketing_payload(decision), LEGAL)
    )


def create_usage_report(
    license_: Dict[str, Any],
    maker: Dict[str, Any],
    period_start: str = "2027-01-01T00:00:00Z",
    period_end: str = "2027-03-31T00:00:00Z",
    lines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Submit a usage report (SUBMITTED; provisional royalty per-line
    rounding). DeviceMaker write, ownership-checked against the license."""
    payload = factories.create_usage_report_payload(
        license_["id"], lines=lines, period_start=period_start, period_end=period_end
    )
    return get_success_data(
        api_client.create_usage_report(payload, make_device_maker_headers(maker["id"]))
    )


def accept_usage_report(
    report: Dict[str, Any], finance_id: str = DEFAULT_FINANCE_ID
) -> Dict[str, Any]:
    """SUBMITTED -> ACCEPTED; computes the final royalty sum-then-round and
    accrues it to the license."""
    return get_success_data(
        api_client.accept_usage_report(
            report["id"], headers=make_finance_controller_headers(finance_id)
        )
    )


def dispute_usage_report(
    report: Dict[str, Any],
    finance_id: str = DEFAULT_FINANCE_ID,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """SUBMITTED -> DISPUTED, freeing the period for a superseding report."""
    payload = {"reason": reason} if reason is not None else None
    return get_success_data(
        api_client.dispute_usage_report(
            report["id"], headers=make_finance_controller_headers(finance_id), payload=payload
        )
    )


# ── Composite: licensing chain ───────────────────────────────────────────────

def setup_licensing_chain(
    maker_name: str = "Beta Devices",
    maker_region: str = "EU",
    standing_tier: Optional[str] = None,
    primary_market: str = "CONSUMER_ELECTRONICS",
    market: Optional[str] = None,
    composition_code: str = "GX-200",
    lock_composition: bool = False,
    freeze_deadline: str = FREEZE_DEADLINE,
    effective_date: str = LICENSE_EFFECTIVE,
    expiry_date: str = LICENSE_EXPIRY,
    move_clock_to_term: bool = True,
) -> SimpleNamespace:
    """Program DESIGN_FROZEN with a QUALIFIED (or LOCKED) composition plus a
    NEGOTIATION license.

    ``market=None`` licenses the primary market; any other value is a
    secondary application and therefore needs ``lock_composition=True`` to
    activate. When ``move_clock_to_term`` is set, the logical clock is moved to
    ``effective_date`` at the end so activation is in-term; leave it False for
    before-term scenarios. Returns maker, program, composition, cycle, license.
    """
    maker = create_device_maker(name=maker_name, region=maker_region, standing_tier=standing_tier)
    program = execute_nda(create_program(maker, primary_market=primary_market))
    qual = create_qualified_composition(program, maker, composition_code)
    program = get_success_data(
        api_client.begin_qualification(
            program["id"], factories.begin_qualification_payload(freeze_deadline), MANAGER
        )
    )
    program = get_success_data(api_client.freeze_design(program["id"], MANAGER))
    composition = qual.composition
    if lock_composition:
        composition = get_success_data(api_client.lock_composition(composition["id"], MANAGER))
    license_ = create_license(
        maker, program, market or primary_market, effective_date, expiry_date
    )
    if move_clock_to_term:
        set_clock(effective_date)
    return SimpleNamespace(
        maker=maker, program=program, composition=composition, cycle=qual.cycle, license=license_
    )


def setup_active_license(**overrides: Any) -> SimpleNamespace:
    """Licensing chain with the license ACTIVE. Clock ends at effective_date."""
    chain = setup_licensing_chain(**overrides)
    chain.license = activate_license(chain.license)
    return chain


def setup_approved_marketing_license(**overrides: Any) -> SimpleNamespace:
    """Active license whose marketing is APPROVED — royalty-settlement ready."""
    chain = setup_active_license(**overrides)
    chain.license = submit_marketing(chain.license, chain.maker)
    chain.license = review_marketing(chain.license, "APPROVED")
    return chain


def create_accepted_report(
    license_: Dict[str, Any],
    maker: Dict[str, Any],
    period_start: str = "2027-01-01T00:00:00Z",
    period_end: str = "2027-03-31T00:00:00Z",
    lines: Optional[List[Dict[str, Any]]] = None,
    finance_id: str = DEFAULT_FINANCE_ID,
) -> Dict[str, Any]:
    """Submit + accept a usage report; returns the ACCEPTED report."""
    report = create_usage_report(license_, maker, period_start, period_end, lines)
    return accept_usage_report(report, finance_id)


# ── Step fixtures: program lifecycle and remaining transitions ───────────────

def begin_qualification(
    program: Dict[str, Any], design_freeze_date: str = FREEZE_DEADLINE
) -> Dict[str, Any]:
    """COMPOSITION_TUNING -> QUALIFICATION; pins the design-freeze deadline.
    The deadline must lie strictly after the current logical clock."""
    return get_success_data(
        api_client.begin_qualification(
            program["id"], factories.begin_qualification_payload(design_freeze_date), MANAGER
        )
    )


def freeze_design(program: Dict[str, Any]) -> Dict[str, Any]:
    """QUALIFICATION -> DESIGN_FROZEN (assumes the deadline gate and the
    qualified-composition gate both hold)."""
    return get_success_data(api_client.freeze_design(program["id"], MANAGER))


def rework_program(program: Dict[str, Any]) -> Dict[str, Any]:
    """QUALIFICATION -> COMPOSITION_TUNING; clears the design-freeze date."""
    return get_success_data(api_client.rework_program(program["id"], MANAGER))


def close_program(program: Dict[str, Any]) -> Dict[str, Any]:
    """DESIGN_FROZEN -> CLOSED (assumes nothing is in flight)."""
    return get_success_data(api_client.close_program(program["id"], MANAGER))


def terminate_program(program: Dict[str, Any], reason: Optional[str] = None) -> Dict[str, Any]:
    """Terminate from any non-terminal program state; runs the commitment
    release and campaign cancel cascades."""
    payload = {"reason": reason} if reason is not None else None
    return get_success_data(api_client.terminate_program(program["id"], MANAGER, payload))


def lock_composition(composition: Dict[str, Any]) -> Dict[str, Any]:
    """QUALIFIED -> LOCKED (immutable thereafter)."""
    return get_success_data(api_client.lock_composition(composition["id"], MANAGER))


def retire_composition(composition: Dict[str, Any]) -> Dict[str, Any]:
    """EXPERIMENTAL/TUNED/QUALIFIED -> RETIRED; runs the four-hop cascade."""
    return get_success_data(api_client.retire_composition(composition["id"], MANAGER))


def ip_review(maker: Dict[str, Any], to_status: str) -> Dict[str, Any]:
    """Advance a maker's IP posture one legal hop to ``to_status``."""
    return get_success_data(
        api_client.ip_review_device_maker(maker["id"], factories.ip_review_payload(to_status), LEGAL)
    )


def abort_campaign(campaign: Dict[str, Any]) -> Dict[str, Any]:
    """SCHEDULED/RUNNING -> ABORTED; runs the allocation-release and
    breach-watch cascade."""
    return get_success_data(api_client.abort_campaign(campaign["id"], PLANNER))


def complete_campaign(campaign: Dict[str, Any]) -> Dict[str, Any]:
    """RUNNING -> COMPLETED: moves the logical clock to the campaign's
    end_date first, so the completion gate passes."""
    end = get_success_data(api_client.get_campaign(campaign["id"], PLANNER))["end_date"]
    set_clock(end)
    return get_success_data(api_client.complete_campaign(campaign["id"], PLANNER))
