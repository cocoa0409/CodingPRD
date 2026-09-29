"""Role-based access control on the Hotel Channel Distribution API.

Four different refusals live one beside the other in this contract and each has
its own identifier: the 401 for an absent, empty or unrecognised credential, the
403 for a recognised role that the target route does not admit, the 403 for a
channel partner acting on a channel that is not its own, and the 403 for a caller
reaching for authority the system owns. Every refusal here is paired with the
call that the admitted role makes successfully on the same route, so that the
refusal is demonstrably about the caller and not about a malformed request.
"""

from typing import Any, Callable, Dict

import pytest
import requests

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CHANNEL_OPS_ENGINEER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    REVENUE_DIRECTOR_HEADERS,
    REVENUE_MANAGER_HEADERS,
    TEST_USERS,
    ApiErrorId,
    assert_channel_ledger,
    assert_fields,
    assert_instant_equals,
    assert_inventory_day,
    assert_pace,
    assert_performance,
    assert_quoted_rate,
    assert_ranked_channel,
    assert_reservation_totals,
    assert_unchanged,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_with_undeclared_role,
    headers_without_credentials,
    headers_without_role,
    headers_without_user_id,
    make_channel_partner_headers,
    make_revenue_director_headers,
)
from test_helpers import factories, fixtures

# The two director identities the segregation-of-duties rule compares. They are
# genuinely different opaque operator identifiers, which is the whole point: the
# bar is keyed on the identifier, never on the role name.
DIRECTOR_ONE = TEST_USERS["revenue_director"]["user_id"]
DIRECTOR_TWO = TEST_USERS["revenue_director_alt"]["user_id"]

# The market the canonical OTA serves, which its bookings and quotes must name.
OTA_MARKET = fixtures.OTA_GEO_MARKET

# The fields a refused request must leave untouched on the plan it targeted.
PLAN_STABLE_FIELDS = [
    "version",
    "updated_at",
    "base_amount_cents",
    "resolved_base_amount_cents",
    "floor_amount_cents",
    "ceiling_amount_cents",
]


def _analytics_window() -> Dict[str, Any]:
    """A thirty-day stay-date window, the longest the canonical property accepts."""
    return factories.mix_params("2026-09-01", "2026-09-30")


def _surface_calls(
    api: Any, world: Dict[str, Any], mapping_id: str, headers: Dict[str, str]
) -> Dict[str, Callable[[], requests.Response]]:
    """One callable per pricing, inventory or analytics route, all as one caller.

    The repricing call deliberately carries a correct ``expected_rate_plan_version``
    so that a refusal cannot be attributed to the concurrency echo.
    """
    return {
        "rate_plan_create": lambda: api.create_rate_plan(
            world["property_id"],
            factories.rate_plan_payload(
                code="PARTNERBAR",
                rate_class="PUBLIC",
                base_amount_cents=19000,
                floor_amount_cents=15000,
                ceiling_amount_cents=30000,
            ),
            headers,
        ),
        "rate_plan_reprice": lambda: api.patch_rate_plan(
            world["rate_plan_id"],
            factories.reprice_payload(
                expected_rate_plan_version=fixtures.rate_plan_version(
                    api, world["rate_plan_id"]
                ),
                base_amount_cents=19000,
            ),
            headers,
        ),
        "inventory_day_open": lambda: api.create_inventory_day(
            world["room_type_id"],
            factories.inventory_day_payload(fixtures.STAY_DATE),
            headers,
        ),
        "restriction_place": lambda: api.create_restriction(
            factories.stop_sell_payload(
                world["room_type_id"], fixtures.STAY_DATE, fixtures.STAY_DATE
            ),
            headers,
        ),
        "mapping_create": lambda: api.create_mapping(
            factories.mapping_payload(
                world["rate_plan_id"], world["channel_id"], world["room_type_id"]
            ),
            headers,
        ),
        "quoted_rate_read": lambda: api.get_quoted_rate(
            mapping_id,
            headers,
            factories.quoted_rate_params(
                stay_date=fixtures.STAY_DATE, geo_market_code=OTA_MARKET
            ),
        ),
        "performance_read": lambda: api.get_channel_performance(
            world["channel_id"],
            headers,
            factories.performance_params("2026-09-01", "2026-09-30"),
        ),
        "pace_read": lambda: api.get_pace(
            world["room_type_id"], headers, factories.pace_params(fixtures.STAY_DATE)
        ),
        "channel_mix_read": lambda: api.get_channel_mix(
            world["property_id"], headers, _analytics_window()
        ),
    }


# ── A channel partner outside its own two reservation routes ────────────────


