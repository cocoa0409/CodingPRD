"""Lifecycle compliance tests: declared initial states, legal transition walks,
transition preconditions, side-effect cascades, terminal states and rejections of
undeclared actions.

Every test builds its own state from scratch against an empty database.
"""
import pytest

from test_helpers import (
    DEFAULT_CLOCK_INSTANT,
    ApiErrorId,
    api_client,
    validate_error,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    COMPLIANCE,
    DESK,
    EXAMINER,
    TREASURY,
    USER_IDS,
)


def _bank_baselines(**overrides) -> dict:
    """The four balance baselines supplied at registration (PRD §3.1)."""
    payload = {
        "core_deposits_cents": 30_000_000_000,
        "total_liabilities_cents": 45_000_000_000,
        "tier1_capital_cents": 4_000_000_000,
        "liquidity_buffer_cents": 900_000_000,
    }
    payload.update(overrides)
    return payload


def test_new_agreement_starts_in_draft():
    """A freshly filed agreement occupies the declared initial diligence state.

    PRD §3.2: "A new agreement lands in `DRAFT` with `diligence_score` of 0,
    `rfi_round_count` of 0 and `accrued_fee_cents` of 0; the filer's identifier is
    stamped as `prepared_by_user_id`, which is the identity every later approval is
    compared against, and `reviewed_by_user_id` stays null until the first review
    action."

    Design: Corner/state_machines/corner_initial_states_of_every_declared_machine
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    broker = fx.register_broker()

    data = validate_success(
        api_client.create_agreement(
            broker["id"], f.agreement_payload(agreement_ref="AGR-INIT-1"), DESK
        ),
        expected_status=201,
    )

    assert data["status"] == "DRAFT", (
        f"a new agreement lands in DRAFT, got {data['status']}"
    )
    assert data["diligence_score"] == 0, (
        f"the composite score is 0 until diligence starts, got {data['diligence_score']}"
    )
    assert data["rfi_round_count"] == 0, (
        f"no information request has been issued yet, got {data['rfi_round_count']}"
    )
    assert data["reviewed_by_user_id"] is None, (
        f"reviewed_by_user_id stays null until the first review action, got "
        f"{data['reviewed_by_user_id']}"
    )
    asserts.assert_broker_agreement(data)


def test_new_exception_filing_starts_in_draft():
    """A freshly filed exception occupies the declared initial filing state.

    PRD §3.3: "At creation the filing lands in `DRAFT` with
    `info_request_round_count` and `reliant_program_count` both at 0,
    `prepared_by_user_id` stamped from the drafting officer's identifier and
    `reviewed_by_user_id` null."

    PRD §3.3: "It is also stamped with `reporting_due_date`, a calendar date set to
    the logical clock's date plus 90 days."

    Design: Corner/state_machines/corner_initial_states_of_every_declared_machine
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    bank = fx.register_institution(cert_id="CERT-8001", **_bank_baselines())
    broker = fx.register_broker()

    data = validate_success(
        api_client.create_exception(
            f.exception_payload(broker["id"], bank["id"]), DESK
        ),
        expected_status=201,
    )

    assert data["status"] == "DRAFT", (
        f"a new exception filing lands in DRAFT, got {data['status']}"
    )
    assert data["info_request_round_count"] == 0, (
        f"no information request has been issued yet, got "
        f"{data['info_request_round_count']}"
    )
    assert data["reliant_program_count"] == 0, (
        f"no program relies on a fresh filing, got {data['reliant_program_count']}"
    )
    assert data["prepared_by_user_id"] == USER_IDS["desk"], (
        f"prepared_by_user_id is stamped from the drafting officer, got "
        f"{data['prepared_by_user_id']}"
    )
    assert data["reviewed_by_user_id"] is None, (
        f"reviewed_by_user_id starts null, got {data['reviewed_by_user_id']}"
    )
    assert data["reporting_due_date"] == "2026-10-30", (
        "the due date is the logical-clock date 2026-08-01 plus 90 days, got "
        f"{data['reporting_due_date']}"
    )


def test_new_program_starts_in_pending_classification():
    """A freshly opened program occupies the declared initial program state.

    PRD §3.4: "A new program lands in `PENDING_CLASSIFICATION` with
    `governing_classification_id` null, `outstanding_principal_cents` at 0,
    `prepared_by_user_id` stamped from the opening officer's identifier and
    `attested_by_user_id` null."

    Design: Corner/state_machines/corner_initial_states_of_every_declared_machine
    """
    env = fx.setup_bank(institution_overrides=_bank_baselines())

    data = validate_success(
        api_client.create_program(f.program_payload(env["institution"]["id"]), DESK),
        expected_status=201,
    )

    assert data["state"] == "PENDING_CLASSIFICATION", (
        f"a new program lands in PENDING_CLASSIFICATION, got {data['state']}"
    )
    assert data["governing_classification_id"] is None, (
        "an unclassified program governs nothing, got "
        f"{data['governing_classification_id']}"
    )
    assert data["outstanding_principal_cents"] == 0, (
        f"no money is outstanding yet, got {data['outstanding_principal_cents']}"
    )
    assert data["prepared_by_user_id"] == USER_IDS["desk"], (
        f"prepared_by_user_id is stamped from the opening officer, got "
        f"{data['prepared_by_user_id']}"
    )
    assert data["attested_by_user_id"] is None, (
        f"attested_by_user_id starts null, got {data['attested_by_user_id']}"
    )
    assert data["version"] == 1, f"version starts at 1, got {data['version']}"


