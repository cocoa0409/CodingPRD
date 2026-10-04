"""Routing selectors: certification freshness boundaries, the publish ->
invalidate -> unroutable cascade, and least-busy agent ranking."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_article,
    publish_article,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import create_call_payload, create_queue_payload
from test_helpers.fixtures import (
    OPS,
    SUP,
    activate_contract,
    certify_agent,
    create_agent,
    create_contract,
    create_course,
    create_draft_service_level,
    activate_service_level,
    get_call,
    list_certifications,
    register_call,
    route_call,
    set_clock,
    setup_routable,
)

OPS_H = TEST_USERS["ops_manager_headers"]
SUP_H = TEST_USERS["supervisor_headers"]


def _setup_contract_with_queue():
    """ACTIVE contract + EFFECTIVE ASA SL; returns (contract, sl)."""
    contract = create_contract()
    sl = create_draft_service_level(contract["id"], metric="ASA", target=30)
    activate_service_level(contract, sl["id"])
    return contract, sl


def test_certification_freshness_at_exact_expiry_blocks_routing():
    """PRD §3.2: "A certification is **standing** at time `t` when its
    `valid_until` is strictly after `t` — a certification expiring exactly at
    `t` is already stale — and its `invalidated_at` is null."
    PRD §3.3: "If no eligible queue exists even after the fallback, the route
    attempt fails with `ERR_NO_ELIGIBLE_QUEUE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/certification_freshness_instant_valid_until_boundary
    """
    contract, _ = _setup_contract_with_queue()
    agent = create_agent()
    course = create_course()
    certify_agent(agent["id"], course["id"], valid_until="2026-09-10T00:00:00Z")
    queue = validate_success(
        api_client.create_queue(create_queue_payload(contract["id"]), OPS_H), 201
    )
    call1 = register_call(contract["id"], enqueued_at="2026-09-09T23:59:59Z")
    call2 = register_call(contract["id"], enqueued_at="2026-09-10T00:00:00Z")

    set_clock("2026-09-09T23:59:59Z")
    routed = validate_success(
        api_client.transition_call(call1["id"], {"to_status": "ASSIGNED"}, SUP_H)
    )
    assert routed["status"] == "ASSIGNED"

    set_clock("2026-09-10T00:00:00Z")
    resp = api_client.transition_call(call2["id"], {"to_status": "ASSIGNED"}, SUP_H)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_QUEUE)

    # The certification row still exists; staleness is derived from the clock.
    certs = list_certifications({"agent_id": agent["id"]})
    assert len(certs) == 1
    assert certs[0]["invalidated_at"] is None


def test_certification_freshness_one_second_before_expiry_still_routes():
    """PRD §3.2: "A certification is **standing** at time `t` when its
    `valid_until` is strictly after `t` — a certification expiring exactly at
    `t` is already stale — and its `invalidated_at` is null."

    Design: Difficulty/resource_temporal_overlap/certification_freshness_instant_valid_until_boundary
    """
    contract, _ = _setup_contract_with_queue()
    agent = create_agent()
    course = create_course()
    certify_agent(agent["id"], course["id"], valid_until="2026-09-10T00:00:00Z")
    validate_success(
        api_client.create_queue(create_queue_payload(contract["id"]), OPS_H), 201
    )
    call = register_call(contract["id"], enqueued_at="2026-09-09T23:59:59Z")
    set_clock("2026-09-09T23:59:59Z")
    routed = validate_success(
        api_client.transition_call(call["id"], {"to_status": "ASSIGNED"}, SUP_H)
    )
    assert routed["assigned_via"] == "PRIMARY"
    assert routed["route_depth"] == 1
    assert routed["agent_id"] == agent["id"]


def test_publish_invalidates_cert_unroutes_agent_forces_overflow():
    """PRD §3.6: "every certification whose `program_code` equals the
    article's, and whose grounding course completion's `completed_at` is
    strictly before the article's `effective_at`, is invalidated — its
    `invalidated_at` is set to the current logical-clock reading and its
    `invalidated_by_article_id` to the publishing article's id."
    PRD §3.6: "Agents left holding no remaining standing certification for
    that program are not deactivated, but they become unroutable for it".
    PRD §3.3: "If no eligible queue exists even after the fallback, the route
    attempt fails with `ERR_NO_ELIGIBLE_QUEUE` (HTTP 409)."
    PRD §3.2: "when the course has a `knowledge_article_id` set, completion is
    the retraining path: every certification of that same agent for that same
    program whose `invalidated_by_article_id` equals the linked article is
    re-validated".

    Design: Difficulty/transitive_cascade/publish_invalidates_cert_unroutes_agent_forces_overflow
    """
    contract, _ = _setup_contract_with_queue()
    agent = create_agent()
    course = create_course()
    certify_agent(agent["id"], course["id"], valid_until="2027-01-01T00:00:00Z")

    overflow_q = validate_success(
        api_client.create_queue(create_queue_payload(contract["id"]), OPS_H), 201
    )
    primary_q = validate_success(
        api_client.create_queue(
            create_queue_payload(contract["id"], overflow_queue_id=overflow_q["id"]),
            OPS_H,
        ),
        201,
    )

    article = create_article(effective_at="2026-09-10T00:00:00Z")
    set_clock("2026-09-10T00:00:00Z")
    call = register_call(contract["id"], enqueued_at="2026-09-10T08:00:00Z")

    publish_article(article["id"])

    certs = list_certifications({"agent_id": agent["id"]})
    invalidated = [c for c in certs if c["invalidated_at"] is not None]
    assert len(invalidated) == 1
    assert invalidated[0]["invalidated_by_article_id"] == article["id"]

    resp = api_client.transition_call(call["id"], {"to_status": "ASSIGNED"}, SUP_H)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_QUEUE)
    waiting = get_call(call["id"])
    assert waiting["status"] == "WAITING"
    assert waiting["queue_id"] is None
    assert waiting["route_depth"] == 0

    # Retraining restores routability: completing a course linked to the
    # publishing article re-validates the invalidated certification.
    linked_course = create_course(knowledge_article_id=article["id"])
    certify_agent(agent["id"], linked_course["id"], valid_until="2027-06-01T00:00:00Z")
    routed = validate_success(
        api_client.transition_call(call["id"], {"to_status": "ASSIGNED"}, SUP_H)
    )
    assert routed["assigned_via"] == "PRIMARY"
    assert routed["route_depth"] == 1


def test_publish_invalidation_leaves_agent_employed_and_unrouted_call_waiting():
    """PRD §3.6: "Agents left holding no remaining standing certification for
    that program are not deactivated, but they become unroutable for it: the
    agent selector of §3.3 will no longer match them to that program's
    queues".

    Design: Difficulty/transitive_cascade/publish_invalidates_cert_unroutes_agent_forces_overflow
    """
    contract, _ = _setup_contract_with_queue()
    agent = create_agent()
    course = create_course()
    certify_agent(agent["id"], course["id"], valid_until="2027-01-01T00:00:00Z")
    validate_success(
        api_client.create_queue(create_queue_payload(contract["id"]), OPS_H), 201
    )
    article = create_article(effective_at="2026-09-10T00:00:00Z")
    set_clock("2026-09-10T00:00:00Z")
    call = register_call(contract["id"], enqueued_at="2026-09-10T08:00:00Z")

    publish_article(article["id"])

    agent_after = validate_success(api_client.get_agent(agent["id"], OPS_H))
    assert agent_after["employment_status"] == "ACTIVE"

    resp = api_client.transition_call(call["id"], {"to_status": "ASSIGNED"}, SUP_H)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_QUEUE)
    assert get_call(call["id"])["status"] == "WAITING"


def test_agent_selector_least_busy_then_created_at():
    """PRD §3.3: "the agent is not the `agent_id` of any call currently
    `ASSIGNED` or `ANSWERED`. The ranking prefers the agent with the fewest
    calls `COMPLETED` for program P today — where "today" is the logical date
    in the contract's `measurement_tz` — with ties broken by the agent's
    `created_at` ascending."

    Design: Corner/calculations/agent_selector_least_busy_then_created_at
    """
    contract, _ = _setup_contract_with_queue()
    agent_old = create_agent(full_name="Agent Old")
    agent_new = create_agent(full_name="Agent New")
    course = create_course()
    certify_agent(agent_old["id"], course["id"])
    certify_agent(agent_new["id"], course["id"])
    validate_success(
        api_client.create_queue(create_queue_payload(contract["id"]), OPS_H), 201
    )
    call1 = register_call(contract["id"], enqueued_at="2026-09-05T09:00:00Z")
    call2 = register_call(contract["id"], enqueued_at="2026-09-05T09:01:00Z")

    routed1 = validate_success(
        api_client.transition_call(call1["id"], {"to_status": "ASSIGNED"}, SUP_H)
    )
    assert routed1["agent_id"] == agent_old["id"], (
        "tie 0-0 broken by earliest created_at"
    )
    assert routed1["assigned_via"] == "PRIMARY"
    assert routed1["route_depth"] == 1

    routed2 = validate_success(
        api_client.transition_call(call2["id"], {"to_status": "ASSIGNED"}, SUP_H)
    )
    assert routed2["agent_id"] == agent_new["id"], (
        "agent on an ASSIGNED call is excluded from the pool"
    )
    assert routed2["assigned_via"] == "PRIMARY"
    assert routed2["route_depth"] == 1
