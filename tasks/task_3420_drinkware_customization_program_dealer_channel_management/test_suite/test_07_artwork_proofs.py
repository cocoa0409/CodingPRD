"""Artwork proofing rounds: the cyclic revision axis (PRD section 3.6)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_proof,
    boot_clock,
    create_colorway_drop,
    create_order,
    create_proof_exhausted_order,
    create_product_line,
    create_submitted_order,
    get_order,
    get_proof,
    make_buyer_headers,
    request_proof_changes,
    submit_order,
    submit_proof,
    validate_error,
    validate_success,
    TEST_USERS,
)


def test_artwork_proof_revision_cycle_supersedes_and_completes(api):
    """The revision loop supersedes each rejected predecessor and advances the
    round counter; round 2 approval lands ART_APPROVED with the FINAL quote
    computed from the new proof.

    PRD section 3.6: "On acceptance the order's `proof_round` increments, the
    new proof is created in `SUBMITTED` with its `round_number` set to the new
    `proof_round` and `submitted_by` stamped with the buyer's `X-User-ID`, any
    earlier proof of the order sitting in `CHANGES_REQUESTED` moves to
    `SUPERSEDED`, and the order's artwork axis becomes `PROOF_SUBMITTED`."
    PRD section 3.6: "Approving the latest proof moves it to `APPROVED`, moves
    the order's artwork axis to `ART_APPROVED`, and computes the FINAL quote
    from the approved proof's actual `color_count` and `placement_count`"

    Design: Difficulty/non_linear_state_machine/artwork_proof_revision_cycle_supersedes_and_completes
    """
    boot_clock()
    line = create_product_line(name="Mug 12 oz", base_sku="MUG12",
                               base_custom_price_cents=2500, map_price_cents=2999,
                               min_custom_quantity=5)
    drop = create_colorway_drop(line["id"], color_name="Seafoam",
                                pantone_code="PMS 7464")
    order = create_order(line["id"], drop["id"], buyer_ref="buyer-cycle",
                         quantity=10, requested_ship_date="2026-09-15T00:00:00Z")
    submit_order(order["id"], "buyer-cycle")

    proof1 = submit_proof(order["id"], "buyer-cycle",
                          artwork_file_ref="s3://art/cycle-v1.ai")
    changed = request_proof_changes(proof1["id"], review_notes="logo off-center")
    assert changed["status"] == "CHANGES_REQUESTED"
    order_mid = get_order(order["id"])
    assert order_mid["artwork_status"] == "CHANGES_REQUESTED"
    assert order_mid["proof_round"] == 1

    proof2 = submit_proof(order["id"], "buyer-cycle",
                          artwork_file_ref="s3://art/cycle-v2.ai",
                          color_count=2, placement_count=1,
                          pantone_codes=["PMS 7464", "PMS White"])
    assert proof2["round_number"] == 2
    assert get_proof(proof1["id"])["status"] == "SUPERSEDED"
    assert get_order(order["id"])["artwork_status"] == "PROOF_SUBMITTED"

    approved = approve_proof(proof2["id"])
    assert approved["status"] == "APPROVED"
    final = get_order(order["id"])
    assert final["artwork_status"] == "ART_APPROVED"
    assert final["quote_variant"] == "FINAL"
    # 10 x (2500 + 1*150) = 26500; INDIVIDUAL has no tier; + 8000 setup
    # (10 < 144); no reservation, so the ship-date probe applies (off-peak).
    assert final["final_quote_cents"] == 34500


def test_approve_superseded_proof_returns_invalid_state(api):
    """Only the latest round is reviewable; approving a SUPERSEDED proof is a
    409 and moves nothing.

    PRD section 3.6: "Review belongs to a `PrepressTech`, and only the latest
    round of an `ACTIVE` order is reviewable — the proof's `round_number` must
    equal the order's current `proof_round` and the proof must be `SUBMITTED`;
    older rounds are `SUPERSEDED`."

    Design: Corner/state_machines/approve_superseded_proof_returns_invalid_state
    """
    boot_clock()
    trio = create_submitted_order()
    order_id = trio["order"]["id"]
    proof1 = submit_proof(order_id, "buyer-std")
    request_proof_changes(proof1["id"], review_notes="fix kerning")
    proof2 = submit_proof(order_id, "buyer-std",
                          artwork_file_ref="s3://art/std-v2.ai")

    resp = api.approve_proof(proof1["id"],
                             TEST_USERS["prepress_tech_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_proof(proof1["id"])["status"] == "SUPERSEDED"
    order = get_order(order_id)
    assert order["artwork_status"] == "PROOF_SUBMITTED"
    assert order["proof_round"] == 2


def test_proof_round_cap_at_3_exhausts_artwork(api):
    """The third request-changes lands the axis in PROOF_EXHAUSTED; a fourth
    proof is refused; only cancellation remains (with a zero fee, since art
    was never approved).

    PRD section 3.6: "Submission requires the order to be `ACTIVE` and its
    artwork axis to be at `NO_ART` or `CHANGES_REQUESTED`, and it requires
    `proof_round` to still be below 3 — a fourth submission is rejected with
    `ERR_PROOF_ROUND_EXHAUSTED`."
    PRD section 3.6: "unless the proof was already the third round, in which
    case the artwork axis lands in `PROOF_EXHAUSTED`, the cycle closes, and
    only cancellation remains for the order."
    PRD section 3.8: "The cancellation fee is zero while the artwork axis is
    anything other than `ART_APPROVED`"

    Design: Corner/state_machines/proof_round_cap_at_3_exhausts_artwork
    """
    bundle = create_proof_exhausted_order()
    order = bundle["order"]
    assert order["artwork_status"] == "PROOF_EXHAUSTED"
    assert order["proof_round"] == 3

    resp = api.create_artwork_proof(
        {
            "order_id": order["id"], "artwork_file_ref": "s3://art/std-v4.ai",
            "color_count": 1, "placement_count": 1, "pantone_codes": ["PMS 533"],
        },
        make_buyer_headers("buyer-std"),
    )
    validate_error(resp, ApiErrorId.ERR_PROOF_ROUND_EXHAUSTED)

    cancelled = validate_success(
        api.cancel_order(order["id"], make_buyer_headers("buyer-std")))
    assert cancelled["order_state"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 0
    assert cancelled["payment_status"] == "REFUNDED"
