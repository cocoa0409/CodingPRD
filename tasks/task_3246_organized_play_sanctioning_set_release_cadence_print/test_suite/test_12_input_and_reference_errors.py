"""Request shape, reference resolution, duplicate keys, empty collections and
filter-plus-paginate consistency."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_application,
    get_allocation,
    get_application,
    get_code,
    get_judge,
    make_store_organizer_headers,
    mint_code,
    pass_distribution,
    propose_distribution,
    register_judge,
    set_clock,
    setup_application,
    setup_release_context,
    validate_error,
    validate_paginated,
    validate_success,
    void_distribution,
)


def test_an_undeclared_field_on_the_application_edit_is_refused(api):
    """PRD §2.12: "Only then is the request's own shape examined — every required
    body field present, no undeclared body field supplied, every value conforming
    to its declared type and enumerated domain — with any violation rejected as
    `ERR_INVALID_REQUEST`."
    PRD §3.2: "a store may correct its own submission: the `expected_headcount`
    and `scheduled_date` remain editable on a submitted application, and an edit
    advances the application's `version` by one."

    Design: Corner/endpoints/application_patch_bumps_version_and_refuses_unknown_field
    """
    store, set_release, fmt = setup_release_context()
    application = create_application(store, set_release, fmt, tier="LOCAL")
    before = get_application(application["id"])

    patched = validate_success(api_client.patch_event_application(
        application["id"],
        {"expected_headcount": 18, "scheduled_date": "2026-09-26T19:00:00Z"},
        make_store_organizer_headers(store["id"]),
    ), 200)
    assert patched["expected_headcount"] == 18
    assert patched["scheduled_date"] == "2026-09-26T19:00:00Z"
    assert patched["version"] == before["version"] + 1

    refused = api_client.patch_event_application(
        application["id"], {"tier": "CHAMPIONSHIP"},
        make_store_organizer_headers(store["id"]),
    )
    validate_error(refused, "ERR_INVALID_REQUEST", expected_status=400)
    assert get_application(application["id"])["tier"] == "LOCAL"


def test_a_redemption_code_that_matches_no_card_is_refused(api):
    """PRD §2.11: "A redemption code is a special case of reference resolution:
    because a printed code is presented by value rather than by identifier, the
    code supplied when redeeming against an event must match exactly one existing
    code redemption row, and a code that matches none or matches more than one is
    rejected with `ERR_INVALID_REDEMPTION_CODE`."

    Design: Corner/errors/unknown_redemption_code_is_rejected_before_redeeming
    """
    store, _set_release, _fmt, application, _allocation = setup_application(
        tier="LOCAL", approve=False
    )
    known = mint_code(application["id"], redemption_code="KNOWN-1", code_kind="DIGITAL")

    refused = api_client.redeem_code(
        application["id"],
        {"redemption_code": "NOT-A-REAL-CODE", "code_kind": "DIGITAL",
         "action": "REDEEM"},
        make_store_organizer_headers(store["id"]),
    )
    validate_error(refused, "ERR_INVALID_REDEMPTION_CODE", expected_status=404)

    unchanged = get_code(known["id"])
    assert unchanged["status"] == "AVAILABLE"
    assert unchanged["redemption_seq"] is None


def test_an_unknown_code_leaves_the_application_codes_untouched(api):
    """PRD §2.11: "the code supplied when redeeming against an event must match
    exactly one existing code redemption row, and a code that matches none or
    matches more than one is rejected with `ERR_INVALID_REDEMPTION_CODE`."

    Design: Corner/errors/unknown_redemption_code_is_rejected_before_redeeming
    """
    store, _set_release, _fmt, application, _allocation = setup_application(
        tier="LOCAL", approve=False
    )
    mint_code(application["id"], redemption_code="KNOWN-2", code_kind="DIGITAL")

    api_client.redeem_code(
        application["id"],
        {"redemption_code": "NOT-A-REAL-CODE", "code_kind": "DIGITAL",
         "action": "REDEEM"},
        make_store_organizer_headers(store["id"]),
    )

    _data, meta = validate_paginated(api_client.list_code_redemptions(
        TEST_USERS["ops_admin_headers"],
        params={"event_application_id": application["id"], "limit": 10},
    ))
    assert meta["total_count"] == 1


def test_a_street_date_before_the_prerelease_end_is_refused(api):
    """PRD §3.7: "A release whose `street_date` falls before its
    `prerelease_end_date` is rejected with `ERR_STREET_DATE_BEFORE_PRERELEASE`
    and a release whose `set_code` collides with an existing release is rejected
    with `ERR_DUPLICATE_SET_CODE`."
    PRD §2.5: "The prerelease window sits strictly before the street date: a
    release whose `street_date` falls before its `prerelease_end_date` is rejected
    outright"

    Design: Corner/errors/street_date_before_prerelease_end_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")

    refused = api_client.create_set_release(
        {
            "set_code": "BAD1",
            "prerelease_start_date": "2026-09-11T00:00:00Z",
            "prerelease_end_date": "2026-09-13T23:59:59Z",
            "street_date": "2026-09-12T00:00:00Z",
        },
        TEST_USERS["ops_admin_headers"],
    )
    validate_error(refused, "ERR_STREET_DATE_BEFORE_PRERELEASE", expected_status=422)

    data, _meta = validate_paginated(api_client.list_set_releases(
        TEST_USERS["ops_admin_headers"], params={"limit": 100}
    ))
    assert all(row["set_code"] != "BAD1" for row in data)


