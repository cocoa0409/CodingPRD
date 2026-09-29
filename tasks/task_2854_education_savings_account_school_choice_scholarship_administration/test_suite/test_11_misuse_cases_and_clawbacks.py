"""Misuse cases: the substantiation cascade, the penalty tier and the reversal identity."""

from test_helpers import (
    CO,
    ER1,
    MISUSE_SUBSTANTIATED,
    PA,
    PENALTY_RATE_LOW,
    PENALTY_RATE_MID,
    Q1_ADMIN_FEE_CENTS,
    Q1_GROSS_CENTS,
    Q1_NET_CENTS,
    ApiErrorId,
    adjudicate_misuse_case,
    assert_append_only_record,
    assert_clawback_entry,
    assert_ledger_identity,
    assert_misuse_case,
    create_account_status_action_payload,
    create_adjudication_payload,
    decide_appeal,
    file_clawback_appeal,
    file_purchase_request,
    open_misuse_case,
    read_account,
    read_misuse_case,
    read_purchase_request,
    reinstate_account,
    review_misuse_case,
    setup_approved_purchase_request,
    setup_clawback_issued_case,
    setup_misuse_case_under_review,
    setup_pending_purchase_request,
    setup_purchase_environment,
    setup_substantiated_case,
    suspend_account,
    validate_error,
    validate_paginated,
    validate_success,
)

FIRST_HOLD_CENTS = 150000
SECOND_HOLD_CENTS = 60000


