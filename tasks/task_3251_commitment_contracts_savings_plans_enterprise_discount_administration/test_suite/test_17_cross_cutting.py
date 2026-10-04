"""Tests for cross-cutting layers: OCC, period-close cascades, marketplace weight."""
from test_helpers import (
    validate_error,
    validate_success,
    api_client,
    make_admin_headers,
    make_finance_headers,
    make_platform_headers,
    create_org,
    create_active_agreement,
    create_amendment,
    create_linked_account,
    create_plan,
    create_grant,
    ingest_usage,
    generate_invoice,
    get_agreement,
    get_credit_grant,
    set_clock,
    ApiErrorId,
)

ADMIN = make_admin_headers()
FINANCE = make_finance_headers()
PLATFORM = make_platform_headers()


def test_occ_stale_amendment_rejected_412(api):
    """PRD section 2.7: "One write endpoint participates in optimistic
    concurrency control: creating a private pricing amendment. The request must
    carry `expected_agreement_version`, holding the value of the target
    agreement's `version` as last observed by the caller. If the agreement's
    `version` has since advanced — because another writer suspended, resumed, or
    terminated the agreement, added a tier, or created a prior amendment — the
    create is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412), preventing
    the caller from writing pricing terms against an agreement it has not
    observed. No other endpoint takes a version field."

    Design: Corner/cross_cutting_layers/occ_stale_amendment_rejected_412
    """
    org = create_org(name="Oc Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    agr = create_active_agreement(
        org["id"],
        tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
        committed_spend_cents=1000000,
    )
    v = get_agreement(agr["id"])["version"]
    # another writer advances the version
    validate_success(api.suspend_agreement(agr["id"], ADMIN))
    resp = api.create_pricing_amendment(
        {
            "agreement_id": agr["id"], "service_family": "COMPUTE",
            "discount_rate": 0.20,
            "effective_from": "2026-10-01T00:00:00Z",
            "effective_to": "2026-11-01T00:00:00Z",
            "expected_agreement_version": v,
        },
        FINANCE,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_AGREEMENT_VERSION)
    assert resp.status_code == 412
    # retry with the fresh version succeeds (amendments allowed while SUSPENDED)
    v2 = get_agreement(agr["id"])["version"]
    data = create_amendment(
        agr["id"], v2,
        service_family="COMPUTE", discount_rate=0.20,
        effective_from="2026-10-01T00:00:00Z",
        effective_to="2026-11-01T00:00:00Z",
    )
    assert data["id"]
    # amendment creation itself increments the agreement version
    assert get_agreement(agr["id"])["version"] == v2 + 1


def test_cascading_period_close_expires_plan_agreement_and_credits_together(api):
    """PRD section 3.8: "When the operator runs it for an organization,
    `current_period_index` advances by exactly 1, and three expiry sweeps fire
    against the logical clock: every credit grant in `ISSUED` or `DEPLETING` whose
    `expires_at` has been reached moves to `EXPIRED` under the forfeiture
    bookkeeping of §3.7; every `ACTIVE` commitment plan whose `term_end` has been
    reached moves to `EXPIRED`; and every agreement whose lifecycle is `ACTIVE`
    and whose `term_end` has been reached moves to `EXPIRED`. The org's
    `unapplied_credit_cents` is then recomputed."

    Design: Corner/cross_cutting_layers/cascading_period_close_expires_plan_agreement_and_credits_together
    """
    org = create_org(name="Pc Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    agr = create_active_agreement(
        org["id"],
        tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
        committed_spend_cents=1000000,
        term_start="2026-09-01T00:00:00Z", term_end="2026-10-01T00:00:00Z",
    )
    plan = create_plan(
        org["id"], agr["id"], type="SAVINGS_PLAN", instance_family="COMPUTE",
        units=0, hourly_commitment_cents=100, plan_discount_rate=0.30,
        term_start="2026-09-01T00:00:00Z", term_end="2026-10-01T00:00:00Z",
    )
    grant = create_grant(org["id"], amount_cents=900,
                         expires_at="2026-09-15T00:00:00Z")
    set_clock("2026-10-01T00:00:00Z")
    data = validate_success(api.run_period_close(org["id"], PLATFORM))
    assert data["current_period_index"] == 1
    assert data["unapplied_credit_cents"] == 0
    assert get_agreement(agr["id"])["lifecycle_status"] == "EXPIRED"
    assert validate_success(api.get_commitment_plan(plan["id"], ADMIN))["status"] == "EXPIRED"
    assert get_credit_grant(grant["id"])["status"] == "EXPIRED"


def test_rate_threshold_consumed_counter_tracks_pass1_marketplace_weight(api):
    """PRD section 3.6: "Generation also advances the agreement's
    `consumed_commitment_cents` by the period's eligible spend, using the pass-1
    marketplace weighting of §3.8."
    PRD section 3.8: "Pass 1 computes consumed spend as the sum of
    `list_price_cents` over eligible non-marketplace usage in the agreement's
    covered families across the term, plus half of the marketplace
    `list_price_cents` — the base marketplace weight is one half, and each
    marketplace record's weighted contribution is truncated down to integer cents
    before summation."

    Design: Corner/cross_cutting_layers/rate_threshold_consumed_counter_tracks_pass1_marketplace_weight
    """
    org = create_org(name="Mw Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    agr = create_active_agreement(
        org["id"],
        tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
        committed_spend_cents=1000000,
    )
    acct = create_linked_account(org["id"], name="a1", external_ref="e1")
    ingest_usage(acct["id"], usage_hour_start="2026-09-01T00:00:00Z",
                 list_price_cents=1000)
    ingest_usage(acct["id"], usage_hour_start="2026-09-01T01:00:00Z",
                 list_price_cents=800, is_marketplace=True)
    generate_invoice(org["id"], period_index=0)
    agr_after = get_agreement(agr["id"])
    assert agr_after["consumed_commitment_cents"] == 1400, (
        f"1000 + floor(800 * 0.5) = 1400, got "
        f"{agr_after['consumed_commitment_cents']}"
    )
