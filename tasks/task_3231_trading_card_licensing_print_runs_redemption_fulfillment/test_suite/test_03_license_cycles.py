"""License lifecycle: the suspension/reactivation cycle and its unwind.

The license is the only entity in the platform with a true cycle back into a
state it previously held, and the cascade it drives reaches product lines,
card sets and their frozen quantities.
"""

from test_helpers import (
    ApiErrorId,
    approve_artwork_for_set,
    approve_card_set,
    assert_card_set,
    assert_license,
    assert_license_invariants,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    get_success_data,
    submit_card_set_for_review,
    TEST_USERS,
    validate_error,
    validate_success,
)

LM = TEST_USERS["licensing_manager_headers"]
PM = TEST_USERS["product_manager_headers"]


def _line_ready_with_approved_set(api):
    license_obj = create_active_license(api, approval_window_days=10)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(
        api, line["id"], set_tier="BASE", print_run_quantity=500
    )
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    return license_obj, line, card_set


def test_suspending_and_reactivating_returns_the_license_to_active(api):
    """PRD §3.1: "The first is activation, which serves double duty: it takes a
    `DRAFT` license live, and it also brings a `SUSPENDED` license back."

    Design: Difficulty/non_linear_state_machine/license_suspension_and_reactivation_cycles_back_to_active
    """
    license_obj, line, card_set = _line_ready_with_approved_set(api)
    suspended = validate_success(api.suspend_license(license_obj["id"], LM))
    assert suspended["status"] == "SUSPENDED"
    assert_license(suspended)
    reactivated = validate_success(api.activate_license(license_obj["id"], LM))
    assert reactivated["status"] == "ACTIVE", "the cycle re-enters the state it left"
    assert_license(reactivated)


def test_the_round_trip_advances_the_rights_version_twice(api):
    """PRD §3.1: "In both cases the effect is the same — the license's `status`
    becomes `ACTIVE`, its `version` advances by one, and its `rights_version`
    advances by one."

    PRD §3.1: "The visible effect is that `status` becomes `SUSPENDED` and both
    `version` and `rights_version` advance by one."

    Design: Difficulty/non_linear_state_machine/license_suspension_and_reactivation_cycles_back_to_active
    """
    license_obj, line, card_set = _line_ready_with_approved_set(api)
    start = validate_success(api.get_license(license_obj["id"], LM))
    assert start["rights_version"] == 1
    suspended = validate_success(api.suspend_license(license_obj["id"], LM))
    assert suspended["rights_version"] == 2
    reactivated = validate_success(api.activate_license(license_obj["id"], LM))
    assert reactivated["rights_version"] == 3, (
        "the round trip advanced the pinned-rights counter twice"
    )
    assert reactivated["version"] > suspended["version"] > start["version"]
    assert_license_invariants(reactivated)


def test_reactivating_a_suspended_license_without_an_approved_set_is_refused(api):
    """PRD §3.1: "Activation from `SUSPENDED` carries one additional
    requirement: the license must already govern at least one card set in
    `APPROVED` status. Reactivating a license that has never had a set approved
    is refused with `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/license_suspension_and_reactivation_cycles_back_to_active
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    draft_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    assert draft_set["status"] == "DRAFT"

    assert validate_success(api.suspend_license(license_obj["id"], LM))["status"] == "SUSPENDED"
    resp = api.activate_license(license_obj["id"], LM)
    # PRD 3.1: "Activation from `SUSPENDED` carries one additional requirement:
    # the license must already govern at least one card set in `APPROVED`
    # status. Reactivating a license that has never had a set approved is
    # refused with `ERR_INVALID_STATE`."
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_suspension_returns_every_line_to_planning(api):
    """PRD §3.1: "every product line whose `license_id` points at this license
    is returned to `PLANNING`".

    Design: Difficulty/non_linear_state_machine/license_suspension_and_reactivation_cycles_back_to_active
    """
    license_obj, line, card_set = _line_ready_with_approved_set(api)
    assert line["status"] == "READY_FOR_APPROVAL"
    validate_success(api.suspend_license(license_obj["id"], LM))
    read = validate_success(api.get_product_line(line["id"], PM))
    assert read["status"] == "PLANNING"
    assert read["sets_per_case"] == (
        read["boxes_per_case"] * read["packs_per_box"] * read["cards_per_pack"]
    )


def test_the_reactivated_license_leaves_its_line_in_planning(api):
    """PRD §3.1: "every product line whose `license_id` points at this license
    is returned to `PLANNING`".

    PRD §3.1: "sets stay approved — but it does cancel the quantity
    commitments that had been made under them".

    Design: Difficulty/non_linear_state_machine/license_suspension_and_reactivation_cycles_back_to_active
    """
    license_obj, line, card_set = _line_ready_with_approved_set(api)
    validate_success(api.suspend_license(license_obj["id"], LM))
    assert validate_success(api.activate_license(license_obj["id"], LM))["status"] == "ACTIVE"
    line_read = validate_success(api.get_product_line(line["id"], PM))
    assert line_read["status"] == "PLANNING", (
        "reactivation does not push the dependent line back out of PLANNING"
    )
    set_read = validate_success(api.get_card_set(card_set["id"], PM))
    assert set_read["status"] == "APPROVED"
    assert set_read["print_run_status"] == "UNDECIDED"
    assert_card_set(set_read)


def test_a_suspended_license_can_no_longer_authorise_line_readiness(api):
    """PRD §2.7: "A license counts as in-force when three things hold together:
    its `status` is `ACTIVE` as of the logical clock, the clock has reached or
    passed its `term_starts_on`, and the clock has not passed its
    `term_ends_on`."

    PRD §3.2: "From `PLANNING` it requires that the license named by
    `license_id` be in force".

    Design: Difficulty/non_linear_state_machine/license_suspension_and_reactivation_cycles_back_to_active
    """
    license_obj = create_active_license(api)
    resp = api.create_product_line(
        {
            "license_id": license_obj["id"],
            "line_name": "2026 Flagship Baseball",
            "line_kind": "BASE",
            "packs_per_box": 10,
            "cards_per_pack": 10,
            "boxes_per_case": 20,
            "cases_printed": 50,
            "run_planned_on": "2026-10-01T00:00:00Z",
        },
        PM,
    )
    line = get_success_data(resp)
    validate_success(api.suspend_license(license_obj["id"], LM))
    resp = api.ready_product_line(line["id"], PM)
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_IN_FORCE)


def test_an_expired_license_cannot_be_reactivated(api):
    """PRD §3.1: "Expiry is terminal — there is no path back out of `EXPIRED`".

    Design: Difficulty/non_linear_state_machine/license_suspension_and_reactivation_cycles_back_to_active
    """
    license_obj = create_active_license(
        api, term_ends_on="2026-12-31T00:00:00Z"
    )
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))

    get_success_data(
        api.set_clock("2027-06-01T00:00:00Z", TEST_USERS["platform_admin_headers"])
    )
    expired = validate_success(api.expire_license(license_obj["id"], LM))
    assert expired["status"] == "EXPIRED"
    resp = api.activate_license(license_obj["id"], LM)
    validate_error(resp, ApiErrorId.ERR_LICENSE_TERM_EXPIRED, expected_status=422)