"""Declared transitions, undeclared transitions, terminal states and side effects.

Every entity here carries an explicit transition table. These tests exercise the
initial states, the transitions the contract declares along with the side effects
each one performs on other rows, and the requests the table does not declare at
all — a skipped rung, a replayed action, or a move out of a terminal state.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    CLEARANCE_CLEARED,
    CLEARANCE_FLAGGED,
    CLEARANCE_PENDING,
    CLEARANCE_SUSPENDED,
    CONVERSION_STATUS_ATTESTED,
    CONVERSION_STATUS_NOT_STARTED,
    CONVERSION_STATUS_NOTICES_ISSUED,
    CONVERSION_STATUS_WITHDRAWN,
    DEAL_STATUS_ABANDONED,
    DEAL_STATUS_BOARD_REVIEW,
    DEAL_STATUS_CLOSED,
    DEAL_STATUS_DILIGENCE,
    DEAL_STATUS_SIGNED,
    DEAL_STATUS_SOURCING,
    DEFAULT_CLOCK_INSTANT,
    DISPOSITION_ASSUMED,
    DISPOSITION_ESCROWED,
    DISPOSITION_EXCLUDED,
    DISPOSITION_INDEMNIFIED,
    EMPLOYMENT_EMPLOYED,
    EMPLOYMENT_OFFERED,
    EMPLOYMENT_PROSPECTIVE,
    FULL_NOTICE_COVERAGE_BPS,
    MIN_NOTICE_LEAD_DAYS,
    NOVATION_ACTION_NOVATE,
    NOVATION_ACTION_RECORD_CONSENT,
    NOVATION_ACTION_SEND_NOTICE,
    NOVATION_NOT_REQUESTED,
    OFFER_STATUS_DRAFT,
    OFFER_STATUS_EXTENDED,
    OFFER_STATUS_RESCINDED,
    OPINION_STATUS_ACCEPTED,
    OPINION_STATUS_SUBMITTED,
    OPINION_STATUS_SUPERSEDED,
    PACKAGE_STATUS_APPROVED,
    PACKAGE_STATUS_DENIED,
    PACKAGE_STATUS_DRAFT,
    PACKAGE_STATUS_IN_REVIEW,
    PACKAGE_STATUS_SUBMITTED,
    PACKAGE_STATUS_WITHDRAWN,
    PLAN_STATUS_APPROVED,
    PLAN_STATUS_EXECUTED,
    POSTURE_AT_RISK,
    POSTURE_BLOCKED,
    POSTURE_READY,
    PROVIDER_BASED_UPLIFT_BPS,
    ROLE_CODE_BILLER,
    STANDARD_FMV_CONCLUDED_CENTS,
    STANDARD_PLAN_PERCENTILE,
    STANDARD_PLAN_TOTAL_CENTS,
    TASK_STATUS_COMPLETE,
    TASK_STATUS_FAILED,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_OPEN,
    USER_COMPLIANCE_OFFICER,
    USER_COMPLIANCE_OFFICER_ALT,
    USER_INTEGRATION_MANAGER,
    USER_VALUATION_ANALYST,
)
from test_helpers.fixtures import (
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_ALT,
    DEAL_LEAD,
    INTEGRATION_MANAGER,
    VALUATION_ANALYST,
    accepted_market_fmv,
    advance_deal_status,
    approve_plan,
    board_review_deal,
    create_acquisition,
    create_conversion,
    create_liability,
    create_offer,
    create_package,
    create_payer_contract,
    create_physician,
    create_plan,
    create_task,
    diligence_deal,
    execute_plan,
    file_cr_opinion,
    file_income_fmv,
    file_market_fmv,
    read_acquisition,
    reset_clock,
    read_task,
    set_clearance,
    set_clock,
    set_disposition,
    set_package_status,
    set_task_status,
    submit_opinion,
    submit_plan,
)

ABANDON_REASON = "Seller withdrew from the letter of intent."
CASCADE_ABANDON_REASON = "Regulatory approval withdrawn."
FAILURE_REASON = "Two clinicians missed the training window."
INCOME_CONCLUDED_CENTS = 2_167_511_341

# A BILLER offer drafted for 5,282,350 harmonises to 5,572,880 and earns 557,288.
POOL_TOTAL_CENTS = 3_000_000
BILLER_LEGACY_WAGE_CENTS = 5_282_350
BILLER_PTO_HOURS = 104
BILLER_SERVICE_MONTHS = 84
BILLER_OFFERED_WAGE_CENTS = 5_572_880
BILLER_BONUS_CENTS = 557_288
OFFER_EXPIRES_ON = "2026-09-15"
DAY_AFTER_EXPIRY_INSTANT = "2026-09-16T00:00:00Z"
ZERO_COVERAGE_PCT = 0.00

LEASE_EXPOSURE_CENTS = 2_500_000
ESCROW_TOTAL_CENTS = 10_000_000
ESCROW_AVAILABLE_AFTER_LEASE_CENTS = 7_500_000

PACKAGE_FILED_ON = "2026-08-03"
AUGUST_CYCLE_KEY = "2026-08-15"
COMMERCIAL_PROJECTED_EFFECTIVE_ON = "2026-11-01"


def test_a_new_deal_starts_in_sourcing_with_its_clearance_still_pending(api: ApiClient):
    """Three independent dimensions, each at its own declared starting value.

    PRD: "A newly opened acquisition sits in `deal_status` `SOURCING` with
    `compliance_clearance` `PENDING` and `readiness_posture` `BLOCKED`, carries
    `hr_staffing_coverage_pct` of 0.00, and has `tail_premium_cents` not yet
    computed."

    Design: Corner/state_machines/acquisition_starts_in_sourcing_and_pending_clearance
    """
    reset_clock(api)

    acquisition = create_acquisition(api)

    a.assert_status(acquisition, DEAL_STATUS_SOURCING, "deal_status")
    assert acquisition["compliance_clearance"] == CLEARANCE_PENDING
    assert acquisition["readiness_posture"] == POSTURE_BLOCKED

    flagged = set_clearance(api, acquisition["id"], CLEARANCE_FLAGGED)
    assert flagged["compliance_clearance"] == CLEARANCE_FLAGGED
    a.assert_status(flagged, DEAL_STATUS_SOURCING, "deal_status")
    assert flagged["readiness_posture"] == POSTURE_BLOCKED


def test_leaving_sourcing_requires_at_least_one_registered_physician(api: ApiClient):
    """The precondition is substantive, and satisfying it makes the same request pass.

    PRD: "Advancing from `SOURCING` to `DILIGENCE` is the `DealLead`'s first
    workflow step and its only precondition is substantive: at least one physician
    must already be registered against the acquisition."

    Design: Corner/state_machines/acquisition_diligence_without_any_physician_rejected
    """
    reset_clock(api)
    acquisition = create_acquisition(api)

    rejected = api.set_acquisition_status(
        acquisition["id"], f.acquisition_status_payload(DEAL_STATUS_DILIGENCE), DEAL_LEAD
    )

    validate_error(rejected, ApiErrorId.INVALID_STATE_TRANSITION, 409)
    unchanged = read_acquisition(api, acquisition["id"])
    a.assert_status(unchanged, DEAL_STATUS_SOURCING, "deal_status")
    a.assert_version_unchanged(acquisition, unchanged)

    create_physician(api, acquisition["id"])
    advanced = validate_success(
        api.set_acquisition_status(
            acquisition["id"], f.acquisition_status_payload(DEAL_STATUS_DILIGENCE), DEAL_LEAD
        )
    )
    a.assert_status(advanced, DEAL_STATUS_DILIGENCE, "deal_status")


def test_the_workflow_ladder_cannot_be_skipped_out_of_sourcing(api: ApiClient):
    """Undeclared targets are refused at the sequencing rank before any business rule.

    PRD: "**State transition legality** — the requested transition is declared for
    the entity's current state, on every action endpoint. This rank absorbs every
    terminal-state lockdown and every repeat of an already-applied transition, and
    it outranks every business rule below it: an action that is both out of
    sequence and economically impossible reports the sequencing failure."

    Design: Corner/state_machines/acquisition_sourcing_to_signed_is_not_a_declared_transition_rejected
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    create_physician(api, acquisition["id"])

    for target in (
        DEAL_STATUS_SIGNED,
        DEAL_STATUS_BOARD_REVIEW,
        DEAL_STATUS_CLOSED,
        DEAL_STATUS_SOURCING,
    ):
        rejected = api.set_acquisition_status(
            acquisition["id"], f.acquisition_status_payload(target), DEAL_LEAD
        )
        validate_error(rejected, ApiErrorId.INVALID_STATE_TRANSITION, 409)

    unchanged = read_acquisition(api, acquisition["id"])
    a.assert_status(unchanged, DEAL_STATUS_SOURCING, "deal_status")
    a.assert_fields_null(unchanged, "closed_at", "abandoned_reason")


