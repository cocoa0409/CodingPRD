"""Endpoint-level shapes and the error identity each failing route reports: path
scoping, clock stamping, tier pricing, the empty scorecard, and seven distinct
error ids reached one at a time."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_instant_equals,
    assert_ledger_batch_balanced,
    assert_ledger_rows,
    assert_unpaginated_meta,
    validate_unpaginated,
)
from test_helpers.constants import CLOCK_DEFAULT, MECHANICAL_POLICY
from test_helpers.factories import (
    build_negotiation_world,
    build_sale_world,
    build_under_review_world,
    case_payload,
    create_announcement,
    create_buyer,
    create_policy,
    create_sale,
    create_seller,
    inspection_payload,
    policy_payload,
    set_clock,
    settle_sale,
)
from test_helpers.test_users import (
    admin_headers,
    buyer_rep_headers,
    headers_blank_user_id,
    inspector_headers,
    seller_rep_headers,
)


def test_an_announcement_belongs_only_to_the_sale_it_was_posted_against(api):
    """The owning sale comes from the path, so the sibling sale's disclosure record
    stays empty, and the disclosure instant is the logical clock.

    PRD: "The row records its `sale_id` from the path it was posted against and an
    `announced_at_utc` taken from the logical clock, and it is immutable thereafter —
    announcements carry no `updated_at` and no `version`."

    Design: Corner/endpoints/an_announcement_is_scoped_to_the_sale_it_was_filed_against
    """
    world = build_sale_world(api, [MECHANICAL_POLICY])
    sale_b = create_sale(
        api,
        world["seller"]["id"],
        world["buyer"]["id"],
        sale_price_cents=900000,
        announced_odometer_miles=61000,
    )

    announcement = create_announcement(
        api,
        world["sale"]["id"],
        "FRAME_DAMAGE",
        disclosure_text="Repaired left frame rail, documented",
    )

    assert announcement["sale_id"] == world["sale"]["id"]
    assert announcement["defect_class"] == "FRAME_DAMAGE"
    assert_instant_equals(
        announcement["announced_at_utc"], CLOCK_DEFAULT, "announced_at_utc"
    )
    assert "version" not in announcement
    assert "updated_at" not in announcement

    rows_a, meta_a = validate_unpaginated(
        api.list_announcements(world["sale"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta_a, 1)
    rows_b, meta_b = validate_unpaginated(api.list_announcements(sale_b["id"], admin_headers()))
    assert_unpaginated_meta(meta_b, 0)
    assert rows_b == []
    assert rows_a[0]["id"] == announcement["id"]


def test_releasing_proceeds_stamps_the_clock_and_posts_one_balanced_pair(api):
    """The settlement instant is the clock at release time rather than the hammer
    time, and the money moves as exactly one balanced pair.

    PRD: "Releasing proceeds is an `AuctionAdmin` action that advances
    `settlement_status` `UNSETTLED → SETTLED` and stamps `settled_at_utc` with the
    current logical clock."

    Design: Corner/endpoints/settle_posts_the_balanced_proceeds_pair_and_stamps_the_logical_clock
    """
    world = build_sale_world(api, [MECHANICAL_POLICY])
    release_time = "2026-08-02T06:00:00.000Z"
    set_clock(api, release_time)

    settled = settle_sale(api, world["sale"]["id"])

    assert settled["settlement_status"] == "SETTLED"
    assert_instant_equals(settled["settled_at_utc"], release_time, "settled_at_utc")
    assert settled["version"] == 2
    assert settled["settlement_hold"] is False

    entries, meta = validate_unpaginated(
        api.list_sale_ledger_entries(world["sale"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 2)
    assert_ledger_batch_balanced(entries, "the proceeds pair")
    assert_ledger_rows(
        entries,
        [
            {"party": "SELLER", "entry_type": "SALE_PROCEEDS", "amount_signed_cents": 1450000},
            {"party": "BUYER", "entry_type": "SALE_PROCEEDS", "amount_signed_cents": -1450000},
        ],
    )


def test_a_standard_inspection_costs_12500_and_opens_a_seventy_two_hour_window(api):
    """Both the fee and the window end are derived from the tier and the clock alone,
    with no client input beyond the tier name.

    PRD: "The tier selects the fee: `fee_cents` is 12500 for a `STANDARD` programme
    and 27500 for a `PREMIUM` one. The new row records `requested_at_utc` from the
    logical clock, computes `window_end_utc` as 72 hours (three days) after
    `requested_at_utc`, sets `status` to `REQUESTED`, leaves `completed_at_utc` null
    and `findings` as the empty array."

    Design: Corner/endpoints/a_standard_inspection_request_is_priced_at_12500_and_opens_a_72_hour_window
    """
    world = build_sale_world(api, [MECHANICAL_POLICY])
    requested_at = "2026-08-01T09:30:00.000Z"
    set_clock(api, requested_at)

    inspection = validate_success(
        api.create_inspection(
            inspection_payload(world["sale"]["id"], "STANDARD"),
            buyer_rep_headers(world["buyer"]["id"]),
        ),
        201,
    )

    assert inspection["status"] == "REQUESTED"
    assert inspection["fee_cents"] == 12500
    assert_instant_equals(inspection["requested_at_utc"], requested_at, "requested_at_utc")
    assert_instant_equals(
        inspection["window_end_utc"], "2026-08-04T09:30:00.000Z", "window_end_utc"
    )
    assert inspection["findings"] == []
    assert inspection["completed_at_utc"] is None

    rows, meta = validate_unpaginated(
        api.list_sale_inspections(world["sale"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert rows[0]["program_tier"] == "STANDARD"


def test_a_consignor_with_no_sales_reads_a_scorecard_of_zeros(api):
    """With no sales at all the rate short-circuits to zero instead of dividing by
    zero, and the sample floor keeps the tier where it started.

    PRD: "Each variant's rate is then 0 when its sales count is 0, and otherwise
    10000 multiplied by the upheld count, divided by the sales count, rounded half up
    to a whole number of basis points"

    Design: Corner/endpoints/a_seller_scorecard_with_no_sales_reads_all_zeros
    """
    seller = create_seller(api)

    scorecard = validate_success(
        api.get_seller_scorecard(seller["id"], seller_rep_headers(seller["id"])), 200
    )

    assert scorecard["seller_id"] == seller["id"]
    assert scorecard["policy_tier"] == "GOOD_STANDING"
    assert scorecard["rolling_window_sales_count"] == 0
    assert scorecard["rolling_window_upheld_count"] == 0
    assert scorecard["rolling_arbitration_rate_bps"] == 0
    assert scorecard["lifetime_sales_count"] == 0
    assert scorecard["lifetime_upheld_count"] == 0
    assert scorecard["lifetime_arbitration_rate_bps"] == 0
    assert_instant_equals(scorecard["computed_at_utc"], CLOCK_DEFAULT, "computed_at_utc")


def test_a_blank_identity_header_is_unauthenticated_before_any_lookup(api):
    """The identity check precedes resolution of the addressed row, so a real seller
    id still answers 401 rather than 200.

    PRD: "If `X-User-Role` is absent or blank, the request fails with
    `ERR_UNAUTHENTICATED` (HTTP 401); the same code and status apply when `X-User-ID`
    is absent or blank."

    Design: Corner/errors/a_blank_user_id_header_returns_unauthenticated
    """
    seller = create_seller(api)

    response = api.get_seller(seller["id"], headers_blank_user_id())

    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert response.status_code == 401
    assert isinstance(error["message"], str)
    assert error["message"] != ""
    body = response.json()
    assert body["meta"]["api_request_id"].startswith("req_")


def test_countering_an_unknown_round_under_a_real_case_names_the_round(api):
    """The case segment resolved, so the second path segment is the one that fails and
    the standing offer is left exactly as it was.

    PRD: "A round identifier in the path resolves to a `NegotiationRound` whose
    `case_id` equals the path's case — else `ERR_ROUND_NOT_FOUND`. This guards
    countering and accepting."

    Design: Corner/errors/counter_on_an_unknown_round_id_returns_round_not_found
    """
    world = build_negotiation_world(
        api, seller_offer_cents=100000, policy_presets=[MECHANICAL_POLICY]
    )

    response = api.counter_round(
        world["case"]["id"],
        NON_EXISTENT_UUID,
        {
            "buyer_demand_cents": 200000,
            "counter_note": "Estimate is higher than the offer",
        },
        buyer_rep_headers(world["buyer"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ROUND_NOT_FOUND.value)
    assert response.status_code == 404

    rounds, meta = validate_unpaginated(
        api.list_negotiation_rounds(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)
    assert rounds[0]["status"] == "OPEN"
    assert rounds[0]["buyer_demand_cents"] is None


def test_completing_an_inspection_that_does_not_exist_names_the_inspection(api):
    """The path lookup runs ahead of the status gate, so the answer is a 404 rather
    than the 409 a wrong-status row would produce.

    PRD: "An inspection identifier in the path resolves to a `PostSaleInspection` —
    else `ERR_INSPECTION_NOT_FOUND`. This guards inspection completion."

    Design: Corner/errors/completing_an_unknown_inspection_returns_inspection_not_found
    """
    response = api.complete_inspection(
        NON_EXISTENT_UUID, {"findings": ["MECHANICAL"]}, inspector_headers()
    )

    validate_error(response, ApiErrorId.ERR_INSPECTION_NOT_FOUND.value)
    assert response.status_code == 404


def test_a_claim_for_an_unpublished_family_reports_a_missing_policy(api):
    """The defect family is a legal enum member; what is missing is the published
    policy that would govern it, and nothing is written.

    PRD: "Exactly one policy must govern the claimed family, or
    `ERR_POLICY_NOT_FOUND`."

    Design: Corner/errors/a_claim_for_a_defect_class_with_no_policy_returns_policy_not_found
    """
    world = build_sale_world(api, [MECHANICAL_POLICY], light_channel="YELLOW")

    response = api.create_case(
        case_payload(
            world["sale"]["id"],
            defect_class="FRAME_DAMAGE",
            claim_amount_cents=60000,
            odometer_at_claim=84100,
            complaint_text="Cut and welded frame rail",
        ),
        buyer_rep_headers(world["buyer"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_POLICY_NOT_FOUND.value)
    assert response.status_code == 404

    sale = validate_success(api.get_sale(world["sale"]["id"], admin_headers()), 200)
    assert sale["open_case_count"] == 0
    assert sale["arbitration_status"] == "NONE"


def test_paying_a_fee_for_an_unknown_bidder_answers_before_the_version_check(api):
    """A deliberately wrong expected version cannot turn this into a stale-version
    failure, because the addressed row does not exist to compare against.

    PRD: "A buyer identifier in the path resolves to a `Buyer` — else
    `ERR_BUYER_NOT_FOUND`. This guards fee payment, buyer reads and the buyer's
    frivolous-fee list."

    Design: Corner/errors/a_fee_payment_against_an_unknown_buyer_returns_buyer_not_found
    """
    buyer = create_buyer(api)

    response = api.pay_buyer_fee(
        NON_EXISTENT_UUID,
        {"amount_cents": 1000, "expected_buyer_version": 99},
        buyer_rep_headers(buyer["id"]),
    )

    validate_error(response, ApiErrorId.ERR_BUYER_NOT_FOUND.value)
    assert response.status_code == 404

    stored = validate_success(api.get_buyer(buyer["id"], admin_headers()), 200)
    assert stored["frivolous_fee_balance_cents"] == 0
    assert stored["version"] == 1


def test_a_second_policy_for_a_family_that_already_has_one_is_refused(api):
    """The defect family is the policy's natural key, so entirely different numbers do
    not buy a second row, and the incumbent is untouched.

    PRD: "exactly one policy may exist per family: a second publication for a
    `defect_class` that already has a policy is refused with
    `ERR_DUPLICATE_POLICY_DEFECT_CLASS`."

    Design: Corner/errors/a_second_policy_for_the_same_defect_class_is_rejected
    """
    policy = create_policy(api, MECHANICAL_POLICY)

    response = api.create_policy(
        policy_payload(
            MECHANICAL_POLICY,
            window_hours=96,
            mileage_limit=500,
            min_claim_amount_cents=10000,
            requires_third_party_verification=True,
            max_allowance_bps=5000,
            psi_extension_hours=0,
            psi_clean_waives_rights=False,
        ),
        admin_headers(),
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_POLICY_DEFECT_CLASS.value)
    assert response.status_code == 409

    stored = validate_success(api.get_policy(policy["id"], admin_headers()), 200)
    assert stored["window_hours"] == 48
    assert stored["max_allowance_bps"] == 2000
    assert stored["version"] == 1


def test_an_offer_one_cent_over_the_cap_is_refused_and_the_cap_itself_opens_a_round(api):
    """The ceiling is 2000 bps of the 1450000 sale price rather than anything drawn
    from the repair estimate, and it includes its own endpoint.

    PRD: "the cap is the sale's `sale_price_cents` multiplied by the policy's
    `max_allowance_bps`, divided by 10000 and rounded half up to whole cents, and an
    offer above that cap is refused with `ERR_ALLOWANCE_EXCEEDS_CAP`."

    Design: Corner/errors/a_seller_offer_one_cent_over_the_cap_is_rejected_and_the_cap_itself_is_accepted
    """
    world = build_under_review_world(api, [MECHANICAL_POLICY])
    headers = seller_rep_headers(world["seller"]["id"])

    over = api.seller_response(
        world["case"]["id"],
        {
            "response_type": "OFFER_REPAIR_ALLOWANCE",
            "response_note": "Full policy limit plus a cent",
            "seller_offer_cents": 290001,
        },
        headers,
    )
    validate_error(over, ApiErrorId.ERR_ALLOWANCE_EXCEEDS_CAP.value)
    assert over.status_code == 422

    at_cap = validate_success(
        api.seller_response(
            world["case"]["id"],
            {
                "response_type": "OFFER_REPAIR_ALLOWANCE",
                "response_note": "Full policy limit",
                "seller_offer_cents": 290000,
            },
            headers,
        ),
        201,
    )
    assert at_cap["status"] == "OPEN"
    assert at_cap["seller_offer_cents"] == 290000

    rounds, meta = validate_unpaginated(
        api.list_negotiation_rounds(world["case"]["id"], admin_headers())
    )
    assert_unpaginated_meta(meta, 1)

    case = validate_success(api.get_case(world["case"]["id"], admin_headers()), 200)
    assert case["status"] == "NEGOTIATION"
    assert case["current_round_index"] == 1
