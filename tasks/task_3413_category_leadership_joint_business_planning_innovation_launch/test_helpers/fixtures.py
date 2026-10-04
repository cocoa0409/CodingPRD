"""Composite setup helpers — multi-step state builders used by the test suite.

Conventions
-----------
* Every helper builds state exclusively through PRD-declared endpoints; the
  server is restarted before each test, so nothing is ever assumed to pre-exist.
* Setup calls use the lenient ``get_success_data`` validator, so a broken
  precondition surfaces as a clear "Setup step failed" error.
* Identity threading: ``RetailerBuyer`` is entity-backed (PRD §2.1), so every
  ownership-gated call uses ``make_retailer_buyer_headers(retailer["id"])`` —
  never the shared fallback constant.
* Time-windowed preconditions are reached by advancing the shared logical
  clock (PRD §2.4) via the PlatformAdmin-only endpoint, never by assuming
  wall-clock dates. The clock is monotonic non-decreasing, so helpers use
  ``ensure_clock_at_least``: setting an earlier instant fails ERR_VALIDATION,
  which proves the clock is already past the target and the precondition
  ``clock >= target`` holds either way.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import MAX_NEGOTIATION_ROUNDS, REVIEW_MIN_DAYS_AFTER_LAUNCH
from .factories import (
    DEFAULTS,
    create_activate_payload,
    create_analysis_decide_payload,
    create_analysis_payload,
    create_category_payload,
    create_deduction_payload,
    create_deduction_resolve_payload,
    create_event_payload,
    create_forecast_commit_payload,
    create_forecast_payload,
    create_launch_payload,
    create_negotiate_payload,
    create_phase_patch_payload,
    create_plan_decide_payload,
    create_plan_payload,
    create_ppd_decide_payload,
    create_ppd_payload,
    create_retailer_payload,
    create_review_payload,
    create_shelf_decide_payload,
    create_shelf_rec_payload,
)
from .test_users import TEST_USERS, make_retailer_buyer_headers
from .types import DeductionAction, PlanDecision, PricePackDecision, ShelfRecDecision, AnalysisDecision

# Header shortcuts for the five opaque roles (safe to share: their X-User-ID is
# never compared to any entity id — PRD §2.1).
ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
PLANNER_HEADERS = TEST_USERS["manufacturer_planner_headers"]
ADVISOR_HEADERS = TEST_USERS["category_advisor_headers"]
SUPPLY_HEADERS = TEST_USERS["supply_chain_planner_headers"]
FINANCE_HEADERS = TEST_USERS["finance_analyst_headers"]

_ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


# ---------------------------------------------------------------------------
# Logical clock helpers (PRD §2.4)
# ---------------------------------------------------------------------------

def add_days_iso(iso: str, days: int) -> str:
    """Add ``days`` days to a ``YYYY-MM-DDTHH:MM:SSZ`` instant."""
    dt = datetime.strptime(iso, _ISO_FORMAT) + timedelta(days=days)
    return dt.strftime(_ISO_FORMAT)


def set_clock(to_iso8601: str) -> dict:
    """Set the logical clock; fails hard if the server rejects the advance."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN_HEADERS)
    )


def ensure_clock_at_least(to_iso8601: str) -> None:
    """Guarantee ``clock >= to_iso8601`` afterwards.

    The clock is monotonic non-decreasing: setting an earlier instant is
    rejected with ERR_VALIDATION (PRD §2.4), which here means the clock already
    reads later than the target — exactly the condition the caller needs.
    """
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN_HEADERS)
    if resp.status_code == 200:
        return
    body = resp.json() if resp.text else {}
    err = body.get("data", {}).get("error_id") if isinstance(body, dict) else None
    if resp.status_code == 400 and err == "ERR_VALIDATION":
        return  # clock already ahead of the target
    raise AssertionError(f"Clock advance to {to_iso8601} failed: HTTP {resp.status_code} {body}")


# ---------------------------------------------------------------------------
# Reference data (PRD §3.1)
# ---------------------------------------------------------------------------

def create_retailer(**overrides) -> dict:
    """Create a Retailer (PlatformAdmin). Returns the retailer resource."""
    return get_success_data(
        api_client.create_retailer(create_retailer_payload(**overrides), ADMIN_HEADERS)
    )