def test_an_abandoned_deal_accepts_no_further_status_request(api: ApiClient):
    """Terminal means terminal: not a re-abandonment, not a return to the start.

    PRD: "`CLOSED` and `ABANDONED` are the deal's terminal workflow states."

    Design: Corner/state_machines/acquisition_abandoned_is_terminal_and_locks_status_changes
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    abandoned = advance_deal_status(
        api, acquisition["id"], DEAL_STATUS_ABANDONED, abandoned_reason=ABANDON_REASON
    )
    a.assert_status(abandoned, DEAL_STATUS_ABANDONED, "deal_status")

    for target in (DEAL_STATUS_DILIGENCE, DEAL_STATUS_ABANDONED, DEAL_STATUS_SOURCING):
        rejected = api.set_acquisition_status(
            acquisition["id"],
            f.acquisition_status_payload(target, abandoned_reason=ABANDON_REASON),
            DEAL_LEAD,
        )
        validate_error(rejected, ApiErrorId.INVALID_STATE_TRANSITION, 409)

    unchanged = read_acquisition(api, acquisition["id"])
    a.assert_status(unchanged, DEAL_STATUS_ABANDONED, "deal_status")
    assert unchanged["abandoned_reason"] == ABANDON_REASON
    a.assert_fields_null(unchanged, "closed_at")


def test_replaying_the_submit_on_an_opinion_is_refused(api: ApiClient):
    """There is no self-edge, so the replay fails rather than re-stamping the row.

    PRD: "An opinion's lifecycle runs `DRAFT → SUBMITTED → ACCEPTED`, with
    `REJECTED` and `SUPERSEDED` as its terminal states."

    Design: Corner/state_machines/valuation_opinion_second_submit_rejected
    """
    reset_clock(api)
    deal = diligence_deal(api)
    opinion = file_market_fmv(api, deal["acquisition"]["id"])
    submitted = submit_opinion(api, opinion["id"])
    a.assert_status(submitted, OPINION_STATUS_SUBMITTED)

    replayed = api.set_valuation_opinion_status(
        opinion["id"], f.opinion_status_payload(OPINION_STATUS_SUBMITTED), VALUATION_ANALYST
    )

    validate_error(replayed, ApiErrorId.INVALID_STATE_TRANSITION, 409)
    unchanged = validate_success(api.get_valuation_opinion(opinion["id"], VALUATION_ANALYST))
    a.assert_status(unchanged, OPINION_STATUS_SUBMITTED)
    a.assert_fields_null(unchanged, "accepted_by_user_id")
    a.assert_money_equals(
        unchanged["concluded_value_cents"], STANDARD_FMV_CONCLUDED_CENTS, "concluded_value_cents"
    )
    assert unchanged["expires_on"] == "2027-08-01"


def test_accepting_an_opinion_records_the_officer_and_leaves_it_unpinned(api: ApiClient):
    """Acceptance writes exactly one audit field; pinning belongs to board review.

    PRD: "On acceptance the caller's `X-User-ID` is stored in
    `accepted_by_user_id`, which is the field the compensation-approval
    segregation check later reads."

    Design: Corner/state_machines/valuation_opinion_accept_records_accepter_and_leaves_pin_unset
    """
    reset_clock(api)
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    opinion = file_market_fmv(api, acquisition_id)
    submit_opinion(api, opinion["id"])

    accepted = validate_success(
        api.set_valuation_opinion_status(
            opinion["id"],
            f.opinion_status_payload(
                OPINION_STATUS_ACCEPTED,
                review_note="Multiple supported by three regional transactions.",
            ),
            COMPLIANCE_OFFICER,
        )
    )

    a.assert_status(accepted, OPINION_STATUS_ACCEPTED)
    assert accepted["accepted_by_user_id"] == USER_COMPLIANCE_OFFICER
    assert accepted["prepared_by_user_id"] == USER_VALUATION_ANALYST
    assert accepted["is_pinned"] is False

    still_diligence = read_acquisition(api, acquisition_id)
    a.assert_status(still_diligence, DEAL_STATUS_DILIGENCE, "deal_status")
    a.assert_fields_null(still_diligence, "purchase_price_cents")

    rival = file_market_fmv(api, acquisition_id)
    submit_opinion(api, rival["id"])
    second_accept = api.set_valuation_opinion_status(
        rival["id"], f.opinion_status_payload(OPINION_STATUS_ACCEPTED), COMPLIANCE_OFFICER_ALT
    )
    validate_error(second_accept, ApiErrorId.INVALID_STATE_TRANSITION, 409)


def test_abandoning_a_deal_supersedes_only_its_unaccepted_opinions(api: ApiClient):
    """The cascade is conditional on the child's state, not blanket.

    PRD: "`DILIGENCE → ABANDONED` also has no precondition, stores
    `abandoned_reason`, sets every valuation opinion on the deal that is still in
    `DRAFT` or `SUBMITTED` to `SUPERSEDED`, and sets every staff transition offer
    in `EXTENDED` to `RESCINDED`, releasing each one's `retention_bonus_cents`
    from `retention_pool_committed_cents` back into the available balance."

    Design: Corner/state_machines/acquisition_abandonment_supersedes_open_valuation_opinions
    """
    reset_clock(api)
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    accepted_fmv = accepted_market_fmv(api, acquisition_id, officer_headers=COMPLIANCE_OFFICER)
    submitted_cr = file_cr_opinion(api, acquisition_id)
    submit_opinion(api, submitted_cr["id"])
    drafted_fmv = file_income_fmv(api, acquisition_id)

    abandoned = advance_deal_status(
        api, acquisition_id, DEAL_STATUS_ABANDONED, abandoned_reason=CASCADE_ABANDON_REASON
    )

    a.assert_status(abandoned, DEAL_STATUS_ABANDONED, "deal_status")
    assert abandoned["abandoned_reason"] == CASCADE_ABANDON_REASON

    superseded_draft = validate_success(
        api.get_valuation_opinion(drafted_fmv["id"], VALUATION_ANALYST)
    )
    a.assert_status(superseded_draft, OPINION_STATUS_SUPERSEDED)
    a.assert_money_equals(
        superseded_draft["concluded_value_cents"],
        INCOME_CONCLUDED_CENTS,
        "concluded_value_cents",
    )

    superseded_submitted = validate_success(
        api.get_valuation_opinion(submitted_cr["id"], VALUATION_ANALYST)
    )
    a.assert_status(superseded_submitted, OPINION_STATUS_SUPERSEDED)

    untouched = validate_success(api.get_valuation_opinion(accepted_fmv["id"], VALUATION_ANALYST))
    a.assert_status(untouched, OPINION_STATUS_ACCEPTED)

    a.assert_retention_pool(abandoned, POOL_TOTAL_CENTS, 0, POOL_TOTAL_CENTS)


def test_approving_a_plan_walks_the_physician_to_offered(api: ApiClient):
    """One plan transition mutates a different entity and records its approver.

    PRD: "On approval the caller's `X-User-ID` is stored in `approved_by_user_id`,
    the linked physician's `employment_status` is recomputed to `OFFERED`, and any
    other compensation plan for the same `physician_id` that is currently in
    `EXECUTED` is set to `SUPERSEDED` — a physician may hold only one live
    executed arrangement."

    Design: Corner/state_machines/comp_plan_approval_then_execution_walks_physician_to_employed
    """
    reset_clock(api)
    deal = board_review_deal(api)
    physician_id = deal["physician"]["id"]
    assert deal["physician"]["employment_status"] == EMPLOYMENT_PROSPECTIVE
    pinned = validate_success(api.get_valuation_opinion(deal["fmv"]["id"], VALUATION_ANALYST))
    assert pinned["is_pinned"] is True
    a.assert_money_equals(
        deal["acquisition"]["purchase_price_cents"],
        STANDARD_FMV_CONCLUDED_CENTS,
        "purchase_price_cents",
    )

    plan = create_plan(api, deal["acquisition"]["id"], physician_id)
    submit_plan(api, plan["id"])
    approved = approve_plan(api, plan["id"], COMPLIANCE_OFFICER_ALT)

    a.assert_status(approved, PLAN_STATUS_APPROVED)
    assert approved["approved_by_user_id"] == USER_COMPLIANCE_OFFICER_ALT
    a.assert_money_equals(
        approved["projected_total_cash_comp_cents"],
        STANDARD_PLAN_TOTAL_CENTS,
        "projected_total_cash_comp_cents",
    )
    a.assert_percentage_equals(
        approved["benchmark_percentile"], STANDARD_PLAN_PERCENTILE, "benchmark_percentile"
    )

    offered = validate_success(api.get_physician(physician_id, DEAL_LEAD))
    assert offered["employment_status"] == EMPLOYMENT_OFFERED


def test_executing_a_plan_stamps_the_instant_and_employs_the_physician(api: ApiClient):
    """The second transition moves the same physician on to the employed reading.

    PRD: "On execution `executed_at` is stamped with the current logical instant
    and the physician's `employment_status` is recomputed to `EMPLOYED`."

    Design: Corner/state_machines/comp_plan_approval_then_execution_walks_physician_to_employed
    """
    reset_clock(api)
    deal = board_review_deal(api)
    physician_id = deal["physician"]["id"]
    plan = create_plan(api, deal["acquisition"]["id"], physician_id)
    submit_plan(api, plan["id"])
    approve_plan(api, plan["id"], COMPLIANCE_OFFICER_ALT)

    executed = execute_plan(api, plan["id"], physician_id)

    a.assert_status(executed, PLAN_STATUS_EXECUTED)
    a.assert_instant_equals(executed["executed_at"], DEFAULT_CLOCK_INSTANT, "executed_at")

    employed = validate_success(api.get_physician(physician_id, DEAL_LEAD))
    assert employed["employment_status"] == EMPLOYMENT_EMPLOYED


def test_no_payer_notice_goes_out_before_the_board_has_reviewed(api: ApiClient):
    """The novation ladder has no entry point while the deal is still sourcing.

    PRD: "`SEND_NOTICE` moves `NOT_REQUESTED → NOTICE_SENT`, requires the parent
    acquisition's `deal_status` to be `BOARD_REVIEW` or `SIGNED`, and stamps
    `notice_sent_on` with the current logical date."

    Design: Corner/state_machines/payer_novation_send_notice_before_board_review_rejected
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    contract = create_payer_contract(api, acquisition["id"])
    assert contract["novation_status"] == NOVATION_NOT_REQUESTED

    for action in (
        NOVATION_ACTION_SEND_NOTICE,
        NOVATION_ACTION_RECORD_CONSENT,
        NOVATION_ACTION_NOVATE,
    ):
        rejected = api.act_on_novation(
            contract["id"], f.novation_payload(action), INTEGRATION_MANAGER
        )
        validate_error(rejected, ApiErrorId.INVALID_STATE_TRANSITION, 409)

    unchanged = validate_success(api.get_payer_contract(contract["id"], INTEGRATION_MANAGER))
    assert unchanged["novation_status"] == NOVATION_NOT_REQUESTED
    a.assert_fields_null(unchanged, "notice_sent_on", "consent_received_on")


