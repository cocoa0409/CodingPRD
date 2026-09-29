"""Composite setup helpers for the ISO Residual Accounting API.

Every helper drives the public endpoints only — there is no back door into the
server's state. Setup calls use the lenient ``get_success_data`` validator so a
broken preamble surfaces as a setup failure rather than as a confusing
assertion error.

Money is always sent as an integer count of cents and percentages as decimal
fractions, exactly as the PRD requires.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    attrite_merchant_payload,
    create_adjustment_payload,
    create_advance_payload,
    create_agent_payload,
    create_chargeback_payload,
    create_merchant_payload,
    create_percent_advance_payload,
    create_processor_program_payload,
    create_residual_batch_payload,
    create_residual_line_payload,
    create_thin_residual_line_payload,
    hold_payload,
    notice_payload,
    reactivate_merchant_payload,
    reassign_agent_payload,
    request_info_payload,
    settle_payload,
    transfer_portfolio_payload,
    unique_checksum,
    unique_mid,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["iso_admin_headers"]
ANALYST = TEST_USERS["residual_analyst_headers"]
CONTROLLER = TEST_USERS["residual_controller_headers"]

CANONICAL_PERIOD = "2026-07"


# ------------------------------------------------------------------ calendar
def month_bounds(period_month: str) -> tuple:
    """Return (first day of the month, first day of the following month).

    The coverage window is half-open, so the second value is the exclusive end
    of a file that covers exactly one accounting month.
    """
    year, month = (int(part) for part in period_month.split("-"))
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return f"{year:04d}-{month:02d}-01", f"{next_year:04d}-{next_month:02d}-01"


# --------------------------------------------------------------------- clock
def set_logical_clock(current_utc: str, headers: Optional[Dict] = None) -> dict:
    """Move the server's logical current UTC instant."""
    return get_success_data(api_client.set_clock(current_utc, headers or ADMIN))


# ---------------------------------------------------------------- primitives
def make_program(**overrides) -> dict:
    """Register a processor program with the canonical buy-rate economics."""
    payload = create_processor_program_payload(**overrides)
    return get_success_data(api_client.create_processor_program(payload, ADMIN))


def make_agent(**overrides) -> dict:
    """Create an agent, optionally under a parent."""
    payload = create_agent_payload(**overrides)
    return get_success_data(api_client.create_agent(payload, ADMIN))


def make_merchant(owning_agent_id: str, processor_program_id: str, **overrides) -> dict:
    """Board a merchant; it lands in PENDING."""
    payload = create_merchant_payload(owning_agent_id, processor_program_id, **overrides)
    return get_success_data(api_client.create_merchant(payload, ADMIN))


def activate_merchant(merchant_id: str) -> dict:
    return get_success_data(api_client.activate_merchant(merchant_id, ADMIN))


def make_active_merchant(owning_agent_id: str, processor_program_id: str, **overrides) -> dict:
    """Board a merchant and move it to ACTIVE."""
    merchant = make_merchant(owning_agent_id, processor_program_id, **overrides)
    return activate_merchant(merchant["id"])


def attrite_merchant(merchant_id: str, attrition_date: str = "2026-07-20") -> dict:
    return get_success_data(
        api_client.attrite_merchant(merchant_id, attrite_merchant_payload(attrition_date), ADMIN)
    )


def reactivate_merchant(merchant_id: str, reactivation_date: str = "2026-07-25") -> dict:
    return get_success_data(
        api_client.reactivate_merchant(
            merchant_id, reactivate_merchant_payload(reactivation_date), ADMIN
        )
    )


def reassign_merchant(merchant_id: str, new_agent_id: str) -> dict:
    """Re-read the merchant's version, then reassign it to another active agent."""
    merchant = fetch_merchant(merchant_id)
    payload = reassign_agent_payload(new_agent_id, merchant["version"])
    return get_success_data(api_client.reassign_merchant_agent(merchant_id, payload, ADMIN))


def book_chargeback(merchant_id: str, **overrides) -> dict:
    payload = create_chargeback_payload(**overrides)
    return get_success_data(api_client.create_chargeback_event(merchant_id, payload, ANALYST))


