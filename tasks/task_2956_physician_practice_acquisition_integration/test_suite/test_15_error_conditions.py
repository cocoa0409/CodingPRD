"""The violations the specification names, and the neighbours that stay legal.

Each rule here is exercised at the point where it actually bites: a uniqueness
guard against the scope it is declared over, a transition precondition against
the row that fails it, and a gate ladder against the order §2.12 fixes. Every
refusal is followed by the closest legal sibling, because a rule that rejects
everything is indistinguishable from one that rejects the right thing.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import PRECEDENCE_RANK, ApiErrorId
from test_helpers.constants import (
    BATCH_ACTION_EXTRACT,
    BATCH_ACTION_LOAD,
    BATCH_STATUS_RECONCILED,
    BATCH_STATUS_STAGED,
    CHART_TYPE_IMAGING,
    CHART_TYPE_STRUCTURED,
    CLEARANCE_CLEARED,
    CONVERSION_STATUS_ATTESTED,
    CONVERSION_STATUS_NOTICES_ISSUED,
    CONVERSION_STATUS_WITHDRAWN,
    CONVERSION_TYPE_FREESTANDING_CLINIC,
    CR_CONCLUSION_NOT_REASONABLE,
    CR_CONCLUSION_REASONABLE,
    DEAL_STATUS_BOARD_REVIEW,
    DEAL_STATUS_CLOSED,
    DEAL_STATUS_DILIGENCE,
    DEAL_STATUS_SIGNED,
    DEFAULT_CLOCK_INSTANT,
    DISPOSITION_ASSUMED,
    DISPOSITION_ESCROWED,
    DISPOSITION_EXCLUDED,
    DISPOSITION_INDEMNIFIED,
    DISPOSITION_UNASSIGNED,
    EMPLOYMENT_OFFERED,
    EMPLOYMENT_PROSPECTIVE,
    LIABILITY_EQUIPMENT_LEASE,
    LIABILITY_MALPRACTICE_TAIL,
    LIABILITY_PAYER_REFUND_EXPOSURE,
    LIABILITY_STARK_SELF_DISCLOSURE,
    LIABILITY_UNPAID_PTO,
    LICENSE_EXPIRY_C,
    NOVATION_ACTION_SEND_NOTICE,
    NOVATION_NOTICE_SENT,
    NPI_B,
    NPI_C,
    OPINION_STATUS_ACCEPTED,
    OPINION_STATUS_DRAFT,
    OPINION_STATUS_SUBMITTED,
    OPINION_STATUS_SUPERSEDED,
    OPINION_TYPE_COMMERCIAL_REASONABLENESS,
    OPINION_TYPE_FMV,
    PACKAGE_STATUS_DRAFT,
    PACKAGE_STATUS_SUBMITTED,
    PACKAGE_STATUS_WITHDRAWN,
    PAYER_TYPE_MEDICAID,
    PAYER_TYPE_MEDICARE,
    PHYSICIAN_NAME_A,
    PHYSICIAN_NAME_B,
    PHYSICIAN_NAME_C,
    PLAN_STATUS_APPROVED,
    PLAN_STATUS_EXECUTED,
    PLAN_STATUS_SUBMITTED,
    POLICY_FORM_CLAIMS_MADE,
    POSTURE_READY,
    SPECIALTY_CARDIOLOGY,
    STANDARD_FMV_CONCLUDED_CENTS,
    STANDARD_FMV_EXPIRES_ON,
    STANDARD_PLAN_PERCENTILE,
    STANDARD_PLAN_TOTAL_CENTS,
    STRUCTURE_ASSET,
    STRUCTURE_EQUITY,
    TASK_COMPLIANCE_TRAINING,
    TASK_IT_DATA_MIGRATION,
    TASK_STATUS_COMPLETE,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_OPEN,
)
from test_helpers.fixtures import (
    COMPENSATION_DESIGNER,
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_ALT,
    DEAL_LEAD,
    INTEGRATION_MANAGER,
    VALUATION_ANALYST,
    accept_opinion,
    accepted_cr_opinion,
    accepted_income_fmv,
    accepted_market_fmv,
    acquisition_version,
    act_on_novation,
    advance_deal_status,
    approved_plan,
    board_review_deal,
    create_acquisition,
    create_batch,
    create_cardiology_acquisition,
    create_conversion,
    create_liability,
    create_package,
    create_payer_contract,
    create_physician,
    create_plan,
    create_task,
    diligence_deal,
    execute_plan,
    executed_plan,
    file_cr_opinion,
    file_market_fmv,
    park_clock_on_date,
    progress_batch,
    read_acquisition,
    reconcile_batch,
    reset_clock,
    second_physician,
    set_clearance,
    set_conversion_status,
    set_disposition,
    set_package_status,
    set_task_status,
    submit_opinion,
    submit_plan,
)

BATCH_LABEL = "CHARTS-2026-A"
IMAGING_LABEL = "IMAGES-2026-A"
EMPTY_BATCH_LABEL = "PLACEHOLDER-2026-A"
SECOND_PRACTICE_NAME = "Northgate Cardiology Associates"
FULL_RECORD_COUNT = 20_000


# ---------------------------------------------------------------------------
# Uniqueness guards and the scope each is declared over
# ---------------------------------------------------------------------------


def _two_deals_the_first_with_a_provider(api: ApiClient):
    reset_clock(api)
    first = create_acquisition(api)
    second = create_acquisition(
        api, target_practice_name=SECOND_PRACTICE_NAME, specialty=SPECIALTY_CARDIOLOGY
    )
    provider = create_physician(api, first["id"])
    return first, second, provider


def test_a_national_provider_identifier_is_unique_across_every_deal(api: ApiClient):
    """The second deal shares nothing with the first, and the identifier still collides.

    PRD: "An `npi` is exactly ten decimal digits and must be globally unique
    across every physician in the system, not merely within one deal: a collision
    is `ERR_DUPLICATE_NPI`."

    Design: Corner/errors/duplicate_npi_across_two_acquisitions_rejected
    """
    first, second, provider = _two_deals_the_first_with_a_provider(api)

    collision = api.create_physician(
        f.physician_payload(
            second["id"],
            npi=provider["npi"],
            full_name=PHYSICIAN_NAME_A,
            specialty=SPECIALTY_CARDIOLOGY,
        ),
        DEAL_LEAD,
    )

    validate_error(collision, ApiErrorId.DUPLICATE_NPI, 409)
    assert a.assert_total_count(api.list_physicians({"acquisition_id": second["id"]}, DEAL_LEAD), 0) == []
    untouched = validate_success(api.get_physician(provider["id"], DEAL_LEAD))
    assert untouched["employment_status"] == EMPLOYMENT_PROSPECTIVE
    assert untouched["acquisition_id"] == first["id"]
    a.assert_version_unchanged(provider, untouched)


def test_a_distinct_identifier_joins_the_second_deal_without_complaint(api: ApiClient):
    """Only the identifier was in the way, so changing it is the whole fix.

    PRD: "Registering a physician is also the `DealLead`'s work. The payload
    carries the `acquisition_id` of the deal being joined, the provider's `npi`,
    their `full_name`, their own `specialty` from the same four-value
    enumeration, and their `state_license_expires_on`."

    Design: Corner/errors/duplicate_npi_across_two_acquisitions_rejected
    """
    _first, second, _provider = _two_deals_the_first_with_a_provider(api)

    accepted = api.create_physician(
        f.physician_payload(second["id"], npi=NPI_B, specialty=SPECIALTY_CARDIOLOGY),
        DEAL_LEAD,
    )

    registered = validate_success(accepted, 201)
    assert registered["npi"] == NPI_B
    assert registered["acquisition_id"] == second["id"]
    assert registered["employment_status"] == EMPLOYMENT_PROSPECTIVE
    rows = a.assert_total_count(api.list_physicians({"acquisition_id": second["id"]}, DEAL_LEAD), 1)
    a.assert_contains_id(rows, registered["id"])


def _two_deals_the_first_with_a_batch(api: ApiClient):
    reset_clock(api)
    first = create_acquisition(api)
    second = create_acquisition(
        api, target_practice_name=SECOND_PRACTICE_NAME, specialty=SPECIALTY_CARDIOLOGY
    )
    batch = create_batch(
        api,
        first["id"],
        batch_label=BATCH_LABEL,
        chart_type=CHART_TYPE_STRUCTURED,
        record_count=FULL_RECORD_COUNT,
    )
    return first, second, batch


def test_a_repeated_batch_label_within_one_deal_is_refused(api: ApiClient):
    """The refused write leaves the batch it collided with exactly as it was.

    PRD: "The payload names the `acquisition_id`, a human-readable `batch_label`
    that must be unique within that one acquisition — a collision is
    `ERR_DUPLICATE_BATCH_LABEL`, and the same label may be reused freely across
    different acquisitions — the `source_system` the charts are extracted from,
    one of `ATHENA`, `ECLINICALWORKS`, or `PAPER_CHART`, the `chart_type`, one of
    `STRUCTURED`, `IMAGING`, or `SCANNED_DOCUMENT`, the `record_count` staged in
    the batch, and the `last_encounter_on` date of the most recent clinical
    encounter represented in the batch."

    Design: Corner/errors/duplicate_batch_label_within_one_acquisition_rejected
    """
    first, _second, batch = _two_deals_the_first_with_a_batch(api)

    collision = api.create_ehr_migration_batch(
        f.ehr_migration_batch_payload(
            first["id"],
            batch_label=BATCH_LABEL,
            chart_type=CHART_TYPE_IMAGING,
            record_count=5_000,
            last_encounter_on="2026-06-30",
        ),
        INTEGRATION_MANAGER,
    )

    validate_error(collision, ApiErrorId.DUPLICATE_BATCH_LABEL, 409)
    rows = a.assert_total_count(
        api.list_ehr_migration_batches({"acquisition_id": first["id"]}, INTEGRATION_MANAGER), 1
    )
    a.assert_contains_id(rows, batch["id"])
    unaffected = validate_success(api.get_ehr_migration_batch(batch["id"], INTEGRATION_MANAGER))
    a.assert_status(unaffected, BATCH_STATUS_STAGED)
    assert unaffected["record_count"] == FULL_RECORD_COUNT
    a.assert_version_unchanged(batch, unaffected)


def test_the_same_label_on_a_second_deal_is_accepted(api: ApiClient):
    """Label uniqueness is scoped to one acquisition, so the neighbour may reuse it.

    PRD: "The payload names the `acquisition_id`, a human-readable `batch_label`
    that must be unique within that one acquisition — a collision is
    `ERR_DUPLICATE_BATCH_LABEL`, and the same label may be reused freely across
    different acquisitions — the `source_system` the charts are extracted from,
    one of `ATHENA`, `ECLINICALWORKS`, or `PAPER_CHART`, the `chart_type`, one of
    `STRUCTURED`, `IMAGING`, or `SCANNED_DOCUMENT`, the `record_count` staged in
    the batch, and the `last_encounter_on` date of the most recent clinical
    encounter represented in the batch."

    Design: Corner/errors/duplicate_batch_label_within_one_acquisition_rejected
    """
    _first, second, batch = _two_deals_the_first_with_a_batch(api)

    accepted = api.create_ehr_migration_batch(
        f.ehr_migration_batch_payload(
            second["id"],
            batch_label=BATCH_LABEL,
            chart_type=CHART_TYPE_IMAGING,
            record_count=5_000,
            last_encounter_on="2026-06-30",
        ),
        INTEGRATION_MANAGER,
    )

    twin = validate_success(accepted, 201)
    assert twin["batch_label"] == batch["batch_label"]
    assert twin["acquisition_id"] == second["id"]
    assert twin["id"] != batch["id"]
    a.assert_status(twin, BATCH_STATUS_STAGED)


# ---------------------------------------------------------------------------
# An empty batch: storable, never extractable
# ---------------------------------------------------------------------------


def _deal_with_an_empty_batch(api: ApiClient):
    reset_clock(api)
    acquisition = create_acquisition(api)
    response = api.create_ehr_migration_batch(
        f.ehr_migration_batch_payload(
            acquisition["id"], batch_label=EMPTY_BATCH_LABEL, record_count=0
        ),
        INTEGRATION_MANAGER,
    )
    batch = validate_success(response, 201)
    return acquisition, batch


def test_an_empty_batch_is_storable_but_can_never_be_extracted(api: ApiClient):
    """A placeholder is allowed to exist and refused permission to move.

    PRD: "`EXTRACT` moves `STAGED → EXTRACTED` and requires `record_count` to be
    greater than 0, failing with `ERR_EMPTY_MIGRATION_BATCH` otherwise: a
    placeholder batch may sit staged forever but can never be extracted, because
    an empty batch has no defined match rate."

    Design: Corner/errors/empty_migration_batch_cannot_be_extracted
    """
    _acquisition, batch = _deal_with_an_empty_batch(api)
    assert batch["record_count"] == 0
    a.assert_status(batch, BATCH_STATUS_STAGED)

    refused = api.progress_ehr_migration_batch(
        batch["id"], f.batch_progress_payload(BATCH_ACTION_EXTRACT), INTEGRATION_MANAGER
    )

    validate_error(refused, ApiErrorId.EMPTY_MIGRATION_BATCH, 422)
    unchanged = validate_success(api.get_ehr_migration_batch(batch["id"], INTEGRATION_MANAGER))
    a.assert_status(unchanged, BATCH_STATUS_STAGED)
    assert unchanged["retry_count"] == 0
    assert unchanged["match_rate_bps"] == 0
    assert unchanged["unprocessed_count"] == 0
    a.assert_version_unchanged(batch, unchanged)


def test_the_migration_line_cannot_complete_while_the_placeholder_sits_staged(api: ApiClient):
    """A batch that can never move keeps its own checklist line permanently open.

    PRD: "Completing it, `IN_PROGRESS → COMPLETE`, is available to the same two
    roles and carries two conditional preconditions: when `task_code` is
    `HR_STAFFING_PLAN`, the acquisition's `hr_staffing_coverage_pct` must be at
    least 80.00; when `task_code` is `IT_DATA_MIGRATION`, every migration batch on
    the acquisition must be in `RECONCILED` or `ABORTED`, or the request fails
    with `ERR_MIGRATION_INCOMPLETE`."

    Design: Corner/errors/empty_migration_batch_cannot_be_extracted
    """
    acquisition, batch = _deal_with_an_empty_batch(api)
    task = create_task(
        api, acquisition["id"], task_code=TASK_IT_DATA_MIGRATION, due_on="2026-10-20"
    )
    started = set_task_status(api, task["id"], TASK_STATUS_IN_PROGRESS)
    a.assert_status(started, TASK_STATUS_IN_PROGRESS)

    refused = api.set_readiness_task_status(
        task["id"], f.task_status_payload(TASK_STATUS_COMPLETE), INTEGRATION_MANAGER
    )

    validate_error(refused, ApiErrorId.MIGRATION_INCOMPLETE, 422)
    still_open = validate_success(api.get_readiness_task(task["id"], INTEGRATION_MANAGER))
    a.assert_status(still_open, TASK_STATUS_IN_PROGRESS)
    assert still_open["verified_by_user_id"] is None
    a.assert_status(
        validate_success(api.get_ehr_migration_batch(batch["id"], INTEGRATION_MANAGER)),
        BATCH_STATUS_STAGED,
    )


# ---------------------------------------------------------------------------
# One live credentialing package per provider per payer
# ---------------------------------------------------------------------------

MEDICARE_PAYER_NAME = "Medicare Part B"
MEDICARE_REVENUE_SHARE_BPS = 3800
FIRST_FILING_ON = "2026-08-03"
SECOND_FILING_ON = "2026-08-04"


def _one_provider_two_payers_one_live_package(api: ApiClient):
    reset_clock(api)
    acquisition = create_acquisition(api)
    physician = create_physician(api, acquisition["id"])
    commercial = create_payer_contract(api, acquisition["id"])
    medicare = create_payer_contract(
        api,
        acquisition["id"],
        payer_name=MEDICARE_PAYER_NAME,
        payer_type=PAYER_TYPE_MEDICARE,
        notice_days_required=0,
        annual_revenue_share_bps=MEDICARE_REVENUE_SHARE_BPS,
    )
    package = create_package(
        api,
        acquisition["id"],
        physician["id"],
        commercial["id"],
        submitted_on=FIRST_FILING_ON,
    )
    return acquisition, physician, commercial, medicare, package


def test_a_second_live_package_for_the_same_pair_is_refused(api: ApiClient):
    """The guard is on the provider-and-payer pair, so the other payer stays open.

    PRD: "At most one live package may exist for a given physician-and-payer
    pair: if another package for the same `physician_id` and `payer_contract_id`
    is in `DRAFT`, `SUBMITTED`, `IN_REVIEW`, or `APPROVED`, the create is rejected
    with `ERR_DUPLICATE_CREDENTIALING_PACKAGE`."

    Design: Corner/errors/second_live_credentialing_package_for_one_pair_rejected
    """
    acquisition, physician, commercial, medicare, package = (
        _one_provider_two_payers_one_live_package(api)
    )
    a.assert_status(package, PACKAGE_STATUS_DRAFT)

    collision = api.create_credentialing_package(
        f.credentialing_package_payload(
            acquisition["id"], physician["id"], commercial["id"], submitted_on=SECOND_FILING_ON
        ),
        INTEGRATION_MANAGER,
    )

    validate_error(collision, ApiErrorId.DUPLICATE_CREDENTIALING_PACKAGE, 409)
    rows = a.assert_total_count(
        api.list_credentialing_packages({"payer_contract_id": commercial["id"]}, INTEGRATION_MANAGER),
        1,
    )
    a.assert_contains_id(rows, package["id"])

    other_payer = api.create_credentialing_package(
        f.credentialing_package_payload(
            acquisition["id"], physician["id"], medicare["id"], submitted_on=SECOND_FILING_ON
        ),
        INTEGRATION_MANAGER,
    )
    second_pair = validate_success(other_payer, 201)
    assert second_pair["physician_id"] == physician["id"]
    assert second_pair["payer_contract_id"] == medicare["id"]
    a.assert_status(second_pair, PACKAGE_STATUS_DRAFT)


def test_withdrawing_the_first_package_frees_the_pair_for_a_refiling(api: ApiClient):
    """Liveness is a status set, and WITHDRAWN is outside it.

    PRD: "A package that was denied or withdrawn does not block a fresh filing."

    Design: Corner/errors/second_live_credentialing_package_for_one_pair_rejected
    """
    acquisition, physician, commercial, _medicare, package = (
        _one_provider_two_payers_one_live_package(api)
    )
    refiling = f.credentialing_package_payload(
        acquisition["id"], physician["id"], commercial["id"], submitted_on=SECOND_FILING_ON
    )
    validate_error(
        api.create_credentialing_package(refiling, INTEGRATION_MANAGER),
        ApiErrorId.DUPLICATE_CREDENTIALING_PACKAGE,
        409,
    )

    withdrawn = set_package_status(api, package["id"], PACKAGE_STATUS_WITHDRAWN)
    a.assert_status(withdrawn, PACKAGE_STATUS_WITHDRAWN)

    accepted = api.create_credentialing_package(refiling, INTEGRATION_MANAGER)

    fresh = validate_success(accepted, 201)
    assert fresh["id"] != package["id"]
    assert fresh["submitted_on"] == SECOND_FILING_ON
    a.assert_status(fresh, PACKAGE_STATUS_DRAFT)
    a.assert_total_count(
        api.list_credentialing_packages({"payer_contract_id": commercial["id"]}, INTEGRATION_MANAGER),
        2,
    )


# ---------------------------------------------------------------------------
# Opinion type and method must agree, and completeness is checked first
# ---------------------------------------------------------------------------


def test_a_fair_market_value_opinion_may_not_be_filed_as_a_narrative(api: ApiClient):
    """The mismatch surfaces only because the narrative's own input is present.

    PRD: "`method` takes one of `INCOME_APPROACH`, `MARKET_APPROACH`, or
    `NARRATIVE`, and it must be compatible with `opinion_type`: an `FMV` opinion
    requires `INCOME_APPROACH` or `MARKET_APPROACH`, and a
    `COMMERCIAL_REASONABLENESS` opinion requires `NARRATIVE`."

    Design: Corner/errors/fmv_opinion_with_narrative_method_rejected
    """
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    version = acquisition_version(api, acquisition_id, VALUATION_ANALYST)

    refused = api.create_valuation_opinion(
        f.cr_opinion_payload(
            acquisition_id,
            version,
            opinion_type=OPINION_TYPE_FMV,
            cr_conclusion=CR_CONCLUSION_REASONABLE,
        ),
        VALUATION_ANALYST,
    )

    validate_error(refused, ApiErrorId.OPINION_METHOD_MISMATCH, 422)
    a.assert_total_count(
        api.list_valuation_opinions({"acquisition_id": acquisition_id}, VALUATION_ANALYST), 0
    )

    mirrored = api.create_valuation_opinion(
        f.market_fmv_payload(
            acquisition_id, version, opinion_type=OPINION_TYPE_COMMERCIAL_REASONABLENESS
        ),
        VALUATION_ANALYST,
    )
    validate_error(mirrored, ApiErrorId.OPINION_METHOD_MISMATCH, 422)
    assert acquisition_version(api, acquisition_id, VALUATION_ANALYST) == version


def test_a_missing_narrative_conclusion_is_reported_before_the_mismatch(api: ApiClient):
    """Two defects in one body, and the completeness rule is the one that answers.

    PRD: "Beyond compatibility, the method dictates which inputs must be present,
    and a gap is `ERR_MISSING_VALUATION_INPUT`: `INCOME_APPROACH` requires
    `normalized_ebitda_cents`, `projection_years`, `ebitda_growth_bps`,
    `discount_rate_bps`, and `terminal_growth_bps`; `MARKET_APPROACH` requires
    `normalized_ebitda_cents` and `market_multiple_bps`; `NARRATIVE` requires
    `cr_conclusion`, which is either `REASONABLE` or `NOT_REASONABLE`."

    Design: Corner/errors/fmv_opinion_with_narrative_method_rejected
    """
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    version = acquisition_version(api, acquisition_id, VALUATION_ANALYST)
    assert (
        PRECEDENCE_RANK[ApiErrorId.MISSING_VALUATION_INPUT]
        < PRECEDENCE_RANK[ApiErrorId.OPINION_METHOD_MISMATCH]
    )

    refused = api.create_valuation_opinion(
        f.without(
            f.cr_opinion_payload(acquisition_id, version, opinion_type=OPINION_TYPE_FMV),
            "cr_conclusion",
        ),
        VALUATION_ANALYST,
    )

    validate_error(refused, ApiErrorId.MISSING_VALUATION_INPUT, 422)
    a.assert_total_count(
        api.list_valuation_opinions({"acquisition_id": acquisition_id}, VALUATION_ANALYST), 0
    )


# ---------------------------------------------------------------------------
# An unattested opinion: drafted for ever, never submitted
# ---------------------------------------------------------------------------


def test_an_opinion_without_an_independence_attestation_cannot_leave_draft(api: ApiClient):
    """The value was computed at filing time; only the exit from DRAFT is barred.

    PRD: "Submitting is the preparer's own act and nobody else's: the caller's
    `X-User-ID` must equal `prepared_by_user_id`, or the request fails with
    `ERR_NOT_PLAN_OWNER`, and `independence_attested` must be true, or it fails
    with `ERR_VALUER_INDEPENDENCE_NOT_ATTESTED`."

    Design: Corner/errors/unattested_opinion_cannot_be_submitted
    """
    deal = diligence_deal(api)
    opinion = file_market_fmv(api, deal["acquisition"]["id"], independence_attested=False)
    assert opinion["independence_attested"] is False
    a.assert_status(opinion, OPINION_STATUS_DRAFT)
    a.assert_money_equals(
        opinion["concluded_value_cents"], STANDARD_FMV_CONCLUDED_CENTS, "concluded_value_cents"
    )
    assert opinion["expires_on"] == STANDARD_FMV_EXPIRES_ON

    refused = api.set_valuation_opinion_status(
        opinion["id"], f.opinion_status_payload(OPINION_STATUS_SUBMITTED), VALUATION_ANALYST
    )

    validate_error(refused, ApiErrorId.VALUER_INDEPENDENCE_NOT_ATTESTED, 422)
    stuck = validate_success(api.get_valuation_opinion(opinion["id"], VALUATION_ANALYST))
    a.assert_status(stuck, OPINION_STATUS_DRAFT)
    assert stuck["independence_attested"] is False
    assert stuck["is_pinned"] is False
    a.assert_money_equals(
        stuck["concluded_value_cents"], STANDARD_FMV_CONCLUDED_CENTS, "concluded_value_cents"
    )
    a.assert_version_unchanged(opinion, stuck)


def test_an_attested_replacement_opinion_submits_where_the_first_could_not(api: ApiClient):
    """Nothing but the attestation flag separates the stuck draft from a live filing.

    PRD: "An opinion may perfectly well be drafted without an independence
    attestation; it simply cannot leave `DRAFT`."

    Design: Corner/errors/unattested_opinion_cannot_be_submitted
    """
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    stuck = file_market_fmv(api, acquisition_id, independence_attested=False)
    validate_error(
        api.set_valuation_opinion_status(
            stuck["id"], f.opinion_status_payload(OPINION_STATUS_SUBMITTED), VALUATION_ANALYST
        ),
        ApiErrorId.VALUER_INDEPENDENCE_NOT_ATTESTED,
        422,
    )

    replacement = file_market_fmv(api, acquisition_id, independence_attested=True)
    submitted = submit_opinion(api, replacement["id"])

    a.assert_status(submitted, OPINION_STATUS_SUBMITTED)
    assert submitted["id"] == replacement["id"]
    a.assert_money_equals(
        submitted["concluded_value_cents"], STANDARD_FMV_CONCLUDED_CENTS, "concluded_value_cents"
    )
    a.assert_status(
        validate_success(api.get_valuation_opinion(stuck["id"], VALUATION_ANALYST)),
        OPINION_STATUS_DRAFT,
    )


# ---------------------------------------------------------------------------
# The escrow pool: committed item by item, released in full
# ---------------------------------------------------------------------------

ESCROW_TOTAL_CENTS = 10_000_000
LEASE_CENTS = 2_500_000
REFUND_CENTS = 1_750_000
PTO_CENTS = 12_000_000
COMMITTED_AFTER_TWO_CENTS = 4_250_000
AVAILABLE_AFTER_TWO_CENTS = 5_750_000
AVAILABLE_AFTER_THE_RELEASE_CENTS = 8_250_000


def _two_escrowed_items_and_one_oversized_exposure(api: ApiClient):
    reset_clock(api)
    acquisition = create_acquisition(api)
    lease = create_liability(
        api,
        acquisition["id"],
        category=LIABILITY_EQUIPMENT_LEASE,
        description="Remaining term on the imaging suite lease",
        estimated_amount_cents=LEASE_CENTS,
    )
    refund = create_liability(
        api,
        acquisition["id"],
        category=LIABILITY_PAYER_REFUND_EXPOSURE,
        description="Open commercial payer audit for 2024 dates of service",
        estimated_amount_cents=REFUND_CENTS,
    )
    pto = create_liability(
        api,
        acquisition["id"],
        category=LIABILITY_UNPAID_PTO,
        description="Accrued and unused paid time off across the transferring staff",
        estimated_amount_cents=PTO_CENTS,
    )
    set_disposition(api, lease["id"], DISPOSITION_ESCROWED, disposition_note="Held pending consent")
    set_disposition(api, refund["id"], DISPOSITION_ESCROWED, disposition_note="Held pending audit")
    return acquisition, lease, refund, pto


def test_an_exposure_beyond_the_remaining_pool_is_refused(api: ApiClient):
    """The third item fails against what the first two left, not against the total.

    PRD: "`UNASSIGNED → ESCROWED` and `ASSUMED → ESCROWED` behave identically to
    one another: each requires that `estimated_amount_cents` does not exceed the
    acquisition's `escrow_available_cents`, failing with `ERR_ESCROW_INSUFFICIENT`
    otherwise, and each sets the item's `escrowed_amount_cents` to
    `estimated_amount_cents`, adds that amount to `escrow_committed_cents`, and
    subtracts it from `escrow_available_cents`."

    Design: Corner/errors/escrowing_an_item_above_the_available_balance_rejected
    """
    acquisition, _lease, _refund, pto = _two_escrowed_items_and_one_oversized_exposure(api)
    before = read_acquisition(api, acquisition["id"])
    a.assert_escrow(
        before, ESCROW_TOTAL_CENTS, COMMITTED_AFTER_TWO_CENTS, AVAILABLE_AFTER_TWO_CENTS
    )
    assert PTO_CENTS > AVAILABLE_AFTER_TWO_CENTS

    refused = api.set_liability_disposition(
        pto["id"],
        f.disposition_payload(DISPOSITION_ESCROWED, disposition_note="Held pending the true-up"),
        DEAL_LEAD,
    )

    validate_error(refused, ApiErrorId.ESCROW_INSUFFICIENT, 422)
    after = read_acquisition(api, acquisition["id"])
    a.assert_escrow(
        after, ESCROW_TOTAL_CENTS, COMMITTED_AFTER_TWO_CENTS, AVAILABLE_AFTER_TWO_CENTS
    )
    a.assert_version_unchanged(before, after)
    untouched = validate_success(api.get_liability_item(pto["id"], DEAL_LEAD))
    a.assert_status(untouched, DISPOSITION_UNASSIGNED, "disposition")
    a.assert_money_equals(untouched["escrowed_amount_cents"], 0, "escrowed_amount_cents")


def test_an_exposure_of_exactly_the_remaining_pool_is_accepted(api: ApiClient):
    """The comparison is inclusive, so an exact fit drains the pool to nothing.

    PRD: "`escrow_committed_cents` is at all times the sum of
    `escrowed_amount_cents` over the acquisition's liability items whose
    `disposition` is `ESCROWED`; `escrow_available_cents` is `escrow_total_cents`
    minus `escrow_committed_cents`."

    Design: Corner/errors/escrowing_an_item_above_the_available_balance_rejected
    """
    acquisition, _lease, _refund, _pto = _two_escrowed_items_and_one_oversized_exposure(api)
    exact_fit = create_liability(
        api,
        acquisition["id"],
        category=LIABILITY_UNPAID_PTO,
        description="Accrued paid time off for the transferring front-office staff",
        estimated_amount_cents=AVAILABLE_AFTER_TWO_CENTS,
    )

    escrowed = set_disposition(
        api, exact_fit["id"], DISPOSITION_ESCROWED, disposition_note="Held in full"
    )

    a.assert_status(escrowed, DISPOSITION_ESCROWED, "disposition")
    a.assert_money_equals(
        escrowed["escrowed_amount_cents"], AVAILABLE_AFTER_TWO_CENTS, "escrowed_amount_cents"
    )
    a.assert_escrow(
        read_acquisition(api, acquisition["id"]), ESCROW_TOTAL_CENTS, ESCROW_TOTAL_CENTS, 0
    )


def test_releasing_one_item_reopens_only_its_own_share_of_the_pool(api: ApiClient):
    """A release restores exactly what it committed, which is still not enough.

    PRD: "Finally, `ESCROWED → EXCLUDED` releases an escrowed item: it checks the
    structure-and-category legality for `EXCLUDED`, subtracts the item's
    `escrowed_amount_cents` from `escrow_committed_cents`, adds the same amount
    back to `escrow_available_cents`, and resets the item's own
    `escrowed_amount_cents` to 0."

    Design: Corner/errors/escrowing_an_item_above_the_available_balance_rejected
    """
    acquisition, lease, _refund, pto = _two_escrowed_items_and_one_oversized_exposure(api)

    released = set_disposition(
        api, lease["id"], DISPOSITION_EXCLUDED, disposition_note="Lessor took the balance back"
    )

    a.assert_status(released, DISPOSITION_EXCLUDED, "disposition")
    a.assert_money_equals(released["escrowed_amount_cents"], 0, "escrowed_amount_cents")
    a.assert_escrow(
        read_acquisition(api, acquisition["id"]),
        ESCROW_TOTAL_CENTS,
        REFUND_CENTS,
        AVAILABLE_AFTER_THE_RELEASE_CENTS,
    )
    still_refused = api.set_liability_disposition(
        pto["id"],
        f.disposition_payload(DISPOSITION_ESCROWED, disposition_note="Held pending the true-up"),
        DEAL_LEAD,
    )
    validate_error(still_refused, ApiErrorId.ESCROW_INSUFFICIENT, 422)
    a.assert_escrow(
        read_acquisition(api, acquisition["id"]),
        ESCROW_TOTAL_CENTS,
        REFUND_CENTS,
        AVAILABLE_AFTER_THE_RELEASE_CENTS,
    )


# ---------------------------------------------------------------------------
# Disposition legality is a joint function of structure and category
# ---------------------------------------------------------------------------

TAIL_CENTS = 4_000_000
ASSET_TAIL_CENTS = 1_200_000
STARK_CENTS = 900_000
EQUITY_PRACTICE_NAME = "Riverbend Physicians Group"


def _one_tail_on_an_equity_deal_and_one_on_an_asset_deal(api: ApiClient):
    reset_clock(api)
    equity = create_acquisition(
        api, target_practice_name=EQUITY_PRACTICE_NAME, structure=STRUCTURE_EQUITY
    )
    asset = create_acquisition(api, structure=STRUCTURE_ASSET)
    equity_tail = create_liability(
        api,
        equity["id"],
        category=LIABILITY_MALPRACTICE_TAIL,
        description="Uncovered tail on the retiring cardiologist's claims-made policy",
        estimated_amount_cents=TAIL_CENTS,
        indemnity_cap_cents=TAIL_CENTS,
    )
    asset_tail = create_liability(
        api,
        asset["id"],
        category=LIABILITY_MALPRACTICE_TAIL,
        description="Uncovered tail on a departing physician's policy",
        estimated_amount_cents=ASSET_TAIL_CENTS,
    )
    return equity, asset, equity_tail, asset_tail


def test_an_equity_buyer_may_not_leave_a_malpractice_tail_behind(api: ApiClient):
    """The same EXCLUDED request the asset deal accepts, the equity deal refuses.

    PRD: "When `structure` is `EQUITY`, a disposition of `EXCLUDED` is not
    permitted for `MALPRACTICE_TAIL`, `STARK_SELF_DISCLOSURE`, or
    `PAYER_REFUND_EXPOSURE`, because an equity buyer takes the entity together
    with its whole history and cannot leave those behind."

    Design: Corner/errors/equity_deal_excluding_a_malpractice_tail_liability_rejected
    """
    _equity, _asset, equity_tail, asset_tail = (
        _one_tail_on_an_equity_deal_and_one_on_an_asset_deal(api)
    )
    exclusion = f.disposition_payload(
        DISPOSITION_EXCLUDED, disposition_note="Seller to retain the tail exposure"
    )

    refused = api.set_liability_disposition(equity_tail["id"], exclusion, DEAL_LEAD)

    validate_error(refused, ApiErrorId.LIABILITY_DISPOSITION_NOT_PERMITTED, 422)
    unchanged = validate_success(api.get_liability_item(equity_tail["id"], DEAL_LEAD))
    a.assert_status(unchanged, DISPOSITION_UNASSIGNED, "disposition")
    a.assert_version_unchanged(equity_tail, unchanged)

    on_the_asset_deal = validate_success(
        api.set_liability_disposition(asset_tail["id"], exclusion, DEAL_LEAD)
    )
    a.assert_status(on_the_asset_deal, DISPOSITION_EXCLUDED, "disposition")

    indemnified = validate_success(
        api.set_liability_disposition(
            equity_tail["id"],
            f.disposition_payload(
                DISPOSITION_INDEMNIFIED, disposition_note="Capped seller indemnity in its place"
            ),
            DEAL_LEAD,
        )
    )
    a.assert_status(indemnified, DISPOSITION_INDEMNIFIED, "disposition")
    a.assert_money_equals(indemnified["indemnity_cap_cents"], TAIL_CENTS, "indemnity_cap_cents")


def test_an_asset_buyer_may_not_assume_a_stark_self_disclosure(api: ApiClient):
    """The asset half of the same rule closes off the opposite disposition.

    PRD: "When `structure` is `ASSET`, a disposition of `ASSUMED` is not permitted
    for `STARK_SELF_DISCLOSURE`."

    Design: Corner/errors/equity_deal_excluding_a_malpractice_tail_liability_rejected
    """
    _equity, asset, _equity_tail, _asset_tail = (
        _one_tail_on_an_equity_deal_and_one_on_an_asset_deal(api)
    )
    stark = create_liability(
        api,
        asset["id"],
        category=LIABILITY_STARK_SELF_DISCLOSURE,
        description="Self-disclosed space-lease overpayment under the SRDP",
        estimated_amount_cents=STARK_CENTS,
    )

    refused = api.set_liability_disposition(
        stark["id"],
        f.disposition_payload(DISPOSITION_ASSUMED, disposition_note="Buyer to carry the exposure"),
        DEAL_LEAD,
    )

    validate_error(refused, ApiErrorId.LIABILITY_DISPOSITION_NOT_PERMITTED, 422)
    a.assert_status(
        validate_success(api.get_liability_item(stark["id"], DEAL_LEAD)),
        DISPOSITION_UNASSIGNED,
        "disposition",
    )

    excluded = set_disposition(
        api, stark["id"], DISPOSITION_EXCLUDED, disposition_note="Seller retains the SRDP matter"
    )
    a.assert_status(excluded, DISPOSITION_EXCLUDED, "disposition")


# ---------------------------------------------------------------------------
# The board-review gates: the tail term, and the reasonableness conclusion
# ---------------------------------------------------------------------------

SHORT_TAIL_MONTHS = 36
STANDARD_TAIL_MONTHS = 60
SIXTY_MONTH_PRACTICE_NAME = "Harbour Point Cardiology"
OCCURRENCE_PRACTICE_NAME = "Elmgrove Family Practice"


def _cardiology_diligence_deal(api: ApiClient, npi: str = NPI_B, **acq_overrides):
    acquisition = create_cardiology_acquisition(api, **acq_overrides)
    create_physician(
        api,
        acquisition["id"],
        npi=npi,
        full_name=PHYSICIAN_NAME_B,
        specialty=SPECIALTY_CARDIOLOGY,
    )
    return advance_deal_status(api, acquisition["id"], DEAL_STATUS_DILIGENCE)


def _valued_claims_made_deal(api: ApiClient, tail_months: int):
    reset_clock(api)
    acquisition = _cardiology_diligence_deal(
        api,
        malpractice_policy_form=POLICY_FORM_CLAIMS_MADE,
        tail_coverage_months=tail_months,
    )
    fmv = accepted_market_fmv(api, acquisition["id"])
    accepted_cr_opinion(api, acquisition["id"])
    return read_acquisition(api, acquisition["id"]), fmv


def test_a_thirty_six_month_tail_blocks_the_board_review(api: ApiClient):
    """Every earlier gate is satisfied, so the tail term is the only thing left to fail.

    PRD: "Fourth, when `tail_coverage_required` is true, `tail_coverage_months`
    must be at least 60 — the standard five-year tail term — or the transition
    fails with `ERR_TAIL_COVERAGE_INSUFFICIENT`."

    Design: Corner/errors/thirty_six_month_tail_blocks_the_board_review
    """
    acquisition, fmv = _valued_claims_made_deal(api, SHORT_TAIL_MONTHS)
    assert acquisition["tail_coverage_required"] is True
    assert acquisition["tail_coverage_months"] == SHORT_TAIL_MONTHS

    refused = api.set_acquisition_status(
        acquisition["id"], f.acquisition_status_payload(DEAL_STATUS_BOARD_REVIEW), DEAL_LEAD
    )

    validate_error(refused, ApiErrorId.TAIL_COVERAGE_INSUFFICIENT, 422)
    unmoved = read_acquisition(api, acquisition["id"])
    a.assert_status(unmoved, DEAL_STATUS_DILIGENCE, "deal_status")
    a.assert_consideration_all_null(unmoved)
    assert unmoved["tail_premium_cents"] is None
    still_unpinned = validate_success(api.get_valuation_opinion(fmv["id"], COMPLIANCE_OFFICER))
    a.assert_status(still_unpinned, OPINION_STATUS_ACCEPTED)
    assert still_unpinned["is_pinned"] is False


def test_a_sixty_month_tail_clears_an_inclusive_floor_and_occurrence_skips_it(api: ApiClient):
    """Sixty months is enough, and a deal with nothing uncovered is never asked.

    PRD: "A deal on an occurrence policy skips that fourth check entirely."

    Design: Corner/errors/thirty_six_month_tail_blocks_the_board_review
    """
    reset_clock(api)
    at_the_floor = _cardiology_diligence_deal(
        api,
        target_practice_name=SIXTY_MONTH_PRACTICE_NAME,
        malpractice_policy_form=POLICY_FORM_CLAIMS_MADE,
        tail_coverage_months=STANDARD_TAIL_MONTHS,
    )
    accepted_market_fmv(api, at_the_floor["id"])
    accepted_cr_opinion(api, at_the_floor["id"])

    priced = advance_deal_status(api, at_the_floor["id"], DEAL_STATUS_BOARD_REVIEW)

    a.assert_status(priced, DEAL_STATUS_BOARD_REVIEW, "deal_status")
    a.assert_money_equals(
        priced["purchase_price_cents"], STANDARD_FMV_CONCLUDED_CENTS, "purchase_price_cents"
    )
    a.assert_money_cents(priced["tail_premium_cents"], "tail_premium_cents")

    occurrence = create_acquisition(api, target_practice_name=OCCURRENCE_PRACTICE_NAME)
    create_physician(
        api,
        occurrence["id"],
        npi=NPI_C,
        full_name=PHYSICIAN_NAME_C,
        state_license_expires_on=LICENSE_EXPIRY_C,
    )
    advance_deal_status(api, occurrence["id"], DEAL_STATUS_DILIGENCE)
    accepted_market_fmv(api, occurrence["id"])
    accepted_cr_opinion(api, occurrence["id"])

    exempt = advance_deal_status(api, occurrence["id"], DEAL_STATUS_BOARD_REVIEW)

    assert exempt["tail_coverage_required"] is False
    assert exempt["tail_coverage_months"] == 0
    a.assert_status(exempt, DEAL_STATUS_BOARD_REVIEW, "deal_status")
    a.assert_money_equals(exempt["tail_premium_cents"], 0, "tail_premium_cents")


def _deal_with_a_not_reasonable_conclusion(api: ApiClient):
    reset_clock(api)
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    fmv = accepted_income_fmv(api, acquisition_id)
    unhelpful = accepted_cr_opinion(
        api,
        acquisition_id,
        cr_conclusion=CR_CONCLUSION_NOT_REASONABLE,
    )
    return read_acquisition(api, acquisition_id), fmv, unhelpful


def test_an_accepted_but_unreasonable_conclusion_blocks_the_board_review(api: ApiClient):
    """The gate reads the conclusion, not the review status, so acceptance does not help.

    PRD: "Second, at least one opinion with `opinion_type`
    `COMMERCIAL_REASONABLENESS` must be in `ACCEPTED` and carry `cr_conclusion` of
    `REASONABLE`; a missing opinion and a `NOT_REASONABLE` conclusion are equally
    fatal, and both report `ERR_COMMERCIAL_REASONABLENESS_NOT_ESTABLISHED`."

    Design: Corner/errors/not_reasonable_conclusion_blocks_the_board_review
    """
    acquisition, fmv, unhelpful = _deal_with_a_not_reasonable_conclusion(api)

    refused = api.set_acquisition_status(
        acquisition["id"], f.acquisition_status_payload(DEAL_STATUS_BOARD_REVIEW), DEAL_LEAD
    )

    validate_error(refused, ApiErrorId.COMMERCIAL_REASONABLENESS_NOT_ESTABLISHED, 422)
    unmoved = read_acquisition(api, acquisition["id"])
    a.assert_status(unmoved, DEAL_STATUS_DILIGENCE, "deal_status")
    a.assert_consideration_all_null(unmoved)
    assert validate_success(api.get_valuation_opinion(fmv["id"], COMPLIANCE_OFFICER))[
        "is_pinned"
    ] is False
    reviewed = validate_success(api.get_valuation_opinion(unhelpful["id"], COMPLIANCE_OFFICER))
    a.assert_status(reviewed, OPINION_STATUS_ACCEPTED)
    assert reviewed["cr_conclusion"] == CR_CONCLUSION_NOT_REASONABLE


def test_the_unreasonable_conclusion_must_be_superseded_before_a_replacement_lands(
    api: ApiClient,
):
    """One accepted opinion per type, so the replacement waits for the first to retire.

    PRD: "Accepting it, `SUBMITTED → ACCEPTED`, has three preconditions: the
    caller's `X-User-ID` must differ from `prepared_by_user_id`, or the request
    fails with `ERR_SEGREGATION_OF_DUTIES`; the opinion's `expires_on` must not be
    before the current logical date, or it fails with
    `ERR_VALUATION_OPINION_EXPIRED`; and no other opinion on the same acquisition
    with the same `opinion_type` may already be in `ACCEPTED`."

    Design: Corner/errors/not_reasonable_conclusion_blocks_the_board_review
    """
    acquisition, fmv, unhelpful = _deal_with_a_not_reasonable_conclusion(api)
    replacement = file_cr_opinion(api, acquisition["id"])
    submit_opinion(api, replacement["id"])

    blocked = api.set_valuation_opinion_status(
        replacement["id"],
        f.opinion_status_payload(OPINION_STATUS_ACCEPTED, review_note="Reasonable on review"),
        COMPLIANCE_OFFICER,
    )

    validate_error(blocked, ApiErrorId.INVALID_STATE_TRANSITION, 409)

    retired = validate_success(
        api.set_valuation_opinion_status(
            unhelpful["id"],
            f.opinion_status_payload(OPINION_STATUS_SUPERSEDED),
            COMPLIANCE_OFFICER,
        )
    )
    a.assert_status(retired, OPINION_STATUS_SUPERSEDED)
    accepted = accept_opinion(api, replacement["id"], COMPLIANCE_OFFICER, "Reasonable on review")
    a.assert_status(accepted, OPINION_STATUS_ACCEPTED)

    priced = advance_deal_status(api, acquisition["id"], DEAL_STATUS_BOARD_REVIEW)

    a.assert_status(priced, DEAL_STATUS_BOARD_REVIEW, "deal_status")
    a.assert_money_equals(
        priced["purchase_price_cents"], fmv["concluded_value_cents"], "purchase_price_cents"
    )
    assert validate_success(api.get_valuation_opinion(fmv["id"], COMPLIANCE_OFFICER))[
        "is_pinned"
    ] is True


# ---------------------------------------------------------------------------
# Plan approval reads the pin, not merely the acceptance
# ---------------------------------------------------------------------------


def _diligence_deal_with_a_submitted_plan(api: ApiClient):
    reset_clock(api)
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    fmv = accepted_market_fmv(api, acquisition_id, officer_headers=COMPLIANCE_OFFICER)
    plan = create_plan(api, acquisition_id, deal["physician"]["id"])
    submit_plan(api, plan["id"])
    return deal["acquisition"], deal["physician"], fmv, plan


def test_an_accepted_but_unpinned_opinion_cannot_carry_a_plan_approval(api: ApiClient):
    """The compensation figures are inside the safe harbour; only the pin is missing.

    PRD: "A valuation opinion with `opinion_type` `FMV` on the same acquisition
    must be in `ACCEPTED` with `is_pinned` true, or the request fails with
    `ERR_FMV_OPINION_NOT_ACCEPTED` — which in practice means the deal must already
    have reached `BOARD_REVIEW`."

    Design: Corner/errors/unpinned_fmv_opinion_blocks_the_plan_approval
    """
    _acquisition, physician, fmv, plan = _diligence_deal_with_a_submitted_plan(api)

    refused = api.set_compensation_plan_status(
        plan["id"],
        f.plan_status_payload(
            PLAN_STATUS_APPROVED, review_note="Percentile is inside the safe harbour"
        ),
        COMPLIANCE_OFFICER_ALT,
    )

    validate_error(refused, ApiErrorId.FMV_OPINION_NOT_ACCEPTED, 422)
    unapproved = validate_success(api.get_compensation_plan(plan["id"], COMPENSATION_DESIGNER))
    a.assert_status(unapproved, PLAN_STATUS_SUBMITTED)
    assert unapproved["approved_by_user_id"] is None
    assert unapproved["returned_count"] == 0
    a.assert_money_equals(
        unapproved["projected_total_cash_comp_cents"],
        STANDARD_PLAN_TOTAL_CENTS,
        "projected_total_cash_comp_cents",
    )
    a.assert_percentage_equals(
        unapproved["benchmark_percentile"], STANDARD_PLAN_PERCENTILE, "benchmark_percentile"
    )
    assert (
        validate_success(api.get_physician(physician["id"], DEAL_LEAD))["employment_status"]
        == EMPLOYMENT_PROSPECTIVE
    )
    pending = validate_success(api.get_valuation_opinion(fmv["id"], COMPLIANCE_OFFICER))
    a.assert_status(pending, OPINION_STATUS_ACCEPTED)
    assert pending["is_pinned"] is False


def test_the_board_review_pin_lets_the_identical_approval_through(api: ApiClient):
    """Nothing about the plan changes; the board pins the opinion it is measured against.

    PRD: "The accepted `FMV` opinion has `is_pinned` set to true; it is now the
    single opinion the rest of the deal is measured against."

    Design: Corner/errors/unpinned_fmv_opinion_blocks_the_plan_approval
    """
    acquisition, physician, fmv, plan = _diligence_deal_with_a_submitted_plan(api)
    approval = f.plan_status_payload(
        PLAN_STATUS_APPROVED, review_note="Percentile is inside the safe harbour"
    )
    validate_error(
        api.set_compensation_plan_status(plan["id"], approval, COMPLIANCE_OFFICER_ALT),
        ApiErrorId.FMV_OPINION_NOT_ACCEPTED,
        422,
    )

    accepted_cr_opinion(api, acquisition["id"], officer_headers=COMPLIANCE_OFFICER_ALT)
    priced = advance_deal_status(api, acquisition["id"], DEAL_STATUS_BOARD_REVIEW)
    a.assert_status(priced, DEAL_STATUS_BOARD_REVIEW, "deal_status")
    assert validate_success(api.get_valuation_opinion(fmv["id"], COMPLIANCE_OFFICER))[
        "is_pinned"
    ] is True

    approved = validate_success(
        api.set_compensation_plan_status(plan["id"], approval, COMPLIANCE_OFFICER_ALT)
    )

    a.assert_status(approved, PLAN_STATUS_APPROVED)
    assert approved["approved_by_user_id"] == COMPLIANCE_OFFICER_ALT["X-User-ID"]
    assert (
        validate_success(api.get_physician(physician["id"], DEAL_LEAD))["employment_status"]
        == EMPLOYMENT_OFFERED
    )


# ---------------------------------------------------------------------------
# The signing gate: every physician papered, every exposure allocated
# ---------------------------------------------------------------------------

UNPAPERED_TAIL_CENTS = 1_200_000


def _cleared_board_review_deal_with_two_physicians(api: ApiClient):
    reset_clock(api)
    acquisition = create_acquisition(api)
    first = create_physician(api, acquisition["id"])
    second = second_physician(api, acquisition["id"])
    advance_deal_status(api, acquisition["id"], DEAL_STATUS_DILIGENCE)
    accepted_market_fmv(api, acquisition["id"], officer_headers=COMPLIANCE_OFFICER)
    accepted_cr_opinion(api, acquisition["id"], officer_headers=COMPLIANCE_OFFICER_ALT)
    acquisition = advance_deal_status(api, acquisition["id"], DEAL_STATUS_BOARD_REVIEW)
    plan = approved_plan(api, acquisition["id"], first["id"])
    set_clearance(api, acquisition["id"], CLEARANCE_CLEARED)
    return read_acquisition(api, acquisition["id"]), first, second, plan


def test_one_physician_left_unpapered_blocks_the_signing(api: ApiClient):
    """The gate runs over every physician on the deal, not merely over one of them.

    PRD: "Every physician on the acquisition must have at least one compensation
    plan in `APPROVED` or in `EXECUTED`, or the request fails with
    `ERR_COMP_PLAN_MISSING` — no physician may be left without a signed-off
    arrangement at signature."

    Design: Corner/errors/signing_with_one_physician_left_unpapered_rejected
    """
    acquisition, first, second, _plan = _cleared_board_review_deal_with_two_physicians(api)

    refused = api.set_acquisition_status(
        acquisition["id"], f.acquisition_status_payload(DEAL_STATUS_SIGNED), DEAL_LEAD
    )

    validate_error(refused, ApiErrorId.COMP_PLAN_MISSING, 422)
    unmoved = read_acquisition(api, acquisition["id"])
    a.assert_status(unmoved, DEAL_STATUS_BOARD_REVIEW, "deal_status")
    a.assert_money_equals(
        unmoved["purchase_price_cents"], STANDARD_FMV_CONCLUDED_CENTS, "purchase_price_cents"
    )
    a.assert_money_cents(unmoved["net_consideration_cents"], "net_consideration_cents")
    assert (
        validate_success(api.get_physician(first["id"], DEAL_LEAD))["employment_status"]
        == EMPLOYMENT_OFFERED
    )
    assert (
        validate_success(api.get_physician(second["id"], DEAL_LEAD))["employment_status"]
        == EMPLOYMENT_PROSPECTIVE
    )

    approved_plan(api, acquisition["id"], second["id"])
    signed = advance_deal_status(api, acquisition["id"], DEAL_STATUS_SIGNED)
    a.assert_status(signed, DEAL_STATUS_SIGNED, "deal_status")


def test_an_unassigned_exposure_blocks_the_signing_one_rung_further_down(api: ApiClient):
    """With both physicians papered, the next rung of the ladder becomes visible.

    PRD: "No liability item on the acquisition may still be in `UNASSIGNED`, or the
    request fails with `ERR_LIABILITY_UNASSIGNED`; an acquisition with no liability
    items at all satisfies this rule vacuously."

    Design: Corner/errors/signing_with_one_physician_left_unpapered_rejected
    """
    acquisition, _first, second, _plan = _cleared_board_review_deal_with_two_physicians(api)
    approved_plan(api, acquisition["id"], second["id"])
    exposure = create_liability(
        api,
        acquisition["id"],
        category=LIABILITY_MALPRACTICE_TAIL,
        description="Uncovered tail on a departing physician's policy",
        estimated_amount_cents=UNPAPERED_TAIL_CENTS,
    )
    a.assert_status(exposure, DISPOSITION_UNASSIGNED, "disposition")
    assert (
        PRECEDENCE_RANK[ApiErrorId.COMP_PLAN_MISSING]
        < PRECEDENCE_RANK[ApiErrorId.LIABILITY_UNASSIGNED]
    )

    refused = api.set_acquisition_status(
        acquisition["id"], f.acquisition_status_payload(DEAL_STATUS_SIGNED), DEAL_LEAD
    )

    validate_error(refused, ApiErrorId.LIABILITY_UNASSIGNED, 422)
    a.assert_status(
        read_acquisition(api, acquisition["id"]), DEAL_STATUS_BOARD_REVIEW, "deal_status"
    )

    assumed = set_disposition(
        api, exposure["id"], DISPOSITION_ASSUMED, disposition_note="Buyer carries the tail"
    )
    a.assert_status(assumed, DISPOSITION_ASSUMED, "disposition")
    signed = advance_deal_status(api, acquisition["id"], DEAL_STATUS_SIGNED)
    a.assert_status(signed, DEAL_STATUS_SIGNED, "deal_status")


# ---------------------------------------------------------------------------
# The closing ladder: five gates, answered in precedence order
# ---------------------------------------------------------------------------

TRAINING_DUE_ON = "2026-10-25"
MIGRATION_RECORD_COUNT = 20_000


def _signed_deal_with_an_approved_plan_a_task_and_a_batch(api: ApiClient):
    reset_clock(api)
    acquisition = create_acquisition(api)
    physician = create_physician(api, acquisition["id"])
    advance_deal_status(api, acquisition["id"], DEAL_STATUS_DILIGENCE)
    accepted_market_fmv(api, acquisition["id"], officer_headers=COMPLIANCE_OFFICER)
    accepted_cr_opinion(api, acquisition["id"], officer_headers=COMPLIANCE_OFFICER_ALT)
    advance_deal_status(api, acquisition["id"], DEAL_STATUS_BOARD_REVIEW)
    plan = approved_plan(api, acquisition["id"], physician["id"])
    set_clearance(api, acquisition["id"], CLEARANCE_CLEARED)
    acquisition = advance_deal_status(api, acquisition["id"], DEAL_STATUS_SIGNED)
    task = create_task(
        api,
        acquisition["id"],
        task_code=TASK_COMPLIANCE_TRAINING,
        is_blocking=True,
        due_on=TRAINING_DUE_ON,
    )
    batch = create_batch(
        api,
        acquisition["id"],
        batch_label=BATCH_LABEL,
        chart_type=CHART_TYPE_STRUCTURED,
        record_count=MIGRATION_RECORD_COUNT,
    )
    return acquisition, physician, plan, task, batch


def test_an_approved_plan_is_not_enough_to_close(api: ApiClient):
    """Three gates are unmet at once and the highest-priority one answers.

    PRD: "Every physician must have at least one plan actually in `EXECUTED` —
    approval is not enough at this gate — or the request fails with
    `ERR_NO_EXECUTED_COMP_PLAN`."

    Design: Corner/errors/closing_walks_down_the_close_gate_ladder
    """
    acquisition, _physician, plan, task, batch = (
        _signed_deal_with_an_approved_plan_a_task_and_a_batch(api)
    )
    a.assert_status(plan, PLAN_STATUS_APPROVED)
    a.assert_status(task, TASK_STATUS_OPEN)
    a.assert_status(batch, BATCH_STATUS_STAGED)
    assert (
        PRECEDENCE_RANK[ApiErrorId.NO_EXECUTED_COMP_PLAN]
        < PRECEDENCE_RANK[ApiErrorId.READINESS_NOT_READY]
        < PRECEDENCE_RANK[ApiErrorId.MIGRATION_INCOMPLETE]
    )

    refused = api.set_acquisition_status(
        acquisition["id"], f.acquisition_status_payload(DEAL_STATUS_CLOSED), DEAL_LEAD
    )

    validate_error(refused, ApiErrorId.NO_EXECUTED_COMP_PLAN, 422)
    unmoved = read_acquisition(api, acquisition["id"])
    a.assert_status(unmoved, DEAL_STATUS_SIGNED, "deal_status")
    assert unmoved["closed_at"] is None


def test_each_repair_reveals_exactly_the_next_unmet_close_gate(api: ApiClient):
    """The ladder is walked one rung at a time until the deal finally closes.

    PRD: "On success the server stamps `closed_at` with the current logical
    instant and sets every valuation opinion on the deal that is still in `DRAFT`
    or `SUBMITTED` to `SUPERSEDED`; the pinned `ACCEPTED` opinion is left exactly
    as it is."

    Design: Corner/errors/closing_walks_down_the_close_gate_ladder
    """
    acquisition, physician, plan, task, batch = (
        _signed_deal_with_an_approved_plan_a_task_and_a_batch(api)
    )
    closing = f.acquisition_status_payload(DEAL_STATUS_CLOSED)

    executed = execute_plan(api, plan["id"], physician["id"])
    a.assert_status(executed, PLAN_STATUS_EXECUTED)
    validate_error(
        api.set_acquisition_status(acquisition["id"], closing, DEAL_LEAD),
        ApiErrorId.READINESS_NOT_READY,
        422,
    )

    set_task_status(api, task["id"], TASK_STATUS_IN_PROGRESS)
    completed = set_task_status(api, task["id"], TASK_STATUS_COMPLETE)
    a.assert_status(completed, TASK_STATUS_COMPLETE)
    a.assert_status(read_acquisition(api, acquisition["id"]), POSTURE_READY, "readiness_posture")
    validate_error(
        api.set_acquisition_status(acquisition["id"], closing, DEAL_LEAD),
        ApiErrorId.MIGRATION_INCOMPLETE,
        422,
    )

    progress_batch(api, batch["id"], BATCH_ACTION_EXTRACT)
    progress_batch(api, batch["id"], BATCH_ACTION_LOAD)
    reconciled = reconcile_batch(api, batch["id"], MIGRATION_RECORD_COUNT, 0)
    a.assert_status(reconciled, BATCH_STATUS_RECONCILED)

    closed = validate_success(api.set_acquisition_status(acquisition["id"], closing, DEAL_LEAD))

    a.assert_status(closed, DEAL_STATUS_CLOSED, "deal_status")
    a.assert_instant_equals(closed["closed_at"], DEFAULT_CLOCK_INSTANT, "closed_at")


# ---------------------------------------------------------------------------
# Post-close tracking: the period rule is checked before the close gate
# ---------------------------------------------------------------------------

AUGUST_START_ON = "2026-08-01"
AUGUST_END_ON = "2026-08-31"
SECOND_DAY_OF_AUGUST = "2026-08-02"
SEPTEMBER_END_ON = "2026-09-30"
JULY_START_ON = "2026-07-01"
JULY_END_ON = "2026-07-31"


def _signed_deal_with_an_executed_plan(api: ApiClient):
    reset_clock(api)
    acquisition = create_acquisition(api)
    physician = create_physician(api, acquisition["id"])
    advance_deal_status(api, acquisition["id"], DEAL_STATUS_DILIGENCE)
    accepted_market_fmv(api, acquisition["id"], officer_headers=COMPLIANCE_OFFICER)
    accepted_cr_opinion(api, acquisition["id"], officer_headers=COMPLIANCE_OFFICER_ALT)
    advance_deal_status(api, acquisition["id"], DEAL_STATUS_BOARD_REVIEW)
    plan = executed_plan(api, acquisition["id"], physician["id"])
    set_clearance(api, acquisition["id"], CLEARANCE_CLEARED)
    acquisition = advance_deal_status(api, acquisition["id"], DEAL_STATUS_SIGNED)
    return acquisition, physician, plan


def test_a_report_on_a_merely_signed_deal_is_refused(api: ApiClient):
    """Everything the append needs is in place except the close itself.

    PRD: "And the acquisition's `deal_status` must be `CLOSED`, or the request
    fails with `ERR_ACQUISITION_NOT_CLOSED`."

    Design: Corner/errors/performance_report_filed_before_the_close_rejected
    """
    acquisition, physician, plan = _signed_deal_with_an_executed_plan(api)
    assert acquisition["closed_at"] is None

    refused = api.create_performance_report(
        f.performance_report_payload(acquisition["id"], physician["id"], plan["id"]),
        INTEGRATION_MANAGER,
    )

    validate_error(refused, ApiErrorId.ACQUISITION_NOT_CLOSED, 422)
    a.assert_total_count(
        api.list_performance_reports({"acquisition_id": acquisition["id"]}, INTEGRATION_MANAGER), 0
    )
    a.assert_status(
        validate_success(api.get_compensation_plan(plan["id"], COMPENSATION_DESIGNER)),
        PLAN_STATUS_EXECUTED,
    )


def test_a_period_that_is_not_one_whole_month_is_reported_before_the_close_gate(api: ApiClient):
    """Two defects in one body again, and the earlier rule in §2.12 answers.

    PRD: "The period must be a single whole calendar month — `period_start_on` the
    first day of a month, `period_end_on` the last day of that same month — and
    `period_start_on` must not precede the calendar date of the acquisition's
    `closed_at`; any of these failing is `ERR_INVALID_REPORT_PERIOD`."

    Design: Corner/errors/performance_report_filed_before_the_close_rejected
    """
    acquisition, physician, plan = _signed_deal_with_an_executed_plan(api)
    assert (
        PRECEDENCE_RANK[ApiErrorId.INVALID_REPORT_PERIOD]
        < PRECEDENCE_RANK[ApiErrorId.ACQUISITION_NOT_CLOSED]
    )

    late_start = api.create_performance_report(
        f.performance_report_payload(
            acquisition["id"],
            physician["id"],
            plan["id"],
            period_start_on=SECOND_DAY_OF_AUGUST,
            period_end_on=AUGUST_END_ON,
        ),
        INTEGRATION_MANAGER,
    )
    validate_error(late_start, ApiErrorId.INVALID_REPORT_PERIOD, 422)

    two_months = api.create_performance_report(
        f.performance_report_payload(
            acquisition["id"],
            physician["id"],
            plan["id"],
            period_start_on=AUGUST_START_ON,
            period_end_on=SEPTEMBER_END_ON,
        ),
        INTEGRATION_MANAGER,
    )
    validate_error(two_months, ApiErrorId.INVALID_REPORT_PERIOD, 422)
    a.assert_total_count(
        api.list_performance_reports({"acquisition_id": acquisition["id"]}, INTEGRATION_MANAGER), 0
    )


def test_after_the_close_the_period_may_not_precede_the_closing_date(api: ApiClient):
    """The close both opens the endpoint and fixes the earliest reportable month.

    PRD: "Post-close tracking exists only after the deal has actually closed. An
    `IntegrationManager` appends one month of actuals at a time, naming the
    `acquisition_id`, the `physician_id` whose period is being reported, the
    `applied_comp_plan_id` of the executed plan the period is measured against,
    the `period_start_on` and `period_end_on` bounding the period, the
    `actual_wrvu` generated in the period, and the `actual_collections_cents`
    posted in it."

    Design: Corner/errors/performance_report_filed_before_the_close_rejected
    """
    acquisition, physician, plan = _signed_deal_with_an_executed_plan(api)
    task = create_task(
        api,
        acquisition["id"],
        task_code=TASK_COMPLIANCE_TRAINING,
        is_blocking=True,
        due_on=TRAINING_DUE_ON,
    )
    set_task_status(api, task["id"], TASK_STATUS_IN_PROGRESS)
    set_task_status(api, task["id"], TASK_STATUS_COMPLETE)
    closed = advance_deal_status(api, acquisition["id"], DEAL_STATUS_CLOSED)
    a.assert_instant_equals(closed["closed_at"], DEFAULT_CLOCK_INSTANT, "closed_at")

    backdated = api.create_performance_report(
        f.performance_report_payload(
            acquisition["id"],
            physician["id"],
            plan["id"],
            period_start_on=JULY_START_ON,
            period_end_on=JULY_END_ON,
        ),
        INTEGRATION_MANAGER,
    )

    validate_error(backdated, ApiErrorId.INVALID_REPORT_PERIOD, 422)

    filed = validate_success(
        api.create_performance_report(
            f.performance_report_payload(acquisition["id"], physician["id"], plan["id"]),
            INTEGRATION_MANAGER,
        ),
        201,
    )

    assert filed["period_start_on"] == AUGUST_START_ON
    assert filed["period_end_on"] == AUGUST_END_ON
    folded = validate_success(api.get_compensation_plan(plan["id"], COMPENSATION_DESIGNER))
    assert folded["months_elapsed"] == 1
    a.assert_money_equals(
        filed["true_up_applied_cents"], folded["comp_true_up_cents"], "true_up_applied_cents"
    )
    a.assert_percentage_equals(
        filed["benchmark_percentile_after"],
        folded["benchmark_percentile"],
        "benchmark_percentile_after",
    )


# ---------------------------------------------------------------------------
# The committee calendar decides viability, not the raw lead time
# ---------------------------------------------------------------------------

LATE_FILING_ON = "2026-08-04"
LATE_CYCLE_KEY = "2026-08-15"
LATE_PROJECTED_ON = "2026-11-15"
VIABLE_FILING_ON = "2026-08-03"
VIABLE_PROJECTED_ON = "2026-11-01"
COMMERCIAL_LEAD_DAYS = 90
MEDICARE_FILING_ON = "2026-09-02"
MEDICARE_LEAD_DAYS = 60
MEDICARE_PROJECTED_ON = "2026-11-01"
MEDICAID_LEAD_DAYS = 120
MEDICAID_PROJECTED_ON = "2027-01-01"
MEDICAID_PAYER_NAME = "Sunrise Medicaid Plan"


def _board_review_deal_with_a_noticed_commercial_contract(api: ApiClient):
    reset_clock(api)
    acquisition = create_acquisition(api)
    first = create_physician(api, acquisition["id"])
    second = second_physician(api, acquisition["id"])
    advance_deal_status(api, acquisition["id"], DEAL_STATUS_DILIGENCE)
    accepted_market_fmv(api, acquisition["id"], officer_headers=COMPLIANCE_OFFICER)
    accepted_cr_opinion(api, acquisition["id"], officer_headers=COMPLIANCE_OFFICER_ALT)
    acquisition = advance_deal_status(api, acquisition["id"], DEAL_STATUS_BOARD_REVIEW)
    contract = create_payer_contract(api, acquisition["id"])
    contract = act_on_novation(
        api, contract["id"], NOVATION_ACTION_SEND_NOTICE, note="Change-of-ownership notice issued"
    )
    a.assert_status(contract, NOVATION_NOTICE_SENT, "novation_status")
    return acquisition, first, second, contract


def test_a_commercial_package_filed_one_day_late_misses_its_lead_time(api: ApiClient):
    """One extra day of delay costs fourteen days of projected effective date.

    PRD: "The package's `projected_effective_on` must not fall after
    `target_close_on` extended by the payer's retro-billing window, or the filing
    fails with `ERR_CREDENTIALING_LEAD_TIME_MISSED`; landing exactly on that limit
    is viable and one day past it is not, which means an identical filing date can
    be perfectly viable for a `MEDICARE` contract and fatal for a `COMMERCIAL`
    one."

    Design: Corner/errors/commercial_package_filed_one_day_late_returns_lead_time_missed
    """
    acquisition, first, _second, contract = (
        _board_review_deal_with_a_noticed_commercial_contract(api)
    )
    late = create_package(
        api, acquisition["id"], first["id"], contract["id"], submitted_on=LATE_FILING_ON
    )
    assert late["committee_cycle_key"] == LATE_CYCLE_KEY
    assert late["projected_effective_on"] == LATE_PROJECTED_ON
    assert late["lead_days"] == COMMERCIAL_LEAD_DAYS
    assert late["retro_billing_allowed"] is False
    assert acquisition["target_close_on"] == VIABLE_PROJECTED_ON

    refused = api.set_credentialing_package_status(
        late["id"], f.package_status_payload(PACKAGE_STATUS_SUBMITTED), INTEGRATION_MANAGER
    )

    validate_error(refused, ApiErrorId.CREDENTIALING_LEAD_TIME_MISSED, 422)
    unfiled = validate_success(api.get_credentialing_package(late["id"], INTEGRATION_MANAGER))
    a.assert_status(unfiled, PACKAGE_STATUS_DRAFT)
    assert unfiled["projected_effective_on"] == LATE_PROJECTED_ON
    a.assert_version_unchanged(late, unfiled)


def test_a_projected_date_landing_exactly_on_the_limit_is_viable(api: ApiClient):
    """The day before is a different committee meeting and a different answer.

    PRD: "`projected_effective_on` is then computed by adding `lead_days` days to
    `submitted_on` and pushing the result forward to the earliest committee meeting
    date on or after that intermediate date — again the first or fifteenth of a
    month, and again lower-inclusive, so a lead time landing exactly on a meeting
    date uses that meeting."

    Design: Corner/errors/commercial_package_filed_one_day_late_returns_lead_time_missed
    """
    acquisition, _first, second, contract = (
        _board_review_deal_with_a_noticed_commercial_contract(api)
    )
    on_time = create_package(
        api, acquisition["id"], second["id"], contract["id"], submitted_on=VIABLE_FILING_ON
    )
    assert on_time["projected_effective_on"] == VIABLE_PROJECTED_ON

    filed = set_package_status(api, on_time["id"], PACKAGE_STATUS_SUBMITTED)

    a.assert_status(filed, PACKAGE_STATUS_SUBMITTED)
    assert filed["projected_effective_on"] == VIABLE_PROJECTED_ON


def test_medicare_moves_the_limit_where_medicaid_projects_past_it(api: ApiClient):
    """The same filing date is viable or fatal according to the payer's lead time.

    PRD: "`lead_days` is the payer's processing lead time, looked up from the linked
    contract's `payer_type`: 90 days for `COMMERCIAL`, 75 for `MANAGED_MEDICARE`,
    60 for `MEDICARE`, and 120 for `MEDICAID`."

    Design: Corner/errors/commercial_package_filed_one_day_late_returns_lead_time_missed
    """
    acquisition, first, second, _contract = (
        _board_review_deal_with_a_noticed_commercial_contract(api)
    )
    medicare = create_payer_contract(
        api,
        acquisition["id"],
        payer_name=MEDICARE_PAYER_NAME,
        payer_type=PAYER_TYPE_MEDICARE,
        notice_days_required=0,
        annual_revenue_share_bps=MEDICARE_REVENUE_SHARE_BPS,
    )
    act_on_novation(api, medicare["id"], NOVATION_ACTION_SEND_NOTICE)
    medicaid = create_payer_contract(
        api,
        acquisition["id"],
        payer_name=MEDICAID_PAYER_NAME,
        payer_type=PAYER_TYPE_MEDICAID,
        notice_days_required=0,
        annual_revenue_share_bps=1500,
    )
    act_on_novation(api, medicaid["id"], NOVATION_ACTION_SEND_NOTICE)

    under_medicare = create_package(
        api, acquisition["id"], first["id"], medicare["id"], submitted_on=MEDICARE_FILING_ON
    )
    assert under_medicare["lead_days"] == MEDICARE_LEAD_DAYS
    assert under_medicare["projected_effective_on"] == MEDICARE_PROJECTED_ON
    assert under_medicare["retro_billing_allowed"] is True
    filed = set_package_status(api, under_medicare["id"], PACKAGE_STATUS_SUBMITTED)
    a.assert_status(filed, PACKAGE_STATUS_SUBMITTED)

    under_medicaid = create_package(
        api, acquisition["id"], second["id"], medicaid["id"], submitted_on=MEDICARE_FILING_ON
    )
    assert under_medicaid["lead_days"] == MEDICAID_LEAD_DAYS
    assert under_medicaid["projected_effective_on"] == MEDICAID_PROJECTED_ON
    assert under_medicaid["retro_billing_allowed"] is False

    refused = api.set_credentialing_package_status(
        under_medicaid["id"],
        f.package_status_payload(PACKAGE_STATUS_SUBMITTED),
        INTEGRATION_MANAGER,
    )

    validate_error(refused, ApiErrorId.CREDENTIALING_LEAD_TIME_MISSED, 422)
    a.assert_status(
        validate_success(api.get_credentialing_package(under_medicaid["id"], INTEGRATION_MANAGER)),
        PACKAGE_STATUS_DRAFT,
    )


# ---------------------------------------------------------------------------
# Two boundary rules on one transition, in precedence order
# ---------------------------------------------------------------------------

NOTICE_CLOCK_DATE = "2026-10-03"
NOTICE_CLOCK_TIME = "09:00:00"
LATE_NOTICE_ON = "2026-10-03"
ADEQUATE_NOTICE_ON = "2026-10-02"
CONVERSION_EFFECTIVE_ON = "2026-11-01"
REQUIRED_NOTICE_COUNT = 1200
SHORT_NOTIFIED_COUNT = 1199
SHORT_LEAD_DAYS = 29
ADEQUATE_LEAD_DAYS = 30
FULL_COVERAGE_BPS = 10000
SHORT_COVERAGE_BPS = 9991
MAIN_SITE_NAME = "Lakeside Main Office"
ANNEX_SITE_NAME = "Lakeside Riverside Annex"
THIRD_SITE_NAME = "Lakeside Northside Clinic"


def _attested_conversion(
    api: ApiClient,
    acquisition_id: str,
    site_name: str,
    notices_issued_on: str,
    notified_patient_count: int,
):
    conversion = create_conversion(
        api,
        acquisition_id,
        site_name=site_name,
        conversion_type=CONVERSION_TYPE_FREESTANDING_CLINIC,
        required_notice_count=REQUIRED_NOTICE_COUNT,
        notified_patient_count=notified_patient_count,
        notices_issued_on=notices_issued_on,
        effective_on=CONVERSION_EFFECTIVE_ON,
    )
    return set_conversion_status(
        api, conversion["id"], CONVERSION_STATUS_ATTESTED, note="Site criteria reviewed"
    )


def _board_review_deal_at_the_notice_window(api: ApiClient):
    reset_clock(api)
    deal = board_review_deal(api)
    park_clock_on_date(api, NOTICE_CLOCK_DATE, NOTICE_CLOCK_TIME)
    return deal["acquisition"]


def test_twenty_nine_days_of_notice_is_not_enough(api: ApiClient):
    """Coverage is perfect and entirely beside the point.

    PRD: "Recording that the notices went out, `ATTESTED → NOTICES_ISSUED`, carries
    three preconditions: `notices_issued_on` must not be null; `notice_lead_days`
    must be at least 30, or the request fails with
    `ERR_PATIENT_NOTICE_LEAD_TIME_SHORT` — exactly thirty days of lead time is
    adequate and twenty-nine is not; and `notice_coverage_bps` must be at least
    10000, or the request fails with `ERR_PATIENT_NOTICE_COVERAGE_INCOMPLETE`."

    Design: Corner/errors/twenty_nine_day_notice_blocks_the_notice_issuance
    """
    acquisition = _board_review_deal_at_the_notice_window(api)
    late = _attested_conversion(
        api, acquisition["id"], MAIN_SITE_NAME, LATE_NOTICE_ON, REQUIRED_NOTICE_COUNT
    )
    assert late["notice_lead_days"] == SHORT_LEAD_DAYS
    a.assert_bps(late["notice_coverage_bps"], "notice_coverage_bps")
    assert late["notice_coverage_bps"] == FULL_COVERAGE_BPS

    refused = api.set_billing_conversion_status(
        late["id"],
        f.conversion_status_payload(CONVERSION_STATUS_NOTICES_ISSUED, note="Mailing completed"),
        INTEGRATION_MANAGER,
    )

    validate_error(refused, ApiErrorId.PATIENT_NOTICE_LEAD_TIME_SHORT, 422)
    unmoved = validate_success(api.get_billing_conversion(late["id"], INTEGRATION_MANAGER))
    a.assert_status(unmoved, CONVERSION_STATUS_ATTESTED)
    assert unmoved["notice_lead_days"] == SHORT_LEAD_DAYS

    withdrawn = set_conversion_status(
        api, late["id"], CONVERSION_STATUS_WITHDRAWN, note="Site pulled from the conversion"
    )
    a.assert_status(withdrawn, CONVERSION_STATUS_WITHDRAWN)


def test_one_unnotified_patient_out_of_twelve_hundred_fails_the_coverage_floor(api: ApiClient):
    """Truncation is what makes 1199 of 1200 fall short, and 1200 clears it.

    PRD: "`notice_coverage_bps` is `notified_patient_count` multiplied by 10000,
    divided by `required_notice_count`, and **truncated** toward zero to whole
    basis points; notifying all but one patient never rounds up to complete
    coverage, so one missed patient out of twelve hundred reports 9991 basis points
    and fails."

    Design: Corner/errors/twenty_nine_day_notice_blocks_the_notice_issuance
    """
    acquisition = _board_review_deal_at_the_notice_window(api)
    partial = _attested_conversion(
        api, acquisition["id"], ANNEX_SITE_NAME, ADEQUATE_NOTICE_ON, SHORT_NOTIFIED_COUNT
    )
    assert partial["notice_lead_days"] == ADEQUATE_LEAD_DAYS
    assert partial["notice_coverage_bps"] == SHORT_COVERAGE_BPS

    refused = api.set_billing_conversion_status(
        partial["id"],
        f.conversion_status_payload(CONVERSION_STATUS_NOTICES_ISSUED, note="Mailing completed"),
        INTEGRATION_MANAGER,
    )

    validate_error(refused, ApiErrorId.PATIENT_NOTICE_COVERAGE_INCOMPLETE, 422)
    a.assert_status(
        validate_success(api.get_billing_conversion(partial["id"], INTEGRATION_MANAGER)),
        CONVERSION_STATUS_ATTESTED,
    )

    complete = _attested_conversion(
        api, acquisition["id"], THIRD_SITE_NAME, ADEQUATE_NOTICE_ON, REQUIRED_NOTICE_COUNT
    )
    assert complete["notice_lead_days"] == ADEQUATE_LEAD_DAYS
    assert complete["notice_coverage_bps"] == FULL_COVERAGE_BPS

    issued = set_conversion_status(
        api, complete["id"], CONVERSION_STATUS_NOTICES_ISSUED, note="Mailing completed"
    )
    a.assert_status(issued, CONVERSION_STATUS_NOTICES_ISSUED)


def test_a_late_and_incomplete_mailing_never_mentions_its_coverage_gap(api: ApiClient):
    """Both rules guard one transition, and the earlier rank speaks for both.

    PRD: "34. **Patient-notice lead time sufficient**, on `POST
    /billing-conversions/{conversionId}/status` with a target status of
    `NOTICES_ISSUED`. Otherwise `ERR_PATIENT_NOTICE_LEAD_TIME_SHORT` (422)."

    Design: Corner/errors/twenty_nine_day_notice_blocks_the_notice_issuance
    """
    acquisition = _board_review_deal_at_the_notice_window(api)
    doubly_defective = _attested_conversion(
        api, acquisition["id"], MAIN_SITE_NAME, LATE_NOTICE_ON, SHORT_NOTIFIED_COUNT
    )
    assert doubly_defective["notice_lead_days"] == SHORT_LEAD_DAYS
    assert doubly_defective["notice_coverage_bps"] == SHORT_COVERAGE_BPS
    assert (
        PRECEDENCE_RANK[ApiErrorId.PATIENT_NOTICE_LEAD_TIME_SHORT]
        < PRECEDENCE_RANK[ApiErrorId.PATIENT_NOTICE_COVERAGE_INCOMPLETE]
    )

    refused = api.set_billing_conversion_status(
        doubly_defective["id"],
        f.conversion_status_payload(CONVERSION_STATUS_NOTICES_ISSUED, note="Mailing completed"),
        INTEGRATION_MANAGER,
    )

    validate_error(refused, ApiErrorId.PATIENT_NOTICE_LEAD_TIME_SHORT, 422)
    a.assert_status(
        validate_success(api.get_billing_conversion(doubly_defective["id"], INTEGRATION_MANAGER)),
        CONVERSION_STATUS_ATTESTED,
    )