def test_a_street_date_exactly_at_the_prerelease_end_is_accepted(api):
    """PRD §3.7: "A release whose `street_date` falls before its
    `prerelease_end_date` is rejected with `ERR_STREET_DATE_BEFORE_PRERELEASE`"

    Design: Corner/errors/street_date_before_prerelease_end_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")

    accepted = validate_success(api_client.create_set_release(
        {
            "set_code": "EDGE1",
            "prerelease_start_date": "2026-09-11T00:00:00Z",
            "prerelease_end_date": "2026-09-13T23:59:59Z",
            "street_date": "2026-09-13T23:59:59Z",
        },
        TEST_USERS["ops_admin_headers"],
    ), 201)
    assert accepted["status"] == "ANNOUNCED"


def test_a_second_announcement_of_the_same_set_code_is_refused(api):
    """PRD §3.7: "a release whose `set_code` collides with an existing release is
    rejected with `ERR_DUPLICATE_SET_CODE`."

    Design: Corner/errors/duplicate_set_code_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    validate_success(api_client.create_set_release(
        {
            "set_code": "DUP1",
            "prerelease_start_date": "2026-09-11T00:00:00Z",
            "prerelease_end_date": "2026-09-13T23:59:59Z",
            "street_date": "2026-09-18T00:00:00Z",
        },
        TEST_USERS["ops_admin_headers"],
    ), 201)

    refused = api_client.create_set_release(
        {
            "set_code": "DUP1",
            "prerelease_start_date": "2026-10-02T00:00:00Z",
            "prerelease_end_date": "2026-10-04T23:59:59Z",
            "street_date": "2026-10-09T00:00:00Z",
        },
        TEST_USERS["ops_admin_headers"],
    )
    validate_error(refused, "ERR_DUPLICATE_SET_CODE", expected_status=409)

    data, meta = validate_paginated(api_client.list_set_releases(
        TEST_USERS["ops_admin_headers"], params={"limit": 100}
    ))
    assert meta["total_count"] == 1
    assert data[0]["street_date"] == "2026-09-18T00:00:00Z"


