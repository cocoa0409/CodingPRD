"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its own
preconditions from scratch using only endpoints the PRD declares.  Setup calls
go through `get_success_data()` so a broken precondition reports as a setup
failure rather than as a confusing assertion mismatch.

Identity discipline:

* the acting consultant, compliance officer and auditor identities are three
  distinct opaque values, because two segregation-of-duties rules compare them;
* `InstallerOperator` calls always use `make_installer_operator_headers(
  installer["id"])`, never the shared fallback constant, because job ownership
  compares `X-User-ID` against `installer_id`.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_installer_operator_headers,
)

ADMIN = TEST_USERS["manufacturer_admin_headers"]
CONSULTANT = TEST_USERS["design_consultant_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
CLIENT = TEST_USERS["client_representative_headers"]
AUDITOR = TEST_USERS["safety_auditor_headers"]
AUDITOR_2 = TEST_USERS["safety_auditor_2_headers"]


# ==========================================================================
# Tier 0 — single-call primitives
# ==========================================================================
def set_clock(current_utc: str, headers: Optional[Dict[str, str]] = None) -> dict:
    """Move the logical clock to an explicit ISO-8601 UTC instant."""
    return get_success_data(api_client.set_clock(current_utc, headers or ADMIN))


def set_clock_to_date(date_str: str, headers: Optional[Dict[str, str]] = None) -> dict:
    """Move the logical clock to midnight UTC on the given calendar date."""
    return set_clock(f"{date_str}T00:00:00Z", headers)


def register_standard(**overrides: Any) -> dict:
    return get_success_data(
        api_client.create_standard(f.standard_payload(**overrides), OFFICER)
    )


def activate_standard(standard_id: str) -> dict:
    return get_success_data(api_client.activate_standard(standard_id, OFFICER))


def create_active_standard(**overrides: Any) -> dict:
    """Register an edition and activate it; returns the ACTIVE row."""
    standard = register_standard(**overrides)
    return activate_standard(standard["id"])


def supersede_standard(standard_id: str, successor_standard_id: str) -> dict:
    return get_success_data(
        api_client.supersede_standard(
            standard_id, f.supersede_payload(successor_standard_id), OFFICER
        )
    )


def create_model(payload: Dict[str, Any]) -> dict:
    return get_success_data(api_client.create_component_model(payload, ADMIN))


def certify_model(model_id: str) -> dict:
    return get_success_data(api_client.certify_component_model(model_id, OFFICER))


def create_certified_model(payload: Dict[str, Any]) -> dict:
    """Add a catalogue model and certify it against the ACTIVE edition."""
    model = create_model(payload)
    return certify_model(model["id"])


def set_model_lifecycle(model_id: str, lifecycle_status: str) -> dict:
    return get_success_data(
        api_client.set_component_model_lifecycle(
            model_id, f.lifecycle_payload(lifecycle_status), ADMIN
        )
    )


def create_project(**overrides: Any) -> dict:
    return get_success_data(
        api_client.create_project(f.project_payload(**overrides), CONSULTANT)
    )


def start_consultation(project_id: str) -> dict:
    return get_success_data(api_client.start_consultation(project_id, CONSULTANT))


def create_project_in_consultation(**overrides: Any) -> dict:
    """Open a project and take it into CONSULTATION so design content is editable."""
    project = create_project(**overrides)
    return start_consultation(project["id"])


def create_play_area(project_id: str, **overrides: Any) -> dict:
    return get_success_data(
        api_client.create_play_area(project_id, f.play_area_payload(**overrides), CONSULTANT)
    )


def create_placement(area_id: str, component_model_id: str, **overrides: Any) -> dict:
    return get_success_data(
        api_client.create_placement(
            area_id, f.placement_payload(component_model_id, **overrides), CONSULTANT
        )
    )


def validate_placement(placement_id: str) -> dict:
    return get_success_data(api_client.validate_placement(placement_id, CONSULTANT))


def create_validated_placement(
    area_id: str, component_model_id: str, **overrides: Any
) -> dict:
    """Create a placement and walk it straight to VALIDATED."""
    placement = create_placement(area_id, component_model_id, **overrides)
    return validate_placement(placement["id"])


def delete_placement(placement_id: str) -> None:
    response = api_client.delete_placement(placement_id, CONSULTANT)
    assert 200 <= response.status_code < 300, (
        f"Setup step failed: DELETE placement returned {response.status_code}: {response.text}"
    )


def issue_rendering(project_id: str, pinned_standard_id: str) -> dict:
    return get_success_data(
        api_client.issue_rendering(
            project_id, f.rendering_payload(pinned_standard_id), CONSULTANT
        )
    )


def record_votes(rendering_id: str, yes_votes: int, no_votes: int) -> dict:
    return get_success_data(
        api_client.record_community_votes(
            rendering_id, f.community_votes_payload(yes_votes, no_votes), CLIENT
        )
    )


def close_review(rendering_id: str) -> dict:
    """Close the review round; the response body is the project."""
    return get_success_data(api_client.close_review(rendering_id, CONSULTANT))


def get_project(project_id: str) -> dict:
    return get_success_data(api_client.get_project(project_id, CONSULTANT))


def project_version(project_id: str) -> int:
    return get_project(project_id)["version"]


def get_play_area(area_id: str) -> dict:
    return get_success_data(api_client.get_play_area(area_id, CONSULTANT))


def get_placement(placement_id: str) -> dict:
    return get_success_data(api_client.get_placement(placement_id, CONSULTANT))


def get_rendering(rendering_id: str) -> dict:
    return get_success_data(api_client.get_rendering(rendering_id, CONSULTANT))


def get_quote(quote_id: str) -> dict:
    return get_success_data(api_client.get_quote(quote_id, CONSULTANT))


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, ADMIN))


