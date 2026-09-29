"""Enrolment, schema admission and the per-entity not-found codes.

These are the platform-level guarantees the rest of the suite leans on: what a
create echoes back, what a read does not change, which malformed bodies never
reach a business rule, and the fact that every entity answers an unknown id with
its own code rather than a generic 404.
"""

from test_helpers import (
    ADMIN,
    MERCH,
    NON_EXISTENT_UUID,
    TECH1,
    api_client,
    assert_customer,
    assert_grade_policy,
    assert_instant,
    assert_markdown_campaign,
    assert_null,
    assert_pagination_meta,
    create_channel_payload,
    create_customer,
    create_customer_payload,
    create_diversion_report_payload,
    create_grade_policy_payload,
    create_markdown_campaign_payload,
    create_refurb_order_payload,
    fetch_unit,
    setup_accepted_trade_in,
    setup_credit_source_grant,
    setup_estate,
    validate_error,
    validate_paginated,
    validate_success,
)

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def test_enrolment_returns_the_declared_fields_and_the_system_stamps():
    """The create echoes what was declared and adds the stamps nobody may send.

    PRD §3.1: "Enrolment captures an `email`, which must be non-empty and unique across
    all customers, and a `full_name`, which must also be non-empty."
    PRD §3.1: "A `loyalty_tier` may be supplied and is one of `STANDARD` or `PLUS`; when
    it is omitted the customer is enrolled as `STANDARD`."
    PRD §3.1: "The customer's `status` is set to `ACTIVE` on enrolment and is only ever
    `ACTIVE` or `SUSPENDED`."
    PRD §3.1: "Two derived quantities start at zero and are never written directly by a
    client: `credit_balance_minor`, the customer's live brand-currency balance, and
    `diverted_grams_total`, their lifetime diverted mass."
    PRD §2.6: "Every resource the platform persists carries a server-minted `id`, which
    is a UUID with no type prefix of any kind, and a `created_at` timestamp in ISO 8601
    UTC with three fractional digits recording when the row was first written."
    PRD §4: "Endpoints that bring a new resource into existence return HTTP 201;
    endpoints that modify, transition or read an existing resource, and endpoints that
    run a batch operation, return HTTP 200."

    Design: Corner/entities/customer_creation_returns_declared_fields_and_system_stamps
    """
    created = validate_success(
        api_client.create_customer(
            create_customer_payload(
                email="ava@example.com", full_name="Ava Reyes", loyalty_tier="PLUS"
            ),
            ADMIN,
        ),
        201,
    )
    assert_customer(created)
    # Declared fields come back exactly as they were sent.
    assert created["email"] == "ava@example.com"
    assert created["full_name"] == "Ava Reyes"
    assert created["loyalty_tier"] == "PLUS"
    # System-managed fields the client never sends.
    assert created["status"] == "ACTIVE"
    assert created["credit_balance_minor"] == 0
    assert created["diverted_grams_total"] == 0
    assert created["version"] == 1
    assert_instant(created["created_at"], DEFAULT_CLOCK, "created_at")
    assert_instant(created["updated_at"], DEFAULT_CLOCK, "updated_at")


def test_reading_a_customer_returns_the_stored_row_without_touching_it():
    """A read is not a mutation: same values, same version.

    PRD §2.6: "Most resources — customers, condition-tier policies, brand-currency
    policies, store locations, refurbishment bays, channels, trade-ins, brand-currency
    grants, resale units, refurbishment orders, markdown campaigns, resale orders and
    diversion reports — additionally carry `updated_at`, an ISO 8601 UTC timestamp
    refreshed on every mutation of the row, and `version`, an integer that is
    initialized to 1 when the row is created and incremented by exactly one on every
    mutation."
    PRD §3.1: "A `loyalty_tier` may be supplied and is one of `STANDARD` or `PLUS`; when
    it is omitted the customer is enrolled as `STANDARD`."
    PRD §4: "Endpoints that bring a new resource into existence return HTTP 201;
    endpoints that modify, transition or read an existing resource, and endpoints that
    run a batch operation, return HTTP 200."

    Design: Corner/entities/customer_retrieval_returns_the_stored_row
    """
    created = create_customer(email="ben@example.com", full_name="Ben Ortiz")
    version_at_create = created["version"]

    fetched = validate_success(api_client.get_customer(created["id"], ADMIN))
    assert_customer(fetched)
    assert fetched["id"] == created["id"]
    assert fetched["email"] == "ben@example.com"
    assert fetched["full_name"] == "Ben Ortiz"
    assert fetched["loyalty_tier"] == "STANDARD"
    assert fetched["status"] == "ACTIVE"
    assert fetched["credit_balance_minor"] == 0
    assert fetched["diverted_grams_total"] == 0
    # A read never bumps the version, and never refreshes updated_at either.
    assert fetched["version"] == version_at_create
    assert_instant(fetched["created_at"], created["created_at"], "created_at")
    assert_instant(fetched["updated_at"], created["updated_at"], "updated_at")

    # Reading a second time is just as inert.
    again = validate_success(api_client.get_customer(created["id"], MERCH))
    assert again["version"] == version_at_create


