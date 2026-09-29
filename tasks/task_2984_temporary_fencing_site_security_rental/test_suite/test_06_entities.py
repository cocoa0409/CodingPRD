"""Resource shape, defaults, identity and reference resolution.

Covers the housekeeping contract of PRD §2.4, the envelope and pagination rules
of PRD §2.2 and §2.3, the declared defaults of PRD §3.1 and §3.2, and the shape
and resolution rungs of PRD §2.7 that decide what a malformed or dangling
request is answered with.
"""

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_success,
)

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_ACCOUNT_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_CREW_NOT_FOUND,
    ERR_JOBSITE_NOT_FOUND,
    ERR_MUNICIPALITY_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_cents,
    assert_envelope_meta,
    assert_fleet_counts,
    assert_freshly_created,
    assert_instant_is_utc,
    assert_integer,
    ids_of,
)

#: Syntactically valid UUIDs that name no stored row of any type.
UNKNOWN_CONTRACT_ID = "3f1c9a52-0000-4c0a-9c2e-000000000999"
UNKNOWN_JOBSITE_ID = "7c2b1d40-0000-4a11-8b3d-000000000111"
UNKNOWN_ACCOUNT_ID = "9a4d2f10-0000-4b22-9d44-000000000222"
UNKNOWN_MUNICIPALITY_ID = "9a4d2f10-0000-4b22-9d44-000000000333"
UNKNOWN_CREW_ID = "9a4d2f10-0000-4b22-9d44-000000000444"


def test_creating_a_jurisdiction_returns_every_declared_field(api):
    """PRD §4: "Creation endpoints — the eight `POST` routes that mint a new
    row ... answer `201`" and PRD §2.2: "Every response body ... carries exactly
    three top-level keys: `meta`, `response_type` and `data`."

    Design: Corner/entities/create_municipality_returns_every_declared_field
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)

    response = api.create_municipality(F.municipality_payload(), U.PLATFORM_ADMIN)
    municipality = validate_success(response, expected_status=201)

    body = response.json()
    assert body["response_type"] == "object", body
    assert isinstance(body["data"], dict), body
    assert_envelope_meta(body)

    assert municipality["name"] == "City of Harbor Point"
    assert municipality["jurisdiction_code"] == C.HRB_CODE
    assert_integer(
        municipality["permit_lead_time_days"],
        C.HRB_LEAD_TIME_DAYS,
        "permit_lead_time_days",
    )
    assert_integer(
        municipality["max_concurrent_closure_linear_feet"],
        C.HRB_MAX_CLOSURE_FT,
        "max_concurrent_closure_linear_feet",
    )
    assert_integer(
        municipality["rental_tax_rate_bp"], C.HRB_TAX_RATE_BP, "rental_tax_rate_bp"
    )
    assert_integer(
        municipality["permit_review_rounds_allowed"],
        C.HRB_REVIEW_ROUNDS,
        "permit_review_rounds_allowed",
    )
    assert municipality["allows_solid_wind_screen"] is True

    # PRD §3.1: the derived corridor counter starts empty.
    assert_integer(
        municipality["committed_closure_linear_feet"],
        0,
        "committed_closure_linear_feet",
    )
    assert_freshly_created(municipality)


def test_reading_a_product_returns_its_stored_data_and_seeded_fleet_counters(api):
    """PRD §3.1: "Registration seats the whole fleet in the yard: `available_count`
    opens equal to `owned_count`, and `reserved_count`, `deployed_count`,
    `damaged_count` and `lost_count` all open at zero."

    Design: Corner/entities/get_product_returns_stored_data_and_fleet_counters
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)
    panel = FX.seed_panel_product(api)

    stored = validate_success(api.get_product(panel["id"], U.DISPATCH_COORDINATOR))

    assert stored["code"] == C.PANEL_CODE
    assert stored["category"] == C.CATEGORY_FENCE_PANEL
    assert stored["description"] == "10 ft chain-link fence panel"
    assert_integer(stored["panel_length_ft"], C.PANEL_LENGTH_FT, "panel_length_ft")
    assert_cents(stored["unit_monthly_rate_cents"], 0, "unit_monthly_rate_cents")
    assert_cents(
        stored["replacement_cost_cents_per_unit"],
        C.PANEL_REPLACEMENT_CENTS,
        "replacement_cost_cents_per_unit",
    )
    assert_integer(stored["fleet_age_months"], C.PANEL_FLEET_AGE_MONTHS, "fleet_age_months")
    assert_integer(stored["wind_load_rating_mph"], 90, "wind_load_rating_mph")
    assert_integer(stored["owned_count"], C.PANEL_OWNED_COUNT, "owned_count")

    assert_fleet_counts(
        stored,
        available=C.PANEL_OWNED_COUNT,
        reserved=0,
        deployed=0,
        damaged=0,
        lost=0,
    )
    assert_freshly_created(stored)