def test_new_placement_starts_pending_and_unreviewed():
    """A booked tranche starts at the head of both of its state dimensions.

    PRD §3.5: "A booked tranche starts in `PENDING` on the funding dimension and
    `UNREVIEWED` on the surveillance dimension, with `accrued_interest_cents`,
    `early_withdrawal_penalty_cents`, `net_settlement_cents` and `fee_accrual_cents`
    all at 0 and `settlement_date` null."

    Design: Corner/state_machines/corner_initial_states_of_every_declared_machine
    """
    env = fx.setup_open_program(institution_overrides=_bank_baselines())

    data = validate_success(
        api_client.create_placement(f.placement_payload(env["program"]["id"]), DESK),
        expected_status=201,
    )

    assert data["funding_status"] == "PENDING", (
        f"the funding dimension starts at PENDING, got {data['funding_status']}"
    )
    assert data["compliance_status"] == "UNREVIEWED", (
        f"the surveillance dimension starts at UNREVIEWED, got {data['compliance_status']}"
    )
    assert data["accrued_interest_cents"] == 0, (
        f"no interest has accrued yet, got {data['accrued_interest_cents']}"
    )
    assert data["early_withdrawal_penalty_cents"] == 0, (
        f"no penalty has been assessed yet, got {data['early_withdrawal_penalty_cents']}"
    )
    assert data["net_settlement_cents"] == 0, (
        f"nothing has settled yet, got {data['net_settlement_cents']}"
    )
    assert data["fee_accrual_cents"] == 0, (
        f"no fee has accrued yet, got {data['fee_accrual_cents']}"
    )
    assert data["settlement_date"] is None, (
        f"settlement_date stays null while the tranche is PENDING, got "
        f"{data['settlement_date']}"
    )


def test_new_contingency_plan_starts_in_draft():
    """A freshly drafted plan occupies the declared initial plan state.

    PRD §3.7: "A new plan lands in `DRAFT` with `activation_stage` of `NONE`,
    `required_buffer_cents` and `buffer_shortfall_cents` at 0, `prepared_by_user_id`
    stamped from the drafting controller and `approved_by_user_id` null."

    Design: Corner/state_machines/corner_initial_states_of_every_declared_machine
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    bank = fx.register_institution(cert_id="CERT-8002", **_bank_baselines())

    data = validate_success(
        api_client.create_contingency_plan(
            bank["id"], f.contingency_plan_payload(plan_version_label="CFP-INIT-1"),
            TREASURY,
        ),
        expected_status=201,
    )

    assert data["status"] == "DRAFT", f"a new plan lands in DRAFT, got {data['status']}"
    assert data["activation_stage"] == "NONE", (
        f"no escalation stage is engaged yet, got {data['activation_stage']}"
    )
    assert data["required_buffer_cents"] == 0, (
        f"required_buffer_cents starts at 0, got {data['required_buffer_cents']}"
    )
    assert data["buffer_shortfall_cents"] == 0, (
        f"buffer_shortfall_cents starts at 0, got {data['buffer_shortfall_cents']}"
    )
    assert data["approved_by_user_id"] is None, (
        f"approved_by_user_id starts null, got {data['approved_by_user_id']}"
    )
    asserts.assert_contingency_plan(data)


def test_new_call_report_filing_starts_in_draft_with_nothing_compared():
    """A freshly opened filing occupies the declared initial workflow state and has
    compared nothing.

    PRD §3.9: "A new filing opens in `DRAFT` with `computed_brokered_cents`,
    `computed_listing_cents`, `computed_core_cents`, `variance_cents`, `variance_bps`
    and `amendment_round` all at 0, `accuracy_status` of `NOT_ASSESSED`, and
    `examiner_finding_note`, `prepared_by_user_id` and `attested_by_user_id` all
    null."

    PRD §3.9: "Nothing is compared at creation."

    Design: Corner/state_machines/corner_initial_states_of_every_declared_machine
    """
    env = fx.setup_active_placement(institution_overrides=_bank_baselines())

    data = validate_success(
        api_client.create_call_report_filing(
            env["institution"]["id"],
            f.call_report_filing_payload(
                report_period="2026Q3", rc_e_brokered_reported_cents=0
            ),
            DESK,
        ),
        expected_status=201,
    )

    assert data["status"] == "DRAFT", (
        f"a new filing opens in DRAFT, got {data['status']}"
    )
    assert data["computed_brokered_cents"] == 0, (
        "nothing is snapshotted at creation even though brokered money is live, got "
        f"{data['computed_brokered_cents']}"
    )
    assert data["computed_listing_cents"] == 0, (
        f"computed_listing_cents starts at 0, got {data['computed_listing_cents']}"
    )
    assert data["computed_core_cents"] == 0, (
        f"computed_core_cents starts at 0, got {data['computed_core_cents']}"
    )
    assert data["variance_cents"] == 0, (
        f"no variance is measured at creation, got {data['variance_cents']}"
    )
    assert data["variance_bps"] == 0, (
        f"no variance is measured at creation, got {data['variance_bps']}"
    )
    assert data["amendment_round"] == 0, (
        f"no amendment has been required yet, got {data['amendment_round']}"
    )
    assert data["accuracy_status"] == "NOT_ASSESSED", (
        f"accuracy is unassessed until preparation, got {data['accuracy_status']}"
    )
    assert data["prepared_by_user_id"] is None, (
        f"prepared_by_user_id starts null, got {data['prepared_by_user_id']}"
    )
    assert data["attested_by_user_id"] is None, (
        f"attested_by_user_id starts null, got {data['attested_by_user_id']}"
    )
    assert data["examiner_finding_note"] is None, (
        f"examiner_finding_note starts null, got {data['examiner_finding_note']}"
    )


def test_agreement_walks_draft_to_under_diligence_to_approved():
    """The declared happy path of the diligence machine is travelled end to end.

    PRD §3.2: "Starting diligence moves the agreement from `DRAFT` to
    `UNDER_DILIGENCE`, recomputes the composite score, stamps `reviewed_by_user_id`
    with the acting identifier, sets the counterparty's `diligence_status` to
    `IN_DILIGENCE`, and increments both the agreement's `version` and the
    counterparty's `version` by 1."

    PRD §3.2: "When the composite score is at least 70 and `aml_program_score` is at
    least 60, the agreement becomes `APPROVED`, the counterparty's `diligence_status`
    becomes `APPROVED` and `approved_agreement_count` increases by 1."

    PRD §3.2: "The composite `diligence_score` is a weighted blend of the four
    sub-scores: thirty-five parts of `aml_program_score`, thirty parts of
    `financial_condition_score`, twenty parts of `insurance_coverage_score` and fifteen
    parts of `recordkeeping_score`, summed as an exact rational and divided by one
    hundred, with that single final quotient rounded half up to a whole point in the 0
    to 100 range."

    Design: Corner/state_machines/corner_valid_transition_walk_agreement_program_placement
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    broker = fx.register_broker()
    agreement = fx.draft_agreement(broker["id"], DESK, agreement_ref="AGR-WALK-1")
    assert agreement["status"] == "DRAFT", "the walk starts from DRAFT"

    started = validate_success(
        api_client.diligence_action(
            agreement["id"], f.diligence_action_payload("START_DILIGENCE"), COMPLIANCE
        )
    )
    assert started["status"] == "UNDER_DILIGENCE", (
        f"START_DILIGENCE moves DRAFT to UNDER_DILIGENCE, got {started['status']}"
    )
    assert started["diligence_score"] == 74, (
        "the composite of 80, 75, 70 and 65 rounds to 74, got "
        f"{started['diligence_score']}"
    )
    assert started["reviewed_by_user_id"] == USER_IDS["compliance"], (
        f"reviewed_by_user_id is stamped with the acting reviewer, got "
        f"{started['reviewed_by_user_id']}"
    )

    approved = validate_success(
        api_client.diligence_action(
            agreement["id"], f.diligence_action_payload("APPROVE"), COMPLIANCE
        )
    )
    assert approved["status"] == "APPROVED", (
        f"a composite of 74 on an AML sub-score of 80 approves, got {approved['status']}"
    )

    counterparty = fx.read_broker(broker["id"])
    assert counterparty["diligence_status"] == "APPROVED", (
        f"the counterparty mirror follows the agreement to APPROVED, got "
        f"{counterparty['diligence_status']}"
    )
    assert counterparty["approved_agreement_count"] == 1, (
        f"approved_agreement_count rises to 1, got "
        f"{counterparty['approved_agreement_count']}"
    )


