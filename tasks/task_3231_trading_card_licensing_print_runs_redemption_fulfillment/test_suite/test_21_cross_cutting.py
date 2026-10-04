"""Cross-cutting complexity: derived-field reconciliation, supersession and
read-your-writes.

Three claims about how a write propagates: the PATCH recomputes only its own
derived field, freezing a second decision supersedes the first, and a stale
version leaves nothing behind.
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
    submit_card_set_for_review,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

LM = TEST_USERS["licensing_manager_headers"]
PM = TEST_USERS["product_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


def test_patching_a_planning_line_recomputes_only_its_own_derived_field(api):
    """PRD §3.2: "Once the line leaves planning it is frozen; this is the only
    update-shaped operation in the platform, and it recomputes `sets_per_case`
    and advances the line's `version`."

    Design: Corner/cross_cutting_complexity_layers/patching_a_product_line_bumps_only_its_own_version
    """
    license_obj = create_active_license(api)
    line = create_product_line_raw(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)

    patched = validate_success(api.patch_product_line(line["id"], {"packs_per_box": 20}, PM))
    assert patched["packs_per_box"] == 20
    assert patched["sets_per_case"] == 4000, "20 x 20 x 10 recomputed from the patched field"
    assert patched["version"] == line["version"] + 1


def test_the_patch_does_not_reach_the_parent_licence_or_the_children(api):
    """PRD §2.5: "The important qualification is that recomputing an aggregate
    is not by itself a mutation of the entity the aggregate *describes*."

    Design: Corner/cross_cutting_complexity_layers/patching_a_product_line_bumps_only_its_own_version
    """
    license_obj = create_active_license(api)
    line = create_product_line_raw(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    license_before = validate_success(api.get_license(license_obj["id"], LM))

    validate_success(api.patch_product_line(line["id"], {"packs_per_box": 20}, PM))

    license_after = validate_success(api.get_license(license_obj["id"], LM))
    assert license_after["version"] == license_before["version"], (
        "the patch does not cascade into the licence"
    )
    child = validate_success(api.get_card_set(card_set["id"], PM))
    assert child["version"] == card_set["version"]
    assert child["product_line_id"] == line["id"]


def test_a_line_out_of_planning_can_no_longer_be_patched(api):
    """PRD §3.2: "Note that `packs_per_box`, `cards_per_pack`, `boxes_per_case`,
    `cases_printed`, `run_planned_on` and `line_name` all remain editable — but
    only while the line is still `PLANNING`."

    Design: Corner/cross_cutting_complexity_layers/patching_a_product_line_bumps_only_its_own_version
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    resp = api.patch_product_line(line["id"], {"packs_per_box": 20}, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_freezing_a_second_decision_supersedes_the_first(api):
    """PRD §3.3: "It supersedes every other decision for the same set that is
    currently `APPROVED`".

    Design: Corner/cross_cutting_complexity_layers/a_superseded_print_run_decision_can_be_replaced_by_a_fresh_proposal
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))

    first = get_success_data(
        api.create_print_run_decision(
            create_print_run_decision_payload(
                card_set_id=card_set["id"],
                authority="BRAND_DIRECTIVE",
                proposed_against_line_version=line["version"],
                declared_quantity=12000,
                announced=True,
            ),
            PLANNER,
        )
    )
    frozen_first = validate_success(
        api.approve_print_run_decision(
            first["id"],
            {
                "expected_card_set_version": card_set["version"],
                "expected_product_line_version": line["version"],
            },
            PLANNER,
        )
    )
    assert frozen_first["status"] == "APPROVED"

    second = get_success_data(
        api.create_print_run_decision(
            create_print_run_decision_payload(
                card_set_id=card_set["id"],
                authority="BRAND_DIRECTIVE",
                proposed_against_line_version=line["version"],
                declared_quantity=12000,
                announced=False,
                proposed_on="2026-09-06T00:00:00Z",
            ),
            PLANNER,
        )
    )
    current = get_success_data(api.get_card_set(card_set["id"], PM))
    frozen_second = validate_success(
        api.approve_print_run_decision(
            second["id"],
            {
                "expected_card_set_version": current["version"],
                "expected_product_line_version": line["version"],
            },
            PLANNER,
        )
    )
    assert frozen_second["status"] == "APPROVED"

    first_read = validate_success(api.get_print_run_decision(first["id"], PLANNER))
    assert first_read["status"] == "SUPERSEDED", "the second freeze displaced the first"


def test_only_one_decision_is_ever_approved_for_a_set(api):
    """PRD §3.3: "An approved decision is the freeze."

    Design: Corner/cross_cutting_complexity_layers/a_superseded_print_run_decision_can_be_replaced_by_a_fresh_proposal
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))

    for quantity, announced, proposed_on in (
        (12000, True, "2026-09-05T00:00:00Z"),
        (12000, False, "2026-09-06T00:00:00Z"),
    ):
        decision = get_success_data(
            api.create_print_run_decision(
                create_print_run_decision_payload(
                    card_set_id=card_set["id"],
                    authority="BRAND_DIRECTIVE",
                    proposed_against_line_version=line["version"],
                    declared_quantity=quantity,
                    announced=announced,
                    proposed_on=proposed_on,
                ),
                PLANNER,
            )
        )
        current = get_success_data(api.get_card_set(card_set["id"], PM))
        validate_success(
            api.approve_print_run_decision(
                decision["id"],
                {
                    "expected_card_set_version": current["version"],
                    "expected_product_line_version": line["version"],
                },
                PLANNER,
            )
        )

    rows, meta = validate_paginated(
        api.list_set_print_run_decisions(card_set["id"], PLANNER, params={"status": "APPROVED"})
    )
    assert meta["total_count"] == 1, "exactly one approved row survives per set"
    assert len(rows) == 1


