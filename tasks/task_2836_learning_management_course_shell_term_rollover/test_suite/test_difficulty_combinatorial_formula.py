"""Combinatorial formulas: pinned rounding order, double clamps and pinned
evaluation order.

Each test pins the single stored figure the PRD's arithmetic uniquely derives, so
a plausible reordering of the same formula is visible as a wrong number rather
than as a wrong branch.
"""
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.test_users import make_instructor_headers


# ─── sandbox storage chargeback ───────────────────────────────────────────

def _billable_owner_setup(api):
    """One faculty owner with a SANDBOX (210.00 MB), a DEV (175.00 MB) and a
    second SANDBOX (187.50 MB) shell, created in that order."""
    term = fx.create_term(api)
    owner = fx.create_faculty(api)
    instructor = make_instructor_headers(owner["id"])

    sandbox_a = fx.provision_shell(
        api, term["id"], owner["id"], shell_type="SANDBOX", base_seat_cap=5
    )
    fx.create_content_item(
        api, sandbox_a["id"], instructor, item_type="FILE",
        title="Lecture capture A", points_possible=0.00, storage_mb=210.00,
    )
    dev_b = fx.provision_shell(
        api, term["id"], owner["id"], shell_type="DEV", base_seat_cap=5
    )
    fx.create_content_item(
        api, dev_b["id"], instructor, item_type="FILE",
        title="Lecture capture B", points_possible=0.00, storage_mb=175.00,
    )
    sandbox_c = fx.provision_shell(
        api, term["id"], owner["id"], shell_type="SANDBOX", base_seat_cap=5
    )
    fx.create_content_item(
        api, sandbox_c["id"], instructor, item_type="FILE",
        title="Lecture capture C", points_possible=0.00, storage_mb=187.50,
    )
    return {
        "term": term,
        "owner": owner,
        "instructor": instructor,
        "sandbox_a": sandbox_a,
        "dev_b": dev_b,
        "sandbox_c": sandbox_c,
    }


def test_chargeback_rounds_each_shell_before_summing_to_three_fifty_two(api):
    """1.65 + 0.56 + 1.31 is stored as 3.52, never the 3.53 of a single late round.

    PRD §3.3: "For each shell, subtract a free allowance of 100.00 megabytes from
    its `storage_mb` and treat any negative result as zero; multiply the remainder
    by a rate of 0.0150 US dollars per megabyte; multiply again by the class
    multiplier, which is 1.00 for a `SANDBOX` shell and 0.50 for a `DEV` shell;
    then round that single shell's charge half up to two decimal places."
    PRD §3.3: "**The rounding order is pinned and observable:** for an owner
    holding a `SANDBOX` shell at 210.00 megabytes, a `DEV` shell at 175.00
    megabytes and a second `SANDBOX` shell at 187.50 megabytes, rounding per shell
    first yields 1.65 plus 0.56 plus 1.31, and the stored total must be 3.52 —
    never the 3.53 that summing the unrounded 1.65, 0.5625 and 1.3125 and rounding
    once at the end would produce."
    PRD §3.3 also fixes the starting value: "A person's
    `sandbox_storage_charge_usd` starts at 0.00 and is only ever written by the
    chargeback computation described later in this subsection."

    Design: Difficulty/combinatorial_formula/sandbox_chargeback_rounds_per_shell_then_sums_never_the_reverse
    """
    fresh_owner = fx.create_faculty(api)
    assert fresh_owner["sandbox_storage_charge_usd"] == 0.00

    setup = _billable_owner_setup(api)
    owner = fx.read_person(api, setup["owner"]["id"])
    assert owner["sandbox_storage_charge_usd"] == 3.52
    assert owner["sandbox_storage_charge_usd"] != 3.53

    assert fx.read_shell(api, setup["sandbox_a"]["id"])["storage_mb"] == 210.00
    assert fx.read_shell(api, setup["dev_b"]["id"])["storage_mb"] == 175.00
    assert fx.read_shell(api, setup["sandbox_c"]["id"])["storage_mb"] == 187.50


