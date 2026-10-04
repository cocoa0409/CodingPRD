"""Composite setup helpers — multi-step PRD workflows behind one call each.

The server is restarted before every test, so every helper builds its
preconditions from scratch through PRD-declared endpoints. Setup calls use
the lenient get_success_data validator: a failed precondition surfaces as a
setup error, not a confusing assertion failure.

Identity threading (PRD §2.1): after creating a Fleet or ServiceCenter, every
ownership-gated call in these helpers uses make_fleet_manager_headers
(fleet["id"]) / make_service_advisor_headers(center["id"]) — never a shared
constant id. Segregation of duties (PRD §3.2): the family chain submits for
review as SUBMITTER_USER_ID and certifies as CERTIFIER_USER_ID, two distinct
opaque ids.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC, REQUIRED_TEST_TYPES
from .factories import (
    adjudicate_claim_payload,
    authorize_service_center_payload,
    calibrate_spec_payload,
    create_aftertreatment_spec_payload,
    create_campaign_work_order_payload,
    create_diagnostic_tool_payload,
    create_engine_family_payload,
    create_engine_unit_payload,
    create_field_campaign_payload,
    create_fleet_payload,
    create_in_use_result_payload,
    create_maintenance_record_payload,
    create_regulation_standard_payload,
    create_reman_order_payload,
    create_service_center_payload,
    create_technician_payload,
    create_telematics_snapshot_payload,
    create_test_run_payload,
    create_warranty_claim_payload,
    grade_core_payload,
    record_results_payload,
    resubmit_claim_payload,
    review_test_run_payload,
    set_clock_payload,
)
from .test_users import (
    ADJUDICATOR_USER_ID,
    CERTIFIER_USER_ID,
    SUBMITTER_USER_ID,
    TEST_USERS,
    make_certification_engineer_headers,
    make_fleet_manager_headers,
    make_regulatory_officer_headers,
    make_service_advisor_headers,
    make_warranty_adjudicator_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
OFFICER = TEST_USERS["officer_headers"]
ADJUDICATOR = TEST_USERS["adjudicator_headers"]
PLANNER = TEST_USERS["planner_headers"]


# ---------------------------------------------------------------------------
# logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
def set_logical_clock(current_utc: str) -> str:
    """Set the logical clock; returns the echoed current_utc. The clock starts
    at 2026-09-01T00:00:00Z and never falls back to wall-clock — advancing it
    is the only way time passes."""
    data = get_success_data(api_client.set_clock(set_clock_payload(current_utc), ADMIN))
    return data["current_utc"]


# ---------------------------------------------------------------------------
# regulation standards (PRD §3.1)
# ---------------------------------------------------------------------------
def create_draft_standard(**overrides) -> dict:
    return get_success_data(
        api_client.create_regulation_standard(create_regulation_standard_payload(**overrides), ADMIN)
    )


def publish_standard(standard_id: str) -> dict:
    return get_success_data(api_client.publish_regulation_standard(standard_id, OFFICER))


def create_published_standard(**overrides) -> dict:
    """Draft standard created and published. Returns the PUBLISHED standard."""
    standard = create_draft_standard(**overrides)
    return publish_standard(standard["id"])


# ---------------------------------------------------------------------------
# engine family certification lifecycle (PRD §3.2, §3.3)
# ---------------------------------------------------------------------------
def create_family(regulation_standard_id: str, **overrides) -> dict:
    """Family in DESIGN against a published standard."""
    return get_success_data(
        api_client.create_engine_family(
            create_engine_family_payload(regulation_standard_id=regulation_standard_id, **overrides),
            ENGINEER,
        )
    )


def get_family(family_id: str) -> dict:
    return get_success_data(api_client.get_engine_family(family_id, ADMIN))


def get_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_engine_unit(unit_id, ADMIN))


def add_spec_version(family: dict, calibrate: bool = True, activate: bool = True,
                     calibrate_overrides: dict = None, **spec_overrides) -> dict:
    """Create a new spec version for the family (OCC: expected version read
    from the given family dict), optionally calibrate (defaults CALIBRATED)
    and activate it. Returns the resulting spec."""
    spec = get_success_data(
        api_client.create_aftertreatment_spec(
            family["id"],
            create_aftertreatment_spec_payload(
                expected_engine_family_version=family["version"], **spec_overrides
            ),
            ENGINEER,
        )
    )
    if calibrate:
        spec = get_success_data(
            api_client.calibrate_spec(spec["id"], calibrate_spec_payload(**(calibrate_overrides or {})), ENGINEER)
        )
    if activate:
        spec = get_success_data(api_client.activate_spec(spec["id"], ENGINEER))
    return spec


def begin_family_testing(family_id: str) -> dict:
    return get_success_data(api_client.begin_testing(family_id, ENGINEER))


def schedule_test_run(family_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_test_run(family_id, create_test_run_payload(**overrides), ENGINEER)
    )


def record_run_results(run_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.record_test_results(run_id, record_results_payload(**overrides), ENGINEER)
    )


def review_run(run_id: str, decision: str = "ACCEPT") -> dict:
    return get_success_data(api_client.review_test_run(run_id, review_test_run_payload(decision), OFFICER))


def add_accepted_test_run(family_id: str, test_type: str, **run_overrides) -> dict:
    """Schedule a run of the given type, record passing results, review ACCEPT.
    Returns the ACCEPTED run."""
    run = schedule_test_run(family_id, test_type=test_type, **run_overrides)
    run = record_run_results(run["id"])
    return review_run(run["id"], "ACCEPT")


def setup_family_testing(**overrides) -> dict:
    """Published standard + family with an ACTIVE calibrated spec, moved to
    TESTING. Returns {"standard", "family", "spec"} (family as of TESTING)."""
    standard = create_published_standard(**overrides.pop("standard_overrides", {}))
    family = create_family(standard["id"], **overrides.pop("family_overrides", {}))
    spec = add_spec_version(family, **overrides.pop("spec_overrides", {}))
    family = begin_family_testing(family["id"])
    return {"standard": standard, "family": family, "spec": spec}


def setup_family_under_review(submitter_user_id: str = SUBMITTER_USER_ID,
                              test_types=REQUIRED_TEST_TYPES, **overrides) -> dict:
    """TESTING family + one ACCEPTED run per required type, submitted for
    review by submitter_user_id (the segregation-of-duties anchor).
    Returns {"standard", "family", "spec", "runs"}."""
    env = setup_family_testing(**overrides)
    runs = {
        test_type: add_accepted_test_run(env["family"]["id"], test_type)
        for test_type in test_types
    }
    family = get_success_data(
        api_client.submit_review(
            env["family"]["id"],
            make_certification_engineer_headers(submitter_user_id),
        )
    )
    env["family"] = family
    env["runs"] = runs
    return env


def certify_family(family_id: str, certifier_user_id: str = CERTIFIER_USER_ID) -> dict:
    """Certify an UNDER_REVIEW family. certifier_user_id must differ from the
    family's submitted_by_user_id (PRD §3.2 segregation of duties)."""
    return get_success_data(
        api_client.certify_family(family_id, make_regulatory_officer_headers(certifier_user_id))
    )


