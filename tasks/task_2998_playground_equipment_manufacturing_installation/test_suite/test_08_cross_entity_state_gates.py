"""Gates a request fails because of the state of a neighbouring entity.

Compliance certification is refused when the edition the project's rendering
pinned has since been retired, and a scheduled job cannot be started while the
company booked to do the work is suspended — in both cases the request itself is
well formed and the blocking state lives on another row entirely.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    make_installer_operator_headers,
    validate_error,
    validate_success,
)
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


# ==========================================================================
# Certification against an edition a supersession has retired
# ==========================================================================
def _setup_design_approved_project(catalogue: dict, client_name: str) -> dict:
    """A DESIGN_APPROVED project with one VALIDATED deck and an ISSUED rendering.

    The rendering pins the catalogue's ACTIVE edition, and the review closes on
    15 yes votes to 10 no votes, which is exactly the inclusive 60.0-percent
    approval threshold.
    """
    project = fx.create_project_in_consultation(client_name=client_name)
    area = fx.create_play_area(project["id"])
    placement = fx.create_validated_placement(
        area["id"],
        catalogue["deck"]["id"],
        color_choice="SKY_BLUE",
        x_start_cm=700,
        quantity=1,
    )
    rendering = fx.issue_rendering(project["id"], catalogue["standard"]["id"])
    fx.record_votes(rendering["id"], fx.APPROVE_VOTES[0], fx.APPROVE_VOTES[1])
    project = fx.close_review(rendering["id"])
    return {
        "project": project,
        "area": area,
        "placement": placement,
        "rendering": fx.get_rendering(rendering["id"]),
    }


def _get_standard(standard_id: str) -> dict:
    return validate_success(api_client.get_standard(standard_id, fx.OFFICER), 200)


def test_certification_succeeds_while_the_pinned_edition_is_still_active():
    """A DESIGN_APPROVED project whose pinned edition is still ACTIVE certifies and becomes COMPLIANT.

    PRD: "A successful certification advances both project dimensions at once: `design_status` moves `DESIGN_APPROVED → CERTIFIED` and `compliance_status` moves to `COMPLIANT`, and the project's `version` is incremented by one."

    Design: Difficulty/cross_entity_state_dependency/project_certification_blocked_when_pinned_standard_superseded
    """
    catalogue = fx.setup_toddler_catalogue()
    scenario = _setup_design_approved_project(catalogue, "Cedar Hollow School")
    project = scenario["project"]

    assert project["design_status"] == "DESIGN_APPROVED", (
        f"expected DESIGN_APPROVED, got {project['design_status']} before certification"
    )
    assert _get_standard(catalogue["standard"]["id"])["status"] == "ACTIVE", (
        "the pinned edition must still be ACTIVE for the control certification"
    )

    certified = validate_success(
        api_client.certify_compliance(project["id"], fx.OFFICER), 200
    )
    a.assert_project(certified)
    assert certified["design_status"] == "CERTIFIED", (
        f"expected CERTIFIED, got {certified['design_status']} after certification"
    )
    assert certified["compliance_status"] == "COMPLIANT", (
        f"expected COMPLIANT, got {certified['compliance_status']} after certification"
    )
    assert certified["version"] == project["version"] + 1, (
        f"expected version {project['version'] + 1}, got {certified['version']}"
    )


def test_certification_is_refused_once_the_pinned_edition_has_been_superseded():
    """The edition the rendering pinned is retired, so certification reports the inactive-edition gate rather than the demoted placements.

    PRD: "The rendering of the project still in `ISSUED` status must have a `pinned_standard_id` whose edition is *still* `ACTIVE` — if a supersession has moved on since the rendering was drawn, certification is refused with `ERR_STANDARD_NOT_ACTIVE`, which is the mechanism that catches the `DESIGN_APPROVED` project hop three deliberately spared."
    PRD: "The `DESIGN_APPROVED` project keeps its `ISSUED` rendering — which now pins an edition that is no longer `ACTIVE`, so its later attempt at compliance certification will fail with `ERR_STANDARD_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/project_certification_blocked_when_pinned_standard_superseded
    """
    catalogue = fx.setup_toddler_catalogue()
    scenario = _setup_design_approved_project(catalogue, "Cedar Hollow School")
    project_id = scenario["project"]["id"]
    original_standard_id = catalogue["standard"]["id"]

    successor = fx.setup_draft_successor(effective_from="2026-01-01")
    fx.supersede_standard(original_standard_id, successor["id"])

    assert _get_standard(original_standard_id)["status"] == "SUPERSEDED", (
        "the pinned edition must be retired before the certification attempt"
    )
    rendering = fx.get_rendering(scenario["rendering"]["id"])
    assert rendering["pinned_standard_id"] == original_standard_id, (
        "the pin is never rewritten by a later supersession"
    )
    assert rendering["status"] == "ISSUED", (
        f"expected ISSUED, got {rendering['status']}; the spared project keeps its rendering"
    )
    project_before = fx.get_project(project_id)
    assert project_before["design_status"] == "DESIGN_APPROVED", (
        f"expected DESIGN_APPROVED, got {project_before['design_status']} after the cascade"
    )

    response = api_client.certify_compliance(project_id, fx.OFFICER)
    validate_error(response, ApiErrorId.ERR_STANDARD_NOT_ACTIVE.value, 409)

    project_after = fx.get_project(project_id)
    assert project_after["design_status"] == "DESIGN_APPROVED", (
        f"expected DESIGN_APPROVED, got {project_after['design_status']} "
        "after the refused certification"
    )
    assert project_after["compliance_status"] == project_before["compliance_status"], (
        f"expected {project_before['compliance_status']}, got "
        f"{project_after['compliance_status']} after the refused certification"
    )
    assert project_after["version"] == project_before["version"], (
        f"expected version {project_before['version']}, got {project_after['version']} "
        "after the refused certification"
    )


def test_supersession_reverts_the_certified_project_but_spares_the_design_approved_one():
    """One supersession demotes both projects' placements, yet only the CERTIFIED project loses its design status and its rendering.

    PRD: "**Hop two:** because those models are now decertified, every `ComponentPlacement` whose `component_model_id` is one of them moves to `NEEDS_RECERTIFICATION`, provided its own `status` was `DRAFT` or `VALIDATED` and its owning project's `design_status` is one of `CONSULTATION`, `RENDERED`, `COMMUNITY_REVIEW`, `REVISION_REQUESTED`, `DESIGN_APPROVED`, `CERTIFIED` or `ORDERED`."
    PRD: "A project already sitting in `DESIGN_APPROVED` is a deliberate exception: its community sign-off is preserved and its `design_status` is *not* reverted, though its `compliance_status` still becomes `RETROFIT_REQUIRED`."
    PRD: "**Hop four:** for exactly those projects whose `design_status` hop three reverted to `REVISION_REQUESTED`, every `DesignRendering` of theirs in `ISSUED` status moves to `SUPERSEDED` and every `Quote` of theirs in `ISSUED` status moves to `EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/project_certification_blocked_when_pinned_standard_superseded
    """
    catalogue = fx.setup_toddler_catalogue()
    spared = _setup_design_approved_project(catalogue, "Cedar Hollow School")
    certified_scenario = _setup_design_approved_project(catalogue, "Dogwood Lane School")

    certified = validate_success(
        api_client.certify_compliance(certified_scenario["project"]["id"], fx.OFFICER),
        200,
    )
    assert certified["design_status"] == "CERTIFIED", (
        f"expected CERTIFIED, got {certified['design_status']} before the supersession"
    )

    successor = fx.setup_draft_successor(effective_from="2026-01-01")
    fx.supersede_standard(catalogue["standard"]["id"], successor["id"])

    assert _get_standard(successor["id"])["status"] == "ACTIVE", (
        "the successor edition must be promoted atomically"
    )

    spared_project = fx.get_project(spared["project"]["id"])
    assert spared_project["design_status"] == "DESIGN_APPROVED", (
        f"expected DESIGN_APPROVED, got {spared_project['design_status']} for the spared project"
    )
    assert spared_project["compliance_status"] == "RETROFIT_REQUIRED", (
        f"expected RETROFIT_REQUIRED, got {spared_project['compliance_status']} "
        "for the spared project"
    )
    assert fx.get_rendering(spared["rendering"]["id"])["status"] == "ISSUED", (
        "the spared project keeps its ISSUED rendering"
    )

    reverted_project = fx.get_project(certified_scenario["project"]["id"])
    assert reverted_project["design_status"] == "REVISION_REQUESTED", (
        f"expected REVISION_REQUESTED, got {reverted_project['design_status']} "
        "for the certified project"
    )
    assert reverted_project["compliance_status"] == "RETROFIT_REQUIRED", (
        f"expected RETROFIT_REQUIRED, got {reverted_project['compliance_status']} "
        "for the certified project"
    )
    assert (
        fx.get_rendering(certified_scenario["rendering"]["id"])["status"] == "SUPERSEDED"
    ), "hop four retires the reverted project's ISSUED rendering"

    for label, scenario in (("spared", spared), ("reverted", certified_scenario)):
        placement = fx.get_placement(scenario["placement"]["id"])
        assert placement["status"] == "NEEDS_RECERTIFICATION", (
            f"expected NEEDS_RECERTIFICATION, got {placement['status']} "
            f"for the {label} project's placement"
        )


# ==========================================================================
# Starting a job whose installer has been administratively suspended
# ==========================================================================
def _setup_startable_job() -> dict:
    """A SCHEDULED job on its first startable day, booked with an ACTIVE installer.

    The window is 2026-08-06 to 2026-08-08 with a crew of 4, so the job books 12
    crew days, and the logical clock is moved to the window's first day.
    """
    scenario = fx.setup_job_scheduled(
        job_overrides={
            "scheduled_start_date": "2026-08-06",
            "scheduled_end_date": "2026-08-08",
            "crew_size": 4,
        }
    )
    fx.set_clock_to_date("2026-08-06")
    return scenario


def _set_status(installer_id: str, status: str) -> dict:
    """Drive the installer's membership status as the admin and return the row."""
    return validate_success(
        api_client.set_installer_status(
            installer_id, f.installer_status_payload(status), fx.ADMIN
        ),
        200,
    )


