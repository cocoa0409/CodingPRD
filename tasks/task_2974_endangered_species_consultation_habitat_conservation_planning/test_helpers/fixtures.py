"""Composite setup helpers that walk the consultation and permitting lifecycle.

Every helper builds its preconditions from scratch through PRD-declared endpoints,
because each test starts against an empty database.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    ACTION_COUNTY_CODE,
    biological_assessment_payload,
    conservation_bank_payload,
    critical_habitat_unit_payload,
    database_query_payload,
    field_survey_payload,
    habitat_conservation_plan_payload,
    funding_assurance_payload,
    incidental_take_permit_payload,
    plan_decision_payload,
    project_action_payload,
    proponent_payload,
    species_payload,
    threatened_species_payload,
)
from .test_users import (
    AGENCY_APPROVER_ID,
    AGENCY_ISSUER_ID,
    AGENCY_REGISTRAR_ID,
    TEST_USERS,
    anonymous_headers,
    make_proponent_headers,
)

CANONICAL_CLOCK = "2026-10-01T00:00:00Z"

REGISTRAR = TEST_USERS["agency_registrar_headers"]
REVIEWER = TEST_USERS["agency_reviewer_headers"]
ISSUER = TEST_USERS["agency_issuer_headers"]
APPROVER = TEST_USERS["agency_approver_headers"]
ADJUDICATOR = TEST_USERS["agency_adjudicator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

STAGES = (
    "registry",
    "proponent",
    "action",
    "determinations",
    "effect_determination",
    "ba_submitted",
    "opinion",
    "plan",
    "commitments",
    "funded",
    "submitted",
    "approved",
    "permit",
)


def _stage_index(stage):
    assert stage in STAGES, f"unknown fixture stage {stage!r}"
    return STAGES.index(stage)


def set_clock(to_iso8601, headers=None):
    """Move the logical clock, running any permit expiry cascade it triggers."""
    response = api_client.set_clock(to_iso8601, headers or REGISTRAR)
    get_success_data(response, 200)
    return to_iso8601


def register_species(**overrides):
    """Register one species as the wildlife agency."""
    return get_success_data(
        api_client.create_species(species_payload(**overrides), REGISTRAR), 201
    )


def register_threatened_species(**overrides):
    return get_success_data(
        api_client.create_species(threatened_species_payload(**overrides), REGISTRAR),
        201,
    )


def designate_critical_habitat_unit(species_id, **overrides):
    return get_success_data(
        api_client.create_critical_habitat_unit(
            species_id, critical_habitat_unit_payload(**overrides), REGISTRAR
        ),
        201,
    )


def establish_conservation_bank(species_id, **overrides):
    return get_success_data(
        api_client.create_conservation_bank(
            conservation_bank_payload(species_id, **overrides), REGISTRAR
        ),
        201,
    )


def register_proponent(**overrides):
    """Register a proponent through the one operation open to the anonymous caller."""
    return get_success_data(
        api_client.create_proponent(proponent_payload(**overrides), anonymous_headers()),
        201,
    )


def open_project_action(proponent, **overrides):
    """Register a project action owned by the given proponent."""
    headers = make_proponent_headers(proponent["id"])
    return get_success_data(
        api_client.create_project_action(
            project_action_payload(proponent["id"], **overrides), headers
        ),
        201,
    )


def record_field_survey(action, proponent, species_id, **overrides):
    headers = make_proponent_headers(proponent["id"])
    return get_success_data(
        api_client.create_presence_determination(
            action["id"], field_survey_payload(species_id, **overrides), headers
        ),
        201,
    )


def record_database_query(action, proponent, species_id, **overrides):
    headers = make_proponent_headers(proponent["id"])
    return get_success_data(
        api_client.create_presence_determination(
            action["id"], database_query_payload(species_id, **overrides), headers
        ),
        201,
    )


def run_effect_determination(action, proponent):
    headers = make_proponent_headers(proponent["id"])
    return get_success_data(
        api_client.run_effect_determination(action["id"], headers), 200
    )


def submit_biological_assessment(consultation_id, proponent, **overrides):
    headers = make_proponent_headers(proponent["id"])
    return get_success_data(
        api_client.submit_biological_assessment(
            consultation_id, biological_assessment_payload(**overrides), headers
        ),
        200,
    )


def issue_biological_opinion(consultation_id, payload=None, headers=None):
    return get_success_data(
        api_client.issue_biological_opinion(
            consultation_id, payload if payload is not None else {}, headers or ISSUER
        ),
        201,
    )


def read_plan(plan_id, headers=None):
    """Re-read a plan so a following write can carry its live version."""
    return get_success_data(
        api_client.get_habitat_conservation_plan(plan_id, headers or AUDITOR), 200
    )


def read_permit(permit_id, headers=None):
    """Re-read a permit so a following write can carry its live version."""
    return get_success_data(
        api_client.get_incidental_take_permit(permit_id, headers or AUDITOR), 200
    )


def read_bank(bank_id, headers=None):
    return get_success_data(
        api_client.get_conservation_bank(bank_id, headers or AUDITOR), 200
    )


def read_action(action_id, headers=None):
    return get_success_data(api_client.get_project_action(action_id, headers or AUDITOR), 200)


def read_consultation(consultation_id, headers=None):
    return get_success_data(
        api_client.get_consultation(consultation_id, headers or AUDITOR), 200
    )


def read_proponent(proponent_id, headers=None):
    return get_success_data(api_client.get_proponent(proponent_id, headers or AUDITOR), 200)


def add_commitment(plan_id, proponent, spec):
    """Add one mitigation commitment, reading the plan's live version first.

    Each commitment write bumps the plan version, so the guard is refreshed on
    every call rather than reused from an earlier read.
    """
    headers = make_proponent_headers(proponent["id"])
    plan = read_plan(plan_id, headers)
    payload = dict(spec)
    payload["expected_hcp_version"] = plan["version"]
    return get_success_data(
        api_client.create_mitigation_commitment(plan_id, payload, headers), 201
    )


def add_funding_assurance(plan_id, proponent, contribution_cents, **overrides):
    headers = make_proponent_headers(proponent["id"])
    return get_success_data(
        api_client.create_funding_assurance(
            plan_id, funding_assurance_payload(contribution_cents, **overrides), headers
        ),
        200,
    )


def fully_fund_plan(plan_id, proponent, **overrides):
    """Contribute exactly the plan's outstanding endowment requirement."""
    headers = make_proponent_headers(proponent["id"])
    plan = read_plan(plan_id, headers)
    outstanding = plan["endowment_required_cents"] - plan["endowment_secured_cents"]
    if outstanding <= 0:
        return plan
    return add_funding_assurance(plan_id, proponent, outstanding, **overrides)


