"""Admissibility rules, their boundaries and their order against each other.

Every case here reaches exactly one rung of the validation ladder on purpose: the
neighbouring rules are all satisfied, so the error identifier that comes back
names the one rule under test and nothing else.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ANALYZED_BEFORE_COLLECTION,
    ERR_COLLECTED_IN_FUTURE,
    ERR_CONTAMINANT_NOT_IN_PANEL,
    ERR_DETECTION_LIMIT_BELOW_CAPABILITY,
    ERR_DETECTION_LIMIT_TOO_HIGH,
    ERR_DUPLICATE_PERIOD_RESULT,
    ERR_ENTRY_POINT_MISMATCH,
    ERR_INSUFFICIENT_MONITORING_HISTORY,
    ERR_LABORATORY_CERTIFICATION_EXPIRED,
    ERR_METHOD_NOT_CERTIFIED,
    ERR_MONITORING_PERIOD_MISMATCH,
    ERR_NO_QUALIFYING_TECHNOLOGY,
    ERR_PAGINATION_OUT_OF_RANGE,
    ERR_RESAMPLE_TARGET_NOT_INVALIDATED,
    ERR_SAMPLE_NOT_RECEIVED,
    ERR_SHIP_BEFORE_COLLECTION,
    ERR_VIOLATION_PENDING_BLOCKS_REDUCTION,
)
from test_helpers.assertions import (
    assert_decimal,
    assert_entry_point_posture,
    assert_equals,
    assert_instant_equals,
    assert_is_null,
    assert_page,
    assert_status,
    assert_total_count,
)
from test_helpers.fixtures import (
    accept_result,
    accepted_quarter,
    build_registry,
    collect_sample,
    complete_pilot,
    issued_violation,
    open_evaluation,
    read_entry_point,
    read_evaluation,
    read_lab_result,
    read_pilot,
    read_sample,
    receive_sample,
    received_sample,
    register_contaminant,
    register_entry_point,
    register_pilot,
    reject_result,
    selected_project,
    set_clock,
    ship_sample,
    start_pilot,
    submit_result,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    FINANCE_OFFICER_HEADERS,
    SAMPLING_TECHNICIAN_HEADERS,
    TREATMENT_ENGINEER_HEADERS,
    UTILITY_ADMIN_HEADERS,
)

_COLLECTED_AT = "2026-05-15T08:00:00.000Z"
_ANALYZED_AT = "2026-05-20T08:00:00.000Z"


def test_a_page_size_one_past_the_maximum_is_refused_rather_than_clamped(api):
    """101 is not quietly turned into 100, and the refusal returns no rows at all.

    One entry point exists, so a successful page would have carried a row; asking
    for a page of 101 instead fails the pagination band and the response body
    carries an error rather than an items array. Asking for the declared maximum of
    100 immediately afterwards succeeds and returns that single row.

    PRD: "A `limit` below 1, a `limit` above 100, or a negative `offset` is refused
    with `ERR_PAGINATION_OUT_OF_RANGE` (HTTP 422); the request is not silently
    clamped."

    Design: Corner/validations/a_page_limit_above_the_declared_maximum_is_rejected
    """
    entry_point = register_entry_point(api)

    response = api.list_entry_points(UTILITY_ADMIN_HEADERS, params={"limit": 101})

    validate_error(response, ERR_PAGINATION_OUT_OF_RANGE, 422)
    assert "items" not in response.json()["data"], (
        "A refused pagination range must not carry an items array"
    )

    rows = assert_page(
        api.list_entry_points(UTILITY_ADMIN_HEADERS, params={"limit": 100}), 1, False
    )
    assert_equals(rows[0], "id", entry_point["id"])


def test_a_result_for_a_compound_outside_the_panel_is_refused(api):
    """PFOS is a real contaminant row, so this is membership and not resolution.

    The sample was collected for a PFOA-only panel and is sitting in RECEIVED at the
    laboratory that will report it, so every neighbouring rule passes; the reported
    compound simply was never on the panel. No result row is created and the panel
    still holds its single entry.

    PRD: "The contaminant must be a member of the sample's `panel_contaminant_ids`;
    a result for a compound the sample was never collected for is refused with
    `ERR_CONTAMINANT_NOT_IN_PANEL`."

    Design: Corner/validations/a_contaminant_outside_the_sample_panel_is_rejected
    """
    registry = build_registry(api)
    unpanelled = register_contaminant(api, code="PFOS")
    sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        collected_at=_COLLECTED_AT,
    )

    validate_error(
        api.create_lab_result(
            f.lab_result_payload(sample["id"], unpanelled["id"], analyzed_at=_ANALYZED_AT),
            registry["lab_headers"],
        ),
        ERR_CONTAMINANT_NOT_IN_PANEL,
        422,
    )

    assert_total_count(
        api.list_lab_results(COMPLIANCE_OFFICER_HEADERS, params={"sample_id": sample["id"]}), 0
    )
    stored = read_sample(api, sample["id"])
    assert_status(stored, "RECEIVED")
    assert len(stored["panel_contaminant_ids"]) == 1, (
        f"Expected a single-contaminant panel, got {stored['panel_contaminant_ids']}"
    )


def test_a_method_the_laboratory_does_not_hold_is_refused(api):
    """METHOD_1633 is a declared method, so the failure is certification and not shape.

    The facility is certified for METHOD_533 only, and its certification rules out
    the submitted method before any temporal rule is consulted — the 120-hour
    elapsed time would have been inside METHOD_1633's own holding window. No result
    is recorded against the laboratory.

    PRD: "The method must appear in the laboratory's `certified_methods`, else
    `ERR_METHOD_NOT_CERTIFIED`."

    Design: Corner/validations/an_uncertified_analytical_method_is_rejected
    """
    registry = build_registry(api)
    sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        collected_at=_COLLECTED_AT,
    )

    validate_error(
        api.create_lab_result(
            f.lab_result_payload(
                sample["id"],
                registry["contaminant_id"],
                method="METHOD_1633",
                analyzed_at=_ANALYZED_AT,
            ),
            registry["lab_headers"],
        ),
        ERR_METHOD_NOT_CERTIFIED,
        422,
    )

    assert_equals(registry["laboratory"], "certified_methods", ["METHOD_533"])
    assert_total_count(
        api.list_lab_results(
            registry["lab_headers"], params={"laboratory_id": registry["laboratory_id"]}
        ),
        0,
    )


def test_a_detection_limit_coarser_than_the_regulatory_mrl_is_refused(api):
    """3.00 clears the laboratory's own floor of 1.00 and still fails the MRL rule.

    Only the upper bound can fire here: the achieved limit is above the
    contaminant's required minimum reporting level, which makes the analysis too
    coarse to demonstrate compliance, while the laboratory's capability floor is
    comfortably satisfied.

    PRD: "it may not exceed the contaminant's `required_mrl_ng_per_l`, or the
    analysis is too coarse to demonstrate compliance and is refused with
    `ERR_DETECTION_LIMIT_TOO_HIGH`"

    Design: Corner/validations/a_detection_limit_above_the_required_mrl_is_rejected
    """
    registry = build_registry(api)
    sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        collected_at=_COLLECTED_AT,
    )

    validate_error(
        api.create_lab_result(
            f.lab_result_payload(
                sample["id"],
                registry["contaminant_id"],
                detection_limit_ng_per_l=3.00,
                analyzed_at=_ANALYZED_AT,
            ),
            registry["lab_headers"],
        ),
        ERR_DETECTION_LIMIT_TOO_HIGH,
        422,
    )

    assert_total_count(
        api.list_lab_results(COMPLIANCE_OFFICER_HEADERS, params={"sample_id": sample["id"]}), 0
    )
    assert_status(read_sample(api, sample["id"]), "RECEIVED")


def test_a_detection_limit_finer_than_the_laboratory_can_reach_is_refused(api):
    """0.50 satisfies the regulatory ceiling and fails the capability floor instead.

    This is the mirror image of the coarse-limit rule: the claimed limit is below
    the laboratory's declared best achievable limit, which is not credible, even
    though a finer limit is exactly what the regulatory MRL of 2.00 wants.

    PRD: "it may not fall below the laboratory's own `lowest_achievable_dl_ng_per_l`,
    because a limit finer than the facility can physically reach is not credible,
    and that is refused with `ERR_DETECTION_LIMIT_BELOW_CAPABILITY`"

    Design: Corner/validations/a_detection_limit_below_the_laboratory_capability_is_rejected
    """
    registry = build_registry(api)
    sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        collected_at=_COLLECTED_AT,
    )

    validate_error(
        api.create_lab_result(
            f.lab_result_payload(
                sample["id"],
                registry["contaminant_id"],
                detection_limit_ng_per_l=0.50,
                analyzed_at=_ANALYZED_AT,
            ),
            registry["lab_headers"],
        ),
        ERR_DETECTION_LIMIT_BELOW_CAPABILITY,
        422,
    )

    assert_total_count(
        api.list_lab_results(COMPLIANCE_OFFICER_HEADERS, params={"sample_id": sample["id"]}), 0
    )


def test_a_detection_limit_sitting_on_both_bounds_at_once_is_accepted(api):
    """Both comparisons are strict, so a limit equal to both ceiling and floor passes.

    The contaminant demands a limit no coarser than 2.00 and the laboratory cannot
    do better than 2.00, so 2.00 is simultaneously the highest and the lowest
    admissible value; the result is created in SUBMITTED at version 1 rather than
    being caught by either bound.

    PRD: "The achieved detection limit is squeezed between two bounds: it may not
    exceed the contaminant's `required_mrl_ng_per_l`, or the analysis is too coarse
    to demonstrate compliance and is refused with `ERR_DETECTION_LIMIT_TOO_HIGH`;
    and it may not fall below the laboratory's own `lowest_achievable_dl_ng_per_l`,
    because a limit finer than the facility can physically reach is not credible,
    and that is refused with `ERR_DETECTION_LIMIT_BELOW_CAPABILITY`."

    Design: Corner/validations/a_lab_result_sitting_on_both_detection_limit_bounds_is_accepted
    """
    registry = build_registry(
        api, laboratory_overrides={"lowest_achievable_dl_ng_per_l": 2.00}
    )
    assert_decimal(
        registry["contaminant"]["required_mrl_ng_per_l"], 2.00, label="required_mrl_ng_per_l"
    )
    sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        collected_at=_COLLECTED_AT,
    )

    result = validate_success(
        api.create_lab_result(
            f.lab_result_payload(
                sample["id"],
                registry["contaminant_id"],
                detection_limit_ng_per_l=2.00,
                analyzed_at=_ANALYZED_AT,
            ),
            registry["lab_headers"],
        ),
        201,
    )

    assert_status(result, "SUBMITTED")
    assert_decimal(result["detection_limit_ng_per_l"], 2.00, label="detection_limit_ng_per_l")
    assert_decimal(result["reported_ng_per_l"], 3.00, label="reported_ng_per_l")
    assert_equals(result, "laboratory_id", registry["laboratory_id"])
    assert_equals(result, "version", 1)
    assert_total_count(
        api.list_lab_results(COMPLIANCE_OFFICER_HEADERS, params={"sample_id": sample["id"]}), 1
    )


def test_the_second_acceptance_in_one_quarter_is_refused_but_the_row_survives(api):
    """Two legal submissions for one quarter collide only at the second acceptance.

    Both samples were collected inside 2026Q2, both were received and both were
    reported, so both results exist in SUBMITTED — the uniqueness rule is a review
    check, not a creation check. Accepting the first is fine; accepting the second is
    refused and leaves it in SUBMITTED, from where it can still be rejected, which
    changes nothing about the accepted count.

    PRD: "no other result may already hold `ACCEPTED` status for the same
    combination of entry point, contaminant and monitoring period, else
    `ERR_DUPLICATE_PERIOD_RESULT`"

    Design: Corner/validations/a_second_accepted_result_for_the_same_period_is_refused
    """
    registry = build_registry(api)
    first_sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        collected_at=_COLLECTED_AT,
        preservative_lot="LOT-D1",
    )
    second_sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        collected_at="2026-05-16T08:00:00.000Z",
        preservative_lot="LOT-D2",
    )
    first = submit_result(
        api,
        registry["laboratory_id"],
        first_sample["id"],
        registry["contaminant_id"],
        analyzed_at=_ANALYZED_AT,
    )
    second = submit_result(
        api,
        registry["laboratory_id"],
        second_sample["id"],
        registry["contaminant_id"],
        analyzed_at="2026-05-21T08:00:00.000Z",
    )
    accept_result(api, first["id"])

    validate_error(
        api.review_lab_result(
            second["id"], f.accept_review_payload(), COMPLIANCE_OFFICER_HEADERS
        ),
        ERR_DUPLICATE_PERIOD_RESULT,
        422,
    )

    assert_status(read_lab_result(api, first["id"]), "ACCEPTED")
    assert_status(read_lab_result(api, second["id"]), "SUBMITTED")
    assert_entry_point_posture(
        read_entry_point(api, registry["entry_point_id"]), accepted_result_count=1
    )

    rejected = reject_result(api, second["id"], reject_reason_code="QC_FAILURE")
    assert_status(rejected, "REJECTED")
    assert_entry_point_posture(
        read_entry_point(api, registry["entry_point_id"]), accepted_result_count=1
    )


def test_a_resample_pointing_at_a_live_collection_is_refused(api):
    """The reference resolves, so the refusal is about the target's status.

    The named sample exists and is sitting in COLLECTED, never having failed
    anything, and a resample only exists to replace a collection that failed — so
    the new collection is refused and no resample row is created against the target.

    PRD: "A resample reference must point at a sample whose status is
    `INVALIDATED`; pointing it at a live sample is refused with
    `ERR_RESAMPLE_TARGET_NOT_INVALIDATED`, since a resample exists only to replace a
    collection that failed."

    Design: Corner/validations/resampling_a_target_that_was_never_invalidated_is_rejected
    """
    contaminant = register_contaminant(api)
    entry_point = register_entry_point(api)
    target = collect_sample(
        api, entry_point["id"], [contaminant["id"]], collected_at=_COLLECTED_AT
    )

    validate_error(
        api.create_sample(
            f.sample_payload(
                entry_point["id"],
                [contaminant["id"]],
                collected_at="2026-05-16T08:00:00.000Z",
                preservative_lot="LOT-A2",
                resample_of_sample_id=target["id"],
            ),
            SAMPLING_TECHNICIAN_HEADERS,
        ),
        ERR_RESAMPLE_TARGET_NOT_INVALIDATED,
        422,
    )

    assert_status(read_sample(api, target["id"]), "COLLECTED")
    assert_total_count(
        api.list_samples(
            COMPLIANCE_OFFICER_HEADERS, params={"resample_of_sample_id": target["id"]}
        ),
        0,
    )


def test_a_collection_dated_after_the_clock_is_refused_until_the_clock_catches_up(api):
    """The period label agrees with the date, so only the clock comparison can fire.

    A collection instant of 1 September sits in the third quarter and the declared
    period says so, but the logical clock still reads 1 August, and a sample cannot
    be drawn in the future. Moving the clock to 2 September makes the identical body
    legal, which proves the refusal was about the clock and nothing else.

    PRD: "The collection instant must be at or before the logical clock; a future
    instant is refused with `ERR_COLLECTED_IN_FUTURE`."

    Design: Corner/validations/a_collection_instant_after_the_logical_clock_is_rejected
    """
    contaminant = register_contaminant(api)
    entry_point = register_entry_point(api)
    payload = f.sample_payload(
        entry_point["id"],
        [contaminant["id"]],
        monitoring_period="2026Q3",
        collected_at="2026-09-01T00:00:00.000Z",
    )

    validate_error(
        api.create_sample(payload, SAMPLING_TECHNICIAN_HEADERS), ERR_COLLECTED_IN_FUTURE, 422
    )

    assert_total_count(
        api.list_samples(COMPLIANCE_OFFICER_HEADERS, params={"entry_point_id": entry_point["id"]}),
        0,
    )

    set_clock(api, "2026-09-02T00:00:00.000Z")
    accepted = validate_success(
        api.create_sample(payload, SAMPLING_TECHNICIAN_HEADERS), 201
    )
    assert_status(accepted, "COLLECTED")
    assert_equals(accepted, "monitoring_period", "2026Q3")


def test_a_period_label_naming_the_wrong_quarter_is_refused(api):
    """2026Q1 is well formed, so the failure is semantic rather than a shape error.

    A collection drawn on 15 May belongs to the second quarter, and the declared
    first-quarter label disagrees with it; the same body with the correct label is
    accepted immediately afterwards.

    PRD: "And the declared monitoring period must be exactly the calendar quarter
    containing the collection instant — the first quarter covering January through
    March, the second April through June, the third July through September and the
    fourth October through December — with any disagreement refused as
    `ERR_MONITORING_PERIOD_MISMATCH`."

    Design: Corner/validations/a_monitoring_period_outside_the_collection_quarter_is_rejected
    """
    contaminant = register_contaminant(api)
    entry_point = register_entry_point(api)

    validate_error(
        api.create_sample(
            f.sample_payload(
                entry_point["id"],
                [contaminant["id"]],
                monitoring_period="2026Q1",
                collected_at=_COLLECTED_AT,
            ),
            SAMPLING_TECHNICIAN_HEADERS,
        ),
        ERR_MONITORING_PERIOD_MISMATCH,
        422,
    )

    assert_total_count(
        api.list_samples(COMPLIANCE_OFFICER_HEADERS, params={"monitoring_period": "2026Q1"}), 0
    )

    accepted = validate_success(
        api.create_sample(
            f.sample_payload(
                entry_point["id"],
                [contaminant["id"]],
                monitoring_period="2026Q2",
                collected_at=_COLLECTED_AT,
            ),
            SAMPLING_TECHNICIAN_HEADERS,
        ),
        201,
    )
    assert_status(accepted, "COLLECTED")
    assert_equals(accepted, "monitoring_period", "2026Q2")


def test_shipping_while_the_clock_reads_earlier_than_collection_is_refused(api):
    """Rewinding the clock behind the collection instant blocks the shipment.

    The sample is legitimately COLLECTED and the laboratory resolves, so the state
    and foreign-key rungs are clear; the only defect is that the clock has been
    moved back to 1 May, behind the 15 May collection. Nothing is stamped on the
    sample by the failed attempt, and restoring the clock to the collection instant
    lets the same shipment through with that instant recorded.

    PRD: "because the logical clock can be moved backwards, a shipment attempted
    while the clock reads earlier than the sample's collection instant is refused
    with `ERR_SHIP_BEFORE_COLLECTION`"

    Design: Corner/validations/shipping_a_sample_before_its_collection_instant_is_rejected
    """
    registry = build_registry(api)
    set_clock(api, _COLLECTED_AT)
    sample = collect_sample(
        api, registry["entry_point_id"], [registry["contaminant_id"]], collected_at=_COLLECTED_AT
    )
    set_clock(api, "2026-05-01T00:00:00.000Z")

    validate_error(
        api.ship_sample(
            sample["id"],
            f.ship_sample_payload(registry["laboratory_id"]),
            SAMPLING_TECHNICIAN_HEADERS,
        ),
        ERR_SHIP_BEFORE_COLLECTION,
        422,
    )

    blocked = read_sample(api, sample["id"])
    assert_status(blocked, "COLLECTED")
    assert_is_null(blocked, "assigned_laboratory_id", "shipped_at")

    set_clock(api, _COLLECTED_AT)
    shipped = validate_success(
        api.ship_sample(
            sample["id"],
            f.ship_sample_payload(registry["laboratory_id"]),
            SAMPLING_TECHNICIAN_HEADERS,
        )
    )
    assert_status(shipped, "IN_TRANSIT")
    assert_instant_equals(shipped["shipped_at"], _COLLECTED_AT, label="shipped_at")


def test_an_analysis_dated_before_the_collection_is_refused(api):
    """A negative elapsed time cannot exceed a holding limit, so only ordering fires.

    The analysis instant is five days before the sample was drawn, which satisfies
    the holding-time rule vacuously and leaves the certification valid, so the
    physically impossible ordering is the only rule left to catch it.

    PRD: "And an analysis instant that precedes the collection instant is
    physically impossible and refused with `ERR_ANALYZED_BEFORE_COLLECTION`."

    Design: Corner/validations/an_analysis_instant_before_collection_is_rejected
    """
    registry = build_registry(api)
    sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        collected_at=_COLLECTED_AT,
    )

    validate_error(
        api.create_lab_result(
            f.lab_result_payload(
                sample["id"],
                registry["contaminant_id"],
                analyzed_at="2026-05-10T08:00:00.000Z",
            ),
            registry["lab_headers"],
        ),
        ERR_ANALYZED_BEFORE_COLLECTION,
        422,
    )

    assert_total_count(
        api.list_lab_results(COMPLIANCE_OFFICER_HEADERS, params={"sample_id": sample["id"]}), 0
    )
    assert_status(read_sample(api, sample["id"]), "RECEIVED")


def test_an_analysis_on_the_expiry_instant_is_already_outside_the_certification(api):
    """The certification lapses at its expiry instant, not after it.

    The facility holds METHOD_1633 until 1 June, and an analysis stamped exactly
    1 June is refused — the comparison is inclusive of the expiry instant. The
    method's 720-hour holding window comfortably covers the 400 hours since
    collection, so nothing else could be firing, and an analysis an hour before
    expiry is accepted.

    PRD: "the laboratory's certification must still have been valid at the moment of
    analysis: an `analyzed_at` at or after the laboratory's `certification_expires_on`
    is refused with `ERR_LABORATORY_CERTIFICATION_EXPIRED`"

    Design: Corner/validations/an_analysis_on_the_certification_expiry_instant_is_rejected
    """
    registry = build_registry(
        api,
        laboratory_overrides={
            "certified_methods": ["METHOD_1633"],
            "certification_expires_on": "2026-06-01T00:00:00.000Z",
        },
    )
    sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        collected_at=_COLLECTED_AT,
    )

    validate_error(
        api.create_lab_result(
            f.lab_result_payload(
                sample["id"],
                registry["contaminant_id"],
                method="METHOD_1633",
                analyzed_at="2026-06-01T00:00:00.000Z",
            ),
            registry["lab_headers"],
        ),
        ERR_LABORATORY_CERTIFICATION_EXPIRED,
        422,
    )

    assert_total_count(
        api.list_lab_results(
            registry["lab_headers"], params={"laboratory_id": registry["laboratory_id"]}
        ),
        0,
    )

    accepted = validate_success(
        api.create_lab_result(
            f.lab_result_payload(
                sample["id"],
                registry["contaminant_id"],
                method="METHOD_1633",
                analyzed_at="2026-05-31T23:00:00.000Z",
            ),
            registry["lab_headers"],
        ),
        201,
    )
    assert_status(accepted, "SUBMITTED")


def test_a_claim_naming_the_wrong_entry_point_for_its_project_is_refused(api):
    """Both references resolve; the mismatch is between two fields of two entities.

    The capital project serves EPTDS-01, and a claim naming EPTDS-02 against it is
    refused even though both identifiers are live rows. Nothing is filed against the
    project, and the same body naming the project's own entry point is accepted into
    INVESTIGATING.

    PRD: "The named entry point must be the same entry point the named project
    serves, else `ERR_ENTRY_POINT_MISMATCH`."

    Design: Corner/validations/a_claim_pointing_at_another_entry_points_project_is_rejected
    """
    entry_point = register_entry_point(api)
    selected = selected_project(api, entry_point["id"])
    unrelated = register_entry_point(api, label="EPTDS-02")

    validate_error(
        api.create_cost_recovery_claim(
            f.cost_recovery_claim_payload(unrelated["id"], selected["project_id"]),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        ERR_ENTRY_POINT_MISMATCH,
        422,
    )

    assert_total_count(
        api.list_cost_recovery_claims(
            COMPLIANCE_OFFICER_HEADERS, params={"capital_project_id": selected["project_id"]}
        ),
        0,
    )
    assert_equals(selected["project"], "entry_point_id", entry_point["id"])

    claim = validate_success(
        api.create_cost_recovery_claim(
            f.cost_recovery_claim_payload(entry_point["id"], selected["project_id"]),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        201,
    )
    assert_status(claim, "INVESTIGATING")


def test_the_unreceived_sample_gate_masks_the_panel_membership_failure(api):
    """One request breaks two rules and reports only the higher one.

    The sample is still in transit and the reported compound was never on its panel,
    so both the state rung and the referential-integrity rung would fire; the state
    band sits above the referential band, so the answer is the custody failure. The
    panel rule was reachable all along: receiving the sample and repeating the
    identical submission produces it.

    PRD: "The bands, in order, are: authentication and authorisation, then ownership,
    then existence, then request shape and pagination, then optimistic concurrency,
    then state, then business safety, then business referential integrity, then
    business temporal rules, then business constraints, then fiscal rules."

    Design: Corner/validations/the_sample_state_gate_runs_before_the_panel_membership_check
    """
    registry = build_registry(api)
    unpanelled = register_contaminant(api, code="PFOS")
    sample = collect_sample(
        api, registry["entry_point_id"], [registry["contaminant_id"]], collected_at=_COLLECTED_AT
    )
    ship_sample(api, sample["id"], registry["laboratory_id"])
    payload = f.lab_result_payload(
        sample["id"], unpanelled["id"], analyzed_at=_ANALYZED_AT
    )

    response = api.create_lab_result(payload, registry["lab_headers"])

    validate_error(response, ERR_SAMPLE_NOT_RECEIVED, 422)
    assert response.json()["data"]["error_id"] != ERR_CONTAMINANT_NOT_IN_PANEL, (
        "The state band must outrank the panel-membership rule"
    )
    assert_status(read_sample(api, sample["id"]), "IN_TRANSIT")

    receive_sample(api, sample["id"], registry["laboratory_id"])
    validate_error(
        api.create_lab_result(payload, registry["lab_headers"]),
        ERR_CONTAMINANT_NOT_IN_PANEL,
        422,
    )


def test_the_removal_floor_blocks_selection_but_never_abandonment(api):
    """The same evidence refuses one action and permits the other.

    Two completed pilots remove 80.00 and 75.00 percent, so the two-pilot evidence
    floor is satisfied in both branches while neither technology reaches the 90.00
    percent removal floor. Selecting is therefore refused and leaves the evaluation
    piloting with no project behind it, whereas abandoning the same evaluation on the
    same evidence succeeds and hands the entry point back its untreated status.

    PRD: "A `SELECT` additionally requires at least one completed pilot whose
    `removal_pct` is at least 90.00, else `ERR_NO_QUALIFYING_TECHNOLOGY`. An
    `ABANDON` requires a `decision_note`, else `ERR_INVALID_REQUEST`."

    Design: Corner/validations/the_qualifying_technology_gate_applies_only_to_the_select_action
    """
    entry_point = register_entry_point(api)
    evaluation = open_evaluation(api, entry_point["id"])
    gac = register_pilot(api, f.gac_pilot_payload(evaluation["id"]))
    start_pilot(api, gac["id"])
    complete_pilot(api, gac["id"], effluent_ng_per_l=10.00)
    ix = register_pilot(api, f.ix_pilot_payload(evaluation["id"]))
    start_pilot(api, ix["id"])
    complete_pilot(
        api,
        ix["id"],
        effluent_ng_per_l=12.50,
        bed_volumes_treated=18000.00,
        spent_media_kg=300.00,
    )

    validate_error(
        api.decide_treatment_evaluation(
            evaluation["id"],
            f.evaluation_decision_payload(
                action="SELECT", decision_note="Attempting to select the least bad option"
            ),
            TREATMENT_ENGINEER_HEADERS,
        ),
        ERR_NO_QUALIFYING_TECHNOLOGY,
        422,
    )

    blocked = read_evaluation(api, evaluation["id"])
    assert_status(blocked, "PILOTING")
    assert_is_null(blocked, "selected_technology")
    assert_total_count(
        api.list_capital_projects(
            FINANCE_OFFICER_HEADERS, params={"treatment_evaluation_id": evaluation["id"]}
        ),
        0,
    )
    assert_decimal(read_pilot(api, gac["id"])["removal_pct"], 80.00, label="removal_pct")
    assert_decimal(read_pilot(api, ix["id"])["removal_pct"], 75.00, label="removal_pct")

    abandoned = validate_success(
        api.decide_treatment_evaluation(
            evaluation["id"],
            f.evaluation_decision_payload(
                action="ABANDON", decision_note="Neither technology clears the removal floor"
            ),
            TREATMENT_ENGINEER_HEADERS,
        )
    )
    assert_status(abandoned, "REJECTED_ALL")
    assert_equals(
        abandoned, "decision_note", "Neither technology clears the removal floor"
    )
    assert_entry_point_posture(
        read_entry_point(api, entry_point["id"]), treatment_status="NONE"
    )
    assert_total_count(
        api.list_capital_projects(
            FINANCE_OFFICER_HEADERS, params={"treatment_evaluation_id": evaluation["id"]}
        ),
        0,
    )


def test_the_open_violation_gate_and_the_history_gate_answer_on_different_entry_points(api):
    """The same request body earns two different refusals one entry point apart.

    Both entry points are quarterly with a single accepted quarter, so neither has
    the four-quarter record a reduction needs; they differ only in that the first
    carries an issued exceedance. The first is stopped by the posture rule that sits
    higher in the ladder, the second falls through to the history rule, and neither
    records a requested target.

    PRD: "Its `compliance_posture` must not be `VIOLATION_PENDING`, else
    `ERR_VIOLATION_PENDING_BLOCKS_REDUCTION`. Its `open_violation_count` must be
    zero, else `ERR_OPEN_VIOLATION_BLOCKS_REDUCTION`; an unrescinded exceedance
    blocks relief even after the posture itself has recovered, which is why the two
    checks are separate. `consecutive_qualifying_quarters` must be at least four,
    else `ERR_INSUFFICIENT_MONITORING_HISTORY`."

    Design: Corner/validations/the_violation_gate_applies_only_where_a_violation_is_open
    """
    registry = build_registry(api)
    violation = issued_violation(api, registry, reported_ng_per_l=4.50)
    clean_entry_point = register_entry_point(api, label="EPTDS-02")
    clean_registry = dict(registry, entry_point=clean_entry_point, entry_point_id=clean_entry_point["id"])
    accepted_quarter(
        api, clean_registry, "2026Q2", 1.20, preservative_lot="LOT-CLEAN"
    )

    validate_error(
        api.request_monitoring_reduction(
            registry["entry_point_id"],
            f.reduction_request_payload(
                justification="Requesting relief while the violation is open"
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        ERR_VIOLATION_PENDING_BLOCKS_REDUCTION,
        422,
    )
    blocked = read_entry_point(api, registry["entry_point_id"])
    assert_entry_point_posture(
        blocked,
        posture="VIOLATION_PENDING",
        monitoring_status="QUARTERLY",
        open_violation_count=1,
    )
    assert_is_null(blocked, "requested_monitoring_status")
    assert_equals(violation["determination"], "determination", "MCL_VIOLATION")

    validate_error(
        api.request_monitoring_reduction(
            clean_entry_point["id"],
            f.reduction_request_payload(
                justification="Requesting relief after one clean quarter"
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        ERR_INSUFFICIENT_MONITORING_HISTORY,
        422,
    )
    clean = read_entry_point(api, clean_entry_point["id"])
    assert_entry_point_posture(
        clean,
        monitoring_status="QUARTERLY",
        open_violation_count=0,
        consecutive_qualifying_quarters=1,
    )
    assert_is_null(clean, "requested_monitoring_status")
