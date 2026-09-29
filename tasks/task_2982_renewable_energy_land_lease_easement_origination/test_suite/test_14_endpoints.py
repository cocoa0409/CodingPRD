"""Endpoint claims: the lifecycle-free CRUD triple, the one PATCH, an action and a computed read."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import (
    assert_acres_equals,
    assert_ascending_by_created_at,
    assert_cents_equals,
    assert_instant_equals,
    assert_null,
    assert_page_meta,
    assert_rate_equals,
    assert_status,
    assert_version_is,
)
from test_helpers.factories import projection_params
from test_helpers.fixtures import (
    accept_option,
    amend_landowner,
    client,
    draft_royalty_option,
    execute_option,
    exercise_option,
    plan_corridor,
    publish_setback_rule,
    read_corridor,
    read_landowner,
    read_lease,
    register_landowner,
    register_parcel,
    send_option,
    set_clock,
)
from test_helpers.test_users import PAYMENT_ADMIN, PORTFOLIO_MANAGER, TITLE_COUNSEL

SANDHILL = {
    "legal_name": "Sandhill Prairie LLC",
    "entity_type": "LLC",
    "mailing_state": "TX",
    "contact_email": "ops@sandhill.example",
    "w9_on_file": True,
    "payment_hold": False,
}

CAPROCK_OWNER = {
    "legal_name": "Caprock Ranch Holdings LLC",
    "entity_type": "LLC",
    "mailing_state": "TX",
    "contact_email": "land@caprock.example",
    "w9_on_file": True,
    "payment_hold": False,
}


def _two_ordinances_in_two_counties():
    """One waivable property-line rule here, one unwaivable road rule next door."""
    first = publish_setback_rule(
        jurisdiction_code="48451",
        rule_type="PROPERTY_LINE",
        setback_feet=150,
        encumbrance_rate_per_acre=0.0600,
        consent_waivable=True,
    )
    second = publish_setback_rule(
        jurisdiction_code="48029",
        rule_type="PUBLIC_ROAD",
        setback_feet=75,
        encumbrance_rate_per_acre=0.0300,
        consent_waivable=False,
    )
    return first, second


def test_the_jurisdiction_filter_returns_only_that_countys_ordinance():
    """
    Two ordinances are on the books in two different counties. The exact-match
    jurisdiction filter separates them, and the envelope counts what matched rather
    than what exists.

    PRD: "Rules are readable individually and as a collection filtered by jurisdiction
    or type; a body `setback_rule_id` naming no rule is answered with
    `ERR_SETBACK_RULE_NOT_FOUND` (404)."

    Design: Corner/endpoints/setback_rule_create_then_read_then_list_by_jurisdiction
    """
    first, _second = _two_ordinances_in_two_counties()

    response = client().list_setback_rules(
        TITLE_COUNSEL, {"jurisdiction_code": "48451", "limit": 10, "offset": 0}
    )

    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert_page_meta(meta, total_count=1, has_more=False, limit=10, offset=0)
    assert rows[0]["id"] == first["id"], rows[0]["id"]
    assert_rate_equals(
        rows[0]["encumbrance_rate_per_acre"], 0.0600, "encumbrance_rate_per_acre"
    )


def test_each_published_ordinance_is_readable_on_its_own_and_in_the_full_list():
    """
    The only entity with no lifecycle and no parent is the clean create-read-list
    triple: the second rule comes back on its own identifier with the flags it was
    published with, and the unfiltered collection holds both, oldest first.

    PRD: "Setback rules have no lifecycle at all: once published, a rule simply
    exists."

    Design: Corner/endpoints/setback_rule_create_then_read_then_list_by_jurisdiction
    """
    _first, second = _two_ordinances_in_two_counties()

    rule = validate_success(client().get_setback_rule(second["id"], TITLE_COUNSEL), 200)

    assert rule["jurisdiction_code"] == "48029", rule["jurisdiction_code"]
    assert rule["rule_type"] == "PUBLIC_ROAD", rule["rule_type"]
    assert rule["consent_waivable"] is False, rule["consent_waivable"]
    rows, meta = validate_paginated(client().list_setback_rules(TITLE_COUNSEL, {}))
    assert_page_meta(meta, total_count=2)
    assert_ascending_by_created_at(rows, "setback rules")


def test_the_amendment_moves_both_payable_flags_and_bumps_the_version():
    """
    The one partial update in the API is deliberately narrow. It carries the two
    payable flags, and the accepted amendment lands the owner on the second version of
    the row.

    PRD: "Only a `PaymentAdministrator` may amend a landowner afterwards, and only the
    payable attributes are mutable: `contact_email`, `w9_on_file` and `payment_hold`."

    Design: Corner/endpoints/patch_landowner_updates_only_the_payable_flags_and_bumps_version
    """
    registered = register_landowner(**dict(SANDHILL, w9_on_file=False, payment_hold=False))
    assert_version_is(registered, 1, "landowner")

    amended = amend_landowner(registered["id"], w9_on_file=True, payment_hold=True)

    assert amended["w9_on_file"] is True, amended["w9_on_file"]
    assert amended["payment_hold"] is True, amended["payment_hold"]
    assert_version_is(amended, 2, "amended landowner")


def test_the_amendment_leaves_the_deed_identity_and_the_ledger_alone():
    """
    The recorded instruments depend on the identity fields, so the amendment may not
    touch them — and because it is not a state change, it runs no posture cascade and
    moves no money.

    PRD: "The `legal_name` and `entity_type` are fixed at registration — they are what
    the recorded instruments will say — and are not accepted on an amendment."

    Design: Corner/endpoints/patch_landowner_updates_only_the_payable_flags_and_bumps_version
    """
    registered = register_landowner(**dict(SANDHILL, w9_on_file=False, payment_hold=False))

    amend_landowner(registered["id"], w9_on_file=True, payment_hold=True)

    landowner = read_landowner(registered["id"], PAYMENT_ADMIN)
    assert landowner["legal_name"] == "Sandhill Prairie LLC", landowner["legal_name"]
    assert landowner["entity_type"] == "LLC", landowner["entity_type"]
    assert landowner["mailing_state"] == "TX", landowner["mailing_state"]
    assert_status(landowner, "PROSPECT", "landowner")
    assert_cents_equals(landowner["total_paid_cents"], 0, "total_paid_cents")


def test_permitting_stamps_the_instant_the_logical_clock_reads():
    """
    The route permit is a bodyless action whose only visible effects are the status
    flip and one timestamp, and that timestamp comes from the logical clock the
    harness moved rather than from wall time.

    PRD: "The route-permit action, available only to a `PortfolioManager`, moves it
    `PLANNED → PERMITTED` and stamps `permitted_at` from the logical clock;
    `PERMITTED` is terminal."

    Design: Corner/endpoints/permit_corridor_action_endpoint_stamps_permitted_at_from_the_logical_clock
    """
    corridor = plan_corridor(
        route_name="Sandhill Gen-Tie 138",
        total_length_m=8000,
        voltage_class="GENTIE_138KV",
        buffer_m=120,
    )
    assert_status(corridor, "PLANNED", "corridor")
    assert_null(corridor["permitted_at"], "permitted_at")
    set_clock("2026-08-10T00:00:00Z", PORTFOLIO_MANAGER)

    response = client().permit_corridor(corridor["id"], {}, PORTFOLIO_MANAGER)

    permitted = validate_success(response, 200)
    assert_status(permitted, "PERMITTED", "corridor")
    assert_instant_equals(
        permitted["permitted_at"], "2026-08-10T00:00:00Z", "permitted_at"
    )


def test_permitting_grants_no_crossing_and_the_advance_sweeps_nothing():
    """
    Nothing else in the store can be swept by the clock advance, and permitting the
    route grants no crossing over it, so the corridor's own count stays where planning
    put it and its buffer is untouched.

    PRD: "A corridor opens in `PLANNED` with `granted_crossing_count` of 0 and a null
    `permitted_at`."

    Design: Corner/endpoints/permit_corridor_action_endpoint_stamps_permitted_at_from_the_logical_clock
    """
    corridor = plan_corridor(
        route_name="Sandhill Gen-Tie 138",
        total_length_m=8000,
        voltage_class="GENTIE_138KV",
        buffer_m=120,
    )

    sweeps = set_clock("2026-08-10T00:00:00Z", PORTFOLIO_MANAGER)
    client().permit_corridor(corridor["id"], {}, PORTFOLIO_MANAGER)

    assert sweeps["expired_option_count"] == 0, sweeps["expired_option_count"]
    assert sweeps["completed_booking_count"] == 0, sweeps["completed_booking_count"]
    after = read_corridor(corridor["id"])
    assert after["granted_crossing_count"] == 0, after["granted_crossing_count"]
    assert after["buffer_m"] == 120, after["buffer_m"]


def _royalty_lease_on_a_hundred_and_fifty_buildable_acres():
    """A royalty-hybrid lease whose as-built basis is three quarters of the deed."""
    landowner_id = register_landowner(**CAPROCK_OWNER)["id"]
    publish_setback_rule(
        jurisdiction_code="48453",
        rule_type="OCCUPIED_DWELLING",
        setback_feet=1200,
        encumbrance_rate_per_acre=0.2500,
        consent_waivable=True,
    )
    parcel = register_parcel(
        landowner_id,
        apn="R-8453-200",
        county_fips="48453",
        gross_acres=200.00,
        interconnection_distance_km=3.50,
        resource_capacity_factor=0.38,
        slope_pct=4.0,
        title_condition_grade="B",
        zoning_code="AG2",
    )
    assert_acres_equals(parcel["raw_setback_acres"], 50.00, "raw_setback_acres")
    assert_acres_equals(parcel["buildable_acres"], 150.00, "buildable_acres")
    assert_status(parcel, "QUALIFIED", "parcel")
    option = draft_royalty_option(
        parcel["id"],
        landowner_id,
        option_term_days=365,
        option_fee_per_acre_cents=2500,
        extension_count_allowed=1,
        extension_fee_per_acre_cents=3000,
        base_rent_per_acre_cents=120000,
        royalty_rate_bps=350,
        escalator_pct_bps=200,
        escalator_mode="SIMPLE",
    )
    send_option(option["id"])
    accept_option(option["id"], landowner_id)
    execute_option(option["id"])
    lease = exercise_option(option["id"], "NOE-2026-0002")
    assert_acres_equals(
        lease["acre_basis_at_exercise"], 150.00, "acre_basis_at_exercise"
    )
    assert_cents_equals(
        lease["total_security_required_cents"], 7837500, "total_security_required_cents"
    )
    return lease


def test_the_projection_returns_both_rent_variants_side_by_side():
    """
    One read answers what two invoices would have said about the same lease year: the
    deeded-acre figure with the royalty suppressed, the as-built figure with the
    royalty in the greater-of, and the signed difference between them.

    PRD: "It takes a `period_year` and a `production_mwh` assumption and returns both
    variants side by side for comparison without creating anything:
    `lease_agreement_id` and `period_year` echo the inputs, `provisional_acre_basis`
    and `provisional_gross_rent_cents` give the deeded-acre royalty-suppressed figure,
    `final_acre_basis`, `final_per_acre_component_cents`,
    `final_royalty_component_cents` and `final_gross_rent_cents` give the as-built
    figure with the royalty in play, and `variant_delta_cents` is
    `final_gross_rent_cents` less `provisional_gross_rent_cents`."

    Design: Corner/endpoints/rent_projection_computed_read_returns_both_variants_without_persisting
    """
    lease = _royalty_lease_on_a_hundred_and_fifty_buildable_acres()

    response = client().get_rent_projection(
        lease["id"], projection_params(3, 100000), PORTFOLIO_MANAGER
    )

    projection = validate_success(response, 200)
    assert response.json()["response_type"] == "object"
    assert projection["lease_agreement_id"] == lease["id"]
    assert projection["period_year"] == 3, projection["period_year"]
    assert_acres_equals(
        projection["provisional_acre_basis"], 200.00, "provisional_acre_basis"
    )
    assert_cents_equals(
        projection["provisional_gross_rent_cents"], 24960000, "provisional gross"
    )
    assert_acres_equals(projection["final_acre_basis"], 150.00, "final_acre_basis")
    assert_cents_equals(
        projection["final_per_acre_component_cents"], 18720000, "final per-acre"
    )
    assert_cents_equals(
        projection["final_royalty_component_cents"], 14700000, "final royalty"
    )
    assert_cents_equals(projection["final_gross_rent_cents"], 18720000, "final gross")
    assert_cents_equals(projection["variant_delta_cents"], -6240000, "variant_delta_cents")


def test_the_projection_writes_nothing_it_projected():
    """
    The computed read is the one place the two variants are evaluated without a row
    being created, so afterwards the lease carries no invoice, sits on the version
    exercise left it on, and has not been nudged toward recording.

    PRD: "Because that difference is material to a developer's model, the API exposes a
    **non-persisting projection capability** on a lease, available to a
    `PortfolioManager` or a `PaymentAdministrator`."

    Design: Corner/endpoints/rent_projection_computed_read_returns_both_variants_without_persisting
    """
    lease = _royalty_lease_on_a_hundred_and_fifty_buildable_acres()

    client().get_rent_projection(
        lease["id"], projection_params(3, 100000), PORTFOLIO_MANAGER
    )

    _rows, meta = validate_paginated(
        client().list_rent_invoices(
            PAYMENT_ADMIN, {"lease_agreement_id": lease["id"]}
        )
    )
    assert_page_meta(meta, total_count=0)
    after = read_lease(lease["id"])
    assert_version_is(after, lease["version"], "lease")
    assert after["recording_status"] == "UNRECORDED", after["recording_status"]
