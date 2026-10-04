"""Title catalog and committee selection claims (PRD §3.5, §2.8)."""
import pytest

from test_helpers import (
    ACM_APPROVER_ID,
    ACM_PROPOSER_ID,
    ACM_THIRD_ID,
    ApiErrorId,
    SelectionStatus,
    TEST_USERS,
    api_client,
    approve_selection,
    assert_age_band_selection,
    create_selection_payload,
    create_title,
    create_title_payload,
    make_advisory_committee_member_headers,
    propose_selection,
    reopen_selection,
    set_logical_clock,
    setup_approved_selection,
    setup_locked_selection,
    validate_error,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]


class TestTitleCatalog:
    def test_title_create_with_invalid_age_band_returns_invalid_request(self, api):
        """PRD §3.5: "The five bands partition the program's age range:
        `INFANT` for 0–11 months, `TODDLER` for 12–23, `TWO` for 24–35,
        `THREE` for 36–47, and `FOUR` for 48–59."
        PRD §2.8: "**Body well-formedness** — required fields are present,
        types are correct, enum values are in range, ... any violation is
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/title_create_with_invalid_age_band_returns_invalid_request
        """
        set_logical_clock()
        payload = create_title_payload(
            age_band="FIVE",
            title_name="Bad Band Book",
            author="X",
            available_from_month="2026-01",
            available_until_month="2026-12",
        )
        resp = api.create_title(payload, _ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestSelectionGuards:
    def test_selection_outside_title_window_rejected(self, api):
        """PRD §3.5: "A `PlatformAdmin` catalogs each title with its
        `title_name`, `author`, the `age_band` it suits, and an availability
        window from `available_from_month` through `available_until_month`,
        both inclusive" and "the month must fall inside the named title's
        inclusive availability window, else `ERR_TITLE_UNAVAILABLE_MONTH`."
        (Clock held at 2026-01 so the rejected month is not also in the past,
        isolating the window rule.)

        Design: Corner/validations/selection_outside_title_window_rejected
        """
        set_logical_clock("2026-01-01T00:00:00Z")
        title = create_title(
            "TWO",
            title_name="Short Run Book",
            author="S Short",
            available_from_month="2026-01",
            available_until_month="2026-06",
        )
        resp = api.create_selection(
            create_selection_payload("2026-08", "TWO", title["id"]),
            make_advisory_committee_member_headers(ACM_PROPOSER_ID),
        )
        validate_error(resp, ApiErrorId.ERR_TITLE_UNAVAILABLE_MONTH)
        edge = propose_selection("2026-06", "TWO", title["id"])
        assert edge["status"] == SelectionStatus.PROPOSED.value, (
            "the window's final month is inclusive and must accept a selection"
        )

    def test_selection_self_approval_rejected(self, api):
        """PRD §3.5: "a committee member approves a `PROPOSED` selection (else
        `ERR_INVALID_STATE`), but the approver's `X-User-ID` must differ from
        `proposed_by` — self-approval is rejected with
        `ERR_SELF_APPROVAL_FORBIDDEN`."

        Design: Corner/validations/selection_self_approval_rejected
        """
        set_logical_clock()
        title = create_title("INFANT")
        selection = propose_selection("2026-10", "INFANT", title["id"])
        resp = api.approve_selection(
            selection["id"], make_advisory_committee_member_headers(ACM_PROPOSER_ID)
        )
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)
        after = validate_success(api.get_selection(selection["id"], _ADMIN))
        assert after["status"] == SelectionStatus.PROPOSED.value
        assert after.get("approved_by") is None

    def test_selection_reopen_after_lock_rejected(self, api):
        """PRD §3.5: "That door closes permanently once a print order for the
        selection has been confirmed: confirmation locks the selection into the
        terminal `LOCKED` state, reopening a locked selection fails with
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/selection_reopen_after_lock_rejected
        """
        set_logical_clock()
        locked = setup_locked_selection("2026-10", "INFANT")
        selection = locked["selection"]
        assert selection["status"] == SelectionStatus.LOCKED.value
        resp = api.reopen_selection(
            selection["id"], {},
            make_advisory_committee_member_headers(ACM_APPROVER_ID),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_selection(selection["id"], _ADMIN))
        assert after["status"] == SelectionStatus.LOCKED.value
        assert after["approved_by"] == ACM_APPROVER_ID


