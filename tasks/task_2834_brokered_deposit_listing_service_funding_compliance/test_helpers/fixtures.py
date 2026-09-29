"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch through the PRD's own endpoints.  Setup calls use the
lenient ``get_success_data`` validator so a broken precondition surfaces as a
setup failure rather than as a confusing assertion failure.

Identity threading: the opaque operator identifiers are kept distinct per
capacity (desk originates, compliance determines and approves, treasury drafts,
examiner supervises) so the duty-segregation comparisons of PRD §2.9 never
reject a setup call.  ``BrokerRepresentative`` calls must use
``make_broker_representative_headers(broker["id"])``.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import DEFAULT_CLOCK_INSTANT
from .test_users import ADMIN, COMPLIANCE, DESK, EXAMINER, TREASURY


# ─── Reads ────────────────────────────────────────────

def read_institution(institution_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_institution(institution_id, headers or ADMIN)
    )


def read_broker(broker_id, headers=None) -> dict:
    return get_success_data(api_client.get_broker(broker_id, headers or ADMIN))


def read_agreement(agreement_id, headers=None) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, headers or ADMIN))


def read_exception(exception_id, headers=None) -> dict:
    return get_success_data(api_client.get_exception(exception_id, headers or ADMIN))


def read_program(program_id, headers=None) -> dict:
    return get_success_data(api_client.get_program(program_id, headers or ADMIN))


def read_classification(classification_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_classification(classification_id, headers or ADMIN)
    )


def read_placement(placement_id, headers=None) -> dict:
    return get_success_data(api_client.get_placement(placement_id, headers or ADMIN))


def read_plan(plan_id, headers=None) -> dict:
    return get_success_data(api_client.get_contingency_plan(plan_id, headers or ADMIN))


def read_filing(filing_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_call_report_filing(filing_id, headers or ADMIN)
    )


def read_wholesale_summary(institution_id, params=None, headers=None) -> dict:
    return get_success_data(
        api_client.get_wholesale_funding_summary(
            institution_id, headers or TREASURY, params=params
        )
    )


def read_fee_summary(agreement_id, headers=None) -> dict:
    return get_success_data(api_client.get_fee_summary(agreement_id, headers or DESK))


# ─── Tier 1: single-step primitives ───────────────────

def set_clock(current_utc: str = DEFAULT_CLOCK_INSTANT) -> dict:
    """Point the logical clock at an explicit instant (PRD §2.10)."""
    return get_success_data(api_client.set_clock(f.clock_payload(current_utc), ADMIN))


def register_institution(**overrides) -> dict:
    return get_success_data(
        api_client.create_institution(f.institution_payload(**overrides), ADMIN)
    )


def publish_rate_cap(**overrides) -> dict:
    return get_success_data(
        api_client.publish_national_rate_cap(f.national_rate_cap_payload(**overrides), ADMIN)
    )


def register_broker(**overrides) -> dict:
    return get_success_data(api_client.create_broker(f.broker_payload(**overrides), DESK))


def draft_agreement(broker_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_agreement(
            broker_id, f.agreement_payload(**overrides), headers or DESK
        )
    )


def diligence_action(agreement_id, action, headers=None, **extra) -> dict:
    return get_success_data(
        api_client.diligence_action(
            agreement_id, f.diligence_action_payload(action, **extra), headers or COMPLIANCE
        )
    )


def file_exception(broker_id, institution_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_exception(
            f.exception_payload(broker_id, institution_id, **overrides), headers or DESK
        )
    )


def exception_filing_action(exception_id, action, headers=None, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api_client.exception_filing_action(exception_id, payload, headers or DESK)
    )


def exception_review_action(exception_id, action, headers=None, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api_client.exception_review_action(exception_id, payload, headers or COMPLIANCE)
    )


def open_program(institution_id, headers=None, **overrides) -> dict:
    """Create a programme; it lands in PENDING_CLASSIFICATION."""
    return get_success_data(
        api_client.create_program(
            f.program_payload(institution_id, **overrides), headers or DESK
        )
    )