def submit_plan(plan_id, proponent):
    headers = make_proponent_headers(proponent["id"])
    return get_success_data(api_client.submit_plan(plan_id, headers), 200)


def decide_plan(plan_id, decision="APPROVE", headers=None, **overrides):
    return get_success_data(
        api_client.decide_plan(
            plan_id, plan_decision_payload(decision, **overrides), headers or APPROVER
        ),
        200,
    )


def issue_permit(plan_id, headers=None, **overrides):
    return get_success_data(
        api_client.issue_incidental_take_permit(
            plan_id, incidental_take_permit_payload(**overrides), headers or ISSUER
        ),
        201,
    )


def file_monitoring_report(permit_id, proponent, **overrides):
    """File one monitoring report, refreshing the permit version guard first."""
    headers = make_proponent_headers(proponent["id"])
    permit = read_permit(permit_id, headers)
    payload = {
        "period_start": "2027-01-01",
        "period_end": "2027-04-01",
        "take_units_reported": 1.00,
        "mitigation_units_verified": 10.00,
    }
    payload.update(overrides)
    payload["expected_permit_version"] = permit["version"]
    return get_success_data(
        api_client.create_monitoring_report(permit_id, payload, headers), 201
    )


def adjudicate_report(report_id, decision="ACCEPT", headers=None, note=None):
    payload = {"decision": decision}
    payload["adjudication_note"] = note or "Take and mitigation figures reconcile."
    return get_success_data(
        api_client.adjudicate_monitoring_report(report_id, payload, headers or ADJUDICATOR),
        200,
    )


