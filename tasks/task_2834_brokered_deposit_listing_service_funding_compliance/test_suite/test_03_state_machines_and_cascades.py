"""Non-linear state machines and transitive cascades.

Two placement dimensions move independently of one another (PRD §3.5, §3.6) and
the counterparty diligence file combines a bounded revision cycle with a forked
approval (PRD §3.2).  Two cascades then run several hops past the record the
caller actually addressed: revoking a primary purpose exception reaches all the
way to a liquidity contingency plan (PRD §3.3, §3.7) and suspending an agreement
reaches all the way to a pending tranche (PRD §3.2, §3.4, §3.5).
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import COMPLIANCE, DESK, TREASURY

CORE_DEPOSITS_CENTS = 40_000_000_000
TOTAL_LIABILITIES_CENTS = 50_000_000_000
PRINCIPAL_CENTS = 2_000_000_000
PENDING_PRINCIPAL_CENTS = 1_000_000_000
RATE_BPS = 470


def _read_limit(institution_id: str, limit_id: str) -> dict:
    """The bank's board limit row identified by ``limit_id``."""
    limits, _meta = validate_paginated(
        api_client.list_concentration_limits(
            institution_id, TREASURY, params={"metric": "BROKERED_TO_TOTAL_DEPOSITS"}
        )
    )
    matches = [limit for limit in limits if limit["id"] == limit_id]
    assert len(matches) == 1, (
        f"exactly one limit row must carry id {limit_id}, got {len(matches)}"
    )
    return matches[0]


def _surveilled_placement_env() -> dict:
    """Capped bank, open brokered program at 470 bps and one PENDING tranche.

    The governing benchmark publishes 400 bps from 2026-07-01, so the ceiling as
    of 2026-08-01 is 400 + 75 == 475 bps and the tranche's 470 bps passes.
    """
    env = fx.setup_open_program(
        institution_overrides={
            "legal_name": "Two Dimension Bank NA",
            "capital_category": "ADEQUATELY_CAPITALIZED",
            "core_deposits_cents": CORE_DEPOSITS_CENTS,
            "total_liabilities_cents": TOTAL_LIABILITIES_CENTS,
        },
        broker_overrides={"legal_name": "Surveillance Brokers LLC"},
        program_overrides={
            "program_name": "Surveilled CD",
            "tenor_days": 60,
            "offered_rate_bps": RATE_BPS,
            "early_withdrawal_penalty_days": 90,
            "principal_erosion_allowed": True,
        },
    )
    env["placement"] = fx.book_placement(
        env["program"]["id"],
        DESK,
        principal_cents=PRINCIPAL_CENTS,
        rate_bps=RATE_BPS,
        issue_date="2026-08-01",
        tenor_days=60,
    )
    return env


def _agreement_at_rfi_round_limit() -> dict:
    """Counterparty with one agreement back in `UNDER_DILIGENCE` after both
    permitted request-for-information rounds have been travelled.

    The sub-scores 70/70/65/65 give a composite of
    (35*70 + 30*70 + 20*65 + 15*65) / 100 == 68.25, rounded half up to 68.
    """
    fx.set_clock()
    broker = fx.register_broker(legal_name="Fork Path Brokers LLC")
    agreement = fx.draft_agreement(
        broker["id"],
        DESK,
        aml_program_score=70,
        financial_condition_score=70,
        insurance_coverage_score=65,
        recordkeeping_score=65,
    )
    fx.diligence_action(agreement["id"], "START_DILIGENCE", COMPLIANCE)
    fx.diligence_action(agreement["id"], "ISSUE_RFI", COMPLIANCE, note="round 1 questions")
    fx.diligence_action(agreement["id"], "RESUME_DILIGENCE", COMPLIANCE)
    fx.diligence_action(agreement["id"], "ISSUE_RFI", COMPLIANCE, note="round 2 questions")
    agreement = fx.diligence_action(agreement["id"], "RESUME_DILIGENCE", COMPLIANCE)
    return {"broker": broker, "agreement": agreement}


def _revocation_env() -> dict:
    """The full four-hop staging: an ACKNOWLEDGED notice filing, an open program
    whose governing determination leans on it, one ACTIVE listing-service
    tranche, a board limit that breaches at 400 bps and an APPROVED plan.

    The bank is `WELL_CAPITALIZED`, so its regime is `EXEMPT` and no benchmark
    publication is needed for any of the calls below.
    """
    env = fx.setup_program_relying_on_exception(
        publish_benchmark=False,
        institution_overrides={
            "legal_name": "Cascade Bank NA",
            "capital_category": "WELL_CAPITALIZED",
            "core_deposits_cents": CORE_DEPOSITS_CENTS,
            "total_liabilities_cents": TOTAL_LIABILITIES_CENTS,
            "liquidity_buffer_cents": 100_000_000,
        },
        broker_overrides={
            "legal_name": "Cascade Listing Service Inc",
            "broker_type": "LISTING_SERVICE",
            "has_placement_discretion": True,
        },
        program_overrides={
            "program_name": "Sweep Listing Program",
            "funding_channel_claim": "LISTING_SERVICE",
            "tenor_days": 60,
            "offered_rate_bps": RATE_BPS,
        },
    )
    env["program"] = fx.attest_program(env["program"]["id"], DESK)
    env["limit"] = fx.create_concentration_limit(
        env["institution"]["id"],
        TREASURY,
        metric="BROKERED_TO_TOTAL_DEPOSITS",
        warning_threshold_bps=200,
        breach_threshold_bps=400,
    )
    placement = fx.book_placement(
        env["program"]["id"],
        DESK,
        principal_cents=PRINCIPAL_CENTS,
        rate_bps=RATE_BPS,
        issue_date="2026-08-01",
        tenor_days=60,
    )
    env["placement"] = fx.activate_placement(placement["id"], DESK)
    env["plan"] = fx.setup_approved_plan(
        env["institution"]["id"], plan_version_label="CFP-2026-H2"
    )
    env["institution"] = fx.read_institution(env["institution"]["id"])
    return env


