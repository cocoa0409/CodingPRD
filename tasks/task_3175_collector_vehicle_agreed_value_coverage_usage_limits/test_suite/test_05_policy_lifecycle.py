"""Policy lifecycle: review cycle, activation gates, period overlap."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_listed_driver,
    create_member,
    create_policy_for,
    create_published_guide,
    create_guide_tool_valuation,
    propose_and_approve,
    get_vehicle,
    setup_active_policy,
    setup_approved_guide_valuation,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
UW = TEST_USERS["underwriter_headers"]


def test_policy_review_cycle_loop(api):
    """PRD §3.6: "An underwriter may pull it into `UNDER_REVIEW` (or it
    arrives there automatically when its pinned valuation goes stale); while
    under review, usage-event creation and claim settlement are blocked.
    Resolving the review back to `ACTIVE` requires the pinned valuation to be
    `APPROVED` and not stale — otherwise `ERR_VALUATION_STALE` — which in
    practice means a fresh valuation has been approved and re-pinned first."

    Design: Difficulty/non_linear_state_machine/policy_review_cycle_loop
    """
    ctx = setup_active_policy()
    pid = ctx["policy"]["id"]
    reviewed = validate_success(api.begin_review(pid, UW))
    assert reviewed["status"] == "UNDER_REVIEW"
    resolved = validate_success(api.resolve_review(pid, UW))
    assert resolved["status"] == "ACTIVE", (
        "UNDER_REVIEW -> ACTIVE closes the review cycle"
    )


def test_policy_suspend_resume_cycle(api):
    """PRD §3.6: "Suspension and resumption follow the same staleness gate on
    resume."

    Design: Difficulty/non_linear_state_machine/policy_review_cycle_loop
    """
    ctx = setup_active_policy()
    pid = ctx["policy"]["id"]
    suspended = validate_success(api.suspend_policy(pid, UW))
    assert suspended["status"] == "SUSPENDED"
    resumed = validate_success(api.resume_policy(pid, UW))
    assert resumed["status"] == "ACTIVE", (
        "SUSPENDED -> ACTIVE closes the second cycle"
    )


def test_policy_activation_gated_on_vehicle_eligibility(api):
    """PRD §3.6: "Activation is where the platform's underwriting gates
    converge, evaluated in order: the vehicle must be `ELIGIBLE`
    (`ERR_VEHICLE_INELIGIBLE`)".
    PRD §3.2: "The age test depends on class: an `ANTIQUE` must be at least 45
    years old, a `CLASSIC` at least 25, a `MODERN_COLLECTIBLE` at least 15,
    and an `EXOTIC` at least 10."

    Design: Difficulty/cross_entity_state_dependency/policy_activation_gated_on_vehicle_eligibility
    """
    member, m_headers = create_member(full_name="Meg", email="meg@x.com")
    # 2002 CLASSIC at the 2026-09-01 logical clock: age 24 < 25 -> INELIGIBLE.
    ctx = setup_approved_guide_valuation(
        (member, m_headers), base_value_cents=3_000_000, proposed=3_000_000,
        year=2002, make="Porsche", model="911", document=False,
    )
    from test_helpers import evaluate_vehicle
    evaluated = evaluate_vehicle(ctx["vehicle"]["id"])
    assert evaluated["eligibility_status"] == "INELIGIBLE"
    policy = create_policy_for(member, ctx["vehicle"], ctx["valuation"])
    add_listed_driver(policy["id"], m_headers)
    resp = api.activate_policy(policy["id"], UW)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_INELIGIBLE)


def test_policy_activation_eligibility_gate_precedes_other_gates(api):
    """PRD §3.6: "Activation is where the platform's underwriting gates
    converge, evaluated in order: the vehicle must be `ELIGIBLE`
    (`ERR_VEHICLE_INELIGIBLE`); its documentation must be `COMPLETE`
    (`ERR_DOCUMENTATION_INCOMPLETE`)".

    Design: Difficulty/cross_entity_state_dependency/policy_activation_gated_on_vehicle_eligibility
    """
    member, m_headers = create_member(full_name="Meg2", email="meg2@x.com")
    # Vehicle is BOTH ineligible (age) and undocumented: eligibility gate fires.
    ctx = setup_approved_guide_valuation(
        (member, m_headers), base_value_cents=3_000_000, proposed=3_000_000,
        year=2002, make="Porsche", model="911", document=False,
    )
    from test_helpers import evaluate_vehicle
    assert evaluate_vehicle(ctx["vehicle"]["id"])["eligibility_status"] == "INELIGIBLE"
    policy = create_policy_for(member, ctx["vehicle"], ctx["valuation"])
    add_listed_driver(policy["id"], m_headers)
    resp = api.activate_policy(policy["id"], UW)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_INELIGIBLE)


def test_activation_without_daily_driver_rejected(api):
    """PRD §3.6: "the member must own or lease a separate daily driver
    (`ERR_NO_DAILY_DRIVER`)".

    Design: Corner/validations/activation_without_daily_driver_rejected
    """
    member, m_headers = create_member(
        full_name="Hank", email="hank@x.com", has_daily_driver=False
    )
    vctx = setup_approved_guide_valuation(
        (member, m_headers), base_value_cents=3_000_000, proposed=3_000_000,
    )
    policy = create_policy_for(member, vctx["vehicle"], vctx["valuation"])
    add_listed_driver(policy["id"], m_headers)
    resp = api.activate_policy(policy["id"], UW)
    validate_error(resp, ApiErrorId.ERR_NO_DAILY_DRIVER)


def test_error_documentation_incomplete_on_activate(api):
    """PRD §3.6: "its documentation must be `COMPLETE`
    (`ERR_DOCUMENTATION_INCOMPLETE`)".
    PRD §3.3: "`documentation_status` becomes `COMPLETE` exactly when all
    eight required types are accepted, remaining `INCOMPLETE` otherwise."

    Design: Corner/errors/error_documentation_incomplete_on_activate
    """
    from test_helpers import (
        REQUIRED_PHOTO_TYPES,
        accept_photos,
        create_vehicle,
        evaluate_vehicle,
        submit_all_photos,
    )

    member, m_headers = create_member(full_name="Ori", email="ori@x.com")
    vehicle = create_vehicle(member, vin="VIN133")
    photos = submit_all_photos(vehicle["id"], m_headers)
    # Accept only 7 of 8 types: documentation stays INCOMPLETE.
    accept_photos(vehicle["id"], photos, only_types=set(REQUIRED_PHOTO_TYPES) - {"VIN_PLATE"})
    evaluate_vehicle(vehicle["id"])
    create_published_guide()
    valuation = propose_and_approve(
        create_guide_tool_valuation(vehicle["id"], 3_000_000)["id"]
    )
    policy = create_policy_for(member, get_vehicle(vehicle["id"]), valuation)
    add_listed_driver(policy["id"], m_headers)
    assert policy["status"] == "PENDING_DOCUMENTS"
    resp = api.activate_policy(policy["id"], UW)
    validate_error(resp, ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE)


def test_policy_period_half_open_adjacency_allowed(api):
    """PRD §3.6: "A vehicle may not sit under two non-cancelled policies whose
    half-open windows intersect; adjacency — one policy's `period_end` exactly
    equal to the other's `period_start` — is allowed, but true overlap is
    rejected with `ERR_POLICY_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/policy_period_half_open_overlap
    """
    member, m_headers = create_member(full_name="Ola", email="ola@x.com")
    ctx = setup_approved_guide_valuation(
        (member, m_headers), base_value_cents=3_000_000, proposed=3_000_000,
        document=False,
    )
    p1 = create_policy_for(member, ctx["vehicle"], ctx["valuation"])
    assert p1["status"] in ("QUOTED", "PENDING_DOCUMENTS")
    # A second APPROVED valuation for the second policy.
    val2 = propose_and_approve(
        create_guide_tool_valuation(ctx["vehicle"]["id"], 3_000_000)["id"]
    )
    # Adjacent window [2027-09-01, 2028-09-01) touches p1's period_end.
    adjacent = api.create_policy(
        {
            "member_id": member["id"],
            "vehicle_id": ctx["vehicle"]["id"],
            "valuation_id": val2["id"],
            "usage_tier": "REGULAR",
            "period_start": "2027-09-01T00:00:00Z",
            "period_end": "2028-09-01T00:00:00Z",
        },
        UW,
    )
    validate_success(adjacent, expected_status=201)


def test_policy_period_half_open_overlap_rejected(api):
    """PRD §3.6: "A vehicle may not sit under two non-cancelled policies whose
    half-open windows intersect; adjacency — one policy's `period_end` exactly
    equal to the other's `period_start` — is allowed, but true overlap is
    rejected with `ERR_POLICY_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/policy_period_half_open_overlap
    """
    member, m_headers = create_member(full_name="Ola2", email="ola2@x.com")
    ctx = setup_approved_guide_valuation(
        (member, m_headers), base_value_cents=3_000_000, proposed=3_000_000,
        document=False,
    )
    create_policy_for(member, ctx["vehicle"], ctx["valuation"])
    val2 = propose_and_approve(
        create_guide_tool_valuation(ctx["vehicle"]["id"], 3_000_000)["id"]
    )
    # Starts one day BEFORE the first policy's period_end: true overlap.
    resp = api.create_policy(
        {
            "member_id": member["id"],
            "vehicle_id": ctx["vehicle"]["id"],
            "valuation_id": val2["id"],
            "usage_tier": "REGULAR",
            "period_start": "2027-08-31T00:00:00Z",
            "period_end": "2028-08-31T00:00:00Z",
        },
        UW,
    )
    validate_error(resp, ApiErrorId.ERR_POLICY_PERIOD_OVERLAP)