def test_administrative_suspension_leaves_the_scheduled_booking_in_place():
    """Suspending the installer cancels nothing: the job stays SCHEDULED and the crew-day ledger is unchanged.

    PRD: "An *administrative* suspension moves the installer `ACTIVE → SUSPENDED` and does **not** cancel any existing booking; it only blocks the creation of new jobs and blocks a `SCHEDULED` job from being started."
    PRD: "An installer's `committed_crew_days` is the sum of `booked_crew_days` over every job booked with that installer whose `status` is **not** one of `AUDIT_PASSED`, `AUDIT_FAILED` or `CANCELLED`; a finished or cancelled job no longer occupies the calendar."

    Design: Difficulty/cross_entity_state_dependency/job_start_blocked_when_installer_suspended
    """
    scenario = _setup_startable_job()
    installer_id = scenario["installer"]["id"]
    job = scenario["job"]

    a.assert_installation_job(job)
    a.assert_booked_crew_days(job)
    assert job["booked_crew_days"] == 12, (
        f"expected 12, got {job['booked_crew_days']} for a crew of 4 over three days"
    )
    assert scenario["installer"]["committed_crew_days"] == 12, (
        f"expected 12, got {scenario['installer']['committed_crew_days']} before the suspension"
    )

    suspended = _set_status(installer_id, "SUSPENDED")
    a.assert_installer(suspended)
    assert suspended["status"] == "SUSPENDED", (
        f"expected SUSPENDED, got {suspended['status']}"
    )
    assert suspended["committed_crew_days"] == 12, (
        f"expected 12, got {suspended['committed_crew_days']}; an administrative "
        "suspension cancels no booking"
    )
    assert suspended["open_audit_failures"] == 0, (
        f"expected 0, got {suspended['open_audit_failures']} open audit failures"
    )
    assert fx.get_job(job["id"])["status"] == "SCHEDULED", (
        "the booking survives an administrative suspension"
    )