def test_a_second_registration_of_the_same_judge_reference_is_refused(api):
    """PRD §3.10: "A registration whose `judge_ref` collides with an existing
    certification is rejected with `ERR_DUPLICATE_JUDGE_REF`."

    Design: Corner/errors/duplicate_judge_ref_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    register_judge(judge_ref="JUDGE-DUP", name="D. Referee", level="LEVEL_1")

    refused = api_client.create_judge(
        {"judge_ref": "JUDGE-DUP", "name": "Different Name", "level": "LEVEL_3"},
        TEST_USERS["ops_admin_headers"],
    )
    validate_error(refused, "ERR_DUPLICATE_JUDGE_REF", expected_status=409)

    unchanged = get_judge("JUDGE-DUP")
    assert unchanged["name"] == "D. Referee"
    assert unchanged["level"] == "LEVEL_1"
    _data, meta = validate_paginated(api_client.list_judges(
        TEST_USERS["ops_admin_headers"], params={"limit": 100}
    ))
    assert meta["total_count"] == 1


def test_minting_a_duplicate_code_value_is_refused(api):
    """PRD §3.11: "The code itself must be globally unique across all minted
    cards, and a duplicate is rejected with `ERR_DUPLICATE_REDEMPTION_CODE`."

    Design: Corner/errors/duplicate_redemption_code_is_rejected
    """
    store, _set_release, _fmt, application, _allocation = setup_application(
        tier="LOCAL", approve=False
    )
    first = mint_code(application["id"], redemption_code="CODEDUP-1", code_kind="DIGITAL")

    refused = api_client.create_code_redemption(
        {
            "redemption_code": "CODEDUP-1",
            "code_kind": "PHYSICAL",
            "event_application_id": application["id"],
        },
        TEST_USERS["ops_admin_headers"],
    )
    validate_error(refused, "ERR_DUPLICATE_REDEMPTION_CODE", expected_status=409)

    assert get_code(first["id"])["code_kind"] == "DIGITAL"
    _data, meta = validate_paginated(api_client.list_code_redemptions(
        TEST_USERS["ops_admin_headers"],
        params={"event_application_id": application["id"], "limit": 10},
    ))
    assert meta["total_count"] == 1


def test_filtering_out_a_mutated_row_leaves_the_underlying_table_intact(api):
    """PRD §3.5: "Points come back by voiding a passed distribution, by filing a
    report that declares unclaimed prizes, and by disbursing a physical prize
    grant."
    PRD §3.5: "Voiding a distribution that has reached `PASSED` moves it to
    `VOIDED` and adds its quantity to the pool's `total_restored_tp`"
    PRD §2.3: "rows come back ordered by their creation timestamp in ascending
    order, oldest first."

    Design: Corner/cross_cutting_layers/qr_pagination_consistency_under_rotation_mutation
    """
    store, _set_release, _fmt, application, allocation = setup_application(
        tier="QUALIFIER"
    )
    distributions = [
        propose_distribution(allocation["id"], store["id"], quantity=5,
                             recipient_ref=f"PLAYER-P{index}")
        for index in range(1, 4)
    ]

    pass_distribution(distributions[0]["id"])
    void_distribution(distributions[0]["id"])

    proposed, meta = validate_paginated(api_client.list_prize_distributions(
        TEST_USERS["judge_headers"],
        params={"prize_allocation_id": allocation["id"], "status": "PROPOSED",
                "limit": 10, "offset": 0},
    ))
    assert meta["total_count"] == 2, "the voided row is excluded by the status filter"
    assert all(row["status"] == "PROPOSED" for row in proposed)
    assert all(row["prize_allocation_id"] == allocation["id"] for row in proposed)

    unfiltered, all_meta = validate_paginated(api_client.list_prize_distributions(
        TEST_USERS["judge_headers"],
        params={"prize_allocation_id": allocation["id"], "limit": 10, "offset": 0},
    ))
    assert all_meta["total_count"] == 3, "a VOID is a status change, not a row removal"


def test_the_voided_distribution_still_restores_its_quantity_to_the_pool(api):
    """PRD §3.5: "Voiding a distribution that has reached `PASSED` moves it to
    `VOIDED` and adds its quantity to the pool's `total_restored_tp`"
    PRD §2.3: "rows come back ordered by their creation timestamp in ascending
    order, oldest first."

    Design: Corner/cross_cutting_layers/qr_pagination_consistency_under_rotation_mutation
    """
    store, _set_release, _fmt, application, allocation = setup_application(
        tier="QUALIFIER"
    )
    distributions = [
        propose_distribution(allocation["id"], store["id"], quantity=5,
                             recipient_ref=f"PLAYER-Q{index}")
        for index in range(1, 4)
    ]
    pass_distribution(distributions[0]["id"])
    void_distribution(distributions[0]["id"])

    updated = get_allocation(allocation["id"])
    assert updated["total_restored_tp"] == 5
    assert updated["remaining_tp"] == 48


def test_an_application_with_no_report_yields_an_empty_report_collection(api):
    """PRD §2.3: "`total_count` reports the size of the full filtered result set,
    not the size of the page, and `has_more` reports whether any rows remain
    beyond the current page."

    Design: Difficulty/boundary_precision_check/empty_report_collection_is_an_empty_set_not_an_error
    """
    store, _set_release, _fmt, application, allocation = setup_application(
        tier="LOCAL"
    )

    summary = validate_success(
        api_client.get_prizing_summary(application["id"], TEST_USERS["judge_headers"]),
        200,
    )
    assert summary["prize_pool_remaining_tp"] == 16

    data, meta = validate_paginated(api_client.list_prize_reports(
        TEST_USERS["judge_headers"],
        params={"event_application_id": application["id"], "limit": 10},
    ))
    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_an_emptied_report_collection_is_a_success_envelope(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §3.6: "it adds the report's `unclaimed_tp` to the parent pool's
    `total_restored_tp`, which lifts the conserved invariant by exactly that
    amount"

    Design: Difficulty/boundary_precision_check/empty_report_collection_is_an_empty_set_not_an_error
    """
    store, _set_release, _fmt, application, allocation = setup_application(
        tier="LOCAL"
    )

    response = api_client.list_prize_reports(
        TEST_USERS["judge_headers"],
        params={"event_application_id": application["id"], "limit": 10},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["response_type"] == "array"
    assert body["data"] == []
    assert body["meta"]["total_count"] == 0
    assert get_allocation(allocation["id"])["total_restored_tp"] == 0, (
        "no report has ever been filed against this allocation"
    )