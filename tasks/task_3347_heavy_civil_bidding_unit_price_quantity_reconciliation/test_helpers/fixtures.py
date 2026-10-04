"""Composite setup helpers.

Every fixture builds its preconditions from scratch through PRD-declared
endpoints, because the harness restarts the server (and therefore empties the
database) before every single test.

Layering:

* primitive helpers — one entity each
* ``setup_*`` composites — a project walked to a named lifecycle stage
* threshold helpers — a project parked at an exact cumulative state
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    BOND_EFFECTIVE_FROM,
    BOND_EFFECTIVE_TO,
    CREW_DAY_EQUIPMENT_CENTS,
    CREW_DAY_LABOR_CENTS,
    DAILY_PRODUCTIVITY_UNITS,
    DEFAULT_ADVERTISED_DBE_GOAL_PCT,
    DEFAULT_BID_DEADLINE_AT,
    DEFAULT_MEASURED_AT,
    DEFAULT_RETENTION_RATE_PCT,
    LOGICAL_CLOCK_START,
    OVERRUN_THRESHOLD_PCT,
    QUOTE_WINDOW_END,
    QUOTE_WINDOW_START,
    SURETY_AGGREGATE_CAPACITY_CENTS,
    SURETY_NAME,
    SURETY_SINGLE_JOB_LIMIT_CENTS,
    UNDERRUN_THRESHOLD_PCT,
)
from .test_users import TEST_USERS, make_surety_headers

ADMIN = TEST_USERS["platform_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
OFFICER = TEST_USERS["contracting_officer_headers"]
MANAGER = TEST_USERS["project_manager_headers"]
ENGINEER = TEST_USERS["engineer_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def advance_clock(to_iso8601, headers=None):
    """Advance the logical clock; time never moves any other way."""
    return get_success_data(
        api_client.set_current_utc(to_iso8601, headers or ADMIN)
    )


def reset_clock():
    advance_clock(LOGICAL_CLOCK_START)


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------

def create_project(**overrides):
    payload = {
        "project_code": "CALTRANS-04-1J5604",
        "owner_agency_name": "Caltrans District 4",
        "contract_type": "UNIT_PRICE",
        "bid_deadline_at": DEFAULT_BID_DEADLINE_AT,
        "retention_rate_pct": DEFAULT_RETENTION_RATE_PCT,
        "advertised_dbe_goal_pct": DEFAULT_ADVERTISED_DBE_GOAL_PCT,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_project(payload, ESTIMATOR), 201)


def create_surety(**overrides):
    payload = {
        "surety_name": SURETY_NAME,
        "aggregate_capacity_cents": SURETY_AGGREGATE_CAPACITY_CENTS,
        "single_job_limit_cents": SURETY_SINGLE_JOB_LIMIT_CENTS,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_surety(payload, ADMIN), 201)


def create_bid_item(project_id, **overrides):
    payload = {
        "item_code": "2025-390102",
        "item_description": "Class 2 aggregate base",
        "unit_of_measure": "TON",
        "estimated_quantity": 1000,
        "overrun_threshold_pct": OVERRUN_THRESHOLD_PCT,
        "underrun_threshold_pct": UNDERRUN_THRESHOLD_PCT,
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_bid_item(project_id, payload, ESTIMATOR), 201
    )


def price_bid_item(project_id, bid_item_id, **overrides):
    payload = {
        "bid_unit_price_cents": 3000,
        "crew_day_labor_cents": CREW_DAY_LABOR_CENTS,
        "crew_day_equipment_cents": CREW_DAY_EQUIPMENT_CENTS,
        "daily_productivity_units": DAILY_PRODUCTIVITY_UNITS,
    }
    payload.update(overrides)
    return get_success_data(
        api_client.price_bid_item(project_id, bid_item_id, payload, ESTIMATOR)
    )


def submit_bid_item(project_id, bid_item_id):
    return get_success_data(
        api_client.submit_bid_item(project_id, bid_item_id, ESTIMATOR)
    )


def create_quote(project_id, **overrides):
    payload = {
        "project_id": project_id,
        "trade_code": "SWPPP",
        "contact_name": "Dana Reyes",
        "quoted_amount_cents": 18_000_000,
        "quote_window_start": QUOTE_WINDOW_START,
        "quote_window_end": QUOTE_WINDOW_END,
        "unicap_registered": True,
        "good_faith_effort_basis": "SOLICITED_DBE",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_quote(payload, ESTIMATOR), 201)


def create_bond(project_id, surety_id, **overrides):
    payload = {
        "project_id": project_id,
        "surety_id": surety_id,
        "bond_type": "PERFORMANCE",
        "bond_amount_cents": 12_000_000,
        "effective_from": BOND_EFFECTIVE_FROM,
        "effective_to": BOND_EFFECTIVE_TO,
        "maintain_bond_horizon_days": 30,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_bond(payload, ESTIMATOR), 201)


def issue_bond(bond_id, surety_id):
    return get_success_data(api_client.issue_bond(bond_id, make_surety_headers(surety_id)))


def create_commitment(surety_id, project_id, committed_amount_cents):
    payload = {
        "surety_id": surety_id,
        "project_id": project_id,
        "committed_amount_cents": committed_amount_cents,
    }
    return get_success_data(api_client.create_surety_commitment(payload, OFFICER), 201)


def create_reconciliation(project_id):
    return get_success_data(api_client.create_reconciliation(project_id, OFFICER), 201)


def create_measurement(bid_item_id, measured_quantity, measured_at=None, headers=None):
    """Record a measurement carrying the pay item's current version (OCC guard)."""
    item = get_success_data(api_client.get_bid_item(bid_item_id, ESTIMATOR))
    payload = {
        "measured_quantity": measured_quantity,
        "measured_at": measured_at or DEFAULT_MEASURED_AT,
        "expected_bid_item_version": item["version"],
    }
    return get_success_data(
        api_client.create_measurement(bid_item_id, payload, headers or MANAGER), 201
    )


