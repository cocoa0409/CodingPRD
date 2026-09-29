"""Cross-cutting layers: optimistic concurrency and the version counter itself.

Each test below translates exactly one designed instance; the `Design:` line at
the end of every docstring names the instance it comes from.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import canonical_instant
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_collection,
    assert_error,
    assert_index,
    assert_instant_equals,
    assert_versioned_resource,
)
from test_helpers.constants import (
    AppliedTo,
    CompliancePosture,
    DeterminationOutcome,
    FulfillmentStatus,
    NqtlItemStatus,
    NqtlType,
    PlanYearStatus,
    StringencyFinding,
    SubClassification,
    SubmissionType,
)

OUTPATIENT_SLICE = {"sub_classification": SubClassification.OFFICE_VISITS}


# ═══ cross_cutting_layers / stale_expected_parent_versions_rejected ═══════════════


def test_both_declared_concurrency_guards_answer_412_and_clear_after_a_re_read(
    api, officer_headers
):
    """Two parents, two stale numbers, two 412s — and the same call succeeds re-read.

    The author holds the item version it saw at inventory time, but a validated
    denial-rate submission for the item's classification has since recomputed the item's
    index and advanced its version, so the analysis create is refused on the item's
    guard.  Re-reading the item yields a strictly larger number and the identical
    payload is accepted.  The officer then holds the plan-year version it saw when the
    year was opened, while the inventory, the submission and the analysis have each
    moved the year's derived fields, so the determination is refused on the plan year's
    guard — a different code for a different parent.  Re-reading the year yields a
    strictly larger number and the determination lands: with a disparity of three to one
    on a limitation imposed on the mental-health side alone, the index is pinned at the
    top of its range and the year is dragged into remediation.  Only one analysis exists
    at the end, because a refused create stores nothing.

    PRD: "An officer holding the older number is therefore deciding from a superseded
    record, and the request is rejected with `ERR_STALE_PLAN_YEAR_VERSION` (HTTP 412) so
    that the officer re-reads before deciding."

    Design: Corner/cross_cutting_layers/stale_expected_parent_versions_rejected
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    plan_year_version_at_creation = scenario.py_version

    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        officer_headers,
        nqtl_type=NqtlType.PRIOR_AUTHORIZATION,
        applied_to=AppliedTo.MENTAL_HEALTH_SUD_ONLY,
        description="Prior authorization imposed on MH/SUD outpatient visits only.",
    )
    item_version_at_creation = item["version"]
    fx.with_denial_rate_evidence(api, scenario, nqtl_item_id=item["id"])

    stale_analysis_payload = f.analysis_payload(
        item["id"],
        item_version_at_creation,
        stringency_written_finding=StringencyFinding.MORE_STRINGENT_MH,
        stringency_operation_finding=StringencyFinding.MORE_STRINGENT_MH,
    )
    assert_error(
        api.create_analysis(stale_analysis_payload, scenario.sponsor_headers),
        ApiErrorId.STALE_NQTL_ITEM_VERSION,
        412,
    )

    item_version_now = fx.item_version(api, item["id"])
    assert item_version_now > item_version_at_creation, (
        f"the validated submission should have advanced the item version past "
        f"{item_version_at_creation}, got {item_version_now}"
    )
    analysis = fx.draft_analysis(
        api,
        item["id"],
        item_version_now,
        stringency_written_finding=StringencyFinding.MORE_STRINGENT_MH,
        stringency_operation_finding=StringencyFinding.MORE_STRINGENT_MH,
    )
    fx.submit_analysis(api, analysis["id"])

    assert_error(
        api.create_determination(
            item["id"],
            f.determination_payload(
                DeterminationOutcome.VIOLATION,
                plan_year_version_at_creation,
                rationale="Determination written from a stale reading of the plan year.",
            ),
            officer_headers,
        ),
        ApiErrorId.STALE_PLAN_YEAR_VERSION,
        412,
    )

    plan_year_version_now = fx.plan_year_version(
        api, scenario.plan_year_id, officer_headers
    )
    assert plan_year_version_now > plan_year_version_at_creation, (
        f"the inventory, submission and analysis should have advanced the plan year "
        f"past {plan_year_version_at_creation}, got {plan_year_version_now}"
    )
    determined = validate_success(
        api.create_determination(
            item["id"],
            f.determination_payload(
                DeterminationOutcome.VIOLATION,
                plan_year_version_now,
                rationale="Determination rewritten after re-reading the plan year.",
            ),
            officer_headers,
        ),
        201,
    )
    assert determined["status"] == NqtlItemStatus.VIOLATION
    assert_index(
        determined["stringency_in_operation_index"],
        10.00,
        "stringency_in_operation_index",
    )
    assert determined["stringency_flag"] is True

    plan_year = fx.read_plan_year(api, scenario.plan_year_id, officer_headers)
    assert plan_year["open_violation_count"] == 1
    assert plan_year["status"] == PlanYearStatus.REMEDIATION
    assert plan_year["compliance_posture"] == CompliancePosture.VIOLATION

    assert_collection(
        api.list_analyses({"nqtl_item_id": item["id"]}, officer_headers), 1, 1, False
    )


