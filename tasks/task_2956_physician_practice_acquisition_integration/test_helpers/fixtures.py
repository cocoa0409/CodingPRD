"""Composite setup helpers and pytest fixtures.

Setup calls go through `get_success_data`, so a broken precondition surfaces as
a clear setup failure rather than as a confusing assertion inside the test body.

Every ownership-gated call is made with the identity the PRD requires: the two
valuation analysts and the two compliance officers keep distinct user ids so the
segregation-of-duties rules hold, and any `PracticePhysician` call is issued
with `make_practice_physician_headers(<the real Physician id>)`.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import (
    BATCH_ACTION_EXTRACT,
    BATCH_ACTION_LOAD,
    CLEARANCE_CLEARED,
    DEAL_STATUS_BOARD_REVIEW,
    DEAL_STATUS_CLOSED,
    DEAL_STATUS_DILIGENCE,
    DEAL_STATUS_SIGNED,
    DEFAULT_CLOCK_INSTANT,
    LICENSE_EXPIRY_B,
    NPI_B,
    OFFER_STATUS_ACCEPTED,
    OFFER_STATUS_EXTENDED,
    OPINION_STATUS_ACCEPTED,
    OPINION_STATUS_SUBMITTED,
    PHYSICIAN_NAME_B,
    PLAN_STATUS_APPROVED,
    PLAN_STATUS_EXECUTED,
    PLAN_STATUS_SUBMITTED,
    TASK_STATUS_COMPLETE,
    TASK_STATUS_IN_PROGRESS,
    USER_COMPLIANCE_OFFICER_ALT,
)
from . import factories as f
from .test_users import (
    make_compensation_designer_headers,
    make_compliance_officer_headers,
    make_deal_lead_headers,
    make_integration_manager_headers,
    make_practice_physician_headers,
    make_valuation_analyst_headers,
)

Entity = Dict[str, Any]

DEAL_LEAD = make_deal_lead_headers()
VALUATION_ANALYST = make_valuation_analyst_headers()
COMPLIANCE_OFFICER = make_compliance_officer_headers()
COMPLIANCE_OFFICER_ALT = make_compliance_officer_headers(USER_COMPLIANCE_OFFICER_ALT)
COMPENSATION_DESIGNER = make_compensation_designer_headers()
INTEGRATION_MANAGER = make_integration_manager_headers()


# ---------------------------------------------------------------------------
# Tier 1 — logical clock and root entities
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, instant: str, headers: Optional[Dict] = None) -> Entity:
    """Park the logical clock on an explicit instant."""
    return get_success_data(api.set_clock(instant, headers or INTEGRATION_MANAGER))


def park_clock_on_date(api: ApiClient, date: str, time_of_day: str = "00:00:00") -> Entity:
    return set_clock(api, f.make_clock_instant(date, time_of_day))


def reset_clock(api: ApiClient) -> Entity:
    """Re-assert the PRD's pre-set clock reading."""
    return set_clock(api, DEFAULT_CLOCK_INSTANT)


def create_acquisition(api: ApiClient, **overrides: Any) -> Entity:
    return get_success_data(
        api.create_acquisition(f.acquisition_payload(**overrides), DEAL_LEAD)
    )


def create_cardiology_acquisition(api: ApiClient, **overrides: Any) -> Entity:
    return get_success_data(
        api.create_acquisition(f.cardiology_acquisition_payload(**overrides), DEAL_LEAD)
    )


def create_physician(api: ApiClient, acquisition_id: str, **overrides: Any) -> Entity:
    return get_success_data(
        api.create_physician(f.physician_payload(acquisition_id, **overrides), DEAL_LEAD)
    )


def acquisition_version(api: ApiClient, acquisition_id: str, headers=None) -> int:
    data = get_success_data(
        api.get_acquisition(acquisition_id, headers or DEAL_LEAD)
    )
    return data["version"]


def read_acquisition(api: ApiClient, acquisition_id: str, headers=None) -> Entity:
    return get_success_data(api.get_acquisition(acquisition_id, headers or DEAL_LEAD))


def advance_deal_status(
    api: ApiClient, acquisition_id: str, target_status: str, **extra: Any
) -> Entity:
    return get_success_data(
        api.set_acquisition_status(
            acquisition_id, f.acquisition_status_payload(target_status, **extra), DEAL_LEAD
        )
    )