def get_installer(installer_id: str) -> dict:
    return get_success_data(api_client.get_installer(installer_id, ADMIN))


def installer_version(installer_id: str) -> int:
    return get_installer(installer_id)["version"]


def get_job(job_id: str) -> dict:
    return get_success_data(api_client.get_installation_job(job_id, CONSULTANT))


def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_warranty_claim(claim_id, OFFICER))


def issue_quote(
    project_id: str,
    rendering_id: str,
    variant: str = "FIRM",
    expected_project_version: Optional[int] = None,
    **overrides: Any,
) -> dict:
    """Issue a quote, reading the project's live version unless one is supplied."""
    version = (
        expected_project_version
        if expected_project_version is not None
        else project_version(project_id)
    )
    payload = f.quote_payload(
        project_id, rendering_id, version, variant=variant, **overrides
    )
    return get_success_data(api_client.create_quote(payload, CONSULTANT))


def accept_quote(quote_id: str) -> dict:
    return get_success_data(api_client.accept_quote(quote_id, CLIENT))


def create_pledge(project_id: str, **overrides: Any) -> dict:
    return get_success_data(
        api_client.create_pledge(project_id, f.pledge_payload(**overrides), CLIENT)
    )


def collect_pledge(pledge_id: str) -> dict:
    return get_success_data(api_client.collect_pledge(pledge_id, CLIENT))


def refund_pledge(pledge_id: str) -> dict:
    return get_success_data(api_client.refund_pledge(pledge_id, CLIENT))


def create_collected_pledge(project_id: str, amount_cents: int, **overrides: Any) -> dict:
    pledge = create_pledge(project_id, amount_cents=amount_cents, **overrides)
    return collect_pledge(pledge["id"])


def certify_compliance(project_id: str) -> dict:
    """The officer identity differs from the consultant identity by construction."""
    return get_success_data(api_client.certify_compliance(project_id, OFFICER))


def create_order(quote_id: str) -> dict:
    return get_success_data(
        api_client.create_order(f.order_payload(quote_id), CONSULTANT)
    )


