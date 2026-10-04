"""Error catalogue coverage and the optimistic-concurrency corner.

The entity-specific not-found identifiers are distinguishable from the generic
body-reference identifier, and one approval path is gated on a version the
client read earlier.
"""

from test_helpers import (
    ApiErrorId,
    approve_artwork_for_set,
    approve_card_set,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    create_print_run_decision_payload,
    create_product_line_raw,
    get_success_data,
    NON_EXISTENT_UUID,
    submit_card_set_for_review,
    TEST_USERS,
    validate_error,
    validate_success,
)

LM = TEST_USERS["licensing_manager_headers"]
PM = TEST_USERS["product_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
ANALYST = TEST_USERS["redemption_analyst_headers"]
CS = TEST_USERS["collector_support_headers"]

PRINT_RUN_MISS = "11111111-1111-4111-8111-111111111111"
COMPLAINT_MISS = "22222222-2222-4222-8222-222222222222"


def test_each_collection_reports_its_own_not_found_identifier(api):
    """PRD §2.6: "The platform first confirms that the id resolves; if it does not, the request is rejected with the entity-specific not-found identifier for that resource — `ERR_LICENSE_NOT_FOUND`, `ERR_PRODUCT_LINE_NOT_FOUND`, `ERR_CARD_SET_NOT_FOUND`, `ERR_PACK_CONFIGURATION_NOT_FOUND`, `ERR_SIGNING_SESSION_NOT_FOUND`, `ERR_ARTWORK_APPROVAL_NOT_FOUND`, `ERR_PRINT_RUN_DECISION_NOT_FOUND`, `ERR_REDEMPTION_NOT_FOUND`, `ERR_COLLECTOR_NOTIFICATION_NOT_FOUND`, `ERR_DISTRIBUTION_ALLOCATION_NOT_FOUND`, `ERR_QUALITY_CLAIM_NOT_FOUND`, or `ERR_COLLECTOR_COMPLAINT_NOT_FOUND` — all of which carry the same status, `404`."

    Design: Corner/errors/every_entity_not_found_error_is_reachable_from_its_collection
    """
    resp = api.get_print_run_decision(PRINT_RUN_MISS, PLANNER)
    validate_error(resp, ApiErrorId.ERR_PRINT_RUN_DECISION_NOT_FOUND, expected_status=404)
    other = api.get_complaint(COMPLAINT_MISS, CS)
    validate_error(other, ApiErrorId.ERR_COLLECTOR_COMPLAINT_NOT_FOUND, expected_status=404)


def test_a_path_segment_miss_is_never_reported_as_a_body_reference_miss(api):
    """PRD §2.6: "resolution is left to right across the path, so the first
    identifier that fails to resolve determines the error, and the platform
    does not attempt to read anything to the right of it."

    Design: Corner/errors/every_entity_not_found_error_is_reachable_from_its_collection
    """
    license_obj = create_active_license(api)
    resp = api.get_license(COMPLAINT_MISS, LM)
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_FOUND, expected_status=404)
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_REFERENCE_NOT_FOUND, (
        "the reference identifier is reserved for ids supplied in request bodies"
    )


def test_a_resolvable_id_still_reads_while_others_fail(api):
    """PRD §2.6: "The platform first confirms that the id resolves".

    Design: Corner/errors/every_entity_not_found_error_is_reachable_from_its_collection
    """
    license_obj = create_active_license(api)
    read = validate_success(api.get_license(license_obj["id"], LM))
    assert read["id"] == license_obj["id"]
    assert read["status"] == "ACTIVE"


def test_a_control_id_on_another_collection_fails_with_its_own_code(api):
    """PRD §2.6: "This applies in two shapes. An entity-addressed operation —
    one whose path ends in the resource's own id, such as an approval or a
    state transition — returns that entity's not-found identifier. A collection
    endpoint whose path contains a parent id as a path segment, such as the
    list of card sets inside a product line or the list of allocations reserved
    against a line, returns the not-found identifier of the *path-segment*
    entity."

    Design: Corner/errors/every_entity_not_found_error_is_reachable_from_its_collection
    """
    for fetch, expected in (
        (lambda: api.get_redemption(PRINT_RUN_MISS, ANALYST), ApiErrorId.ERR_REDEMPTION_NOT_FOUND),
        (
            lambda: api.get_notification(PRINT_RUN_MISS, ANALYST),
            ApiErrorId.ERR_COLLECTOR_NOTIFICATION_NOT_FOUND,
        ),
        (
            lambda: api.get_quality_claim(PRINT_RUN_MISS, TEST_USERS["quality_analyst_headers"]),
            ApiErrorId.ERR_QUALITY_CLAIM_NOT_FOUND,
        ),
    ):
        validate_error(fetch(), expected, expected_status=404)


