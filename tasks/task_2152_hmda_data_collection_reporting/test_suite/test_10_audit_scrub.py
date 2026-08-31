"""The data scrub: drawing a sample, recording findings, the closed remediation
windows and the two defect-rate variants."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_three_defect_findings,
    assert_audit_finding,
    assert_audit_sample,
    close_audit_sample,
    create_application,
    create_audit_finding,
    create_audit_finding_payload,
    create_audit_sample,
    create_audit_sample_payload,
    create_institution,
    make_compliance_analyst_headers,
    read_audit_sample,
    set_clock,
    setup_originated_application,
    setup_sample_over_two_records,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_closing_an_already_closed_sample_is_rejected(api):
    """PRD §3.8: "Closing is defined only from `DRAFT` or `IN_REVIEW`; a sample
    already closed is refused with `ERR_SAMPLE_NOT_OPEN`."
    PRD §3.8: "With `defect_count` at zero the sample closes `CLOSED_CLEAN` with
    `defect_rate_pct` of 0.00, whether it closes from `DRAFT` or from
    `IN_REVIEW`."

    Design: Corner/state_machines/audit_sample_close_twice_returns_sample_not_open
    """
    institution = create_institution()
    setup_originated_application(institution["id"])
    sample = create_audit_sample(institution["id"])
    close_audit_sample(sample["id"], "FIELD_WEIGHTED")

    validate_error(
        api.close_audit_sample(
            sample["id"], {"defect_rate_basis": "RECORD_WEIGHTED"},
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_SAMPLE_NOT_OPEN.value,
    )

    after = read_audit_sample(sample["id"])
    assert after["status"] == "CLOSED_CLEAN"
    assert after["defect_rate_basis"] == "FIELD_WEIGHTED"
    assert after["defect_rate_pct"] == 0.00
    assert after["population_size"] == 1
    assert after["sample_size"] == 1


def test_the_first_finding_moves_the_sample_into_review(api):
    """PRD §3.8: "The very first finding on a sample moves it `DRAFT →
    IN_REVIEW`."
    PRD §3.8: "On acceptance, `is_defect` is derived as whether `recorded_value`
    and `source_document_value` differ, compared exactly and case-sensitively;
    `resolution` starts at `OPEN`."

    Design: Corner/state_machines/first_audit_finding_bubbles_sample_from_draft_to_in_review
    """
    institution = create_institution()
    record = setup_originated_application(institution["id"])
    sample = create_audit_sample(institution["id"])

    finding = validate_success(
        api.create_audit_finding(
            create_audit_finding_payload(
                sample["id"], record["id"], field_name="income_thousands",
                recorded_value="120", source_document_value="120",
                severity="NON_MATERIAL",
            ),
            make_compliance_analyst_headers(),
        ),
        201,
    )
    assert_audit_finding(finding)
    assert finding["is_defect"] is False
    assert finding["resolution"] == "OPEN"

    after = read_audit_sample(sample["id"])
    assert after["status"] == "IN_REVIEW"
    assert after["defect_count"] == 0
    assert after["records_with_defect_count"] == 0


def test_the_defect_comparison_is_case_sensitive(api):
    """PRD §3.8: "On acceptance, `is_defect` is derived as whether
    `recorded_value` and `source_document_value` differ, compared exactly and
    case-sensitively; `resolution` starts at `OPEN`."
    PRD §3.8: "Under `FIELD_WEIGHTED`, `defect_rate_pct` is `defect_count` divided
    by that total field count, multiplied by 100, and rounded to two decimal places
    — several defects on one record dilute across every field reviewed in the
    sample."

    Design: Corner/calculations/audit_finding_defect_comparison_is_case_sensitive
    """
    institution = create_institution()
    record = setup_originated_application(institution["id"])
    sample = create_audit_sample(institution["id"], fields_reviewed_per_record=5)

    finding = create_audit_finding(
        sample["id"], record["id"], field_name="race_codes",
        recorded_value="WHITE", source_document_value="white",
        severity="NON_MATERIAL",
    )
    assert finding["is_defect"] is True

    after = read_audit_sample(sample["id"])
    assert after["defect_count"] == 1
    assert after["records_with_defect_count"] == 1
    assert after["sample_size"] == 1

    closed = close_audit_sample(sample["id"], "FIELD_WEIGHTED")
    assert closed["defect_rate_pct"] == 20.00


def test_a_finding_naming_an_unsampled_record_is_rejected(api):
    """PRD §3.8: "A finding may only name a record the sample actually drew: an
    `application_id` absent from the sample's `selected_application_ids` is refused
    with `ERR_FINDING_APPLICATION_NOT_IN_SAMPLE`."

    Design: Corner/validations/finding_for_an_application_outside_the_sample_rejected
    """
    institution = create_institution()
    set_clock("2026-12-01T00:00:00Z")
    inside = setup_originated_application(institution["id"])
    outside = setup_originated_application(
        institution["id"], application_date="2026-10-01T00:00:00Z",
        loan_purpose="REFINANCING", loan_amount_cents=28000000, income_thousands=130,
        demographic_overrides={"race_codes": ["ASIAN"], "sex_code": "FEMALE"},
        action_overrides={"action_taken_date": "2026-11-02T00:00:00Z", "rate_spread": 1.90},
    )
    sample = create_audit_sample(institution["id"])
    assert inside["id"] in sample["selected_application_ids"]

    validate_error(
        api.create_audit_finding(
            create_audit_finding_payload(
                sample["id"], outside["id"], field_name="rate_spread",
                recorded_value="1.90", source_document_value="1.95",
                severity="NON_MATERIAL",
                remediation_start="2026-12-01T00:00:00Z",
                remediation_end="2026-12-05T00:00:00Z",
            ),
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_FINDING_APPLICATION_NOT_IN_SAMPLE.value,
    )

    after = read_audit_sample(sample["id"])
    assert after["population_size"] == 1
    assert after["sample_size"] == 1
    assert after["status"] == "DRAFT"
    assert after["defect_count"] == 0


def test_closing_an_unknown_sample_is_a_not_found(api):
    """PRD §2.9: "Path identifier resolution, left to right — the relevant
    not-found error, 404."
    PRD §2.6: "A request naming an institution that does not exist yields
    `ERR_INSTITUTION_NOT_FOUND`; an unknown register record yields
    `ERR_APPLICATION_NOT_FOUND`; and the same pattern holds for
    `ERR_DEMOGRAPHIC_ENTRY_NOT_FOUND`, `ERR_GEOCODE_ASSIGNMENT_NOT_FOUND`,
    `ERR_CENSUS_TRACT_NOT_FOUND`, `ERR_EDIT_RUN_NOT_FOUND`,
    `ERR_EDIT_EXCEPTION_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`, and
    `ERR_AUDIT_SAMPLE_NOT_FOUND`. All of these carry HTTP 404."

    Design: Corner/errors/close_unknown_audit_sample_returns_not_found
    """
    validate_error(
        api.close_audit_sample(
            UNKNOWN_ID, {"defect_rate_basis": "FIELD_WEIGHTED"},
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_AUDIT_SAMPLE_NOT_FOUND.value,
    )


def test_field_weighted_closure_dilutes_defects_across_every_reviewed_field(api):
    """PRD §3.8: "The total field count reviewed across the sample is `sample_size`
    multiplied by `fields_reviewed_per_record`. Under `FIELD_WEIGHTED`,
    `defect_rate_pct` is `defect_count` divided by that total field count,
    multiplied by 100, and rounded to two decimal places — several defects on one
    record dilute across every field reviewed in the sample."
    PRD §3.8: "With at least one defect it closes `IN_REVIEW →
    CLOSED_WITH_FINDINGS` and `defect_rate_pct` is computed under the chosen
    variant."

    Design: Difficulty/dual_variant_calc/audit_defect_rate_field_weighted_vs_record_weighted
    """
    scenario = setup_sample_over_two_records(fields_reviewed_per_record=4)
    add_three_defect_findings(
        scenario["sample"]["id"],
        scenario["application_a"]["id"],
        scenario["application_b"]["id"],
    )

    before = read_audit_sample(scenario["sample"]["id"])
    assert_audit_sample(before)
    assert before["population_size"] == 2
    assert before["sample_size"] == 2
    assert before["defect_count"] == 3
    assert before["records_with_defect_count"] == 2

    closed = close_audit_sample(scenario["sample"]["id"], "FIELD_WEIGHTED")
    assert closed["defect_rate_pct"] == 37.50
    assert closed["status"] == "CLOSED_WITH_FINDINGS"


def test_record_weighted_closure_collapses_defects_onto_the_defective_records(api):
    """PRD §3.8: "Under `RECORD_WEIGHTED`, `defect_rate_pct` is
    `records_with_defect_count` divided by `sample_size`, multiplied by 100, and
    rounded to two decimal places — several defects on one record collapse to a
    single defective record."
    PRD §3.8: "Against identical findings the two variants return different
    percentages, which is why the basis is recorded on the sample alongside the
    rate."
    PRD §3.8: "In both closures from `IN_REVIEW`, every finding belonging to the
    sample moves its `resolution` from `OPEN` to `ACCEPTED_AS_IS`."

    Design: Difficulty/dual_variant_calc/audit_defect_rate_field_weighted_vs_record_weighted
    """
    scenario = setup_sample_over_two_records(fields_reviewed_per_record=4)
    add_three_defect_findings(
        scenario["sample"]["id"],
        scenario["application_a"]["id"],
        scenario["application_b"]["id"],
    )
    first_closed = close_audit_sample(scenario["sample"]["id"], "FIELD_WEIGHTED")
    assert first_closed["defect_rate_pct"] == 37.50

    second_sample = create_audit_sample(
        scenario["institution"]["id"], fields_reviewed_per_record=4
    )
    add_three_defect_findings(
        second_sample["id"],
        scenario["application_a"]["id"],
        scenario["application_b"]["id"],
    )
    closed = close_audit_sample(second_sample["id"], "RECORD_WEIGHTED")

    assert closed["defect_rate_pct"] == 100.00
    assert closed["status"] == "CLOSED_WITH_FINDINGS"
    assert closed["defect_rate_pct"] != first_closed["defect_rate_pct"]

    findings, _meta = validate_paginated(
        api.list_audit_sample_findings(second_sample["id"], TEST_USERS["examiner_headers"])
    )
    assert all(row["resolution"] == "ACCEPTED_AS_IS" for row in findings)


def test_sample_size_is_clamped_by_the_population_itself(api):
    """PRD §3.8: "The tier percentage is 10 percent when `population_size` is at
    most 30, 30 percent when it is at most 100, 15 percent when it is at most 500,
    and 5 percent above that. The raw draw is `population_size` multiplied by that
    tier percentage, rounded up to the next whole number. `sample_size` is then the
    smallest of three quantities: the larger of the raw draw and the minimum sample
    of 5, the maximum sample of 50, and `population_size` itself — so a tiny
    population is sampled in full rather than over-drawn, and a vast one is capped
    at fifty records."

    Design: Difficulty/combinatorial_formula/audit_sample_size_nested_min_max_over_tier_floor_and_population
    """
    institution = create_institution()
    setup_originated_application(institution["id"])
    setup_originated_application(
        institution["id"], application_date="2026-02-12T00:00:00Z",
        loan_purpose="REFINANCING", loan_amount_cents=41000000, income_thousands=150,
        demographic_overrides={"race_codes": ["ASIAN"], "sex_code": "FEMALE"},
        action_overrides={"action_taken_date": "2026-04-20T00:00:00Z", "rate_spread": 2.10},
    )
    setup_originated_application(
        institution["id"], application_date="2026-02-14T00:00:00Z",
        loan_type="FHA", loan_purpose="HOME_IMPROVEMENT",
        lien_status="SUBORDINATE_LIEN", loan_amount_cents=8000000, income_thousands=95,
        demographic_overrides={"ethnicity_codes": ["HISPANIC_OR_LATINO"],
                               "sex_code": "FEMALE"},
        action_overrides={"action_taken_date": "2026-05-11T00:00:00Z", "rate_spread": 0.90},
    )

    sample = validate_success(
        api.create_audit_sample(
            create_audit_sample_payload(institution["id"], fields_reviewed_per_record=6),
            make_compliance_analyst_headers(),
        ),
        201,
    )
    assert sample["population_size"] == 3
    assert sample["sample_size"] == 3
    assert sample["sample_size"] != 1, "the raw tier draw alone is not the answer"
    assert sample["sample_size"] != 5, "the minimum-sample floor alone is not the answer"


def test_the_systematic_walk_selects_every_candidate_in_creation_order(api):
    """PRD §3.8: "Candidates are ordered by `created_at` ascending — never by
    identifier — and their number is stored as `population_size`."
    PRD §3.8: "The stride is `population_size` divided by `sample_size` and rounded
    down, with a floor of 1. `selected_application_ids` then holds, in order, the
    identifiers of the candidates found at positions zero, one stride, two strides,
    and so on, taking as many entries as `sample_size` demands."
    PRD §3.8: "When `method` reads `STRATIFIED_BY_ACTION`, the candidate list is
    first ordered by `action_taken` in the enumeration order given in §3.5 and only
    then by `created_at` ascending within each action, and the same stride walk is
    applied to that reordered list. A newly drawn sample starts in `DRAFT`."

    Design: Difficulty/combinatorial_formula/audit_sample_size_nested_min_max_over_tier_floor_and_population
    """
    institution = create_institution()
    first = setup_originated_application(institution["id"])
    second = setup_originated_application(
        institution["id"], application_date="2026-02-12T00:00:00Z",
        loan_purpose="REFINANCING", loan_amount_cents=41000000, income_thousands=150,
        demographic_overrides={"race_codes": ["ASIAN"], "sex_code": "FEMALE"},
        action_overrides={"action_taken_date": "2026-04-20T00:00:00Z", "rate_spread": 2.10},
    )
    third = setup_originated_application(
        institution["id"], application_date="2026-02-14T00:00:00Z",
        loan_type="FHA", loan_purpose="HOME_IMPROVEMENT",
        lien_status="SUBORDINATE_LIEN", loan_amount_cents=8000000, income_thousands=95,
        demographic_overrides={"ethnicity_codes": ["HISPANIC_OR_LATINO"],
                               "sex_code": "FEMALE"},
        action_overrides={"action_taken_date": "2026-05-11T00:00:00Z", "rate_spread": 0.90},
    )

    sample = create_audit_sample(institution["id"], fields_reviewed_per_record=6)
    assert len(sample["selected_application_ids"]) == 3
    assert sample["selected_application_ids"] == [first["id"], second["id"], third["id"]]
    assert sample["status"] == "DRAFT"


def test_drawing_a_sample_over_an_empty_candidate_set_is_rejected(api):
    """PRD §3.8: "The candidate population is every register record of the
    institution with an `action_taken` recorded, whose `action_taken_date` falls on
    or after `period_start` and on or before `period_end`, whose `lar_status` is one
    of `COMPLETE`, `EXCEPTION_FLAGGED`, or `CLEARED`, and whose `is_superseded`
    flag is false."
    PRD §3.8: "An empty candidate set is refused with
    `ERR_EMPTY_SAMPLE_POPULATION`."

    Design: Difficulty/boundary_precision_check/audit_sample_over_empty_candidate_set_is_rejected
    """
    institution = create_institution()
    create_application(institution["id"])

    validate_error(
        api.create_audit_sample(
            create_audit_sample_payload(institution["id"]),
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_EMPTY_SAMPLE_POPULATION.value,
    )


def test_no_sample_row_survives_the_empty_population_rejection(api):
    """PRD §3.8: "An empty candidate set is refused with
    `ERR_EMPTY_SAMPLE_POPULATION`."
    PRD §3.8: "The analyst draws a sample by naming the institution with
    `institution_id`, choosing a `method` of either `SYSTEMATIC_INTERVAL` or
    `STRATIFIED_BY_ACTION`, bounding the review with `period_start` and
    `period_end`, and declaring `fields_reviewed_per_record`, the number of register
    fields re-keyed per sampled record, which must be at least 1."

    Design: Difficulty/boundary_precision_check/audit_sample_over_empty_candidate_set_is_rejected
    """
    institution = create_institution()
    create_application(institution["id"])

    validate_error(
        api.create_audit_sample(
            create_audit_sample_payload(institution["id"]),
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_EMPTY_SAMPLE_POPULATION.value,
    )

    rows, meta = validate_paginated(
        api.list_institution_audit_samples(institution["id"], TEST_USERS["examiner_headers"])
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_a_remediation_window_touching_an_open_finding_collides(api):
    """PRD §3.8: "Because the same record cannot be under two simultaneous
    remediation efforts, a new finding is refused with
    `ERR_REMEDIATION_WINDOW_OVERLAP` when another finding on the same
    `application_id` whose `resolution` still reads `OPEN` satisfies both of the
    following: the new window's start is no later than the existing window's end,
    and the existing window's start is no later than the new window's end."
    PRD §3.8: "Because the window is closed at both ends, touching endpoints do
    collide — a new window beginning at exactly the instant an existing one ends is
    a conflict."

    Design: Difficulty/resource_temporal_overlap/remediation_closed_windows_touching_endpoints_rejected
    """
    scenario = setup_sample_over_two_records(fields_reviewed_per_record=4)
    create_audit_finding(
        scenario["sample"]["id"], scenario["application_a"]["id"],
        field_name="income_thousands", recorded_value="120",
        source_document_value="112", severity="MATERIAL",
        remediation_start="2026-09-01T00:00:00Z", remediation_end="2026-09-05T00:00:00Z",
    )

    validate_error(
        api.create_audit_finding(
            create_audit_finding_payload(
                scenario["sample"]["id"], scenario["application_a"]["id"],
                field_name="rate_spread", recorded_value="1.75",
                source_document_value="1.85", severity="NON_MATERIAL",
                remediation_start="2026-09-05T00:00:00Z",
                remediation_end="2026-09-10T00:00:00Z",
            ),
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_REMEDIATION_WINDOW_OVERLAP.value,
    )


def test_the_same_remediation_window_is_free_on_another_record(api):
    """PRD §3.8: "Because the same record cannot be under two simultaneous
    remediation efforts, a new finding is refused with
    `ERR_REMEDIATION_WINDOW_OVERLAP` when another finding on the same
    `application_id` whose `resolution` still reads `OPEN` satisfies both of the
    following: the new window's start is no later than the existing window's end,
    and the existing window's start is no later than the new window's end."
    PRD §3.8: "The sample's `defect_count` — its own findings marked as defects —
    and `records_with_defect_count` — the number of distinct records among those
    defect findings — are recomputed."

    Design: Difficulty/resource_temporal_overlap/remediation_closed_windows_touching_endpoints_rejected
    """
    scenario = setup_sample_over_two_records(fields_reviewed_per_record=4)
    create_audit_finding(
        scenario["sample"]["id"], scenario["application_a"]["id"],
        field_name="income_thousands", recorded_value="120",
        source_document_value="112", severity="MATERIAL",
        remediation_start="2026-09-01T00:00:00Z", remediation_end="2026-09-05T00:00:00Z",
    )
    validate_error(
        api.create_audit_finding(
            create_audit_finding_payload(
                scenario["sample"]["id"], scenario["application_a"]["id"],
                field_name="rate_spread", recorded_value="1.75",
                source_document_value="1.85", severity="NON_MATERIAL",
                remediation_start="2026-09-05T00:00:00Z",
                remediation_end="2026-09-10T00:00:00Z",
            ),
            make_compliance_analyst_headers(),
        ),
        ApiErrorId.ERR_REMEDIATION_WINDOW_OVERLAP.value,
    )

    validate_success(
        api.create_audit_finding(
            create_audit_finding_payload(
                scenario["sample"]["id"], scenario["application_b"]["id"],
                field_name="rate_spread", recorded_value="2.10",
                source_document_value="2.20", severity="NON_MATERIAL",
                remediation_start="2026-09-05T00:00:00Z",
                remediation_end="2026-09-10T00:00:00Z",
            ),
            make_compliance_analyst_headers(),
        ),
        201,
    )

    a_rows, a_meta = validate_paginated(
        api.list_application_audit_findings(
            scenario["application_a"]["id"], TEST_USERS["examiner_headers"]
        )
    )
    b_rows, b_meta = validate_paginated(
        api.list_application_audit_findings(
            scenario["application_b"]["id"], TEST_USERS["examiner_headers"]
        )
    )
    assert a_meta["total_count"] == 1
    assert b_meta["total_count"] == 1
    assert len(a_rows) == 1 and len(b_rows) == 1

    sample = read_audit_sample(scenario["sample"]["id"])
    assert sample["defect_count"] == 2
    assert sample["records_with_defect_count"] == 2
    assert sample["status"] == "IN_REVIEW"