@pytest.mark.parametrize(
    "surface",
    [
        "rate_plan_create",
        "rate_plan_reprice",
        "inventory_day_open",
        "restriction_place",
        "mapping_create",
        "quoted_rate_read",
        "performance_read",
        "pace_read",
        "channel_mix_read",
    ],
)
def test_channel_partner_is_refused_on_the_pricing_inventory_and_analytics_surfaces(
    api, world, surface
):
    """A ChannelPartner is admitted only by the two reservation routes and the two
    reservation reads, so every pricing, inventory and analytics route answers
    ERR_ROLE_NOT_PERMITTED, and because the role check precedes path resolution,
    body validation and the version echo, no row and no version moves.

    Design: Corner/rbac/channel_partner_cannot_reach_the_pricing_inventory_or_analytics_surface
    """
    mapping = fixtures.create_verified_mapping(
        api, world["rate_plan_id"], world["channel_id"], world["room_type_id"]
    )
    partner_headers = make_channel_partner_headers(world["channel_id"])
    plan_before = fixtures.read_rate_plan(api, world["rate_plan_id"])

    response = _surface_calls(api, world, mapping["id"], partner_headers)[surface]()
    validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED.value, 403)

    # Nothing was created and nothing advanced: the plan is still the one the
    # world seeded, and the four surfaces the partner reached for are unchanged.
    assert_unchanged(
        plan_before,
        fixtures.read_rate_plan(api, world["rate_plan_id"]),
        PLAN_STABLE_FIELDS,
        entity_name="rate plan",
    )
    assert len(fixtures.list_rate_plans(api, property_id=world["property_id"])) == 1
    assert fixtures.list_inventory_days(api, room_type_id=world["room_type_id"]) == []
    assert fixtures.list_restrictions(api, room_type_id=world["room_type_id"]) == []
    assert len(fixtures.list_mappings(api, channel_id=world["channel_id"])) == 1


def test_channel_partner_keeps_its_own_scoped_reservation_list(api, world):
    """The reservation list is the one read a ChannelPartner shares with the staff
    roles, so it answers 200 with an array rather than a refusal, and the partner
    sees only the reservations whose channel is its own.

    Design: Corner/rbac/channel_partner_cannot_reach_the_pricing_inventory_or_analytics_surface
    """
    fixtures.open_inventory_day(api, world["room_type_id"], fixtures.STAY_DATE)
    partner_headers = make_channel_partner_headers(world["channel_id"])

    rows, meta = validate_paginated(api.list_reservations(partner_headers, None))
    assert rows == [], f"a partner with no bookings should see no reservations, got {rows}"
    assert meta["total_count"] == 0, (
        f"meta.total_count should be 0, got {meta['total_count']}"
    )

    booking = validate_success(
        api.create_reservation(
            factories.reservation_payload(
                channel_id=world["channel_id"],
                rate_plan_id=world["rate_plan_id"],
                room_type_id=world["room_type_id"],
                arrival_date=fixtures.STAY_DATE,
                nights=1,
                geo_market_code=OTA_MARKET,
            ),
            partner_headers,
        ),
        201,
    )

    rows, meta = validate_paginated(api.list_reservations(partner_headers, None))
    assert [row["id"] for row in rows] == [booking["id"]], (
        f"the partner should now see its own one reservation, got {rows}"
    )
    assert meta["total_count"] == 1, (
        f"meta.total_count should be 1, got {meta['total_count']}"
    )


