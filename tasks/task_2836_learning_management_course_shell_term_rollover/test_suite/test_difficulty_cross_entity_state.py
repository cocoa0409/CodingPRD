"""Depth tests: one entity's operation is decided by another entity's state.

Two pairs are exercised here. A GradePassback's SUBMIT is decided by the
continuity_posture dimension of its grandparent AcademicTerm — the passback, its
shell and its enrollments are untouched between the refusal and the acceptance.
A ToolPlacement's ACTIVATE is decided by two independent fields of its parent
ToolIntegration: the parent's approval_state first, then the parent's
tool_version drifting away from its own approved_version.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    fixtures as fx,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["lms_admin_headers"]

OUTAGE_WINDOW_START = "2026-12-07T08:00:00Z"
OUTAGE_WINDOW_END = "2026-12-08T08:00:00Z"

APPROVED_TOOL_VERSION = "1.0.0"
UPGRADED_TOOL_VERSION = "1.1.0"


def _staged_passback_under_continuity_mode(api):
    """A STAGED passback on a PUBLISHED shell whose term has been frozen.

    The term is walked to FINALS with a single ACTIVE STUDENT enrollment graded
    75.00 against one 100.00-point ASSIGNMENT, so neither ERR_NO_GRADES_STAGED
    nor ERR_FERPA_BLOCK_ACTIVE can fire. The posture is then escalated
    NORMAL -> ELEVATED -> CONTINUITY_MODE, which needs one OPEN OUTAGE window.
    """
    setup = fx.graded_shell_setup(api, points_possible=100.00, grades=(75.00,))
    setup["passback"] = fx.stage_passback(
        api, setup["shell"]["id"], setup["instructor_headers"]
    )
    fx.change_posture(
        api, setup["term"]["id"], "ELEVATED", reason="severe weather watch"
    )
    setup["window"] = fx.open_window_for(
        api, setup["term"]["id"], "OUTAGE", OUTAGE_WINDOW_START, OUTAGE_WINDOW_END
    )
    setup["frozen_term"] = fx.change_posture(
        api,
        setup["term"]["id"],
        "CONTINUITY_MODE",
        reason="datacentre outage during finals",
    )
    return setup


def test_passback_submit_refused_while_the_term_sits_in_continuity_mode(api):
    """PRD §3.8: "**Submitting** (`SUBMIT`) takes `STAGED` → `SUBMITTED` and
    carries three gates: the shell's term must not be in `continuity_posture`
    `CONTINUITY_MODE`, otherwise `ERR_TERM_POSTURE_FROZEN`; no staged enrollment
    may belong to a person whose `ferpa_block` is true, otherwise
    `ERR_FERPA_BLOCK_ACTIVE`; and at least one staged enrollment must have a
    `graded_points_possible` above 0, otherwise `ERR_NO_GRADES_STAGED`."
    PRD §3.9: "It escalates again `ELEVATED` → `CONTINUITY_MODE`, which requires
    at least one window of that term whose `kind` is `OUTAGE` and whose
    `window_state` is `OPEN` to exist, otherwise `ERR_INVALID_STATE_TRANSITION`
    — the highest posture must be justified by a live outage on the record."
    PRD §3.9: "A newly opened window records `affected_enrollment_count` — the
    shell's `active_enrollment_count` for a shell-scoped window, or the term's
    `total_active_enrollments` for a term-wide one"
    PRD §3.8: "The passback opens in `passback_state` `STAGED` with `term_id`
    copied from the shell, `variant_applied` `PROVISIONAL`,
    `staged_enrollment_count` set to the number of gradable rows described
    above, and every provisional percentage computed."

    Design: Difficulty/cross_entity_state_dependency/grade_passback_submit_depends_on_the_academic_terms_continuity_posture
    """
    s = _staged_passback_under_continuity_mode(api)

    assert s["shell"]["provisioning_state"] == "PUBLISHED", (
        "the shell must be published before the freeze, because publishing is "
        "itself posture-gated"
    )
    enrollment = fx.read_enrollment(api, s["enrollments"][0]["id"])
    assert enrollment["earned_points_total"] == pytest.approx(75.00, abs=0.005)
    assert s["passback"]["passback_state"] == "STAGED"
    assert s["passback"]["staged_enrollment_count"] == 1
    assert s["window"]["affected_enrollment_count"] == 1, (
        "a term-wide window snapshots the term's total_active_enrollments"
    )
    assert s["frozen_term"]["continuity_posture"] == "CONTINUITY_MODE"

    refused = api.grade_passback_transition(
        s["passback"]["id"], {"action": "SUBMIT"}, s["instructor_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_TERM_POSTURE_FROZEN.value)

    after = fx.read_passback(api, s["passback"]["id"])
    assert after["passback_state"] == "STAGED", (
        "the refused transition must not have moved the passback"
    )
    assert after["variant_applied"] == "PROVISIONAL"
    assert after["submitted_points_total"] == pytest.approx(0.00, abs=0.005)
    term = fx.read_term(api, s["term"]["id"])
    assert term["lifecycle_state"] == "FINALS", (
        "only the posture dimension moved; the lifecycle dimension is untouched"
    )


def test_passback_submit_accepted_once_the_outage_closes_and_the_posture_thaws(api):
    """PRD §3.9: "It de-escalates `CONTINUITY_MODE` → `ELEVATED`, which requires
    the mirror image: **no** window of that term with `kind` `OUTAGE` and
    `window_state` `OPEN` may remain, otherwise `ERR_INVALID_STATE_TRANSITION`."
    PRD §3.9: "A window is **closed** (`CLOSE`) from `OPEN`, which stamps
    `closed_at` from the logical clock"
    PRD §3.8: "**Submitting** (`SUBMIT`) takes `STAGED` → `SUBMITTED` and carries
    three gates: the shell's term must not be in `continuity_posture`
    `CONTINUITY_MODE`, otherwise `ERR_TERM_POSTURE_FROZEN`; no staged enrollment
    may belong to a person whose `ferpa_block` is true, otherwise
    `ERR_FERPA_BLOCK_ACTIVE`; and at least one staged enrollment must have a
    `graded_points_possible` above 0, otherwise `ERR_NO_GRADES_STAGED`."
    PRD §3.8: "Submitting flips `variant_applied` to `FINAL`, recomputes every
    staged enrollment's `final_grade_pct` under the final variant, sets
    `submitted_points_total` to the sum of the staged enrollments'
    `earned_points_total`, and sets `accepted_points_total` and
    `disputed_points_held` to 0.00."
    PRD §3.8: "The **final** variant divides by the shell's
    `total_points_possible` — every gradable point in the shell, graded or not —
    so missing work drags the figure down, and it writes `final_grade_pct`."

    Design: Difficulty/cross_entity_state_dependency/grade_passback_submit_depends_on_the_academic_terms_continuity_posture
    """
    s = _staged_passback_under_continuity_mode(api)

    refused = api.grade_passback_transition(
        s["passback"]["id"], {"action": "SUBMIT"}, s["instructor_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_TERM_POSTURE_FROZEN.value)

    closed_window = fx.transition_window(api, s["window"]["id"], "CLOSE")
    assert closed_window["window_state"] == "CLOSED"
    thawed = fx.change_posture(
        api, s["term"]["id"], "ELEVATED", reason="power restored"
    )
    assert thawed["continuity_posture"] == "ELEVATED", (
        "the same term row must now be out of CONTINUITY_MODE"
    )

    submitted = fx.transition_passback(
        api, s["passback"]["id"], "SUBMIT", s["instructor_headers"]
    )
    assert submitted["passback_state"] == "SUBMITTED", (
        "the byte-identical request now succeeds: only the parent term's posture "
        "changed"
    )
    assert submitted["variant_applied"] == "FINAL"
    assert submitted["submitted_points_total"] == pytest.approx(75.00, abs=0.005)
    assert submitted["accepted_points_total"] == pytest.approx(0.00, abs=0.005)
    assert submitted["disputed_points_held"] == pytest.approx(0.00, abs=0.005)

    enrollment = fx.read_enrollment(api, s["enrollments"][0]["id"])
    assert enrollment["final_grade_pct"] == pytest.approx(75.00, abs=0.005), (
        "75.00 earned over the shell's 100.00 total_points_possible"
    )
    term = fx.read_term(api, s["term"]["id"])
    assert term["lifecycle_state"] == "FINALS"


def _placement_on_a_tool_still_under_review(api):
    """A REQUESTED placement whose tool has both verdicts in but is not finalised.

    The tool carries pii_tier 0, data_sharing_scope ROSTER_ONLY, vpat_score 90.00
    and wcag_level AA, so its score stays well under the conditional threshold
    and a two-CLEAR round finalises straight to APPROVED.
    """
    setup = fx.provisioned_shell_setup(api, "IN_SESSION")
    tool = fx.tool_under_review(api, tool_version=APPROVED_TOOL_VERSION)
    fx.file_review(api, tool["id"], "PRIVACY", "CLEAR")
    fx.file_review(api, tool["id"], "ACCESSIBILITY", "CLEAR")
    setup["tool"] = tool
    setup["placement"] = fx.request_placement(api, tool["id"], setup["shell"]["id"])
    return setup


def test_placement_activation_refused_while_its_tool_is_still_under_review(api):
    """PRD §3.7: "A tool is put in front of students by placing it in a shell: an
    `Instructor` or `LmsAdmin` names a `tool_id` and a `shell_id`, and the
    placement opens in `placement_state` `REQUESTED` with `pinned_tool_version`
    null."
    PRD §3.7: "**Activating** (`ACTIVATE`) requires the tool's `approval_state` to
    be `APPROVED` or `CONDITIONAL`, otherwise `ERR_TOOL_NOT_APPROVED`; the tool's
    `approved_version` to equal its current `tool_version`, otherwise
    `ERR_TOOL_VERSION_DRIFT`, which is what stops a vendor upgrade from slipping
    into classrooms on the strength of an older approval; the shell's
    `provisioning_state` to be `PROVISIONED` or `PUBLISHED`, otherwise
    `ERR_SHELL_STATE_BLOCKS_ENROLLMENT`; and, when the tool's
    `data_sharing_scope` is anything other than `NONE`, that no enrollment of the
    shell whose `enrollment_state` is `ACTIVE` or `WAITLISTED` belongs to a person
    whose `ferpa_block` is true, otherwise `ERR_FERPA_BLOCK_ACTIVE`."
    PRD §3.7: "The tool takes `UNDER_REVIEW` → `APPROVED` when neither dimension
    is `BLOCKED`, both dimensions are `CLEARED`, and the freshly computed score is
    below 40.00; `approved_version` is set to the tool's current `tool_version`."
    PRD §3.7: "A new tool opens with `approval_state` `DRAFT`,
    `privacy_review_state` `PENDING`, `accessibility_review_state` `PENDING`,
    `risk_score` null, `approved_version` null, `active_placement_count` 0 and
    `suspension_reason` null."
    PRD §3.7: "An `LmsAdmin` opens the review by an `action` of `OPEN_REVIEW`,
    which takes `approval_state` `DRAFT` → `UNDER_REVIEW` and requires both verdict
    dimensions to be `PENDING`."
    PRD §2.4: "Almost every record additionally carries `updated_at` — the same
    timestamp format, refreshed on every mutation — and `version`, an integer that
    starts at 1 on creation and increments by exactly one on every mutation of
    that record."

    Design: Difficulty/cross_entity_state_dependency/tool_placement_activation_depends_on_the_tool_integrations_approval_and_version
    """
    s = _placement_on_a_tool_still_under_review(api)

    assert s["shell"]["provisioning_state"] == "PROVISIONED", (
        "the shell-side gate is satisfied, so only the tool's state can decide"
    )
    assert s["placement"]["placement_state"] == "REQUESTED"
    assert s["placement"]["pinned_tool_version"] is None
    before = fx.read_tool(api, s["tool"]["id"])
    assert before["approval_state"] == "UNDER_REVIEW"
    assert before["approved_version"] is None

    refused = api.tool_placement_transition(
        s["placement"]["id"], {"action": "ACTIVATE"}, ADMIN
    )
    validate_error(refused, ApiErrorId.ERR_TOOL_NOT_APPROVED.value)

    untouched = fx.read_placement(api, s["placement"]["id"])
    assert untouched["placement_state"] == "REQUESTED", (
        "a refused activation leaves the placement exactly as it was"
    )
    assert untouched["pinned_tool_version"] is None
    assert untouched["version"] == s["placement"]["version"], (
        "version increments only on a mutation, and nothing was mutated"
    )

    approved = fx.transition_tool(api, s["tool"]["id"], "FINALIZE_REVIEW")
    assert approved["approval_state"] == "APPROVED"
    assert approved["approved_version"] == APPROVED_TOOL_VERSION
    assert approved["risk_score"] == pytest.approx(13.00, abs=0.005)


def test_placement_activation_refused_on_version_drift_then_pins_the_approved_version(api):
    """PRD §4: "Record a vendor upgrade or revised privacy/accessibility metadata.
    A tool_version change strands approved_version and produces version drift."
    PRD §3.7: "**Activating** (`ACTIVATE`) requires the tool's `approval_state` to
    be `APPROVED` or `CONDITIONAL`, otherwise `ERR_TOOL_NOT_APPROVED`; the tool's
    `approved_version` to equal its current `tool_version`, otherwise
    `ERR_TOOL_VERSION_DRIFT`, which is what stops a vendor upgrade from slipping
    into classrooms on the strength of an older approval; the shell's
    `provisioning_state` to be `PROVISIONED` or `PUBLISHED`, otherwise
    `ERR_SHELL_STATE_BLOCKS_ENROLLMENT`; and, when the tool's
    `data_sharing_scope` is anything other than `NONE`, that no enrollment of the
    shell whose `enrollment_state` is `ACTIVE` or `WAITLISTED` belongs to a person
    whose `ferpa_block` is true, otherwise `ERR_FERPA_BLOCK_ACTIVE`."
    PRD §3.7: "Activation pins `pinned_tool_version` to the tool's
    `approved_version`, raises the tool's `active_placement_count` by one,
    re-scores the tool, and re-derives the shell's `publish_readiness`."
    PRD §3.7: "The exposure points are the `active_placement_count` multiplied by
    3, capped at 15."
    PRD §3.7: "A shell is publish-ready exactly when its
    `blocked_placement_count` is 0."

    Design: Difficulty/cross_entity_state_dependency/tool_placement_activation_depends_on_the_tool_integrations_approval_and_version
    """
    s = _placement_on_a_tool_still_under_review(api)
    approved = fx.transition_tool(api, s["tool"]["id"], "FINALIZE_REVIEW")
    assert approved["approved_version"] == APPROVED_TOOL_VERSION

    upgraded = validate_success(
        api.patch_tool_integration(
            s["tool"]["id"], {"tool_version": UPGRADED_TOOL_VERSION}, ADMIN
        )
    )
    assert upgraded["tool_version"] == UPGRADED_TOOL_VERSION
    assert upgraded["approved_version"] == APPROVED_TOOL_VERSION, (
        "the vendor upgrade strands the approved version rather than re-approving"
    )
    assert upgraded["approval_state"] == "APPROVED", (
        "the approval dimension itself is untouched by the metadata edit"
    )

    drifted = api.tool_placement_transition(
        s["placement"]["id"], {"action": "ACTIVATE"}, ADMIN
    )
    validate_error(drifted, ApiErrorId.ERR_TOOL_VERSION_DRIFT.value)
    still_requested = fx.read_placement(api, s["placement"]["id"])
    assert still_requested["placement_state"] == "REQUESTED"
    assert still_requested["pinned_tool_version"] is None
    assert still_requested["version"] == s["placement"]["version"], (
        "the second refusal is as side-effect free as the first"
    )

    restored = validate_success(
        api.patch_tool_integration(
            s["tool"]["id"], {"tool_version": APPROVED_TOOL_VERSION}, ADMIN
        )
    )
    assert restored["tool_version"] == restored["approved_version"]

    active = fx.transition_placement(api, s["placement"]["id"], "ACTIVATE")
    assert active["placement_state"] == "ACTIVE", (
        "the identical activation request now succeeds on the strength of the "
        "parent tool's fields alone"
    )
    assert active["pinned_tool_version"] == APPROVED_TOOL_VERSION

    tool = fx.read_tool(api, s["tool"]["id"])
    assert tool["active_placement_count"] == 1
    assert tool["risk_score"] == pytest.approx(16.00, abs=0.005), (
        "re-scoring adds 3 exposure points for the one active placement"
    )
    shell = fx.read_shell(api, s["shell"]["id"])
    assert shell["blocked_placement_count"] == 0
    assert shell["publish_readiness"] is True