def approve_measurement(measurement_id, headers=None):
    return get_success_data(
        api_client.approve_measurement(measurement_id, headers or MANAGER)
    )


def pay_measurement(measurement_id, headers=None):
    return get_success_data(api_client.pay_measurement(measurement_id, headers or MANAGER))


def void_measurement(measurement_id, headers=None):
    return get_success_data(
        api_client.void_measurement(measurement_id, headers or MANAGER)
    )


def finalize_reconciliation(project_id, reconciliation_id):
    """Finalize using the project's current version (the OCC guard is band 4)."""
    project = get_success_data(api_client.get_project(project_id, OFFICER))
    payload = {"expected_project_version": project["version"]}
    return get_success_data(
        api_client.finalize_reconciliation(project_id, reconciliation_id, payload, OFFICER)
    )


def release_retention(project_id, reconciliation_id):
    return get_success_data(
        api_client.release_retention(project_id, reconciliation_id, OFFICER)
    )


def report_condition(project_id, reported_at=None, claimed_amount_cents=3_000_000):
    payload = {
        "project_id": project_id,
        "reported_at": reported_at or "2026-12-03T00:00:00Z",
        "claimed_amount_cents": claimed_amount_cents,
    }
    return get_success_data(api_client.create_condition(payload, MANAGER), 201)


def document_condition(condition_id, urls=None):
    payload = {"documentation_package_urls": urls or ["https://docs.granite.example/dsc/001.pdf"]}
    return get_success_data(
        api_client.document_condition(condition_id, payload, MANAGER)
    )


# ---------------------------------------------------------------------------
# Composite lifecycle stages
# ---------------------------------------------------------------------------

def setup_priced_item(
    project_id,
    *,
    item_code="2025-390102",
    item_description="Class 2 aggregate base",
    unit_of_measure="TON",
    estimated_quantity=1000,
    overrun_threshold_pct=OVERRUN_THRESHOLD_PCT,
    underrun_threshold_pct=UNDERRUN_THRESHOLD_PCT,
    bid_unit_price_cents=3000,
    crew_day_labor_cents=CREW_DAY_LABOR_CENTS,
    crew_day_equipment_cents=CREW_DAY_EQUIPMENT_CENTS,
    daily_productivity_units=DAILY_PRODUCTIVITY_UNITS,
    submit=True,
):
    """Add a pay item, price it, and optionally move it into the bid total."""
    item = create_bid_item(
        project_id,
        item_code=item_code,
        item_description=item_description,
        unit_of_measure=unit_of_measure,
        estimated_quantity=estimated_quantity,
        overrun_threshold_pct=overrun_threshold_pct,
        underrun_threshold_pct=underrun_threshold_pct,
    )
    item = price_bid_item(
        project_id,
        item["id"],
        bid_unit_price_cents=bid_unit_price_cents,
        crew_day_labor_cents=crew_day_labor_cents,
        crew_day_equipment_cents=crew_day_equipment_cents,
        daily_productivity_units=daily_productivity_units,
    )
    if submit:
        item = submit_bid_item(project_id, item["id"])
    return item


