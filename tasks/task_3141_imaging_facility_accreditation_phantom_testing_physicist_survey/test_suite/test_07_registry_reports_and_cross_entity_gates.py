"""Dose registry benchmark reporting, credential gates and read endpoints."""
from test_helpers import (
    TEST_USERS,
    api_client,
    read_facility,
    read_record,
    read_submission,
    read_unit,
    setup_imaging_facility,
    validate_error,
    validate_paginated,
    validate_success,
)

REVIEWER = TEST_USERS["accreditation_body_headers"]
READER = TEST_USERS["any_headers"]


# ══════════════════════════════════════════════════════════════════════════
# Registry benchmark classification
# ══════════════════════════════════════════════════════════════════════════

def test_a_first_record_compares_against_its_modality_constant(api):
    """PRD §3.6: "When no other record of the same unit and the same exam
    category is already `SUBMITTED`, the comparison value is the modality
    constant for the record's own `modality_code`: `2.0` for `MRI`, `2.3` for
    `CT`, `2.5` for `MAMM`, `3.0` for `PET` and `2.2` for `US`."
    PRD §3.6: "The rule then computes the ratio of the record's
    `dose_index_value` to that comparison value and classifies it: a ratio of
    at most `1.00` is `WITHIN_BENCHMARK`"

    Design: Corner/entities/dose_registry_record_benchmark_comparison_value_is_computed_from_the_category_constant
    """
    scenario = setup_imaging_facility()
    record = validate_success(
        api_client.create_dose_registry_record(
            {
                "unit_id": scenario.unit_id,
                "exam_category_code": "CT_HEAD",
                "exam_month": "2026-07-01T00:00:00Z",
                "dose_index_value": 2.3,
                "benchmark_comparison_value": 9.9,
            },
            scenario.admin,
        ),
        201,
    )
    submitted = validate_success(
        api_client.submit_dose_registry_record(record["id"], {}, scenario.admin), 200
    )
    # The client-supplied comparison value is ignored.
    assert submitted["benchmark_comparison_value"] == 2.3
    assert submitted["benchmark_status"] == "WITHIN_BENCHMARK"
    assert submitted["submission_status"] == "SUBMITTED"
    assert submitted["registry_fee_cents"] == 2500
    assert submitted["submitted_at"] == "2026-09-05T00:00:00Z"


def test_a_later_record_compares_against_the_stored_maximum(api):
    """PRD §3.6: "When such records do exist, the comparison value is instead
    the maximum `benchmark_comparison_value` already on file among them."
    PRD §3.6: "a ratio above `1.00` but at most `1.35` is `ABOVE_BENCHMARK`"
    PRD §3.6: "Only submitted records of the same unit and category
    participate — staged records, rejected records, records of other units and
    records of other categories are all excluded."

    Design: Difficulty/combinatorial_formula/registry_benchmark_classification_evaluation_order_over_max_comparison
    """
    scenario = setup_imaging_facility()
    first = _stage_and_submit(scenario, 2.3, "2026-07-01T00:00:00Z")
    assert first["benchmark_status"] == "WITHIN_BENCHMARK"
    assert first["benchmark_comparison_value"] == 2.3

    second = _stage_and_submit(scenario, 2.7, "2026-08-01T00:00:00Z")
    assert second["benchmark_comparison_value"] == 2.3
    assert second["benchmark_status"] == "ABOVE_BENCHMARK"
    assert second["benchmark_status"] != "WITHIN_BENCHMARK"
    assert read_facility(scenario.facility_id)["registry_credit_cents"] == 500000 - 2500 - 2500


def test_the_record_under_evaluation_is_included_in_its_own_unit_average(api):
    """PRD §3.6: "It collects every dose registry record of the same unit and
    the same exam category whose `submission_status` is `SUBMITTED`, sums
    their `dose_index_value` values into a numerator, sums their
    `benchmark_comparison_value` values into a denominator, and divides the
    first by the second."
    PRD §3.6: "The record being submitted is counted inside its own average —
    the included-self variant — which means a unit already holding one
    submitted `CT_HEAD` record at `2.3`, receiving a new `2.7`, yields an
    average of `2.50`"

    Design: Difficulty/combinatorial_formula/registry_benchmark_classification_evaluation_order_over_max_comparison
    """
    scenario = setup_imaging_facility()
    _stage_and_submit(scenario, 2.3, "2026-07-01T00:00:00Z")
    second = _stage_and_submit(scenario, 2.7, "2026-08-01T00:00:00Z")

    # numerator (2.3 + 2.7) / denominator (2.3 + 2.3) = 2.50
    assert second["dose_benchmark_average"] == 2.5
    assert _round6(second["dose_benchmark_average"]) == 2.5


