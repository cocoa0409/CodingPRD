"""Transitions on one entity gated by the state of a different entity.

Closing the deal is gated on the readiness checklist; converting a
provider-based department is gated on the Medicare payer contract having
novated. In both cases the identical request is refused and then accepted once
the other entity moves.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    CONTRACT_FORM_ASSIGNABLE,
    CONVERSION_STATUS_ATTESTED,
    CONVERSION_STATUS_CONVERTED,
    CONVERSION_STATUS_NOTICES_ISSUED,
    CONVERSION_TYPE_PROVIDER_BASED_DEPARTMENT,
    DEAL_STATUS_CLOSED,
    DEAL_STATUS_SIGNED,
    DEFAULT_CLOCK_INSTANT,
    NOVATION_ACTION_NOVATE,
    NOVATION_ACTION_RECORD_CONSENT,
    NOVATION_ACTION_SEND_NOTICE,
    NOVATION_CONSENT_RECEIVED,
    NOVATION_NOVATED,
    PACKAGE_STATUS_APPROVED,
    PACKAGE_STATUS_IN_REVIEW,
    PACKAGE_STATUS_SUBMITTED,
    PAYER_TYPE_MEDICARE,
    POSTURE_AT_RISK,
    POSTURE_READY,
    TASK_COMPLIANCE_TRAINING,
    TASK_STATUS_COMPLETE,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_OPEN,
    TASK_STATUS_WAIVED,
    USER_COMPLIANCE_OFFICER,
    USER_INTEGRATION_MANAGER,
)
from test_helpers.fixtures import (
    COMPLIANCE_OFFICER,
    DEAL_LEAD,
    INTEGRATION_MANAGER,
    act_on_novation,
    create_conversion,
    create_package,
    create_payer_contract,
    create_task,
    in_progress_task,
    read_acquisition,
    read_task,
    set_conversion_status,
    set_package_status,
    set_task_status,
    signed_deal,
)

MEDICARE_PACKAGE_SUBMITTED_ON = "2026-09-02"
MEDICARE_PROJECTED_EFFECTIVE_ON = "2026-11-01"
FULL_COVERAGE_BPS = 10_000
ADEQUATE_LEAD_DAYS = 30
PROVIDER_BASED_UPLIFT_BPS = 4_000


def _signed_deal_with_a_started_checklist_line(api: ApiClient):
    deal = signed_deal(api)
    deal["task"] = in_progress_task(
        api, deal["acquisition"]["id"], task_code=TASK_COMPLIANCE_TRAINING
    )
    return deal


def _close(api: ApiClient, acquisition_id: str):
    return api.set_acquisition_status(
        acquisition_id, f.acquisition_status_payload(DEAL_STATUS_CLOSED), DEAL_LEAD
    )


def test_closing_is_refused_while_a_blocking_line_is_still_in_progress(api: ApiClient):
    """The deal cannot close on another entity's unfinished work.

    PRD: "`readiness_posture` must be `READY`, or the request fails with
    `ERR_READINESS_NOT_READY` — and because an acquisition with no blocking
    checklist lines reads `BLOCKED`, such a deal fails here rather than closing on
    an empty checklist."

    Design: Difficulty/cross_entity_state_dependency/acquisition_close_requires_every_blocking_readiness_task_terminal
    """
    deal = _signed_deal_with_a_started_checklist_line(api)
    acquisition_id = deal["acquisition"]["id"]

    before = read_acquisition(api, acquisition_id)
    assert before["readiness_posture"] == POSTURE_AT_RISK

    rejected = _close(api, acquisition_id)
    validate_error(rejected, ApiErrorId.READINESS_NOT_READY, 422)

    unchanged = read_acquisition(api, acquisition_id)
    a.assert_status(unchanged, DEAL_STATUS_SIGNED, "deal_status")
    a.assert_fields_null(unchanged, "closed_at")
    a.assert_status(read_task(api, deal["task"]["id"]), TASK_STATUS_IN_PROGRESS)


def test_completing_the_line_lets_the_identical_close_request_succeed(api: ApiClient):
    """Nothing about the request changes; only the other entity's state does.

    PRD: "Completion stores the caller's `X-User-ID` in `verified_by_user_id` and
    recomputes the posture."

    Design: Difficulty/cross_entity_state_dependency/acquisition_close_requires_every_blocking_readiness_task_terminal
    """
    deal = _signed_deal_with_a_started_checklist_line(api)
    acquisition_id = deal["acquisition"]["id"]
    validate_error(_close(api, acquisition_id), ApiErrorId.READINESS_NOT_READY, 422)

    completed = set_task_status(api, deal["task"]["id"], TASK_STATUS_COMPLETE)
    a.assert_status(completed, TASK_STATUS_COMPLETE)
    assert completed["verified_by_user_id"] == USER_INTEGRATION_MANAGER

    ready = read_acquisition(api, acquisition_id)
    assert ready["readiness_posture"] == POSTURE_READY

    closed = validate_success(_close(api, acquisition_id))
    a.assert_status(closed, DEAL_STATUS_CLOSED, "deal_status")
    a.assert_instant_equals(closed["closed_at"], DEFAULT_CLOCK_INSTANT, "closed_at")


def test_a_waived_blocking_line_satisfies_the_gate_just_as_completion_does(api: ApiClient):
    """Waiving is the alternative terminal, and it requires a real justification.

    PRD: "A waived blocking line counts as satisfied for posture purposes, which
    is the whole point of the waiver."

    Design: Difficulty/cross_entity_state_dependency/acquisition_close_requires_every_blocking_readiness_task_terminal
    """
    deal = signed_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    task = create_task(api, acquisition_id, task_code=TASK_COMPLIANCE_TRAINING)
    a.assert_status(task, TASK_STATUS_OPEN)

    unjustified = api.set_readiness_task_status(
        task["id"], f.task_status_payload(TASK_STATUS_WAIVED), COMPLIANCE_OFFICER
    )
    validate_error(unjustified, ApiErrorId.WAIVER_JUSTIFICATION_REQUIRED, 422)

    waived = set_task_status(
        api,
        task["id"],
        TASK_STATUS_WAIVED,
        headers=COMPLIANCE_OFFICER,
        waiver_justification="Training deferred to the health system's own annual cycle.",
    )
    a.assert_status(waived, TASK_STATUS_WAIVED)
    assert waived["verified_by_user_id"] == USER_COMPLIANCE_OFFICER

    ready = read_acquisition(api, acquisition_id)
    assert ready["readiness_posture"] == POSTURE_READY

    closed = validate_success(_close(api, acquisition_id))
    a.assert_status(closed, DEAL_STATUS_CLOSED, "deal_status")


# ---------------------------------------------------------------------------
# The provider-based conversion gated on the Medicare novation
# ---------------------------------------------------------------------------


def _signed_deal_with_a_consented_medicare_contract(api: ApiClient):
    """A Medicare contract stuck at CONSENT_RECEIVED because no package is approved."""
    deal = signed_deal(api)
    acquisition_id = deal["acquisition"]["id"]

    contract = create_payer_contract(
        api,
        acquisition_id,
        payer_name="Medicare Part B",
        payer_type=PAYER_TYPE_MEDICARE,
        contract_form=CONTRACT_FORM_ASSIGNABLE,
        notice_days_required=0,
        annual_revenue_share_bps=3_500,
    )
    act_on_novation(api, contract["id"], NOVATION_ACTION_SEND_NOTICE)

    package = create_package(
        api,
        acquisition_id,
        deal["physician"]["id"],
        contract["id"],
        submitted_on=MEDICARE_PACKAGE_SUBMITTED_ON,
    )
    set_package_status(api, package["id"], PACKAGE_STATUS_SUBMITTED)
    package = set_package_status(api, package["id"], PACKAGE_STATUS_IN_REVIEW)
    contract = act_on_novation(api, contract["id"], NOVATION_ACTION_RECORD_CONSENT)

    conversion = create_conversion(
        api,
        acquisition_id,
        site_name="Lakeside Main Campus Clinic",
        conversion_type=CONVERSION_TYPE_PROVIDER_BASED_DEPARTMENT,
    )
    set_conversion_status(api, conversion["id"], CONVERSION_STATUS_ATTESTED)
    conversion = set_conversion_status(api, conversion["id"], CONVERSION_STATUS_NOTICES_ISSUED)

    deal["contract"] = contract
    deal["package"] = package
    deal["conversion"] = conversion
    return deal


def _convert(api: ApiClient, conversion_id: str):
    return api.set_billing_conversion_status(
        conversion_id,
        f.conversion_status_payload(CONVERSION_STATUS_CONVERTED),
        INTEGRATION_MANAGER,
    )


def test_a_provider_based_site_cannot_convert_until_medicare_novates(api: ApiClient):
    """The conversion is gated on a payer contract row, not on its own state.

    PRD: "When `conversion_type` is `PROVIDER_BASED_DEPARTMENT`, some payer
    contract on the same acquisition with `payer_type` `MEDICARE` must be in
    `novation_status` `NOVATED`, or the request fails with
    `ERR_PAYER_NOVATION_INCOMPLETE` — a provider-based department bills Medicare
    under the health system's number, and that requires the Medicare relationship
    to have novated."

    Design: Difficulty/cross_entity_state_dependency/provider_based_conversion_requires_medicare_contract_novated
    """
    deal = _signed_deal_with_a_consented_medicare_contract(api)
    assert deal["contract"]["novation_status"] == NOVATION_CONSENT_RECEIVED
    assert deal["contract"]["consent_received_on"] == "2026-08-01"

    rejected = _convert(api, deal["conversion"]["id"])
    validate_error(rejected, ApiErrorId.PAYER_NOVATION_INCOMPLETE, 422)

    unchanged = validate_success(
        api.get_billing_conversion(deal["conversion"]["id"], INTEGRATION_MANAGER)
    )
    a.assert_status(unchanged, CONVERSION_STATUS_NOTICES_ISSUED)


def test_the_conversions_own_notice_figures_are_already_satisfied(api: ApiClient):
    """The refusal is not about this site's notices, which are complete and timely.

    PRD: "`provider_based_uplift_bps` is 4000 when `conversion_type` is
    `PROVIDER_BASED_DEPARTMENT` and exactly 0 when it is `FREESTANDING_CLINIC`."

    Design: Difficulty/cross_entity_state_dependency/provider_based_conversion_requires_medicare_contract_novated
    """
    deal = _signed_deal_with_a_consented_medicare_contract(api)
    conversion = deal["conversion"]

    assert conversion["notice_coverage_bps"] == FULL_COVERAGE_BPS
    assert conversion["notice_lead_days"] == ADEQUATE_LEAD_DAYS
    assert conversion["provider_based_uplift_bps"] == PROVIDER_BASED_UPLIFT_BPS

    package = validate_success(
        api.get_credentialing_package(deal["package"]["id"], INTEGRATION_MANAGER)
    )
    assert package["projected_effective_on"] == MEDICARE_PROJECTED_EFFECTIVE_ON
    assert package["retro_billing_allowed"] is True


def test_novating_the_medicare_contract_unblocks_the_identical_conversion(api: ApiClient):
    """Approving the package permits the novation, and the novation permits the conversion.

    PRD: "`NOVATE` moves either `CONSENT_RECEIVED → NOVATED` or
    `NEW_AGREEMENT_PENDING → NOVATED`, and in both cases requires at least one
    credentialing package on this contract to be in `APPROVED`: a payer
    relationship is not novated until at least one provider is credentialed under
    it."

    Design: Difficulty/cross_entity_state_dependency/provider_based_conversion_requires_medicare_contract_novated
    """
    deal = _signed_deal_with_a_consented_medicare_contract(api)
    validate_error(
        _convert(api, deal["conversion"]["id"]), ApiErrorId.PAYER_NOVATION_INCOMPLETE, 422
    )

    set_package_status(api, deal["package"]["id"], PACKAGE_STATUS_APPROVED)
    novated = act_on_novation(api, deal["contract"]["id"], NOVATION_ACTION_NOVATE)
    assert novated["novation_status"] == NOVATION_NOVATED

    converted = validate_success(_convert(api, deal["conversion"]["id"]))
    a.assert_status(converted, CONVERSION_STATUS_CONVERTED)
