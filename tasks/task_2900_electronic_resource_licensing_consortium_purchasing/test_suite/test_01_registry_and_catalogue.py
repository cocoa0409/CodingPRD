"""Registry and catalogue: members, vendors, packages and their stored shapes."""

from test_helpers import (
    MISSING_UUID,
    SINGLE_CRITERION,
    assert_commitment,
    assert_member,
    assert_product,
    assert_single_resource_meta,
    assert_trial,
    assert_usage_report,
    assert_vendor,
    commitment_payload,
    create_member,
    create_product,
    create_vendor,
    create_draft_trial,
    feedback_payload,
    file_usage,
    incident_payload,
    make_librarian_headers,
    member_payload,
    minimal_vendor_payload,
    pledge,
    product_payload,
    read_subscription,
    setup_active_subscription,
    setup_catalog,
    setup_configured_access,
    setup_members,
    trial_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_member_creation_persists_the_ledger_and_standing_defaults(api, admin):
    """Registering a member library mints the ledger and standing defaults.

    PRD: "A freshly registered member has `annual_committed_cents` of 0 and
    `standing` of `IN_GOOD_STANDING`, as §2.10 describes."

    Design: Corner/entities/member_creation_persists_the_ledger_and_standing_defaults
    """
    response = api.create_member(
        member_payload(name="Alpha College", fte_count=4000,
                       carnegie_class="BACCALAUREATE", budget_ceiling_cents=9000000),
        admin,
    )
    data = validate_success(response, expected_status=201)
    body = response.json()

    assert body["response_type"] == "object", "a single resource answers response_type object"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_")

    assert_member(data)
    assert data["name"] == "Alpha College"
    assert data["fte_count"] == 4000
    assert data["carnegie_class"] == "BACCALAUREATE"
    assert data["budget_ceiling_cents"] == 9000000
    assert data["annual_committed_cents"] == 0, "a freshly registered member owes nothing"
    assert data["standing"] == "IN_GOOD_STANDING"
    assert data["version"] == 1


def test_product_retrieval_returns_the_stored_tier_bands(api, admin):
    """Reading a package back returns its negotiating ceilings and tier schedule.

    PRD: "At least one band must be supplied, the first band must have a
    `min_participants` of exactly 1 so that a lone participant is always priced,
    and `min_participants` must be strictly increasing across the array."

    Design: Corner/entities/product_retrieval_returns_the_stored_tier_bands
    """
    scenario = setup_catalog()

    response = api.get_product(scenario["product"]["id"], admin)
    data = validate_success(response)

    assert_product(data)
    assert data["base_list_price_cents"] == 10000000
    assert data["title_count"] == 400
    assert float(data["inflation_cap_pct"]) == 5.00
    assert data["cancellation_notice_days"] == 90
    assert data["perpetual_access_mode_offered"] == "FULL_ARCHIVE"
    assert data["ill_mode_offered"] == "SECURE_ELECTRONIC"
    assert data["text_mining_offered"] is True

    bands = data["tier_bands"]
    assert len(bands) == 3, f"the schedule stores three bands, got {len(bands)}"
    assert bands[1]["min_participants"] == 3
    assert float(bands[1]["discount_pct"]) == 10


def test_trial_list_paginates_with_total_count_and_has_more(api, admin):
    """The trial listing reports the pre-window total and a truthful has_more.

    PRD: "List responses populate four pagination fields inside `meta`: the
    `limit` and `offset` actually applied, the `total_count` of records matching
    the filter before the page window is applied, and the boolean `has_more`,
    which is true when the sum of `offset` and the number of records returned is
    still less than `total_count`."

    Design: Corner/entities/trial_list_paginates_with_total_count_and_has_more
    """
    vendor = create_vendor()
    member = create_member()
    for index in range(3):
        product = create_product(vendor["id"], name=f"Atlas Collection {index + 1}")
        create_draft_trial(product["id"], member["id"], "2026-08-01", "2026-08-31")

    response = api.list_trials(admin, {"member_id": member["id"], "limit": 2, "offset": 0})
    data, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert len(data) == 2, f"the page window admits two rows, got {len(data)}"
    assert meta["total_count"] == 3, "total_count counts matches before the window"
    assert meta["has_more"] is True


def test_unknown_subscription_id_returns_subscription_not_found(api, admin):
    """A syntactically valid id that names no subscription is a 404.

    PRD: "Path segments are resolved strictly left to right, and the first
    segment that names a non-existent row decides the response."

    Design: Corner/entities/unknown_subscription_id_returns_subscription_not_found
    """
    response = api.get_subscription(MISSING_UUID, admin)

    validate_error(response, "ERR_SUBSCRIPTION_NOT_FOUND", 404)
    assert response.json()["response_type"] == "error"


def test_product_creation_missing_base_list_price_is_rejected(api, admin):
    """A package registration without its list price never reaches the catalogue.

    PRD: "A licensable package is registered against its vendor by supplying
    `vendor_id` together with the package `name`, its `base_list_price_cents` (at
    least 1), its `title_count` (at least 1), and a block of negotiating
    parameters that bound what the consortium will accept and what the vendor is
    willing to give."

    Design: Corner/entities/product_creation_missing_base_list_price_is_rejected
    """
    vendor = create_vendor()
    payload = product_payload(vendor["id"])
    payload.pop("base_list_price_cents")

    validate_error(api.create_product(payload, admin), "ERR_INVALID_REQUEST", 422)

    _, meta = validate_paginated(api.list_products(admin))
    assert meta["total_count"] == 0, "the rejected registration stored nothing"


def test_vendor_creation_applies_declared_field_defaults(api, admin):
    """A publisher registered with a name alone takes both declared defaults.

    PRD: "`archival_agency_code` names the third-party preservation agency the
    vendor deposits its content with — one of `PORTICO`, `CLOCKSS` or `LOCKSS` —
    and defaults to null, meaning the vendor deposits nowhere."

    PRD: "`vpat_on_file` is a boolean that defaults to false and records whether
    a current accessibility conformance report (a VPAT) is held by the
    collections office."

    Design: Corner/entities/vendor_creation_applies_declared_field_defaults
    """
    response = api.create_vendor(minimal_vendor_payload(), admin)
    data = validate_success(response, expected_status=201)

    assert_vendor(data)
    assert data["name"] == "Meridian Press"
    assert data["archival_agency_code"] is None, "a vendor deposits nowhere by default"
    assert data["vpat_on_file"] is False
    assert data["version"] == 1


def test_commitment_projected_price_is_computed_and_extra_field_input_ignored(api):
    """The projected price is derived; a client-supplied figure is ignored.

    PRD: "The **projection** variant runs when a member pledges, and its result
    is stamped on the commitment as `projected_price_cents`."

    PRD: "the pledge is created with `status` of `PLEDGED`, `subscription_id` of
    null and `tier_price_cents` of null, because a pledge is not yet attached to
    any contract."

    Design: Corner/entities/commitment_projected_price_is_computed_and_extra_field_input_ignored
    """
    scenario = setup_catalog()
    member_id = scenario["member"]["id"]

    response = api.create_commitment(
        scenario["product"]["id"],
        commitment_payload(member_id, projected_price_cents=1),
        make_librarian_headers(member_id),
    )
    data = validate_success(response, expected_status=201)

    assert_commitment(data)
    assert data["projected_price_cents"] == 4500000, (
        "10,000,000 x 0.60 x 0.75 with no discount, under the fairness ceiling"
    )
    assert float(data["applied_discount_pct"]) == 0
    assert data["participant_count_at_pricing"] == 1
    assert data["status"] == "PLEDGED"
    assert data["tier_price_cents"] is None
    assert data["subscription_id"] is None


def test_trial_creation_mints_system_fields_and_extra_field_input_ignored(api):
    """A client-supplied id and version are ignored; the counters open clean.

    PRD: "Identifiers are never prefixed with a type tag and are never supplied
    by the client: a create request that includes an `id` has that value
    ignored."

    PRD: "The trial is created in `DRAFT` status, with `provisional_score` and
    `final_score` both null, `feedback_count` and
    `distinct_stakeholder_group_count` both 0, and `quorum_penalty_applied`
    false."

    Design: Corner/entities/trial_creation_mints_system_fields_and_extra_field_input_ignored
    """
    scenario = setup_catalog()
    member_id = scenario["member"]["id"]

    payload = trial_payload(member_id, "2026-08-01", "2026-08-31", SINGLE_CRITERION,
                            id=MISSING_UUID, version=99)
    response = api.create_trial(scenario["product"]["id"], payload,
                                make_librarian_headers(member_id))
    data = validate_success(response, expected_status=201)

    assert_trial(data)
    assert data["id"] != MISSING_UUID, "a supplied id is ignored"
    assert data["version"] == 1, "a supplied version is ignored"
    assert data["status"] == "DRAFT"
    assert data["provisional_score"] is None
    assert data["final_score"] is None
    assert data["feedback_count"] == 0
    assert data["distinct_stakeholder_group_count"] == 0
    assert data["quorum_penalty_applied"] is False


def test_usage_report_is_immutable_and_carries_no_version_field(api, admin):
    """A COUNTER month is an append-only ledger row with no mutation surface.

    PRD: "Two resource types are deliberately append-only ledger rows and carry
    only `id` and `created_at`: `FeedbackEntry` and `UsageReport`. Neither
    exposes `updated_at` and neither exposes `version` — those two keys are
    absent from their representations entirely, because a stakeholder score and a
    month of COUNTER statistics are historical facts that are never edited in
    place."

    Design: Corner/entities/usage_report_is_immutable_and_carries_no_version_field
    """
    scenario = setup_active_subscription()
    file_usage(scenario["subscription"]["id"], scenario["vendor"]["id"],
               scenario["member"]["id"], "2027-01", 1200)

    data, meta = validate_paginated(
        api.list_usage_reports(admin, {"subscription_id": scenario["subscription"]["id"]})
    )
    assert meta["total_count"] == 1
    row = data[0]
    assert_usage_report(row)
    assert row["full_text_requests"] == 1200
    assert row["period_month"] == "2027-01"
    assert "version" not in row, "a usage row exposes no version"
    assert "updated_at" not in row, "a usage row exposes no updated_at"

    for method in ("PATCH", "PUT", "DELETE"):
        probe = api.raw(method, f"/erm/usage-reports/{row['id']}", {}, admin)
        assert probe.status_code in (404, 405), (
            f"{method} on a usage row must not be a published surface, "
            f"got HTTP {probe.status_code}"
        )


def test_feedback_on_an_unknown_trial_returns_trial_not_found(api):
    """Feedback aimed at a trial that does not exist is a trial 404.

    PRD: "Path segments are resolved strictly left to right, and the first
    segment that names a non-existent row decides the response."

    Design: Corner/entities/feedback_on_an_unknown_trial_returns_trial_not_found
    """
    member = create_member()

    response = api.submit_feedback(MISSING_UUID,
                                   feedback_payload("FACULTY", "CONTENT_FIT", 90),
                                   make_librarian_headers(member["id"]))

    validate_error(response, "ERR_TRIAL_NOT_FOUND", 404)


def test_access_incident_with_an_invalid_symptom_enum_is_rejected(api, admin):
    """A symptom code outside the declared set never becomes an incident row.

    PRD: "A `MemberLibrarian` files an access incident against a subscription
    with its own `member_id`, a `symptom_code` of `OFF_CAMPUS_DENIED`,
    `WALK_IN_BLOCKED`, `PROXY_LOOP` or `SAML_ATTRIBUTE_MISSING`, and the boolean
    `off_campus`, true when the failure was observed from outside the registered
    IP ranges."

    Design: Corner/entities/access_incident_with_an_invalid_symptom_enum_is_rejected
    """
    scenario = setup_configured_access()
    subscription_id = scenario["subscription"]["id"]
    member_id = scenario["member"]["id"]

    response = api.create_access_incident(
        subscription_id,
        incident_payload(member_id, symptom_code="VPN_TIMEOUT"),
        make_librarian_headers(member_id),
    )
    validate_error(response, "ERR_INVALID_REQUEST", 422)

    assert read_subscription(subscription_id)["access_health_score"] == 100, (
        "a rejected report decays nothing"
    )
    _, meta = validate_paginated(
        api.list_access_incidents(admin, {"subscription_id": subscription_id})
    )
    assert meta["total_count"] == 0


def test_commitment_junction_resolves_one_member_product_pair(api, admin):
    """Filtering the commitment junction on both keys returns exactly one row.

    PRD: "Commitments are readable individually, showing both the projected and
    the settled price side by side, and can be paged with optional `product_id`,
    `member_id`, `subscription_id` and `status` filters."

    Design: Corner/entities/commitment_junction_resolves_one_member_product_pair
    """
    vendor = create_vendor()
    product = create_product(vendor["id"])
    alpha, bravo = setup_members([{"name": "Alpha College"}, {"name": "Bravo University"}])
    commitment_alpha = pledge(product["id"], alpha["id"])
    pledge(product["id"], bravo["id"])

    data, meta = validate_paginated(
        api.list_commitments(admin, {"product_id": product["id"], "member_id": alpha["id"]})
    )

    assert meta["total_count"] == 1, "the pair resolves to a single junction row"
    assert data[0]["id"] == commitment_alpha["id"]
    assert data[0]["member_id"] == alpha["id"]
    assert data[0]["status"] == "PLEDGED"


def test_vendor_create_then_read_and_list_round_trip(api, admin):
    """A registered publisher reads back verbatim and exposes no mutation surface.

    PRD: "Reading back is broadly permitted: all five roles may read an
    individual member, vendor or product, and may page through the product
    catalogue."

    PRD: "The catalogue listing accepts an optional `vendor_id` filter alongside
    `limit` and `offset`."

    Design: Corner/endpoints/vendor_create_then_read_and_list_round_trip
    """
    vendor = create_vendor()

    response = api.get_vendor(vendor["id"], admin)
    data = validate_success(response)
    assert_single_resource_meta(response.json()["meta"])

    assert_vendor(data)
    assert data["id"] == vendor["id"]
    assert data["name"] == "Atlas Scholarly"
    assert data["archival_agency_code"] == "PORTICO"
    assert data["vpat_on_file"] is True
    assert data["version"] == 1

    _, meta = validate_paginated(api.list_products(admin, {"vendor_id": vendor["id"]}))
    assert meta["total_count"] == 0, "the publisher has no packages yet"

    for method in ("PATCH", "PUT", "DELETE"):
        probe = api.raw(method, f"/erm/vendors/{vendor['id']}", {}, admin)
        assert probe.status_code in (404, 405), (
            f"{method} on a vendor must not be a published surface, "
            f"got HTTP {probe.status_code}"
        )