def test_job_start_is_blocked_while_the_installer_is_suspended():
    """The start is refused because of the installer's status, not anything about the job itself.

    PRD: "Starting the job moves it `SCHEDULED → IN_PROGRESS` under three further conditions: the installer's own `status` must be `ACTIVE`, or the start is refused with `ERR_INSTALLER_NOT_ACTIVE`"
    PRD: "An *administrative* suspension moves the installer `ACTIVE → SUSPENDED` and does **not** cancel any existing booking; it only blocks the creation of new jobs and blocks a `SCHEDULED` job from being started."

    Design: Difficulty/cross_entity_state_dependency/job_start_blocked_when_installer_suspended
    """
    scenario = _setup_startable_job()
    installer_id = scenario["installer"]["id"]
    job_id = scenario["job"]["id"]

    _set_status(installer_id, "SUSPENDED")

    response = api_client.start_job(job_id, make_installer_operator_headers(installer_id))
    validate_error(response, ApiErrorId.ERR_INSTALLER_NOT_ACTIVE.value, 409)

    job_after = fx.get_job(job_id)
    assert job_after["status"] == "SCHEDULED", (
        f"expected SCHEDULED, got {job_after['status']} after the refused start"
    )
    assert job_after["version"] == scenario["job"]["version"], (
        f"expected version {scenario['job']['version']}, got {job_after['version']} "
        "after the refused start"
    )
    installer_after = fx.get_installer(installer_id)
    assert installer_after["committed_crew_days"] == 12, (
        f"expected 12, got {installer_after['committed_crew_days']} after the refused start"
    )