def book_canonical_chargebacks(merchant_id: str, period_month: str = CANONICAL_PERIOD) -> List[dict]:
    """The 4,500-cent AGENT_CHARGED and 12,000-cent ISO_ABSORBED pair."""
    first = book_chargeback(
        merchant_id,
        amount_cents=4500,
        occurred_on="2026-07-12",
        period_month=period_month,
        liability="AGENT_CHARGED",
    )
    second = book_chargeback(
        merchant_id,
        amount_cents=12000,
        occurred_on="2026-07-20",
        period_month=period_month,
        liability="ISO_ABSORBED",
    )
    return [first, second]


def make_batch(processor_program_id: str, **overrides) -> dict:
    payload = create_residual_batch_payload(processor_program_id, **overrides)
    return get_success_data(api_client.create_residual_batch(payload, ANALYST))


def add_line(batch_id: str, merchant_id: str, **overrides) -> dict:
    """Append the canonical processor file line for one merchant."""
    payload = create_residual_line_payload(merchant_id, **overrides)
    return get_success_data(api_client.create_residual_line(batch_id, payload, ANALYST))


def add_thin_line(batch_id: str, merchant_id: str, **overrides) -> dict:
    """Append a 125-authorization line worth 3,200 cents of fee income."""
    payload = create_thin_residual_line_payload(merchant_id, **overrides)
    return get_success_data(api_client.create_residual_line(batch_id, payload, ANALYST))


def normalize_batch(batch_id: str) -> dict:
    return get_success_data(api_client.normalize_residual_batch(batch_id, ANALYST))


def recall_batch(batch_id: str) -> dict:
    return get_success_data(api_client.recall_residual_batch(batch_id, ANALYST))


def post_batch(batch_id: str) -> dict:
    return get_success_data(api_client.post_residual_batch(batch_id, CONTROLLER))


def reverse_batch(batch_id: str) -> dict:
    return get_success_data(api_client.reverse_residual_batch(batch_id, CONTROLLER))


def suspend_program(program_id: str) -> dict:
    return get_success_data(api_client.suspend_processor_program(program_id, ADMIN))


def reinstate_program(program_id: str) -> dict:
    return get_success_data(api_client.reinstate_processor_program(program_id, ADMIN))


# ------------------------------------------------------------------- reads
def fetch_program(program_id: str) -> dict:
    return get_success_data(api_client.get_processor_program(program_id, ADMIN))


def fetch_agent(agent_id: str) -> dict:
    return get_success_data(api_client.get_agent(agent_id, ADMIN))


def fetch_merchant(merchant_id: str) -> dict:
    return get_success_data(api_client.get_merchant(merchant_id, ADMIN))


def fetch_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_residual_batch(batch_id, ANALYST))


def fetch_line(line_id: str) -> dict:
    return get_success_data(api_client.get_residual_line(line_id, ANALYST))


def fetch_advance(advance_id: str) -> dict:
    return get_success_data(api_client.get_agent_advance(advance_id, ADMIN))


def fetch_statement_by_id(statement_id: str) -> dict:
    return get_success_data(api_client.get_agent_statement(statement_id, CONTROLLER))


def fetch_adjustment(adjustment_id: str) -> dict:
    return get_success_data(api_client.get_statement_adjustment(adjustment_id, CONTROLLER))


def list_rows(list_call, params: Optional[Dict] = None, headers: Optional[Dict] = None) -> tuple:
    """Run a list endpoint and return (rows, meta)."""
    response = list_call(headers or CONTROLLER, params or {})
    body = response.json()
    get_success_data(response)
    return body["data"], body["meta"]


def list_statements(**params) -> List[dict]:
    rows, _ = list_rows(api_client.list_agent_statements, params)
    return rows


def list_allocations(**params) -> List[dict]:
    rows, _ = list_rows(api_client.list_residual_allocations, params)
    return rows


def list_profitability(**params) -> List[dict]:
    rows, _ = list_rows(api_client.list_merchant_profitability, params)
    return rows


def list_adjustments(**params) -> List[dict]:
    rows, _ = list_rows(api_client.list_statement_adjustments, params)
    return rows


def list_lines(**params) -> List[dict]:
    rows, _ = list_rows(api_client.list_residual_lines, params)
    return rows


def list_batches(**params) -> List[dict]:
    rows, _ = list_rows(api_client.list_residual_batches, params)
    return rows


def list_advances(**params) -> List[dict]:
    rows, _ = list_rows(api_client.list_agent_advances, params, ADMIN)
    return rows