def test_the_admitted_roles_reach_every_one_of_those_surfaces(api, world):
    """Each route the partner was refused on is reached successfully by a role the
    contract lists for it, which is what proves those refusals were about the
    caller's role and not about a malformed request.

    Design: Corner/rbac/channel_partner_cannot_reach_the_pricing_inventory_or_analytics_surface
    """
    # The revenue manager owns commercial content, the sellable calendar and
    # restrictions; the connectivity engineer owns mappings.
    validate_success(
        api.create_rate_plan(
            world["property_id"],
            factories.rate_plan_payload(
                code="PARTNERBAR",
                rate_class="PUBLIC",
                base_amount_cents=19000,
                floor_amount_cents=15000,
                ceiling_amount_cents=30000,
            ),
            REVENUE_MANAGER_HEADERS,
        ),
        201,
    )
    validate_success(
        api.create_inventory_day(
            world["room_type_id"],
            factories.inventory_day_payload(fixtures.STAY_DATE),
            REVENUE_MANAGER_HEADERS,
        ),
        201,
    )
    # Closed on a night no booking below touches, so the calendar stays sellable.
    validate_success(
        api.create_restriction(
            factories.stop_sell_payload(
                world["room_type_id"], fixtures.STAY_DATE_4, fixtures.STAY_DATE_4
            ),
            REVENUE_MANAGER_HEADERS,
        ),
        201,
    )
    mapping = validate_success(
        api.create_mapping(
            factories.mapping_payload(
                world["rate_plan_id"],
                world["channel_id"],
                world["room_type_id"],
                content_description_hash=fixtures.KING_HASH,
                content_image_count=fixtures.KING_IMAGE_COUNT,
            ),
            CHANNEL_OPS_ENGINEER_HEADERS,
        ),
        201,
    )

    # 25000 base, no promotion, channel adjustment 0, inside the 18000-40000 band,
    # no package inclusion -> 25000.
    quote = validate_success(
        api.get_quoted_rate(
            mapping["id"],
            REVENUE_MANAGER_HEADERS,
            factories.quoted_rate_params(
                stay_date=fixtures.STAY_DATE, geo_market_code=OTA_MARKET
            ),
        ),
        200,
    )
    assert_quoted_rate(
        quote,
        {
            "channel_mapping_id": mapping["id"],
            "stay_date": fixtures.STAY_DATE,
            "base_amount_cents": 25000,
            "promotion_discount_cents": 0,
            "sell_amount_cents": 25000,
        },
    )

    # 25000 gross, 1750 bp commission -> 4375, net 20625, one room night.
    validate_success(
        api.create_reservation(
            factories.reservation_payload(
                channel_id=world["channel_id"],
                rate_plan_id=world["rate_plan_id"],
                room_type_id=world["room_type_id"],
                arrival_date=fixtures.STAY_DATE,
                nights=1,
                geo_market_code=OTA_MARKET,
            ),
            REVENUE_MANAGER_HEADERS,
        ),
        201,
    )

    performance = validate_success(
        api.get_channel_performance(
            world["channel_id"],
            REVENUE_MANAGER_HEADERS,
            factories.performance_params("2026-09-01", "2026-09-30"),
        ),
        200,
    )
    assert_performance(
        performance,
        {
            "channel_id": world["channel_id"],
            # `basis` is optional on the request and defaults to the stay view.
            "basis": "STAY",
            "gross_amount_cents": 25000,
            "commission_amount_cents": 4375,
            "net_amount_cents": 20625,
            "room_nights": 1,
            "net_adr_cents": 20625,
            "commission_cost_ratio_bp": 1750,
        },
    )

    pace = validate_success(
        api.get_pace(
            world["room_type_id"],
            REVENUE_MANAGER_HEADERS,
            factories.pace_params(fixtures.STAY_DATE),
        ),
        200,
    )
    assert_pace(
        pace,
        {
            "room_type_id": world["room_type_id"],
            "target_stay_date": fixtures.STAY_DATE,
            # `baseline` is optional and defaults to the rolling comparison.
            "baseline": "ROLLING",
            "as_of_date": fixtures.FIXTURE_TODAY,
            "target_room_nights": 1,
        },
    )

    mix = validate_success(
        api.get_channel_mix(world["property_id"], REVENUE_MANAGER_HEADERS, _analytics_window()),
        200,
    )
    assert len(mix["ranked_channels"]) == 1, (
        f"one channel holds room nights in the window, got {mix['ranked_channels']}"
    )
    assert_ranked_channel(
        mix["ranked_channels"][0],
        {
            "rank": 1,
            "net_adr_cents": 20625,
            "commission_bp": fixtures.OTA_COMMISSION_BP,
            "commission_cost_ratio_bp": 1750,
            "room_nights": 1,
        },
    )


# ── Absent, empty and unrecognised credentials ──────────────────────────────


@pytest.mark.parametrize(
    "credential",
    [
        "no_role_header",
        "empty_role_header",
        "no_user_id_header",
        "empty_user_id_header",
        "neither_header",
        "undeclared_role",
    ],
)
def test_absent_empty_or_unrecognised_credentials_are_unauthenticated(
    api, world, credential
):
    """Both caller headers must be present and non-empty and the role must name one
    of the five declared roles; anything else is unauthenticated, which is a 401
    and never the 403 reserved for a role the route does not admit.

    Design: Corner/rbac/requests_with_missing_or_unknown_x_user_headers_are_unauthenticated
    """
    headers = {
        "no_role_header": headers_without_role(),
        "empty_role_header": headers_with_empty_role(),
        "no_user_id_header": headers_without_user_id(),
        "empty_user_id_header": headers_with_empty_user_id(),
        "neither_header": headers_without_credentials(),
        "undeclared_role": headers_with_undeclared_role(),
    }[credential]

    # A read the platform admin is entitled to, so only the credential can fail.
    validate_error(
        api.get_property(world["property_id"], headers),
        ApiErrorId.UNAUTHENTICATED.value,
        401,
    )


def test_an_unusable_credential_outranks_an_unresolvable_path_id(api, world):
    """The credential check is the first gate of the ordered pipeline, so a request
    that is both unauthenticated and aimed at an identifier that resolves to
    nothing is reported as unauthenticated rather than as not found.

    Design: Corner/rbac/requests_with_missing_or_unknown_x_user_headers_are_unauthenticated
    """
    validate_error(
        api.get_property(NON_EXISTENT_UUID, headers_without_credentials()),
        ApiErrorId.UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api.get_reservation(NON_EXISTENT_UUID, headers_with_undeclared_role()),
        ApiErrorId.UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api.get_rate_plan(NON_EXISTENT_UUID, headers_with_empty_role()),
        ApiErrorId.UNAUTHENTICATED.value,
        401,
    )


