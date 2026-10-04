"""Merchant onboarding, batch recording, and concurrency/versioning tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    accept_offer_payload,
    create_active_loan,
    create_batch_payload,
    create_eligible_merchant,
    create_issued_offer,
    create_merchant,
    create_merchant_payload,
    create_sweep_payload,
    get_success_data,
    make_merchant_owner_headers,
    post_sweep,
    record_finalized_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]
SERVICER = TEST_USERS["servicer_agent_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Queue B: entities — creation rules and computed-field behavior
# ---------------------------------------------------------------------------

def test_merchant_create_missing_required_field_rejected(api):
    """PRD Section 2.7: "Tenth and last, request-body shape — required fields present, enum values valid, cents non-negative integers, `state_code` two uppercase letters — reported as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/merchant_create_missing_required_field_rejected
    """
    payload = {
        "state_code": "TX",
        "owner_name": "No Name",
        "processing_started_at": "2023-01-01T00:00:00Z",
    }
    resp = api.create_merchant(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_merchant_create_computed_input_ignored(api):
    """PRD Section 3.1: "A new merchant enters `ONBOARDING` status with all aggregates zeroed: `lifetime_net_cents`, `trailing_12m_months_recorded`, `trailing_30d_net_cents`, and `prior_30d_net_cents` are zero, `seasonality_index` and `trailing_30d_chargeback_ratio` are zero, `loans_repaid_count` is 0, and `active_loan_id` is null."

    Design: Corner/entities/merchant_create_computed_input_ignored
    """
    payload = create_merchant_payload(
        legal_name="Override Co", owner_name="Ov Err")
    payload["lifetime_net_cents"] = 99_999_999
    payload["seasonality_index"] = 9.9
    created = validate_success(api.create_merchant(payload, ADMIN), expected_status=201)
    assert created["lifetime_net_cents"] == 0, "client-supplied computed field must be ignored"
    assert created["seasonality_index"] == 0
    assert created["status"] == "ONBOARDING"

    fetched = validate_success(api.get_merchant(created["id"], ADMIN))
    assert fetched["lifetime_net_cents"] == 0
    assert fetched["seasonality_index"] == 0


def test_batch_create_defaults_applied(api):
    """PRD Section 3.1: "A `PlatformAdmin` or `ServicerAgent` records a batch for a merchant with `processing_date` (a calendar date, unique per merchant — a second batch for the same merchant and date is rejected with `ERR_DUPLICATE_PROCESSING_DATE`), `gross_cents`, and optionally `refunds_cents` and `chargebacks_cents`, which both default to 0. At creation the batch is `OPEN` and its `net_settled_cents` is computed as gross minus refunds minus chargebacks."

    Design: Corner/entities/batch_create_defaults_applied
    """
    merchant = create_merchant(legal_name="Def Co", owner_name="De Fault")
    payload = {"processing_date": "2026-09-01", "gross_cents": 7500}
    batch = validate_success(
        api.create_batch(merchant["id"], payload, ADMIN), expected_status=201)
    assert batch["refunds_cents"] == 0
    assert batch["chargebacks_cents"] == 0
    assert batch["net_settled_cents"] == 7500
    assert batch["status"] == "OPEN"


def test_loan_get_not_found_returns_404(api):
    """PRD Section 2.3: "When a path nests one resource beneath another, the path parameters are validated left to right — the parent is resolved first, and the first parameter that names a nonexistent resource yields `ERR_NOT_FOUND`."

    Design: Corner/entities/loan_get_not_found_returns_404
    """
    resp = api.get_loan(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_merchant_create_invalid_state_code_rejected(api):
    """PRD Section 2.7: "Tenth and last, request-body shape — required fields present, enum values valid, cents non-negative integers, `state_code` two uppercase letters — reported as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/merchant_create_invalid_enum_rejected
    """
    payload = create_merchant_payload(
        legal_name="Bad State Co", owner_name="Ba D", state_code="Texas")
    resp = api.create_merchant(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_merchants_list_pagination_envelope(api):
    """PRD Section 2.3: "List endpoints accept the optional query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Results are always sorted by `created_at` ascending. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in `meta`, alongside `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/merchants_list_pagination_envelope
    """
    create_merchant(legal_name="P1 Co", owner_name="P One")
    create_merchant(legal_name="P2 Co", owner_name="P Two", state_code="CA")
    data, meta = validate_paginated(
        api.list_merchants(AUDITOR, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ---------------------------------------------------------------------------
# Queue B: state_machines / validations — batch rules
# ---------------------------------------------------------------------------

def test_batch_finalize_from_finalized_rejected(api):
    """PRD Section 3.1: "An `OPEN` batch becomes `FINALIZED` when a `ServicerAgent` finalizes it. Finalization is the moment a batch begins to count: the merchant's aggregates are recomputed from the full set of the merchant's batches in `FINALIZED` or `SWEPT` status, and the merchant's `version` increments."

    Design: Corner/state_machines/batch_finalize_from_finalized_rejected
    """
    merchant = create_merchant(legal_name="FF Co", owner_name="F F")
    record_finalized_batch(merchant["id"], "2026-09-01", 1000)

    batch_id = validate_paginated(
        api.list_batches(merchant["id"], ADMIN))[0][0]["id"]
    resp = api.finalize_batch(batch_id, SERVICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    merchant_after = validate_success(api.get_merchant(merchant["id"], ADMIN))
    assert merchant_after["lifetime_net_cents"] == 1000, (
        "rejected finalize must not double-count the batch"
    )


def test_duplicate_processing_date_rejected(api):
    """PRD Section 3.1: "A `PlatformAdmin` or `ServicerAgent` records a batch for a merchant with `processing_date` (a calendar date, unique per merchant — a second batch for the same merchant and date is rejected with `ERR_DUPLICATE_PROCESSING_DATE`), `gross_cents`, and optionally `refunds_cents` and `chargebacks_cents`, which both default to 0."

    Design: Corner/validations/duplicate_processing_date_rejected
    """
    merchant = create_merchant(legal_name="Dup Co", owner_name="Du P")
    validate_success(api.create_batch(
        merchant["id"],
        create_batch_payload(processing_date="2026-09-01", gross_cents=1000),
        ADMIN), expected_status=201)
    resp = api.create_batch(
        merchant["id"],
        create_batch_payload(processing_date="2026-09-01", gross_cents=2000),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PROCESSING_DATE)


# ---------------------------------------------------------------------------
# Queue B: merchant activation gates
# ---------------------------------------------------------------------------

def test_merchant_activate_tenure_insufficient_rejected(api):
    """PRD Section 3.1: "A merchant in `ONBOARDING` is activated by a `PlatformAdmin`, moving it to `ELIGIBLE`, only when two minimums both hold at that moment: the merchant has at least 365 days of tenure — the clock minus `processing_started_at` is no less than 365 days, otherwise `ERR_MERCHANT_TENURE_INSUFFICIENT` — and `lifetime_net_cents` is at least 10000000 cents ($100,000 of lifetime net settled volume), otherwise `ERR_MERCHANT_VOLUME_INSUFFICIENT`."

    Design: Corner/validations/merchant_activate_tenure_insufficient_rejected
    """
    merchant = create_merchant(
        legal_name="Young Co",
        owner_name="Yo Ung",
        processing_started_at="2026-01-01T00:00:00Z",
    )
    record_finalized_batch(merchant["id"], "2026-08-01", 15_000_000)
    resp = api.activate_merchant(merchant["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_MERCHANT_TENURE_INSUFFICIENT)
    assert validate_success(api.get_merchant(merchant["id"], ADMIN))["status"] == "ONBOARDING"


def test_merchant_activate_volume_insufficient_rejected(api):
    """PRD Section 3.1: "A merchant in `ONBOARDING` is activated by a `PlatformAdmin`, moving it to `ELIGIBLE`, only when two minimums both hold at that moment: the merchant has at least 365 days of tenure — the clock minus `processing_started_at` is no less than 365 days, otherwise `ERR_MERCHANT_TENURE_INSUFFICIENT` — and `lifetime_net_cents` is at least 10000000 cents ($100,000 of lifetime net settled volume), otherwise `ERR_MERCHANT_VOLUME_INSUFFICIENT`."

    Design: Corner/validations/merchant_activate_volume_insufficient_rejected
    """
    merchant = create_merchant(legal_name="Small Co", owner_name="Sm All")
    record_finalized_batch(merchant["id"], "2026-08-01", 5_000_000)
    resp = api.activate_merchant(merchant["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_MERCHANT_VOLUME_INSUFFICIENT)
    assert validate_success(api.get_merchant(merchant["id"], ADMIN))["status"] == "ONBOARDING"


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_layers — OCC and version bookkeeping
# ---------------------------------------------------------------------------

def test_offer_accept_stale_version_rejected(api):
    """PRD Section 2.6: "Accepting an offer requires `expected_merchant_version` in the request body, carrying the caller's last-observed `version` of the target merchant. If the merchant's current `version` does not match — because, for example, another writer accepted an offer in the meantime, setting `active_loan_id` and superseding the caller's view — the acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/offer_accept_stale_version_rejected
    """
    merchant = create_eligible_merchant(legal_name="Flat Co")
    offer = create_issued_offer(merchant["id"])

    observed = validate_success(api.get_merchant(merchant["id"], ADMIN))
    stale_version = observed["version"]
    # A finalize after the observation increments the merchant's version.
    record_finalized_batch(merchant["id"], "2026-09-01", 1_000_000)

    payload = accept_offer_payload(stale_version)
    resp = api.accept_offer(
        offer["id"], payload, make_merchant_owner_headers(merchant["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    offer_after = validate_success(api.get_offer(offer["id"], UNDERWRITER))
    assert offer_after["status"] == "OFFERED", "no acceptance side effects may occur"
    merchant_after = validate_success(api.get_merchant(merchant["id"], ADMIN))
    assert merchant_after["active_loan_id"] is None


def test_sweep_post_stale_version_rejected(api):
    """PRD Section 2.6: "Posting a settlement sweep against a loan requires `expected_loan_version` in the request body, carrying the caller's last-observed `version` of that loan. Because a sweep mutates `remaining_balance_cents`, a caller holding a stale balance view must re-read the loan before posting the next sweep; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/sweep_post_stale_version_rejected
    """
    bundle = create_active_loan(principal_cents=500_000)
    loan_id = bundle["loan"]["id"]
    merchant_id = bundle["merchant"]["id"]
    b1 = record_finalized_batch(merchant_id, "2026-09-02", 50_000)
    b2 = record_finalized_batch(merchant_id, "2026-09-03", 50_000)

    stale_version = validate_success(api.get_loan(loan_id, SERVICER))["version"]
    validate_success(api.create_sweep(
        loan_id, create_sweep_payload(b1["id"], stale_version), SERVICER),
        expected_status=201)

    resp = api.create_sweep(
        loan_id, create_sweep_payload(b2["id"], stale_version), SERVICER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    fresh_version = validate_success(api.get_loan(loan_id, SERVICER))["version"]
    second = validate_success(api.create_sweep(
        loan_id, create_sweep_payload(b2["id"], fresh_version), SERVICER),
        expected_status=201)
    assert second["holdback_cents"] == 5000

    loan_after = validate_success(api.get_loan(loan_id, SERVICER))
    assert loan_after["paid_to_date_cents"] == 10_000


def test_version_increments_on_finalize(api):
    """PRD Section 2.4: "Every entity in this API carries a server-minted `id` (a UUID, with no type prefix), a `created_at` timestamp in ISO 8601 UTC with three fractional digits, an `updated_at` timestamp in the same format refreshed on every mutation, and an integer `version` that starts at 1 and increments by 1 on every mutation of that entity."
    PRD Section 3.1: "Finalization is the moment a batch begins to count: the merchant's aggregates are recomputed from the full set of the merchant's batches in `FINALIZED` or `SWEPT` status, and the merchant's `version` increments."

    Design: Corner/cross_cutting_layers/version_increments_on_finalize
    """
    merchant = create_merchant(legal_name="Ver Co", owner_name="Ve R")
    assert merchant["version"] == 1

    batch = validate_success(api.create_batch(
        merchant["id"],
        create_batch_payload(processing_date="2026-09-01", gross_cents=1000),
        ADMIN), expected_status=201)
    validate_success(api.finalize_batch(batch["id"], SERVICER))

    after = validate_success(api.get_merchant(merchant["id"], ADMIN))
    assert after["version"] == 2, "finalize cascade increments Merchant.version by exactly 1"
    assert after["lifetime_net_cents"] == 1000, "aggregate reconciled immediately"