def list_chargebacks(**params) -> List[dict]:
    rows, _ = list_rows(api_client.list_chargeback_events, params, ANALYST)
    return rows


def fetch_statement(agent_id: str, period_month: str = CANONICAL_PERIOD) -> Optional[dict]:
    """The (agent_id, period_month) pair is unique, so at most one row matches."""
    rows = list_statements(agent_id=agent_id, period_month=period_month)
    return rows[0] if rows else None


def require_statement(agent_id: str, period_month: str = CANONICAL_PERIOD) -> dict:
    statement = fetch_statement(agent_id, period_month)
    assert statement is not None, (
        f"expected a statement for agent {agent_id} and period {period_month}"
    )
    return statement


# ------------------------------------------------------ statement lifecycle
def issue_statement(statement_id: str) -> dict:
    return get_success_data(api_client.issue_agent_statement(statement_id, CONTROLLER))


def recall_statement(statement_id: str) -> dict:
    return get_success_data(api_client.recall_agent_statement(statement_id, CONTROLLER))


def finalize_statement(statement_id: str) -> dict:
    return get_success_data(api_client.finalize_agent_statement(statement_id, CONTROLLER))


def hold_statement(statement_id: str, hold_reason: str = "MANUAL_REVIEW") -> dict:
    return get_success_data(
        api_client.hold_agent_statement(statement_id, hold_payload(hold_reason), CONTROLLER)
    )


def release_statement(statement_id: str) -> dict:
    return get_success_data(api_client.release_agent_statement_hold(statement_id, CONTROLLER))


def settle_statement(statement_id: str, paid_on: str = "2026-08-15") -> dict:
    return get_success_data(
        api_client.settle_agent_statement(statement_id, settle_payload(paid_on), CONTROLLER)
    )


# ------------------------------------------------------------- adjustments
def propose_adjustment(statement_id: str, headers: Optional[Dict] = None, **overrides) -> dict:
    """Re-read the statement's version, then propose a signed correction."""
    statement = fetch_statement_by_id(statement_id)
    payload = create_adjustment_payload(statement["version"], **overrides)
    return get_success_data(
        api_client.create_statement_adjustment(
            statement_id, payload, headers or CONTROLLER
        )
    )


def review_adjustment(adjustment_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.review_statement_adjustment(adjustment_id, headers or CONTROLLER)
    )


def request_info_on_adjustment(
    adjustment_id: str,
    info_request_note: str = "Provide the processor dispute record",
    headers: Optional[Dict] = None,
) -> dict:
    return get_success_data(
        api_client.request_info_statement_adjustment(
            adjustment_id, request_info_payload(info_request_note), headers or CONTROLLER
        )
    )


def resubmit_adjustment(adjustment_id: str, headers: Optional[Dict] = None, **payload) -> dict:
    return get_success_data(
        api_client.resubmit_statement_adjustment(
            adjustment_id, dict(payload), headers or CONTROLLER
        )
    )


def approve_adjustment(adjustment_id: str, headers: Optional[Dict] = None) -> dict:
    return get_success_data(
        api_client.approve_statement_adjustment(adjustment_id, headers or CONTROLLER)
    )


def reject_adjustment(adjustment_id: str, headers: Optional[Dict] = None, **payload) -> dict:
    return get_success_data(
        api_client.reject_statement_adjustment(
            adjustment_id, dict(payload), headers or CONTROLLER
        )
    )


def propose_and_apply_adjustment(
    statement_id: str,
    proposer: Optional[Dict] = None,
    approver: Optional[Dict] = None,
    **overrides,
) -> dict:
    """Walk PROPOSED -> UNDER_REVIEW -> APPLIED with two distinct principals."""
    from .test_users import CONTROLLER_ONE, CONTROLLER_TWO

    adjustment = propose_adjustment(statement_id, proposer or CONTROLLER_ONE, **overrides)
    review_adjustment(adjustment["id"], approver or CONTROLLER_TWO)
    return approve_adjustment(adjustment["id"], approver or CONTROLLER_TWO)


# ---------------------------------------------------------------- advances
def fund_advance(agent_id: str, **overrides) -> dict:
    """Fund a straight-line advance, re-reading the agent's version first."""
    agent = fetch_agent(agent_id)
    payload = create_advance_payload(agent["version"], **overrides)
    return get_success_data(api_client.create_agent_advance(agent_id, payload, ADMIN))


