"""Entity shapes: what the server assigns, what it inherits, and what it defaults.

Creation-time postures across the franchise spine — the zeroed franchisee counters, the two
registration defaults, the four fields a club copies off its territory, the append-only guest
usage row — plus the schema and existence refusals that stop a malformed spine being written
at all.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_append_only_fields,
    assert_club,
    assert_common_fields,
    assert_franchisee,
    assert_member,
    create_club_payload,
    create_franchisee,
    create_franchisee_payload,
    create_member,
    create_member_payload,
    create_territory,
    create_territory_payload,
    make_club_manager_headers,
    make_franchise_owner_headers,
    read_club,
    read_territory,
    setup_guest_usage_scenario,
    setup_single_club_franchise,
    setup_two_franchise_clubs,
    sign_agreement,
)

BRAND = TEST_USERS["brand_administrator_headers"]


def test_registration_stores_the_stated_royalty_rate_rather_than_the_default():
    """A 900-basis-point rate is stored as given, and the flag stated as false is not quietly
    flipped to the eligible default.

    PRD 3.1: "Two commercial parameters may be supplied at registration and both have
    defaults: `royalty_rate_bps` expresses the royalty rate in basis points against the
    verified dues basis and defaults to 650 — that is, six and a half percent — with an
    accepted range of 0 through 1200 inclusive; and `national_account_eligible`, which
    defaults to true, determines whether the operator participates in corporate revenue
    sharing at all."

    Design: Corner/entities/corner_franchisee_created_with_explicit_royalty_rate_and_zeroed_counters
    """
    created = validate_success(
        api_client.create_franchisee(
            create_franchisee_payload(
                legal_name="Summit Strength Holdings LLC",
                contact_email="ops@summitstrength.example",
                royalty_rate_bps=900,
                national_account_eligible=False,
            ),
            BRAND,
        ),
        expected_status=201,
    )

    assert_franchisee(created)
    assert created["legal_name"] == "Summit Strength Holdings LLC"
    assert created["royalty_rate_bps"] == 900
    assert created["national_account_eligible"] is False
    assert created["version"] == 1


def test_a_new_operator_starts_at_full_standing_with_every_counter_at_zero():
    """Registration does no scoring work of its own: the operator arrives at 100 points with
    nothing yet recorded against it.

    PRD 3.1: "A newly registered operator starts in `ACTIVE` standing with `compliance_score`
    at 100, `inspection_fail_streak` at 0, `collections_watch_club_count` at 0,
    `disputed_royalty_count` at 0 and `corporate_allocation_cents` at 0."

    Design: Corner/entities/corner_franchisee_created_with_explicit_royalty_rate_and_zeroed_counters
    """
    created = create_franchisee(
        legal_name="Summit Strength Holdings LLC",
        contact_email="ops@summitstrength.example",
        royalty_rate_bps=900,
    )

    assert created["status"] == "ACTIVE"
    assert created["compliance_score"] == 100
    assert created["inspection_fail_streak"] == 0
    assert created["collections_watch_club_count"] == 0
    assert created["disputed_royalty_count"] == 0
    assert created["corporate_allocation_cents"] == 0


def test_omitting_both_commercial_parameters_falls_back_to_six_and_a_half_percent():
    """With neither optional input supplied the operator is billed at 650 basis points and is
    eligible for corporate revenue sharing.

    PRD 3.1: "Two commercial parameters may be supplied at registration and both have
    defaults: `royalty_rate_bps` expresses the royalty rate in basis points against the
    verified dues basis and defaults to 650 — that is, six and a half percent — with an
    accepted range of 0 through 1200 inclusive; and `national_account_eligible`, which
    defaults to true, determines whether the operator participates in corporate revenue
    sharing at all."

    Design: Corner/entities/corner_franchisee_defaults_royalty_rate_and_national_account_flag
    """
    created = validate_success(
        api_client.create_franchisee(
            {
                "legal_name": "Harborline Fitness LLC",
                "contact_email": "ops@harborlinefit.example",
            },
            BRAND,
        ),
        expected_status=201,
    )

    assert created["royalty_rate_bps"] == 650
    assert created["national_account_eligible"] is True


def test_a_grant_without_a_protected_radius_is_malformed():
    """`protected_radius_km` has no default, so a grant that omits it is stopped in the schema
    band rather than written with a meaningless null circle.

    PRD 2.6: "All required body fields are present with correct types; enum values fall inside
    their declared sets; dates are `YYYY-MM-DD` and every `period_month` is `YYYY-MM`; integer
    money fields are at least 0; `discount_pct` and `corporate_credit_pct` lie within 0 through
    1 inclusive; `center_lat`, `requested_lat` and any other latitude lies within −90 through
    90; `center_lng`, `requested_lng` and any other longitude lies within −180 through 180;
    `protected_radius_km` and `requested_radius_km` are greater than 0; `visit_count` is at
    least 1; `limit` lies within 1 through 100; `offset` is at least 0."

    Design: Corner/entities/corner_territory_creation_rejects_missing_protected_radius
    """
    franchisee = create_franchisee(
        legal_name="Harborline Fitness LLC", contact_email="ops@harborlinefit.example"
    )

    response = api_client.create_territory(
        {
            "franchisee_id": franchisee["id"],
            "center_lat": 34.0,
            "center_lng": -118.0,
            "state_code": "CA",
        },
        BRAND,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_a_radius_below_the_half_kilometre_minimum_is_refused():
    """0.4 km is a positive number and still outside the accepted band, so the numeric range is
    enforced rather than merely the sign.

    PRD 3.1: "A grant names the receiving `franchisee_id`, the protected circle's centre as
    `center_lat` and `center_lng`, its `protected_radius_km` — accepted between 0.5 and 50.0
    kilometres inclusive — and the `state_code` whose health-club statute will govern agreements
    signed there."

    Design: Corner/entities/corner_territory_radius_below_half_kilometre_is_out_of_range
    """
    franchisee = create_franchisee(
        legal_name="Harborline Fitness LLC", contact_email="ops@harborlinefit.example"
    )

    response = api_client.create_territory(
        create_territory_payload(franchisee["id"], protected_radius_km=0.4), BRAND
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_a_state_outside_the_three_modelled_jurisdictions_is_refused():
    """`AZ` is not one of the three statutes this network models, and neither refused grant
    leaves a trade area behind.

    PRD 2.9: "Three jurisdictions are modelled, and the `state_code` enumeration is exactly
    `CA`, `TX`, `NY`."

    Design: Corner/entities/corner_territory_radius_below_half_kilometre_is_out_of_range
    """
    franchisee = create_franchisee(
        legal_name="Harborline Fitness LLC", contact_email="ops@harborlinefit.example"
    )
    api_client.create_territory(
        create_territory_payload(franchisee["id"], protected_radius_km=0.4), BRAND
    )

    response = api_client.create_territory(
        create_territory_payload(franchisee["id"], state_code="AZ"), BRAND
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    _, meta = validate_paginated(api_client.list_territories(BRAND))
    assert meta["total_count"] == 0


def test_a_grant_to_an_unknown_operator_returns_the_franchisee_specific_code():
    """The parent reference is resolved before anything else about the circle matters, and it
    answers with the `Franchisee` family's own code rather than a generic one.

    PRD 2.6: "The 404 codes are grouped by family: `ERR_FRANCHISEE_NOT_FOUND` for a missing
    `Franchisee`; `ERR_TERRITORY_NOT_FOUND` for a missing `Territory`; `ERR_CLUB_NOT_FOUND` for
    any missing club reference, whether it arrived as `club_id`, `home_club_id`, `host_club_id`,
    `from_club_id` or `to_club_id`; `ERR_MEMBER_NOT_FOUND` for a missing `Member`;
    `ERR_PLAN_ASSET_NOT_FOUND` for a missing `MembershipPlanTemplate`, `Promotion` or
    `CorporateAccount`; `ERR_MEMBERSHIP_RECORD_NOT_FOUND` for a missing `MembershipAgreement`,
    `TransferRequest`, `GuestUsageEvent` or `BillingEvent`; and `ERR_OPS_RECORD_NOT_FOUND` for a
    missing `RelocationRequest`, `FacilityInspection`, `UsageSettlement` or `RoyaltyReport`."

    Design: Corner/entities/corner_territory_creation_rejects_unknown_franchisee
    """
    response = api_client.create_territory(
        create_territory_payload(NON_EXISTENT_UUID), BRAND
    )
    validate_error(response, ApiErrorId.ERR_FRANCHISEE_NOT_FOUND.value)


def test_an_unknown_club_id_on_the_single_read_returns_the_club_specific_code():
    """A well-formed identifier that names nothing is a `Club` existence failure, not one of the
    grouped record buckets.

    PRD 2.6: "The 404 codes are grouped by family: `ERR_FRANCHISEE_NOT_FOUND` for a missing
    `Franchisee`; `ERR_TERRITORY_NOT_FOUND` for a missing `Territory`; `ERR_CLUB_NOT_FOUND` for
    any missing club reference, whether it arrived as `club_id`, `home_club_id`, `host_club_id`,
    `from_club_id` or `to_club_id`; `ERR_MEMBER_NOT_FOUND` for a missing `Member`;
    `ERR_PLAN_ASSET_NOT_FOUND` for a missing `MembershipPlanTemplate`, `Promotion` or
    `CorporateAccount`; `ERR_MEMBERSHIP_RECORD_NOT_FOUND` for a missing `MembershipAgreement`,
    `TransferRequest`, `GuestUsageEvent` or `BillingEvent`; and `ERR_OPS_RECORD_NOT_FOUND` for a
    missing `RelocationRequest`, `FacilityInspection`, `UsageSettlement` or `RoyaltyReport`."

    Design: Corner/entities/corner_get_club_with_unknown_id_returns_club_not_found
    """
    response = api_client.get_club(NON_EXISTENT_UUID, BRAND)
    validate_error(response, ApiErrorId.ERR_CLUB_NOT_FOUND.value)


def test_a_club_shell_copies_its_operator_state_and_coordinates_off_the_territory():
    """None of the four inherited fields appear on the create payload, yet the shell reports the
    territory's own operator, statute and centre point.

    PRD 3.1: "Four fields are inherited rather than accepted: `franchisee_id`, `state_code`,
    `lat` and `lng` are copied from the parent territory at creation — `lat` and `lng` from the
    territory's centre — and any client-supplied value for them is ignored outright rather than
    rejected."

    Design: Corner/entities/corner_club_inherits_franchisee_state_and_coordinates_from_territory
    """
    franchisee = create_franchisee(
        legal_name="Harborline Fitness LLC", contact_email="ops@harborlinefit.example"
    )
    territory = create_territory(
        franchisee["id"], center_lat=34.0, center_lng=-118.0, protected_radius_km=5.0
    )

    shell = validate_success(
        api_client.create_club(
            create_club_payload(territory["id"], name="Harborline Downtown"),
            make_franchise_owner_headers(franchisee["id"]),
        ),
        expected_status=201,
    )
    assert_club(shell)
    assert shell["franchisee_id"] == franchisee["id"]
    assert shell["state_code"] == "CA"
    assert shell["lat"] == 34.0
    assert shell["lng"] == -118.0


def test_a_club_shell_starts_compliant_unscored_and_with_a_flat_ledger():
    """Every computed posture on a brand-new shell sits at its documented zero, and holding only
    a shell does not activate the trade area.

    PRD 3.1: "A new shell starts with `status` `PRE_OPENING`, `equipment_compliance_state`
    `COMPLIANT`, `last_inspection_score` null, `active_agreement_count` 0,
    `delinquent_member_count` 0, `collections_watch` false and `settlement_ledger_cents` 0."

    Design: Corner/entities/corner_club_inherits_franchisee_state_and_coordinates_from_territory
    """
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        open_the_club=False,
        with_plan=False,
    )

    shell = read_club(scenario["club"]["id"])
    assert shell["status"] == "PRE_OPENING"
    assert shell["equipment_compliance_state"] == "COMPLIANT"
    assert shell["last_inspection_score"] is None
    assert shell["active_agreement_count"] == 0
    assert shell["delinquent_member_count"] == 0
    assert shell["collections_watch"] is False
    assert shell["settlement_ledger_cents"] == 0
    assert read_territory(scenario["territory"]["id"])["status"] == "RESERVED"


def test_omitting_the_guest_fee_stores_the_brand_standard_rate():
    """The per-visit rate a shell inherits by default is 1250 cents, which is the figure later
    pinned into every visit batch.

    PRD 3.1: "The shell names its `territory_id`, its trading `name`, and the `opened_on` date on
    which the location opened, written as a `YYYY-MM-DD` calendar date; a per-visit
    `guest_fee_cents` charged to visiting members' home clubs may also be supplied, defaulting to
    1250 cents and accepted between 0 and 5000 inclusive."

    Design: Corner/entities/corner_club_defaults_guest_fee_to_twelve_hundred_fifty_cents
    """
    franchisee = create_franchisee(
        legal_name="Harborline Fitness LLC", contact_email="ops@harborlinefit.example"
    )
    territory = create_territory(franchisee["id"])

    shell = validate_success(
        api_client.create_club(
            {
                "territory_id": territory["id"],
                "name": "Harborline Downtown",
                "opened_on": "2024-05-01",
            },
            make_franchise_owner_headers(franchisee["id"]),
        ),
        expected_status=201,
    )
    assert shell["guest_fee_cents"] == 1250


def test_a_member_record_is_minted_with_server_owned_identity_and_version_one():
    """The four common properties are all assigned by the server; none of them appear among the
    endpoint's inputs.

    PRD 2.5: "`version` is an integer that starts at 1 when the record is created and increments
    by exactly 1 on every mutation of that record — including mutations caused by a cascade from
    a different entity's operation, not merely by direct writes to the record itself."

    Design: Corner/entities/corner_member_system_fields_are_server_assigned_at_creation
    """
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        with_plan=False,
    )

    created = validate_success(
        api_client.create_member(
            create_member_payload(full_name="Ana Reyes", email="ana.reyes@example.com"),
            make_club_manager_headers(scenario["club"]["id"]),
        ),
        expected_status=201,
    )
    assert_common_fields(created)
    assert_member(created)
    assert created["version"] == 1


def test_a_fresh_member_holds_nothing_and_is_active():
    """The system-owned status and the computed agreement count both start where the contract
    says, before any membership is sold.

    PRD 3.3: "A member is created with `status` `ACTIVE` and `agreement_count` 0."

    Design: Corner/entities/corner_member_system_fields_are_server_assigned_at_creation
    """
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        with_plan=False,
    )

    member = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    assert member["status"] == "ACTIVE"
    assert member["agreement_count"] == 0


def test_a_visit_batch_carries_no_version_and_no_updated_timestamp():
    """The ledger row exposes only the two system fields an append-only record is allowed, and
    there is no operation that could edit it.

    PRD 2.5: "A `BillingEvent` and a `GuestUsageEvent` each carry only `id` and `created_at`:
    neither has an `updated_at` field and neither has a `version` field, and there is no endpoint
    that updates either one."

    Design: Corner/entities/corner_guest_usage_event_is_append_only_with_no_version_field
    """
    scenario = setup_guest_usage_scenario(period_visits=[("2026-08", 4)])
    event = scenario["guest_usage_events"][0]

    assert_append_only_fields(event)
    assert "version" not in event
    assert "updated_at" not in event


def test_a_visit_batch_pins_the_home_club_the_fee_and_the_computed_total():
    """Four visits at a 1250-cent host fee is 5000 cents, snapshotted against the home club as it
    stood at recording time and not yet swept into any settlement.

    PRD 3.7: "`home_club_id_at_visit` captures the agreement's `home_club_id` as it stands at
    that instant, which means a later transfer never re-points historical usage at the new home
    club. `guest_fee_cents_at_visit` captures the host club's `guest_fee_cents` as it stands at
    that instant. And `usage_fee_cents` is `visit_count` multiplied by `guest_fee_cents_at_visit`.
    The batch is created unsettled, with `settlement_id` null, and it is immutable: it has no
    `version`, no `updated_at`, and no update operation."

    Design: Corner/entities/corner_guest_usage_event_is_append_only_with_no_version_field
    """
    scenario = setup_guest_usage_scenario(period_visits=[("2026-08", 4)])
    event = scenario["guest_usage_events"][0]

    assert event["home_club_id_at_visit"] == scenario["home_club"]["id"]
    assert event["guest_fee_cents_at_visit"] == 1250
    assert event["visit_count"] == 4
    assert event["usage_fee_cents"] == 5000
    assert event["settlement_id"] is None


def test_the_first_page_of_the_club_listing_reports_the_unpaginated_total():
    """Two rows come back on a page of two, while the envelope still reports all three matching
    clubs and flags that more remain.

    PRD 2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count` (the
    number of rows matching the filters before the page window is applied) and `has_more` (true
    when rows remain beyond the current window)."

    Design: Corner/entities/corner_club_list_returns_paginated_envelope_with_total_count_and_has_more
    """
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        open_the_club=False,
        with_plan=False,
    )
    franchisee_id = scenario["franchisee"]["id"]
    for name, lat, opened_on in [
        ("Harborline Northside", 34.3, "2024-06-01"),
        ("Harborline Summit", 34.6, "2024-07-01"),
    ]:
        territory = create_territory(franchisee_id, center_lat=lat, center_lng=-118.0)
        validate_success(
            api_client.create_club(
                create_club_payload(territory["id"], name=name, opened_on=opened_on),
                make_franchise_owner_headers(franchisee_id),
            ),
            expected_status=201,
        )

    rows, meta = validate_paginated(
        api_client.list_clubs(
            BRAND, params={"franchisee_id": franchisee_id, "limit": 2, "offset": 0}
        )
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


def test_the_final_page_of_the_club_listing_reports_no_more_rows():
    """Offsetting past the first page returns the single remaining club with the same total and
    the flag cleared.

    PRD 2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count` (the
    number of rows matching the filters before the page window is applied) and `has_more` (true
    when rows remain beyond the current window)."

    Design: Corner/entities/corner_club_list_returns_paginated_envelope_with_total_count_and_has_more
    """
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        open_the_club=False,
        with_plan=False,
    )
    franchisee_id = scenario["franchisee"]["id"]
    for name, lat, opened_on in [
        ("Harborline Northside", 34.3, "2024-06-01"),
        ("Harborline Summit", 34.6, "2024-07-01"),
    ]:
        territory = create_territory(franchisee_id, center_lat=lat, center_lng=-118.0)
        validate_success(
            api_client.create_club(
                create_club_payload(territory["id"], name=name, opened_on=opened_on),
                make_franchise_owner_headers(franchisee_id),
            ),
            expected_status=201,
        )

    rows, meta = validate_paginated(
        api_client.list_clubs(
            BRAND, params={"franchisee_id": franchisee_id, "limit": 2, "offset": 2}
        )
    )
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_a_re_read_agreement_still_reports_the_terms_pinned_at_signature():
    """The library figures are copied onto the contract at signing, so the re-read returns 4500
    dues, a 4900 initiation fee and a 30-day notice period.

    PRD 3.3: "`monthly_dues_base_cents` is a pinned copy of the template's `monthly_dues_cents`,
    and `initiation_fee_cents` a pinned copy of the template's `initiation_fee_cents`, so a later
    edit to the library cannot move a signed contract."

    Design: Corner/entities/corner_agreement_retrieval_returns_every_pinned_pricing_field
    """
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
    )
    member = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    agreement = sign_agreement(
        member["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=False,
    )

    reread = validate_success(api_client.get_agreement(agreement["id"], BRAND))
    assert reread["monthly_dues_base_cents"] == 4500
    assert reread["initiation_fee_cents"] == 4900
    assert reread["cancellation_notice_days"] == 30
    assert reread["state_code"] == "CA"


def test_the_term_end_date_uses_the_thirty_day_month_rather_than_the_calendar_year():
    """Twelve months of 30 days is 360 days from 2026-08-01, which lands on 2027-07-27 rather than
    the calendar anniversary.

    PRD 3.3: "`term_end_on` is the `signed_on` date plus 30 days multiplied by the template's
    `term_months`, using the 30-day month convention."

    Design: Corner/entities/corner_agreement_retrieval_returns_every_pinned_pricing_field
    """
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
    )
    member = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    agreement = sign_agreement(
        member["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=False,
    )

    reread = validate_success(api_client.get_agreement(agreement["id"], BRAND))
    assert reread["signed_on"] == "2026-08-01"
    assert reread["term_end_on"] == "2027-07-27"
    assert reread["agreement_status"] == "PENDING"
    assert reread["dues_status"] == "CURRENT"


def test_one_member_holding_two_memberships_resolves_from_either_side_of_the_join():
    """The membership record is the junction of the graph, so filtering on the member yields both
    contracts while filtering on one club yields only its own.

    PRD 2.3: "Filter parameters on list endpoints are named exactly after the field they filter
    on, and combine conjunctively."

    Design: Corner/entities/corner_graph_topology_agreement_joins_member_club_plan_promotion_and_corporate_account
    """
    setup = setup_two_franchise_clubs(
        first={
            "legal_name": "Harborline Fitness LLC",
            "contact_email": "ops@harborlinefit.example",
            "club_name": "Harborline Downtown",
        },
        second={
            "legal_name": "Ridgeway Athletics LLC",
            "contact_email": "ops@ridgewayath.example",
            "club_name": "Ridgeway Valley",
        },
    )
    first_club = setup["first"]["club"]["id"]
    second_club = setup["second"]["club"]["id"]
    member = create_member(first_club, full_name="Ana Reyes", email="ana.reyes@example.com")
    first_agreement = sign_agreement(
        member["id"], first_club, setup["plan_template"]["id"], multi_club_access=False
    )
    second_agreement = sign_agreement(
        member["id"], second_club, setup["plan_template"]["id"], multi_club_access=False
    )

    by_member, member_meta = validate_paginated(
        api_client.list_agreements(BRAND, params={"member_id": member["id"]})
    )
    assert member_meta["total_count"] == 2
    assert {row["id"] for row in by_member} == {first_agreement["id"], second_agreement["id"]}
    by_club, club_meta = validate_paginated(
        api_client.list_agreements(BRAND, params={"home_club_id": second_club})
    )
    assert club_meta["total_count"] == 1
    assert [row["id"] for row in by_club] == [second_agreement["id"]]


def test_two_pending_memberships_count_on_the_member_but_on_neither_club():
    """Both contracts raise the member's own holding count, and neither club counts a membership
    that has not yet paid.

    PRD 3.3: "What signing does *not* do is move the club's `active_agreement_count`: a `PENDING`
    agreement is not yet an active membership, and the counter only moves when the first payment
    lands, as §3.4 describes."

    Design: Corner/entities/corner_graph_topology_agreement_joins_member_club_plan_promotion_and_corporate_account
    """
    setup = setup_two_franchise_clubs(
        first={
            "legal_name": "Harborline Fitness LLC",
            "contact_email": "ops@harborlinefit.example",
            "club_name": "Harborline Downtown",
        },
        second={
            "legal_name": "Ridgeway Athletics LLC",
            "contact_email": "ops@ridgewayath.example",
            "club_name": "Ridgeway Valley",
        },
    )
    first_club = setup["first"]["club"]["id"]
    second_club = setup["second"]["club"]["id"]
    member = create_member(first_club, full_name="Ana Reyes", email="ana.reyes@example.com")
    sign_agreement(member["id"], first_club, setup["plan_template"]["id"], multi_club_access=False)
    sign_agreement(member["id"], second_club, setup["plan_template"]["id"], multi_club_access=False)

    assert validate_success(api_client.get_member(member["id"], BRAND))["agreement_count"] == 2
    assert read_club(first_club)["active_agreement_count"] == 0
    assert read_club(second_club)["active_agreement_count"] == 0