def test_a_checklist_line_cannot_be_completed_straight_out_of_open(api: ApiClient):
    """Completion has exactly one declared source state, and OPEN is not it.

    PRD: "Completing it, `IN_PROGRESS → COMPLETE`, is available to the same two
    roles and carries two conditional preconditions: when `task_code` is
    `HR_STAFFING_PLAN`, the acquisition's `hr_staffing_coverage_pct` must be at
    least 80.00; when `task_code` is `IT_DATA_MIGRATION`, every migration batch on
    the acquisition must be in `RECONCILED` or `ABORTED`, or the request fails with
    `ERR_MIGRATION_INCOMPLETE`."

    Design: Corner/state_machines/readiness_task_complete_directly_from_open_rejected
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    task = create_task(api, acquisition["id"])
    a.assert_status(task, TASK_STATUS_OPEN)

    for target in (TASK_STATUS_COMPLETE, TASK_STATUS_FAILED):
        rejected = api.set_readiness_task_status(
            task["id"],
            f.task_status_payload(target, failure_reason=FAILURE_REASON),
            INTEGRATION_MANAGER,
        )
        validate_error(rejected, ApiErrorId.INVALID_STATE_TRANSITION, 409)

    unchanged = read_task(api, task["id"])
    a.assert_status(unchanged, TASK_STATUS_OPEN)
    a.assert_fields_null(unchanged, "verified_by_user_id")
    at_risk = read_acquisition(api, acquisition["id"])
    assert at_risk["readiness_posture"] == POSTURE_AT_RISK


def test_a_withdrawn_package_is_dead_but_does_not_block_a_replacement(api: ApiClient):
    """Terminal for the row, yet outside the set the duplicate guard protects.

    PRD: "At most one live package may exist for a given physician-and-payer pair:
    if another package for the same `physician_id` and `payer_contract_id` is in
    `DRAFT`, `SUBMITTED`, `IN_REVIEW`, or `APPROVED`, the create is rejected with
    `ERR_DUPLICATE_CREDENTIALING_PACKAGE`."

    Design: Corner/state_machines/credentialing_package_withdrawn_is_terminal_and_frees_its_seat
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    physician = create_physician(api, acquisition["id"])
    contract = create_payer_contract(api, acquisition["id"])
    package = create_package(
        api, acquisition["id"], physician["id"], contract["id"], submitted_on=PACKAGE_FILED_ON
    )
    a.assert_status(package, PACKAGE_STATUS_DRAFT)
    withdrawn = set_package_status(api, package["id"], PACKAGE_STATUS_WITHDRAWN)
    a.assert_status(withdrawn, PACKAGE_STATUS_WITHDRAWN)

    for target in (
        PACKAGE_STATUS_SUBMITTED,
        PACKAGE_STATUS_IN_REVIEW,
        PACKAGE_STATUS_APPROVED,
        PACKAGE_STATUS_DENIED,
    ):
        rejected = api.set_credentialing_package_status(
            package["id"], f.package_status_payload(target), INTEGRATION_MANAGER
        )
        validate_error(rejected, ApiErrorId.INVALID_STATE_TRANSITION, 409)

    dead = validate_success(api.get_credentialing_package(package["id"], INTEGRATION_MANAGER))
    a.assert_status(dead, PACKAGE_STATUS_WITHDRAWN)
    assert dead["committee_cycle_key"] == AUGUST_CYCLE_KEY
    assert dead["projected_effective_on"] == COMMERCIAL_PROJECTED_EFFECTIVE_ON

    replacement = validate_success(
        api.create_credentialing_package(
            f.credentialing_package_payload(
                acquisition["id"],
                physician["id"],
                contract["id"],
                submitted_on=PACKAGE_FILED_ON,
            ),
            INTEGRATION_MANAGER,
        ),
        201,
    )
    a.assert_status(replacement, PACKAGE_STATUS_DRAFT)
    assert replacement["id"] != package["id"]