def test_a_redemption_code_cannot_be_reused_on_another_set(api):
    """PRD §3.5: "A redemption code already in use by another redemption is
    refused with `ERR_REDEMPTION_CODE_DUPLICATE`."

    Design: Corner/errors/redemption_code_of_a_universe_series_is_rejected_on_reuse
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    first_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, first_set["id"], license_obj["id"])
    first_set = submit_card_set_for_review(api, first_set["id"])
    first_set = get_success_data(
        approve_card_set(api, first_set["id"], first_set["version"])
    )
    second_set = create_card_set_raw(
        api, line["id"], set_name="Flagship Auto", set_tier="BASE", print_run_quantity=1000
    )
    approve_artwork_for_set(api, second_set["id"], license_obj["id"])
    second_set = submit_card_set_for_review(api, second_set["id"])
    second_set = get_success_data(
        approve_card_set(api, second_set["id"], second_set["version"])
    )

    get_success_data(
        api.issue_redemption(
            first_set["id"],
            {
                "redemption_code": "RDM-4001",
                "signer_name": "Ken Griffey Jr",
                "estimated_value_cents": 300000,
                "opened_on": "2026-09-01T00:00:00Z",
            },
            ANALYST,
        )
    )
    resp = api.issue_redemption(
        second_set["id"],
        {
            "redemption_code": "RDM-4001",
            "signer_name": "Ken Griffey Jr",
            "estimated_value_cents": 300000,
            "opened_on": "2026-09-01T00:00:00Z",
        },
        ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_REDEMPTION_CODE_DUPLICATE, expected_status=409)


def test_the_duplicate_redemption_never_reaches_the_second_set(api):
    """PRD §3.5: "New redemptions open in `ISSUED`, and issuing one recomputes
    `autograph_redemptions_outstanding` on the set."

    Design: Corner/errors/redemption_code_of_a_universe_series_is_rejected_on_reuse
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    first_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, first_set["id"], license_obj["id"])
    first_set = submit_card_set_for_review(api, first_set["id"])
    first_set = get_success_data(approve_card_set(api, first_set["id"], first_set["version"]))
    second_set = create_card_set_raw(
        api, line["id"], set_name="Flagship Auto", set_tier="BASE", print_run_quantity=1000
    )
    approve_artwork_for_set(api, second_set["id"], license_obj["id"])
    second_set = submit_card_set_for_review(api, second_set["id"])
    second_set = get_success_data(approve_card_set(api, second_set["id"], second_set["version"]))

    for set_id, code in ((first_set["id"], "RDM-4001"), (second_set["id"], "RDM-4001")):
        api.issue_redemption(
            set_id,
            {
                "redemption_code": code,
                "signer_name": "Ken Griffey Jr",
                "estimated_value_cents": 300000,
                "opened_on": "2026-09-01T00:00:00Z",
            },
            ANALYST,
        )
    read = validate_success(api.get_card_set(second_set["id"], PM))
    assert read["autograph_redemptions_outstanding"] == 0