def report_circumstance(plan_id, proponent, **overrides):
    headers = make_proponent_headers(proponent["id"])
    payload = {
        "circumstance_type": "CHANGED",
        "description": "Multi-year drought reduced forage cover on the mitigation site.",
        "response_cost_cents": 500_000,
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_changed_circumstance_event(plan_id, payload, headers), 201
    )


def respond_to_circumstance(event_id, proponent, contributed_cents, note=None):
    headers = make_proponent_headers(proponent["id"])
    payload = {"contributed_cents": contributed_cents}
    payload["response_note"] = note or "Supplemental drought response funded."
    return get_success_data(
        api_client.respond_to_circumstance_event(event_id, payload, headers), 200
    )


DEFAULT_COMMITMENT_UNITS = (45.01, 14.71)


def build_scenario(
    stage="permit",
    clock=CANONICAL_CLOCK,
    species_overrides=None,
    include_unit=True,
    unit_overrides=None,
    include_threatened=True,
    threatened_overrides=None,
    include_bank=True,
    bank_overrides=None,
    proponent_overrides=None,
    action_overrides=None,
    field_survey_overrides=None,
    include_database_query=True,
    database_query_overrides=None,
    opinion_payload=None,
    plan_overrides=None,
    commitments=None,
    funding_cents=None,
    decision="APPROVE",
    permit_overrides=None,
):
    """Walk the lifecycle up to `stage` and return every row created on the way.

    Stages, in order: registry, proponent, action, determinations,
    effect_determination, ba_submitted, opinion, plan, commitments, funded,
    submitted, approved, permit.
    """
    target = _stage_index(stage)
    scenario = {"clock": clock}
    if clock is not None:
        set_clock(clock)

    scenario["species"] = register_species(**(species_overrides or {}))
    if include_unit:
        scenario["unit"] = designate_critical_habitat_unit(
            scenario["species"]["id"], **(unit_overrides or {})
        )
        scenario["species"] = read_species(scenario["species"]["id"])
    else:
        scenario["unit"] = None
    if include_threatened:
        scenario["threatened_species"] = register_threatened_species(
            **(threatened_overrides or {})
        )
    else:
        scenario["threatened_species"] = None
    if include_bank:
        scenario["bank"] = establish_conservation_bank(
            scenario["species"]["id"], **(bank_overrides or {})
        )
    else:
        scenario["bank"] = None
    if target == _stage_index("registry"):
        return scenario

    scenario["proponent"] = register_proponent(**(proponent_overrides or {}))
    scenario["proponent_headers"] = make_proponent_headers(scenario["proponent"]["id"])
    if target == _stage_index("proponent"):
        return scenario

    scenario["action"] = open_project_action(
        scenario["proponent"], **(action_overrides or {})
    )
    if target == _stage_index("action"):
        return scenario

    survey = dict(field_survey_overrides or {})
    if include_unit and "critical_habitat_unit_id" not in survey:
        survey["critical_habitat_unit_id"] = scenario["unit"]["id"]
    scenario["field_determination"] = record_field_survey(
        scenario["action"], scenario["proponent"], scenario["species"]["id"], **survey
    )
    if include_database_query and scenario["threatened_species"] is not None:
        scenario["query_determination"] = record_database_query(
            scenario["action"],
            scenario["proponent"],
            scenario["threatened_species"]["id"],
            **(database_query_overrides or {}),
        )
    else:
        scenario["query_determination"] = None
    if target == _stage_index("determinations"):
        return scenario

    scenario["action"] = run_effect_determination(scenario["action"], scenario["proponent"])
    consultation_id = scenario["action"]["active_consultation_id"]
    scenario["consultation"] = (
        read_consultation(consultation_id) if consultation_id else None
    )
    if target == _stage_index("effect_determination"):
        return scenario

    scenario["consultation"] = submit_biological_assessment(
        consultation_id, scenario["proponent"]
    )
    if target == _stage_index("ba_submitted"):
        return scenario

    scenario["opinion"] = issue_biological_opinion(consultation_id, opinion_payload)
    scenario["consultation"] = read_consultation(consultation_id)
    scenario["action"] = read_action(scenario["action"]["id"])
    if target == _stage_index("opinion"):
        return scenario

    scenario["plan"] = get_success_data(
        api_client.create_habitat_conservation_plan(
            scenario["action"]["id"],
            habitat_conservation_plan_payload(**(plan_overrides or {})),
            scenario["proponent_headers"],
        ),
        201,
    )
    scenario["action"] = read_action(scenario["action"]["id"])
    if target == _stage_index("plan"):
        return scenario

    specs = commitments
    if specs is None:
        specs = [
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": units,
                "conservation_bank_id": scenario["bank"]["id"],
            }
            for units in DEFAULT_COMMITMENT_UNITS
        ]
    scenario["commitments"] = [
        add_commitment(scenario["plan"]["id"], scenario["proponent"], spec)
        for spec in specs
    ]
    scenario["plan"] = read_plan(scenario["plan"]["id"])
    if scenario["bank"] is not None:
        scenario["bank"] = read_bank(scenario["bank"]["id"])
    if target == _stage_index("commitments"):
        return scenario

    if funding_cents is None:
        fully_fund_plan(scenario["plan"]["id"], scenario["proponent"])
    elif funding_cents > 0:
        add_funding_assurance(
            scenario["plan"]["id"], scenario["proponent"], funding_cents
        )
    scenario["plan"] = read_plan(scenario["plan"]["id"])
    if target == _stage_index("funded"):
        return scenario

    scenario["plan"] = submit_plan(scenario["plan"]["id"], scenario["proponent"])
    if target == _stage_index("submitted"):
        return scenario

    scenario["plan"] = decide_plan(scenario["plan"]["id"], decision)
    if scenario["bank"] is not None:
        scenario["bank"] = read_bank(scenario["bank"]["id"])
    if target == _stage_index("approved"):
        return scenario

    scenario["permit"] = issue_permit(
        scenario["plan"]["id"], **(permit_overrides or {})
    )
    scenario["plan"] = read_plan(scenario["plan"]["id"])
    scenario["action"] = read_action(scenario["action"]["id"])
    return scenario