def test_an_unauthenticated_write_changes_nothing(api, world):
    """An unauthenticated request is refused before any state is touched, so a
    creation attempt carrying an otherwise valid body leaves the collection
    exactly as the authenticated caller left it.

    Design: Corner/rbac/requests_with_missing_or_unknown_x_user_headers_are_unauthenticated
    """
    payload = factories.property_payload(code="GHOSTPROP", name="Ghost Property")

    validate_error(
        api.create_property(payload, headers_without_credentials()),
        ApiErrorId.UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api.create_property(payload, headers_with_undeclared_role()),
        ApiErrorId.UNAUTHENTICATED.value,
        401,
    )

    # Only the world's own property exists; neither refused write created a row.
    rows, meta = validate_paginated(
        api.list_properties(PLATFORM_ADMIN_HEADERS, factories.page_params(limit=100))
    )
    assert meta["total_count"] == 1, (
        f"only the seeded property should exist, meta.total_count is {meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [world["property_id"]], (
        f"the property collection should be unchanged, got {rows}"
    )


def test_a_complete_declared_credential_is_authenticated(api, world):
    """A request carrying both headers with a declared role passes the credential
    gate and is answered on its merits, which is what makes the 401s above
    attributable to the credential and not to the route.

    Design: Corner/rbac/requests_with_missing_or_unknown_x_user_headers_are_unauthenticated
    """
    read = validate_success(api.get_property(world["property_id"], PLATFORM_ADMIN_HEADERS), 200)
    assert read["id"] == world["property_id"], (
        f"the read should return the seeded property, got {read['id']}"
    )

    created = validate_success(
        api.create_property(
            factories.property_payload(code="GHOSTPROP", name="Ghost Property"),
            PLATFORM_ADMIN_HEADERS,
        ),
        201,
    )
    assert created["code"] == "GHOSTPROP", (
        f"the created property should carry the requested code, got {created['code']}"
    )


# ── A channel partner acting on someone else's channel ──────────────────────


def test_a_partner_cannot_book_on_another_channels_identifier(api, world):
    """A ChannelPartner's identifier *is* its channel, so a booking naming any other
    channel is an ownership violation rather than a role refusal, and it is caught
    before the body is priced, so no reservation exists and no ledger moves.

    Design: Corner/rbac/channel_partner_cannot_book_or_cancel_on_another_channels_id
    """
    opaque = fixtures.create_opaque_channel(api, world["property_id"])
    fixtures.open_inventory_day(api, world["room_type_id"], fixtures.STAY_DATE)

    # The opaque channel's partner reaching for the OTA's identifier in the body.
    response = api.create_reservation(
        factories.reservation_payload(
            channel_id=world["channel_id"],
            rate_plan_id=world["rate_plan_id"],
            room_type_id=world["room_type_id"],
            arrival_date=fixtures.STAY_DATE,
            nights=1,
            geo_market_code=OTA_MARKET,
        ),
        make_channel_partner_headers(opaque["channel"]["id"]),
    )
    validate_error(response, ApiErrorId.CHANNEL_OWNERSHIP_VIOLATION.value, 403)

    assert fixtures.list_reservations(api) == [], (
        "a refused booking must not leave a reservation behind"
    )
    assert_channel_ledger(
        fixtures.read_channel(api, world["channel_id"]),
        {
            "gross_revenue_cents": 0,
            "commission_accrued_cents": 0,
            "net_revenue_cents": 0,
            "room_nights_sold": 0,
            "bookings_count": 0,
            "cancellations_count": 0,
        },
    )
    assert_inventory_day(
        fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE),
        capacity=fixtures.KING_CAPACITY,
        ceiling=fixtures.KING_CEILING,
        allocated=0,
        committed=0,
        shared=fixtures.KING_CEILING,
        pooled_state="OPEN",
    )


