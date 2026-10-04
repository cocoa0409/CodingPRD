"""Warranty claims: intake shape, warranty windows, the fraud gate, and
replacement resolution (PRD section 3.9)."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    api_client,
    boot_clock,
    create_authorized_dealer,
    create_completed_order,
    create_product_line,
    create_warranty_claim,
    create_warranty_claim_payload,
    decide_claim,
    file_dtc_claims,
    get_drop,
    make_buyer_headers,
    make_dealer_headers,
    make_warranty_agent_headers,
    set_clock,
    start_claim_review,
    validate_error,
    validate_paginated,
    validate_success,
    assert_drop_unit_ledger_invariant,
    assert_warranty_claim,
    TEST_USERS,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_WARRANTY = TEST_USERS["warranty_agent_headers"]


def _ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_warranty_claim_conditional_required_fields_enforced(api):
    """dealer_id is required exactly when claim_source is DEALER, buyer_ref
    exactly when DTC — each absence is a request-shape failure.

    PRD section 3.9: "When `claim_source` is `DEALER` the `dealer_id` is
    required and, for a `Dealer` caller, must equal the acting identity; when
    it is `DTC` the `buyer_ref` is required with the same ownership rule."
    PRD section 2.7: "(3) request-body shape — required fields present, types
    correct, enum values in range, and conditionally required fields satisfied
    ... with any failure reported as `ERR_INVALID_REQUEST`"

    Design: Corner/entities/warranty_claim_conditional_required_fields_enforced
    """
    boot_clock()
    line = create_product_line()

    resp_dealer = api.create_warranty_claim(
        {"claim_source": "DEALER", "serial_number": "S-100", "component": "LID",
         "failure_description": "cracked", "purchase_date": "2026-06-01T00:00:00Z",
         "product_line_id": line["id"]},
        _WARRANTY)
    validate_error(resp_dealer, ApiErrorId.ERR_INVALID_REQUEST)

    resp_dtc = api.create_warranty_claim(
        {"claim_source": "DTC", "serial_number": "S-101", "component": "LID",
         "failure_description": "cracked", "purchase_date": "2026-06-01T00:00:00Z",
         "product_line_id": line["id"]},
        _WARRANTY)
    validate_error(resp_dtc, ApiErrorId.ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(api.list_warranty_claims(_WARRANTY))
    assert len(rows) == 0 and meta["total_count"] == 0


def test_dealer_files_dealer_source_claim(api):
    """A dealer-source claim anchors on the purchase date and the line's
    HARDWARE term: 2026-03-01 + 12 calendar months = 2027-03-01.

    PRD section 3.9: "Without an `order_id`, the `product_line_id` and
    `purchase_date` are required and the warranty anchors on the purchase
    date."
    PRD section 3.9: "computes `warranty_expires_at` as the anchor plus the
    component's warranty term in calendar months from the product line —
    `warranty_months_lid`, `warranty_months_insulation`, or
    `warranty_months_hardware`."
    PRD section 2.8: "Calendar arithmetic for warranty expiry is performed in
    calendar months, with the expiry landing at the same clock time on the
    expiry month-day."

    Design: Corner/entities/dealer_files_dealer_source_claim
    """
    pair = create_authorized_dealer()  # boots the clock
    dealer_id = pair["dealer"]["id"]
    line = create_product_line()  # warranty_months_hardware == 12

    resp = api.create_warranty_claim(
        {"claim_source": "DEALER", "dealer_id": dealer_id,
         "product_line_id": line["id"], "serial_number": "S-D1",
         "component": "HARDWARE", "failure_description": "handle snapped",
         "purchase_date": "2026-03-01T00:00:00Z"},
        make_dealer_headers(dealer_id))
    claim = validate_success(resp, 201)
    assert_warranty_claim(claim)
    assert claim["status"] == "FILED"
    assert _ts(claim["warranty_anchor_at"]) == _ts("2026-03-01T00:00:00Z")
    assert _ts(claim["warranty_expires_at"]) == _ts("2027-03-01T00:00:00Z")
    assert claim["fraud_flag"] is False, "no priors in the trailing window"
    assert claim.get("replacement_colorway_resolution") is None


def test_fraud_flag_requires_three_priors(api):
    """The fourth claim in the trailing year is fraud-flagged; a flagged claim
    cannot be decided straight from FILED but can be after start-review.

    PRD section 3.9: "`fraud_flag` is set true when the claimant — keyed by
    `dealer_id` for dealer-source claims and by `buyer_ref` for direct ones —
    already has at least 3 other claims not in `DENIED` status filed within
    the trailing 365 days."
    PRD section 3.9: "The fraud gate stands in front of every decision: a
    fraud-flagged claim may not be decided directly from `FILED` and must pass
    through review first, else the decision is rejected with
    `ERR_FRAUD_REVIEW_REQUIRED`."

    Design: Corner/calculations/fraud_flag_requires_three_priors
    """
    boot_clock()
    line = create_product_line()  # LID warranty 24 months
    claims = file_dtc_claims(line["id"], "buyer-fraud", 4,
                             purchase_date="2026-01-01T00:00:00Z")
    assert claims[3]["fraud_flag"] is True, "three non-DENIED priors on file"

    # Control: the first claim (unflagged) is decidable directly from FILED.
    repaired = decide_claim(claims[0]["id"], "APPROVE_REPAIR",
                            decision_reason="routine")
    assert repaired["status"] == "APPROVED_REPAIR"

    resp = api.decide_warranty_claim(
        claims[3]["id"],
        {"outcome": "DENY", "decision_reason": "pattern abuse"},
        _WARRANTY)
    validate_error(resp, ApiErrorId.ERR_FRAUD_REVIEW_REQUIRED)

    start_claim_review(claims[3]["id"])
    denied = decide_claim(claims[3]["id"], "DENY",
                          decision_reason="pattern abuse confirmed")
    assert denied["status"] == "DENIED"


def test_warranty_expiry_strictly_before_boundary(api):
    """Filing is valid strictly before the expiry instant; filing exactly at
    it is rejected. (The valid leg runs at the earlier clock first so the
    logical clock only moves forward.)

    PRD section 3.9: "The claim is valid only while it is filed strictly
    before the expiry; filing exactly at the expiry moment is rejected with
    `ERR_WARRANTY_EXPIRED`."

    Design: Corner/calculations/warranty_expiry_strictly_before_boundary
    """
    boot_clock()
    line = create_product_line()  # LID warranty 24 months
    # purchase 2024-10-01 + 24 months -> expiry 2026-10-01T00:00:00Z.
    payload_base = {
        "claim_source": "DTC", "buyer_ref": "buyer-expiry",
        "product_line_id": line["id"], "component": "LID",
        "failure_description": "seal failed",
        "purchase_date": "2024-10-01T00:00:00Z",
    }

    set_clock("2026-09-30T23:59:59Z")  # one second before expiry
    ok = validate_success(api.create_warranty_claim(
        {**payload_base, "serial_number": "S-E2"},
        make_buyer_headers("buyer-expiry")), 201)
    assert ok["status"] == "FILED"
    assert ok["fraud_flag"] is False

    set_clock("2026-10-01T00:00:00Z")  # exactly the expiry instant
    resp = api.create_warranty_claim(
        {**payload_base, "serial_number": "S-E1"},
        make_buyer_headers("buyer-expiry"))
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)


def test_warranty_credit_equivalent_when_line_discontinued(api):
    """With no customized order and the line DISCONTINUED, a replacement
    approval degrades to CREDIT_EQUIVALENT at the line's map price.

    PRD section 3.9: "Otherwise the resolution is `CREDIT_EQUIVALENT` and the
    `credit_equivalent_cents` is set to the product line's `map_price_cents`
    snapshot."

    Design: Corner/state_machines/warranty_credit_equivalent_when_line_discontinued
    """
    boot_clock()
    line = create_product_line()
    validate_success(api.discontinue_product_line(line["id"], _ADMIN))

    claim = create_warranty_claim(
        headers=make_buyer_headers("buyer-cred"),
        claim_source="DTC", buyer_ref="buyer-cred",
        product_line_id=line["id"], serial_number="S-C1", component="LID",
        failure_description="lid thread stripped",
        purchase_date="2026-06-01T00:00:00Z")

    decided = decide_claim(claim["id"], "APPROVE_REPLACEMENT",
                           decision_reason="cannot repair a stripped thread")
    assert decided["status"] == "APPROVED_REPLACEMENT"
    assert decided["replacement_colorway_resolution"] == "CREDIT_EQUIVALENT"
    assert decided["credit_equivalent_cents"] == 3499, "map_price_cents snapshot"


def test_warranty_same_colorway_replacement_reserves_drop_unit(api):
    """A replacement approval against an order whose drop is ALLOCATION_LOCKED
    with stock resolves SAME_COLORWAY and reserves one unit in the drop
    ledger.

    PRD section 3.9: "When the claim carries an `order_id` whose order's drop
    is currently `ALLOCATION_LOCKED` or `LIVE` and still has at least one
    `unallocated_units`, the `replacement_colorway_resolution` is
    `SAME_COLORWAY` and the drop's `warranty_reserved_units` increases by one,
    preserving the unit-ledger invariant of §2.10."
    PRD section 3.9: "the claim's buyer or dealer must match the order's, and
    the warranty then anchors on the order's `completed_at`."

    Design: Corner/cross_cutting_layers/warranty_same_colorway_replacement_reserves_drop_unit
    """
    bundle = create_completed_order()  # completed at the boot clock 2026-09-01T06:00Z
    order_id, drop_id = bundle["order"]["id"], bundle["drop"]["id"]

    set_clock("2026-09-06T00:00:00Z")
    validate_success(api.open_allocation(drop_id, _ADMIN))
    set_clock("2026-09-21T00:00:00Z")
    version = get_drop(drop_id)["version"]
    validate_success(api.lock_allocation(
        drop_id, {"expected_drop_version": version}, _ADMIN))
    locked = get_drop(drop_id)
    assert locked["status"] == "ALLOCATION_LOCKED"
    assert locked["unallocated_units"] == 2500  # 3000 - 500 dtc - 0 committed

    # Order-anchored claim: order_id replaces product_line_id/purchase_date.
    payload = create_warranty_claim_payload(
        claim_source="DTC", buyer_ref="buyer-std", order_id=order_id,
        serial_number="S-W1", component="INSULATION",
        failure_description="lost vacuum seal")
    payload.pop("purchase_date", None)
    claim = validate_success(api.create_warranty_claim(
        payload, make_buyer_headers("buyer-std")), 201)
    assert _ts(claim["warranty_anchor_at"]) == _ts(bundle["order"]["completed_at"])

    decided = decide_claim(claim["id"], "APPROVE_REPLACEMENT",
                           decision_reason="insulation failure is replace-only")
    assert decided["status"] == "APPROVED_REPLACEMENT"
    assert decided["replacement_colorway_resolution"] == "SAME_COLORWAY"

    drop = get_drop(drop_id)
    assert drop["warranty_reserved_units"] == 1
    assert drop["unallocated_units"] == 2499
    assert_drop_unit_ledger_invariant(drop)  # 3000 == 0 + 500 + 1 + 2499