def _page(response, expected_status=200):
    """A list response's rows and its ``meta`` block (PRD §2.3)."""
    rows = validate_success(response, expected_status=expected_status)
    body = response.json()
    assert body["response_type"] == "array", body
    assert isinstance(rows, list), body
    assert_envelope_meta(body)
    return rows, body["meta"]


def test_jobsites_filtered_by_account_paginate_with_a_filter_wide_total_count(api):
    """PRD §2.3: "`total_count` giving the number of rows matching the filters
    before the page window is applied, and `has_more` set to true exactly when
    rows matching the filters remain beyond the current page." The default page is
    "`limit` defaults to 10" at "`offset` ... default 0".

    Design: Corner/entities/list_jobsites_filtered_by_account_paginates_with_total_count
    """
    world = FX.seed_world(
        api,
        jobsite={
            "site_label": "Foundry Road Phase Yard",
            "address_line": "402 Foundry Road",
            "site_condition": C.CONDITION_SOIL,
            "phase_count": 4,
        },
    )
    account_a = world["account"]["id"]
    site_1 = world["jobsite"]
    site_2 = FX.add_jobsite(
        world,
        api,
        site_label="Dock Street Rebuild",
        address_line="8 Dock Street",
        site_condition=C.CONDITION_ASPHALT,
        phase_count=2,
    )
    site_3 = FX.add_jobsite(
        world,
        api,
        site_label="Mill Lane Culvert",
        address_line="77 Mill Lane",
        site_condition=C.CONDITION_CONCRETE,
        phase_count=1,
    )

    account_b = FX.seed_event_account(api)
    site_4 = FX.seed_jobsite(
        api,
        account_b["id"],
        world["municipality"]["id"],
        site_label="Quay Street Festival Lot",
        address_line="11 Quay Street",
    )

    first, first_meta = _page(
        api.list_jobsites(
            U.ACCOUNT_MANAGER,
            params={"customer_account_id": account_a, "limit": 2, "offset": 0},
        )
    )
    assert len(first) == 2, first
    assert_integer(first_meta["total_count"], 3, "total_count")
    assert first_meta["has_more"] is True
    assert_integer(first_meta["limit"], 2, "limit")
    assert_integer(first_meta["offset"], 0, "offset")

    second, second_meta = _page(
        api.list_jobsites(
            U.ACCOUNT_MANAGER,
            params={"customer_account_id": account_a, "limit": 2, "offset": 2},
        )
    )
    assert len(second) == 1, second
    assert_integer(second_meta["total_count"], 3, "total_count")
    assert second_meta["has_more"] is False
    assert_integer(second_meta["offset"], 2, "offset")

    # PRD §2.3 orders list results by created_at ascending, so the two pages
    # partition account A's three jobsites without repetition or loss.
    walked = ids_of(first) + ids_of(second)
    assert walked == [site_1["id"], site_2["id"], site_3["id"]], walked
    assert site_4["id"] not in walked

    other, other_meta = _page(
        api.list_jobsites(
            U.ACCOUNT_MANAGER, params={"customer_account_id": account_b["id"]}
        )
    )
    assert len(other) == 1, other
    assert other[0]["id"] == site_4["id"]
    assert_integer(other_meta["total_count"], 1, "total_count")
    assert other_meta["has_more"] is False
    assert_integer(other_meta["limit"], C.DEFAULT_LIMIT, "limit")
    assert_integer(other_meta["offset"], 0, "offset")