def create_category(**overrides) -> dict:
    """Create a Category (PlatformAdmin). Returns the category resource."""
    return get_success_data(
        api_client.create_category(create_category_payload(**overrides), ADMIN_HEADERS)
    )


# ---------------------------------------------------------------------------
# Plan lifecycle (PRD §3.1)
# ---------------------------------------------------------------------------

def create_plan(retailer_id: str, category_id: str, **overrides) -> dict:
    """Create a JointBusinessPlan (ManufacturerPlanner); lands PROPOSED, round 1."""
    return get_success_data(
        api_client.create_plan(
            create_plan_payload(retailer_id, category_id, **overrides), PLANNER_HEADERS
        )
    )


def get_plan(plan_id: str) -> dict:
    """Fresh read of a plan (ManufacturerPlanner)."""
    return get_success_data(api_client.get_plan(plan_id, PLANNER_HEADERS))


def get_plan_version(plan_id: str) -> int:
    """Capture the plan's current OCC version (PRD §2.8)."""
    return get_plan(plan_id)["version"]


def setup_proposed_plan(
    retailer_overrides: Optional[Dict] = None,
    category_overrides: Optional[Dict] = None,
    **plan_overrides,
) -> dict:
    """Retailer + category + one PROPOSED plan.

    Returns {"retailer", "category", "plan", "buyer_headers"} where
    buyer_headers is the entity-backed RetailerBuyer identity for the retailer.
    """
    retailer = create_retailer(**(retailer_overrides or {}))
    category = create_category(**(category_overrides or {}))
    plan = create_plan(retailer["id"], category["id"], **plan_overrides)
    return {
        "retailer": retailer,
        "category": category,
        "plan": plan,
        "buyer_headers": make_retailer_buyer_headers(retailer["id"]),
    }


def setup_accepted_plan(
    retailer_overrides: Optional[Dict] = None,
    category_overrides: Optional[Dict] = None,
    **plan_overrides,
) -> dict:
    """PROPOSED plan + retailer decide ACCEPT -> ACCEPTED (version 2)."""
    scenario = setup_proposed_plan(retailer_overrides, category_overrides, **plan_overrides)
    scenario["plan"] = get_success_data(
        api_client.decide_plan(
            scenario["plan"]["id"],
            create_plan_decide_payload(PlanDecision.ACCEPT.value),
            scenario["buyer_headers"],
        )
    )
    return scenario


def setup_activated_plan(
    retailer_overrides: Optional[Dict] = None,
    category_overrides: Optional[Dict] = None,
    accrual_rate_pct=DEFAULTS["ACCRUAL_RATE_PCT"],
    edlp_split_pct=DEFAULTS["EDLP_SPLIT_PCT"],
    **plan_overrides,
) -> dict:
    """ACCEPTED plan + activate -> ACTIVATED (version 3) with its TradeFund.

    Returns {"retailer", "category", "plan", "fund", "buyer_headers"}.
    """
    scenario = setup_accepted_plan(retailer_overrides, category_overrides, **plan_overrides)
    scenario["plan"] = get_success_data(
        api_client.activate_plan(
            scenario["plan"]["id"],
            create_activate_payload(
                accrual_rate_pct=accrual_rate_pct, edlp_split_pct=edlp_split_pct
            ),
            PLANNER_HEADERS,
        )
    )
    scenario["fund"] = get_fund_for_plan(scenario["plan"]["id"])
    return scenario


def negotiate_rounds(plan_id: str, retailer_id: str, targets: List[float]) -> List[dict]:
    """Alternating negotiation moves over ``targets``: index 0 is the retailer
    countering from PROPOSED, index 1 the manufacturer re-proposing from
    COUNTERED, and so on (PRD §3.1). Returns the plan after each move."""
    buyer_headers = make_retailer_buyer_headers(retailer_id)
    plans = []
    for i, target in enumerate(targets):
        headers = buyer_headers if i % 2 == 0 else PLANNER_HEADERS
        plans.append(
            get_success_data(
                api_client.negotiate_plan(plan_id, create_negotiate_payload(target), headers)
            )
        )
    return plans


