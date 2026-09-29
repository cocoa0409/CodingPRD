"""Breadth probes over the declared endpoints.

The partial PATCH, the three-axis cross-reference on an evaluation, the derived
compliance rollup and the last action of a unit's life each get one probe.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    BASIS_INTERWELL,
    CAP_ADEQUATE,
    CAP_NOT_APPLICABLE,
    CLOSURE_STATE_ACTIVE,
    CLOSURE_STATE_CARE_COMPLETE,
    CLOSURE_STATE_CLOSURE_PLANNED,
    CLOSURE_STATE_POST_CLOSURE_CARE,
    DOC_SHA256_ALT,
    DOC_URI_ALT,
    FREQUENCY_SEMIANNUAL,
    GHOST_UUID,
    METHOD_CLOSURE_IN_PLACE,
    METHOD_NONPARAMETRIC,
    METHOD_PARAMETRIC,
    PHASE_DETECTION,
    POSTING_CLOSURE_PLAN,
    POSTING_STABILITY_ASSESSMENT,
    POSTURE_COMPLIANT,
    POSTURE_WATCH,
    STABILITY_ADEQUATE,
    TIMELINESS_ON_TIME,
    VERDICT_UNRESTRICTED,
    WELL_STATUS_DECOMMISSIONED,
)
from test_helpers.test_users import PUBLIC_VIEWER_HEADERS, UTILITY_ADMIN_HEADERS

FOUR_DOWNGRADIENT = ("DG-01", "DG-02", "DG-03", "DG-04")
DEAD_WELL_REASON = "Well abandoned after access road realignment"


def test_a_program_patch_overwrites_only_the_fields_it_carries(api):
    """A method-only PATCH must leave the window bounds the previous PATCH stored.

    PRD: A configuration change may supply any subset of four fields — `statistical_method`, either `PARAMETRIC_PREDICTION_INTERVAL` (the default) or `NONPARAMETRIC_PREDICTION_INTERVAL`; `comparison_basis`, either `INTERWELL` (the default) or `INTRAWELL`; and the two inclusive bounds on which sampling dates count as background data, `background_window_start_on` and `background_window_end_on`, where the start must not be later than the end. Only the fields actually supplied are overwritten; anything omitted keeps its current value.
    Design: Corner/endpoints/program_patch_updates_only_the_supplied_fields
    """
    world = fixtures.seed_unit(api, "IMP-0139")
    hydro = world["hydro_headers"]

    initial = fixtures.read_program(api, world["program_id"])
    assert initial["version"] == 1
    assert initial["statistical_method"] == METHOD_PARAMETRIC
    assert initial["comparison_basis"] == BASIS_INTERWELL
    assert initial["background_window_start_on"] is None
    assert initial["background_window_end_on"] is None

    configured = fixtures.configure_program(api, world["program_id"], hydro)
    assert configured["comparison_basis"] == BASIS_INTERWELL
    a.assert_date(
        configured["background_window_start_on"], "2025-01-01", "background_window_start_on"
    )
    a.assert_date(configured["background_window_end_on"], "2025-12-31", "background_window_end_on")
    assert configured["version"] == 2

    narrowed = validate_success(
        api.patch_program(
            world["program_id"], {"statistical_method": METHOD_NONPARAMETRIC}, hydro
        )
    )

    assert narrowed["statistical_method"] == METHOD_NONPARAMETRIC
    assert narrowed["version"] == 3
    assert narrowed["comparison_basis"] == BASIS_INTERWELL
    a.assert_date(
        narrowed["background_window_start_on"], "2025-01-01", "background_window_start_on"
    )
    a.assert_date(narrowed["background_window_end_on"], "2025-12-31", "background_window_end_on")

    reread = fixtures.read_program(api, world["program_id"])
    assert reread["version"] == 3
    assert reread["phase"] == PHASE_DETECTION
    assert reread["network_certified"] is False
    assert reread["unit_id"] == world["unit_id"]
    assert reread["id"] == world["unit"]["monitoring_program_id"]


def test_the_compliance_well_link_is_checked_on_existence_state_and_membership(api):
    """Four rejected links and one that resolves as far as the data-sufficiency check.

    PRD: the compliance well is a `CERTIFIED` well (a decommissioned well is `ERR_INVALID_WELL_STATE`) belonging to the program's own unit and carrying `well_role` `DOWNGRADIENT`; a well from another unit, or a background well used as a compliance well, is `ERR_RESULT_WELL_NOT_IN_PROGRAM` (HTTP 422).
    PRD: 7. Every referenced monitoring-family identifier exists, else `ERR_MONITORING_ENTITY_NOT_FOUND`.
    Design: Corner/endpoints/evaluation_compliance_well_must_be_a_downgradient_well_of_the_same_unit
    """
    world = fixtures.seed_unit(api, "IMP-0140")
    hydro = world["hydro_headers"]
    stats = world["stats_headers"]
    wells = fixtures.install_standard_network(
        api, world["unit_id"], hydro, ("BG-01",), FOUR_DOWNGRADIENT
    )
    fixtures.configure_program(api, world["program_id"], hydro)
    fixtures.certify_network(api, world["program_id"], hydro, "2025-01-05")
    dead = validate_success(
        api.decommission_well(
            wells["DG-04"]["id"], factories.decommission_payload("2026-07-01", DEAD_WELL_REASON), hydro
        )
    )
    assert dead["well_status"] == WELL_STATUS_DECOMMISSIONED

    other_unit = fixtures.create_unit(api, "IMP-0141")
    foreign_well = fixtures.install_well(api, other_unit["id"], hydro, "DG-01")

    program_id = world["program_id"]
    for code, well_id, expected in (
        ("EV-BG", wells["BG-01"]["id"], ApiErrorId.RESULT_WELL_NOT_IN_PROGRAM),
        ("EV-XUNIT", foreign_well["id"], ApiErrorId.RESULT_WELL_NOT_IN_PROGRAM),
        ("EV-GHOST", GHOST_UUID, ApiErrorId.MONITORING_ENTITY_NOT_FOUND),
        ("EV-DEAD", wells["DG-04"]["id"], ApiErrorId.INVALID_WELL_STATE),
        ("EV-OK", wells["DG-01"]["id"], ApiErrorId.INSUFFICIENT_BACKGROUND_DATA),
    ):
        response = api.create_statistical_evaluation(
            factories.evaluation_payload(program_id, well_id, code), stats
        )
        validate_error(response, expected.value)

    _, page = validate_paginated(api.list_statistical_evaluations(UTILITY_ADMIN_HEADERS))
    assert page["total_count"] == 0

    program = fixtures.read_program(api, program_id)
    assert program["downgradient_well_count"] == 3
    assert program["background_well_count"] == 1
    assert program["network_certified"] is True


def test_the_compliance_rollup_reads_costs_only_from_an_approved_plan(api):
    """The five plan-sourced fields are null while the plan is DRAFT and populated after approval.

    PRD: The four cost figures and the recommended method are taken from the unit's **approved** closure plan only; when the unit has no approved plan all five are null, and a plan still in draft or merely certified is not read.
    PRD: Nothing in it is cached; every field is re-derived at read time from the unit, its monitoring program and its closure plans.
    Design: Corner/endpoints/compliance_summary_re_derives_every_field_and_reads_only_the_approved_plan
    """
    world = fixtures.seed_unit(api, "IMP-0142")
    fixtures.file_stability(api, world, "2026-07-15")
    plan = fixtures.draft_plan(api, world, "CP-0142")

    before = validate_success(api.get_compliance_summary(world["unit_id"], PUBLIC_VIEWER_HEADERS))

    assert before["unit_id"] == world["unit_id"]
    assert before["unit_code"] == "IMP-0142"
    assert before["closure_state"] == CLOSURE_STATE_ACTIVE
    assert before["cap_integrity_state"] == CAP_NOT_APPLICABLE
    assert before["compliance_posture"] == POSTURE_WATCH
    for field in (
        "in_place_pv_usd_cents",
        "removal_pv_usd_cents",
        "in_place_nominal_usd_cents",
        "removal_nominal_usd_cents",
        "recommended_method",
    ):
        assert before[field] is None, f"{field} must be null while the only plan is DRAFT"
    assert before["monitoring_phase"] == PHASE_DETECTION
    assert before["sampling_frequency"] == FREQUENCY_SEMIANNUAL
    assert before["next_sampling_due_date"] is None
    assert before["open_ssi_count"] == 0
    assert before["overdue_posting_types"] == []
    a.assert_date(before["closure_deadline_date"], "2031-03-31", "closure_deadline_date")
    assert before["granted_extension_months"] == 0
    assert before["post_closure_care_end_date"] is None
    assert before["ash_in_place_tons"] == 480000
    assert before["late_posting_count"] == 0
    assert before["ash_mass_balance_ok"] is True

    fixtures.certify_plan_both_halves(api, world, plan["id"], "2026-08-01")
    fixtures.approve_plan(api, plan["id"], "2026-08-01", "PERMIT-2026-B")

    after = validate_success(api.get_compliance_summary(world["unit_id"], PUBLIC_VIEWER_HEADERS))

    assert after["compliance_posture"] == POSTURE_WATCH
    assert after["closure_state"] == CLOSURE_STATE_CLOSURE_PLANNED
    a.assert_cents(after["in_place_pv_usd_cents"], 119600444, "in_place_pv_usd_cents")
    a.assert_cents(after["removal_pv_usd_cents"], 919600444, "removal_pv_usd_cents")
    a.assert_cents(after["in_place_nominal_usd_cents"], 130000000, "in_place_nominal_usd_cents")
    a.assert_cents(after["removal_nominal_usd_cents"], 930000000, "removal_nominal_usd_cents")
    assert after["recommended_method"] == METHOD_CLOSURE_IN_PLACE

    unit = fixtures.read_unit(api, world["unit_id"])
    assert after["governing_stability_verdict"] == STABILITY_ADEQUATE
    assert after["governing_stability_verdict"] == unit["governing_stability_verdict"]
    assert after["location_restriction_verdict"] == VERDICT_UNRESTRICTED
    assert after["location_restriction_verdict"] == unit["location_restriction_verdict"]


def test_care_completion_is_refused_until_the_care_period_has_run_out(api):
    """The identical request is a 409 on day one of care and a 200 on the end date itself.

    PRD: the current date must be on or after `post_closure_care_end_date`, or the refusal is `ERR_CARE_PERIOD_NOT_ELAPSED` (HTTP 409). The date comparison is inclusive, so certification on the end date itself is permitted. Success moves the unit `POST_CLOSURE_CARE → CARE_COMPLETE` and recomputes posture. `CARE_COMPLETE` is terminal: no closure-state transition leads out of it, and every unit-scoped write is thereafter refused with `ERR_INVALID_UNIT_STATE`.
    Design: Corner/endpoints/care_completion_is_refused_until_the_care_period_has_elapsed
    """
    world = fixtures.seed_unit(api, "IMP-0143")
    fixtures.seed_post_closure_care(api, world, "2026-08-01", plan_code="CP-0143")
    fixtures.post_document(api, world, POSTING_STABILITY_ASSESSMENT, "2026-08-01")
    fixtures.post_document(
        api, world, POSTING_CLOSURE_PLAN, "2026-08-01", document_uri=DOC_URI_ALT,
        document_sha256=DOC_SHA256_ALT,
    )

    seeded = fixtures.read_unit(api, world["unit_id"])
    assert seeded["closure_state"] == CLOSURE_STATE_POST_CLOSURE_CARE
    assert seeded["cap_integrity_state"] == CAP_ADEQUATE
    a.assert_date(seeded["post_closure_care_start_on"], "2026-08-01", "post_closure_care_start_on")
    a.assert_date(seeded["post_closure_care_end_date"], "2056-08-01", "post_closure_care_end_date")
    assert seeded["closure_timeliness"] == TIMELINESS_ON_TIME
    assert seeded["compliance_posture"] == POSTURE_COMPLIANT

    too_early = api.certify_care_complete(world["unit_id"], None, world["civil_headers"])
    validate_error(too_early, ApiErrorId.CARE_PERIOD_NOT_ELAPSED.value)
    assert (
        fixtures.read_unit(api, world["unit_id"])["closure_state"]
        == CLOSURE_STATE_POST_CLOSURE_CARE
    )

    fixtures.set_clock(api, "2056-08-01T00:00:00Z")

    complete = validate_success(
        api.certify_care_complete(world["unit_id"], None, world["civil_headers"])
    )

    assert complete["closure_state"] == CLOSURE_STATE_CARE_COMPLETE
    a.assert_date(complete["post_closure_care_end_date"], "2056-08-01", "post_closure_care_end_date")
    assert complete["deficiency_extension_months"] == 0

    late_inspection = api.create_cap_inspection(
        factories.cap_inspection_payload(world["unit_id"], "2056-08-01"), world["civil_headers"]
    )
    validate_error(late_inspection, ApiErrorId.INVALID_UNIT_STATE.value)
    _, inspections = validate_paginated(
        api.list_cap_inspections(UTILITY_ADMIN_HEADERS, {"unit_id": world["unit_id"]})
    )
    assert inspections["total_count"] == 0
