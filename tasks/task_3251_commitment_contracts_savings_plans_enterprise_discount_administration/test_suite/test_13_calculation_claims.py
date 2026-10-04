"""Tests for calculation claims: full waterfall, half-open window, shared coverage, forecast window."""
from test_helpers import (
    validate_error,
    validate_success,
    api_client,
    make_admin_headers,
    make_finance_headers,
    create_org,
    create_active_agreement,
    create_amendment,
    create_linked_account,
    create_plan,
    create_grant,
    ingest_usage,
    generate_invoice,
    period_close,
    get_agreement,
    get_invoice_lines,
    ApiErrorId,
)

ADMIN = make_admin_headers()
FINANCE = make_finance_headers()


def test_waterfall_stage_order_amendment_then_plan_then_tier_then_credit(api):
    """PRD section 3.6: "Each line is priced by a pinned, non-commutative
    four-stage waterfall."
    PRD section 3.6: "Stage 1 — private pricing. If the invoice has an agreement
    and a `PricingAmendment` of that agreement covers the record's
    `service_family` with the record's `usage_hour_start` inside the amendment's
    half-open window, the line base is the list price reduced by the amendment's
    `discount_rate`; otherwise the list price carries through untouched."
    PRD section 3.6: "Stage 4 — credits. The post-stage-3 remainders of all lines
    form a credit pool, allocated against the org's usable grants as described in
    §3.7; the line records `credit_applied_cents` as computed at generation,
    though the grants are only actually debited at finalize."

    Design: Corner/calculations/waterfall_stage_order_amendment_then_plan_then_tier_then_credit
    """
    org = create_org(name="Wf Org", max_hourly_commitment_cents=100000,
                     capacity_quota_units=100)
    agr = create_active_agreement(
        org["id"],
        tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
        committed_spend_cents=1000000,
    )
    create_amendment(
        agr["id"], get_agreement(agr["id"])["version"],
        service_family="COMPUTE", discount_rate=0.10,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-10-01T00:00:00Z",
    )
    create_plan(
        org["id"], agr["id"], type="SAVINGS_PLAN", instance_family="COMPUTE",
        units=0, hourly_commitment_cents=100000, plan_discount_rate=0.30,
        term_start="2026-09-01T00:00:00Z", term_end="2026-10-01T00:00:00Z",
    )
    create_grant(org["id"], amount_cents=6700, expires_at="2026-12-01T00:00:00Z")
    acct = create_linked_account(org["id"], name="a1", external_ref="e1")
    ingest_usage(acct["id"], usage_hour_start="2026-09-01T00:00:00Z",
                 list_price_cents=100000)
    inv = generate_invoice(org["id"], period_index=0)
    line = get_invoice_lines(inv["id"])[0]
    assert line["amendment_discount_cents"] == 10000
    assert line["plan_discount_cents"] == 27000
    assert line["tier_discount_cents"] == 6300
    assert line["credit_applied_cents"] == 6700
    assert line["net_due_cents"] == 50000
    assert inv["total_due_cents"] == 50000


def test_amendment_window_excludes_usage_outside_half_open_window(api):
    """PRD section 3.6: "Stage 1 — private pricing. If the invoice has an
    agreement and a `PricingAmendment` of that agreement covers the record's
    `service_family` with the record's `usage_hour_start` inside the amendment's
    half-open window, the line base is the list price reduced by the amendment's
    `discount_rate`; otherwise the list price carries through untouched."
    PRD section 3.3: "A `FinanceAnalyst` layers private pricing onto specific
    service families by creating a `PricingAmendment` with a `discount_rate` (at
    least 0, strictly less than 1) and a half-open effective window
    `effective_from` (inclusive) to `effective_to` (exclusive)."

    Design: Corner/calculations/amendment_window_excludes_usage_outside_half_open_window
    """
    org = create_org(name="Hw Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    agr = create_active_agreement(
        org["id"],
        tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
        committed_spend_cents=1000000,
    )
    create_amendment(
        agr["id"], get_agreement(agr["id"])["version"],
        service_family="COMPUTE", discount_rate=0.50,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-10-01T00:00:00Z",
    )
    acct = create_linked_account(org["id"], name="a1", external_ref="e1")
    ingest_usage(acct["id"], usage_hour_start="2026-09-30T23:00:00Z",
                 list_price_cents=1000)
    ingest_usage(acct["id"], usage_hour_start="2026-10-01T00:00:00Z",
                 list_price_cents=1000)
    inv = generate_invoice(org["id"], period_index=0)
    line = get_invoice_lines(inv["id"])[0]
    assert line["amendment_discount_cents"] == 500, (
        "only the 23:00 hour is inside [09-01, 10-01); the 10-01T00:00 hour is "
        "excluded by half-open semantics"
    )
    assert line["tier_discount_cents"] == 150
    assert line["net_due_cents"] == 1350