def test_program_walks_to_open_and_its_tranche_walks_to_active():
    """A program is determined and attested, and money booked under it is activated.

    PRD §3.4: "Applying a determination moves the program from
    `PENDING_CLASSIFICATION` (or from `RECLASSIFICATION_PENDING`) to `CLASSIFIED`,
    sets `governing_classification_id` to the new determination's `id`, increments the
    program's `version` by 1, and re-derives `effective_cap_bps`."

    PRD §3.4: "Attestation by a funding-desk officer moves the program `CLASSIFIED →
    OPEN_FOR_PLACEMENT` and stamps `attested_by_user_id` with the acting identifier."

    PRD §3.5: "On success the tranche's `classified_as` is set from the
    `determined_class` of the program's governing determination, its `principal_cents`
    is added to the matching wholesale bucket on the bank and the concentration posture
    is re-run, the same amount is added to the program's `outstanding_principal_cents`,
    and the agreement's `accrued_fee_cents` together with this tranche's own
    `fee_accrual_cents` are recomputed by the fee rule of §3.2."

    Design: Corner/state_machines/corner_valid_transition_walk_agreement_program_placement
    """
    env = fx.setup_brokered_program(institution_overrides=_bank_baselines())
    program = env["program"]
    assert program["state"] == "PENDING_CLASSIFICATION", "the walk starts unclassified"

    determination = validate_success(
        api_client.create_classification(
            f.classification_payload(program["id"], program["version"]), COMPLIANCE
        ),
        expected_status=201,
    )
    classified = fx.read_program(program["id"])
    assert classified["state"] == "CLASSIFIED", (
        f"the determination moves the program to CLASSIFIED, got {classified['state']}"
    )
    assert classified["governing_classification_id"] == determination["id"], (
        "the new determination becomes the governing one"
    )
    assert classified["version"] == 2, (
        f"the determination increments the program version to 2, got {classified['version']}"
    )

    attested = validate_success(
        api_client.program_state_action(
            program["id"], {"action": "ATTEST_CLASSIFICATION"}, DESK
        )
    )
    assert attested["state"] == "OPEN_FOR_PLACEMENT", (
        f"attestation opens the program for placement, got {attested['state']}"
    )
    assert attested["attested_by_user_id"] == USER_IDS["desk"], (
        f"attested_by_user_id is stamped with the attesting officer, got "
        f"{attested['attested_by_user_id']}"
    )

    placement = fx.book_placement(program["id"], DESK, principal_cents=2_000_000_000)
    assert placement["funding_status"] == "PENDING", "the tranche is booked PENDING"

    active = validate_success(
        api_client.funding_action(placement["id"], {"action": "ACTIVATE"}, DESK)
    )
    assert active["funding_status"] == "ACTIVE", (
        f"ACTIVATE moves the tranche PENDING to ACTIVE, got {active['funding_status']}"
    )
    assert active["classified_as"] == "BROKERED", (
        "the activated tranche takes the determined class of its program, got "
        f"{active['classified_as']}"
    )

    program_after = fx.read_program(program["id"])
    assert program_after["outstanding_principal_cents"] == 2_000_000_000, (
        "the activated principal joins the program's outstanding balance, got "
        f"{program_after['outstanding_principal_cents']}"
    )
    bank_after = fx.read_institution(env["institution"]["id"])
    assert bank_after["brokered_deposits_cents"] == 2_000_000_000, (
        "the activated principal joins the brokered bucket, got "
        f"{bank_after['brokered_deposits_cents']}"
    )