def test_the_variant_divergence_on_the_unit_average(api):
    """PRD §3.6: "skipping the record under test would leave the same inputs
    at `2.30` with a different denominator"
    PRD §3.6: "The average is retained at full precision and reported with 6
    significant digits."

    Design: Corner/calculations/facility_dose_index_benchmark_included_self_variance
    """
    scenario = setup_imaging_facility()
    _stage_and_submit(scenario, 2.3, "2026-07-01T00:00:00Z")
    second = _stage_and_submit(scenario, 2.7, "2026-08-01T00:00:00Z")

    # The included-self variant yields 2.50; the excluded-self variant would
    # leave the same rows at 2.30.
    assert second["dose_benchmark_average"] == 2.5
    assert second["dose_benchmark_average"] != 2.3
    assert second["benchmark_status"] == "ABOVE_BENCHMARK"
    assert _round6(second["dose_benchmark_average"]) == 2.5


def test_the_first_record_of_the_pair_is_within_benchmark(api):
    """PRD §3.6: "a ratio of at most `1.00` is `WITHIN_BENCHMARK`"
    PRD §3.6: "The facility dose index benchmark rule computes the
    unit-and-category average."

    Design: Corner/calculations/facility_dose_index_benchmark_included_self_variance
    """
    scenario = setup_imaging_facility()
    first = _stage_and_submit(scenario, 2.3, "2026-07-01T00:00:00Z")
    _stage_and_submit(scenario, 2.7, "2026-08-01T00:00:00Z")

    assert read_record(first["id"])["benchmark_status"] == "WITHIN_BENCHMARK"
    assert read_facility(scenario.facility_id)["registry_credit_cents"] == 500000 - 5000


# ══════════════════════════════════════════════════════════════════════════
# Cross-entity credential gate on the review path
# ══════════════════════════════════════════════════════════════════════════

def test_a_revoked_technologist_credential_blocks_the_review_acceptance(api):
    """PRD §3.3: "An accepted review is gated by two safety conditions in
    addition to the coverage arithmetic. The facility must have no open
    corrective action plan whose `deadline_status` is `OVERDUE`, and every
    personnel qualification of the facility whose `personnel_role` is
    `INTERPRETING_PHYSICIAN` or `TECHNOLOGIST` must be `VERIFIED` — the
    applicable refusal being `ERR_QUALIFICATION_UNVERIFIED`."
    PRD §3.3: "A review request may also be refused outright, before any
    scoring, when it asks for an acceptance the evidence does not support"

    Design: Difficulty/cross_entity_state_dependency/clinical_review_accept_gated_by_technologist_roster_state
    """
    scenario = setup_imaging_facility()
    submission = validate_success(
        api_client.create_clinical_image_submission(
            {
                "unit_id": scenario.unit_id,
                "image_type": "CLINICAL",
                "submitted_at": "2026-09-12T00:00:00Z",
                "reviewer_note_code": "NOTE-1",
                "required_view_count": 10,
                "accepted_view_count": 10,
                "expected_unit_version": read_unit(scenario.unit_id)["version"],
            },
            scenario.admin,
        ),
        201,
    )
    validate_success(
        api_client.revoke_personnel_qualification(
            scenario.tech_qualification_id, {}, REVIEWER
        ),
        200,
    )

    res = api_client.review_clinical_image_submission(
        submission["id"], {"review_outcome": "ACCEPT"}, REVIEWER
    )
    assert res.status_code == 400, f"Expected 400, got {res.status_code}: {res.text}"
    error = validate_error(res, "ERR_QUALIFICATION_UNVERIFIED")
    assert error["error_id"] != "ERR_ACCREDITATION_LAPSED"

    after = read_submission(submission["id"])
    assert after["review_status"] == "PENDING_REVIEW"
    assert after["review_outcome_score"] is None
    assert read_facility(scenario.facility_id)["roster_disposition"] == "HALT"


def test_a_revoked_credential_is_reported_by_the_qualification_read(api):
    """PRD §3.8: "Revocation is the draft act available to the accrediting
    body and takes effect from `PENDING`, `VERIFIED` or `LAPSED` — any status
    other than the terminal `REVOKED`."
    PRD §3.8: "If any gathered row is `REVOKED`, the disposition is `HALT`"

    Design: Difficulty/cross_entity_state_dependency/clinical_review_accept_gated_by_technologist_roster_state
    """
    scenario = setup_imaging_facility()
    revoked = validate_success(
        api_client.revoke_personnel_qualification(scenario.tech_qualification_id, {}, REVIEWER), 200
    )
    assert revoked["credential_status"] == "REVOKED"

    read_back = validate_success(
        api_client.get_personnel_qualification(scenario.tech_qualification_id, READER), 200
    )
    assert read_back["credential_status"] == "REVOKED"
    assert read_facility(scenario.facility_id)["roster_disposition"] == "HALT"


# ══════════════════════════════════════════════════════════════════════════
# Read endpoints
# ══════════════════════════════════════════════════════════════════════════