def test_reading_a_contract_by_an_unknown_uuid_is_not_found(api):
    """PRD §2.7: "A path identifier that resolves to no stored row is rejected
    with the not-found error of that path's own type" and PRD §5 pairs
    `ERR_CONTRACT_NOT_FOUND` with HTTP 404.

    Design: Corner/entities/get_contract_with_unknown_uuid_not_found
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)

    response = api.get_contract(UNKNOWN_CONTRACT_ID, U.ACCOUNT_MANAGER)
    validate_error(response, ERR_CONTRACT_NOT_FOUND, 404)

    body = response.json()
    assert body["response_type"] == "error", body
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
    assert_envelope_meta(body)


def test_omitting_a_required_field_is_a_shape_failure_that_persists_nothing(api):
    """PRD §2.7: "A request whose body is not well-formed for its endpoint is
    rejected with `ERR_VALIDATION` ... a required input field is absent". PRD §3.2
    requires `linear_feet` on a quote and PRD §3.1 requires a jobsite's
    `site_condition`, for which no default is declared.

    Design: Corner/entities/create_quote_missing_required_linear_feet_rejected
    """
    world = FX.seed_world(api, jobsite={"phase_count": 4})
    jobsite_id = world["jobsite"]["id"]
    assert_integer(world["jobsite"]["version"], 1, "version")

    quote_body = F.quote_payload(world["jobsite"]["version"])
    del quote_body["linear_feet"]
    validate_error(
        api.create_quote(jobsite_id, quote_body, U.ACCOUNT_MANAGER), ERR_VALIDATION, 400
    )

    jobsite_body = F.jobsite_payload(
        world["account"]["id"],
        world["municipality"]["id"],
        site_label="Dock Street Rebuild",
        address_line="8 Dock Street",
    )
    del jobsite_body["site_condition"]
    del jobsite_body["requires_sidewalk_closure"]
    validate_error(
        api.create_jobsite(jobsite_body, U.ACCOUNT_MANAGER), ERR_VALIDATION, 400
    )

    # Neither rejection wrote a partial row, and neither bumped the parent.
    rows, meta = _page(
        api.list_jobsites(
            U.ACCOUNT_MANAGER,
            params={"customer_account_id": world["account"]["id"]},
        )
    )
    assert ids_of(rows) == [jobsite_id], rows
    assert_integer(meta["total_count"], 1, "total_count")

    quotes, quote_meta = _page(
        api.list_quotes(U.ACCOUNT_MANAGER, params={"jobsite_id": jobsite_id})
    )
    assert quotes == []
    assert_integer(quote_meta["total_count"], 0, "total_count")

    reread = FX.read_jobsite(api, jobsite_id)
    assert_integer(reread["version"], 1, "version")


def test_omitted_optional_inputs_take_their_declared_defaults(api):
    """PRD §3.1: "`permit_review_rounds_allowed` ... defaults to 2",
    "`allows_solid_wind_screen` ... defaults to true", "`phase_count` ... defaults
    to 1" and "`requires_sidewalk_closure` flag defaults to false"; PRD §3.2:
    "`wind_screen` ... defaults to `NONE`" with "`addon_lines` ... defaulting to
    an empty list", and a new quote "opens in `DRAFT`".

    Design: Corner/entities/omitted_optional_inputs_apply_declared_defaults
    """
    FX.set_clock(api, C.DEFAULT_CLOCK)

    municipality_body = F.municipality_payload()
    del municipality_body["permit_review_rounds_allowed"]
    del municipality_body["allows_solid_wind_screen"]
    municipality = validate_success(
        api.create_municipality(municipality_body, U.PLATFORM_ADMIN),
        expected_status=201,
    )
    account = FX.seed_account(api)
    FX.seed_panel_product(api)

    jobsite_body = F.jobsite_payload(account["id"], municipality["id"])
    del jobsite_body["requires_sidewalk_closure"]
    assert "phase_count" not in jobsite_body
    jobsite = validate_success(
        api.create_jobsite(jobsite_body, U.ACCOUNT_MANAGER), expected_status=201
    )

    quote_body = F.quote_payload(jobsite["version"])
    del quote_body["wind_screen"]
    assert "addon_lines" not in quote_body
    quote = validate_success(
        api.create_quote(jobsite["id"], quote_body, U.ACCOUNT_MANAGER),
        expected_status=201,
    )

    stored_municipality = FX.read_municipality(api, municipality["id"])
    assert_integer(
        stored_municipality["permit_review_rounds_allowed"],
        2,
        "permit_review_rounds_allowed",
    )
    assert stored_municipality["allows_solid_wind_screen"] is True
    assert_integer(
        stored_municipality["committed_closure_linear_feet"],
        0,
        "committed_closure_linear_feet",
    )

    stored_jobsite = FX.read_jobsite(api, jobsite["id"])
    assert_integer(stored_jobsite["phase_count"], 1, "phase_count")
    assert stored_jobsite["requires_sidewalk_closure"] is False

    assert quote["wind_screen"] == C.SCREEN_NONE
    assert quote["addon_lines"] == []
    assert quote["status"] == C.QUOTE_DRAFT
    # The NONE default takes screen factor 1.00 and a zero per-foot adder, so the
    # 500-foot line at the 54-cent band prices at 27000 with no term discount.
    assert_cents(quote["monthly_recurring_cents"], 27000, "monthly_recurring_cents")


def test_quote_money_is_server_computed_and_a_dictated_amount_is_rejected(api):
    """PRD §2.7: a body "carries a field the endpoint does not define" is
    `ERR_VALIDATION`, and PRD §3.2 derives every money field of a quote from the
    six inputs it does define.

    Design: Corner/entities/quote_money_fields_computed_server_side_extra_field_rejected
    """
    world = FX.seed_world(api, jobsite={"phase_count": 4})
    jobsite_id = world["jobsite"]["id"]
    version = world["jobsite"]["version"]

    dictated = F.quote_payload(version, monthly_recurring_cents=1)
    validate_error(
        api.create_quote(jobsite_id, dictated, U.ACCOUNT_MANAGER), ERR_VALIDATION, 400
    )

    quote = validate_success(
        api.create_quote(jobsite_id, F.quote_payload(version), U.ACCOUNT_MANAGER),
        expected_status=201,
    )

    # 500 feet lands in the 250–999 band at 54 cents a foot, unscreened and at the
    # three-month minimum term; labor is 500 x 95 against the 35000 floor; and the
    # 27000 recurring figure stays under the 150000 permit-fee waiver threshold.
    assert_integer(quote["tier_rate_cents_per_ft"], 54, "tier_rate_cents_per_ft")
    assert_cents(quote["monthly_recurring_cents"], 27000, "monthly_recurring_cents")
    assert_cents(quote["install_labor_cents"], 47500, "install_labor_cents")
    assert_cents(
        quote["permit_handling_fee_cents"], 12500, "permit_handling_fee_cents"
    )
    assert_cents(quote["one_time_cents"], 78500, "one_time_cents")
    assert_integer(quote["panel_unit_count"], 50, "panel_unit_count")
    assert quote["monthly_recurring_cents"] != 1


def test_a_new_quote_carries_server_minted_identity_and_no_validity_yet(api):
    """PRD §2.4: "`id` — an opaque server-generated UUID string" with "`created_at`
    and `updated_at` — ISO-8601 UTC instants" and "`version` — an integer that
    starts at 1"; PRD §3.2 sets `issued_at_utc` and `valid_through_utc` only at
    issue.

    Design: Corner/entities/quote_system_fields_are_server_minted
    """
    world = FX.seed_world(api, jobsite={"phase_count": 4})
    jobsite_id = world["jobsite"]["id"]

    quote = validate_success(
        api.create_quote(
            jobsite_id,
            F.quote_payload(world["jobsite"]["version"]),
            U.ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )

    assert isinstance(quote["id"], str) and len(quote["id"]) == 36, quote["id"]
    assert is_valid_uuid(quote["id"]), quote["id"]
    assert_instant_is_utc(quote["created_at"], "created_at")
    assert_instant_is_utc(quote["updated_at"], "updated_at")
    assert_freshly_created(quote)
    assert quote["status"] == C.QUOTE_DRAFT
    assert quote["issued_at_utc"] is None
    assert quote["valid_through_utc"] is None
    assert quote["jobsite_id"] == jobsite_id


def test_bad_enums_nonpositive_numbers_and_a_zero_length_window_are_shape_failures(api):
    """PRD §2.7: the shape rung covers "a value is of the wrong JSON type, an
    enumerated field carries a value outside its declared set, or a numeric field
    declared strictly positive arrives at zero or below", and PRD §2.6 makes a
    zero-length window `ERR_VALIDATION` too. The rung sits at priority 3, ahead of
    every business rule.

    Design: Corner/entities/invalid_enum_and_nonpositive_and_inverted_window_rejected
    """
    world = FX.seed_world(
        api, jobsite={"phase_count": 4, "requires_sidewalk_closure": True}
    )
    jobsite_id = world["jobsite"]["id"]
    version = world["jobsite"]["version"]

    off_enum_condition = F.jobsite_payload(
        world["account"]["id"],
        world["municipality"]["id"],
        site_label="Gravel Pit Annex",
        address_line="9 Gravel Pit Road",
        site_condition="GRAVEL",
    )
    validate_error(
        api.create_jobsite(off_enum_condition, U.ACCOUNT_MANAGER), ERR_VALIDATION, 400
    )

    off_enum_screen = F.quote_payload(version, wind_screen="SOLID_200")
    validate_error(
        api.create_quote(jobsite_id, off_enum_screen, U.ACCOUNT_MANAGER),
        ERR_VALIDATION,
        400,
    )

    # Zero feet is a shape failure, so the below-minimum-term rule never runs.
    zero_feet = F.quote_payload(version, linear_feet=0)
    response = api.create_quote(jobsite_id, zero_feet, U.ACCOUNT_MANAGER)
    validate_error(response, ERR_VALIDATION, 400)
    assert response.status_code == 400, response.status_code

    # A window whose end equals its start carries no instants at all.
    zero_window = F.permit_payload(
        jobsite_id,
        closure_start_utc="2026-08-10T00:00:00Z",
        closure_end_utc="2026-08-10T00:00:00Z",
        sidewalk_closure_type=C.CLOSURE_FULL,
    )
    lead_time_free = api.create_permit(zero_window, U.MUNICIPAL_LIAISON)
    validate_error(lead_time_free, ERR_VALIDATION, 400)

    rows, meta = _page(
        api.list_jobsites(
            U.ACCOUNT_MANAGER, params={"customer_account_id": world["account"]["id"]}
        )
    )
    assert ids_of(rows) == [jobsite_id], rows
    assert_integer(meta["total_count"], 1, "total_count")
    assert "Gravel Pit Annex" not in [row["site_label"] for row in rows]


def test_pricing_on_an_unknown_jobsite_is_not_found_before_the_version_check(api):
    """PRD §2.7 puts "a path identifier that resolves to no stored row" at
    priority 4 and the optimistic-concurrency comparison of PRD §2.8 at
    priority 8, so the unknown parent answers first.

    Design: Corner/entities/create_quote_on_unknown_jobsite_not_found
    """
    world = FX.seed_world(api, jobsite={"phase_count": 4})

    validate_error(
        api.create_quote(
            UNKNOWN_JOBSITE_ID,
            F.quote_payload(world["jobsite"]["version"]),
            U.ACCOUNT_MANAGER,
        ),
        ERR_JOBSITE_NOT_FOUND,
        404,
    )

    untouched = FX.read_jobsite(api, world["jobsite"]["id"])
    assert_integer(untouched["version"], 1, "version")


def test_every_unresolved_body_foreign_key_answers_with_its_own_type(api):
    """PRD §2.7: "A reference carried in the request body that resolves to no
    stored row is rejected with that referenced type's own not-found error", at a
    rung ahead of every state and business check.

    Design: Corner/entities/body_foreign_keys_and_dispatch_crew_reference_not_found
    """
    world = FX.seed_world(api, jobsite={"phase_count": 4})
    contract, _quote = FX.seed_contract(
        api, world["jobsite"]["id"], world["account"]["id"], linear_feet=500
    )
    install = FX.plan_work_order(
        api, contract["id"], C.WO_DELIVERY_INSTALL, 500
    )

    validate_error(
        api.create_jobsite(
            F.jobsite_payload(
                UNKNOWN_ACCOUNT_ID,
                world["municipality"]["id"],
                site_label="Orphan Site",
                address_line="1 Nowhere Lane",
            ),
            U.ACCOUNT_MANAGER,
        ),
        ERR_ACCOUNT_NOT_FOUND,
        404,
    )

    validate_error(
        api.create_jobsite(
            F.jobsite_payload(
                world["account"]["id"],
                UNKNOWN_MUNICIPALITY_ID,
                site_label="Orphan Site",
                address_line="1 Nowhere Lane",
            ),
            U.ACCOUNT_MANAGER,
        ),
        ERR_MUNICIPALITY_NOT_FOUND,
        404,
    )

    validate_error(
        api.create_quote(
            world["jobsite"]["id"],
            F.quote_payload(
                FX.jobsite_version(api, world["jobsite"]["id"]),
                panel_product_code="PANEL-NOPE",
            ),
            U.ACCOUNT_MANAGER,
        ),
        ERR_PRODUCT_NOT_FOUND,
        404,
    )

    validate_error(
        api.dispatch_work_order(
            install["id"],
            F.dispatch_payload(UNKNOWN_CREW_ID, "2026-08-03T08:00:00Z"),
            U.DISPATCH_COORDINATOR,
        ),
        ERR_CREW_NOT_FOUND,
        404,
    )

    unmoved = FX.read_work_order(api, install["id"])
    assert unmoved["status"] == C.WO_PLANNED
    assert unmoved["crew_id"] is None
    assert_fleet_counts(
        FX.read_product(api, world["panel"]["id"]),
        available=C.PANEL_OWNED_COUNT,
        reserved=0,
        deployed=0,
    )