def test_each_partner_books_successfully_on_its_own_channel(api, world):
    """Each ChannelPartner is admitted on the one channel whose id is its own
    identifier, and the booking is priced on that channel's commission, which is
    what makes the cross-channel refusal about ownership and not about the body.

    Design: Corner/rbac/channel_partner_cannot_book_or_cancel_on_another_channels_id
    """
    opaque = fixtures.create_opaque_channel(api, world["property_id"])
    fixtures.open_inventory_day(api, world["room_type_id"], fixtures.STAY_DATE)

    # The OTA serves only US-CA, so its own partner must name that market.
    # 25000 gross, 1750 bp -> 4375 commission, net 20625, gross under the
    # 50000 loyalty floor so tier_bp is 0 and the credit is 0.
    ota_booking = validate_success(
        api.create_reservation(
            factories.reservation_payload(
                channel_id=world["channel_id"],
                rate_plan_id=world["rate_plan_id"],
                room_type_id=world["room_type_id"],
                arrival_date=fixtures.STAY_DATE,
                nights=1,
                geo_market_code=OTA_MARKET,
            ),
            make_channel_partner_headers(world["channel_id"]),
        ),
        201,
    )
    assert_fields(
        ota_booking,
        {
            "channel_id": world["channel_id"],
            "reservation_state": "CONFIRMED",
            "cancelled_at": None,
            "version": 1,
        },
        entity_name="reservation",
    )
    assert_reservation_totals(
        ota_booking, gross=25000, commission=4375, net=20625, loyalty_credit=0
    )

    # The opaque channel's geo_market_codes default to the empty list, so it
    # serves every market and its partner names none.
    # 25000 gross, 2500 bp -> 6250 commission, net 18750.
    opaque_booking = validate_success(
        api.create_reservation(
            factories.reservation_payload(
                channel_id=opaque["channel"]["id"],
                rate_plan_id=world["rate_plan_id"],
                room_type_id=world["room_type_id"],
                arrival_date=fixtures.STAY_DATE,
                nights=1,
            ),
            make_channel_partner_headers(opaque["channel"]["id"]),
        ),
        201,
    )
    assert_fields(
        opaque_booking,
        {
            "channel_id": opaque["channel"]["id"],
            "reservation_state": "CONFIRMED",
            "geo_market_code": None,
        },
        entity_name="reservation",
    )
    assert_reservation_totals(
        opaque_booking, gross=25000, commission=6250, net=18750, loyalty_credit=0
    )

    assert_channel_ledger(
        fixtures.read_channel(api, world["channel_id"]),
        {
            "gross_revenue_cents": 25000,
            "commission_accrued_cents": 4375,
            "net_revenue_cents": 20625,
            "room_nights_sold": 1,
            "bookings_count": 1,
        },
    )
    assert_channel_ledger(
        fixtures.read_channel(api, opaque["channel"]["id"]),
        {
            "gross_revenue_cents": 25000,
            "commission_accrued_cents": 6250,
            "net_revenue_cents": 18750,
            "room_nights_sold": 1,
            "bookings_count": 1,
        },
    )


def test_a_partner_cannot_cancel_another_channels_reservation(api, world):
    """On cancellation the ownership test reads the *stored* reservation's channel,
    so a partner cancelling a stay that arrived on another channel is refused and
    the reservation stays CONFIRMED; the owning partner then cancels it.

    Design: Corner/rbac/channel_partner_cannot_book_or_cancel_on_another_channels_id
    """
    opaque = fixtures.create_opaque_channel(api, world["property_id"])
    fixtures.open_inventory_day(api, world["room_type_id"], fixtures.STAY_DATE)

    booking = fixtures.create_reservation(
        api,
        opaque["channel"]["id"],
        world["rate_plan_id"],
        world["room_type_id"],
        fixtures.STAY_DATE,
        1,
        headers=make_channel_partner_headers(opaque["channel"]["id"]),
    )

    validate_error(
        api.cancel_reservation(
            booking["id"], make_channel_partner_headers(world["channel_id"])
        ),
        ApiErrorId.CHANNEL_OWNERSHIP_VIOLATION.value,
        403,
    )
    unchanged = fixtures.read_reservation(api, booking["id"])
    assert_fields(
        unchanged,
        {"reservation_state": "CONFIRMED", "cancelled_at": None, "version": 1},
        entity_name="reservation",
    )
    assert_channel_ledger(
        fixtures.read_channel(api, opaque["channel"]["id"]),
        {"bookings_count": 1, "cancellations_count": 0, "room_nights_sold": 1},
    )

    # The owner is admitted on the very same route and the same reservation.
    cancelled = validate_success(
        api.cancel_reservation(
            booking["id"], make_channel_partner_headers(opaque["channel"]["id"])
        ),
        200,
    )
    assert_fields(
        cancelled, {"reservation_state": "CANCELLED", "version": 2}, entity_name="reservation"
    )
    assert_instant_equals(cancelled["cancelled_at"], fixtures.FIXTURE_CLOCK, "cancelled_at")
    assert_channel_ledger(
        fixtures.read_channel(api, opaque["channel"]["id"]),
        {
            "gross_revenue_cents": 0,
            "commission_accrued_cents": 0,
            "net_revenue_cents": 0,
            "room_nights_sold": 0,
            "bookings_count": 1,
            "cancellations_count": 1,
        },
    )


# ── Segregation of duties on one promotion ──────────────────────────────────