class TestSubstantiationCascade:
    """One adjudication reaches the account, its requests and its encumbrances."""

    def test_substantiation_suspends_voids_both_requests_and_releases_the_hold(self, api):
        """PRD §3.8: "First, the substantiation itself moves the account `ACTIVE →
        SUSPENDED` with `suspension_reason` set to the literal string
        `MISUSE_SUBSTANTIATED`. Second, that suspension itself voids every purchase request
        of the account whose `approval_status` is `PENDING_REVIEW` or `APPROVED`, setting
        `approval_status` to `VOID` and `settlement_status` to `CANCELLED`. Third, each
        voided request that had actually reached `APPROVED` releases its hold, so the
        account's `encumbered_cents` falls by that request's `amount_cents` and its
        `balance_cents` rises by the same amount."

        Design: Difficulty/transitive_cascade/substantiation_suspends_account_voids_requests_and_releases_encumbrances
        """
        env = setup_purchase_environment(quarters=1, provider_codes=("TUTORING",))
        env = setup_approved_purchase_request(
            env, category_key="tutoring", amount_cents=FIRST_HOLD_CENTS
        )
        approved_request_id = env.purchase_request_id
        pending = file_purchase_request(
            env.account_id,
            env.student_id,
            env.provider_id,
            env.tutoring["id"],
            amount_cents=40000,
            service_start_at="2026-11-02T00:00:00Z",
            service_end_at="2026-12-01T00:00:00Z",
        )
        assert pending["approval_status"] == "PENDING_REVIEW", (
            f"the second request is still unreviewed, got {pending['approval_status']!r}"
        )

        before = read_account(env.account_id)
        assert before["balance_cents"] == Q1_NET_CENTS - FIRST_HOLD_CENTS, (
            f"one hold has taken the balance to 79088, got {before['balance_cents']}"
        )
        assert before["encumbered_cents"] == FIRST_HOLD_CENTS, (
            f"with 150000 encumbered, got {before['encumbered_cents']}"
        )

        env = setup_misuse_case_under_review(
            env,
            case_overrides={
                "purchase_request_id": approved_request_id,
                "detection_rule": "DUPLICATE_INVOICE",
                "disallowed_principal_cents": FIRST_HOLD_CENTS,
            },
        )
        adjudicated = adjudicate_misuse_case(
            env.misuse_case_id,
            "SUBSTANTIATED",
            rationale="Invoice duplication confirmed against the provider ledger.",
        )
        assert_misuse_case(adjudicated)
        assert adjudicated["status"] == "SUBSTANTIATED", (
            f"the case is substantiated, got {adjudicated['status']!r}"
        )
        assert adjudicated["adjudicated_by_user_id"] == CO["X-User-ID"], (
            f"by the acting officer, got {adjudicated['adjudicated_by_user_id']!r}"
        )

        account = read_account(env.account_id)
        assert account["status"] == "SUSPENDED", (
            f"hop one suspends the account, got {account['status']!r}"
        )
        assert account["suspension_reason"] == MISUSE_SUBSTANTIATED, (
            f"with the literal cascade reason, got {account['suspension_reason']!r}"
        )

        voided = read_purchase_request(approved_request_id)
        assert voided["approval_status"] == "VOID", (
            f"hop two voids the approved request, got {voided['approval_status']!r}"
        )
        assert voided["settlement_status"] == "CANCELLED", (
            f"and closes its money track, got {voided['settlement_status']!r}"
        )
        cancelled = read_purchase_request(pending["id"])
        assert cancelled["approval_status"] == "VOID", (
            "hop two reaches the merely pending request as well, got "
            f"{cancelled['approval_status']!r}"
        )
        assert cancelled["settlement_status"] == "CANCELLED", (
            f"cancelling it too, got {cancelled['settlement_status']!r}"
        )

        assert account["encumbered_cents"] == 0, (
            f"hop three releases the hold entirely, got {account['encumbered_cents']}"
        )
        assert account["balance_cents"] == Q1_NET_CENTS, (
            "hop four restores the pre-encumbrance balance of 229088, got "
            f"{account['balance_cents']}"
        )
        assert account["lifetime_spent_cents"] == 0, (
            f"no money left the account, got {account['lifetime_spent_cents']}"
        )
        assert account["lifetime_clawed_back_cents"] == 0, (
            f"and nothing has been recovered yet, got "
            f"{account['lifetime_clawed_back_cents']}"
        )
        assert_ledger_identity(account)

    def test_every_voided_hold_is_released_not_only_the_one_the_case_names(self, api):
        """PRD §3.8: "Third, each voided request that had actually reached `APPROVED`
        releases its hold, so the account's `encumbered_cents` falls by that request's
        `amount_cents` and its `balance_cents` rises by the same amount."

        PRD §3.8: "Second, that suspension itself voids every purchase request of the
        account whose `approval_status` is `PENDING_REVIEW` or `APPROVED`, setting
        `approval_status` to `VOID` and `settlement_status` to `CANCELLED`."

        Design: Difficulty/transitive_cascade/substantiation_suspends_account_voids_requests_and_releases_encumbrances
        """
        env = setup_purchase_environment(
            quarters=1, provider_codes=("TUTORING", "MATERIALS")
        )
        env = setup_approved_purchase_request(
            env, category_key="tutoring", amount_cents=FIRST_HOLD_CENTS
        )
        named_request_id = env.purchase_request_id
        second = file_purchase_request(
            env.account_id,
            env.student_id,
            env.provider_id,
            env.materials["id"],
            amount_cents=SECOND_HOLD_CENTS,
        )
        second = validate_success(
            api.decide_purchase_request(second["id"], {"decision": "APPROVED"}, ER1)
        )
        assert second["approval_status"] == "APPROVED", (
            f"a second hold is in place on another category, got "
            f"{second['approval_status']!r}"
        )

        before = read_account(env.account_id)
        assert before["encumbered_cents"] == FIRST_HOLD_CENTS + SECOND_HOLD_CENTS, (
            f"two holds total 210000, got {before['encumbered_cents']}"
        )
        assert before["balance_cents"] == Q1_NET_CENTS - 210000, (
            f"leaving 19088 spendable, got {before['balance_cents']}"
        )

        env = setup_misuse_case_under_review(
            env,
            case_overrides={
                "purchase_request_id": named_request_id,
                "detection_rule": "CAP_CIRCUMVENTION",
                "disallowed_principal_cents": FIRST_HOLD_CENTS,
            },
        )
        adjudicate_misuse_case(
            env.misuse_case_id,
            "SUBSTANTIATED",
            rationale="The household split one engagement across two catalogue lines.",
        )

        for request_id, label in (
            (named_request_id, "the request the case names"),
            (second["id"], "the request the case never mentions"),
        ):
            row = read_purchase_request(request_id)
            assert row["approval_status"] == "VOID", (
                f"{label} is voided, got {row['approval_status']!r}"
            )
            assert row["settlement_status"] == "CANCELLED", (
                f"{label} has its money track cancelled, got "
                f"{row['settlement_status']!r}"
            )

        account = read_account(env.account_id)
        assert account["encumbered_cents"] == 0, (
            "both holds are released, not merely the named one, got "
            f"{account['encumbered_cents']}"
        )
        assert account["balance_cents"] == Q1_NET_CENTS, (
            "and the sum of the two releases restores 229088 exactly, got "
            f"{account['balance_cents']}"
        )
        assert account["lifetime_spent_cents"] == 0, (
            f"a release is not a spend, got {account['lifetime_spent_cents']}"
        )
        assert_ledger_identity(account)


