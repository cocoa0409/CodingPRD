"""Permit application lifecycle: revision cycle, approval gates, payment,
revocation, capacity, and clock-driven completion.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    create_unit, create_determination, create_final_determination,
    create_submitted_permit, create_under_review_permit,
    create_approved_permit, create_active_permit,
    get_permit, revoke_permit, get_unit_posture, advance_clock,
    create_permit_payload, create_finalize_payload,
    create_return_for_revision_payload,
    make_permit_applicant_headers,
)

PO = TEST_USERS["permit_officer_headers"]


def test_permit_revision_cycle_runs_twice(api):
    """PRD §3.3: "A `PermitOfficer` or `RefugeManager` may return an
    application that sits in `SUBMITTED` or `UNDER_REVIEW` for revision,
    moving it to `REVISION_REQUESTED` and recording the payload's `note` onto
    the application as its `revision_note`. The applicant — and only that
    applicant, with `X-User-ID` matching the stored `applicant_ref` —
    resubmits, moving the application from `REVISION_REQUESTED` to
    `UNDER_REVIEW`."
    PRD §2.4: "**`version` (integer):** a system-managed integer that
    increments by one on every modification."

    Design: Difficulty/non_linear_state_machine/permit_revision_cycle_runs_twice
    """
    unit = create_unit()
    det = create_final_determination(use_type="RESEARCH")
    permit = create_submitted_permit(
        unit["id"], det["id"], applicant_ref="app-1", crew_size=4,
        start_date="2026-10-10", end_date="2026-10-12")
    version_at_create = permit["version"]

    returned1 = validate_success(api_client.return_permit_for_revision(
        permit["id"], create_return_for_revision_payload(note="round 1"), PO))
    assert returned1["status"] == "REVISION_REQUESTED"
    resubmitted1 = validate_success(api_client.resubmit_permit(
        permit["id"], {}, make_permit_applicant_headers("app-1")))
    assert resubmitted1["status"] == "UNDER_REVIEW"
    returned2 = validate_success(api_client.return_permit_for_revision(
        permit["id"], create_return_for_revision_payload(note="round 2"), PO))
    assert returned2["status"] == "REVISION_REQUESTED"
    resubmitted2 = validate_success(api_client.resubmit_permit(
        permit["id"], {}, make_permit_applicant_headers("app-1")))
    assert resubmitted2["status"] == "UNDER_REVIEW"
    approved = validate_success(api_client.approve_permit(permit["id"], PO))
    assert approved["status"] == "APPROVED"
    assert approved["version"] == version_at_create + 5, (
        "five modifications after creation (two returns, two resubmits, one "
        f"approve) must advance the version by 5: {version_at_create} -> "
        f"{approved['version']}")


def test_pay_on_active_permit_state_beats_fiscal(api):
    """PRD §2.6: "Every request passes through a single ordered validation
    cascade, and the first failing check determines the error returned; later
    checks are never consulted once an earlier one has fired."
    PRD §2.6: "5. **State preconditions** — the invoked transition's
    from-state holds; terminal states reject every transition
    (`ERR_INVALID_STATE`, 409)."
    PRD §2.6: "The fiscal rules close the cascade: (21) exact permit payment
    (`ERR_PAYMENT_AMOUNT_MISMATCH`); (22) refunds bounded by what was
    actually paid (`ERR_REFUND_EXCEEDS_PAID`); (23) a zero balance required
    to complete an agreement (`ERR_OUTSTANDING_BALANCE`); and (24) no
    overpayment of an agreement's outstanding balance (`ERR_OVERPAYMENT`)."

    Design: Difficulty/priority_pair_validation_conflict/pay_on_active_permit_state_beats_fiscal
    """
    unit = create_unit()
    det = create_final_determination(use_type="RESEARCH")
    permit = create_active_permit(unit["id"], det["id"], applicant_ref="app-1")
    assert permit["status"] == "ACTIVE"
    resp = api_client.pay_permit(
        permit["id"], {"amount_cents": 1}, make_permit_applicant_headers("app-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_permit(permit["id"])
    assert after["status"] == "ACTIVE", (
        "a rejected second payment must leave the permit ACTIVE")


def test_permit_approve_gated_by_determination_state_and_finding(api):
    """PRD §3.3: "The referenced determination must have reached `FINAL`, else
    `ERR_DETERMINATION_NOT_FINAL`. That determination's `finding` must be
    `COMPATIBLE`, else `ERR_USE_INCOMPATIBLE`."

    Design: Difficulty/cross_entity_state_dependency/permit_approve_gated_by_determination_state_and_finding
    """
    unit = create_unit()
    det_open = create_determination(use_type="RESEARCH", title="Research use")
    det_incompatible = create_determination(
        use_type="PHOTOGRAPHY", title="Photo use")
    advance_clock("2026-09-05T00:00:00Z")
    validate_success(api_client.open_determination_comment(det_open["id"], PO))
    validate_success(api_client.open_determination_comment(det_incompatible["id"], PO))
    advance_clock("2026-09-21T00:00:00Z")
    validate_success(api_client.finalize_determination(
        det_incompatible["id"],
        create_finalize_payload(
            finding="NOT_COMPATIBLE", rationale="Would disturb nesting."),
        PO))

    permit_not_final = create_under_review_permit(
        unit["id"], det_open["id"], applicant_ref="app-1", use_type="RESEARCH",
        crew_size=2, start_date="2026-10-10", end_date="2026-10-11")
    permit_incompatible = create_under_review_permit(
        unit["id"], det_incompatible["id"], applicant_ref="app-2",
        use_type="PHOTOGRAPHY", crew_size=1,
        start_date="2026-10-10", end_date="2026-10-10")

    resp1 = api_client.approve_permit(permit_not_final["id"], PO)
    validate_error(resp1, ApiErrorId.ERR_DETERMINATION_NOT_FINAL)
    resp2 = api_client.approve_permit(permit_incompatible["id"], PO)
    validate_error(resp2, ApiErrorId.ERR_USE_INCOMPATIBLE)
    assert get_permit(permit_not_final["id"])["status"] == "UNDER_REVIEW"
    assert get_permit(permit_incompatible["id"])["status"] == "UNDER_REVIEW"


def test_commercial_permit_aggregate_daily_capacity(api):
    """PRD §3.3: "And for a `COMMERCIAL_FILMING` application, a capacity rule
    applies: no calendar day within the requested window may already carry two
    or more commercial-filming permits in `APPROVED` or `ACTIVE` status on the
    same unit — approving into such a day is rejected with
    `ERR_COMMERCIAL_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/commercial_permit_aggregate_daily_capacity
    """
    unit = create_unit(name="River Bluffs", habitat_type="FOREST", acreage=2400)
    det = create_final_determination(use_type="COMMERCIAL_FILMING")
    c1 = create_active_permit(
        unit["id"], det["id"], applicant_ref="studio-a",
        use_type="COMMERCIAL_FILMING", crew_size=2,
        start_date="2026-10-10", end_date="2026-10-12")
    c2 = create_active_permit(
        unit["id"], det["id"], applicant_ref="studio-b",
        use_type="COMMERCIAL_FILMING", crew_size=2,
        start_date="2026-10-11", end_date="2026-10-13")
    assert c1["status"] == "ACTIVE" and c2["status"] == "ACTIVE", (
        "an overlap of exactly two commercial permits on a day is allowed")
    c3 = create_under_review_permit(
        unit["id"], det["id"], applicant_ref="studio-c",
        use_type="COMMERCIAL_FILMING", crew_size=2,
        start_date="2026-10-12", end_date="2026-10-14")
    resp = api_client.approve_permit(c3["id"], PO)
    validate_error(resp, ApiErrorId.ERR_COMMERCIAL_CAPACITY_EXCEEDED)
    assert get_permit(c3["id"])["status"] == "UNDER_REVIEW", (
        "the third overlapping commercial permit must remain UNDER_REVIEW")


def test_approve_from_submitted_rejected(api):
    """PRD §3.3: "Approval is the officer's decision point, moving an
    application from `UNDER_REVIEW` to `APPROVED`."
    PRD §2.6: "5. **State preconditions** — the invoked transition's
    from-state holds; terminal states reject every transition
    (`ERR_INVALID_STATE`, 409)."

    Design: Corner/state_machines/approve_from_submitted_rejected
    """
    unit = create_unit()
    det = create_final_determination(use_type="RESEARCH")
    permit = create_submitted_permit(
        unit["id"], det["id"], applicant_ref="app-1")
    resp = api_client.approve_permit(permit["id"], PO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_permit(permit["id"])
    assert after["status"] == "SUBMITTED"
    assert after["assessed_fee_cents"] is None, (
        "assessed_fee_cents must remain null until approval")


def test_revoke_terminal_lockdown_then_pay_rejected(api):
    """PRD §3.3: "`COMPLETED`, `REVOKED`, and `EXPIRED` are terminal: from any
    of them, every further transition is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/revoke_terminal_lockdown_then_pay_rejected
    """
    unit = create_unit()
    det = create_final_determination(use_type="RESEARCH")
    permit = create_approved_permit(unit["id"], det["id"], applicant_ref="app-1")
    revoked = revoke_permit(permit["id"], reason="False statements in application")
    assert revoked["status"] == "REVOKED"
    resp = api_client.pay_permit(
        permit["id"], {"amount_cents": permit["assessed_fee_cents"]},
        make_permit_applicant_headers(permit["applicant_ref"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_permit_auto_completes_past_end_date(api):
    """PRD §3.3: "A permit still `ACTIVE` when the clock advances past its
    `end_date` completes on its own, moving to `COMPLETED` and releasing its
    days."

    Design: Corner/state_machines/permit_auto_completes_past_end_date
    """
    unit = create_unit()
    det = create_final_determination(use_type="RESEARCH")
    permit = create_active_permit(
        unit["id"], det["id"], applicant_ref="app-1", crew_size=2,
        start_date="2026-10-10", end_date="2026-10-11")
    assert get_unit_posture(unit["id"])["committed_visitor_days"] == 4
    advance_clock("2026-10-13T00:00:00Z")
    after = get_permit(permit["id"])
    assert after["status"] == "COMPLETED", (
        f"clock past end_date must complete the permit, got {after['status']}")
    posture = get_unit_posture(unit["id"])
    assert posture["committed_visitor_days"] == 0, (
        "completion must release the permit's committed visitor days")


def test_payment_amount_mismatch_rejected(api):
    """PRD §3.3: "The applicant — again only the matching `applicant_ref` —
    pays by supplying `amount_cents`, which must equal the
    `assessed_fee_cents` exactly; any other amount is rejected with
    `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 402)."

    Design: Corner/errors/payment_amount_mismatch_rejected
    """
    unit = create_unit()
    det = create_final_determination(use_type="RESEARCH")
    permit = create_approved_permit(unit["id"], det["id"], applicant_ref="app-1")
    assert permit["assessed_fee_cents"] == 21000
    resp = api_client.pay_permit(
        permit["id"], {"amount_cents": 20000},
        make_permit_applicant_headers("app-1"))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)
    assert get_permit(permit["id"])["status"] == "APPROVED", (
        "a mismatched payment must leave the permit APPROVED")


def test_permit_end_before_start_rejected(api):
    """PRD §3.3: "the authorized window runs from `start_date` through
    `end_date` inclusive — the `end_date` may equal the `start_date` but may
    not precede it, or the submission fails with `ERR_DATE_RANGE_INVALID`."

    Design: Corner/validations/permit_end_before_start_rejected
    """
    unit = create_unit()
    det = create_determination(use_type="RESEARCH")
    payload = create_permit_payload(
        unit["id"], det["id"], applicant_ref="app-1", use_type="RESEARCH",
        crew_size=2, start_date="2026-10-10", end_date="2026-10-09")
    resp = api_client.create_permit(
        payload, make_permit_applicant_headers("app-1"))
    validate_error(resp, ApiErrorId.ERR_DATE_RANGE_INVALID)


def test_use_type_mismatch_rejected(api):
    """PRD §3.3: "The requested `use_type` must be one of `RESEARCH`,
    `PHOTOGRAPHY`, `COMMERCIAL_FILMING`, or `GUIDED_ACTIVITY`, and it must
    equal the referenced determination's `use_type` exactly; a mismatch is
    rejected with `ERR_USE_TYPE_MISMATCH`."

    Design: Corner/validations/use_type_mismatch_rejected
    """
    unit = create_unit()
    det = create_determination(use_type="RESEARCH")
    payload = create_permit_payload(
        unit["id"], det["id"], applicant_ref="app-1", use_type="PHOTOGRAPHY",
        crew_size=2, start_date="2026-10-10", end_date="2026-10-10")
    resp = api_client.create_permit(
        payload, make_permit_applicant_headers("app-1"))
    validate_error(resp, ApiErrorId.ERR_USE_TYPE_MISMATCH)


def test_immediate_read_after_write_consistency(api):
    """PRD §3.3: "A successful payment moves the permit from `APPROVED` to
    `ACTIVE` and commits the party's load onto the unit: the permit's
    `crew_size` multiplied by its inclusive day count is added into the
    unit's `committed_visitor_days`."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    unit = create_unit()
    det = create_final_determination(use_type="RESEARCH")
    permit = create_approved_permit(unit["id"], det["id"], applicant_ref="app-1")
    assert permit["assessed_fee_cents"] == 21000
    paid = validate_success(api_client.pay_permit(
        permit["id"], {"amount_cents": 21000},
        make_permit_applicant_headers("app-1")))
    assert paid["status"] == "ACTIVE", (
        "the pay response itself must report ACTIVE")
    posture = get_unit_posture(unit["id"])
    assert posture["committed_visitor_days"] == 12, (
        f"the immediately-following posture read must already show "
        f"crew 4 x 3 days = 12, got {posture['committed_visitor_days']}")
