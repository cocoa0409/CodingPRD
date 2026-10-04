"""Transfer requests, the buyer training gate, transfer fees, and store-side
OCC (PRD §3.4, §2.5)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_enrollment,
    create_franchisee,
    create_store,
    create_territory,
    create_transfer,
    get_store,
    get_training_enrollment,
    get_transfer_request,
    make_franchisee_headers,
    setup_transfer_approved,
    setup_transfer_in_buyer_training,
    setup_transfer_pending,
    validate_error,
    validate_success,
)


def test_transfer_fee_frozen_at_creation_even_as_store_mutates(api, franchisor_ops_headers):
    """PRD §3.4: "The transfer fee is computed once, at creation, and frozen
    thereafter — later edits to the sale price are impossible." and "a sale of
    at least 25,000,000 but under 75,000,000 cents pays two percent of the
    price, rounded half up to whole cents" and "If the store is at least ten
    whole years old — measured from its `opened_on` to the logical clock — the
    fee is then multiplied by 0.90, again rounded half up to whole cents,
    yielding `transfer_fee_cents`."

    Design: Corner/entities/transfer_fee_frozen_at_creation_even_as_store_mutates
    """
    territory = create_territory()
    seller = create_franchisee()
    buyer = create_franchisee()
    store = create_store(territory["id"], seller["id"],
                         opened_on="2016-09-01T00:00:00Z")
    store_v = store["version"]
    transfer = create_transfer(store, seller["id"], buyer["id"],
                               sale_price_cents=40_000_000)
    # Mid tier: 40,000,000 x 0.02 = 800,000; 10-year age discount x 0.90.
    assert transfer["transfer_fee_cents"] == 720_000
    assert transfer["seller_franchisee_id"] == seller["id"]
    # Transfer creation bumped the OCC parent.
    bumped = get_store(store["id"])
    assert bumped["version"] == store_v + 1
    # Fee stays frozen even as the store mutates (cancel bumps store state indirectly).
    validate_success(api.cancel_transfer(transfer["id"], make_franchisee_headers(seller["id"])), 200)
    after = get_transfer_request(transfer["id"])
    assert after["transfer_fee_cents"] == 720_000


def test_advance_to_training_requires_buyer_enrollment(api, franchisor_ops_headers):
    """PRD §3.4: "Advancing a `PENDING` request to `BUYER_TRAINING` requires
    the buyer to hold a `TRANSFER_BUYER` training enrollment in `ENROLLED` or
    `COMPLETED` status, failing which the advance is refused with
    `ERR_BUYER_TRAINING_INCOMPLETE`"

    Design: Difficulty/cross_entity_state_dependency/transfer_approve_requires_buyer_training_completed
    """
    ctx = setup_transfer_pending()
    resp = api.advance_transfer_to_training(ctx["transfer"]["id"], franchisor_ops_headers)
    validate_error(resp, ApiErrorId.ERR_BUYER_TRAINING_INCOMPLETE, 422)
    still = get_transfer_request(ctx["transfer"]["id"])
    assert still["status"] == "PENDING"


def test_enrollment_completion_advances_transfer_to_pending_approval(api, franchisor_ops_headers):
    """PRD §3.4: "While a request waits in `BUYER_TRAINING`, the buyer's
    enrollment outcome drives it: the enrollment flipping to `COMPLETED` moves
    the request to `PENDING_APPROVAL`"
    PRD §3.4: "a score of at least 80 completes the enrollment (stamping
    `completed_on`)"

    Design: Difficulty/cross_entity_state_dependency/transfer_approve_requires_buyer_training_completed
    """
    ctx = setup_transfer_in_buyer_training()
    # Pre-completion approve: the request is in BUYER_TRAINING, not a
    # from-state of approve.
    resp = api.approve_transfer(ctx["transfer"]["id"], franchisor_ops_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    enrollment = validate_success(
        api.record_training_result(ctx["enrollment"]["id"], {"score": 85},
                                   franchisor_ops_headers), 200)
    assert enrollment["status"] == "COMPLETED"
    assert enrollment["completed_on"] is not None
    transfer = get_transfer_request(ctx["transfer"]["id"])
    assert transfer["status"] == "PENDING_APPROVAL"
    approved = validate_success(api.approve_transfer(transfer["id"], franchisor_ops_headers), 200)
    assert approved["status"] == "APPROVED"


def test_state_beats_safety_on_transfer_approve(api, franchisor_ops_headers):
    """PRD §2.8: "the first failing rung determines the error returned. In
    order: ... (5) state validity ...; (6) the buyer-training gate on transfer
    advancement and approval"
    PRD §2.8: "State failures return `ERR_INVALID_STATE` (HTTP 409); stale-version failures return `ERR_STALE_VERSION` (HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_transfer_approve
    """
    ctx = setup_transfer_pending()
    validate_success(
        api.cancel_transfer(ctx["transfer"]["id"],
                            make_franchisee_headers(ctx["seller"]["id"])), 200)
    # CANCELLED is terminal; the buyer also has no training enrollment, so the
    # priority-6 safety gate would fail too — state must win.
    resp = api.approve_transfer(ctx["transfer"]["id"], franchisor_ops_headers)
    error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert error["error_id"] != ApiErrorId.ERR_BUYER_TRAINING_INCOMPLETE


def test_advance_cancelled_transfer_reports_state_not_training_gate(api, franchisor_ops_headers):
    """PRD §2.8: "the first failing rung determines the error returned. In
    order: ... (5) state validity — the target must be in a from-state of the
    requested transition, terminal states reject everything ...; (6) the
    buyer-training gate on transfer advancement and approval"
    PRD §3.4: "the seller may also cancel any request in `PENDING`,
    `BUYER_TRAINING`, or `PENDING_APPROVAL`, moving it to terminal
    `CANCELLED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_transfer_approve
    """
    ctx = setup_transfer_pending()
    validate_success(
        api.cancel_transfer(ctx["transfer"]["id"],
                            make_franchisee_headers(ctx["seller"]["id"])), 200)
    # Advance on the CANCELLED request: buyer has no enrollment either, but
    # the terminal-state check (priority 5) fires before the training gate.
    resp = api.advance_transfer_to_training(ctx["transfer"]["id"], franchisor_ops_headers)
    error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert error["error_id"] != ApiErrorId.ERR_BUYER_TRAINING_INCOMPLETE


def test_store_read_reflects_transfer_completion_immediately(api, franchisor_ops_headers):
    """PRD §3.4: "Completing an approved request applies the same store-status
    guard, flips the store's `franchisee_id` to the buyer, recognizes
    `transfer_fee_cents`, and increments the store's `version` by 1."
    PRD §3.1: "a franchisee flips to `ACTIVE` automatically the first time a
    store opens under their ownership or is transferred to them."

    Design: Corner/consistency_model/store_read_reflects_transfer_completion_immediately
    """
    ctx = setup_transfer_approved()
    completed = validate_success(
        api.complete_transfer(ctx["transfer"]["id"], franchisor_ops_headers), 200)
    assert completed["status"] == "COMPLETED"
    store = validate_success(api.get_store(ctx["store"]["id"], franchisor_ops_headers), 200)
    assert store["franchisee_id"] == ctx["buyer"]["id"]
    from test_helpers import validate_paginated
    buyer_rows, buyer_meta = validate_paginated(
        api.list_franchisee_stores(ctx["buyer"]["id"],
                                   make_franchisee_headers(ctx["buyer"]["id"])))
    seller_rows, seller_meta = validate_paginated(
        api.list_franchisee_stores(ctx["seller"]["id"],
                                   make_franchisee_headers(ctx["seller"]["id"])))
    assert buyer_meta["total_count"] == 1
    assert seller_meta["total_count"] == 0
    buyer = validate_success(
        api.get_franchisee(ctx["buyer"]["id"],
                           make_franchisee_headers(ctx["buyer"]["id"])), 200)
    assert buyer["status"] == "ACTIVE"


def test_transfer_create_with_stale_store_version_412(api):
    """PRD §2.5: "Creating a transfer request requires the request to carry
    `expected_store_version` — a non-optional field holding the client's last
    observed `version` of the target store. A mismatch with the store's
    current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_layers/transfer_create_with_stale_store_version_412
    """
    ctx = setup_transfer_pending()
    stale_version = ctx["store"]["version"]  # observed before the first create
    buyer_b = create_franchisee()
    from test_helpers import create_transfer_request_payload
    resp = api.create_transfer_request(
        create_transfer_request_payload(ctx["store"]["id"], buyer_b["id"], stale_version,
                                        sale_price_cents=50_000_000),
        make_franchisee_headers(ctx["seller"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
    from test_helpers import validate_paginated
    rows, meta = validate_paginated(
        api.list_store_transfer_requests(
            ctx["store"]["id"], make_franchisee_headers(ctx["seller"]["id"]))
    )
    assert meta["total_count"] == 1
