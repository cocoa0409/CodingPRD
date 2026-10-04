"""Artwork deadlines, the expiry sweep and the license suspension cascade.

Advancing the logical clock is a business event: it is what expires artwork
nobody decided. Suspension is the other broad unwind, and it reaches every
line and set underneath the license.
"""

from test_helpers import (
    TEST_USERS,
    approve_artwork_for_set,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    get_success_data,
    validate_success,
)

LM = TEST_USERS["licensing_manager_headers"]
PM = TEST_USERS["product_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

PENDING_SUBMITTED_ON = "2026-09-05T00:00:00Z"
AFTER_THE_WINDOW = "2026-09-20T00:00:00Z"


def _two_sets_with_pending_artwork(api):
    """Line READY, one set under review and one still draft, both with a
    SUBMITTED artwork waiting on a licensor decision."""
    license_obj = create_active_license(api, approval_window_days=10)
    line = create_line_ready(api, license_obj["id"])

    under_review = create_card_set_raw(
        api, line["id"], set_name="Flagship Base", set_tier="BASE", print_run_quantity=500
    )
    approve_artwork_for_set(api, under_review["id"], license_obj["id"])
    under_review = get_success_data(api.submit_card_set(under_review["id"], PM))

    draft = create_card_set_raw(
        api, line["id"], set_name="Flagship Chrome", set_tier="BASE", print_run_quantity=1000
    )

    pending = {}
    for key, card_set, code in (
        ("under_review", under_review, "ART-BASE-011"),
        ("draft", draft, "ART-CHROME-011"),
    ):
        pending[key] = get_success_data(
            api.submit_artwork(
                card_set["id"],
                {
                    "artwork_code": code,
                    "approver_id": license_obj["id"],
                    "submitted_on": PENDING_SUBMITTED_ON,
                },
                PM,
            )
        )
    return license_obj, line, under_review, draft, pending


def test_advancing_the_clock_past_the_window_expires_pending_artwork(api):
    """PRD §3.2: "any artwork still sitting in `SUBMITTED` whose `submitted_on`
    plus the license's `approval_window_days` has been passed by the new clock
    value is moved to `EXPIRED`."

    Design: Difficulty/transitive_cascade/license_suspension_clears_approved_sets_through_the_artwork_chain
    """
    license_obj, line, under_review, draft, pending = _two_sets_with_pending_artwork(api)
    assert pending["under_review"]["status"] == "SUBMITTED"
    assert pending["draft"]["status"] == "SUBMITTED"

    get_success_data(api.set_clock(AFTER_THE_WINDOW, ADMIN))

    for key in ("under_review", "draft"):
        read = validate_success(api.get_artwork_approval(pending[key]["id"], PM))
        assert read["status"] == "EXPIRED", (
            f"{key}: submitted_on plus the 10-day approval window has been passed"
        )
        assert read["version"] > pending[key]["version"]


def test_an_expired_artwork_leaves_the_parent_set_status_untouched(api):
    """PRD §3.2: "Expiry advances the artwork's `version` and deliberately
    leaves the parent card set's status exactly as it was — an expired artwork
    is not a rejection, and it does not silently un-approve the set it belongs
    to."

    Design: Difficulty/transitive_cascade/license_suspension_clears_approved_sets_through_the_artwork_chain
    """
    license_obj, line, under_review, draft, pending = _two_sets_with_pending_artwork(api)
    get_success_data(api.set_clock(AFTER_THE_WINDOW, ADMIN))

    read = validate_success(api.get_card_set(under_review["id"], PM))
    assert read["status"] == "UNDER_REVIEW", "expiry is not a rejection"
    draft_read = validate_success(api.get_card_set(draft["id"], PM))
    assert draft_read["status"] == "DRAFT", "the draft set was already out of review"


def test_the_clock_advance_is_what_drives_the_sweep(api):
    """PRD §2.4: "advancing it past an artwork approval's deadline is itself the
    event that expires that approval".

    Design: Difficulty/transitive_cascade/license_suspension_clears_approved_sets_through_the_artwork_chain
    """
    license_obj, line, under_review, draft, pending = _two_sets_with_pending_artwork(api)
    before = validate_success(api.get_artwork_approval(pending["under_review"]["id"], PM))
    assert before["status"] == "SUBMITTED", "still inside the window at the start"

    result = validate_success(api.set_clock(AFTER_THE_WINDOW, ADMIN))
    assert result["current_utc"].startswith("2026-09-20")

    after = validate_success(api.get_artwork_approval(pending["under_review"]["id"], PM))
    assert after["status"] == "EXPIRED"


def test_suspension_returns_the_line_to_planning(api):
    """PRD §3.1: "every product line whose `license_id` points at this license
    is returned to `PLANNING`".

    Design: Difficulty/transitive_cascade/license_suspension_clears_approved_sets_through_the_artwork_chain
    """
    license_obj, line, under_review, draft, pending = _two_sets_with_pending_artwork(api)
    assert validate_success(api.suspend_license(license_obj["id"], LM))["status"] == "SUSPENDED"
    read = validate_success(api.get_product_line(line["id"], PM))
    assert read["status"] == "PLANNING"


def test_suspension_resets_the_print_run_status_of_every_set_under_the_line(api):
    """PRD §3.1: "every card set belonging to one of those product lines has
    its print-run status reset to the `UNDECIDED` value, discarding whatever
    print-run decision had been frozen for it."

    Design: Difficulty/transitive_cascade/license_suspension_clears_approved_sets_through_the_artwork_chain
    """
    license_obj, line, under_review, draft, pending = _two_sets_with_pending_artwork(api)
    validate_success(api.suspend_license(license_obj["id"], LM))
    for card_set in (under_review, draft):
        read = validate_success(api.get_card_set(card_set["id"], PM))
        assert read["print_run_status"] == "UNDECIDED", (
            f"set {card_set['set_name']} must lose its frozen quantity commitment"
        )


def test_suspension_does_not_reverse_the_sets_own_status(api):
    """PRD §3.1: "A suspension does not reverse approvals — sets stay approved
    — but it does cancel the quantity commitments that had been made under
    them".

    Design: Difficulty/transitive_cascade/license_suspension_clears_approved_sets_through_the_artwork_chain
    """
    license_obj, line, under_review, draft, pending = _two_sets_with_pending_artwork(api)
    validate_success(api.suspend_license(license_obj["id"], LM))
    read = validate_success(api.get_card_set(under_review["id"], PM))
    assert read["status"] == "UNDER_REVIEW", "the cascade touches quantities, not review state"
    draft_read = validate_success(api.get_card_set(draft["id"], PM))
    assert draft_read["status"] == "DRAFT"