"""Parallel style dimensions, the label revision cycle, the audit lifecycle
fall-back, and the three transitive cascades of the labeling service.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    ADMIN,
    AUDITOR,
    LAB,
    APPROVER,
    SPECIALIST,
    validate_error,
    validate_success,
    assert_finding_unit_conservation,
    add_material_input,
    approve_label,
    create_style,
    open_audit,
    raise_finding,
    register_brand,
    register_market,
    create_hangtag,
    draft_determination,
    draft_permanent_label,
    expected_content_hash,
    fiber_results_payload,
    post_results,
    publish_label,
    read_audit,
    read_brand,
    read_label,
    read_style,
    record_disposition,
    reopen_finding,
    reserve_fiber_test,
    retest_payload,
    setup_audit_with_findings,
    setup_label_ready_style,
    setup_pending_permanent_label,
    submit_label,
    verify_finding,
)


# --- module-local setup helpers ------------------------------------------

# A measurement that deviates 3.5 percentage points from the default
# 60.0 COTTON / 40.0 POLYESTER declaration, so it exceeds the US market's
# fiber_tolerance_pp of 3.0 while its measured sum stays at 100.0.
FAILING_MEASUREMENT = [
    {"fiber_generic_name": "COTTON", "measured_pct": 56.5},
    {"fiber_generic_name": "POLYESTER", "measured_pct": 43.5},
]

LATER_BENCH = {"specimen_received_at": "2026-08-10T09:00:00Z",
               "results_due_at": "2026-08-11T09:00:00Z"}


def _cascade_world():
    """A label-ready style carrying: L1 a PUBLISHED permanent label, H1 a DRAFT
    hangtag hanging off L1, L2 a second permanent label in PENDING_APPROVAL and
    L3 a third permanent label still in DRAFT as the negative control."""
    bundle = setup_label_ready_style()
    l1 = publish_label(approve_label(submit_label(
        draft_permanent_label(bundle)["id"])["id"])["id"],
        "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
    h1 = create_hangtag(l1)
    l2 = submit_label(draft_permanent_label(
        bundle, placement_code="SIDE_SEAM_INSIDE")["id"])
    l3 = draft_permanent_label(bundle, placement_code="WAISTBAND_INSIDE")
    return {
        "bundle": bundle,
        "style_id": bundle["style"]["id"],
        "l1": read_label(l1["id"]),
        "h1": read_label(h1["id"]),
        "l2": l2,
        "l3": l3,
    }


def _three_critical_findings_world():
    """One audit over one brand carrying three CRITICAL findings: two by code and
    one escalated from MAJOR by an affected quantity of 5,000 units."""
    brand_id, style_id, audit, findings = setup_audit_with_findings(
        finding_specs=[
            {"finding_code": "FIBER_CONTENT_MISSTATED", "units_affected": 100},
            {"finding_code": "ORIGIN_MISSTATED", "units_affected": 100},
            {"finding_code": "CARE_UNSUBSTANTIATED", "units_affected": 5000},
        ])
    return brand_id, audit, findings


# =========================================================================
# Style's two orthogonal state dimensions
# =========================================================================


def test_fiber_dimension_branch_and_cycle_leave_origin_state_issued(api):
    """PRD 3.2: "Every style carries **two independent state dimensions on the same
    row**, and this independence is not decorative: nothing in one dimension reads
    or writes the other."

    PRD 3.4: "A fiber-content reservation also drives the style's substantiation
    dimension: from `FIBER_DECLARED` it advances to `FIBER_TEST_PENDING`, and from
    `FIBER_SUBSTANTIATED` it *also* advances to `FIBER_TEST_PENDING`, which is the
    re-verification of an already substantiated style."

    PRD 3.4: "A fiber-content retest drives the style's substantiation dimension
    from `FIBER_MISSTATED` back to `FIBER_TEST_PENDING` and increments the style's
    `version` by 1."

    Design: Difficulty/non_linear_state_machine/style_substantiation_and_origin_dimensions_advance_independently
    """
    bundle = setup_label_ready_style(skip_fiber=True, skip_care=True)
    style_id = bundle["style"]["id"]

    s0 = read_style(style_id)
    assert s0["substantiation_state"] == "FIBER_DECLARED", (
        "a style with no laboratory evidence starts at FIBER_DECLARED, got "
        f"{s0['substantiation_state']}")
    assert s0["origin_state"] == "ORIGIN_ISSUED", (
        "issuing a determination advances only the origin dimension, got "
        f"{s0['origin_state']}")

    lab_test = reserve_fiber_test(style_id)
    s1 = read_style(style_id)
    assert s1["substantiation_state"] == "FIBER_TEST_PENDING", (
        "a fiber-content reservation moves FIBER_DECLARED to FIBER_TEST_PENDING, "
        f"got {s1['substantiation_state']}")
    assert s1["origin_state"] == "ORIGIN_ISSUED", (
        "the reservation must not perturb the origin dimension, got "
        f"{s1['origin_state']}")

    post_results(lab_test["id"], {"measured_fibers": FAILING_MEASUREMENT})
    s2 = read_style(style_id)
    assert s2["substantiation_state"] == "FIBER_MISSTATED", (
        "a failing fiber-content run branches the dimension to FIBER_MISSTATED, "
        f"got {s2['substantiation_state']}")
    assert s2["origin_state"] == "ORIGIN_ISSUED", (
        "the failure cascade must not perturb the origin dimension, got "
        f"{s2['origin_state']}")

    retested = validate_success(
        api.retest_lab_test(lab_test["id"], retest_payload(), LAB), 200)
    assert retested["state"] == "BENCH_RESERVED", (
        f"a retest returns the row to BENCH_RESERVED, got {retested['state']}")
    assert retested["attempt_no"] == 2, (
        f"a retest increments attempt_no to 2, got {retested['attempt_no']}")
    s3 = read_style(style_id)
    assert s3["substantiation_state"] == "FIBER_TEST_PENDING", (
        "a fiber-content retest returns FIBER_MISSTATED to FIBER_TEST_PENDING, "
        f"got {s3['substantiation_state']}")
    assert s3["origin_state"] == "ORIGIN_ISSUED", (
        f"the retest must not perturb the origin dimension, got {s3['origin_state']}")

    post_results(lab_test["id"], fiber_results_payload())
    s4 = read_style(style_id)
    assert s4["substantiation_state"] == "FIBER_SUBSTANTIATED", (
        "a passing fiber-content run advances FIBER_TEST_PENDING to "
        f"FIBER_SUBSTANTIATED, got {s4['substantiation_state']}")
    assert s4["origin_state"] == "ORIGIN_ISSUED", (
        f"the pass must not perturb the origin dimension, got {s4['origin_state']}")
    assert s4["label_readiness"] == "READY", (
        "label_readiness reads READY only once both dimensions are satisfied, got "
        f"{s4['label_readiness']}")


def test_supply_graph_append_resets_only_the_origin_dimension(api):
    """PRD 3.3: "Alongside all that, the style's `origin_state` drops from
    `ORIGIN_ISSUED` to `ORIGIN_UNDETERMINED`, `label_readiness` becomes `BLOCKED`,
    `label_readiness` is recomputed, and the style's `version` is incremented by 1
    — as is the version of the voided determination and of every artifact the
    cascade touched."

    PRD 3.2: "What makes the pair observable is the computed `label_readiness`
    field, which reads `READY` when `substantiation_state` is `FIBER_SUBSTANTIATED`
    **and** `origin_state` is `ORIGIN_ISSUED`, and reads `BLOCKED` in every other
    combination."

    Design: Difficulty/non_linear_state_machine/style_substantiation_and_origin_dimensions_advance_independently
    """
    bundle = setup_label_ready_style()
    style_id = bundle["style"]["id"]

    before = read_style(style_id)
    assert before["substantiation_state"] == "FIBER_SUBSTANTIATED", (
        f"expected FIBER_SUBSTANTIATED, got {before['substantiation_state']}")
    assert before["origin_state"] == "ORIGIN_ISSUED", (
        f"expected ORIGIN_ISSUED, got {before['origin_state']}")
    assert before["label_readiness"] == "READY", (
        f"both dimensions satisfied must read READY, got {before['label_readiness']}")

    node = add_material_input(style_id, stage="TRIM", country_code="TR",
                              value_added_usd=0.40, weight_grams=10.0,
                              is_ornamentation=True)
    assert node["depth"] == 0, (
        f"a TRIM node is always a graph root at depth 0, got {node['depth']}")

    after = read_style(style_id)
    assert after["origin_state"] == "ORIGIN_UNDETERMINED", (
        "appending a supply node drops origin_state to ORIGIN_UNDETERMINED, got "
        f"{after['origin_state']}")
    assert after["substantiation_state"] == "FIBER_SUBSTANTIATED", (
        "no part of the origin cascade touches the substantiation dimension, got "
        f"{after['substantiation_state']}")
    assert after["label_readiness"] == "BLOCKED", (
        f"label_readiness must fall back to BLOCKED, got {after['label_readiness']}")
    assert after["version"] == before["version"] + 1, (
        "the style's version is incremented by exactly 1 by the append, expected "
        f"{before['version'] + 1}, got {after['version']}")


def test_redrafting_a_determination_moves_only_the_origin_dimension(api):
    """PRD 3.3: "From `ORIGIN_ISSUED` the style returns to `ORIGIN_DRAFTED` while
    the issued row **keeps standing** until the new row is itself issued;
    `label_readiness` returns to `BLOCKED`, which is what blocks any
    permanent-label approval while the re-draft is pending."

    Design: Difficulty/non_linear_state_machine/style_substantiation_and_origin_dimensions_advance_independently
    """
    bundle = setup_label_ready_style()
    style_id = bundle["style"]["id"]
    issued_id = bundle["determination"]["id"]

    before = read_style(style_id)
    new_draft = draft_determination(style_id)
    assert new_draft["state"] == "DRAFT", (
        f"a re-draft is created in DRAFT, got {new_draft['state']}")

    still_issued = validate_success(
        api.get_origin_determination(issued_id, ADMIN), 200)
    assert still_issued["state"] == "ISSUED", (
        "the previously issued determination keeps standing until the new row is "
        f"itself issued, got {still_issued['state']}")

    after = read_style(style_id)
    assert after["origin_state"] == "ORIGIN_DRAFTED", (
        "re-drafting from ORIGIN_ISSUED returns the style to ORIGIN_DRAFTED, got "
        f"{after['origin_state']}")
    assert after["substantiation_state"] == "FIBER_SUBSTANTIATED", (
        "the origin re-draft must not perturb the substantiation dimension, got "
        f"{after['substantiation_state']}")
    assert after["label_readiness"] == "BLOCKED", (
        f"label_readiness returns to BLOCKED, got {after['label_readiness']}")
    assert after["version"] == before["version"] + 1, (
        "the style's version is incremented by 1 by the re-draft, expected "
        f"{before['version'] + 1}, got {after['version']}")


# =========================================================================
# The permanent-label revision cycle
# =========================================================================

REVISION_NOTE = "Placement must be the side seam for this silhouette."


def test_revision_cycle_returns_to_pending_approval_and_then_approves(api):
    """PRD 3.6: "That requires the artifact to be in `PENDING_APPROVAL`, takes a
    `revision_note`, moves the artifact to `REVISION_REQUESTED`, stores the note,
    and increments its `version` by 1."

    PRD 3.5: "A `DRAFT` artifact self-transitions and stays in `DRAFT`; a
    `REVISION_REQUESTED` artifact returns to `DRAFT` and its `revision_note` is
    cleared."

    Design: Difficulty/non_linear_state_machine/label_spec_revision_cycle_returns_to_pending_approval_and_then_approves
    """
    bundle, label = setup_pending_permanent_label()
    label_id = label["id"]
    assert label["state"] == "PENDING_APPROVAL", (
        f"a submitted permanent label sits in PENDING_APPROVAL, got {label['state']}")

    sent_back = validate_success(
        api.request_revision_label_spec(label_id, REVISION_NOTE, APPROVER), 200)
    assert sent_back["state"] == "REVISION_REQUESTED", (
        "request-revision moves PENDING_APPROVAL to REVISION_REQUESTED, got "
        f"{sent_back['state']}")
    assert sent_back["revision_note"] == REVISION_NOTE, (
        f"the supplied note must be stored, got {sent_back['revision_note']!r}")
    assert sent_back["version"] == label["version"] + 1, (
        "request-revision increments the artifact's version by 1, expected "
        f"{label['version'] + 1}, got {sent_back['version']}")

    edited = validate_success(api.update_label_spec(
        label_id, {"placement_code": "SIDE_SEAM_INSIDE"}, SPECIALIST), 200)
    assert edited["state"] == "DRAFT", (
        f"editing a REVISION_REQUESTED artifact returns it to DRAFT, got {edited['state']}")
    assert edited["revision_note"] is None, (
        "the revision_note is cleared the next time the author edits the artifact, "
        f"got {edited['revision_note']!r}")
    assert edited["placement_code"] == "SIDE_SEAM_INSIDE", (
        f"the edit must apply, got {edited['placement_code']}")
    assert edited["version"] == sent_back["version"] + 1, (
        "the edit increments the artifact's version by 1, expected "
        f"{sent_back['version'] + 1}, got {edited['version']}")

    resubmitted = validate_success(api.submit_label_spec(label_id, SPECIALIST), 200)
    assert resubmitted["state"] == "PENDING_APPROVAL", (
        "the second submit re-enters PENDING_APPROVAL, got "
        f"{resubmitted['state']}")

    approved = validate_success(api.approve_label_spec(label_id, APPROVER), 200)
    assert approved["state"] == "APPROVED", (
        f"the second lap of the gate must approve, got {approved['state']}")
    assert approved["approved_by_user_id"] == APPROVER["X-User-ID"], (
        "approved_by_user_id is the acting approver's X-User-ID, got "
        f"{approved['approved_by_user_id']!r}")
    assert approved["authored_by_user_id"] == SPECIALIST["X-User-ID"], (
        "authored_by_user_id is the operator that last edited the artifact, got "
        f"{approved['authored_by_user_id']!r}")


def test_patch_while_pending_and_approve_while_revision_requested_are_refused(api):
    """PRD 3.5: "Editing an artifact is permitted while it is in `DRAFT` or in
    `REVISION_REQUESTED`, and any other state is rejected with
    `ERR_LABEL_STATE_INVALID`."

    PRD 3.6: "The artifact must be in `PENDING_APPROVAL`; any other state is
    rejected with `ERR_LABEL_STATE_INVALID`."

    Design: Difficulty/non_linear_state_machine/label_spec_revision_cycle_returns_to_pending_approval_and_then_approves
    """
    bundle, label = setup_pending_permanent_label()
    label_id = label["id"]

    validate_error(
        api.update_label_spec(label_id, {"placement_code": "SIDE_SEAM_INSIDE"},
                              SPECIALIST),
        ApiErrorId.ERR_LABEL_STATE_INVALID)
    untouched = read_label(label_id)
    assert untouched["placement_code"] == label["placement_code"], (
        "a refused edit must not mutate the artifact, got "
        f"{untouched['placement_code']}")
    assert untouched["version"] == label["version"], (
        f"a refused edit must not bump the version, got {untouched['version']}")

    sent_back = validate_success(
        api.request_revision_label_spec(label_id, REVISION_NOTE, APPROVER), 200)
    assert sent_back["state"] == "REVISION_REQUESTED", (
        f"expected REVISION_REQUESTED, got {sent_back['state']}")

    validate_error(api.approve_label_spec(label_id, APPROVER),
                   ApiErrorId.ERR_LABEL_STATE_INVALID)
    still_back = read_label(label_id)
    assert still_back["state"] == "REVISION_REQUESTED", (
        "a refused approval leaves the artifact in REVISION_REQUESTED, got "
        f"{still_back['state']}")


def test_re_edit_out_of_revision_requested_recomputes_content_hash(api):
    """PRD 3.5: "In both cases `content_hash` is recomputed, `authored_by_user_id`
    is set to the acting operator's `X-User-ID` — which re-arms the
    segregation-of-duties check for the next approval attempt — a hangtag
    additionally has its `consistency_state` recomputed against its parent, and the
    artifact's `version` is incremented by 1."

    PRD 3.5: "It is built by concatenating five segments separated by a single
    vertical-bar character, in this order: the normalized `fiber_content_text`; the
    normalized `origin_text`; the care code string; the identity string; and the
    artifact's `languages` sorted ascending and joined with a single comma between
    entries."

    Design: Difficulty/non_linear_state_machine/label_spec_revision_cycle_returns_to_pending_approval_and_then_approves
    """
    bundle, label = setup_pending_permanent_label()
    label_id = label["id"]
    hash_before = label["content_hash"]

    validate_success(
        api.request_revision_label_spec(label_id, REVISION_NOTE, APPROVER), 200)
    edited = validate_success(api.update_label_spec(
        label_id, {"languages": ["en", "fr"]}, SPECIALIST), 200)

    assert edited["state"] == "DRAFT", (
        f"the re-edit returns the artifact to DRAFT, got {edited['state']}")
    assert edited["languages"] == ["en", "fr"], (
        f"the edited languages must be stored, got {edited['languages']}")
    assert edited["content_hash"] != hash_before, (
        "editing a hash-bearing field must recompute content_hash, it is still "
        f"{edited['content_hash']}")

    brand = bundle["brand"]
    expected = expected_content_hash(
        edited["fiber_content_text"], edited["origin_text"], edited["wash_temp_c"],
        edited["bleach_code"], edited["dry_code"], edited["iron_code"],
        edited["dryclean_code"], edited["identity_display_mode"],
        edited["languages"], rn_number=brand["rn_number"],
        legal_name=brand["legal_name"])
    assert edited["content_hash"] == expected, (
        f"expected content_hash {expected}, got {edited['content_hash']}")

    reapproved = validate_success(api.approve_label_spec(
        validate_success(api.submit_label_spec(label_id, SPECIALIST), 200)["id"],
        APPROVER), 200)
    assert reapproved["state"] == "APPROVED", (
        "the cycle must still close after the re-edit, got "
        f"{reapproved['state']}")


# =========================================================================
# The audit lifecycle: PENDING_CLOSURE falls back to IN_REVIEW
# =========================================================================

REOPEN_REASON = "Spot check found the same care claim on 40 remaining units."


def _one_finding_audit():
    """One audit over one brand carrying exactly one MAJOR finding of 100 units,
    observed from its OPEN starting state."""
    register_market("US")
    brand = register_brand()
    style = create_style(brand["id"])
    audit = open_audit(brand["id"])
    return brand, style, audit


def test_audit_walks_open_in_review_pending_closure_and_back_to_in_review(api):
    """PRD 3.9: "an audit in `IN_REVIEW` whose open-finding count has reached 0
    moves to `PENDING_CLOSURE`, and an audit in `PENDING_CLOSURE` whose
    open-finding count has risen above 0 falls back to `IN_REVIEW`."

    PRD 3.9: "`open_finding_count` counts the findings whose state is `OPEN` **or**
    `REMEDIATED` — a remediated finding is still open for closure purposes, because
    nobody has verified it yet."

    Design: Difficulty/non_linear_state_machine/audit_falls_back_from_pending_closure_to_in_review_on_reopen
    """
    brand, style, audit = _one_finding_audit()
    assert audit["state"] == "OPEN", (
        f"a new audit lands in OPEN, got {audit['state']}")
    assert audit["open_finding_count"] == 0, (
        f"a new audit has open_finding_count 0, got {audit['open_finding_count']}")

    finding = raise_finding(audit["id"], style["id"],
                            finding_code="CARE_UNSUBSTANTIATED", units_affected=100)
    a1 = read_audit(audit["id"])
    assert a1["state"] == "IN_REVIEW", (
        f"the first finding drives the audit from OPEN to IN_REVIEW, got {a1['state']}")
    assert a1["open_finding_count"] == 1, (
        f"one OPEN finding gives open_finding_count 1, got {a1['open_finding_count']}")

    remediated = record_disposition(finding["id"], units_destroyed=100)
    assert remediated["state"] == "REMEDIATED", (
        f"a complete disposition moves OPEN to REMEDIATED, got {remediated['state']}")
    a2 = read_audit(audit["id"])
    assert a2["state"] == "IN_REVIEW", (
        "a remediated finding is still open for closure purposes, so the audit stays "
        f"IN_REVIEW, got {a2['state']}")
    assert a2["open_finding_count"] == 1, (
        "a REMEDIATED finding still counts towards open_finding_count, got "
        f"{a2['open_finding_count']}")

    closed = verify_finding(finding["id"])
    assert closed["state"] == "CLOSED", (
        f"verification moves REMEDIATED to CLOSED, got {closed['state']}")
    a3 = read_audit(audit["id"])
    assert a3["state"] == "PENDING_CLOSURE", (
        "an IN_REVIEW audit whose open-finding count reaches 0 moves to "
        f"PENDING_CLOSURE, got {a3['state']}")
    assert a3["open_finding_count"] == 0, (
        f"a CLOSED finding leaves the open set, got {a3['open_finding_count']}")

    reopened = reopen_finding(finding["id"], REOPEN_REASON)
    assert reopened["state"] == "OPEN", (
        f"reopening returns the finding to OPEN, got {reopened['state']}")
    a4 = read_audit(audit["id"])
    assert a4["state"] == "IN_REVIEW", (
        "a PENDING_CLOSURE audit whose open-finding count rises above 0 falls back "
        f"to IN_REVIEW, got {a4['state']}")
    assert a4["open_finding_count"] == 1, (
        f"the reopened finding is counted again, got {a4['open_finding_count']}")


def test_close_is_refused_once_the_audit_has_fallen_back_to_in_review(api):
    """PRD 3.9: "A close requested while the audit is in `IN_REVIEW` — which means
    it still has open findings — is rejected with `ERR_AUDIT_STATE_INVALID`."

    PRD 3.9: "The parent audit is pulled from `PENDING_CLOSURE` back to `IN_REVIEW`
    and re-derives its counters, and the brand-of-record's `posture` is recomputed."

    Design: Difficulty/non_linear_state_machine/audit_falls_back_from_pending_closure_to_in_review_on_reopen
    """
    brand, style, audit = _one_finding_audit()
    finding = raise_finding(audit["id"], style["id"],
                            finding_code="CARE_UNSUBSTANTIATED", units_affected=100)
    record_disposition(finding["id"], units_destroyed=100)
    verify_finding(finding["id"])
    assert read_audit(audit["id"])["state"] == "PENDING_CLOSURE", (
        "the audit must reach PENDING_CLOSURE before the fall-back is exercised")

    reopen_finding(finding["id"], REOPEN_REASON)
    validate_error(api.close_compliance_audit(audit["id"], AUDITOR),
                   ApiErrorId.ERR_AUDIT_STATE_INVALID)
    after = read_audit(audit["id"])
    assert after["state"] == "IN_REVIEW", (
        f"the refused close leaves the audit in IN_REVIEW, got {after['state']}")
    assert after["closed_at"] is None, (
        f"a refused close must not stamp closed_at, got {after['closed_at']!r}")


def test_reopen_restores_the_unit_buckets_and_leaves_units_in_scope_alone(api):
    """PRD 3.9: "The finding returns to `OPEN`, stores the reason, clears
    `verified_at`, `disposition_recorded_at` and `corrective_label_spec_id`, and
    resets `units_relabeled`, `units_destroyed` and `units_released` to 0 — which
    restores `units_unresolved` to the full `units_affected` and leaves the audit's
    `units_in_scope` byte-identical to its pre-disposition value."

    PRD 3.9: "`units_in_scope` sums `units_affected` over **every** finding of the
    audit with no state filter at all, which is what makes it invariant under
    disposition, verification and reopening."

    Design: Difficulty/non_linear_state_machine/audit_falls_back_from_pending_closure_to_in_review_on_reopen
    """
    brand, style, audit = _one_finding_audit()
    finding = raise_finding(audit["id"], style["id"],
                            finding_code="CARE_UNSUBSTANTIATED", units_affected=100)
    scope_before = read_audit(audit["id"])["units_in_scope"]
    assert scope_before == 100, (
        f"units_in_scope sums units_affected over every finding, got {scope_before}")

    remediated = record_disposition(finding["id"], units_destroyed=100)
    assert remediated["units_unresolved"] == 0, (
        "a complete disposition drives units_unresolved to 0, got "
        f"{remediated['units_unresolved']}")
    assert read_audit(audit["id"])["units_in_scope"] == 100, (
        "units_in_scope is invariant under disposition")

    verify_finding(finding["id"])
    assert read_audit(audit["id"])["units_in_scope"] == 100, (
        "units_in_scope is invariant under verification")

    reopened = reopen_finding(finding["id"], REOPEN_REASON)
    assert reopened["reopen_reason"] == REOPEN_REASON, (
        f"the reopen reason must be stored, got {reopened['reopen_reason']!r}")
    assert reopened["units_relabeled"] == 0, (
        f"units_relabeled is reset to 0, got {reopened['units_relabeled']}")
    assert reopened["units_destroyed"] == 0, (
        f"units_destroyed is reset to 0, got {reopened['units_destroyed']}")
    assert reopened["units_released"] == 0, (
        f"units_released is reset to 0, got {reopened['units_released']}")
    assert reopened["units_unresolved"] == 100, (
        "reopening restores units_unresolved to the full units_affected, got "
        f"{reopened['units_unresolved']}")
    assert reopened["verified_at"] is None, (
        f"reopening clears verified_at, got {reopened['verified_at']!r}")
    assert reopened["disposition_recorded_at"] is None, (
        f"reopening clears disposition_recorded_at, got "
        f"{reopened['disposition_recorded_at']!r}")
    assert reopened["corrective_label_spec_id"] is None, (
        "reopening clears corrective_label_spec_id, got "
        f"{reopened['corrective_label_spec_id']!r}")
    assert_finding_unit_conservation(reopened)
    assert read_audit(audit["id"])["units_in_scope"] == scope_before, (
        "units_in_scope is byte-identical to its pre-disposition value after a reopen")


# =========================================================================
# Cascade: a failed re-verification travels test -> style -> labels -> hangtags
# =========================================================================


def test_failed_reverification_withdraws_published_and_pending_labels(api):
    """PRD 3.4: "The second hop, caused by the first, sets the style's
    `substantiation_state` to `FIBER_MISSTATED` and its `label_readiness` to
    `BLOCKED`."

    PRD 3.4: "The third hop, caused by the second, withdraws every permanent label
    of that style whose state is `PENDING_APPROVAL`, `APPROVED` or `PUBLISHED`,
    recording `withdrawn_reason` as `AUTO_FIBER_MISSTATED`, and a withdrawn
    published label stops occupying its market window."

    Design: Difficulty/transitive_cascade/failed_reverification_cascades_test_to_style_to_permanent_labels_to_hangtags
    """
    world = _cascade_world()
    style_id = world["style_id"]

    retest_row = reserve_fiber_test(style_id, **LATER_BENCH)
    assert retest_row["state"] == "BENCH_RESERVED", (
        f"the re-verification reservation lands in BENCH_RESERVED, got {retest_row['state']}")
    assert read_style(style_id)["substantiation_state"] == "FIBER_TEST_PENDING", (
        "re-verifying an already substantiated style moves it to FIBER_TEST_PENDING")

    failed = post_results(retest_row["id"], {"measured_fibers": FAILING_MEASUREMENT})
    assert failed["state"] == "FAILED", (
        f"a deviation of 3.5 pp against a 3.0 pp tolerance fails, got {failed['state']}")
    assert failed["result_delta_pp_max"] == pytest.approx(3.5, abs=0.01), (
        "the largest deviation is stored as result_delta_pp_max, expected 3.5, got "
        f"{failed['result_delta_pp_max']}")

    style = read_style(style_id)
    assert style["substantiation_state"] == "FIBER_MISSTATED", (
        "the second hop sets substantiation_state to FIBER_MISSTATED, got "
        f"{style['substantiation_state']}")
    assert style["label_readiness"] == "BLOCKED", (
        f"the second hop sets label_readiness to BLOCKED, got {style['label_readiness']}")

    published = read_label(world["l1"]["id"])
    assert published["state"] == "WITHDRAWN", (
        f"the PUBLISHED permanent label is pulled, got {published['state']}")
    assert published["withdrawn_reason"] == "AUTO_FIBER_MISSTATED", (
        "the cascade literal on the third hop is AUTO_FIBER_MISSTATED, got "
        f"{published['withdrawn_reason']!r}")

    pending = read_label(world["l2"]["id"])
    assert pending["state"] == "WITHDRAWN", (
        f"the PENDING_APPROVAL permanent label is pulled too, got {pending['state']}")
    assert pending["withdrawn_reason"] == "AUTO_FIBER_MISSTATED", (
        "the same cascade literal applies to the pending label, got "
        f"{pending['withdrawn_reason']!r}")


def test_failed_reverification_withdraws_the_hangtag_with_parent_withdrawn(api):
    """PRD 3.4: "The fourth hop, caused by the third, withdraws every hangtag whose
    `parent_label_spec_id` names one of the labels pulled in the third hop and whose
    state is `DRAFT`, `PENDING_APPROVAL`, `APPROVED` or `PUBLISHED`, recording
    `AUTO_PARENT_WITHDRAWN`."

    PRD 2.9: "Third, every row a cascade touches has its `version` incremented by 1
    and its `updated_at` refreshed, exactly as if it had been mutated directly."

    Design: Difficulty/transitive_cascade/failed_reverification_cascades_test_to_style_to_permanent_labels_to_hangtags
    """
    world = _cascade_world()
    style_id = world["style_id"]
    parent_before = world["l1"]
    hangtag_before = world["h1"]
    assert hangtag_before["state"] == "DRAFT", (
        f"the hangtag starts as a DRAFT child, got {hangtag_before['state']}")

    retest_row = reserve_fiber_test(style_id, **LATER_BENCH)
    post_results(retest_row["id"], {"measured_fibers": FAILING_MEASUREMENT})

    hangtag = read_label(hangtag_before["id"])
    assert hangtag["state"] == "WITHDRAWN", (
        "a hangtag is pulled even while it is still a draft, got "
        f"{hangtag['state']}")
    assert hangtag["withdrawn_reason"] == "AUTO_PARENT_WITHDRAWN", (
        "the fourth hop records AUTO_PARENT_WITHDRAWN rather than the fiber literal, "
        f"got {hangtag['withdrawn_reason']!r}")
    assert hangtag["version"] == hangtag_before["version"] + 1, (
        "the cascaded child's version is incremented by exactly 1, expected "
        f"{hangtag_before['version'] + 1}, got {hangtag['version']}")

    parent = read_label(parent_before["id"])
    assert parent["version"] == parent_before["version"] + 1, (
        "the intermediate parent's version is incremented by exactly 1, expected "
        f"{parent_before['version'] + 1}, got {parent['version']}")


def test_draft_label_and_prior_passed_run_survive_the_fiber_cascade(api):
    """PRD 2.9: "A permanent label is caught by a cascade when its state is
    `PENDING_APPROVAL`, `APPROVED` or `PUBLISHED` — a draft permanent label is left
    alone, because it has not yet asserted anything."

    PRD 3.4: "The fourth laboratory state, `SUPERSEDED`, is reached only by the
    system and only from `PASSED` — either because a newer run of the same style and
    test type reached `PASSED`, or because the style's declaration was replaced."

    Design: Difficulty/transitive_cascade/failed_reverification_cascades_test_to_style_to_permanent_labels_to_hangtags
    """
    world = _cascade_world()
    style_id = world["style_id"]
    draft_before = world["l3"]
    first_run_id = world["bundle"]["fiber_test"]["id"]

    retest_row = reserve_fiber_test(style_id, **LATER_BENCH)
    post_results(retest_row["id"], {"measured_fibers": FAILING_MEASUREMENT})

    draft_label = read_label(draft_before["id"])
    assert draft_label["state"] == "DRAFT", (
        f"the DRAFT permanent label is left alone by the cascade, got {draft_label['state']}")
    assert draft_label["withdrawn_reason"] is None, (
        "an untouched draft records no cascade literal, got "
        f"{draft_label['withdrawn_reason']!r}")
    assert draft_label["version"] == draft_before["version"], (
        "a row the cascade does not touch keeps its version, expected "
        f"{draft_before['version']}, got {draft_label['version']}")

    first_run = validate_success(api.get_lab_test(first_run_id, ADMIN), 200)
    assert first_run["state"] == "PASSED", (
        "a failing run never supersedes the last passing run of the same style and "
        f"test type, got {first_run['state']}")

    style = read_style(style_id)
    assert style["origin_state"] == "ORIGIN_ISSUED", (
        "the fiber cascade never touches the origin dimension, got "
        f"{style['origin_state']}")


# =========================================================================
# Cascade: a supply-graph append travels determination -> style -> label -> hangtag
# =========================================================================


def test_supply_node_append_voids_the_determination_and_pulls_its_labels(api):
    """PRD 3.3: "The second hop, caused by the first, transitions the style's
    `ISSUED` origin determination to `VOID`."

    PRD 3.3: "The third hop, caused by the second, withdraws every permanent label
    whose `origin_determination_id` is that voided determination and whose state is
    `PENDING_APPROVAL`, `APPROVED` or `PUBLISHED`, recording `withdrawn_reason` as
    `AUTO_ORIGIN_VOIDED`."

    Design: Difficulty/transitive_cascade/appending_a_supply_node_cascades_determination_to_style_to_label_to_hangtag
    """
    world = _cascade_world()
    style_id = world["style_id"]
    determination_id = world["bundle"]["determination"]["id"]

    trim = add_material_input(style_id, stage="TRIM", country_code="TR",
                              value_added_usd=0.40, weight_grams=10.0,
                              is_ornamentation=True)
    assert trim["depth"] == 0, (
        f"a TRIM node must always be a root, so its depth is 0, got {trim['depth']}")

    voided = validate_success(
        api.get_origin_determination(determination_id, ADMIN), 200)
    assert voided["state"] == "VOID", (
        "the second hop transitions the ISSUED determination to VOID, got "
        f"{voided['state']}")

    style = read_style(style_id)
    assert style["origin_state"] == "ORIGIN_UNDETERMINED", (
        "the style's origin_state drops to ORIGIN_UNDETERMINED, got "
        f"{style['origin_state']}")
    assert style["label_readiness"] == "BLOCKED", (
        f"label_readiness becomes BLOCKED, got {style['label_readiness']}")
    assert style["substantiation_state"] == "FIBER_SUBSTANTIATED", (
        "the origin cascade never reads or writes the substantiation dimension, got "
        f"{style['substantiation_state']}")

    published = read_label(world["l1"]["id"])
    assert published["state"] == "WITHDRAWN", (
        f"the PUBLISHED label pinned to the voided row is pulled, got {published['state']}")
    assert published["withdrawn_reason"] == "AUTO_ORIGIN_VOIDED", (
        "the third hop's cascade literal is AUTO_ORIGIN_VOIDED, got "
        f"{published['withdrawn_reason']!r}")

    pending = read_label(world["l2"]["id"])
    assert pending["state"] == "WITHDRAWN", (
        f"the PENDING_APPROVAL label pinned to the same row is pulled, got {pending['state']}")
    assert pending["withdrawn_reason"] == "AUTO_ORIGIN_VOIDED", (
        f"the pending label carries the same literal, got {pending['withdrawn_reason']!r}")


def test_supply_node_append_pulls_the_hangtag_and_bumps_every_touched_version(api):
    """PRD 3.3: "The fourth hop, caused by the third, withdraws every hangtag whose
    `parent_label_spec_id` is one of the labels pulled in the third hop and whose
    state is `DRAFT`, `PENDING_APPROVAL`, `APPROVED` or `PUBLISHED`, recording
    `AUTO_PARENT_WITHDRAWN`."

    PRD 3.3: "Alongside all that, the style's `origin_state` drops from
    `ORIGIN_ISSUED` to `ORIGIN_UNDETERMINED`, `label_readiness` becomes `BLOCKED`,
    `label_readiness` is recomputed, and the style's `version` is incremented by 1 —
    as is the version of the voided determination and of every artifact the cascade
    touched."

    Design: Difficulty/transitive_cascade/appending_a_supply_node_cascades_determination_to_style_to_label_to_hangtag
    """
    world = _cascade_world()
    style_id = world["style_id"]
    determination_before = world["bundle"]["determination"]
    hangtag_before = world["h1"]
    label_before = world["l1"]
    style_before = read_style(style_id)

    add_material_input(style_id, stage="TRIM", country_code="TR",
                       value_added_usd=0.40, weight_grams=10.0,
                       is_ornamentation=True)

    hangtag = read_label(hangtag_before["id"])
    assert hangtag["state"] == "WITHDRAWN", (
        "the DRAFT hangtag of a pulled parent is withdrawn on the fourth hop, got "
        f"{hangtag['state']}")
    assert hangtag["withdrawn_reason"] == "AUTO_PARENT_WITHDRAWN", (
        "a child pulled because of its parent records AUTO_PARENT_WITHDRAWN, got "
        f"{hangtag['withdrawn_reason']!r}")
    assert hangtag["version"] == hangtag_before["version"] + 1, (
        f"the hangtag's version rises by 1, expected {hangtag_before['version'] + 1}, "
        f"got {hangtag['version']}")

    determination = validate_success(
        api.get_origin_determination(determination_before["id"], ADMIN), 200)
    assert determination["version"] == determination_before["version"] + 1, (
        "the voided determination's version rises by 1, expected "
        f"{determination_before['version'] + 1}, got {determination['version']}")

    label = read_label(label_before["id"])
    assert label["version"] == label_before["version"] + 1, (
        f"the pulled label's version rises by 1, expected {label_before['version'] + 1}, "
        f"got {label['version']}")

    style = read_style(style_id)
    assert style["version"] == style_before["version"] + 1, (
        f"the style's version rises by 1, expected {style_before['version'] + 1}, got "
        f"{style['version']}")


def test_draft_label_survives_and_a_pulled_label_refuses_operator_withdrawal(api):
    """PRD 2.9: "A permanent label is caught by a cascade when its state is
    `PENDING_APPROVAL`, `APPROVED` or `PUBLISHED` — a draft permanent label is left
    alone, because it has not yet asserted anything."

    PRD 3.5: "Withdrawal from any other state — and any action at all on an artifact
    already in `WITHDRAWN` — is rejected with `ERR_LABEL_STATE_INVALID`."

    Design: Difficulty/transitive_cascade/appending_a_supply_node_cascades_determination_to_style_to_label_to_hangtag
    """
    world = _cascade_world()
    style_id = world["style_id"]
    draft_before = world["l3"]

    add_material_input(style_id, stage="TRIM", country_code="TR",
                       value_added_usd=0.40, weight_grams=10.0,
                       is_ornamentation=True)

    draft_label = read_label(draft_before["id"])
    assert draft_label["state"] == "DRAFT", (
        f"the DRAFT permanent label is left alone, got {draft_label['state']}")
    assert draft_label["withdrawn_reason"] is None, (
        f"an untouched draft records no reason, got {draft_label['withdrawn_reason']!r}")
    assert draft_label["version"] == draft_before["version"], (
        "an untouched draft keeps its version, expected "
        f"{draft_before['version']}, got {draft_label['version']}")

    already_pulled = read_label(world["l1"]["id"])
    assert already_pulled["state"] == "WITHDRAWN", (
        f"precondition: the cascade already pulled this label, got {already_pulled['state']}")
    validate_error(
        api.withdraw_label_spec(already_pulled["id"], "manual double withdrawal", APPROVER),
        ApiErrorId.ERR_LABEL_STATE_INVALID)

    unchanged = read_label(already_pulled["id"])
    assert unchanged["withdrawn_reason"] == "AUTO_ORIGIN_VOIDED", (
        "the refused operator call must not overwrite the cascade literal, got "
        f"{unchanged['withdrawn_reason']!r}")
    assert unchanged["version"] == already_pulled["version"], (
        "a refused call mutates nothing, expected version "
        f"{already_pulled['version']}, got {unchanged['version']}")


# =========================================================================
# Cascade: verifying one finding travels finding -> audit rollup -> brand posture
# =========================================================================


def test_verifying_one_finding_re_derives_the_audit_rollup(api):
    """PRD 3.7: "The first hop stamps `verified_at` from the logical clock and moves
    the finding to `CLOSED`."

    PRD 3.7: "`critical_finding_count` counts the subset of those whose `severity` is
    `CRITICAL`."

    PRD 3.7: "`units_in_scope` sums `units_affected` over **every** finding of the
    audit with no state filter at all, which is what makes it invariant under
    disposition, verification and reopening."

    Design: Difficulty/transitive_cascade/verifying_one_finding_cascades_finding_to_audit_rollup_to_brand_posture
    """
    _brand_id, audit, findings = _three_critical_findings_world()
    escalated = findings[2]
    assert escalated["severity"] == "CRITICAL", (
        "a MAJOR base code escalates one level at exactly 5,000 affected units, got "
        f"{escalated['severity']}")
    assert audit["state"] == "IN_REVIEW", (
        f"the first finding drove the audit to IN_REVIEW, got {audit['state']}")
    assert audit["open_finding_count"] == 3, (
        f"all three findings sit in OPEN, got {audit['open_finding_count']}")
    assert audit["critical_finding_count"] == 3, (
        f"all three findings are CRITICAL, got {audit['critical_finding_count']}")
    assert audit["units_in_scope"] == 5200, (
        f"units_in_scope sums 100 + 100 + 5000, got {audit['units_in_scope']}")

    record_disposition(escalated["id"], units_destroyed=5000)
    verified = verify_finding(escalated["id"])
    assert verified["state"] == "CLOSED", (
        f"the first hop moves the verified finding to CLOSED, got {verified['state']}")
    assert verified["verified_at"] is not None, (
        "the first hop stamps verified_at from the logical clock, got None")

    rolled_up = read_audit(audit["id"])
    assert rolled_up["critical_finding_count"] == 2, (
        "closing one CRITICAL finding drops the critical count to 2, got "
        f"{rolled_up['critical_finding_count']}")
    assert rolled_up["open_finding_count"] == 2, (
        f"two findings remain in the open set, got {rolled_up['open_finding_count']}")
    assert rolled_up["state"] == "IN_REVIEW", (
        "the audit stays IN_REVIEW while its open-finding count is above 0, got "
        f"{rolled_up['state']}")
    assert rolled_up["units_in_scope"] == 5200, (
        "units_in_scope is invariant under verification, expected 5200, got "
        f"{rolled_up['units_in_scope']}")


def test_verifying_one_finding_drops_the_brand_from_restricted_to_open(api):
    """PRD 3.7: "The third hop, caused by the second, recomputes the brand-of-record's
    `posture`: because no audit of that party is any longer in `IN_REVIEW` with at
    least 3 critical findings, a posture that was `RESTRICTED` for that reason drops
    back to `OPEN`."

    PRD 3.1: "`critical_audit_finding_count` is the sum of the critical-finding counts
    of every compliance audit whose audited party resolves through the same
    brand-of-record rule to this party, and it starts at 0."

    Design: Difficulty/transitive_cascade/verifying_one_finding_cascades_finding_to_audit_rollup_to_brand_posture
    """
    brand_id, audit, findings = _three_critical_findings_world()

    before = read_brand(brand_id)
    assert before["posture"] == "RESTRICTED", (
        "an IN_REVIEW audit with three critical findings restricts the brand, got "
        f"{before['posture']}")
    assert before["critical_audit_finding_count"] == 3, (
        "the brand rolls up three critical findings, got "
        f"{before['critical_audit_finding_count']}")
    assert before["outstanding_penalty_usd"] == pytest.approx(0.00, abs=0.01), (
        "no customs entry has been assessed, so the ledger is 0.00, got "
        f"{before['outstanding_penalty_usd']}")

    record_disposition(findings[2]["id"], units_destroyed=5000)
    verify_finding(findings[2]["id"])

    after = read_brand(brand_id)
    assert after["posture"] == "OPEN", (
        "with the critical count down to 2 the restriction predicate no longer holds, "
        f"so the posture drops to OPEN, got {after['posture']}")
    assert after["critical_audit_finding_count"] == 2, (
        "the brand's critical roll-up follows the audit's, got "
        f"{after['critical_audit_finding_count']}")
    assert after["version"] == before["version"] + 1, (
        f"the party's version rises by 1, expected {before['version'] + 1}, got "
        f"{after['version']}")
    assert read_audit(audit["id"])["state"] == "IN_REVIEW", (
        "the posture drops even though the audit itself is still IN_REVIEW")


def test_a_remediated_finding_still_counts_so_posture_holds_at_restricted(api):
    """PRD 3.7: "`open_finding_count` counts the findings whose state is `OPEN` **or**
    `REMEDIATED` — a remediated finding is still open for closure purposes, because
    nobody has verified it yet."

    PRD 3.7: "The audit's counters are re-derived — the finding is still counted,
    because remediated sits in the open set, so the audit does not yet move to
    `PENDING_CLOSURE` on this account alone unless it was the only remaining one — and
    the `version` of the finding and of the audit are each incremented by 1."

    Design: Difficulty/transitive_cascade/verifying_one_finding_cascades_finding_to_audit_rollup_to_brand_posture
    """
    brand_id, audit, findings = _three_critical_findings_world()

    remediated = record_disposition(findings[2]["id"], units_destroyed=5000)
    assert remediated["state"] == "REMEDIATED", (
        f"a complete disposition moves the finding to REMEDIATED, got {remediated['state']}")

    mid = read_audit(audit["id"])
    assert mid["open_finding_count"] == 3, (
        "a remediated finding still sits in the open set, expected 3, got "
        f"{mid['open_finding_count']}")
    assert mid["critical_finding_count"] == 3, (
        "the critical subset of the open set is still 3, got "
        f"{mid['critical_finding_count']}")
    assert mid["state"] == "IN_REVIEW", (
        f"the audit does not move to PENDING_CLOSURE on this account, got {mid['state']}")
    assert mid["version"] == audit["version"] + 1, (
        f"the audit's version rises by 1, expected {audit['version'] + 1}, got "
        f"{mid['version']}")

    still_restricted = read_brand(brand_id)
    assert still_restricted["posture"] == "RESTRICTED", (
        "the intermediate disposition leaves the restriction predicate satisfied, got "
        f"{still_restricted['posture']}")
    assert still_restricted["critical_audit_finding_count"] == 3, (
        "the brand's critical roll-up is unchanged by remediation alone, got "
        f"{still_restricted['critical_audit_finding_count']}")

    verify_finding(findings[2]["id"])
    assert read_brand(brand_id)["posture"] == "OPEN", (
        "only the verification hop moves the posture, and it moves it to OPEN")
