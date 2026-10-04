"""Validation precedence: licensing authority outranks existence and state.

Two error-category pairs are pinned here — the licensing gate against an
absent resource, and the continuous-activeness window against every later row
of the cascade.
"""

from test_helpers import (
    ApiErrorId,
    approve_artwork_for_set,
    approve_card_set,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    create_product_line_payload,
    get_success_data,
    submit_card_set_for_review,
    TEST_USERS,
    validate_error,
    validate_success,
)

LM = TEST_USERS["licensing_manager_headers"]
PM = TEST_USERS["product_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _out_of_term_license(api):
    """A license that was activated inside its term and has since run out."""
    license_obj = create_active_license(api, term_ends_on="2026-12-31T00:00:00Z")
    assert license_obj["status"] == "ACTIVE"
    get_success_data(api.set_clock("2027-06-01T00:00:00Z", ADMIN))
    return license_obj


def test_a_line_under_an_out_of_term_license_is_refused(api):
    """PRD §2.7: "A license counts as in-force when three things hold together: its
    `status` is `ACTIVE` as of the logical clock, the clock has reached or
    passed its `term_starts_on`, and the clock has not passed its
    `term_ends_on`. All three are evaluated against the same clock value, and a
    request that fails any of them is refused with `ERR_LICENSE_NOT_IN_FORCE`
    (`403`)."

    Design: Difficulty/priority_pair_validation_conflict/out_of_force_license_beats_missing_resource_on_line_activation
    """
    license_obj = _out_of_term_license(api)
    line = get_success_data(
        api.create_product_line(
            create_product_line_payload(
                license_id=license_obj["id"], line_name="Late Flagship"
            ),
            PM,
        )
    )
    resp = api.ready_product_line(line["id"], PM)
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_IN_FORCE, expected_status=403)


def test_the_out_of_term_refusal_is_not_the_malformed_request_error(api):
    """PRD §3.9: "A malformed request — an unparseable body, a value of the
    wrong JSON type, or a required input field missing entirely — is refused
    with `ERR_INVALID_REQUEST` and is likewise settled before business rules
    are evaluated."

    PRD §2.7: "a request that fails any of them is refused with
    `ERR_LICENSE_NOT_IN_FORCE` (`403`)."

    Design: Difficulty/priority_pair_validation_conflict/out_of_force_license_beats_missing_resource_on_line_activation
    """
    license_obj = _out_of_term_license(api)
    line = get_success_data(
        api.create_product_line(
            create_product_line_payload(license_id=license_obj["id"]), PM
        )
    )
    resp = api.ready_product_line(line["id"], PM)
    body = resp.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_INVALID_REQUEST
    assert body["data"]["error_id"] == ApiErrorId.ERR_LICENSE_NOT_IN_FORCE
    assert resp.status_code == 403


def test_the_out_of_term_refusal_is_not_a_reference_not_found(api):
    """PRD §2.6: "Where the request body supplies identifiers rather than the
    path, a reference that does not resolve to an existing instance is rejected
    with `ERR_REFERENCE_NOT_FOUND` (`404`)."

    Design: Difficulty/priority_pair_validation_conflict/out_of_force_license_beats_missing_resource_on_line_activation
    """
    license_obj = _out_of_term_license(api)
    line = get_success_data(
        api.create_product_line(
            create_product_line_payload(license_id=license_obj["id"]), PM
        )
    )
    resp = api.ready_product_line(line["id"], PM)
    body = resp.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_REFERENCE_NOT_FOUND
    assert body["data"]["error_id"] != ApiErrorId.ERR_PRODUCT_LINE_NOT_FOUND
    assert body["response_type"] == "error"


def test_the_same_line_request_succeeds_inside_the_term(api):
    """PRD §2.7: "the clock has reached or passed its `term_starts_on`, and the
    clock has not passed its `term_ends_on`."

    Design: Difficulty/priority_pair_validation_conflict/out_of_force_license_beats_missing_resource_on_line_activation
    """
    license_obj = create_active_license(api, term_ends_on="2026-12-31T00:00:00Z")
    created = validate_success(
        api.create_product_line(
            create_product_line_payload(
                license_id=license_obj["id"], line_name="In Term Flagship"
            ),
            PM,
        ),
        expected_status=201,
    )
    assert created["status"] == "PLANNING", (
        "inside the term the identical request is accepted"
    )