class TestSelectionReworkCycle:
    def test_reopen_returns_selection_to_proposed_and_clears_approver(self, api):
        """PRD §3.5: "The cycle is reworkable: reopening an `APPROVED`
        selection — with an optional `reason` — sends it back to `PROPOSED`
        and clears `approved_by`."

        Design: Difficulty/non_linear_state_machine/selection_approve_reopen_rework_cycle
        """
        set_logical_clock()
        title = create_title("TODDLER")
        approved = setup_approved_selection("2026-12", "TODDLER", title_id=title["id"])[
            "selection"
        ]
        resp = api.reopen_selection(
            approved["id"],
            {"reason": "committee wants a different title"},
            make_advisory_committee_member_headers(ACM_APPROVER_ID),
        )
        reopened = validate_success(resp)
        assert_age_band_selection(reopened)
        assert reopened["status"] == SelectionStatus.PROPOSED.value
        assert reopened.get("approved_by") is None, "reopen clears the approver"
        assert reopened["proposed_by"] == ACM_PROPOSER_ID, (
            "the proposer is unchanged across the rework cycle"
        )

    def test_reopened_selection_can_be_approved_by_another_member(self, api):
        """PRD §3.5: "Approval moves the selection to `APPROVED` and records
        `approved_by`." and "the approver's `X-User-ID` must differ from
        `proposed_by`".

        Design: Difficulty/non_linear_state_machine/selection_approve_reopen_rework_cycle
        """
        set_logical_clock()
        title = create_title("TODDLER")
        approved = setup_approved_selection("2026-12", "TODDLER", title_id=title["id"])[
            "selection"
        ]
        reopen_selection(approved["id"], reason="committee wants a different title")
        reapproved = approve_selection(approved["id"], approver_id=ACM_THIRD_ID)
        assert reapproved["status"] == SelectionStatus.APPROVED.value
        assert reapproved["approved_by"] == ACM_THIRD_ID
        assert reapproved["proposed_by"] == ACM_PROPOSER_ID


class TestSelectionValidationOrdering:
    def test_past_month_selection_rejection_precedes_duplicate(self, api):
        """PRD §2.8: "When a request violates several rules at once, the
        earliest applicable check in this order produces the error, and later
        checks are not consulted" — scalar temporal rules (check 9) precede
        uniqueness rules (check 10).
        PRD §3.5: "the `mailing_month` must not be earlier than the current
        logical month (else `ERR_SELECTION_MONTH_PAST`); the pair of month and
        band must be unique, since a second selection for a slot that already
        has one is `ERR_SELECTION_EXISTS`".

        Design: Difficulty/priority_pair_validation_conflict/selection_month_past_beats_duplicate_conflict
        """
        set_logical_clock()
        title = create_title("INFANT")
        propose_selection("2026-10", "INFANT", title["id"])
        set_logical_clock("2026-11-01T00:00:00Z")
        resp = api.create_selection(
            create_selection_payload("2026-10", "INFANT", title["id"]),
            make_advisory_committee_member_headers(ACM_THIRD_ID),
        )
        validate_error(resp, ApiErrorId.ERR_SELECTION_MONTH_PAST)

    def test_selection_month_past_and_exists_each_fire_alone(self, api):
        """PRD §3.5: "the `mailing_month` must not be earlier than the current
        logical month (else `ERR_SELECTION_MONTH_PAST`); the pair of month and
        band must be unique, since a second selection for a slot that already
        has one is `ERR_SELECTION_EXISTS`".

        Design: Difficulty/priority_pair_validation_conflict/selection_month_past_beats_duplicate_conflict
        """
        set_logical_clock()
        title_infant = create_title("INFANT")
        title_toddler = create_title("TODDLER")
        set_logical_clock("2026-11-01T00:00:00Z")
        # Past month on a free slot: only the temporal rule can fire.
        resp = api.create_selection(
            create_selection_payload("2026-10", "TODDLER", title_toddler["id"]),
            make_advisory_committee_member_headers(ACM_PROPOSER_ID),
        )
        validate_error(resp, ApiErrorId.ERR_SELECTION_MONTH_PAST)
        # Current month on an occupied slot: only the uniqueness rule can fire.
        propose_selection("2026-11", "INFANT", title_infant["id"])
        resp = api.create_selection(
            create_selection_payload("2026-11", "INFANT", title_infant["id"]),
            make_advisory_committee_member_headers(ACM_APPROVER_ID),
        )
        validate_error(resp, ApiErrorId.ERR_SELECTION_EXISTS)