class TestAdjudicationAuthority:
    """Deciding a misuse outcome is exclusive to the compliance role."""

    def test_an_expense_reviewer_cannot_adjudicate_the_case(self, api):
        """PRD §2.1: "A `ComplianceOfficer` opens, reviews and adjudicates misuse cases,
        issues clawbacks, suspends and reinstates accounts, and sanctions or delists
        providers."

        PRD §2.1: "An `ExpenseReviewer` decides the approval track of purchase requests and
        settles provider claims."

        PRD §2.8: "2. Role permitted on this endpoint — `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/expense_reviewer_cannot_adjudicate_a_misuse_case
        """
        env = setup_purchase_environment(quarters=1, provider_codes=("TUTORING",))
        env = setup_pending_purchase_request(
            env, category_key="tutoring", amount_cents=FIRST_HOLD_CENTS
        )
        env = setup_misuse_case_under_review(
            env,
            case_overrides={
                "purchase_request_id": env.purchase_request_id,
                "disallowed_principal_cents": FIRST_HOLD_CENTS,
            },
        )
        assert env.misuse_case["status"] == "UNDER_REVIEW", (
            f"the case is ready for adjudication, got {env.misuse_case['status']!r}"
        )

        refused = api.adjudicate_misuse_case(
            env.misuse_case_id,
            create_adjudication_payload(
                "SUBSTANTIATED", "Reviewer attempted to close their own finding."
            ),
            ER1,
        )
        validate_error(refused, ApiErrorId.FORBIDDEN_ROLE.value, 403)

        blocked = read_misuse_case(env.misuse_case_id)
        assert blocked["status"] == "UNDER_REVIEW", (
            f"the case did not move, got {blocked['status']!r}"
        )
        assert blocked["adjudicated_by_user_id"] is None, (
            f"and records no adjudicator, got {blocked['adjudicated_by_user_id']!r}"
        )
        account = read_account(env.account_id)
        assert account["status"] == "ACTIVE", (
            f"the account is untouched by the refused call, got {account['status']!r}"
        )
        assert account["suspension_reason"] is None, (
            f"with no suspension reason, got {account['suspension_reason']!r}"
        )
        request = read_purchase_request(env.purchase_request_id)
        assert request["approval_status"] == "PENDING_REVIEW", (
            f"and the implicated request still awaits review, got "
            f"{request['approval_status']!r}"
        )

        allowed = validate_success(
            api.adjudicate_misuse_case(
                env.misuse_case_id,
                create_adjudication_payload(
                    "SUBSTANTIATED", "Attendance logs contradict the billed hours."
                ),
                CO,
            )
        )
        assert allowed["status"] == "SUBSTANTIATED", (
            "the identical payload from the compliance officer succeeds, so the block was "
            f"at the route and not in the body, got {allowed['status']!r}"
        )
        assert read_account(env.account_id)["status"] == "SUSPENDED", (
            "and only then does the cascade run"
        )


