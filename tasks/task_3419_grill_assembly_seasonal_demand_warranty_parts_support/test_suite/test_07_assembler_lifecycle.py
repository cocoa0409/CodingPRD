"""Assembler standing: certification-gated assignment, the score-gated
suspend/reinstate/decertify lifecycle, the 3-no-show auto-suspension cascade,
the active-job-count conservation invariant, and the dual quality variants.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assembler_status_payload,
    assign_job,
    cancel_job,
    complete_job,
    create_certified_assembler,
    create_job,
    create_sale,
    job_action_payload,
    job_assign_payload,
    make_assembler_headers,
    no_show_job,
    set_logical_clock,
    setup_in_season,
    start_job,
    unique_suffix,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["planner_admin_headers"]
AGENT = TEST_USERS["service_agent_headers"]


def test_assembler_suspend_and_reinstate_with_score_gate(api):
    """PRD 3.6: "Reinstatement — `SUSPENDED → CERTIFIED` — is a `PlannerAdmin`
    certification action guarded by the assembler's rolling quality: it requires
    `provisional_quality_bp` of at least 7000, so an assembler whose recent record is
    still poor cannot be waved back in. Decertification — from either `CERTIFIED` or
    `SUSPENDED` — is a `PlannerAdmin` action guarded by the lifetime record: it
    requires `official_quality_bp` of 4000 or less, so only a genuinely degraded
    assembler can be pushed out. An attempt that fails either guard is rejected."
    PRD 3.6: "Suspension — `CERTIFIED → SUSPENDED` — may be invoked by a
    `ServiceAgent` or `PlannerAdmin`"

    Design: Corner/state_machines/assembler_suspend_and_reinstate_with_score_gate
    """
    bundle = setup_in_season(channel_type="DIRECT")
    assembler = create_certified_assembler(name="ASM-S", service_regions=["NW"])
    sale = create_sale(bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"],
                       quantity=1, proof_of_purchase_token=f"RCPT-{unique_suffix()}")
    job = create_job(sale["id"], job_type="RETAIL_ASSEMBLY")
    assign_job(job["id"], assembler["id"], "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z")
    no_show_job(job["id"])
    # One lifetime no-show: official = 10000 - 1200 = 8800, above the decertify ceiling.
    refused = api.assembler_status(assembler["id"], assembler_status_payload("DECERTIFY"), headers=PLANNER)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE)
    suspended = validate_success(
        api.assembler_status(assembler["id"], assembler_status_payload("SUSPEND"), headers=AGENT), 200)
    assert suspended["status"] == "SUSPENDED"
    reinstated = validate_success(
        api.assembler_status(assembler["id"], assembler_status_payload("CERTIFY"), headers=PLANNER), 200)
    assert reinstated["status"] == "CERTIFIED"
    assert reinstated["provisional_quality_bp"] == 8800, (
        f"provisional 8800 >= 7000 reinstatement floor, got {reinstated['provisional_quality_bp']}"
    )


def test_no_show_threshold_auto_suspends_and_unassigns(api):
    """PRD 3.6: "Second, if `no_show_count` has reached the suspension threshold of 3
    lifetime no-shows, the assembler auto-transitions `CERTIFIED → SUSPENDED`. Third,
    that suspension cascades: every other `SCHEDULED` job of the assembler returns to
    `REQUESTED` with its `assembler_id` cleared and its windows nulled — while jobs
    already `IN_PROGRESS` are deliberately not touched."
    PRD 3.6: "The no-showed job itself keeps its `assembler_id` for audit; only its
    status changes to `NO_SHOW`"

    Design: Difficulty/transitive_cascade/no_show_threshold_auto_suspends_and_unassigns
    """
    bundle = setup_in_season(channel_type="DIRECT")
    assembler = create_certified_assembler(name="ASM-X", service_regions=["NW"])
    jobs = []
    for i, hour in enumerate((9, 10, 11, 13)):
        sale = create_sale(bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"],
                           quantity=1, proof_of_purchase_token=f"RCPT-{unique_suffix()}")
        job = create_job(sale["id"], job_type="RETAIL_ASSEMBLY")
        assign_job(job["id"], assembler["id"], f"2026-04-02T{hour:02d}:00:00Z", f"2026-04-02T{hour + 1:02d}:00:00Z")
        jobs.append(job)
    for job in jobs[:3]:
        validate_success(api.transition_assembly_job(job["id"], job_action_payload("NO_SHOW"), headers=AGENT), 200)
    after = validate_success(api.get_assembler(assembler["id"], headers=PLANNER), 200)
    assert after["status"] == "SUSPENDED", "the third no-show auto-suspends without any explicit SUSPEND call"
    assert after["no_show_count"] == 3
    assert after["provisional_quality_bp"] == 6400, "10000 - 1200 x 3 recent no-shows = 6400"
    fourth = validate_success(api.get_assembly_job(jobs[3]["id"], headers=AGENT), 200)
    assert fourth["status"] == "REQUESTED", "the cascade unassigns the still-SCHEDULED fourth job"
    assert fourth["assembler_id"] is None
    first = validate_success(api.get_assembly_job(jobs[0]["id"], headers=AGENT), 200)
    assert first["status"] == "NO_SHOW"
    assert first["assembler_id"] == assembler["id"], "the no-showed job keeps its assembler for audit"


def test_assembler_active_count_conserved_across_assign_and_complete(api):
    """PRD 3.6: "A successful assignment stores the `assembler_id` and both windows
    and adds 1 to the assembler's `active_job_count`."
    PRD 3.6: "Completion subtracts 1 from `active_job_count`, adds 1 to
    `jobs_completed`"
    PRD 3.6: "A `ServiceAgent` may cancel a job from `REQUESTED` or `SCHEDULED` — the
    latter also subtracting 1 from the assignee's `active_job_count`"

    Design: Difficulty/compensating_invariant/assembler_active_count_conserved_across_assign_and_complete
    """
    bundle = setup_in_season(channel_type="DIRECT")
    assembler = create_certified_assembler(name="ASM-K", service_regions=["NW"])
    s1 = create_sale(bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"],
                     quantity=1, proof_of_purchase_token=f"RCPT-{unique_suffix()}")
    s2 = create_sale(bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"],
                     quantity=1, proof_of_purchase_token=f"RCPT-{unique_suffix()}")
    j1 = create_job(s1["id"], job_type="RETAIL_ASSEMBLY")
    j2 = create_job(s2["id"], job_type="RETAIL_ASSEMBLY")

    def active_count():
        return validate_success(api.get_assembler(assembler["id"], headers=PLANNER), 200)["active_job_count"]

    assign_job(j1["id"], assembler["id"], "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z")
    assert active_count() == 1
    assign_job(j2["id"], assembler["id"], "2026-04-02T10:00:00Z", "2026-04-02T11:00:00Z")
    assert active_count() == 2
    cancel_job(j1["id"])  # compensates the first assignment
    assert active_count() == 1
    start_job(j2["id"], assembler["id"])
    completed = complete_job(j2["id"], assembler["id"])  # compensates the second
    assert completed["status"] == "COMPLETED"
    after = validate_success(api.get_assembler(assembler["id"], headers=PLANNER), 200)
    assert after["active_job_count"] == 0
    assert after["jobs_completed"] == 1


def test_assembler_quality_official_diverges_from_provisional(api):
    """PRD 3.6: "The lifetime score, `official_quality_bp`, starts from a perfect
    10000 basis points and subtracts 1200 basis points per lifetime no-show, floored
    at 0 — every no-show counts forever, and completions earn no credit"
    PRD 3.6: "The rolling score, `provisional_quality_bp`, looks only at the last 90
    days measured back from the logical clock — events exactly 90 days old are
    included in the window — and starts from 10000, subtracts 1200 basis points per
    no-show inside that window, adds a 25-basis-point completion bonus per completion
    inside the window, and clamps the result into the 0-to-10000 range"

    Design: Difficulty/dual_variant_calc/assembler_quality_official_diverges_from_provisional
    """
    bundle = setup_in_season(channel_type="DIRECT", allocated_units=20, units_built=100,
                             in_season_clock="2026-03-01T00:00:00Z")
    assembler = create_certified_assembler(name="ASM-Q", service_regions=["NW"])
    season_id, model_id, channel_id = bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"]

    def _job_on(date, hour):
        sale = create_sale(season_id, model_id, channel_id, quantity=1,
                           proof_of_purchase_token=f"RCPT-{unique_suffix()}")
        job = create_job(sale["id"], job_type="RETAIL_ASSEMBLY")
        assign_job(job["id"], assembler["id"],
                   f"{date}T{hour:02d}:00:00Z", f"{date}T{hour + 1:02d}:00:00Z")
        return job

    # No-show #1 at logical clock 2026-03-01; the clock then jumps 111 days forward.
    no_show_job(_job_on("2026-03-02", 9)["id"])
    set_logical_clock("2026-06-20T00:00:00Z")
    # No-show #2 and three completions all land inside the 90-day window.
    no_show_job(_job_on("2026-06-21", 9)["id"])
    for date in ("2026-06-22", "2026-06-23", "2026-06-24"):
        job = _job_on(date, 9)
        start_job(job["id"], assembler["id"])
        complete_job(job["id"], assembler["id"])
    after = validate_success(api.get_assembler(assembler["id"], headers=PLANNER), 200)
    assert after["no_show_count"] == 2
    assert after["jobs_completed"] == 3
    # official counts both no-shows forever: 10000 - 1200 x 2 = 7600.
    assert after["official_quality_bp"] == 7600, (
        f"lifetime score must be 7600, got {after['official_quality_bp']}"
    )
    # provisional forgives the 111-day-old no-show and credits 3 recent completions:
    # 10000 - 1200 x 1 + 25 x 3 = 8875.
    assert after["provisional_quality_bp"] == 8875, (
        f"rolling 90-day score must be 8875, got {after['provisional_quality_bp']}"
    )
    assert after["official_quality_bp"] != after["provisional_quality_bp"]