def test_attestation_is_blocked_while_the_variance_is_material():
    """A filing whose brokered line is materially wrong cannot leave PREPARED.

    PRD §3.9: "Preparing snapshots the bank's live derived balances at that instant —
    `computed_brokered_cents` from `brokered_deposits_cents`, `computed_listing_cents`
    from `listing_service_deposits_cents`, `computed_core_cents` from
    `core_deposits_cents` — and then measures the brokered line only: `variance_cents`
    is the absolute difference between `rc_e_brokered_reported_cents` and
    `computed_brokered_cents`, in either direction, so over-reporting and
    under-reporting by the same amount are equally material."

    PRD §3.9: "The tier follows: `accuracy_status` is `ACCURATE` when `variance_cents`
    is exactly zero, `VARIANCE_MINOR` when there is some variance but `variance_bps` is
    strictly below 25, and `VARIANCE_MATERIAL` when `variance_bps` is 25 or more."

    PRD §3.9: "Attestation is also the accuracy gate — a filing whose
    `accuracy_status` is `VARIANCE_MATERIAL` cannot be attested and is refused with
    `ERR_FILING_VARIANCE_MATERIAL`; the operator must correct the reported numbers, or
    the underlying book must change, and the filing must be prepared again."

    Design: Corner/state_machines/corner_attest_precondition_blocks_material_variance
    """
    env = fx.setup_active_placement(
        institution_overrides=_bank_baselines(),
        placement_overrides={"principal_cents": 2_000_000_000},
    )
    filing = fx.create_call_report_filing(
        env["institution"]["id"], DESK,
        report_period="2026Q3",
        rc_e_brokered_reported_cents=0,
        rc_o_listing_reported_cents=0,
        rc_e_core_reported_cents=30_000_000_000,
    )

    prepared = validate_success(
        api_client.filing_workflow_action(filing["id"], {"action": "PREPARE"}, DESK)
    )
    assert prepared["status"] == "PREPARED", (
        f"PREPARE moves the filing DRAFT to PREPARED, got {prepared['status']}"
    )
    assert prepared["computed_brokered_cents"] == 2_000_000_000, (
        "preparation snapshots the live brokered bucket, got "
        f"{prepared['computed_brokered_cents']}"
    )
    assert prepared["variance_cents"] == 2_000_000_000, (
        "the brokered line was reported as 0 against a book of 2,000,000,000, got "
        f"{prepared['variance_cents']}"
    )
    assert prepared["variance_bps"] == 625, (
        "2,000,000,000 * 10000 // 32,000,000,000 is 625 basis points, got "
        f"{prepared['variance_bps']}"
    )
    assert prepared["accuracy_status"] == "VARIANCE_MATERIAL", (
        f"625 basis points is at or above 25, got {prepared['accuracy_status']}"
    )

    validate_error(
        api_client.filing_workflow_action(filing["id"], {"action": "ATTEST"}, COMPLIANCE),
        ApiErrorId.ERR_FILING_VARIANCE_MATERIAL.value,
    )

    after = fx.read_filing(filing["id"])
    assert after["status"] == "PREPARED", (
        f"the refused attestation leaves the filing in PREPARED, got {after['status']}"
    )
    assert after["attested_by_user_id"] is None, (
        f"a refused attestation stamps nobody, got {after['attested_by_user_id']}"
    )


def test_attestation_succeeds_once_the_reported_brokered_line_matches():
    """A filing that reports the brokered line exactly walks PREPARED to ATTESTED.

    PRD §3.9: "The tier follows: `accuracy_status` is `ACCURATE` when `variance_cents`
    is exactly zero, `VARIANCE_MINOR` when there is some variance but `variance_bps` is
    strictly below 25, and `VARIANCE_MATERIAL` when `variance_bps` is 25 or more."

    PRD §3.9: "Attesting moves it `PREPARED → ATTESTED` and stamps
    `attested_by_user_id`, and it is the segregation-of-duties gate: the attesting
    identifier must differ from `prepared_by_user_id`."

    Design: Corner/state_machines/corner_attest_precondition_blocks_material_variance
    """
    env = fx.setup_active_placement(
        institution_overrides=_bank_baselines(),
        placement_overrides={"principal_cents": 2_000_000_000},
    )
    filing = fx.create_call_report_filing(
        env["institution"]["id"], DESK,
        report_period="2026Q3",
        rc_e_brokered_reported_cents=2_000_000_000,
        rc_o_listing_reported_cents=0,
        rc_e_core_reported_cents=30_000_000_000,
    )

    prepared = validate_success(
        api_client.filing_workflow_action(filing["id"], {"action": "PREPARE"}, DESK)
    )
    assert prepared["variance_cents"] == 0, (
        f"the reported brokered line matches the book, got {prepared['variance_cents']}"
    )
    assert prepared["accuracy_status"] == "ACCURATE", (
        f"an exact match is ACCURATE, got {prepared['accuracy_status']}"
    )
    assert prepared["prepared_by_user_id"] == USER_IDS["desk"], (
        f"preparation stamps the acting officer, got {prepared['prepared_by_user_id']}"
    )

    attested = validate_success(
        api_client.filing_workflow_action(filing["id"], {"action": "ATTEST"}, COMPLIANCE)
    )
    assert attested["status"] == "ATTESTED", (
        f"ATTEST moves PREPARED to ATTESTED, got {attested['status']}"
    )
    assert attested["attested_by_user_id"] == USER_IDS["compliance"], (
        f"attested_by_user_id is stamped with the attesting reviewer, got "
        f"{attested['attested_by_user_id']}"
    )