class TestPenaltyTier:
    """The tier is keyed on the principal alone, never on the running total."""

    def test_a_principal_of_250000_takes_the_middle_band_and_splits_the_recovery(
        self, api
    ):
        """PRD §3.8: "Re-deriving the tier from `clawback_total_cents` instead of the
        principal would be wrong: a principal of exactly 250000 sits in the 0.20 band and
        produces a total of 300000, whereas re-deriving from the total would push it into
        the 0.35 band and produce 337500."

        PRD §3.8: "`account_debit_cents` is the smaller of the account's `balance_cents` and
        `clawback_total_cents`."

        Design: Difficulty/combinatorial_formula/clawback_penalty_tier_keyed_on_principal_not_running_total
        """
        env = setup_purchase_environment(quarters=1, provider_codes=("TUTORING",))
        env = setup_misuse_case_under_review(
            env,
            case_overrides={
                "detection_rule": "CAP_CIRCUMVENTION",
                "disallowed_principal_cents": 250000,
            },
        )
        adjudicate_misuse_case(
            env.misuse_case_id,
            "SUBSTANTIATED",
            rationale="Cap circumvention confirmed across two catalogue lines.",
        )

        clawback = validate_success(api.issue_clawback(env.misuse_case_id, CO))
        assert clawback["penalty_rate"] == PENALTY_RATE_MID, (
            "the principal of exactly 250000 sits on the inclusive upper edge of the 0.20 "
            f"band, got {clawback['penalty_rate']}"
        )
        assert clawback["penalty_cents"] == 50000, (
            f"so the penalty is 50000, got {clawback['penalty_cents']}"
        )
        assert clawback["clawback_total_cents"] == 300000, (
            "and the total is 300000, not the 337500 a tier re-derived from the total "
            f"would produce, got {clawback['clawback_total_cents']}"
        )
        assert clawback["account_debit_cents"] == Q1_NET_CENTS, (
            f"the debit is capped by the balance at 229088, got "
            f"{clawback['account_debit_cents']}"
        )
        assert clawback["receivable_cents"] == 300000 - Q1_NET_CENTS, (
            f"leaving 70912 as a receivable, got {clawback['receivable_cents']}"
        )
        assert clawback["account_balance_cents"] == 0, (
            f"and the balance lands on exactly 0, never negative, got "
            f"{clawback['account_balance_cents']}"
        )
        assert (
            clawback["account_debit_cents"] + clawback["receivable_cents"]
            == clawback["clawback_total_cents"]
        ), f"the debit and the receivable sum back to the total, got {clawback!r}"

        case = read_misuse_case(env.misuse_case_id)
        assert case["status"] == "CLAWBACK_ISSUED", (
            f"the case advances to CLAWBACK_ISSUED, got {case['status']!r}"
        )
        account = read_account(env.account_id)
        assert account["balance_cents"] == 0, (
            f"the account is drained but not overdrawn, got {account['balance_cents']}"
        )
        assert account["lifetime_clawed_back_cents"] == Q1_NET_CENTS, (
            f"and the recovery counter carries the debit, got "
            f"{account['lifetime_clawed_back_cents']}"
        )

        entries, meta = validate_paginated(
            api.list_case_clawback_entries(env.misuse_case_id, PA)
        )
        assert meta["total_count"] == 2, (
            f"a split recovery appends two ledger rows, got {meta['total_count']}"
        )
        assert [entry["entry_type"] for entry in entries] == [
            "ACCOUNT_DEBIT",
            "RECEIVABLE",
        ], f"oldest first, the debit then the receivable, got {entries!r}"
        assert entries[0]["amount_cents"] == Q1_NET_CENTS, (
            f"the debit row carries 229088, got {entries[0]['amount_cents']}"
        )
        assert entries[1]["amount_cents"] == 300000 - Q1_NET_CENTS, (
            f"and the receivable row 70912, got {entries[1]['amount_cents']}"
        )
        for entry in entries:
            assert_clawback_entry(entry)
            assert_append_only_record(entry, "clawback entry")
            assert entry["misuse_case_id"] == env.misuse_case_id, (
                f"each row names the case that produced it, got {entry!r}"
            )
            assert entry["created_by_user_id"] == CO["X-User-ID"], (
                f"and the acting officer, got {entry['created_by_user_id']!r}"
            )

    def test_one_cent_above_the_low_band_edge_takes_the_middle_rate(self, api):
        """PRD §3.8: "A principal of 50000 takes 0.10, giving a penalty of 5000 and a total
        of 55000; a principal of 50001 takes 0.20, giving a penalty of 10000 and a total of
        60001."

        PRD §3.8: "`penalty_rate` is the first matching band for
        `disallowed_principal_cents`: 0.10 when the principal is 50000 cents or less, 0.20
        when it is 250000 cents or less, and 0.35 for anything above that. Both band
        boundaries are inclusive on their upper edge."

        Design: Difficulty/combinatorial_formula/clawback_penalty_tier_keyed_on_principal_not_running_total
        """
        env = setup_purchase_environment(quarters=1, provider_codes=("TUTORING",))
        env = setup_misuse_case_under_review(
            env,
            case_overrides={
                "detection_rule": "NON_ALLOWABLE_EXPENSE",
                "disallowed_principal_cents": 50001,
            },
        )
        adjudicate_misuse_case(
            env.misuse_case_id,
            "SUBSTANTIATED",
            rationale="The purchase is outside every allowable catalogue line.",
        )

        clawback = validate_success(api.issue_clawback(env.misuse_case_id, CO))
        assert clawback["penalty_rate"] == PENALTY_RATE_MID, (
            f"one cent past the inclusive 50000 edge lands in the 0.20 band, got "
            f"{clawback['penalty_rate']}"
        )
        assert clawback["penalty_rate"] != PENALTY_RATE_LOW, (
            "the low band stops at 50000 inclusive, so it cannot apply here"
        )
        assert clawback["penalty_cents"] == 10000, (
            f"the penalty rounds half up to 10000, got {clawback['penalty_cents']}"
        )
        assert clawback["clawback_total_cents"] == 60001, (
            f"and the total is 60001, got {clawback['clawback_total_cents']}"
        )
        assert clawback["account_debit_cents"] == 60001, (
            f"the balance covers the whole total, got "
            f"{clawback['account_debit_cents']}"
        )
        assert clawback["receivable_cents"] == 0, (
            f"so nothing is booked as receivable, got {clawback['receivable_cents']}"
        )
        assert clawback["account_balance_cents"] == Q1_NET_CENTS - 60001, (
            f"and the balance falls to 169087, got {clawback['account_balance_cents']}"
        )

        account = read_account(env.account_id)
        assert account["lifetime_clawed_back_cents"] == 60001, (
            f"the recovery counter carries the debit, got "
            f"{account['lifetime_clawed_back_cents']}"
        )
        assert account["lifetime_disbursed_cents"] == Q1_GROSS_CENTS, (
            f"the credit history is untouched, got "
            f"{account['lifetime_disbursed_cents']}"
        )
        assert account["lifetime_admin_fee_cents"] == Q1_ADMIN_FEE_CENTS, (
            f"as is the fee history, got {account['lifetime_admin_fee_cents']}"
        )
        assert_ledger_identity(account)

        entries, meta = validate_paginated(
            api.list_case_clawback_entries(env.misuse_case_id, PA)
        )
        assert meta["total_count"] == 1, (
            "a fully covered recovery appends the debit row alone, got "
            f"{meta['total_count']}"
        )
        assert entries[0]["entry_type"] == "ACCOUNT_DEBIT", (
            f"and that row is the debit, got {entries[0]['entry_type']!r}"
        )
        assert entries[0]["amount_cents"] == 60001, (
            f"carrying the full total, got {entries[0]['amount_cents']}"
        )


