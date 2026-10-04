"""State-machine terminal states and gated transitions: punch verification,
warranty review, floor sequencing with order bubble-up, and the punch-resolve
auto-claim cascade (PRD §3.6, §3.8)."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    acknowledge_order,
    assert_warranty_claim,
    complete_phase,
    create_and_lock_configuration,
    create_order,
    create_phase,
    file_claim,
    file_punch,
    get_order,
    make_dealer_headers,
    make_end_user_headers,
    make_module_entry,
    make_review_payload,
    make_verify_payload,
    reserve_slot,
    resolve_punch,
    review_claim,
    set_logical_clock,
    setup_completed_phase,
    setup_dealer_world,
    setup_phase_in_progress,
    start_install,
    submit_order,
    validate_error,
    validate_paginated,
    verify_punch,
)

ADMIN_HEADERS = TEST_USERS["admin_headers"]


def test_verified_punch_terminal_rejects_reverify(api):
    """PRD §3.8: "An `outcome` of `CONFIRMED` moves the ticket `RESOLVED →
    VERIFIED`, its terminal accepted state" — a further verify of a VERIFIED
    ticket is a generic state violation rejected with `ERR_INVALID_STATE`
    (§2.9 step 8).

    Design: Corner/state_machines/sm_verified_punch_terminal_rejects_reverify
    """
    ctx = setup_phase_in_progress(api)
    dealer_id = ctx["dealer"]["id"]
    eu_id = ctx["end_user"]["id"]
    ticket = file_punch(
        api, ctx["phase"]["id"], make_end_user_headers(eu_id),
        severity="MINOR", description="Scuff",
    )
    resolve_punch(api, ticket["id"], dealer_id, resolution_note="Polished out")
    verified = verify_punch(api, ticket["id"], eu_id, outcome="CONFIRMED")
    assert verified["status"] == "VERIFIED"

    resp = api.verify_punch_ticket(
        ticket["id"], make_verify_payload("CONFIRMED"),
        make_end_user_headers(eu_id),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_approved_claim_terminal_rejects_rereview(api):
    """PRD §3.8: "Reviewing a claim that is already `APPROVED` or `DENIED` is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sm_approved_claim_terminal_rejects_rereview
    """
    ctx = setup_completed_phase(api)
    claim = file_claim(
        api, ctx["order"]["id"], ctx["phase"]["id"], ctx["dealer"]["id"],
        claim_type="PARTS", part_number="PN-CHR-TASK",
        description="Caster failed",
    )
    approved = review_claim(api, claim["id"], decision="APPROVE",
                            review_note="covered")
    assert approved["status"] == "APPROVED"

    resp = api.review_warranty_claim(
        claim["id"], make_review_payload("DENY", "reconsider"), ADMIN_HEADERS
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_denied_claim_terminal_rejects_rereview(api):
    """PRD §3.8: "Reviewing a claim that is already `APPROVED` or `DENIED` is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sm_denied_claim_terminal_rejects_rereview
    """
    ctx = setup_completed_phase(api)
    claim = file_claim(
        api, ctx["order"]["id"], ctx["phase"]["id"], ctx["dealer"]["id"],
        claim_type="LABOR", description="Re-level panel run",
    )
    denied = review_claim(api, claim["id"], decision="DENY",
                          review_note="wear and tear")
    assert denied["status"] == "DENIED"

    resp = api.review_warranty_claim(
        claim["id"], make_review_payload("APPROVE", "reconsider"), ADMIN_HEADERS
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_floor_sequence_enforced_then_bubble_up_close(api):
    """PRD §3.6: "Floor sequencing comes first: every other phase of the same
    order with a lower `floor_number` — or the same `floor_number` and a lower
    `phase_sequence` — must already be `COMPLETE`, else
    `ERR_FLOOR_SEQUENCE_VIOLATION`." and "if the order is `ACKNOWLEDGED`, has
    at least one phase, and every phase of the order is `COMPLETE`, the order
    itself moves `ACKNOWLEDGED → CLOSED`".

    Design: Corner/state_machines/sm_floor_sequence_enforced_then_bubble_up_close
    """
    ctx = setup_dealer_world(api)
    dealer_id = ctx["dealer"]["id"]
    spec = create_and_lock_configuration(
        api, dealer_id, modules=[make_module_entry("TASK_CHAIR_SET", "A", 20)]
    )
    order = create_order(api, ctx["agreement"]["id"], spec["id"], dealer_id)
    order = submit_order(api, order, dealer_id)
    acknowledge_order(api, order["id"])

    ph1 = create_phase(api, order["id"], dealer_id,
                       floor_number=1, phase_sequence=1, planned_units=10)
    ph2 = create_phase(api, order["id"], dealer_id,
                       floor_number=2, phase_sequence=2, planned_units=10)
    reserve_slot(api, ph1["id"], dealer_id)
    reserve_slot(api, ph2["id"], dealer_id)
    set_logical_clock(api, "2026-11-02T00:00:00Z")
    start_install(api, ph1["id"], dealer_id)
    start_install(api, ph2["id"], dealer_id)

    # Floor 2 cannot complete while floor 1 is still IN_PROGRESS.
    resp = api.complete_phase(ph2["id"], make_dealer_headers(dealer_id))
    validate_error(resp, ApiErrorId.ERR_FLOOR_SEQUENCE_VIOLATION)

    done1 = complete_phase(api, ph1["id"], dealer_id)
    assert done1["install_status"] == "COMPLETE"
    done2 = complete_phase(api, ph2["id"], dealer_id)
    assert done2["install_status"] == "COMPLETE"

    order_now = get_order(api, order["id"], make_dealer_headers(dealer_id))
    assert order_now["status"] == "CLOSED"


def test_punch_resolve_with_part_auto_creates_warranty_claim(api):
    """PRD §3.8: "When the ticket's `requires_part` is true, resolution
    auto-engages manufacturer parts support: a `WarrantyClaim` is created in
    `SUBMITTED` status with `claim_type` `PARTS`, the `part_number` copied
    from the ticket, `punch_ticket_id` set to the ticket's `id`,
    `project_order_id` and `installation_phase_id` copied from the ticket's
    phase, and `filed_date` set to the clock date". Claims "can be listed
    filtered by `project_order_id`, `installation_phase_id`, and
    `punch_ticket_id`."

    Design: Corner/state_machines/sm_punch_resolve_with_part_auto_creates_warranty_claim
    """
    ctx = setup_phase_in_progress(api)
    dealer_id = ctx["dealer"]["id"]
    eu_id = ctx["end_user"]["id"]
    pt1 = file_punch(
        api, ctx["phase"]["id"], make_end_user_headers(eu_id),
        severity="CRITICAL", description="Broken caster",
        requires_part=True, part_number="PN-CHR-TASK",
    )
    pt2 = file_punch(
        api, ctx["phase"]["id"], make_end_user_headers(eu_id),
        severity="MINOR", description="Scuff",
    )

    resolve_punch(api, pt1["id"], dealer_id, resolution_note="Caster ordered")
    resolve_punch(api, pt2["id"], dealer_id, resolution_note="Polished")

    claims1, meta1 = validate_paginated(
        api.list_warranty_claims(
            make_dealer_headers(dealer_id),
            params={"punch_ticket_id": pt1["id"]},
        )
    )
    assert meta1["total_count"] == 1
    assert len(claims1) == 1
    assert_warranty_claim(claims1[0])
    assert claims1[0]["status"] == "SUBMITTED"
    assert claims1[0]["claim_type"] == "PARTS"
    assert claims1[0]["part_number"] == "PN-CHR-TASK"
    assert claims1[0]["punch_ticket_id"] == pt1["id"]
    assert claims1[0]["filed_date"] == "2026-11-02"

    claims2, meta2 = validate_paginated(
        api.list_warranty_claims(
            make_dealer_headers(dealer_id),
            params={"punch_ticket_id": pt2["id"]},
        )
    )
    assert meta2["total_count"] == 0
    assert claims2 == []