def _suspension_chain_env() -> dict:
    """An APPROVED agreement underwriting one open program that carries one
    ACTIVE tranche of 2,000,000,000 cents and one PENDING tranche of
    1,000,000,000 cents, at a bank with no board limits at all."""
    env = fx.setup_open_program(
        publish_benchmark=False,
        institution_overrides={
            "legal_name": "Suspend Chain Bank NA",
            "capital_category": "WELL_CAPITALIZED",
            "core_deposits_cents": CORE_DEPOSITS_CENTS,
            "total_liabilities_cents": TOTAL_LIABILITIES_CENTS,
        },
        broker_overrides={"legal_name": "Suspend Chain Brokers LLC"},
        program_overrides={
            "program_name": "Suspend Chain CD",
            "tenor_days": 60,
            "offered_rate_bps": RATE_BPS,
        },
    )
    env["active_placement"] = fx.add_active_placement(
        env,
        {
            "principal_cents": PRINCIPAL_CENTS,
            "rate_bps": RATE_BPS,
            "issue_date": "2026-08-01",
            "tenor_days": 60,
        },
    )
    env["pending_placement"] = fx.book_placement(
        env["program"]["id"],
        DESK,
        principal_cents=PENDING_PRINCIPAL_CENTS,
        rate_bps=RATE_BPS,
        issue_date="2026-08-01",
        tenor_days=60,
    )
    env["institution"] = fx.read_institution(env["institution"]["id"])
    return env