def test_a_lapsed_draft_offer_cannot_be_extended_but_can_be_rescinded(api: ApiClient):
    """The pool is never touched, and the row's only remaining exit is a rescission.

    PRD: "The offer's `offer_expires_on` must not be before the current logical
    date — an offer that has already lapsed cannot be extended."

    Design: Corner/state_machines/staff_offer_extend_after_expiry_date_rejected
    """
    reset_clock(api)
    deal = diligence_deal(api, retention_pool_total_cents=POOL_TOTAL_CENTS)
    acquisition_id = deal["acquisition"]["id"]
    offer = create_offer(
        api,
        acquisition_id,
        staff_member_name="Dana Whitfield",
        role_code=ROLE_CODE_BILLER,
        legacy_annual_wage_cents=BILLER_LEGACY_WAGE_CENTS,
        legacy_pto_hours=BILLER_PTO_HOURS,
        credited_service_months=BILLER_SERVICE_MONTHS,
        offer_expires_on=OFFER_EXPIRES_ON,
    )
    set_clock(api, DAY_AFTER_EXPIRY_INSTANT)

    rejected = api.set_staff_transition_offer_status(
        offer["id"], f.offer_status_payload(OFFER_STATUS_EXTENDED), INTEGRATION_MANAGER
    )

    validate_error(rejected, ApiErrorId.INVALID_STATE_TRANSITION, 409)
    unchanged = validate_success(
        api.get_staff_transition_offer(offer["id"], INTEGRATION_MANAGER)
    )
    a.assert_status(unchanged, OFFER_STATUS_DRAFT)
    a.assert_fields_null(unchanged, "extended_on")
    a.assert_money_equals(
        unchanged["offered_annual_wage_cents"],
        BILLER_OFFERED_WAGE_CENTS,
        "offered_annual_wage_cents",
    )
    a.assert_money_equals(
        unchanged["retention_bonus_cents"], BILLER_BONUS_CENTS, "retention_bonus_cents"
    )

    ledger = read_acquisition(api, acquisition_id)
    a.assert_retention_pool(ledger, POOL_TOTAL_CENTS, 0, POOL_TOTAL_CENTS)
    a.assert_percentage_equals(
        ledger["hr_staffing_coverage_pct"], ZERO_COVERAGE_PCT, "hr_staffing_coverage_pct"
    )

    rescinded = validate_success(
        api.set_staff_transition_offer_status(
            offer["id"],
            f.offer_status_payload(OFFER_STATUS_RESCINDED, note="Offer lapsed unextended."),
            INTEGRATION_MANAGER,
        )
    )
    a.assert_status(rescinded, OFFER_STATUS_RESCINDED)