def classify_program(program_id, expected_program_version=None, headers=None,
                     **overrides) -> dict:
    """Record a determination against the programme's currently observed version."""
    if expected_program_version is None:
        expected_program_version = read_program(program_id)["version"]
    return get_success_data(
        api_client.create_classification(
            f.classification_payload(program_id, expected_program_version, **overrides),
            headers or COMPLIANCE,
        )
    )


def program_state_action(program_id, action, headers=None, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api_client.program_state_action(program_id, payload, headers or DESK)
    )


def attest_program(program_id, headers=None) -> dict:
    """Move the programme CLASSIFIED -> OPEN_FOR_PLACEMENT (PRD §3.4)."""
    return program_state_action(program_id, "ATTEST_CLASSIFICATION", headers or DESK)


def book_placement(program_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_placement(
            f.placement_payload(program_id, **overrides), headers or DESK
        )
    )


def funding_action(placement_id, action, headers=None, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api_client.funding_action(placement_id, payload, headers or DESK)
    )


def activate_placement(placement_id, headers=None) -> dict:
    return funding_action(placement_id, "ACTIVATE", headers)


def early_withdraw_placement(placement_id, withdrawal_date, headers=None) -> dict:
    return funding_action(
        placement_id, "EARLY_WITHDRAW", headers, withdrawal_date=withdrawal_date
    )


def cancel_placement(placement_id, headers=None) -> dict:
    return funding_action(placement_id, "CANCEL", headers)


def record_rate_cap_check(placement_id, check_date, headers=None) -> dict:
    return get_success_data(
        api_client.create_rate_cap_check(
            placement_id, f.rate_cap_check_payload(check_date), headers or COMPLIANCE
        )
    )


def create_concentration_limit(institution_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_concentration_limit(
            institution_id, f.concentration_limit_payload(**overrides), headers or TREASURY
        )
    )


def draft_contingency_plan(institution_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_contingency_plan(
            institution_id, f.contingency_plan_payload(**overrides), headers or TREASURY
        )
    )


def plan_lifecycle_action(plan_id, action, headers=None, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api_client.plan_lifecycle_action(plan_id, payload, headers or TREASURY)
    )


def create_call_report_filing(institution_id, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_call_report_filing(
            institution_id, f.call_report_filing_payload(**overrides), headers or DESK
        )
    )


def filing_workflow_action(filing_id, action, headers=None, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api_client.filing_workflow_action(filing_id, payload, headers or DESK)
    )


def run_maturity_sweep(as_of_date) -> dict:
    return get_success_data(
        api_client.run_maturity_sweep(f.maturity_run_payload(as_of_date), ADMIN)
    )


def change_capital_category(institution_id, capital_category,
                            expected_institution_version=None, headers=None) -> dict:
    """Supervisory re-categorisation guarded by the observed bank version."""
    if expected_institution_version is None:
        expected_institution_version = read_institution(institution_id)["version"]
    return get_success_data(
        api_client.change_capital_category(
            institution_id,
            {
                "capital_category": capital_category,
                "expected_institution_version": expected_institution_version,
            },
            headers or EXAMINER,
        )
    )


def adjust_balances(institution_id, headers=None, **fields) -> dict:
    return get_success_data(
        api_client.adjust_balances(institution_id, dict(fields), headers or TREASURY)
    )


# ─── Tier 2: bank with a published benchmark ──────────

def setup_bank(clock=DEFAULT_CLOCK_INSTANT, publish_benchmark=True,
               institution_overrides=None, benchmark_overrides=None) -> dict:
    """Clock, one registered bank and (by default) one benchmark publication."""
    if clock is not None:
        set_clock(clock)
    institution = register_institution(**(institution_overrides or {}))
    benchmark = None
    if publish_benchmark:
        benchmark = publish_rate_cap(**(benchmark_overrides or {}))
    return {"institution": institution, "benchmark": benchmark}


# ─── Tier 2: counterparty with an approved agreement ──