def _submitted_by_director_one(api, rate_plan_id):
    """A MEMBER_RATE promotion submitted by the first director identity.

    The discount is 1000 bp, well under the three-thousand-basis-point submission
    ceiling, so the only thing that can refuse the approval below is the identity
    of the caller.
    """
    promotion = fixtures.create_promotion(
        api,
        rate_plan_id,
        start_date=fixtures.STAY_DATE,
        end_date=fixtures.STAY_DATE_2,
        code="MEMBER10",
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=1000,
    )
    submitted = validate_success(
        api.submit_promotion(promotion["id"], make_revenue_director_headers(DIRECTOR_ONE)), 200
    )
    assert_fields(
        submitted,
        {
            "approval_status": "SUBMITTED",
            "submitted_by_user_id": DIRECTOR_ONE,
            "approved_by_user_id": None,
            "distribution_status": "NOT_LOADED",
            "version": 2,
        },
        entity_name="promotion",
    )
    return submitted


def test_the_submitting_director_cannot_approve_its_own_promotion(api, world):
    """A RevenueDirector may submit a promotion, but the approving director must be a
    different operator identifier, so the submitter's own approval is refused with
    ERR_SEGREGATION_OF_DUTIES and the promotion stays SUBMITTED.

    Design: Corner/rbac/the_same_director_cannot_submit_and_then_approve_or_reject_a_promotion
    """
    promotion = _submitted_by_director_one(api, world["rate_plan_id"])

    validate_error(
        api.approve_promotion(promotion["id"], make_revenue_director_headers(DIRECTOR_ONE)),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
        403,
    )

    after = fixtures.read_promotion(api, promotion["id"])
    assert_fields(
        after,
        {
            "approval_status": "SUBMITTED",
            "submitted_by_user_id": DIRECTOR_ONE,
            "approved_by_user_id": None,
            "reject_reason": None,
            "revision_count": 0,
            "version": 2,
        },
        entity_name="promotion",
    )