class TestReinstatementGate:
    """REINSTATE is guarded by every case on the account, not by the account alone."""

    def test_reinstatement_is_blocked_while_any_case_is_short_of_a_terminal_status(
        self, api
    ):
        """PRD §3.8: "The account must be `SUSPENDED`, **and** every misuse case naming this
        `account_id` must already be in `DISMISSED`, `RESOLVED`, or `REVERSED`; a single case
        still sitting in `OPEN`, `UNDER_REVIEW`, `SUBSTANTIATED`, `CLAWBACK_ISSUED`, or
        `UNDER_APPEAL` blocks reinstatement with `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/cross_entity_state_dependency/account_reinstatement_blocked_while_any_misuse_case_stays_open
        """
        env = setup_purchase_environment(quarters=1, provider_codes=("TUTORING",))
        env = setup_substantiated_case(
            env,
            case_overrides={
                "detection_rule": "NON_ALLOWABLE_EXPENSE",
                "disallowed_principal_cents": 100000,
            },
        )
        first_case_id = env.misuse_case_id
        assert read_account(env.account_id)["status"] == "SUSPENDED", (
            "the substantiation suspended the account"
        )

        second_case = open_misuse_case(
            env.account_id,
            detection_rule="PROVIDER_COLLUSION",
            disallowed_principal_cents=20000,
        )
        assert second_case["status"] == "OPEN", (
            f"a second case is opened and left open, got {second_case['status']!r}"
        )

        first_attempt = api.account_status_action(
            env.account_id,
            create_account_status_action_payload(
                "REINSTATE", "Household requested reinstatement."
            ),
            CO,
        )
        validate_error(first_attempt, ApiErrorId.INVALID_STATE_TRANSITION.value, 409)

        review_misuse_case(second_case["id"])
        dismissed = adjudicate_misuse_case(
            second_case["id"],
            "DISMISSED",
            rationale="Shared address explained by a co-located community centre.",
        )
        assert dismissed["status"] == "DISMISSED", (
            f"the second case is dismissed, got {dismissed['status']!r}"
        )

        second_attempt = api.account_status_action(
            env.account_id,
            create_account_status_action_payload(
                "REINSTATE", "Second attempt after dismissing the collusion case."
            ),
            CO,
        )
        validate_error(second_attempt, ApiErrorId.INVALID_STATE_TRANSITION.value, 409)

        account = read_account(env.account_id)
        assert account["status"] == "SUSPENDED", (
            "the gate is not merely an absence of OPEN cases: the first case still sits in "
            f"SUBSTANTIATED, got {account['status']!r}"
        )
        assert account["suspension_reason"] == MISUSE_SUBSTANTIATED, (
            f"and the suspension reason stands throughout, got "
            f"{account['suspension_reason']!r}"
        )
        assert account["balance_cents"] == Q1_NET_CENTS, (
            f"neither refused reinstatement moved money, got {account['balance_cents']}"
        )

        rows, meta = validate_paginated(
            api.list_misuse_cases(PA, params={"account_id": env.account_id})
        )
        assert meta["total_count"] == 2, (
            f"both cases point at this account, got {meta['total_count']}"
        )
        assert {row["id"]: row["status"] for row in rows} == {
            first_case_id: "SUBSTANTIATED",
            second_case["id"]: "DISMISSED",
        }, f"one substantiated and one dismissed, got {rows!r}"

    def test_reinstatement_succeeds_once_the_only_case_is_dismissed_and_revives_nothing(
        self, api
    ):
        """PRD §3.8: "On success `suspension_reason` is set back to null and the `version`
        rises by 1. Reinstatement does **not** revive the purchase requests the suspension
        voided; the guardian must file new ones."

        PRD §3.8: "`SUSPEND` moves the account `ACTIVE → SUSPENDED` — from any other state
        it is `ERR_INVALID_STATE_TRANSITION` — stores the `reason` as `suspension_reason`,
        and runs exactly the same void-and-release cascade the substantiation cascade runs"

        Design: Difficulty/cross_entity_state_dependency/account_reinstatement_blocked_while_any_misuse_case_stays_open
        """
        env = setup_purchase_environment(quarters=1, provider_codes=("TUTORING",))
        env = setup_approved_purchase_request(
            env, category_key="tutoring", amount_cents=FIRST_HOLD_CENTS
        )
        suspended = suspend_account(
            env.account_id, reason="Documentation audit in progress."
        )
        assert suspended["status"] == "SUSPENDED", (
            f"the officer suspended the account directly, got {suspended['status']!r}"
        )
        assert suspended["suspension_reason"] == "Documentation audit in progress.", (
            f"storing the supplied reason, got {suspended['suspension_reason']!r}"
        )
        assert read_purchase_request(env.purchase_request_id)["approval_status"] == "VOID", (
            "and the same void-and-release cascade ran"
        )

        case = open_misuse_case(
            env.account_id,
            detection_rule="FALSIFIED_ENROLLMENT",
            disallowed_principal_cents=30000,
        )
        blocked = api.account_status_action(
            env.account_id,
            create_account_status_action_payload(
                "REINSTATE", "Audit closed with no findings."
            ),
            CO,
        )
        validate_error(blocked, ApiErrorId.INVALID_STATE_TRANSITION.value, 409)
        assert read_account(env.account_id)["status"] == "SUSPENDED", (
            "one live case is enough to hold the account down"
        )

        review_misuse_case(case["id"])
        adjudicate_misuse_case(
            case["id"],
            "DISMISSED",
            rationale="The registrar confirmed the enrolment letter was genuine.",
        )
        before = read_account(env.account_id)

        reinstated = reinstate_account(env.account_id)
        assert reinstated["status"] == "ACTIVE", (
            "with every case terminal the same call now succeeds, got "
            f"{reinstated['status']!r}"
        )
        assert reinstated["suspension_reason"] is None, (
            f"and the reason is cleared, got {reinstated['suspension_reason']!r}"
        )
        assert reinstated["version"] == before["version"] + 1, (
            f"the account's version rose by 1, got {reinstated['version']}"
        )

        request = read_purchase_request(env.purchase_request_id)
        assert request["approval_status"] == "VOID", (
            f"the voided request is not revived, got {request['approval_status']!r}"
        )
        assert request["settlement_status"] == "CANCELLED", (
            f"nor is its money track reopened, got {request['settlement_status']!r}"
        )
        account = read_account(env.account_id)
        assert account["balance_cents"] == Q1_NET_CENTS, (
            f"the released hold stays released, got {account['balance_cents']}"
        )
        assert account["encumbered_cents"] == 0, (
            f"with nothing re-encumbered, got {account['encumbered_cents']}"
        )
        assert_ledger_identity(account)