def test_official_shell_storage_is_outside_the_billable_set(api):
    """900.00 MB on an OFFICIAL shell leaves the owner's charge at 3.52.

    PRD §3.3: "The billable set is that person's shells whose `shell_type` is
    `SANDBOX` or `DEV` and whose `provisioning_state` is neither `REJECTED` nor
    `PURGED`; `OFFICIAL` shells are never charged."
    PRD §3.3 also fixes the sandbox expiry the same request writes: "On approval
    `effective_seat_cap` is set equal to `base_seat_cap`, `publish_readiness` is
    set to true, and `sandbox_expires_at` is set to sixty days after the term's
    `term_end_at` for a `SANDBOX` or `DEV` shell while remaining null for an
    `OFFICIAL` one."

    Design: Difficulty/combinatorial_formula/sandbox_chargeback_rounds_per_shell_then_sums_never_the_reverse
    """
    setup = _billable_owner_setup(api)
    assert fx.read_person(api, setup["owner"]["id"])["sandbox_storage_charge_usd"] == 3.52

    official = fx.provision_shell(
        api, setup["term"]["id"], setup["owner"]["id"],
        shell_type="OFFICIAL", base_seat_cap=25,
    )
    fx.create_content_item(
        api, official["id"], setup["instructor"], item_type="FILE",
        title="Official course video", points_possible=0.00, storage_mb=900.00,
    )

    # Billing the OFFICIAL shell's 900.00 MB would have read 15.52 here.
    assert fx.read_person(api, setup["owner"]["id"])["sandbox_storage_charge_usd"] == 3.52
    assert official["sandbox_expires_at"] is None
    # term_end_at 2026-12-11T00:00:00Z plus sixty days.
    assert setup["sandbox_a"]["sandbox_expires_at"] == "2027-02-09T00:00:00Z"
    assert setup["dev_b"]["sandbox_expires_at"] == "2027-02-09T00:00:00Z"


# ─── tool risk score: both clamps ─────────────────────────────────────────

HIGH_RISK_TOOL = {
    "vendor_name": "Acme Analytics",
    "tool_name": "DeepProctor",
    "tool_version": "4.2.0",
    "data_sharing_scope": "FULL_PROFILE",
    "pii_tier": 3,
    "vpat_score": 0.00,
    "wcag_level": "NONE",
}

LOW_RISK_TOOL = {
    "vendor_name": "Campus Coop",
    "tool_name": "QuietReader",
    "tool_version": "1.0.0",
    "data_sharing_scope": "NONE",
    "pii_tier": 0,
    "vpat_score": 100.00,
    "wcag_level": "AAA",
}


def _cleared_tool(api, metadata):
    """Register a tool with explicit governance metadata and clear both dimensions."""
    tool = get_success_data(
        api.create_tool_integration(
            fac.create_tool_integration_payload(**metadata), fx.LMS_ADMIN
        )
    )
    fx.transition_tool(api, tool["id"], "OPEN_REVIEW")
    fx.file_review(api, tool["id"], "PRIVACY", "CLEAR")
    fx.file_review(api, tool["id"], "ACCESSIBILITY", "CLEAR")
    return tool


