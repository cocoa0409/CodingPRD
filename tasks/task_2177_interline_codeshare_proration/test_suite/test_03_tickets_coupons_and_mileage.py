"""Issuing tickets, appending coupons, flying them and accruing mileage cost."""

from test_helpers import (
    ApiErrorId,
    OPERATOR,
    UNKNOWN_UUID,
    assert_coupon,
    assert_ticket,
    create_coupon_payload,
    create_ticket_payload,
    fly,
    make_accountant_headers,
    new_carrier,
    new_ticket,
    read_carrier,
    read_coupon,
    read_ticket,
    set_clock,
    setup_ticket_with_coupons,
    setup_two_carriers,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Ticket issue
# --------------------------------------------------------------------------- #
def test_new_ticket_seeds_the_whole_fare_into_the_slack_bucket(api):
    """PRD §3.4: "A new ticket opens with `coupon_count` at zero, `last_run_type` of `NONE`,
    and `unallocated_residual_minor` equal to the whole `total_fare_minor` — the fare starts
    entirely unallocated and stays conserved from there."
    PRD §3.4: "The first, `proration_status`, moves among `UNPRORATED`, `PROVISIONAL`, `FINAL`
    and `REPRORATION_REQUIRED`, and starts at `UNPRORATED`. The second, `billing_status`,
    moves among `UNBILLED`, `BILLED`, `SETTLED` and `DISPUTED`, and starts at `UNBILLED`."

    Design: Corner/entities/ticket_creation_seeds_the_conservation_slack_bucket
    """
    aa = new_carrier("AA")
    payload = create_ticket_payload(
        aa["id"],
        "0030000000001",
        total_fare_minor=87654,
        issue_date="2026-08-01T00:00:00Z",
    )

    ticket = validate_success(
        api.create_ticket(payload, make_accountant_headers(aa["id"])), 201
    )
    assert_ticket(ticket)
    assert ticket["unallocated_residual_minor"] == 87654
    assert ticket["coupon_count"] == 0
    assert ticket["proration_status"] == "UNPRORATED"
    assert ticket["billing_status"] == "UNBILLED"
    assert ticket["last_run_type"] == "NONE"
    assert ticket["version"] == 1


def test_reading_an_unknown_ticket_id_is_a_not_found(api):
    """PRD §2.7: "**Path identifiers.** Every `id` embedded in the request path resolves to a
    stored row, checked strictly left to right, so an outer segment's failure is reported
    before an inner segment is even looked at. The code names the missing type:
    `ERR_CARRIER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
    `ERR_COUPON_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`,
    `ERR_MEMO_NOT_FOUND` or `ERR_SAMPLE_NOT_FOUND`, all HTTP 404. Applies to every operation
    carrying a path identifier."

    Design: Corner/entities/get_ticket_with_unknown_id_returns_not_found
    """
    resp = api.get_ticket(UNKNOWN_UUID, make_accountant_headers(UNKNOWN_UUID))
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_FOUND.value)
    assert resp.json()["response_type"] == "error"


