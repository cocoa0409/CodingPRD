"""Intake: submission, the provisional quote, and physical receipt."""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID

from test_helpers import (
    ADMIN,
    AUTH1,
    CREDIT_POLICY_CORE,
    GRADE_POLICY_FOOTWEAR_A,
    GRADE_POLICY_OUTERWEAR_B,
    INTAKE,
    api_client,
    assert_credit_grant,
    assert_instant,
    assert_null,
    assert_pagination_meta,
    assert_trade_in,
    create_credit_policy,
    create_customer,
    create_grade_policy,
    create_store_location,
    create_trade_in,
    create_trade_in_payload,
    disposition_trade_in,
    fetch_customer,
    fetch_trade_in,
    grant_of_trade_in,
    grants_of_trade_in,
    make_customer_headers,
    receive_trade_in,
    authenticate_trade_in,
    set_clock,
    units_of_trade_in,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_provisional_quote_withholds_the_loyalty_bonus_that_issuance_pays():
    """The quote and the issuance price the same claim differently.

    PRD §3.2: "The provisional variant contributes **no loyalty bonus at all**,
    even for a `PLUS` customer — that term is reserved for issuance."
    PRD §3.2: "The base credit is `msrp_minor` multiplied by that tier's
    `base_credit_pct_bp`, divided by ten thousand, and rounded down to whole
    minor units."
    PRD §3.2: "When the intake `channel` is `MAIL_IN`, a channel bonus is added:
    the base credit multiplied by the brand-currency policy's
    `mail_in_bonus_pct_bp`, divided by ten thousand, rounded down; for an
    `IN_STORE` submission the channel bonus is zero."
    PRD §3.4: "And it adds a loyalty term: when the participant's
    `loyalty_tier` is `PLUS`, five percent of the base credit — the base credit
    multiplied by five hundred basis points, divided by ten thousand, rounded
    down — is added on top; for a `STANDARD` participant that term is zero."

    Design: Difficulty/dual_variant_calc/trade_in_credit_quote_versus_issuance_diverges_on_identical_grade
    """
    create_grade_policy(GRADE_POLICY_FOOTWEAR_A)
    create_credit_policy(CREDIT_POLICY_CORE)
    create_store_location()
    customer = create_customer(loyalty_tier="PLUS")

    trade_in = create_trade_in(
        customer,
        channel="MAIL_IN",
        product_category="FOOTWEAR",
        declared_grade="A",
        msrp_minor=120000,
        item_mass_grams=900,
    )
    assert_trade_in(trade_in)
    # base 42000 = floor(120000 * 3500 / 10000), mail-in bonus 4200, no loyalty.
    assert trade_in["appraised_credit_minor"] == 46200

    receive_trade_in(trade_in["id"])
    authenticate_trade_in(trade_in["id"], "GENUINE", "A")
    accepted = disposition_trade_in(trade_in["id"], "ACCEPT", "OWNED_INVENTORY")

    # The same base 42000 now also earns the PLUS loyalty term of 2100.
    assert accepted["appraised_credit_minor"] == 48300
    assert accepted["appraised_credit_minor"] - trade_in["appraised_credit_minor"] == 2100
    # The divergence is the variant, not the grade: both grades read A.
    assert accepted["declared_grade"] == "A"
    assert accepted["assessed_grade"] == "A"


def test_acceptance_grant_pins_the_final_appraisal_and_the_recomputed_balance():
    """The grant minted at acceptance carries the final figure, not the quote.

    PRD §3.4: "The **second link**, caused by the first, creates one
    brand-currency grant."
    PRD §3.4: "It copies `customer_id` from the trade-in, records `trade_in_id`
    as the acceptance that produced it, records `credit_policy_id` as the
    `ACTIVE` brand-currency policy and `credit_policy_version` as that policy's
    current `version`, sets `issued_amount_minor` to the freshly computed final
    appraisal and `remaining_minor` to the same figure, sets `issued_at` equal
    to the trade-in's `accepted_at`, computes `expires_at` as `issued_at` plus
    the pinned policy's `expiry_days` whole days, and enters `status` `ISSUED`."
    PRD §3.4: "The **fourth link**, caused by the third, recomputes the
    participant's `credit_balance_minor` as the sum of `remaining_minor` over
    that customer's grants whose `status` is `ISSUED` or `PARTIALLY_REDEEMED`,
    and increments the customer's version."

    Design: Difficulty/dual_variant_calc/trade_in_credit_quote_versus_issuance_diverges_on_identical_grade
    """
    create_grade_policy(GRADE_POLICY_FOOTWEAR_A)
    credit_policy = create_credit_policy(CREDIT_POLICY_CORE)
    create_store_location()
    customer = create_customer(loyalty_tier="PLUS")

    trade_in = create_trade_in(
        customer,
        channel="MAIL_IN",
        product_category="FOOTWEAR",
        declared_grade="A",
        msrp_minor=120000,
        item_mass_grams=900,
    )
    receive_trade_in(trade_in["id"])
    authenticate_trade_in(trade_in["id"], "GENUINE", "A")
    accepted = disposition_trade_in(trade_in["id"], "ACCEPT", "OWNED_INVENTORY")

    grant = grant_of_trade_in(trade_in["id"])
    assert_credit_grant(grant)
    assert grant["issued_amount_minor"] == 48300
    assert grant["remaining_minor"] == 48300
    assert grant["status"] == "ISSUED"
    assert grant["credit_policy_id"] == credit_policy["id"]
    assert grant["credit_policy_version"] == credit_policy["version"]
    assert_instant(grant["issued_at"], accepted["accepted_at"], "issued_at")
    # 2026-08-01 plus the pinned policy's 180 whole days.
    assert_instant(grant["expires_at"], "2027-01-28T00:00:00Z", "expires_at")

    assert fetch_customer(customer["id"])["credit_balance_minor"] == 48300


def test_submission_derives_the_quote_and_deadline_for_both_channels():
    """Quote, deadline and every status field are server-derived on submission.

    PRD §3.2: "On submission the trade-in enters `SUBMITTED` with
    `authenticity_result` set to `PENDING`, `assessed_grade` and
    `graded_by_user_id` both null, and `appeal_count` at 0."
    PRD §3.2: "A mail-in submission gets three full weeks — twenty-one days from
    creation — because the item still has to travel; an in-store submission gets
    only two days, since the customer is standing at the counter."
    PRD §3.2: "Both are counted from the trade-in's own creation timestamp."
    PRD §3.2: "The `store_location_id` field completes the picture and is
    channel-dependent — it is required when the `channel` is `IN_STORE` and must
    be null when the `channel` is `MAIL_IN`."

    Design: Corner/entities/trade_in_computed_fields_are_server_derived_and_ignore_client_values
    """
    create_grade_policy(GRADE_POLICY_FOOTWEAR_A)
    create_credit_policy(CREDIT_POLICY_CORE)
    store = create_store_location()
    customer = create_customer(loyalty_tier="PLUS")

    mail_in = create_trade_in(
        customer,
        channel="MAIL_IN",
        product_category="FOOTWEAR",
        declared_grade="A",
        msrp_minor=120000,
        item_mass_grams=900,
    )
    in_store = create_trade_in(
        customer,
        channel="IN_STORE",
        store_location_id=store["id"],
        product_category="FOOTWEAR",
        declared_grade="A",
        msrp_minor=120000,
        item_mass_grams=900,
    )

    # The mail-in channel bonus is worth 4200 on a base of 42000.
    assert mail_in["appraised_credit_minor"] == 46200
    assert in_store["appraised_credit_minor"] == 42000
    assert_instant(mail_in["receive_deadline_at"], "2026-08-22T00:00:00Z", "mail-in deadline")
    assert_instant(in_store["receive_deadline_at"], "2026-08-03T00:00:00Z", "in-store deadline")
    assert_null(mail_in["store_location_id"], "MAIL_IN store_location_id")
    assert in_store["store_location_id"] == store["id"]

    for row in (mail_in, in_store):
        assert row["status"] == "SUBMITTED"
        assert row["authenticity_result"] == "PENDING"
        assert row["appeal_count"] == 0
        assert_null(row["assessed_grade"], "assessed_grade")
        assert_null(row["graded_by_user_id"], "graded_by_user_id")
        assert_null(row["received_at"], "received_at")


def test_submission_rejects_an_unknown_customer_then_an_unknown_store():
    """Both body foreign keys are resolved before anything is persisted.

    PRD §2.11: "Every identifier supplied in a request body must reference an
    existing row of its declared entity — `customer_id`, `store_location_id`,
    `channel_id`, `resale_unit_id`, `refurb_bay_id`, `credit_policy_id` and
    `supersedes_report_id` — reported with the same per-entity 404 codes."

    Design: Corner/entities/trade_in_creation_validates_both_foreign_keys_before_persisting
    """
    create_grade_policy(GRADE_POLICY_FOOTWEAR_A)
    create_credit_policy(CREDIT_POLICY_CORE)
    store = create_store_location()
    customer = create_customer(loyalty_tier="PLUS")

    bogus_customer = create_trade_in_payload(
        NON_EXISTENT_UUID,
        channel="IN_STORE",
        store_location_id=store["id"],
        product_category="FOOTWEAR",
        declared_grade="A",
        msrp_minor=120000,
        item_mass_grams=900,
    )
    validate_error(
        api_client.create_trade_in(bogus_customer, INTAKE),
        "ERR_CUSTOMER_NOT_FOUND",
        404,
    )

    bogus_store = create_trade_in_payload(
        customer["id"],
        channel="IN_STORE",
        store_location_id=NON_EXISTENT_UUID,
        product_category="FOOTWEAR",
        declared_grade="A",
        msrp_minor=120000,
        item_mass_grams=900,
    )
    validate_error(
        api_client.create_trade_in(bogus_store, INTAKE),
        "ERR_STORE_LOCATION_NOT_FOUND",
        404,
    )

    good = create_trade_in_payload(
        customer["id"],
        channel="IN_STORE",
        store_location_id=store["id"],
        product_category="FOOTWEAR",
        declared_grade="A",
        msrp_minor=120000,
        item_mass_grams=900,
    )
    created = validate_success(api_client.create_trade_in(good, INTAKE), 201)
    assert created["customer_id"] == customer["id"]
    assert created["store_location_id"] == store["id"]

    rows, meta = validate_paginated(api_client.list_trade_ins(ADMIN))
    # The two rejected calls persisted nothing at all.
    assert_pagination_meta(meta, total_count=1)
    assert len(rows) == 1


def test_trade_in_listing_paginates_then_filters_by_participant_and_status():
    """The trade-in list paginates in creation order and filters on two keys.

    PRD §3.2: "Trade-ins are readable individually by `ProgramAdmin`,
    `IntakeAgent`, `Authenticator` and `Customer`, and listable by the same four
    roles with optional filters on `customer_id`, `store_location_id`, `status`
    and `channel`, plus `limit` and `offset`."
    PRD §2.3: "Unless a specific endpoint states otherwise, every list endpoint
    returns its rows sorted by creation timestamp in ascending order."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the envelope's `meta` object, alongside the request
    identifier and timestamp."

    Design: Corner/entities/trade_in_listing_paginates_and_filters_by_customer_and_status
    """
    create_grade_policy(GRADE_POLICY_FOOTWEAR_A)
    create_credit_policy(CREDIT_POLICY_CORE)
    store = create_store_location()
    ava = create_customer(email="ava@example.com", full_name="Ava Reyes")
    ben = create_customer(email="ben@example.com", full_name="Ben Ortiz")

    item = dict(
        channel="IN_STORE",
        store_location_id=store["id"],
        product_category="FOOTWEAR",
        declared_grade="A",
        msrp_minor=120000,
    )
    # The clock is nudged between submissions so creation order is unambiguous.
    ava_first = create_trade_in(ava, item_mass_grams=900, **item)
    set_clock("2026-08-01T01:00:00Z")
    ava_second = create_trade_in(ava, item_mass_grams=950, **item)
    set_clock("2026-08-01T02:00:00Z")
    ben_only = create_trade_in(ben, item_mass_grams=800, **item)

    receive_trade_in(ava_first["id"])

    page, meta = validate_paginated(
        api_client.list_trade_ins(ADMIN, {"limit": 1, "offset": 0})
    )
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert_pagination_meta(meta, total_count=3, has_more=True)
    assert len(page) == 1
    assert page[0]["id"] == ava_first["id"]

    mine, meta = validate_paginated(
        api_client.list_trade_ins(ADMIN, {"customer_id": ava["id"]})
    )
    assert_pagination_meta(meta, total_count=2, has_more=False)
    assert {row["id"] for row in mine} == {ava_first["id"], ava_second["id"]}
    assert ben_only["id"] not in {row["id"] for row in mine}

    received, meta = validate_paginated(
        api_client.list_trade_ins(
            ADMIN, {"customer_id": ava["id"], "status": "RECEIVED"}
        )
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)
    assert received[0]["id"] == ava_first["id"]
    assert received[0]["status"] == "RECEIVED"


def test_a_new_trade_in_is_submitted_and_has_minted_nothing_downstream():
    """Submission alone produces no grant, no ledger entry and no unit.

    PRD §3.2: "On submission the trade-in enters `SUBMITTED` with
    `authenticity_result` set to `PENDING`, `assessed_grade` and
    `graded_by_user_id` both null, and `appeal_count` at 0."
    PRD §3.1: "Two derived quantities start at zero and are never written
    directly by a client: `credit_balance_minor`, the customer's live
    brand-currency balance, and `diverted_grams_total`, their lifetime diverted
    mass."
    PRD §2.6: "Most resources — customers, condition-tier policies,
    brand-currency policies, store locations, refurbishment bays, channels,
    trade-ins, brand-currency grants, resale units, refurbishment orders,
    markdown campaigns, resale orders and diversion reports — additionally carry
    `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation of the
    row, and `version`, an integer that is initialized to 1 when the row is
    created and incremented by exactly one on every mutation."

    Design: Corner/state_machines/trade_in_starts_in_submitted_with_no_downstream_rows
    """
    create_grade_policy(GRADE_POLICY_FOOTWEAR_A)
    create_credit_policy(CREDIT_POLICY_CORE)
    create_store_location()
    customer = create_customer(loyalty_tier="PLUS")

    trade_in = create_trade_in(
        customer,
        channel="MAIL_IN",
        product_category="FOOTWEAR",
        declared_grade="A",
        msrp_minor=120000,
        item_mass_grams=900,
    )
    assert trade_in["status"] == "SUBMITTED"
    assert trade_in["authenticity_result"] == "PENDING"
    assert trade_in["appeal_count"] == 0
    assert trade_in["version"] == 1
    assert_null(trade_in["received_at"], "received_at")
    assert_null(trade_in["accepted_at"], "accepted_at")
    assert_null(trade_in["assessed_grade"], "assessed_grade")

    grants, grant_meta = validate_paginated(
        api_client.list_credit_grants(ADMIN, {"customer_id": customer["id"]})
    )
    assert_pagination_meta(grant_meta, total_count=0)
    assert grants == []
    units, unit_meta = validate_paginated(
        api_client.list_resale_units(ADMIN, {"trade_in_id": trade_in["id"]})
    )
    assert_pagination_meta(unit_meta, total_count=0)
    assert units == []

    stored = fetch_customer(customer["id"])
    assert stored["credit_balance_minor"] == 0
    assert stored["diverted_grams_total"] == 0
    assert stored["version"] == 1


def test_second_receipt_of_the_same_trade_in_is_refused_and_writes_nothing():
    """Receipt is a one-shot transition, not an idempotent upsert.

    PRD §3.2: "The trade-in must actually be in `SUBMITTED` — anything else is
    `ERR_TRADE_IN_NOT_RECEIVABLE`."
    PRD §3.2: "Receipt writes `received_at` from the logical clock and increments
    the trade-in's version."

    Design: Corner/state_machines/trade_in_receive_applies_its_side_effects_once_and_is_not_idempotent
    """
    create_grade_policy(GRADE_POLICY_FOOTWEAR_A)
    create_credit_policy(CREDIT_POLICY_CORE)
    create_store_location()
    customer = create_customer(loyalty_tier="PLUS")
    trade_in = create_trade_in(
        customer,
        channel="MAIL_IN",
        product_category="FOOTWEAR",
        declared_grade="A",
        msrp_minor=120000,
        item_mass_grams=900,
    )
    assert trade_in["version"] == 1

    set_clock("2026-08-05T09:00:00Z")
    first = validate_success(api_client.receive_trade_in(trade_in["id"], INTAKE), 200)
    assert first["status"] == "RECEIVED"
    assert_instant(first["received_at"], "2026-08-05T09:00:00Z", "received_at")
    assert first["version"] == 2

    validate_error(
        api_client.receive_trade_in(trade_in["id"], INTAKE),
        "ERR_TRADE_IN_NOT_RECEIVABLE",
        409,
    )

    after = fetch_trade_in(trade_in["id"], INTAKE)
    assert after["status"] == "RECEIVED"
    assert_instant(after["received_at"], first["received_at"], "received_at")
    assert after["version"] == first["version"]


def test_receive_deadline_is_inclusive_and_channel_specific():
    """Receipt exactly on the deadline is on time; one second later is not.

    PRD §2.4: "A trade-in received at exactly its `receive_deadline_at` is on
    time."
    PRD §3.2: "The logical clock must be at or before `receive_deadline_at`; a
    receipt attempted strictly after the deadline is refused with
    `ERR_INTAKE_WINDOW_EXPIRED` and the trade-in does not change state, so an
    expired mail-in stays `SUBMITTED` rather than moving to some dead-letter
    status."
    PRD §3.2: "A mail-in submission gets three full weeks — twenty-one days from
    creation — because the item still has to travel; an in-store submission gets
    only two days, since the customer is standing at the counter."

    Design: Corner/validations/intake_deadline_is_inclusive_for_both_channels
    """
    create_grade_policy(GRADE_POLICY_OUTERWEAR_B)
    create_credit_policy(CREDIT_POLICY_CORE)
    store = create_store_location()
    customer = create_customer(loyalty_tier="PLUS")

    on_time = create_trade_in(customer, channel="MAIL_IN")
    late = create_trade_in(customer, channel="MAIL_IN")
    in_store = create_trade_in(
        customer, channel="IN_STORE", store_location_id=store["id"]
    )
    assert_instant(on_time["receive_deadline_at"], "2026-08-22T00:00:00Z", "mail-in deadline")
    assert_instant(in_store["receive_deadline_at"], "2026-08-03T00:00:00Z", "in-store deadline")

    set_clock("2026-08-03T00:00:00Z")
    stored_receipt = validate_success(
        api_client.receive_trade_in(in_store["id"], INTAKE), 200
    )
    assert stored_receipt["status"] == "RECEIVED"
    assert_instant(stored_receipt["received_at"], "2026-08-03T00:00:00Z", "received_at")

    set_clock("2026-08-22T00:00:00Z")
    mail_receipt = validate_success(
        api_client.receive_trade_in(on_time["id"], INTAKE), 200
    )
    assert mail_receipt["status"] == "RECEIVED"
    assert_instant(mail_receipt["received_at"], "2026-08-22T00:00:00Z", "received_at")

    set_clock("2026-08-22T00:00:01Z")
    validate_error(
        api_client.receive_trade_in(late["id"], INTAKE),
        "ERR_INTAKE_WINDOW_EXPIRED",
        409,
    )
    untouched = fetch_trade_in(late["id"], INTAKE)
    assert untouched["status"] == "SUBMITTED"
    assert_null(untouched["received_at"], "received_at")


def test_body_foreign_key_outranks_suspension_which_outranks_a_closed_store():
    """Existence, then participant standing, then infrastructure standing.

    PRD §2.11: "**Body foreign keys.** Every identifier supplied in a request
    body must reference an existing row of its declared entity — `customer_id`,
    `store_location_id`, `channel_id`, `resale_unit_id`, `refurb_bay_id`,
    `credit_policy_id` and `supersedes_report_id` — reported with the same
    per-entity 404 codes."
    PRD §2.11: "**Referenced-party standing.** The referenced customer must be
    `ACTIVE`, otherwise `ERR_CUSTOMER_SUSPENDED` (409), on trade-in submission
    and on resale order placement."
    PRD §2.11: "Then the referenced infrastructure must be usable: a store must
    be `ACTIVE`, otherwise `ERR_STORE_LOCATION_CLOSED`; a bay must be
    `AVAILABLE`, otherwise `ERR_BAY_OUT_OF_SERVICE`; a channel must be `ACTIVE`,
    otherwise `ERR_CHANNEL_NOT_ACTIVE`; each of the three carries HTTP 409."

    Design: Corner/validations/missing_foreign_key_outranks_customer_suspension_and_closed_store
    """
    create_grade_policy(GRADE_POLICY_OUTERWEAR_B)
    create_credit_policy(CREDIT_POLICY_CORE)
    store = create_store_location()
    customer = create_customer()
    suspended = validate_success(
        api_client.patch_customer(customer["id"], {"status": "SUSPENDED"}, ADMIN), 200
    )
    assert suspended["status"] == "SUSPENDED"

    caller = make_customer_headers(customer["id"])

    # The bogus store is resolved before the suspension is even consulted.
    validate_error(
        api_client.create_trade_in(
            create_trade_in_payload(
                customer["id"], channel="IN_STORE", store_location_id=NON_EXISTENT_UUID
            ),
            caller,
        ),
        "ERR_STORE_LOCATION_NOT_FOUND",
        404,
    )

    # With every identifier resolving, the participant's standing surfaces.
    validate_error(
        api_client.create_trade_in(
            create_trade_in_payload(
                customer["id"], channel="IN_STORE", store_location_id=store["id"]
            ),
            caller,
        ),
        "ERR_CUSTOMER_SUSPENDED",
        409,
    )

    validate_success(
        api_client.patch_customer(customer["id"], {"status": "ACTIVE"}, ADMIN), 200
    )
    closed = validate_success(
        api_client.patch_store_location(store["id"], {"status": "CLOSED"}, ADMIN), 200
    )
    assert closed["status"] == "CLOSED"
    validate_error(
        api_client.create_trade_in(
            create_trade_in_payload(
                customer["id"], channel="IN_STORE", store_location_id=store["id"]
            ),
            caller,
        ),
        "ERR_STORE_LOCATION_CLOSED",
        409,
    )

    validate_success(
        api_client.patch_store_location(store["id"], {"status": "ACTIVE"}, ADMIN), 200
    )
    accepted = validate_success(
        api_client.create_trade_in(
            create_trade_in_payload(
                customer["id"], channel="IN_STORE", store_location_id=store["id"]
            ),
            caller,
        ),
        201,
    )
    assert accepted["status"] == "SUBMITTED"
    assert_instant(
        accepted["receive_deadline_at"], "2026-08-03T00:00:00Z", "in-store deadline"
    )


def test_missing_policies_and_the_counterfeit_bar_refuse_the_intake_path():
    """Three distinct 409s guard the intake path.

    PRD §3.2: "It reads the single `ACTIVE` condition-tier policy for the pair
    (`product_category`, `declared_grade`) and the single `ACTIVE`
    brand-currency policy; if either is absent, submission fails with
    `ERR_GRADE_POLICY_MISSING` or `ERR_CREDIT_POLICY_MISSING` respectively."
    PRD §3.4: "The `authenticity_result` must be either `GENUINE` or
    `INCONCLUSIVE`; a trade-in the grader marked `COUNTERFEIT` can never be
    accepted, and the attempt is refused with `ERR_COUNTERFEIT_NOT_ACCEPTABLE`,
    leaving rejection as the only permitted disposition for a counterfeit."
    PRD §3.4: "The trade-in moves to `REJECTED`, `reject_reason` is written from
    the request body, `appraised_credit_minor` is zeroed out — the provisional
    quote is explicitly withdrawn rather than left standing — and the version is
    bumped."

    Design: Corner/errors/intake_policy_gates_and_counterfeit_rejection_are_triggerable
    """
    create_grade_policy(GRADE_POLICY_OUTERWEAR_B)
    create_store_location()
    customer = create_customer(loyalty_tier="PLUS")
    caller = make_customer_headers(customer["id"])

    # No brand-currency policy is live yet, and the mail-in bonus needs one.
    validate_error(
        api_client.create_trade_in(
            create_trade_in_payload(customer["id"], channel="MAIL_IN"), caller
        ),
        "ERR_CREDIT_POLICY_MISSING",
        409,
    )

    create_credit_policy(CREDIT_POLICY_CORE)

    # A BAG grade B condition-tier policy was never published.
    validate_error(
        api_client.create_trade_in(
            create_trade_in_payload(
                customer["id"], channel="MAIL_IN", product_category="BAG",
                item_mass_grams=900,
            ),
            caller,
        ),
        "ERR_GRADE_POLICY_MISSING",
        409,
    )

    trade_in = create_trade_in(customer, channel="MAIL_IN")
    # base 10000 plus the 1000 mail-in bonus; the PLUS term is withheld here.
    assert trade_in["appraised_credit_minor"] == 11000

    receive_trade_in(trade_in["id"])
    graded = authenticate_trade_in(trade_in["id"], "COUNTERFEIT", "B")
    assert graded["authenticity_result"] == "COUNTERFEIT"
    assert graded["status"] == "AUTHENTICATED"

    validate_error(
        api_client.disposition_trade_in(
            trade_in["id"],
            {"decision": "ACCEPT", "ownership_treatment": "OWNED_INVENTORY"},
            AUTH1,
        ),
        "ERR_COUNTERFEIT_NOT_ACCEPTABLE",
        409,
    )

    rejected = validate_success(
        api_client.disposition_trade_in(
            trade_in["id"],
            {"decision": "REJECT", "reject_reason": "counterfeit item, returned to sender"},
            AUTH1,
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["reject_reason"] == "counterfeit item, returned to sender"
    assert rejected["appraised_credit_minor"] == 0
    assert units_of_trade_in(trade_in["id"]) == []
    assert grants_of_trade_in(trade_in["id"]) == []
