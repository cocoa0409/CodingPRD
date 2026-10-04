"""Calculation corners: aggregate traversal, royalty summation and degenerate
zero cases.

Each test pins one arithmetic rule the PRD states verbatim, including the
degenerate inputs where the answer must still be defined.
"""

from test_helpers import (
    advance_clock,
    ApiErrorId,
    approve_artwork_for_set,
    approve_card_set,
    assert_license_invariants,
    assert_product_line,
    BRAND_DIRECTIVE_BASE,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    create_product_line_raw,
    get_success_data,
    REORDER_HIT_RATE,
    SIGNER_ROYALTY_CENTS,
    submit_card_set_for_review,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["product_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LM = TEST_USERS["licensing_manager_headers"]
QA = TEST_USERS["quality_analyst_headers"]
SC = TEST_USERS["signing_coordinator_headers"]
DIST = TEST_USERS["distribution_manager_headers"]


def _approve(api, license_id, line_id, name, tier, quantity, announced=True,
             autograph_planned_count=0, serial_numbered=False):
    card_set = create_card_set_raw(
        api,
        line_id,
        set_name=name,
        set_tier=tier,
        announced=announced,
        serial_numbered=serial_numbered,
        autograph_planned_count=autograph_planned_count,
        print_run_quantity=quantity,
    )
    approve_artwork_for_set(api, card_set["id"], license_id)
    card_set = submit_card_set_for_review(api, card_set["id"])
    return get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))


# ---------------------------------------------------------------------------
# license_set_counts — aggregate over a licence chain with two lines
# ---------------------------------------------------------------------------
def test_the_license_counts_span_two_product_lines(api):
    """PRD §3.1: "`set_count` is the number of card sets, in any status
    whatsoever, whose parent product line names this license."

    Design: Corner/calculations/license_set_counts_track_sets_across_two_lines
    """
    license_obj = create_active_license(api)
    line_one = create_line_ready(api, license_obj["id"])
    line_two = create_line_ready(
        api, license_obj["id"], line_name="2026 Chrome Baseball", line_kind="INSERT",
        packs_per_box=5,
    )
    _approve(api, license_obj["id"], line_one["id"], "Flagship Base", "BASE", 500)
    _approve(api, license_obj["id"], line_two["id"], "Chrome Base", "INSERT", 0)
    create_card_set_raw(
        api, line_two["id"], set_name="Chrome Refractor", set_tier="INSERT",
        announced=False, serial_numbered=True, print_run_quantity=0,
    )

    read = validate_success(api.get_license(license_obj["id"], LM))
    assert read["set_count"] == 3, "every set under both lines counts, in any status"
    assert read["approved_set_count"] == 2, "the third set is still DRAFT"
    assert_license_invariants(read)


def test_an_unapproved_set_still_counts_towards_set_count(api):
    """PRD §3.1: "`approved_set_count` is the subset of those whose `status` is
    `APPROVED`."

    Design: Corner/calculations/license_set_counts_track_sets_across_two_lines
    """
    license_obj = create_active_license(api)
    line_one = create_line_ready(api, license_obj["id"])
    line_two = create_line_ready(
        api, license_obj["id"], line_name="2026 Chrome Baseball", line_kind="INSERT",
        packs_per_box=5,
    )
    _approve(api, license_obj["id"], line_one["id"], "Flagship Base", "BASE", 500)
    draft_set = create_card_set_raw(
        api, line_two["id"], set_name="Chrome Refractor", set_tier="INSERT",
        announced=False, print_run_quantity=0,
    )
    assert draft_set["status"] == "DRAFT"
    read = validate_success(api.get_license(license_obj["id"], LM))
    assert read["approved_set_count"] == 1
    assert read["set_count"] == 2


