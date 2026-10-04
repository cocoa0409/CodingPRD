"""Work-order intake, triage scoring (hazard base, vulnerable bonus, age-boost
cap, tier bands, outer cap), filtered listing, partner referral attribution,
the block/unblock revision loop, and the typed-incident scheduling gate."""
from test_helpers import (
    ApiErrorId,
    accept_deployment,
    assert_work_order,
    create_operation,
    get_work_order,
    intake_work_order,
    make_deployable_volunteer,
    make_partner_liaison_headers,
    offer_deployment,
    register_partner,
    set_clock,
    setup_assessed_incident,
    setup_in_progress_work_order,
    setup_typed_incident,
    transition_operation,
    transition_work_order,
    triage_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_work_order_invalid_hazard_enum_rejected(api, intake_coordinator_headers):
    """PRD §2.6: "The request body must be well-formed: required fields present, types correct, enum members valid, `planned_end` strictly after `planned_start`, `ends_at` strictly after `starts_at`, and no unknown fields. Violations are rejected with `ERR_VALIDATION` (HTTP 400)."
    PRD §3.6: "The request carries the `requester_name`, the `hazard_kind`, and two prioritization flags that default to false" — with `hazard_kind` drawn from the five hazard kinds of §2.10 (`TREE_REMOVAL`, `MUCK_OUT`, `TARPING`, `DEBRIS`, `STRUCTURAL`).

    Design: Corner/entities/work_order_invalid_enum_rejected
    """
    set_clock()
    incident = setup_assessed_incident(severity=3, affected_households=40, name="Storm A")
    resp = api.create_work_order(
        incident["id"],
        {"requester_name": "Bad Enum", "hazard_kind": "ARSON"},
        intake_coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_work_order_list_filters_and_pagination_envelope(api, intake_coordinator_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0."
    PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §4: "List work orders, filterable by incident, operation, partner, status, and priority tier".

    Design: Corner/endpoints/work_orders_filtered_list_and_pagination
    """
    set_clock()
    incident = setup_assessed_incident(severity=3, affected_households=40, name="Storm A")
    wo1 = intake_work_order(
        incident["id"], requester_name="Owner One", hazard_kind="TREE_REMOVAL",
        vulnerable_resident=True,
    )
    intake_work_order(
        incident["id"], requester_name="Owner Two", hazard_kind="DEBRIS",
        vulnerable_resident=False,
    )
    set_clock("2026-09-03T00:00:00Z")
    triage_work_order(wo1)
    items, meta = validate_paginated(
        api.list_work_orders(intake_coordinator_headers, params={"status": "TRIAGED"})
    )
    assert len(items) == 1
    assert items[0]["id"] == wo1["id"]
    assert meta["total_count"] == 1
    items, meta = validate_paginated(
        api.list_work_orders(intake_coordinator_headers, params={"incident_id": incident["id"]})
    )
    assert len(items) == 2
    assert meta["total_count"] == 2
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False


def test_priority_age_boost_capped_at_twenty_points(api):
    """PRD §3.6: "Age then adds its own boost: the number of whole 24-hour days between the work order's `created_at` and the triage moment, multiplied by 5 points per day, capped at 20."
    PRD §3.6: "The score is the sum of base, bonus, and age boost, capped at 100. The tier reads off the score: at least 80 is `P1`, at least 50 but below 80 is `P2`, and anything lower is `P3`."

    Design: Corner/calculations/priority_age_boost_capped_at_twenty
    """
    set_clock()
    incident = setup_assessed_incident(severity=2, affected_households=15, name="Storm A")
    work_order = intake_work_order(
        incident["id"], requester_name="Patient Owner", hazard_kind="DEBRIS",
        vulnerable_resident=False,
    )
    set_clock("2026-09-11T00:00:00Z")  # exactly 10 full days of waiting
    triaged = triage_work_order(work_order)
    assert_work_order(triaged)
    assert triaged["status"] == "TRIAGED"
    # DEBRIS base 20 + no bonus + min(20, 10 days x 5) = 40; uncapped math would give 70.
    assert triaged["priority_score"] == 40
    assert triaged["priority_tier"] == "P3"


def test_partner_referral_attribution_enforced(api):
    """PRD §2.1: "When `X-User-Role` is `PartnerLiaison`, `X-User-ID` is the `id` of the acting `PartnerAgency`; a liaison creating a work order must set `source_partner_id` equal to their own `X-User-ID`, and a mismatch is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.6: "a `PartnerLiaison` refers a request on behalf of their agency and must set `source_partner_id` to their own `PartnerAgency` id — a direct intake leaves `source_partner_id` null, and a liaison quoting another agency's id fails authorization."

    Design: Corner/endpoints/work_order_referral_partner_attribution
    """
    set_clock()
    p1 = register_partner(name="County EM", kind="EMERGENCY_MANAGEMENT",
                          contact_email="em@county.gov")
    p2 = register_partner(name="Recovery Group", kind="LTRG", contact_email="ltrg@x.org")
    incident = setup_assessed_incident(severity=3, affected_households=40, name="Storm A")
    liaison1 = make_partner_liaison_headers(p1["id"])
    resp = api.create_work_order(
        incident["id"],
        {
            "requester_name": "Referred Owner",
            "hazard_kind": "MUCK_OUT",
            "vulnerable_resident": True,
            "municipality_sourced": True,
            "source_partner_id": p1["id"],
        },
        liaison1,
    )
    work_order = validate_success(resp, 201)
    assert_work_order(work_order)
    assert work_order["source_partner_id"] == p1["id"]
    assert work_order["status"] == "INTAKE"
    resp = api.create_work_order(
        incident["id"],
        {"requester_name": "Misattributed", "hazard_kind": "DEBRIS",
         "source_partner_id": p2["id"]},
        liaison1,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    items, meta = validate_paginated(
        api.list_work_orders(liaison1, params={"source_partner_id": p1["id"]})
    )
    assert meta["total_count"] == 1
    assert items[0]["id"] == work_order["id"]


def _setup_two_tree_removal_orders_at_assessed():
    """Incident ASSESSED; two TREE_REMOVAL work orders (one vulnerable, one
    not) created at the default clock; clock advanced exactly 48 hours."""
    set_clock()
    incident = setup_assessed_incident(name="Hurricane Helena")
    wo_vulnerable = intake_work_order(
        incident["id"], requester_name="Elderly Homeowner", hazard_kind="TREE_REMOVAL",
        vulnerable_resident=True, municipality_sourced=False,
    )
    wo_plain = intake_work_order(
        incident["id"], requester_name="Fit Homeowner", hazard_kind="TREE_REMOVAL",
        vulnerable_resident=False, municipality_sourced=False,
    )
    set_clock("2026-09-03T00:00:00Z")
    return wo_vulnerable, wo_plain


def test_priority_vulnerable_order_hits_score_cap(api):
    """PRD §3.6: "The score starts from a per-hazard base — 60 for `STRUCTURAL`, 50 for `TREE_REMOVAL`, 35 for `TARPING`, 30 for `MUCK_OUT`, and 20 for `DEBRIS`. A `vulnerable_resident` household adds a bonus of 40. Age then adds its own boost: the number of whole 24-hour days between the work order's `created_at` and the triage moment, multiplied by 5 points per day, capped at 20. The score is the sum of base, bonus, and age boost, capped at 100."
    PRD §3.6: "The tier reads off the score: at least 80 is `P1`, at least 50 but below 80 is `P2`, and anything lower is `P3`."

    Design: Difficulty/combinatorial_formula/priority_score_conditional_cap_math
    """
    wo_vulnerable, _wo_plain = _setup_two_tree_removal_orders_at_assessed()
    triaged = triage_work_order(wo_vulnerable)
    assert triaged["status"] == "TRIAGED"
    # 50 + 40 + min(20, floor(48h/24) x 5 = 10) = 100, held by the outer cap.
    assert triaged["priority_score"] == 100
    assert triaged["priority_tier"] == "P1"


def test_priority_non_vulnerable_twin_lands_p2(api):
    """PRD §3.6: "A `vulnerable_resident` household adds a bonus of 40." (its conditional branch) and "The tier reads off the score: at least 80 is `P1`, at least 50 but below 80 is `P2`, and anything lower is `P3`."

    Design: Difficulty/combinatorial_formula/priority_score_conditional_cap_math
    """
    _wo_vulnerable, wo_plain = _setup_two_tree_removal_orders_at_assessed()
    triaged = triage_work_order(wo_plain)
    assert triaged["status"] == "TRIAGED"
    # 50 + 0 + 10 = 60 -> P2 band.
    assert triaged["priority_score"] == 60
    assert triaged["priority_tier"] == "P2"


def test_block_sets_reason_and_unblock_clears_it(api, operations_lead_headers):
    """PRD §3.6: "The lead may block an `IN_PROGRESS` order by supplying a non-empty `blocked_reason`, and the revocation cascade of §3.1 can block it automatically with `blocked_reason` `CAPABILITY_LOST`; `blocked_reason` is null at all other times."
    PRD §3.6: "Unblocking returns `BLOCKED` to `SCHEDULED`, clears `blocked_reason` back to null, and re-runs the capability check: if the hazard maps to a capability, the operation's `capability_gap` must again show no positive entry for it, else `ERR_CAPABILITY_GAP`."

    Design: Difficulty/non_linear_state_machine/work_order_block_unblock_cycle
    """
    bundle = setup_in_progress_work_order()
    work_order_id = bundle["wo1"]["id"]
    blocked = transition_work_order(
        work_order_id, operations_lead_headers,
        status="BLOCKED", blocked_reason="lightning hold",
    )
    assert blocked["status"] == "BLOCKED"
    assert blocked["blocked_reason"] == "lightning hold"
    unblocked = transition_work_order(work_order_id, operations_lead_headers, status="SCHEDULED")
    assert unblocked["status"] == "SCHEDULED"
    assert unblocked["blocked_reason"] is None


def test_unblocked_order_restarts_to_in_progress(api, operations_lead_headers):
    """PRD §3.6: "From `SCHEDULED`, an `OperationsLead` starts the work — moving it to `IN_PROGRESS` — only while the operation is `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/work_order_block_unblock_cycle
    """
    bundle = setup_in_progress_work_order()
    work_order_id = bundle["wo1"]["id"]
    transition_work_order(
        work_order_id, operations_lead_headers,
        status="BLOCKED", blocked_reason="lightning hold",
    )
    transition_work_order(work_order_id, operations_lead_headers, status="SCHEDULED")
    restarted = transition_work_order(work_order_id, operations_lead_headers, status="IN_PROGRESS")
    assert restarted["status"] == "IN_PROGRESS"


def _setup_mustered_op_under_typed_incident():
    """Two DEPLOYABLE CHAINSAW volunteers; TYPED incident; hazard-aligned op
    driven DRAFT -> OPEN -> (two accepted offers) -> MUSTERED."""
    set_clock()
    v1 = make_deployable_volunteer(full_name="Ada Voss", email="ada@x.org")
    v2 = make_deployable_volunteer(full_name="Bo Karr", email="bo@x.org")
    incident = setup_typed_incident(name="Storm B")
    operation = create_operation(incident["id"], title="B Tree Ops")
    operation = transition_operation(operation["id"], status="OPEN")
    d1 = offer_deployment(operation["id"], v1["id"])
    accept_deployment(d1["id"], v1["id"])
    d2 = offer_deployment(operation["id"], v2["id"])
    accept_deployment(d2["id"], v2["id"])
    operation = transition_operation(operation["id"], status="MUSTERED")
    return incident, operation


def test_schedule_rejected_when_incident_not_typed(api, intake_coordinator_headers):
    """PRD §3.6: "Scheduling binds a `TRIAGED` work order to an operation through `operation_id`, and it is the most gated step on the work-order path. The incident must be `TYPED`, else `ERR_INCIDENT_NOT_TYPED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/work_order_schedule_requires_typed_incident
    """
    _incident_b, op_b = _setup_mustered_op_under_typed_incident()
    incident_a = setup_assessed_incident(name="Storm A", severity=3, affected_households=40)
    work_order = intake_work_order(
        incident_a["id"], requester_name="Homeowner A", hazard_kind="TREE_REMOVAL",
        vulnerable_resident=False,
    )
    work_order = triage_work_order(work_order)
    resp = api.patch_work_order(
        work_order["id"],
        {"status": "SCHEDULED", "operation_id": op_b["id"]},
        intake_coordinator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_TYPED)
    after = get_work_order(work_order["id"])
    assert after["status"] == "TRIAGED"
    assert after["operation_id"] is None


def test_schedule_succeeds_once_incident_typed(api, intake_coordinator_headers):
    """PRD §3.6: "The incident must be `TYPED`, else `ERR_INCIDENT_NOT_TYPED` (HTTP 409). The target operation must be `MUSTERED` or `ACTIVE`, else `ERR_OPERATION_NOT_OPEN` (HTTP 409). The operation's `hazard_focus` must equal the work order's `hazard_kind`, else `ERR_HAZARD_MISMATCH` (HTTP 422)." and "A successful scheduling records the binding in `operation_id`."

    Design: Difficulty/cross_entity_state_dependency/work_order_schedule_requires_typed_incident
    """
    incident, operation = _setup_mustered_op_under_typed_incident()
    work_order = intake_work_order(
        incident["id"], requester_name="Homeowner B", hazard_kind="TREE_REMOVAL",
        vulnerable_resident=False,
    )
    work_order = triage_work_order(work_order)
    scheduled = transition_work_order(
        work_order["id"], intake_coordinator_headers,
        status="SCHEDULED", operation_id=operation["id"],
    )
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["operation_id"] == operation["id"]
