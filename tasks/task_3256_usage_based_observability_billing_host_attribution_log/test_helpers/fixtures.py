"""Composite setup helpers for the observability-billing API (PRD §2.6, §3).

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the test harness restarts the server before every test, so each test
starts against an empty database). Setup steps use the lenient get_success_data
validator so a failing setup produces a clear "Setup failed" error.

Short aliases for the shared role-header dicts: PA (PlatformAdmin), BA
(BillingAdmin), IA (IngestionAgent), FR (FinanceReader). TeamLead calls that are
ownership-gated thread the actual Team.id through make_team_lead_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ENTERPRISE_PLAN,
    FREE_PLAN,
    OCT_START_UTC,
    SEPT_PERIOD_END,
    SEPT_PERIOD_START,
    SEPT_WINDOW_END,
)
from .factories import (
    create_billing_account_payload,
    create_billing_period_payload,
    create_commitment_payload,
    create_custom_metric_series_payload,
    create_dispute_payload,
    create_exclusion_filter_payload,
    create_host_hour_record_payload,
    create_log_event_payload,
    create_monitor_payload,
    create_remediate_payload,
    create_retention_tier_payload,
    create_rollup_payload,
    create_tag_policy_payload,
    create_team_payload,
    create_usage_record_payload,
)
from .test_users import TEST_USERS, make_team_lead_headers

PA = TEST_USERS["platform_admin_headers"]
BA = TEST_USERS["billing_admin_headers"]
IA = TEST_USERS["ingestion_agent_headers"]
FR = TEST_USERS["finance_reader_headers"]


# ---------------------------------------------------------------------------
# Tier 1: state progression primitives
# ---------------------------------------------------------------------------

def set_clock(current_utc="2026-09-01T00:00:00Z"):
    """Advance the logical clock (PRD §2.6). Returns the clock payload."""
    return get_success_data(api_client.set_clock(current_utc, PA))


def create_plan_tier_config(plan=None, **overrides):
    """Create a PlanTierConfig. `plan` selects a named rate card."""
    payload = dict(plan or ENTERPRISE_PLAN)
    payload.update(overrides)
    return get_success_data(api_client.create_plan_tier_config(payload, PA))


def create_account(name="Acme Observability", plan_tier="ENTERPRISE", **overrides):
    """Create a BillingAccount. Returns the account dict (carries version=1)."""
    payload = create_billing_account_payload(name=name, plan_tier=plan_tier, **overrides)
    return get_success_data(api_client.create_billing_account(payload, PA))


def create_open_period(account_id, start=SEPT_PERIOD_START, end=SEPT_PERIOD_END):
    """Open a BillingPeriod in OPEN status. Returns the period dict."""
    payload = create_billing_period_payload(period_start_utc=start, period_end_utc=end)
    return get_success_data(api_client.create_billing_period(account_id, payload, BA))


def close_period(account_id, period_id, at_utc=OCT_START_UTC):
    """Advance the clock past period end and close the period. Returns the
    CLOSED period dict."""
    set_clock(at_utc)
    return get_success_data(api_client.close_billing_period(account_id, period_id, BA))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def setup_account_with_period(name="Acme Observability", plan_tier="ENTERPRISE",
                              plan=None, start=SEPT_PERIOD_START,
                              end=SEPT_PERIOD_END):
    """Clock at period start + plan config + account + OPEN period.
    Returns (account, period)."""
    set_clock(start)
    create_plan_tier_config(plan=plan)
    account = create_account(name=name, plan_tier=plan_tier)
    period = create_open_period(account["id"], start=start, end=end)
    return account, period


def setup_account_with_period_and_team(name="Acme Observability"):
    """Account + OPEN period + one Team. Returns (account, period, team)."""
    account, period = setup_account_with_period(name=name)
    team = get_success_data(api_client.create_team(account["id"], create_team_payload(), BA))
    return account, period, team


def setup_account_with_retention_tier(name="Acme Observability", **tier_overrides):
    """Account + one RetentionTier (OCC-threaded). Returns (account, tier).

    Note: creating the tier bumps the account version by 1 (PRD §2.8), so the
    returned account dict is refreshed after the create."""
    set_clock()
    create_plan_tier_config()
    account = create_account(name=name)
    tier = get_success_data(
        api_client.create_retention_tier(
            account["id"],
            create_retention_tier_payload(account["version"], **tier_overrides),
            BA,
        )
    )
    account = get_success_data(api_client.get_billing_account(account["id"], BA))
    return account, tier


def setup_period_with_retention_tier(name="Acme Observability", **tier_overrides):
    """Account + OPEN period + RetentionTier. Returns (account, period, tier)."""
    account, tier = setup_account_with_retention_tier(name=name, **tier_overrides)
    period = create_open_period(account["id"])
    return account, period, tier


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_active_commitment(account_id, meter="INFRA_HOST", committed_quantity=10,
                             committed_rate=100, overage_rate=500,
                             window_start=SEPT_PERIOD_START,
                             window_end=SEPT_WINDOW_END):
    """Create + activate a Commitment. OCC-threads the account version.
    Returns (commitment, account) with the account refreshed post-create."""
    account = get_success_data(api_client.get_billing_account(account_id, BA))
    payload = create_commitment_payload(
        account["version"],
        meter=meter,
        committed_quantity=committed_quantity,
        committed_unit_rate_cents=committed_rate,
        overage_unit_rate_cents=overage_rate,
        window_start_utc=window_start,
        window_end_utc=window_end,
    )
    commitment = get_success_data(api_client.create_commitment(account_id, payload, BA))
    get_success_data(api_client.activate_commitment(account_id, commitment["id"], BA))
    commitment = get_success_data(api_client.get_commitment_flat(commitment["id"], BA))
    account = get_success_data(api_client.get_billing_account(account_id, BA))
    return commitment, account


def post_usage(account_id, period_id, meter, quantity, team_id=None):
    """Post a UsageRecord as IngestionAgent. Returns the record dict."""
    payload = create_usage_record_payload(meter=meter, quantity=quantity)
    if team_id is not None:
        payload["team_id"] = team_id
    return get_success_data(
        api_client.create_usage_record(account_id, period_id, payload, IA)
    )


def post_host_hours(account_id, period_id, samples):
    """Ingest a list of (hour_bucket_utc, infra, container, serverless) tuples.
    Returns the list of created HostHourRecords."""
    records = []
    for bucket, infra, container, serverless in samples:
        payload = create_host_hour_record_payload(
            hour_bucket_utc=bucket,
            infra_host_count=infra,
            container_host_count=container,
            serverless_invocation_count=serverless,
        )
        records.append(
            get_success_data(
                api_client.create_host_hour_record(account_id, period_id, payload, IA)
            )
        )
    return records


def setup_excluded_log_event(name="Cascade Test", tag_pattern="noisy-*",
                             event_tag="noisy-worker", size_bytes=500,
                             with_log_index_commitment=True, committed_quantity=100):
    """Account + OPEN period + tier + enabled exclusion filter (sample 0) +
    optional ACTIVE LOG_INDEX commitment + one EXCLUDED LogEvent.
    Returns (account, period, tier, exclusion_filter, commitment_or_None, event)."""
    account, period, tier = setup_period_with_retention_tier(name=name)
    exclusion_filter = get_success_data(
        api_client.create_exclusion_filter(
            account["id"],
            create_exclusion_filter_payload(service_tag_pattern=tag_pattern),
            BA,
        )
    )
    commitment = None
    if with_log_index_commitment:
        commitment, account = create_active_commitment(
            account["id"],
            meter="LOG_INDEX",
            committed_quantity=committed_quantity,
            committed_rate=1,
            overage_rate=5,
        )
    event = get_success_data(
        api_client.ingest_log_event(
            account["id"],
            period["id"],
            create_log_event_payload(
                size_bytes=size_bytes,
                service_tag=event_tag,
                retention_tier_id=tier["id"],
            ),
            IA,
        )
    )
    return account, period, tier, exclusion_filter, commitment, event


def setup_series_with_open_incident(name="Incident Test", metric_name="api.req",
                                    opening_estimate=20000):
    """Account + period + team + series + one rollup that opens an incident.
    Returns (account, period, team, series, incident)."""
    account, period, team = setup_account_with_period_and_team(name=name)
    series = get_success_data(
        api_client.create_custom_metric_series(
            account["id"],
            create_custom_metric_series_payload(team["id"], metric_name=metric_name),
            BA,
        )
    )
    get_success_data(
        api_client.post_rollup(
            account["id"], series["id"], create_rollup_payload(cardinality_estimate=opening_estimate), IA
        )
    )
    incidents, _meta = _list_incidents(account["id"])
    assert len(incidents) == 1, "Setup expected exactly one OPEN CardinalityIncident"
    return account, period, team, series, incidents[0]


def setup_remediated_incident(name="Remediate Test", opening_estimate=20000,
                              note="Dropped high-cardinality tag"):
    """Series with an incident walked OPEN -> TRIAGED -> REMEDIATED.
    Returns (account, period, team, series, incident)."""
    account, period, team, series, incident = setup_series_with_open_incident(
        name=name, opening_estimate=opening_estimate
    )
    get_success_data(api_client.triage_incident(account["id"], incident["id"], BA))
    get_success_data(
        api_client.remediate_incident(
            account["id"], incident["id"], create_remediate_payload(remediation_note=note), BA
        )
    )
    incident = get_success_data(api_client.get_cardinality_incident_flat(incident["id"], BA))
    return account, period, team, series, incident


def setup_verified_incident(name="Verify Test", opening_estimate=20000,
                            below_threshold=(5000, 4000)):
    """Series with an incident walked to VERIFIED via two consecutive
    below-threshold rollups. Returns (account, period, team, series, incident)."""
    account, period, team, series, incident = setup_remediated_incident(
        name=name, opening_estimate=opening_estimate
    )
    for estimate in below_threshold:
        get_success_data(
            api_client.post_rollup(
                account["id"], series["id"], create_rollup_payload(cardinality_estimate=estimate), IA
            )
        )
    incident = get_success_data(api_client.get_cardinality_incident_flat(incident["id"], BA))
    return account, period, team, series, incident


def setup_closed_period_with_draft_invoice(name="Invoice Test", usage=None):
    """Account + OPEN period (+ optional usage [(meter, quantity)]) + close.
    Returns (account, period, invoice) with the DRAFT invoice that close created."""
    account, period = setup_account_with_period(name=name)
    for meter, quantity in (usage or []):
        post_usage(account["id"], period["id"], meter, quantity)
    close_period(account["id"], period["id"])
    invoices = get_success_data(
        api_client.list_invoices_flat(BA, params={"billing_period_id": period["id"]})
    )
    assert isinstance(invoices, list) and len(invoices) == 1, (
        "Setup expected close to draft exactly one invoice"
    )
    return account, period, invoices[0]


def setup_paid_invoice(name="Paid Invoice Test", usage=None):
    """Full invoice lifecycle DRAFT -> ISSUED -> PAID.
    Returns (account, period, invoice)."""
    account, period, invoice = setup_closed_period_with_draft_invoice(
        name=name, usage=usage or [("TRACE", 1)]
    )
    get_success_data(api_client.issue_invoice(account["id"], invoice["id"], BA))
    get_success_data(api_client.pay_invoice(account["id"], invoice["id"], BA))
    invoice = get_success_data(api_client.get_invoice(account["id"], invoice["id"], BA))
    return account, period, invoice


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_commitment_with_consumption(name="Consumption Test", meter="INFRA_HOST",
                                      committed_quantity=10, committed_rate=100,
                                      overage_rate=500, consume=0):
    """ACTIVE commitment with `consume` units already drawn via usage records.
    Returns (account, period, commitment)."""
    account, period = setup_account_with_period(name=name)
    commitment, account = create_active_commitment(
        account["id"],
        meter=meter,
        committed_quantity=committed_quantity,
        committed_rate=committed_rate,
        overage_rate=overage_rate,
    )
    if consume:
        post_usage(account["id"], period["id"], meter, consume)
        commitment = get_success_data(api_client.get_commitment_flat(commitment["id"], BA))
    return account, period, commitment


def get_meter_accumulator(account_id, period_id, meter):
    """Fetch the MeterAccumulator for one meter in a period (lenient read)."""
    rows = get_success_data(
        api_client.list_meter_accumulators(account_id, period_id, BA, params={"meter": meter})
    )
    assert isinstance(rows, list) and len(rows) == 1, (
        f"expected exactly one {meter} accumulator, got {rows!r}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# Tier 5: finalization / terminal state
# ---------------------------------------------------------------------------

def setup_settled_period(name="Settled Test", usage=None, pay=True):
    """Full lifecycle through SETTLED: close -> issue -> pay/void -> settle.
    Returns (account, period, invoice)."""
    account, period, invoice = setup_closed_period_with_draft_invoice(
        name=name, usage=usage or [("TRACE", 1)]
    )
    get_success_data(api_client.issue_invoice(account["id"], invoice["id"], BA))
    if pay:
        get_success_data(api_client.pay_invoice(account["id"], invoice["id"], BA))
    else:
        get_success_data(api_client.void_invoice(account["id"], invoice["id"], BA))
    get_success_data(api_client.settle_billing_period(account["id"], period["id"], BA))
    period = get_success_data(api_client.get_billing_period(account["id"], period["id"], BA))
    invoice = get_success_data(api_client.get_invoice(account["id"], invoice["id"], BA))
    return account, period, invoice


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _list_incidents(account_id, params=None):
    """List cardinality incidents; returns (rows, meta)."""
    from prd_bench_local_runner.testing import validate_paginated

    resp = api_client.list_cardinality_incidents(account_id, BA, params=params)
    return validate_paginated(resp)
