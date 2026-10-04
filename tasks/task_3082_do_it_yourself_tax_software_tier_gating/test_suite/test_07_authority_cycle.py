"""Authority callbacks, rejection correction cycles, and cascades."""
from test_helpers import (
    CORRECTION_HINTS,
    TEST_USERS,
    add_state_return,
    amend_return,
    file_return,
    filing_callback,
    get_return,
    list_refund_transfers,
    make_taxpayer_headers,
    ready_state_return,
    reopen_return,
    setup_accepted_return,
    setup_active_refund_transfer,
    setup_submitted_return,
    submit_review,
    unique_email,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


class TestRejectionCorrectionCycle:
    def test_rejection_correction_resubmission_cycle(self, api):
        """PRD §3.7: "Recovery is a loop, not a dead end. Reopening a
        `REJECTED` return takes it back to `DRAFT`, the filer corrects and
        re-submits through review, and each new filing creates a fresh attempt
        with the next `attempt_sequence`." PRD §3.6: "Each attempt is
        numbered: `attempt_sequence` is a 1-based, monotonically increasing
        sequence per return, assigned at creation in `created_at` order as one
        greater than the largest existing sequence for that return."

        Design: Difficulty/non_linear_state_machine/return_rejection_correction_resubmission_cycle
        """
        account, ret, attempt1, sr_ids = setup_submitted_return(
            forms=("F1040",), state_codes=("CA",), email=unique_email("cyc1")
        )
        filing_callback(attempt1["id"], "REJECTED", rejection_code="R0000_SSN_MISMATCH")
        ret.refresh(get_return(ret))
        assert ret.data["status"] == "REJECTED"
        reopen_return(ret)
        submit_review(ret)
        attempt2 = file_return(ret, payload_hash="hash-2")
        assert attempt2["attempt_sequence"] == 2
        assert attempt2["outcome"] == "PENDING"
        # The rolled-back state return re-filed with the second submission.
        states = api.list_state_returns(
            ret.id, make_taxpayer_headers(account["id"])
        )
        state_rows = {s["id"]: s for s in validate_success(states)}
        assert state_rows[sr_ids[0]]["status"] == "FILED"
        assert get_return(ret)["status"] == "SUBMITTED"

    def test_rejection_sets_correction_hint_and_state_rollback(self, api):
        """PRD §3.7: "an SSN mismatch yields "Verify the SSN exactly as
        printed on the Social Security card."; a name-control mismatch yields
        "Name control mismatch: check last-name spelling against SSA
        records."; a duplicate-filing yields "A return for this SSN was
        already accepted; amend instead of refiling."; a dependent-claimed
        yields "A dependent on this return was claimed elsewhere; review the
        dependent list."; and a math error yields "The authority recomputed a
        line; review the flagged worksheet totals.""

        Design: Difficulty/non_linear_state_machine/return_rejection_correction_resubmission_cycle
        """
        account, ret, attempt1, _ = setup_submitted_return(
            forms=("F1040",), email=unique_email("cyc1b")
        )
        rejected = filing_callback(
            attempt1["id"], "REJECTED", rejection_code="R0000_SSN_MISMATCH"
        )
        assert rejected["outcome"] == "REJECTED"
        assert (
            rejected["correction_hint"]
            == CORRECTION_HINTS["R0000_SSN_MISMATCH"]
        )


class TestAuthorityRejectionCascade:
    def test_rejection_cascades_to_return_and_state_returns(self, api):
        """PRD §3.7: "A rejection moves the attempt `PENDING` → `REJECTED`,
        records the `rejection_code`, stamps `resolved_at`, moves the parent
        return `SUBMITTED` → `REJECTED`, and rolls every `FILED` state return
        back to `READY`."

        Design: Difficulty/transitive_cascade/authority_rejection_three_hop_cascade
        """
        account, ret, attempt, sr_ids = setup_submitted_return(
            forms=("F1040",), state_codes=("CA", "NY"), email=unique_email("casc1")
        )
        rejected = filing_callback(
            attempt["id"], "REJECTED", rejection_code="R3000_MATH_ERROR"
        )
        assert rejected["outcome"] == "REJECTED"
        assert rejected["correction_hint"] == CORRECTION_HINTS["R3000_MATH_ERROR"]
        assert get_return(ret)["status"] == "REJECTED"
        states = api.list_state_returns(
            ret.id, make_taxpayer_headers(account["id"])
        )
        state_rows = {s["id"]: s for s in validate_success(states)}
        assert state_rows[sr_ids[0]]["status"] == "READY"
        assert state_rows[sr_ids[1]]["status"] == "READY"

    def test_rejection_cascade_leaves_return_reopenable(self, api):
        """PRD §3.7: "A rejection moves the attempt `PENDING` → `REJECTED`,
        records the `rejection_code`, stamps `resolved_at`, moves the parent
        return `SUBMITTED` → `REJECTED`, and rolls every `FILED` state return
        back to `READY`."

        Design: Difficulty/transitive_cascade/authority_rejection_three_hop_cascade
        """
        account, ret, attempt, sr_ids = setup_submitted_return(
            forms=("F1040",), state_codes=("CA", "NY"), email=unique_email("casc1b")
        )
        filing_callback(attempt["id"], "REJECTED", rejection_code="R3000_MATH_ERROR")
        assert get_return(ret)["status"] == "REJECTED"
        states = api.list_state_returns(
            ret.id, make_taxpayer_headers(account["id"])
        )
        state_rows = {s["id"]: s for s in validate_success(states)}
        assert all(s["status"] == "READY" for s in state_rows.values())
        # After the cascade the return can be reopened for correction.
        reopened = reopen_return(ret)
        assert reopened["status"] == "DRAFT"

    def test_immediate_visibility_of_cascaded_state(self, api):
        """PRD §3.7: "A rejection moves the attempt `PENDING` → `REJECTED`,
        records the `rejection_code`, stamps `resolved_at`, moves the parent
        return `SUBMITTED` → `REJECTED`, and rolls every `FILED` state return
        back to `READY`."

        Design: Corner/consistency_model/immediate_visibility_of_cascaded_state
        """
        account, ret, attempt, sr_ids = setup_submitted_return(
            forms=("F1040",), state_codes=("CA",), email=unique_email("cm1")
        )
        rejected = filing_callback(
            attempt["id"], "REJECTED", rejection_code="R0500_NAME_CONTROL"
        )
        # The callback response itself reports the resolved outcome.
        assert rejected["outcome"] == "REJECTED"
        # Every subsequent read observes the full cascade with no lag.
        assert get_return(ret)["status"] == "REJECTED"
        states = api.list_state_returns(
            ret.id, make_taxpayer_headers(account["id"])
        )
        state_rows = {s["id"]: s for s in validate_success(states)}
        assert state_rows[sr_ids[0]]["status"] == "READY"
        attempts = api.list_filing_attempts(
            ret.id, make_taxpayer_headers(account["id"])
        )
        attempt_rows = {a["id"]: a for a in validate_success(attempts)}
        assert (
            attempt_rows[attempt["id"]]["correction_hint"]
            == CORRECTION_HINTS["R0500_NAME_CONTROL"]
        )


class TestCorrectionHintMapping:
    def test_dependent_claimed_hint(self, api):
        """PRD §3.7: "a dependent-claimed yields "A dependent on this return
        was claimed elsewhere; review the dependent list.""

        Design: Corner/calculations/correction_hint_mapping_per_rejection_code
        """
        account, ret, attempt, _ = setup_submitted_return(
            forms=("F1040",), email=unique_email("calc4")
        )
        rejected = filing_callback(
            attempt["id"], "REJECTED", rejection_code="R2000_DEPENDENT_CLAIMED"
        )
        assert rejected["outcome"] == "REJECTED"
        assert rejected["rejection_code"] == "R2000_DEPENDENT_CLAIMED"
        assert (
            rejected["correction_hint"]
            == CORRECTION_HINTS["R2000_DEPENDENT_CLAIMED"]
        )


class TestAcceptanceCascade:
    def test_acceptance_settles_active_refund_transfer(self, api):
        """PRD §3.7: "An acceptance moves the attempt `PENDING` → `ACCEPTED`,
        stamps `resolved_at` from the logical clock, moves the parent return
        `SUBMITTED` → `ACCEPTED` (its terminal state for the original filing),
        and settles any `ACTIVE` refund-transfer agreement as §3.5 described."

        Design: Corner/cross_cutting_layers/accepted_filing_settles_active_refund_transfer
        """
        account, ret = _setup_review_ready_with_active_rt(email=unique_email("cc1"))
        attempt = file_return(ret, payload_hash="hash-rt")
        filing_callback(attempt["id"], "ACCEPTED")
        assert get_return(ret)["status"] == "ACCEPTED"
        agreements = list_refund_transfers(ret)
        assert agreements[0]["status"] == "SETTLED"
        attempts = api.list_filing_attempts(
            ret.id, make_taxpayer_headers(account["id"])
        )
        attempt_rows = {a["id"]: a for a in validate_success(attempts)}
        assert attempt_rows[attempt["id"]]["outcome"] == "ACCEPTED"
        account_data = validate_success(
            api.get_account(account["id"], TEST_USERS["platform_operator_headers"])
        )
        assert account_data["disclosure_accepted_version"] == "RTD-2026-1"


def _setup_review_ready_with_active_rt(email):
    """Return with F1040 + W2_WH(9000), ACTIVE refund transfer, then
    submit-review so it is READY_FOR_REVIEW."""
    from test_helpers import (
        accept_disclosure,
        add_form,
        create_refund_transfer,
        setup_return_with_forms,
    )

    account, ret = setup_return_with_forms(forms=("F1040",), email=email)
    add_form(ret, "W2_WH", 9000)
    create_refund_transfer(ret, bank_partner_code="BANK_B")
    accept_disclosure(ret)
    submit_review(ret)
    return account, ret


class TestAmendment:
    def test_amended_return_must_pass_through_review_before_filing(self, api):
        """PRD §3.6: "filing an `AMENDED` return directly is
        explicitly forbidden and rejected with `ERR_INVALID_STATE`, since an
        amended return must pass through review again first"

        Design: Corner/state_machines/amend_blocked_until_authority_acceptance
        """
        account, ret, _attempt = setup_accepted_return(
            forms=("F1040",), email=unique_email("sm1b")
        )
        amended = amend_return(ret)
        assert amended["status"] == "AMENDED"
        resp = api.file_return(
            ret.id, "hash-amend", ret.version,
            make_taxpayer_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
