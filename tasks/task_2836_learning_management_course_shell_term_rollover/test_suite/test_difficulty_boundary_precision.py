"""Boundary and precision probes on three different metrics.

Each metric is exercised exactly on its boundary and one step to either side:
the rollover-readiness percentage over an empty versus a one-member input set,
the seat-cap overflow allowance at the floor() step, and the two inclusive risk
thresholds that fork a tool's approval.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_two_decimals


# ─── rollover_completion_pct: the empty input set ─────────────────────────

def test_a_term_owning_no_shells_reads_one_hundred_and_opens_registration(api):
    """Zero-of-zero is the vacuously-ready convention, not 0.00.

    PRD §3.1: "A newly registered term opens with `lifecycle_state` `PLANNING`
    and `continuity_posture` `NORMAL`, and with every aggregate counter at its
    floor: `published_shell_count`, `overflow_shell_count`,
    `total_active_enrollments`, `open_amendment_count` and `sis_sync_epoch` all
    read 0, while `rollover_completion_pct` reads 100.00 for the reason explained
    in §3.2."
    PRD §3.2: "When the eligible set is empty the percentage is 100.00 by
    convention — which is precisely why a brand-new term with no shells at all
    can open registration."
    PRD §3.2: "Before the gate is evaluated the term's
    `rollover_completion_pct` is recomputed and persisted, and the transition
    proceeds only when the recomputed value is at least 100.00; below that it is
    refused with `ERR_ROLLOVER_INCOMPLETE`."

    Design: Difficulty/boundary_precision_check/rollover_completion_pct_empty_set_convention_versus_zero_percent_at_the_registration_gate
    """
    term = fx.create_term(
        api, term_code="2027SP",
        term_start_at="2027-01-11T00:00:00Z", term_end_at="2027-04-21T00:00:00Z",
    )
    assert term["rollover_completion_pct"] == 100.00

    opened = fx.transition_term(api, term["id"], "REGISTRATION_OPEN")
    assert opened["lifecycle_state"] == "REGISTRATION_OPEN"
    # The recompute over an empty eligible set must not collapse to 0.00.
    assert opened["rollover_completion_pct"] == 100.00


def test_one_uncompleted_official_shell_reads_zero_and_blocks_registration(api):
    """Zero-of-one is 0.00 and the recompute persists even though the gate refuses.

    PRD §3.2: "Before the gate is evaluated the term's
    `rollover_completion_pct` is recomputed and persisted, and the transition
    proceeds only when the recomputed value is at least 100.00; below that it is
    refused with `ERR_ROLLOVER_INCOMPLETE`."
    PRD §3.2: "The percentage itself is defined over a term's **eligible
    shells**: those belonging to the term whose `shell_type` is `OFFICIAL` and
    whose `provisioning_state` is none of `REJECTED`, `MERGED` or `PURGED`."
    PRD §3.2: "Of those, a shell counts as completed when it is the target shell
    of at least one rollover job whose `job_state` is `COMPLETED`."

    Design: Difficulty/boundary_precision_check/rollover_completion_pct_empty_set_convention_versus_zero_percent_at_the_registration_gate
    """
    term = fx.create_term(
        api, term_code="2027SU",
        term_start_at="2027-05-10T00:00:00Z", term_end_at="2027-08-06T00:00:00Z",
    )
    owner = fx.create_faculty(api)
    fx.provision_shell(
        api, term["id"], owner["id"], sis_section_code="SU-CS101",
        shell_type="OFFICIAL", base_seat_cap=25,
    )

    response = api.term_lifecycle_transition(
        term["id"], {"target_state": "REGISTRATION_OPEN"}, fx.REGISTRAR
    )
    validate_error(response, "ERR_ROLLOVER_INCOMPLETE", 422)

    blocked = fx.read_term(api, term["id"])
    assert blocked["lifecycle_state"] == "PLANNING"
    assert blocked["rollover_completion_pct"] == 0.00


def test_a_sandbox_shell_never_enters_the_readiness_denominator(api):
    """A term whose only shell is a SANDBOX still has an empty eligible set.

    PRD §3.2: "Sandbox and development shells are governance artifacts and never
    enter either count, and a shell absorbed by a cross-list merge leaves the
    eligible set, which can move the percentage without any rollover activity at
    all."
    PRD §3.2: "When the eligible set is empty the percentage is 100.00 by
    convention — which is precisely why a brand-new term with no shells at all
    can open registration."

    Design: Difficulty/boundary_precision_check/rollover_completion_pct_empty_set_convention_versus_zero_percent_at_the_registration_gate
    """
    term = fx.create_term(
        api, term_code="2027FA",
        term_start_at="2027-08-23T00:00:00Z", term_end_at="2027-12-10T00:00:00Z",
    )
    owner = fx.create_faculty(api)
    sandbox = fx.provision_shell(
        api, term["id"], owner["id"], sis_section_code="FA-SBX",
        shell_type="SANDBOX", base_seat_cap=5,
    )
    assert sandbox["shell_type"] == "SANDBOX"
    assert sandbox["provisioning_state"] == "PROVISIONED"

    opened = fx.transition_term(api, term["id"], "REGISTRATION_OPEN")
    assert opened["lifecycle_state"] == "REGISTRATION_OPEN"
    # Counting the sandbox would have produced 0.00 and blocked the term.
    assert opened["rollover_completion_pct"] == 100.00


# ─── effective_seat_cap: the floor() step at 9, 10 and 19 seats ───────────

def _three_caps_setup(api):
    """One IN_SESSION term owning PROVISIONED shells of base_seat_cap 9, 10 and 19."""
    term = fx.create_term_in_state(api, "IN_SESSION", term_code="2026FA")
    owner = fx.create_faculty(api)
    shells = {}
    for cap, code in ((9, "NINE-01"), (10, "TEN-01"), (19, "NINETEEN-01")):
        shells[cap] = fx.provision_shell(
            api, term["id"], owner["id"], sis_section_code=code,
            shell_type="OFFICIAL", base_seat_cap=cap,
        )
    return {"term": term, "owner": owner, "shells": shells}


def test_a_nine_seat_shell_buys_nothing_while_a_ten_seat_shell_buys_one(api):
    """floor(0.90) is 0 and floor(1.00) is 1 — the boundary at one whole seat.

    PRD §3.4: "Step one derives the overflow ratio from the *term's*
    `continuity_posture` and from nothing else: 0.00 under `NORMAL`, 0.10 under
    `ELEVATED`, and 0.20 under `CONTINUITY_MODE`. The overflow allowance is the
    shell's `base_seat_cap` multiplied by that ratio and rounded **down** to a
    whole seat."
    PRD §3.4: "Under `ELEVATED`, a shell with `base_seat_cap` 9 gets an allowance
    of 0 and an `effective_seat_cap` of 9, while a shell with `base_seat_cap` 10
    gets an allowance of 1 and an `effective_seat_cap` of 11."
    PRD §3.4: "The capacity rule is evaluated on every enrollment create, on
    every drop that frees a seat, on every applied SIS operation in array order,
    on both directions of a cross-list merge, and whenever the term's
    `continuity_posture` changes, since the ratio moves with it."

    Design: Difficulty/boundary_precision_check/seat_cap_overflow_allowance_floor_boundary_at_nine_ten_and_nineteen_seats
    """
    setup = _three_caps_setup(api)
    # Under NORMAL the ratio is 0.00, so no shell buys a seat.
    assert setup["shells"][9]["effective_seat_cap"] == 9
    assert setup["shells"][10]["effective_seat_cap"] == 10

    elevated = fx.change_posture(api, setup["term"]["id"], "ELEVATED", "boundary probe")
    assert elevated["continuity_posture"] == "ELEVATED"

    nine = fx.read_shell(api, setup["shells"][9]["id"])
    ten = fx.read_shell(api, setup["shells"][10]["id"])
    assert nine["effective_seat_cap"] == 9
    assert ten["effective_seat_cap"] == 11
    # Zero enrollments: 0 / 9 * 100, and no shell is over its base cap.
    assert nine["seat_utilization_pct"] == 0.00
    assert nine["overflow_flag"] is False
    assert ten["overflow_flag"] is False


def test_a_nineteen_seat_shell_still_buys_only_one_seat(api):
    """floor(1.90) is 1; round_half_up would wrongly hand out a second seat.

    PRD §3.4: "The overflow allowance is the shell's `base_seat_cap` multiplied
    by that ratio and rounded **down** to a whole seat."
    PRD §3.4: "Step two freezes `effective_seat_cap` at `base_seat_cap` plus that
    allowance, and that frozen value governs the entire run — it is never
    recomputed between individual promotions inside one run."
    PRD §3.4: "Rounding the allowance down has visible consequences at small
    caps."

    Design: Difficulty/boundary_precision_check/seat_cap_overflow_allowance_floor_boundary_at_nine_ten_and_nineteen_seats
    """
    setup = _three_caps_setup(api)
    assert setup["shells"][19]["effective_seat_cap"] == 19

    fx.change_posture(api, setup["term"]["id"], "ELEVATED", "boundary probe")

    nineteen = fx.read_shell(api, setup["shells"][19]["id"])
    assert nineteen["effective_seat_cap"] == 20
    # A posture change never rewrites the SIS-declared cap it derives from.
    assert nineteen["base_seat_cap"] == 19
    assert fx.read_shell(api, setup["shells"][9]["id"])["base_seat_cap"] == 9
    assert nineteen["seat_utilization_pct"] == 0.00
    assert nineteen["overflow_flag"] is False


# ─── risk_score: the two inclusive approval thresholds ────────────────────

def _cleared_tool(api, **metadata):
    """A tool moved to UNDER_REVIEW with both dimensions CLEARED by distinct people."""
    tool = fx.tool_under_review(api, low_risk=False, tool_version="1.0.0", **metadata)
    fx.file_review(api, tool["id"], "PRIVACY", "CLEAR")
    fx.file_review(api, tool["id"], "ACCESSIBILITY", "CLEAR")
    return tool


def test_a_score_of_exactly_forty_is_conditional_and_thirty_nine_seventy_is_approved(api):
    """One whole VPAT point — 0.30 risk points — separates CONDITIONAL from APPROVED.

    PRD §3.7: "The tool takes `UNDER_REVIEW` → `APPROVED` when neither dimension
    is `BLOCKED`, both dimensions are `CLEARED`, and the freshly computed score is
    below 40.00; `approved_version` is set to the tool's current `tool_version`."
    PRD §3.7: "The tool takes `UNDER_REVIEW` → `CONDITIONAL` when neither
    dimension is `BLOCKED` and either at least one dimension is `CONDITIONAL` or
    the score falls in the range from 40.00 up to but not including 70.00;
    `approved_version` is likewise set to the current `tool_version`, and a
    conditional tool may still be placed."
    PRD §3.7: "Both thresholds are inclusive on their lower edge, and the
    boundaries are live: `pii_tier` 0 with `ROSTER_AND_GRADES`, a `vpat_score` of
    50.00, `wcag_level` `AA` and no placements scores exactly 40.00 and is
    therefore `CONDITIONAL` rather than `APPROVED`, while the same tool with a
    `vpat_score` of 51.00 scores 39.70 and is `APPROVED`;"

    Design: Difficulty/boundary_precision_check/tool_risk_thresholds_are_inclusive_on_the_lower_side_at_forty_and_seventy_points
    """
    at_threshold = _cleared_tool(
        api, vendor_name="VendorP", tool_name="AtThreshold",
        data_sharing_scope="ROSTER_AND_GRADES", pii_tier=0, vpat_score=50.00,
        wcag_level="AA",
    )
    just_under = _cleared_tool(
        api, vendor_name="VendorQ", tool_name="JustUnder",
        data_sharing_scope="ROSTER_AND_GRADES", pii_tier=0, vpat_score=51.00,
        wcag_level="AA",
    )

    conditional = fx.transition_tool(api, at_threshold["id"], "FINALIZE_REVIEW")
    approved = fx.transition_tool(api, just_under["id"], "FINALIZE_REVIEW")

    assert conditional["risk_score"] == 40.00
    assert conditional["approval_state"] == "CONDITIONAL"
    assert conditional["approved_version"] == "1.0.0"

    assert approved["risk_score"] == 39.70
    assert approved["approval_state"] == "APPROVED"
    assert approved["approved_version"] == "1.0.0"

    assert_two_decimals(conditional["risk_score"], "risk_score")
    assert_two_decimals(approved["risk_score"], "risk_score")


def test_a_score_of_exactly_seventy_is_rejected_and_pins_no_version(api):
    """The upper threshold is inclusive too, and only that branch leaves the version null.

    PRD §3.7: "The tool takes `UNDER_REVIEW` → `REJECTED` when either dimension
    is `BLOCKED` or the score is 70.00 or above; `approved_version` is left null,
    and this is the only branch that cascades into placements — every placement
    of the tool whose `placement_state` is `REQUESTED` or `ACTIVE` moves to
    `BLOCKED` in `created_at` ascending order with `blocked_reason` "tool
    rejected"."
    PRD §3.7: "Both thresholds are inclusive on their lower edge, and the
    boundaries are live: ... `pii_tier` 3 with `ROSTER_AND_GRADES`, a `vpat_score`
    of 50.00, `wcag_level` `AA` and no placements scores exactly 70.00 and is
    `REJECTED`."
    PRD §3.7: "The PII points are the `pii_tier` multiplied by 10, so 0 through
    30."

    Design: Difficulty/boundary_precision_check/tool_risk_thresholds_are_inclusive_on_the_lower_side_at_forty_and_seventy_points
    """
    at_reject = _cleared_tool(
        api, vendor_name="VendorR", tool_name="AtReject",
        data_sharing_scope="ROSTER_AND_GRADES", pii_tier=3, vpat_score=50.00,
        wcag_level="AA",
    )

    rejected = fx.transition_tool(api, at_reject["id"], "FINALIZE_REVIEW")
    assert rejected["risk_score"] == 70.00
    assert rejected["approval_state"] == "REJECTED"
    assert rejected["approved_version"] is None
    # No placement exists, so the rejection cascade has nothing to block.
    assert rejected["active_placement_count"] == 0
    assert_two_decimals(rejected["risk_score"], "risk_score")
