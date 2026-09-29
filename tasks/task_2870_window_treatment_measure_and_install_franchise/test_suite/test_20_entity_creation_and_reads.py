"""Creation, read-back and listing of the rows the rest of the domain stands on."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CONSULTATION_NOT_FOUND,
    ERR_DESIGNER_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LEAD_NOT_FOUND,
    ERR_OPENING_NOT_FOUND,
    ERR_VALUE_OUT_OF_RANGE,
)
from test_helpers.assertions import (
    assert_eighth_multiple,
    assert_identity,
    assert_immutable_ledger_row,
    assert_inches_equal,
    assert_instant_equals,
    assert_instant_millis_format,
    assert_ledger_entry,
    assert_no_such_field,
    assert_page_meta,
    assert_versioned_resource,
)
from test_helpers.constants import DEFAULT_LIMIT
from test_helpers.fixtures import (
    CLOCK_START,
    accept_quote,
    book_consultation,
    build_quote,
    charter_territory,
    configure_opening,
    hire_designer,
    intake_lead,
    present_quote,
    record_opening,
)
from test_helpers.test_users import designer_headers, franchisee_headers, franchisor_headers

MISSING_ID = "00000000-0000-4000-8000-000000000000"

TERRITORY_COUNTERS = (
    "open_leads_count",
    "net_sales_cents",
    "royalty_accrued_cents",
    "remake_chargeback_cents",
    "open_order_exposure_cents",
    "available_kit_count",
    "on_loan_kit_count",
    "lost_kit_count",
)

DESIGNER_COUNTERS = (
    "remeasure_exception_count",
    "late_sample_return_count",
    "clean_install_count",
)


def test_a_charter_answers_with_every_declared_field_at_its_start_value(api):
    """All four commercial terms echo back, and all eight derived figures read zero.

    "A newly chartered territory is stamped `ACTIVE`, and every derived figure on it
    starts at zero — `open_leads_count`, `net_sales_cents`, `royalty_accrued_cents`,
    `remake_chargeback_cents`, `open_order_exposure_cents`, `available_kit_count`,
    `on_loan_kit_count` and `lost_kit_count`."

    "Every resource the API mints carries an `id` that is a server-generated UUID
    string with no type prefix."

    Design: Corner/entities/territory_creation_returns_every_declared_field_at_its_start_value
    """
    payload = f.territory_payload(legal_name="Northgate Blinds LLC",
                                  postal_codes=["30301", "30302"],
                                  royalty_rate_pct=0.0625,
                                  lead_capacity_per_week=7,
                                  credit_limit_cents=750000,
                                  liability_window="LIFETIME")
    territory = validate_success(api.create_territory(
        payload, franchisor_headers()), 201)

    assert territory["legal_name"] == "Northgate Blinds LLC"
    assert territory["postal_codes"] == ["30301", "30302"]
    assert territory["royalty_rate_pct"] == 0.0625
    assert territory["lead_capacity_per_week"] == 7
    assert territory["credit_limit_cents"] == 750000
    assert territory["liability_window"] == "LIFETIME"

    assert territory["status"] == "ACTIVE"
    for counter in TERRITORY_COUNTERS:
        assert territory[counter] == 0, f"{counter} must start at zero"

    assert_versioned_resource(territory, "territory", version=1)
    assert_instant_equals(territory["updated_at"], territory["created_at"],
                          "territory.updated_at")
    assert_instant_millis_format(territory["created_at"],
                                 "territory.created_at")


def test_reading_a_designer_back_repeats_the_creation_response(api):
    """A read is not a mutation: the GET body matches the POST body field for field.

    "A new designer is stamped `ACTIVE` with `remeasure_liability_score` at the base
    value of 100 and all three incident counters — `remeasure_exception_count`,
    `late_sample_return_count` and `clean_install_count` — at zero."

    "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant in the
    same format that is refreshed on every mutation, and `version`, an integer that
    starts at 1 on creation and increments by one on every mutation of the row."

    Design: Corner/entities/designer_read_back_is_byte_identical_to_the_create_response
    """
    territory = charter_territory(api)
    owner = franchisee_headers(territory["id"])
    created = validate_success(api.create_designer(
        f.designer_payload(territory["id"], full_name="Dana Reed",
                           home_postal_code="30301",
                           certifications=["MOTORIZATION", "CHILD_SAFETY"]),
        owner), 201)

    assert created["status"] == "ACTIVE"
    assert created["remeasure_liability_score"] == 100
    assert created["certifications"] == ["MOTORIZATION", "CHILD_SAFETY"]
    for counter in DESIGNER_COUNTERS:
        assert created[counter] == 0, f"{counter} must start at zero"
    assert_versioned_resource(created, "designer", version=1)

    read_back = validate_success(api.get_designer(created["id"], owner))
    assert read_back == created

    # A second read still does not bump the row.
    assert validate_success(api.get_designer(created["id"], owner))["version"] == 1


def test_the_designer_listing_filters_by_territory_and_pages(api):
    """Three designers in one territory and one next door: 2 + 1 rows against total 3.

    "Both are echoed back in `meta`, alongside `total_count` (the number of rows
    matching the request's filters before pagination is applied) and `has_more` (true
    when rows remain beyond the current page)."

    "Filter parameters on list endpoints are query-string parameters and combine
    conjunctively: a request supplying both a territory filter and a status filter
    returns only rows matching both."

    Design: Corner/entities/designer_listing_filters_by_territory_and_pages_with_total_count
    """
    home = charter_territory(api, postal_codes=["30301"])
    neighbour = charter_territory(api, legal_name="Southgate Blinds LLC",
                                  postal_codes=["30401"])
    hire_designer(api, home, full_name="Dana Reed")
    hire_designer(api, home, full_name="Milo Vance")
    hire_designer(api, home, full_name="Ines Park")
    hire_designer(api, neighbour, full_name="Bo Chen",
                  home_postal_code="30401")
    owner = franchisee_headers(home["id"])

    first_page, first_meta = validate_paginated(api.list_designers(
        owner, territory_id=home["id"], limit=2, offset=0))
    assert len(first_page) == 2
    assert_page_meta(first_meta, total_count=3, has_more=True, limit=2, offset=0)
    assert all(row["territory_id"] == home["id"] for row in first_page)

    second_page, second_meta = validate_paginated(api.list_designers(
        owner, territory_id=home["id"], limit=2, offset=2))
    assert len(second_page) == 1
    assert_page_meta(second_meta, total_count=3, has_more=False, limit=2, offset=2)

    everyone, everyone_meta = validate_paginated(
        api.list_designers(franchisor_headers()))
    assert len(everyone) == 4
    assert_page_meta(everyone_meta, total_count=4, has_more=False,
                     limit=DEFAULT_LIMIT, offset=0)


def test_omitted_optional_inputs_land_on_their_declared_defaults(api):
    """A minimal charter, a minimal hire and a minimal intake fill themselves in.

    "Four commercial terms may be supplied and each has a default:
    `royalty_rate_pct`, the fraction of net sales owed to headquarters, defaults to
    0.055 and may not be negative nor exceed 0.15, with at most four decimal places;
    `lead_capacity_per_week`, the number of live leads the territory may hold at
    once, defaults to 5 and must be at least 1; `credit_limit_cents`, the ceiling on
    the territory's open manufacturing exposure, defaults to twenty thousand dollars
    expressed as 2000000 cents and may not be negative; and `liability_window`, which
    is either `ROLLING_180D` or `LIFETIME` and defaults to `ROLLING_180D`."

    "A designer is created with a `territory_id`, a `full_name` of between 1 and 120
    characters, a `home_postal_code` of exactly five digits, and an optional
    `certifications` array defaulting to empty, whose members are drawn without
    duplication from `MOTORIZATION`, `CHILD_SAFETY` and `COMMERCIAL`."

    "A lead carries a `customer_name` of 1 to 120 characters, a `postal_code` of
    exactly five digits, a `source` that is one of `NATIONAL_CALL_CENTER`,
    `WEB_FORM`, `REFERRAL` or `WALK_IN`, a `requested_at` instant stating the
    earliest date the homeowner wants a visit, and an optional
    `child_occupied_dwelling` boolean defaulting to false."

    Design: Corner/entities/unsupplied_optional_inputs_fall_back_to_their_declared_defaults
    """
    territory = validate_success(api.create_territory(
        {"legal_name": "Northgate Blinds LLC", "postal_codes": ["30301"]},
        franchisor_headers()), 201)
    assert territory["royalty_rate_pct"] == 0.055
    assert territory["lead_capacity_per_week"] == 5
    assert territory["credit_limit_cents"] == 2000000
    assert territory["liability_window"] == "ROLLING_180D"
    assert territory["status"] == "ACTIVE"

    owner = franchisee_headers(territory["id"])
    designer = validate_success(api.create_designer(
        {"territory_id": territory["id"], "full_name": "Dana Reed",
         "home_postal_code": "30301"}, owner), 201)
    assert designer["certifications"] == []

    lead = validate_success(api.create_lead(
        {"customer_name": "Ana Ruiz", "postal_code": "30301",
         "source": "WEB_FORM", "requested_at": "2026-08-01T08:00:00.000Z"},
        owner), 201)
    assert lead["child_occupied_dwelling"] is False
    assert lead["status"] == "ROUTED"
    assert lead["territory_id"] == territory["id"]


def test_the_caller_cannot_inject_geometry_or_price_onto_an_opening(api):
    """Six readings decide the cut list; the numbers the client sent are ignored.

    "The finished dimensions the vendor will cut to are **derived here and never
    supplied by the caller**."

    "Fields the server owns — anything described in this document as derived,
    computed or system-stamped — are **silently ignored** when a client supplies
    them, never rejected."

    "A newly recorded opening is stamped with `measure_status` `MEASURED`,
    `install_outcome` `PENDING`, `credited` false, `list_price_cents` zero and
    `billable_sqft` zero, and with `quote_id`, `fabric_code` and `lift_system` all
    null."

    Design: Corner/entities/opening_geometry_and_price_are_computed_and_caller_values_are_impossible_to_inject
    """
    territory = charter_territory(api)
    designer = hire_designer(api, territory)
    lead = intake_lead(api, territory)
    consultation = book_consultation(api, designer, lead)

    payload = f.opening_payload(consultation["id"], label="Den window",
                                room_type="OFFICE", mount_type="INSIDE",
                                width_top_in=24.000, width_middle_in=24.000,
                                width_bottom_in=24.000,
                                height_left_in=48.000, height_center_in=48.500,
                                height_right_in=48.000, depth_in=3.000)
    payload.update({"ordered_width_in": 99.000, "ordered_height_in": 99.000,
                    "out_of_square_in": 0.000, "billable_sqft": 99.00,
                    "list_price_cents": 123456, "measure_status": "QUOTED",
                    "install_outcome": "INSTALLED", "credited": True})
    opening = validate_success(api.create_opening(
        payload, designer_headers(designer["id"])), 201)

    assert_identity(opening, "opening")
    assert_inches_equal(opening["out_of_square_in"], 0.500, "out_of_square_in")
    assert_inches_equal(opening["ordered_width_in"], 23.500, "ordered_width_in")
    assert_inches_equal(opening["ordered_height_in"], 47.750, "ordered_height_in")
    assert_eighth_multiple(opening["ordered_width_in"], "ordered_width_in")
    assert_eighth_multiple(opening["ordered_height_in"], "ordered_height_in")
    assert opening["measure_status"] == "MEASURED"
    assert opening["install_outcome"] == "PENDING"
    assert opening["credited"] is False
    assert opening["list_price_cents"] == 0
    assert opening["billable_sqft"] == 0
    assert opening["quote_id"] is None
    assert opening["fabric_code"] is None
    assert opening["lift_system"] is None

    priced = configure_opening(api, designer, opening, fabric_code="LT-SHEER",
                               lift_system="CORDED", motorization_option="NONE")
    assert priced["measure_status"] == "CONFIGURED"
    assert priced["billable_sqft"] == 8.000
    assert priced["list_price_cents"] == 4960
    # Pricing re-reads the geometry; it never re-derives or disturbs it.
    assert_inches_equal(priced["ordered_width_in"], 23.500, "ordered_width_in")
    assert_inches_equal(priced["ordered_height_in"], 47.750, "ordered_height_in")
    assert_inches_equal(priced["out_of_square_in"], 0.500, "out_of_square_in")


def test_body_foreign_keys_are_resolved_in_their_declared_order(api):
    """Two bad ids on one booking report the lead, and a bad supersession reports the opening.

    "**Body reference existence** — every foreign key carried in the request body must
    resolve, validated in the order the fields are declared for that endpoint,
    returning the matching not-found error."

    "Consultation booking, for example, resolves the lead before the designer, so a
    request naming two bad ids reports the lead."

    "When `replaces_opening_id` is supplied it must resolve to an existing opening —
    an unresolvable id is `ERR_OPENING_NOT_FOUND` — and that opening must belong to
    the same consultation, or the request fails with `ERR_OPENING_NOT_ON_QUOTE`."

    Design: Corner/entities/body_foreign_keys_are_resolved_in_the_declared_input_order
    """
    territory = charter_territory(api)
    designer = hire_designer(api, territory)
    lead = intake_lead(api, territory)
    dsg = designer_headers(designer["id"])

    validate_error(api.create_consultation(
        f.consultation_payload(MISSING_ID, MISSING_ID), dsg),
        ERR_LEAD_NOT_FOUND, 404)
    validate_error(api.create_consultation(
        f.consultation_payload(lead["id"], MISSING_ID), dsg),
        ERR_DESIGNER_NOT_FOUND, 404)

    consultation = book_consultation(api, designer, lead)
    validate_error(api.create_opening(
        f.opening_payload(MISSING_ID), dsg), ERR_CONSULTATION_NOT_FOUND, 404)
    validate_error(api.create_opening(
        f.opening_payload(consultation["id"], replaces_opening_id=MISSING_ID),
        dsg), ERR_OPENING_NOT_FOUND, 404)

    # None of the four refusals wrote a row.
    _bookings, booking_meta = validate_paginated(api.list_consultations(
        dsg, designer_id=designer["id"]))
    assert_page_meta(booking_meta, total_count=1)
    _openings, opening_meta = validate_paginated(api.list_openings(
        dsg, consultation_id=consultation["id"]))
    assert_page_meta(opening_meta, total_count=0)


def test_shape_breaches_and_domain_breaches_carry_different_error_ids(api):
    """An undeclared enum and a malformed instant are 400; four out-of-domain numbers are 422.

    "**Request shape** — `ERR_INVALID_REQUEST` (HTTP 400) on every write endpoint when a
    required field is missing, a field carries the wrong JSON type, an enum value is
    not a declared member, an instant is not a valid ISO 8601 UTC string, or an array
    breaches its declared cardinality or contains duplicates."

    "**Numeric and interval domains** — `ERR_VALUE_OUT_OF_RANGE` (HTTP 422). Each of the
    six wall readings and the pocket depth must be strictly greater than zero, at
    most 300.000, and carry at most three decimal places. A royalty rate must be at
    least 0 and at most 0.15. A vendor cutoff hour must be between 0 and 23
    inclusive. Every capacity and count input must be at least 1. A scheduled end
    instant must be strictly after its start instant; a hold end instant must be
    strictly after its hold start instant and no more than fourteen days after it; a
    hold start instant must be at or after the logical clock."

    Design: Corner/entities/enum_and_numeric_domain_breaches_split_across_two_error_ids
    """
    territory = charter_territory(api)
    designer = hire_designer(api, territory)
    lead = intake_lead(api, territory)
    consultation = book_consultation(api, designer, lead)
    owner = franchisee_headers(territory["id"])
    dsg = designer_headers(designer["id"])

    validate_error(api.create_opening(
        f.opening_payload(consultation["id"], room_type="SUNROOM"), dsg),
        ERR_INVALID_REQUEST, 400)
    validate_error(api.create_lead(
        f.lead_payload(customer_name="Bo Chen",
                       requested_at="2026-08-01 08:00:00"), owner),
        ERR_INVALID_REQUEST, 400)

    validate_error(api.create_opening(
        f.opening_payload(consultation["id"], width_top_in=0.000), dsg),
        ERR_VALUE_OUT_OF_RANGE, 422)
    validate_error(api.create_opening(
        f.opening_payload(consultation["id"], width_top_in=24.0001), dsg),
        ERR_VALUE_OUT_OF_RANGE, 422)
    validate_error(api.create_consultation(
        f.consultation_payload(lead["id"], designer["id"],
                               scheduled_start_at="2026-08-06T14:00:00.000Z",
                               scheduled_end_at="2026-08-06T14:00:00.000Z"),
        dsg), ERR_VALUE_OUT_OF_RANGE, 422)
    validate_error(api.create_territory(
        f.territory_payload(legal_name="Overreach Blinds LLC",
                            postal_codes=["30501"], royalty_rate_pct=0.1501),
        franchisor_headers()), ERR_VALUE_OUT_OF_RANGE, 422)

    _rows, meta = validate_paginated(api.list_openings(
        dsg, consultation_id=consultation["id"]))
    assert_page_meta(meta, total_count=0)


def test_a_missing_required_field_is_refused_before_the_depth_gate(api):
    """No `depth_in` is a shape error, not the inside-mount depth error.

    "**Request shape** — `ERR_INVALID_REQUEST` (HTTP 400) on every write endpoint when a
    required field is missing, a field carries the wrong JSON type, an enum value is
    not a declared member, an instant is not a valid ISO 8601 UTC string, or an array
    breaches its declared cardinality or contains duplicates."

    "An inside mount is refused outright when the pocket is too shallow to hold the
    headrail: `depth_in` must be at least 2.500 inches, and anything less is
    `ERR_INSUFFICIENT_MOUNT_DEPTH`."

    Design: Corner/entities/a_missing_required_field_is_refused_before_any_business_gate_runs
    """
    territory = charter_territory(api)
    designer = hire_designer(api, territory)
    lead = intake_lead(api, territory)
    consultation = book_consultation(api, designer, lead)
    dsg = designer_headers(designer["id"])

    incomplete = f.opening_payload(consultation["id"], mount_type="INSIDE")
    del incomplete["depth_in"]
    validate_error(api.create_opening(incomplete, dsg),
                   ERR_INVALID_REQUEST, 400)

    _rows, refused_meta = validate_paginated(api.list_openings(
        dsg, consultation_id=consultation["id"]))
    assert_page_meta(refused_meta, total_count=0)

    completed = dict(incomplete, depth_in=3.000)
    opening = validate_success(api.create_opening(completed, dsg), 201)
    assert opening["measure_status"] == "MEASURED"
    assert opening["mount_type"] == "INSIDE"
    assert_inches_equal(opening["depth_in"], 3.000, "depth_in")


def test_a_ledger_row_carries_no_version_and_no_updated_at(api):
    """The one accrual on the account is an immutable row of `id` and `created_at` only.

    "The single exception is `LedgerEntry`. A ledger row is immutable once written, so
    it carries only `id` and `created_at` — it has neither `updated_at` nor `version`,
    and neither field appears in its response body."

    "A ledger row names the `territory_id` it lands on, an `entry_type` drawn from
    `NET_SALES_ROYALTY`, `ROYALTY_REVERSAL`, `REMAKE_CHARGEBACK`,
    `REMEASURE_CHARGEBACK`, `SAMPLE_LATE_FEE` and `SAMPLE_REPLACEMENT`, a signed
    `amount_cents`, the `basis_cents` the amount was derived from (net sales for
    royalty rows, remake cost for chargeback rows, kit replacement value for sample
    rows), the `occurred_at` logical instant of the triggering transition, and a fixed
    machine-readable `memo` naming that transition — `quote_accepted`,
    `install_trueup`, `remake_replacement`, `remake_full_credit`, `sample_late`,
    `sample_lost` or `remeasure_chargeback`."

    Design: Corner/entities/ledger_entries_are_immutable_rows_with_no_version_and_no_write_endpoint
    """
    territory = charter_territory(api, royalty_rate_pct=0.055)
    designer = hire_designer(api, territory)
    lead = intake_lead(api, territory)
    consultation = book_consultation(api, designer, lead)
    opening = record_opening(api, designer, consultation,
                             label="Den window", room_type="OFFICE")
    configure_opening(api, designer, opening, fabric_code="LT-SHEER",
                      lift_system="CORDLESS", motorization_option="NONE")
    quote = build_quote(api, designer, consultation)
    present_quote(api, designer, quote)
    accepted = accept_quote(api, designer, quote)
    assert accepted["net_sales_cents"] == 6760

    owner = franchisee_headers(territory["id"])
    rows, meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner))
    assert_page_meta(meta, total_count=1, has_more=False)
    row = rows[0]
    assert_ledger_entry(row, "NET_SALES_ROYALTY", 372, 6760, "quote_accepted",
                        "QUOTE", source_entity_id=quote["id"],
                        territory_id=territory["id"])
    assert_immutable_ledger_row(row)
    assert_no_such_field(row, "updated_at", "version")
    assert_instant_equals(row["occurred_at"], CLOCK_START,
                          "ledger entry.occurred_at")

    filtered, filtered_meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner, entry_type="ROYALTY_REVERSAL"))
    assert filtered == []
    assert_page_meta(filtered_meta, total_count=0, has_more=False)

    # The filtered read did not disturb the row it excluded.
    again, again_meta = validate_paginated(api.list_ledger_entries(
        territory["id"], owner))
    assert_page_meta(again_meta, total_count=1)
    assert again[0] == row