def setup_approved_agreement(broker_overrides=None, agreement_overrides=None) -> dict:
    """Counterparty plus an agreement carried to APPROVED.

    The draft is filed by the funding desk and both diligence actions are taken
    by compliance, so the acting identifier always differs from
    ``prepared_by_user_id`` as §3.2 requires of an approval.
    """
    broker = register_broker(**(broker_overrides or {}))
    agreement = draft_agreement(broker["id"], DESK, **(agreement_overrides or {}))
    diligence_action(agreement["id"], "START_DILIGENCE", COMPLIANCE)
    agreement = diligence_action(agreement["id"], "APPROVE", COMPLIANCE)
    return {"broker": broker, "agreement": agreement}


def setup_conditional_agreement(broker_overrides=None, agreement_overrides=None) -> dict:
    """Same chain, but sub-scores land the composite in the 60-69 band."""
    overrides = {
        "aml_program_score": 65,
        "financial_condition_score": 65,
        "insurance_coverage_score": 65,
        "recordkeeping_score": 65,
    }
    overrides.update(agreement_overrides or {})
    return setup_approved_agreement(broker_overrides, overrides)


# ─── Tier 3: programmes ───────────────────────────────

def setup_core_program(env=None, program_overrides=None, **bank_kwargs) -> dict:
    """A counterparty-less programme sitting in PENDING_CLASSIFICATION."""
    env = dict(env or setup_bank(**bank_kwargs))
    env["program"] = open_program(
        env["institution"]["id"], DESK, **(program_overrides or {})
    )
    return env


def setup_brokered_program(env=None, broker_overrides=None, agreement_overrides=None,
                           program_overrides=None, **bank_kwargs) -> dict:
    """Bank, approved counterparty file and a BROKERED programme in
    PENDING_CLASSIFICATION."""
    env = dict(env or setup_bank(**bank_kwargs))
    if "agreement" not in env:
        env.update(setup_approved_agreement(broker_overrides, agreement_overrides))
    overrides = {
        "broker_id": env["broker"]["id"],
        "agreement_id": env["agreement"]["id"],
        "program_name": "60D Brokered CD",
        "funding_channel_claim": "BROKERED",
    }
    overrides.update(program_overrides or {})
    env["program"] = open_program(env["institution"]["id"], DESK, **overrides)
    return env


def setup_classified_program(env=None, classification_overrides=None, **kwargs) -> dict:
    """Programme carried to CLASSIFIED by a compliance determination."""
    env = dict(env) if env else setup_brokered_program(**kwargs)
    env["classification"] = classify_program(
        env["program"]["id"], env["program"]["version"], COMPLIANCE,
        **(classification_overrides or {})
    )
    env["program"] = read_program(env["program"]["id"])
    return env


def setup_open_program(env=None, classification_overrides=None, **kwargs) -> dict:
    """Programme carried all the way to OPEN_FOR_PLACEMENT.

    Compliance determines and the funding desk attests, so the attesting
    identifier differs from the determination's ``determined_by_user_id``.
    """
    env = dict(env) if env else setup_brokered_program(**kwargs)
    if "classification" not in env:
        env = setup_classified_program(env, classification_overrides)
    env["program"] = attest_program(env["program"]["id"], DESK)
    return env


def setup_open_core_program(env=None, program_overrides=None,
                            classification_overrides=None, **bank_kwargs) -> dict:
    """Counterparty-less programme open for placement; determined class is CORE."""
    env = setup_core_program(env, program_overrides, **bank_kwargs)
    return setup_open_program(env, classification_overrides)


# ─── Tier 3: placements ───────────────────────────────

def setup_booked_placement(env=None, placement_overrides=None, **kwargs) -> dict:
    """Open programme plus one tranche booked into PENDING/UNREVIEWED."""
    env = dict(env) if env else setup_open_program(**kwargs)
    env["placement"] = book_placement(
        env["program"]["id"], DESK, **(placement_overrides or {})
    )
    return env


def setup_active_placement(env=None, placement_overrides=None, **kwargs) -> dict:
    """Open programme plus one tranche carried to ACTIVE."""
    env = setup_booked_placement(env, placement_overrides, **kwargs)
    env["placement"] = activate_placement(env["placement"]["id"], DESK)
    env["institution"] = read_institution(env["institution"]["id"])
    return env


