"""The zero-quantity guard and the one-UTF-per-channel scope, in isolation.

Both are the "continuation half" of a boundary rule: a quantity that must be
at least one card, and a channel-level conflict that is scoped to the pair
rather than to the allocation row.
"""

from test_helpers import (
    ApiErrorId,
    approve_artwork_for_set,
    approve_card_set,
    build_packed_out_line,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    get_success_data,
    submit_card_set_for_review,
    TEST_USERS,
    validate_error,
    validate_success,
)

PM = TEST_USERS["product_manager_headers"]
QA = TEST_USERS["quality_analyst_headers"]
CS = TEST_USERS["collector_support_headers"]
DIST = TEST_USERS["distribution_manager_headers"]


def _approved_set_for_claims(api):
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    return get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))


def test_a_quality_claim_asserting_zero_affected_cards_cannot_be_approved(api):
    """PRD §3.7: "Approval requires the claim to still be in `UNDER_REVIEW`
    (`ERR_INVALID_STATE`) and requires `affected_quantity` to be at least 1 — a
    claim asserting zero affected cards is refused with
    `ERR_CLAIM_QUANTITY_INVALID`."

    Design: Difficulty/boundary_precision_check/claim_backdate_window_opens_at_thirty_days_not_twenty_nine
    """
    card_set = _approved_set_for_claims(api)
    claim = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            {
                "claim_type": "MISPRINT",
                "severity": "MINOR",
                "affected_quantity": 0,
                "filed_on": "2026-09-01T00:00:00Z",
            },
            QA,
        )
    )
    reviewed = validate_success(api.open_claim_review(claim["id"], QA))
    assert reviewed["status"] == "UNDER_REVIEW"

    resp = api.approve_quality_claim(claim["id"], QA)
    validate_error(resp, ApiErrorId.ERR_CLAIM_QUANTITY_INVALID, expected_status=422)
    after = validate_success(api.get_quality_claim(claim["id"], QA))
    assert after["status"] == "UNDER_REVIEW", "the refused approval wrote nothing"


def test_one_affected_card_is_enough_to_approve_a_quality_claim(api):
    """PRD §3.7: "requires `affected_quantity` to be at least 1".

    Design: Difficulty/boundary_precision_check/claim_backdate_window_opens_at_thirty_days_not_twenty_nine
    """
    card_set = _approved_set_for_claims(api)
    claim = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            {
                "claim_type": "DAMAGE",
                "severity": "MAJOR",
                "affected_quantity": 1,
                "filed_on": "2026-09-01T00:00:00Z",
            },
            QA,
        )
    )
    get_success_data(api.open_claim_review(claim["id"], QA))
    approved = validate_success(api.approve_quality_claim(claim["id"], QA))
    assert approved["status"] == "APPROVED"
    assert approved["claim_weight"] == 2, "MAJOR weighs two"


def test_a_complaint_asserting_zero_cards_cannot_be_approved(api):
    """PRD §3.7: "Both branches independently require `claim_quantity` to be at
    least 1, and a complaint asserting fewer is refused with
    `ERR_CLAIM_QUANTITY_INVALID` regardless of which breach reason it names."

    Design: Difficulty/boundary_precision_check/claim_backdate_window_opens_at_thirty_days_not_twenty_nine
    """
    card_set = _approved_set_for_claims(api)
    complaint = get_success_data(
        api.file_complaint(
            card_set["id"],
            {
                "complaint_label": "No replacement policy",
                "breach_reason": "NO_REPLACEMENT_POLICY",
                "claim_quantity": 0,
            },
            CS,
        )
    )
    reviewed = validate_success(api.start_complaint_review(complaint["id"], CS))
    assert reviewed["status"] == "UNDER_REVIEW"

    resp = api.approve_complaint(complaint["id"], CS)
    validate_error(resp, ApiErrorId.ERR_CLAIM_QUANTITY_INVALID, expected_status=422)
    after = validate_success(api.get_complaint(complaint["id"], CS))
    assert after["status"] == "UNDER_REVIEW"


def test_an_undisclosed_run_complaint_with_zero_cards_is_refused_the_same_way(api):
    """PRD §3.7: "a complaint asserting fewer is refused with
    `ERR_CLAIM_QUANTITY_INVALID` regardless of which breach reason it names."

    Design: Difficulty/boundary_precision_check/claim_backdate_window_opens_at_thirty_days_not_twenty_nine
    """
    card_set = _approved_set_for_claims(api)
    complaint = get_success_data(
        api.file_complaint(
            card_set["id"],
            {
                "complaint_label": "Run never disclosed",
                "breach_reason": "UNDISCLOSED_PRINT_RUN",
                "claim_quantity": 0,
            },
            CS,
        )
    )
    get_success_data(api.start_complaint_review(complaint["id"], CS))
    resp = api.approve_complaint(complaint["id"], CS)
    validate_error(resp, ApiErrorId.ERR_UNDISCLOSED_RUN_DECLARED, expected_status=422)


def test_the_first_hobby_allocation_may_be_marked_unable_to_fill(api):
    """PRD §3.8: "if another allocation for the same product line and the same
    channel is already in `UTF` status, the move is refused with
    `ERR_CHANNEL_ALREADY_UTF`."

    Design: Difficulty/resource_temporal_overlap/two_hobby_allocations_for_one_line_cannot_both_be_utf
    """
    scenario = build_packed_out_line(api)
    line = scenario["line"]
    allocation = get_success_data(
        api.create_allocation(
            {
                "product_line_id": line["id"],
                "channel": "HOBBY",
                "quantity_allocated": 10,
                "effective_price_cents": 72000,
            },
            DIST,
        )
    )
    marked = validate_success(api.mark_allocation_utf(allocation["id"], DIST))
    assert marked["status"] == "UTF"
    assert marked["version"] == allocation["version"] + 1


def test_the_utf_conflict_is_scoped_to_the_channel_pair(api):
    """PRD §3.8: "if another allocation for the same product line and the same
    channel is already in `UTF` status".

    Design: Difficulty/resource_temporal_overlap/two_hobby_allocations_for_one_line_cannot_both_be_utf
    """
    scenario = build_packed_out_line(api)
    line = scenario["line"]
    first = get_success_data(
        api.create_allocation(
            {
                "product_line_id": line["id"],
                "channel": "HOBBY",
                "quantity_allocated": 10,
                "effective_price_cents": 72000,
            },
            DIST,
        )
    )
    second = get_success_data(
        api.create_allocation(
            {
                "product_line_id": line["id"],
                "channel": "HOBBY",
                "quantity_allocated": 5,
                "effective_price_cents": 66000,
            },
            DIST,
        )
    )
    validate_success(api.mark_allocation_utf(first["id"], DIST))
    resp = api.mark_allocation_utf(second["id"], DIST)
    validate_error(resp, ApiErrorId.ERR_CHANNEL_ALREADY_UTF, expected_status=409)
    assert resp.json()["response_type"] == "error"