# ═══ cross_cutting_layers / version_increments_on_every_write_and_never_on_a_read ══


def test_the_version_counter_moves_on_an_indirect_write_and_never_on_a_read(
    api, officer_headers, regulator_headers
):
    """Reads are free; a recomputation forced by a sibling aggregate is not.

    A freshly inventoried item starts its counter at one.  Two consecutive reads by a
    role that cannot write anything at all leave the counter, the creation stamp and the
    update stamp exactly where they were — reading is not a mutation.  Then a data
    submission is produced against a request that names a different aggregate entirely,
    and because that submission is validated for this item's classification it forces the
    item's in-operation index to be recomputed: the counter advances by exactly one even
    though nobody addressed the item.  The recomputed index is the network-facing
    weighting of a disparity of 1.9235 with no documentation credit behind it, which sits
    well under the flag threshold, and the item is still merely inventoried — a
    recomputation is not a transition.  The submission also fulfils the request it was
    produced against.

    PRD: "A recomputation that rewrites a derived field — a counter, a score, a posture —
    is a mutation for this purpose and therefore both refreshes `updated_at` and
    increments `version`."

    Design: Corner/cross_cutting_layers/version_increments_on_every_write_and_never_on_a_read
    """
    scenario = fx.classified_plan(api, **OUTPATIENT_SLICE)
    item = fx.inventory_item(
        api,
        scenario.plan_year_id,
        scenario.classification_id,
        officer_headers,
        nqtl_type=NqtlType.NETWORK_ADMISSION,
        applied_to=AppliedTo.BOTH,
        description="Provider network admission standards for outpatient office visits.",
    )
    assert_versioned_resource(item)
    version_at_creation = item["version"]
    assert version_at_creation == 1, (
        f"a freshly written row starts at version 1, got {version_at_creation}"
    )

    request = fx.issue_vendor_request(
        api,
        scenario.admin_id,
        scenario.plan_year_id,
        nqtl_item_id=item["id"],
        requested_item_count=1,
        requested_submission_types=[SubmissionType.DENIAL_RATES],
    )

    first_read = fx.read_item(api, item["id"], regulator_headers)
    second_read = fx.read_item(api, item["id"], regulator_headers)
    for read in (first_read, second_read):
        assert_versioned_resource(read)
        assert read["version"] == version_at_creation, (
            f"a read must not advance the version: expected {version_at_creation}, "
            f"got {read['version']}"
        )
        assert_instant_equals(read["created_at"], item["created_at"], "created_at")
        assert_instant_equals(read["updated_at"], item["updated_at"], "updated_at")

    fx.produce_submission(
        api,
        request["id"],
        f.denial_rate_submission_payload(scenario.classification_id),
        scenario.admin_id,
    )

    recomputed = fx.read_item(api, item["id"], regulator_headers)
    assert_versioned_resource(recomputed)
    assert recomputed["version"] == version_at_creation + 1, (
        f"the validated submission is one mutation of the item: expected "
        f"{version_at_creation + 1}, got {recomputed['version']}"
    )
    assert_instant_equals(recomputed["created_at"], item["created_at"], "created_at")
    assert canonical_instant(recomputed["updated_at"]) >= canonical_instant(
        recomputed["created_at"]
    ), "updated_at must never precede created_at"
    assert_index(
        recomputed["stringency_in_operation_index"],
        2.77,
        "stringency_in_operation_index",
    )
    assert recomputed["stringency_flag"] is False
    assert recomputed["status"] == NqtlItemStatus.INVENTORIED

    fulfilled = fx.read_vendor_request(api, request["id"], regulator_headers)
    assert fulfilled["validated_submission_count"] == 1
    assert fulfilled["fulfillment_status"] == FulfillmentStatus.FULFILLED
