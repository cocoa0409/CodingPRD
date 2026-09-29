"""Violation-to-error mappings and the priority ordering between competing rules.

Each test drives one family of refusals: the request-shape rung, the commitment
bounds, the seven uniqueness keys, the data-sufficiency thresholds, the workload
ceiling, methodology version integrity, the exit notice window, the registry
listing guard and the settlement preconditions.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_BUFFER_POOL_DEFICIT,
    ERR_CLAWBACK_OUTSTANDING,
    ERR_COMMITMENT_TERMS_INVALID,
    ERR_COVERAGE_BELOW_MINIMUM,
    ERR_DUPLICATE_BASELINE,
    ERR_DUPLICATE_DATA_PACKET,
    ERR_DUPLICATE_PAYMENT,
    ERR_DUPLICATE_QUANTIFICATION_RUN,
    ERR_DUPLICATE_STANDARD_VERSION,
    ERR_DUPLICATE_VERIFICATION,
    ERR_EXIT_WINDOW_NOT_OPEN,
    ERR_INVALID_REQUEST,
    ERR_SAMPLE_TOO_SMALL,
    ERR_STANDARD_VERSION_MISMATCH,
    ERR_SUPERSEDED_BATCH_MISMATCH,
    ERR_SUPERSEDED_BATCH_NOT_CANCELLED,
    ERR_TELEMETRY_EVIDENCE_REQUIRED,
    ERR_UNRESOLVED_REVERSAL,
    ERR_VERIFIER_CAPACITY_EXCEEDED,
)
from test_helpers.assertions import (
    assert_acres,
    assert_pct,
    assert_rate,
    assert_tonnes,
)
from test_helpers.constants import (
    BASELINE_HISTORICAL_DATA,
    BASELINE_PROPOSED,
    CLOCK_2027,
    COMPLETENESS_PARTIAL,
    CROP_YEAR_2026,
    CROP_YEAR_2027,
    ENROLLMENT_ACTIVE,
    ENROLLMENT_EXIT_REQUESTED,
    EVIDENCE_EQUIPMENT_TELEMETRY,
    EVIDENCE_FARM_RECORD,
    EXIT_LAND_SALE,
    EXIT_VOLUNTARY,
    GROWER_ACTIVE,
    ISSUANCE_CANCELLED,
    ISSUANCE_ISSUED,
    METHOD_MEASUREMENT,
    METHOD_MODEL,
    OPINION_PENDING,
    OPINION_POSITIVE,
    PAYMENT_ACCRUED,
    PAYMENT_CLAWED_BACK,
    PERMANENCE_BREACHED,
    PERMANENCE_IN_COMPLIANCE,
    POOL_DEFICIT,
    POOL_HEALTHY,
    QC_PASSED,
    REGISTRY_LISTED,
    REGISTRY_SUSPENDED,
    REGISTRY_UNLISTED,
    REVERSAL_ASSESSED,
    REVERSAL_REPORTED,
    REVERSAL_UNINTENTIONAL,
    RISK_TIER_HIGH,
    RUN_VERIFIED,
    SOIL_LOAM,
    STANDARD_ACTIVE,
)
from test_helpers.factories import (
    accrual_payload,
    baseline_payload,
    boundary_payload,
    cancellation_payload,
    clock_payload,
    data_packet_payload,
    enrollment_payload,
    exit_decision_payload,
    exit_request_payload,
    grower_payload,
    issue_payload,
    practice_history_payload,
    practice_standard_payload,
    quantification_run_payload,
    registry_listing_payload,
    retirement_payload,
    reversal_payload,
    revision_payload,
    verification_payload,
)
from test_helpers.test_users import (
    ADMIN_BASELINE_HEADERS,
    ADMIN_HEADERS,
    ADMIN_REVERSAL_ASSESSOR_HEADERS,
    ADMIN_REVERSAL_REPORTER_HEADERS,
    REGISTRY_HEADERS,
)


def test_seven_body_defects_all_collapse_to_one_invalid_request_code(scenario):
    """A missing field, an unknown enum member, a degenerate rectangle, a negative
    acreage, a percentage above 100, a crop year outside the window and an instant
    without its trailing Z are all refused as malformed, and none of them persists a row.

    PRD §2.10: "Every required body field is present and non-null; enum fields carry a
    declared member; decimal fields are numbers inside their declared scale; acreage,
    tonnage, percentage and cents fields are not negative; percentage fields lie between 0
    and 100 inclusive; a `crop_year` is an integer between 2000 and 2100 inclusive; the
    boundary values are integers with `boundary_max_x` strictly greater than
    `boundary_min_x` and `boundary_max_y` strictly greater than `boundary_min_y`; instants
    are ISO 8601 UTC with a trailing `Z` → otherwise `ERR_INVALID_REQUEST` (400)."

    PRD §2.10: "The rungs are evaluated in ascending order, the **first** violated rung
    decides the response, and no later rung runs."

    Design: Corner/validations/request_body_violations_return_invalid_request
    """
    scenario.set_clock()
    scenario.publish_standard()
    scenario.create_grower()
    scenario.mapped_field()
    scenario.create_enrollment()

    without_tax_id = grower_payload()
    without_tax_id.pop("tax_id")
    validate_error(
        scenario.api.create_grower(without_tax_id, ADMIN_HEADERS), ERR_INVALID_REQUEST, 400
    )

    validate_error(
        scenario.api.create_field(
            scenario.grower_id,
            boundary_payload(4000, 4000, 5000, 5000, gross_acres=250.00,
                             soil_group="MARS_REGOLITH"),
            ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    # A rectangle of zero width is refused on the shape rung rather than accepted
    # and derived to 0.00 mapped acres.
    validate_error(
        scenario.api.create_field(
            scenario.grower_id,
            boundary_payload(6000, 6000, 6000, 7000, gross_acres=10.00, soil_group=SOIL_LOAM),
            ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    validate_error(
        scenario.api.create_enrollment(
            enrollment_payload(scenario.field_id, scenario.standard_id, enrolled_acres=-1.00),
            ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    # The shape rung precedes every quality computation, so no packet is scored.
    validate_error(
        scenario.api.file_data_packet(
            scenario.enrollment_id,
            data_packet_payload(CROP_YEAR_2026, source=EVIDENCE_FARM_RECORD, coverage_pct=120.00),
            ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    validate_error(
        scenario.api.file_practice_history(
            scenario.field_id,
            practice_history_payload(1999, adopted=True, acres=100.00),
            ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    validate_error(
        scenario.api.set_clock(clock_payload("2026-06-01")), ERR_INVALID_REQUEST, 400
    )

    fields, field_meta = validate_paginated(
        scenario.api.list_fields({"grower_id": scenario.grower_id}, ADMIN_HEADERS)
    )
    assert field_meta["total_count"] == 1
    assert fields[0]["id"] == scenario.field_id

    _rows, enrollment_meta = validate_paginated(
        scenario.api.list_enrollments({"field_id": scenario.field_id}, ADMIN_HEADERS)
    )
    assert enrollment_meta["total_count"] == 1

    _history, history_meta = validate_paginated(
        scenario.api.list_practice_history({"field_id": scenario.field_id}, ADMIN_HEADERS)
    )
    assert history_meta["total_count"] == 0

    _packets, packet_meta = validate_paginated(
        scenario.api.list_data_packets({"enrollment_id": scenario.enrollment_id}, ADMIN_HEADERS)
    )
    assert packet_meta["total_count"] == 0


def test_commitment_bounds_refuse_four_breaches_and_admit_both_equalities(scenario):
    """Too few commitment years, too many, more acres than the survey found and zero acres
    all carry the same code, while equality at the minimum year count and at the surveyed
    acreage is admitted.

    PRD §3.3: "Commitment terms are checked as a group: `commitment_years` must be at least
    the pinned standard's `min_adoption_years` and at most 12, `enrolled_acres` must be
    greater than zero and must not exceed the field's surveyed `mapped_acres`, and any
    breach of those three reports `ERR_COMMITMENT_TERMS_INVALID`."

    Design: Corner/validations/commitment_terms_bounds_are_enforced_with_inclusive_acreage_equality
    """
    scenario.set_clock()
    scenario.publish_standard()
    scenario.create_grower()
    field = scenario.mapped_field()
    assert_acres(field["mapped_acres"], 1000.00)
    assert scenario.standard["min_adoption_years"] == 3

    for overrides in (
        {"commitment_years": 2},
        {"commitment_years": 13},
        {"enrolled_acres": 1500.00},
        {"enrolled_acres": 0.00},
    ):
        validate_error(
            scenario.api.create_enrollment(
                enrollment_payload(scenario.field_id, scenario.standard_id, **overrides),
                ADMIN_HEADERS,
            ),
            ERR_COMMITMENT_TERMS_INVALID,
            422,
        )

    accepted = validate_success(
        scenario.api.create_enrollment(
            enrollment_payload(scenario.field_id, scenario.standard_id,
                               commitment_years=3, enrolled_acres=1000.00),
            ADMIN_HEADERS,
        ),
        201,
    )

    assert accepted["commitment_years"] == 3
    assert_acres(accepted["enrolled_acres"], 1000.00)

    rows, meta = validate_paginated(
        scenario.api.list_enrollments({"field_id": scenario.field_id}, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == accepted["id"]


def test_four_composite_keys_each_raise_their_own_duplicate_code(scenario):
    """Republishing a standard version, repeating a baseline method, refiling a crop year
    from the same source and reopening a crop year under another method each raise their own
    409, while bumping the standard version escapes the key altogether.

    PRD §2.10: "Seven distinct uniqueness rules live on this rung, each with its own code
    (all 409)"

    PRD §3.4: "At most one `PROPOSED` baseline may exist per enrollment and `method`; a
    second proposal naming the **same** method is refused with `ERR_DUPLICATE_BASELINE`."

    PRD §3.5: "At most one non-rejected packet may exist for a given enrollment, `crop_year`
    and `source`; a second reports `ERR_DUPLICATE_DATA_PACKET`."

    PRD §3.6: "At most one non-rejected run may exist per enrollment and `crop_year`; a
    second reports `ERR_DUPLICATE_QUANTIFICATION_RUN`."

    Design: Corner/validations/uniqueness_rules_reject_duplicate_standard_baseline_packet_and_run
    """
    scenario.accepted_enrollment(standard_overrides={"telemetry_required": False})
    scenario.propose_baseline(BASELINE_HISTORICAL_DATA)

    # The incumbent proposal holds the (enrollment, method) key, so a repeat of the same
    # method is a duplicate rather than a supersession.
    validate_error(
        scenario.api.propose_baseline(
            scenario.enrollment_id,
            baseline_payload(scenario.enrollment_version, BASELINE_HISTORICAL_DATA),
            ADMIN_BASELINE_HEADERS,
        ),
        ERR_DUPLICATE_BASELINE,
        409,
    )
    baselines = scenario.baselines_of_enrollment()
    assert len(baselines) == 1
    assert baselines[0]["status"] == BASELINE_PROPOSED

    scenario.approve_baseline()
    scenario.passed_packet(source=EVIDENCE_FARM_RECORD)
    run = scenario.create_run(METHOD_MODEL)
    assert_tonnes(run["net_removals_t"], 283.360)

    # Every rate field differs, yet the (practice_code, standard_version) pair is taken.
    validate_error(
        scenario.api.create_practice_standard(
            practice_standard_payload(
                additionality_lookback_years=4,
                max_prior_adoption_pct=15.00,
                min_documented_years=3,
                min_adoption_years=2,
                uncertainty_base_pct=12.00,
                sequestration_rate_per_acre=0.4000,
                modeled_baseline_rate_per_acre=0.2500,
                buffer_base_pct=12.00,
                effective_from="2021-01-01",
            ),
            ADMIN_HEADERS,
        ),
        ERR_DUPLICATE_STANDARD_VERSION,
        409,
    )

    # Neither reported_acres nor coverage_pct belongs to the packet key.
    validate_error(
        scenario.api.file_data_packet(
            scenario.enrollment_id,
            data_packet_payload(CROP_YEAR_2026, source=EVIDENCE_FARM_RECORD,
                                reported_acres=900.00, coverage_pct=88.00),
            ADMIN_HEADERS,
        ),
        ERR_DUPLICATE_DATA_PACKET,
        409,
    )

    telemetry = scenario.passed_packet(source=EVIDENCE_EQUIPMENT_TELEMETRY)
    assert telemetry["qc_status"] == QC_PASSED

    # The measurement input set is now non-empty and covers 92.00 per cent, so the run is
    # refused on the uniqueness rung rather than on data sufficiency: the key is
    # (enrollment, crop_year) and the differing method does not create a distinct row.
    validate_error(
        scenario.api.create_quantification_run(
            quantification_run_payload(
                scenario.enrollment_id, scenario.baseline_id, scenario.enrollment_version,
                CROP_YEAR_2026, METHOD_MEASUREMENT,
            ),
            ADMIN_HEADERS,
        ),
        ERR_DUPLICATE_QUANTIFICATION_RUN,
        409,
    )

    second_version = validate_success(
        scenario.api.create_practice_standard(
            practice_standard_payload(standard_version=2, telemetry_required=False),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert second_version["standard_version"] == 2

    farm_records, farm_meta = validate_paginated(
        scenario.api.list_data_packets(
            {"enrollment_id": scenario.enrollment_id, "source": EVIDENCE_FARM_RECORD},
            ADMIN_HEADERS,
        )
    )
    assert farm_meta["total_count"] == 1
    assert farm_records[0]["id"] == scenario.packets[0]["id"]

    _runs, run_meta = validate_paginated(
        scenario.api.list_quantification_runs(
            {"enrollment_id": scenario.enrollment_id}, ADMIN_HEADERS
        )
    )
    assert run_meta["total_count"] == 1


def test_one_packet_set_yields_three_different_sufficiency_verdicts(scenario):
    """A model run over farm records alone lacks telemetry, the same evidence measured is
    below the coverage floor, and the sample intensity floor is inclusive at 5.00 — while
    the model method itself never applies the coverage floor.

    PRD §3.6: "If the pinned standard's `telemetry_required` is true and no packet in the
    collection has a `source` of `EQUIPMENT_TELEMETRY`, the run is refused with
    `ERR_TELEMETRY_EVIDENCE_REQUIRED`."

    PRD §3.6: "`mean_coverage_pct` must then be at least 60.00, and a lower figure is
    refused with `ERR_COVERAGE_BELOW_MINIMUM`."

    PRD §2.10: "`sample_pct` must be at least 5.00 on both verification assignment and
    resampling, and a value below that floor reports `ERR_SAMPLE_TOO_SMALL`."

    Design: Corner/validations/data_sufficiency_gates_refuse_telemetry_coverage_and_sample_shortfalls
    """
    scenario.active_enrollment()
    farm_record = scenario.passed_packet(source=EVIDENCE_FARM_RECORD)
    assert_pct(farm_record["qc_score"], 88.00)

    # Packets exist, so the emptiness gate passes and the telemetry gate is what fails.
    validate_error(
        scenario.api.create_quantification_run(
            quantification_run_payload(
                scenario.enrollment_id, scenario.baseline_id, scenario.enrollment_version,
                CROP_YEAR_2026, METHOD_MODEL,
            ),
            ADMIN_HEADERS,
        ),
        ERR_TELEMETRY_EVIDENCE_REQUIRED,
        422,
    )

    thin = scenario.file_packet(source=EVIDENCE_EQUIPMENT_TELEMETRY, coverage_pct=55.00)
    assert_pct(thin["qc_score"], 77.50)
    assert thin["completeness_status"] == COMPLETENESS_PARTIAL
    passed_thin = scenario.qc_packet(thin["id"], "PASS")
    assert passed_thin["qc_status"] == QC_PASSED
    assert passed_thin["completeness_status"] == COMPLETENESS_PARTIAL

    # Measurement narrows to the telemetry packet alone, so the farm record's 92.00 cannot
    # lift the mean above the floor.
    validate_error(
        scenario.api.create_quantification_run(
            quantification_run_payload(
                scenario.enrollment_id, scenario.baseline_id, scenario.enrollment_version,
                CROP_YEAR_2026, METHOD_MEASUREMENT,
            ),
            ADMIN_HEADERS,
        ),
        ERR_COVERAGE_BELOW_MINIMUM,
        422,
    )

    run = validate_success(
        scenario.api.create_quantification_run(
            quantification_run_payload(
                scenario.enrollment_id, scenario.baseline_id, scenario.enrollment_version,
                CROP_YEAR_2026, METHOD_MODEL,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert run["packet_count"] == 2
    assert_pct(run["mean_coverage_pct"], 73.50)
    assert_acres(run["verified_acres"], 1000.00)
    assert_tonnes(run["gross_removals_t"], 257.250)
    assert_tonnes(run["net_removals_t"], 226.380)

    scenario.submit_run(run["id"])
    scenario.accredit_body(max_concurrent_visits=2)

    validate_error(
        scenario.api.create_verification(
            verification_payload(run["id"], scenario.body_id, sample_pct=4.00,
                                 site_visit_start="2026-07-01", site_visit_end="2026-07-03"),
            ADMIN_HEADERS,
        ),
        ERR_SAMPLE_TOO_SMALL,
        422,
    )

    commissioned = validate_success(
        scenario.api.create_verification(
            verification_payload(run["id"], scenario.body_id, sample_pct=5.00,
                                 site_visit_start="2026-07-01", site_visit_end="2026-07-03"),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert commissioned["opinion"] == OPINION_PENDING
    assert_pct(commissioned["sample_pct"], 5.00)


def test_the_workload_ceiling_is_checked_before_the_pending_verification_key(scenario):
    """Two requests violating the same pair of rules resolve differently on the strength of
    their visit windows alone: the overlapping one is a capacity refusal, the disjoint one a
    duplicate refusal.

    PRD §3.6: "Counting only that body's verifications whose `opinion` is still `PENDING`,
    count how many have a closed visit interval running from `site_visit_start` through
    `site_visit_end` inclusive that intersects the requested interval; two windows that
    merely share an endpoint day do intersect."

    PRD §3.6: "At most one verification with a pending opinion may exist per run; a second
    reports `ERR_DUPLICATE_VERIFICATION`."

    Design: Corner/validations/verifier_capacity_is_checked_before_verification_uniqueness
    """
    scenario.active_enrollment()
    scenario.passed_packet()
    run = scenario.create_run(METHOD_MODEL)
    assert_tonnes(run["net_removals_t"], 283.360)
    scenario.submit_run()
    scenario.accredit_body(max_concurrent_visits=1)
    incumbent = scenario.commission_verification(
        sample_pct=10.00, site_visit_start="2026-07-01", site_visit_end="2026-07-10"
    )

    # Sharing only the closing day still intersects, so the capacity rung fires first.
    validate_error(
        scenario.api.create_verification(
            verification_payload(scenario.run_id, scenario.body_id, sample_pct=12.00,
                                 site_visit_start="2026-07-10", site_visit_end="2026-07-20"),
            ADMIN_HEADERS,
        ),
        ERR_VERIFIER_CAPACITY_EXCEEDED,
        409,
    )

    # A disjoint window finds no intersecting pending visit, so the decision passes down to
    # the uniqueness rung — the same 409 status under a different code.
    validate_error(
        scenario.api.create_verification(
            verification_payload(scenario.run_id, scenario.body_id, sample_pct=12.00,
                                 site_visit_start="2026-09-01", site_visit_end="2026-09-05"),
            ADMIN_HEADERS,
        ),
        ERR_DUPLICATE_VERIFICATION,
        409,
    )

    rows, meta = validate_paginated(
        scenario.api.list_verifications({"quantification_run_id": scenario.run_id}, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == incumbent["id"]
    assert rows[0]["opinion"] == OPINION_PENDING


def test_one_revision_strands_a_verified_run_at_both_version_gated_sites(scenario):
    """A methodology revision leaves the pinned enrollment permanently out of step: the
    pending issuance and any later quantification are both refused, while the enrollment's
    pinned version and the verified run's figures stay exactly where they were.

    PRD §3.2: "A revision is a self-loop: the standard stays `ACTIVE`, its
    `standard_version` advances by exactly one, and every rate and threshold field on the
    row is left untouched."

    PRD §3.2: "No enrollment is rewritten, so an enrollment that pinned the earlier version
    now disagrees with its own standard — and from that moment its quantification and its
    issuance are refused with `ERR_STANDARD_VERSION_MISMATCH`, permanently."

    Design: Corner/validations/standard_revision_blocks_quantification_and_issuance_for_pinned_enrollments
    """
    scenario.verified_run(
        standard_overrides={"telemetry_required": False},
        packet_overrides={"source": EVIDENCE_FARM_RECORD},
    )
    assert scenario.run["status"] == RUN_VERIFIED
    # A positive opinion filed without a restatement carries a zero discrepancy, not 100.00.
    assert_pct(scenario.verification["material_discrepancy_pct"], 0.00)
    assert scenario.verification["restated_removals_t"] is None

    revised = validate_success(
        scenario.api.revise_practice_standard(
            scenario.standard_id,
            revision_payload(revision_note="2027 methodology update: revised soil factors"),
            ADMIN_HEADERS,
        ),
        200,
    )

    assert revised["standard_version"] == 2
    assert revised["status"] == STANDARD_ACTIVE
    assert_rate(revised["sequestration_rate_per_acre"], 0.3500)
    assert_pct(revised["buffer_base_pct"], 10.00)

    # The version gate guards issuance, not only run creation.
    validate_error(
        scenario.api.issue_credits(
            scenario.run_id, issue_payload(CROP_YEAR_2026), ADMIN_HEADERS
        ),
        ERR_STANDARD_VERSION_MISMATCH,
        409,
    )
    assert scenario.batches_of_run() == []

    scenario.set_clock(CLOCK_2027)

    # The 2027 crop year holds no packet at all, yet the version gate is reported instead of
    # any data-sufficiency complaint.
    validate_error(
        scenario.api.create_quantification_run(
            quantification_run_payload(
                scenario.enrollment_id, scenario.baseline_id, scenario.enrollment_version,
                CROP_YEAR_2027, METHOD_MODEL,
            ),
            ADMIN_HEADERS,
        ),
        ERR_STANDARD_VERSION_MISMATCH,
        409,
    )

    assert scenario.reload_enrollment()["pinned_standard_version"] == 1
    stranded = scenario.reload_run()
    assert stranded["status"] == RUN_VERIFIED
    assert_tonnes(stranded["net_removals_t"], 283.360)


def test_both_exit_clauses_share_one_code_and_a_denial_clears_the_request(scenario):
    """In its own first crop year no exit year is acceptable, a year later naming that same
    year is still refused, naming the year after is admitted, and a denial returns the row
    to active service with both exit fields blank.

    PRD §3.9: "Two independent temporal clauses both carry `ERR_EXIT_WINDOW_NOT_OPEN`: the
    `requested_exit_year` must be at least the current crop year plus one, so a mid-year
    request naming the current crop year is refused; and the current crop year minus the
    enrollment's `start_crop_year` must be at least one, so an enrollment cannot file an exit
    inside its own first crop year."

    PRD §3.9: "The `status` returns `EXIT_REQUESTED → ACTIVE`, the supplied
    `rejection_reason` is stored, and both `exit_reason` and `requested_exit_year` are
    cleared back to null."

    Design: Corner/validations/exit_window_requires_one_served_year_and_one_year_notice
    """
    scenario.active_enrollment()
    assert scenario.enrollment["status"] == ENROLLMENT_ACTIVE
    assert scenario.enrollment["start_crop_year"] == CROP_YEAR_2026

    # Clause (b): no year has yet been served, even though 2027 satisfies clause (a).
    validate_error(
        scenario.api.request_exit(
            scenario.enrollment_id,
            exit_request_payload(CROP_YEAR_2027, EXIT_VOLUNTARY),
            scenario.grower_auth,
        ),
        ERR_EXIT_WINDOW_NOT_OPEN,
        422,
    )

    scenario.set_clock(CLOCK_2027)

    # Clause (a): one year has now been served, but the notice period is not respected.
    validate_error(
        scenario.api.request_exit(
            scenario.enrollment_id,
            exit_request_payload(CROP_YEAR_2027, EXIT_VOLUNTARY),
            scenario.grower_auth,
        ),
        ERR_EXIT_WINDOW_NOT_OPEN,
        422,
    )
    assert scenario.reload_enrollment()["status"] == ENROLLMENT_ACTIVE

    requested = validate_success(
        scenario.api.request_exit(
            scenario.enrollment_id,
            exit_request_payload(2028, EXIT_LAND_SALE),
            scenario.grower_auth,
        ),
        200,
    )
    assert requested["status"] == ENROLLMENT_EXIT_REQUESTED
    assert requested["exit_reason"] == EXIT_LAND_SALE
    assert requested["requested_exit_year"] == 2028

    denied = validate_success(
        scenario.api.decide_exit(
            scenario.enrollment_id,
            exit_decision_payload("DENY", rejection_reason="commitment period still running"),
            ADMIN_HEADERS,
        ),
        200,
    )
    assert denied["status"] == ENROLLMENT_ACTIVE
    assert denied["rejection_reason"] == "commitment period still running"
    assert denied["exit_reason"] is None
    assert denied["requested_exit_year"] is None

    reread = scenario.reload_enrollment()
    assert reread["status"] == ENROLLMENT_ACTIVE
    assert reread["exit_reason"] is None
    assert reread["requested_exit_year"] is None


def test_a_superseding_batch_waits_for_its_predecessors_cancellation(scenario):
    """A 2027 re-issuance naming the 2026 batch is minted unlisted with its serial range
    continuing at 233, is refused the registry while the predecessor is still issued, and
    reaches the registry on the identical call once that predecessor has been cancelled.

    PRD §3.8: "A re-issued batch — one carrying a `supersedes_batch_id` — starts `UNLISTED`
    like any other and follows the same edge, but with one extra guard: the batch named by
    `supersedes_batch_id` must already have `issuance_status` of `CANCELLED`, and listing a
    superseding batch while its predecessor is still `ISSUED` is refused with
    `ERR_SUPERSEDED_BATCH_NOT_CANCELLED`."

    PRD §3.7: "`serial_start` is the buffer pool's current `next_serial_number`, and
    `serial_end` is `serial_start` plus `issued_credits` minus one, both inclusive."

    Design: Corner/validations/superseding_batch_cannot_be_listed_until_its_predecessor_is_cancelled
    """
    scenario.issued_batch(
        standard_overrides={"telemetry_required": False},
        packet_overrides={"source": EVIDENCE_FARM_RECORD},
    )
    first = scenario.batch
    assert first["serial_start"] == 1
    assert first["serial_end"] == 232

    scenario.set_clock(CLOCK_2027)
    scenario.passed_packet(CROP_YEAR_2027, source=EVIDENCE_FARM_RECORD)
    scenario.create_run(METHOD_MODEL, CROP_YEAR_2027)
    scenario.submit_run()
    scenario.commission_verification(
        site_visit_start="2027-09-01", site_visit_end="2027-09-05"
    )
    scenario.opine(OPINION_POSITIVE)
    assert scenario.reload_run()["status"] == RUN_VERIFIED

    second = scenario.issue(
        vintage_year=CROP_YEAR_2027, supersedes_batch_id=first["id"]
    )

    assert second["supersedes_batch_id"] == first["id"]
    assert second["registry_status"] == REGISTRY_UNLISTED
    assert second["issuance_status"] == ISSUANCE_ISSUED
    # The tier basis of 232 + 283 is still short of the MEDIUM floor of 1000 credits.
    assert second["risk_tier"] == RISK_TIER_HIGH
    assert_pct(second["buffer_pct"], 18.00)
    assert second["gross_credits"] == 283
    assert second["buffer_credits"] == 51
    assert second["issued_credits"] == 232
    assert second["serial_start"] == 233
    assert second["serial_end"] == 464

    validate_error(
        scenario.api.list_batch_on_registry(
            second["id"],
            registry_listing_payload(registry_account_ref="REG-ACCT-77"),
            REGISTRY_HEADERS,
        ),
        ERR_SUPERSEDED_BATCH_NOT_CANCELLED,
        409,
    )
    assert scenario.reload_batch(second["id"])["registry_status"] == REGISTRY_UNLISTED

    predecessor = scenario.reload_batch(first["id"])
    cancelled = validate_success(
        scenario.api.cancel_batch(
            first["id"],
            cancellation_payload(
                predecessor["version"],
                cancellation_reason="superseded by the 2027 re-issuance",
            ),
            REGISTRY_HEADERS,
        ),
        200,
    )
    assert cancelled["issuance_status"] == ISSUANCE_CANCELLED

    listed = validate_success(
        scenario.api.list_batch_on_registry(
            second["id"],
            registry_listing_payload(registry_account_ref="REG-ACCT-77"),
            REGISTRY_HEADERS,
        ),
        200,
    )
    assert listed["registry_status"] == REGISTRY_LISTED
    assert listed["registry_account_ref"] == "REG-ACCT-77"

    # The two axes moved independently: the predecessor was never on the registry.
    final = scenario.reload_batch(first["id"])
    assert final["issuance_status"] == ISSUANCE_CANCELLED
    assert final["registry_status"] == REGISTRY_UNLISTED


def test_one_reversal_blocks_four_later_operations_with_four_different_codes(scenario):
    """A cross-enrollment supersedes reference is refused on its own rung, and once the
    reversal against the listed batch is assessed the drained pool blocks retirement, the
    other enrollment's untouched payment, a repeat accrual and the second issuance, each
    with its own code.

    PRD §3.7: "When `supersedes_batch_id` is supplied it must name a batch belonging to the
    **same** enrollment, or the request is refused with `ERR_SUPERSEDED_BATCH_MISMATCH`."

    PRD §3.8: "Retirement is refused with `ERR_UNRESOLVED_REVERSAL` while any reversal event
    whose `status` is `REPORTED` or `ASSESSED` references the batch."

    PRD §3.9: "it is additionally refused with `ERR_CLAWBACK_OUTSTANDING` while the grower's
    `outstanding_clawback_cents` is above zero."

    PRD §2.12: "An issuance whose buffer contribution would still leave `balance_credits`
    below `required_reserve_credits` is refused with `ERR_BUFFER_POOL_DEFICIT`, and a pool
    already in `DEFICIT` refuses every issuance outright."

    Design: Corner/validations/settlement_preconditions_block_retire_pay_reaccrual_and_issuance_after_a_reversal
    """
    # Enrollment A: per-credit, issued for 2026 and placed on the registry.
    scenario.listed_batch(
        standard_overrides={"telemetry_required": False},
        packet_overrides={"source": EVIDENCE_FARM_RECORD},
    )
    enrollment_a = scenario.enrollment_id
    batch_a = scenario.batch["id"]
    assert scenario.batch["issued_credits"] == 232
    assert scenario.batch["registry_status"] == REGISTRY_LISTED
    payment_a = scenario.payments_of_enrollment(enrollment_a)[0]
    assert payment_a["net_amount_cents"] == 306240
    assert payment_a["status"] == PAYMENT_ACCRUED

    # Enrollment B: per-acre, verified for 2026 but never issued, with its own accrual.
    field_b = scenario.register_field(
        field_name="South Quarter", boundary_min_x=4000, boundary_min_y=0,
        boundary_max_x=6000, boundary_max_y=2000,
    )
    scenario.map_confirm(field_b["id"])
    scenario.file_reference_history(field_b["id"])
    scenario.create_per_acre_enrollment(field_b["id"])
    enrollment_b = scenario.enrollment_id
    scenario.submit_enrollment()
    scenario.screen_enrollment("ACCEPT")
    scenario.propose_baseline(BASELINE_HISTORICAL_DATA)
    scenario.approve_baseline()
    scenario.passed_packet(source=EVIDENCE_FARM_RECORD)
    scenario.create_run(METHOD_MODEL)
    run_b = scenario.run_id
    scenario.submit_run()
    scenario.commission_verification(
        site_visit_start="2026-10-01", site_visit_end="2026-10-05"
    )
    scenario.opine(OPINION_POSITIVE)
    assert scenario.reload_run()["status"] == RUN_VERIFIED
    payment_b = scenario.accrue_payment(CROP_YEAR_2026, enrollment_b)
    assert payment_b["net_amount_cents"] == 770000
    assert payment_b["status"] == PAYMENT_ACCRUED

    pool = scenario.buffer_pool()
    assert pool["balance_credits"] == 51
    assert pool["outstanding_issued_credits"] == 232
    assert pool["required_reserve_credits"] == 12
    assert pool["pool_status"] == POOL_HEALTHY

    # Rung 20: batch A belongs to enrollment A, not to the run being issued.
    validate_error(
        scenario.api.issue_credits(
            run_b, issue_payload(CROP_YEAR_2026, supersedes_batch_id=batch_a),
            ADMIN_HEADERS,
        ),
        ERR_SUPERSEDED_BATCH_MISMATCH,
        422,
    )
    assert scenario.batches_of_run(run_b) == []

    reported = validate_success(
        scenario.api.create_reversal_event(
            reversal_payload(batch_a, 478.00, CROP_YEAR_2026, REVERSAL_UNINTENTIONAL),
            ADMIN_REVERSAL_REPORTER_HEADERS,
        ),
        201,
    )
    assert reported["status"] == REVERSAL_REPORTED
    assert reported["affected_credits"] == 0
    assert reported["buffer_draw_credits"] == 0
    assert reported["unbacked_credits"] == 0
    assert reported["grower_clawback_cents"] == 0

    # Still LISTED and ISSUED, so this is the settlement rung and not the state rung.
    validate_error(
        scenario.api.retire_batch(
            batch_a, retirement_payload(retirement_beneficiary="Northwind Airlines"),
            REGISTRY_HEADERS,
        ),
        ERR_UNRESOLVED_REVERSAL,
        409,
    )
    assert scenario.reload_batch(batch_a)["registry_status"] == REGISTRY_LISTED

    assessed = validate_success(
        scenario.api.assess_reversal(reported["id"], None, ADMIN_REVERSAL_ASSESSOR_HEADERS),
        200,
    )
    assert assessed["status"] == REVERSAL_ASSESSED
    assert assessed["affected_credits"] == 111
    assert assessed["buffer_draw_credits"] == 51
    assert assessed["unbacked_credits"] == 60
    # 60 unbacked credits at 2750 cents, taken at the 60.00 per-credit share.
    assert assessed["grower_clawback_cents"] == 99000

    drained = scenario.buffer_pool()
    assert drained["balance_credits"] == 0
    assert drained["drawn_total"] == 51
    assert drained["unbacked_reversal_credits"] == 60
    assert drained["required_reserve_credits"] == 12
    assert drained["pool_status"] == POOL_DEFICIT

    suspended = scenario.reload_batch(batch_a)
    assert suspended["registry_status"] == REGISTRY_SUSPENDED
    assert suspended["issuance_status"] == ISSUANCE_ISSUED

    breached = scenario.reload_enrollment(enrollment_a)
    assert breached["permanence_status"] == PERMANENCE_BREACHED
    assert breached["status"] == ENROLLMENT_ACTIVE

    clawed = scenario.payments_of_enrollment(enrollment_a)
    assert len(clawed) == 1
    assert clawed[0]["status"] == PAYMENT_CLAWED_BACK

    grower = scenario.reload_grower()
    assert grower["outstanding_clawback_cents"] == 99000
    assert grower["reversal_count"] == 1
    # 99000 cents is below the 250000 suspension threshold.
    assert grower["status"] == GROWER_ACTIVE

    # Enrollment B never held a batch, so its own permanence is intact and its payment is
    # untouched — yet the grower-level clawback still refuses settlement.
    intact = scenario.reload_enrollment(enrollment_b)
    assert intact["permanence_status"] == PERMANENCE_IN_COMPLIANCE
    assert scenario.payments_of_enrollment(enrollment_b)[0]["status"] == PAYMENT_ACCRUED
    validate_error(
        scenario.api.pay_grower_payment(payment_b["id"], None, ADMIN_HEADERS),
        ERR_CLAWBACK_OUTSTANDING,
        409,
    )

    validate_error(
        scenario.api.accrue_payment(
            enrollment_b, accrual_payload(CROP_YEAR_2026), ADMIN_HEADERS
        ),
        ERR_DUPLICATE_PAYMENT,
        409,
    )

    validate_error(
        scenario.api.issue_credits(run_b, issue_payload(CROP_YEAR_2026), ADMIN_HEADERS),
        ERR_BUFFER_POOL_DEFICIT,
        409,
    )
    assert scenario.batches_of_run(run_b) == []

    ledger = get_success_data(
        scenario.api.get_grower_ledger_summary(scenario.grower_id, ADMIN_HEADERS)
    )
    assert ledger["lifetime_credits_issued"] == 232
    assert ledger["buffer_contributed_credits"] == 51
    assert ledger["accrued_total_cents"] == 770000
    assert ledger["clawed_back_total_cents"] == 306240
    assert ledger["paid_total_cents"] == 0
    assert ledger["outstanding_clawback_cents"] == 99000