def test_start_diligence_side_effects_sync_the_counterparty_mirror():
    """Entering diligence advances the agreement and its counterparty together.

    PRD §3.2: "Starting diligence moves the agreement from `DRAFT` to
    `UNDER_DILIGENCE`, recomputes the composite score, stamps `reviewed_by_user_id`
    with the acting identifier, sets the counterparty's `diligence_status` to
    `IN_DILIGENCE`, and increments both the agreement's `version` and the
    counterparty's `version` by 1."

    PRD §3.2: "A fresh counterparty starts with `diligence_status` of `NOT_STARTED`
    and `approved_agreement_count` of 0; the status is a mirror of the counterparty's
    governing agreement and is only ever moved by the diligence cascade below, never
    written directly."

    Design: Corner/state_machines/corner_start_diligence_side_effects_sync_broker_mirror
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    broker = fx.register_broker()
    agreement = fx.draft_agreement(broker["id"], DESK, agreement_ref="AGR-SYNC-1")
    assert broker["diligence_status"] == "NOT_STARTED", "the mirror starts NOT_STARTED"
    assert broker["version"] == 1, "the counterparty starts at version 1"
    assert agreement["version"] == 1, "the agreement starts at version 1"

    started = validate_success(
        api_client.diligence_action(
            agreement["id"], f.diligence_action_payload("START_DILIGENCE"), COMPLIANCE
        )
    )

    assert started["status"] == "UNDER_DILIGENCE", (
        f"the agreement moves DRAFT to UNDER_DILIGENCE, got {started['status']}"
    )
    assert started["diligence_score"] == 74, (
        "the composite is recomputed on entry into diligence, got "
        f"{started['diligence_score']}"
    )
    assert started["reviewed_by_user_id"] == USER_IDS["compliance"], (
        f"reviewed_by_user_id is stamped with the acting reviewer, got "
        f"{started['reviewed_by_user_id']}"
    )
    assert started["version"] == 2, (
        f"the agreement's version increments by exactly 1, got {started['version']}"
    )

    mirrored = fx.read_broker(broker["id"])
    assert mirrored["diligence_status"] == "IN_DILIGENCE", (
        f"the counterparty mirror moves to IN_DILIGENCE, got "
        f"{mirrored['diligence_status']}"
    )
    assert mirrored["version"] == 2, (
        f"the counterparty's version increments by exactly 1, got {mirrored['version']}"
    )
    assert mirrored["approved_agreement_count"] == 0, (
        "nothing is approved yet, got "
        f"{mirrored['approved_agreement_count']}"
    )


@pytest.mark.parametrize(
    "action",
    ["APPROVE", "REJECT", "ISSUE_RFI", "RESUME_DILIGENCE", "SUSPEND", "TERMINATE"],
)
def test_undeclared_diligence_actions_out_of_draft_are_rejected(action):
    """Only starting diligence is declared out of DRAFT; every other action is
    refused.

    PRD §3.2: "Any diligence action that is not a declared transition out of the
    agreement's current status — including a repeat of an action already taken — is
    refused with `ERR_AGREEMENT_STATE_INVALID`."

    Design: Corner/state_machines/corner_undeclared_diligence_actions_rejected
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    broker = fx.register_broker()
    agreement = fx.draft_agreement(broker["id"], DESK, agreement_ref="AGR-BADACT-1")

    validate_error(
        api_client.diligence_action(
            agreement["id"], f.diligence_action_payload(action), COMPLIANCE
        ),
        ApiErrorId.ERR_AGREEMENT_STATE_INVALID.value,
    )

    unchanged = fx.read_agreement(agreement["id"])
    assert unchanged["status"] == "DRAFT", (
        f"a refused action leaves the agreement in DRAFT, got {unchanged['status']}"
    )
    assert unchanged["version"] == 1, (
        f"a refused action advances no version, got {unchanged['version']}"
    )


def test_repeating_a_diligence_action_already_taken_is_rejected():
    """A second start of diligence is a repeat of an action already taken.

    PRD §3.2: "Any diligence action that is not a declared transition out of the
    agreement's current status — including a repeat of an action already taken — is
    refused with `ERR_AGREEMENT_STATE_INVALID`."

    Design: Corner/state_machines/corner_undeclared_diligence_actions_rejected
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    broker = fx.register_broker()
    agreement = fx.draft_agreement(broker["id"], DESK, agreement_ref="AGR-REPEAT-1")
    fx.diligence_action(agreement["id"], "START_DILIGENCE", COMPLIANCE)

    validate_error(
        api_client.diligence_action(
            agreement["id"], f.diligence_action_payload("START_DILIGENCE"), COMPLIANCE
        ),
        ApiErrorId.ERR_AGREEMENT_STATE_INVALID.value,
    )

    unchanged = fx.read_agreement(agreement["id"])
    assert unchanged["status"] == "UNDER_DILIGENCE", (
        f"the refused repeat leaves the agreement UNDER_DILIGENCE, got "
        f"{unchanged['status']}"
    )
    assert unchanged["version"] == 2, (
        f"only the accepted first start advanced the version, got {unchanged['version']}"
    )
    mirror = fx.read_broker(broker["id"])
    assert mirror["diligence_status"] == "IN_DILIGENCE", (
        f"the counterparty mirror is untouched by the refusal, got "
        f"{mirror['diligence_status']}"
    )
    assert mirror["version"] == 2, (
        f"the counterparty version is untouched by the refusal, got {mirror['version']}"
    )


def test_rejected_agreement_is_terminal():
    """Nothing moves an agreement out of REJECTED.

    PRD §3.2: "Such an agreement can only be rejected, which moves it
    `UNDER_DILIGENCE → REJECTED` — also requiring an acting identifier different from
    the preparer — and sets the counterparty's `diligence_status` to `REJECTED`.
    `REJECTED` is terminal."

    PRD §3.2: "Any diligence action that is not a declared transition out of the
    agreement's current status — including a repeat of an action already taken — is
    refused with `ERR_AGREEMENT_STATE_INVALID`."

    Design: Corner/state_machines/corner_terminal_state_actions_rejected
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    broker = fx.register_broker()
    agreement = fx.draft_agreement(
        broker["id"], DESK,
        agreement_ref="AGR-TERM-1",
        aml_program_score=50,
        financial_condition_score=50,
        insurance_coverage_score=50,
        recordkeeping_score=50,
    )
    fx.diligence_action(agreement["id"], "START_DILIGENCE", COMPLIANCE)
    rejected = validate_success(
        api_client.diligence_action(
            agreement["id"], f.diligence_action_payload("REJECT"), COMPLIANCE
        )
    )
    assert rejected["status"] == "REJECTED", (
        f"a composite of 50 can only be rejected, got {rejected['status']}"
    )
    assert fx.read_broker(broker["id"])["diligence_status"] == "REJECTED", (
        "the counterparty mirror follows the agreement to REJECTED"
    )

    for action in ("START_DILIGENCE", "RESUME_DILIGENCE", "APPROVE", "SUSPEND"):
        validate_error(
            api_client.diligence_action(
                agreement["id"], f.diligence_action_payload(action), COMPLIANCE
            ),
            ApiErrorId.ERR_AGREEMENT_STATE_INVALID.value,
        )

    assert fx.read_agreement(agreement["id"])["status"] == "REJECTED", (
        "the agreement is still REJECTED after every refused action"
    )


