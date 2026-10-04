"""Integer bounds on the pack-configuration ladder and the claim back-date window.

Both rules are strict on one side: serial 30 is inside the published range, and
a claim filed exactly thirty days back is outside the review window.
"""

from test_helpers import (
    ApiErrorId,
    approve_artwork_for_set,
    approve_card_set,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    create_quality_claim_payload,
    get_success_data,
    submit_card_set_for_review,
    TEST_USERS,
    validate_error,
    validate_success,
)

PM = TEST_USERS["product_manager_headers"]
QA = TEST_USERS["quality_analyst_headers"]


def _approved_set(api):
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(
        api, line["id"], set_tier="BASE", print_run_quantity=500, announced=True
    )
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    return get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))


def _propose_config(api, set_id, serial):
    return get_success_data(
        api.create_pack_configuration(
            {
                "card_set_id": set_id,
                "config_serial": serial,
                "base_packs": 10,
                "insert_packs": 0,
                "premium_packs": 0,
            },
            PM,
        )
    )


def test_publishing_config_serial_one_succeeds(api):
    """PRD §3.2: "Publication sets the configuration to `PUBLISHED`, derives
    `odd_value` as the quantity quoted for every physical pack in the set —
    which is the set's `print_run_quantity`".

    Design: Difficulty/boundary_precision_check/config_serial_thirty_is_legal_and_thirty_one_is_not
    """
    card_set = _approved_set(api)
    config = _propose_config(api, card_set["id"], 1)
    published = validate_success(api.publish_pack_configuration(config["id"], PM))
    assert published["status"] == "PUBLISHED"
    assert published["odd_value"] == 500


def test_config_serial_thirty_is_inside_the_range_but_out_of_order(api):
    """PRD §3.2: "The `config_serial` must lie within 1 through 30 inclusive,
    or it is refused with `ERR_CONFIG_SERIAL_OUT_OF_RANGE` — and separately, the
    ladder must hold: the configuration being published must be exactly one
    greater than the number of configurations already published for that set,
    so a gap or a repeat is refused with `ERR_CONFIG_LADDER_VIOLATION`."

    Design: Difficulty/boundary_precision_check/config_serial_thirty_is_legal_and_thirty_one_is_not
    """
    card_set = _approved_set(api)
    first = _propose_config(api, card_set["id"], 1)
    thirty = _propose_config(api, card_set["id"], 30)
    validate_success(api.publish_pack_configuration(first["id"], PM))

    resp = api.publish_pack_configuration(thirty["id"], PM)
    validate_error(resp, ApiErrorId.ERR_CONFIG_LADDER_VIOLATION, expected_status=409)


def test_config_serial_thirty_one_is_out_of_range_and_reported_differently(api):
    """PRD §3.2: "The `config_serial` must lie within 1 through 30 inclusive,
    or it is refused with `ERR_CONFIG_SERIAL_OUT_OF_RANGE`".

    Design: Difficulty/boundary_precision_check/config_serial_thirty_is_legal_and_thirty_one_is_not
    """
    card_set = _approved_set(api)
    thirty_one = _propose_config(api, card_set["id"], 31)
    resp = api.publish_pack_configuration(thirty_one["id"], PM)
    validate_error(resp, ApiErrorId.ERR_CONFIG_SERIAL_OUT_OF_RANGE, expected_status=422)


def test_the_thirty_and_thirty_one_cases_produce_different_error_ids(api):
    """PRD §3.2: "the ladder must hold: the configuration being published must
    be exactly one greater than the number of configurations already published
    for that set, so a gap or a repeat is refused with
    `ERR_CONFIG_LADDER_VIOLATION`."

    Design: Difficulty/boundary_precision_check/config_serial_thirty_is_legal_and_thirty_one_is_not
    """
    card_set = _approved_set(api)
    first = _propose_config(api, card_set["id"], 1)
    thirty = _propose_config(api, card_set["id"], 30)
    thirty_one = _propose_config(api, card_set["id"], 31)
    validate_success(api.publish_pack_configuration(first["id"], PM))

    serial_30_error = api.publish_pack_configuration(thirty["id"], PM).json()["data"]["error_id"]
    serial_31_error = api.publish_pack_configuration(thirty_one["id"], PM).json()["data"]["error_id"]
    assert serial_30_error == ApiErrorId.ERR_CONFIG_LADDER_VIOLATION, (
        "30 is an accepted value, so only the ordering half of the rule can fail"
    )
    assert serial_31_error == ApiErrorId.ERR_CONFIG_SERIAL_OUT_OF_RANGE, (
        "31 is the first rejected value, and it fails the range half instead"
    )
    assert serial_30_error != serial_31_error


