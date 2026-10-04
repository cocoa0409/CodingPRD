"""Entity creation, retrieval and listing contracts.

Each test pins one declared claim about a resource's stored surface: what is
server-minted, what is derived, and what a read or list comes back with.
"""

from test_helpers import (
    ApiErrorId,
    approve_artwork_for_set,
    approve_card_set,
    assert_card_set,
    assert_license,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    create_product_line_payload,
    create_product_line_raw,
    get_success_data,
    is_valid_uuid,
    NON_EXISTENT_UUID,
    submit_card_set_for_review,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

LM = TEST_USERS["licensing_manager_headers"]
PM = TEST_USERS["product_manager_headers"]
QA = TEST_USERS["quality_analyst_headers"]


def test_a_registered_license_comes_back_draft_with_no_rights_yet(api):
    """PRD §3.1: "Registration is immediate and the new license is not yet
    usable: it opens its life in `DRAFT`, with `rights_version` at 0, and with
    both of its aggregate counters — `set_count` and `approved_set_count` — at
    0."

    Design: Corner/entities/license_create_returns_every_declared_field_and_starts_draft
    """
    resp = api.create_license(
        {
            "grantor_name": "Major League Baseball Players Association",
            "exclusivity_scope": "EXCLUSIVE",
            "term_starts_on": "2026-01-01T00:00:00Z",
            "term_ends_on": "2029-12-31T00:00:00Z",
        },
        LM,
    )
    license_obj = validate_success(resp, expected_status=201)
    assert_license(license_obj)
    assert license_obj["status"] == "DRAFT"
    assert license_obj["rights_version"] == 0
    assert license_obj["set_count"] == 0
    assert license_obj["approved_set_count"] == 0
    assert isinstance(license_obj["version"], int)
    assert resp.json()["response_type"] == "object"
    assert resp.json()["meta"]["api_request_id"].startswith("req_")


def test_client_supplied_license_status_and_rights_version_are_not_honoured(api):
    """PRD §3.1: "it opens its life in `DRAFT`, with `rights_version` at 0".

    Design: Corner/entities/license_create_returns_every_declared_field_and_starts_draft
    """
    license_obj = validate_success(
        api.create_license(
            {
                "grantor_name": "Major League Baseball Players Association",
                "exclusivity_scope": "EXCLUSIVE",
                "term_starts_on": "2026-01-01T00:00:00Z",
                "term_ends_on": "2029-12-31T00:00:00Z",
                "status": "ACTIVE",
                "rights_version": 7,
            },
            LM,
        ),
        expected_status=201,
    )
    assert license_obj["status"] == "DRAFT", "status is system-managed, never client-supplied"
    assert license_obj["rights_version"] == 0


def test_a_read_card_set_round_trips_its_stored_configuration(api):
    """PRD §3.2: "A set is created inside a line by naming `product_line_id`,
    giving it a `set_name`, assigning its own `set_tier` — again `BASE`,
    `INSERT` or `PREMIUM`, and the tier may differ from the line's".

    Design: Corner/entities/card_set_get_returns_stored_tier_configuration_and_compound_print_run_status
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(
        api,
        line["id"],
        set_name="Flagship Base",
        set_tier="BASE",
        announced=True,
        serial_numbered=True,
        print_run_quantity=500,
    )
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))

    read = validate_success(api.get_card_set(card_set["id"], PM))
    assert read["set_name"] == "Flagship Base"
    assert read["set_tier"] == "BASE"
    assert read["print_run_quantity"] == 500
    assert read["announced"] is True
    assert read["serial_numbered"] is True
    assert read["status"] == "APPROVED"
    assert read["rights_pinned_version"] == 1


def test_a_freshly_approved_set_reports_the_compound_status_undecided(api):
    """PRD §2.12: "A card set's `print_run_status` is compound: while no
    print-run decision has been frozen for the set it reads as `UNDECIDED`".

    Design: Corner/entities/card_set_get_returns_stored_tier_configuration_and_compound_print_run_status
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))

    read = validate_success(api.get_card_set(card_set["id"], PM))
    assert read["print_run_status"] == "UNDECIDED", (
        "the compound field reflects the absence of a frozen decision, "
        "not the set's own review status"
    )
    assert_card_set(read)