def drive_plan_to_exhaustion(plan_id: str, retailer_id: str) -> requests.Response:
    """From a fresh PROPOSED plan (round 1): run the 5 successful alternating
    negotiates that bring negotiation_round to MAX_NEGOTIATION_ROUNDS, then fire
    the failing move. Returns the failed response (rounds exhausted; the plan
    auto-transitions to EXPIRED inside the same failed request — PRD §2.10).
    """
    moves = ([9, 10] * MAX_NEGOTIATION_ROUNDS)[: MAX_NEGOTIATION_ROUNDS - 1]
    negotiate_rounds(plan_id, retailer_id, moves)
    return api_client.negotiate_plan(plan_id, create_negotiate_payload(10), PLANNER_HEADERS)


# ---------------------------------------------------------------------------
# Promotional events (PRD §3.2)
# ---------------------------------------------------------------------------

def create_penciled_event(plan_id: str, **overrides) -> dict:
    """Pencil an event (ManufacturerPlanner); lands PENCILED, estimate null."""
    return get_success_data(
        api_client.create_event(plan_id, create_event_payload(**overrides), PLANNER_HEADERS)
    )


def create_locked_event(plan_id: str, **overrides) -> dict:
    """Create an event and lock it. The plan must be ACTIVATED and the fund's
    event bucket must cover the computed estimate — arrange accruals first."""
    event = create_penciled_event(plan_id, **overrides)
    return get_success_data(api_client.lock_event(event["id"], PLANNER_HEADERS))


# ---------------------------------------------------------------------------
# Category analyses (PRD §3.3)
# ---------------------------------------------------------------------------

def create_submitted_analysis(plan_id: str, **overrides) -> dict:
    """Submit an analysis (CategoryAdvisor); lands SUBMITTED."""
    return get_success_data(
        api_client.create_category_analysis(
            plan_id, create_analysis_payload(**overrides), ADVISOR_HEADERS
        )
    )


def create_accepted_analysis(plan_id: str, retailer_id: str, **overrides) -> dict:
    """Submit + retailer ACCEPT -> ACCEPTED analysis."""
    analysis = create_submitted_analysis(plan_id, **overrides)
    return get_success_data(
        api_client.decide_category_analysis(
            analysis["id"],
            create_analysis_decide_payload(AnalysisDecision.ACCEPT.value),
            make_retailer_buyer_headers(retailer_id),
        )
    )


# ---------------------------------------------------------------------------
# Shelf recommendations (PRD §3.4)
# ---------------------------------------------------------------------------

def create_proposed_shelf_rec(
    plan_id: str,
    expected_plan_version: Optional[int] = None,
    **overrides,
) -> dict:
    """Create a shelf recommendation (CategoryAdvisor, OCC-guarded).

    ``expected_plan_version=None`` captures the plan's live version via GET
    immediately before the create (PRD §2.8). The caller must already have
    arranged the plan status (ACCEPTED/ACTIVATED) and an ACCEPTED analysis.
    """
    if expected_plan_version is None:
        expected_plan_version = get_plan_version(plan_id)
    return get_success_data(
        api_client.create_shelf_recommendation(
            plan_id,
            create_shelf_rec_payload(expected_plan_version, **overrides),
            ADVISOR_HEADERS,
        )
    )


def create_implementing_shelf_rec(
    plan_id: str,
    retailer_id: str,
    accepted_clock: Optional[str] = None,
    analysis_overrides: Optional[Dict] = None,
    **overrides,
) -> dict:
    """ACCEPTED analysis + PROPOSED recommendation + retailer ACCEPT ->
    IMPLEMENTING. ``accepted_clock`` advances the logical clock to that instant
    before acceptance, pinning ``accepted_at`` for SLA-window tests."""
    create_accepted_analysis(plan_id, retailer_id, **(analysis_overrides or {}))
    rec = create_proposed_shelf_rec(plan_id, **overrides)
    if accepted_clock is not None:
        set_clock(accepted_clock)
    return get_success_data(
        api_client.decide_shelf_recommendation(
            rec["id"],
            create_shelf_decide_payload(ShelfRecDecision.ACCEPT.value),
            make_retailer_buyer_headers(retailer_id),
        )
    )


# ---------------------------------------------------------------------------
# Launches and phases (PRD §3.5)
# ---------------------------------------------------------------------------

def list_phases(launch_id: str) -> List[dict]:
    """The launch's phases in phase_index ascending order (PRD §3.5)."""
    phases = get_success_data(api_client.list_launch_phases(launch_id, PLANNER_HEADERS))
    return sorted(phases, key=lambda p: p["phase_index"])