def test_a_title_window_breach_outranks_an_absent_pack_configuration(api):
    """PRD §3.9: "It then requires the license behind the parent product line
    to be in force (`ERR_LICENSE_NOT_IN_FORCE`) and to have been continuously
    `ACTIVE` across the whole span from the artwork's `submitted_on` to now
    (`ERR_LICENSE_TERM_WINDOW_BREACH`)".

    Design: Difficulty/priority_pair_validation_conflict/breached_title_window_beats_absent_pack_configuration_on_set_approval
    """
    get_success_data(api.set_clock("2026-09-10T00:00:00Z", ADMIN))
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    # A live set is put through the ordinary approval chain purely to satisfy
    # the reactivation precondition "the license must already govern at least
    # one card set in APPROVED status".
    live_set = create_card_set_raw(
        api, line["id"], set_name="Flagship Live", set_tier="BASE",
        print_run_quantity=500,
    )
    approve_artwork_for_set(
        api, live_set["id"], license_obj["id"],
        submitted_on="2026-09-05T00:00:00Z", decided_on="2026-09-05T00:00:00Z",
    )
    live_set = submit_card_set_for_review(api, live_set["id"])
    get_success_data(approve_card_set(api, live_set["id"], live_set["version"]))

    # The set under test stays DRAFT: its decided artwork sits inside the
    # approval window, but the suspension interrupts the span that card-set
    # approval measures from submitted_on.
    card_set = create_card_set_raw(
        api, line["id"], set_name="Flagship Ghost", set_tier="BASE",
        print_run_quantity=500,
    )
    approve_artwork_for_set(
        api, card_set["id"], license_obj["id"],
        submitted_on="2026-09-01T00:00:00Z", decided_on="2026-09-01T00:00:00Z",
    )
    current = get_success_data(api.get_card_set(card_set["id"], PM))
    assert current["status"] == "DRAFT"

    get_success_data(api.suspend_license(license_obj["id"], LM))
    reactivated = get_success_data(api.activate_license(license_obj["id"], LM))
    assert reactivated["status"] == "ACTIVE", "the license is in force again"

    current = get_success_data(api.get_card_set(card_set["id"], PM))
    resp = api.approve_card_set(
        card_set["id"], {"expected_card_set_version": current["version"]}, PM
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_TERM_WINDOW_BREACH, expected_status=403)


def test_the_window_breach_is_neither_the_pack_config_error_nor_the_pin_error(api):
    """PRD §3.9: "the identifier a client receives must be the one belonging to
    the highest-priority failure."

    Design: Difficulty/priority_pair_validation_conflict/breached_title_window_beats_absent_pack_configuration_on_set_approval
    """
    get_success_data(api.set_clock("2026-09-10T00:00:00Z", ADMIN))
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    live_set = create_card_set_raw(
        api, line["id"], set_name="Flagship Live", set_tier="BASE",
        print_run_quantity=500,
    )
    approve_artwork_for_set(
        api, live_set["id"], license_obj["id"],
        submitted_on="2026-09-05T00:00:00Z", decided_on="2026-09-05T00:00:00Z",
    )
    live_set = submit_card_set_for_review(api, live_set["id"])
    get_success_data(approve_card_set(api, live_set["id"], live_set["version"]))

    card_set = create_card_set_raw(
        api, line["id"], set_name="Flagship Ghost", set_tier="BASE",
        print_run_quantity=500,
    )
    approve_artwork_for_set(
        api, card_set["id"], license_obj["id"],
        submitted_on="2026-09-01T00:00:00Z", decided_on="2026-09-01T00:00:00Z",
    )
    current = get_success_data(api.get_card_set(card_set["id"], PM))
    get_success_data(api.suspend_license(license_obj["id"], LM))
    get_success_data(api.activate_license(license_obj["id"], LM))

    current = get_success_data(api.get_card_set(card_set["id"], PM))
    resp = api.approve_card_set(
        card_set["id"], {"expected_card_set_version": current["version"]}, PM
    )
    error_id = resp.json()["data"]["error_id"]
    assert error_id == ApiErrorId.ERR_LICENSE_TERM_WINDOW_BREACH
    assert error_id != ApiErrorId.ERR_PACK_CONFIG_MISSING
    assert error_id != ApiErrorId.ERR_RIGHTS_VERSION_MISMATCH
    assert resp.status_code == 403