class TestPlacementParallelStateDimensions:
    """One tranche, two state dimensions that advance on different triggers."""

    def test_a_passing_review_advances_only_the_compliance_dimension(self):
        """PRD §3.5: "`funding_status` tracks where the money is in its funding
        lifecycle and moves only on funding actions, on the maturity sweep, and
        on program or agreement cascades — never on a surveillance review."  And
        PRD §3.6:
        "An `UNREVIEWED` tranche whose review comes back `PASS` or
        `EXEMPT_NO_CAP` moves `UNREVIEWED → RATE_CHECKED`".

        The ceiling as of 2026-08-01 is the published 400 bps plus 75, so the
        tranche's 470 bps sits 5 bps under it and the review passes while the
        money itself has not moved at all.

        Design: Difficulty/non_linear_state_machine/placement_parallel_funding_and_compliance_dimensions
        """
        env = _surveilled_placement_env()
        placement_id = env["placement"]["id"]

        check = validate_success(
            api_client.create_rate_cap_check(
                placement_id, f.rate_cap_check_payload("2026-08-01"), COMPLIANCE
            ),
            expected_status=201,
        )
        asserts.assert_rate_cap_check(check)
        assert check["applied_tenor_bucket"] == "DAYS_31_90", (
            "applied_tenor_bucket is copied from the tranche's own bucket, "
            f"expected DAYS_31_90, got {check['applied_tenor_bucket']}"
        )
        assert check["national_rate_bps_snapshot"] == 400, (
            "the snapshot must hold the selected publication's 400 bps, got "
            f"{check['national_rate_bps_snapshot']}"
        )
        assert check["effective_cap_bps"] == 475, (
            "the ceiling is the national leg 400 + 75 == 475 bps, got "
            f"{check['effective_cap_bps']}"
        )
        assert check["breach_bps"] == 0, (
            f"470 bps is under the 475 bps ceiling, got breach_bps {check['breach_bps']}"
        )
        assert check["outcome"] == "PASS", (
            f"the outcome must be PASS, got {check['outcome']}"
        )

        placement = fx.read_placement(placement_id)
        assert placement["compliance_status"] == "RATE_CHECKED", (
            "the surveillance dimension must advance UNREVIEWED -> RATE_CHECKED, "
            f"got {placement['compliance_status']}"
        )
        assert placement["funding_status"] == "PENDING", (
            "funding_status never moves on a review, so the tranche must still "
            f"be PENDING, got {placement['funding_status']}"
        )

    def test_a_breach_flags_the_tranche_while_the_money_stays_active(self):
        """PRD §3.6: "A tranche already `RATE_CHECKED` or `REMEDIATED` whose
        review comes back `BREACH` moves to `FLAGGED`".  And: "`breach_bps` is
        the amount by which `offered_rate_bps` exceeds `effective_cap_bps`,
        floored at zero so it is never negative".

        A later publication of 300 bps effective 2026-08-05 is the one the
        selector picks for a 2026-08-10 review, dropping the ceiling to 375 bps,
        so the tranche's 470 bps breaches by 95 bps on the compliance dimension
        while the funding dimension holds at ACTIVE.

        Design: Difficulty/non_linear_state_machine/placement_parallel_funding_and_compliance_dimensions
        """
        env = _surveilled_placement_env()
        placement_id = env["placement"]["id"]

        fx.record_rate_cap_check(placement_id, "2026-08-01", COMPLIANCE)
        fx.activate_placement(placement_id, DESK)
        fx.publish_rate_cap(
            tenor_bucket="DAYS_31_90",
            published_national_rate_bps=300,
            effective_date="2026-08-05",
        )

        check = validate_success(
            api_client.create_rate_cap_check(
                placement_id, f.rate_cap_check_payload("2026-08-10"), COMPLIANCE
            ),
            expected_status=201,
        )
        assert check["effective_cap_bps"] == 375, (
            "the publication effective 2026-08-05 governs 2026-08-10, so the "
            f"ceiling is 300 + 75 == 375 bps, got {check['effective_cap_bps']}"
        )
        assert check["outcome"] == "BREACH", (
            f"470 bps over a 375 bps ceiling is a BREACH, got {check['outcome']}"
        )
        assert check["breach_bps"] == 95, (
            f"breach_bps must be 470 - 375 == 95, got {check['breach_bps']}"
        )

        placement = fx.read_placement(placement_id)
        assert placement["compliance_status"] == "FLAGGED", (
            "a RATE_CHECKED tranche whose review breaches moves to FLAGGED, got "
            f"{placement['compliance_status']}"
        )
        assert placement["funding_status"] == "ACTIVE", (
            "the funding dimension is untouched by surveillance, so the tranche "
            f"must still be ACTIVE, got {placement['funding_status']}"
        )

    def test_remediation_lands_after_the_funding_dimension_is_terminal(self):
        """PRD §3.5: "`MATURED`, `WITHDRAWN_EARLY`, `ROLLED_OVER` and `CANCELLED`
        are all terminal on the funding dimension."  And PRD §3.6: "A `FLAGGED`
        tranche whose review comes back `PASS` or `EXEMPT_NO_CAP` moves `FLAGGED
        → REMEDIATED`, with the appended review carrying a `breach_bps` of zero."
        And: "The cycle `FLAGGED → REMEDIATED → FLAGGED` therefore has no round
        limit and no terminal state: surveillance runs for as long as the tranche
        exists."

        The tranche walks PENDING -> ACTIVE -> WITHDRAWN_EARLY on the funding
        dimension while the compliance dimension walks UNREVIEWED ->
        RATE_CHECKED -> FLAGGED -> REMEDIATED, and the last surveillance step
        lands after the funding dimension has already stopped for good.  The
        2026-08-15 publication of 450 bps lifts the ceiling back to 525 bps for
        the 2026-09-01 review.

        Design: Difficulty/non_linear_state_machine/placement_parallel_funding_and_compliance_dimensions
        """
        env = _surveilled_placement_env()
        placement_id = env["placement"]["id"]

        fx.record_rate_cap_check(placement_id, "2026-08-01", COMPLIANCE)
        fx.activate_placement(placement_id, DESK)
        fx.publish_rate_cap(
            tenor_bucket="DAYS_31_90",
            published_national_rate_bps=300,
            effective_date="2026-08-05",
        )
        fx.record_rate_cap_check(placement_id, "2026-08-10", COMPLIANCE)
        withdrawn = fx.early_withdraw_placement(placement_id, "2026-08-25", DESK)
        assert withdrawn["funding_status"] == "WITHDRAWN_EARLY", (
            "the early withdrawal must move the funding dimension to its "
            f"terminal WITHDRAWN_EARLY, got {withdrawn['funding_status']}"
        )
        assert withdrawn["compliance_status"] == "FLAGGED", (
            "a funding action never moves the surveillance dimension, so the "
            f"tranche must still be FLAGGED, got {withdrawn['compliance_status']}"
        )

        fx.publish_rate_cap(
            tenor_bucket="DAYS_31_90",
            published_national_rate_bps=450,
            effective_date="2026-08-15",
        )
        check = validate_success(
            api_client.create_rate_cap_check(
                placement_id, f.rate_cap_check_payload("2026-09-01"), COMPLIANCE
            ),
            expected_status=201,
        )
        assert check["effective_cap_bps"] == 525, (
            "the publication effective 2026-08-15 is the latest on or before "
            f"2026-09-01, so the ceiling is 450 + 75 == 525 bps, got "
            f"{check['effective_cap_bps']}"
        )
        assert check["outcome"] == "PASS", (
            f"470 bps under a 525 bps ceiling passes, got {check['outcome']}"
        )
        assert check["breach_bps"] == 0, (
            f"the remediating review must carry breach_bps 0, got {check['breach_bps']}"
        )

        placement = fx.read_placement(placement_id)
        assert placement["compliance_status"] == "REMEDIATED", (
            "the surveillance dimension must move FLAGGED -> REMEDIATED even "
            f"though the money is gone, got {placement['compliance_status']}"
        )
        assert placement["funding_status"] == "WITHDRAWN_EARLY", (
            "the terminal funding status must be untouched by the review, got "
            f"{placement['funding_status']}"
        )
        assert placement["settlement_date"] == "2026-08-25", (
            "settlement_date is the supplied withdrawal_date, expected "
            f"2026-08-25, got {placement['settlement_date']}"
        )
        assert placement["accrued_interest_cents"] == 6_180_822, (
            "interest over the 24 days from 2026-08-01 to 2026-08-25 is "
            "2000000000 * 470 * 24 / 10000 / 365 rounded half up == 6180822, got "
            f"{placement['accrued_interest_cents']}"
        )
        assert placement["early_withdrawal_penalty_cents"] == 23_178_082, (
            "the contractual penalty is 2000000000 * 470 * 90 / 10000 / 365 "
            f"rounded half up == 23178082, got "
            f"{placement['early_withdrawal_penalty_cents']}"
        )
        assert placement["net_settlement_cents"] == 1_983_002_740, (
            "net settlement is 2000000000 + 6180822 - 23178082 == 1983002740, "
            f"got {placement['net_settlement_cents']}"
        )
        asserts.assert_net_settlement_arithmetic(placement)

        checks, _meta = validate_paginated(
            api_client.list_rate_cap_checks(placement_id, COMPLIANCE)
        )
        assert len(checks) == 3, (
            "surveillance is append-only, so all three reviews must survive, got "
            f"{len(checks)}"
        )