def setup_sealed_project(
    *,
    project_code="CALTRANS-04-1J5604",
    advertised_dbe_goal_pct=DEFAULT_ADVERTISED_DBE_GOAL_PCT,
    retention_rate_pct=DEFAULT_RETENTION_RATE_PCT,
    bid_deadline_at=DEFAULT_BID_DEADLINE_AT,
    bid_unit_price_cents=3000,
    estimated_quantity=1000,
    open_reconciliation_before_seal=False,
    quote_overrides=None,
    carry_quote=False,
):
    """Project whose single pay item is SUBMITTED and whose bid is SEALED."""
    advance_clock(LOGICAL_CLOCK_START)
    project = create_project(
        project_code=project_code,
        advertised_dbe_goal_pct=advertised_dbe_goal_pct,
        retention_rate_pct=retention_rate_pct,
        bid_deadline_at=bid_deadline_at,
    )
    item = setup_priced_item(
        project["id"],
        bid_unit_price_cents=bid_unit_price_cents,
        estimated_quantity=estimated_quantity,
    )
    quote = None
    if quote_overrides is not None:
        quote = create_quote(project["id"], **quote_overrides)
        if carry_quote:
            quote = get_success_data(api_client.carry_quote(quote["id"], ESTIMATOR))
    reconciliation = None
    if open_reconciliation_before_seal:
        reconciliation = create_reconciliation(project["id"])
    project = get_success_data(api_client.seal_bid(project["id"], ESTIMATOR))
    return {
        "project": project,
        "bid_item": item,
        "quote": quote,
        "reconciliation": reconciliation,
        "surety": None,
        "bond": None,
        "commitment": None,
    }


def setup_open_project(
    *,
    project_code="CALTRANS-04-1J5604",
    advertised_dbe_goal_pct=DEFAULT_ADVERTISED_DBE_GOAL_PCT,
    bid_unit_price_cents=3000,
    estimated_quantity=1000,
    with_surety=True,
    surety_overrides=None,
    bond_overrides=None,
    bond_amount_cents=12_000_000,
    bond_type="PERFORMANCE",
    issue_bond_now=False,
    open_reconciliation_before_seal=False,
    quote_overrides=None,
    carry_quote=False,
):
    """Project whose sealed bid has been opened, so the contract is AWARDED."""
    ctx = setup_sealed_project(
        project_code=project_code,
        advertised_dbe_goal_pct=advertised_dbe_goal_pct,
        bid_unit_price_cents=bid_unit_price_cents,
        estimated_quantity=estimated_quantity,
        open_reconciliation_before_seal=open_reconciliation_before_seal,
        quote_overrides=quote_overrides,
        carry_quote=carry_quote,
    )
    project = ctx["project"]
    surety = None
    bond = None
    if with_surety:
        surety = create_surety(**(surety_overrides or {}))
        bond = create_bond(
            project["id"],
            surety["id"],
            bond_type=bond_type,
            bond_amount_cents=bond_amount_cents,
            **(bond_overrides or {}),
        )
    advance_clock(project["bid_deadline_at"])
    project = get_success_data(api_client.open_bid(project["id"], OFFICER))
    if bond is not None and issue_bond_now:
        bond = issue_bond(bond["id"], surety["id"])
    ctx.update(
        {
            "project": project,
            "surety": surety,
            "bond": bond,
            "surety_headers": make_surety_headers(surety["id"]) if surety else None,
        }
    )
    return ctx


def setup_active_project(
    *,
    project_code="CALTRANS-04-1J5604",
    advertised_dbe_goal_pct=DEFAULT_ADVERTISED_DBE_GOAL_PCT,
    retention_rate_pct=DEFAULT_RETENTION_RATE_PCT,
    bid_unit_price_cents=3000,
    estimated_quantity=1000,
    surety_overrides=None,
    bond_amount_cents=12_000_000,
    bond_type="PERFORMANCE",
    commitment_amount_cents=None,
    open_reconciliation=True,
    quote_overrides=None,
    carry_quote=False,
):
    """Mobilized project: item ACTIVE, claim window open, reconciliation OPEN."""
    advance_clock(LOGICAL_CLOCK_START)
    project = create_project(
        project_code=project_code,
        advertised_dbe_goal_pct=advertised_dbe_goal_pct,
        retention_rate_pct=retention_rate_pct,
    )
    item = setup_priced_item(
        project["id"],
        bid_unit_price_cents=bid_unit_price_cents,
        estimated_quantity=estimated_quantity,
    )
    surety = create_surety(**(surety_overrides or {}))
    commitment = None
    if commitment_amount_cents is not None:
        commitment = create_commitment(surety["id"], project["id"], commitment_amount_cents)
    bond = create_bond(
        project["id"],
        surety["id"],
        bond_type=bond_type,
        bond_amount_cents=bond_amount_cents,
    )
    quote = None
    if quote_overrides is not None:
        quote = create_quote(project["id"], **quote_overrides)
        if carry_quote:
            quote = get_success_data(api_client.carry_quote(quote["id"], ESTIMATOR))
    project = get_success_data(api_client.seal_bid(project["id"], ESTIMATOR))
    advance_clock(project["bid_deadline_at"])
    project = get_success_data(api_client.open_bid(project["id"], OFFICER))
    bond = issue_bond(bond["id"], surety["id"])
    project = get_success_data(api_client.start_work(project["id"], MANAGER))
    item = get_success_data(api_client.get_bid_item(item["id"], ESTIMATOR))
    reconciliation = None
    if open_reconciliation:
        reconciliation = create_reconciliation(project["id"])
    return {
        "project": project,
        "bid_item": item,
        "surety": surety,
        "bond": bond,
        "commitment": commitment,
        "reconciliation": reconciliation,
        "quote": quote,
        "surety_headers": make_surety_headers(surety["id"]),
    }