def test_reinstating_the_installer_lets_the_identical_start_succeed():
    """Reinstatement is admitted with no open audit failures, and the same start call then moves the job to IN_PROGRESS.

    PRD: "Reinstatement moves `SUSPENDED → ACTIVE` but only while `open_audit_failures` is 0; while any audit failure remains open the reinstatement is refused with `ERR_AUDIT_FAILURES_OPEN`."
    PRD: "Starting the job moves it `SCHEDULED → IN_PROGRESS` under three further conditions: the installer's own `status` must be `ACTIVE`, or the start is refused with `ERR_INSTALLER_NOT_ACTIVE`"

    Design: Difficulty/cross_entity_state_dependency/job_start_blocked_when_installer_suspended
    """
    scenario = _setup_startable_job()
    installer_id = scenario["installer"]["id"]
    job_id = scenario["job"]["id"]
    operator_headers = make_installer_operator_headers(installer_id)

    _set_status(installer_id, "SUSPENDED")
    validate_error(
        api_client.start_job(job_id, operator_headers),
        ApiErrorId.ERR_INSTALLER_NOT_ACTIVE.value,
        409,
    )

    reinstated = _set_status(installer_id, "ACTIVE")
    assert reinstated["status"] == "ACTIVE", (
        f"expected ACTIVE, got {reinstated['status']} after reinstatement"
    )
    assert reinstated["open_audit_failures"] == 0, (
        f"expected 0, got {reinstated['open_audit_failures']}; reinstatement requires none open"
    )

    started = validate_success(api_client.start_job(job_id, operator_headers), 200)
    a.assert_installation_job(started)
    assert started["status"] == "IN_PROGRESS", (
        f"expected IN_PROGRESS, got {started['status']} after the accepted start"
    )
    assert started["booked_crew_days"] == 12, (
        f"expected 12, got {started['booked_crew_days']}; starting rewrites no window"
    )

    installer_after = fx.get_installer(installer_id)
    assert installer_after["committed_crew_days"] == 12, (
        f"expected 12, got {installer_after['committed_crew_days']}; an IN_PROGRESS job "
        "still occupies the calendar"
    )