def set_clearance(
    api: ApiClient,
    acquisition_id: str,
    target_clearance: str,
    headers: Optional[Dict] = None,
    **extra: Any,
) -> Entity:
    return get_success_data(
        api.set_compliance_clearance(
            acquisition_id,
            f.compliance_clearance_payload(target_clearance, **extra),
            headers or COMPLIANCE_OFFICER,
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 — a diligence-stage deal with at least one physician
# ---------------------------------------------------------------------------


def diligence_deal(api: ApiClient, physician_overrides: Optional[Dict] = None, **acq_overrides: Any) -> Dict[str, Entity]:
    """Acquisition in DILIGENCE with one registered physician."""
    acquisition = create_acquisition(api, **acq_overrides)
    physician = create_physician(api, acquisition["id"], **(physician_overrides or {}))
    acquisition = advance_deal_status(api, acquisition["id"], DEAL_STATUS_DILIGENCE)
    return {"acquisition": acquisition, "physician": physician}


def second_physician(api: ApiClient, acquisition_id: str, **overrides: Any) -> Entity:
    defaults = {
        "npi": NPI_B,
        "full_name": PHYSICIAN_NAME_B,
        "state_license_expires_on": LICENSE_EXPIRY_B,
    }
    defaults.update(overrides)
    return create_physician(api, acquisition_id, **defaults)


# ---------------------------------------------------------------------------
# Tier 3 — valuation opinions
# ---------------------------------------------------------------------------


def file_opinion(api: ApiClient, payload: Dict[str, Any], headers=None) -> Entity:
    return get_success_data(
        api.create_valuation_opinion(payload, headers or VALUATION_ANALYST)
    )


def file_market_fmv(api: ApiClient, acquisition_id: str, headers=None, **overrides: Any) -> Entity:
    version = acquisition_version(api, acquisition_id, headers or VALUATION_ANALYST)
    return file_opinion(
        api, f.market_fmv_payload(acquisition_id, version, **overrides), headers
    )


def file_income_fmv(api: ApiClient, acquisition_id: str, headers=None, **overrides: Any) -> Entity:
    version = acquisition_version(api, acquisition_id, headers or VALUATION_ANALYST)
    return file_opinion(
        api, f.income_fmv_payload(acquisition_id, version, **overrides), headers
    )


def file_cr_opinion(api: ApiClient, acquisition_id: str, headers=None, **overrides: Any) -> Entity:
    version = acquisition_version(api, acquisition_id, headers or VALUATION_ANALYST)
    return file_opinion(
        api, f.cr_opinion_payload(acquisition_id, version, **overrides), headers
    )


def submit_opinion(api: ApiClient, opinion_id: str, preparer_headers=None) -> Entity:
    return get_success_data(
        api.set_valuation_opinion_status(
            opinion_id,
            f.opinion_status_payload(OPINION_STATUS_SUBMITTED),
            preparer_headers or VALUATION_ANALYST,
        )
    )


def accept_opinion(
    api: ApiClient, opinion_id: str, officer_headers=None, review_note: str = "Accepted"
) -> Entity:
    return get_success_data(
        api.set_valuation_opinion_status(
            opinion_id,
            f.opinion_status_payload(OPINION_STATUS_ACCEPTED, review_note=review_note),
            officer_headers or COMPLIANCE_OFFICER,
        )
    )


def accepted_market_fmv(
    api: ApiClient,
    acquisition_id: str,
    preparer_headers=None,
    officer_headers=None,
    **overrides: Any,
) -> Entity:
    """File, submit and accept a MARKET_APPROACH fair market value opinion."""
    opinion = file_market_fmv(api, acquisition_id, preparer_headers, **overrides)
    submit_opinion(api, opinion["id"], preparer_headers)
    return accept_opinion(api, opinion["id"], officer_headers, "Market approach accepted")


def accepted_income_fmv(
    api: ApiClient,
    acquisition_id: str,
    preparer_headers=None,
    officer_headers=None,
    **overrides: Any,
) -> Entity:
    opinion = file_income_fmv(api, acquisition_id, preparer_headers, **overrides)
    submit_opinion(api, opinion["id"], preparer_headers)
    return accept_opinion(api, opinion["id"], officer_headers, "Income approach accepted")


def accepted_cr_opinion(
    api: ApiClient,
    acquisition_id: str,
    preparer_headers=None,
    officer_headers=None,
    **overrides: Any,
) -> Entity:
    opinion = file_cr_opinion(api, acquisition_id, preparer_headers, **overrides)
    submit_opinion(api, opinion["id"], preparer_headers)
    return accept_opinion(api, opinion["id"], officer_headers, "Commercially reasonable")


# ---------------------------------------------------------------------------
# Tier 4 — board review, compensation plans, signing and closing
# ---------------------------------------------------------------------------


def board_review_deal(
    api: ApiClient,
    physician_overrides: Optional[Dict] = None,
    fmv_overrides: Optional[Dict] = None,
    **acq_overrides: Any,
) -> Dict[str, Entity]:
    """A deal walked all the way to BOARD_REVIEW with a pinned FMV.

    The fair market value opinion is accepted by `co-1` and the commercial
    reasonableness opinion by `co-2`, so `co-2` remains free to approve a
    compensation plan on the acquisition.
    """
    deal = diligence_deal(api, physician_overrides, **acq_overrides)
    acquisition_id = deal["acquisition"]["id"]
    fmv = accepted_market_fmv(
        api, acquisition_id, officer_headers=COMPLIANCE_OFFICER, **(fmv_overrides or {})
    )
    cr = accepted_cr_opinion(api, acquisition_id, officer_headers=COMPLIANCE_OFFICER_ALT)
    acquisition = advance_deal_status(api, acquisition_id, DEAL_STATUS_BOARD_REVIEW)
    return {
        "acquisition": acquisition,
        "physician": deal["physician"],
        "fmv": fmv,
        "cr": cr,
    }


def create_plan(
    api: ApiClient,
    acquisition_id: str,
    physician_id: str,
    headers=None,
    **overrides: Any,
) -> Entity:
    caller = headers or COMPENSATION_DESIGNER
    version = acquisition_version(api, acquisition_id, caller)
    return get_success_data(
        api.create_compensation_plan(
            f.compensation_plan_payload(acquisition_id, version, physician_id, **overrides),
            caller,
        )
    )


def submit_plan(api: ApiClient, plan_id: str, headers=None) -> Entity:
    return get_success_data(
        api.set_compensation_plan_status(
            plan_id,
            f.plan_status_payload(PLAN_STATUS_SUBMITTED),
            headers or COMPENSATION_DESIGNER,
        )
    )


def approve_plan(api: ApiClient, plan_id: str, officer_headers=None) -> Entity:
    """Approval is issued by an officer other than the one who accepted the pinned opinion."""
    return get_success_data(
        api.set_compensation_plan_status(
            plan_id,
            f.plan_status_payload(PLAN_STATUS_APPROVED),
            officer_headers or COMPLIANCE_OFFICER_ALT,
        )
    )


def execute_plan(api: ApiClient, plan_id: str, physician_id: str) -> Entity:
    """Execution is the physician's own act, so the caller id is the Physician id."""
    return get_success_data(
        api.set_compensation_plan_status(
            plan_id,
            f.plan_status_payload(PLAN_STATUS_EXECUTED),
            make_practice_physician_headers(physician_id),
        )
    )


def approved_plan(
    api: ApiClient,
    acquisition_id: str,
    physician_id: str,
    officer_headers=None,
    **overrides: Any,
) -> Entity:
    plan = create_plan(api, acquisition_id, physician_id, **overrides)
    submit_plan(api, plan["id"])
    return approve_plan(api, plan["id"], officer_headers)


def executed_plan(
    api: ApiClient,
    acquisition_id: str,
    physician_id: str,
    officer_headers=None,
    **overrides: Any,
) -> Entity:
    plan = approved_plan(api, acquisition_id, physician_id, officer_headers, **overrides)
    return execute_plan(api, plan["id"], physician_id)


def board_review_deal_with_executed_plan(
    api: ApiClient, **acq_overrides: Any
) -> Dict[str, Entity]:
    """BOARD_REVIEW, cleared for compliance, with the physician's plan EXECUTED."""
    deal = board_review_deal(api, **acq_overrides)
    acquisition_id = deal["acquisition"]["id"]
    physician_id = deal["physician"]["id"]
    plan = executed_plan(api, acquisition_id, physician_id)
    set_clearance(api, acquisition_id, CLEARANCE_CLEARED)
    deal["plan"] = plan
    deal["acquisition"] = read_acquisition(api, acquisition_id)
    return deal


def signed_deal(api: ApiClient, **acq_overrides: Any) -> Dict[str, Entity]:
    """A SIGNED deal: every physician papered, no liability left unassigned."""
    deal = board_review_deal_with_executed_plan(api, **acq_overrides)
    acquisition_id = deal["acquisition"]["id"]
    deal["acquisition"] = advance_deal_status(api, acquisition_id, DEAL_STATUS_SIGNED)
    return deal


def closed_deal(api: ApiClient, **acq_overrides: Any) -> Dict[str, Entity]:
    """A CLOSED deal: readiness READY through a single completed blocking line."""
    deal = signed_deal(api, **acq_overrides)
    acquisition_id = deal["acquisition"]["id"]
    task = create_task(api, acquisition_id)
    set_task_status(api, task["id"], TASK_STATUS_IN_PROGRESS)
    set_task_status(api, task["id"], TASK_STATUS_COMPLETE)
    deal["task"] = read_task(api, task["id"])
    deal["acquisition"] = advance_deal_status(api, acquisition_id, DEAL_STATUS_CLOSED)
    return deal


# ---------------------------------------------------------------------------
# Tier 5 — child collections
# ---------------------------------------------------------------------------


def create_liability(api: ApiClient, acquisition_id: str, **overrides: Any) -> Entity:
    return get_success_data(
        api.create_liability_item(
            f.liability_item_payload(acquisition_id, **overrides), DEAL_LEAD
        )
    )


def set_disposition(
    api: ApiClient, item_id: str, target_disposition: str, **extra: Any
) -> Entity:
    return get_success_data(
        api.set_liability_disposition(
            item_id, f.disposition_payload(target_disposition, **extra), DEAL_LEAD
        )
    )


def create_payer_contract(api: ApiClient, acquisition_id: str, **overrides: Any) -> Entity:
    return get_success_data(
        api.create_payer_contract(
            f.payer_contract_payload(acquisition_id, **overrides), INTEGRATION_MANAGER
        )
    )


def act_on_novation(api: ApiClient, contract_id: str, action: str, **extra: Any) -> Entity:
    return get_success_data(
        api.act_on_novation(
            contract_id, f.novation_payload(action, **extra), INTEGRATION_MANAGER
        )
    )


def create_package(
    api: ApiClient,
    acquisition_id: str,
    physician_id: str,
    payer_contract_id: str,
    **overrides: Any,
) -> Entity:
    return get_success_data(
        api.create_credentialing_package(
            f.credentialing_package_payload(
                acquisition_id, physician_id, payer_contract_id, **overrides
            ),
            INTEGRATION_MANAGER,
        )
    )


def set_package_status(api: ApiClient, package_id: str, target_status: str, **extra: Any) -> Entity:
    return get_success_data(
        api.set_credentialing_package_status(
            package_id, f.package_status_payload(target_status, **extra), INTEGRATION_MANAGER
        )
    )


def create_batch(api: ApiClient, acquisition_id: str, **overrides: Any) -> Entity:
    return get_success_data(
        api.create_ehr_migration_batch(
            f.ehr_migration_batch_payload(acquisition_id, **overrides), INTEGRATION_MANAGER
        )
    )


def progress_batch(api: ApiClient, batch_id: str, action: str, **extra: Any) -> Entity:
    return get_success_data(
        api.progress_ehr_migration_batch(
            batch_id, f.batch_progress_payload(action, **extra), INTEGRATION_MANAGER
        )
    )


def reconcile_batch(
    api: ApiClient, batch_id: str, validated_count: int, defect_count: int
) -> Entity:
    return get_success_data(
        api.progress_ehr_migration_batch(
            batch_id, f.reconcile_payload(validated_count, defect_count), INTEGRATION_MANAGER
        )
    )


def loaded_batch(api: ApiClient, acquisition_id: str, **overrides: Any) -> Entity:
    """Stage a batch and drive it through EXTRACT and LOAD."""
    batch = create_batch(api, acquisition_id, **overrides)
    progress_batch(api, batch["id"], BATCH_ACTION_EXTRACT)
    return progress_batch(api, batch["id"], BATCH_ACTION_LOAD)


def create_offer(api: ApiClient, acquisition_id: str, **overrides: Any) -> Entity:
    return get_success_data(
        api.create_staff_transition_offer(
            f.staff_offer_payload(acquisition_id, **overrides), INTEGRATION_MANAGER
        )
    )


def set_offer_status(api: ApiClient, offer_id: str, target_status: str, **extra: Any) -> Entity:
    return get_success_data(
        api.set_staff_transition_offer_status(
            offer_id, f.offer_status_payload(target_status, **extra), INTEGRATION_MANAGER
        )
    )


def extended_offer(api: ApiClient, acquisition_id: str, **overrides: Any) -> Entity:
    offer = create_offer(api, acquisition_id, **overrides)
    return set_offer_status(api, offer["id"], OFFER_STATUS_EXTENDED)


def accepted_offer(api: ApiClient, acquisition_id: str, **overrides: Any) -> Entity:
    offer = extended_offer(api, acquisition_id, **overrides)
    return set_offer_status(api, offer["id"], OFFER_STATUS_ACCEPTED)


def create_conversion(api: ApiClient, acquisition_id: str, **overrides: Any) -> Entity:
    return get_success_data(
        api.create_billing_conversion(
            f.billing_conversion_payload(acquisition_id, **overrides), INTEGRATION_MANAGER
        )
    )


def set_conversion_status(
    api: ApiClient, conversion_id: str, target_status: str, **extra: Any
) -> Entity:
    return get_success_data(
        api.set_billing_conversion_status(
            conversion_id, f.conversion_status_payload(target_status, **extra), INTEGRATION_MANAGER
        )
    )


def create_task(api: ApiClient, acquisition_id: str, headers=None, **overrides: Any) -> Entity:
    return get_success_data(
        api.create_readiness_task(
            f.readiness_task_payload(acquisition_id, **overrides),
            headers or INTEGRATION_MANAGER,
        )
    )


def set_task_status(
    api: ApiClient, task_id: str, target_status: str, headers=None, **extra: Any
) -> Entity:
    return get_success_data(
        api.set_readiness_task_status(
            task_id,
            f.task_status_payload(target_status, **extra),
            headers or INTEGRATION_MANAGER,
        )
    )


def read_task(api: ApiClient, task_id: str, headers=None) -> Entity:
    return get_success_data(api.get_readiness_task(task_id, headers or INTEGRATION_MANAGER))


def in_progress_task(api: ApiClient, acquisition_id: str, **overrides: Any) -> Entity:
    task = create_task(api, acquisition_id, **overrides)
    return set_task_status(api, task["id"], TASK_STATUS_IN_PROGRESS)


def create_report(
    api: ApiClient,
    acquisition_id: str,
    physician_id: str,
    applied_comp_plan_id: str,
    **overrides: Any,
) -> Entity:
    return get_success_data(
        api.create_performance_report(
            f.performance_report_payload(
                acquisition_id, physician_id, applied_comp_plan_id, **overrides
            ),
            INTEGRATION_MANAGER,
        )
    )


def novated_contract(
    api: ApiClient, acquisition_id: str, physician_id: str, **contract_overrides: Any
) -> Dict[str, Entity]:
    """Walk a payer contract all the way to NOVATED via an approved package.

    Novation requires at least one APPROVED credentialing package on the
    contract, so the package is filed and approved on the way. The contractual
    notice period defaults to zero days here because `RECORD_CONSENT` refuses to
    run until that period has actually elapsed on the logical clock.
    """
    contract_overrides.setdefault("notice_days_required", 0)
    contract = create_payer_contract(api, acquisition_id, **contract_overrides)
    act_on_novation(api, contract["id"], "SEND_NOTICE")
    package = create_package(
        api, acquisition_id, physician_id, contract["id"], submitted_on="2026-08-03"
    )
    set_package_status(api, package["id"], "SUBMITTED")
    set_package_status(api, package["id"], "IN_REVIEW")
    package = set_package_status(api, package["id"], "APPROVED")
    contract = act_on_novation(api, contract["id"], "RECORD_CONSENT")
    contract = act_on_novation(api, contract["id"], "NOVATE")
    return {"contract": contract, "package": package}


def all_ids(rows: List[Entity]) -> List[str]:
    return [row["id"] for row in rows]


# ---------------------------------------------------------------------------
# pytest fixtures over the most reused chains
# ---------------------------------------------------------------------------


@pytest.fixture
def clock_at_default(api: ApiClient) -> str:
    """Park the clock on the PRD's pre-set reading so date rules are deterministic."""
    reset_clock(api)
    return DEFAULT_CLOCK_INSTANT


@pytest.fixture
def acquisition(api: ApiClient, clock_at_default: str) -> Entity:
    return create_acquisition(api)


@pytest.fixture
def diligence_fixture(api: ApiClient, clock_at_default: str) -> Dict[str, Entity]:
    return diligence_deal(api)


@pytest.fixture
def board_review_fixture(api: ApiClient, clock_at_default: str) -> Dict[str, Entity]:
    return board_review_deal(api)


@pytest.fixture
def signed_fixture(api: ApiClient, clock_at_default: str) -> Dict[str, Entity]:
    return signed_deal(api)


@pytest.fixture
def closed_fixture(api: ApiClient, clock_at_default: str) -> Dict[str, Entity]:
    return closed_deal(api)