class TestOverturnedClawbackRestoresTheLedger:
    """The reversal is an exact compensation that puts the identity back."""

    def test_an_overturned_appeal_restores_the_balance_and_the_money_identity(self, api):
        """PRD §3.9: "`CLAWBACK` moves the misuse case `UNDER_APPEAL → REVERSED`. A clawback
        entry with `entry_type` `REVERSAL` is appended whose `amount_cents` equals the case's
        `account_debit_cents`; the account's `balance_cents` rises by that same
        `account_debit_cents` and its `lifetime_clawed_back_cents` falls by the same amount,
        an exact compensation rather than a recomputation — the penalty is never re-derived
        at reversal time."

        PRD §3.9: "That reversal then moves the account `SUSPENDED → ACTIVE`, but only when
        no other misuse case on the account is still in `OPEN`, `UNDER_REVIEW`,
        `SUBSTANTIATED`, `CLAWBACK_ISSUED`, or `UNDER_APPEAL`."

        Design: Difficulty/compensating_invariant/overturned_clawback_appeal_restores_the_account_money_identity
        """
        env = setup_purchase_environment(quarters=1, provider_codes=("TUTORING",))
        env = setup_clawback_issued_case(
            env,
            case_overrides={
                "detection_rule": "FALSIFIED_ENROLLMENT",
                "disallowed_principal_cents": FIRST_HOLD_CENTS,
            },
        )
        case_before = read_misuse_case(env.misuse_case_id)
        assert case_before["clawback_total_cents"] == 180000, (
            f"the assessment totalled 180000, got {case_before['clawback_total_cents']}"
        )
        assert case_before["account_debit_cents"] == 180000, (
            f"all of it came out of the balance, got {case_before['account_debit_cents']}"
        )
        assert case_before["receivable_cents"] == 0, (
            f"leaving no receivable, got {case_before['receivable_cents']}"
        )
        account_before = read_account(env.account_id)
        assert account_before["balance_cents"] == Q1_NET_CENTS - 180000, (
            f"the balance stood at 49088, got {account_before['balance_cents']}"
        )

        appeal = file_clawback_appeal(env.misuse_case_id, env.student_id)
        assert read_misuse_case(env.misuse_case_id)["status"] == "UNDER_APPEAL", (
            "filing the appeal put the case under appeal"
        )

        decided = decide_appeal(
            appeal["id"],
            "OVERTURNED",
            "Corrected enrollment letter verified with the registrar.",
        )
        assert decided["status"] == "OVERTURNED", (
            f"the appeal is allowed, got {decided['status']!r}"
        )

        case = read_misuse_case(env.misuse_case_id)
        assert case["status"] == "REVERSED", (
            f"the case is reversed, got {case['status']!r}"
        )
        assert case["clawback_total_cents"] == 180000, (
            "and the assessment it recorded is still on the row rather than erased, got "
            f"{case['clawback_total_cents']}"
        )

        entries, meta = validate_paginated(
            api.list_case_clawback_entries(env.misuse_case_id, PA)
        )
        assert meta["total_count"] == 2, (
            f"the ledger is append-only, so two rows now exist, got {meta['total_count']}"
        )
        assert [entry["entry_type"] for entry in entries] == [
            "ACCOUNT_DEBIT",
            "REVERSAL",
        ], f"the debit first and its compensation after, got {entries!r}"
        assert entries[1]["amount_cents"] == 180000, (
            f"the reversal carries the debited amount, got {entries[1]['amount_cents']}"
        )

        account = read_account(env.account_id)
        assert account["balance_cents"] == Q1_NET_CENTS, (
            f"the pre-clawback balance is restored exactly, got "
            f"{account['balance_cents']}"
        )
        assert account["lifetime_clawed_back_cents"] == 0, (
            f"and the recovery counter returns to 0 with no drift, got "
            f"{account['lifetime_clawed_back_cents']}"
        )
        assert account["status"] == "ACTIVE", (
            f"the reversal reactivated the account, got {account['status']!r}"
        )
        assert account["suspension_reason"] is None, (
            f"clearing the suspension reason, got {account['suspension_reason']!r}"
        )
        assert (
            account["balance_cents"]
            + account["lifetime_spent_cents"]
            + account["lifetime_clawed_back_cents"]
            + account["lifetime_admin_fee_cents"]
            == account["lifetime_disbursed_cents"]
        ), f"and the money identity holds again, got {account!r}"
        assert account["lifetime_disbursed_cents"] == Q1_GROSS_CENTS, (
            f"against the 233168 ever credited, got "
            f"{account['lifetime_disbursed_cents']}"
        )
        assert_ledger_identity(account)

    def test_the_reversal_compensates_the_debit_rather_than_the_assessed_total(self, api):
        """PRD §3.9: "A clawback entry with `entry_type` `REVERSAL` is appended whose
        `amount_cents` equals the case's `account_debit_cents`"

        PRD §3.9: "The case's `receivable_cents` is set to 0."

        PRD §3.8: "Each entry records the `misuse_case_id` that produced it, the
        `account_id` it moves or records against, and `created_by_user_id` — the acting
        officer's `X-User-ID`, or the literal string `system` for a cascaded reversal."

        Design: Difficulty/compensating_invariant/overturned_clawback_appeal_restores_the_account_money_identity
        """
        env = setup_purchase_environment(quarters=1, provider_codes=("TUTORING",))
        env = setup_clawback_issued_case(
            env,
            case_overrides={
                "detection_rule": "CAP_CIRCUMVENTION",
                "disallowed_principal_cents": 250000,
            },
        )
        case_before = read_misuse_case(env.misuse_case_id)
        assert case_before["clawback_total_cents"] == 300000, (
            f"the total assessed was 300000, got {case_before['clawback_total_cents']}"
        )
        assert case_before["account_debit_cents"] == Q1_NET_CENTS, (
            "but only 229088 could be taken from the balance, got "
            f"{case_before['account_debit_cents']}"
        )
        assert case_before["receivable_cents"] == 300000 - Q1_NET_CENTS, (
            f"with 70912 booked as a receivable, got {case_before['receivable_cents']}"
        )
        assert read_account(env.account_id)["balance_cents"] == 0, (
            "and the balance drained to 0"
        )

        appeal = file_clawback_appeal(env.misuse_case_id, env.student_id)
        decide_appeal(
            appeal["id"],
            "OVERTURNED",
            "The two catalogue lines funded genuinely separate services.",
        )

        entries, meta = validate_paginated(
            api.list_case_clawback_entries(env.misuse_case_id, PA)
        )
        assert meta["total_count"] == 3, (
            f"the reversal is appended to the two assessment rows, got "
            f"{meta['total_count']}"
        )
        assert [entry["entry_type"] for entry in entries] == [
            "ACCOUNT_DEBIT",
            "RECEIVABLE",
            "REVERSAL",
        ], f"oldest first, so the reversal follows what it compensates, got {entries!r}"
        reversal = entries[2]
        assert reversal["amount_cents"] == Q1_NET_CENTS, (
            "the reversal compensates the 229088 actually debited, not the 300000 total, "
            f"got {reversal['amount_cents']}"
        )
        assert reversal["amount_cents"] != 300000, (
            "a recomputation from the assessed total would overpay the account"
        )
        assert reversal["created_by_user_id"] == "system", (
            f"and a cascaded reversal is booked by the system, got "
            f"{reversal['created_by_user_id']!r}"
        )
        assert reversal["account_id"] == env.account_id, (
            f"against the account it moves, got {reversal['account_id']!r}"
        )

        case = read_misuse_case(env.misuse_case_id)
        assert case["status"] == "REVERSED", (
            f"the case is reversed, got {case['status']!r}"
        )
        assert case["receivable_cents"] == 0, (
            f"and the receivable side is cleared, got {case['receivable_cents']}"
        )

        account = read_account(env.account_id)
        assert account["balance_cents"] == Q1_NET_CENTS, (
            f"the balance is back to 229088, got {account['balance_cents']}"
        )
        assert account["lifetime_clawed_back_cents"] == 0, (
            f"with nothing left recovered, got {account['lifetime_clawed_back_cents']}"
        )
        assert account["status"] == "ACTIVE", (
            f"and the account is active again, got {account['status']!r}"
        )
        assert_ledger_identity(account)