@pytest.mark.parametrize(
    "action",
    ["ATTEST_CLASSIFICATION", "SUSPEND", "RESUME", "START_RECLASSIFICATION", "CLOSE"],
)
def test_closed_program_refuses_every_state_action(action):
    """A closed program is inert on every action, including a repeat of the close.

    PRD §3.4: "Any state action that is not a declared transition out of the program's
    current `state`, including any action at all against a `CLOSED` program, is refused
    with `ERR_PROGRAM_STATE_INVALID`."

    Design: Corner/state_machines/corner_terminal_state_actions_rejected
    """
    env = fx.setup_open_program(institution_overrides=_bank_baselines())
    closed = fx.program_state_action(env["program"]["id"], "CLOSE", DESK)
    assert closed["state"] == "CLOSED", (
        f"CLOSE moves the open program to CLOSED, got {closed['state']}"
    )

    validate_error(
        api_client.program_state_action(
            env["program"]["id"], {"action": action}, DESK
        ),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID.value,
    )

    assert fx.read_program(env["program"]["id"])["state"] == "CLOSED", (
        "the program stays CLOSED after the refused action"
    )


def test_cancelled_tranche_is_terminal_on_the_funding_dimension():
    """A cancelled tranche can never be activated afterwards.

    PRD §3.5: "Cancellation moves a tranche `PENDING → CANCELLED` and moves no money
    whatsoever, because a `PENDING` tranche has never entered any wholesale bucket."

    PRD §3.5: "`MATURED`, `WITHDRAWN_EARLY`, `ROLLED_OVER` and `CANCELLED` are all
    terminal on the funding dimension."

    PRD §3.5: "Any funding action that is not a declared transition out of the
    tranche's current `funding_status` — a second activation, or an early withdrawal of
    an already-matured tranche — is refused with `ERR_PLACEMENT_STATE_INVALID`."

    Design: Corner/state_machines/corner_terminal_state_actions_rejected
    """
    env = fx.setup_booked_placement(institution_overrides=_bank_baselines())
    cancelled = validate_success(
        api_client.funding_action(env["placement"]["id"], {"action": "CANCEL"}, DESK)
    )
    assert cancelled["funding_status"] == "CANCELLED", (
        f"CANCEL moves the pending tranche to CANCELLED, got {cancelled['funding_status']}"
    )

    validate_error(
        api_client.funding_action(env["placement"]["id"], {"action": "ACTIVATE"}, DESK),
        ApiErrorId.ERR_PLACEMENT_STATE_INVALID.value,
    )
    validate_error(
        api_client.funding_action(env["placement"]["id"], {"action": "CANCEL"}, DESK),
        ApiErrorId.ERR_PLACEMENT_STATE_INVALID.value,
    )

    after = fx.read_placement(env["placement"]["id"])
    assert after["funding_status"] == "CANCELLED", (
        f"the tranche stays CANCELLED, got {after['funding_status']}"
    )
    bank = fx.read_institution(env["institution"]["id"])
    assert bank["brokered_deposits_cents"] == 0, (
        "a cancelled tranche never entered any wholesale bucket, got "
        f"{bank['brokered_deposits_cents']}"
    )
    assert bank["total_deposits_cents"] == 30_000_000_000, (
        "the bank's deposits are unchanged by a cancellation, got "
        f"{bank['total_deposits_cents']}"
    )


def test_second_activation_of_a_live_tranche_is_rejected():
    """A tranche already ACTIVE cannot be activated again, and no money moves twice.

    PRD §3.5: "Any funding action that is not a declared transition out of the
    tranche's current `funding_status` — a second activation, or an early withdrawal of
    an already-matured tranche — is refused with `ERR_PLACEMENT_STATE_INVALID`."

    PRD §2.11: "The reconciliation is a hard invariant: after any sequence of funding
    actions, each wholesale bucket equals the sum of `principal_cents` over the bank's
    `ACTIVE` placements of the matching class."

    Design: Corner/state_machines/corner_second_activate_rejected
    """
    env = fx.setup_active_placement(
        institution_overrides=_bank_baselines(),
        placement_overrides={"principal_cents": 2_000_000_000},
    )
    assert env["placement"]["funding_status"] == "ACTIVE", "the tranche is live"

    validate_error(
        api_client.funding_action(env["placement"]["id"], {"action": "ACTIVATE"}, DESK),
        ApiErrorId.ERR_PLACEMENT_STATE_INVALID.value,
    )

    placement = fx.read_placement(env["placement"]["id"])
    assert placement["funding_status"] == "ACTIVE", (
        f"the refused action leaves the tranche ACTIVE, got {placement['funding_status']}"
    )
    bank = fx.read_institution(env["institution"]["id"])
    assert bank["brokered_deposits_cents"] == 2_000_000_000, (
        "the principal must be counted exactly once, got "
        f"{bank['brokered_deposits_cents']}"
    )
    assert bank["total_deposits_cents"] == 32_000_000_000, (
        "core 30,000,000,000 plus one live tranche of 2,000,000,000, got "
        f"{bank['total_deposits_cents']}"
    )
    program = fx.read_program(env["program"]["id"])
    assert program["outstanding_principal_cents"] == 2_000_000_000, (
        "the program's outstanding principal must be counted exactly once, got "
        f"{program['outstanding_principal_cents']}"
    )
    asserts.assert_wholesale_buckets_match_active_placements(bank, [placement])


