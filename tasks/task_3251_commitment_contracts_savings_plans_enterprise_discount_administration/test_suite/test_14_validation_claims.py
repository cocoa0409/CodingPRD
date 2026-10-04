"""Tests for validation claims: tier ordering, duplicates, fiscal gates, term gates."""
from test_helpers import (
    validate_error,
    validate_success,
    api_client,
    make_admin_headers,
    make_manager_headers,
    create_org,
    create_agreement,
    create_active_agreement,
    add_tier,
    create_linked_account,
    create_plan,
    ingest_usage,
    generate_invoice,
    setup_finalized_invoice,
    get_agreement,
    ApiErrorId,
)

ADMIN = make_admin_headers()


def test_tier_thresholds_must_be_strictly_increasing_per_family(api):
    """PRD section 3.3: "Within one agreement and one service family, thresholds
    must be strictly increasing: adding a tier whose `threshold_cents` is not
    strictly greater than every existing threshold for that family on that
    agreement is rejected with `ERR_TIER_THRESHOLD_NOT_INCREASING` (HTTP 422)."

    Design: Corner/validations/tier_thresholds_must_be_strictly_increasing_per_family
    """
    org = create_org(name="Ti Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    agr = create_agreement(org["id"], committed_spend_cents=1000000)
    add_tier(agr["id"], service_family="COMPUTE", threshold_cents=1000, rate=0.10)
    resp = api.create_discount_tier(
        {"agreement_id": agr["id"], "service_family": "COMPUTE",
         "threshold_cents": 1000, "rate": 0.20},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_TIER_THRESHOLD_NOT_INCREASING)
    assert resp.status_code == 422
    # a lower threshold is equally rejected
    resp = api.create_discount_tier(
        {"agreement_id": agr["id"], "service_family": "COMPUTE",
         "threshold_cents": 500, "rate": 0.20},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_TIER_THRESHOLD_NOT_INCREASING)


def test_duplicate_usage_record_same_account_family_hour_rejected(api):
    """PRD section 3.5: "At most one record may exist per account, service
    family, and hour; a second record for the same triple is rejected with
    `ERR_DUPLICATE_USAGE_RECORD` (HTTP 422)."

    Design: Corner/validations/duplicate_usage_record_same_account_family_hour_rejected
    """
    org = create_org(name="Du Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    acct = create_linked_account(org["id"], name="a1", external_ref="e1")
    ingest_usage(acct["id"], usage_hour_start="2026-09-01T00:00:00Z",
                 list_price_cents=100)
    resp = api.create_usage_record(
        {"linked_account_id": acct["id"], "service_family": "COMPUTE",
         "usage_hour_start": "2026-09-01T00:00:00Z", "list_price_cents": 200},
        make_manager_headers(acct["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_USAGE_RECORD)
    assert resp.status_code == 422
    # the original record is untouched
    records = api.list_usage_records(
        ADMIN, params={"linked_account_id": acct["id"]}
    ).json()["data"]
    assert len(records) == 1
    assert records[0]["list_price_cents"] == 100


def test_settle_amount_mismatch_rejected_fiscal_check(api):
    """PRD section 3.9: "Settlement moves `FINALIZED` to `SETTLED` and is
    exact-amount: the request's `amount_cents` must equal the invoice's
    `total_due_cents` to the cent, otherwise `ERR_SETTLEMENT_AMOUNT_MISMATCH`
    (HTTP 422)."

    Design: Corner/validations/settle_amount_mismatch_rejected_fiscal_check
    """
    org = create_org(name="Se Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    acct = create_linked_account(org["id"], name="a1", external_ref="e1")
    inv = setup_finalized_invoice(org["id"], acct["id"], 1000)
    resp = api.settle_invoice(inv["id"], {"amount_cents": 999}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_AMOUNT_MISMATCH)
    assert resp.status_code == 422
    refreshed = validate_success(api.get_invoice(inv["id"], ADMIN))
    assert refreshed["status"] == "FINALIZED"
    data = validate_success(
        api.settle_invoice(inv["id"], {"amount_cents": 1000}, ADMIN)
    )
    assert data["status"] == "SETTLED"


def test_invoice_period_already_billed_rejected(api):
    """PRD section 3.6: "Invoice generation bills one organization for one
    period. The caller supplies `org_id` and `period_index`; a period that is
    already covered by a non-`VOIDED` invoice of the org is rejected with
    `ERR_INVOICE_PERIOD_ALREADY_BILLED` (HTTP 422)."

    Design: Corner/validations/invoice_period_already_billed_rejected
    """
    org = create_org(name="Pb Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    acct = create_linked_account(org["id"], name="a1", external_ref="e1")
    ingest_usage(acct["id"], usage_hour_start="2026-09-01T00:00:00Z",
                 list_price_cents=100)
    generate_invoice(org["id"], period_index=0)
    resp = api.generate_invoice({"org_id": org["id"], "period_index": 0}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVOICE_PERIOD_ALREADY_BILLED)
    assert resp.status_code == 422


def test_second_active_agreement_per_org_rejected(api):
    """PRD section 3.2: "And no other agreement of the same organization may
    already be `ACTIVE`, else `ERR_ORG_HAS_ACTIVE_AGREEMENT` (HTTP 409)."

    Design: Corner/validations/second_active_agreement_per_org_rejected
    """
    org = create_org(name="Sg Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    agr_a = create_agreement(org["id"], name="A", committed_spend_cents=1000000)
    add_tier(agr_a["id"], service_family="COMPUTE", threshold_cents=0, rate=0.10)
    agr_b = create_agreement(org["id"], name="B", committed_spend_cents=500000)
    add_tier(agr_b["id"], service_family="COMPUTE", threshold_cents=0, rate=0.15)
    validate_success(api.activate_agreement(agr_a["id"], ADMIN))
    resp = api.activate_agreement(agr_b["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ORG_HAS_ACTIVE_AGREEMENT)
    assert resp.status_code == 409
    assert get_agreement(agr_b["id"])["lifecycle_status"] == "NEGOTIATION"


def test_commitment_ceiling_boundary_exactly_at_cap_succeeds(api):
    """PRD section 3.4: "Finally, the fiscal ceiling: the sum of
    `hourly_commitment_cents` over the org's `ACTIVE` plans plus the new plan's
    commitment must not exceed `max_hourly_commitment_cents`, else
    `ERR_COMMITMENT_CEILING_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/commitment_ceiling_boundary_exactly_at_cap_succeeds
    """
    org = create_org(name="Ce Org", max_hourly_commitment_cents=150,
                     capacity_quota_units=100)
    agr = create_active_agreement(
        org["id"],
        tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
        committed_spend_cents=1000000,
    )
    create_plan(org["id"], agr["id"], instance_family="COMPUTE",
                hourly_commitment_cents=100)
    data = validate_success(
        api.create_commitment_plan(
            {
                "org_id": org["id"], "agreement_id": agr["id"],
                "type": "SAVINGS_PLAN", "instance_family": "STORAGE", "units": 0,
                "hourly_commitment_cents": 50, "plan_discount_rate": 0.30,
                "term_start": "2026-09-01T00:00:00Z",
                "term_end": "2026-10-01T00:00:00Z",
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert data["status"] == "ACTIVE"
    resp = api.create_commitment_plan(
        {
            "org_id": org["id"], "agreement_id": agr["id"],
            "type": "SAVINGS_PLAN", "instance_family": "DATABASE", "units": 0,
            "hourly_commitment_cents": 1, "plan_discount_rate": 0.30,
            "term_start": "2026-09-01T00:00:00Z",
            "term_end": "2026-10-01T00:00:00Z",
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_CEILING_EXCEEDED)
    assert resp.status_code == 422


def test_trueup_assess_before_term_end_rejected(api):
    """PRD section 3.8: "Only an `EXPIRED` agreement may be assessed for a
    shortfall; assessing earlier fails with `ERR_TERM_NOT_ENDED` (HTTP 409)."

    Design: Corner/validations/trueup_assess_before_term_end_rejected
    """
    org = create_org(name="Tu Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    agr = create_active_agreement(
        org["id"],
        tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
        committed_spend_cents=1000000,
    )
    resp = api.assess_trueup({"agreement_id": agr["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_TERM_NOT_ENDED)
    assert resp.status_code == 409


def test_usage_ingest_with_nonzero_minute_rejected(api):
    """PRD section 3.5: "The `usage_hour_start` must be aligned to the hour —
    minute and second both zero — otherwise the record is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/usage_ingest_with_nonzero_minute_rejected
    """
    org = create_org(name="Hr Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    acct = create_linked_account(org["id"], name="a1", external_ref="e1")
    resp = api.create_usage_record(
        {"linked_account_id": acct["id"], "service_family": "COMPUTE",
         "usage_hour_start": "2026-09-01T00:30:00Z", "list_price_cents": 100},
        make_manager_headers(acct["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400