def test_the_set_is_left_in_draft_by_the_window_breach(api):
    """PRD §3.9: "Every mutating request passes through the same ordered
    validation cascade before its business effect is applied and before any
    side effect lands."

    Design: Difficulty/priority_pair_validation_conflict/breached_title_window_beats_absent_pack_configuration_on_set_approval
    """
    get_success_data(api.set_clock("2026-09-10T00:00:00Z", ADMIN))
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    live_set = create_card_set_raw(
        api, line["id"], set_name="Flagship Live", set_tier="BASE",
        print_run_quantity=500,
    )
    approve_artwork_for_set(
        api, live_set["id"], license_obj["id"],
        submitted_on="2026-09-05T00:00:00Z", decided_on="2026-09-05T00:00:00Z",
    )
    live_set = submit_card_set_for_review(api, live_set["id"])
    get_success_data(approve_card_set(api, live_set["id"], live_set["version"]))

    card_set = create_card_set_raw(
        api, line["id"], set_name="Flagship Ghost", set_tier="BASE",
        print_run_quantity=500,
    )
    approve_artwork_for_set(
        api, card_set["id"], license_obj["id"],
        submitted_on="2026-09-01T00:00:00Z", decided_on="2026-09-01T00:00:00Z",
    )
    current = get_success_data(api.get_card_set(card_set["id"], PM))
    get_success_data(api.suspend_license(license_obj["id"], LM))
    get_success_data(api.activate_license(license_obj["id"], LM))
    current = get_success_data(api.get_card_set(card_set["id"], PM))
    api.approve_card_set(
        card_set["id"], {"expected_card_set_version": current["version"]}, PM
    )

    after = validate_success(api.get_card_set(card_set["id"], PM))
    assert after["status"] == "DRAFT"
    assert after["rights_pinned_version"] == 0
    licenses = validate_success(api.get_license(license_obj["id"], LM))
    assert licenses["approved_set_count"] == 1, (
        "only the companion live set is approved; the ghost set stays DRAFT"
    )
    assert validate_success(api.get_card_set(card_set["id"], PM))["status"] == "DRAFT"


def test_a_stale_expected_version_is_reported_before_the_window_breach(api):
    """PRD §3.9: "It first requires the client's `expected_card_set_version` to
    match the card set's current `version`, and a divergence is a stale-version
    rejection carrying `ERR_STALE_VERSION` per §2.8".

    Design: Difficulty/priority_pair_validation_conflict/breached_title_window_beats_absent_pack_configuration_on_set_approval
    """
    get_success_data(api.set_clock("2026-09-10T00:00:00Z", ADMIN))
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    live_set = create_card_set_raw(
        api, line["id"], set_name="Flagship Live", set_tier="BASE",
        print_run_quantity=500,
    )
    approve_artwork_for_set(
        api, live_set["id"], license_obj["id"],
        submitted_on="2026-09-05T00:00:00Z", decided_on="2026-09-05T00:00:00Z",
    )
    live_set = submit_card_set_for_review(api, live_set["id"])
    get_success_data(approve_card_set(api, live_set["id"], live_set["version"]))

    card_set = create_card_set_raw(
        api, line["id"], set_name="Flagship Ghost", set_tier="BASE",
        print_run_quantity=500,
    )
    approve_artwork_for_set(
        api, card_set["id"], license_obj["id"],
        submitted_on="2026-09-01T00:00:00Z", decided_on="2026-09-01T00:00:00Z",
    )
    current = get_success_data(api.get_card_set(card_set["id"], PM))
    get_success_data(api.suspend_license(license_obj["id"], LM))
    get_success_data(api.activate_license(license_obj["id"], LM))

    current = get_success_data(api.get_card_set(card_set["id"], PM))
    resp = api.approve_card_set(
        card_set["id"],
        {"expected_card_set_version": current["version"] - 1},
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)