def read_species(species_id, headers=None):
    return get_success_data(api_client.get_species(species_id, headers or AUDITOR), 200)


def setup_canonical_permit(**overrides):
    """The full chain through permit issuance: an ACTIVE permit on an IMPLEMENTING plan."""
    return build_scenario("permit", **overrides)


def setup_take_exceedance(report_clock="2027-04-15T00:00:00Z", take_units=3.60, **overrides):
    """An ACTIVE permit driven past its reinitiation trigger by one report.

    Returns the scenario with the filed report under the key `report`.
    """
    scenario = build_scenario("permit", **overrides)
    set_clock(report_clock)
    scenario["report"] = file_monitoring_report(
        scenario["permit"]["id"],
        scenario["proponent"],
        take_units_reported=take_units,
    )
    scenario["permit"] = read_permit(scenario["permit"]["id"])
    scenario["plan"] = read_plan(scenario["plan"]["id"])
    scenario["action"] = read_action(scenario["action"]["id"])
    scenario["consultation"] = read_consultation(scenario["consultation"]["id"])
    scenario["proponent"] = read_proponent(scenario["proponent"]["id"])
    return scenario


def setup_single_species_action(**overrides):
    """The canonical chain with only the endangered species on the action."""
    defaults = {
        "include_threatened": False,
        "include_database_query": False,
    }
    defaults.update(overrides)
    return build_scenario(**defaults)


def setup_jeopardy_plan(stage="submitted", **overrides):
    """A plan whose opinion concludes JEOPARDY because the population is tiny.

    A recovery-unit population of 80 puts the jeopardy fraction on its threshold.
    """
    defaults = {
        "stage": stage,
        "species_overrides": {"recovery_unit_population": 80},
        "include_threatened": False,
        "include_database_query": False,
    }
    defaults.update(overrides)
    return build_scenario(**defaults)


def setup_second_action(scenario, **overrides):
    """Open a second project action under the same proponent and registry."""
    payload_overrides = {
        "action_name": "Sunrise Park Phase II",
        "county_code": ACTION_COUNTY_CODE,
    }
    payload_overrides.update(overrides)
    return open_project_action(scenario["proponent"], **payload_overrides)