def test_the_licence_product_line_collection_lists_both_lines(api):
    """PRD §3.1: "a license's product lines are browsable as a nested
    collection."

    Design: Corner/calculations/license_set_counts_track_sets_across_two_lines
    """
    license_obj = create_active_license(api)
    create_line_ready(api, license_obj["id"])
    create_line_ready(
        api, license_obj["id"], line_name="2026 Chrome Baseball", line_kind="INSERT",
        packs_per_box=5,
    )
    rows, meta = validate_paginated(
        api.list_license_product_lines(license_obj["id"], LM)
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2


def test_an_approved_line_alone_leaves_both_counts_at_zero(api):
    """PRD §3.1: "with both of its aggregate counters — `set_count` and
    `approved_set_count` — at 0."

    Design: Corner/calculations/license_set_counts_track_sets_across_two_lines
    """
    license_obj = create_active_license(api)
    create_line_ready(api, license_obj["id"])
    read = validate_success(api.get_license(license_obj["id"], LM))
    assert read["set_count"] == 0
    assert read["approved_set_count"] == 0


# ---------------------------------------------------------------------------
# autograph_royalty_charge — per-line royalty summation
# ---------------------------------------------------------------------------
def _three_set_session(api):
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    sets = [
        _approve(api, license_obj["id"], line["id"], name, "BASE", quantity,
                 autograph_planned_count=200)
        for name, quantity in (
            ("Flagship Base", 500),
            ("Flagship Auto", 1000),
            ("Flagship Patch", 1500),
        )
    ]
    session = get_success_data(
        api.create_signing_session(
            {
                "signer_name": "Ken Griffey Jr",
                "signer_kind": "PLAYER_ASSOCIATION",
                "license_id": license_obj["id"],
                "scheduled_on": "2026-10-05T00:00:00Z",
                "allocation_lines": [
                    {"card_set_id": sets[0]["id"], "player_id": "kgj", "quantity_delivered": 20},
                    {"card_set_id": sets[1]["id"], "player_id": "kgj", "quantity_delivered": 30},
                    {"card_set_id": sets[2]["id"], "player_id": "kgj", "quantity_delivered": 10},
                ],
            },
            SC,
        )
    )
    validate_success(api.prepare_signing_stock(session["id"], SC))
    return license_obj, line, sets, session


def test_shipping_charges_the_royalty_per_allocation_line(api):
    """PRD §3.4: "Each line's charge is the platform's flat `SIGNER_ROYALTY_CENTS`
    rate of 750 cents per card, multiplied by that line's `quantity_delivered`,
    and the session's royalty total is the sum of those per-line charges,
    recorded on the session."

    Design: Corner/calculations/signer_royalty_charge_sums_over_every_allocation_line
    """
    license_obj, line, sets, session = _three_set_session(api)
    advance_clock(api, session["ship_date"])
    shipped = validate_success(api.ship_signing_stock(session["id"], SC))
    assert shipped["status"] == "STOCK_SHIPPED"
    total_cards = 20 + 30 + 10
    assert shipped["total_allocated_count"] == total_cards
    assert shipped["autograph_royalty_cents"] == SIGNER_ROYALTY_CENTS * total_cards
    assert shipped["autograph_royalty_cents"] == 45000, (
        "750 x 60 summed over all three lines, not a once-per-session 750"
    )


def test_every_allocation_line_is_charged_including_unshipped_sets(api):
    """PRD §3.4: "Every allocation line is charged, including lines whose card
    set is merely approved and has not shipped, and including lines whose set
    later ships."

    Design: Corner/calculations/signer_royalty_charge_sums_over_every_allocation_line
    """
    license_obj, line, sets, session = _three_set_session(api)
    advance_clock(api, session["ship_date"])
    shipped = validate_success(api.ship_signing_stock(session["id"], SC))
    per_line = [
        SIGNER_ROYALTY_CENTS * line_item["quantity_delivered"]
        for line_item in shipped["allocation_lines"]
    ]
    assert sorted(per_line) == [7500, 15000, 22500]
    assert sum(per_line) == shipped["autograph_royalty_cents"]


def test_shipping_secures_the_autograph_count_on_every_referenced_set(api):
    """PRD §3.4: "The shipping transition also recomputes
    `autograph_secured_count` and `autograph_planned_count` on every referenced
    card set, and recomputes `total_allocated_count` on the session as the sum
    of `quantity_delivered` across its lines."

    Design: Corner/calculations/signer_royalty_charge_sums_over_every_allocation_line
    """
    license_obj, line, sets, session = _three_set_session(api)
    advance_clock(api, session["ship_date"])
    validate_success(api.ship_signing_stock(session["id"], SC))
    for card_set, expected in zip(sets, (20, 30, 10)):
        read = validate_success(api.get_card_set(card_set["id"], PM))
        assert read["autograph_secured_count"] == expected
        assert read["autograph_planned_count"] == 200


def test_shipping_a_session_reaches_the_licence_version(api):
    """PRD §3.4: "It reaches the license as well: the license's `version`
    advances by one and its `set_count` and `approved_set_count` are
    recomputed."

    Design: Corner/calculations/signer_royalty_charge_sums_over_every_allocation_line
    """
    license_obj, line, sets, session = _three_set_session(api)
    before = validate_success(api.get_license(license_obj["id"], LM))
    advance_clock(api, session["ship_date"])
    validate_success(api.ship_signing_stock(session["id"], SC))
    after = validate_success(api.get_license(license_obj["id"], LM))
    assert after["version"] == before["version"] + 1
    assert after["set_count"] == 3
    assert after["approved_set_count"] == 3


def test_a_single_line_session_charges_only_that_line(api):
    """PRD §3.4: "the session's royalty total is the sum of those per-line
    charges, recorded on the session."

    Design: Corner/calculations/signer_royalty_charge_sums_over_every_allocation_line
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = _approve(
        api, license_obj["id"], line["id"], "Flagship Base", "BASE", 500,
        autograph_planned_count=200,
    )
    session = get_success_data(
        api.create_signing_session(
            {
                "signer_name": "Ken Griffey Jr",
                "signer_kind": "PLAYER_ASSOCIATION",
                "license_id": license_obj["id"],
                "scheduled_on": "2026-10-05T00:00:00Z",
                "allocation_lines": [
                    {"card_set_id": card_set["id"], "player_id": "kgj", "quantity_delivered": 7}
                ],
            },
            SC,
        )
    )
    validate_success(api.prepare_signing_stock(session["id"], SC))
    advance_clock(api, session["ship_date"])
    shipped = validate_success(api.ship_signing_stock(session["id"], SC))
    assert shipped["autograph_royalty_cents"] == 750 * 7 == 5250


# ---------------------------------------------------------------------------
# tier_snap_aggregate — degenerate zero cases
# ---------------------------------------------------------------------------
def test_a_line_with_no_card_sets_reports_zero_allocated_cards(api):
    """PRD §3.8: "Every card set under the line participates in this total
    regardless of its status, because the line's producible total is what each
    set *will* run; a set whose quantity is 0 contributes 0."

    Design: Corner/calculations/available_cards_never_drop_below_zero_on_a_set
    """
    license_obj = create_active_license(api)
    line = create_product_line_raw(api, license_obj["id"])
    read = validate_success(api.get_product_line(line["id"], PM))
    assert_product_line(read)
    assert read["allocated_cards"] == 0, "the empty aggregation has a defined zero case"
    assert read["allocated_cards"] is not None
    assert read["sets_per_case"] == 2000


def test_the_empty_line_nested_collection_reports_zero_rows(api):
    """PRD §2.3: "Responses to list endpoints carry the pagination fields in
    the `meta` object of the envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/calculations/available_cards_never_drop_below_zero_on_a_set
    """
    license_obj = create_active_license(api)
    line = create_product_line_raw(api, license_obj["id"])
    rows, meta = validate_paginated(api.list_line_card_sets(line["id"], PM))
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_a_set_with_no_claims_reports_a_zero_claim_count(api):
    """PRD §3.7: "computes its `claim_weight` from the severity — `SEVERITY_WEIGHT_MINOR` of 1 for `MINOR`, `SEVERITY_WEIGHT_MAJOR` of 2 for `MAJOR` and `SEVERITY_WEIGHT_CRITICAL` of 3 for `CRITICAL`, with the `severity` enum closed and every value weighted — and recomputes `quality_claim_count` on the set."

    Design: Corner/calculations/available_cards_never_drop_below_zero_on_a_set
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    read = validate_success(api.get_card_set(card_set["id"], QA))
    assert read["quality_claim_count"] == 0, "no claims means an exact zero, not null"
    assert read["settled_complaint_count"] == 0
    assert read["autograph_redemptions_outstanding"] == 0


def test_an_empty_line_still_accepts_a_reservation(api):
    """PRD §3.8: "If that projected number of sets is strictly greater than the
    capacity, the reservation is refused with
    `ERR_ALLOCATION_EXCEEDS_PRINT_RUN`."

    Design: Corner/calculations/available_cards_never_drop_below_zero_on_a_set
    """
    license_obj = create_active_license(api)
    line = create_product_line_raw(api, license_obj["id"])
    allocation = validate_success(
        api.create_allocation(
            {
                "product_line_id": line["id"],
                "channel": "HOBBY",
                "quantity_allocated": 50,
                "effective_price_cents": 72000,
            },
            DIST,
        ),
        expected_status=201,
    )
    assert allocation["status"] == "RESERVED"
    assert allocation["shipped_quantity"] == 0