def create_launch_with_phases(plan_id: str, **overrides) -> Tuple[dict, List[dict]]:
    """Create a launch (ManufacturerPlanner) and read back its auto-created
    phases. Returns (launch, phases sorted by phase_index)."""
    launch = get_success_data(
        api_client.create_launch(plan_id, create_launch_payload(**overrides), PLANNER_HEADERS)
    )
    return launch, list_phases(launch["id"])


def gate_all_phases(
    launch_id: str,
    phases: Optional[List[dict]] = None,
    patch_overrides: Optional[Dict] = None,
) -> List[dict]:
    """Patch every phase with gate-passing inputs and evaluate in ascending
    phase_index order (the sequencing precondition — PRD §3.5). Returns the
    refreshed phases, all GATE_PASSED."""
    if phases is None:
        phases = list_phases(launch_id)
    for phase in sorted(phases, key=lambda p: p["phase_index"]):
        get_success_data(
            api_client.patch_launch_phase(
                launch_id,
                phase["id"],
                create_phase_patch_payload(**(patch_overrides or {})),
                PLANNER_HEADERS,
            )
        )
        get_success_data(api_client.evaluate_launch_phase(launch_id, phase["id"], PLANNER_HEADERS))
    return list_phases(launch_id)


def execute_launch(launch_id: str, launch_date: str) -> dict:
    """Advance the logical clock to >= launch_date, then execute the launch
    (ManufacturerPlanner). Returns the LAUNCHED launch."""
    ensure_clock_at_least(launch_date)
    return get_success_data(api_client.execute_launch(launch_id, PLANNER_HEADERS))


def create_launched_launch(
    plan_id: str,
    launch_date: str = DEFAULTS["LAUNCH_DATE"],
    phase_patch: Optional[Dict] = None,
    **overrides,
) -> Tuple[dict, List[dict]]:
    """Launch created, all four phases gate-passed, clock advanced to the
    launch date, launch executed. Returns (LAUNCHED launch, phases)."""
    overrides.setdefault("launch_date", launch_date)
    launch, phases = create_launch_with_phases(plan_id, **overrides)
    phases = gate_all_phases(launch["id"], phases, phase_patch)
    launch = execute_launch(launch["id"], launch_date)
    return launch, phases


# ---------------------------------------------------------------------------
# Trade funds (PRD §3.6)
# ---------------------------------------------------------------------------

def get_fund(fund_id: str) -> dict:
    """Fresh read of a fund (FinanceAnalyst)."""
    return get_success_data(api_client.get_fund(fund_id, FINANCE_HEADERS))


def get_fund_for_plan(plan_id: str) -> dict:
    """Locate the plan's single fund via the plan_id filter (PRD §3.6)."""
    funds = get_success_data(
        api_client.list_funds(PLANNER_HEADERS, params={"plan_id": plan_id})
    )
    assert isinstance(funds, list) and len(funds) == 1, (
        f"Setup failed: expected exactly one fund for plan {plan_id}, got {funds!r}"
    )
    return funds[0]


def post_accrual(fund_id: str, period: str, invoiced_sales_cents: int) -> dict:
    """Post one period's invoiced sales (FinanceAnalyst); returns the fund."""
    return get_success_data(
        api_client.post_fund_accrual(
            fund_id,
            {"period": period, "invoiced_sales_cents": invoiced_sales_cents},
            FINANCE_HEADERS,
        )
    )


# ---------------------------------------------------------------------------
# Deductions (PRD §3.6)
# ---------------------------------------------------------------------------

def file_deduction(
    fund_id: str,
    retailer_id: str,
    claim_reference: str,
    bucket: str = DEFAULTS["DEDUCTION_BUCKET"],
    amount_cents: int = DEFAULTS["DEDUCTION_AMOUNT_CENTS"],
) -> dict:
    """File a deduction claim (RetailerBuyer of the fund's plan); lands RECEIVED."""
    return get_success_data(
        api_client.create_deduction(
            fund_id,
            create_deduction_payload(claim_reference, bucket=bucket, amount_cents=amount_cents),
            make_retailer_buyer_headers(retailer_id),
        )
    )