def fund_percent_advance(agent_id: str, **overrides) -> dict:
    """Fund a percent-of-residual advance, re-reading the agent's version first."""
    agent = fetch_agent(agent_id)
    payload = create_percent_advance_payload(agent["version"], **overrides)
    return get_success_data(api_client.create_agent_advance(agent_id, payload, ADMIN))


def restructure_advance(advance_id: str, **payload) -> dict:
    return get_success_data(
        api_client.restructure_agent_advance(advance_id, dict(payload), ADMIN)
    )


# --------------------------------------------------------- agent lifecycle
def file_notice(agent_id: str, departure_effective_date: str) -> dict:
    return get_success_data(
        api_client.file_agent_notice(
            agent_id, notice_payload(departure_effective_date), ADMIN
        )
    )


def rescind_notice(agent_id: str) -> dict:
    return get_success_data(api_client.rescind_agent_notice(agent_id, ADMIN))


def depart_agent(agent_id: str) -> dict:
    return get_success_data(api_client.depart_agent(agent_id, ADMIN))


def transfer_portfolio(agent_id: str, target_agent_id: str) -> dict:
    return get_success_data(
        api_client.transfer_agent_portfolio(
            agent_id, transfer_portfolio_payload(target_agent_id), ADMIN
        )
    )


def notice_and_depart(agent_id: str, departure_effective_date: str) -> dict:
    """File a notice for the current logical date and complete the departure."""
    file_notice(agent_id, departure_effective_date)
    return depart_agent(agent_id)


# ------------------------------------------------------ composite scenarios
def setup_program_agent_merchant(
    program_overrides: Optional[Dict] = None,
    agent_overrides: Optional[Dict] = None,
    merchant_overrides: Optional[Dict] = None,
    activate: bool = True,
) -> dict:
    """A program, one top-level agent and one merchant boarded under both."""
    program = make_program(**(program_overrides or {}))
    agent = make_agent(**(agent_overrides or {}))
    merchant = make_merchant(agent["id"], program["id"], **(merchant_overrides or {}))
    if activate:
        merchant = activate_merchant(merchant["id"])
    return {"program": program, "agent": agent, "merchant": merchant}


def setup_normalized_batch(
    period_month: str = CANONICAL_PERIOD,
    coverage_start: str = "2026-07-01",
    coverage_end: str = "2026-08-01",
    program_overrides: Optional[Dict] = None,
    agent_overrides: Optional[Dict] = None,
    merchant_overrides: Optional[Dict] = None,
    line_overrides: Optional[Dict] = None,
    with_chargebacks: bool = False,
) -> dict:
    """Program + active merchant + one canonical line, normalized but not posted."""
    base = setup_program_agent_merchant(
        program_overrides, agent_overrides, merchant_overrides
    )
    if with_chargebacks:
        book_canonical_chargebacks(base["merchant"]["id"], period_month)
    batch = make_batch(
        base["program"]["id"],
        period_month=period_month,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )
    line = add_line(batch["id"], base["merchant"]["id"], **(line_overrides or {}))
    batch = normalize_batch(batch["id"])
    base.update({"batch": batch, "line": line})
    return base


def setup_canonical_posted_period(
    period_month: str = CANONICAL_PERIOD,
    coverage_start: str = "2026-07-01",
    coverage_end: str = "2026-08-01",
    program_overrides: Optional[Dict] = None,
    agent_overrides: Optional[Dict] = None,
    merchant_overrides: Optional[Dict] = None,
    line_overrides: Optional[Dict] = None,
    with_chargebacks: bool = True,
    post: bool = True,
) -> dict:
    """The canonical monthly cycle for one agent and one merchant.

    Program economics 45 bps / 6 cents per item / 13 bps of assessment, an
    active merchant with a 3,900-cent equipment lease, the two July
    chargebacks, and the canonical processor line normalized and posted.
    """
    scenario = setup_normalized_batch(
        period_month=period_month,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        program_overrides=program_overrides,
        agent_overrides=agent_overrides,
        merchant_overrides=merchant_overrides,
        line_overrides=line_overrides,
        with_chargebacks=with_chargebacks,
    )
    if post:
        scenario["batch"] = post_batch(scenario["batch"]["id"])
        scenario["statement"] = fetch_statement(scenario["agent"]["id"], period_month)
    else:
        scenario["statement"] = None
    return scenario