def test_the_loyalty_tier_defaults_to_standard_when_it_is_omitted():
    """An omitted tier is STANDARD, not null — and it is worth exactly no bonus.

    PRD §3.1: "A `loyalty_tier` may be supplied and is one of `STANDARD` or `PLUS`; when
    it is omitted the customer is enrolled as `STANDARD`."
    PRD §3.1: "The customer's `status` is set to `ACTIVE` on enrolment and is only ever
    `ACTIVE` or `SUSPENDED`."
    PRD §3.4: "And it adds a loyalty term: when the participant's `loyalty_tier` is
    `PLUS`, five percent of the base credit — the base credit multiplied by five hundred
    basis points, divided by ten thousand, rounded down — is added on top; for a
    `STANDARD` participant that term is zero."
    PRD §3.4: "The evaluation order is pinned and the bonuses never compound: the base
    credit is computed first from `msrp_minor` and the tier's `base_credit_pct_bp`,
    rounded down; the mail-in channel bonus is then computed against **that base**,
    rounded down, and applies only when the intake `channel` was `MAIL_IN`; the loyalty
    bonus is likewise computed against that same base, rounded down, independently of the
    channel bonus."

    Design: Corner/entities/customer_loyalty_tier_defaults_to_standard_when_omitted
    """
    estate = setup_estate()
    customer = create_customer(email="ava@example.com", full_name="Ava Reyes")
    assert customer["loyalty_tier"] == "STANDARD"
    assert customer["status"] == "ACTIVE"
    assert customer["credit_balance_minor"] == 0
    assert customer["diverted_grams_total"] == 0

    # A mail-in acceptance for that participant pays 10000 base plus the 1000 mail-in
    # bonus and nothing else, where a PLUS tier would have added 500.
    scenario = setup_credit_source_grant(estate, customer=customer)
    assert scenario["grant"]["issued_amount_minor"] == 11000
    assert scenario["customer"]["loyalty_tier"] == "STANDARD"
    assert scenario["customer"]["credit_balance_minor"] == 11000


def test_a_policy_row_missing_a_required_field_is_refused_and_persists_nothing():
    """Omitting warranty_days is a malformed body, and the retry with it succeeds.

    PRD §2.11: "**Body shape.** On every creating and modifying request, all required
    fields must be present, every enumerated value must be inside its declared set, every
    money, mass and basis-point field must be a non-negative integer, and every timestamp
    must be a valid ISO 8601 UTC instant, otherwise `ERR_INVALID_REQUEST` (422)."
    PRD §3.1: "`warranty_days` is the resale warranty length, a whole number of days of
    at least zero, measured from the instant an order is fulfilled."
    PRD §2.7: "A **condition-tier policy** is keyed on the pair (`product_category`,
    `condition_grade`) and is created with `status` `ACTIVE`; publishing a new policy for
    the same pair flips the previously `ACTIVE` row for that pair to `RETIRED`."
    PRD §2.6: "Every resource the platform persists carries a server-minted `id`, which
    is a UUID with no type prefix of any kind, and a `created_at` timestamp in ISO 8601
    UTC with three fractional digits recording when the row was first written."

    Design: Corner/entities/grade_policy_creation_missing_required_field_is_rejected
    """
    incomplete = create_grade_policy_payload()
    del incomplete["warranty_days"]
    validate_error(
        api_client.create_grade_policy(incomplete, ADMIN),
        "ERR_INVALID_REQUEST",
        422,
    )

    # The refused call wrote nothing, so this is the first row for the pair and it is
    # created ACTIVE rather than immediately retiring an invisible predecessor.
    policy = validate_success(
        api_client.create_grade_policy(create_grade_policy_payload(), ADMIN), 201
    )
    assert_grade_policy(policy)
    assert policy["product_category"] == "OUTERWEAR"
    assert policy["condition_grade"] == "B"
    assert policy["warranty_days"] == 30
    assert policy["status"] == "ACTIVE"
    assert policy["version"] == 1

    stored = validate_success(api_client.get_grade_policy(policy["id"], ADMIN))
    assert stored["status"] == "ACTIVE"
    assert stored["warranty_days"] == 30
    assert stored["version"] == 1


