"""Farm recruitment, capacity arithmetic, activation gate, certification derivation."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_farm,
    complete_audit,
    create_active_farm,
    create_contract,
    create_farm,
    get_farm,
    make_auditor_headers,
    remove_farm,
    schedule_audit,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

NM = TEST_USERS["network_manager_headers"]


def test_farm_create_assigns_defaults_and_computed_fields(api):
    """PRD §3.1: "The new farm enters `ONBOARDING` with `certification_status`
    `CERTIFICATION_PENDING` (no audit has passed yet, so `last_passed_audit_at`
    is null), its `removal_reason` is null, and the server immediately computes
    its `effective_bird_capacity` per §2.8."
    PRD §2.8: "the server computes the farm's `effective_bird_capacity` as the
    smallest of three component caps: the pasture cap is `pasture_sqft` divided
    by 108.0, floored to a whole bird; the barn cap is `barn_sqft` divided by
    1.2, floored to a whole bird; and the nest cap is `nest_box_count`
    multiplied by 5."

    Design: Corner/entities/farm_create_assigns_defaults_and_computed_fields
    """
    resp = api.create_farm(
        {
            "name": "Default Check Farm",
            "region": "IA",
            "pasture_sqft": 21600,
            "barn_sqft": 180,
            "nest_box_count": 30,
            "declared_bird_count": 140,
        },
        NM,
    )
    farm = validate_success(resp, 201)
    assert_farm(farm)
    assert farm["status"] == "ONBOARDING"
    assert farm["certification_status"] == "CERTIFICATION_PENDING"
    assert farm["effective_bird_capacity"] == 150, (
        f"expected min(floor(21600/108.0), floor(180/1.2), 30*5) == 150, "
        f"got {farm['effective_bird_capacity']}"
    )
    assert farm["version"] == 1
    assert farm["last_passed_audit_at"] is None


def test_farm_create_missing_required_field_returns_400(api):
    """PRD §3.1: "Every one of these inputs is required; `pasture_sqft`,
    `barn_sqft`, and `declared_bird_count` must each be greater than zero,
    `nest_box_count` must be at least zero, and `name` and `region` must be
    non-empty — any violation is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/farm_create_missing_required_field_returns_400
    """
    resp = api.create_farm(
        {
            "name": "Missing Pasture Farm",
            "region": "IA",
            "barn_sqft": 180,
            "nest_box_count": 30,
            "declared_bird_count": 140,
        },
        NM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_farm_system_field_input_ignored(api):
    """PRD §2.4: "The `id` is a server-minted UUID carrying no type prefix."
    PRD §2.4: "The `version` field is an integer that starts on creation and
    increments by one with every mutation of the resource"

    Design: Corner/entities/farm_system_field_input_ignored
    """
    forged_id = "00000000-0000-0000-0000-000000000000"
    resp = api.create_farm(
        {
            "id": forged_id,
            "version": 99,
            "name": "Forged Fields Farm",
            "region": "IA",
            "pasture_sqft": 21600,
            "barn_sqft": 180,
            "nest_box_count": 30,
            "declared_bird_count": 140,
        },
        NM,
    )
    farm = validate_success(resp, 201)
    assert farm["id"] != forged_id, "server must mint its own id, ignoring the client's"
    assert farm["version"] == 1, "client-supplied version must be ignored"


def test_capacity_min_selects_nest_box_binding(api):
    """PRD §2.8: "the server computes the farm's `effective_bird_capacity` as
    the smallest of three component caps: the pasture cap is `pasture_sqft`
    divided by 108.0, floored to a whole bird; the barn cap is `barn_sqft`
    divided by 1.2, floored to a whole bird; and the nest cap is
    `nest_box_count` multiplied by 5."

    Design: Corner/calculations/capacity_min_selects_nest_box_binding
    """
    resp = api.create_farm(
        {
            "name": "Nest Bound Farm",
            "region": "MO",
            "pasture_sqft": 108000,
            "barn_sqft": 1200,
            "nest_box_count": 10,
            "declared_bird_count": 50,
        },
        NM,
    )
    farm = validate_success(resp, 201)
    assert farm["effective_bird_capacity"] == 50, (
        f"expected nest-box term to bind: min(1000, 1000, 50) == 50, "
        f"got {farm['effective_bird_capacity']}"
    )


def test_farm_activate_twice_second_returns_invalid_state(api):
    """PRD §3.1: "the server requires, first, that the farm is actually in
    `ONBOARDING` (any other state is `ERR_INVALID_STATE`, or `ERR_FARM_TERMINAL`
    when `REMOVED`)"

    Design: Corner/state_machines/farm_activate_twice_second_returns_invalid_state
    """
    bundle = create_active_farm(name="Double Activate Farm")
    farm_id = bundle["farm"]["id"]
    assert bundle["farm"]["status"] == "ACTIVE"

    resp = api.activate_farm(farm_id, NM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_farm_patch_while_active_returns_invalid_state(api):
    """PRD §3.1: "Amendments attempted while the farm is `ACTIVE` or `SUSPENDED`
    are rejected with `ERR_INVALID_STATE`"

    Design: Corner/state_machines/farm_patch_while_active_returns_invalid_state
    """
    bundle = create_active_farm(name="Patch Lock Farm")
    farm_id = bundle["farm"]["id"]

    resp = api.patch_farm(farm_id, {"pasture_sqft": 30000}, NM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_farm_removed_is_terminal_for_mutations(api):
    """PRD §3.1: "amendments — indeed any mutation at all, other than reads —
    attempted against a `REMOVED` farm are rejected with `ERR_FARM_TERMINAL`
    (HTTP 409)."
    PRD §3.4: "First, the farm's `status` becomes `REMOVED`, its
    `certification_status` becomes `DECERTIFIED`, the `removal_reason` is set,
    and the farm's `version` increments by one."

    Design: Corner/state_machines/farm_removed_is_terminal_for_mutations
    """
    farm = create_farm(name="Doomed Farm")
    farm_id = farm["id"]
    removed = validate_success(api.remove_farm(farm_id, {"reason": "withdrew from program"}, NM), 200)
    assert removed["status"] == "REMOVED"

    resp_patch = api.patch_farm(farm_id, {"declared_bird_count": 100}, NM)
    validate_error(resp_patch, ApiErrorId.ERR_FARM_TERMINAL, 409)

    resp_activate = api.activate_farm(farm_id, NM)
    validate_error(resp_activate, ApiErrorId.ERR_FARM_TERMINAL, 409)

    reread = validate_success(api.get_farm(farm_id, NM), 200)
    assert reread["status"] == "REMOVED"
    assert reread["certification_status"] == "DECERTIFIED"


def test_activate_without_prereqs_reports_certification_first(api):
    """PRD §3.1: "Second, the farm's `certification_status` must be `CERTIFIED`
    — meaning at least one audit has passed — otherwise the request fails with
    `ERR_CERTIFICATION_REQUIRED` (HTTP 422)."
    PRD §3.1: "These checks run in the global precedence of §2.11 —
    certification before contract coverage before capacity"

    Design: Corner/validations/activate_without_prereqs_reports_certification_first
    """
    farm = create_farm(name="Unready Farm")
    resp = api.activate_farm(farm["id"], NM)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_REQUIRED, 422)


def test_derived_certification_recomputed_on_pass_and_removal(api):
    """PRD §2.7: "If the farm's `status` is `REMOVED`, the `certification_status`
    is `DECERTIFIED`. Otherwise, if the farm has never passed an audit —
    `last_passed_audit_at` is null — it is `CERTIFICATION_PENDING`."
    PRD §3.2: "the server stamps `auditor_user_id` with the caller's `X-User-ID`
    and `completed_at` with the current instant, then refreshes the farm by
    setting `last_passed_audit_at` to the completion instant, re-deriving
    `certification_status` to `CERTIFIED` per §2.7"

    Design: Corner/cross_cutting_layers/derived_certification_recomputed_on_pass_and_removal
    """
    farm = create_farm(name="Derived Cert Farm")
    farm_id = farm["id"]
    assert farm["certification_status"] == "CERTIFICATION_PENDING"

    audit = schedule_audit(farm_id)
    set_clock("2026-09-03T09:00:00Z")
    complete_audit(audit["id"], "PASSED")

    passed_farm = get_farm(farm_id)
    assert passed_farm["certification_status"] == "CERTIFIED"
    assert passed_farm["last_passed_audit_at"] is not None
    assert passed_farm["last_passed_audit_at"].startswith("2026-09-03T09:00:00"), (
        f"last pass stamp must equal the completion instant, "
        f"got {passed_farm['last_passed_audit_at']}"
    )

    remove_farm(farm_id, reason="program withdrawal")
    removed_farm = get_farm(farm_id)
    assert removed_farm["certification_status"] == "DECERTIFIED"


def test_cert_lapse_anniversary_boundary(api):
    """PRD §2.7: "Otherwise, if the current logical instant is strictly later
    than `last_passed_audit_at` plus 365 days, the certification has lapsed and
    the value is `CERT_LAPSED`; at the exact instant of `last_passed_audit_at`
    plus 365 days the farm is still `CERTIFIED`, because lapse requires strictly
    greater."

    Design: Corner/calculations/cert_lapse_anniversary_boundary
    """
    farm = create_farm(name="Anniversary Farm")
    farm_id = farm["id"]
    audit = schedule_audit(farm_id)
    set_clock("2026-09-03T09:00:00Z")
    complete_audit(audit["id"], "PASSED")

    # Exactly last_passed + 365 days: still CERTIFIED.
    set_clock("2027-09-03T09:00:00Z")
    at_anniversary = get_farm(farm_id)
    assert at_anniversary["certification_status"] == "CERTIFIED", (
        f"at exactly the 365-day anniversary the farm must still be CERTIFIED, "
        f"got {at_anniversary['certification_status']}"
    )

    # One second later: CERT_LAPSED.
    set_clock("2027-09-03T09:00:01Z")
    after_anniversary = get_farm(farm_id)
    assert after_anniversary["certification_status"] == "CERT_LAPSED"


def test_bird_capacity_over_declared_rejected(api):
    """PRD §3.1: "Fourth, the `declared_bird_count` must not exceed the farm's
    current `effective_bird_capacity`, with equality permitted; an over-declared
    flock fails with `ERR_BIRD_CAPACITY_INSUFFICIENT` (HTTP 422)."
    PRD §2.8: "the barn cap is `barn_sqft` divided by 1.2, floored to a whole
    bird"

    Design: Difficulty/boundary_precision_check/bird_capacity_exact_equality_boundary
    """
    farm = create_farm(
        name="Tight Barn Farm",
        region="MN",
        pasture_sqft=10800,
        barn_sqft=90,
        nest_box_count=20,
        declared_bird_count=76,
    )
    farm_id = farm["id"]
    audit = schedule_audit(farm_id)
    set_clock("2026-09-03T09:00:00Z")
    complete_audit(audit["id"], "PASSED")
    create_contract(farm_id)

    reread = get_farm(farm_id)
    assert reread["effective_bird_capacity"] == 75, (
        f"barn binds: min(floor(10800/108.0)=100, floor(90/1.2)=75, 20*5=100) "
        f"== 75, got {reread['effective_bird_capacity']}"
    )

    resp = api.activate_farm(farm_id, NM)
    validate_error(resp, ApiErrorId.ERR_BIRD_CAPACITY_INSUFFICIENT, 422)


def test_bird_capacity_exact_equality_accepted(api):
    """PRD §3.1: "Fourth, the `declared_bird_count` must not exceed the farm's
    current `effective_bird_capacity`, with equality permitted; an over-declared
    flock fails with `ERR_BIRD_CAPACITY_INSUFFICIENT` (HTTP 422)."
    PRD §2.8: "Activation of a farm requires its `declared_bird_count` to be at
    most this capacity, with equality permitted."

    Design: Difficulty/boundary_precision_check/bird_capacity_exact_equality_boundary
    """
    farm = create_farm(
        name="Tight Barn Farm",
        region="MN",
        pasture_sqft=10800,
        barn_sqft=90,
        nest_box_count=20,
        declared_bird_count=76,
    )
    farm_id = farm["id"]
    audit = schedule_audit(farm_id)
    set_clock("2026-09-03T09:00:00Z")
    complete_audit(audit["id"], "PASSED")
    create_contract(farm_id)

    # Correct the declaration down to exactly the capacity (allowed while ONBOARDING).
    patched = validate_success(api.patch_farm(farm_id, {"declared_bird_count": 75}, NM), 200)
    assert patched["effective_bird_capacity"] == 75

    activated = validate_success(api.activate_farm(farm_id, NM), 200)
    assert activated["status"] == "ACTIVE", "declared 75 == capacity 75 must activate (inclusive)"
