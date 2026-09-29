"""Design revision cycles and the installation rework loop.

Both state machines exercised here are genuine cycles rather than ladders: a
design project re-enters a `design_status` it already occupied, and an
installation job loops back to the very check it failed — the first loop bounded
only by the community's verdict, the second bounded by a hard rework ceiling.
"""

from test_helpers import (
    AUDITOR_USER_ID,
    ApiErrorId,
    TEST_USERS,
    api_client,
    make_installer_operator_headers,
    validate_error,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

AUDITOR_HEADERS = TEST_USERS["safety_auditor_headers"]


# ==========================================================================
# The design revision cycle: RENDERED -> COMMUNITY_REVIEW ->
# REVISION_REQUESTED -> RENDERED
# ==========================================================================
def _setup_rendered_project_with_draft_deck() -> dict:
    """A project in `RENDERED` with one DRAFT deck placement and a round-1
    rendering pinned to the ACTIVE edition.

    The single placement is deliberately left in `DRAFT`: a rendering only needs
    each play area to hold one placement in `DRAFT` or `VALIDATED`.
    """
    scenario = fx.setup_project_with_toddler_area(
        project_overrides={"client_name": "Fernwood Commons"}
    )
    scenario["deck_placement"] = fx.create_placement(
        scenario["area"]["id"],
        scenario["deck"]["id"],
        color_choice="SKY_BLUE",
        x_start_cm=700,
        quantity=1,
    )
    scenario["rendering"] = fx.issue_rendering(
        scenario["project"]["id"], scenario["standard"]["id"]
    )
    return scenario


def test_revision_cycle_reenters_rendered_and_then_community_review():
    """A below-threshold review reopens the project, and the replacement rendering drives it back through RENDERED into COMMUNITY_REVIEW.

    PRD: "Because a project in `REVISION_REQUESTED` is editable again and may have a new rendering issued from it, the cycle `RENDERED → COMMUNITY_REVIEW → REVISION_REQUESTED → RENDERED` may run as many times as the community demands, each pass minting a rendering whose `round_number` is one higher than the last and incrementing `revision_rounds` once per completed round that ended in revision."

    Design: Difficulty/non_linear_state_machine/design_project_revision_cycle_reenters_rendered
    """
    scenario = _setup_rendered_project_with_draft_deck()
    project_id = scenario["project"]["id"]
    round_one = scenario["rendering"]

    project = fx.get_project(project_id)
    assert project["design_status"] == "RENDERED", (
        f"expected RENDERED, got {project['design_status']} once the first rendering was issued"
    )
    assert project["revision_rounds"] == 0, (
        f"expected 0, got {project['revision_rounds']} before any review closed"
    )

    fx.record_votes(round_one["id"], fx.REVISE_VOTES[0], fx.REVISE_VOTES[1])
    project = fx.get_project(project_id)
    assert project["design_status"] == "COMMUNITY_REVIEW", (
        f"expected COMMUNITY_REVIEW, got {project['design_status']} after the first vote batch"
    )

    project = fx.close_review(round_one["id"])
    assert project["design_status"] == "REVISION_REQUESTED", (
        f"expected REVISION_REQUESTED, got {project['design_status']} after closing a 40.0 percent review"
    )
    assert project["revision_rounds"] == 1, (
        f"expected 1, got {project['revision_rounds']} after one round ended in revision"
    )

    round_two = fx.issue_rendering(project_id, scenario["standard"]["id"])
    project = fx.get_project(project_id)
    assert project["design_status"] == "RENDERED", (
        f"expected RENDERED again, got {project['design_status']} after issuing the second rendering"
    )
    assert project["revision_rounds"] == 1, (
        f"expected 1, got {project['revision_rounds']} — issuing a rendering closes no round"
    )

    fx.record_votes(round_two["id"], 20, 5)
    project = fx.get_project(project_id)
    assert project["design_status"] == "COMMUNITY_REVIEW", (
        f"expected COMMUNITY_REVIEW again, got {project['design_status']} after the second vote batch"
    )
    assert project["revision_rounds"] == 1, (
        f"expected 1, got {project['revision_rounds']} while the second round is still open"
    )


def test_second_round_rendering_carries_round_number_two():
    """The replacement rendering is round 2 and ISSUED, while the withdrawn round-1 rendering keeps round_number 1.

    PRD: "A successful issuance creates a rendering in `ISSUED` status whose `round_number` is one greater than the highest `round_number` any previous rendering of the project holds, or 1 when this is the project's first."

    Design: Difficulty/non_linear_state_machine/design_project_revision_cycle_reenters_rendered
    """
    scenario = _setup_rendered_project_with_draft_deck()
    project_id = scenario["project"]["id"]
    round_one = scenario["rendering"]

    assert round_one["round_number"] == 1, (
        f"expected 1, got {round_one['round_number']} for the project's first rendering"
    )

    fx.record_votes(round_one["id"], fx.REVISE_VOTES[0], fx.REVISE_VOTES[1])
    fx.close_review(round_one["id"])

    round_two = fx.issue_rendering(project_id, scenario["standard"]["id"])
    assert round_two["round_number"] == 2, (
        f"expected 2, got {round_two['round_number']} for the second pass through RENDERED"
    )
    assert round_two["status"] == "ISSUED", (
        f"expected ISSUED, got {round_two['status']} for the freshly issued rendering"
    )

    round_one_after = fx.get_rendering(round_one["id"])
    assert round_one_after["round_number"] == 1, (
        f"expected 1, got {round_one_after['round_number']} — a round number is never rewritten"
    )
    assert round_one_after["status"] == "WITHDRAWN", (
        f"expected WITHDRAWN, got {round_one_after['status']} for the rendering the review rejected"
    )


def test_each_round_accumulates_its_own_community_tallies():
    """Round-2 tallies start from zero rather than inheriting round 1's, so the two approval percentages are 40.0 and 80.0.

    PRD: "After the batch is absorbed, `community_approval_pct` is re-derived: with no votes at all it is 0.0; otherwise it is one hundred multiplied by the accumulated `yes_votes`, divided by the sum of `yes_votes` and `no_votes`, rounded half up to exactly one decimal place."

    Design: Difficulty/non_linear_state_machine/design_project_revision_cycle_reenters_rendered
    """
    scenario = _setup_rendered_project_with_draft_deck()
    project_id = scenario["project"]["id"]
    round_one = scenario["rendering"]

    fx.record_votes(round_one["id"], fx.REVISE_VOTES[0], fx.REVISE_VOTES[1])
    round_one_after = fx.get_rendering(round_one["id"])
    assert round_one_after["yes_votes"] == 10, (
        f"expected 10, got {round_one_after['yes_votes']} on the round-1 rendering"
    )
    assert round_one_after["no_votes"] == 15, (
        f"expected 15, got {round_one_after['no_votes']} on the round-1 rendering"
    )
    assert round_one_after["community_approval_pct"] == 40.0, (
        f"expected 40.0, got {round_one_after['community_approval_pct']} for 10 yes of 25 ballots"
    )

    fx.close_review(round_one["id"])
    round_two = fx.issue_rendering(project_id, scenario["standard"]["id"])
    assert round_two["yes_votes"] == 0 and round_two["no_votes"] == 0, (
        f"expected 0/0, got {round_two['yes_votes']}/{round_two['no_votes']} on a freshly issued rendering"
    )
    assert round_two["community_approval_pct"] == 0.0, (
        f"expected 0.0, got {round_two['community_approval_pct']} before any round-2 ballot"
    )

    fx.record_votes(round_two["id"], 20, 5)
    round_two_after = fx.get_rendering(round_two["id"])
    assert round_two_after["yes_votes"] == 20, (
        f"expected 20, got {round_two_after['yes_votes']} — round-1 tallies are not carried forward"
    )
    assert round_two_after["no_votes"] == 5, (
        f"expected 5, got {round_two_after['no_votes']} — round-1 tallies are not carried forward"
    )
    assert round_two_after["community_approval_pct"] == 80.0, (
        f"expected 80.0, got {round_two_after['community_approval_pct']} for 20 yes of 25 ballots"
    )

    round_one_final = fx.get_rendering(round_one["id"])
    assert round_one_final["yes_votes"] == 10 and round_one_final["no_votes"] == 15, (
        "the round-1 tallies must still read 10/15 after round 2 has been voted on, got "
        f"{round_one_final['yes_votes']}/{round_one_final['no_votes']}"
    )


def test_revision_cycle_does_not_demote_the_projects_placement():
    """The revise branch touches the rendering, the project status and its ISSUED quotes — never the placements.

    PRD: "On the **revise branch**, where `community_approval_pct` is below 60.0, three further things happen beyond the status move: the rendering's `status` becomes `WITHDRAWN`, the project's `design_status` becomes `REVISION_REQUESTED` and its `revision_rounds` counter is incremented by one, and every `Quote` of the project still in `ISSUED` status is moved to `EXPIRED`."

    Design: Difficulty/non_linear_state_machine/design_project_revision_cycle_reenters_rendered
    """
    scenario = _setup_rendered_project_with_draft_deck()
    project_id = scenario["project"]["id"]
    round_one = scenario["rendering"]
    placement_id = scenario["deck_placement"]["id"]

    assert scenario["deck_placement"]["status"] == "DRAFT", (
        f"expected DRAFT, got {scenario['deck_placement']['status']} for a newly created placement"
    )

    fx.record_votes(round_one["id"], fx.REVISE_VOTES[0], fx.REVISE_VOTES[1])
    fx.close_review(round_one["id"])
    placement = fx.get_placement(placement_id)
    assert placement["status"] == "DRAFT", (
        f"expected DRAFT, got {placement['status']} after the review reopened the project"
    )

    round_two = fx.issue_rendering(project_id, scenario["standard"]["id"])
    fx.record_votes(round_two["id"], 20, 5)
    placement = fx.get_placement(placement_id)
    assert placement["status"] == "DRAFT", (
        f"expected DRAFT, got {placement['status']} after the project re-entered COMMUNITY_REVIEW"
    )


# ==========================================================================
# The installation rework loop: INSPECTION_PENDING -> INSPECTION_FAILED ->
# REWORK_IN_PROGRESS -> INSPECTION_PENDING
# ==========================================================================
def _fail_install_inspection(job_id: str, deficiency_count: int = 1) -> dict:
    """File a further failing installation inspection on the job."""
    return fx.file_inspection(
        job_id,
        AUDITOR_HEADERS,
        kind="INSTALL_INSPECTION",
        result="FAIL",
        deficiency_count=deficiency_count,
    )


def _run_one_rework_cycle(job_id: str, installer_id: str) -> dict:
    """Drive one full rework cycle and return the job as COMPLETE left it."""
    fx.rework_job(job_id, installer_id, "START")
    return fx.rework_job(job_id, installer_id, "COMPLETE")


def test_completed_rework_returns_the_job_to_the_check_it_failed():
    """A job that failed its installation inspection lands back in INSPECTION_PENDING, not AUDIT_PENDING.

    PRD: "`COMPLETE` is admissible only from `REWORK_IN_PROGRESS`, increments `rework_cycles` by one, and **returns the job to whichever check it failed**: when `last_failed_inspection_kind` is `INSTALL_INSPECTION` the job lands back in `INSPECTION_PENDING`, closing the cycle `INSPECTION_PENDING → INSPECTION_FAILED → REWORK_IN_PROGRESS → INSPECTION_PENDING`; when it is `POST_INSTALL_AUDIT` the same trigger lands the job in `AUDIT_PENDING` instead."

    Design: Difficulty/non_linear_state_machine/installation_job_rework_cycle_returns_to_inspection_pending
    """
    scenario = fx.setup_job_inspection_failed()
    job_id = scenario["job"]["id"]
    installer_id = scenario["installer"]["id"]

    assert scenario["job"]["status"] == "INSPECTION_FAILED", (
        f"expected INSPECTION_FAILED, got {scenario['job']['status']} after the failing inspection"
    )
    assert scenario["job"]["last_failed_inspection_kind"] == "INSTALL_INSPECTION", (
        "expected INSTALL_INSPECTION, got "
        f"{scenario['job']['last_failed_inspection_kind']} as the failed check"
    )
    assert scenario["job"]["rework_cycles"] == 0, (
        f"expected 0, got {scenario['job']['rework_cycles']} before any rework started"
    )

    job = fx.rework_job(job_id, installer_id, "START")
    assert job["status"] == "REWORK_IN_PROGRESS", (
        f"expected REWORK_IN_PROGRESS, got {job['status']} after starting rework"
    )
    assert job["rework_cycles"] == 0, (
        f"expected 0, got {job['rework_cycles']} — a cycle counts only once completed"
    )

    job = fx.rework_job(job_id, installer_id, "COMPLETE")
    assert job["status"] == "INSPECTION_PENDING", (
        f"expected INSPECTION_PENDING, got {job['status']} after completing the rework"
    )
    assert job["rework_cycles"] == 1, (
        f"expected 1, got {job['rework_cycles']} after one completed rework cycle"
    )
    assert job["last_failed_inspection_kind"] == "INSTALL_INSPECTION", (
        "expected INSTALL_INSPECTION to be remembered, got "
        f"{job['last_failed_inspection_kind']} after the return to INSPECTION_PENDING"
    )


def test_third_rework_start_is_refused_once_two_cycles_are_recorded():
    """The loop closes at two completed cycles: a third START is refused and leaves the job untouched.

    PRD: "`START` is admissible while the job's `status` is `INSPECTION_FAILED` or `AUDIT_FAILED` and moves it to `REWORK_IN_PROGRESS`, but only while `rework_cycles` is strictly less than 2; at two completed cycles the loop is closed and a further attempt is refused with `ERR_REWORK_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/installation_job_rework_cycle_returns_to_inspection_pending
    """
    scenario = fx.setup_job_inspection_failed()
    job_id = scenario["job"]["id"]
    installer_id = scenario["installer"]["id"]

    job = _run_one_rework_cycle(job_id, installer_id)
    assert job["rework_cycles"] == 1, (
        f"expected 1, got {job['rework_cycles']} after the first cycle"
    )

    _fail_install_inspection(job_id)
    job = _run_one_rework_cycle(job_id, installer_id)
    assert job["rework_cycles"] == 2, (
        f"expected 2, got {job['rework_cycles']} after the second cycle"
    )
    assert job["status"] == "INSPECTION_PENDING", (
        f"expected INSPECTION_PENDING, got {job['status']} after the second cycle"
    )

    _fail_install_inspection(job_id)
    job = fx.get_job(job_id)
    assert job["status"] == "INSPECTION_FAILED", (
        f"expected INSPECTION_FAILED, got {job['status']} after the third failing inspection"
    )

    response = api_client.rework_job(
        job_id,
        f.rework_payload("START"),
        make_installer_operator_headers(installer_id),
    )
    validate_error(response, ApiErrorId.ERR_REWORK_LIMIT_EXCEEDED.value, 409)

    job = fx.get_job(job_id)
    assert job["status"] == "INSPECTION_FAILED", (
        f"expected INSPECTION_FAILED, got {job['status']} after the refused third attempt"
    )
    assert job["rework_cycles"] == 2, (
        f"expected 2, got {job['rework_cycles']} after the refused third attempt"
    )


def test_each_pass_through_the_loop_appends_the_next_inspection_record():
    """The three failing inspections of a twice-reworked job are numbered 1, 2 and 3.

    PRD: "The record's `job_id` comes from the request path, its `performed_by_user_id` is set from the acting `X-User-ID`, and its `sequence_number` is 1 for the job's first record and one greater than the highest existing sequence number thereafter."

    Design: Difficulty/non_linear_state_machine/installation_job_rework_cycle_returns_to_inspection_pending
    """
    scenario = fx.setup_job_inspection_failed()
    job_id = scenario["job"]["id"]
    installer_id = scenario["installer"]["id"]

    first = scenario["inspection"]
    assert first["sequence_number"] == 1, (
        f"expected 1, got {first['sequence_number']} for the job's first inspection record"
    )
    assert first["job_id"] == job_id, (
        f"expected {job_id}, got {first['job_id']} on the first inspection record"
    )

    _run_one_rework_cycle(job_id, installer_id)
    second = _fail_install_inspection(job_id)
    assert second["sequence_number"] == 2, (
        f"expected 2, got {second['sequence_number']} for the second inspection record"
    )

    _run_one_rework_cycle(job_id, installer_id)
    third = _fail_install_inspection(job_id)
    assert third["sequence_number"] == 3, (
        f"expected 3, got {third['sequence_number']} for the third inspection record"
    )
    assert third["performed_by_user_id"] == AUDITOR_USER_ID, (
        f"expected {AUDITOR_USER_ID}, got {third['performed_by_user_id']} as the filing auditor"
    )


def test_the_failing_inspector_is_pinned_once_and_the_project_is_left_alone():
    """The first failing inspection pins the inspector, and repeated failures never touch the owning project.

    PRD: "An **installation inspection that fails** creates the record, likewise sets `install_inspector_user_id` if it is still null — so the auditor who first touched the job is barred from the eventual audit whichever way the inspection went — moves the job `INSPECTION_PENDING → INSPECTION_FAILED`, and records `last_failed_inspection_kind` as `INSTALL_INSPECTION`."

    Design: Difficulty/non_linear_state_machine/installation_job_rework_cycle_returns_to_inspection_pending
    """
    scenario = fx.setup_job_inspection_failed()
    job_id = scenario["job"]["id"]
    project_id = scenario["project"]["id"]
    installer_id = scenario["installer"]["id"]

    assert scenario["job"]["install_inspector_user_id"] == AUDITOR_USER_ID, (
        f"expected {AUDITOR_USER_ID}, got {scenario['job']['install_inspector_user_id']} "
        "pinned by the first failing inspection"
    )
    project = fx.get_project(project_id)
    assert project["design_status"] == "ORDERED", (
        f"expected ORDERED, got {project['design_status']} after a failed installation inspection"
    )
    assert project["installed_on"] is None, (
        f"expected None, got {project['installed_on']} while no inspection has passed"
    )

    _run_one_rework_cycle(job_id, installer_id)
    _fail_install_inspection(job_id)
    job = fx.get_job(job_id)
    assert job["install_inspector_user_id"] == AUDITOR_USER_ID, (
        f"expected {AUDITOR_USER_ID}, got {job['install_inspector_user_id']} after a second failure"
    )
    project = fx.get_project(project_id)
    assert project["design_status"] == "ORDERED", (
        f"expected ORDERED, got {project['design_status']} after a second failed inspection"
    )
    assert project["installed_on"] is None, (
        f"expected None, got {project['installed_on']} after a second failed inspection"
    )