def start_production(order_id: str) -> dict:
    return get_success_data(api_client.start_production(order_id, ADMIN))


def advance_kitting(order_id: str, kitting_status: str) -> dict:
    return get_success_data(
        api_client.advance_kitting(order_id, f.kitting_payload(kitting_status), ADMIN)
    )


def advance_bagging(order_id: str, bagging_status: str) -> dict:
    return get_success_data(
        api_client.advance_bagging(order_id, f.bagging_payload(bagging_status), ADMIN)
    )


def ship_order(order_id: str) -> dict:
    return get_success_data(api_client.ship_order(order_id, ADMIN))


def create_installer(**overrides: Any) -> dict:
    return get_success_data(
        api_client.create_installer(f.installer_payload(**overrides), ADMIN)
    )


def set_installer_status(installer_id: str, status: str) -> dict:
    return get_success_data(
        api_client.set_installer_status(
            installer_id, f.installer_status_payload(status), ADMIN
        )
    )


def book_job(order_id: str, installer_id: str, **overrides: Any) -> dict:
    return get_success_data(
        api_client.create_installation_job(
            f.job_payload(order_id, installer_id, **overrides), CONSULTANT
        )
    )


def reschedule_job(
    job_id: str,
    scheduled_start_date: str,
    scheduled_end_date: str,
    expected_installer_version: int,
    **overrides: Any,
) -> dict:
    return get_success_data(
        api_client.reschedule_job(
            job_id,
            f.reschedule_payload(
                expected_installer_version,
                scheduled_start_date,
                scheduled_end_date,
                **overrides,
            ),
            CONSULTANT,
        )
    )


def cancel_job(job_id: str) -> dict:
    return get_success_data(api_client.cancel_job(job_id, CONSULTANT))


def start_job(job_id: str, installer_id: str) -> dict:
    return get_success_data(
        api_client.start_job(job_id, make_installer_operator_headers(installer_id))
    )


def complete_job(job_id: str, installer_id: str) -> dict:
    return get_success_data(
        api_client.complete_job(job_id, make_installer_operator_headers(installer_id))
    )


def rework_job(job_id: str, installer_id: str, action: str) -> dict:
    return get_success_data(
        api_client.rework_job(
            job_id,
            f.rework_payload(action),
            make_installer_operator_headers(installer_id),
        )
    )


