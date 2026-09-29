"""Monitoring scans, the violation-case remediation cycle, tax verification and reinstatement."""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CASE_ALREADY_TERMINAL,
    ERR_CASE_INVALID_TRANSITION,
    ERR_OPEN_VIOLATION_CASES,
    ERR_RISK_SCORE_TOO_HIGH,
)
from test_helpers.assertions import (
    assert_append_only_row,
    assert_created,
    assert_error_response,
    assert_field,
    assert_fields,
    assert_list_response,
    assert_null,
    assert_object_response,
    assert_one_decimal_score,
    assert_pagination_meta,
    assert_total_count,
    assert_version_unchanged,
    rows_by,
)
from test_helpers.constants import (
    VERIFY_OUTCOME_FAILED,
    VERIFY_OUTCOME_UPHELD,
)
from test_helpers.fixtures import (
    activated_partner,
    clear_case,
    create_network,
    file_tax_document,
    open_case,
    pin_clock,
    read_affiliate,
    register_affiliate,
    suspend_partner,
    verify_tax_document,
)
from test_helpers.test_users import (
    COMPLIANCE_ANALYST,
    FINANCE_CONTROLLER,
    PROGRAM_ADMIN,
    SECOND_COMPLIANCE_ANALYST,
    make_affiliate_partner_headers,
)

CLOCK = f.JUL_05_00_00
NEXT_DAY = "2026-07-06T00:00:00.000Z"


def _transition(api, case_id, headers, action, note, **extra):
    """Drive one leg of the §3.7 remediation cycle and return the updated case."""
    return assert_object_response(
        api.transition_violation_case(
            case_id, f.case_transition_payload(action, note=note, **extra), headers
        )
    )


def _failed_remediation_round(api, case_id, affiliate_id, label):
    """`OPEN → REMEDIATION_REQUESTED → REMEDIATION_SUBMITTED → OPEN` on a failed verify."""
    requested = _transition(
        api,
        case_id,
        COMPLIANCE_ANALYST,
        "REQUEST_REMEDIATION",
        f"remove the brand keywords ({label})",
    )
    assert_field(requested, "state", "REMEDIATION_REQUESTED")

    submitted = _transition(
        api,
        case_id,
        make_affiliate_partner_headers(affiliate_id),
        "SUBMIT_REMEDIATION",
        f"campaigns paused ({label})",
        remediation_evidence_ref=f"evidence-{label}",
    )
    assert_fields(
        submitted,
        {
            "state": "REMEDIATION_SUBMITTED",
            "remediation_evidence_ref": f"evidence-{label}",
        },
    )

    return _transition(
        api,
        case_id,
        SECOND_COMPLIANCE_ANALYST,
        "VERIFY",
        f"brand terms still live ({label})",
        verify_outcome=VERIFY_OUTCOME_FAILED,
    )


