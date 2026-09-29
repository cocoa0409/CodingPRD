"""Cross-entity gates, temporal occupancy and compensating invariants.

Three families of rule are exercised here.  First, the gates where one record's
state decides whether a write against a *different* record is admitted at all:
the counterparty file gating program creation (PRD §3.4), the exception filing
gating a classification determination (PRD §3.4), and an open examination
freezing the bank it points at (PRD §3.9).  Second, the two opposite interval
semantics the system uses: exclusive occupancy of a contingency plan's closed
coverage window (PRD §3.7) against the buffered aggregate capacity of the
maturity ladder (PRD §3.5).  Third, the conserved quantities of PRD §2.11 —
the wholesale buckets under an activation followed by its compensating early
withdrawal, and an exception filing's reliance count under a classification
followed by a reclassification that drops the reliance.
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
from test_helpers.test_users import ADMIN, COMPLIANCE, DESK, EXAMINER, TREASURY


def _list_programs(**params) -> tuple:
    return validate_paginated(api_client.list_programs(ADMIN, params=params))


def _list_classifications(**params) -> tuple:
    return validate_paginated(api_client.list_classifications(ADMIN, params=params))


def _list_placements(**params) -> tuple:
    return validate_paginated(api_client.list_placements(ADMIN, params=params))


def _list_plans(institution_id, **params) -> tuple:
    return validate_paginated(
        api_client.list_contingency_plans(institution_id, TREASURY, params=params)
    )


def _active_limit(institution_id) -> dict:
    limits, _ = validate_paginated(
        api_client.list_concentration_limits(
            institution_id, TREASURY, params={"status": "ACTIVE"}
        )
    )
    assert len(limits) == 1, (
        f"exactly one ACTIVE board limit was created, got {len(limits)}"
    )
    return limits[0]


def _setup_bank_with_draft_agreement() -> dict:
    """One bank, one deposit broker and one agreement still sitting in DRAFT.

    The sub-scores 80/75/70/65 give a composite of 74, so a later approval lands
    in APPROVED rather than CONDITIONAL.
    """
    env = fx.setup_bank(institution_overrides={"legal_name": "Gate Bank NA"})
    env["broker"] = fx.register_broker(legal_name="Gate Deposit Brokers LLC")
    env["agreement"] = fx.draft_agreement(env["broker"]["id"], DESK)
    return env


def _brokered_program_payload(env: dict, program_name: str) -> dict:
    """The same program payload every attempt below sends, differing only in name."""
    return f.program_payload(
        env["institution"]["id"],
        broker_id=env["broker"]["id"],
        agreement_id=env["agreement"]["id"],
        program_name=program_name,
        funding_channel_claim="BROKERED",
    )


class TestProgramCreationGatedOnBrokerAgreementStatus:
    """A program may not be raised through a counterparty file that has not
    cleared underwriting, and the identical request is admitted once it has."""

    def test_program_create_is_refused_while_the_agreement_is_draft(self):
        """PRD §3.4: "Where a counterparty is named, both the agreement's `status`
        and the counterparty's `diligence_status` must be `APPROVED` or
        `CONDITIONAL`; a `DRAFT`, `SUSPENDED`, `REJECTED` or `TERMINATED` file
        cannot underwrite new funding and the attempt is refused with
        `ERR_AGREEMENT_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/program_creation_gated_on_broker_agreement_status
        """
        env = _setup_bank_with_draft_agreement()
        assert env["agreement"]["status"] == "DRAFT", (
            "a freshly drafted agreement sits in DRAFT, got "
            f"{env['agreement']['status']}"
        )

        resp = api_client.create_program(
            _brokered_program_payload(env, "Gate CD Draft Attempt"), DESK
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_APPROVED.value)

        programs, meta = _list_programs(institution_id=env["institution"]["id"])
        assert meta["total_count"] == 0, (
            "the refused attempt must persist nothing, but the bank now lists "
            f"{meta['total_count']} programs"
        )
        assert programs == [], "no program record may survive a refused create"

    def test_program_create_is_refused_while_the_agreement_is_under_diligence(self):
        """PRD §3.4: "Where a counterparty is named, both the agreement's `status`
        and the counterparty's `diligence_status` must be `APPROVED` or
        `CONDITIONAL`; a `DRAFT`, `SUSPENDED`, `REJECTED` or `TERMINATED` file
        cannot underwrite new funding and the attempt is refused with
        `ERR_AGREEMENT_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/program_creation_gated_on_broker_agreement_status
        """
        env = _setup_bank_with_draft_agreement()
        agreement = fx.diligence_action(
            env["agreement"]["id"], "START_DILIGENCE", COMPLIANCE
        )
        asserts.assert_broker_agreement(agreement)
        assert agreement["status"] == "UNDER_DILIGENCE", (
            f"START_DILIGENCE moves the file to UNDER_DILIGENCE, got {agreement['status']}"
        )
        assert agreement["diligence_score"] == 74, (
            "the sub-scores 80/75/70/65 give a composite of 74, got "
            f"{agreement['diligence_score']}"
        )
        broker = fx.read_broker(env["broker"]["id"])
        assert broker["diligence_status"] == "IN_DILIGENCE", (
            "the counterparty tracks the open review as IN_DILIGENCE, got "
            f"{broker['diligence_status']}"
        )

        resp = api_client.create_program(
            _brokered_program_payload(env, "Gate CD Diligence Attempt"), DESK
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_APPROVED.value)

        _, meta = _list_programs(institution_id=env["institution"]["id"])
        assert meta["total_count"] == 0, (
            "an UNDER_DILIGENCE file underwrites nothing, so no program may exist; "
            f"got total_count {meta['total_count']}"
        )

    def test_the_same_program_create_succeeds_once_the_agreement_is_approved(self):
        """PRD §3.2: "When the composite score is at least 70 and
        `aml_program_score` is at least 60, the agreement becomes `APPROVED`, the
        counterparty's `diligence_status` becomes `APPROVED` and
        `approved_agreement_count` increases by 1."

        PRD §3.4: "A new program lands in `PENDING_CLASSIFICATION` with
        `governing_classification_id` null, `outstanding_principal_cents` at 0,
        `prepared_by_user_id` stamped from the opening officer's identifier and
        `attested_by_user_id` null."

        Design: Difficulty/cross_entity_state_dependency/program_creation_gated_on_broker_agreement_status
        """
        env = _setup_bank_with_draft_agreement()
        validate_error(
            api_client.create_program(
                _brokered_program_payload(env, "Gate CD Draft Attempt"), DESK
            ),
            ApiErrorId.ERR_AGREEMENT_NOT_APPROVED.value,
        )
        fx.diligence_action(env["agreement"]["id"], "START_DILIGENCE", COMPLIANCE)
        validate_error(
            api_client.create_program(
                _brokered_program_payload(env, "Gate CD Diligence Attempt"), DESK
            ),
            ApiErrorId.ERR_AGREEMENT_NOT_APPROVED.value,
        )

        agreement = fx.diligence_action(env["agreement"]["id"], "APPROVE", COMPLIANCE)
        assert agreement["status"] == "APPROVED", (
            f"a composite of 74 clears the floor of 70, got {agreement['status']}"
        )
        broker = fx.read_broker(env["broker"]["id"])
        assert broker["diligence_status"] == "APPROVED", (
            "the counterparty's diligence_status follows the agreement to APPROVED, "
            f"got {broker['diligence_status']}"
        )
        assert broker["approved_agreement_count"] == 1, (
            "approved_agreement_count increases by 1 on approval, got "
            f"{broker['approved_agreement_count']}"
        )

        program = validate_success(
            api_client.create_program(
                _brokered_program_payload(env, "Gate CD Approved Attempt"), DESK
            ),
            expected_status=201,
        )
        asserts.assert_deposit_program(program)
        assert program["state"] == "PENDING_CLASSIFICATION", (
            f"a new program lands in PENDING_CLASSIFICATION, got {program['state']}"
        )
        assert program["version"] == 1, (
            f"a newly created program is at version 1, got {program['version']}"
        )
        assert program["governing_classification_id"] is None, (
            "governing_classification_id starts null, got "
            f"{program['governing_classification_id']}"
        )
        assert program["outstanding_principal_cents"] == 0, (
            "outstanding_principal_cents starts at 0, got "
            f"{program['outstanding_principal_cents']}"
        )
        assert program["attested_by_user_id"] is None, (
            f"attested_by_user_id starts null, got {program['attested_by_user_id']}"
        )

        _, meta = _list_programs(institution_id=env["institution"]["id"])
        assert meta["total_count"] == 1, (
            "only the third attempt persisted a program, so total_count must be 1; "
            f"got {meta['total_count']}"
        )


def _setup_listing_program_with_draft_exception() -> dict:
    """A listing service that *does* hold placement discretion, an APPROVED
    agreement, a PENDING_CLASSIFICATION program under it, and a qualifying
    twenty-five-percent notice left in DRAFT."""
    env = fx.setup_bank(institution_overrides={"legal_name": "Reliance Bank NA"})
    env.update(
        fx.setup_approved_agreement(
            broker_overrides={
                "legal_name": "Reliance Listing Services LLC",
                "broker_type": "LISTING_SERVICE",
                "has_placement_discretion": True,
            }
        )
    )
    env["program"] = fx.open_program(
        env["institution"]["id"],
        DESK,
        broker_id=env["broker"]["id"],
        agreement_id=env["agreement"]["id"],
        program_name="Reliance Sweep MMDA",
        funding_channel_claim="LISTING_SERVICE",
        product_type="MONEY_MARKET",
        tenor_days=0,
        offered_rate_bps=420,
        early_withdrawal_penalty_days=0,
    )
    env["exception"] = fx.file_exception(
        env["broker"]["id"],
        env["institution"]["id"],
        DESK,
        designated_business_line="advisory cash sweep",
        total_customer_assets_cents=40_000_000_000,
        deposits_placed_at_ifs_cents=4_000_000_000,
    )
    return env


class TestClassificationGatedOnReliedExceptionStatus:
    """The relied filing's own status both gates the determination and decides
    which branch of the decision tree fires."""

    def test_determination_naming_a_draft_filing_is_refused(self):
        """PRD §3.4: "Where an exception is named, that filing's `status` must be
        `ACKNOWLEDGED` or `GRANTED` — a `DRAFT`, `UNDER_REVIEW`,
        `INFO_REQUESTED`, `DENIED`, `WITHDRAWN` or `REVOKED` filing cannot be
        relied upon and the attempt is refused with `ERR_EXCEPTION_NOT_RELIABLE`"

        PRD §2.11: "only two things ever advance a program's `version` — a
        classification determination and the supervisory capital re-categorisation
        cascade."

        Design: Difficulty/cross_entity_state_dependency/classification_gated_on_relied_exception_status
        """
        env = _setup_listing_program_with_draft_exception()
        exception = env["exception"]
        asserts.assert_primary_purpose_exception(exception)
        assert exception["status"] == "DRAFT", (
            f"a newly filed notice lands in DRAFT, got {exception['status']}"
        )
        assert exception["filing_type"] == "NOTICE", (
            "the twenty-five-percent basis is a NOTICE filing, got "
            f"{exception['filing_type']}"
        )
        assert exception["business_line_deposit_ratio_bps"] == 1000, (
            "4,000,000,000 of 40,000,000,000 is 1000 bps, got "
            f"{exception['business_line_deposit_ratio_bps']}"
        )
        assert exception["test_outcome"] == "QUALIFIED", (
            "1000 bps sits strictly below the twenty-five-percent threshold, so the "
            f"arithmetic qualified; got {exception['test_outcome']}"
        )

        resp = api_client.create_classification(
            f.classification_payload(
                env["program"]["id"],
                env["program"]["version"],
                rationale_code="PPE_RELIANCE_25PCT",
                relied_exception_id=exception["id"],
            ),
            COMPLIANCE,
        )
        validate_error(resp, ApiErrorId.ERR_EXCEPTION_NOT_RELIABLE.value)

        program = fx.read_program(env["program"]["id"])
        assert program["state"] == "PENDING_CLASSIFICATION", (
            "the refused determination leaves the program awaiting classification, "
            f"got {program['state']}"
        )
        assert program["version"] == env["program"]["version"], (
            "no determination was applied, so no version was consumed: expected "
            f"{env['program']['version']}, got {program['version']}"
        )
        assert program["governing_classification_id"] is None, (
            "a refused determination governs nothing, got "
            f"{program['governing_classification_id']}"
        )
        _, meta = _list_classifications(program_id=env["program"]["id"])
        assert meta["total_count"] == 0, (
            f"the refused determination must persist nothing, got {meta['total_count']}"
        )
        assert fx.read_exception(exception["id"])["reliant_program_count"] == 0, (
            "a refused determination adds no reliance to the filing"
        )

    def test_same_determination_lands_listing_service_once_the_notice_is_acknowledged(self):
        """PRD §3.3: "A `NOTICE` filing is self-effecting: it moves `DRAFT →
        ACKNOWLEDGED` with no review at all, and re-bases `reporting_due_date` to
        the logical clock's date plus 90 days."

        PRD §3.4: "Third, when a relied exception is present, its `status` is
        `ACKNOWLEDGED` or `GRANTED` and its `test_outcome` is either `QUALIFIED` or
        `NOT_EVALUATED`, the reliance carries the program out of the brokered class
        and the `determined_class` is `LISTING_SERVICE_NON_BROKERED`."

        PRD §3.4: "Reliance accounting travels with it: when the new determination
        names an exception, that filing's `reliant_program_count` increases by 1"

        Design: Difficulty/cross_entity_state_dependency/classification_gated_on_relied_exception_status
        """
        env = _setup_listing_program_with_draft_exception()
        validate_error(
            api_client.create_classification(
                f.classification_payload(
                    env["program"]["id"],
                    env["program"]["version"],
                    rationale_code="PPE_RELIANCE_25PCT",
                    relied_exception_id=env["exception"]["id"],
                ),
                COMPLIANCE,
            ),
            ApiErrorId.ERR_EXCEPTION_NOT_RELIABLE.value,
        )

        exception = fx.exception_filing_action(env["exception"]["id"], "SUBMIT", DESK)
        assert exception["status"] == "ACKNOWLEDGED", (
            "a qualifying NOTICE self-effects to ACKNOWLEDGED, got "
            f"{exception['status']}"
        )
        assert exception["reporting_due_date"] == "2026-10-30", (
            "submission re-bases the deadline to the clock date plus 90 days, "
            f"expected 2026-10-30, got {exception['reporting_due_date']}"
        )

        classification = validate_success(
            api_client.create_classification(
                f.classification_payload(
                    env["program"]["id"],
                    env["program"]["version"],
                    rationale_code="PPE_RELIANCE_25PCT",
                    relied_exception_id=exception["id"],
                ),
                COMPLIANCE,
            ),
            expected_status=201,
        )
        asserts.assert_deposit_classification(classification)
        assert classification["determined_class"] == "LISTING_SERVICE_NON_BROKERED", (
            "branch three fires on a reliable, qualified filing, so the class is "
            f"LISTING_SERVICE_NON_BROKERED; got {classification['determined_class']}"
        )
        assert classification["deposit_broker_prong"] == "NOT_APPLICABLE", (
            "for each of the first four branches deposit_broker_prong is "
            f"NOT_APPLICABLE, got {classification['deposit_broker_prong']}"
        )
        assert classification["call_report_line"] == "RC_E_M2_LISTING", (
            "LISTING_SERVICE_NON_BROKERED maps to RC_E_M2_LISTING, got "
            f"{classification['call_report_line']}"
        )
        assert classification["relied_exception_id"] == exception["id"], (
            "the determination records the filing it leaned on"
        )

        program = fx.read_program(env["program"]["id"])
        assert program["state"] == "CLASSIFIED", (
            f"applying a determination moves the program to CLASSIFIED, got {program['state']}"
        )
        assert program["governing_classification_id"] == classification["id"], (
            "governing_classification_id points at the new determination"
        )
        assert fx.read_exception(exception["id"])["reliant_program_count"] == 1, (
            "the relied filing's reliant_program_count increases by 1"
        )


def _setup_bank_under_examination() -> dict:
    """A bank with no programs or placements and one 2026Q2 filing driven all the
    way to UNDER_EXAMINER_REVIEW, so the computed brokered figure is 0 and the
    filing is ACCURATE."""
    env = fx.setup_bank(institution_overrides={"legal_name": "Exam Lock Bank NA"})
    env["filing"] = fx.setup_filing_under_examiner_review(
        env["institution"]["id"], report_period="2026Q2"
    )
    return env


class TestCapitalCategoryChangeGatedOnExaminerReviewLock:
    """The child filing's state freezes the parent bank it points at."""

    def test_capital_recategorisation_is_refused_while_an_examination_is_open(self):
        """PRD §3.9: "While any filing of a bank sits in `UNDER_EXAMINER_REVIEW`,
        that bank's `capital_category` and its balance baselines are frozen against
        operator edits, and either edit attempted during that window is refused
        with `ERR_EXAMINER_REVIEW_LOCK`."

        PRD §3.1: "it is refused with `ERR_EXAMINER_REVIEW_LOCK` while any of the
        bank's call report filings sits in `UNDER_EXAMINER_REVIEW`, because the
        baselines an examiner is reading may not shift underneath them."

        Design: Difficulty/cross_entity_state_dependency/capital_category_change_gated_on_examiner_review_lock
        """
        env = _setup_bank_under_examination()
        filing = env["filing"]
        asserts.assert_call_report_filing(filing)
        assert filing["status"] == "UNDER_EXAMINER_REVIEW", (
            f"the filing must be under examination, got {filing['status']}"
        )
        assert filing["computed_brokered_cents"] == 0, (
            "the bank has no placements, so the snapshotted brokered figure is 0; "
            f"got {filing['computed_brokered_cents']}"
        )
        assert filing["computed_core_cents"] == 40_000_000_000, (
            "the snapshotted core figure is the operator baseline 40,000,000,000, "
            f"got {filing['computed_core_cents']}"
        )
        assert filing["variance_cents"] == 0 and filing["variance_bps"] == 0, (
            "0 reported against 0 computed is an exact match, got "
            f"{filing['variance_cents']} cents / {filing['variance_bps']} bps"
        )
        assert filing["accuracy_status"] == "ACCURATE", (
            "accuracy_status is ACCURATE when variance_cents is exactly zero, got "
            f"{filing['accuracy_status']}"
        )

        institution = fx.read_institution(env["institution"]["id"])
        observed_version = institution["version"]
        resp = api_client.change_capital_category(
            env["institution"]["id"],
            {
                "capital_category": "ADEQUATELY_CAPITALIZED",
                "expected_institution_version": observed_version,
            },
            EXAMINER,
        )
        validate_error(resp, ApiErrorId.ERR_EXAMINER_REVIEW_LOCK.value)

        after = fx.read_institution(env["institution"]["id"])
        assert after["capital_category"] == "WELL_CAPITALIZED", (
            "the refused re-categorisation must not move the category, got "
            f"{after['capital_category']}"
        )
        assert after["version"] == observed_version, (
            f"a refused write consumes no version: expected {observed_version}, "
            f"got {after['version']}"
        )
        assert after["rate_cap_regime"] == "EXEMPT", (
            "the regime still follows WELL_CAPITALIZED, got "
            f"{after['rate_cap_regime']}"
        )

    def test_balance_baseline_adjustment_is_refused_by_the_same_lock(self):
        """PRD §3.1: "Like a re-categorisation, it is refused with
        `ERR_EXAMINER_REVIEW_LOCK` while one of the bank's filings is under
        examiner review."

        PRD §3.9: "While any filing of a bank sits in `UNDER_EXAMINER_REVIEW`,
        that bank's `capital_category` and its balance baselines are frozen against
        operator edits, and either edit attempted during that window is refused
        with `ERR_EXAMINER_REVIEW_LOCK`."

        Design: Difficulty/cross_entity_state_dependency/capital_category_change_gated_on_examiner_review_lock
        """
        env = _setup_bank_under_examination()
        institution_id = env["institution"]["id"]

        resp = api_client.adjust_balances(
            institution_id, {"liquidity_buffer_cents": 2_000_000_000}, TREASURY
        )
        validate_error(resp, ApiErrorId.ERR_EXAMINER_REVIEW_LOCK.value)

        after = fx.read_institution(institution_id)
        assert after["liquidity_buffer_cents"] == 1_000_000_000, (
            "the frozen baseline keeps its registered value 1,000,000,000, got "
            f"{after['liquidity_buffer_cents']}"
        )
        assert after["total_deposits_cents"] == 40_000_000_000, (
            "no baseline moved, so total_deposits_cents is still the core baseline; "
            f"got {after['total_deposits_cents']}"
        )
        assert after["capital_category"] == "WELL_CAPITALIZED", (
            "the balance path may not move the category either, got "
            f"{after['capital_category']}"
        )

    def test_the_lock_lifts_once_the_examiner_accepts_the_filing(self):
        """PRD §3.9: "The lock lifts as soon as no filing of that bank remains
        `UNDER_EXAMINER_REVIEW` — that is, once the examiner has accepted or
        required an amendment."

        PRD §3.1: "From the capital category the system immediately derives
        `rate_cap_regime`, which is `EXEMPT` when the category is
        `WELL_CAPITALIZED` and `CAPPED` for every other category."

        Design: Difficulty/cross_entity_state_dependency/capital_category_change_gated_on_examiner_review_lock
        """
        env = _setup_bank_under_examination()
        institution_id = env["institution"]["id"]
        observed_version = fx.read_institution(institution_id)["version"]

        validate_error(
            api_client.change_capital_category(
                institution_id,
                {
                    "capital_category": "ADEQUATELY_CAPITALIZED",
                    "expected_institution_version": observed_version,
                },
                EXAMINER,
            ),
            ApiErrorId.ERR_EXAMINER_REVIEW_LOCK.value,
        )

        filing = fx.filing_workflow_action(
            env["filing"]["id"], "ACCEPT", EXAMINER,
            examiner_finding_note="no exceptions noted",
        )
        assert filing["status"] == "ACCEPTED", (
            f"ACCEPT moves the filing to the terminal ACCEPTED, got {filing['status']}"
        )
        assert filing["examiner_finding_note"] == "no exceptions noted", (
            "the accept action records the supplied note, got "
            f"{filing['examiner_finding_note']}"
        )
        assert filing["amendment_round"] == 0, (
            "no amendment was ever required, so amendment_round stays 0, got "
            f"{filing['amendment_round']}"
        )

        institution = validate_success(
            api_client.change_capital_category(
                institution_id,
                {
                    "capital_category": "ADEQUATELY_CAPITALIZED",
                    "expected_institution_version": observed_version,
                },
                EXAMINER,
            )
        )
        asserts.assert_institution(institution)
        assert institution["capital_category"] == "ADEQUATELY_CAPITALIZED", (
            "the re-categorisation now applies, got "
            f"{institution['capital_category']}"
        )
        assert institution["rate_cap_regime"] == "CAPPED", (
            "every category other than WELL_CAPITALIZED derives CAPPED, got "
            f"{institution['rate_cap_regime']}"
        )
        assert institution["version"] == observed_version + 1, (
            "the successful write advances the bank's version by one: expected "
            f"{observed_version + 1}, got {institution['version']}"
        )


def _plan_payload(label: str, effective_from: str, effective_to: str) -> dict:
    """Coverage window plus the strictly increasing triggers 3000 < 4000 < 5000."""
    return f.contingency_plan_payload(
        plan_version_label=label,
        effective_from=effective_from,
        effective_to=effective_to,
        stage_1_trigger_bps=3000,
        stage_2_trigger_bps=4000,
        stage_3_trigger_bps=5000,
        stage_1_action_code="MONITOR_DAILY",
        stage_2_action_code="DRAW_FHLB_LINE",
        stage_3_action_code="SELL_LIQUID_SECURITIES",
    )


def _setup_bank_with_draft_plan() -> dict:
    """One bank and one DRAFT plan covering the closed interval 2026-08-01 ..
    2026-09-30."""
    env = fx.setup_bank(institution_overrides={"legal_name": "Window Bank NA"})
    env["plan_a"] = validate_success(
        api_client.create_contingency_plan(
            env["institution"]["id"],
            _plan_payload("CFP-2026-A", "2026-08-01", "2026-09-30"),
            TREASURY,
        ),
        expected_status=201,
    )
    return env


class TestContingencyPlanClosedWindowExclusiveOccupancy:
    """At most one live plan may cover any given day, and which plans count is
    decided by status rather than by dates alone."""

    def test_a_window_overlapping_only_a_draft_plan_is_accepted(self):
        """PRD §3.7: "That interval must not intersect the closed interval of any
        other plan of the same bank whose `status` is `UNDER_REVIEW`, `APPROVED`,
        `ACTIVATED` or `DEACTIVATED`; plans in `DRAFT` and `REJECTED` occupy no
        window at all."

        Design: Difficulty/resource_temporal_overlap/contingency_plan_closed_window_exclusive_occupancy
        """
        env = _setup_bank_with_draft_plan()
        assert env["plan_a"]["status"] == "DRAFT", (
            f"a new plan lands in DRAFT, got {env['plan_a']['status']}"
        )

        plan_b = validate_success(
            api_client.create_contingency_plan(
                env["institution"]["id"],
                _plan_payload("CFP-2026-B", "2026-09-01", "2026-10-31"),
                TREASURY,
            ),
            expected_status=201,
        )
        asserts.assert_contingency_plan(plan_b)
        assert plan_b["effective_from"] == "2026-09-01", (
            "the accepted window starts inside plan A's dates, got "
            f"{plan_b['effective_from']}"
        )
        assert plan_b["status"] == "DRAFT", (
            f"the second plan also lands in DRAFT, got {plan_b['status']}"
        )
        assert fx.read_plan(env["plan_a"]["id"])["status"] == "DRAFT", (
            "the untouched plan A is still DRAFT and still occupies no window"
        )
        _, meta = _list_plans(env["institution"]["id"])
        assert meta["total_count"] == 2, (
            "both DRAFT plans coexist over the same September days, so total_count "
            f"must be 2; got {meta['total_count']}"
        )

    def test_a_window_touching_a_live_plans_end_date_is_refused(self):
        """PRD §3.7: "Touching endpoints do overlap — a new plan starting on the
        day an existing plan ends is a conflict — while a one-day gap is not, and
        a conflict is refused with `ERR_PLAN_WINDOW_OVERLAP`."

        PRD §3.7: "Submitting for review moves the plan `DRAFT → UNDER_REVIEW` and
        changes no derived field."

        Design: Difficulty/resource_temporal_overlap/contingency_plan_closed_window_exclusive_occupancy
        """
        env = _setup_bank_with_draft_plan()
        plan_b = validate_success(
            api_client.create_contingency_plan(
                env["institution"]["id"],
                _plan_payload("CFP-2026-B", "2026-09-01", "2026-10-31"),
                TREASURY,
            ),
            expected_status=201,
        )
        plan_b = fx.plan_lifecycle_action(plan_b["id"], "SUBMIT_FOR_REVIEW", TREASURY)
        assert plan_b["status"] == "UNDER_REVIEW", (
            "SUBMIT_FOR_REVIEW moves the plan to UNDER_REVIEW, where it starts "
            f"occupying its window; got {plan_b['status']}"
        )
        assert plan_b["effective_to"] == "2026-10-31", (
            f"plan B's window ends on 2026-10-31, got {plan_b['effective_to']}"
        )

        resp = api_client.create_contingency_plan(
            env["institution"]["id"],
            _plan_payload("CFP-2026-C", "2026-10-31", "2026-12-31"),
            TREASURY,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_WINDOW_OVERLAP.value)

        _, meta = _list_plans(env["institution"]["id"])
        assert meta["total_count"] == 2, (
            "the refused plan C persisted nothing, so only A and B exist; got "
            f"total_count {meta['total_count']}"
        )

    def test_a_window_starting_the_day_after_a_live_plan_ends_is_accepted(self):
        """PRD §3.7: "Touching endpoints do overlap — a new plan starting on the
        day an existing plan ends is a conflict — while a one-day gap is not, and
        a conflict is refused with `ERR_PLAN_WINDOW_OVERLAP`."

        PRD §3.7: "A new plan lands in `DRAFT` with `activation_stage` of `NONE`,
        `required_buffer_cents` and `buffer_shortfall_cents` at 0,
        `prepared_by_user_id` stamped from the drafting controller and
        `approved_by_user_id` null."

        Design: Difficulty/resource_temporal_overlap/contingency_plan_closed_window_exclusive_occupancy
        """
        env = _setup_bank_with_draft_plan()
        plan_b = validate_success(
            api_client.create_contingency_plan(
                env["institution"]["id"],
                _plan_payload("CFP-2026-B", "2026-09-01", "2026-10-31"),
                TREASURY,
            ),
            expected_status=201,
        )
        fx.plan_lifecycle_action(plan_b["id"], "SUBMIT_FOR_REVIEW", TREASURY)
        validate_error(
            api_client.create_contingency_plan(
                env["institution"]["id"],
                _plan_payload("CFP-2026-C", "2026-10-31", "2026-12-31"),
                TREASURY,
            ),
            ApiErrorId.ERR_PLAN_WINDOW_OVERLAP.value,
        )

        plan_d = validate_success(
            api_client.create_contingency_plan(
                env["institution"]["id"],
                _plan_payload("CFP-2026-D", "2026-11-01", "2026-12-31"),
                TREASURY,
            ),
            expected_status=201,
        )
        asserts.assert_contingency_plan(plan_d)
        assert plan_d["effective_from"] == "2026-11-01", (
            "2026-11-01 is the day after plan B ends, so the closed intervals are "
            f"disjoint; got {plan_d['effective_from']}"
        )
        assert plan_d["status"] == "DRAFT", (
            f"the accepted plan lands in DRAFT, got {plan_d['status']}"
        )
        assert plan_d["activation_stage"] == "NONE", (
            f"activation_stage starts at NONE, got {plan_d['activation_stage']}"
        )
        assert plan_d["required_buffer_cents"] == 0, (
            f"required_buffer_cents starts at 0, got {plan_d['required_buffer_cents']}"
        )
        assert plan_d["buffer_shortfall_cents"] == 0, (
            f"buffer_shortfall_cents starts at 0, got {plan_d['buffer_shortfall_cents']}"
        )
        assert plan_d["approved_by_user_id"] is None, (
            f"approved_by_user_id starts null, got {plan_d['approved_by_user_id']}"
        )

        _, meta = _list_plans(env["institution"]["id"])
        assert meta["total_count"] == 3, (
            "A, B and D survive while the refused C persisted nothing, so "
            f"total_count must be 3; got {meta['total_count']}"
        )


def _setup_ladder_anchor() -> dict:
    """An open brokered program with one ACTIVE tranche of 12,000,000,000 cents
    issued 2026-08-01 for 60 days, so it matures 2026-09-30.

    With core deposits of 40,000,000,000 the bank's total_deposits_cents is then
    52,000,000,000 and the ladder cap is 3500 bps of that, 18,200,000,000.
    """
    env = fx.setup_open_program(
        broker_overrides={"legal_name": "Ladder Deposit Brokers LLC"},
        program_overrides={"program_name": "Ladder Brokered CD"},
        institution_overrides={
            "legal_name": "Ladder Bank NA",
            "total_liabilities_cents": 80_000_000_000,
            "tier1_capital_cents": 8_000_000_000,
        },
    )
    anchor = fx.book_placement(
        env["program"]["id"],
        DESK,
        principal_cents=12_000_000_000,
        rate_bps=470,
        issue_date="2026-08-01",
        tenor_days=60,
    )
    env["anchor"] = fx.activate_placement(anchor["id"], DESK)
    env["institution"] = fx.read_institution(env["institution"]["id"])
    return env


class TestMaturityLadderBufferedWindowAggregateCapacity:
    """Neighbours share the ladder window freely until their summed principal
    reaches the cap, and one calendar day moves a neighbour out of the window."""

    def test_neighbour_exactly_fifteen_days_away_counts_towards_the_aggregate(self):
        """PRD §3.5: "Consider a candidate tranche maturing on a given date: the
        system takes the closed window running from 15 calendar days before that
        `maturity_date` to 15 calendar days after it, both endpoints inclusive, so
        a neighbour maturing exactly 15 days away is inside the window."

        PRD §3.5: "The cap is an inclusive bound: an exposure that reaches the cap,
        not merely one that passes it, is refused with
        `ERR_MATURITY_WINDOW_CONCENTRATION`."

        Design: Difficulty/resource_temporal_overlap/maturity_ladder_buffered_window_aggregate_capacity
        """
        env = _setup_ladder_anchor()
        assert env["anchor"]["maturity_date"] == "2026-09-30", (
            "60 days after 2026-08-01 is 2026-09-30, got "
            f"{env['anchor']['maturity_date']}"
        )
        assert env["institution"]["brokered_deposits_cents"] == 12_000_000_000, (
            "the ACTIVE anchor sits in the brokered bucket, got "
            f"{env['institution']['brokered_deposits_cents']}"
        )
        assert env["institution"]["total_deposits_cents"] == 52_000_000_000, (
            "40,000,000,000 core plus 12,000,000,000 brokered is 52,000,000,000, "
            f"got {env['institution']['total_deposits_cents']}"
        )

        resp = api_client.create_placement(
            f.placement_payload(
                env["program"]["id"],
                principal_cents=6_200_000_000,
                rate_bps=470,
                issue_date="2026-08-01",
                tenor_days=75,
            ),
            DESK,
        )
        validate_error(resp, ApiErrorId.ERR_MATURITY_WINDOW_CONCENTRATION.value)

        _, meta = _list_placements(program_id=env["program"]["id"])
        assert meta["total_count"] == 1, (
            "the refused candidate persisted nothing, so only the anchor exists; "
            f"got total_count {meta['total_count']}"
        )

    def test_neighbour_sixteen_days_away_falls_outside_the_window(self):
        """PRD §3.5: "This is a buffered aggregate rule rather than an
        exclusive-occupancy rule — each neighbour on its own is perfectly
        admissible, and only the aggregate breaches."

        PRD §2.11: "Placements in `PENDING`, `MATURED`, `WITHDRAWN_EARLY`,
        `ROLLED_OVER` or `CANCELLED` contribute to none of them."

        Design: Difficulty/resource_temporal_overlap/maturity_ladder_buffered_window_aggregate_capacity
        """
        env = _setup_ladder_anchor()
        validate_error(
            api_client.create_placement(
                f.placement_payload(
                    env["program"]["id"],
                    principal_cents=6_200_000_000,
                    rate_bps=470,
                    issue_date="2026-08-01",
                    tenor_days=75,
                ),
                DESK,
            ),
            ApiErrorId.ERR_MATURITY_WINDOW_CONCENTRATION.value,
        )

        placement = validate_success(
            api_client.create_placement(
                f.placement_payload(
                    env["program"]["id"],
                    principal_cents=6_200_000_000,
                    rate_bps=470,
                    issue_date="2026-08-01",
                    tenor_days=76,
                ),
                DESK,
            ),
            expected_status=201,
        )
        asserts.assert_deposit_placement(placement)
        assert placement["maturity_date"] == "2026-10-16", (
            "76 days after 2026-08-01 is 2026-10-16, 16 days past the anchor, so the "
            f"window excludes it; got {placement['maturity_date']}"
        )
        assert placement["tenor_bucket"] == "DAYS_31_90", (
            f"a 76 day tranche lands in DAYS_31_90, got {placement['tenor_bucket']}"
        )
        assert placement["funding_status"] == "PENDING", (
            f"a booked tranche starts in PENDING, got {placement['funding_status']}"
        )

        institution = fx.read_institution(env["institution"]["id"])
        assert institution["brokered_deposits_cents"] == 12_000_000_000, (
            "a PENDING tranche contributes to no wholesale bucket, so the brokered "
            f"figure is still 12,000,000,000; got {institution['brokered_deposits_cents']}"
        )
        assert institution["total_deposits_cents"] == 52_000_000_000, (
            "total_deposits_cents is likewise unmoved by a PENDING tranche, got "
            f"{institution['total_deposits_cents']}"
        )

        placements, meta = _list_placements(program_id=env["program"]["id"])
        assert meta["total_count"] == 2, (
            "the ACTIVE anchor and the accepted PENDING candidate, and nothing from "
            f"the refused attempt; got total_count {meta['total_count']}"
        )
        asserts.assert_wholesale_buckets_match_active_placements(institution, placements)


def _setup_conserve_env() -> dict:
    """A bank with one ACTIVE board limit (warning 400 bps, breach 2000 bps), an
    open brokered program that forbids principal erosion, and one PENDING tranche
    of 2,000,000,000 cents at 470 bps issued 2026-08-01 for 60 days."""
    env = fx.setup_bank(institution_overrides={"legal_name": "Conserve Bank NA"})
    env["limit"] = fx.create_concentration_limit(
        env["institution"]["id"],
        TREASURY,
        metric="BROKERED_TO_TOTAL_DEPOSITS",
        warning_threshold_bps=400,
        breach_threshold_bps=2000,
    )
    env = fx.setup_brokered_program(
        env,
        broker_overrides={"legal_name": "Conserve Deposit Brokers LLC"},
        program_overrides={
            "program_name": "Conserve Brokered CD",
            "early_withdrawal_penalty_days": 30,
            "principal_erosion_allowed": False,
        },
    )
    env = fx.setup_open_program(env)
    env["placement"] = fx.book_placement(
        env["program"]["id"],
        DESK,
        principal_cents=2_000_000_000,
        rate_bps=470,
        issue_date="2026-08-01",
        tenor_days=60,
    )
    env["institution"] = fx.read_institution(env["institution"]["id"])
    return env


class TestActivateThenEarlyWithdrawConservesBrokeredPrincipal:
    """The wholesale bucket, the program's outstanding principal and the board
    posture all return to their exact pre-activation values."""

    def test_activation_moves_the_bucket_the_posture_and_the_program_together(self):
        """PRD §3.5: "On success the tranche's `classified_as` is set from the
        `determined_class` of the program's governing determination, its
        `principal_cents` is added to the matching wholesale bucket on the bank and
        the concentration posture is re-run, the same amount is added to the
        program's `outstanding_principal_cents`"

        PRD §3.7: "The `concentration_posture` is `FROZEN` when at least one
        `ACTIVE` limit is in breach, `RESTRICTED` when none is in breach but at
        least one is in warning, and `OPEN` otherwise."

        Design: Difficulty/compensating_invariant/activate_then_early_withdraw_conserves_brokered_principal
        """
        env = _setup_conserve_env()
        institution_id = env["institution"]["id"]
        assert env["institution"]["brokered_deposits_cents"] == 0, (
            "nothing is funded yet, so the brokered bucket is 0; got "
            f"{env['institution']['brokered_deposits_cents']}"
        )
        assert env["institution"]["total_deposits_cents"] == 40_000_000_000, (
            "total_deposits_cents starts at the core baseline, got "
            f"{env['institution']['total_deposits_cents']}"
        )
        assert env["institution"]["concentration_posture"] == "OPEN", (
            "no limit is in warning yet, so the posture is OPEN; got "
            f"{env['institution']['concentration_posture']}"
        )
        assert fx.read_program(env["program"]["id"])["outstanding_principal_cents"] == 0, (
            "a program with no live money carries outstanding_principal_cents of 0"
        )

        placement = fx.activate_placement(env["placement"]["id"], DESK)
        asserts.assert_deposit_placement(placement)
        assert placement["funding_status"] == "ACTIVE", (
            f"ACTIVATE moves the tranche to ACTIVE, got {placement['funding_status']}"
        )
        assert placement["classified_as"] == "BROKERED", (
            "the tranche inherits BROKERED from the governing determination, got "
            f"{placement['classified_as']}"
        )
        assert placement["compliance_status"] == "UNREVIEWED", (
            "the surveillance dimension never moved, got "
            f"{placement['compliance_status']}"
        )

        institution = fx.read_institution(institution_id)
        assert institution["brokered_deposits_cents"] == 2_000_000_000, (
            "the activated principal enters the brokered bucket, got "
            f"{institution['brokered_deposits_cents']}"
        )
        assert institution["total_deposits_cents"] == 42_000_000_000, (
            "40,000,000,000 core plus 2,000,000,000 brokered is 42,000,000,000, got "
            f"{institution['total_deposits_cents']}"
        )
        assert institution["single_broker_max_ratio_bps"] == 476, (
            "2,000,000,000 of 42,000,000,000 is 476 bps with the remainder "
            f"discarded, got {institution['single_broker_max_ratio_bps']}"
        )
        assert institution["concentration_posture"] == "RESTRICTED", (
            "476 bps is at or above the warning level of 400 and below the breach "
            f"level of 2000, so the posture is RESTRICTED; got {institution['concentration_posture']}"
        )
        assert institution["breached_metric_count"] == 0, (
            "a warning is not a breach, so breached_metric_count stays 0; got "
            f"{institution['breached_metric_count']}"
        )

        limit = _active_limit(institution_id)
        asserts.assert_concentration_limit(limit)
        assert limit["current_value_bps"] == 476, (
            "the ACTIVE limit takes the brokered-to-deposits value into "
            f"current_value_bps, got {limit['current_value_bps']}"
        )
        assert limit["breach_state"] == "WARNING", (
            f"476 bps sits in the warning band 400..1999, got {limit['breach_state']}"
        )

        program = fx.read_program(env["program"]["id"])
        assert program["outstanding_principal_cents"] == 2_000_000_000, (
            "the same amount is added to the program's outstanding principal, got "
            f"{program['outstanding_principal_cents']}"
        )

        summary = validate_success(
            api_client.get_wholesale_funding_summary(institution_id, TREASURY)
        )
        assert summary["wholesale_funding_ratio_bps"] == 476, (
            "the point-in-time ratio is 2,000,000,000 of 42,000,000,000, or 476 bps; "
            f"got {summary['wholesale_funding_ratio_bps']}"
        )
        assert summary["brokered_headroom_cents"] == 7_999_999_999, (
            "the closed-form headroom against a 2000 bps breach threshold on a "
            "42,000,000,000 deposit base is 7,999,999,999 cents; got "
            f"{summary['brokered_headroom_cents']}"
        )

    def test_early_withdrawal_restores_every_balance_and_posture_exactly(self):
        """PRD §2.11: "In particular, an activation followed by its compensating
        early withdrawal must return the bucket to its exact pre-activation value,
        and a full sweep followed by rollovers must leave the arithmetic consistent
        to the cent."

        PRD §3.5: "Interest is settled first: `accrued_interest_cents` is
        `principal_cents` multiplied by `rate_bps`, multiplied by the number of
        whole calendar days from `issue_date` to the settlement date, divided by
        10000 and then by a day-count basis of 365, with that single final quotient
        rounded half up to whole cents."

        PRD §3.5: "Where the program does not allow it, the penalty is clamped to
        the smaller of the contractual figure and `accrued_interest_cents` — an
        exact comparison with no further rounding — so the depositor's principal is
        never eroded and `net_settlement_cents` can never fall below
        `principal_cents`."

        Design: Difficulty/compensating_invariant/activate_then_early_withdraw_conserves_brokered_principal
        """
        env = _setup_conserve_env()
        institution_id = env["institution"]["id"]
        fx.activate_placement(env["placement"]["id"], DESK)

        placement = fx.early_withdraw_placement(
            env["placement"]["id"], "2026-08-25", DESK
        )
        asserts.assert_deposit_placement(placement)
        assert placement["funding_status"] == "WITHDRAWN_EARLY", (
            "EARLY_WITHDRAW moves the tranche to WITHDRAWN_EARLY, got "
            f"{placement['funding_status']}"
        )
        assert placement["settlement_date"] == "2026-08-25", (
            "the supplied withdrawal_date is recorded as settlement_date, got "
            f"{placement['settlement_date']}"
        )
        assert placement["accrued_interest_cents"] == 6_180_822, (
            "24 whole days from 2026-08-01 at 470 bps on 2,000,000,000 cents rounds "
            f"half up to 6,180,822; got {placement['accrued_interest_cents']}"
        )
        assert placement["early_withdrawal_penalty_cents"] == 6_180_822, (
            "the contractual 30 day figure of 7,726,027 is clamped down to the "
            f"interest earned; got {placement['early_withdrawal_penalty_cents']}"
        )
        assert placement["net_settlement_cents"] == 2_000_000_000, (
            "with the penalty clamped the depositor's principal is untouched, got "
            f"{placement['net_settlement_cents']}"
        )
        asserts.assert_net_settlement_arithmetic(placement)
        assert placement["compliance_status"] == "UNREVIEWED", (
            "the funding dimension moved twice and the compliance dimension never "
            f"moved; got {placement['compliance_status']}"
        )

        institution = fx.read_institution(institution_id)
        assert institution["brokered_deposits_cents"] == 0, (
            "the compensating withdrawal returns the bucket to its exact "
            f"pre-activation value of 0; got {institution['brokered_deposits_cents']}"
        )
        assert institution["total_deposits_cents"] == 40_000_000_000, (
            "total_deposits_cents is back to the core baseline, got "
            f"{institution['total_deposits_cents']}"
        )
        assert institution["single_broker_max_ratio_bps"] == 0, (
            "no counterparty has any live exposure, so the ratio is 0; got "
            f"{institution['single_broker_max_ratio_bps']}"
        )
        assert institution["concentration_posture"] == "OPEN", (
            "with every ACTIVE limit back WITHIN the posture is OPEN again, got "
            f"{institution['concentration_posture']}"
        )
        assert institution["breached_metric_count"] == 0, (
            f"nothing is in breach, got {institution['breached_metric_count']}"
        )

        limit = _active_limit(institution_id)
        assert limit["current_value_bps"] == 0, (
            f"the limit re-measures to 0 bps, got {limit['current_value_bps']}"
        )
        assert limit["breach_state"] == "WITHIN", (
            f"0 bps is below the warning level of 400, got {limit['breach_state']}"
        )

        program = fx.read_program(env["program"]["id"])
        assert program["outstanding_principal_cents"] == 0, (
            "the same amount is subtracted from the program's outstanding principal, "
            f"got {program['outstanding_principal_cents']}"
        )

        summary = validate_success(
            api_client.get_wholesale_funding_summary(institution_id, TREASURY)
        )
        assert summary["wholesale_funding_ratio_bps"] == 0, (
            "no wholesale money is live, so the point-in-time ratio is 0; got "
            f"{summary['wholesale_funding_ratio_bps']}"
        )
        placements, _ = _list_placements(program_id=env["program"]["id"])
        asserts.assert_wholesale_buckets_match_active_placements(institution, placements)


def _setup_refcount_env() -> dict:
    """A listing service with placement discretion under an APPROVED agreement, an
    ACKNOWLEDGED twenty-five-percent notice on the same pair, and one
    PENDING_CLASSIFICATION program, so the determined class flips between
    LISTING_SERVICE_NON_BROKERED and BROKERED purely on exception reliance."""
    env = fx.setup_bank(institution_overrides={"legal_name": "Refcount Bank NA"})
    env.update(
        fx.setup_approved_agreement(
            broker_overrides={
                "legal_name": "Refcount Listing Services LLC",
                "broker_type": "LISTING_SERVICE",
                "has_placement_discretion": True,
            }
        )
    )
    env["exception"] = fx.setup_acknowledged_exception(
        env["broker"]["id"],
        env["institution"]["id"],
        designated_business_line="wealth sweep",
        total_customer_assets_cents=40_000_000_000,
        deposits_placed_at_ifs_cents=4_000_000_000,
    )
    env["program"] = fx.open_program(
        env["institution"]["id"],
        DESK,
        broker_id=env["broker"]["id"],
        agreement_id=env["agreement"]["id"],
        program_name="Refcount Sweep MMDA",
        funding_channel_claim="LISTING_SERVICE",
        product_type="MONEY_MARKET",
        tenor_days=0,
        offered_rate_bps=420,
        early_withdrawal_penalty_days=0,
    )
    return env


def _determine(program_id, expected_program_version, rationale_code, **overrides) -> dict:
    return validate_success(
        api_client.create_classification(
            f.classification_payload(
                program_id, expected_program_version, rationale_code=rationale_code,
                **overrides
            ),
            COMPLIANCE,
        ),
        expected_status=201,
    )


class TestClassifyThenReclassifyConservesExceptionRelianceCount:
    """The reliance count is a reference count: the classification raises it and
    the reclassification that drops the reliance returns it exactly."""

    def test_relying_determination_raises_the_reliance_count(self):
        """PRD §3.4: "Reliance accounting travels with it: when the new
        determination names an exception, that filing's `reliant_program_count`
        increases by 1"

        PRD §3.4: "The determination also captures
        `program_version_at_determination`, which is the program's `version`
        immediately after this determination has been applied, that is the observed
        `expected_program_version` plus the determination's own increment of 1."

        Design: Difficulty/compensating_invariant/classify_then_reclassify_conserves_exception_reliance_count
        """
        env = _setup_refcount_env()
        assert env["exception"]["status"] == "ACKNOWLEDGED", (
            "the notice self-effected to ACKNOWLEDGED, got "
            f"{env['exception']['status']}"
        )
        assert env["exception"]["reliant_program_count"] == 0, (
            "no program leans on the filing yet, got "
            f"{env['exception']['reliant_program_count']}"
        )

        classification = _determine(
            env["program"]["id"],
            env["program"]["version"],
            "PPE_RELIANCE_25PCT",
            relied_exception_id=env["exception"]["id"],
        )
        asserts.assert_deposit_classification(classification)
        assert classification["determined_class"] == "LISTING_SERVICE_NON_BROKERED", (
            "the reliance carries the program out of the brokered class, got "
            f"{classification['determined_class']}"
        )
        assert classification["deposit_broker_prong"] == "NOT_APPLICABLE", (
            f"branch three records no prong, got {classification['deposit_broker_prong']}"
        )
        assert classification["call_report_line"] == "RC_E_M2_LISTING", (
            "LISTING_SERVICE_NON_BROKERED maps to RC_E_M2_LISTING, got "
            f"{classification['call_report_line']}"
        )
        assert classification["relied_exception_id"] == env["exception"]["id"], (
            "the determination names the filing it relied upon"
        )
        assert classification["program_version_at_determination"] == 2, (
            "the observed version 1 plus this determination's own increment is 2, got "
            f"{classification['program_version_at_determination']}"
        )

        program = fx.read_program(env["program"]["id"])
        assert program["state"] == "CLASSIFIED", (
            f"the program is now CLASSIFIED, got {program['state']}"
        )
        assert program["version"] == 2, (
            f"applying a determination increments the version by 1, got {program['version']}"
        )
        assert program["governing_classification_id"] == classification["id"], (
            "the new determination governs the program"
        )
        exception = fx.read_exception(env["exception"]["id"])
        assert exception["reliant_program_count"] == 1, (
            "the relied filing's reliance count rises to 1, got "
            f"{exception['reliant_program_count']}"
        )

    def test_reclassification_without_reliance_restores_the_count_exactly(self):
        """PRD §2.11: "A second conserved quantity governs exception reliance:
        `reliant_program_count` on an exception filing equals the number of programs
        whose `governing_classification_id` names a determination whose
        `relied_exception_id` is that filing, so a classification relying on a
        filing followed by a reclassification that does not rely on it must return
        the count to its exact prior value."

        PRD §3.4: "Starting a reclassification is admitted from `CLASSIFIED` and
        from `OPEN_FOR_PLACEMENT`, moves the program to `RECLASSIFICATION_PENDING`,
        and clears `attested_by_user_id` back to null so the program must be
        attested afresh once the new determination lands."

        PRD §3.4: "Fifth and last, the deposit-broker prongs apply and the
        `determined_class` is `BROKERED`; which prong drove it is recorded in
        `deposit_broker_prong`, again first match wins — `PLACEMENT_DISCRETION`
        when the counterparty has placement discretion"

        Design: Difficulty/compensating_invariant/classify_then_reclassify_conserves_exception_reliance_count
        """
        env = _setup_refcount_env()
        first = _determine(
            env["program"]["id"],
            env["program"]["version"],
            "PPE_RELIANCE_25PCT",
            relied_exception_id=env["exception"]["id"],
        )
        assert fx.read_exception(env["exception"]["id"])["reliant_program_count"] == 1, (
            "the forward leg must raise the reliance count to 1 before it can be "
            "restored"
        )

        program = fx.program_state_action(
            env["program"]["id"], "START_RECLASSIFICATION", DESK
        )
        assert program["state"] == "RECLASSIFICATION_PENDING", (
            "START_RECLASSIFICATION moves the program to RECLASSIFICATION_PENDING, "
            f"got {program['state']}"
        )
        assert program["attested_by_user_id"] is None, (
            "the action clears attested_by_user_id back to null, got "
            f"{program['attested_by_user_id']}"
        )
        assert program["version"] == 2, (
            "state actions deliberately do not advance the version, so it is still 2; "
            f"got {program['version']}"
        )

        second = _determine(
            env["program"]["id"], program["version"], "RELIANCE_WITHDRAWN_BROKER_PRONG"
        )
        asserts.assert_deposit_classification(second)
        assert second["determined_class"] == "BROKERED", (
            "with no reliance named, the fifth branch applies, got "
            f"{second['determined_class']}"
        )
        assert second["deposit_broker_prong"] == "PLACEMENT_DISCRETION", (
            "the counterparty holds placement discretion, got "
            f"{second['deposit_broker_prong']}"
        )
        assert second["call_report_line"] == "RC_E_M1_BROKERED", (
            f"BROKERED maps to RC_E_M1_BROKERED, got {second['call_report_line']}"
        )
        assert second["relied_exception_id"] is None, (
            f"the new determination names no filing, got {second['relied_exception_id']}"
        )
        assert second["program_version_at_determination"] == 3, (
            "the observed version 2 plus this determination's own increment is 3, got "
            f"{second['program_version_at_determination']}"
        )

        exception = fx.read_exception(env["exception"]["id"])
        assert exception["reliant_program_count"] == 0, (
            "the superseded determination's filing is decremented, so the count is "
            f"back to its exact prior value of 0; got {exception['reliant_program_count']}"
        )
        assert exception["status"] == "ACKNOWLEDGED", (
            "the reclassification does not disturb the filing's own status, got "
            f"{exception['status']}"
        )
        assert exception["reporting_due_date"] == "2026-10-30", (
            "the filing's deadline is untouched, expected 2026-10-30, got "
            f"{exception['reporting_due_date']}"
        )

        program = fx.read_program(env["program"]["id"])
        assert program["state"] == "CLASSIFIED", (
            f"the reclassification lands the program back in CLASSIFIED, got {program['state']}"
        )
        assert program["version"] == 3, (
            f"the second determination increments the version to 3, got {program['version']}"
        )
        assert program["governing_classification_id"] == second["id"], (
            "the newer determination now governs the program"
        )

        rows, meta = _list_classifications(program_id=env["program"]["id"])
        assert meta["total_count"] == 2, (
            "both immutable determinations survive the restoration, got "
            f"{meta['total_count']}"
        )
        assert {row["id"] for row in rows} == {first["id"], second["id"]}, (
            "the two listed determinations are exactly the forward and compensating "
            "rows"
        )
        superseded, meta = _list_classifications(
            relied_exception_id=env["exception"]["id"]
        )
        assert meta["total_count"] == 1, (
            "only the superseded row still names the filing, got "
            f"{meta['total_count']}"
        )
        assert superseded[0]["id"] == first["id"], (
            "the row naming the filing is the superseded determination"
        )