def test_the_latest_freeze_wins_on_the_set(api):
    """PRD §3.3: "sets the set's `print_run_quantity` to the decision's
    `final_quantity`, sets the set's `announced` flag to the decision's
    `announced`".

    Design: Corner/cross_cutting_complexity_layers/a_superseded_print_run_decision_can_be_replaced_by_a_fresh_proposal
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))

    for quantity, announced, proposed_on in (
        (12000, True, "2026-09-05T00:00:00Z"),
        (12000, False, "2026-09-06T00:00:00Z"),
    ):
        decision = get_success_data(
            api.create_print_run_decision(
                create_print_run_decision_payload(
                    card_set_id=card_set["id"],
                    authority="BRAND_DIRECTIVE",
                    proposed_against_line_version=line["version"],
                    declared_quantity=quantity,
                    announced=announced,
                    proposed_on=proposed_on,
                ),
                PLANNER,
            )
        )
        current = get_success_data(api.get_card_set(card_set["id"], PM))
        validate_success(
            api.approve_print_run_decision(
                decision["id"],
                {
                    "expected_card_set_version": current["version"],
                    "expected_product_line_version": line["version"],
                },
                PLANNER,
            )
        )
    read = validate_success(api.get_card_set(card_set["id"], PM))
    assert read["print_run_quantity"] == 12000
    assert read["announced"] is False
    assert read["print_run_status"] == "UNDISCLOSED", (
        "the compound status resolves past LOCKED to the non-disclosing branch"
    )


def test_a_stale_expected_version_lands_nothing_at_all(api):
    """PRD §3.9: "It first requires the client's `expected_card_set_version` to
    match the card set's current `version`, and a divergence is a stale-version
    rejection carrying `ERR_STALE_VERSION` per §2.8".

    Design: Corner/cross_cutting_complexity_layers/rejected_transition_carries_no_side_effects
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    submitted = get_success_data(api.submit_card_set(card_set["id"], PM))
    stale_version = submitted["version"]

    get_success_data(
        api.submit_artwork(
            card_set["id"],
            {
                "artwork_code": "ART-BASE-002",
                "approver_id": license_obj["id"],
                "submitted_on": "2026-08-27T00:00:00Z",
            },
            PM,
        )
    )
    resp = api.approve_card_set(
        card_set["id"], {"expected_card_set_version": stale_version}, PM
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_the_stale_rejection_leaves_the_set_and_the_licence_counts_untouched(api):
    """PRD §2.8: "If the supplied `expected_card_set_version` does not match the
    card set's current `version`, the request is refused with `ERR_STALE_VERSION`
    (`412`) and no mutation occurs."

    Design: Corner/cross_cutting_complexity_layers/rejected_transition_carries_no_side_effects
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    submitted = get_success_data(api.submit_card_set(card_set["id"], PM))
    stale_version = submitted["version"]
    second_artwork = get_success_data(
        api.submit_artwork(
            card_set["id"],
            {
                "artwork_code": "ART-BASE-002",
                "approver_id": license_obj["id"],
                "submitted_on": "2026-08-27T00:00:00Z",
            },
            PM,
        )
    )
    api.approve_card_set(card_set["id"], {"expected_card_set_version": stale_version}, PM)

    read = validate_success(api.get_card_set(card_set["id"], PM))
    assert read["status"] == "UNDER_REVIEW"
    assert read["rights_pinned_version"] == 0
    lic = validate_success(api.get_license(license_obj["id"], LM))
    assert lic["approved_set_count"] == 0
    assert validate_success(api.get_artwork_approval(second_artwork["id"], PM))["status"] == (
        "SUBMITTED"
    ), "artwork was not consumed by the rejected call"


def test_the_current_version_moves_the_response_past_the_stale_check(api):
    """PRD §2.8: "This is the mechanism that stops a client from approving a set
    or freezing a print run based on a picture of the set that another writer
    has already moved past".

    PRD §2.8: "A card set that has never been approved holds
    `rights_pinned_version` of 0, which will not match any live license."

    Design: Corner/cross_cutting_complexity_layers/rejected_transition_carries_no_side_effects
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    submitted = get_success_data(api.submit_card_set(card_set["id"], PM))
    get_success_data(
        api.submit_artwork(
            card_set["id"],
            {
                "artwork_code": "ART-BASE-002",
                "approver_id": license_obj["id"],
                "submitted_on": "2026-08-27T00:00:00Z",
            },
            PM,
        )
    )
    resp = api.approve_card_set(
        card_set["id"], {"expected_card_set_version": submitted["version"]}, PM
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    current = validate_success(api.get_card_set(card_set["id"], PM))
    resp = api.approve_card_set(
        card_set["id"], {"expected_card_set_version": current["version"]}, PM
    )
    assert resp.status_code != 412, (
        "with the current version the stale check no longer fires"
    )
    assert resp.status_code in (200, 409)