def establish_out_of_area_bank(species_id, **overrides):
    """A bank for the same species whose service area excludes the action's county."""
    defaults = {
        "bank_name": "Owens Valley Habitat Bank",
        "service_area_county_codes": ["06059"],
        "credit_price_cents": 300_000,
        "credits_total_minted": 5.00,
    }
    defaults.update(overrides)
    return establish_conservation_bank(species_id, **defaults)


def setup_action_with_determination_count(count=11, **overrides):
    """An action carrying `count` database-query determinations of one acre each."""
    scenario = build_scenario(
        "action",
        include_unit=False,
        include_threatened=False,
        include_bank=False,
        **overrides,
    )
    scenario["determinations"] = [
        record_database_query(
            scenario["action"],
            scenario["proponent"],
            scenario["species"]["id"],
            habitat_overlap_acres=1.00,
        )
        for _ in range(count)
    ]
    return scenario


def setup_two_penalty_reports():
    """An ACTIVE permit carrying one REJECTED report and one late ACCEPTED report.

    R1 covers [2026-10-01, 2026-10-31) and is rejected at clock 2026-11-20.
    R2 covers [2027-01-01, 2027-03-31) and is accepted late at clock 2027-05-20.
    """
    scenario = build_scenario("permit")
    set_clock("2026-11-20T00:00:00Z")
    scenario["r1"] = file_monitoring_report(
        scenario["permit"]["id"],
        scenario["proponent"],
        period_start="2026-10-01",
        period_end="2026-10-31",
        take_units_reported=1.00,
        mitigation_units_verified=59.72,
    )
    adjudicate_report(
        scenario["r1"]["id"],
        "REJECT",
        note="Survey effort insufficient for the reported period.",
    )
    set_clock("2027-05-20T00:00:00Z")
    scenario["r2"] = file_monitoring_report(
        scenario["permit"]["id"],
        scenario["proponent"],
        period_start="2027-01-01",
        period_end="2027-03-31",
        take_units_reported=1.00,
        mitigation_units_verified=59.72,
    )
    adjudicate_report(scenario["r2"]["id"], "ACCEPT", note="Take within authorized limits.")
    return scenario


def setup_informal_consultation_under_review(clock=CANONICAL_CLOCK):
    """An action on the informal branch whose consultation sits at UNDER_REVIEW.

    One THREATENED database-query determination of 10.00 acres over a 200.00-acre
    footprint yields overlap_pct 5.00 with no confirmed presence, so the ladder
    resolves NLAA.
    """
    scenario = build_scenario(
        "action", clock=clock, include_unit=False, include_bank=False
    )
    scenario["determination"] = record_database_query(
        scenario["action"],
        scenario["proponent"],
        scenario["threatened_species"]["id"],
        habitat_overlap_acres=10.00,
    )
    scenario["action"] = run_effect_determination(
        scenario["action"], scenario["proponent"]
    )
    scenario["consultation_id"] = scenario["action"]["active_consultation_id"]
    scenario["consultation"] = submit_biological_assessment(
        scenario["consultation_id"],
        scenario["proponent"],
        ba_narrative=(
            "Informal effects analysis for 10.00 acres of presumed-occupied habitat."
        ),
    )
    return scenario


def request_consultation_information(consultation_id, note=None, headers=None):
    payload = {"request_note": note or "Please provide burrow survey transect data."}
    return get_success_data(
        api_client.request_information(consultation_id, payload, headers or REVIEWER), 200
    )


def setup_tolled_consultation():
    """A formal consultation that has traversed the information-request cycle twice.

    Episode one runs 2026-10-05 to 2026-10-12 and tolls seven days; episode two runs
    2026-10-15 to 2026-10-18 and tolls three more.
    """
    scenario = build_scenario("ba_submitted")
    consultation_id = scenario["consultation"]["id"]
    scenario["consultation_id"] = consultation_id
    set_clock("2026-10-05T00:00:00Z")
    scenario["rq1"] = request_consultation_information(
        consultation_id, "Clarify the take estimate for the CHU-1 acreage."
    )
    set_clock("2026-10-12T00:00:00Z")
    scenario["rev2"] = submit_biological_assessment(
        consultation_id,
        scenario["proponent"],
        ba_narrative="Revision 2 - additional transect data supplied.",
    )
    set_clock("2026-10-15T00:00:00Z")
    scenario["rq2"] = request_consultation_information(
        consultation_id, "Clarify the take estimate for the CHU-1 acreage."
    )
    set_clock("2026-10-18T00:00:00Z")
    scenario["rev3"] = submit_biological_assessment(
        consultation_id,
        scenario["proponent"],
        ba_narrative="Revision 3 - take estimate reconciled with the CHU-1 acreage.",
    )
    return scenario


