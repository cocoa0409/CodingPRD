"""Review gating, filing, suspension, and the amendment hold."""
from test_helpers import (
    TEST_USERS,
    accept_disclosure,
    add_form,
    create_account,
    create_refund_transfer,
    create_return,
    file_return,
    filing_callback,
    get_pending_prompt,
    get_return,
    make_taxpayer_headers,
    seed_catalog,
    set_clock,
    setup_accepted_return,
    setup_return_with_forms,
    setup_submitted_return,
    submit_review,
    suspend_account,
    unique_email,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


class TestAccountSuspension:
    def test_suspension_blocks_otherwise_valid_submit_review(self, api):
        """PRD §3.1: "Suspension is one-way — this surface offers no
        reactivation path — and from that moment every mutating endpoint on
        the account's returns fails with `ERR_ACCOUNT_SUSPENDED`, while reads
        remain available."

        Design: Difficulty/cross_entity_state_dependency/suspended_account_blocks_return_review
        """
        account, ret = setup_return_with_forms(
            forms=("F1040",), email=unique_email("xes1")
        )
        suspend_account(account)
        resp = api.submit_review(
            ret.id, ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)
        assert get_return(ret)["status"] == "DRAFT"

    def test_suspension_blocks_form_add_on_return(self, api):
        """PRD §3.1: "Suspension is one-way — this surface offers no
        reactivation path — and from that moment every mutating endpoint on
        the account's returns fails with `ERR_ACCOUNT_SUSPENDED`, while reads
        remain available."

        Design: Difficulty/cross_entity_state_dependency/suspended_account_blocks_return_review
        """
        # Seed W2_WH too so the catalog-existence check passes and only the
        # suspension gate can fire.
        seed_catalog(tiers=("FREE",), forms=("F1040", "W2_WH"))
        account = create_account(email=unique_email("xes1b"))
        ret = create_return(account)
        add_form(ret, "F1040", 0)
        suspend_account(account)
        resp = api.add_form(
            ret.id, "W2_WH", 1000, ret.version,
            make_taxpayer_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)

    def test_suspension_masks_free_file_ineligibility(self, api):
        """PRD §2.8: "Only then does the server consult state: a `SUSPENDED`
        account rejects every return-graph mutation with
        `ERR_ACCOUNT_SUSPENDED` (HTTP 409), and a target resource in an
        illegal from-state for the requested transition is rejected with
        `ERR_INVALID_STATE` (HTTP 409) — this covers terminal-state lockdowns,
        a direct file attempt on an `AMENDED` return, and double-resolution of
        an already-settled prompt, among others."

        Design: Difficulty/priority_pair_validation_conflict/suspended_account_masks_free_file_ineligibility
        """
        account, ret = setup_return_with_forms(
            forms=("F1040", "SCH_D"), email=unique_email("prio1")
        )
        suspend_account(account)
        resp = api.submit_review(
            ret.id, ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)
        assert get_return(ret)["status"] == "DRAFT"

    def test_suspended_account_masks_ineligible_return_with_pending_prompt(self, api):
        """PRD §2.8: "Only then does the server consult state: a `SUSPENDED`
        account rejects every return-graph mutation with
        `ERR_ACCOUNT_SUSPENDED` (HTTP 409), and a target resource in an
        illegal from-state for the requested transition is rejected with
        `ERR_INVALID_STATE` (HTTP 409) — this covers terminal-state lockdowns,
        a direct file attempt on an `AMENDED` return, and double-resolution of
        an already-settled prompt, among others."

        Design: Difficulty/priority_pair_validation_conflict/suspended_account_masks_free_file_ineligibility
        """
        # Even with a PENDING prompt outstanding (the upgrade-ack gate), the
        # suspension state check fires first.
        account, ret = setup_return_with_forms(
            forms=("F1040", "SCH_D"), email=unique_email("prio1b")
        )
        assert get_pending_prompt(ret) is not None
        suspend_account(account)
        resp = api.submit_review(
            ret.id, ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)
        after = get_return(ret)
        assert after["status"] == "DRAFT"
        assert after["upgrade_prompt_pending"] is True


class TestSubmitReviewGates:
    def test_pending_prompt_masks_free_file_ineligibility(self, api):
        """PRD §3.6: "Any outstanding `PENDING` upgrade prompt blocks review
        with `ERR_UPGRADE_ACK_REQUIRED` (HTTP 409) — the price change must be
        acknowledged or decline-downgraded first, and this gate is evaluated
        before the free-file gate."

        Design: Difficulty/priority_pair_validation_conflict/upgrade_ack_required_masks_free_file_ineligibility
        """
        account, ret = setup_return_with_forms(
            forms=("F1040", "SCH_D"), email=unique_email("prio2")
        )
        resp = api.submit_review(
            ret.id, ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UPGRADE_ACK_REQUIRED)
        after = get_return(ret)
        assert after["status"] == "DRAFT"
        assert after["upgrade_prompt_pending"] is True

    def test_pending_prompt_gate_fires_for_over_income_filer(self, api):
        """PRD §3.6: "Any outstanding `PENDING` upgrade prompt blocks review
        with `ERR_UPGRADE_ACK_REQUIRED` (HTTP 409) — the price change must be
        acknowledged or decline-downgraded first, and this gate is evaluated
        before the free-file gate."

        Design: Difficulty/priority_pair_validation_conflict/upgrade_ack_required_masks_free_file_ineligibility
        """
        # Over-income account: the free-file gate would also fail, but the
        # pending-prompt gate fires first.
        account, ret = setup_return_with_forms(
            forms=("F1040", "SCH_D"),
            agi_cents=9000000,
            email=unique_email("prio2b"),
        )
        resp = api.submit_review(
            ret.id, ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UPGRADE_ACK_REQUIRED)
        assert get_return(ret)["status"] == "DRAFT"

    def test_empty_form_set_rejected_on_submit(self, api):
        """PRD §3.6: "The return must contain at least one `ACTIVE` form, else
        `ERR_NO_FORMS_ON_RETURN` (HTTP 422)." PRD §3.2: "An empty form set
        classifies as `FREE`."

        Design: Difficulty/boundary_precision_check/empty_form_set_boundary_on_submit
        """
        from test_helpers import remove_form

        account, ret = setup_return_with_forms(
            forms=("F1040",), email=unique_email("bnd2")
        )
        forms = api.list_forms(ret.id, make_taxpayer_headers(account["id"]))
        form_id = validate_success(forms)[0]["id"]
        remove_form(ret, form_id)
        resp = api.submit_review(
            ret.id, ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NO_FORMS_ON_RETURN)
        after = get_return(ret)
        assert after["minimum_required_tier"] == "FREE"
        assert after["status"] == "DRAFT"

    def test_empty_form_set_boundary_after_all_forms_removed(self, api):
        """PRD §3.6: "The return must contain at least one `ACTIVE` form, else
        `ERR_NO_FORMS_ON_RETURN` (HTTP 422)." PRD §3.2: "An empty form set
        classifies as `FREE`."

        Design: Difficulty/boundary_precision_check/empty_form_set_boundary_on_submit
        """
        from test_helpers import remove_form

        account, ret = setup_return_with_forms(
            forms=("F1040", "W2_WH"), email=unique_email("bnd2b")
        )
        forms = api.list_forms(ret.id, make_taxpayer_headers(account["id"]))
        for form in validate_success(forms):
            remove_form(ret, form["id"])
        resp = api.submit_review(
            ret.id, ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NO_FORMS_ON_RETURN)
        assert get_return(ret)["minimum_required_tier"] == "FREE"


class TestRefundMath:
    def test_federal_refund_excludes_removed_forms(self, api):
        """PRD §3.2: "And because withholding and estimated-payment forms feed
        the refund, `federal_refund_cents` is recomputed as the exact cent sum
        of `amount_cents` over `ACTIVE` forms whose form spec has
        `counts_toward_refund` set; a negative total means the taxpayer owes
        rather than receives."

        Design: Corner/calculations/federal_refund_aggregation_excludes_removed_forms
        """
        from test_helpers import remove_form

        account, ret = setup_return_with_forms(
            forms=("F1040",), email=unique_email("calc3")
        )
        w2 = add_form(ret, "W2_WH", 7000)
        assert get_return(ret)["federal_refund_cents"] == 7000
        removed = remove_form(ret, w2["id"])
        assert removed["status"] == "REMOVED"
        assert get_return(ret)["federal_refund_cents"] == 0


class TestFilingInFlight:
    def test_reopen_blocked_while_filing_pending(self, api):
        """PRD §3.6: "Reopening a `READY_FOR_REVIEW` return takes it back to
        `DRAFT` — provided no filing attempt is in flight, else
        `ERR_FILING_IN_FLIGHT` — and the revision loop between `DRAFT` and
        `READY_FOR_REVIEW` may cycle any number of times."

        Design: Corner/state_machines/reopen_while_filing_pending_rejected
        """
        account, ret, attempt, _ = setup_submitted_return(
            forms=("F1040",), email=unique_email("sm2")
        )
        resp = api.reopen_return(
            ret.id, ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FILING_IN_FLIGHT)
        assert get_return(ret)["status"] == "SUBMITTED"

    def test_second_file_rejected_while_attempt_pending(self, api):
        """PRD §3.6: "filing an `AMENDED` return directly is
        explicitly forbidden and rejected with `ERR_INVALID_STATE`, since an
        amended return must pass through review again first"

        Design: Corner/validations/filing_while_pending_attempt_exists_rejected
        """
        account, ret, attempt, _ = setup_submitted_return(
            forms=("F1040",), email=unique_email("val8")
        )
        resp = api.file_return(
            ret.id, "hash-2", ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_return(ret)["status"] == "SUBMITTED"


class TestRefundTransferNotActiveGate:
    def test_file_blocked_until_disclosure_accepted_then_succeeds(self, api):
        """PRD §3.5: "The disclosure is a hard gate. Accepting it moves the
        agreement `PENDING_DISCLOSURE` → `ACTIVE` — allowed while the return
        is `DRAFT`, `AMENDED`, or `READY_FOR_REVIEW`, and rejected from any
        other status with `ERR_INVALID_STATE` — and produces three effects:
        the owning account's `disclosure_accepted_version` is set to the
        agreement's `disclosure_version`, the return's
        `refund_transfer_selected` flag becomes true (it is never set
        directly, only by acceptance), and the $40.00 service fee folds into
        `total_fees_due_cents`."

        Design: Corner/endpoints/refund_transfer_file_blocked_until_disclosure_accepted
        """
        # W2_WH carries the withholding that funds the refund-transfer fees.
        account2, ret2 = setup_return_with_forms(
            forms=("F1040",), email=unique_email("ep4")
        )
        add_form(ret2, "W2_WH", 9000)
        agreement = create_refund_transfer(ret2, bank_partner_code="BANK_A")
        assert agreement["status"] == "PENDING_DISCLOSURE"
        submit_review(ret2)
        accepted = accept_disclosure(ret2)
        assert accepted["status"] == "ACTIVE"
        after_accept = get_return(ret2)
        assert after_accept["refund_transfer_selected"] is True
        assert after_accept["total_fees_due_cents"] == 4000
        assert after_accept["federal_refund_cents"] == 9000
        attempt = file_return(ret2, payload_hash="hash-rt")
        assert attempt["outcome"] == "PENDING"


class TestAmendmentHold:
    def _setup_accepted_then_amended_to_review(self):
        """Return filed + ACCEPTED at 2026-10-01T00:00:00Z, amended, and back
        in READY_FOR_REVIEW. Returns (account, ret)."""
        seed_catalog(tiers=("FREE",), forms=("F1040",))
        set_clock("2026-10-01T00:00:00Z")
        account = create_account(email=unique_email("ovr2"))
        ret = create_return(account)
        add_form(ret, "F1040", 0)
        submit_review(ret)
        attempt = file_return(ret, payload_hash="hash-1")
        filing_callback(attempt["id"], "ACCEPTED")
        ret.refresh(get_return(ret))
        from test_helpers import amend_return

        amend_return(ret)
        submit_review(ret)
        return account, ret

    def test_refile_at_exact_hold_boundary_rejected(self, api):
        """PRD §3.7: "Re-filing after an acceptance is throttled by the
        **amendment hold**. When any filing attempt for the return previously
        resolved `ACCEPTED`, the system takes the most recent such attempt's
        `resolved_at` and rejects any new filing while the logical clock reads
        at or before `resolved_at` plus 24 hours."

        Design: Difficulty/resource_temporal_overlap/amendment_hold_closed_interval_boundary
        """
        account, ret = self._setup_accepted_then_amended_to_review()
        set_clock("2026-10-02T00:00:00Z")
        resp = api.file_return(
            ret.id, "hash-2", ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_HOLD_ACTIVE)

    def test_refile_one_second_past_boundary_succeeds(self, api):
        """PRD §3.7: "The boundary is closed: filing at exactly the 24-hour
        mark is still rejected with `ERR_AMENDMENT_HOLD_ACTIVE`, and only a
        clock reading strictly past the boundary — one second suffices —
        allows the filing through."

        Design: Difficulty/resource_temporal_overlap/amendment_hold_closed_interval_boundary
        """
        account, ret = self._setup_accepted_then_amended_to_review()
        set_clock("2026-10-02T00:00:00Z")
        resp = api.file_return(
            ret.id, "hash-2", ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_HOLD_ACTIVE)
        set_clock("2026-10-02T00:00:01Z")
        attempt = file_return(ret, payload_hash="hash-2")
        assert attempt["attempt_sequence"] == 2
        assert get_return(ret)["status"] == "SUBMITTED"


class TestAmend:
    def test_amend_blocked_on_never_accepted_return(self, api):
        """PRD §3.7: "A return that was accepted can instead be **amended**:
        amending requires at least one `ACCEPTED` filing attempt on the return
        and moves it `ACCEPTED` → `AMENDED`, reopening it for edits — forms
        may be added and removed, state returns reworked, snapshots imported."

        Design: Corner/state_machines/amend_blocked_until_authority_acceptance
        """
        account, ret = setup_return_with_forms(
            forms=("F1040",), email=unique_email("sm1")
        )
        resp = api.amend_return(
            ret.id, ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_return(ret)["status"] == "DRAFT"