class TestBrokerAgreementDiligenceCycle:
    """A bounded revision cycle plus a forked approval on the same file."""

    def test_a_third_information_request_is_refused_at_the_round_ceiling(self):
        """PRD §3.2: "the round is admitted only while `rfi_round_count` is below
        the ceiling of two rounds, and a third attempt is refused with
        `ERR_REVIEW_ROUND_LIMIT`".  And: "so the cycle `UNDER_DILIGENCE →
        RFI_ISSUED → UNDER_DILIGENCE` can be travelled at most twice."

        Design: Difficulty/non_linear_state_machine/broker_agreement_rfi_cycle_and_approve_branch
        """
        env = _agreement_at_rfi_round_limit()
        agreement_id = env["agreement"]["id"]
        assert env["agreement"]["rfi_round_count"] == 2, (
            "both permitted rounds must already be spent, got "
            f"{env['agreement']['rfi_round_count']}"
        )

        response = api_client.diligence_action(
            agreement_id,
            f.diligence_action_payload("ISSUE_RFI", note="round 3 questions"),
            COMPLIANCE,
        )
        validate_error(response, ApiErrorId.ERR_REVIEW_ROUND_LIMIT.value)

        agreement = fx.read_agreement(agreement_id)
        assert agreement["rfi_round_count"] == 2, (
            "a refused round must not advance the counter, expected 2, got "
            f"{agreement['rfi_round_count']}"
        )
        assert agreement["status"] == "UNDER_DILIGENCE", (
            "the refused action must leave the agreement where it was, expected "
            f"UNDER_DILIGENCE, got {agreement['status']}"
        )

    def test_the_approve_trigger_forks_to_conditional_at_a_composite_of_68(self):
        """PRD §3.2: "Approval from `UNDER_DILIGENCE` is one action with two
        divergent destinations chosen by the score band, and both destinations
        carry the same shape of side effect."  And: "When the composite score is
        at least 60 but below 70 and `aml_program_score` is at least 60, the
        agreement becomes `CONDITIONAL`, the counterparty's `diligence_status`
        becomes `CONDITIONAL` and `approved_agreement_count` likewise increases
        by 1."

        Sub-scores 70/70/65/65 weight out to 6825 / 100 == 68.25, rounded half up
        to a composite of 68 -- inside the conditional band.

        Design: Difficulty/non_linear_state_machine/broker_agreement_rfi_cycle_and_approve_branch
        """
        env = _agreement_at_rfi_round_limit()
        broker_id = env["broker"]["id"]

        approved = validate_success(
            api_client.diligence_action(
                env["agreement"]["id"], f.diligence_action_payload("APPROVE"), COMPLIANCE
            )
        )
        assert approved["diligence_score"] == 68, (
            "the composite must be 68, got " f"{approved['diligence_score']}"
        )
        assert approved["status"] == "CONDITIONAL", (
            "a composite of 68 takes the conditional fork, expected CONDITIONAL, "
            f"got {approved['status']}"
        )

        broker = fx.read_broker(broker_id)
        assert broker["diligence_status"] == "CONDITIONAL", (
            "the counterparty mirrors its governing agreement, expected "
            f"CONDITIONAL, got {broker['diligence_status']}"
        )
        assert broker["approved_agreement_count"] == 1, (
            "the conditional branch likewise increases the count by 1, got "
            f"{broker['approved_agreement_count']}"
        )

    def test_the_same_trigger_forks_to_approved_at_a_composite_of_74(self):
        """PRD §3.2: "When the composite score is at least 70 and
        `aml_program_score` is at least 60, the agreement becomes `APPROVED`, the
        counterparty's `diligence_status` becomes `APPROVED` and
        `approved_agreement_count` increases by 1."

        Sub-scores 80/75/70/65 weight out to 7425 / 100 == 74.25, rounded half up
        to a composite of 74, so the very same APPROVE action that landed the
        first agreement in CONDITIONAL lands this one in APPROVED and the
        counterparty now counts two live files.

        Design: Difficulty/non_linear_state_machine/broker_agreement_rfi_cycle_and_approve_branch
        """
        env = _agreement_at_rfi_round_limit()
        broker_id = env["broker"]["id"]
        fx.diligence_action(env["agreement"]["id"], "APPROVE", COMPLIANCE)

        high = fx.draft_agreement(
            broker_id,
            DESK,
            aml_program_score=80,
            financial_condition_score=75,
            insurance_coverage_score=70,
            recordkeeping_score=65,
        )
        fx.diligence_action(high["id"], "START_DILIGENCE", COMPLIANCE)
        approved = validate_success(
            api_client.diligence_action(
                high["id"], f.diligence_action_payload("APPROVE"), COMPLIANCE
            )
        )
        assert approved["diligence_score"] == 74, (
            f"the composite must be 74, got {approved['diligence_score']}"
        )
        assert approved["status"] == "APPROVED", (
            "a composite of 74 takes the approved fork, expected APPROVED, got "
            f"{approved['status']}"
        )

        broker = fx.read_broker(broker_id)
        assert broker["diligence_status"] == "APPROVED", (
            "the counterparty mirrors the agreement just approved, expected "
            f"APPROVED, got {broker['diligence_status']}"
        )
        assert broker["approved_agreement_count"] == 2, (
            "one conditional file plus one approved file must count 2, got "
            f"{broker['approved_agreement_count']}"
        )

    def test_suspension_then_resumption_re_enters_the_cycle_mid_stream(self):
        """PRD §3.2: "Suspending an agreement is permitted from either `APPROVED`
        or `CONDITIONAL`, and both produce an identical three-hop cascade."  And:
        "A suspended agreement can be brought back: resuming diligence moves it
        `SUSPENDED → UNDER_DILIGENCE`, recomputes the composite score and sets the
        counterparty's `diligence_status` back to `IN_DILIGENCE`, which is how the
        cycle `APPROVED → SUSPENDED → UNDER_DILIGENCE → APPROVED` is travelled."

        The same RESUME_DILIGENCE trigger that closes an information-request loop
        also re-enters diligence from SUSPENDED, and the approval that follows
        forks by score exactly as the first one did.

        Design: Difficulty/non_linear_state_machine/broker_agreement_rfi_cycle_and_approve_branch
        """
        env = _agreement_at_rfi_round_limit()
        agreement_id = env["agreement"]["id"]
        broker_id = env["broker"]["id"]
        fx.diligence_action(agreement_id, "APPROVE", COMPLIANCE)

        suspended = validate_success(
            api_client.diligence_action(
                agreement_id,
                f.diligence_action_payload(
                    "SUSPEND", note="adverse AML finding at the counterparty"
                ),
                COMPLIANCE,
            )
        )
        assert suspended["status"] == "SUSPENDED", (
            f"the first hop must suspend the agreement, got {suspended['status']}"
        )
        broker = fx.read_broker(broker_id)
        assert broker["diligence_status"] == "SUSPENDED", (
            "the second hop mirrors the suspension onto the counterparty, got "
            f"{broker['diligence_status']}"
        )
        assert broker["approved_agreement_count"] == 0, (
            "the second hop decrements the count by 1, expected 0, got "
            f"{broker['approved_agreement_count']}"
        )

        resumed = validate_success(
            api_client.diligence_action(
                agreement_id, f.diligence_action_payload("RESUME_DILIGENCE"), COMPLIANCE
            )
        )
        assert resumed["status"] == "UNDER_DILIGENCE", (
            "resuming diligence must re-enter UNDER_DILIGENCE from SUSPENDED, got "
            f"{resumed['status']}"
        )
        assert resumed["diligence_score"] == 68, (
            "the composite is recomputed on every entry into diligence, expected "
            f"68, got {resumed['diligence_score']}"
        )
        broker = fx.read_broker(broker_id)
        assert broker["diligence_status"] == "IN_DILIGENCE", (
            "the counterparty goes back to IN_DILIGENCE, got "
            f"{broker['diligence_status']}"
        )

        reapproved = validate_success(
            api_client.diligence_action(
                agreement_id, f.diligence_action_payload("APPROVE"), COMPLIANCE
            )
        )
        assert reapproved["status"] == "CONDITIONAL", (
            "the second approval forks on the same composite of 68, expected "
            f"CONDITIONAL, got {reapproved['status']}"
        )
        broker = fx.read_broker(broker_id)
        assert broker["approved_agreement_count"] == 1, (
            "the re-approval restores the count to 1, got "
            f"{broker['approved_agreement_count']}"
        )