def test_consolidated_coverage_shared_across_accounts_in_created_at_order(api):
    """PRD section 3.4: "The `ACTUAL` mode replays real usage chronologically
    hour by hour, ordered by `usage_hour_start` ascending with ties broken by
    account creation order; within each hour the plan's remaining budget is
    exactly `hourly_commitment_cents`, and post-amendment usage of the plan's
    `instance_family` across all of the org's linked accounts is covered in
    account `created_at` ascending order until the hourly budget is exhausted, so
    the covered amount is the sum over hours of the smaller of that hour's family
    usage and the hourly commitment."

    Design: Corner/calculations/consolidated_coverage_shared_across_accounts_in_created_at_order
    """
    org = create_org(name="Sh Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    agr = create_active_agreement(
        org["id"],
        tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
        committed_spend_cents=1000000,
    )
    a1 = create_linked_account(org["id"], name="a1", external_ref="e1")
    a2 = create_linked_account(org["id"], name="a2", external_ref="e2")
    create_plan(
        org["id"], agr["id"], type="SAVINGS_PLAN", instance_family="COMPUTE",
        units=0, hourly_commitment_cents=100, plan_discount_rate=0.30,
        term_start="2026-09-01T00:00:00Z", term_end="2026-10-01T00:00:00Z",
    )
    # a2 ingests first, but allocation order follows account created_at ASC.
    ingest_usage(a2["id"], usage_hour_start="2026-09-01T00:00:00Z",
                 list_price_cents=80)
    ingest_usage(a1["id"], usage_hour_start="2026-09-01T00:00:00Z",
                 list_price_cents=80)
    inv = generate_invoice(org["id"], period_index=0)
    lines = get_invoice_lines(inv["id"])
    by_acct = {l["linked_account_id"]: l for l in lines}
    l1, l2 = by_acct[a1["id"]], by_acct[a2["id"]]
    assert l1["plan_covered_cents"] == 80
    assert l1["plan_discount_cents"] == 24
    assert l2["plan_covered_cents"] == 20
    assert l2["plan_discount_cents"] == 6
    assert l1["net_due_cents"] == 50  # 56 * 0.9 = 50.4 -> 50
    assert l2["net_due_cents"] == 67  # 74 * 0.9 = 66.6 -> 67
    assert inv["total_due_cents"] == 117


def test_forecast_window_insufficient_rejected_with_three_period_rule(api):
    """PRD section 3.10: "If fewer closed periods with usage exist than the
    requested window requires, generation is rejected with
    `ERR_FORECAST_WINDOW_INSUFFICIENT` (HTTP 409)."
    PRD section 3.10: "A forecast names an `agreement_id`, a `variant` of
    `LINEAR` or `COHORT_WEIGHTED`, and an optional `window_periods` defaulting to
    3 and required to be at least 3."

    Design: Corner/calculations/forecast_window_insufficient_rejected_with_three_period_rule
    """
    org = create_org(name="Fw Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    agr = create_active_agreement(
        org["id"],
        tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
        committed_spend_cents=1000000,
    )
    acct = create_linked_account(org["id"], name="a1", external_ref="e1")
    for i in range(2):
        ingest_usage(acct["id"], usage_hour_start=f"2026-09-01T{i:02d}:00:00Z",
                     list_price_cents=1000)
        period_close(org["id"])
    resp = api.create_renewal_forecast(
        {"agreement_id": agr["id"], "variant": "LINEAR"}, FINANCE
    )
    validate_error(resp, ApiErrorId.ERR_FORECAST_WINDOW_INSUFFICIENT)
    assert resp.status_code == 409