def test_a_sourcing_deal_cannot_attest_a_site_however_complete_its_notices(api: ApiClient):
    """The gate is the parent's workflow state, not anything on the conversion row.

    PRD: "Attesting the provider-based criteria, `NOT_STARTED → ATTESTED`, requires
    the parent acquisition's `deal_status` to be `BOARD_REVIEW`, `SIGNED`, or
    `CLOSED`, and stamps `attested_on` with the current logical date."

    Design: Corner/state_machines/billing_conversion_attest_in_sourcing_rejected
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    conversion = create_conversion(api, acquisition["id"])
    a.assert_status(conversion, CONVERSION_STATUS_NOT_STARTED)
    assert conversion["notice_coverage_bps"] == FULL_NOTICE_COVERAGE_BPS
    assert conversion["notice_lead_days"] == MIN_NOTICE_LEAD_DAYS
    assert conversion["provider_based_uplift_bps"] == PROVIDER_BASED_UPLIFT_BPS

    for target in (CONVERSION_STATUS_ATTESTED, CONVERSION_STATUS_NOTICES_ISSUED):
        rejected = api.set_billing_conversion_status(
            conversion["id"], f.conversion_status_payload(target), INTEGRATION_MANAGER
        )
        validate_error(rejected, ApiErrorId.INVALID_STATE_TRANSITION, 409)

    unchanged = validate_success(
        api.get_billing_conversion(conversion["id"], INTEGRATION_MANAGER)
    )
    a.assert_status(unchanged, CONVERSION_STATUS_NOT_STARTED)
    a.assert_fields_null(unchanged, "attested_on")

    withdrawn = validate_success(
        api.set_billing_conversion_status(
            conversion["id"],
            f.conversion_status_payload(CONVERSION_STATUS_WITHDRAWN),
            INTEGRATION_MANAGER,
        )
    )
    a.assert_status(withdrawn, CONVERSION_STATUS_WITHDRAWN)


def test_escrowed_money_can_only_leave_by_the_one_declared_unwind(api: ApiClient):
    """Reallocating an escrowed item sideways is undeclared; releasing it is not.

    PRD: "Finally, `ESCROWED → EXCLUDED` releases an escrowed item: it checks the
    structure-and-category legality for `EXCLUDED`, subtracts the item's
    `escrowed_amount_cents` from `escrow_committed_cents`, adds the same amount
    back to `escrow_available_cents`, and resets the item's own
    `escrowed_amount_cents` to 0."

    Design: Corner/state_machines/liability_item_escrowed_to_assumed_is_not_declared_rejected
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    # The cap is supplied at creation so the INDEMNIFIED probe below clears the
    # schema rank — PRD ranks "`indemnity_cap_cents` present and at least
    # `estimated_amount_cents` when a disposition of `INDEMNIFIED` is requested"
    # at rank 3, above state-transition legality at rank 14 — and the request is
    # therefore judged on the undeclared transition rather than on a missing cap.
    item = create_liability(
        api,
        acquisition["id"],
        estimated_amount_cents=LEASE_EXPOSURE_CENTS,
        indemnity_cap_cents=LEASE_EXPOSURE_CENTS,
    )
    escrowed = set_disposition(api, item["id"], DISPOSITION_ESCROWED)
    a.assert_money_equals(
        escrowed["escrowed_amount_cents"], LEASE_EXPOSURE_CENTS, "escrowed_amount_cents"
    )

    for target in (DISPOSITION_ASSUMED, DISPOSITION_INDEMNIFIED):
        rejected = api.set_liability_disposition(
            item["id"], f.disposition_payload(target), DEAL_LEAD
        )
        validate_error(rejected, ApiErrorId.INVALID_STATE_TRANSITION, 409)

    unchanged = validate_success(api.get_liability_item(item["id"], DEAL_LEAD))
    assert unchanged["disposition"] == DISPOSITION_ESCROWED
    a.assert_money_equals(
        unchanged["escrowed_amount_cents"], LEASE_EXPOSURE_CENTS, "escrowed_amount_cents"
    )
    committed = read_acquisition(api, acquisition["id"])
    a.assert_escrow(
        committed, ESCROW_TOTAL_CENTS, LEASE_EXPOSURE_CENTS, ESCROW_AVAILABLE_AFTER_LEASE_CENTS
    )

    excluded = set_disposition(api, item["id"], DISPOSITION_EXCLUDED)
    assert excluded["disposition"] == DISPOSITION_EXCLUDED
    a.assert_money_equals(excluded["escrowed_amount_cents"], 0, "escrowed_amount_cents")
    released = read_acquisition(api, acquisition["id"])
    a.assert_escrow(released, ESCROW_TOTAL_CENTS, 0, ESCROW_TOTAL_CENTS)


