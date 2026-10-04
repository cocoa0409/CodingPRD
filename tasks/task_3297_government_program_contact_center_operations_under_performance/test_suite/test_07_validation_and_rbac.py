"""Validation pipeline: priority ordering, enum closure, RBAC denials,
ownership gates, overflow rules, surge overlap, and OCC behavior."""
from test_helpers import (
    TEST_USERS,
    api_client,
    build_user_headers,
    create_incident_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import NON_EXISTENT_ID
from test_helpers.factories import (
    create_contract_payload,
    create_queue_payload,
    create_service_level_payload,
    create_surge_window_payload,
)
from test_helpers.fixtures import (
    BILL,
    KM,
    OPS,
    SUP,
    activate_contract,
    activate_service_level,
    answer_call,
    certify_agent,
    complete_call,
    create_agent,
    create_article,
    create_contract,
    create_course,
    create_draft_service_level,
    create_invoice,
    create_queue,
    create_review,
    get_contract,
    get_invoice,
    list_certifications,
    list_invoice_lines,
    make_agent_headers,
    prepare_invoice,
    publish_article,
    register_call,
    route_call,
    set_clock,
    setup_completed_call,
    setup_routable,
    get_call,
)

ADMIN = TEST_USERS["platform_admin_headers"]
QA_H = TEST_USERS["quality_analyst_headers"]
SEC = TEST_USERS["security_officer_headers"]


# ------------------------------------------------------------- auth / priority

def test_unauthenticated_missing_headers():
    """PRD §2.1: "A request missing either header, or presenting an
    `X-User-Role` value outside this declared set, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.6: "Every request is validated in a fixed priority order, and the
    first failing check determines the error returned. The order is: (1)
    authentication — both headers present and the role recognized, else
    `ERR_UNAUTHENTICATED`".

    Design: Corner/errors/unauthenticated_missing_headers
    """
    resp = api_client.get_contract(NON_EXISTENT_ID, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_stale_version_on_invoice_approve():
    """PRD §3.12: "The optimistic-concurrency gate of §2.8 fires first: a
    request with `to_status` of `APPROVED` must carry
    `expected_contract_version` equal to the contract's current `version`, or
    it is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.1: "A successful activation does three things at once: the service
    level becomes `EFFECTIVE`; every other service level of the same contract,
    `program_code`, and `metric` that is currently `EFFECTIVE` and has a
    strictly earlier `effective_from` is cascaded to `SUPERSEDED`; and the
    parent Contract's `version` is incremented by 1."

    Design: Corner/errors/stale_version_on_invoice_approve
    """
    ctx = setup_routable()
    contract_id = ctx["contract"]["id"]
    sl2 = create_draft_service_level(
        contract_id, metric="ABANDON", target=0.05, cap_pct_of_gross=0.5,
        remedy_fee_cents=800,
    )
    invoice = create_invoice(contract_id)
    prepare_invoice(invoice["id"])
    validate_success(
        api_client.transition_invoice(invoice["id"], {"to_status": "SUBMITTED"}, BILL)
    )

    contract = get_contract(contract_id)
    stale_version = contract["version"]
    # Activating the second service level bumps Contract.version by 1.
    activate_service_level(contract, sl2["id"])
    assert get_contract(contract_id)["version"] == stale_version + 1

    resp = api_client.transition_invoice(
        invoice["id"],
        {"to_status": "APPROVED", "expected_contract_version": stale_version},
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_invoice(invoice["id"])["status"] == "SUBMITTED"


def test_occ_happy_path_version_advances():
    """PRD §2.8: "If the contract's current `version` differs from the
    supplied value — because activation, closure, or any other mutation has
    advanced it since — the write is rejected with `ERR_STALE_VERSION`
    (HTTP 412), and no state change occurs."
    PRD §3.1: "A successful activation does three things at once: the service
    level becomes `EFFECTIVE`; ... and the parent Contract's `version` is
    incremented by 1."

    Design: Corner/cross_cutting_layers/occ_happy_path_version_advances
    """
    ctx = setup_routable()
    contract_id = ctx["contract"]["id"]
    sl2 = create_draft_service_level(
        contract_id, metric="ABANDON", target=0.05, cap_pct_of_gross=0.5,
        remedy_fee_cents=800,
    )
    observed = get_contract(contract_id)["version"]
    activated = validate_success(
        api_client.transition_service_level(
            sl2["id"],
            {"to_status": "EFFECTIVE", "expected_contract_version": observed},
            OPS,
        )
    )
    assert activated["status"] == "EFFECTIVE"
    assert get_contract(contract_id)["version"] == observed + 1

    replay = api_client.transition_service_level(
        sl2["id"],
        {"to_status": "EFFECTIVE", "expected_contract_version": observed},
        OPS,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)


def test_stale_version_beats_invalid_state_on_sl_activation():
    """PRD §2.6: "Every request is validated in a fixed priority order, and
    the first failing check determines the error returned. The order is: ...
    (5) optimistic-concurrency staleness on the guarded writes, else
    `ERR_STALE_VERSION` (HTTP 412); (6) state-machine legality of the
    requested transition, else `ERR_INVALID_STATE`".

    Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_invalid_state_on_sl_activation
    """
    ctx = setup_routable()
    sl = ctx["sl"]
    assert sl["status"] == "EFFECTIVE"
    contract = get_contract(ctx["contract"]["id"])
    stale = contract["version"] - 1
    assert stale >= 1
    resp = api_client.transition_service_level(
        sl["id"],
        {"to_status": "EFFECTIVE", "expected_contract_version": stale},
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = validate_success(api_client.get_service_level(sl["id"], OPS))
    assert after["status"] == "EFFECTIVE"
    assert get_contract(ctx["contract"]["id"])["version"] == contract["version"]


def test_stale_version_rejection_leaves_service_level_unchanged():
    """PRD §2.8: "If the contract's current `version` differs from the
    supplied value — because activation, closure, or any other mutation has
    advanced it since — the write is rejected with `ERR_STALE_VERSION`
    (HTTP 412), and no state change occurs."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_invalid_state_on_sl_activation
    """
    ctx = setup_routable()
    sl2 = create_draft_service_level(
        ctx["contract"]["id"], metric="ABANDON", target=0.05,
        cap_pct_of_gross=0.5, remedy_fee_cents=800,
    )
    contract = get_contract(ctx["contract"]["id"])
    resp = api_client.transition_service_level(
        sl2["id"],
        {"to_status": "EFFECTIVE",
         "expected_contract_version": contract["version"] - 1},
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = validate_success(api_client.get_service_level(sl2["id"], OPS))
    assert after["status"] == "DRAFT", "no state change occurs"


def test_missing_role_beats_state_check_on_call_answer():
    """PRD §2.6: "Every request is validated in a fixed priority order, and
    the first failing check determines the error returned. The order is: (1)
    authentication ...; (2) authorization — the role is permitted for this
    endpoint, else `ERR_FORBIDDEN`; ... (6) state-machine legality of the
    requested transition, else `ERR_INVALID_STATE`".
    PRD §1: "A floor supervisor registers and routes calls and manages
    coaching. Agents answer only the calls placed on their own desks."

    Design: Difficulty/priority_pair_validation_conflict/missing_role_beats_state_check_on_call_answer
    """
    ctx = setup_routable()
    call = register_call(ctx["contract"]["id"], enqueued_at="2026-09-05T09:00:00Z")
    resp = api_client.transition_call(call["id"], {"to_status": "ANSWERED"}, KM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_call(call["id"])["status"] == "WAITING"


def test_knowledge_manager_cannot_route_calls():
    """PRD §2.1: "A request whose role is authenticated but not permitted for
    the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §1: "A floor supervisor registers and routes calls and manages
    coaching."

    Design: Difficulty/priority_pair_validation_conflict/missing_role_beats_state_check_on_call_answer
    """
    ctx = setup_routable()
    call = register_call(ctx["contract"]["id"], enqueued_at="2026-09-05T09:00:00Z")
    resp = api_client.transition_call(call["id"], {"to_status": "ASSIGNED"}, KM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_body_fk_order_contract_before_agent_on_completion():
    """PRD §2.6: "existence — path identifiers are validated left to right,
    and body foreign keys are checked in the endpoint's declared input order,
    each miss producing the entity-specific 404 (`ERR_CONTRACT_NOT_FOUND`,
    `ERR_SERVICE_LEVEL_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, ...,
    `ERR_TRAINING_COURSE_NOT_FOUND`, ...)".

    Design: Corner/validations/body_fk_order_contract_before_agent_on_completion
    """
    course = create_course()
    resp1 = api_client.complete_training_course(
        course["id"],
        {"agent_id": NON_EXISTENT_ID, "valid_until": "2027-01-01T00:00:00Z"},
        KM,
    )
    validate_error(resp1, ApiErrorId.ERR_AGENT_NOT_FOUND)
    resp2 = api_client.complete_training_course(
        NON_EXISTENT_ID,
        {"agent_id": NON_EXISTENT_ID, "valid_until": "2027-01-01T00:00:00Z"},
        KM,
    )
    validate_error(resp2, ApiErrorId.ERR_TRAINING_COURSE_NOT_FOUND)
    rows, _ = validate_paginated(api_client.list_certifications(OPS))
    assert len(rows) == 0


def test_invalid_enum_value_rejected():
    """PRD §2.6: "request shape — required fields present, values well-typed,
    enum values inside their declared sets, referential fields well-formed,
    else `ERR_INVALID_REQUEST` (HTTP 400)".
    PRD §3.1: "the `metric` it governs — one of `ASA`, `ABANDON`, or `QA_AVG`".

    Design: Corner/validations/invalid_enum_value_rejected
    """
    contract = create_contract()
    payload = create_service_level_payload(contract["id"], metric="ASA", target=30)
    payload["metric"] = "SPEEDY"
    resp1 = api_client.create_service_level(payload, OPS)
    validate_error(resp1, ApiErrorId.ERR_INVALID_REQUEST)

    resp2 = api_client.transition_contract(
        contract["id"], {"to_status": "FROZEN"}, OPS
    )
    validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST)

    rows, _ = validate_paginated(
        api_client.list_service_levels(OPS, params={"contract_id": contract["id"]})
    )
    assert len(rows) == 0
    assert get_contract(contract["id"])["status"] == "DRAFT"


def test_existence_checked_before_state_on_transition():
    """PRD §2.6: "Every request is validated in a fixed priority order, and
    the first failing check determines the error returned. The order is: ...
    (3) existence — path identifiers are validated left to right ... each miss
    producing the entity-specific 404 ...; ... (6) state-machine legality of
    the requested transition, else `ERR_INVALID_STATE`".

    Design: Corner/validations/existence_checked_before_state_on_transition
    """
    resp = api_client.transition_queue(
        NON_EXISTENT_ID, {"to_status": "PAUSED"}, OPS
    )
    validate_error(resp, ApiErrorId.ERR_QUEUE_NOT_FOUND)


def test_peer_role_exclusive_denials():
    """PRD §2.1: "A request whose role is authenticated but not permitted for
    the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §1: "An operations lead shapes the commercial and topological
    skeleton — contracts, service levels, queues, surge windows."
    PRD §1: "A knowledge manager publishes rule changes and administers the
    training pipeline that keeps certifications honest."
    PRD §1: "a billing analyst prepares invoices whose withheld amounts are
    computed from measured performance rather than asserted effort."

    Design: Corner/roles/peer_role_exclusive_denials
    """
    contract = create_contract()
    resp1 = api_client.create_queue(
        create_queue_payload(contract["id"]), BILL
    )
    validate_error(resp1, ApiErrorId.ERR_FORBIDDEN)

    resp2 = api_client.create_knowledge_article(
        {
            "program_code": "MEDICAID",
            "title": "t",
            "body": "b",
            "effective_at": "2026-09-10T00:00:00Z",
        },
        SUP,
    )
    validate_error(resp2, ApiErrorId.ERR_FORBIDDEN)

    resp3 = api_client.create_invoice(
        {"contract_id": contract["id"], "period": "2026-09"},
        build_user_headers("00000000-0000-4000-8000-000000000000", "Agent"),
    )
    validate_error(resp3, ApiErrorId.ERR_FORBIDDEN)


def test_agent_identity_ownership_on_answer_and_dispute():
    """PRD §2.9: "An `Agent` may act only on calls assigned to that agent's
    own `X-User-ID`: answering or completing a call whose `agent_id` names
    someone else is rejected with `ERR_FORBIDDEN`, as is disputing a quality
    review of a call the agent did not handle."
    PRD §3.5: "Dispute, requested with `to_status` of `DISPUTED`, is the
    reviewed agent's prerogative: the acting `X-User-ID` must equal the
    `handled_by_agent_id` of the reviewed call, and anyone else's dispute is
    refused with `ERR_FORBIDDEN`."

    Design: Corner/roles/agent_identity_ownership_on_answer_and_dispute
    """
    ctx = setup_routable()
    agent_a = ctx["agent"]
    agent_b = create_agent(full_name="Agent Two")
    certify_agent(agent_b["id"], ctx["course"]["id"])
    contract_id = ctx["contract"]["id"]

    # A completed call handled by agent A, with a SUBMITTED review.
    call_a = register_call(contract_id, enqueued_at="2026-09-05T09:00:00Z")
    call_a = route_call(call_a["id"])
    assert call_a["agent_id"] == agent_a["id"]
    call_a = answer_call(call_a, agent_a["id"])
    call_a = complete_call(call_a, agent_a["id"])
    review = create_review(call_a["id"], accuracy_score=90, compliance_score=90)

    # A second call routed to agent B (agent A is free again after completing).
    call_b = register_call(contract_id, enqueued_at="2026-09-05T09:05:00Z")
    call_b = route_call(call_b["id"])
    assert call_b["agent_id"] == agent_b["id"]

    resp1 = api_client.transition_call(
        call_b["id"], {"to_status": "ANSWERED"}, make_agent_headers(agent_a["id"])
    )
    validate_error(resp1, ApiErrorId.ERR_FORBIDDEN)

    resp2 = api_client.transition_quality_review(
        review["id"], {"to_status": "DISPUTED"}, make_agent_headers(agent_b["id"])
    )
    validate_error(resp2, ApiErrorId.ERR_FORBIDDEN)

    assert get_call(call_b["id"])["status"] == "ASSIGNED"
    review_after = validate_success(api_client.get_quality_review(review["id"], QA_H))
    assert review_after["status"] == "SUBMITTED"


def test_overflow_mismatch_and_overflow_locked():
    """PRD §3.3: "The target must be another queue of the same contract, with
    the same `language_code`, and — when the queue is `SPECIALTY` — the same
    `specialty_tag`; the referenced queue must already exist both at creation
    and on every later update, and any mismatch is rejected with
    `ERR_QUEUE_OVERFLOW_MISMATCH` (HTTP 409)."
    PRD §3.3: "clearing the overflow reference (setting it back to null) is
    forbidden once at least one call has been assigned to the queue, and such
    an attempt is rejected with `ERR_OVERFLOW_LOCKED` (HTTP 409)."

    Design: Corner/validations/overflow_mismatch_and_overflow_locked
    """
    ctx = setup_routable()
    contract_id = ctx["contract"]["id"]
    q_en2 = create_queue(contract_id)
    q_en1 = create_queue(contract_id, overflow_queue_id=q_en2["id"])
    q_es = create_queue(contract_id, language_code="es")

    call = register_call(contract_id, enqueued_at="2026-09-05T09:00:00Z")
    route_call(call["id"])

    mismatch = api_client.create_queue(
        create_queue_payload(contract_id, overflow_queue_id=q_es["id"]), OPS
    )
    validate_error(mismatch, ApiErrorId.ERR_QUEUE_OVERFLOW_MISMATCH)

    # The queue from setup_routable is the earliest-created English queue,
    # so the call was assigned to it; clearing its overflow after the
    # assignment is locked. Give it an overflow target first so there is an
    # overflow reference to clear.
    assigned = get_call(call["id"])
    primary = ctx["queue"]
    assert assigned["queue_id"] == primary["id"]
    set_overflow = api_client.patch_queue(
        primary["id"], {"overflow_queue_id": q_en2["id"]}, OPS
    )
    validate_success(set_overflow)
    locked = api_client.patch_queue(primary["id"], {"overflow_queue_id": None}, OPS)
    validate_error(locked, ApiErrorId.ERR_OVERFLOW_LOCKED)

    # Repointing to a valid target of the same language is allowed.
    repoint = api_client.patch_queue(
        primary["id"], {"overflow_queue_id": q_en2["id"]}, OPS
    )
    repointed = validate_success(repoint)
    assert repointed["version"] > primary["version"]


def test_surge_window_adjacency_rejected():
    """PRD §3.7: "Windows of the same contract and program may not overlap,
    and adjacency counts as collision: a candidate window spanning the
    half-open interval from its start to its end collides with an existing
    `DECLARED` or `ACTIVE` window whenever the candidate's start is strictly
    before the existing window's end and the candidate's end is strictly after
    the existing window's start — so a candidate beginning exactly when
    another ends is rejected. Collisions surface as `ERR_SURGE_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/surge_window_adjacency_rejected
    """
    ctx = setup_routable()
    contract_id = ctx["contract"]["id"]
    validate_success(
        api_client.create_surge_window(
            create_surge_window_payload(
                contract_id,
                starts_on="2026-09-01T00:00:00Z",
                ends_on="2026-09-30T00:00:00Z",
                expected_volume_factor=1.5,
            ),
            OPS,
        ),
        201,
    )
    resp = api_client.create_surge_window(
        create_surge_window_payload(
            contract_id,
            surge_type="POLICY_CHANGE",
            starts_on="2026-09-30T00:00:00Z",
            ends_on="2026-10-15T00:00:00Z",
            expected_volume_factor=1.2,
        ),
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_SURGE_OVERLAP)
    rows, meta = validate_paginated(
        api_client.list_surge_windows(OPS, params={"contract_id": contract_id})
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "ACTIVE", (
        "clock is at 2026-09-01 == starts_on, so the window auto-activated"
    )


def test_surge_window_true_gap_is_accepted():
    """PRD §3.7: "Windows of the same contract and program may not overlap,
    and adjacency counts as collision: a candidate window spanning the
    half-open interval from its start to its end collides with an existing
    `DECLARED` or `ACTIVE` window whenever the candidate's start is strictly
    before the existing window's end and the candidate's end is strictly after
    the existing window's start".

    Design: Difficulty/resource_temporal_overlap/surge_window_adjacency_rejected
    """
    ctx = setup_routable()
    contract_id = ctx["contract"]["id"]
    validate_success(
        api_client.create_surge_window(
            create_surge_window_payload(
                contract_id,
                starts_on="2026-09-01T00:00:00Z",
                ends_on="2026-09-30T00:00:00Z",
                expected_volume_factor=1.5,
            ),
            OPS,
        ),
        201,
    )
    resp = api_client.create_surge_window(
        create_surge_window_payload(
            contract_id,
            surge_type="POLICY_CHANGE",
            starts_on="2026-10-01T00:00:00Z",
            ends_on="2026-10-15T00:00:00Z",
            expected_volume_factor=1.2,
        ),
        OPS,
    )
    validate_success(resp, expected_status=201)
    rows, _ = validate_paginated(
        api_client.list_surge_windows(OPS, params={"contract_id": contract_id})
    )
    assert len(rows) == 2