def test_the_license_pages_cover_the_whole_filtered_set(api):
    """PRD §2.3: "List endpoints accept `limit` and `offset` as query
    parameters. `limit` bounds how many items are returned and defaults to 10;
    its minimum accepted value is 1 and its maximum is 100."

    PRD §2.3: "Responses to list endpoints carry the pagination fields in the
    `meta` object of the envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/licenses_list_paginates_and_reports_total_count_and_has_more
    """
    for grantor, scope, end, window in (
        ("Major League Baseball Players Association", "EXCLUSIVE", "2029-12-31T00:00:00Z", 10),
        ("Major League Baseball Players Association", "NON_EXCLUSIVE", "2027-12-31T00:00:00Z", 10),
        ("National Football League", "EXCLUSIVE", "2030-12-31T00:00:00Z", 20),
    ):
        get_success_data(
            api.create_license(
                {
                    "grantor_name": grantor,
                    "exclusivity_scope": scope,
                    "term_starts_on": "2026-01-01T00:00:00Z",
                    "term_ends_on": end,
                    "approval_window_days": window,
                },
                LM,
            )
        )

    first_page, meta = validate_paginated(
        api.list_licenses(LM, params={"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2 and meta["offset"] == 0

    second_page, meta2 = validate_paginated(
        api.list_licenses(LM, params={"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert {row["id"] for row in first_page} | {row["id"] for row in second_page} == {
        row["id"] for row in first_page + second_page
    }


def test_the_license_list_honours_its_filters_and_defaults(api):
    """PRD §3.1: "Licenses can be browsed as a collection, filtered by `status`
    or by `grantor_name`, and read individually".

    Design: Corner/entities/licenses_list_paginates_and_reports_total_count_and_has_more
    """
    for grantor in (
        "Major League Baseball Players Association",
        "Major League Baseball Players Association",
        "National Football League",
    ):
        get_success_data(
            api.create_license(
                {
                    "grantor_name": grantor,
                    "term_starts_on": "2026-01-01T00:00:00Z",
                    "term_ends_on": "2029-12-31T00:00:00Z",
                },
                LM,
            )
        )

    filtered, meta = validate_paginated(
        api.list_licenses(LM, params={"grantor_name": "National Football League"})
    )
    assert len(filtered) == 1
    assert meta["total_count"] == 1
    assert filtered[0]["approval_window_days"] == 10

    drafts, drafts_meta = validate_paginated(api.list_licenses(LM, params={"status": "DRAFT"}))
    assert len(drafts) == 3, "every license is still DRAFT"
    assert drafts_meta["total_count"] == 3

    default_page, default_meta = validate_paginated(api.list_licenses(LM))
    assert len(default_page) == 3
    assert default_meta["limit"] == 10, "the limit parameter defaults to 10"
    assert default_meta["offset"] == 0


def test_an_unallocated_quality_claim_id_reports_its_own_not_found_id(api):
    """PRD §2.6: "The platform first confirms that the id resolves; if it does not, the request is rejected with the entity-specific not-found identifier for that resource — `ERR_LICENSE_NOT_FOUND`, `ERR_PRODUCT_LINE_NOT_FOUND`, `ERR_CARD_SET_NOT_FOUND`, `ERR_PACK_CONFIGURATION_NOT_FOUND`, `ERR_SIGNING_SESSION_NOT_FOUND`, `ERR_ARTWORK_APPROVAL_NOT_FOUND`, `ERR_PRINT_RUN_DECISION_NOT_FOUND`, `ERR_REDEMPTION_NOT_FOUND`, `ERR_COLLECTOR_NOTIFICATION_NOT_FOUND`, `ERR_DISTRIBUTION_ALLOCATION_NOT_FOUND`, `ERR_QUALITY_CLAIM_NOT_FOUND`, or `ERR_COLLECTOR_COMPLAINT_NOT_FOUND` — all of which carry the same status, `404`."

    Design: Corner/entities/quality_claim_get_with_an_unknown_id_returns_quality_claim_not_found
    """
    resp = api.get_quality_claim(NON_EXISTENT_UUID, QA)
    error = validate_error(resp, ApiErrorId.ERR_QUALITY_CLAIM_NOT_FOUND, expected_status=404)
    assert error["error_id"] != ApiErrorId.ERR_REFERENCE_NOT_FOUND
    assert len(error["message"].strip()) > 0
    assert resp.json()["response_type"] == "error"


def test_a_card_set_without_a_name_is_a_malformed_request(api):
    """PRD §3.9: "A malformed request — an unparseable body, a value of the
    wrong JSON type, or a required input field missing entirely — is refused
    with `ERR_INVALID_REQUEST`".

    Design: Corner/entities/card_set_create_missing_required_set_name_returns_invalid_request
    """
    license_obj = create_active_license(api)
    line = create_product_line_raw(api, license_obj["id"])
    resp = api.create_card_set(
        {
            "product_line_id": line["id"],
            "set_tier": "BASE",
            "announced": True,
            "serial_numbered": False,
            "autograph_planned_count": 0,
            "print_run_quantity": 500,
        },
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    rows, meta = validate_paginated(
        api.list_card_sets(PM, params={"product_line_id": line["id"]})
    )
    assert rows == [] and meta["total_count"] == 0


def test_omitting_the_approval_window_stores_the_declared_default(api):
    """PRD §3.1: "a licensor service level for artwork decisions,
    `approval_window_days`, which defaults to 10 days when the caller does not
    supply it."

    Design: Corner/entities/license_create_omitting_approval_window_applies_the_declared_default
    """
    created = validate_success(
        api.create_license(
            {
                "grantor_name": "National Football League",
                "exclusivity_scope": "NON_EXCLUSIVE",
                "term_starts_on": "2026-02-01T00:00:00Z",
                "term_ends_on": "2030-12-31T00:00:00Z",
            },
            LM,
        ),
        expected_status=201,
    )
    assert created["approval_window_days"] == 10
    read = validate_success(api.get_license(created["id"], LM))
    assert read["approval_window_days"] == 10, "the default is stored, not null"

    explicit = validate_success(
        api.create_license(
            {
                "grantor_name": "National Football League",
                "exclusivity_scope": "NON_EXCLUSIVE",
                "term_starts_on": "2026-02-01T00:00:00Z",
                "term_ends_on": "2030-12-31T00:00:00Z",
                "approval_window_days": 20,
            },
            LM,
        ),
        expected_status=201,
    )
    assert explicit["approval_window_days"] == 20, "the default is a fallback, not a floor"


def test_filed_claims_are_weighted_by_severity_and_counted_on_the_set(api):
    """PRD §3.7: "computes its `claim_weight` from the severity —
    `SEVERITY_WEIGHT_MINOR` of 1 for `MINOR`, `SEVERITY_WEIGHT_MAJOR` of 2 for
    `MAJOR` and `SEVERITY_WEIGHT_CRITICAL` of 3 for `CRITICAL`, with the
    `severity` enum closed and every value weighted — and recomputes
    `quality_claim_count` on the set."

    Design: Corner/entities/card_set_aggregate_counters_are_computed_from_child_records
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)

    major = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            {
                "claim_type": "DAMAGE",
                "severity": "MAJOR",
                "affected_quantity": 25,
                "filed_on": "2026-08-20T00:00:00Z",
            },
            QA,
        )
    )
    critical = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            {
                "claim_type": "MISSING_HIT",
                "severity": "CRITICAL",
                "affected_quantity": 5,
                "filed_on": "2026-08-21T00:00:00Z",
            },
            QA,
        )
    )
    assert major["claim_weight"] == 2
    assert critical["claim_weight"] == 3
    assert major["status"] == "FILED", "a new claim opens in FILED, never in a client state"
    assert critical["status"] == "FILED"

    read = validate_success(api.get_card_set(card_set["id"], QA))
    assert read["quality_claim_count"] == 2


def test_the_license_set_count_follows_the_parent_line_chain(api):
    """PRD §3.1: "`set_count` is the number of card sets, in any status
    whatsoever, whose parent product line names this license."

    Design: Corner/entities/card_set_aggregate_counters_are_computed_from_child_records
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    create_card_set_raw(api, line["id"], set_name="Flagship Base", set_tier="BASE",
                        print_run_quantity=500)
    assert validate_success(api.get_license(license_obj["id"], LM))["set_count"] == 1

    create_card_set_raw(api, line["id"], set_name="Flagship Auto", set_tier="BASE",
                        print_run_quantity=1000)
    assert validate_success(api.get_license(license_obj["id"], LM))["set_count"] == 2


def test_a_product_line_ignores_client_supplied_system_fields(api):
    """PRD §3.2: "A new line opens in `PLANNING` and has its `sets_per_case`
    derived immediately."

    Design: Corner/entities/product_line_create_system_fields_input_ignored
    """
    license_obj = create_active_license(api)
    created = validate_success(
        api.create_product_line(
            {
                "license_id": license_obj["id"],
                "line_name": "2026 Flagship Baseball",
                "line_kind": "BASE",
                "packs_per_box": 10,
                "cards_per_pack": 10,
                "boxes_per_case": 20,
                "cases_printed": 50,
                "run_planned_on": "2026-10-01T00:00:00Z",
                "status": "APPROVED",
                "sets_per_case": 999,
            },
            PM,
        ),
        expected_status=201,
    )
    assert created["status"] == "PLANNING"
    assert created["sets_per_case"] == 2000, "the derived value wins over the supplied one"
    assert is_valid_uuid(created["id"])


def test_a_card_set_naming_an_unknown_product_line_reports_a_body_reference_miss(api):
    """PRD §2.6: "Where the request body supplies identifiers rather than the path,
    a reference that does not resolve to an existing instance is rejected with
    `ERR_REFERENCE_NOT_FOUND` (`404`). This covers `product_line_id`,
    `card_set_id`, `license_id`, `approver_id`, `redemption_id` and `player_id`
    wherever they appear as inputs."

    Design: Corner/entities/card_set_create_with_an_unknown_product_line_returns_reference_not_found
    """
    resp = api.create_card_set(
        {
            "product_line_id": NON_EXISTENT_UUID,
            "set_name": "Flagship Base",
            "set_tier": "BASE",
            "announced": True,
            "serial_numbered": False,
            "autograph_planned_count": 0,
            "print_run_quantity": 500,
        },
        PM,
    )
    error = validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND, expected_status=404)
    assert error["error_id"] != ApiErrorId.ERR_PRODUCT_LINE_NOT_FOUND

    rows, meta = validate_paginated(api.list_card_sets(PM))
    assert rows == [] and meta["total_count"] == 0


def test_a_card_set_with_an_unknown_tier_is_refused_at_the_type_boundary(api):
    """PRD §3.2: "assigning its own `set_tier` — again `BASE`, `INSERT` or
    `PREMIUM`, and the tier may differ from the line's".

    PRD §3.9: "A malformed request — an unparseable body, a value of the wrong
    JSON type, or a required input field missing entirely — is refused with
    `ERR_INVALID_REQUEST`".

    Design: Corner/entities/card_set_create_with_an_unknown_tier_is_rejected
    """
    license_obj = create_active_license(api)
    line = create_product_line_raw(api, license_obj["id"])
    resp = api.create_card_set(
        {
            "product_line_id": line["id"],
            "set_name": "Flagship Rare",
            "set_tier": "ULTRA",
            "announced": True,
            "serial_numbered": False,
            "autograph_planned_count": 0,
            "print_run_quantity": 100,
        },
        PM,
    )
    error = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
    assert error["error_id"] != ApiErrorId.ERR_PRINT_RUN_NOT_ALLOWED, (
        "the tier never resolved to a known member, so no tier rule can fire"
    )
    rows, meta = validate_paginated(
        api.list_card_sets(PM, params={"product_line_id": line["id"]})
    )
    assert rows == [] and meta["total_count"] == 0


def test_a_line_whose_product_is_not_a_multiple_of_the_set_size_is_refused(api):
    """PRD §3.2: "it is required to be an exact multiple of `CARDS_PER_SET`, the
    platform's standard set size of 100 cards".

    Design: Corner/entities/product_line_create_system_fields_input_ignored
    """
    license_obj = create_active_license(api)
    resp = api.create_product_line(
        create_product_line_payload(
            license_id=license_obj["id"], packs_per_box=7, cards_per_pack=7
        ),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_BOX_CONFIGURATION_INVALID, expected_status=422)