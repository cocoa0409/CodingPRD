"""Sale events: slot guards, close semantics, the tiered auction fee, the
proceeds waterfall, and the dismissal cascades that reach sale events."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_isr,
    assert_case_pool_invariants,
    assert_sale_event,
    close_sale_event,
    create_case,
    create_case_in_state,
    create_isr,
    create_sale_event_payload,
    create_sell_authorized_asset,
    create_settled_sale,
    create_valued_asset,
    dismiss_case,
    get_asset,
    get_case,
    post_expense,
    schedule_sale_event,
    set_clock,
    settle_sale_event,
    validate_created,
    validate_error,
    validate_paginated,
)


def test_bid_equal_reserve_settles_forward(api):
    """PRD §3.6: "A winning bid at or above the reserve moves the event to
    `CLOSED_PENDING_SETTLEMENT` and sets `gross_proceeds_cents` to the
    winning bid. A winning bid below the reserve moves the event to `NO_SALE`
    with `gross_proceeds_cents` of zero; the asset remains `SALE_AUTHORIZED`
    and may be re-listed by scheduling a fresh sale event."

    Design: Difficulty/boundary_precision_check/bid_equal_reserve_settles_forward
    """
    case = create_case_in_state(
        "FORFEITED", case_number="26-MJ-0012", judicial_district="D. Nev.",
        forfeiture_type="CIVIL", lead_agency_code="DEA",
    )
    asset_g = create_sell_authorized_asset(
        case["id"], raw_value_cents=800_000, grade="EXCELLENT",
        description="coupe G",
    )
    event_g = schedule_sale_event(
        asset_g["id"], reserve_price_cents=800_000, auctioneer_ref="auc-8",
        slot_start="2026-09-06T10:00:00Z", slot_end="2026-09-06T12:00:00Z",
    )
    asset_h = create_sell_authorized_asset(
        case["id"], raw_value_cents=800_000, grade="EXCELLENT",
        description="coupe H",
    )
    event_h = schedule_sale_event(
        asset_h["id"], reserve_price_cents=800_000, auctioneer_ref="auc-8",
        slot_start="2026-09-06T13:00:00Z", slot_end="2026-09-06T15:00:00Z",
    )

    sold = close_sale_event(event_g["id"], 800_000)
    assert sold["status"] == "CLOSED_PENDING_SETTLEMENT"
    assert sold["gross_proceeds_cents"] == 800_000, "bid == reserve sells"

    unsold = close_sale_event(event_h["id"], 799_999)
    assert unsold["status"] == "NO_SALE"
    assert unsold["gross_proceeds_cents"] == 0, (
        "bid == reserve - 1 does not sell"
    )

    assert get_asset(asset_g["id"])["legal_state"] == "SALE_AUTHORIZED", (
        "the legal track advances to SOLD only at settle"
    )
    assert get_asset(asset_h["id"])["legal_state"] == "SALE_AUTHORIZED", (
        "a NO_SALE asset remains re-listable"
    )


def test_auction_slot_half_open_overlap(api):
    """PRD §3.6: "the slot must not overlap any non-`CANCELLED` slot
    belonging to the same `auctioneer_ref`, where half-open intervals that
    merely touch — one event's `slot_end` equal to the other's `slot_start`
    — do not conflict (`ERR_AUCTION_SLOT_CONFLICT`)."

    Design: Difficulty/resource_temporal_overlap/auction_slot_half_open_overlap
    """
    case = create_case_in_state(
        "FORFEITED", case_number="26-MJ-0016", judicial_district="D. Minn.",
        forfeiture_type="CIVIL", lead_agency_code="USMS",
    )
    asset_a1 = create_sell_authorized_asset(
        case["id"], raw_value_cents=700_000, grade="EXCELLENT",
        description="sedan A1",
    )
    asset_a2 = create_sell_authorized_asset(
        case["id"], raw_value_cents=700_000, grade="EXCELLENT",
        description="sedan A2",
    )
    asset_a3 = create_sell_authorized_asset(
        case["id"], raw_value_cents=700_000, grade="EXCELLENT",
        description="sedan A3",
    )
    schedule_sale_event(
        asset_a1["id"], reserve_price_cents=700_000, auctioneer_ref="auc-9",
        slot_start="2026-09-20T10:00:00Z", slot_end="2026-09-20T12:00:00Z",
    )
    adjacent = validate_created(
        api.create_sale_event(
            create_sale_event_payload(
                asset_a2["id"], sale_method="PUBLIC_AUCTION",
                auctioneer_ref="auc-9", slot_start="2026-09-20T12:00:00Z",
                slot_end="2026-09-20T14:00:00Z", reserve_price_cents=700_000,
            ),
            TEST_USERS["auction_coordinator_headers"],
        )
    )
    assert_sale_event(adjacent)
    assert adjacent["status"] == "OPEN_FOR_BIDS", (
        "adjacency [12:00,14:00) after [10:00,12:00) is not an overlap "
        "under half-open semantics"
    )

    straddle = api.create_sale_event(
        create_sale_event_payload(
            asset_a3["id"], sale_method="PUBLIC_AUCTION",
            auctioneer_ref="auc-9", slot_start="2026-09-20T11:00:00Z",
            slot_end="2026-09-20T13:00:00Z", reserve_price_cents=700_000,
        ),
        TEST_USERS["auction_coordinator_headers"],
    )
    validate_error(straddle, ApiErrorId.ERR_AUCTION_SLOT_CONFLICT)
    assert straddle.status_code == 409, "11:00 < 12:00 straddles the E1 slot"

    other_house = validate_created(
        api.create_sale_event(
            create_sale_event_payload(
                asset_a3["id"], sale_method="PUBLIC_AUCTION",
                auctioneer_ref="auc-7", slot_start="2026-09-20T11:00:00Z",
                slot_end="2026-09-20T13:00:00Z", reserve_price_cents=700_000,
            ),
            TEST_USERS["auction_coordinator_headers"],
        )
    )
    assert other_house["status"] == "OPEN_FOR_BIDS", (
        "the identical straddle under a different auctioneer_ref is a "
        "different resource"
    )


def test_sale_slot_constraint_beats_temporal(api):
    """PRD §2.10: "Every request is evaluated against an ordered pipeline of
    checks, and the first failure wins: the response carries the error of the
    earliest tier that fails, and later tiers are never consulted."
    PRD §2.10: "8. **Uniqueness and interval constraints**" precede
    "10. **Clock-relative rules** — a sale slot may not open in the past
    (`ERR_SLOT_IN_PAST`)".
    PRD §3.6: "the slot must not overlap any non-`CANCELLED` slot belonging
    to the same `auctioneer_ref` ... (`ERR_AUCTION_SLOT_CONFLICT`)."

    Design: Difficulty/priority_pair_validation_conflict/sale_slot_constraint_beats_temporal
    """
    case = create_case_in_state(
        "FORFEITED", case_number="26-MJ-0010", judicial_district="E.D.N.Y.",
        forfeiture_type="CIVIL", lead_agency_code="HSI",
    )
    asset_a1 = create_sell_authorized_asset(
        case["id"], raw_value_cents=900_000, grade="EXCELLENT",
        description="van one",
    )
    asset_a2 = create_sell_authorized_asset(
        case["id"], raw_value_cents=900_000, grade="EXCELLENT",
        description="van two",
    )
    schedule_sale_event(
        asset_a1["id"], reserve_price_cents=900_000, auctioneer_ref="auc-5",
        slot_start="2026-09-10T10:00:00Z", slot_end="2026-09-10T12:00:00Z",
    )
    set_clock("2026-09-10T11:00:00Z")

    # Overlaps E1 (10:30 < 12:00) AND starts before the 11:00 clock: the
    # tier-8 interval constraint must win over the tier-10 temporal rule.
    both = api.create_sale_event(
        create_sale_event_payload(
            asset_a2["id"], sale_method="PUBLIC_AUCTION",
            auctioneer_ref="auc-5", slot_start="2026-09-10T10:30:00Z",
            slot_end="2026-09-10T11:30:00Z", reserve_price_cents=900_000,
        ),
        TEST_USERS["auction_coordinator_headers"],
    )
    validate_error(both, ApiErrorId.ERR_AUCTION_SLOT_CONFLICT)
    assert both.status_code == 409

    # Disjoint from E1 but starting in the past: only the temporal rule fails.
    past = api.create_sale_event(
        create_sale_event_payload(
            asset_a2["id"], sale_method="PUBLIC_AUCTION",
            auctioneer_ref="auc-5", slot_start="2026-09-10T09:00:00Z",
            slot_end="2026-09-10T09:30:00Z", reserve_price_cents=900_000,
        ),
        TEST_USERS["auction_coordinator_headers"],
    )
    validate_error(past, ApiErrorId.ERR_SLOT_IN_PAST)
    assert past.status_code == 409


def test_sale_event_reserve_and_active_sale_rejections(api):
    """PRD §3.6: "the reserve must not exceed the asset's
    `appraised_value_cents` (`ERR_RESERVE_ABOVE_VALUE`); the asset may have
    at most one active sale — standing at `OPEN_FOR_BIDS` or
    `CLOSED_PENDING_SETTLEMENT` — at a time (`ERR_SALE_ALREADY_ACTIVE`)".

    Design: Corner/errors/sale_event_reserve_and_active_sale_rejections
    """
    case = create_case_in_state(
        "FORFEITED", case_number="26-MJ-1024", judicial_district="D. Minn.",
        forfeiture_type="CIVIL", lead_agency_code="FBI",
    )
    asset = create_sell_authorized_asset(
        case["id"], raw_value_cents=700_000, grade="EXCELLENT",
        description="hatchback",
    )

    over_reserve = api.create_sale_event(
        create_sale_event_payload(
            asset["id"], sale_method="PUBLIC_AUCTION", auctioneer_ref="auc-13",
            slot_start="2026-09-06T10:00:00Z", slot_end="2026-09-06T12:00:00Z",
            reserve_price_cents=700_001,
        ),
        TEST_USERS["auction_coordinator_headers"],
    )
    validate_error(over_reserve, ApiErrorId.ERR_RESERVE_ABOVE_VALUE)
    assert over_reserve.status_code == 422, (
        "reserve exceeds the appraised 700000 by one cent"
    )

    first = validate_created(
        api.create_sale_event(
            create_sale_event_payload(
                asset["id"], sale_method="PUBLIC_AUCTION",
                auctioneer_ref="auc-13", slot_start="2026-09-06T10:00:00Z",
                slot_end="2026-09-06T12:00:00Z", reserve_price_cents=500_000,
            ),
            TEST_USERS["auction_coordinator_headers"],
        )
    )
    assert first["status"] == "OPEN_FOR_BIDS"

    second = api.create_sale_event(
        create_sale_event_payload(
            asset["id"], sale_method="PUBLIC_AUCTION", auctioneer_ref="auc-14",
            slot_start="2026-09-09T10:00:00Z", slot_end="2026-09-09T12:00:00Z",
            reserve_price_cents=500_000,
        ),
        TEST_USERS["auction_coordinator_headers"],
    )
    validate_error(second, ApiErrorId.ERR_SALE_ALREADY_ACTIVE)
    assert second.status_code == 409, (
        "one active event per asset, even under a different auctioneer and "
        "a disjoint slot"
    )


def test_auction_fee_tiered_marginal_at_settle(api):
    """PRD §3.6: "First the auction fee is computed on a tiered marginal
    schedule applied to the gross proceeds: ten percent (1,000 basis points)
    on the first 1,000,000 cents ($10,000), seven percent (700 basis points)
    on the next 4,000,000 cents ($40,000), and four percent (400 basis
    points) on everything beyond that — each bracket's fee rounded half up to
    a whole cent and the three bracket fees then summed into
    `auction_fee_cents`. The `net_proceeds_cents` is the gross proceeds minus
    that fee."
    PRD §3.6: "`sharing_pool_gross_basis_cents` — the estimate basis that
    ignores lien and cost carve-outs — by the gross minus the fee, and
    `sharing_pool_net_basis_cents` — the canonical distributable basis — by
    the waterfall remainder"

    Design: Corner/calculations/auction_fee_tiered_marginal_at_settle
    """
    case = create_case_in_state(
        "FORFEITED", case_number="26-MJ-1017", judicial_district="S.D. Tex.",
        forfeiture_type="CRIMINAL", lead_agency_code="FBI",
    )
    asset = create_sell_authorized_asset(
        case["id"], raw_value_cents=6_500_000, grade="EXCELLENT",
        description="luxury sedan",
    )
    event = schedule_sale_event(
        asset["id"], reserve_price_cents=6_500_000, auctioneer_ref="seller-1",
        sale_method="CONTRACTED_SELLER",
        slot_start="2026-09-06T10:00:00Z", slot_end="2026-09-06T12:00:00Z",
    )
    close_sale_event(event["id"], 6_500_000)
    settled = settle_sale_event(event["id"])

    assert settled["status"] == "SETTLED"
    # 1000000 @ 10% + 4000000 @ 7% + 1500000 @ 4% = 100000 + 280000 + 60000.
    assert settled["auction_fee_cents"] == 440_000
    assert settled["net_proceeds_cents"] == 6_060_000

    final_case = get_case(case["id"])
    assert final_case["sharing_pool_gross_basis_cents"] == 6_060_000
    assert final_case["sharing_pool_net_basis_cents"] == 6_060_000, (
        "no carve-outs: the gross and net bases coincide"
    )
    assert final_case["available_proceeds_cents"] == 6_060_000
    assert_case_pool_invariants(final_case)


def test_waterfall_priority_order_partial_and_side_effects(api):
    """PRD §3.6: "Bucket one pays the asset's verified liens: every interest
    of this asset with a lien kind standing at `VERIFIED`, ordered by
    `priority_position` ascending with ties broken by `created_at` ascending,
    is paid the lesser of its claimed `amount_cents` and the funds remaining;
    each payment creates a distribution of kind `LIEN_PAYMENT` directly in
    `PAID` status with `payee_ref` set to the lien's `lienholder_name`, moves
    the lien to `SATISFIED` with `satisfied_amount_cents` recording the
    amount actually paid, and reduces the remainder."
    PRD §3.6: "Finally the asset's `legal_state` moves to `SOLD` and its
    `custody_state` to `TRANSFERRED_OUT`, and the sale event moves to
    `SETTLED`"

    Design: Corner/calculations/waterfall_priority_order_partial_and_side_effects
    """
    case = create_case_in_state(
        "FORFEITED", case_number="26-MJ-1018", judicial_district="N.D. Ohio",
        forfeiture_type="CIVIL", lead_agency_code="DEA",
    )
    result = create_settled_sale(
        case_id=case["id"], raw_value_cents=1_000_000, grade="EXCELLENT",
        asset_type="VEHICLE", description="cargo van",
        winning_bid_cents=1_000_000,
        costs=[{
            "entry_kind": "COST", "expense_type": "STORAGE",
            "amount_cents": 50_000, "incurred_on": "2026-09-02T00:00:00Z",
        }],
        # The priority-2 lien is filed FIRST; the priority-1 lien SECOND.
        liens=[
            {
                "petitioner_ref": "cl-b1", "kind": "LIEN_MORTGAGE",
                "lienholder_name": "First Bank", "amount_cents": 600_000,
                "priority_position": 2,
            },
            {
                "petitioner_ref": "cl-b2", "kind": "LIEN_TAX",
                "lienholder_name": "County Treasurer", "amount_cents": 400_000,
                "priority_position": 1,
            },
        ],
        auctioneer_ref="auc-11",
    )
    settled = result["sale_event"]
    assert settled["status"] == "SETTLED"
    assert settled["auction_fee_cents"] == 100_000
    assert settled["net_proceeds_cents"] == 900_000, (
        "the settle response itself already carries the computed figures"
    )

    interests, _ = validate_paginated(
        api.list_asset_third_party_interests(
            result["asset"]["id"], TEST_USERS["fund_administrator_headers"]
        )
    )
    by_payee = {r["lienholder_name"]: r for r in interests}
    # Priority 1 (created second) is paid in full before priority 2.
    assert by_payee["County Treasurer"]["status"] == "SATISFIED"
    assert by_payee["County Treasurer"]["satisfied_amount_cents"] == 400_000
    # Priority 2 (created first) is capped at the 900000 - 400000 remainder.
    assert by_payee["First Bank"]["status"] == "SATISFIED"
    assert by_payee["First Bank"]["satisfied_amount_cents"] == 500_000

    distributions = result["distributions"]
    assert len(distributions) == 2, (
        "two LIEN_PAYMENT rows; no COST_REIMBURSEMENT row because nothing "
        "remained for the cost bucket"
    )
    assert all(d["distribution_kind"] == "LIEN_PAYMENT" for d in distributions)
    assert all(d["status"] == "PAID" for d in distributions)
    amounts = {d["payee_ref"]: d["amount_cents"] for d in distributions}
    assert amounts == {
        "County Treasurer": 400_000,
        "First Bank": 500_000,
    }

    final_case = result["case"]
    assert final_case["lien_payments_cents"] == 900_000
    assert final_case["cost_reimbursements_cents"] == 0
    assert final_case["available_proceeds_cents"] == 0
    assert_case_pool_invariants(final_case)

    assert result["asset"]["legal_state"] == "SOLD"
    assert result["asset"]["custody_state"] == "TRANSFERRED_OUT"


def test_sharing_pool_gross_vs_net_basis(api):
    """PRD §3.6: "`sharing_pool_gross_basis_cents` — the estimate basis that
    ignores lien and cost carve-outs — by the gross minus the fee, and
    `sharing_pool_net_basis_cents` — the canonical distributable basis — by
    the waterfall remainder, so the gross basis always equals the net basis
    plus the lien payments plus the cost reimbursements. The case's
    `available_proceeds_cents` is rederived as `sharing_pool_net_basis_cents`
    minus `equitable_shares_paid_cents`."

    Design: Difficulty/dual_variant_calc/sharing_pool_gross_vs_net_basis
    """
    case = create_case_in_state(
        "FORFEITED", case_number="26-MJ-0002", judicial_district="N.D. Cal.",
        forfeiture_type="CRIMINAL", lead_agency_code="FBI",
    )
    result = create_settled_sale(
        case_id=case["id"], raw_value_cents=2_000_000, grade="EXCELLENT",
        asset_type="VEHICLE", description="armored car",
        winning_bid_cents=2_000_000,
        costs=[{
            "entry_kind": "COST", "expense_type": "SECURITY",
            "amount_cents": 100_000, "incurred_on": "2026-09-02T00:00:00Z",
        }],
        liens=[{
            "petitioner_ref": "cl-bank", "kind": "LIEN_MORTGAGE",
            "lienholder_name": "Meridian Bank", "amount_cents": 300_000,
            "priority_position": 1,
        }],
        auctioneer_ref="auc-1",
        slot_start="2026-09-05T10:00:00Z", slot_end="2026-09-05T12:00:00Z",
    )
    settled = result["sale_event"]
    assert settled["auction_fee_cents"] == 170_000
    assert settled["net_proceeds_cents"] == 1_830_000

    final_case = result["case"]
    assert final_case["sharing_pool_gross_basis_cents"] == 1_830_000, (
        "gross 2000000 - fee 170000; carve-outs ignored"
    )
    assert final_case["sharing_pool_net_basis_cents"] == 1_430_000, (
        "1830000 - 300000 lien - 100000 cost reimbursement"
    )
    assert final_case["available_proceeds_cents"] == 1_430_000
    assert final_case["lien_payments_cents"] == 300_000
    assert final_case["cost_reimbursements_cents"] == 100_000
    assert_case_pool_invariants(final_case)

    interests, _ = validate_paginated(
        api.list_asset_third_party_interests(
            result["asset"]["id"], TEST_USERS["fund_administrator_headers"]
        )
    )
    assert interests[0]["status"] == "SATISFIED"
    assert interests[0]["satisfied_amount_cents"] == 300_000


def test_case_dismiss_cascade_cancels_open_sale(api):
    """PRD §3.1: "Dismissal cascades in two links. Link 1 moves every asset
    of the case whose `legal_state` is `SEIZED`, `VALUATION_PENDING`,
    `VALUED`, `DISPOSITION_REVIEW`, or `SALE_AUTHORIZED` to `RETURN_PENDING`;
    assets already `RETAINED` are unaffected by the dismissal. Link 2, caused
    by link 1, cancels every sale event on a transitioned asset that stands
    at `OPEN_FOR_BIDS` or `CLOSED_PENDING_SETTLEMENT`, moving it to
    `CANCELLED`."

    Design: Corner/state_machines/case_dismiss_cascade_cancels_open_sale
    """
    case = create_case(
        case_number="26-MJ-1015", judicial_district="D. Utah",
        forfeiture_type="CIVIL", lead_agency_code="FBI",
    )
    asset, _valuation = create_valued_asset(
        case["id"], raw_value_cents=500_000, grade="EXCELLENT",
        method="BLUE_BOOK", description="tractor",
    )
    post_expense(
        asset["id"], 75_000, entry_kind="COST", expense_type="STORAGE",
        incurred_on="2026-09-02T00:00:00Z",
    )
    # The case is never forfeited: the asset reaches SALE_AUTHORIZED through
    # the interlocutory path (burden 150000 == 30% of 500000 qualifies).
    isr = create_isr(asset["id"], justification="at threshold")
    adjudicate_isr(isr["id"], "APPROVE")
    event = schedule_sale_event(
        asset["id"], reserve_price_cents=500_000, auctioneer_ref="auc-6",
        slot_start="2026-09-08T10:00:00Z", slot_end="2026-09-08T12:00:00Z",
    )

    dismissed = dismiss_case(case["id"])
    assert dismissed["status"] == "DISMISSED"

    after = get_asset(asset["id"])
    assert after["legal_state"] == "RETURN_PENDING", "cascade link 1"
    assert after["custody_state"] == "RELEASED_FOR_SALE", (
        "the dismiss cascade does not move the custody dimension"
    )
    events, _ = validate_paginated(
        api.list_asset_sale_events(
            asset["id"], TEST_USERS["court_official_headers"]
        )
    )
    assert events[0]["id"] == event["id"]
    assert events[0]["status"] == "CANCELLED", "cascade link 2"


def test_dismiss_forfeited_case_invalid_state(api):
    """PRD §3.1: "When a `CourtOfficial` instead dismisses the case, the move
    is from `OPEN` or `FORFEITURE_PENDING` to `DISMISSED`"
    PRD §3.1: "`FORFEITED` and `DISMISSED` are both terminal for the case"
    PRD §3.1: "When a `CourtOfficial` records the forfeiture order, the case
    moves from `FORFEITURE_PENDING` to `FORFEITED` and `forfeited_at` is
    stamped with the current logical clock time."

    Design: Corner/state_machines/dismiss_forfeited_case_invalid_state
    """
    case = create_case_in_state(
        "FORFEITED", case_number="26-MJ-1011", judicial_district="D. Nev.",
        forfeiture_type="CRIMINAL", lead_agency_code="FBI",
    )
    resp = api.dismiss_case(case["id"], TEST_USERS["court_official_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409

    after = get_case(case["id"])
    assert after["status"] == "FORFEITED"
    assert after["forfeited_at"] == "2026-09-01T00:00:00Z", (
        "the forfeiture stamp was taken at the untouched default clock"
    )
