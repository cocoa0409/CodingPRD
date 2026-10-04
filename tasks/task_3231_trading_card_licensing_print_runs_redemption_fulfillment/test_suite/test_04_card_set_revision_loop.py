"""Card-set revision loop and the license counters it moves.

A card set can cycle APPROVED -> DRAFT -> UNDER_REVIEW -> APPROVED without any
new artwork, and the license's approved_set_count follows it down and back up.
"""

from test_helpers import (
    TEST_USERS,
    approve_artwork_for_set,
    approve_card_set,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    get_success_data,
    validate_success,
)

LM = TEST_USERS["licensing_manager_headers"]
PM = TEST_USERS["product_manager_headers"]


def _set_in_under_review(api):
    """License active, line ready, set in UNDER_REVIEW holding one artwork."""
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    submitted = get_success_data(api.submit_card_set(card_set["id"], PM))
    assert submitted["status"] == "UNDER_REVIEW"
    return license_obj, line, submitted


def test_first_approval_raises_the_license_approved_set_count(api):
    """PRD §3.1: "`approved_set_count` is the subset of those whose `status` is
    `APPROVED`."

    PRD §3.2: "the set becomes `APPROVED`, `rights_pinned_version` is set to
    the license's current `rights_version`, and the license's counters are
    recomputed."

    Design: Difficulty/non_linear_state_machine/card_set_revision_loop_returns_to_under_review_for_a_second_approval
    """
    license_obj, line, card_set = _set_in_under_review(api)
    approved = validate_success(approve_card_set(api, card_set["id"], card_set["version"]))
    assert approved["status"] == "APPROVED"
    assert approved["rights_pinned_version"] == 1
    lic = validate_success(api.get_license(license_obj["id"], LM))
    assert lic["approved_set_count"] == 1
    assert lic["set_count"] == 1


def test_returning_the_set_to_draft_lowers_the_approved_set_count(api):
    """PRD §3.2: "From `UNDER_REVIEW`, a set can be returned to draft by the
    `ProductManager`, which reverses the review and additionally rejects every
    one of the set's artwork approvals that is still in `SUBMITTED`."

    PRD §2.9: "a value that moves backwards (a set rolled out of approval, a
    claim credited rather than approved) immediately lowers the counter rather
    than leaving a stale increment behind."

    Design: Difficulty/non_linear_state_machine/card_set_revision_loop_returns_to_under_review_for_a_second_approval
    """
    license_obj, line, card_set = _set_in_under_review(api)
    approved = validate_success(approve_card_set(api, card_set["id"], card_set["version"]))
    assert approved["status"] == "APPROVED"
    back = validate_success(api.return_card_set_to_draft(card_set["id"], PM))
    assert back["status"] == "DRAFT"
    lic = validate_success(api.get_license(license_obj["id"], LM))
    assert lic["approved_set_count"] == 0
    assert lic["set_count"] == 1, "both sets still exist, so set_count must not move"


def test_the_set_re_enters_under_review_without_new_artwork(api):
    """Submission of the set for review requires that its parent line already be
    `READY_FOR_APPROVAL` — otherwise `ERR_PRODUCT_LINE_NOT_READY` — that at
    least one piece of the set's artwork already be `APPROVED`
    (`ERR_ARTWORK_NOT_APPROVED`), and that no piece of its artwork still be
    sitting in `SUBMITTED` (`ERR_ARTWORK_APPROVAL_PENDING`).

    Design: Difficulty/non_linear_state_machine/card_set_revision_loop_returns_to_under_review_for_a_second_approval
    """
    license_obj, line, card_set = _set_in_under_review(api)
    approved = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    back = get_success_data(api.return_card_set_to_draft(card_set["id"], PM))
    resubmitted = get_success_data(api.submit_card_set(card_set["id"], PM))
    assert resubmitted["status"] == "UNDER_REVIEW"
    assert resubmitted["version"] > back["version"], (
        "the re-submission is a fresh write, not a replayed one"
    )


def test_the_second_approval_restores_the_approved_set_count(api):
    """PRD §3.1: "`approved_set_count` is the subset of those whose `status` is
    `APPROVED`."

    Aggregate counters — how many sets sit under a license, how many redemptions
    remain outstanding against a set, how many claims have been filed — are
    recomputed by full traversal rather than by incremental adjustment

    Design: Difficulty/non_linear_state_machine/card_set_revision_loop_returns_to_under_review_for_a_second_approval
    """
    license_obj, line, card_set = _set_in_under_review(api)
    first = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    get_success_data(api.return_card_set_to_draft(card_set["id"], PM))
    resubmitted = get_success_data(api.submit_card_set(card_set["id"], PM))
    second = validate_success(approve_card_set(api, card_set["id"], resubmitted["version"]))
    assert second["status"] == "APPROVED"
    assert second["version"] > first["version"]
    lic = validate_success(api.get_license(license_obj["id"], LM))
    assert lic["approved_set_count"] == 1, "the counter returns to exactly its prior value"


def test_the_approved_artwork_survives_the_whole_revision_loop(api):
    """PRD §3.2: "Submission of the set for review requires that its parent line
    already be `READY_FOR_APPROVAL` — otherwise `ERR_PRODUCT_LINE_NOT_READY` —
    that at least one piece of the set's artwork already be `APPROVED`
    (`ERR_ARTWORK_NOT_APPROVED`), and that no piece of its artwork still be
    sitting in `SUBMITTED` (`ERR_ARTWORK_APPROVAL_PENDING`)."

    Design: Difficulty/non_linear_state_machine/card_set_revision_loop_returns_to_under_review_for_a_second_approval
    """
    license_obj, line, card_set = _set_in_under_review(api)
    artwork = get_success_data(
        api.list_set_artwork(card_set["id"], TEST_USERS["product_manager_headers"])
    )
    assert len(artwork) == 1
    artwork_id = artwork[0]["id"]
    assert artwork[0]["status"] == "APPROVED"

    get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    get_success_data(api.return_card_set_to_draft(card_set["id"], PM))
    get_success_data(api.submit_card_set(card_set["id"], PM))
    read = validate_success(api.get_artwork_approval(artwork_id, PM))
    assert read["status"] == "APPROVED", "the revision loop never touches the artwork chain"
    assert read["decided_on"] is not None


def test_the_second_approval_repins_the_rights_version(api):
    """PRD §2.8: "When a card set is approved, the platform captures the license's
    rights version at that instant into the set's `rights_pinned_version`."

    Design: Difficulty/non_linear_state_machine/card_set_revision_loop_returns_to_under_review_for_a_second_approval
    """
    license_obj, line, card_set = _set_in_under_review(api)
    get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    lic_before = validate_success(api.get_license(license_obj["id"], LM))
    assert lic_before["rights_version"] == 1

    get_success_data(api.return_card_set_to_draft(card_set["id"], PM))
    resubmitted = get_success_data(api.submit_card_set(card_set["id"], PM))
    second = validate_success(approve_card_set(api, card_set["id"], resubmitted["version"]))
    lic_after = validate_success(api.get_license(license_obj["id"], LM))
    assert second["rights_pinned_version"] == lic_after["rights_version"], (
        "the pin re-reads the live license at the moment of approval"
    )