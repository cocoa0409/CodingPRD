"""State machine legality and transition tests (Corner section state_machines +
Difficulty rule non_linear_state_machine)."""
import pytest

from test_helpers import (
    api_client, TEST_USERS, make_volunteer_editor_headers,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_editor, create_page, create_revision, create_accepted_revision,
    create_open_dispute, set_clock, resolve_dispute_payload,
    create_protection_request_payload,
)


def _setup_page_with_accepted_revision(username_prefix="sm"):
    initiator, initiator_headers = create_editor(username=f"{username_prefix}_i", email=f"{username_prefix}_i@x.com")
    respondent, respondent_headers = create_editor(username=f"{username_prefix}_r", email=f"{username_prefix}_r@x.com")
    page = create_page(initiator_headers, title=f"{username_prefix} Page")
    revision, page = create_accepted_revision(page, initiator_headers)
    return initiator, initiator_headers, respondent, page, revision


class TestDisputeTerminalState:
    def test_dispute_resolve_from_resolved_returns_invalid_state(self):
        """PRD §3.4: "An `Administrator` may resolve an open dispute by providing
        `resolution_notes`. Resolution transitions the dispute to `RESOLVED`."
        PRD §5: `ERR_INVALID_STATE` (HTTP 409) — "Resource in wrong state for
        requested transition".

        Design: Corner/state_machines/dispute_resolve_from_resolved_returns_invalid_state
        """
        set_clock()
        initiator, initiator_headers, respondent, page, revision = _setup_page_with_accepted_revision("rs")
        dispute = create_open_dispute(page, initiator_headers, respondent["id"], revision["id"])
        resp = api_client.resolve_dispute(dispute["id"], resolve_dispute_payload(), TEST_USERS["administrator_headers"])
        resolved = validate_success(resp)
        assert resolved["status"] == "RESOLVED"
        # Second resolve attempt on a terminal dispute
        resp = api_client.resolve_dispute(
            dispute["id"], resolve_dispute_payload(resolution_notes="again"),
            TEST_USERS["administrator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api_client.get_dispute(dispute["id"], TEST_USERS["administrator_headers"]))
        assert after["resolution_notes"] == "resolved"


class TestRevisionInitialState:
    def test_newly_created_revision_starts_pending(self):
        """PRD §3.2: "Each revision is created in `PENDING` status."

        Design: Corner/state_machines/newly_created_revision_starts_pending
        """
        set_clock()
        editor, editor_headers = create_editor(username="is", email="is@x.com")
        page = create_page(editor_headers, title="Init State")
        revision = create_revision(page["id"], editor_headers, content_text="new")
        assert revision["status"] == "PENDING"


class TestEditorTerminalLockdown:
    def test_editor_block_from_blocked_terminal_lockdown(self):
        """PRD §3.1: "Blocking transitions `account_status` to `BLOCKED` — a
        terminal state."
        PRD §5: `ERR_INVALID_STATE` (HTTP 409).

        Design: Corner/state_machines/editor_block_from_blocked_terminal_lockdown
        """
        set_clock()
        editor, editor_headers = create_editor(username="tl", email="tl@x.com")
        resp = api_client.block_editor(editor["id"], TEST_USERS["administrator_headers"])
        blocked = validate_success(resp)
        assert blocked["account_status"] == "BLOCKED"
        # Suspend from BLOCKED must fail
        resp = api_client.suspend_editor(editor["id"], TEST_USERS["administrator_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api_client.get_editor(editor["id"], TEST_USERS["administrator_headers"]))
        assert after["account_status"] == "BLOCKED"

    def test_editor_reinstate_from_blocked_terminal_lockdown(self):
        """PRD §3.1: "Blocking transitions `account_status` to `BLOCKED` — a
        terminal state."
        PRD §5: `ERR_INVALID_STATE` (HTTP 409).

        Design: Corner/state_machines/editor_block_from_blocked_terminal_lockdown
        """
        set_clock()
        editor, editor_headers = create_editor(username="tl2", email="tl2@x.com")
        validate_success(api_client.block_editor(editor["id"], TEST_USERS["administrator_headers"]))
        resp = api_client.reinstate_editor(editor["id"], TEST_USERS["administrator_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api_client.get_editor(editor["id"], TEST_USERS["administrator_headers"]))
        assert after["account_status"] == "BLOCKED"


class TestDisputeEscalationTiming:
    def test_dispute_escalate_before_72_hours_rejected(self):
        """PRD §3.4: "Escalation requires that the current level be `TALK` or
        `NOTICE`, that at least 72 hours have elapsed since the dispute was
        opened or since the last escalation, and that no resolution has been
        reached at the current level. Attempting escalation sooner is rejected
        with `ERR_ESCALATION_TOO_SOON` (HTTP 409)."

        Design: Corner/state_machines/dispute_escalate_before_72_hours_rejected
        """
        set_clock()
        initiator, initiator_headers, respondent, page, revision = _setup_page_with_accepted_revision("es")
        dispute = create_open_dispute(page, initiator_headers, respondent["id"], revision["id"],
                                      dispute_type="SOURCING")
        # Only 24 hours elapsed
        set_clock("2026-09-02T00:00:00Z")
        resp = api_client.escalate_dispute(
            dispute["id"], {"expected_dispute_version": dispute["version"]}, initiator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ESCALATION_TOO_SOON)
        after = get_success_data(api_client.get_dispute(dispute["id"], TEST_USERS["administrator_headers"]))
        assert after["level"] == "TALK"


class TestArbitrationEscalationSideEffect:
    def test_arbitration_escalation_auto_protects_page_full(self):
        """PRD §3.4: "If the level becomes `ARBITRATION`, the page's
        `dispute_level` is set to `ARB` and the page is automatically protected
        at level `FULL`."

        Design: Corner/state_machines/arbitration_escalation_auto_protects_page_full
        """
        set_clock()
        initiator, initiator_headers, respondent, page, revision = _setup_page_with_accepted_revision("ar")
        dispute = create_open_dispute(page, initiator_headers, respondent["id"], revision["id"])
        # TALK -> NOTICE after 96 hours
        set_clock("2026-09-05T00:00:00Z")
        resp = api_client.escalate_dispute(
            dispute["id"], {"expected_dispute_version": dispute["version"]}, initiator_headers,
        )
        dispute = validate_success(resp)
        assert dispute["level"] == "NOTICE"
        # NOTICE -> ARBITRATION after another 96 hours
        set_clock("2026-09-09T00:00:00Z")
        resp = api_client.escalate_dispute(
            dispute["id"], {"expected_dispute_version": dispute["version"]}, initiator_headers,
        )
        dispute = validate_success(resp)
        assert dispute["level"] == "ARBITRATION"
        page_after = get_success_data(api_client.get_page(page["id"], TEST_USERS["administrator_headers"]))
        assert page_after["dispute_level"] == "ARB"
        assert page_after["protection_level"] == "FULL"


class TestDisputeEscalationLadderCyclic:
    def test_escalation_advances_level_and_returns_status_open(self):
        """PRD §3.4: "Escalation advances the level from `TALK` to `NOTICE` or
        from `NOTICE` to `ARBITRATION`, updates `escalated_at`, and increments
        the dispute's `version`."
        PRD §3.4: "The dispute opens at `level` `TALK` with `status` `OPEN`."

        Design: Difficulty/non_linear_state_machine/dispute_escalation_ladder_cyclic_levels
        """
        set_clock()
        initiator, initiator_headers, respondent, page, revision = _setup_page_with_accepted_revision("dl")
        dispute = create_open_dispute(page, initiator_headers, respondent["id"], revision["id"])
        created_version = dispute["version"]
        set_clock("2026-09-05T00:00:00Z")
        resp = api_client.escalate_dispute(
            dispute["id"], {"expected_dispute_version": created_version}, initiator_headers,
        )
        escalated = validate_success(resp)
        assert escalated["level"] == "NOTICE"
        assert escalated["status"] == "OPEN"
        assert escalated["version"] == created_version + 1
        page_after = get_success_data(api_client.get_page(page["id"], TEST_USERS["administrator_headers"]))
        assert page_after["dispute_level"] == "NOTICE"

    def test_escalation_cycles_open_through_notice_to_arbitration(self):
        """PRD §3.4: "Escalation advances the level from `TALK` to `NOTICE` or
        from `NOTICE` to `ARBITRATION`, updates `escalated_at`, and increments
        the dispute's `version`."

        Design: Difficulty/non_linear_state_machine/dispute_escalation_ladder_cyclic_levels
        """
        set_clock()
        initiator, initiator_headers, respondent, page, revision = _setup_page_with_accepted_revision("dl2")
        dispute = create_open_dispute(page, initiator_headers, respondent["id"], revision["id"])
        set_clock("2026-09-05T00:00:00Z")
        resp = api_client.escalate_dispute(
            dispute["id"], {"expected_dispute_version": dispute["version"]}, initiator_headers,
        )
        dispute = validate_success(resp)
        assert dispute["status"] == "OPEN"
        assert dispute["level"] == "NOTICE"
        set_clock("2026-09-09T00:00:00Z")
        resp = api_client.escalate_dispute(
            dispute["id"], {"expected_dispute_version": dispute["version"]}, initiator_headers,
        )
        dispute = validate_success(resp)
        assert dispute["status"] == "OPEN"
        assert dispute["level"] == "ARBITRATION"


class TestProtectionRequestFork:
    def test_protection_approve_sets_page_protection_level(self):
        """PRD §3.5: "Approval sets the page's `protection_level` to the
        requested level."
        PRD §3.5: "An `Administrator` may approve a protection request when the
        page has at least three flagged revisions in the last seven days or an
        open Arbitration dispute, and when the requested level is `SEMI` or
        `FULL`."

        Design: Difficulty/non_linear_state_machine/protection_request_fork_approve_or_deny
        """
        set_clock()
        editor, editor_headers = create_editor(username="pf", email="pf@x.com")
        page = create_page(editor_headers, title="Fork Page")
        # Satisfy the approval precondition: 3 flagged revisions in last 7 days
        for i in range(3):
            rev = create_revision(page["id"], editor_headers, content_text=f"bad {i}")
            resp = api_client.flag_revision(rev["id"], {"report_type": "VANDALISM"},
                                            TEST_USERS["administrator_headers"])
            validate_success(resp)
        resp = api_client.create_protection_request(
            page["id"], create_protection_request_payload(requested_level="FULL", reason="vandalism wave"),
            editor_headers,
        )
        request = validate_success(resp, expected_status=201)
        assert request["status"] == "PENDING"
        resp = api_client.approve_protection_request(request["id"], TEST_USERS["administrator_headers"])
        approved = validate_success(resp)
        assert approved["status"] == "APPROVED"
        page_after = get_success_data(api_client.get_page(page["id"], TEST_USERS["administrator_headers"]))
        assert page_after["protection_level"] == "FULL"

    def test_protection_deny_leaves_page_protection_untouched(self):
        """PRD §3.5: "An `Administrator` may deny a protection request without
        preconditions; denial transitions the request to `DENIED`."
        PRD §3.2: "A new page starts with `protection_level` set to `NONE`."

        Design: Difficulty/non_linear_state_machine/protection_request_fork_approve_or_deny
        """
        set_clock()
        editor, editor_headers = create_editor(username="pd", email="pd@x.com")
        page = create_page(editor_headers, title="Deny Page")
        resp = api_client.create_protection_request(
            page["id"], create_protection_request_payload(requested_level="SEMI", reason="caution"),
            editor_headers,
        )
        request = validate_success(resp, expected_status=201)
        resp = api_client.deny_protection_request(request["id"], TEST_USERS["administrator_headers"])
        denied = validate_success(resp)
        assert denied["status"] == "DENIED"
        page_after = get_success_data(api_client.get_page(page["id"], TEST_USERS["administrator_headers"]))
        assert page_after["protection_level"] == "NONE"