def test_risk_score_clamps_a_raw_one_twenty_down_to_the_ceiling(api):
    """A raw 120.00 stores 100.00 and rejects the tool.

    PRD §3.7: "The raw total is the sum of those five, and the stored `risk_score`
    is that total clamped into the range from 0.00 to 100.00 and then rounded half
    up to two decimal places — rounded **once**, after clamping, never per addend."
    PRD §3.7: "The tool takes `UNDER_REVIEW` → `REJECTED` when either dimension is
    `BLOCKED` or the score is 70.00 or above; `approved_version` is left null, and
    this is the only branch that cascades into placements — every placement of the
    tool whose `placement_state` is `REQUESTED` or `ACTIVE` moves to `BLOCKED` in
    `created_at` ascending order with `blocked_reason` "tool rejected"."
    PRD §3.7 also fixes the value at registration: "A new tool opens with
    `approval_state` `DRAFT`, `privacy_review_state` `PENDING`,
    `accessibility_review_state` `PENDING`, `risk_score` null, `approved_version`
    null, `active_placement_count` 0 and `suspension_reason` null."

    Design: Difficulty/combinatorial_formula/tool_risk_score_four_input_nonlinear_double_clamp_at_ceiling_and_floor
    """
    tool = _cleared_tool(api, HIGH_RISK_TOOL)
    assert tool["approval_state"] == "DRAFT"
    assert tool["risk_score"] is None
    assert tool["active_placement_count"] == 0

    finalized = fx.transition_tool(api, tool["id"], "FINALIZE_REVIEW")
    # 3 * 10 + 40 + (100 - 0.00) * 0.30 + 20 + 0 = 120.00, clamped to 100.00.
    assert finalized["risk_score"] == 100.00
    assert finalized["approval_state"] == "REJECTED"
    assert finalized["approved_version"] is None
    assert finalized["active_placement_count"] == 0


def test_risk_score_clamps_a_raw_minus_five_up_to_the_floor(api):
    """The AAA credit drives the raw total to minus 5.00; the stored score is 0.00.

    PRD §3.7: "The conformance points are 20 for `NONE`, 10 for `A`, 0 for `AA`
    and **minus 5** for `AAA` — the top conformance level earns a credit, which is
    why the raw total can go below zero."
    PRD §3.7: "Both clamps are reachable: a tool with `pii_tier` 3,
    `FULL_PROFILE`, a `vpat_score` of 0.00, `wcag_level` `NONE` and five active
    placements totals 30 plus 40 plus 30.00 plus 20 plus 15, that is 135.00, and
    stores 100.00; a tool with `pii_tier` 0, `NONE`, a `vpat_score` of 100.00,
    `wcag_level` `AAA` and no placements totals minus 5.00 and stores 0.00."
    PRD §3.7: "The tool takes `UNDER_REVIEW` → `APPROVED` when neither dimension
    is `BLOCKED`, both dimensions are `CLEARED`, and the freshly computed score is
    below 40.00; `approved_version` is set to the tool's current `tool_version`."

    Design: Difficulty/combinatorial_formula/tool_risk_score_four_input_nonlinear_double_clamp_at_ceiling_and_floor
    """
    tool = _cleared_tool(api, LOW_RISK_TOOL)
    finalized = fx.transition_tool(api, tool["id"], "FINALIZE_REVIEW")
    # 0 + 0 + (100 - 100.00) * 0.30 + (-5) = -5.00, clamped up to 0.00.
    assert finalized["risk_score"] == 0.00
    assert finalized["approval_state"] == "APPROVED"
    assert finalized["approved_version"] == "1.0.0"


# ─── seat capacity: pinned evaluation order ───────────────────────────────

def _elevated_shell_with_batch(api):
    """An IN_SESSION, ELEVATED term whose base_seat_cap-10 shell has an eleven-add
    SIS batch staged and validated against it."""
    term = fx.create_term_in_state(api, "IN_SESSION")
    owner = fx.create_faculty(api)
    shell = fx.provision_shell(api, term["id"], owner["id"], base_seat_cap=10)
    cap_under_normal = shell["effective_seat_cap"]

    fx.change_posture(api, term["id"], "ELEVATED", "finals-season staffing shortage")
    cap_under_elevated = fx.read_shell(api, shell["id"])["effective_seat_cap"]

    students = fx.create_students(api, 12)
    operations = [
        fac.sync_operation("ADD", shell["id"], person["id"], "STUDENT")
        for person in students[:11]
    ]
    batch = fx.stage_sync_batch(api, term["id"], operations)
    validated = fx.transition_sync_batch(api, batch["id"], "VALIDATE")
    return {
        "term": term,
        "shell": shell,
        "students": students,
        "batch": batch,
        "validated": validated,
        "cap_under_normal": cap_under_normal,
        "cap_under_elevated": cap_under_elevated,
    }


