"""Multi-hop cascades: a compliance edition change and a failed post-installation audit.

Each of the two triggers here is a single call whose consequences propagate
several hops along a chain of records, and the PRD requires every hop to be
visible the moment the trigger's response is returned.
"""

from test_helpers import (
    AUDITOR_2_USER_ID,
    TEST_USERS,
    api_client,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN_HEADERS = TEST_USERS["manufacturer_admin_headers"]
OFFICER_HEADERS = TEST_USERS["compliance_officer_headers"]
AUDITOR_HEADERS = TEST_USERS["safety_auditor_headers"]
AUDITOR_2_HEADERS = TEST_USERS["safety_auditor_2_headers"]


def _get_standard(standard_id: str) -> dict:
    return validate_success(api_client.get_standard(standard_id, OFFICER_HEADERS))


def _get_model(model_id: str) -> dict:
    return validate_success(api_client.get_component_model(model_id, ADMIN_HEADERS))


# ==========================================================================
# Superseding the ACTIVE edition: models, placements, project, rendering, quote
# ==========================================================================
def _setup_supersede_cascade() -> dict:
    """A RENDERED project with three VALIDATED placements certified against the
    ACTIVE edition, one ISSUED PROVISIONAL quote, and a DRAFT successor edition
    whose effective_from is already reached.
    """
    scenario = fx.setup_three_placement_design(
        project_overrides={"client_name": "Maple Grove School"}
    )
    scenario["quote"] = fx.issue_quote(
        scenario["project"]["id"], scenario["rendering"]["id"], variant="PROVISIONAL"
    )
    scenario["successor"] = fx.setup_draft_successor(
        effective_from="2026-01-01",
        min_use_zone_clearance_cm=213,
        requires_accessible_route=True,
    )
    return scenario


def test_supersede_retires_the_edition_and_promotes_the_successor():
    """The retiring edition records its successor and the successor is ACTIVE in the same breath.

    PRD: "When all three hold, the retiring edition takes `status` `ACTIVE → SUPERSEDED` and records the successor in its `superseded_by_standard_id`, while the successor is atomically promoted to `ACTIVE`, so the single-`ACTIVE` invariant never lapses even momentarily."

    Design: Difficulty/transitive_cascade/standard_supersede_cascades_to_decert_models_placements_project_and_quote
    """
    scenario = _setup_supersede_cascade()
    retiring_id = scenario["standard"]["id"]
    successor_id = scenario["successor"]["id"]

    retired = fx.supersede_standard(retiring_id, successor_id)
    assert retired["status"] == "SUPERSEDED", (
        f"expected SUPERSEDED, got {retired['status']} for the retired edition"
    )
    assert retired["superseded_by_standard_id"] == successor_id, (
        f"expected {successor_id}, got {retired['superseded_by_standard_id']} "
        "as the recorded successor"
    )

    successor = _get_standard(successor_id)
    assert successor["status"] == "ACTIVE", (
        f"expected ACTIVE, got {successor['status']} for the promoted successor"
    )


def test_supersede_decertifies_every_model_pinned_to_the_retired_edition():
    """All three models certified against the retired edition become DECERTIFIED while keeping their historical pin.

    PRD: "**Hop one:** because the retired edition no longer governs, every `ComponentModel` whose `certified_against_standard_id` points at it and whose `certification_status` is `CERTIFIED` moves `CERTIFIED → DECERTIFIED`; the historical pin in `certified_against_standard_id` is deliberately retained, so the record of what the model was once certified against survives."

    Design: Difficulty/transitive_cascade/standard_supersede_cascades_to_decert_models_placements_project_and_quote
    """
    scenario = _setup_supersede_cascade()
    retiring_id = scenario["standard"]["id"]

    fx.supersede_standard(retiring_id, scenario["successor"]["id"])

    for key in ("post", "deck", "slide"):
        model = _get_model(scenario[key]["id"])
        assert model["certification_status"] == "DECERTIFIED", (
            f"expected DECERTIFIED, got {model['certification_status']} "
            f"for the {key} model after its edition was retired"
        )

    deck = _get_model(scenario["deck"]["id"])
    assert deck["certified_against_standard_id"] == retiring_id, (
        f"expected the retained pin {retiring_id}, got {deck['certified_against_standard_id']}"
    )


def test_supersede_marks_every_placement_of_a_decertified_model_for_recertification():
    """The three VALIDATED placements of the decertified models move to NEEDS_RECERTIFICATION.

    PRD: "**Hop two:** because those models are now decertified, every `ComponentPlacement` whose `component_model_id` is one of them moves to `NEEDS_RECERTIFICATION`, provided its own `status` was `DRAFT` or `VALIDATED` and its owning project's `design_status` is one of `CONSULTATION`, `RENDERED`, `COMMUNITY_REVIEW`, `REVISION_REQUESTED`, `DESIGN_APPROVED`, `CERTIFIED` or `ORDERED`."

    Design: Difficulty/transitive_cascade/standard_supersede_cascades_to_decert_models_placements_project_and_quote
    """
    scenario = _setup_supersede_cascade()

    for key in ("post_placement", "deck_placement", "slide_placement"):
        assert scenario[key]["status"] == "VALIDATED", (
            f"expected VALIDATED, got {scenario[key]['status']} for the {key} before the trigger"
        )

    fx.supersede_standard(scenario["standard"]["id"], scenario["successor"]["id"])

    for key in ("post_placement", "deck_placement", "slide_placement"):
        placement = fx.get_placement(scenario[key]["id"])
        assert placement["status"] == "NEEDS_RECERTIFICATION", (
            f"expected NEEDS_RECERTIFICATION, got {placement['status']} for the {key}"
        )


def test_supersede_recomputes_the_emptied_areas_derived_geometry():
    """With every placement out of the input set the area reads a fall height of 0 and the 15 cm floor, while its specified depth is untouched.

    PRD: "After the hops, every play area touched by hop two has its `critical_fall_height_cm` and `required_surfacing_depth_cm` recomputed, because placements that have left `DRAFT` and `VALIDATED` also leave the input set of those two derived numbers."

    Design: Difficulty/transitive_cascade/standard_supersede_cascades_to_decert_models_placements_project_and_quote
    """
    scenario = _setup_supersede_cascade()
    area_id = scenario["area"]["id"]

    before = fx.get_play_area(area_id)
    assert before["critical_fall_height_cm"] == 122, (
        f"expected 122, got {before['critical_fall_height_cm']} while the placements still count"
    )
    assert before["required_surfacing_depth_cm"] == 28, (
        f"expected 28, got {before['required_surfacing_depth_cm']} while the placements still count"
    )

    fx.supersede_standard(scenario["standard"]["id"], scenario["successor"]["id"])

    after = fx.get_play_area(area_id)
    assert after["critical_fall_height_cm"] == 0, (
        f"expected 0, got {after['critical_fall_height_cm']} once no placement is DRAFT or VALIDATED"
    )
    assert after["required_surfacing_depth_cm"] == 15, (
        f"expected the 15 cm floor, got {after['required_surfacing_depth_cm']} for an emptied area"
    )
    assert after["surfacing_depth_cm"] == 30, (
        f"expected the specified 30, got {after['surfacing_depth_cm']} — the depth is an input, not derived"
    )


def test_supersede_flags_the_project_for_retrofit_and_reverts_it_to_revision_requested():
    """The owning project becomes RETROFIT_REQUIRED and, being RENDERED, is reverted to REVISION_REQUESTED without counting a community round.

    PRD: "**Hop three:** because those placements now need recertification, each owning `DesignProject` has its `compliance_status` set to `RETROFIT_REQUIRED`; and additionally, any such project whose `design_status` is `RENDERED`, `COMMUNITY_REVIEW` or `CERTIFIED` is reverted to `REVISION_REQUESTED`."

    Design: Difficulty/transitive_cascade/standard_supersede_cascades_to_decert_models_placements_project_and_quote
    """
    scenario = _setup_supersede_cascade()
    project_id = scenario["project"]["id"]

    before = fx.get_project(project_id)
    assert before["design_status"] == "RENDERED", (
        f"expected RENDERED, got {before['design_status']} before the edition was retired"
    )

    fx.supersede_standard(scenario["standard"]["id"], scenario["successor"]["id"])

    project = fx.get_project(project_id)
    assert project["compliance_status"] == "RETROFIT_REQUIRED", (
        f"expected RETROFIT_REQUIRED, got {project['compliance_status']} after the cascade"
    )
    assert project["design_status"] == "REVISION_REQUESTED", (
        f"expected REVISION_REQUESTED, got {project['design_status']} after the cascade"
    )
    assert project["revision_rounds"] == 0, (
        f"expected 0, got {project['revision_rounds']} — no community round closed here"
    )


def test_supersede_supersedes_the_rendering_and_expires_the_quote():
    """The reverted project's ISSUED rendering becomes SUPERSEDED and its ISSUED quote becomes EXPIRED.

    PRD: "**Hop four:** for exactly those projects whose `design_status` hop three reverted to `REVISION_REQUESTED`, every `DesignRendering` of theirs in `ISSUED` status moves to `SUPERSEDED` and every `Quote` of theirs in `ISSUED` status moves to `EXPIRED`."

    Design: Difficulty/transitive_cascade/standard_supersede_cascades_to_decert_models_placements_project_and_quote
    """
    scenario = _setup_supersede_cascade()

    assert scenario["rendering"]["status"] == "ISSUED", (
        f"expected ISSUED, got {scenario['rendering']['status']} before the trigger"
    )
    assert scenario["quote"]["status"] == "ISSUED", (
        f"expected ISSUED, got {scenario['quote']['status']} before the trigger"
    )

    fx.supersede_standard(scenario["standard"]["id"], scenario["successor"]["id"])

    rendering = fx.get_rendering(scenario["rendering"]["id"])
    assert rendering["status"] == "SUPERSEDED", (
        f"expected SUPERSEDED, got {rendering['status']} after the cascade"
    )
    quote = fx.get_quote(scenario["quote"]["id"])
    assert quote["status"] == "EXPIRED", (
        f"expected EXPIRED, got {quote['status']} after the cascade"
    )


# ==========================================================================
# A failed post-installation audit: job, project, installer, sibling job
# ==========================================================================
def _setup_audit_pending_with_a_second_scheduled_job() -> dict:
    """An installed project whose job A awaits its audit while job B of the same
    installer is still SCHEDULED.

    Job A books 2026-08-06 .. 2026-08-08 with a crew of 4 and job B books
    2026-08-10 .. 2026-08-11 with a crew of 2, leaving the clear travel day the
    booking rules demand between the two windows.
    """
    scenario = fx.setup_job_scheduled(
        job_overrides={
            "scheduled_start_date": "2026-08-06",
            "scheduled_end_date": "2026-08-08",
            "crew_size": 4,
        }
    )
    installer_id = scenario["installer"]["id"]
    job_a_id = scenario["job"]["id"]
    scenario["second_job"] = fx.book_second_job(
        scenario, "2026-08-10", "2026-08-11", crew_size=2
    )
    fx.set_clock_to_date("2026-08-06")
    fx.start_job(job_a_id, installer_id)
    fx.complete_job(job_a_id, installer_id)
    scenario["inspection"] = fx.file_inspection(
        job_a_id,
        AUDITOR_HEADERS,
        kind="INSTALL_INSPECTION",
        result="PASS",
        surfacing_depth_measured_cm=30,
    )
    scenario["job"] = fx.get_job(job_a_id)
    scenario["project"] = fx.get_project(scenario["project"]["id"])
    scenario["installer"] = fx.get_installer(installer_id)
    return scenario


def _fail_the_post_installation_audit(job_id: str) -> dict:
    """File the failing post-installation audit as the second auditor, who is not
    the one recorded as the install inspector."""
    return validate_success(
        api_client.file_inspection(
            job_id,
            f.inspection_payload(
                kind="POST_INSTALL_AUDIT", result="FAIL", deficiency_count=2
            ),
            AUDITOR_2_HEADERS,
        ),
        201,
    )


def test_failed_audit_record_is_attributed_to_the_second_auditor():
    """The audit record carries kind POST_INSTALL_AUDIT and the acting auditor's id.

    PRD: "The record's `job_id` comes from the request path, its `performed_by_user_id` is set from the acting `X-User-ID`, and its `sequence_number` is 1 for the job's first record and one greater than the highest existing sequence number thereafter."

    Design: Difficulty/transitive_cascade/audit_failure_cascades_to_project_noncompliance_installer_suspension_and_job_cancellation
    """
    scenario = _setup_audit_pending_with_a_second_scheduled_job()
    job_a_id = scenario["job"]["id"]

    audit = _fail_the_post_installation_audit(job_a_id)
    assert audit["kind"] == "POST_INSTALL_AUDIT", (
        f"expected POST_INSTALL_AUDIT, got {audit['kind']} for the filed audit"
    )
    assert audit["performed_by_user_id"] == AUDITOR_2_USER_ID, (
        f"expected {AUDITOR_2_USER_ID}, got {audit['performed_by_user_id']} as the acting auditor"
    )
    assert audit["job_id"] == job_a_id, (
        f"expected {job_a_id}, got {audit['job_id']} on the audit record"
    )


def test_failed_audit_moves_the_job_to_audit_failed():
    """Hop one takes the audited job from AUDIT_PENDING to AUDIT_FAILED and remembers which check failed.

    PRD: "Hop one: the record is created and the job moves `AUDIT_PENDING → AUDIT_FAILED` with `last_failed_inspection_kind` set to `POST_INSTALL_AUDIT`."

    Design: Difficulty/transitive_cascade/audit_failure_cascades_to_project_noncompliance_installer_suspension_and_job_cancellation
    """
    scenario = _setup_audit_pending_with_a_second_scheduled_job()
    job_a_id = scenario["job"]["id"]

    assert scenario["job"]["status"] == "AUDIT_PENDING", (
        f"expected AUDIT_PENDING, got {scenario['job']['status']} before the audit was filed"
    )

    _fail_the_post_installation_audit(job_a_id)

    job_a = fx.get_job(job_a_id)
    assert job_a["status"] == "AUDIT_FAILED", (
        f"expected AUDIT_FAILED, got {job_a['status']} after the failing audit"
    )
    assert job_a["last_failed_inspection_kind"] == "POST_INSTALL_AUDIT", (
        f"expected POST_INSTALL_AUDIT, got {job_a['last_failed_inspection_kind']}"
    )


def test_failed_audit_makes_the_project_non_compliant_without_touching_its_design_status():
    """Hop two flips the owning project to NON_COMPLIANT while it stays INSTALLED on its recorded installation date.

    PRD: "Hop two: because the job has failed its audit, the owning project's `compliance_status` becomes `NON_COMPLIANT` — note that its `design_status` is left alone, so a project can be `AUDITED`-bound yet non-compliant."

    Design: Difficulty/transitive_cascade/audit_failure_cascades_to_project_noncompliance_installer_suspension_and_job_cancellation
    """
    scenario = _setup_audit_pending_with_a_second_scheduled_job()

    assert scenario["project"]["design_status"] == "INSTALLED", (
        f"expected INSTALLED, got {scenario['project']['design_status']} after the passing inspection"
    )
    assert scenario["project"]["installed_on"] == "2026-08-06", (
        f"expected 2026-08-06, got {scenario['project']['installed_on']} as the installation date"
    )

    _fail_the_post_installation_audit(scenario["job"]["id"])

    project = fx.get_project(scenario["project"]["id"])
    assert project["compliance_status"] == "NON_COMPLIANT", (
        f"expected NON_COMPLIANT, got {project['compliance_status']} after the failing audit"
    )
    assert project["design_status"] == "INSTALLED", (
        f"expected INSTALLED, got {project['design_status']} — a failed audit never advances the project"
    )
    assert project["installed_on"] == "2026-08-06", (
        f"expected 2026-08-06, got {project['installed_on']} — unchanged by the failed audit"
    )


def test_failed_audit_suspends_the_installer_on_its_first_open_failure():
    """Hop three counts the failure and suspends the installer, because the threshold is one.

    PRD: "Hop three: because that project is now non-compliant, the installer's `open_audit_failures` is incremented, and the suspension threshold is **one** — a single failed post-installation audit is enough — so the installer's `status` becomes `SUSPENDED` as a compliance suspension."

    Design: Difficulty/transitive_cascade/audit_failure_cascades_to_project_noncompliance_installer_suspension_and_job_cancellation
    """
    scenario = _setup_audit_pending_with_a_second_scheduled_job()
    installer_id = scenario["installer"]["id"]

    assert scenario["installer"]["status"] == "ACTIVE", (
        f"expected ACTIVE, got {scenario['installer']['status']} before the audit"
    )
    assert scenario["installer"]["open_audit_failures"] == 0, (
        f"expected 0, got {scenario['installer']['open_audit_failures']} before the audit"
    )

    _fail_the_post_installation_audit(scenario["job"]["id"])

    installer = fx.get_installer(installer_id)
    assert installer["open_audit_failures"] == 1, (
        f"expected 1, got {installer['open_audit_failures']} after one failed audit"
    )
    assert installer["status"] == "SUSPENDED", (
        f"expected SUSPENDED, got {installer['status']} once the threshold of one was reached"
    )


def test_failed_audit_cancels_the_suspended_installers_other_scheduled_job():
    """Hop four cancels the installer's still-scheduled second job.

    PRD: "Hop four: because the installer is now compliance-suspended, every *other* job of that installer whose `status` is `SCHEDULED` or `IN_PROGRESS` moves to `CANCELLED`, and `committed_crew_days` is then recomputed over what remains."

    Design: Difficulty/transitive_cascade/audit_failure_cascades_to_project_noncompliance_installer_suspension_and_job_cancellation
    """
    scenario = _setup_audit_pending_with_a_second_scheduled_job()
    job_b_id = scenario["second_job"]["id"]

    assert scenario["second_job"]["status"] == "SCHEDULED", (
        f"expected SCHEDULED, got {scenario['second_job']['status']} for the second job"
    )

    _fail_the_post_installation_audit(scenario["job"]["id"])

    job_b = fx.get_job(job_b_id)
    assert job_b["status"] == "CANCELLED", (
        f"expected CANCELLED, got {job_b['status']} for the suspended installer's other job"
    )


def test_failed_audit_empties_the_installers_committed_crew_days():
    """The installer's committed crew-days fall from 16 to 0, because AUDIT_FAILED and CANCELLED both leave the calendar.

    PRD: "An installer's `committed_crew_days` is the sum of `booked_crew_days` over every job booked with that installer whose `status` is **not** one of `AUDIT_PASSED`, `AUDIT_FAILED` or `CANCELLED`; a finished or cancelled job no longer occupies the calendar."

    Design: Difficulty/transitive_cascade/audit_failure_cascades_to_project_noncompliance_installer_suspension_and_job_cancellation
    """
    scenario = _setup_audit_pending_with_a_second_scheduled_job()
    installer_id = scenario["installer"]["id"]

    assert scenario["installer"]["committed_crew_days"] == 16, (
        f"expected 16, got {scenario['installer']['committed_crew_days']} while both jobs are live"
    )

    _fail_the_post_installation_audit(scenario["job"]["id"])

    installer = fx.get_installer(installer_id)
    assert installer["committed_crew_days"] == 0, (
        f"expected 0, got {installer['committed_crew_days']} once both jobs left the calendar"
    )


def test_the_per_job_crew_day_ledgers_survive_the_cascade():
    """Each job keeps its own booked_crew_days of 12 and 4 even after the cascade empties the installer aggregate.

    PRD: "Each job contributes `booked_crew_days`, which is its `crew_size` multiplied by the inclusive day count of its booking window — the number of calendar days from `scheduled_start_date` to `scheduled_end_date` counting both ends, so a window whose two dates are equal counts as one day."

    Design: Difficulty/transitive_cascade/audit_failure_cascades_to_project_noncompliance_installer_suspension_and_job_cancellation
    """
    scenario = _setup_audit_pending_with_a_second_scheduled_job()
    job_a_id = scenario["job"]["id"]
    job_b_id = scenario["second_job"]["id"]

    _fail_the_post_installation_audit(job_a_id)

    job_a = fx.get_job(job_a_id)
    assert job_a["booked_crew_days"] == 12, (
        f"expected 12, got {job_a['booked_crew_days']} for a crew of 4 over three days"
    )
    job_b = fx.get_job(job_b_id)
    assert job_b["booked_crew_days"] == 4, (
        f"expected 4, got {job_b['booked_crew_days']} for a crew of 2 over two days"
    )
