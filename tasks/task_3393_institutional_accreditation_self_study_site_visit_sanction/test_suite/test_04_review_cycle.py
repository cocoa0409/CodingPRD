"""Review cycle lifecycle: open-cycle gate, sub-resource gates, CDR assessment, OCC."""
from test_helpers import (
    ApiErrorId,
    CDR_RATES_BOUNDARY_DEFICIENT,
    advance_cycle,
    assemble_review_team,
    create_candidate_institution,
    create_review_cycle,
    get_review_cycle,
    record_federal_compliance,
    register_team_pool,
    review_cycle_payload,
    set_logical_clock,
    setup_argument_draft,
    setup_cycle_materials_open,
    setup_decided_cycle,
    setup_submitted_argument,
    submit_argument,
    team_assembly_payload,
    validate_error,
    validate_success,
)


def test_second_open_cycle_for_same_institution_rejected(api, staff_headers):
    """PRD section 3.3: "At most one cycle per institution may be open at a time — creating a cycle while another cycle of the same institution holds any `status` other than `CLOSED` is rejected with `ERR_CYCLE_ALREADY_OPEN` (HTTP 409)."

    Design: Corner/state_machines/second_open_cycle_blocked_for_same_institution
    """
    set_logical_clock()
    ctx = create_candidate_institution()
    institution_id = ctx["institution"]["id"]
    create_review_cycle(institution_id)

    response = api.create_review_cycle(
        institution_id, review_cycle_payload(), staff_headers
    )
    validate_error(response, ApiErrorId.ERR_CYCLE_ALREADY_OPEN)


def test_cycle_advance_blocked_until_argument_submitted(api, staff_headers):
    """PRD section 3.3: "Three steps are gated on sub-resources, and each gate failure surfaces `ERR_CYCLE_PREREQUISITE_NOT_MET` (HTTP 409): moving from `MATERIALS_OPEN` to `EVALUATION_ACTIVE` requires an assurance argument of this cycle in `SUBMITTED` or `REVIEW_LOCKED`; moving from `EVALUATION_ACTIVE` to `VISIT_COMPLETE` requires a review team of this cycle in `REPORT_FILED`; and moving from `VISIT_COMPLETE` to `PANEL_REVIEW` requires a decision panel of this cycle in `CONVENED`."

    Design: Difficulty/cross_entity_state_dependency/cycle_advance_gated_on_argument_submission
    """
    ctx = setup_argument_draft()
    cycle_id = ctx["cycle"]["id"]
    institution_id = ctx["institution"]["id"]

    blocked = api.advance_review_cycle(cycle_id, {}, staff_headers)
    validate_error(blocked, ApiErrorId.ERR_CYCLE_PREREQUISITE_NOT_MET)

    submit_argument(ctx["argument"]["id"], institution_id)
    advanced = api.advance_review_cycle(cycle_id, {}, staff_headers)
    assert validate_success(advanced)["status"] == "EVALUATION_ACTIVE"


def test_cdr_three_year_boundary_is_inclusive(api):
    """PRD section 3.3: "The assessment reads the rates chronologically: the cycle is `DEFICIENT` if any single rate is 40.0 or greater, or if three rates were provided and all three are 30.0 or greater — both boundaries are inclusive, so exactly 40.0 triggers the single-year rule and exactly 30.0 counts toward the three-year rule."

    Design: Corner/calculations/cdr_three_consecutive_years_boundary
    """
    ctx = setup_cycle_materials_open()
    cycle_id = ctx["cycle"]["id"]

    deficient = record_federal_compliance(
        cycle_id, cohort_default_rates=CDR_RATES_BOUNDARY_DEFICIENT
    )
    assert deficient["federal_compliance_status"] == "DEFICIENT"

    compliant = record_federal_compliance(
        cycle_id, cohort_default_rates=[30.0, 30.0, 29.9]
    )
    assert compliant["federal_compliance_status"] == "COMPLIANT"


def test_cdr_single_year_rule_triggers_at_forty(api):
    """PRD section 3.3: "The assessment reads the rates chronologically: the cycle is `DEFICIENT` if any single rate is 40.0 or greater, or if three rates were provided and all three are 30.0 or greater — both boundaries are inclusive, so exactly 40.0 triggers the single-year rule and exactly 30.0 counts toward the three-year rule."

    Design: Corner/calculations/cdr_single_year_immediate_rule
    """
    ctx = setup_cycle_materials_open()
    cycle_id = ctx["cycle"]["id"]

    compliant = record_federal_compliance(cycle_id, cohort_default_rates=[12.0, 39.9])
    assert compliant["federal_compliance_status"] == "COMPLIANT"

    deficient = record_federal_compliance(cycle_id, cohort_default_rates=[12.0, 40.0])
    assert deficient["federal_compliance_status"] == "DEFICIENT"


def test_decided_cycle_waits_for_effective_outcome(api, staff_headers):
    """PRD section 3.3: "The final step from `DECIDED` into `CLOSED` requires the action outcome created by the deciding panel to have reached `EFFECTIVE`, again failing with `ERR_CYCLE_PREREQUISITE_NOT_MET` otherwise."

    Design: Corner/state_machines/decided_cycle_advance_blocked_until_outcome_effective
    """
    ctx = setup_decided_cycle()
    cycle_id = ctx["cycle"]["id"]
    outcome_id = ctx["outcome"]["id"]

    drafted = api.advance_review_cycle(cycle_id, {}, staff_headers)
    validate_error(drafted, ApiErrorId.ERR_CYCLE_PREREQUISITE_NOT_MET)

    api.advance_action_outcome(outcome_id, {}, staff_headers)
    disclosed = api.advance_review_cycle(cycle_id, {}, staff_headers)
    validate_error(disclosed, ApiErrorId.ERR_CYCLE_PREREQUISITE_NOT_MET)

    api.advance_action_outcome(outcome_id, {}, staff_headers)
    closed = api.advance_review_cycle(cycle_id, {}, staff_headers)
    assert validate_success(closed)["status"] == "CLOSED"


def test_team_assembly_with_stale_cycle_version_rejected(api, staff_headers):
    """PRD section 2.7: "The team assembly endpoint, `POST /accreditation/review-cycles/{id}/review-teams`, likewise requires `expected_review_cycle_version`, carrying the `version` of the cycle the client last observed — the cycle's version advances on every cycle mutation, including advance steps, federal-compliance recording, and earlier team assemblies."
    PRD section 2.7: "In both cases, if the supplied value does not equal the parent resource's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412): the client holds a stale view and must re-read the resource before writing, which prevents it from overwriting changes it has not observed."

    Design: Corner/cross_cutting_complexity_layers/occ_team_assembly_stale_cycle_version_rejected
    """
    ctx = setup_submitted_argument()
    cycle_id = ctx["cycle"]["id"]
    stale_version = ctx["cycle"]["version"]

    record_federal_compliance(cycle_id)
    register_team_pool()

    stale = api.assemble_review_team(
        cycle_id, team_assembly_payload(stale_version), staff_headers
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh_version = get_review_cycle(cycle_id)["version"]
    assert fresh_version == stale_version + 1

    assembled = api.assemble_review_team(
        cycle_id, team_assembly_payload(fresh_version), staff_headers
    )
    team = validate_success(assembled, 201)
    assert team["status"] == "PROPOSED"
    assert team["review_cycle_id"] == cycle_id