class TestViolationCaseRemediationLoop:
    def test_escalating_before_two_failed_verifications_is_refused(self, api):
        """A brand-new `OPEN` case cannot be escalated straight away and is left untouched.

        PRD §3.7: "From `OPEN` a `ComplianceAnalyst` may escalate to `ESCALATED`, but only
        once `failed_verification_count` has reached two — an escalation attempted earlier
        is refused as an invalid transition."

        Design: Corner/state_machines/case_failed_verification_loops_back_to_open_then_escalates_to_upheld
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = register_affiliate(api, network["id"], partner_type="CONTENT")
        case = open_case(
            api,
            partner["id"],
            violation_type="TRADEMARK_BIDDING",
            detected_at=CLOCK,
            headers=COMPLIANCE_ANALYST,
        )

        # §3.7: "However it was opened, a case starts at `OPEN` with
        # `failed_verification_count` of zero and a `severity_weight` copied from the
        # fixed severity table at creation: 40 for `COOKIE_STUFFING`, 30 for
        # `FORCED_CLICK`, 25 for `UNAUTHORIZED_COUPON` and 20 for `TRADEMARK_BIDDING`."
        assert_fields(
            case,
            {
                "state": "OPEN",
                "failed_verification_count": 0,
                "severity_weight": 20,
                "violation_type": "TRADEMARK_BIDDING",
                "opened_by_user_id": "cmp-001",
                "version": 1,
            },
        )
        assert_null(case, "source_scan_id")

        response = api.transition_violation_case(
            case["id"],
            f.case_transition_payload("ESCALATE", note="straight to escalation"),
            COMPLIANCE_ANALYST,
        )

        assert_error_response(response, ERR_CASE_INVALID_TRANSITION, 409)
        unchanged = assert_object_response(
            api.get_violation_case(case["id"], COMPLIANCE_ANALYST)
        )
        assert_fields(unchanged, {"state": "OPEN", "failed_verification_count": 0})
        assert_version_unchanged(unchanged, 1, "violation case")

    def test_two_failed_verifications_return_the_case_to_open_then_escalation_upholds_it(
        self, api
    ):
        """Two failed rounds cycle the case back to `OPEN`, after which escalation upholds it.

        PRD §3.7: "A verification whose outcome is failed sends the case **back to `OPEN`**
        and raises its `failed_verification_count` by one; both variants are recomputed,
        though the point-in-time figure does not move because `OPEN` and
        `REMEDIATION_SUBMITTED` both count at full weight."

        Design: Corner/state_machines/case_failed_verification_loops_back_to_open_then_escalates_to_upheld
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = register_affiliate(api, network["id"], partner_type="CONTENT")
        case = open_case(
            api,
            partner["id"],
            violation_type="TRADEMARK_BIDDING",
            detected_at=CLOCK,
            headers=COMPLIANCE_ANALYST,
        )

        first = _failed_remediation_round(api, case["id"], partner["id"], "round-a")
        assert_fields(first, {"state": "OPEN", "failed_verification_count": 1})

        second = _failed_remediation_round(api, case["id"], partner["id"], "round-b")
        assert_fields(second, {"state": "OPEN", "failed_verification_count": 2})

        escalated = _transition(
            api, case["id"], COMPLIANCE_ANALYST, "ESCALATE", "two failed rounds"
        )
        assert_fields(
            escalated, {"state": "ESCALATED", "failed_verification_count": 2}
        )

        # §3.7: "From `ESCALATED` only a `ProgramAdmin` may verify with an upheld outcome,
        # moving the case to the terminal `UPHELD` and recomputing both variants."
        upheld = _transition(
            api,
            case["id"],
            PROGRAM_ADMIN,
            "VERIFY",
            "violation confirmed",
            verify_outcome=VERIFY_OUTCOME_UPHELD,
        )
        assert_fields(
            upheld,
            {
                "state": "UPHELD",
                "last_note": "violation confirmed",
                "failed_verification_count": 2,
            },
        )

        # §3.7: the point-in-time figure "counts only cases whose `state` is `OPEN`,
        # `REMEDIATION_REQUESTED`, `REMEDIATION_SUBMITTED`, `ESCALATED` or `UPHELD`", and
        # the trailing "state factor is 0.25 for a `VERIFIED_CLEARED` case and 1.00 for
        # every other state" — an `UPHELD` case detected today scores 20 * 1.00 * 1.00.
        owner = read_affiliate(api, partner["id"])
        assert_fields(
            owner,
            {
                "fraud_risk_score": 20,
                "open_violation_case_count": 1,
                "status": "PENDING_APPLICATION",
            },
        )
        assert_one_decimal_score(owner, "fraud_risk_score_trailing", 20.0)

    def test_transition_on_an_upheld_case_is_refused_as_already_terminal(self, api):
        """An `UPHELD` case accepts no further action and keeps its terminal state.

        PRD §2.10 rule 22: "The case's `state` is neither `VERIFIED_CLEARED` nor `UPHELD` —
        otherwise `ERR_CASE_ALREADY_TERMINAL` (409). Applies to case transitions."

        Design: Corner/state_machines/case_failed_verification_loops_back_to_open_then_escalates_to_upheld
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = register_affiliate(api, network["id"], partner_type="CONTENT")
        case = open_case(
            api,
            partner["id"],
            violation_type="TRADEMARK_BIDDING",
            detected_at=CLOCK,
            headers=COMPLIANCE_ANALYST,
        )
        _failed_remediation_round(api, case["id"], partner["id"], "round-a")
        _failed_remediation_round(api, case["id"], partner["id"], "round-b")
        _transition(api, case["id"], COMPLIANCE_ANALYST, "ESCALATE", "two failed rounds")
        upheld = _transition(
            api,
            case["id"],
            PROGRAM_ADMIN,
            "VERIFY",
            "violation confirmed",
            verify_outcome=VERIFY_OUTCOME_UPHELD,
        )
        assert_field(upheld, "state", "UPHELD")
        terminal_version = upheld["version"]

        response = api.transition_violation_case(
            case["id"],
            f.case_transition_payload("REQUEST_REMEDIATION", note="one more chance"),
            COMPLIANCE_ANALYST,
        )

        assert_error_response(response, ERR_CASE_ALREADY_TERMINAL, 409)
        after = assert_object_response(
            api.get_violation_case(case["id"], COMPLIANCE_ANALYST)
        )
        assert_field(after, "state", "UPHELD")
        assert_version_unchanged(after, terminal_version, "upheld violation case")


class TestTaxDocumentVerificationMirror:
    def test_verifying_the_newest_document_drives_the_partner_mirrored_status(self, api):
        """Accepting then rejecting successive filings walks the partner's mirror VALID → REJECTED.

        PRD §3.8: "Either outcome is mirrored onto the partner's `tax_document_status`, but
        **only when the verified document is that partner's most recent one ordered by
        `created_at` descending** — verifying an older document leaves the mirrored status
        alone, because the mirror always reflects the newest filing."

        Design: Corner/state_machines/tax_document_verification_syncs_affiliate_tax_document_status
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = register_affiliate(api, network["id"], partner_type="CONTENT")

        first = file_tax_document(
            api,
            partner["id"],
            headers=PROGRAM_ADMIN,
            form_type="W9",
            tax_id_last4="1234",
            treaty_withholding_bps=0,
            expires_on=f.TAX_EXPIRY_2027,
        )
        # §3.8: "Filing creates the document at `PENDING`, sets the partner's mirrored
        # `tax_document_status` to `PENDING`, and increments the partner's `version` while
        # leaving the partner's own `status` untouched."
        assert_field(first, "status", "PENDING")
        before = read_affiliate(api, partner["id"])
        assert_fields(
            before,
            {
                "tax_document_status": "PENDING",
                "status": "PENDING_APPLICATION",
                "version": 2,
            },
        )

        accepted = assert_object_response(
            api.verify_tax_document(
                first["id"], f.verify_tax_document_payload("VALID"), FINANCE_CONTROLLER
            )
        )
        # §3.8: "Accepting requires the document to be `PENDING` and its `expires_on` to be
        # strictly after the current logical clock, and moves it to `VALID` recording the
        # verifier in `verified_by_user_id`."
        assert_fields(accepted, {"status": "VALID", "verified_by_user_id": "fc-001"})
        assert_field(
            read_affiliate(api, partner["id"]), "tax_document_status", "VALID"
        )

        # A second, strictly later filing becomes the partner's most recent document.
        pin_clock(api, NEXT_DAY)
        second = file_tax_document(
            api,
            partner["id"],
            headers=make_affiliate_partner_headers(partner["id"]),
            form_type="W8BEN",
            tax_id_last4="9876",
            treaty_withholding_bps=1500,
            expires_on="2028-06-30T00:00:00.000Z",
        )
        assert_field(second, "status", "PENDING")
        assert_field(
            read_affiliate(api, partner["id"]), "tax_document_status", "PENDING"
        )

        # §3.8: "Rejecting requires only that the document is `PENDING` and moves it to the
        # terminal `REJECTED`."
        rejected = verify_tax_document(api, second["id"], "REJECTED")
        assert_field(rejected, "status", "REJECTED")

        after = read_affiliate(api, partner["id"])
        assert_fields(after, {"tax_document_status": "REJECTED", "version": 5})

        rows, meta = assert_list_response(
            api.list_tax_documents(
                partner["id"], FINANCE_CONTROLLER, {"limit": 10, "offset": 0}
            )
        )
        assert_pagination_meta(meta, total_count=2)
        by_id = rows_by(rows, "id")
        # The older row is not rewritten when a newer filing is rejected.
        assert_field(by_id[first["id"]], "status", "VALID")
        assert_field(by_id[second["id"]], "status", "REJECTED")

    def test_verifying_an_older_document_leaves_the_partner_mirror_alone(self, api):
        """Accepting a superseded filing moves that row only; the mirror keeps the newest status.

        PRD §3.8: "Either outcome is mirrored onto the partner's `tax_document_status`, but
        **only when the verified document is that partner's most recent one ordered by
        `created_at` descending** — verifying an older document leaves the mirrored status
        alone, because the mirror always reflects the newest filing."

        Design: Corner/state_machines/tax_document_verification_syncs_affiliate_tax_document_status
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = register_affiliate(api, network["id"], partner_type="CONTENT")

        older = file_tax_document(
            api,
            partner["id"],
            headers=PROGRAM_ADMIN,
            form_type="W9",
            tax_id_last4="1234",
            treaty_withholding_bps=0,
            expires_on=f.TAX_EXPIRY_2027,
        )
        pin_clock(api, NEXT_DAY)
        newer = file_tax_document(
            api,
            partner["id"],
            headers=PROGRAM_ADMIN,
            form_type="W8BEN",
            tax_id_last4="9876",
            treaty_withholding_bps=1500,
            expires_on="2028-06-30T00:00:00.000Z",
        )
        assert older["created_at"] < newer["created_at"], (
            "the second filing must be strictly newer so 'most recent' is unambiguous"
        )
        assert_field(
            read_affiliate(api, partner["id"]), "tax_document_status", "PENDING"
        )

        accepted = verify_tax_document(api, older["id"], "VALID")

        assert_fields(accepted, {"status": "VALID", "verified_by_user_id": "fc-001"})
        assert_field(
            read_affiliate(api, partner["id"]), "tax_document_status", "PENDING"
        )
        rows, meta = assert_list_response(
            api.list_tax_documents(
                partner["id"], FINANCE_CONTROLLER, {"limit": 10, "offset": 0}
            )
        )
        assert_pagination_meta(meta, total_count=2)
        by_id = rows_by(rows, "id")
        assert_field(by_id[newer["id"]], "status", "PENDING")


class TestReinstatementOpenCaseGate:
    def test_reinstating_a_partner_with_an_open_case_is_refused(self, api):
        """A suspended partner still carrying one `OPEN` case cannot be reinstated.

        PRD §2.10 rule 35: "When reinstating a partner, that partner's
        `open_violation_case_count` is 0 — otherwise `ERR_OPEN_VIOLATION_CASES` (409).
        Applies to the status-change operation."

        Design: Corner/validations/reinstatement_blocked_while_case_open_then_succeeds_after_clearing
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = activated_partner(api, network["id"], partner_type="CONTENT")
        affiliate_id = partner["affiliate_id"]
        open_case(
            api,
            affiliate_id,
            violation_type="TRADEMARK_BIDDING",
            detected_at=CLOCK,
            headers=COMPLIANCE_ANALYST,
        )
        suspend_partner(api, affiliate_id, reason="trademark bidding under investigation")

        # §3.7: "A `target_status` of `SUSPENDED` is available to a `ComplianceAnalyst`
        # from either `PENDING_APPLICATION` or `ACTIVE`, sets `suspension_cause` to
        # `COMPLIANCE_ACTION` and runs the same cascade."
        before = read_affiliate(api, affiliate_id)
        assert_fields(
            before,
            {
                "status": "SUSPENDED",
                "suspension_cause": "COMPLIANCE_ACTION",
                "open_violation_case_count": 1,
                "fraud_risk_score": 20,
            },
        )
        # A single `TRADEMARK_BIDDING` case detected on the clock instant is 20 * 1.00 *
        # 1.00, which already sits under the 25.0 reinstatement ceiling.
        assert_one_decimal_score(before, "fraud_risk_score_trailing", 20.0)

        response = api.change_affiliate_status(
            affiliate_id,
            f.status_change_payload("ACTIVE", "premature reinstatement attempt"),
            PROGRAM_ADMIN,
        )

        assert_error_response(response, ERR_OPEN_VIOLATION_CASES, 409)
        after = read_affiliate(api, affiliate_id)
        assert_fields(
            after, {"status": "SUSPENDED", "suspension_cause": "COMPLIANCE_ACTION"}
        )
        assert_version_unchanged(after, before["version"], "suspended partner")

    def test_reinstatement_succeeds_once_the_only_case_is_verified_cleared(self, api):
        """Clearing the last case empties the open count and lets the reinstatement through.

        PRD §3.7: "Reinstatement is a `ProgramAdmin` action on a `SUSPENDED` partner and
        carries three gates: the partner's `open_violation_case_count` must be zero, its
        `fraud_risk_score_trailing` must be strictly below 25.0, and if it has a
        `parent_affiliate_id` that parent must itself be `ACTIVE`."

        Design: Corner/validations/reinstatement_blocked_while_case_open_then_succeeds_after_clearing
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = activated_partner(api, network["id"], partner_type="CONTENT")
        affiliate_id = partner["affiliate_id"]
        case = open_case(
            api,
            affiliate_id,
            violation_type="TRADEMARK_BIDDING",
            detected_at=CLOCK,
            headers=COMPLIANCE_ANALYST,
        )
        suspend_partner(api, affiliate_id, reason="trademark bidding under investigation")

        cleared = clear_case(api, case["id"], affiliate_id)

        # §3.7: "A verification whose outcome is cleared moves the case to the terminal
        # `VERIFIED_CLEARED`, lowers the partner's `open_violation_case_count` by one and
        # recomputes both fraud variants."
        assert_field(cleared, "state", "VERIFIED_CLEARED")
        gated = read_affiliate(api, affiliate_id)
        assert_fields(
            gated, {"open_violation_case_count": 0, "fraud_risk_score": 0}
        )
        # §3.7: "The state factor is 0.25 for a `VERIFIED_CLEARED` case and 1.00 for every
        # other state." A weight-20 case detected on the clock instant decays by nothing —
        # "The decay is 1.00 minus 0.01 for each whole day of age" — so 20 * 1.00 * 0.25.
        assert_one_decimal_score(gated, "fraud_risk_score_trailing", 5.0)

        reinstated = assert_object_response(
            api.change_affiliate_status(
                affiliate_id,
                f.status_change_payload("ACTIVE", "case cleared, partner reinstated"),
                PROGRAM_ADMIN,
            )
        )

        # §3.7: "Reinstatement restores `status` to `ACTIVE` and `suspension_cause` to
        # `NONE` and nothing else".
        assert_fields(reinstated, {"status": "ACTIVE", "suspension_cause": "NONE"})
        assert_fields(
            read_affiliate(api, affiliate_id),
            {"status": "ACTIVE", "suspension_cause": "NONE"},
        )


class TestReinstatementTrailingScoreCeiling:
    def test_reinstatement_refused_when_cleared_cases_still_total_above_the_ceiling(
        self, api
    ):
        """Three cleared cookie-stuffing cases leave a trailing 30.0 that keeps the partner suspended.

        PRD §2.10 rule 36: "When reinstating a partner, that partner's
        `fraud_risk_score_trailing` is strictly below 25.0 — otherwise
        `ERR_RISK_SCORE_TOO_HIGH` (409). Applies to the status-change operation. The
        boundary is strict: a trailing score of exactly 25.0 keeps the partner suspended."

        Design: Corner/validations/reinstatement_rejected_when_trailing_score_sits_on_the_ceiling
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = activated_partner(api, network["id"], partner_type="CONTENT")
        affiliate_id = partner["affiliate_id"]

        cases = []
        for round_index in range(3):
            cases.append(
                open_case(
                    api,
                    affiliate_id,
                    violation_type="COOKIE_STUFFING",
                    detected_at=CLOCK,
                    headers=COMPLIANCE_ANALYST,
                )
            )
            if round_index == 1:
                # §3.7: "Whenever a recompute leaves an `ACTIVE` partner's point-in-time
                # `fraud_risk_score` at 70 or above, the program suspends that partner in
                # the same request, setting `status` to `SUSPENDED` and `suspension_cause`
                # to `FRAUD_SCORE_BREACH`" — two weight-40 cases sum to 80.
                breached = read_affiliate(api, affiliate_id)
                assert_fields(
                    breached,
                    {
                        "status": "SUSPENDED",
                        "suspension_cause": "FRAUD_SCORE_BREACH",
                        "fraud_risk_score": 80,
                    },
                )

        for case in cases:
            clear_case(api, case["id"], affiliate_id)

        before = read_affiliate(api, affiliate_id)
        assert_fields(
            before,
            {
                "status": "SUSPENDED",
                "suspension_cause": "FRAUD_SCORE_BREACH",
                "open_violation_case_count": 0,
                "fraud_risk_score": 0,
            },
        )
        # Three weight-40 cases detected on the clock instant, each cleared: the trailing
        # figure "counts cases in **any** state, `VERIFIED_CLEARED` included", so
        # 3 * 40 * 1.00 * 0.25 == 30.0.
        assert_one_decimal_score(before, "fraud_risk_score_trailing", 30.0)

        response = api.change_affiliate_status(
            affiliate_id,
            f.status_change_payload(
                "ACTIVE", "all fraud cases cleared, requesting reinstatement"
            ),
            PROGRAM_ADMIN,
        )

        assert_error_response(response, ERR_RISK_SCORE_TOO_HIGH, 409)
        after = read_affiliate(api, affiliate_id)
        assert_field(after, "status", "SUSPENDED")
        assert_version_unchanged(after, before["version"], "suspended partner")
        assert_total_count(
            api.list_violation_cases(
                COMPLIANCE_ANALYST,
                {
                    "affiliate_id": affiliate_id,
                    "state": "VERIFIED_CLEARED",
                    "limit": 10,
                    "offset": 0,
                },
            ),
            3,
        )

    def test_reinstatement_refused_when_the_trailing_score_is_exactly_the_ceiling(
        self, api
    ):
        """A trailing score landing exactly on 25.0 still refuses the reinstatement.

        PRD §2.10 rule 36: "When reinstating a partner, that partner's
        `fraud_risk_score_trailing` is strictly below 25.0 — otherwise
        `ERR_RISK_SCORE_TOO_HIGH` (409). Applies to the status-change operation. The
        boundary is strict: a trailing score of exactly 25.0 keeps the partner suspended."

        Design: Corner/validations/reinstatement_rejected_when_trailing_score_sits_on_the_ceiling
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = activated_partner(api, network["id"], partner_type="CONTENT")
        affiliate_id = partner["affiliate_id"]

        # `UNAUTHORIZED_COUPON` carries a `severity_weight` of 25, so four cases cleared on
        # the day they were detected contribute 4 * 25 * 1.00 * 0.25 == 25.0 exactly.
        cases = [
            open_case(
                api,
                affiliate_id,
                violation_type="UNAUTHORIZED_COUPON",
                detected_at=CLOCK,
                headers=COMPLIANCE_ANALYST,
            )
            for _ in range(4)
        ]
        for case in cases:
            assert_field(case, "severity_weight", 25)
            clear_case(api, case["id"], affiliate_id)

        before = read_affiliate(api, affiliate_id)
        assert_fields(
            before,
            {
                "status": "SUSPENDED",
                "open_violation_case_count": 0,
                "fraud_risk_score": 0,
            },
        )
        assert_one_decimal_score(before, "fraud_risk_score_trailing", 25.0)

        response = api.change_affiliate_status(
            affiliate_id,
            f.status_change_payload("ACTIVE", "cases cleared, requesting reinstatement"),
            PROGRAM_ADMIN,
        )

        assert_error_response(response, ERR_RISK_SCORE_TOO_HIGH, 409)
        after = read_affiliate(api, affiliate_id)
        assert_field(after, "status", "SUSPENDED")
        assert_version_unchanged(after, before["version"], "suspended partner")


class TestMonitoringScanCaseOpening:
    def test_scan_opens_a_forced_click_case_only_once_the_signal_reaches_its_threshold(
        self, api
    ):
        """A scan one basis point under the forced-click threshold opens nothing; 1500 opens one case.

        PRD §3.7: "The four signals are examined in a **fixed order**, and each condition
        that holds opens at most one case for this scan: `trademark_hits` greater than zero
        opens a `TRADEMARK_BIDDING` case; `forced_click_ratio_bps` of 1500 or more opens a
        `FORCED_CLICK` case; `cookie_stuffing_index` of 60 or more opens a `COOKIE_STUFFING`
        case; and `unauthorized_coupon_hits` greater than zero opens an
        `UNAUTHORIZED_COUPON` case."

        Design: Corner/endpoints/monitoring_scan_opens_a_case_only_when_a_signal_breaches_its_threshold
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = activated_partner(api, network["id"], partner_type="CONTENT")
        affiliate_id = partner["affiliate_id"]

        quiet = assert_created(
            api.create_monitoring_scan(
                f.monitoring_scan_payload(
                    affiliate_id,
                    engine="GOOGLE_ADS",
                    window_start="2026-06-01T00:00:00.000Z",
                    window_end="2026-06-08T00:00:00.000Z",
                    trademark_hits=0,
                    forced_click_ratio_bps=1499,
                    cookie_stuffing_index=59,
                    unauthorized_coupon_hits=0,
                ),
                COMPLIANCE_ANALYST,
            )
        )
        assert_field(quiet, "opened_case_count", 0)
        # §3.7: "Scans are append-only observations and are never edited, so like clicks
        # they carry only an `id` and a `created_at`".
        assert_append_only_row(quiet)

        breaching = assert_created(
            api.create_monitoring_scan(
                f.monitoring_scan_payload(
                    affiliate_id,
                    engine="GOOGLE_ADS",
                    window_start="2026-06-10T00:00:00.000Z",
                    window_end="2026-06-17T00:00:00.000Z",
                    trademark_hits=0,
                    forced_click_ratio_bps=1500,
                    cookie_stuffing_index=59,
                    unauthorized_coupon_hits=0,
                ),
                COMPLIANCE_ANALYST,
            )
        )
        # The stuffing index of 59 is still under its inclusive threshold of 60, so only
        # the forced-click signal fires.
        assert_field(breaching, "opened_case_count", 1)

        opened = assert_total_count(
            api.list_violation_cases(
                COMPLIANCE_ANALYST,
                {"source_scan_id": breaching["id"], "limit": 10, "offset": 0},
            ),
            1,
        )
        # §3.7: "Each case opened this way records the scan in its `source_scan_id` and
        # leaves `opened_by_user_id` null, because no human filed it."
        assert_fields(
            opened[0],
            {
                "violation_type": "FORCED_CLICK",
                "severity_weight": 30,
                "state": "OPEN",
                "failed_verification_count": 0,
                "source_scan_id": breaching["id"],
                "affiliate_id": affiliate_id,
            },
        )
        assert_null(opened[0], "opened_by_user_id")

        assert_total_count(
            api.list_violation_cases(
                COMPLIANCE_ANALYST,
                {"source_scan_id": quiet["id"], "limit": 10, "offset": 0},
            ),
            0,
        )
        assert_total_count(
            api.list_monitoring_scans(
                affiliate_id, COMPLIANCE_ANALYST, {"limit": 10, "offset": 0}
            ),
            2,
        )

        # §3.7: "The partner's `open_violation_case_count` rises by the number of cases
        # opened and both fraud-score variants are recomputed."  30 stays under the 70
        # auto-suspension threshold.
        owner = read_affiliate(api, affiliate_id)
        assert_fields(
            owner,
            {
                "open_violation_case_count": 1,
                "fraud_risk_score": 30,
                "status": "ACTIVE",
                "suspension_cause": "NONE",
            },
        )

    def test_scan_breaching_all_four_signals_opens_four_cases_and_suspends_the_partner(
        self, api
    ):
        """One scan over every threshold opens one case per signal and trips auto-suspension.

        PRD §3.7: "All four may fire from one scan, giving `opened_case_count` of 4. Each
        case opened this way records the scan in its `source_scan_id` and leaves
        `opened_by_user_id` null, because no human filed it."

        Design: Corner/endpoints/monitoring_scan_opens_a_case_only_when_a_signal_breaches_its_threshold
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = activated_partner(api, network["id"], partner_type="CONTENT")
        affiliate_id = partner["affiliate_id"]

        scan = assert_created(
            api.create_monitoring_scan(
                f.monitoring_scan_payload(
                    affiliate_id,
                    engine="GOOGLE_ADS",
                    window_start="2026-06-01T00:00:00.000Z",
                    window_end="2026-06-08T00:00:00.000Z",
                    trademark_hits=3,
                    forced_click_ratio_bps=1500,
                    cookie_stuffing_index=60,
                    unauthorized_coupon_hits=2,
                ),
                COMPLIANCE_ANALYST,
            )
        )

        assert_field(scan, "opened_case_count", 4)
        rows = assert_total_count(
            api.list_violation_cases(
                COMPLIANCE_ANALYST,
                {"source_scan_id": scan["id"], "limit": 10, "offset": 0},
            ),
            4,
        )
        by_type = rows_by(rows, "violation_type")
        # §3.7: "40 for `COOKIE_STUFFING`, 30 for `FORCED_CLICK`, 25 for
        # `UNAUTHORIZED_COUPON` and 20 for `TRADEMARK_BIDDING`."
        for violation_type, weight in (
            ("COOKIE_STUFFING", 40),
            ("FORCED_CLICK", 30),
            ("UNAUTHORIZED_COUPON", 25),
            ("TRADEMARK_BIDDING", 20),
        ):
            case = by_type[violation_type]
            assert_fields(
                case,
                {
                    "severity_weight": weight,
                    "state": "OPEN",
                    "source_scan_id": scan["id"],
                    "affiliate_id": affiliate_id,
                },
            )
            assert_null(case, "opened_by_user_id")

        # §3.7: the point-in-time figure "sums their `severity_weight` values, and caps the
        # result at 100", so 40 + 30 + 25 + 20 == 115 is stored as 100, which is at or
        # above the auto-suspension threshold.
        owner = read_affiliate(api, affiliate_id)
        assert_fields(
            owner,
            {
                "open_violation_case_count": 4,
                "fraud_risk_score": 100,
                "status": "SUSPENDED",
                "suspension_cause": "FRAUD_SCORE_BREACH",
            },
        )