def setup_family_certified(**overrides) -> dict:
    """Family driven to CERTIFIED. Returns {"standard", "family", "spec", "runs"}."""
    env = setup_family_under_review(**overrides)
    env["family"] = certify_family(env["family"]["id"])
    return env


def setup_family_in_production(**overrides) -> dict:
    """Family driven to IN_PRODUCTION (production_entered true).
    Returns {"standard", "family", "spec", "runs"}."""
    env = setup_family_certified(**overrides)
    env["family"] = get_success_data(api_client.enter_production(env["family"]["id"], OFFICER))
    return env


# ---------------------------------------------------------------------------
# fleets (PRD §3.4)
# ---------------------------------------------------------------------------
def setup_fleet(**overrides) -> dict:
    """Register a fleet (ACTIVE, neglect_denial_count 0)."""
    return get_success_data(api_client.create_fleet(create_fleet_payload(**overrides), ADMIN))


# ---------------------------------------------------------------------------
# service network (PRD §3.6)
# ---------------------------------------------------------------------------
def create_service_center(**overrides) -> dict:
    """Register a center (APPLIED, BASIC)."""
    return get_success_data(
        api_client.create_service_center(create_service_center_payload(**overrides), ADMIN)
    )


def add_technician(center_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_technician(center_id, create_technician_payload(**overrides), ADMIN)
    )


def add_diagnostic_tool(center_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_diagnostic_tool(center_id, create_diagnostic_tool_payload(**overrides), ADMIN)
    )