def setup_thin_posted_period(
    period_month: str = CANONICAL_PERIOD,
    monthly_minimum_cents: int = 2500,
    per_transaction_fee_cents: int = 20,
    transaction_count: int = 125,
    program_overrides: Optional[Dict] = None,
    agent_overrides: Optional[Dict] = None,
    post: bool = True,
) -> dict:
    """A merchant with no equipment and no chargebacks, worth 70 cents of net revenue."""
    scenario = setup_program_agent_merchant(
        program_overrides,
        agent_overrides,
        {
            "monthly_minimum_cents": monthly_minimum_cents,
            "per_transaction_fee_cents": per_transaction_fee_cents,
            "equipment_lease_monthly_cents": 0,
            "boarded_on": "2026-01-05",
        },
    )
    start, end = month_bounds(period_month)
    batch = make_batch(
        scenario["program"]["id"],
        period_month=period_month,
        coverage_start=start,
        coverage_end=end,
    )
    line = add_thin_line(
        batch["id"], scenario["merchant"]["id"], transaction_count=transaction_count
    )
    batch = normalize_batch(batch["id"])
    scenario.update({"batch": batch, "line": line})
    if post:
        scenario["batch"] = post_batch(batch["id"])
        scenario["statement"] = fetch_statement(scenario["agent"]["id"], period_month)
    else:
        scenario["statement"] = None
    return scenario


def setup_three_level_hierarchy() -> dict:
    """A1 (0.30 / 0.55) -> A2 (0.40 / 0.50) -> A3 (0.45 / 0.45)."""
    a1 = make_agent(
        name="A1 Principal", split_pct=0.30, override_pct=0.55, vesting_start_date="2024-01-15"
    )
    a2 = make_agent(
        name="A2 Regional",
        split_pct=0.40,
        override_pct=0.50,
        vesting_start_date="2025-01-15",
        parent_agent_id=a1["id"],
    )
    a3 = make_agent(
        name="A3 Rep",
        split_pct=0.45,
        override_pct=0.45,
        vesting_start_date="2026-02-01",
        parent_agent_id=a2["id"],
    )
    return {"a1": a1, "a2": a2, "a3": a3}


def setup_hierarchy_posted_period(
    period_month: str = CANONICAL_PERIOD,
    program_overrides: Optional[Dict] = None,
    merchant_overrides: Optional[Dict] = None,
    line_overrides: Optional[Dict] = None,
    with_chargebacks: bool = True,
    post: bool = True,
) -> dict:
    """Three-level hierarchy with the canonical merchant owned by the bottom agent."""
    program = make_program(**(program_overrides or {}))
    hierarchy = setup_three_level_hierarchy()
    merchant = make_active_merchant(
        hierarchy["a3"]["id"], program["id"], **(merchant_overrides or {})
    )
    if with_chargebacks:
        book_canonical_chargebacks(merchant["id"], period_month)
    batch = make_batch(
        program["id"],
        period_month=period_month,
        coverage_start="2026-07-01",
        coverage_end="2026-08-01",
    )
    line = add_line(batch["id"], merchant["id"], **(line_overrides or {}))
    batch = normalize_batch(batch["id"])
    scenario = {
        "program": program,
        "merchant": merchant,
        "batch": batch,
        "line": line,
        **hierarchy,
    }
    if post:
        scenario["batch"] = post_batch(batch["id"])
        scenario["statements"] = {
            key: fetch_statement(hierarchy[key]["id"], period_month)
            for key in ("a1", "a2", "a3")
        }
    return scenario