def test_a_fresh_code_on_the_second_set_is_accepted(api):
    """PRD §3.5: "supplying a `redemption_code` that is globally unique".

    Design: Corner/errors/redemption_code_of_a_universe_series_is_rejected_on_reuse
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    first_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, first_set["id"], license_obj["id"])
    first_set = submit_card_set_for_review(api, first_set["id"])
    first_set = get_success_data(approve_card_set(api, first_set["id"], first_set["version"]))
    second_set = create_card_set_raw(
        api, line["id"], set_name="Flagship Auto", set_tier="BASE", print_run_quantity=1000
    )
    approve_artwork_for_set(api, second_set["id"], license_obj["id"])
    second_set = submit_card_set_for_review(api, second_set["id"])
    second_set = get_success_data(approve_card_set(api, second_set["id"], second_set["version"]))

    get_success_data(
        api.issue_redemption(
            first_set["id"],
            {
                "redemption_code": "RDM-4001",
                "signer_name": "Ken Griffey Jr",
                "estimated_value_cents": 300000,
                "opened_on": "2026-09-01T00:00:00Z",
            },
            ANALYST,
        )
    )
    fresh = validate_success(
        api.issue_redemption(
            second_set["id"],
            {
                "redemption_code": "RDM-4002",
                "signer_name": "Ken Griffey Jr",
                "estimated_value_cents": 300000,
                "opened_on": "2026-09-01T00:00:00Z",
            },
            ANALYST,
        ),
        expected_status=201,
    )
    assert fresh["status"] == "ISSUED"


def test_an_unallocated_redemption_id_reports_its_own_identifier(api):
    """PRD §2.6: "An entity-addressed operation — one whose path ends in the
    resource's own id, such as an approval or a state transition — returns that
    entity's not-found identifier."

    Design: Corner/errors/unknown_redemption_id_returns_redemption_not_found
    """
    resp = api.get_redemption(NON_EXISTENT_UUID, ANALYST)
    error = validate_error(resp, ApiErrorId.ERR_REDEMPTION_NOT_FOUND, expected_status=404)
    assert error["error_id"] != ApiErrorId.ERR_REFERENCE_NOT_FOUND, (
        "a path-segment miss is not reported as a body-reference miss"
    )
    assert len(error["message"].strip()) > 0
    assert resp.json()["response_type"] == "error"


def test_an_unrecognised_role_is_rejected_before_any_lookup(api):
    """PRD §2.1: "A request that omits either header, or that supplies a
    `X-User-Role` value the platform does not recognise, is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/unauthenticated_request_is_rejected_before_any_resource_lookup
    """
    headers = {"X-User-ID": "ghost", "X-User-Role": "GhostRole"}
    resp = api.get_license(NON_EXISTENT_UUID, headers)
    error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
    assert error["error_id"] != ApiErrorId.ERR_LICENSE_NOT_FOUND, (
        "authentication precedes resource existence"
    )
    assert error["error_id"] != ApiErrorId.ERR_FORBIDDEN


def test_a_missing_role_header_is_also_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers. `X-User-ID` identifies
    the acting principal and `X-User-Role` declares the operational capacity the
    principal is acting in."

    Design: Corner/errors/unauthenticated_request_is_rejected_before_any_resource_lookup
    """
    resp = api.get_license(NON_EXISTENT_UUID, {"X-User-ID": "ghost"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_a_print_run_decision_built_against_a_stale_line_is_refused(api):
    """PRD §2.8: "A proposed decision records the product line version it was
    built against in `proposed_against_line_version`, and at approval the client
    must supply `expected_product_line_version`. If that expectation does not
    match the product line's current `version`, the approval is refused with
    `ERR_AUTHORITY_OUTDATED` (`412`)."

    Design: Corner/errors/a_print_run_decision_built_against_a_stale_line_version_is_refused
    """
    license_obj = create_active_license(api)
    line = create_product_line_raw(api, license_obj["id"])
    line_v1 = line["version"]
    card_set = create_card_set_raw(
        api, line["id"], set_tier="BASE", print_run_quantity=500, announced=True
    )
    # PRD 3.2: the line is only editable while it is still PLANNING, so the
    # revision that makes `line_v1` stale has to happen before readiness.
    patched = validate_success(api.patch_product_line(line["id"], {"cases_printed": 45}, PM))
    assert patched["version"] > line_v1
    line = get_success_data(api.ready_product_line(line["id"], PM))
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    submitted = get_success_data(api.submit_card_set(card_set["id"], PM))
    approved = get_success_data(approve_card_set(api, card_set["id"], submitted["version"]))

    decision = get_success_data(
        api.create_print_run_decision(
            create_print_run_decision_payload(
                card_set_id=approved["id"],
                authority="BRAND_DIRECTIVE",
                proposed_against_line_version=line_v1,
                declared_quantity=12000,
                announced=True,
            ),
            PLANNER,
        )
    )

    resp = api.approve_print_run_decision(
        decision["id"],
        {
            "expected_card_set_version": approved["version"],
            "expected_product_line_version": line_v1,
        },
        PLANNER,
    )
    error_id = validate_error(
        resp, ApiErrorId.ERR_AUTHORITY_OUTDATED, expected_status=412
    )["error_id"]
    assert error_id != ApiErrorId.ERR_STALE_VERSION, (
        "the card set version the caller holds is still the current one"
    )


def test_the_outdated_authority_leaves_the_run_unfrozen(api):
    """PRD §2.8: "It is a state precondition evaluated against a field the
    writer reads, not a concurrency race".

    Design: Corner/errors/a_print_run_decision_built_against_a_stale_line_version_is_refused
    """
    license_obj = create_active_license(api)
    line = create_product_line_raw(api, license_obj["id"])
    line_v1 = line["version"]
    card_set = create_card_set_raw(
        api, line["id"], set_tier="BASE", print_run_quantity=500, announced=True
    )
    # PRD 3.2: the line is only editable while it is still PLANNING, so the
    # revision that makes `line_v1` stale has to happen before readiness.
    patched = validate_success(api.patch_product_line(line["id"], {"cases_printed": 45}, PM))
    assert patched["version"] > line_v1
    line = get_success_data(api.ready_product_line(line["id"], PM))
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    submitted = get_success_data(api.submit_card_set(card_set["id"], PM))
    approved = get_success_data(approve_card_set(api, card_set["id"], submitted["version"]))
    decision = get_success_data(
        api.create_print_run_decision(
            create_print_run_decision_payload(
                card_set_id=approved["id"],
                authority="BRAND_DIRECTIVE",
                proposed_against_line_version=line_v1,
                declared_quantity=12000,
                announced=True,
            ),
            PLANNER,
        )
    )
    api.approve_print_run_decision(
        decision["id"],
        {
            "expected_card_set_version": approved["version"],
            "expected_product_line_version": line_v1,
        },
        PLANNER,
    )

    read = validate_success(api.get_card_set(approved["id"], PM))
    assert read["print_run_status"] == "UNDECIDED"
    assert read["print_run_quantity"] == 500
    stored = validate_success(api.get_print_run_decision(decision["id"], PLANNER))
    assert stored["status"] == "PROPOSED"