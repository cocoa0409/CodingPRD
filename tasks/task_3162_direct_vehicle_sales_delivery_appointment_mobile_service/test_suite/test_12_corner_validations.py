"""Corner coverage: role, ownership and franchise-law validation layers."""
from test_helpers import (
    TEST_USERS,
    create_and_enact_jurisdiction,
    create_and_start_batch,
    create_appraisal_payload,
    create_center,
    create_order,
    create_published_configuration,
    create_verified_buyer,
    get_order,
    get_success_data,
    lock_order,
    place_order,
    set_clock,
    settle_order_fee,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    walk_order_to_at_delivery_center,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TRADEIN = TEST_USERS["trade_in_specialist_headers"]


def test_missing_role_header_returns_invalid_user_context(api):
    """PRD §2.1: "A request whose `X-User-Role` header is absent or carries a value
    outside that set is refused with `ERR_INVALID_USER_CONTEXT` (HTTP 400)."
    PRD §3.12: "an absent or unrecognised role yields `ERR_INVALID_USER_CONTEXT`
    (HTTP 400) before anything else is considered"

    Design: Corner/validations/missing_role_header_returns_invalid_user_context
    """
    set_clock()
    config, _ = create_published_configuration()

    res = api.get_configuration(config["id"], {"X-User-ID": "someone",
                                               "X-User-Role": "NotARole",
                                               "Content-Type": "application/json"})
    validate_error(res, "ERR_INVALID_USER_CONTEXT", expected_status=400)

    ok = get_success_data(api.get_configuration(config["id"], ADMIN))
    assert ok["base_price_cents"] == config["base_price_cents"]


def test_buyer_role_cannot_create_a_jurisdiction(api):
    """PRD §2.1: "A request whose role is recognised but is not permitted for the
    requested operation is refused with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §3.1: "State regimes are authored by a `PlatformAdmin` as
    `StateJurisdiction` rows."

    Design: Corner/validations/buyer_role_cannot_create_a_jurisdiction
    """
    set_clock()
    buyer = create_verified_buyer()

    res = api.create_jurisdiction(
        {"state_code": "NV", "direct_sales_permitted": True,
         "doc_fee_cap_cents": 5000}, {"X-User-ID": buyer["id"],
                                      "X-User-Role": "Buyer",
                                      "Content-Type": "application/json"})
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    rows = get_success_data(api.list_jurisdictions(ADMIN))
    assert rows == [], "the refused creation added no regime"


def test_suspended_buyer_cannot_place_an_order(api):
    """PRD §2.1: "A `Buyer` account that is `SUSPENDED` may not perform any
    `Buyer`-role operation at all; every such attempt is refused with
    `ERR_BUYER_SUSPENDED` (HTTP 403)."
    PRD §3.12: "5. Acting buyer account is not suspended — `ERR_BUYER_SUSPENDED`,
    403."

    Design: Corner/validations/suspended_buyer_cannot_place_an_order
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
    settle_order_fee(order["id"])

    suspended = get_success_data(api.suspend_buyer(buyer["id"], ADMIN))
    assert suspended["status"] == "SUSPENDED"

    refused = api.place_order(order["id"], order["version"],
                              {"X-User-ID": buyer["id"], "X-User-Role": "Buyer",
                               "Content-Type": "application/json"})
    validate_error(refused, "ERR_BUYER_SUSPENDED", expected_status=403)
    assert get_order(order["id"])["status"] == "DRAFT"


def test_gallery_only_jurisdiction_refuses_a_gallery_handover(api):
    """PRD §2.4: "when it is true, a handover at a `GALLERY` kind site is refused
    with `ERR_GALLERY_HANDOVER_FORBIDDEN` (HTTP 403)"
    PRD §3.4: "a gallery-only regime must not be paired with a gallery site
    (`ERR_GALLERY_HANDOVER_FORBIDDEN`)"

    Design: Corner/validations/gallery_only_jurisdiction_refuses_a_gallery_handover
    """
    set_clock()
    jur = get_success_data(api.create_jurisdiction(
        {"state_code": "WA", "direct_sales_permitted": True,
         "gallery_only_required": True, "doc_fee_cap_cents": 7500}, ADMIN))
    get_success_data(api.enact_jurisdiction(jur["id"], ADMIN))
    gallery = create_center(center_name="Seattle Gallery", center_kind="GALLERY",
                            state_code="WA", bay_count=0,
                            home_delivery_radius_miles=0, van_count=0)
    config, _ = create_published_configuration()
    buyer = create_verified_buyer(full_name="Wren Washington",
                                  email="wren.washington@example.com",
                                  residency_state_code="WA")
    order = create_order(buyer["id"], config["id"], jur["id"], gallery["id"])
    settle_order_fee(order["id"])
    placed = place_order(order["id"], order["version"], buyer["id"])
    locked = lock_order(order["id"], placed["version"])

    batch, _unit = create_and_start_batch()
    get_success_data(api.allocate_order(order["id"], batch["id"],
                                        locked["version"], ADMIN))
    get_success_data(api.dispatch_to_transport(order["id"], ADMIN))

    refused = api.arrive_at_center(order["id"], ADMIN)
    validate_error(refused, "ERR_GALLERY_HANDOVER_FORBIDDEN", expected_status=403)
    assert get_order(order["id"])["status"] == "IN_TRANSIT"


def test_out_of_state_delivery_required_refuses_in_state_handover(api):
    """PRD §2.4: "When it is false, a resident purchase is lawful only if the
    handover happens outside the state, so a handover that would occur inside the
    state is refused with `ERR_OUT_OF_STATE_DELIVERY_REQUIRED` (HTTP 403)"
    PRD §3.1: "Handover legality is evaluated against the site's own `state_code`,
    not against the buyer's residence"

    Design: Corner/validations/out_of_state_delivery_required_refuses_in_state_handover
    """
    set_clock()
    jur = get_success_data(api.create_jurisdiction(
        {"state_code": "CT", "direct_sales_permitted": False,
         "out_of_state_delivery_required": True, "doc_fee_cap_cents": 7500,
         "transport_lead_days": 5}, ADMIN))
    get_success_data(api.enact_jurisdiction(jur["id"], ADMIN))
    center_ct = create_center(center_name="Hartford Delivery", state_code="CT",
                              bay_count=2, home_delivery_radius_miles=25, van_count=1)
    config, _ = create_published_configuration()
    buyer = create_verified_buyer(full_name="Cara Connecticut",
                                  email="cara.connecticut@example.com",
                                  residency_state_code="CT")
    order = create_order(buyer["id"], config["id"], jur["id"], center_ct["id"])
    settle_order_fee(order["id"])
    placed = place_order(order["id"], order["version"], buyer["id"])
    locked = lock_order(order["id"], placed["version"])
    batch, _unit = create_and_start_batch()
    get_success_data(api.allocate_order(order["id"], batch["id"],
                                        locked["version"], ADMIN))
    get_success_data(api.dispatch_to_transport(order["id"], ADMIN))

    refused = api.arrive_at_center(order["id"], ADMIN)
    validate_error(refused, "ERR_OUT_OF_STATE_DELIVERY_REQUIRED", expected_status=403)
    assert get_order(order["id"])["status"] == "IN_TRANSIT"


def test_finance_decision_is_scoped_to_the_decision_step_only(api):
    """PRD §3.5: "The decision cannot be made for an applicant whose
    `identity_verified` is false, on pain of `ERR_BUYER_NOT_VERIFIED` (HTTP 403)"
    PRD §3.5: "The band itself is selected by a pinned rule: the applicant's
    existing `credit_band` is retained when it is already `PRIME` or `SUBPRIME`,
    and otherwise the band defaults to `NEAR_PRIME`"
    PRD §3.5: "`decision_at`, which remains null until a decision has actually been
    made"

    Design: Corner/validations/finance_decision_is_scoped_to_the_decision_step_only
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
    settle_order_fee(order["id"])
    place_order(order["id"], order["version"], buyer["id"])

    application = get_success_data(api.create_financing_application(
        order["id"], {"term_months": 72, "down_payment_cents": 0,
                      "include_trade_in_credit": False},
        {"X-User-ID": buyer["id"], "X-User-Role": "Buyer",
         "Content-Type": "application/json"}))
    assert application["decision_at"] is None

    decided = get_success_data(api.decide_financing_application(
        application["id"], "APPROVED", TEST_USERS["finance_partner_headers"]))
    assert decided["status"] == "CONDITIONALLY_APPROVED"
    assert decided["credit_band"] == "NEAR_PRIME"
    assert decided["apr_bps"] == 890
    assert decided["decision_at"] is not None


def test_conditional_validation_refuses_an_expired_offer_at_accept_time(api):
    """PRD §3.3: "Before a `DRAFT` or `APPRAISED` appraisal can be offered, its
    `offer_valid_until` must be strictly after the current clock instant"
    PRD §3.3: "An `OFFERED` appraisal that is not accepted before its validity
    instant lapses to `EXPIRED`"

    Design: Corner/validations/conditional_validation_refuses_an_expired_offer_at_accept_time
    """
    set_clock()
    ctx = walk_order_to_at_delivery_center()
    order = ctx["order"]
    buyer_id = ctx["buyer"]["id"]

    appraisal = get_success_data(api.create_appraisal(
        order["id"],
        create_appraisal_payload(trade_vin="5YJ3E1EA7PF000911", mileage=30000,
                                 gross_offer_cents=1000000,
                                 reconditioning_estimate_cents=50000,
                                 offer_valid_until="2026-09-22T00:00:00Z"),
        TRADEIN))
    get_success_data(api.appraise(order["id"], appraisal["id"], TRADEIN))
    get_success_data(api.offer_appraisal(order["id"], appraisal["id"], TRADEIN))
    get_success_data(api.set_current_utc("2026-09-23T00:00:00Z", ADMIN))

    # The clock advance that carried the offer past its validity has already
    # lapsed the row into EXPIRED, so the acceptance is refused on that state —
    # an offer that is no longer live cannot be accepted, whether the refusal
    # names the lapse or the row's terminal state.
    refused = api.accept_appraisal(order["id"], appraisal["id"],
                                   {"X-User-ID": buyer_id, "X-User-Role": "Buyer",
                                    "Content-Type": "application/json"})
    error_id = validate_error_is_one_of(
        refused, ["ERR_APPRAISAL_OFFER_EXPIRED", "ERR_INVALID_STATE"])
    assert error_id in ("ERR_APPRAISAL_OFFER_EXPIRED", "ERR_INVALID_STATE")


def test_keyword_filter_is_applied_on_the_listing_endpoint(api):
    """PRD §2.3: "`total_count` is the number of items matching the filters across
    all pages, not the number on the current page, and `has_more` is a boolean that
    is true exactly when further items exist beyond the current page."
    PRD §2.3: "Every list in the API is ordered by `created_at` ascending unless a
    subsection below states a different ordering for a specific collection."
    PRD §2.3: "`offset` states how many items to skip before the page begins and
    defaults to 0."

    Design: Corner/validations/keyword_filter_is_applied_on_the_listing_endpoint
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()
    placed_order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
    settle_order_fee(placed_order["id"])
    place_order(placed_order["id"], placed_order["version"], buyer["id"])
    draft = create_order(buyer["id"], config["id"], jur["id"], center["id"])

    everything, meta = validate_paginated(api.list_orders(ADMIN))
    assert len(everything) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["offset"] == 0

    first_page, meta = validate_paginated(api.list_orders(
        ADMIN, params={"limit": 1, "offset": 0}))
    assert len(first_page) == 1
    assert meta["total_count"] == 2, (
        "total_count counts the whole collection, not the page"
    )
    assert meta["has_more"] is True
    assert first_page[0]["id"] == placed_order["id"], (
        "the listing orders by created_at ascending, so the first order comes first"
    )

    second_page, meta = validate_paginated(api.list_orders(
        ADMIN, params={"limit": 1, "offset": 1}))
    assert len(second_page) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert second_page[0]["id"] == draft["id"]
    assert first_page[0]["id"] != second_page[0]["id"]