REVOKE_PAYLOAD = {
    "action": "REVOKE",
    "note": "designated business line no longer qualifies",
}


class TestExceptionRevocationCascade:
    """One REVOKE call, four hops of consequences."""

    def test_hop_one_revokes_the_filing_and_nulls_its_reporting_deadline(self):
        """PRD §3.3: "The cascade runs four hops deep. Hop one sets the filing's
        own status to `REVOKED` and nulls `reporting_due_date`."  And PRD §2.11:
        "`reliant_program_count` on an exception filing equals the number of
        programs whose `governing_classification_id` names a determination whose
        `relied_exception_id` is that filing".

        Design: Difficulty/transitive_cascade/exception_revoke_four_hop_to_contingency_activation
        """
        env = _revocation_env()
        exception = fx.read_exception(env["exception"]["id"])
        assert exception["status"] == "ACKNOWLEDGED", (
            "the notice must be ACKNOWLEDGED before the revocation, got "
            f"{exception['status']}"
        )
        assert exception["reliant_program_count"] == 1, (
            "one program's governing determination leans on the filing, so the "
            f"count must be 1, got {exception['reliant_program_count']}"
        )
        assert exception["reporting_due_date"] is not None, (
            "an acknowledged notice carries a periodic reporting deadline, got null"
        )

        revoked = validate_success(
            api_client.exception_review_action(
                exception["id"], dict(REVOKE_PAYLOAD), COMPLIANCE
            )
        )
        assert revoked["status"] == "REVOKED", (
            f"hop one must set the filing's status to REVOKED, got {revoked['status']}"
        )
        assert revoked["reporting_due_date"] is None, (
            "hop one nulls reporting_due_date, got "
            f"{revoked['reporting_due_date']}"
        )

    def test_hop_two_drops_the_reliant_program_to_reclassification_pending(self):
        """PRD §3.3: "Hop two, caused by hop one, walks every program whose
        `governing_classification_id` names a determination whose
        `relied_exception_id` is this filing and whose `state` is `CLASSIFIED` or
        `OPEN_FOR_PLACEMENT`, moves each to `RECLASSIFICATION_PENDING` in program
        `created_at` ascending order, and resets `reliant_program_count` to 0."
        And PRD §2.5: "Each of those is written once and never edited — a
        correction to a published benchmark is a new publication with a later
        `effective_date`, a correction to a classification is a new determination
        that supersedes the prior one, and a correction to a rate-cap review is
        simply a later review."

        Design: Difficulty/transitive_cascade/exception_revoke_four_hop_to_contingency_activation
        """
        env = _revocation_env()
        program_id = env["program"]["id"]
        determination = env["classification"]
        assert env["program"]["state"] == "OPEN_FOR_PLACEMENT", (
            "the program must be open before the revocation, got "
            f"{env['program']['state']}"
        )

        validate_success(
            api_client.exception_review_action(
                env["exception"]["id"], dict(REVOKE_PAYLOAD), COMPLIANCE
            )
        )

        program = fx.read_program(program_id)
        assert program["state"] == "RECLASSIFICATION_PENDING", (
            "hop two must move the reliant program to RECLASSIFICATION_PENDING, "
            f"got {program['state']}"
        )
        exception = fx.read_exception(env["exception"]["id"])
        assert exception["reliant_program_count"] == 0, (
            "hop two resets reliant_program_count to 0, got "
            f"{exception['reliant_program_count']}"
        )

        after = fx.read_classification(determination["id"])
        asserts.assert_deposit_classification(after)
        assert after["determined_class"] == "LISTING_SERVICE_NON_BROKERED", (
            "the superseded determination keeps the class it recorded, expected "
            f"LISTING_SERVICE_NON_BROKERED, got {after['determined_class']}"
        )
        for field, value in determination.items():
            assert after[field] == value, (
                "a determination is written once and never edited, but "
                f"{field} moved from {value} to {after[field]}"
            )

    def test_hop_three_flags_the_tranche_and_re_buckets_it_as_brokered(self):
        """PRD §3.3: "Hop three, caused by hop two, walks the placements of each
        program just moved: every placement whose `funding_status` is `ACTIVE` has
        its `compliance_status` set to `FLAGGED` and its `classified_as` set to
        `BROKERED`, since the reliance that carried it out of the brokered class
        has been withdrawn, processed in placement `created_at` ascending order;
        the bank's balance rollup then re-runs over the new classes."

        The 2,000,000,000-cent tranche moves from the listing bucket to the
        brokered bucket, so total_deposits_cents and the headline ratio of
        2000000000 * 10000 // 42000000000 == 476 bps are unchanged while the
        composition underneath them is not.

        Design: Difficulty/transitive_cascade/exception_revoke_four_hop_to_contingency_activation
        """
        env = _revocation_env()
        placement_id = env["placement"]["id"]
        institution_id = env["institution"]["id"]
        assert env["placement"]["classified_as"] == "LISTING_SERVICE_NON_BROKERED", (
            "the tranche must start in the listing class, got "
            f"{env['placement']['classified_as']}"
        )
        assert env["institution"]["listing_service_deposits_cents"] == PRINCIPAL_CENTS, (
            "the listing bucket must hold the tranche before the revocation, got "
            f"{env['institution']['listing_service_deposits_cents']}"
        )

        validate_success(
            api_client.exception_review_action(
                env["exception"]["id"], dict(REVOKE_PAYLOAD), COMPLIANCE
            )
        )

        placement = fx.read_placement(placement_id)
        assert placement["compliance_status"] == "FLAGGED", (
            f"hop three flags the ACTIVE tranche, got {placement['compliance_status']}"
        )
        assert placement["classified_as"] == "BROKERED", (
            "hop three re-classes the tranche as BROKERED, got "
            f"{placement['classified_as']}"
        )
        assert placement["funding_status"] == "ACTIVE", (
            "hop three moves no money, so the tranche must stay ACTIVE, got "
            f"{placement['funding_status']}"
        )

        institution = fx.read_institution(institution_id)
        assert institution["brokered_deposits_cents"] == PRINCIPAL_CENTS, (
            "the brokered bucket must now hold the tranche, expected "
            f"{PRINCIPAL_CENTS}, got {institution['brokered_deposits_cents']}"
        )
        assert institution["listing_service_deposits_cents"] == 0, (
            "the listing bucket must be empty, got "
            f"{institution['listing_service_deposits_cents']}"
        )
        assert institution["total_deposits_cents"] == 42_000_000_000, (
            "moving money between wholesale buckets cannot change "
            f"total_deposits_cents, expected 42000000000, got "
            f"{institution['total_deposits_cents']}"
        )
        assert institution["wholesale_funding_ratio_bps"] == 476, (
            "the headline ratio must still be 2000000000 * 10000 // 42000000000 "
            f"== 476 bps, got {institution['wholesale_funding_ratio_bps']}"
        )
        asserts.assert_wholesale_buckets_match_active_placements(institution, [placement])
        asserts.assert_institution_invariants(institution)

    def test_hop_four_freezes_the_bank_and_auto_activates_the_approved_plan(self):
        """PRD §3.3: "Hop four, caused by hop three's balance movement, re-runs
        the concentration posture, and if the bank's `concentration_posture` comes
        out as `FROZEN`, every contingency plan of that bank whose `status` is
        `APPROVED` moves to `ACTIVATED` and has its `activation_stage` selected by
        the stage rule in §3.7."  And PRD §3.7: "`required_buffer_cents` is the
        maturing-soon amount multiplied by that multiplier and divided by 10000,
        with the single final quotient rounded half up to whole cents, and
        `buffer_shortfall_cents` is the amount by which `required_buffer_cents`
        exceeds the bank's `liquidity_buffer_cents`, floored at zero."

        At 476 bps the brokered metric is at or above the limit's 400 bps breach
        level, so the bank freezes and the plan activates at STAGE_1_MONITOR,
        which covers a quarter of the 2,000,000,000-cent maturity wall:
        2000000000 * 2500 / 10000 == 500000000 required against a
        100,000,000-cent buffer, a shortfall of 400000000.

        Design: Difficulty/transitive_cascade/exception_revoke_four_hop_to_contingency_activation
        """
        env = _revocation_env()
        institution_id = env["institution"]["id"]
        limit_id = env["limit"]["id"]
        plan_id = env["plan"]["id"]
        assert env["institution"]["concentration_posture"] == "OPEN", (
            "the bank must be OPEN before the revocation, got "
            f"{env['institution']['concentration_posture']}"
        )
        assert env["plan"]["status"] == "APPROVED", (
            f"the plan must be APPROVED and not yet activated, got {env['plan']['status']}"
        )

        validate_success(
            api_client.exception_review_action(
                env["exception"]["id"], dict(REVOKE_PAYLOAD), COMPLIANCE
            )
        )

        limit = _read_limit(institution_id, limit_id)
        assert limit["current_value_bps"] == 476, (
            "the brokered metric must be re-evaluated at 476 bps, got "
            f"{limit['current_value_bps']}"
        )
        assert limit["breach_state"] == "BREACH", (
            "476 bps is at or above the 400 bps breach threshold, so the state "
            f"must be BREACH, got {limit['breach_state']}"
        )

        institution = fx.read_institution(institution_id)
        assert institution["concentration_posture"] == "FROZEN", (
            "one breached ACTIVE limit freezes the bank, got "
            f"{institution['concentration_posture']}"
        )
        assert institution["breached_metric_count"] == 1, (
            "exactly one ACTIVE limit is in breach, got "
            f"{institution['breached_metric_count']}"
        )

        plan = fx.read_plan(plan_id)
        asserts.assert_contingency_plan(plan)
        assert plan["status"] == "ACTIVATED", (
            "hop four activates every APPROVED plan of the frozen bank, got "
            f"{plan['status']}"
        )
        assert plan["activation_stage"] == "STAGE_1_MONITOR", (
            "476 bps clears the 300 bps stage-1 trigger but not the 1000 bps "
            f"stage-2 trigger, expected STAGE_1_MONITOR, got {plan['activation_stage']}"
        )
        assert plan["required_buffer_cents"] == 500_000_000, (
            "a quarter of the 2000000000-cent maturity wall is 500000000, got "
            f"{plan['required_buffer_cents']}"
        )
        assert plan["buffer_shortfall_cents"] == 400_000_000, (
            "500000000 required less the 100000000-cent buffer is 400000000, got "
            f"{plan['buffer_shortfall_cents']}"
        )