def resolve_deduction(deduction_id: str, action: str) -> dict:
    """Resolve a deduction (FinanceAnalyst) with DISPUTE / SETTLE / REJECT /
    WRITE_OFF. Returns the updated deduction."""
    return get_success_data(
        api_client.resolve_deduction(
            deduction_id, create_deduction_resolve_payload(action), FINANCE_HEADERS
        )
    )


def create_disputed_deductions(
    fund_id: str,
    retailer_id: str,
    count: int,
    bucket: str = DEFAULTS["DEDUCTION_BUCKET"],
    amount_cents: int = DEFAULTS["DEDUCTION_AMOUNT_CENTS"],
    ref_prefix: str = "DD",
) -> List[dict]:
    """File ``count`` deductions and dispute each one. Returns the DISPUTED
    deductions in creation order."""
    disputed = []
    for i in range(count):
        ded = file_deduction(
            fund_id, retailer_id, f"{ref_prefix}-{i + 1}", bucket=bucket, amount_cents=amount_cents
        )
        disputed.append(resolve_deduction(ded["id"], DeductionAction.DISPUTE.value))
    return disputed


# ---------------------------------------------------------------------------
# Forecasts (PRD §3.7)
# ---------------------------------------------------------------------------

def create_published_forecast(
    plan_id: str,
    week_start: str = DEFAULTS["WEEK_START"],
    baseline_cases: int = DEFAULTS["BASELINE_CASES"],
) -> dict:
    """Publish a forecast (SupplyChainPlanner); lands PUBLISHED / UNCOMMITTED."""
    return get_success_data(
        api_client.create_forecast(
            plan_id,
            create_forecast_payload(week_start=week_start, baseline_cases=baseline_cases),
            SUPPLY_HEADERS,
        )
    )


def create_committed_forecast(
    plan_id: str,
    retailer_id: str,
    week_start: str = DEFAULTS["WEEK_START"],
    baseline_cases: int = DEFAULTS["BASELINE_CASES"],
    committed_cases: int = DEFAULTS["COMMITTED_CASES"],
) -> dict:
    """Publish + retailer commit -> PUBLISHED / COMMITTED forecast."""
    forecast = create_published_forecast(plan_id, week_start=week_start, baseline_cases=baseline_cases)
    return get_success_data(
        api_client.commit_forecast(
            forecast["id"],
            create_forecast_commit_payload(committed_cases),
            make_retailer_buyer_headers(retailer_id),
        )
    )


# ---------------------------------------------------------------------------
# Price-pack decisions (PRD §3.8)
# ---------------------------------------------------------------------------

def create_price_pack(plan_id: str, **overrides) -> dict:
    """Propose a price-pack decision (ManufacturerPlanner); lands PROPOSED."""
    return get_success_data(
        api_client.create_price_pack_decision(
            plan_id, create_ppd_payload(**overrides), PLANNER_HEADERS
        )
    )


def create_approved_price_pack(plan_id: str, retailer_id: str, **overrides) -> dict:
    """Propose + retailer APPROVE -> APPROVED price-pack decision. The caller
    is responsible for keeping channel-conflict rules satisfied."""
    ppd = create_price_pack(plan_id, **overrides)
    return get_success_data(
        api_client.decide_price_pack_decision(
            ppd["id"],
            create_ppd_decide_payload(PricePackDecision.APPROVE.value),
            make_retailer_buyer_headers(retailer_id),
        )
    )


# ---------------------------------------------------------------------------
# Performance reviews (PRD §3.9)
# ---------------------------------------------------------------------------

def create_open_review(launch_id: str, launch_date: str, **overrides) -> dict:
    """Advance the clock to >= launch_date + REVIEW_MIN_DAYS_AFTER_LAUNCH days
    (the review-eligibility boundary — PRD §3.9), then open the review
    (ManufacturerPlanner). Returns the OPEN review."""
    ensure_clock_at_least(add_days_iso(launch_date, REVIEW_MIN_DAYS_AFTER_LAUNCH))
    return get_success_data(
        api_client.create_performance_review(
            launch_id, create_review_payload(**overrides), PLANNER_HEADERS
        )
    )


# ---------------------------------------------------------------------------
# Composite scenarios
# ---------------------------------------------------------------------------