def test_the_submitting_director_cannot_reject_its_own_promotion(api, world):
    """Rejection carries the same duties bar as approval, so the operator who
    submitted cannot reject either, and the rejection reason is never recorded.

    Design: Corner/rbac/the_same_director_cannot_submit_and_then_approve_or_reject_a_promotion
    """
    promotion = _submitted_by_director_one(api, world["rate_plan_id"])

    validate_error(
        api.reject_promotion(
            promotion["id"],
            make_revenue_director_headers(DIRECTOR_ONE),
            factories.reject_payload("Discount too deep for the season"),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES.value,
        403,
    )

    after = fixtures.read_promotion(api, promotion["id"])
    assert_fields(
        after,
        {
            "approval_status": "SUBMITTED",
            "submitted_by_user_id": DIRECTOR_ONE,
            "reject_reason": None,
            "version": 2,
        },
        entity_name="promotion",
    )


def test_a_second_director_identity_approves_the_same_promotion(api, world):
    """The very promotion its own submitter could not approve is approved by a second
    director identity on the same route, which is what shows the refusal was about
    the operator identifier rather than about the promotion or the role.

    Design: Corner/rbac/the_same_director_cannot_submit_and_then_approve_or_reject_a_promotion
    """
    promotion = _submitted_by_director_one(api, world["rate_plan_id"])

    approved = validate_success(
        api.approve_promotion(promotion["id"], make_revenue_director_headers(DIRECTOR_TWO)), 200
    )
    assert_fields(
        approved,
        {
            "approval_status": "APPROVED",
            "submitted_by_user_id": DIRECTOR_ONE,
            "approved_by_user_id": DIRECTOR_TWO,
            "reject_reason": None,
            # The approval axis moves alone; the technical axis is untouched.
            "distribution_status": "NOT_LOADED",
            "version": 3,
        },
        entity_name="promotion",
    )
    assert DIRECTOR_TWO != DIRECTOR_ONE, (
        "the approving identity must genuinely differ from the submitting one"
    )


def test_revision_clears_the_submitter_and_frees_the_blocked_director(api, world):
    """Revision returns a rejected offer to DRAFT and clears the recorded submitter,
    so the identity that was previously barred from approving becomes free to do
    so once a different operator submits the revised offer.

    Design: Corner/rbac/the_same_director_cannot_submit_and_then_approve_or_reject_a_promotion
    """
    promotion = _submitted_by_director_one(api, world["rate_plan_id"])

    rejected = validate_success(
        api.reject_promotion(
            promotion["id"],
            make_revenue_director_headers(DIRECTOR_TWO),
            factories.reject_payload("Needs a shorter window"),
        ),
        200,
    )
    assert_fields(
        rejected,
        {
            "approval_status": "REJECTED",
            "submitted_by_user_id": DIRECTOR_ONE,
            "reject_reason": "Needs a shorter window",
            "version": 3,
        },
        entity_name="promotion",
    )

    revised = validate_success(
        api.revise_promotion(promotion["id"], REVENUE_MANAGER_HEADERS), 200
    )
    assert_fields(
        revised,
        {
            "approval_status": "DRAFT",
            "submitted_by_user_id": None,
            "reject_reason": None,
            "revision_count": 1,
            "version": 4,
        },
        entity_name="promotion",
    )

    # The second director submits the revised offer, so the first one is free.
    resubmitted = validate_success(
        api.submit_promotion(promotion["id"], make_revenue_director_headers(DIRECTOR_TWO)), 200
    )
    assert_fields(
        resubmitted,
        {"approval_status": "SUBMITTED", "submitted_by_user_id": DIRECTOR_TWO, "version": 5},
        entity_name="promotion",
    )

    approved = validate_success(
        api.approve_promotion(promotion["id"], make_revenue_director_headers(DIRECTOR_ONE)), 200
    )
    assert_fields(
        approved,
        {
            "approval_status": "APPROVED",
            "submitted_by_user_id": DIRECTOR_TWO,
            "approved_by_user_id": DIRECTOR_ONE,
            "revision_count": 1,
            "version": 6,
        },
        entity_name="promotion",
    )


# ── Overriding a system-owned decision ──────────────────────────────────────


def _twin_night(api, world):
    """A two-room type with its own 50% allowance and one open night.

    floor(2 x (1 + 5000/10000)) = 3, so the ceiling is 3 and the overbooking band
    is the single unit between physical capacity 2 and ceiling 3.
    """
    twin = fixtures.create_twin_room_type(api, world["property_id"])
    fixtures.open_inventory_day(api, twin["id"], fixtures.STAY_DATE)
    return twin


def _book_twin(api, world, twin_id, headers=REVENUE_MANAGER_HEADERS, **overrides):
    """One night on the canonical OTA, which serves only the US-CA market."""
    return api.create_reservation(
        factories.reservation_payload(
            channel_id=world["channel_id"],
            rate_plan_id=world["rate_plan_id"],
            room_type_id=twin_id,
            arrival_date=fixtures.STAY_DATE,
            nights=1,
            geo_market_code=OTA_MARKET,
            **overrides,
        ),
        headers,
    )


def _oversell_twin_night(api, world, twin_id):
    """Drive the night to OVERSOLD with three bookings, the third overriding."""
    validate_success(_book_twin(api, world, twin_id), 201)
    validate_success(_book_twin(api, world, twin_id), 201)
    validate_success(_book_twin(api, world, twin_id, override_overbooking=True), 201)
    guards = [
        restriction
        for restriction in fixtures.list_restrictions(api, room_type_id=twin_id)
        if restriction["origin"] == "AUTO_OVERBOOK_GUARD"
    ]
    assert len(guards) == 1, (
        f"one ACTIVE rate plan on the property means one guard restriction, got {guards}"
    )
    return guards[0]


def test_a_channel_partner_may_not_send_the_overbooking_override(api, world):
    """Only a RevenueManager or a RevenueDirector may send `override_overbooking`
    true; a ChannelPartner sending it is refused with ERR_OVERRIDE_NOT_PERMITTED
    even on a night with room to spare, because the field itself is not its to send.

    Design: Corner/rbac/partner_override_and_human_guard_lift_are_both_rejected
    """
    twin = _twin_night(api, world)

    response = _book_twin(
        api,
        world,
        twin["id"],
        headers=make_channel_partner_headers(world["channel_id"]),
        override_overbooking=True,
    )
    validate_error(response, ApiErrorId.OVERRIDE_NOT_PERMITTED.value, 403)

    # The override check precedes the capacity check, so the untouched night is
    # still wide open: 3 - 0 - 0 = 3 units of shared pool.
    assert fixtures.list_reservations(api) == [], (
        "the refused booking must not have been created"
    )
    assert_inventory_day(
        fixtures.inventory_day_on(api, twin["id"], fixtures.STAY_DATE),
        capacity=fixtures.TWIN_CAPACITY,
        ceiling=fixtures.TWIN_CEILING,
        allocated=0,
        committed=0,
        shared=fixtures.TWIN_CEILING,
        pooled_state="OPEN",
    )


def test_a_revenue_manager_sends_the_override_and_consumes_it(api, world):
    """The override is refused to the partner but admitted to the RevenueManager, who
    needs it only once the unit being sold lands in the overbooking band, and the
    flag records the override as consumed only on that booking.

    Design: Corner/rbac/partner_override_and_human_guard_lift_are_both_rejected
    """
    twin = _twin_night(api, world)

    # 0 + 0 = 0 below capacity 2, so the first unit is not in the band.
    first = validate_success(_book_twin(api, world, twin["id"]), 201)
    assert first["overbooking_overridden"] is False, (
        "a booking below physical capacity consumes no override"
    )
    assert_inventory_day(
        fixtures.inventory_day_on(api, twin["id"], fixtures.STAY_DATE),
        allocated=0,
        committed=1,
        shared=2,
        pooled_state="OPEN",
    )

    # 0 + 1 = 1 still below capacity 2, so the second unit is not in the band
    # either. Afterwards held plus committed is 2, at capacity but under the
    # ceiling of 3, and 3 - 0 - 2 leaves one unit of shared pool.
    validate_success(_book_twin(api, world, twin["id"]), 201)
    assert_inventory_day(
        fixtures.inventory_day_on(api, twin["id"], fixtures.STAY_DATE),
        capacity=fixtures.TWIN_CAPACITY,
        ceiling=fixtures.TWIN_CEILING,
        allocated=0,
        committed=2,
        shared=1,
        pooled_state="TIGHT",
    )

    # 0 + 2 has reached capacity 2, so the third unit is in the band and the
    # override is now required; the shared pool still holds one unit, so this is
    # the override error and not the ceiling error.
    validate_error(
        _book_twin(api, world, twin["id"]),
        ApiErrorId.OVERBOOK_OVERRIDE_REQUIRED.value,
        409,
    )

    third = validate_success(_book_twin(api, world, twin["id"], override_overbooking=True), 201)
    assert third["override_overbooking"] is True, "the request's own flag is echoed back"
    assert third["overbooking_overridden"] is True, (
        "the override was actually consumed on this night"
    )

    # committed 3 exceeds physical capacity 2 with the ceiling reached, so the
    # night is OVERSOLD rather than merely EXHAUSTED.
    assert_inventory_day(
        fixtures.inventory_day_on(api, twin["id"], fixtures.STAY_DATE),
        capacity=fixtures.TWIN_CAPACITY,
        ceiling=fixtures.TWIN_CEILING,
        allocated=0,
        committed=3,
        shared=0,
        pooled_state="OVERSOLD",
    )

    guards = [
        restriction
        for restriction in fixtures.list_restrictions(api, room_type_id=twin["id"])
        if restriction["origin"] == "AUTO_OVERBOOK_GUARD"
    ]
    assert len(guards) == 1, f"one guard per ACTIVE rate plan on the property, got {guards}"
    assert_fields(
        guards[0],
        {
            "restriction_type": "STOP_SELL",
            "origin": "AUTO_OVERBOOK_GUARD",
            "restriction_state": "ACTIVE",
            "room_type_id": twin["id"],
            "rate_plan_id": world["rate_plan_id"],
            "start_date": fixtures.STAY_DATE,
            "end_date": fixtures.STAY_DATE,
            "value_nights": None,
            "lifted_at": None,
            "lift_reason": None,
            "version": 1,
        },
        entity_name="guard restriction",
    )


def test_no_human_role_may_lift_the_automatic_overbooking_guard(api, world):
    """A restriction whose origin is AUTO_OVERBOOK_GUARD is system-owned, so the
    RevenueManager the lift route admits is refused with ERR_OVERRIDE_NOT_PERMITTED,
    while the RevenueDirector the route does not admit at all is refused earlier,
    with ERR_ROLE_NOT_PERMITTED.

    Design: Corner/rbac/partner_override_and_human_guard_lift_are_both_rejected
    """
    twin = _twin_night(api, world)
    guard = _oversell_twin_night(api, world, twin["id"])

    validate_error(
        api.lift_restriction(guard["id"], REVENUE_MANAGER_HEADERS),
        ApiErrorId.OVERRIDE_NOT_PERMITTED.value,
        403,
    )
    # Role admission is checked before override authority, so the director never
    # reaches the guard's origin at all.
    validate_error(
        api.lift_restriction(guard["id"], REVENUE_DIRECTOR_HEADERS),
        ApiErrorId.ROLE_NOT_PERMITTED.value,
        403,
    )

    still_active = fixtures.read_restriction(api, guard["id"])
    assert_fields(
        still_active,
        {
            "restriction_state": "ACTIVE",
            "origin": "AUTO_OVERBOOK_GUARD",
            "lifted_at": None,
            "lift_reason": None,
            "version": 1,
        },
        entity_name="guard restriction",
    )


def test_a_revenue_manager_lifts_a_manual_restriction_on_the_same_route(api, world):
    """The lift route itself works for the RevenueManager when the restriction is the
    operator's own: the manual restriction moves ACTIVE to LIFTED with lift_reason
    MANUAL_LIFT, which is what makes the guard refusal about the origin.

    Design: Corner/rbac/partner_override_and_human_guard_lift_are_both_rejected
    """
    twin = _twin_night(api, world)
    manual = fixtures.create_restriction(
        api, twin["id"], "STOP_SELL", fixtures.STAY_DATE_3, fixtures.STAY_DATE_3
    )
    assert_fields(
        manual,
        {"origin": "MANUAL", "restriction_state": "ACTIVE", "lift_reason": None, "version": 1},
        entity_name="restriction",
    )

    lifted = validate_success(api.lift_restriction(manual["id"], REVENUE_MANAGER_HEADERS), 200)
    assert_fields(
        lifted,
        {
            "restriction_state": "LIFTED",
            "origin": "MANUAL",
            "lift_reason": "MANUAL_LIFT",
            "version": 2,
        },
        entity_name="restriction",
    )
    assert_instant_equals(lifted["lifted_at"], fixtures.FIXTURE_CLOCK, "lifted_at")