def test_ticket_issue_without_total_fare_is_malformed(api):
    """PRD §2.7: "**Request shape.** Every required input field is present; every enum-typed
    field carries a declared member; every integer money, mileage and basis-point field is an
    integer inside its declared bounds; ISO 8601 datetime fields and `YYYY-MM-DD` date fields
    parse; `effective_to` is on or after `effective_from`; `period_end` is strictly after
    `period_start`; `from_currency` differs from `to_currency`; `limit` is between 1 and 100
    inclusive and `offset` is at least 0. Otherwise `ERR_INVALID_REQUEST` (400). Applies to
    every operation."

    Design: Corner/entities/ticket_creation_missing_total_fare_returns_invalid_request
    """
    aa = new_carrier("AA")
    payload = create_ticket_payload(aa["id"], "0031000000001", issue_date="2026-08-01T00:00:00Z")
    payload.pop("total_fare_minor")

    resp = api.create_ticket(payload, make_accountant_headers(aa["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    _rows, meta = validate_paginated(
        api.list_tickets(OPERATOR, params={"validating_carrier_id": aa["id"]})
    )
    assert meta["total_count"] == 0, f"no ticket should persist, got {meta['total_count']}"


def test_coupon_with_an_undeclared_cabin_is_malformed(api):
    """PRD §3.4: "Each names its `coupon_number`, which must equal the ticket's current
    `coupon_count` plus one — gaps and repeats are refused with `ERR_COUPON_SEQUENCE_INVALID`
    — its three-uppercase-letter `origin` and `destination` station codes, the
    `operating_carrier_id` of the airline that will actually fly the sector and bill for it,
    the `class_of_service` flown from `ECONOMY`, `PREMIUM`, `BUSINESS` and `FIRST`, and a
    strictly positive `tpm_miles` holding the ticketed point mileage of the sector."
    PRD §2.7: "**Request shape.** Every required input field is present; every enum-typed
    field carries a declared member; every integer money, mileage and basis-point field is an
    integer inside its declared bounds; ISO 8601 datetime fields and `YYYY-MM-DD` date fields
    parse; `effective_to` is on or after `effective_from`; `period_end` is strictly after
    `period_start`; `from_currency` differs from `to_currency`; `limit` is between 1 and 100
    inclusive and `offset` is at least 0. Otherwise `ERR_INVALID_REQUEST` (400). Applies to
    every operation."

    Design: Corner/entities/coupon_creation_with_invalid_enum_class_returns_invalid_request
    """
    aa, bb = setup_two_carriers()
    ticket = new_ticket(aa["id"], "0032000000001", issue_date="2026-08-01T00:00:00Z")

    resp = api.create_coupon(
        ticket["id"],
        create_coupon_payload(bb["id"], 1, class_of_service="SUPER_SAVER"),
        make_accountant_headers(aa["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    unchanged = read_ticket(ticket["id"])
    assert unchanged["coupon_count"] == 0
    assert unchanged["version"] == 1


def test_coupon_number_must_be_the_next_in_sequence(api):
    """PRD §2.7: "**Coupon sequence.** `coupon_number` equals the ticket's current
    `coupon_count` plus 1 — otherwise `ERR_COUPON_SEQUENCE_INVALID` (422). Applies to coupon
    append."

    Design: Corner/validations/coupon_number_out_of_sequence_returns_sequence_invalid
    """
    aa, bb = setup_two_carriers()
    ticket = new_ticket(aa["id"], "0045000000001")

    resp = api.create_coupon(
        ticket["id"], create_coupon_payload(bb["id"], 3), make_accountant_headers(aa["id"])
    )
    validate_error(resp, ApiErrorId.ERR_COUPON_SEQUENCE_INVALID.value)

    unchanged = read_ticket(ticket["id"])
    assert unchanged["coupon_count"] == 0
    assert unchanged["version"] == 1
    _rows, meta = validate_paginated(
        api.list_coupons(OPERATOR, params={"ticket_id": ticket["id"]})
    )
    assert meta["total_count"] == 0


def test_new_rows_start_in_their_declared_initial_states(api):
    """PRD §3.4: "A fresh coupon opens in `coupon_status` `OPEN`, with `weight_units`,
    `allocated_amount_minor`, `ffp_miles_awarded`, `ffp_accrual_cost_minor` and
    `adjusted_amount_minor` at zero, `allocation_basis` of `UNALLOCATED`, `ffp_tier` of
    `NONE`, and both `flown_at` and `billing_invoice_id` null."
    PRD §3.4: "Appending bumps the ticket's `coupon_count` and its `version`."

    Design: Corner/state_machines/new_ticket_and_coupon_start_in_their_declared_initial_states
    """
    aa, bb = setup_two_carriers()
    assert read_carrier(aa["id"])["status"] == "ACTIVE"
    assert read_carrier(bb["id"])["status"] == "ACTIVE"

    ticket = new_ticket(aa["id"], "0035000000001", issue_date="2026-08-01T00:00:00Z")
    assert ticket["proration_status"] == "UNPRORATED"
    assert ticket["billing_status"] == "UNBILLED"

    coupon = validate_success(
        api.create_coupon(
            ticket["id"], create_coupon_payload(bb["id"], 1), make_accountant_headers(aa["id"])
        ),
        201,
    )
    assert_coupon(coupon)
    assert coupon["coupon_status"] == "OPEN"
    assert coupon["flown_at"] is None
    assert coupon["ffp_tier"] == "NONE"
    assert coupon["allocation_basis"] == "UNALLOCATED"
    assert coupon["allocated_amount_minor"] == 0
    assert coupon["billing_invoice_id"] is None

    bumped = read_ticket(ticket["id"])
    assert bumped["coupon_count"] == 1
    assert bumped["version"] == 2, "appending a coupon bumps the ticket's version"


def test_flying_an_already_flown_coupon_is_refused_and_books_no_second_accrual(api):
    """PRD §2.7: "**Coupon state.** The coupon is `OPEN` — otherwise
    `ERR_COUPON_STATE_INVALID` (409). Applies to coupon fly and coupon void."
    PRD §3.4: "The miles the passenger earns on the sector are `ffp_miles_awarded`, computed
    as the sector's `tpm_miles` multiplied by the cabin's earning multiplier and divided by
    10000, rounded half up."
    PRD §3.4: "The multipliers are 5000 basis points for `ECONOMY`, 10000 for `PREMIUM`, 15000
    for `BUSINESS` and 20000 for `FIRST` — in plain terms, economy earns half a mile per
    ticketed mile, premium economy earns mile for mile, business earns one and a half, and
    first earns double."
    PRD §3.4: "The chosen tier is stamped onto the coupon as `ffp_tier`, and
    `ffp_accrual_cost_minor` is the coupon's `ffp_miles_awarded` multiplied by the tier's
    per-thousand rate and divided by 1000, rounded half up."

    Design: Corner/state_machines/flying_an_already_flown_coupon_returns_coupon_state_invalid
    """
    aa, bb = setup_two_carriers()
    _ticket, coupons = setup_ticket_with_coupons(
        aa["id"],
        [{"operating_carrier_id": bb["id"], "class_of_service": "FIRST", "tpm_miles": 5000}],
        ticket_number="0034000000001",
    )
    fly(coupons[0]["id"], aa["id"])

    resp = api.fly_coupon(coupons[0]["id"], make_accountant_headers(aa["id"]))
    validate_error(resp, ApiErrorId.ERR_COUPON_STATE_INVALID.value)

    coupon = read_coupon(coupons[0]["id"])
    assert coupon["ffp_miles_awarded"] == 10000, "5000 FIRST-class miles earn double"
    assert coupon["ffp_accrual_cost_minor"] == 14000, "10000 miles at the TIER_A rate of 1400"
    carrier = read_carrier(bb["id"])
    assert carrier["period_accrued_miles"] == 10000, "the accrual is booked exactly once"
    assert carrier["period_ffp_cost_estimate_minor"] == 14000


def test_coupon_listing_filters_by_operating_carrier_and_paginates(api):
    """PRD §3.4: "Coupons may be listed filtered by `ticket_id`, by `operating_carrier_id`, by
    `billing_invoice_id` or by `coupon_status`."
    PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` echoed back as
    applied, `total_count` giving the number of rows matching the filter before the window was
    applied, and `has_more` set true exactly when `offset` plus the number of returned rows is
    still less than `total_count`."

    Design: Corner/endpoints/coupon_list_filters_by_operating_carrier_and_paginates
    """
    set_clock("2026-08-10T00:00:00Z")
    aa = new_carrier("AA")
    bb = new_carrier("BB")
    cc = new_carrier("CC")
    _ticket, coupons = setup_ticket_with_coupons(
        aa["id"],
        [
            {"operating_carrier_id": bb["id"], "origin": "JFK", "destination": "BOS",
             "class_of_service": "ECONOMY", "tpm_miles": 100},
            {"operating_carrier_id": cc["id"], "origin": "BOS", "destination": "YUL",
             "class_of_service": "ECONOMY", "tpm_miles": 100},
            {"operating_carrier_id": bb["id"], "origin": "YUL", "destination": "CDG",
             "class_of_service": "BUSINESS", "tpm_miles": 333},
        ],
        ticket_number="0058000000001",
    )

    rows, meta = validate_paginated(
        api.list_coupons(
            OPERATOR, params={"operating_carrier_id": bb["id"], "limit": 2, "offset": 0}
        )
    )
    assert meta["total_count"] == 2, f"BB operates two coupons, got {meta['total_count']}"
    assert meta["has_more"] is False
    assert meta["limit"] == 2 and meta["offset"] == 0
    returned = {r["id"] for r in rows}
    assert returned == {coupons[0]["id"], coupons[2]["id"]}
    assert coupons[1]["id"] not in returned, "the CC coupon must be filtered out"

    rows, meta = validate_paginated(
        api.list_coupons(
            OPERATOR, params={"operating_carrier_id": bb["id"], "limit": 1, "offset": 0}
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(rows) == 1


# --------------------------------------------------------------------------- #
# Mileage tier boundary
# --------------------------------------------------------------------------- #
def _two_first_class_coupons():
    set_clock("2026-08-10T00:00:00Z")
    aa, bb = setup_two_carriers()
    _ticket, coupons = setup_ticket_with_coupons(
        aa["id"],
        [
            {"operating_carrier_id": bb["id"], "origin": "JFK", "destination": "LHR",
             "class_of_service": "FIRST", "tpm_miles": 5000},
            {"operating_carrier_id": bb["id"], "origin": "LHR", "destination": "JFK",
             "class_of_service": "FIRST", "tpm_miles": 5000},
        ],
        ticket_number="0025000000001",
    )
    return aa, bb, coupons


def test_second_coupon_at_exactly_ten_thousand_accrued_miles_is_tier_b(api):
    """PRD §3.4: "What those miles *cost* depends on how many miles the operating carrier has
    already accrued this settlement period, and the tier is read from the carrier's running
    `period_accrued_miles` **as it stands before this coupon's miles are added**."
    PRD §3.4: "Below 10000 accumulated miles the coupon is costed at `TIER_A`, 1400 minor
    units per thousand miles. From 10000 up to but not including 40000 it is costed at
    `TIER_B`, 1150 per thousand. At 40000 and above it is costed at `TIER_C`, 900 per thousand."
    PRD §3.4: "The multipliers are 5000 basis points for `ECONOMY`, 10000 for `PREMIUM`, 15000
    for `BUSINESS` and 20000 for `FIRST` — in plain terms, economy earns half a mile per
    ticketed mile, premium economy earns mile for mile, business earns one and a half, and
    first earns double."

    Design: Difficulty/boundary_precision_check/ffp_tier_flips_at_exactly_ten_thousand_cumulative_miles
    """
    aa, bb, coupons = _two_first_class_coupons()
    fly(coupons[0]["id"], aa["id"])
    assert read_carrier(bb["id"])["period_accrued_miles"] == 10000, (
        "the first FIRST-class 5000-mile sector awards exactly 10000 miles"
    )

    second = validate_success(
        api.fly_coupon(coupons[1]["id"], make_accountant_headers(aa["id"])), 200
    )
    assert second["ffp_miles_awarded"] == 10000
    assert second["ffp_tier"] == "TIER_B", (
        "at exactly 10000 accrued miles the TIER_A band is already left behind"
    )
    assert second["ffp_accrual_cost_minor"] == 11500, (
        "10000 miles at 1150 per thousand, not the 14000 a TIER_A reading would give"
    )


def test_earlier_coupon_keeps_its_tier_a_estimate_after_the_tier_flips(api):
    """PRD §3.4: "Only then are the coupon's miles added to the operating carrier's
    `period_accrued_miles`, and its `ffp_accrual_cost_minor` added to that carrier's
    `period_ffp_cost_estimate_minor`."
    PRD §3.4: "Because the tier is read before the addition, coupons flown early in a period
    are costed at a rate at least as high as those flown later — the bill gets cheaper as the
    partner flies more, and the estimate as a whole is therefore systematically conservative
    until it is trued up at period close."

    Design: Difficulty/boundary_precision_check/ffp_tier_flips_at_exactly_ten_thousand_cumulative_miles
    """
    aa, bb, coupons = _two_first_class_coupons()
    fly(coupons[0]["id"], aa["id"])
    fly(coupons[1]["id"], aa["id"])

    first = read_coupon(coupons[0]["id"])
    assert first["ffp_tier"] == "TIER_A"
    assert first["ffp_accrual_cost_minor"] == 14000, "the earlier estimate is never restated"

    carrier = read_carrier(bb["id"])
    assert carrier["period_accrued_miles"] == 20000
    assert carrier["period_ffp_cost_estimate_minor"] == 25500, "14000 + 11500"


# --------------------------------------------------------------------------- #
# Operating-carrier standing gates the fly
# --------------------------------------------------------------------------- #
def _open_coupon_with_suspended_operator(api):
    set_clock("2026-08-10T00:00:00Z")
    aa, bb = setup_two_carriers()
    _ticket, coupons = setup_ticket_with_coupons(
        aa["id"],
        [{"operating_carrier_id": bb["id"]}],
        ticket_number="0027000000001",
    )
    validate_success(api.suspend_carrier(bb["id"], OPERATOR), 200)
    return aa, bb, coupons[0]


def test_fly_is_refused_while_the_operating_carrier_is_suspended(api):
    """PRD §3.1: "Separately, a coupon may not be marked flown while the carrier that actually
    operates it is suspended, which is refused with the distinct code
    `ERR_OPERATING_CARRIER_SUSPENDED`."
    PRD §3.4: "Marking a coupon flown is likewise reserved to the `RevenueAccountant` of the
    ticket's `validating_carrier_id`, requires the coupon to be `OPEN`, and requires the
    coupon's `operating_carrier_id` to name an `ACTIVE` carrier."

    Design: Difficulty/cross_entity_state_dependency/coupon_fly_gated_on_operating_carrier_standing
    """
    aa, _bb, coupon = _open_coupon_with_suspended_operator(api)

    resp = api.fly_coupon(coupon["id"], make_accountant_headers(aa["id"]))
    validate_error(resp, ApiErrorId.ERR_OPERATING_CARRIER_SUSPENDED.value)

    unchanged = read_coupon(coupon["id"])
    assert unchanged["coupon_status"] == "OPEN"
    assert unchanged["flown_at"] is None
    assert read_carrier(aa["id"])["status"] == "ACTIVE", (
        "the acting validating carrier's own standing was never the problem"
    )


def test_refused_fly_books_no_mileage_accrual_on_the_operating_carrier(api):
    """PRD §2.7: "**Operating carrier in good standing.** The coupon's `operating_carrier_id`
    names an `ACTIVE` carrier — otherwise `ERR_OPERATING_CARRIER_SUSPENDED` (409). Applies to
    coupon fly."
    PRD §2.7: "When a request violates more than one rule, the response is decided by the
    **first** rule that fails in the ordering below, and no side effect of the request has
    been applied when it does."

    Design: Difficulty/cross_entity_state_dependency/coupon_fly_gated_on_operating_carrier_standing
    """
    aa, bb, coupon = _open_coupon_with_suspended_operator(api)

    validate_error(
        api.fly_coupon(coupon["id"], make_accountant_headers(aa["id"])),
        ApiErrorId.ERR_OPERATING_CARRIER_SUSPENDED.value,
    )

    stale = read_coupon(coupon["id"])
    assert stale["ffp_miles_awarded"] == 0
    assert stale["ffp_tier"] == "NONE"
    assert stale["ffp_accrual_cost_minor"] == 0

    operator_carrier = read_carrier(bb["id"])
    assert operator_carrier["period_accrued_miles"] == 0
    assert operator_carrier["period_ffp_cost_estimate_minor"] == 0