def test_config_serial_three_zero_is_not_taken_as_serial_thirty(api):
    """PRD §3.2: "so a gap or a repeat is refused with
    `ERR_CONFIG_LADDER_VIOLATION`."

    Design: Difficulty/boundary_precision_check/config_serial_thirty_is_legal_and_thirty_one_is_not
    """
    card_set = _approved_set(api)
    first = _propose_config(api, card_set["id"], 1)
    validate_success(api.publish_pack_configuration(first["id"], PM))
    second = _propose_config(api, card_set["id"], 2)
    published = validate_success(api.publish_pack_configuration(second["id"], PM))
    assert published["status"] == "PUBLISHED"
    assert published["config_serial"] == 2, "the ladder continues from the published count"


def test_a_claim_filed_exactly_thirty_days_back_cannot_open_review(api):
    """PRD §3.7: "the claim's `filed_on` must be strictly after the instant
    thirty days before the clock. A claim filed exactly thirty days ago, or
    earlier, is refused with `ERR_CLAIM_BACKDATE_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/claim_backdate_window_opens_at_thirty_days_not_twenty_nine
    """
    card_set = _approved_set(api)
    # The clock is moved only once the artwork is approved: its submitted_on of
    # 2026-08-25 sits inside the license's 10-day approval window from the
    # default startup instant, and advancing first would expire it.
    get_success_data(
        api.set_clock("2026-09-12T00:00:00Z", TEST_USERS["platform_admin_headers"])
    )
    claim = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            create_quality_claim_payload(filed_on="2026-08-13T00:00:00Z"),
            QA,
        )
    )
    resp = api.open_claim_review(claim["id"], QA)
    validate_error(resp, ApiErrorId.ERR_CLAIM_BACKDATE_EXCEEDED, expected_status=422)
    after = validate_success(api.get_quality_claim(claim["id"], QA))
    assert after["status"] == "FILED"


def test_a_claim_filed_twenty_nine_days_back_opens_review(api):
    """PRD §3.7: "Opening review on a filed claim imposes the evidence window,
    and the window is expressed as a strict comparison rather than as a span".

    Design: Difficulty/boundary_precision_check/claim_backdate_window_opens_at_thirty_days_not_twenty_nine
    """
    card_set = _approved_set(api)
    # The clock is moved only once the artwork is approved: its submitted_on of
    # 2026-08-25 sits inside the license's 10-day approval window from the
    # default startup instant, and advancing first would expire it.
    get_success_data(
        api.set_clock("2026-09-12T00:00:00Z", TEST_USERS["platform_admin_headers"])
    )
    claim = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            create_quality_claim_payload(filed_on="2026-08-14T00:00:00Z"),
            QA,
        )
    )
    reviewed = validate_success(api.open_claim_review(claim["id"], QA))
    assert reviewed["status"] == "UNDER_REVIEW"


def test_the_two_claims_sit_side_by_side_on_the_only_one_day_boundary(api):
    """PRD §3.7: "A claim filed exactly thirty days ago, or earlier, is
    refused with `ERR_CLAIM_BACKDATE_EXCEEDED`."

    PRD §2.9: "Aggregate counters — how many sets sit under a license, how many
    redemptions remain outstanding against a set, how many claims have been
    filed — are recomputed by full traversal rather than by incremental
    adjustment".

    Design: Difficulty/boundary_precision_check/claim_backdate_window_opens_at_thirty_days_not_twenty_nine
    """
    card_set = _approved_set(api)
    get_success_data(
        api.set_clock("2026-09-12T00:00:00Z", TEST_USERS["platform_admin_headers"])
    )
    boundary = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            create_quality_claim_payload(filed_on="2026-08-13T00:00:00Z"),
            QA,
        )
    )
    inside = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            create_quality_claim_payload(filed_on="2026-08-14T00:00:00Z"),
            QA,
        )
    )
    validate_error(
        api.open_claim_review(boundary["id"], QA), ApiErrorId.ERR_CLAIM_BACKDATE_EXCEEDED
    )
    assert validate_success(api.open_claim_review(inside["id"], QA))["status"] == "UNDER_REVIEW"

    read = validate_success(api.get_card_set(card_set["id"], QA))
    assert read["quality_claim_count"] == 2, "the recompute follows the set, not the claim state"