def setup_launched_scenario(
    launch_date: str = DEFAULTS["LAUNCH_DATE"],
    phase_patch: Optional[Dict] = None,
    launch_overrides: Optional[Dict] = None,
    **plan_kwargs,
) -> dict:
    """Activated plan + fund + one fully gate-passed LAUNCHED launch.

    Returns {"retailer", "category", "plan", "fund", "buyer_headers",
    "launch", "phases"}.
    """
    scenario = setup_activated_plan(**plan_kwargs)
    launch, phases = create_launched_launch(
        scenario["plan"]["id"],
        launch_date=launch_date,
        phase_patch=phase_patch,
        **(launch_overrides or {}),
    )
    scenario["launch"] = launch
    scenario["phases"] = phases
    return scenario


def setup_review_scenario(
    *,
    launch_date: str = DEFAULTS["LAUNCH_DATE"],
    review_period_start: str = DEFAULTS["REVIEW_PERIOD_START"],
    review_period_end: str = DEFAULTS["REVIEW_PERIOD_END"],
    activity_clock: Optional[str] = None,
    committed_forecast: Optional[Tuple[str, int, int]] = None,
    published_forecasts: Tuple[Tuple[str, int], ...] = (),
    accruals: Tuple[Tuple[str, int], ...] = (),
    received_deductions: Tuple[Tuple[str, str, int], ...] = (),
    disputed_deductions: int = 0,
    deduction_bucket: str = DEFAULTS["DEDUCTION_BUCKET"],
    deduction_amount_cents: int = DEFAULTS["DEDUCTION_AMOUNT_CENTS"],
    review_fields: Optional[Dict] = None,
    plan_kwargs: Optional[Dict] = None,
    launch_overrides: Optional[Dict] = None,
) -> dict:
    """Full pipeline through an OPEN performance review.

    Order of operations (clock-safe, monotonic):
      1. activated plan + fund;
      2. accruals posted;
      3. clock advanced to ``activity_clock`` (defaults to
         ``review_period_start``) so that deduction ``created_at`` stamps land
         inside the review window — the review's friction_count only tallies
         deductions created within [period_start, period_end] (PRD §3.9);
      4. forecasts published / committed (bias inputs);
      5. deductions filed / disputed (friction inputs);
      6. launch created, gated, and executed (clock advanced to launch_date);
      7. review opened (clock advanced to launch_date + 84 days).

    ``committed_forecast`` is ``(week_start, baseline_cases, committed_cases)``;
    ``published_forecasts`` extra uncommitted ``(week_start, baseline_cases)``;
    ``accruals`` are ``(period, invoiced_sales_cents)``; ``received_deductions``
    are ``(claim_reference, bucket, amount_cents)`` filed but left RECEIVED.

    Returns {"retailer", "category", "plan", "fund", "buyer_headers",
    "launch", "phases", "review", "forecasts", "deductions"}.
    """
    scenario = setup_activated_plan(**(plan_kwargs or {}))
    plan = scenario["plan"]
    fund = scenario["fund"]
    retailer = scenario["retailer"]

    for period, amount in accruals:
        post_accrual(fund["id"], period, amount)

    set_clock(activity_clock or review_period_start)

    forecasts = []
    if committed_forecast is not None:
        week_start, baseline, committed = committed_forecast
        forecasts.append(
            create_committed_forecast(
                plan["id"], retailer["id"],
                week_start=week_start, baseline_cases=baseline, committed_cases=committed,
            )
        )
    for week_start, baseline in published_forecasts:
        forecasts.append(
            create_published_forecast(plan["id"], week_start=week_start, baseline_cases=baseline)
        )

    deductions = []
    for ref, bucket, amount in received_deductions:
        deductions.append(file_deduction(fund["id"], retailer["id"], ref, bucket=bucket, amount_cents=amount))
    deductions.extend(
        create_disputed_deductions(
            fund["id"], retailer["id"], disputed_deductions,
            bucket=deduction_bucket, amount_cents=deduction_amount_cents,
        )
    )

    launch, phases = create_launched_launch(
        plan["id"], launch_date=launch_date, **(launch_overrides or {})
    )

    review_overrides = {"period_start": review_period_start, "period_end": review_period_end}
    review_overrides.update(review_fields or {})
    review = create_open_review(launch["id"], launch_date, **review_overrides)

    scenario.update(
        {
            "launch": launch,
            "phases": phases,
            "review": review,
            "forecasts": forecasts,
            "deductions": deductions,
        }
    )
    return scenario