def test_rfi_cycle_is_bounded_at_two_rounds():
    """The information-request loop may be travelled twice and no more.

    PRD §3.2: "From `UNDER_DILIGENCE` the reviewer may issue a request for
    information, moving the agreement `UNDER_DILIGENCE → RFI_ISSUED`, incrementing
    `rfi_round_count` by 1 and re-stamping `reviewed_by_user_id`; the round is admitted
    only while `rfi_round_count` is below the ceiling of two rounds, and a third attempt
    is refused with `ERR_REVIEW_ROUND_LIMIT`."

    PRD §3.2: "When the counterparty answers, resuming diligence closes the loop
    `RFI_ISSUED → UNDER_DILIGENCE` and recomputes the composite score, so the cycle
    `UNDER_DILIGENCE → RFI_ISSUED → UNDER_DILIGENCE` can be travelled at most twice."

    Design: Corner/state_machines/corner_rfi_cycle_round_limit_then_exit
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    broker = fx.register_broker()
    agreement = fx.draft_agreement(broker["id"], DESK, agreement_ref="AGR-RFI-1")
    fx.diligence_action(agreement["id"], "START_DILIGENCE", COMPLIANCE)

    first = validate_success(
        api_client.diligence_action(
            agreement["id"], f.diligence_action_payload("ISSUE_RFI"), COMPLIANCE
        )
    )
    assert first["status"] == "RFI_ISSUED", (
        f"the first request moves the agreement to RFI_ISSUED, got {first['status']}"
    )
    assert first["rfi_round_count"] == 1, (
        f"the first round counts as 1, got {first['rfi_round_count']}"
    )

    resumed = validate_success(
        api_client.diligence_action(
            agreement["id"], f.diligence_action_payload("RESUME_DILIGENCE"), COMPLIANCE
        )
    )
    assert resumed["status"] == "UNDER_DILIGENCE", (
        f"resuming closes the loop back to UNDER_DILIGENCE, got {resumed['status']}"
    )

    second = validate_success(
        api_client.diligence_action(
            agreement["id"], f.diligence_action_payload("ISSUE_RFI"), COMPLIANCE
        )
    )
    assert second["rfi_round_count"] == 2, (
        f"the second round counts as 2, got {second['rfi_round_count']}"
    )
    fx.diligence_action(agreement["id"], "RESUME_DILIGENCE", COMPLIANCE)

    validate_error(
        api_client.diligence_action(
            agreement["id"], f.diligence_action_payload("ISSUE_RFI"), COMPLIANCE
        ),
        ApiErrorId.ERR_REVIEW_ROUND_LIMIT.value,
    )

    after = fx.read_agreement(agreement["id"])
    assert after["status"] == "UNDER_DILIGENCE", (
        f"the refused third request leaves the agreement UNDER_DILIGENCE, got "
        f"{after['status']}"
    )
    assert after["rfi_round_count"] == 2, (
        f"the refused third request counts no round, got {after['rfi_round_count']}"
    )


def test_agreement_still_exits_to_approved_after_two_rfi_rounds():
    """Exhausting the information-request budget does not block the approval exit.

    PRD §3.2: "When the composite score is at least 70 and `aml_program_score` is at
    least 60, the agreement becomes `APPROVED`, the counterparty's `diligence_status`
    becomes `APPROVED` and `approved_agreement_count` increases by 1."

    PRD §3.2: "When the counterparty answers, resuming diligence closes the loop
    `RFI_ISSUED → UNDER_DILIGENCE` and recomputes the composite score, so the cycle
    `UNDER_DILIGENCE → RFI_ISSUED → UNDER_DILIGENCE` can be travelled at most twice."

    Design: Corner/state_machines/corner_rfi_cycle_round_limit_then_exit
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    broker = fx.register_broker()
    agreement = fx.draft_agreement(broker["id"], DESK, agreement_ref="AGR-RFI-2")
    fx.diligence_action(agreement["id"], "START_DILIGENCE", COMPLIANCE)
    for _ in range(2):
        fx.diligence_action(agreement["id"], "ISSUE_RFI", COMPLIANCE)
        fx.diligence_action(agreement["id"], "RESUME_DILIGENCE", COMPLIANCE)

    approved = validate_success(
        api_client.diligence_action(
            agreement["id"], f.diligence_action_payload("APPROVE"), COMPLIANCE
        )
    )

    assert approved["status"] == "APPROVED", (
        f"the approval exit is still available, got {approved['status']}"
    )
    assert approved["rfi_round_count"] == 2, (
        f"both rounds remain on the record, got {approved['rfi_round_count']}"
    )
    counterparty = fx.read_broker(broker["id"])
    assert counterparty["diligence_status"] == "APPROVED", (
        f"the counterparty mirror follows to APPROVED, got "
        f"{counterparty['diligence_status']}"
    )
    assert counterparty["approved_agreement_count"] == 1, (
        f"approved_agreement_count rises to 1, got "
        f"{counterparty['approved_agreement_count']}"
    )


def test_program_suspension_cancels_pending_tranches_only():
    """Suspending an open program cancels its pending money and leaves live money
    alone.

    PRD §3.4: "Suspension moves an open program `OPEN_FOR_PLACEMENT → SUSPENDED` and
    cancels every placement of that program whose `funding_status` is `PENDING`, in
    placement `created_at` ascending order."

    PRD §3.5: "Cancellation also arrives without being asked for, through the program
    suspension and closure cascades and through the counterparty suspension cascade of
    §3.2."

    Design: Corner/state_machines/corner_program_suspend_cascade_cancels_pending_only
    """
    env = fx.setup_active_placement(
        institution_overrides=_bank_baselines(),
        placement_overrides={"principal_cents": 1_000_000_000},
    )
    live = env["placement"]
    pending_first = fx.book_placement(
        env["program"]["id"], DESK, principal_cents=1_000_000_000
    )
    pending_second = fx.book_placement(
        env["program"]["id"], DESK, principal_cents=1_000_000_000
    )

    suspended = validate_success(
        api_client.program_state_action(
            env["program"]["id"], {"action": "SUSPEND"}, DESK
        )
    )
    assert suspended["state"] == "SUSPENDED", (
        f"SUSPEND moves the open program to SUSPENDED, got {suspended['state']}"
    )

    for label, placement_id in (
        ("the first pending tranche", pending_first["id"]),
        ("the second pending tranche", pending_second["id"]),
    ):
        cancelled = fx.read_placement(placement_id)
        assert cancelled["funding_status"] == "CANCELLED", (
            f"{label} must be cancelled by the cascade, got {cancelled['funding_status']}"
        )
        assert cancelled["settlement_date"] is None, (
            f"{label} settles nothing, got {cancelled['settlement_date']}"
        )

    still_live = fx.read_placement(live["id"])
    assert still_live["funding_status"] == "ACTIVE", (
        f"the live tranche is untouched by the suspension, got "
        f"{still_live['funding_status']}"
    )
    program_after = fx.read_program(env["program"]["id"])
    assert program_after["outstanding_principal_cents"] == 1_000_000_000, (
        "only the live tranche is outstanding, got "
        f"{program_after['outstanding_principal_cents']}"
    )
    bank_after = fx.read_institution(env["institution"]["id"])
    assert bank_after["brokered_deposits_cents"] == 1_000_000_000, (
        "cancelling pending money moves no balances, got "
        f"{bank_after['brokered_deposits_cents']}"
    )
    asserts.assert_wholesale_buckets_match_active_placements(bank_after, [still_live])