def test_a_failed_checklist_line_reopens_and_forgets_its_failure_reason(api: ApiClient):
    """The line machine is cyclic, so a failure is recoverable on the same row.

    PRD: "A `FAILED` line can be reopened with `FAILED → IN_PROGRESS`, which has no
    precondition, clears `failure_reason` back to null, and recomputes the
    posture."

    Design: Corner/state_machines/readiness_task_failed_reopens_to_in_progress_and_clears_reason
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    task = create_task(api, acquisition["id"])
    set_task_status(api, task["id"], TASK_STATUS_IN_PROGRESS)
    failed = set_task_status(
        api, task["id"], TASK_STATUS_FAILED, failure_reason=FAILURE_REASON
    )
    a.assert_status(failed, TASK_STATUS_FAILED)
    assert failed["failure_reason"] == FAILURE_REASON
    blocked = read_acquisition(api, acquisition["id"])
    assert blocked["readiness_posture"] == POSTURE_BLOCKED

    reopened = set_task_status(api, task["id"], TASK_STATUS_IN_PROGRESS)

    a.assert_status(reopened, TASK_STATUS_IN_PROGRESS)
    a.assert_fields_null(reopened, "failure_reason")
    at_risk = read_acquisition(api, acquisition["id"])
    assert at_risk["readiness_posture"] == POSTURE_AT_RISK

    completed = set_task_status(api, task["id"], TASK_STATUS_COMPLETE)
    a.assert_status(completed, TASK_STATUS_COMPLETE)
    assert completed["verified_by_user_id"] == USER_INTEGRATION_MANAGER
    ready = read_acquisition(api, acquisition["id"])
    assert ready["readiness_posture"] == POSTURE_READY


def test_a_flagged_clearance_freezes_child_writes_until_it_is_lifted(api: ApiClient):
    """The regulatory dimension gates the child write surface without moving the workflow.

    PRD: "Any request that would create or advance a resource belonging to that
    acquisition is rejected with `ERR_COMPLIANCE_CLEARANCE_BLOCKED` and HTTP 403."

    Design: Corner/state_machines/compliance_clearance_flagged_blocks_child_writes_then_cleared_restores
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    acquisition_id = acquisition["id"]
    set_clearance(api, acquisition_id, CLEARANCE_FLAGGED)

    for stop in (CLEARANCE_FLAGGED, CLEARANCE_SUSPENDED, CLEARANCE_FLAGGED):
        frozen = read_acquisition(api, acquisition_id)
        if frozen["compliance_clearance"] != stop:
            frozen = set_clearance(api, acquisition_id, stop)
        assert frozen["compliance_clearance"] == stop
        a.assert_status(frozen, DEAL_STATUS_SOURCING, "deal_status")
        validate_error(
            api.create_physician(f.physician_payload(acquisition_id), DEAL_LEAD),
            ApiErrorId.COMPLIANCE_CLEARANCE_BLOCKED,
            403,
        )
        validate_error(
            api.create_ehr_migration_batch(
                f.ehr_migration_batch_payload(acquisition_id), INTEGRATION_MANAGER
            ),
            ApiErrorId.COMPLIANCE_CLEARANCE_BLOCKED,
            403,
        )
        validate_error(
            api.create_staff_transition_offer(
                f.staff_offer_payload(acquisition_id), INTEGRATION_MANAGER
            ),
            ApiErrorId.COMPLIANCE_CLEARANCE_BLOCKED,
            403,
        )
        validate_error(
            api.create_billing_conversion(
                f.billing_conversion_payload(acquisition_id), INTEGRATION_MANAGER
            ),
            ApiErrorId.COMPLIANCE_CLEARANCE_BLOCKED,
            403,
        )
        validate_error(
            api.create_liability_item(f.liability_item_payload(acquisition_id), DEAL_LEAD),
            ApiErrorId.COMPLIANCE_CLEARANCE_BLOCKED,
            403,
        )
        a.assert_total_count(
            api.list_physicians({"acquisition_id": acquisition_id}, DEAL_LEAD), 0
        )

    cleared = set_clearance(api, acquisition_id, CLEARANCE_CLEARED)
    assert cleared["compliance_clearance"] == CLEARANCE_CLEARED

    admitted = validate_success(
        api.create_physician(f.physician_payload(acquisition_id), DEAL_LEAD), 201
    )
    assert admitted["employment_status"] == EMPLOYMENT_PROSPECTIVE
