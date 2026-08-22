"""Ordering opinions of value: vendor slot admission, daily capacity, recording,
the controlling valuation and the servicer's floor."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_valuation,
    create_case,
    create_vendor,
    make_bpo_vendor_headers,
    order_valuation,
    order_valuation_payload,
    package_decision_payload,
    record_value,
    record_value_payload,
    set_clock,
    setup_recorded_valuation,
    setup_submitted_package,
    validate_error,
    validate_paginated,
    validate_success,
)

NEG = TEST_USERS["negotiator_headers"]
ANALYST = TEST_USERS["servicer_analyst_headers"]


def setup_package_with_documents_and_decline(api):
    """Walk a case to the terminal DECLINED negotiation state via a package rejection."""
    case, package, documents = setup_submitted_package()
    package = validate_success(
        api.decide_hardship_package(package["id"], package_decision_payload("REJECT"), ANALYST),
        200,
    )
    return case, package, documents



def test_slot_within_the_vendor_buffer_collides_across_cases(api):
    """PRD §3.6: "The vendor needs an hour of travel and setup either side of a site
    visit, so a requested slot conflicts with an existing one when the requested start
    falls strictly before the existing slot's end extended forward by 60 minutes **and**
    the requested end falls strictly after the existing slot's start pulled back by 60
    minutes."
    PRD §3.6: "Both comparisons are strict, which means a gap of exactly 60 minutes
    between two slots is admissible and a gap of 59 minutes is not. A conflict is refused
    with `ERR_VENDOR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/vendor_buffered_slot_conflict_rejected_on_bpo_vendor
    """
    set_clock("2026-08-05T00:00:00Z")
    vendor = create_vendor()
    case_a = create_case(property_address="118 Larkspur Ln, Reno NV")
    case_b = create_case(
        property_address="6 Manzanita Ct, Reno NV", unpaid_principal_balance_cents=21_500_000
    )
    held = order_valuation(case_a["id"], vendor["id"])

    # 10:00 -> 10:30 is a 30-minute gap, inside the 60-minute buffer.
    conflicting = api.order_valuation(
        case_b["id"],
        order_valuation_payload(
            vendor["id"],
            valuation_type="BPO_INTERIOR",
            inspection_start="2026-08-06T10:30:00Z",
            inspection_end="2026-08-06T11:30:00Z",
        ),
        ANALYST,
    )
    validate_error(conflicting, ApiErrorId.ERR_VENDOR_SCHEDULE_CONFLICT.value)

    _, meta = validate_paginated(
        api.list_valuations(ANALYST, params={"vendor_id": vendor["id"]})
    )
    assert meta["total_count"] == 1, "the refused order must not be persisted"

    stored = validate_success(api.get_valuation(held["id"], ANALYST), 200)
    assert stored["status"] == "ORDERED"
    assert_valuation(stored)

    case_b_after = validate_success(api.get_case(case_b["id"], ANALYST), 200)
    assert case_b_after["final_value_cents"] is None


def test_slot_exactly_sixty_minutes_clear_is_admitted(api):
    """PRD §3.6: "Both comparisons are strict, which means a gap of exactly 60 minutes
    between two slots is admissible and a gap of 59 minutes is not. A conflict is refused
    with `ERR_VENDOR_SCHEDULE_CONFLICT`."
    PRD §3.6: "The first is a **buffered slot conflict** measured across the vendor's
    entire book of work — every valuation that firm holds, on every case, in every
    status."

    Design: Difficulty/resource_temporal_overlap/vendor_buffered_slot_conflict_rejected_on_bpo_vendor
    """
    set_clock("2026-08-05T00:00:00Z")
    vendor = create_vendor()
    case_a = create_case(property_address="118 Larkspur Ln, Reno NV")
    case_b = create_case(
        property_address="6 Manzanita Ct, Reno NV", unpaid_principal_balance_cents=21_500_000
    )
    order_valuation(case_a["id"], vendor["id"])

    # 10:00 -> 11:00 is exactly the 60-minute buffer, so the comparison is not met.
    admitted = validate_success(
        api.order_valuation(
            case_b["id"],
            order_valuation_payload(
                vendor["id"],
                valuation_type="BPO_INTERIOR",
                inspection_start="2026-08-06T11:00:00Z",
                inspection_end="2026-08-06T12:00:00Z",
            ),
            ANALYST,
        ),
        201,
    )

    assert admitted["status"] == "ORDERED"
    assert admitted["case_id"] == case_b["id"]
    assert admitted["vendor_id"] == vendor["id"]

    _, meta = validate_paginated(
        api.list_valuations(ANALYST, params={"vendor_id": vendor["id"]})
    )
    assert meta["total_count"] == 2, "the vendor now holds both inspections"


def test_third_inspection_on_a_two_slot_day_exceeds_daily_capacity(api):
    """PRD §3.6: "The second constraint, evaluated only once the first has passed, is the
    vendor's **aggregate daily allowance**: count the valuations already held by that
    vendor whose `inspection_start` falls on the same UTC calendar date as the requested
    one, and if that count has already reached the firm's `daily_inspection_capacity`,
    refuse the order with `ERR_VENDOR_DAILY_CAPACITY_EXCEEDED`."

    Design: Corner/validations/vendor_daily_capacity_exceeded_on_third_slot
    """
    set_clock("2026-08-05T00:00:00Z")
    vendor = create_vendor()
    case_a = create_case(property_address="A Vireo Way, Reno NV")
    case_b = create_case(property_address="B Vireo Way, Reno NV")
    case_c = create_case(property_address="C Vireo Way, Reno NV")

    order_valuation(case_a["id"], vendor["id"])
    order_valuation(
        case_b["id"], vendor["id"],
        valuation_type="BPO_INTERIOR",
        inspection_start="2026-08-06T11:00:00Z",
        inspection_end="2026-08-06T12:00:00Z",
    )

    # 12:00 -> 13:00 clears the buffer, so only the daily allowance can refuse it.
    refused = api.order_valuation(
        case_c["id"],
        order_valuation_payload(
            vendor["id"],
            inspection_start="2026-08-06T13:00:00Z",
            inspection_end="2026-08-06T14:00:00Z",
        ),
        ANALYST,
    )
    validate_error(refused, ApiErrorId.ERR_VENDOR_DAILY_CAPACITY_EXCEEDED.value)

    _, meta = validate_paginated(
        api.list_valuations(ANALYST, params={"vendor_id": vendor["id"]})
    )
    assert meta["total_count"] == 2

    case_c_after = validate_success(api.get_case(case_c["id"], ANALYST), 200)
    assert case_c_after["final_value_cents"] is None


def test_recording_a_value_twice_is_not_actionable(api):
    """PRD §3.6: "Only the vendor named on a valuation may record its result, and only
    while the valuation is still `ORDERED`; recording against a valuation in any later
    status is refused with `ERR_VALUATION_NOT_ACTIONABLE`."
    PRD §3.6: "The vendor supplies `value_cents`; the server stamps it, stamps
    `recorded_at` with the current logical-clock instant, and moves the valuation to
    `RECEIVED`."

    Design: Corner/state_machines/record_value_twice_second_returns_valuation_not_actionable
    """
    scenario = setup_recorded_valuation(clock="2026-08-06T00:00:00Z")
    valuation = scenario["valuation"]
    assert valuation["status"] == "RECEIVED"

    validate_error(
        api.record_valuation_value(
            valuation["id"],
            record_value_payload(23_000_000),
            make_bpo_vendor_headers(scenario["vendor"]["id"]),
        ),
        ApiErrorId.ERR_VALUATION_NOT_ACTIONABLE.value,
    )

    stored = validate_success(api.get_valuation(valuation["id"], ANALYST), 200)
    assert stored["value_cents"] == 25_200_000
    assert stored["status"] == "RECEIVED"

    case_after = validate_success(api.get_case(scenario["case"]["id"], ANALYST), 200)
    assert case_after["final_value_cents"] == 25_200_000


def test_ordering_a_valuation_on_a_declined_case_is_not_actionable(api):
    """PRD §3.1: "Once a case reaches `CLOSED` or `DECLINED` it accepts no further
    business operations; an attempt to order work against such a file — a valuation, for
    instance — is refused with `ERR_CASE_NOT_ACTIONABLE`."

    Design: Corner/state_machines/order_valuation_on_declined_case_returns_case_not_actionable
    """
    set_clock("2026-08-05T00:00:00Z")
    vendor = create_vendor()
    case, package, _ = setup_package_with_documents_and_decline(api)

    validate_error(
        api.order_valuation(case["id"], order_valuation_payload(vendor["id"]), ANALYST),
        ApiErrorId.ERR_CASE_NOT_ACTIONABLE.value,
    )

    case_after = validate_success(api.get_case(case["id"], ANALYST), 200)
    assert case_after["negotiation_status"] == "DECLINED"

    _, meta = validate_paginated(
        api.list_valuations(ANALYST, params={"case_id": case["id"]})
    )
    assert meta["total_count"] == 0


def test_controlling_valuation_ranks_by_effective_date(api):
    """PRD §3.6: "Among the eligible ones, the controlling valuation is the one with the
    latest `effective_date`, breaking a tie in favour of the later `created_at`. Note
    that `effective_date`, not `recorded_at`, is the ranking key: a later-ordered opinion
    that speaks as of an earlier date does not displace an earlier-ordered one that
    speaks as of a later date."
    PRD §3.6: "`final_value_cents` is simply the controlling valuation's `value_cents`.
    `minimum_acceptable_net_cents` is derived from it in four steps."

    Design: Corner/calculations/controlling_valuation_is_the_latest_effective_date
    """
    set_clock("2026-08-06T00:00:00Z")
    vendor = create_vendor(daily_inspection_capacity=3)
    case = create_case(property_address="13 Nutmeg Ln, Reno NV")

    first = order_valuation(case["id"], vendor["id"])
    record_value(first["id"], vendor["id"], 25_200_000)
    second = order_valuation(
        case["id"], vendor["id"],
        valuation_type="BPO_INTERIOR",
        effective_date="2026-08-12T00:00:00Z",
        inspection_start="2026-08-11T09:00:00Z",
        inspection_end="2026-08-11T10:00:00Z",
    )

    recorded = validate_success(
        api.record_valuation_value(
            second["id"], record_value_payload(23_000_000),
            make_bpo_vendor_headers(vendor["id"]),
        ),
        200,
    )
    assert recorded["value_cents"] == 23_000_000

    first_after = validate_success(api.get_valuation(first["id"], ANALYST), 200)
    assert first_after["value_cents"] == 25_200_000

    case_after = validate_success(api.get_case(case["id"], ANALYST), 200)
    assert case_after["final_value_cents"] == 23_000_000, (
        "the later effective_date controls even though it was recorded second"
    )
    assert case_after["minimum_acceptable_net_cents"] == 20_240_000


def test_gse_floor_is_the_value_floor(api):
    """PRD §3.6: "First, a **value floor**: multiply `final_value_cents` by the ratio the
    investor demands — `0.88` for a `GSE` investor, `0.84` for a `PORTFOLIO` investor,
    `0.86` for an `FHA` investor — and round half up to whole cents."
    PRD §3.6: "Second, a **balance floor**: multiply the case's
    `unpaid_principal_balance_cents` by `0.60` and round half up to whole cents. Each
    floor is rounded on its own, before anything is compared. Third, take the **greater**
    of the two floors."

    Design: Difficulty/combinatorial_formula/minimum_acceptable_net_max_of_two_floors_with_investor_branch
    """
    set_clock("2026-08-05T00:00:00Z")
    vendor = create_vendor()
    gse_case = create_case(property_address="118 Larkspur Ln, Reno NV")
    portfolio_case = create_case(
        property_address="300 Coyote Rdg, Reno NV",
        investor_type="PORTFOLIO",
        unpaid_principal_balance_cents=42_000_000,
    )
    gse_valuation = order_valuation(gse_case["id"], vendor["id"])
    order_valuation(
        portfolio_case["id"], vendor["id"],
        inspection_start="2026-08-06T11:00:00Z",
        inspection_end="2026-08-06T12:00:00Z",
    )

    recorded = validate_success(
        api.record_valuation_value(
            gse_valuation["id"], record_value_payload(25_200_000),
            make_bpo_vendor_headers(vendor["id"]),
        ),
        200,
    )
    assert recorded["status"] == "RECEIVED"

    case_after = validate_success(api.get_case(gse_case["id"], ANALYST), 200)
    assert case_after["final_value_cents"] == 25_200_000
    # 25_200_000 * 0.88 = 22_176_000 beats 26_800_000 * 0.60 = 16_080_000.
    assert case_after["minimum_acceptable_net_cents"] == 22_176_000


def test_portfolio_floor_is_the_balance_floor(api):
    """PRD §3.6: "First, a **value floor**: multiply `final_value_cents` by the ratio the
    investor demands — `0.88` for a `GSE` investor, `0.84` for a `PORTFOLIO` investor,
    `0.86` for an `FHA` investor — and round half up to whole cents."
    PRD §3.6: "Second, a **balance floor**: multiply the case's
    `unpaid_principal_balance_cents` by `0.60` and round half up to whole cents. Each
    floor is rounded on its own, before anything is compared. Third, take the **greater**
    of the two floors."

    Design: Difficulty/combinatorial_formula/minimum_acceptable_net_max_of_two_floors_with_investor_branch
    """
    set_clock("2026-08-05T00:00:00Z")
    vendor = create_vendor()
    gse_case = create_case(property_address="118 Larkspur Ln, Reno NV")
    portfolio_case = create_case(
        property_address="300 Coyote Rdg, Reno NV",
        investor_type="PORTFOLIO",
        unpaid_principal_balance_cents=42_000_000,
    )
    order_valuation(gse_case["id"], vendor["id"])
    portfolio_valuation = order_valuation(
        portfolio_case["id"], vendor["id"],
        inspection_start="2026-08-06T11:00:00Z",
        inspection_end="2026-08-06T12:00:00Z",
    )

    recorded = validate_success(
        api.record_valuation_value(
            portfolio_valuation["id"], record_value_payload(25_200_000),
            make_bpo_vendor_headers(vendor["id"]),
        ),
        200,
    )
    assert recorded["status"] == "RECEIVED"

    case_after = validate_success(api.get_case(portfolio_case["id"], ANALYST), 200)
    assert case_after["final_value_cents"] == 25_200_000
    # 42_000_000 * 0.60 = 25_200_000 beats 25_200_000 * 0.84 = 21_168_000.
    assert case_after["minimum_acceptable_net_cents"] == 25_200_000


def test_unknown_vendor_id_in_the_order_body_is_not_found(api):
    """PRD §2.5: "A `vendor_id` in a valuation order that names no registered vendor firm
    is refused with `ERR_VENDOR_NOT_FOUND` and HTTP 404."

    Design: Corner/errors/vendor_not_found_on_valuation_body_returns_404
    """
    set_clock("2026-08-05T00:00:00Z")
    case = create_case()

    validate_error(
        api.order_valuation(case["id"], order_valuation_payload(NON_EXISTENT_UUID), ANALYST),
        ApiErrorId.ERR_VENDOR_NOT_FOUND.value,
    )

    _, meta = validate_paginated(
        api.list_valuations(ANALYST, params={"case_id": case["id"]})
    )
    assert meta["total_count"] == 0


def test_a_vendor_may_not_record_another_firms_valuation(api):
    """PRD §2.1: "When `X-User-Role` is `BpoVendor`, `X-User-ID` is the `id` of the acting
    vendor record itself; ownership checks compare the `vendor_id` recorded on a
    valuation to that `X-User-ID`, and a vendor may record a value only on valuations it
    holds."
    PRD §2.1: "When an ownership binding fails — a `BpoVendor` whose `X-User-ID` does not
    match the addressed valuation's `vendor_id`, or a `JuniorLienHolder` whose
    `X-User-ID` does not match the addressed lien's `holder_user_id` — the request is
    refused with `ERR_ACTOR_NOT_OWNER` and HTTP 403."

    Design: Corner/rbac/wrong_vendor_cannot_record_value
    """
    set_clock("2026-08-05T00:00:00Z")
    owner = create_vendor()
    intruder = create_vendor(vendor_name="Basin Valuation LLC")
    case = create_case()
    valuation = order_valuation(case["id"], owner["id"])

    validate_error(
        api.record_valuation_value(
            valuation["id"], record_value_payload(25_200_000),
            make_bpo_vendor_headers(intruder["id"]),
        ),
        ApiErrorId.ERR_ACTOR_NOT_OWNER.value,
    )

    stored = validate_success(api.get_valuation(valuation["id"], ANALYST), 200)
    assert stored["status"] == "ORDERED"
    assert stored["value_cents"] is None

    case_after = validate_success(api.get_case(case["id"], ANALYST), 200)
    assert case_after["final_value_cents"] is None