def setup_fully_assured_draft_plan(units=10.00):
    """A DRAFT plan whose single commitment is fully covered by one assurance."""
    scenario = build_scenario("plan")
    scenario["commitments"] = [
        add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": units,
                "conservation_bank_id": scenario["bank"]["id"],
            },
        )
    ]
    plan = read_plan(scenario["plan"]["id"], scenario["proponent_headers"])
    add_funding_assurance(
        scenario["plan"]["id"], scenario["proponent"], plan["endowment_required_cents"]
    )
    scenario["plan"] = read_plan(scenario["plan"]["id"], scenario["proponent_headers"])
    return scenario


def setup_take_threshold_cascade():
    """A permit carried past its reinitiation trigger by a second report.

    Report one is accepted at 2027-02-14 for 2.00 units, one report short of the
    3.60-unit trigger; report two, filed at 2027-05-20 for 1.60 units, crosses it.
    """
    scenario = build_scenario("permit")
    set_clock("2027-02-14T00:00:00Z")
    scenario["r1"] = file_monitoring_report(
        scenario["permit"]["id"],
        scenario["proponent"],
        period_start="2026-10-01",
        period_end="2026-12-31",
        take_units_reported=2.00,
        mitigation_units_verified=59.72,
    )
    adjudicate_report(scenario["r1"]["id"], "ACCEPT")
    scenario["permit_after_r1"] = read_permit(scenario["permit"]["id"])
    set_clock("2027-05-20T00:00:00Z")
    scenario["r2"] = file_monitoring_report(
        scenario["permit"]["id"],
        scenario["proponent"],
        period_start="2027-01-01",
        period_end="2027-03-31",
        take_units_reported=1.60,
        mitigation_units_verified=59.72,
    )
    return scenario


def setup_suspended_permit():
    """A permit suspended by a single report that lands exactly on the trigger.

    The pre-report permit version is returned under `permit_v1` so the optimistic
    concurrency guard can be probed with a stale value.
    """
    scenario = build_scenario("permit")
    scenario["permit_v1"] = scenario["permit"]["version"]
    set_clock("2027-02-14T00:00:00Z")
    scenario["r1"] = file_monitoring_report(
        scenario["permit"]["id"],
        scenario["proponent"],
        period_start="2026-10-01",
        period_end="2026-12-31",
        take_units_reported=3.60,
        mitigation_units_verified=59.72,
    )
    set_clock("2027-05-20T00:00:00Z")
    scenario["permit"] = read_permit(scenario["permit"]["id"])
    return scenario


def setup_jeopardy_submitted_plan(units=1.00, opinion_payload=None):
    """A SUBMITTED, fully assured plan whose opinion concludes jeopardy.

    A recovery-unit population of 80 puts the jeopardy fraction exactly on its
    0.0500 threshold, and a single small commitment leaves the plan short of its
    final mitigation obligation.
    """
    scenario = setup_jeopardy_plan(stage="plan", opinion_payload=opinion_payload)
    scenario["commitments"] = [
        add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": units,
                "conservation_bank_id": scenario["bank"]["id"],
            },
        )
    ]
    fully_fund_plan(scenario["plan"]["id"], scenario["proponent"])
    scenario["plan"] = submit_plan(scenario["plan"]["id"], scenario["proponent"])
    return scenario