def test_the_facility_summary_reports_the_same_derived_posture(api):
    """PRD §2.4: "Three derived values on a facility summarize where that
    facility stands in the program, and they are recomputed as a consequence
    of the operations described in §3 rather than set by hand."

    Design: Corner/endpoints/facility_summary_read_returns_the_same_derived_fields_as_the_entity_read
    """
    scenario = setup_imaging_facility()
    entity = read_facility(scenario.facility_id)
    summary = validate_success(api_client.get_facility_summary(scenario.facility_id, READER), 200)

    assert summary["accreditation_currency"] == entity["accreditation_currency"] == "CURRENT"
    assert summary["payer_participation_status"] == entity["payer_participation_status"]
    assert summary["roster_disposition"] == entity["roster_disposition"]


def test_the_summary_read_does_not_advance_the_facility_version(api):
    """PRD §2.8: "`version` (integer): a server-managed counter that starts at
    1 and advances by one on every mutation of the resource, including
    mutations produced by cascades rather than by direct client writes."
    PRD §2.4: "None of them is ever accepted as a request input."

    Design: Corner/endpoints/facility_summary_read_returns_the_same_derived_fields_as_the_entity_read
    """
    scenario = setup_imaging_facility()
    version_before = read_facility(scenario.facility_id)["version"]
    validate_success(api_client.get_facility_summary(scenario.facility_id, READER), 200)
    validate_success(api_client.get_facility_summary(scenario.facility_id, READER), 200)
    assert read_facility(scenario.facility_id)["version"] == version_before


def test_the_qualification_listing_filters_by_role_with_pagination(api):
    """PRD §2.3: "`limit` caps the number of items returned; when omitted it
    defaults to 10, and it must fall within the inclusive range of 1 to 100."
    PRD §2.3: "The pagination block is reported back inside `meta`: `limit`,
    `offset`, `total_count` (the total number of matching rows before paging),
    and `has_more` (true when further rows remain)."

    Design: Corner/entities/personnel_qualification_list_filters_by_role_and_credential_status
    """
    scenario = setup_imaging_facility()
    validate_success(
        api_client.create_personnel_qualification(
            {
                "facility_id": scenario.facility_id,
                "person_name": "Ravi Menon",
                "personnel_role": "INTERPRETING_PHYSICIAN",
                "credential_number": "RAD-3001",
                "ce_credit_hours": 40.0,
                "required_ce_hours": 40.0,
                "credential_expires_on": "2027-12-31T00:00:00Z",
            },
            REVIEWER,
        ),
        201,
    )

    filtered, filtered_meta = validate_paginated(
        api_client.list_personnel_qualifications(
            READER, {"facility_id": scenario.facility_id, "personnel_role": "MEDICAL_PHYSICIST"}
        )
    )
    assert filtered_meta["total_count"] == 1
    assert filtered_meta["has_more"] is False
    assert len(filtered) == 1
    assert filtered[0]["credential_number"] == "PHYS-2001"

    everything, everything_meta = validate_paginated(
        api_client.list_personnel_qualifications(READER, {"facility_id": scenario.facility_id})
    )
    assert everything_meta["total_count"] == 3
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in everything_meta, f"meta must carry {key}"


def test_a_pagination_limit_below_the_declared_minimum_is_rejected(api):
    """PRD §2.3: "`limit` caps the number of items returned; when omitted it
    defaults to 10, and it must fall within the inclusive range of 1 to 100."

    Design: Corner/entities/personnel_qualification_list_filters_by_role_and_credential_status
    """
    scenario = setup_imaging_facility()
    res = api_client.list_personnel_qualifications(
        READER, {"facility_id": scenario.facility_id, "limit": 0}
    )
    assert res.status_code >= 400, f"Expected a rejection for limit 0, got {res.status_code}"


def test_an_unknown_role_cannot_read_the_qualification_listing(api):
    """PRD §2.1: "Five role names are recognized, spelled exactly as follows:
    `FacilityAdmin`, `MedicalPhysicist`, `AccreditationBody`, `Any`, and
    `Anonymous`."

    Design: Corner/entities/personnel_qualification_list_filters_by_role_and_credential_status
    """
    setup_imaging_facility()
    res = api_client.list_personnel_qualifications(
        {"X-User-ID": "unknown-principal", "X-User-Role": "Auditor", "Content-Type": "application/json"},
        {},
    )
    validate_error(res, "ERR_UNAUTHENTICATED")

    data, meta = validate_paginated(api_client.list_personnel_qualifications(READER, {}))
    assert meta["total_count"] >= 2


# ─── local helpers ────────────────────────────────────────────────────────

def _stage_and_submit(scenario, value, exam_month):
    record = validate_success(
        api_client.create_dose_registry_record(
            {
                "unit_id": scenario.unit_id,
                "exam_category_code": "CT_HEAD",
                "exam_month": exam_month,
                "dose_index_value": value,
            },
            scenario.admin,
        ),
        201,
    )
    return validate_success(
        api_client.submit_dose_registry_record(record["id"], {}, scenario.admin), 200
    )


def _round6(value):
    return float(f"{value:.6g}")