def setup_two_agent_posted_period(
    period_month: str = CANONICAL_PERIOD,
    program_overrides: Optional[Dict] = None,
    merchant_overrides_x: Optional[Dict] = None,
    merchant_overrides_y: Optional[Dict] = None,
    line_overrides_x: Optional[Dict] = None,
    line_overrides_y: Optional[Dict] = None,
    with_chargebacks: bool = True,
    thin_lines: bool = False,
    post: bool = True,
) -> dict:
    """Two independent top-level agents, one merchant each, inside one batch."""
    program = make_program(**(program_overrides or {}))
    agent_x = make_agent(name="AX", split_pct=0.45, override_pct=0.45,
                         vesting_start_date="2024-01-15")
    agent_y = make_agent(name="AY", split_pct=0.45, override_pct=0.45,
                         vesting_start_date="2024-01-15")
    merchant_x = make_active_merchant(agent_x["id"], program["id"], **(merchant_overrides_x or {}))
    merchant_y = make_active_merchant(agent_y["id"], program["id"], **(merchant_overrides_y or {}))
    if with_chargebacks:
        book_canonical_chargebacks(merchant_x["id"], period_month)
        book_canonical_chargebacks(merchant_y["id"], period_month)
    batch = make_batch(
        program["id"],
        period_month=period_month,
        coverage_start="2026-07-01",
        coverage_end="2026-08-01",
    )
    appender = add_thin_line if thin_lines else add_line
    line_x = appender(batch["id"], merchant_x["id"], **(line_overrides_x or {}))
    line_y = appender(batch["id"], merchant_y["id"], **(line_overrides_y or {}))
    batch = normalize_batch(batch["id"])
    scenario = {
        "program": program,
        "agent_x": agent_x,
        "agent_y": agent_y,
        "merchant_x": merchant_x,
        "merchant_y": merchant_y,
        "batch": batch,
        "line_x": line_x,
        "line_y": line_y,
    }
    if post:
        scenario["batch"] = post_batch(batch["id"])
        scenario["statement_x"] = fetch_statement(agent_x["id"], period_month)
        scenario["statement_y"] = fetch_statement(agent_y["id"], period_month)
    return scenario


def setup_agent_with_qualifying_merchants(
    active_count: int = 3,
    attrited_count: int = 1,
    attrition_date: str = "2026-07-20",
    upfront_bonus_cents: int = 0,
    boarded_on: str = "2026-01-05",
    program_overrides: Optional[Dict] = None,
    agent_overrides: Optional[Dict] = None,
) -> dict:
    """An agent whose book contains a known mix of ACTIVE and ATTRITED merchants.

    The attrition rate denominator counts ACTIVE plus ATTRITED merchants, so this
    fixture puts the agent at a precisely known ``portfolio_attrition_bps``.
    """
    program = make_program(**(program_overrides or {}))
    agent = make_agent(**(agent_overrides or {}))
    merchants = []
    for _ in range(active_count + attrited_count):
        merchants.append(
            make_active_merchant(
                agent["id"],
                program["id"],
                mid=unique_mid("MID-Q"),
                monthly_minimum_cents=0,
                per_transaction_fee_cents=15,
                equipment_lease_monthly_cents=0,
                upfront_bonus_cents=upfront_bonus_cents,
                boarded_on=boarded_on,
            )
        )
    attrited = []
    for merchant in merchants[:attrited_count]:
        attrited.append(attrite_merchant(merchant["id"], attrition_date))
    return {
        "program": program,
        "agent": fetch_agent(agent["id"]),
        "merchants": merchants,
        "attrited": attrited,
    }


def setup_adjustment_under_review(
    statement_id: str,
    proposer: Optional[Dict] = None,
    reviewer: Optional[Dict] = None,
    **overrides,
) -> dict:
    """Propose an adjustment and take it UNDER_REVIEW with a second principal."""
    from .test_users import CONTROLLER_ONE, CONTROLLER_TWO

    adjustment = propose_adjustment(statement_id, proposer or CONTROLLER_ONE, **overrides)
    return review_adjustment(adjustment["id"], reviewer or CONTROLLER_TWO)


def setup_issued_statement(
    period_month: str = CANONICAL_PERIOD,
    **scenario_kwargs,
) -> dict:
    """The canonical posted period with the agent's statement issued."""
    scenario = setup_canonical_posted_period(period_month=period_month, **scenario_kwargs)
    scenario["statement"] = issue_statement(scenario["statement"]["id"])
    return scenario


def setup_settleable_statement(period_month: str = CANONICAL_PERIOD, **scenario_kwargs) -> dict:
    """An ISSUED, UNSETTLED statement whose net payable clears the payout floor."""
    return setup_issued_statement(period_month=period_month, **scenario_kwargs)


def checksum(label: str) -> str:
    """A deterministic, unique file checksum built around a readable label."""
    return unique_checksum(f"sha256:{label}")