def authorize_center(center_id: str, authorization_tier: str = "CERTIFIED") -> dict:
    """AUDITED -> AUTHORIZED at the given tier. The center must already hold a
    CERT_ACTIVE emissions-endorsed technician (PRD §3.6)."""
    return get_success_data(
        api_client.authorize_service_center(
            center_id, authorize_service_center_payload(authorization_tier), ADMIN
        )
    )


def setup_service_center(bay_capacity_per_day: int = 2,
                         certification_level: str = "LEVEL_2",
                         emissions_endorsed: bool = True,
                         authorization_tier: str = "CERTIFIED",
                         with_tool: bool = True,
                         **center_overrides) -> dict:
    """Authorized center + one technician + (optionally) one calibrated tool.
    Returns {"center", "technician", "tool"}; tool is None when with_tool is
    False. The technician defaults to LEVEL_2 endorsed so the center passes
    the authorization gate and LEVEL_2-gated work orders."""
    center_overrides.setdefault("bay_capacity_per_day", bay_capacity_per_day)
    center = create_service_center(**center_overrides)
    technician = add_technician(
        center["id"],
        certification_level=certification_level,
        emissions_endorsed=emissions_endorsed,
    )
    get_success_data(api_client.audit_service_center(center["id"], ADMIN))
    center = authorize_center(center["id"], authorization_tier)
    tool = add_diagnostic_tool(center["id"]) if with_tool else None
    return {"center": center, "technician": technician, "tool": tool}


# ---------------------------------------------------------------------------
# engine units, telematics, maintenance (PRD §3.4, §3.5)
# ---------------------------------------------------------------------------
def setup_engine_unit(family_id: str, fleet_id: str, **overrides) -> dict:
    """Register a unit (IN_SERVICE, CLEAR, 0 miles/hours). The family must be
    IN_PRODUCTION and in_service_date must not exceed the logical clock."""
    return get_success_data(
        api_client.create_engine_unit(
            create_engine_unit_payload(
                engine_family_id=family_id, fleet_id=fleet_id, **overrides
            ),
            ADMIN,
        )
    )


def ingest_snapshot(unit_id: str, **overrides) -> dict:
    """Ingest a telematics snapshot (PlatformAdmin). Advances the unit's
    accumulated miles/hours and last_snapshot_at; computes fault_risk_score."""
    return get_success_data(
        api_client.create_telematics_snapshot(
            unit_id, create_telematics_snapshot_payload(**overrides), ADMIN
        )
    )


def add_maintenance_record(unit_id: str, fleet_id: str = None, **overrides) -> dict:
    """Append a maintenance record. With fleet_id, filed by that fleet's
    FleetManager (ownership-threaded); otherwise by PlatformAdmin."""
    headers = make_fleet_manager_headers(fleet_id) if fleet_id else ADMIN
    return get_success_data(
        api_client.create_maintenance_record(
            unit_id, create_maintenance_record_payload(**overrides), headers
        )
    )


# ---------------------------------------------------------------------------
# warranty claims (PRD §3.7)
# ---------------------------------------------------------------------------
def file_claim(unit: dict, center: dict, filer_role: str = "FleetManager",
               **overrides) -> dict:
    """File a warranty claim in SUBMITTED. filer_role "FleetManager" files as
    the unit's owning fleet (default); "ServiceAdvisor" files as the repairing
    center. Both thread the entity-backed X-User-ID."""
    if filer_role == "ServiceAdvisor":
        headers = make_service_advisor_headers(center["id"])
    else:
        headers = make_fleet_manager_headers(unit["fleet_id"])
    return get_success_data(
        api_client.create_warranty_claim(
            create_warranty_claim_payload(
                engine_unit_id=unit["id"], service_center_id=center["id"], **overrides
            ),
            headers,
        )
    )


def start_claim_review(claim_id: str) -> dict:
    return get_success_data(api_client.start_claim_review(claim_id, ADJUDICATOR))


def setup_claim_under_review(unit: dict, center: dict, filer_role: str = "FleetManager",
                             **overrides) -> dict:
    """Claim filed and moved to UNDER_REVIEW."""
    claim = file_claim(unit, center, filer_role=filer_role, **overrides)
    return start_claim_review(claim["id"])


def request_info(claim_id: str) -> dict:
    return get_success_data(api_client.request_claim_info(claim_id, ADJUDICATOR))


