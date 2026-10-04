"""Tests for state-machine claims: terminal lockdown, idempotency, cascades."""
from test_helpers import (
    validate_error,
    validate_success,
    api_client,
    make_admin_headers,
    make_platform_headers,
    create_org,
    create_active_agreement,
    create_linked_account,
    create_grant,
    ingest_usage,
    generate_invoice,
    get_invoice,
    get_invoice_lines,
    get_credit_grant,
    set_clock,
    setup_draft_invoice,
    setup_finalized_invoice,
    ApiErrorId,
)

ADMIN = make_admin_headers()
PLATFORM = make_platform_headers()


def test_credit_grant_terminal_lockdown_revoke_on_exhausted_rejected(api):
    """PRD section 3.7: "Once a grant reaches any terminal state — `EXHAUSTED`,
    `EXPIRED`, or `REVOKED` — any further revoke or consume attempt against it is
    rejected with `ERR_CREDIT_NOT_USABLE` (HTTP 409)."

    Design: Corner/state_machines/credit_grant_terminal_lockdown_revoke_on_exhausted_rejected
    """
    org = create_org(name="Tl Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=10)
    acct = create_linked_account(org["id"], name="a1", external_ref="e1")
    grant = create_grant(org["id"], amount_cents=300,
                         expires_at="2026-12-01T00:00:00Z")
    setup_finalized_invoice(org["id"], acct["id"], 300)
    g = get_credit_grant(grant["id"])
    assert g["status"] == "EXHAUSTED"
    resp = api.revoke_credit_grant(grant["id"], PLATFORM)
    validate_error(resp, ApiErrorId.ERR_CREDIT_NOT_USABLE)
    assert resp.status_code == 409
    g = get_credit_grant(grant["id"])
    assert g["status"] == "EXHAUSTED"
    assert g["consumed_cents"] == 300
    assert g["forfeited_cents"] == 0


def test_invoice_settle_from_draft_rejected_invalid_state(api):
    """PRD section 3.11: "Agreement termination is terminal: an agreement in
    `EXPIRED` or `TERMINATED` accepts no further lifecycle transitions, and any
    attempted transition from a terminal state — here or on any other entity — is
    rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409), as are repeated
    non-idempotent actions such as suspending an already-suspended account."
    PRD section 3.9: "Settlement moves `FINALIZED` to `SETTLED` and is
    exact-amount: the request's `amount_cents` must equal the invoice's
    `total_due_cents` to the cent, otherwise `ERR_SETTLEMENT_AMOUNT_MISMATCH`
    (HTTP 422)."

    Design: Corner/state_machines/invoice_settle_from_draft_rejected_invalid_state
    """
    org = create_org(name="St Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=10)
    acct = create_linked_account(org["id"], name="a1", external_ref="e1")
    inv = setup_draft_invoice(org["id"], acct["id"], 1000)
    resp = api.settle_invoice(inv["id"], {"amount_cents": 1000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert resp.status_code == 409
    assert get_invoice(inv["id"])["status"] == "DRAFT"


def test_agreement_double_activate_rejected_not_idempotent(api):
    """PRD section 3.11: "Agreement termination is terminal: an agreement in
    `EXPIRED` or `TERMINATED` accepts no further lifecycle transitions, and any
    attempted transition from a terminal state — here or on any other entity — is
    rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409), as are repeated
    non-idempotent actions such as suspending an already-suspended account."

    Design: Corner/state_machines/agreement_double_activate_rejected_not_idempotent
    """
    org = create_org(name="Id Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=10)
    agr = create_active_agreement(
        org["id"],
        tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
        committed_spend_cents=1000,
    )
    resp = api.activate_agreement(agr["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert resp.status_code == 409


def test_credit_expiry_at_period_close_forfeits_remainder_conditional_cascade(api):
    """PRD section 3.7: "A period close that finds the clock at or past
    `expires_at` moves an `ISSUED` or `DEPLETING` grant to `EXPIRED`, setting
    `forfeited_cents` to the entire `remaining_cents` and leaving `consumed_cents`
    untouched, so `remaining_cents` recomputes to zero."
    PRD section 3.8: "When the operator runs it for an organization,
    `current_period_index` advances by exactly 1, and three expiry sweeps fire
    against the logical clock: every credit grant in `ISSUED` or `DEPLETING` whose
    `expires_at` has been reached moves to `EXPIRED` under the forfeiture
    bookkeeping of §3.7; every `ACTIVE` commitment plan whose `term_end` has been
    reached moves to `EXPIRED`; and every agreement whose lifecycle is `ACTIVE`
    and whose `term_end` has been reached moves to `EXPIRED`."

    Design: Corner/state_machines/credit_expiry_at_period_close_forfeits_remainder_conditional_cascade
    """
    org = create_org(name="Ex Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=10)
    ga = create_grant(org["id"], amount_cents=500,
                      expires_at="2026-09-15T00:00:00Z")
    gb = create_grant(org["id"], amount_cents=700,
                      expires_at="2026-12-01T00:00:00Z")
    set_clock("2026-10-01T00:00:00Z")
    data = validate_success(api.run_period_close(org["id"], PLATFORM))
    assert data["unapplied_credit_cents"] == 700
    ga_after = get_credit_grant(ga["id"])
    gb_after = get_credit_grant(gb["id"])
    assert ga_after["status"] == "EXPIRED"
    assert ga_after["forfeited_cents"] == 500
    assert ga_after["remaining_cents"] == 0
    assert gb_after["status"] == "ISSUED"
    assert gb_after["remaining_cents"] == 700


def test_invoice_void_reverts_usage_records_to_ingested(api):
    """PRD section 3.9: "A `DRAFT` invoice may instead be voided, moving it to
    `VOIDED`; voiding releases every usage record billed into it back to
    `INGESTED` with `invoice_id` cleared to null, which makes the period billable
    again."

    Design: Corner/state_machines/invoice_void_reverts_usage_records_to_ingested
    """
    org = create_org(name="Vd Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=10)
    acct = create_linked_account(org["id"], name="a1", external_ref="e1")
    usage = ingest_usage(acct["id"], usage_hour_start="2026-09-01T00:00:00Z",
                         list_price_cents=800)
    inv = generate_invoice(org["id"], period_index=0)
    validate_success(api.void_invoice(inv["id"], ADMIN))
    u = validate_success(api.get_usage_record(usage["id"], ADMIN))
    assert u["status"] == "INGESTED"
    assert u["invoice_id"] is None
    # the period is billable again
    inv2 = generate_invoice(org["id"], period_index=0)
    assert inv2["status"] == "DRAFT"


def test_settle_flips_billed_trueup_charges_to_settled_bubble_up(api):
    """PRD section 3.8: "When an invoice of the org's agreement is settled, every
    `BILLED` charge of that agreement moves to `SETTLED`. Waived and settled are
    terminal."
    PRD section 3.9: "Settlement moves `FINALIZED` to `SETTLED` and is
    exact-amount: the request's `amount_cents` must equal the invoice's
    `total_due_cents` to the cent, otherwise `ERR_SETTLEMENT_AMOUNT_MISMATCH`
    (HTTP 422). A successful settle cascades to the agreement's `BILLED` true-up
    charges as described in §3.8."

    Design: Corner/state_machines/settle_flips_billed_trueup_charges_to_settled_bubble_up
    """
    org = create_org(name="Bu Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=10)
    agr = create_active_agreement(
        org["id"],
        tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
        committed_spend_cents=10000,
        term_start="2026-09-01T00:00:00Z", term_end="2026-10-01T00:00:00Z",
    )
    acct = create_linked_account(org["id"], name="a1", external_ref="e1")
    inv = setup_finalized_invoice(org["id"], acct["id"], 6000)
    assert inv["total_due_cents"] == 5400, (
        f"6000 - 10% tier discount of 600 = 5400, got {inv['total_due_cents']}"
    )
    set_clock("2026-10-01T00:00:00Z")
    validate_success(api.run_period_close(org["id"], PLATFORM))
    tu = validate_success(
        api.assess_trueup({"agreement_id": agr["id"]}, ADMIN), expected_status=201
    )
    validate_success(api.bill_trueup_charge(tu["id"], ADMIN))
    data = validate_success(
        api.settle_invoice(inv["id"], {"amount_cents": 5400}, ADMIN)
    )
    assert data["status"] == "SETTLED"
    tu_after = validate_success(api.get_trueup_charge(tu["id"], ADMIN))
    assert tu_after["status"] == "SETTLED"