def setup_permit_with_one_report(term_years=1):
    """A permit on a short term carrying one SUBMITTED report for December-January."""
    scenario = build_scenario("permit", plan_overrides={"permit_term_years": term_years})
    set_clock("2027-02-14T00:00:00Z")
    scenario["r1"] = file_monitoring_report(
        scenario["permit"]["id"],
        scenario["proponent"],
        period_start="2026-12-01",
        period_end="2027-01-31",
        take_units_reported=1.00,
        mitigation_units_verified=59.72,
    )
    scenario["permit"] = read_permit(scenario["permit"]["id"])
    return scenario


def setup_opinion_for_population(population, **overrides):
    """A single-species action carried through to an issued biological opinion."""
    defaults = {
        "stage": "opinion",
        "include_threatened": False,
        "include_database_query": False,
        "species_overrides": {"recovery_unit_population": population},
    }
    defaults.update(overrides)
    return build_scenario(**defaults)


def setup_plan_with_permittee_responsible_commitment(units=10.00):
    """A DRAFT plan holding one permittee-responsible commitment and no funding."""
    scenario = build_scenario("plan")
    scenario["commitments"] = [
        add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {"mechanism": "PERMITTEE_RESPONSIBLE", "units": units},
        )
    ]
    scenario["plan"] = read_plan(scenario["plan"]["id"], scenario["proponent_headers"])
    return scenario


def setup_action_with_absent_determinations():
    """An action whose two determinations are both filtered out of the candidate set."""
    scenario = build_scenario(
        "action", include_unit=False, include_threatened=False, include_bank=False
    )
    scenario["absent_field_survey"] = record_field_survey(
        scenario["action"],
        scenario["proponent"],
        scenario["species"]["id"],
        detection_result="NOT_DETECTED",
        habitat_overlap_acres=12.50,
    )
    scenario["absent_query"] = record_database_query(
        scenario["action"],
        scenario["proponent"],
        scenario["species"]["id"],
        detection_result="NOT_DETECTED",
        habitat_overlap_acres=7.25,
    )
    return scenario


def setup_two_actions_sharing_a_habitat_unit():
    """Two actions of one proponent contending for the same critical habitat unit.

    Action A already carries a field survey citing CHU-1 over 2026-05-04..2026-05-08,
    so the buffered protected span for CHU-1 runs 2026-05-01..2026-05-11. A second
    unit, CHU-2, is designated for the same species as an uncontended control.
    """
    scenario = build_scenario(
        "action", include_threatened=False, include_bank=False
    )
    scenario["unit_2"] = designate_critical_habitat_unit(
        scenario["species"]["id"], unit_code="CHU-2"
    )
    scenario["pd1"] = record_field_survey(
        scenario["action"],
        scenario["proponent"],
        scenario["species"]["id"],
        critical_habitat_unit_id=scenario["unit"]["id"],
        survey_window_start="2026-05-04",
        survey_window_end="2026-05-08",
    )
    scenario["action_b"] = setup_second_action(scenario)
    return scenario


def setup_permit_with_accepted_first_quarter_report():
    """An ACTIVE permit carrying one ACCEPTED report over [2027-01-01, 2027-04-01)."""
    scenario = build_scenario("permit")
    set_clock("2027-04-01T00:00:00Z")
    scenario["r1"] = file_monitoring_report(
        scenario["permit"]["id"],
        scenario["proponent"],
        period_start="2027-01-01",
        period_end="2027-04-01",
        take_units_reported=1.00,
        mitigation_units_verified=59.72,
    )
    adjudicate_report(scenario["r1"]["id"], "ACCEPT")
    set_clock("2027-07-01T00:00:00Z")
    scenario["permit"] = read_permit(scenario["permit"]["id"])
    return scenario


def setup_suspension_at_trigger_clock():
    """The take-exceedance cascade fired, with the clock left on the report date.

    Unlike `setup_suspended_permit`, the logical clock is not advanced past the
    report, so an adjudication in the test lands on 2027-02-14 as well.
    """
    scenario = build_scenario("permit")
    set_clock("2027-02-14T00:00:00Z")
    scenario["r1"] = file_monitoring_report(
        scenario["permit"]["id"],
        scenario["proponent"],
        period_start="2026-10-01",
        period_end="2026-12-31",
        take_units_reported=3.60,
        mitigation_units_verified=59.72,
    )
    scenario["permit"] = read_permit(scenario["permit"]["id"])
    return scenario
