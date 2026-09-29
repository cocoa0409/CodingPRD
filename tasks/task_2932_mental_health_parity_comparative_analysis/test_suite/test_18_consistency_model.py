"""The consistency model: every derived field is readable the instant it is written.

Each test below translates exactly one designed instance; the `Design:` line at
the end of every docstring names the instance it comes from.
"""

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_index,
    assert_ratio,
    assert_score,
)
from test_helpers.constants import (
    AppliedTo,
    CompliancePosture,
    CooperationStatus,
    FulfillmentStatus,
    NqtlItemStatus,
    NqtlType,
    PlanYearStatus,
    RejectionReason,
    SubClassification,
    SubmissionStatus,
    SubmissionType,
)

OUTPATIENT_SLICE = {"sub_classification": SubClassification.OFFICE_VISITS}


# ═══ consistency_model / derived_fields_are_visible_in_the_same_response ══════════


def test_every_derived_consequence_of_one_production_is_readable_immediately(
    api, officer_headers, regulator_headers
):
    """Nothing lags: one write, and every derived consequence is already on the record.

    The submission's own creation response carries the validated verdict and the scored
    ratio — there is no second call to make the verdict appear, and no window in which
    the row sits unscored.  Reading the same submission straight back returns byte-for-
    byte the same three published numbers, its flag and its cleared rejection reason.
    The item, which nobody addressed, already publishes the recomputed index: a
    three-to-one disparity on a limitation imposed on the mental-health side alone,
    undiscounted by any documentation, drives the index to the top of its range with the
    flag raised — visible on the very next read, with no intervening write and no retry.
    The administrator's obligation is already discharged in the same instant, its
    production request already fulfilled, and the plan year's posture already recomputed
    to `AT_RISK` on the strength of the still-un-analysed item.

    PRD: "Every submission is validated automatically inside the same request that
    creates it, moving from `RECEIVED` to either `VALIDATED` or `REJECTED` before the
    response is written; there is no separate validation step and no submission stays in
    `RECEIVED`."

    Design: Corner/consistency_model/derived_fields_are_visible_in_the_same_response
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        officer_headers,
        nqtl_type=NqtlType.PRIOR_AUTHORIZATION,
        applied_to=AppliedTo.MENTAL_HEALTH_SUD_ONLY,
        description="Prior authorization imposed on MH/SUD outpatient visits only.",
    )
    request = fx.issue_vendor_request(
        api,
        scenario.admin_id,
        scenario.plan_year_id,
        nqtl_item_id=item["id"],
        requested_item_count=1,
        requested_submission_types=[SubmissionType.DENIAL_RATES],
    )

    created = fx.produce_submission(
        api,
        request["id"],
        f.denial_rate_submission_payload(
            scenario.classification_id,
            mh_denials=300,
            mh_adjudicated_claims=1000,
            ms_denials=100,
            ms_adjudicated_claims=1000,
        ),
        scenario.admin_id,
    )
    assert created["status"] == SubmissionStatus.VALIDATED
    assert_ratio(created["disparity_ratio"], 3.0000, 4, "disparity_ratio")

    read_back = fx.read_submission(api, created["id"], regulator_headers)
    assert read_back["id"] == created["id"]
    assert read_back["status"] == SubmissionStatus.VALIDATED
    assert_ratio(read_back["disparity_ratio"], 3.0000, 4, "disparity_ratio")
    assert_ratio(read_back["mh_denial_rate"], 0.300000, 6, "mh_denial_rate")
    assert_ratio(read_back["ms_denial_rate"], 0.100000, 6, "ms_denial_rate")
    assert read_back["as_applied_flag"] is True
    assert read_back["rejection_reason"] == RejectionReason.NONE

    recomputed = fx.read_item(api, item["id"], regulator_headers)
    assert_index(
        recomputed["stringency_in_operation_index"],
        10.00,
        "stringency_in_operation_index",
    )
    assert recomputed["stringency_flag"] is True
    assert recomputed["status"] == NqtlItemStatus.INVENTORIED

    administrator = fx.read_administrator(api, scenario.admin_id, regulator_headers)
    assert administrator["outstanding_request_count"] == 0
    assert administrator["late_request_count"] == 0
    assert administrator["breach_count"] == 0
    assert_score(administrator["cooperation_score"], 100.00, "cooperation_score")
    assert_score(
        administrator["regulatory_basis_cooperation_score"],
        100.00,
        "regulatory_basis_cooperation_score",
    )
    assert administrator["cooperation_status"] == CooperationStatus.COOPERATIVE

    fulfilled = fx.read_vendor_request(api, request["id"], regulator_headers)
    assert fulfilled["fulfillment_status"] == FulfillmentStatus.FULFILLED
    assert fulfilled["validated_submission_count"] == 1

    plan_year = fx.read_plan_year(api, scenario.plan_year_id, regulator_headers)
    assert_fields(
        plan_year,
        compliance_posture=CompliancePosture.AT_RISK,
        status=PlanYearStatus.OPEN,
        open_violation_count=0,
        failing_parity_test_count=0,
    )