def resubmit_claim(claim_id: str, unit: dict = None, center: dict = None,
                   filer_role: str = "FleetManager", note: str = "supplemental records") -> dict:
    """INFO_REQUESTED -> UNDER_REVIEW by the filing side. Pass the claim's unit
    (fleet path) or center (advisor path) to thread ownership."""
    if filer_role == "ServiceAdvisor" and center is not None:
        headers = make_service_advisor_headers(center["id"])
    elif unit is not None:
        headers = make_fleet_manager_headers(unit["fleet_id"])
    else:
        headers = TEST_USERS["fleet_manager_headers"]
    return get_success_data(
        api_client.resubmit_claim(claim_id, resubmit_claim_payload(note), headers)
    )


def adjudicate(claim_id: str, decision: str,
               adjudicator_user_id: str = ADJUDICATOR_USER_ID) -> dict:
    """UNDER_REVIEW -> APPROVED_FULL / APPROVED_PARTIAL / DENIED_NEGLECT. The
    decision must match the computed neglect-score band (PRD §3.7)."""
    return get_success_data(
        api_client.adjudicate_claim(
            claim_id,
            adjudicate_claim_payload(decision),
            make_warranty_adjudicator_headers(adjudicator_user_id),
        )
    )


def pay_claim(claim_id: str) -> dict:
    return get_success_data(api_client.pay_claim(claim_id, ADMIN))


# ---------------------------------------------------------------------------
# in-use compliance (PRD §3.4)
# ---------------------------------------------------------------------------
def record_in_use_result(family_id: str, **overrides) -> dict:
    """Record an in-use compliance result; the family must be IN_PRODUCTION.
    Default 9/10 rounds to exactly 0.9000 -> CONFORMING (inclusive boundary)."""
    return get_success_data(
        api_client.create_in_use_result(
            family_id, create_in_use_result_payload(**overrides), OFFICER
        )
    )


def stamp_family_non_conforming(family_id: str, test_period_label: str = None,
                                sample_size: int = 10, passing_units: int = 8) -> dict:
    """Record a NON_CONFORMING in-use result (default 8/10 = 0.8000) so a
    RECALL campaign may be announced. Returns the result record."""
    overrides = {"sample_size": sample_size, "passing_units": passing_units}
    if test_period_label is not None:
        overrides["test_period_label"] = test_period_label
    return record_in_use_result(family_id, **overrides)


# ---------------------------------------------------------------------------
# field campaigns (PRD §3.8)
# ---------------------------------------------------------------------------
def declare_campaign(family_id: str, **overrides) -> dict:
    """Declare a DRAFT campaign. The family must be CERTIFIED, IN_PRODUCTION
    or COMPLIANCE_HOLD."""
    return get_success_data(
        api_client.create_field_campaign(
            create_field_campaign_payload(engine_family_id=family_id, **overrides), OFFICER
        )
    )


def announce_campaign(campaign_id: str) -> dict:
    """DRAFT -> ANNOUNCED; cascades family -> COMPLIANCE_HOLD and flags every
    in-service, not-already-open unit of the family CAMPAIGN_OPEN."""
    return get_success_data(api_client.announce_campaign(campaign_id, OFFICER))


def setup_campaign_announced(family_id: str, **overrides) -> dict:
    campaign = declare_campaign(family_id, **overrides)
    return announce_campaign(campaign["id"])


def setup_campaign_in_progress(family_id: str, **overrides) -> dict:
    """ANNOUNCED campaign moved to IN_PROGRESS (requires notified units > 0 —
    create units BEFORE calling this)."""
    campaign = setup_campaign_announced(family_id, **overrides)
    return get_success_data(api_client.begin_campaign_execution(campaign["id"], OFFICER))


# ---------------------------------------------------------------------------
# campaign work orders (PRD §3.8)
# ---------------------------------------------------------------------------
def schedule_work_order(campaign_id: str, unit_id: str, center_id: str,
                        technician_id: str, **overrides) -> dict:
    """Schedule a unit remedy (SCHEDULED) as the executing center's advisor."""
    return get_success_data(
        api_client.create_campaign_work_order(
            campaign_id,
            create_campaign_work_order_payload(
                engine_unit_id=unit_id,
                service_center_id=center_id,
                assigned_technician_id=technician_id,
                **overrides,
            ),
            make_service_advisor_headers(center_id),
        )
    )