def setup_active_project_with_measurement(
    measured_quantity,
    *,
    approve=False,
    pay=False,
    measured_at=DEFAULT_MEASURED_AT,
    **project_overrides,
):
    """Mobilized project plus one recorded measurement, optionally approved/paid."""
    ctx = setup_active_project(**project_overrides)
    measurement = create_measurement(
        ctx["bid_item"]["id"], measured_quantity, measured_at=measured_at
    )
    if approve:
        measurement = approve_measurement(measurement["id"])
    if pay:
        measurement = pay_measurement(measurement["id"])
    ctx["measurement"] = measurement
    ctx["bid_item"] = get_success_data(api_client.get_bid_item(ctx["bid_item"]["id"], ESTIMATOR))
    return ctx


def setup_active_project_with_claim(
    condition_status="DOCUMENTED",
    *,
    claimed_amount_cents=3_000_000,
    reported_at="2026-12-03T00:00:00Z",
    measured_quantity=None,
    **project_overrides,
):
    """Mobilized project carrying a differing site condition at a named stage."""
    ctx = setup_active_project(**project_overrides)
    # Move the field clock past the discovery instant so the notice clock reads
    # a non-negative whole-day figure.
    advance_clock("2026-12-05T00:00:00Z")
    if measured_quantity is not None:
        measurement = create_measurement(ctx["bid_item"]["id"], measured_quantity)
        ctx["measurement"] = measurement
    condition = report_condition(
        ctx["project"]["id"],
        reported_at=reported_at,
        claimed_amount_cents=claimed_amount_cents,
    )
    if condition_status in ("DOCUMENTED", "UNDER_REVIEW"):
        condition = document_condition(condition["id"])
    if condition_status == "UNDER_REVIEW":
        condition = get_success_data(api_client.submit_claim(condition["id"], MANAGER))
    ctx["condition"] = condition
    return ctx


def setup_awarded_project_with_measurement(
    measured_quantity,
    *,
    project_code="CALTRANS-04-1J5617",
    bid_unit_price_cents=2000,
):
    """Awarded but never mobilized: the pay item sits in AWARDED."""
    ctx = setup_open_project(
        project_code=project_code,
        bid_unit_price_cents=bid_unit_price_cents,
        with_surety=False,
    )
    measurement = create_measurement(ctx["bid_item"]["id"], measured_quantity)
    ctx["measurement"] = measurement
    return ctx


def setup_bonded_awarded_project(
    *,
    project_code="CALTRANS-04-1J5616",
    bid_unit_price_cents=2000,
    bond_amount_cents=12_000_000,
    suspend_surety=False,
):
    """AWARDED project with an ISSUED performance bond, optionally suspended."""
    ctx = setup_open_project(
        project_code=project_code,
        bid_unit_price_cents=bid_unit_price_cents,
        bond_amount_cents=bond_amount_cents,
        issue_bond_now=True,
    )
    if suspend_surety:
        ctx["surety"] = get_success_data(
            api_client.suspend_surety(ctx["surety"]["id"], ADMIN)
        )
    return ctx