def test_out_of_set_and_out_of_range_body_values_never_reach_a_business_rule():
    """A bad enum, two out-of-range basis-point values and a malformed instant are all 422.

    PRD §2.11: "**Body shape.** On every creating and modifying request, all required
    fields must be present, every enumerated value must be inside its declared set, every
    money, mass and basis-point field must be a non-negative integer, and every timestamp
    must be a valid ISO 8601 UTC instant, otherwise `ERR_INVALID_REQUEST` (422)."
    PRD §3.1: "A channel is registered with a `code` unique across channels, a
    `channel_type` of `FULL_PRICE_DTC`, `RESALE_MARKETPLACE` or `OUTLET`, an
    `allowed_assortment` of `NEW_ONLY`, `RESALE_ONLY` or `BOTH`, a
    `max_resale_price_ratio_bp` between 1 and 10000 inclusive, and a non-empty
    `region_code`."
    PRD §3.1: "A channel's `status` begins `ACTIVE` and may be paused; a `PAUSED` channel
    accepts neither new listings nor new resale orders, and both refusals carry
    `ERR_CHANNEL_NOT_ACTIVE`."
    PRD §3.6: "A campaign names its `channel_id` and its `product_category`, delimits its
    half-open window with `window_start_at` and `window_end_at`, and states three cadence
    terms: `cadence_days`, the whole number of at least 1 giving the days of listing age
    required per markdown step; `step_bp`, the per-step reduction as basis points of the
    current price, between 1 and 9999 inclusive; and `floor_pct_bp`, the price floor as
    basis points of the unit's own `list_price_minor`, between 1 and 10000 inclusive."
    PRD §3.6: "A campaign is created in `SCHEDULED` with `run_count` at 0 and
    `last_run_at` null."
    PRD §3.6: "Campaigns on a channel are listable by `ProgramAdmin` and
    `MerchandisingManager` with optional filters on `product_category` and `status`, plus
    `limit` and `offset`."

    Design: Corner/entities/enum_and_range_constraints_rejected_on_channel_and_campaign_inputs
    """
    # One real channel, so the campaign calls below fail on their own fields rather than
    # on the channel reference.
    channel = validate_success(
        api_client.create_channel(create_channel_payload(), ADMIN), 201
    )
    assert channel["channel_type"] == "RESALE_MARKETPLACE"
    assert channel["max_resale_price_ratio_bp"] == 7000
    assert channel["status"] == "ACTIVE"
    assert channel["version"] == 1

    # WHOLESALE is not one of FULL_PRICE_DTC, RESALE_MARKETPLACE or OUTLET.
    validate_error(
        api_client.create_channel(
            create_channel_payload(code="WHOLESALE", channel_type="WHOLESALE"), ADMIN
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    # One past the declared ceiling of the 1..10000 range.
    validate_error(
        api_client.create_channel(
            create_channel_payload(
                code="OUTLET-1", channel_type="OUTLET", max_resale_price_ratio_bp=10001
            ),
            ADMIN,
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    # step_bp stops at 9999, one short of the ten thousand that would zero the price.
    validate_error(
        api_client.create_markdown_campaign(
            create_markdown_campaign_payload(
                channel["id"], product_category="FOOTWEAR", step_bp=10000
            ),
            MERCH,
        ),
        "ERR_INVALID_REQUEST",
        422,
    )
    # A window endpoint that is not an instant at all is a shape failure, not the
    # ill-ordered-window failure.
    validate_error(
        api_client.create_markdown_campaign(
            create_markdown_campaign_payload(
                channel["id"],
                product_category="FOOTWEAR",
                window_start_at="not-an-instant",
            ),
            MERCH,
        ),
        "ERR_INVALID_REQUEST",
        422,
    )

    # Neither refused campaign wrote a row.
    rows, meta = validate_paginated(
        api_client.list_channel_markdown_campaigns(channel["id"], MERCH)
    )
    assert_pagination_meta(meta, 0)
    assert rows == []

    # The same campaign payload lands once step_bp sits inside its inclusive range.
    campaign = validate_success(
        api_client.create_markdown_campaign(
            create_markdown_campaign_payload(
                channel["id"], product_category="FOOTWEAR", step_bp=9999
            ),
            MERCH,
        ),
        201,
    )
    assert_markdown_campaign(campaign)
    assert campaign["step_bp"] == 9999
    assert campaign["status"] == "SCHEDULED"
    assert campaign["run_count"] == 0
    assert_null(campaign["last_run_at"], "last_run_at")

    after_rows, after_meta = validate_paginated(
        api_client.list_channel_markdown_campaigns(channel["id"], MERCH)
    )
    assert_pagination_meta(after_meta, 1)
    assert after_rows[0]["id"] == campaign["id"]
    # And the refused channel creates never touched the channel that does exist.
    assert validate_success(api_client.get_channel(channel["id"], ADMIN))["version"] == 1


def test_each_configuration_entity_answers_an_unknown_id_with_its_own_code():
    """Five reads on an empty programme, five different 404 codes.

    PRD §2.11: "**Path existence.** Every entity named by an `{id}` path segment must
    exist, resolved strictly left to right, so that the outermost missing segment is the
    one reported."
    PRD §2.11: "The code is the per-entity not-found code: `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_GRADE_POLICY_NOT_FOUND`, `ERR_CREDIT_POLICY_NOT_FOUND`,
    `ERR_STORE_LOCATION_NOT_FOUND`, `ERR_REFURB_BAY_NOT_FOUND`, `ERR_CHANNEL_NOT_FOUND`,
    `ERR_TRADE_IN_NOT_FOUND`, `ERR_CREDIT_GRANT_NOT_FOUND`, `ERR_RESALE_UNIT_NOT_FOUND`,
    `ERR_REFURB_ORDER_NOT_FOUND`, `ERR_MARKDOWN_CAMPAIGN_NOT_FOUND`,
    `ERR_RESALE_ORDER_NOT_FOUND` or `ERR_DIVERSION_REPORT_NOT_FOUND`, each answering 404."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."
    PRD §3.1: "Brand-currency policies are readable by `ProgramAdmin` and
    `MerchandisingManager` only."

    Design: Corner/entities/not_found_on_unknown_configuration_entity_ids
    """
    # The id is a syntactically valid UUID, so nothing here is a shape failure — and
    # validate_error also checks the error envelope's non-empty message.
    validate_error(
        api_client.get_customer(NON_EXISTENT_UUID, ADMIN),
        "ERR_CUSTOMER_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.get_grade_policy(NON_EXISTENT_UUID, ADMIN),
        "ERR_GRADE_POLICY_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.get_credit_policy(NON_EXISTENT_UUID, ADMIN),
        "ERR_CREDIT_POLICY_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.get_store_location(NON_EXISTENT_UUID, ADMIN),
        "ERR_STORE_LOCATION_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.get_channel(NON_EXISTENT_UUID, ADMIN),
        "ERR_CHANNEL_NOT_FOUND",
        404,
    )
    # The brand-currency read is admitted for the other permitted role too, so the 404
    # above was about the row and not about the caller.
    validate_error(
        api_client.get_credit_policy(NON_EXISTENT_UUID, MERCH),
        "ERR_CREDIT_POLICY_NOT_FOUND",
        404,
    )


def test_the_operational_surface_reports_a_missing_bay_from_the_body_as_well():
    """Three path reads and one body reference, each with its own 404 code.

    PRD §2.11: "**Path existence.** Every entity named by an `{id}` path segment must
    exist, resolved strictly left to right, so that the outermost missing segment is the
    one reported."
    PRD §2.11: "**Body foreign keys.** Every identifier supplied in a request body must
    reference an existing row of its declared entity — `customer_id`,
    `store_location_id`, `channel_id`, `resale_unit_id`, `refurb_bay_id`,
    `credit_policy_id` and `supersedes_report_id` — reported with the same per-entity 404
    codes."
    PRD §3.5: "The request names the unit through `resale_unit_id`, books a bay through
    `refurb_bay_id`, delimits the booking with `window_start_at` and `window_end_at`, and
    — as §2.8 requires — carries `expected_resale_unit_version`."
    PRD §3.5: "Scheduling refurbishment is open to a `RefurbTechnician` or a
    `ProgramAdmin`."
    PRD §3.5: "A newly scheduled order enters `SCHEDULED` with `rework_count`,
    `logged_cost_minor` and `viability_ratio_bp` all at 0, `performed_by_user_id`,
    `qc_by_user_id` and `viability_override_reason` all null."
    PRD §3.5: "It does, however, increment the unit's version — which is precisely why
    the expected-version input exists."

    Design: Corner/entities/not_found_on_unknown_operational_entity_ids
    """
    estate = setup_estate()
    scenario = setup_accepted_trade_in(estate)
    unit = scenario["unit"]
    unit_version = unit["version"]

    validate_error(
        api_client.get_trade_in(NON_EXISTENT_UUID, ADMIN),
        "ERR_TRADE_IN_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.get_resale_unit(NON_EXISTENT_UUID, ADMIN),
        "ERR_RESALE_UNIT_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.get_refurb_order(NON_EXISTENT_UUID, ADMIN),
        "ERR_REFURB_ORDER_NOT_FOUND",
        404,
    )

    # The unit, the window and the expected version are all good; only the bay named in
    # the body is missing, and it is reported with the bay's own code.
    validate_error(
        api_client.create_refurb_order(
            create_refurb_order_payload(
                unit["id"],
                NON_EXISTENT_UUID,
                "2026-08-01T09:00:00Z",
                "2026-08-01T11:00:00Z",
                unit_version,
            ),
            TECH1,
        ),
        "ERR_REFURB_BAY_NOT_FOUND",
        404,
    )

    # Nothing was booked and the unit was not written to.
    orders, order_meta = validate_paginated(api_client.list_refurb_orders(ADMIN))
    assert_pagination_meta(order_meta, 0)
    assert orders == []
    assert fetch_unit(unit["id"])["version"] == unit_version

    # The identical request against the real bay is accepted, which is what makes the
    # refusal above attributable to the missing bay alone.
    order = validate_success(
        api_client.create_refurb_order(
            create_refurb_order_payload(
                unit["id"],
                estate["bay"]["id"],
                "2026-08-01T09:00:00Z",
                "2026-08-01T11:00:00Z",
                unit_version,
            ),
            TECH1,
        ),
        201,
    )
    assert order["status"] == "SCHEDULED"
    assert order["rework_count"] == 0
    assert order["logged_cost_minor"] == 0
    assert order["viability_ratio_bp"] == 0
    assert fetch_unit(unit["id"])["version"] == unit_version + 1


def test_the_ledger_order_campaign_and_report_reads_each_keep_their_own_code():
    """Four unknown ids, and a fifth carried in a report body rather than a path.

    PRD §2.11: "**Path existence.** Every entity named by an `{id}` path segment must
    exist, resolved strictly left to right, so that the outermost missing segment is the
    one reported."
    PRD §2.11: "**Body foreign keys.** Every identifier supplied in a request body must
    reference an existing row of its declared entity — `customer_id`,
    `store_location_id`, `channel_id`, `resale_unit_id`, `refurb_bay_id`,
    `credit_policy_id` and `supersedes_report_id` — reported with the same per-entity 404
    codes."
    PRD §3.9: "A report declares its half-open period through `period_start_at` and
    `period_end_at`, and may optionally name `supersedes_report_id`, the earlier
    published report this one restates; that field is null for an original report."
    PRD §3.9: "Reports are readable and listable by `ProgramAdmin` and
    `MerchandisingManager`, with optional filters on `supersedes_report_id` and `status`,
    plus `limit` and `offset`."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/not_found_on_unknown_ledger_and_report_entity_ids
    """
    validate_error(
        api_client.get_credit_grant(NON_EXISTENT_UUID, ADMIN),
        "ERR_CREDIT_GRANT_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.get_resale_order(NON_EXISTENT_UUID, ADMIN),
        "ERR_RESALE_ORDER_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.get_markdown_campaign(NON_EXISTENT_UUID, ADMIN),
        "ERR_MARKDOWN_CAMPAIGN_NOT_FOUND",
        404,
    )
    validate_error(
        api_client.get_diversion_report(NON_EXISTENT_UUID, ADMIN),
        "ERR_DIVERSION_REPORT_NOT_FOUND",
        404,
    )

    # A period that would otherwise be perfectly acceptable, refused purely for the row
    # it claims to restate.
    validate_error(
        api_client.create_diversion_report(
            create_diversion_report_payload(supersedes_report_id=NON_EXISTENT_UUID),
            ADMIN,
        ),
        "ERR_DIVERSION_REPORT_NOT_FOUND",
        404,
    )

    # The refused create wrote no report at all.
    reports, report_meta = validate_paginated(api_client.list_diversion_reports(ADMIN))
    assert_pagination_meta(report_meta, 0)
    assert reports == []

    # And the same period is accepted the moment it stops naming a stranger.
    original = validate_success(
        api_client.create_diversion_report(create_diversion_report_payload(), ADMIN), 201
    )
    assert original["status"] == "DRAFT"
    assert_null(original["supersedes_report_id"], "supersedes_report_id")