def start_work_order(work_order_id: str, center_id: str) -> dict:
    """SCHEDULED -> IN_BAY; the center must hold a CALIBRATED_ACTIVE tool."""
    return get_success_data(
        api_client.start_work_order(work_order_id, make_service_advisor_headers(center_id))
    )


def complete_work_order(work_order_id: str, center_id: str) -> dict:
    return get_success_data(
        api_client.complete_work_order(work_order_id, make_service_advisor_headers(center_id))
    )


def verify_work_order(work_order_id: str) -> dict:
    """COMPLETED -> VERIFIED; drives the unit/campaign/family cascade."""
    return get_success_data(api_client.verify_work_order(work_order_id, OFFICER))


def cancel_work_order(work_order_id: str, center_id: str) -> dict:
    """SCHEDULED -> CANCELLED; releases the occupied bay-days."""
    return get_success_data(
        api_client.cancel_work_order(work_order_id, make_service_advisor_headers(center_id))
    )


def setup_work_order_completed(campaign_id: str, unit_id: str, center_id: str,
                               technician_id: str, **overrides) -> dict:
    wo = schedule_work_order(campaign_id, unit_id, center_id, technician_id, **overrides)
    wo = start_work_order(wo["id"], center_id)
    return complete_work_order(wo["id"], center_id)


# ---------------------------------------------------------------------------
# reman orders and the core credit ledger (PRD §3.9)
# ---------------------------------------------------------------------------
def setup_reman_order_quoted(unit_id: str, center_id: str, **overrides) -> dict:
    """Quote a reman order as the ordering center's advisor. The unit is
    re-read immediately before the create so the OCC field carries the unit's
    current version."""
    unit = get_unit(unit_id)
    return get_success_data(
        api_client.create_reman_order(
            create_reman_order_payload(
                engine_unit_id=unit_id,
                service_center_id=center_id,
                expected_engine_unit_version=unit["version"],
                **overrides,
            ),
            make_service_advisor_headers(center_id),
        )
    )


def setup_reman_order_awaiting_core(unit_id: str, center_id: str, **overrides) -> dict:
    """QUOTED -> AWAITING_CORE; posts the provisional credit to the center."""
    order = setup_reman_order_quoted(unit_id, center_id, **overrides)
    return get_success_data(
        api_client.confirm_reman_order(order["id"], make_service_advisor_headers(center_id))
    )


def setup_reman_order_core_received(unit_id: str, center_id: str, **overrides) -> dict:
    """AWAITING_CORE -> CORE_RECEIVED; the clock must be at or before the
    order's expected_core_return_by."""
    order = setup_reman_order_awaiting_core(unit_id, center_id, **overrides)
    return get_success_data(
        api_client.receive_core(order["id"], make_service_advisor_headers(center_id))
    )


def grade_core(order_id: str, core_grade: str) -> dict:
    """Grade a CORE_RECEIVED order (RemanPlanner): A/B/C -> CREDIT_ISSUED,
    REJECT -> CORE_REJECTED with the reversal cascade."""
    return get_success_data(api_client.grade_core(order_id, grade_core_payload(core_grade), PLANNER))


def forfeit_core(order_id: str, center_id: str = None) -> dict:
    """AWAITING_CORE -> CORE_FORFEIT; clock must be strictly past the deadline.
    Filed by the center's advisor when center_id is given, else by a planner."""
    headers = make_service_advisor_headers(center_id) if center_id else PLANNER
    return get_success_data(api_client.forfeit_core(order_id, headers))


def close_reman_order(order_id: str, center_id: str) -> dict:
    return get_success_data(
        api_client.close_reman_order(order_id, make_service_advisor_headers(center_id))
    )


# ---------------------------------------------------------------------------
# full canonical environment
# ---------------------------------------------------------------------------
def setup_full_environment(**overrides) -> dict:
    """The canonical certified-program environment, built from empty state:
    published standard, family IN_PRODUCTION (active calibrated spec, three
    accepted runs, submitter != certifier), one fleet, one authorized center
    with a LEVEL_2 endorsed technician and a calibrated tool.

    Returns {"standard", "family", "spec", "runs", "fleet", "center",
    "technician", "tool"} — the family dict is as of IN_PRODUCTION.
    """
    env = setup_family_in_production(**overrides)
    env["fleet"] = setup_fleet()
    network = setup_service_center()
    env.update(network)
    return env