def complete_project_to_closeout(ctx, measured_quantity=1000, approve=True, pay=False):
    """Drive an already-mobilized project through finalization and retention release.

    Mutates and returns ``ctx`` so callers can observe both the pre-closeout and
    the post-closeout figures of the same project.
    """
    measurement = create_measurement(ctx["bid_item"]["id"], measured_quantity)
    if approve:
        measurement = approve_measurement(measurement["id"])
    if pay:
        measurement = pay_measurement(measurement["id"])
    ctx["measurement"] = measurement
    ctx["reconciliation"] = finalize_reconciliation(
        ctx["project"]["id"], ctx["reconciliation"]["id"]
    )
    ctx["reconciliation"] = release_retention(
        ctx["project"]["id"], ctx["reconciliation"]["id"]
    )
    ctx["project"] = get_success_data(api_client.get_project(ctx["project"]["id"], OFFICER))
    ctx["bid_item"] = get_success_data(api_client.get_bid_item(ctx["bid_item"]["id"], ESTIMATOR))
    ctx["bond"] = get_success_data(api_client.get_bond(ctx["bond"]["id"], OFFICER))
    ctx["surety"] = get_success_data(api_client.get_surety(ctx["surety"]["id"], ADMIN))
    return ctx


def setup_project_through_closeout(
    *,
    project_code="CALTRANS-04-1J5620",
    bid_unit_price_cents=2000,
    measured_quantity=1000,
    bond_amount_cents=12_000_000,
):
    """Project walked all the way to COMPLETE with its reconciliation CLOSED."""
    ctx = setup_active_project(
        project_code=project_code,
        bid_unit_price_cents=bid_unit_price_cents,
        bond_amount_cents=bond_amount_cents,
    )
    return complete_project_to_closeout(ctx, measured_quantity=measured_quantity)


def setup_under_review_claim_with_draft_measurement(
    *,
    project_code="CALTRANS-04-1J5613",
):
    """ACTIVE project holding an UNDER_REVIEW claim and a DRAFT measurement."""
    ctx = setup_active_project_with_claim(
        condition_status="UNDER_REVIEW",
        measured_quantity=900,
        project_code=project_code,
        bid_unit_price_cents=3000,
    )
    return ctx


def setup_surety_with_commitments(
    *,
    aggregate_capacity_cents=200_000_000,
    single_job_limit_cents=150_000_000,
    first_commitment_cents=120_000_000,
    second_project_code="CALTRANS-04-1J5631",
):
    """A surety carrying one live commitment, plus a second open project."""
    advance_clock(LOGICAL_CLOCK_START)
    surety = create_surety(
        aggregate_capacity_cents=aggregate_capacity_cents,
        single_job_limit_cents=single_job_limit_cents,
    )
    project_a = create_project(project_code="CALTRANS-04-1J5630")
    project_b = create_project(project_code=second_project_code)
    commitment = create_commitment(surety["id"], project_a["id"], first_commitment_cents)
    return {
        "surety": surety,
        "project_a": project_a,
        "project_b": project_b,
        "commitment": commitment,
        "surety_headers": make_surety_headers(surety["id"]),
    }


def setup_project_with_reopenable_item(
    *,
    project_code="CALTRANS-04-1J5710",
    included_price_cents=2000,
    included_quantity=1000,
    draft_price_cents=9000,
    draft_quantity=500,
):
    """A project whose bid total covers one item while a second item sits DRAFT.

    The second item is walked ``SUBMITTED -> DRAFT`` by a bid recall so that it
    carries a non-zero unit price while being outside the bid total.
    """
    advance_clock(LOGICAL_CLOCK_START)
    project = create_project(project_code=project_code)
    included = setup_priced_item(
        project["id"],
        item_code="2025-390207",
        item_description="Class 2 aggregate base",
        unit_of_measure="TON",
        estimated_quantity=included_quantity,
        bid_unit_price_cents=included_price_cents,
    )
    draft = setup_priced_item(
        project["id"],
        item_code="2025-390208",
        item_description="Minor concrete structure",
        unit_of_measure="EA",
        estimated_quantity=draft_quantity,
        bid_unit_price_cents=draft_price_cents,
    )
    project = get_success_data(api_client.seal_bid(project["id"], ESTIMATOR))
    project = get_success_data(
        api_client.recall_bid(project["id"], {"reason_code": "OWNER_ADDENDUM"}, OFFICER)
    )
    project = get_success_data(api_client.reset_bid(project["id"], OFFICER))
    # Both items are DRAFT after the recall; bring only the first one back.
    included = price_bid_item(
        project["id"], included["id"], bid_unit_price_cents=included_price_cents
    )
    included = submit_bid_item(project["id"], included["id"])
    project = get_success_data(api_client.get_project(project["id"], ESTIMATOR))
    draft = get_success_data(api_client.get_bid_item(draft["id"], ESTIMATOR))
    return {"project": project, "bid_item": included, "draft_item": draft}