def test_effective_seat_cap_is_frozen_for_the_whole_promotion_run(api):
    """Eleven students fill a cap-10/allowance-1 shell and the cap stays 11.

    PRD §3.4: "Step one derives the overflow ratio from the *term's*
    `continuity_posture` and from nothing else: 0.00 under `NORMAL`, 0.10 under
    `ELEVATED`, and 0.20 under `CONTINUITY_MODE`."
    PRD §3.4: "Step two freezes `effective_seat_cap` at `base_seat_cap` plus that
    allowance, and that frozen value governs the entire run — it is never
    recomputed between individual promotions inside one run."
    PRD §3.4: "The utilization denominator is always `base_seat_cap` and never
    `effective_seat_cap`, and `overflow_flag` is strictly an output of step five:
    it must never feed back into the ratio chosen in step one."
    PRD §3.4: "An overflowing shell legitimately reports above full utilization:
    eleven active students against a base cap of 10 reads a `seat_utilization_pct`
    of 110.00 with `overflow_flag` true."

    Design: Difficulty/combinatorial_formula/waitlist_capacity_pinned_evaluation_order_keeps_overflow_flag_out_of_its_own_input
    """
    setup = _elevated_shell_with_batch(api)
    assert setup["cap_under_normal"] == 10
    assert setup["cap_under_elevated"] == 11
    assert setup["validated"]["validated_operation_count"] == 11
    assert setup["validated"]["rejected_operation_count"] == 0

    applied = fx.transition_sync_batch(api, setup["batch"]["id"], "APPLY")
    assert applied["batch_state"] == "APPLIED"
    assert applied["applied_add_count"] == 11

    shell = fx.read_shell(api, setup["shell"]["id"])
    assert shell["active_enrollment_count"] == 11
    assert shell["waitlisted_enrollment_count"] == 0
    assert shell["seat_utilization_pct"] == 110.00
    assert shell["overflow_flag"] is True
    # A fed-back overflow_flag would have widened the ratio to 0.20 and read 12.
    assert shell["effective_seat_cap"] == 11

    term = fx.read_term(api, setup["term"]["id"])
    assert term["total_active_enrollments"] == 11
    assert term["overflow_shell_count"] == 1
    assert term["sis_sync_epoch"] == setup["batch"]["batch_seq"] == 1


def test_the_twelfth_seat_is_refused_because_the_cap_never_widened(api):
    """A direct ACTIVE create against the filled shell is refused, not absorbed.

    PRD §3.4: "Asking for a live seat requires three things: the shell's
    `provisioning_state` is `PROVISIONED` or `PUBLISHED` (otherwise
    `ERR_SHELL_STATE_BLOCKS_ENROLLMENT`); no other enrollment exists for that same
    shell-and-person pair whose `enrollment_state` is `ACTIVE`, `WAITLISTED` or
    `DROPPED` (otherwise `ERR_ROLE_CONFLICT`); and, when the `role` is `STUDENT`,
    the shell's `active_enrollment_count` is still below its `effective_seat_cap`
    (otherwise `ERR_SEAT_CAP_EXCEEDED`)."
    PRD §3.4: "Step two freezes `effective_seat_cap` at `base_seat_cap` plus that
    allowance, and that frozen value governs the entire run — it is never
    recomputed between individual promotions inside one run."

    Design: Difficulty/combinatorial_formula/waitlist_capacity_pinned_evaluation_order_keeps_overflow_flag_out_of_its_own_input
    """
    setup = _elevated_shell_with_batch(api)
    fx.transition_sync_batch(api, setup["batch"]["id"], "APPLY")

    twelfth = setup["students"][11]
    response = api.create_enrollment(
        fac.create_enrollment_payload(
            setup["shell"]["id"], twelfth["id"], role="STUDENT",
            requested_state="ACTIVE",
        ),
        fx.REGISTRAR,
    )
    validate_error(response, "ERR_SEAT_CAP_EXCEEDED", 422)

    shell = fx.read_shell(api, setup["shell"]["id"])
    assert shell["active_enrollment_count"] == 11
    assert shell["effective_seat_cap"] == 11
