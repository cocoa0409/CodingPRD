"""Assembly jobs: the fee engine's pinned per-component rounding, the five
booking checks (certification, window shape, sale overlap, padded assembler
buffer, concurrency cap), and the no-show reschedule cycle.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_job,
    assembler_status,
    create_assembler,
    create_assembly_job_payload,
    create_certified_assembler,
    create_job,
    create_sale,
    job_action_payload,
    job_assign_payload,
    make_assembler_headers,
    setup_in_season,
    setup_in_season_with_sale,
    setup_job_assigned,
    unique_suffix,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["planner_admin_headers"]
AGENT = TEST_USERS["service_agent_headers"]


def test_assembly_fee_per_component_rounding_order(api):
    """PRD 3.6: "The base component is 7999 cents for every job. In-home work adds a
    flat 5005-cent surcharge, plus travel: the miles beyond the 15 included miles —
    `distance_mi` minus 15, never below zero — at 149 cents per mile."
    PRD 3.6: "each of the three components is individually multiplied by (10000 minus
    the subsidy) and divided by 10000, rounded half up to integer cents, and the three
    rounded figures are summed to form `fee_cents`. Summing first and rounding once is
    explicitly non-compliant"

    Design: Difficulty/combinatorial_formula/assembly_fee_per_component_rounding_order
    """
    bundle = setup_in_season_with_sale(
        channel_type="SPECIALTY_DEALER", allocated_units=5, units_built=20,
        model_over={"model_code": "GX-200", "base_price_cents": 80000, "demand_share_bp": 3000},
    )
    resp = api.create_assembly_job(
        create_assembly_job_payload(bundle["sale"]["id"], "IN_HOME", distance_mi=20), headers=AGENT)
    job = validate_success(resp, 201)
    # SPECIALTY_DEALER subsidy 1000bp applied per component, each rounded half up:
    # round_half_up(7999 x 0.9) = 7199; round_half_up(5005 x 0.9) = 4505;
    # round_half_up((20-15) x 149 x 0.9) = round_half_up(670.5) = 671. Sum 12375.
    assert job["fee_cents"] == 12375, (
        f"per-component rounding must give 12375 (sum-then-round gives 12374 and is non-compliant), "
        f"got {job['fee_cents']}"
    )


def test_job_assign_gated_by_assembler_certification(api):
    """PRD 3.6: "the named assembler must exist and be `CERTIFIED`, else
    `ERR_ASSEMBLER_NOT_CERTIFIED`"
    PRD 3.6: "Certification — `APPLIED → CERTIFIED` — is a `PlannerAdmin` action."

    Design: Difficulty/cross_entity_state_dependency/job_assign_gated_by_assembler_certification
    """
    bundle = setup_in_season_with_sale(channel_type="DIRECT")
    job = create_job(bundle["sale"]["id"], job_type="RETAIL_ASSEMBLY")
    assembler = create_assembler(name="ASM-P", service_regions=["NW"])  # still APPLIED
    refused = api.transition_assembly_job(
        job["id"], job_assign_payload(assembler["id"], "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z"),
        headers=AGENT)
    validate_error(refused, ApiErrorId.ERR_ASSEMBLER_NOT_CERTIFIED)
    assembler_status(assembler["id"], "CERTIFY")
    assigned = validate_success(api.transition_assembly_job(
        job["id"], job_assign_payload(assembler["id"], "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z"),
        headers=AGENT), 200)
    assert assigned["status"] == "SCHEDULED", "the identical ASSIGN succeeds once the assembler is CERTIFIED"


def test_in_home_jobs_require_travel_buffer(api):
    """PRD 3.6: "no active job of the same assembler may overlap, except that a new
    `IN_HOME` job is first padded by 45 minutes on both sides of its window — the
    travel buffer — before the same half-open test, while `RETAIL_ASSEMBLY` jobs are
    never padded, else `ERR_ASSEMBLER_BUFFER_CONFLICT`"

    Design: Difficulty/resource_temporal_overlap/in_home_jobs_require_travel_buffer
    """
    bundle = setup_in_season(channel_type="DIRECT")
    assembler = create_certified_assembler(name="ASM-T", service_regions=["NW"])
    s1 = create_sale(bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"],
                     quantity=1, proof_of_purchase_token=f"RCPT-{unique_suffix()}")
    s2 = create_sale(bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"],
                     quantity=1, proof_of_purchase_token=f"RCPT-{unique_suffix()}")
    j1 = create_job(s1["id"], job_type="IN_HOME", distance_mi=10)
    j2 = create_job(s2["id"], job_type="IN_HOME", distance_mi=10)
    assign_job(j1["id"], assembler["id"], "2026-04-05T10:00:00Z", "2026-04-05T11:00:00Z")
    # 30-minute raw gap: the new IN_HOME job pads to [10:45, 13:15), overlapping j1.
    conflict = api.transition_assembly_job(
        j2["id"], job_assign_payload(assembler["id"], "2026-04-05T11:30:00Z", "2026-04-05T12:30:00Z"),
        headers=AGENT)
    validate_error(conflict, ApiErrorId.ERR_ASSEMBLER_BUFFER_CONFLICT)
    # 45-minute gap: padded to [11:00, 13:30), only touching j1's end — free under the half-open test.
    ok = validate_success(api.transition_assembly_job(
        j2["id"], job_assign_payload(assembler["id"], "2026-04-05T11:45:00Z", "2026-04-05T12:45:00Z"),
        headers=AGENT), 200)
    assert ok["status"] == "SCHEDULED"


def test_sale_windows_overlap_half_open_adjacency_allowed(api):
    """PRD 3.6: "no other active job — `SCHEDULED` or `IN_PROGRESS` — on the same sale
    may overlap the requested window under a half-open overlap test where a window
    ending exactly when another begins is allowed, else `ERR_ASSEMBLY_WINDOW_CONFLICT`"

    Design: Difficulty/resource_temporal_overlap/sale_windows_overlap_half_open_adjacency_allowed
    """
    bundle = setup_in_season_with_sale(channel_type="DIRECT")
    sale = bundle["sale"]
    asm_a = create_certified_assembler(name="ASM-A", service_regions=["NW"])
    asm_b = create_certified_assembler(name="ASM-B", service_regions=["NW"])
    j1 = create_job(sale["id"], job_type="RETAIL_ASSEMBLY")
    j2 = create_job(sale["id"], job_type="RETAIL_ASSEMBLY")
    j3 = create_job(sale["id"], job_type="RETAIL_ASSEMBLY")
    assign_job(j1["id"], asm_a["id"], "2026-04-06T10:00:00Z", "2026-04-06T11:00:00Z")
    # 30-minute overlap on the same sale; ASM-B's own calendar is empty.
    conflict = api.transition_assembly_job(
        j2["id"], job_assign_payload(asm_b["id"], "2026-04-06T10:30:00Z", "2026-04-06T11:30:00Z"),
        headers=AGENT)
    validate_error(conflict, ApiErrorId.ERR_ASSEMBLY_WINDOW_CONFLICT)
    # 11:00 == j1.window_end is adjacency, not overlap, under half-open semantics.
    ok = validate_success(api.transition_assembly_job(
        j3["id"], job_assign_payload(asm_b["id"], "2026-04-06T11:00:00Z", "2026-04-06T12:00:00Z"),
        headers=AGENT), 200)
    assert ok["status"] == "SCHEDULED"


def test_assembler_cannot_start_job_assigned_to_peer(api):
    """PRD 2.1: "An entity-backed caller acting on a resource owned by a different
    account — a `ChannelRep` touching another channel's allocation or sale, an
    `Assembler` starting a job assigned to someone else — is rejected with
    `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."
    PRD 2.9: "The target entity must be in a state from which the requested transition
    exists — posture gates, terminal lockdowns, and invalid-from transitions — else
    the specific 409 code: ... `ERR_JOB_NOT_SCHEDULABLE`"
    PRD 2.8: "Identifiers carried in a request body are resolved with the same
    discipline"

    Design: Corner/validations/assembler_cannot_start_job_assigned_to_peer
    """
    bundle = setup_in_season_with_sale(channel_type="DIRECT")
    job = create_job(bundle["sale"]["id"], job_type="RETAIL_ASSEMBLY")
    asm_a = create_certified_assembler(name="ASM-A", service_regions=["NW"])
    asm_b = create_certified_assembler(name="ASM-B", service_regions=["NW"])
    not_scheduled = api.transition_assembly_job(job["id"], job_action_payload("NO_SHOW"), headers=AGENT)
    validate_error(not_scheduled, ApiErrorId.ERR_JOB_NOT_SCHEDULABLE)  # NO_SHOW requires SCHEDULED
    unknown = api.transition_assembly_job(
        job["id"],
        job_assign_payload("00000000-0000-4000-8000-0000000000cc",
                           "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z"),
        headers=AGENT)
    validate_error(unknown, ApiErrorId.ERR_ASSEMBLER_NOT_FOUND)
    assigned = validate_success(api.transition_assembly_job(
        job["id"], job_assign_payload(asm_a["id"], "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z"),
        headers=AGENT), 200)
    assert assigned["status"] == "SCHEDULED"
    peer = api.transition_assembly_job(job["id"], job_action_payload("START"),
                                       headers=make_assembler_headers(asm_b["id"]))
    validate_error(peer, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    own = validate_success(api.transition_assembly_job(
        job["id"], job_action_payload("START"), headers=make_assembler_headers(asm_a["id"])), 200)
    assert own["status"] == "IN_PROGRESS"


def test_second_concurrent_job_at_capacity_rejected(api):
    """PRD 3.6: "the assembler's `active_job_count` must be strictly below
    `max_concurrent_jobs`, so a booking that would bring the count to the cap is
    refused with `ERR_MAX_CONCURRENT_JOBS`"

    Design: Corner/validations/second_concurrent_job_at_capacity_rejected
    """
    bundle = setup_in_season(channel_type="DIRECT")
    assembler = create_certified_assembler(name="ASM-1", service_regions=["NW"], max_concurrent_jobs=1)
    s1 = create_sale(bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"],
                     quantity=1, proof_of_purchase_token=f"RCPT-{unique_suffix()}")
    s2 = create_sale(bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"],
                     quantity=1, proof_of_purchase_token=f"RCPT-{unique_suffix()}")
    j1 = create_job(s1["id"], job_type="RETAIL_ASSEMBLY")
    j2 = create_job(s2["id"], job_type="RETAIL_ASSEMBLY")
    assign_job(j1["id"], assembler["id"], "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z")
    # The windows do not overlap; the cap is a count, not an interval rule.
    over = api.transition_assembly_job(
        j2["id"], job_assign_payload(assembler["id"], "2026-04-02T11:00:00Z", "2026-04-02T12:00:00Z"),
        headers=AGENT)
    validate_error(over, ApiErrorId.ERR_MAX_CONCURRENT_JOBS)


def test_assembly_job_no_show_reschedule_cycle(api):
    """PRD 3.6: "The no-showed job itself keeps its `assembler_id` for audit; only its
    status changes to `NO_SHOW`, from which a later reassignment reschedules it under
    the same five checks."
    PRD 3.6: "Completion subtracts 1 from `active_job_count`, adds 1 to
    `jobs_completed`, appends the logical clock to `completion_history`, and
    recomputes both quality scores."

    Design: Difficulty/non_linear_state_machine/assembly_job_no_show_reschedule_cycle
    """
    bundle = setup_job_assigned()  # job SCHEDULED to a certified assembler, 2026-04-02 09:00-10:00
    job, assembler = bundle["job"], bundle["assembler"]
    no_show = validate_success(api.transition_assembly_job(
        job["id"], job_action_payload("NO_SHOW"), headers=AGENT), 200)
    assert no_show["status"] == "NO_SHOW"
    rescheduled = validate_success(api.transition_assembly_job(
        job["id"], job_assign_payload(assembler["id"], "2026-04-03T09:00:00Z", "2026-04-03T10:00:00Z"),
        headers=AGENT), 200)
    assert rescheduled["status"] == "SCHEDULED", "the cyclic edge re-enters SCHEDULED from NO_SHOW"
    started = validate_success(api.transition_assembly_job(
        job["id"], job_action_payload("START"), headers=make_assembler_headers(assembler["id"])), 200)
    assert started["status"] == "IN_PROGRESS"
    completed = validate_success(api.transition_assembly_job(
        job["id"], job_action_payload("COMPLETE"), headers=make_assembler_headers(assembler["id"])), 200)
    assert completed["status"] == "COMPLETED"
    after = validate_success(api.get_assembler(assembler["id"], headers=PLANNER), 200)
    assert after["active_job_count"] == 0
    assert after["jobs_completed"] == 1
    assert after["no_show_count"] == 1
    # official: 10000 - 1200 x 1 = 8800; provisional adds the recent completion bonus: +25.
    assert after["official_quality_bp"] == 8800
    assert after["provisional_quality_bp"] == 8825
