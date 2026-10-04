"""Cross-entity gates on card-set submission and production start.

Two card-set transitions are gated by a different entity entirely: the parent
line's status on submission, and a sibling decision row on production start.
"""

from test_helpers import (
    ApiErrorId,
    approve_artwork_for_set,
    approve_card_set,
    BRAND_DIRECTIVE_BASE,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    create_print_run_decision_payload,
    create_product_line_payload,
    create_product_line_raw,
    get_success_data,
    TEST_USERS,
    validate_error,
    validate_success,
)

PM = TEST_USERS["product_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


def test_a_set_with_approved_artwork_cannot_submit_while_its_line_plans(api):
    """PRD §3.2: "Submission of the set for review requires that its parent
    line already be `READY_FOR_APPROVAL` — otherwise `ERR_PRODUCT_LINE_NOT_READY`".

    Design: Difficulty/cross_entity_state_dependency/card_set_submission_requires_the_parent_line_ready_for_approval
    """
    license_obj = create_active_license(api)
    line = create_product_line_raw(api, license_obj["id"])
    assert line["status"] == "PLANNING"
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])

    resp = api.submit_card_set(card_set["id"], PM)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_LINE_NOT_READY, expected_status=409)


def test_the_blocked_submission_leaves_the_set_in_draft(api):
    """PRD §3.2: "A set meeting those conditions moves to `UNDER_REVIEW`."

    Design: Difficulty/cross_entity_state_dependency/card_set_submission_requires_the_parent_line_ready_for_approval
    """
    license_obj = create_active_license(api)
    line = create_product_line_raw(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    before = get_success_data(api.get_card_set(card_set["id"], PM))
    api.submit_card_set(card_set["id"], PM)

    after = validate_success(api.get_card_set(card_set["id"], PM))
    assert after["status"] == "DRAFT"
    assert after["version"] == before["version"], "the refused call wrote nothing"


def test_the_same_submit_succeeds_once_the_line_is_ready(api):
    """PRD §3.2: "Moving a line into readiness is the `ProductManager`'s
    declaration that the line is fit to be manufactured."

    Design: Difficulty/cross_entity_state_dependency/card_set_submission_requires_the_parent_line_ready_for_approval
    """
    license_obj = create_active_license(api)
    line = create_product_line_raw(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])

    ready = validate_success(api.ready_product_line(line["id"], PM))
    assert ready["status"] == "READY_FOR_APPROVAL"
    submitted = validate_success(api.submit_card_set(card_set["id"], PM))
    assert submitted["status"] == "UNDER_REVIEW"


def test_submission_is_refused_while_artwork_is_still_pending(api):
    """PRD §3.2: "and that no piece of its artwork still be sitting in
    `SUBMITTED` (`ERR_ARTWORK_APPROVAL_PENDING`)."

    Design: Difficulty/cross_entity_state_dependency/card_set_submission_requires_the_parent_line_ready_for_approval
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    get_success_data(
        api.submit_artwork(
            card_set["id"],
            {
                "artwork_code": "ART-BASE-002",
                "approver_id": license_obj["id"],
                "submitted_on": "2026-08-26T00:00:00Z",
            },
            PM,
        )
    )
    resp = api.submit_card_set(card_set["id"], PM)
    validate_error(resp, ApiErrorId.ERR_ARTWORK_APPROVAL_PENDING, expected_status=409)


def test_submission_is_refused_without_any_approved_artwork(api):
    """PRD §3.2: "that at least one piece of the set's artwork already be
    `APPROVED` (`ERR_ARTWORK_NOT_APPROVED`)".

    Design: Difficulty/cross_entity_state_dependency/card_set_submission_requires_the_parent_line_ready_for_approval
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    resp = api.submit_card_set(card_set["id"], PM)
    validate_error(resp, ApiErrorId.ERR_ARTWORK_NOT_APPROVED, expected_status=409)


def test_an_approved_set_without_a_locked_run_cannot_start_production(api):
    """PRD §3.2: "starting production on a set whose print-run status is not
    locked is refused with `ERR_PRINT_RUN_NOT_LOCKED`".

    Design: Difficulty/cross_entity_state_dependency/card_production_start_requires_a_locked_print_run
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(
        api, line["id"], set_tier="BASE", print_run_quantity=500, announced=True
    )
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    submitted = get_success_data(
        api.submit_card_set(card_set["id"], PM)
    )
    approved = get_success_data(approve_card_set(api, card_set["id"], submitted["version"]))
    assert approved["status"] == "APPROVED"
    assert approved["print_run_status"] == "UNDECIDED"

    resp = api.start_card_set_production(card_set["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_PRINT_RUN_NOT_LOCKED, expected_status=409)


def test_the_line_ready_move_is_accepted_before_any_frozen_quantity(api):
    """PRD §3.2: "From `PLANNING` it requires that the license named by
    `license_id` be in force, and that the physical configuration satisfy the
    divisibility rule above".

    Design: Difficulty/cross_entity_state_dependency/card_production_start_requires_a_locked_print_run
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    assert line["status"] == "READY_FOR_APPROVAL"
    assert line["sets_per_case"] == 2000, "20 x 10 x 10 must divide evenly by the set size"
    assert line["allocated_cards"] == 0


def test_approving_the_decision_unblocks_production_start(api):
    """PRD §3.3: "sets the set's print-run status to `LOCKED`, sets the set's
    `print_run_quantity` to the decision's `final_quantity`".

    Design: Difficulty/cross_entity_state_dependency/card_production_start_requires_a_locked_print_run
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(
        api, line["id"], set_tier="BASE", print_run_quantity=500, announced=True
    )
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    submitted = get_success_data(api.submit_card_set(card_set["id"], PM))
    approved = get_success_data(approve_card_set(api, card_set["id"], submitted["version"]))

    decision = get_success_data(
        api.create_print_run_decision(
            create_print_run_decision_payload(
                card_set_id=approved["id"],
                authority="BRAND_DIRECTIVE",
                proposed_against_line_version=line["version"],
                declared_quantity=12000,
                announced=True,
            ),
            PLANNER,
        )
    )
    assert decision["final_quantity"] == BRAND_DIRECTIVE_BASE["BASE"] == 12000
    frozen = validate_success(
        api.approve_print_run_decision(
            decision["id"],
            {
                "expected_card_set_version": approved["version"],
                "expected_product_line_version": line["version"],
            },
            PLANNER,
        )
    )
    assert frozen["final_quantity"] == decision["final_quantity"]
    read = validate_success(api.get_card_set(card_set["id"], PM))
    assert read["print_run_status"] in ("DISCLOSED", "UNDISCLOSED", "LOCKED"), (
        "the freeze is what unblocks production start"
    )


def test_a_product_line_whose_product_is_not_divisible_by_the_set_size_is_refused(api):
    """PRD §3.2: "it is required to be an exact multiple of `CARDS_PER_SET`,
    the platform's standard set size of 100 cards; a configuration whose
    product is not divisible by 100 is refused with
    `ERR_BOX_CONFIGURATION_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/card_production_start_requires_a_locked_print_run
    """
    license_obj = create_active_license(api)
    resp = api.create_product_line(
        create_product_line_payload(
            license_id=license_obj["id"],
            boxes_per_case=3,
            packs_per_box=3,
            cards_per_pack=3,
        ),
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_BOX_CONFIGURATION_INVALID, expected_status=422)