def add_active_placement(env, placement_overrides=None) -> dict:
    """Book and activate one more tranche under the same open programme."""
    placement = book_placement(
        env["program"]["id"], DESK, **(placement_overrides or {})
    )
    return activate_placement(placement["id"], DESK)


# ─── Tier 3: exception filings ────────────────────────

def setup_acknowledged_exception(broker_id, institution_id, **overrides) -> dict:
    """Notice filing whose arithmetic qualifies, self-effected to ACKNOWLEDGED."""
    exception = file_exception(broker_id, institution_id, DESK, **overrides)
    return exception_filing_action(exception["id"], "SUBMIT", DESK)


def setup_granted_exception(broker_id, institution_id, **overrides) -> dict:
    """Application filing carried through supervisory review to GRANTED."""
    payload = {"exception_basis": "OTHER_APPLICATION"}
    payload.update(overrides)
    exception = file_exception(broker_id, institution_id, DESK, **payload)
    exception_filing_action(exception["id"], "SUBMIT", DESK)
    return exception_review_action(exception["id"], "GRANT", COMPLIANCE)


def setup_program_relying_on_exception(env=None, exception_overrides=None,
                                       **kwargs) -> dict:
    """Brokered-claim programme whose governing determination leans on an
    ACKNOWLEDGED notice, so the determined class is LISTING_SERVICE_NON_BROKERED."""
    env = dict(env) if env else setup_brokered_program(**kwargs)
    env["exception"] = setup_acknowledged_exception(
        env["broker"]["id"], env["institution"]["id"], **(exception_overrides or {})
    )
    env = setup_classified_program(
        env, {"relied_exception_id": env["exception"]["id"]}
    )
    env["exception"] = read_exception(env["exception"]["id"])
    return env


# ─── Tier 3: board limits and contingency plans ───────

def setup_approved_plan(institution_id, **overrides) -> dict:
    """Plan drafted by treasury and approved by a second identity."""
    plan = draft_contingency_plan(institution_id, TREASURY, **overrides)
    plan_lifecycle_action(plan["id"], "SUBMIT_FOR_REVIEW", TREASURY)
    return plan_lifecycle_action(plan["id"], "APPROVE", COMPLIANCE)


def setup_activated_plan(institution_id, **overrides) -> dict:
    plan = setup_approved_plan(institution_id, **overrides)
    return plan_lifecycle_action(plan["id"], "ACTIVATE", TREASURY)


def setup_frozen_institution(env=None, **kwargs) -> dict:
    """Bank with live brokered money and a board limit whose breach threshold
    sits below the resulting ratio, so the posture evaluates to FROZEN."""
    env = setup_active_placement(env, **kwargs)
    env["limit"] = create_concentration_limit(
        env["institution"]["id"], TREASURY,
        metric="BROKERED_TO_TOTAL_DEPOSITS",
        warning_threshold_bps=1,
        breach_threshold_bps=2,
    )
    env["institution"] = read_institution(env["institution"]["id"])
    return env


# ─── Tier 3: call report filings ──────────────────────

def setup_prepared_filing(institution_id, **overrides) -> dict:
    filing = create_call_report_filing(institution_id, DESK, **overrides)
    return filing_workflow_action(filing["id"], "PREPARE", DESK)


def setup_filed_filing(institution_id, **overrides) -> dict:
    """Filing carried to FILED; the desk prepares and compliance attests."""
    filing = setup_prepared_filing(institution_id, **overrides)
    filing_workflow_action(filing["id"], "ATTEST", COMPLIANCE)
    return filing_workflow_action(filing["id"], "FILE", DESK)


def setup_filing_under_examiner_review(institution_id, **overrides) -> dict:
    """Filing sitting in UNDER_EXAMINER_REVIEW, which locks the bank's
    capital category and balance baselines against operator edits."""
    filing = setup_filed_filing(institution_id, **overrides)
    return filing_workflow_action(filing["id"], "OPEN_EXAM_REVIEW", EXAMINER)
