"""Declared initial states, absorbing terminal states and the cascades between them.

Every entity opens in the state §1.2 declares for it, the screening conversation may
loop as often as the evidence demands, retirement and rejection are absorbing, quality
control is not replayable, and a grower suspension moves three rows at once while
leaving every read untouched.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_GROWER_SUSPENDED,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PRACTICE_STANDARD_RETIRED,
)
from test_helpers.assertions import (
    assert_acres,
    assert_pct,
    assert_tonnes,
    assert_version_unchanged,
)
from test_helpers.constants import (
    BASELINE_HISTORICAL_DATA,
    BASELINE_PROPOSED,
    BASELINE_REJECTED,
    CLOCK_2026,
    COMPLETENESS_COMPLETE,
    CROP_YEAR_2026,
    ENROLLMENT_ACCEPTED,
    ENROLLMENT_ACTIVE,
    ENROLLMENT_DRAFT,
    ENROLLMENT_INFO_REQUESTED,
    ENROLLMENT_SCREENING,
    ENROLLMENT_SUSPENDED,
    FIELD_DRAFT,
    FIELD_ENROLLED,
    FIELD_MAPPED,
    FIELD_SUSPENDED,
    GROWER_ACTIVE,
    GROWER_SUSPENDED,
    METHOD_MODEL,
    PERMANENCE_IN_COMPLIANCE,
    PERMANENCE_NOT_STARTED,
    QC_PASSED,
    QC_PENDING,
    RUN_DRAFT,
    SOIL_CLAY,
    STANDARD_RETIRED,
)
from test_helpers.factories import (
    baseline_payload,
    baseline_rejection_payload,
    boundary_payload,
    data_packet_payload,
    enrollment_payload,
    field_payload,
    qc_payload,
    quantification_run_payload,
    request_info_payload,
    revision_payload,
    screen_payload,
    suspend_grower_payload,
)
from test_helpers.test_users import (
    ADMIN_BASELINE_ALT_HEADERS,
    ADMIN_BASELINE_HEADERS,
    ADMIN_HEADERS,
    ADMIN_SCREENER_HEADERS,
)


def test_creation_opens_every_row_in_its_declared_initial_state(scenario):
    """A field, an enrollment, a baseline, a data packet and a quantification run each
    open in their declared initial state, with the derived figures already computed and
    with nothing short-circuiting into a later state.

    PRD §3.1: "A field's `status` begins at `DRAFT` with a null `surveyor_reference`, and
    it may take the values `DRAFT`, `MAPPED`, `ENROLLED` and `SUSPENDED`."

    PRD §3.3: "The enrollment begins with `status` of `DRAFT` and `permanence_status` of
    `NOT_STARTED`, and its `prior_adoption_pct`, `additionality_score` and
    `documented_years` are all null until screening computes them."

    PRD §3.4: "A proposal starts with `status` of `PROPOSED`, a null
    `approved_by_admin_id` and a null `rejection_note`, and proposing one increments the
    parent enrollment's `version`."

    PRD §3.5: "The quality axis, `qc_status`, takes the values `PENDING`, `PASSED`,
    `FLAGGED` and `REJECTED`; it starts at `PENDING` and moves only through explicit
    quality-control actions."

    PRD §3.6: "A new run starts with `status` of `DRAFT` and `revision_count` of 0, and
    creating it increments the parent enrollment's `version`."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    scenario.set_clock(CLOCK_2026)
    scenario.publish_standard()
    scenario.create_grower()

    field = validate_success(
        scenario.api.create_field(scenario.grower_id, field_payload(), ADMIN_HEADERS), 201
    )

    assert field["status"] == FIELD_DRAFT
    assert field["surveyor_reference"] is None

    scenario.map_confirm(field["id"])
    scenario.file_reference_history(field["id"])

    enrollment = validate_success(
        scenario.api.create_enrollment(
            enrollment_payload(field["id"], scenario.standard_id), ADMIN_HEADERS
        ),
        201,
    )

    assert enrollment["status"] == ENROLLMENT_DRAFT
    assert enrollment["permanence_status"] == PERMANENCE_NOT_STARTED
    assert enrollment["additionality_score"] is None

    scenario.submit_enrollment(enrollment["id"])
    scenario.screen_enrollment("ACCEPT")

    baseline = validate_success(
        scenario.api.propose_baseline(
            enrollment["id"],
            baseline_payload(scenario.enrollment_version, BASELINE_HISTORICAL_DATA),
            ADMIN_BASELINE_HEADERS,
        ),
        201,
    )

    assert baseline["status"] == BASELINE_PROPOSED
    assert baseline["approved_by_admin_id"] is None
    assert baseline["rejection_note"] is None
    # The counterfactual is computed on the proposal itself, not on approval.
    assert_tonnes(baseline["baseline_emissions_t"], 145.000)
    assert_pct(baseline["uncertainty_pct"], 7.00)

    scenario.approve_baseline(baseline["id"])

    packet = validate_success(
        scenario.api.file_data_packet(
            enrollment["id"], data_packet_payload(CROP_YEAR_2026), ADMIN_HEADERS
        ),
        201,
    )

    # The two axes are set independently on the same create: quality opens PENDING while
    # coverage is already derived from the reported 92.00 per cent.
    assert packet["qc_status"] == QC_PENDING
    assert packet["completeness_status"] == COMPLETENESS_COMPLETE
    assert_pct(packet["qc_score"], 96.00)

    scenario.qc_packet(packet["id"], "PASS")

    run = validate_success(
        scenario.api.create_quantification_run(
            quantification_run_payload(
                enrollment["id"], baseline["id"], scenario.enrollment_version,
                CROP_YEAR_2026, METHOD_MODEL,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )

    assert run["status"] == RUN_DRAFT
    assert run["revision_count"] == 0
    assert_tonnes(run["gross_removals_t"], 322.000)
    assert_tonnes(run["net_removals_t"], 283.360)
    # Creation does not auto-submit: the read-back is still a draft.
    reread = get_success_data(scenario.api.get_quantification_run(run["id"], ADMIN_HEADERS))
    assert reread["status"] == RUN_DRAFT


def test_screening_loops_through_info_requested_twice_and_still_accepts(scenario):
    """The screening conversation walks SCREENING → INFO_REQUESTED → SCREENING twice,
    refuses adjudication while the row sits with the applicant, bumps the version on
    every hop, and accepts afterwards on the recomputed score.

    PRD §3.3: "Resubmission — available to programme staff and to the owning grower under
    the same ownership rule and the same requirement that the grower be `ACTIVE` —
    requires the enrollment to be in `INFO_REQUESTED`, re-runs the entire computation
    above against the historical records **as they now stand**, overwrites
    `prior_adoption_pct`, `additionality_score` and `documented_years` with the new
    figures, clears `missing_items` back to null, re-applies both additionality gates,
    and moves the enrollment `INFO_REQUESTED → SCREENING`."

    PRD §3.3: "A `ProgramAdmin` records a `decision` on an enrollment in `SCREENING`, and
    in **both** branches the acting `X-User-ID` is recorded as
    `screening_decision_admin_id`."

    Design: Corner/state_machines/screening_can_loop_through_info_requested_and_back
    """
    scenario.set_clock(CLOCK_2026)
    scenario.publish_standard()
    scenario.create_grower()
    scenario.mapped_field()
    scenario.file_reference_history()
    scenario.create_enrollment()

    submitted = scenario.submit_enrollment()
    assert submitted["status"] == ENROLLMENT_SCREENING

    first_return = get_success_data(
        scenario.api.request_info_enrollment(
            scenario.enrollment_id,
            request_info_payload(["2023 tillage receipts"]),
            ADMIN_HEADERS,
        )
    )

    assert first_return["status"] == ENROLLMENT_INFO_REQUESTED
    assert first_return["missing_items"] == ["2023 tillage receipts"]

    blocked = scenario.api.screen_enrollment(
        scenario.enrollment_id, screen_payload("ACCEPT"), ADMIN_SCREENER_HEADERS
    )
    validate_error(blocked, ERR_INVALID_STATE_TRANSITION, 409)
    assert scenario.reload_enrollment()["status"] == ENROLLMENT_INFO_REQUESTED

    first_resubmit = get_success_data(
        scenario.api.resubmit_enrollment(scenario.enrollment_id, None, scenario.grower_auth)
    )

    # The loop returns to SCREENING, not to DRAFT, and the request is cleared.
    assert first_resubmit["status"] == ENROLLMENT_SCREENING
    assert first_resubmit["missing_items"] is None

    second_return = get_success_data(
        scenario.api.request_info_enrollment(
            scenario.enrollment_id,
            request_info_payload(["2024 telemetry export"]),
            ADMIN_HEADERS,
        )
    )
    assert second_return["status"] == ENROLLMENT_INFO_REQUESTED

    second_resubmit = get_success_data(
        scenario.api.resubmit_enrollment(scenario.enrollment_id, None, ADMIN_HEADERS)
    )
    assert second_resubmit["status"] == ENROLLMENT_SCREENING

    accepted = get_success_data(
        scenario.api.screen_enrollment(
            scenario.enrollment_id, screen_payload("ACCEPT"), ADMIN_SCREENER_HEADERS
        )
    )

    assert accepted["status"] == ENROLLMENT_ACCEPTED
    assert_pct(accepted["additionality_score"], 92.00)
    assert accepted["documented_years"] == 5
    assert (
        submitted["version"]
        < first_return["version"]
        < first_resubmit["version"]
        < second_return["version"]
        < second_resubmit["version"]
        < accepted["version"]
    )


def test_retired_methodology_is_absorbing_and_bars_a_new_enrollment(scenario):
    """Retirement is terminal: a second retire and a revise are both refused as invalid
    transitions, an enrollment naming the retired standard earns the availability error
    rather than a not-found, and the row still reads back.

    PRD §3.2: "A published standard has `status` of `ACTIVE` and may become `RETIRED`,
    which is terminal."

    PRD §3.2: "An enrollment may not cite a `RETIRED` standard, and it may not cite a
    standard whose `effective_from` falls in a calendar year later than the enrollment's
    `start_crop_year`; either fault is refused with `ERR_PRACTICE_STANDARD_RETIRED`, and
    the same check is re-applied at submission and resubmission, not only at creation."

    Design: Corner/state_machines/retired_practice_standard_is_terminal_and_refuses_new_enrollment
    """
    scenario.set_clock(CLOCK_2026)
    scenario.publish_standard()
    scenario.create_grower()
    scenario.mapped_field()

    retired = get_success_data(
        scenario.api.retire_practice_standard(scenario.standard_id, None, ADMIN_HEADERS)
    )
    assert retired["status"] == STANDARD_RETIRED

    validate_error(
        scenario.api.retire_practice_standard(scenario.standard_id, None, ADMIN_HEADERS),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )
    validate_error(
        scenario.api.revise_practice_standard(
            scenario.standard_id, revision_payload(), ADMIN_HEADERS
        ),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )
    validate_error(
        scenario.api.create_enrollment(
            enrollment_payload(scenario.field_id, scenario.standard_id), ADMIN_HEADERS
        ),
        ERR_PRACTICE_STANDARD_RETIRED,
        409,
    )

    # Retirement is a state, not a delete, and the refused revision left the version alone.
    reread = get_success_data(
        scenario.api.get_practice_standard(scenario.standard_id, ADMIN_HEADERS)
    )
    assert reread["status"] == STANDARD_RETIRED
    assert reread["standard_version"] == 1
    assert_version_unchanged(retired, reread)


def test_quality_control_cannot_be_replayed_on_a_passed_packet(scenario):
    """Quality control is not idempotent: replaying PASS is refused, a FLAG cannot walk the
    quality axis backwards out of PASSED, and neither refusal moves the packet's version.

    PRD §3.5: "A `ProgramAdmin` records a `decision` against a packet whose `qc_status` is
    `PENDING`."

    PRD §3.5: "A `decision` of `FLAG` requires a `flag_reason` in the payload, stores it,
    and moves `qc_status` from `PENDING` to `FLAGGED`."

    Design: Corner/state_machines/second_qc_decision_on_a_passed_packet_is_rejected
    """
    scenario.active_enrollment()
    packet = scenario.file_packet()

    passed = scenario.qc_packet(packet["id"], "PASS")

    assert passed["qc_status"] == QC_PASSED
    assert_pct(passed["qc_score"], 96.00)

    validate_error(
        scenario.api.qc_data_packet(packet["id"], qc_payload("PASS"), ADMIN_HEADERS),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )
    validate_error(
        scenario.api.qc_data_packet(packet["id"], qc_payload("FLAG"), ADMIN_HEADERS),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )

    reread = get_success_data(scenario.api.get_data_packet(packet["id"], ADMIN_HEADERS))
    assert reread["qc_status"] == QC_PASSED
    assert reread["completeness_status"] == COMPLETENESS_COMPLETE
    assert reread["flag_reason"] is None
    assert_version_unchanged(passed, reread)


def test_grower_suspension_cascades_two_hops_and_blocks_writes_only(scenario):
    """One suspension moves the grower, its active enrollment and that enrollment's
    enrolled field, refuses every grower-scoped write while leaving reads working, and
    reinstatement restores the pre-suspension states rather than the initial ones.

    PRD §3.1: "Suspension then cascades in two hops: first, every enrollment of that
    grower whose `status` is `ACTIVE` moves to `SUSPENDED`; second, *because* those
    enrollments moved, each of their fields whose `status` is `ENROLLED` moves to
    `SUSPENDED`."

    PRD §2.10: "A suspended grower may still read everything it could read before, but
    every write touching that grower's fields, enrollments, data packets and exit requests
    is refused."

    Design: Corner/state_machines/grower_suspension_cascades_to_field_and_enrollment_and_blocks_writes
    """
    scenario.active_enrollment()

    suspended = get_success_data(
        scenario.api.suspend_grower(
            scenario.grower_id,
            suspend_grower_payload(suspension_reason="audit hold"),
            ADMIN_HEADERS,
        )
    )

    assert suspended["status"] == GROWER_SUSPENDED
    assert suspended["suspension_reason"] == "audit hold"
    # Neither hop touches the acreage ledger.
    assert_acres(suspended["total_enrolled_acres"], 1000.00)

    # Both reads still work, and both rows cascaded from their live states.
    field = scenario.reload_field()
    enrollment = scenario.reload_enrollment()
    assert field["status"] == FIELD_SUSPENDED
    assert enrollment["status"] == ENROLLMENT_SUSPENDED
    assert enrollment["permanence_status"] == PERMANENCE_IN_COMPLIANCE

    # The grower-standing rung wins over the invalid-state error the SUSPENDED
    # enrollment would also earn.
    validate_error(
        scenario.api.file_data_packet(
            scenario.enrollment_id, data_packet_payload(CROP_YEAR_2026), ADMIN_HEADERS
        ),
        ERR_GROWER_SUSPENDED,
        409,
    )
    validate_error(
        scenario.api.create_field(
            scenario.grower_id,
            boundary_payload(3000, 3000, 4000, 4000, gross_acres=250.00, soil_group=SOIL_CLAY),
            ADMIN_HEADERS,
        ),
        ERR_GROWER_SUSPENDED,
        409,
    )

    fields, meta = validate_paginated(
        scenario.api.list_fields({"grower_id": scenario.grower_id}, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1
    assert len(fields) == 1

    reinstated = get_success_data(
        scenario.api.reinstate_grower(scenario.grower_id, None, ADMIN_HEADERS)
    )

    assert reinstated["status"] == GROWER_ACTIVE
    assert reinstated["suspension_reason"] is None
    assert scenario.reload_field()["status"] == FIELD_ENROLLED
    assert scenario.reload_enrollment()["status"] == ENROLLMENT_ACTIVE


def test_baseline_rejection_is_terminal_and_fires_no_cascade(scenario):
    """Rejecting a baseline preserves its figures, leaves the enrollment ACCEPTED and the
    field MAPPED, adds no acreage to the grower, blocks quantification, and cannot be
    walked back by a later approval even from a different administrator.

    PRD §3.4: "A `ProgramAdmin` rejecting a `PROPOSED` baseline supplies a
    `rejection_note`, which is stored, and the baseline moves `PROPOSED → REJECTED`."

    PRD §3.4: "No cascade fires: the enrollment stays `ACCEPTED` so that a fresh baseline
    can be proposed, the field stays `MAPPED`, and no acreage is added to the grower."

    Design: Corner/state_machines/baseline_rejection_is_terminal_and_leaves_enrollment_in_accepted
    """
    scenario.accepted_enrollment()
    proposed = scenario.propose_baseline(BASELINE_HISTORICAL_DATA)

    rejected = get_success_data(
        scenario.api.reject_baseline(
            proposed["id"],
            baseline_rejection_payload(
                rejection_note="historical yield series not attributable"
            ),
            ADMIN_BASELINE_HEADERS,
        )
    )

    assert rejected["status"] == BASELINE_REJECTED
    assert rejected["rejection_note"] == "historical yield series not attributable"
    assert rejected["approved_by_admin_id"] is None
    # Only the status moves; the computed counterfactual is preserved.
    assert_tonnes(rejected["baseline_emissions_t"], 145.000)

    enrollment = scenario.reload_enrollment()
    assert enrollment["status"] == ENROLLMENT_ACCEPTED
    assert enrollment["permanence_status"] == PERMANENCE_NOT_STARTED
    assert scenario.reload_field()["status"] == FIELD_MAPPED
    assert_acres(scenario.reload_grower()["total_enrolled_acres"], 0.00)

    # Quantification needs an ACTIVE enrollment, and the rejection never activated it.
    validate_error(
        scenario.api.create_quantification_run(
            quantification_run_payload(
                scenario.enrollment_id, proposed["id"], enrollment["version"],
                CROP_YEAR_2026, METHOD_MODEL,
            ),
            ADMIN_HEADERS,
        ),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )

    # REJECTED is terminal, so the state rung answers before the duties rung even for an
    # administrator who never screened this enrollment.
    validate_error(
        scenario.api.approve_baseline(proposed["id"], None, ADMIN_BASELINE_ALT_HEADERS),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )
