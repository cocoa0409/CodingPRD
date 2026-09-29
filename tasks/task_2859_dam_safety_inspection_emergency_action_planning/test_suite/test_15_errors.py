"""Error breadth: the rejection ladder read from the top, one rung at a time."""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assert_cents, assert_cfs, assert_instant, assert_total_count
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    ASSESSMENT_DRAFT,
    DEFICIENCY_ORDERED,
    DEFICIENCY_REMEDIATION_SUBMITTED,
    DELINQUENCY_CURRENT,
    DRAWDOWN_REQUESTED,
    EAP_APPROVED,
    EAP_DRAFT,
    ENTRY_CIVIL_PENALTY,
    ENTRY_PAYMENT_RECEIVED,
    HAZARD_HIGH,
    HAZARD_SIGNIFICANT,
    INSPECTION_SCHEDULED,
    INSPECTION_SUBMITTED,
    ORDER_ISSUED,
    ORDER_RESPONSE_FILED,
    ORDER_TYPE_NOTICE,
    PERMIT_ISSUED,
    PERMIT_SUBMITTED,
    PERMIT_TYPE_REPAIR,
    PERMIT_UNDER_ENGINEERING_REVIEW,
    REVIEW_APPROVE,
    ROLE_PROGRAM_ADMIN,
    SAFETY_SATISFACTORY,
    SAFETY_UNRATED,
    UNKNOWN_UUID,
    VERIFY_SATISFIED,
)
from test_helpers.test_users import (
    NO_HEADERS,
    headers_without_user_id,
    make_engineer_headers,
    make_owner_headers,
)


# ---------------------------------------------------------------------------
# Rung 1: identity headers
# ---------------------------------------------------------------------------
def test_a_read_without_an_identity_header_is_refused(api, base):
    """Even a plain read needs an identity, and the role alone is not enough.

    PRD 2.5: "**Identity headers present** — both `X-User-ID` and `X-User-Role` non-empty on every endpoint except the clock-setting capability; otherwise `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/errors/request_without_x_user_id_returns_unauthenticated
    """
    validate_error(
        api.get_owner(base.owner_id, NO_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.get_owner(base.owner_id, headers_without_user_id(ROLE_PROGRAM_ADMIN)),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )


def test_the_missing_identity_outranks_the_malformed_body(api, program, base):
    """An anonymous write with an incomplete payload is a 401, not a 400.

    PRD 2.5: "The **first** violated rule determines the response, and no later rule is evaluated."

    Design: Corner/errors/request_without_x_user_id_returns_unauthenticated
    """
    validate_error(
        api.create_engineer(
            {"full_name": "Ghost", "license_number": "PE-00000"}, NO_HEADERS
        ),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )

    rows, meta = validate_paginated(api.list_engineers(program.admin))
    assert_total_count(meta, 2)
    assert "PE-00000" not in [row["license_number"] for row in rows]
    assert base.engineer_a["license_number"] != "PE-00000"


# ---------------------------------------------------------------------------
# Rung 2: role authorisation
# ---------------------------------------------------------------------------
def test_the_coordinator_cannot_post_to_the_fee_ledger(api, program, base):
    """A role that does not own the operation is refused before anything is written.

    PRD 2.5: "**Role authorised** for the endpoint; otherwise `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/errors/role_without_the_operation_returns_forbidden_role
    """
    validate_error(
        api.create_fee_adjustment(
            base.owner_id,
            f.fee_adjustment_payload(
                entry_type=ENTRY_CIVIL_PENALTY, amount_cents=10_000
            ),
            program.coordinator,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )

    owner = program.get_owner(base.owner_id)
    assert_cents(owner["fee_balance_cents"], 0, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_CURRENT
    _rows, meta = program.ledger(base.owner_id)
    assert_total_count(meta, 0)


def test_the_role_gate_is_reached_before_the_unknown_owner_lookup(api, program):
    """The same forbidden write against a non-existent owner is still a 403.

    PRD 2.5: "Requests are judged against an explicitly ordered ladder of checks."

    Design: Corner/errors/role_without_the_operation_returns_forbidden_role
    """
    validate_error(
        api.create_fee_adjustment(
            UNKNOWN_UUID,
            f.fee_adjustment_payload(
                entry_type=ENTRY_CIVIL_PENALTY, amount_cents=10_000
            ),
            program.coordinator,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )


# ---------------------------------------------------------------------------
# Rung 6: the backing entity behind an engineer identity
# ---------------------------------------------------------------------------
def test_an_engineer_identity_that_is_not_an_engineer_row_is_refused(api, base):
    """Neither an unknown uuid nor an owner's id can act as an engineer.

    PRD 2.5: "**Backing-entity identity** — for the entity-backed roles `Engineer` and `DamOwner`, `X-User-ID` resolves to a row of the backing entity; otherwise `ERR_IDENTITY_UNKNOWN` (403)."

    Design: Corner/errors/unknown_engineer_identity_returns_403_identity_unknown
    """
    validate_error(
        api.create_assessment(
            f.assessment_a1(base.dam_id), make_engineer_headers(UNKNOWN_UUID)
        ),
        ApiErrorId.ERR_IDENTITY_UNKNOWN,
        403,
    )
    validate_error(
        api.create_assessment(
            f.assessment_a1(base.dam_id), make_engineer_headers(base.owner_id)
        ),
        ApiErrorId.ERR_IDENTITY_UNKNOWN,
        403,
    )


def test_the_real_engineer_files_the_assessment_as_a_draft(api, program, base):
    """A resolvable engineer identity is recorded on the filing it authorises.

    PRD 3.2: "Filing records `prepared_by_user_id` as the acting engineer's own identifier — an audit identity, not a foreign-key constraint — and leaves the dam's classification untouched: `status` is `DRAFT`, `certified_score` and `certified_hazard_class` are both null while it stays there, and `certified_at` and `superseded_at` are null."

    Design: Corner/errors/unknown_engineer_identity_returns_403_identity_unknown
    """
    filed = validate_success(
        api.create_assessment(
            f.assessment_a1(base.dam_id), base.engineer_a_headers
        ),
        201,
    )
    assert filed["status"] == ASSESSMENT_DRAFT
    assert filed["prepared_by_user_id"] == base.engineer_a_id
    assert filed["certified_score"] is None
    assert filed["certified_hazard_class"] is None

    _rows, meta = validate_paginated(
        api.list_assessments(program.admin, {"dam_id": base.dam_id})
    )
    assert_total_count(meta, 1)


# ---------------------------------------------------------------------------
# Rung 7: ownership of the served order
# ---------------------------------------------------------------------------
@pytest.fixture()
def served_order(program, base):
    """An ISSUED order against owner A, plus an unrelated owner B."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    visit = program.schedule_inspection(base.dam_id, base.engineer_a_id)
    program.set_clock("2026-08-05T13:00:00Z")
    program.submit_inspection(
        visit["id"],
        base.engineer_a_id,
        performed_at="2026-08-05T12:00:00Z",
        deficiencies=[f.deficiency_item()],
    )
    opened = program.deficiencies_for(base.dam_id)[0]
    order = program.issue_order(
        opened["id"], order_type=ORDER_TYPE_NOTICE, requested_response_days=30
    )
    # Issuing the order moved the finding OPEN -> ORDERED, so re-read the stored row.
    finding = program.deficiencies_for(base.dam_id)[0]
    stranger = program.create_owner(
        legal_name="Basalt Ridge Trust",
        contact_email="ops@basaltridge.example",
    )
    return {"order": order, "finding": finding, "stranger": stranger}


def test_a_stranger_owner_cannot_answer_someone_elses_order(api, program, served_order):
    """Ownership is checked against the served order, not against the role.

    PRD 2.5: "**Owner ownership** — for `DamOwner`-authorised operations, `X-User-ID` equals the owning owner of the target dam, plan, order or permit; otherwise `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/errors/another_owner_cannot_file_the_remediation_response
    """
    order_id = served_order["order"]["id"]
    validate_error(
        api.file_order_response(
            order_id,
            f.order_response_payload(
                corrective_action_summary="We replaced the seals.",
                completed_at="2026-08-20T00:00:00Z",
            ),
            make_owner_headers(served_order["stranger"]["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    order = program.get_order(order_id)
    assert order["status"] == ORDER_ISSUED
    assert order["response_filed_at"] is None


def test_the_served_owner_moves_both_the_order_and_the_finding(
    api, program, base, served_order
):
    """The identical body from the right owner files the response and abates.

    PRD 3.4: "The order moves `ISSUED → RESPONSE_FILED` and the deficiency moves `ORDERED → REMEDIATION_SUBMITTED`."

    Design: Corner/errors/another_owner_cannot_file_the_remediation_response
    """
    order_id = served_order["order"]["id"]
    assert served_order["finding"]["status"] == DEFICIENCY_ORDERED

    filed = validate_success(
        api.file_order_response(
            order_id,
            f.order_response_payload(
                corrective_action_summary="We replaced the seals.",
                completed_at="2026-08-20T00:00:00Z",
            ),
            base.owner_headers,
        )
    )
    assert filed["status"] == ORDER_RESPONSE_FILED
    assert_instant(
        filed["response_filed_at"], "2026-08-05T13:00:00Z", "response_filed_at"
    )
    assert (
        program.deficiencies_for(base.dam_id)[0]["status"]
        == DEFICIENCY_REMEDIATION_SUBMITTED
    )


# ---------------------------------------------------------------------------
# Rung 8: the engineer bound to the inspection
# ---------------------------------------------------------------------------
@pytest.fixture()
def assigned_visit(program, base):
    """A SCHEDULED inspection bound to engineer A, with the clock inside the window."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    visit = program.schedule_inspection(base.dam_id, base.engineer_a_id)
    program.set_clock("2026-08-05T13:00:00Z")
    return visit


def test_an_equally_qualified_engineer_cannot_submit_for_another(
    api, program, base, assigned_visit
):
    """Submission is personal: a second certified engineer is still refused.

    PRD 2.5: "**Engineer assignment** — for engineer-bound operations, `X-User-ID` equals the engineer bound to the target row; otherwise `ERR_NOT_ASSIGNED_ENGINEER` (403)."

    Design: Corner/errors/unassigned_engineer_cannot_submit_the_inspection
    """
    validate_error(
        api.submit_inspection(
            assigned_visit["id"],
            f.inspection_submission_payload(
                condition_rating=SAFETY_SATISFACTORY,
                narrative="Walked the crest.",
                deficiencies=[],
            ),
            base.engineer_b_headers,
        ),
        ApiErrorId.ERR_NOT_ASSIGNED_ENGINEER,
        403,
    )

    unchanged = validate_success(
        api.get_inspection(assigned_visit["id"], program.admin)
    )
    assert unchanged["status"] == INSPECTION_SCHEDULED
    assert unchanged["performed_at"] is None


def test_the_assigned_engineers_submission_leaves_the_rating_unwritten(
    api, program, base, assigned_visit
):
    """The engineer of record submits, but only acceptance rates the dam.

    PRD 3.3: "Acceptance is the terminal act and the only thing in the program that writes a dam's safety rating."

    Design: Corner/errors/unassigned_engineer_cannot_submit_the_inspection
    """
    submitted = validate_success(
        api.submit_inspection(
            assigned_visit["id"],
            f.inspection_submission_payload(
                condition_rating=SAFETY_SATISFACTORY,
                narrative="Walked the crest.",
                deficiencies=[],
            ),
            base.engineer_a_headers,
        )
    )
    assert submitted["status"] == INSPECTION_SUBMITTED
    assert submitted["condition_rating"] == SAFETY_SATISFACTORY
    assert program.get_dam(base.dam_id)["safety_status"] == SAFETY_UNRATED


# ---------------------------------------------------------------------------
# Rung 4: twelve entity-specific not-found codes
# ---------------------------------------------------------------------------
def test_the_same_unknown_id_reports_twelve_different_not_found_codes(api, program):
    """Each path reports the entity it failed to resolve, never a generic code.

    PRD 2.5: "**Path existence** — every `{id}` in the path resolves to an existing row of its expected entity, reported as `ERR_OWNER_NOT_FOUND`, `ERR_ENGINEER_NOT_FOUND`, `ERR_REACH_NOT_FOUND`, `ERR_DAM_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_DEFICIENCY_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_EAP_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` or `ERR_DRAWDOWN_NOT_FOUND` as appropriate (all HTTP 404)."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    probes = [
        (api.get_owner, ApiErrorId.ERR_OWNER_NOT_FOUND),
        (api.get_engineer, ApiErrorId.ERR_ENGINEER_NOT_FOUND),
        (api.get_river_reach, ApiErrorId.ERR_REACH_NOT_FOUND),
        (api.get_dam, ApiErrorId.ERR_DAM_NOT_FOUND),
        (api.get_assessment, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND),
        (api.get_inspection, ApiErrorId.ERR_INSPECTION_NOT_FOUND),
        (api.get_deficiency, ApiErrorId.ERR_DEFICIENCY_NOT_FOUND),
        (api.get_remediation_order, ApiErrorId.ERR_ORDER_NOT_FOUND),
        (api.get_eap, ApiErrorId.ERR_EAP_NOT_FOUND),
        (api.get_permit, ApiErrorId.ERR_PERMIT_NOT_FOUND),
        (api.get_event, ApiErrorId.ERR_EVENT_NOT_FOUND),
        (api.get_drawdown_order, ApiErrorId.ERR_DRAWDOWN_NOT_FOUND),
    ]
    seen = []
    for getter, error_id in probes:
        error = validate_error(getter(UNKNOWN_UUID, program.admin), error_id, 404)
        seen.append(error["error_id"])
    assert len(set(seen)) == 12


def test_a_not_found_response_carries_only_the_declared_error_envelope(api, program):
    """The failure body is the standard error envelope and nothing more.

    PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    response = api.get_dam(UNKNOWN_UUID, program.admin)
    error = validate_error(response, ApiErrorId.ERR_DAM_NOT_FOUND, 404)
    assert error["message"].strip() != ""

    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
    assert body["meta"]["api_request_id"].startswith("req_")
    assert set(body["data"]) == {"error_id", "message"}


# ---------------------------------------------------------------------------
# Rungs 10 to 16: one state guard per entity family
# ---------------------------------------------------------------------------
@pytest.fixture()
def guarded_program(program, base):
    """One dam carrying an entity in every state that guards a further move."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    first = program.schedule_inspection(base.dam_id, base.engineer_a_id)
    program.set_clock("2026-08-05T13:00:00Z")
    program.submit_inspection(
        first["id"],
        base.engineer_a_id,
        performed_at="2026-08-05T12:00:00Z",
        deficiencies=[f.deficiency_item()],
    )
    finding = program.deficiencies_for(base.dam_id)[0]
    order = program.issue_order(
        finding["id"], order_type=ORDER_TYPE_NOTICE, requested_response_days=30
    )
    second = program.schedule_inspection(
        base.dam_id,
        base.engineer_b_id,
        window_start="2026-11-01T00:00:00Z",
        window_end="2026-11-03T00:00:00Z",
    )
    plan = program.draft_plan(base.dam_id, base.owner_id)
    permit = program.apply_permit(base.dam_id, base.owner_id)
    event = program.declare_event(base.dam_id, declared_at="2026-08-05T13:00:00Z")
    drawdown = program.request_drawdown(
        base.dam_id,
        event["id"],
        window_start="2026-08-06T00:00:00Z",
        window_end="2026-08-06T06:00:00Z",
    )
    return {
        "finding": finding,
        "order": order,
        "second": second,
        "plan": plan,
        "permit": permit,
        "event": event,
        "drawdown": drawdown,
    }


def test_a_second_order_on_an_ordered_finding_is_refused(
    api, program, base, guarded_program
):
    """A finding already under order cannot be ordered again.

    PRD 2.5: "**Deficiency state** — issuing a remediation order requires the deficiency to be `OPEN` or `ESCALATED`; a deficiency already `ORDERED`, `REMEDIATION_SUBMITTED` or `CLOSED_VERIFIED` fails with `ERR_DEFICIENCY_INVALID_STATE` (409)."

    Design: Corner/errors/each_state_guard_returns_its_own_invalid_state_error
    """
    validate_error(
        api.create_remediation_order(
            guarded_program["finding"]["id"],
            f.remediation_order_payload(
                order_type=ORDER_TYPE_NOTICE, requested_response_days=30
            ),
            program.admin,
        ),
        ApiErrorId.ERR_DEFICIENCY_INVALID_STATE,
        409,
    )

    finding = program.deficiencies_for(base.dam_id)[0]
    assert finding["status"] == DEFICIENCY_ORDERED
    assert finding["order_count"] == 1


def test_verifying_an_order_before_any_response_is_refused(
    api, program, base, guarded_program
):
    """Verification needs a filed response, so an ISSUED order refuses it.

    PRD 2.5: "**Remediation order state** — filing a response requires `ISSUED`; verification requires `RESPONSE_FILED`; the penalty preview requires `ISSUED` or `RESPONSE_FILED`."

    Design: Corner/errors/each_state_guard_returns_its_own_invalid_state_error
    """
    order_id = guarded_program["order"]["id"]
    validate_error(
        api.verify_order(
            order_id,
            f.order_verify_payload(
                outcome=VERIFY_SATISFIED, notes="Nothing has been filed yet."
            ),
            base.engineer_a_headers,
        ),
        ApiErrorId.ERR_ORDER_INVALID_STATE,
        409,
    )
    assert program.get_order(order_id)["status"] == ORDER_ISSUED


def test_reviewing_a_draft_plan_is_refused(api, program, base, guarded_program):
    """Review is reserved for a submitted plan, not one still being drafted.

    PRD 2.5: "**Plan state** — submission requires `DRAFT` or `REVISION_REQUIRED`; review requires `SUBMITTED`; logging an exercise requires `APPROVED`."

    Design: Corner/errors/each_state_guard_returns_its_own_invalid_state_error
    """
    plan_id = guarded_program["plan"]["id"]
    validate_error(
        api.review_eap(
            plan_id,
            f.eap_review_payload(
                decision=REVIEW_APPROVE, findings="Reviewing a draft."
            ),
            base.engineer_a_headers,
        ),
        ApiErrorId.ERR_EAP_INVALID_STATE,
        409,
    )
    assert program.get_plan(plan_id)["status"] == EAP_DRAFT


def test_resubmitting_a_permit_that_was_never_returned_is_refused(
    api, program, base, guarded_program
):
    """Only a permit sent back for revision may be resubmitted.

    PRD 2.5: "**Permit state** — review assignment requires `SUBMITTED`; a decision requires `UNDER_ENGINEERING_REVIEW`; resubmission requires `RETURNED_FOR_REVISION`."

    Design: Corner/errors/each_state_guard_returns_its_own_invalid_state_error
    """
    permit_id = guarded_program["permit"]["id"]
    validate_error(
        api.resubmit_permit(
            permit_id,
            f.permit_resubmit_payload(
                scope_description="Gate seal replacement, rev 2",
                estimated_project_cost_cents=4_200_000,
            ),
            base.owner_headers,
        ),
        ApiErrorId.ERR_PERMIT_INVALID_STATE,
        409,
    )

    permit = program.get_permit(permit_id)
    assert permit["status"] == PERMIT_SUBMITTED
    assert permit["revision_count"] == 0


def test_activating_an_uncoordinated_release_reports_the_drawdown_state(
    api, program, base, guarded_program
):
    """The order's own state is judged before the event's escalation.

    PRD 2.5: "**Drawdown order state** — coordination requires `REQUESTED`; activation requires `COORDINATED`; completion requires `ACTIVE`; cancellation requires any non-terminal status."

    Design: Corner/errors/each_state_guard_returns_its_own_invalid_state_error
    """
    drawdown_id = guarded_program["drawdown"]["id"]
    validate_error(
        api.activate_drawdown(drawdown_id, None, program.coordinator),
        ApiErrorId.ERR_DRAWDOWN_INVALID_STATE,
        409,
    )

    assert program.get_drawdown(drawdown_id)["status"] == DRAWDOWN_REQUESTED
    assert_cfs(
        program.get_reach(base.reach_id)["committed_release_cfs"],
        0,
        "committed_release_cfs",
    )


def test_returning_an_inspection_that_was_never_submitted_is_refused(
    api, program, guarded_program
):
    """A return needs findings to send back, so a scheduled visit refuses it.

    PRD 2.5: "**Inspection state** — submission requires `SCHEDULED` or `RETURNED`; acceptance and return both require `SUBMITTED`; `ACCEPTED` is terminal."

    Design: Corner/errors/each_state_guard_returns_its_own_invalid_state_error
    """
    second_id = guarded_program["second"]["id"]
    validate_error(
        api.return_inspection(
            second_id,
            f.inspection_return_payload(
                reason="Cannot return an inspection that was never submitted."
            ),
            program.admin,
        ),
        ApiErrorId.ERR_INSPECTION_INVALID_STATE,
        409,
    )
    assert (
        validate_success(api.get_inspection(second_id, program.admin))["status"]
        == INSPECTION_SCHEDULED
    )


# ---------------------------------------------------------------------------
# Rungs 26 and 27: the window edge and the clock edge are distinct errors
# ---------------------------------------------------------------------------
def test_a_visit_reported_exactly_at_the_window_end_is_outside_it(
    api, program, base, assigned_visit
):
    """The window closes exclusively, and that failure outranks the clock check.

    PRD 3.3: "The reported instant must sit inside the reserved window — at or after `window_start` and strictly before `window_end`, so an instant exactly at the start is inside and one exactly at the end is outside, the boundary case rejected with `ERR_OUTSIDE_INSPECTION_WINDOW` — and it must be at or before the current logical clock, equality being permitted, with a later instant rejected as `ERR_PERFORMED_AT_IN_FUTURE`."

    Design: Corner/errors/window_end_and_future_submissions_return_distinct_errors
    """
    validate_error(
        api.submit_inspection(
            assigned_visit["id"],
            f.inspection_submission_payload(
                performed_at="2026-08-06T00:00:00Z",
                condition_rating=SAFETY_SATISFACTORY,
                narrative="At the closing edge.",
                deficiencies=[],
            ),
            base.engineer_a_headers,
        ),
        ApiErrorId.ERR_OUTSIDE_INSPECTION_WINDOW,
        422,
    )
    assert (
        validate_success(api.get_inspection(assigned_visit["id"], program.admin))[
            "status"
        ]
        == INSPECTION_SCHEDULED
    )


def test_a_visit_reported_ahead_of_the_clock_is_refused(
    api, program, base, assigned_visit
):
    """An instant inside the window but later than the clock is a future report.

    PRD 2.5: "**Inspection not reported from the future** — `performed_at` is at or before the logical clock; otherwise `ERR_PERFORMED_AT_IN_FUTURE` (422)."

    Design: Corner/errors/window_end_and_future_submissions_return_distinct_errors
    """
    validate_error(
        api.submit_inspection(
            assigned_visit["id"],
            f.inspection_submission_payload(
                performed_at="2026-08-05T18:00:00Z",
                condition_rating=SAFETY_SATISFACTORY,
                narrative="Ahead of the clock.",
                deficiencies=[],
            ),
            base.engineer_a_headers,
        ),
        ApiErrorId.ERR_PERFORMED_AT_IN_FUTURE,
        422,
    )
    unchanged = validate_success(
        api.get_inspection(assigned_visit["id"], program.admin)
    )
    assert unchanged["status"] == INSPECTION_SCHEDULED
    assert unchanged["performed_at"] is None


def test_a_visit_reported_exactly_at_the_window_start_is_accepted(
    api, program, base, assigned_visit
):
    """The window opens inclusively, so the opening instant submits cleanly.

    PRD 3.3: "Submission moves the inspection `SCHEDULED → SUBMITTED`."

    Design: Corner/errors/window_end_and_future_submissions_return_distinct_errors
    """
    submitted = validate_success(
        api.submit_inspection(
            assigned_visit["id"],
            f.inspection_submission_payload(
                performed_at="2026-08-04T00:00:00Z",
                condition_rating=SAFETY_SATISFACTORY,
                narrative="Exactly at window_start.",
                deficiencies=[],
            ),
            base.engineer_a_headers,
        )
    )
    assert submitted["status"] == INSPECTION_SUBMITTED
    assert_instant(
        submitted["performed_at"], "2026-08-04T00:00:00Z", "performed_at"
    )
    assert program.deficiencies_for(base.dam_id) == []


# ---------------------------------------------------------------------------
# Rung 36: the bond floor binds only on a high-hazard dam
# ---------------------------------------------------------------------------
@pytest.fixture()
def bond_short_owner(program):
    """One owner a cent short of the bond floor, holding a HIGH and a SIGNIFICANT dam."""
    setup = program.bootstrap(
        clock=None, owner={"financial_assurance_bond_cents": 24_999_999}
    )
    program.classify(setup.dam_id, setup.engineer_a_id, f.assessment_a4)
    program.approved_plan(
        setup.dam_id,
        setup.owner_id,
        setup.engineer_b_id,
        inundation_map_ref="IM-2026-D",
        notification_contact_count=8,
    )
    sig_dam = program.create_dam(
        setup.owner_id,
        setup.reach_id,
        name="Basalt Ridge Dam",
        nid_code="ST00181",
    )
    program.classify_significant(sig_dam["id"], setup.engineer_a_id)

    high_permit = program.apply_permit(
        setup.dam_id,
        setup.owner_id,
        permit_type=PERMIT_TYPE_REPAIR,
        estimated_project_cost_cents=8_000_000,
    )
    program.post_ledger_entry(
        setup.owner_id,
        entry_type=ENTRY_PAYMENT_RECEIVED,
        amount_cents=-150_000,
        memo="High-hazard repair review fee settled in full.",
    )
    sig_permit = program.apply_permit(
        sig_dam["id"],
        setup.owner_id,
        permit_type=PERMIT_TYPE_REPAIR,
        estimated_project_cost_cents=4_000_000,
    )
    program.post_ledger_entry(
        setup.owner_id,
        entry_type=ENTRY_PAYMENT_RECEIVED,
        amount_cents=-47_000,
        memo="Significant-hazard repair review fee settled in full.",
    )
    program.assign_permit_review(high_permit["id"], setup.engineer_b_id)
    program.assign_permit_review(sig_permit["id"], setup.engineer_b_id)
    return {
        "setup": setup,
        "sig_dam": sig_dam,
        "high_permit": high_permit,
        "sig_permit": sig_permit,
    }


def test_both_applications_are_priced_and_settled_before_the_decision(
    program, bond_short_owner
):
    """The two review fees differ by tier and uplift, and both are paid off.

    PRD 3.6: "**Second**, an engineering review fee proportional to the project: the cost is multiplied by the work class's percentage — 0.75 percent for `CONSTRUCTION`, 0.5 percent for `REPAIR`, 0.35 percent for `REMOVAL` — and then by the hazard uplift of 1.25 at `HIGH`, 1.10 at `SIGNIFICANT`, and 1.0 at both `LOW` and `UNCLASSIFIED`; the product is rounded half up to whole cents and then capped at 750,000 cents."

    Design: Corner/errors/high_hazard_permit_rejected_for_a_bond_one_cent_below_the_minimum
    """
    high = program.get_permit(bond_short_owner["high_permit"]["id"])
    assert_cents(high["base_fee_cents"], 100_000, "base_fee_cents")
    assert_cents(high["engineering_review_fee_cents"], 50_000, "engineering_review_fee_cents")
    assert_cents(high["total_fee_cents"], 150_000, "total_fee_cents")

    sig = program.get_permit(bond_short_owner["sig_permit"]["id"])
    assert_cents(sig["base_fee_cents"], 25_000, "base_fee_cents")
    assert_cents(sig["engineering_review_fee_cents"], 22_000, "engineering_review_fee_cents")
    assert_cents(sig["total_fee_cents"], 47_000, "total_fee_cents")

    owner = program.get_owner(bond_short_owner["setup"].owner_id)
    assert_cents(owner["fee_balance_cents"], 0, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_CURRENT


def test_the_high_hazard_decision_is_refused_for_the_missing_cent(
    api, program, bond_short_owner
):
    """A bond one cent short blocks the decision, and it is not a fee problem.

    PRD 2.5: "**Financial assurance posted** — when the dam's hazard class is `HIGH`, the owner's posted bond meets the statutory floor; otherwise `ERR_INSUFFICIENT_FINANCIAL_ASSURANCE` (402)."

    Design: Corner/errors/high_hazard_permit_rejected_for_a_bond_one_cent_below_the_minimum
    """
    setup = bond_short_owner["setup"]
    permit_id = bond_short_owner["high_permit"]["id"]
    validate_error(
        api.decide_permit(
            permit_id,
            f.permit_decision_payload(findings="Engineering adequate."),
            make_engineer_headers(setup.engineer_b_id),
        ),
        ApiErrorId.ERR_INSUFFICIENT_FINANCIAL_ASSURANCE,
        402,
    )

    permit = program.get_permit(permit_id)
    assert permit["status"] == PERMIT_UNDER_ENGINEERING_REVIEW
    assert permit["issued_at"] is None
    assert permit["decision_findings"] is None

    dam = program.get_dam(setup.dam_id)
    assert dam["hazard_class"] == HAZARD_HIGH
    assert dam["latest_eap_status"] == EAP_APPROVED


def test_the_same_owners_significant_dam_issues_without_complaint(
    api, program, bond_short_owner
):
    """The bond floor is scoped to high hazard, so the sister permit issues.

    PRD 3.6: "Four further gates then apply, in the order §2.5 fixes: a `CONSTRUCTION` permit on a dam whose `safety_status` is `UNSATISFACTORY` is barred with `ERR_UNSAFE_DAM_PERMIT_BLOCKED` while `REPAIR` and `REMOVAL` work stays permissible on the same dam; a dam whose `hazard_class` is `HIGH` must have a `latest_eap_status` of `APPROVED` or the decision fails with `ERR_EAP_NOT_APPROVED`; the owner must not be delinquent, or the decision fails with `ERR_OWNER_DELINQUENT`; and on a `HIGH`-hazard dam the owner's `financial_assurance_bond_cents` must be at least 25,000,000 cents, or the decision fails with `ERR_INSUFFICIENT_FINANCIAL_ASSURANCE`."

    Design: Corner/errors/high_hazard_permit_rejected_for_a_bond_one_cent_below_the_minimum
    """
    setup = bond_short_owner["setup"]
    assert (
        program.get_dam(bond_short_owner["sig_dam"]["id"])["hazard_class"]
        == HAZARD_SIGNIFICANT
    )

    issued = validate_success(
        api.decide_permit(
            bond_short_owner["sig_permit"]["id"],
            f.permit_decision_payload(findings="Engineering adequate."),
            make_engineer_headers(setup.engineer_b_id),
        )
    )
    assert issued["status"] == PERMIT_ISSUED
    assert issued["issued_at"] is not None