SUSPEND_PAYLOAD = {
    "action": "SUSPEND",
    "note": "adverse AML finding at the counterparty",
}


class TestAgreementSuspensionCascade:
    """One SUSPEND call on the diligence file, three hops into the funding book."""

    def test_hop_one_suspends_the_agreement_itself(self):
        """PRD §3.2: "Suspending an agreement is permitted from either `APPROVED`
        or `CONDITIONAL`, and both produce an identical three-hop cascade. The
        first hop moves the agreement's own `status` to `SUSPENDED`."

        Design: Difficulty/transitive_cascade/agreement_suspend_three_hop_to_pending_placement_cancel
        """
        env = _suspension_chain_env()
        assert env["agreement"]["status"] == "APPROVED", (
            "the cascade must start from an APPROVED file, got "
            f"{env['agreement']['status']}"
        )

        suspended = validate_success(
            api_client.diligence_action(
                env["agreement"]["id"], dict(SUSPEND_PAYLOAD), COMPLIANCE
            )
        )
        assert suspended["status"] == "SUSPENDED", (
            f"hop one must move the agreement to SUSPENDED, got {suspended['status']}"
        )

    def test_hop_two_mirrors_the_suspension_onto_the_counterparty(self):
        """PRD §3.2: "The second hop, caused by the first, sets the counterparty's
        `diligence_status` to `SUSPENDED` and decrements `approved_agreement_count`
        by 1."

        Design: Difficulty/transitive_cascade/agreement_suspend_three_hop_to_pending_placement_cancel
        """
        env = _suspension_chain_env()
        broker_id = env["broker"]["id"]
        before = fx.read_broker(broker_id)
        assert before["approved_agreement_count"] == 1, (
            "one approved agreement must be counted before the suspension, got "
            f"{before['approved_agreement_count']}"
        )

        validate_success(
            api_client.diligence_action(
                env["agreement"]["id"], dict(SUSPEND_PAYLOAD), COMPLIANCE
            )
        )

        broker = fx.read_broker(broker_id)
        assert broker["diligence_status"] == "SUSPENDED", (
            "hop two mirrors the status onto the counterparty, got "
            f"{broker['diligence_status']}"
        )
        assert broker["approved_agreement_count"] == 0, (
            "hop two decrements the count by 1, expected 0, got "
            f"{broker['approved_agreement_count']}"
        )

    def test_hop_three_suspends_the_program_and_cancels_only_pending_money(self):
        """PRD §3.2: "The third hop, caused by the counterparty's suspension,
        walks every program underwritten by that agreement whose `state` is
        `CLASSIFIED` or `OPEN_FOR_PLACEMENT` and moves it to `SUSPENDED`, in
        program `created_at` ascending order, and for each such program moves
        every placement whose `funding_status` is `PENDING` to `CANCELLED`, in
        placement `created_at` ascending order."  And PRD §3.5: "Cancellation
        moves a tranche `PENDING → CANCELLED` and moves no money whatsoever,
        because a `PENDING` tranche has never entered any wholesale bucket."

        Design: Difficulty/transitive_cascade/agreement_suspend_three_hop_to_pending_placement_cancel
        """
        env = _suspension_chain_env()
        institution_id = env["institution"]["id"]
        program_id = env["program"]["id"]

        validate_success(
            api_client.diligence_action(
                env["agreement"]["id"], dict(SUSPEND_PAYLOAD), COMPLIANCE
            )
        )

        program = fx.read_program(program_id)
        assert program["state"] == "SUSPENDED", (
            f"hop three must suspend the open program, got {program['state']}"
        )
        assert program["outstanding_principal_cents"] == PRINCIPAL_CENTS, (
            "only the ACTIVE tranche stands behind outstanding principal, "
            f"expected {PRINCIPAL_CENTS}, got {program['outstanding_principal_cents']}"
        )

        pending = fx.read_placement(env["pending_placement"]["id"])
        assert pending["funding_status"] == "CANCELLED", (
            "hop three cancels the PENDING tranche, got "
            f"{pending['funding_status']}"
        )
        active = fx.read_placement(env["active_placement"]["id"])
        assert active["funding_status"] == "ACTIVE", (
            "an ACTIVE tranche is never cancelled by the cascade, got "
            f"{active['funding_status']}"
        )

        institution = fx.read_institution(institution_id)
        assert institution["brokered_deposits_cents"] == PRINCIPAL_CENTS, (
            "cancelling a PENDING tranche moves no money, so the brokered bucket "
            f"must still be {PRINCIPAL_CENTS}, got "
            f"{institution['brokered_deposits_cents']}"
        )
        assert institution["total_deposits_cents"] == 42_000_000_000, (
            "total_deposits_cents must be unchanged at 42000000000, got "
            f"{institution['total_deposits_cents']}"
        )
        assert institution["concentration_posture"] == "OPEN", (
            "with no board limits at all the posture stays OPEN, got "
            f"{institution['concentration_posture']}"
        )
        assert institution["breached_metric_count"] == 0, (
            "no ACTIVE limit exists to breach, got "
            f"{institution['breached_metric_count']}"
        )
        asserts.assert_wholesale_buckets_match_active_placements(
            institution, [active, pending]
        )