def test_capital_downgrade_caps_the_bank_and_flags_the_breaching_tranche():
    """A supervisory downgrade recomputes every program ceiling and flags live money
    now paying above it.

    PRD §3.1: "A successful re-categorisation re-derives `rate_cap_regime` and then
    cascades. Every one of the bank's programs whose `state` is not `CLOSED` has its
    `effective_cap_bps` recomputed and its `version` incremented by exactly 1, processed
    in `created_at` ascending order; because a program's version moved, each program's
    standing determination is now stale for the purpose of booking new deposits, which
    is what §3.5 reports as `ERR_CLASSIFICATION_STALE` until the program is
    re-classified."

    PRD §3.1: "Every `ACTIVE` placement of the bank is then re-measured against its
    program's new ceiling, and each placement whose rate now sits above the ceiling has
    its `compliance_status` moved to `FLAGGED`."

    PRD §3.1: "The national leg is the publication's `published_national_rate_bps` plus
    75 basis points."

    Design: Corner/state_machines/corner_capital_downgrade_flags_active_placement_cross_entity
    """
    env = fx.setup_active_placement(
        institution_overrides=_bank_baselines(),
        placement_overrides={"principal_cents": 1_000_000_000, "rate_bps": 600},
    )
    before = fx.read_program(env["program"]["id"])
    assert before["effective_cap_bps"] is None, (
        "an EXEMPT bank's program carries no ceiling, got "
        f"{before['effective_cap_bps']}"
    )
    assert before["version"] == 2, (
        f"creation plus one determination puts the program at version 2, got "
        f"{before['version']}"
    )

    bank = fx.change_capital_category(
        env["institution"]["id"], "ADEQUATELY_CAPITALIZED", None, EXAMINER
    )

    assert bank["capital_category"] == "ADEQUATELY_CAPITALIZED", (
        f"the supervisory category is recorded, got {bank['capital_category']}"
    )
    assert bank["rate_cap_regime"] == "CAPPED", (
        f"anything other than WELL_CAPITALIZED is CAPPED, got {bank['rate_cap_regime']}"
    )

    program_after = fx.read_program(env["program"]["id"])
    assert program_after["effective_cap_bps"] == 475, (
        "the published 400 basis points plus 75 is the new ceiling, got "
        f"{program_after['effective_cap_bps']}"
    )
    assert program_after["version"] == 3, (
        f"the cascade increments the program version by exactly 1, got "
        f"{program_after['version']}"
    )

    placement_after = fx.read_placement(env["placement"]["id"])
    assert placement_after["compliance_status"] == "FLAGGED", (
        "a live tranche paying 600 against a ceiling of 475 must be FLAGGED, got "
        f"{placement_after['compliance_status']}"
    )
    assert placement_after["funding_status"] == "ACTIVE", (
        "the funding dimension is untouched by the surveillance cascade, got "
        f"{placement_after['funding_status']}"
    )


def test_capital_downgrade_leaves_a_compliant_tranche_unflagged():
    """The same downgrade leaves live money at or below the new ceiling alone.

    PRD §3.1: "Every `ACTIVE` placement of the bank is then re-measured against its
    program's new ceiling, and each placement whose rate now sits above the ceiling has
    its `compliance_status` moved to `FLAGGED`."

    PRD §3.1: "Every one of the bank's programs whose `state` is not `CLOSED` has its
    `effective_cap_bps` recomputed and its `version` incremented by exactly 1, processed
    in `created_at` ascending order"

    Design: Corner/state_machines/corner_capital_downgrade_flags_active_placement_cross_entity
    """
    env = fx.setup_active_placement(
        institution_overrides=_bank_baselines(),
        placement_overrides={"principal_cents": 1_000_000_000, "rate_bps": 470},
    )

    bank = fx.change_capital_category(
        env["institution"]["id"], "UNDERCAPITALIZED", None, EXAMINER
    )
    assert bank["rate_cap_regime"] == "CAPPED", (
        f"the downgraded bank is CAPPED, got {bank['rate_cap_regime']}"
    )

    program_after = fx.read_program(env["program"]["id"])
    assert program_after["effective_cap_bps"] == 475, (
        f"the recomputed ceiling is 400 plus 75 basis points, got "
        f"{program_after['effective_cap_bps']}"
    )
    assert program_after["version"] == 3, (
        f"the cascade increments the program version by exactly 1, got "
        f"{program_after['version']}"
    )

    placement_after = fx.read_placement(env["placement"]["id"])
    assert placement_after["compliance_status"] == "UNREVIEWED", (
        "470 basis points sits below the 475 ceiling, so nothing is flagged, got "
        f"{placement_after['compliance_status']}"
    )
    assert placement_after["funding_status"] == "ACTIVE", (
        f"the tranche is still live, got {placement_after['funding_status']}"
    )