def file_inspection(
    job_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> dict:
    return get_success_data(
        api_client.file_inspection(
            job_id, f.inspection_payload(**overrides), headers or AUDITOR
        )
    )


def create_warranty_claim(
    project_id: str, placement_id: str, failure_date: str, **overrides: Any
) -> dict:
    return get_success_data(
        api_client.create_warranty_claim(
            f.warranty_claim_payload(
                project_id, placement_id, failure_date, **overrides
            ),
            CLIENT,
        )
    )


def decide_claim(claim_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.decide_warranty_claim(
            claim_id, f.claim_decision_payload(decision), OFFICER
        )
    )


def retrofit_placement(
    placement_id: str, replacement_model_id: str, quantity: int = 1
) -> dict:
    return get_success_data(
        api_client.retrofit_placement(
            placement_id, f.retrofit_payload(replacement_model_id, quantity), CLIENT
        )
    )


# ==========================================================================
# Tier 1 — catalogue and project preconditions
# ==========================================================================
def setup_toddler_catalogue(**standard_overrides: Any) -> Dict[str, Any]:
    """An ACTIVE edition plus four CERTIFIED TODDLER_6_23M models.

    Returns {"standard", "post", "deck", "slide", "climber"}.  Every model's
    deck_height_cm sits at or below the edition's toddler ceiling, so all four
    certify cleanly.
    """
    standard = create_active_standard(**standard_overrides)
    post = create_certified_model(f.post_model_payload())
    deck = create_certified_model(f.deck_model_payload())
    slide = create_certified_model(f.slide_model_payload())
    climber = create_certified_model(f.climber_model_payload())
    return {
        "standard": standard,
        "post": post,
        "deck": deck,
        "slide": slide,
        "climber": climber,
    }


def setup_project_with_toddler_area(
    project_overrides: Optional[Dict[str, Any]] = None,
    area_overrides: Optional[Dict[str, Any]] = None,
    **standard_overrides: Any,
) -> Dict[str, Any]:
    """ACTIVE edition + certified catalogue + a CONSULTATION project with one
    TODDLER_6_23M play area.

    Returns the catalogue dict extended with "project" and "area".
    """
    catalogue = setup_toddler_catalogue(**standard_overrides)
    project = create_project_in_consultation(**(project_overrides or {}))
    area = create_play_area(project["id"], **(area_overrides or {}))
    catalogue["project"] = project
    catalogue["area"] = area
    return catalogue


def setup_two_area_project(
    project_overrides: Optional[Dict[str, Any]] = None,
    toddler_area_overrides: Optional[Dict[str, Any]] = None,
    preschool_area_overrides: Optional[Dict[str, Any]] = None,
    **standard_overrides: Any,
) -> Dict[str, Any]:
    """A CONSULTATION project with a TODDLER_6_23M and a PRESCHOOL_2_5 area,
    plus one certified model per band.  Used by the cross-area age-group
    separation checks.

    Returns {"standard", "toddler_post", "preschool_post", "project",
    "toddler_area", "preschool_area"}.
    """
    standard = create_active_standard(**standard_overrides)
    toddler_post = create_certified_model(f.post_model_payload())
    preschool_post = create_certified_model(
        f.post_model_payload(
            sku="POST-PS-120", age_group="PRESCHOOL_2_5", use_zone_footprint_cm=30
        )
    )
    defaults = {"required_age_groups": ["TODDLER_6_23M", "PRESCHOOL_2_5"]}
    defaults.update(project_overrides or {})
    project = create_project_in_consultation(**defaults)
    toddler_defaults = {"age_group": "TODDLER_6_23M", "axis_origin_cm": 0, "axis_length_cm": 1000}
    toddler_defaults.update(toddler_area_overrides or {})
    preschool_defaults = {
        "age_group": "PRESCHOOL_2_5",
        "axis_origin_cm": 1000,
        "axis_length_cm": 1000,
    }
    preschool_defaults.update(preschool_area_overrides or {})
    toddler_area = create_play_area(project["id"], **toddler_defaults)
    preschool_area = create_play_area(project["id"], **preschool_defaults)
    return {
        "standard": standard,
        "toddler_post": toddler_post,
        "preschool_post": preschool_post,
        "project": project,
        "toddler_area": toddler_area,
        "preschool_area": preschool_area,
    }


def setup_draft_successor(effective_from: str = "2024-06-01", **overrides: Any) -> dict:
    """A DRAFT edition whose effective_from is already reached, ready to be
    nominated as a successor."""
    defaults = {
        "code": "ASTM_F1487",
        "edition_year": 2027,
        "effective_from": effective_from,
    }
    defaults.update(overrides)
    return register_standard(**defaults)


# ==========================================================================
# Tier 2 — a priced three-placement design
# ==========================================================================
def setup_three_placement_design(
    non_default_colors: bool = True,
    project_overrides: Optional[Dict[str, Any]] = None,
    area_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A CONSULTATION project holding three VALIDATED placements and one ISSUED
    rendering, validated bottom-up (post, deck, then the slide bolted to the
    deck).

    Geometry: post anchored at 200 (footprint 30), deck at 700 (footprint 183),
    slide at 1300 (footprint 183 plus 122 cm of run-out), all inside the area's
    half-open interval 0..2000.  Quantities are 3 / 1 / 1, so priced_unit_count
    is 5.

    Returns {"standard", "post", "deck", "slide", "climber", "project", "area",
    "post_placement", "deck_placement", "slide_placement", "rendering"}.
    """
    scenario = setup_project_with_toddler_area(
        project_overrides=project_overrides, area_overrides=area_overrides
    )
    area_id = scenario["area"]["id"]
    post_colour = "FOREST_GREEN" if non_default_colors else "CEDAR"
    deck_colour = "SKY_BLUE" if non_default_colors else "CEDAR"
    slide_colour = "CRIMSON" if non_default_colors else "YELLOW"

    post_placement = create_placement(
        area_id, scenario["post"]["id"], color_choice=post_colour, x_start_cm=200, quantity=3
    )
    deck_placement = create_placement(
        area_id, scenario["deck"]["id"], color_choice=deck_colour, x_start_cm=700, quantity=1
    )
    post_placement = validate_placement(post_placement["id"])
    deck_placement = validate_placement(deck_placement["id"])
    slide_placement = create_placement(
        area_id,
        scenario["slide"]["id"],
        color_choice=slide_colour,
        x_start_cm=1300,
        quantity=1,
        attached_to_placement_id=deck_placement["id"],
    )
    slide_placement = validate_placement(slide_placement["id"])
    rendering = issue_rendering(scenario["project"]["id"], scenario["standard"]["id"])

    scenario.update(
        {
            "post_placement": post_placement,
            "deck_placement": deck_placement,
            "slide_placement": slide_placement,
            "rendering": rendering,
        }
    )
    return scenario


def setup_single_placement_design(
    model_key: str = "climber",
    project_overrides: Optional[Dict[str, Any]] = None,
    area_overrides: Optional[Dict[str, Any]] = None,
    placement_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A CONSULTATION project holding exactly one VALIDATED placement plus an
    ISSUED rendering.  `model_key` selects which catalogue model is placed.

    Returns the catalogue dict extended with "project", "area", "placement",
    "rendering".
    """
    scenario = setup_project_with_toddler_area(
        project_overrides=project_overrides, area_overrides=area_overrides
    )
    overrides = {"color_choice": scenario[model_key]["color_options"][0], "x_start_cm": 400}
    overrides.update(placement_overrides or {})
    placement = create_validated_placement(
        scenario["area"]["id"], scenario[model_key]["id"], **overrides
    )
    rendering = issue_rendering(scenario["project"]["id"], scenario["standard"]["id"])
    scenario["placement"] = placement
    scenario["rendering"] = rendering
    return scenario


# ==========================================================================
# Tier 3 — design lifecycle shortcuts
# ==========================================================================
APPROVE_VOTES = (15, 10)   # 15 of 25 ballots == exactly 60.0 percent
REVISE_VOTES = (10, 15)    # 10 of 25 ballots == 40.0 percent


def setup_reviewed_design(
    yes_votes: int = APPROVE_VOTES[0],
    no_votes: int = APPROVE_VOTES[1],
    scenario: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Take a three-placement design through a closed community review.

    The default tally is 15 yes / 10 no — turnout 25, exactly 60.0 percent, so
    the approve branch runs.  Pass REVISE_VOTES for the revise branch.

    Returns the scenario dict with "project" refreshed to the post-close row and
    "rendering" refreshed to its post-close status.
    """
    scenario = scenario or setup_three_placement_design()
    record_votes(scenario["rendering"]["id"], yes_votes, no_votes)
    project = close_review(scenario["rendering"]["id"])
    scenario["project"] = project
    scenario["rendering"] = get_rendering(scenario["rendering"]["id"])
    return scenario


def setup_design_approved_project(
    scenario: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A project sitting in DESIGN_APPROVED with its rendering still ISSUED."""
    return setup_reviewed_design(
        APPROVE_VOTES[0], APPROVE_VOTES[1], scenario=scenario
    )


def setup_certified_project(
    scenario: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A project advanced to design_status CERTIFIED / compliance_status COMPLIANT."""
    scenario = setup_design_approved_project(scenario)
    scenario["project"] = certify_compliance(scenario["project"]["id"])
    return scenario


def setup_ordered_project(
    pledge_amount_cents: int = 500000,
    scenario: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full run through to an ORDERED project with a CREATED ManufacturingOrder.

    Collects one pledge, issues and accepts a FIRM quote, then raises the order.
    Returns the scenario dict extended with "pledge", "quote" and "order", and
    with "project" and "area" refreshed (the area is LOCKED once ordered).
    """
    scenario = setup_certified_project(scenario)
    project_id = scenario["project"]["id"]
    pledge = create_pledge(project_id, amount_cents=pledge_amount_cents)
    pledge = collect_pledge(pledge["id"])
    quote = issue_quote(project_id, scenario["rendering"]["id"], variant="FIRM")
    quote = accept_quote(quote["id"])
    order = create_order(quote["id"])
    scenario["pledge"] = pledge
    scenario["quote"] = quote
    scenario["order"] = order
    scenario["project"] = get_project(project_id)
    scenario["area"] = get_play_area(scenario["area"]["id"])
    return scenario


def setup_order_in_production(
    scenario: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """An ORDERED project whose order has been moved to IN_PRODUCTION, which is
    the fork after which both prep dimensions become writable."""
    scenario = setup_ordered_project(scenario=scenario)
    scenario["order"] = start_production(scenario["order"]["id"])
    return scenario


# ==========================================================================
# Tier 4 — installer bookings and the installation lifecycle
# ==========================================================================
def setup_job_scheduled(
    scenario: Optional[Dict[str, Any]] = None,
    installer_overrides: Optional[Dict[str, Any]] = None,
    job_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """An ORDERED project with one ACTIVE installer and one SCHEDULED job.

    Default window 2026-08-10 .. 2026-08-12 with crew_size 4, so
    booked_crew_days is 12.  Returns the scenario dict extended with
    "installer" and "job".
    """
    scenario = setup_ordered_project(scenario=scenario)
    installer = create_installer(**(installer_overrides or {}))
    job = book_job(scenario["order"]["id"], installer["id"], **(job_overrides or {}))
    scenario["installer"] = get_installer(installer["id"])
    scenario["job"] = job
    return scenario


def setup_job_in_progress(
    scenario: Optional[Dict[str, Any]] = None,
    start_on: str = "2026-08-10",
    **kwargs: Any,
) -> Dict[str, Any]:
    """A SCHEDULED job started by its own installer on its first startable day."""
    scenario = setup_job_scheduled(scenario=scenario, **kwargs)
    set_clock_to_date(start_on)
    scenario["job"] = start_job(scenario["job"]["id"], scenario["installer"]["id"])
    return scenario


def setup_job_inspection_pending(
    scenario: Optional[Dict[str, Any]] = None,
    start_on: str = "2026-08-10",
    **kwargs: Any,
) -> Dict[str, Any]:
    """A job reported finished and handed to the auditors (INSPECTION_PENDING)."""
    scenario = setup_job_in_progress(scenario=scenario, start_on=start_on, **kwargs)
    scenario["job"] = complete_job(
        scenario["job"]["id"], scenario["installer"]["id"]
    )
    return scenario


def setup_installed_project(
    scenario: Optional[Dict[str, Any]] = None,
    installed_on: str = "2026-08-15",
    surfacing_depth_measured_cm: int = 30,
    inspector_headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """An INSTALL_INSPECTION PASS filed on the given date.

    Leaves the job in AUDIT_PENDING, the project in design_status INSTALLED with
    installed_on set to `installed_on`, and the job's install_inspector_user_id
    recorded as the filing auditor.  Returns the scenario dict extended with
    "inspection" and with "project" and "job" refreshed.
    """
    scenario = setup_job_inspection_pending(scenario=scenario, **kwargs)
    set_clock_to_date(installed_on)
    inspection = file_inspection(
        scenario["job"]["id"],
        inspector_headers or AUDITOR,
        kind="INSTALL_INSPECTION",
        result="PASS",
        surfacing_depth_measured_cm=surfacing_depth_measured_cm,
    )
    scenario["inspection"] = inspection
    scenario["job"] = get_job(scenario["job"]["id"])
    scenario["project"] = get_project(scenario["project"]["id"])
    return scenario


def setup_job_audit_pending(
    scenario: Optional[Dict[str, Any]] = None, **kwargs: Any
) -> Dict[str, Any]:
    """Alias for the state an INSTALL_INSPECTION PASS leaves behind: the job is
    in AUDIT_PENDING and the project is INSTALLED."""
    return setup_installed_project(scenario=scenario, **kwargs)


def setup_job_inspection_failed(
    scenario: Optional[Dict[str, Any]] = None,
    fail_on: str = "2026-08-15",
    **kwargs: Any,
) -> Dict[str, Any]:
    """An INSTALL_INSPECTION FAIL filed, leaving the job in INSPECTION_FAILED
    with last_failed_inspection_kind INSTALL_INSPECTION."""
    scenario = setup_job_inspection_pending(scenario=scenario, **kwargs)
    set_clock_to_date(fail_on)
    scenario["inspection"] = file_inspection(
        scenario["job"]["id"],
        AUDITOR,
        kind="INSTALL_INSPECTION",
        result="FAIL",
        deficiency_count=3,
    )
    scenario["job"] = get_job(scenario["job"]["id"])
    return scenario


def setup_audit_passed(
    scenario: Optional[Dict[str, Any]] = None,
    audit_on: str = "2026-08-20",
    **kwargs: Any,
) -> Dict[str, Any]:
    """A POST_INSTALL_AUDIT PASS filed by a second auditor.

    The audit is filed by AUDITOR_2 because the auditor recorded in the job's
    install_inspector_user_id is permanently barred from auditing that job.
    """
    scenario = setup_installed_project(scenario=scenario, **kwargs)
    set_clock_to_date(audit_on)
    scenario["audit"] = file_inspection(
        scenario["job"]["id"],
        AUDITOR_2,
        kind="POST_INSTALL_AUDIT",
        result="PASS",
    )
    scenario["job"] = get_job(scenario["job"]["id"])
    scenario["project"] = get_project(scenario["project"]["id"])
    scenario["installer"] = get_installer(scenario["installer"]["id"])
    return scenario


def setup_audit_failed(
    scenario: Optional[Dict[str, Any]] = None,
    audit_on: str = "2026-08-20",
    **kwargs: Any,
) -> Dict[str, Any]:
    """A POST_INSTALL_AUDIT FAIL filed by a second auditor, firing the four-hop
    cascade: job AUDIT_FAILED, project NON_COMPLIANT, installer SUSPENDED with
    open_audit_failures 1, and the installer's other open jobs CANCELLED."""
    scenario = setup_installed_project(scenario=scenario, **kwargs)
    set_clock_to_date(audit_on)
    scenario["audit"] = file_inspection(
        scenario["job"]["id"],
        AUDITOR_2,
        kind="POST_INSTALL_AUDIT",
        result="FAIL",
        deficiency_count=4,
    )
    scenario["job"] = get_job(scenario["job"]["id"])
    scenario["project"] = get_project(scenario["project"]["id"])
    scenario["installer"] = get_installer(scenario["installer"]["id"])
    return scenario


def book_second_job(
    scenario: Dict[str, Any],
    scheduled_start_date: str,
    scheduled_end_date: str,
    crew_size: int = 2,
) -> dict:
    """Book a second phased job on the same order and installer.

    The PRD allows an order to carry several phased jobs, so this exercises the
    overlap, travel-buffer and crew-capacity checks against the installer's
    other bookings.
    """
    return book_job(
        scenario["order"]["id"],
        scenario["installer"]["id"],
        scheduled_start_date=scheduled_start_date,
        scheduled_end_date=scheduled_end_date,
        crew_size=crew_size,
    )


# ==========================================================================
# Tier 5 — supersession, decertification and retrofit targeting
# ==========================================================================
def setup_needs_recertification_placement(
    successor_effective_from: str = "2024-06-01",
    replacement_overrides: Optional[Dict[str, Any]] = None,
    project_overrides: Optional[Dict[str, Any]] = None,
    area_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Drive a VALIDATED placement into NEEDS_RECERTIFICATION via a supersession,
    then publish a CERTIFIED replacement that supersedes its model.

    Steps: register and activate edition one; certify a METAL_CLIMBER model;
    open a project in CONSULTATION with one TODDLER_6_23M area holding one
    VALIDATED placement of that model; register a DRAFT successor edition whose
    effective_from is already reached; supersede edition one, which decertifies
    the model, demotes the placement and sets the project's compliance_status to
    RETROFIT_REQUIRED; finally add a replacement model whose
    supersedes_model_id names the original and certify it against edition two.

    Returns {"standard", "successor", "model", "replacement", "project", "area",
    "placement"}.
    """
    standard = create_active_standard()
    model = create_certified_model(f.climber_model_payload())
    project = create_project_in_consultation(**(project_overrides or {}))
    area = create_play_area(project["id"], **(area_overrides or {}))
    placement = create_validated_placement(
        area["id"], model["id"], color_choice="GRAPHITE", x_start_cm=400
    )
    successor = setup_draft_successor(effective_from=successor_effective_from)
    supersede_standard(standard["id"], successor["id"])

    replacement_defaults = {
        "sku": "CLIMB-MTL-122-R2",
        "supersedes_model_id": model["id"],
    }
    replacement_defaults.update(replacement_overrides or {})
    replacement = create_certified_model(f.climber_model_payload(**replacement_defaults))

    return {
        "standard": get_success_data(api_client.get_standard(standard["id"], OFFICER)),
        "successor": get_success_data(api_client.get_standard(successor["id"], OFFICER)),
        "model": get_success_data(api_client.get_component_model(model["id"], ADMIN)),
        "replacement": replacement,
        "project": get_project(project["id"]),
        "area": get_play_area(area["id"]),
        "placement": get_placement(placement["id"]),
    }


def setup_placement_for_parts_purchase(
    model_payload: Optional[Dict[str, Any]] = None,
    project_overrides: Optional[Dict[str, Any]] = None,
    area_overrides: Optional[Dict[str, Any]] = None,
    placement_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One VALIDATED placement whose own model may be bought as a replacement
    part, with no supersession involved.

    Returns {"standard", "model", "project", "area", "placement"}.
    """
    standard = create_active_standard()
    model = create_certified_model(model_payload or f.climber_model_payload())
    project = create_project_in_consultation(**(project_overrides or {}))
    area = create_play_area(project["id"], **(area_overrides or {}))
    overrides = {"color_choice": model["color_options"][0], "x_start_cm": 400}
    overrides.update(placement_overrides or {})
    placement = create_validated_placement(area["id"], model["id"], **overrides)
    return {
        "standard": standard,
        "model": model,
        "project": project,
        "area": get_play_area(area["id"]),
        "placement": placement,
    }


def setup_submitted_claim(
    failure_date: str,
    claim_on: str,
    model_key: str = "climber",
    quantity: int = 1,
    installed_on: str = "2026-08-15",
) -> Dict[str, Any]:
    """An installed project with one SUBMITTED WarrantyClaim against a placement.

    The logical clock is moved to `claim_on` before the claim is filed, so
    `failure_date` must lie between installed_on and claim_on inclusive.
    Returns the installed scenario extended with "claim".
    """
    scenario = setup_installed_project(installed_on=installed_on)
    set_clock_to_date(claim_on)
    placement_key = {
        "post": "post_placement",
        "deck": "deck_placement",
        "slide": "slide_placement",
    }.get(model_key, "slide_placement")
    scenario["claim"] = create_warranty_claim(
        scenario["project"]["id"],
        scenario[placement_key]["id"],
        failure_date,
        quantity=quantity,
    )
    return scenario
