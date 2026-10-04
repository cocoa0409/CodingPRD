"""Learner registration defaults, course seeding and input validation."""
from test_helpers import (
    NON_EXISTENT_UUID, api_client, append_lesson_node, create_course_unit,
    get_success_data, make_learner_headers, register_learner,
    register_learner_headers, validate_error,
)


def test_registration_leaves_every_derived_counter_at_its_initial_value(api):
    """PRD §3.5: "The learner's `gems_balance` starts at zero"
    PRD §3.4: "A learner starts with ten units, the pool is capped at thirty"
    PRD §3.4: "The available allowance is the daily grant of five hearts minus that
    count, floored at zero."
    PRD §3.2: "a `Learner`'s `leaf_count` is derived from the crown states of the
    nodes that learner holds"
    PRD §3.4: "The learner's `xp_total` is recomputed from these awards"

    Design: Corner/entities/creation_anonymous_role_leaves_admin_only_learner_creation
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")

    assert learner["xp_total"] == 0
    assert learner["gems_balance"] == 0
    assert learner["leaf_count"] == 0
    assert learner["hearts_available"] == 5
    assert learner["energy_units"] == 10


def test_registration_mints_the_streak_row_and_the_free_subscription(api):
    """PRD §3.5: "the server also mints that learner's `StreakState` row in
    `EVALUATING` and a `Subscription` row in `FREE` status with `plan_code` `FREE`,
    `seats_total` 1 and `seats_used` 0"
    PRD §3.3: "Registration mints this row in `EVALUATING` with `focus_date` set to
    the learner's local calendar date, `current_length` at 0, and
    `repair_cost_gems` at 0."

    Design: Corner/entities/creation_anonymous_role_leaves_admin_only_learner_creation
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")
    headers = make_learner_headers(learner["id"])

    streak = get_success_data(api_client.list_streak_states(
        headers, {"learner_id": learner["id"]}
    ))[0]
    assert streak["status"] == "EVALUATING"
    assert streak["current_length"] == 0
    assert streak["repair_cost_gems"] == 0

    subscription = get_success_data(api_client.list_subscriptions(
        headers, {"learner_id": learner["id"]}
    ))[0]
    assert subscription["status"] == "FREE"
    assert subscription["plan_code"] == "FREE"
    assert subscription["seats_total"] == 1
    assert subscription["seats_used"] == 0
    assert subscription["limits_removed"] is False


def test_unknown_identifiers_report_their_own_not_found_error(api, admin_headers):
    """PRD §2.10: "the learner named by `X-User-ID` or by a `learner_id` in the body
    or query must exist (`ERR_LEARNER_NOT_FOUND`, 404); then the lesson node named
    in a path (`ERR_LESSON_NODE_NOT_FOUND`, 404)"
    PRD §2.4: "`id` is a server-minted identifier formatted as a UUID"

    Design: Corner/entities/not_found_learner_profile_read_returns_404
    """
    validate_error(
        api_client.get_learner(NON_EXISTENT_UUID, admin_headers),
        "ERR_LEARNER_NOT_FOUND",
    )
    validate_error(
        api_client.get_lesson_node(NON_EXISTENT_UUID, admin_headers),
        "ERR_LESSON_NODE_NOT_FOUND",
    )


def test_role_outside_the_endpoint_roles_cannot_patch_a_profile(api, anonymous_headers):
    """PRD §2.1: "The acting role must be one of those listed for the operation; a
    request whose role is not permitted, or in which one learner acts on another
    learner's resource, is refused with `ERR_UNAUTHORIZED` at HTTP 403."
    PRD §2.1: "`Anonymous` exclusively owns learner registration"

    Design: Corner/entities/computed_field_input_ignored_on_learner_patch_invalid_role
    """
    learner = register_learner(display_name="Ada", local_date_offset_days=0,
                               program_tier="FREE")

    validate_error(
        api_client.patch_learner(
            learner["id"],
            {"expected_learner_version": learner["version"],
             "program_tier": "CERTIFICATION_ELITE"},
            anonymous_headers,
        ),
        "ERR_UNAUTHORIZED",
    )

    assert get_success_data(api_client.get_learner(
        learner["id"], make_learner_headers(learner["id"])
    ))["program_tier"] == "FREE"


def test_practice_against_a_locked_node_is_refused_and_costs_nothing(api):
    """PRD §3.1: "A practice attempt submitted against a node that has not opened,
    or whose prerequisite is still unmet, is refused — the first with
    `ERR_NODE_LOCKED`"
    PRD §3.4: "One unit is spent only when an attempt is actually accepted"

    Design: Corner/state_machines/practice_on_locked_node_returns_node_locked
    """
    learner, headers = register_learner_headers(display_name="Ada",
                                                local_date_offset_days=0,
                                                program_tier="FREE")
    unit = create_course_unit(total_nodes=2)
    root = append_lesson_node(unit["id"], 1)
    locked = append_lesson_node(unit["id"], 2, root["id"])

    response = api_client.practice(
        locked["id"],
        {"learner_id": learner["id"], "recorded_at": "2026-09-01T10:00:00Z",
         "response_ms": 5000, "correct": True},
        headers,
    )
    validate_error(response, "ERR_NODE_LOCKED")

    assert get_success_data(api_client.get_learner(
        learner["id"], headers
    ))["energy_units"] == 10, "a refused attempt spends no energy"


def test_node_posture_follows_its_unit_unlock_posture(api):
    """PRD §3.1: "A freshly appended node starts in `LOCKED`. The only way it opens
    is for the system to confirm that its owning unit is in either the `AVAILABLE`
    or `IN_PROGRESS` posture and that either it has no prerequisite at all"
    PRD §3.1: "it advances to `AVAILABLE` when the number of units whose state is
    `COMPLETED` and whose `unit_index` is strictly below this unit's `unit_index`
    has reached this unit's `unlock_index`"

    Design: Corner/state_machines/initial_state_of_lesson_node_created_under_available_unit
    """
    open_unit = create_course_unit(unit_index=1, cefr_band="A1", unlock_index=0,
                                   total_nodes=1)
    locked_unit = create_course_unit(unit_index=2, cefr_band="B1", unlock_index=1,
                                     total_nodes=1)

    root1 = append_lesson_node(open_unit["id"], 1)
    root2 = append_lesson_node(locked_unit["id"], 1)

    assert root1["state"] == "UNLOCKED", (
        "unit 1 needs no completed predecessor, so its root node opens on append, "
        f"got {root1['state']}"
    )
    assert root2["state"] == "LOCKED", (
        "unit 2 still needs one completed unit below it, so its root node stays "
        f"locked, got {root2['state']}"
    )


def test_subscribing_with_a_plan_outside_the_paid_set_is_refused(api):
    """PRD §3.5: "The request is admitted only when the requested `plan_code` is
    `PLUS_FAMILY` or `CERTIFICATION_ELITE` and no other subscription for that same
    learner is currently `ACTIVE`"
    PRD §2.10: "the membership of every enum field in its declared set
    (`ERR_INVALID_REQUEST`, 400)"

    Design: Corner/state_machines/subscription_free_to_active_requires_paid_plan
    """
    learner, headers = register_learner_headers(display_name="Ada",
                                                local_date_offset_days=0,
                                                program_tier="FREE")
    free = get_success_data(api_client.list_subscriptions(
        headers, {"learner_id": learner["id"]}
    ))[0]
    assert free["status"] == "FREE"

    validate_error(
        api_client.create_subscription(
            {"learner_id": learner["id"], "plan_code": "GOLD",
             "seats_total": 1, "auto_renew": True},
            headers,
        ),
        "ERR_INVALID_REQUEST",
    )

    still_free = get_success_data(api_client.get_subscription(
        free["id"], headers
    ))
    assert still_free["status"] == "FREE"
    assert get_success_data(api_client.get_learner(
        learner["id"], headers
    ))["hearts_available"] == 5, "the gate stays in force"


def test_paid_plan_removes_the_heart_and_energy_gate(api):
    """PRD §3.4: "When `program_tier` is `PLUS_FAMILY` or `CERTIFICATION_ELITE` and
    the learner's `Subscription.limits_removed` flag is true, the gate is reported
    as unlimited and both `hearts_available` and `energy_units` are returned as null
    rather than as a number."
    PRD §3.5: "Subscribe to a paid plan by supplying `learner_id`, a `plan_code`,
    `seats_total` and `auto_renew`."

    Design: Corner/state_machines/subscription_free_to_active_requires_paid_plan
    """
    learner, headers = register_learner_headers(display_name="Ada",
                                                local_date_offset_days=0,
                                                program_tier="PLUS_FAMILY")
    subscription = get_success_data(api_client.create_subscription(
        {"learner_id": learner["id"], "plan_code": "PLUS_FAMILY",
         "seats_total": 4, "auto_renew": True},
        headers,
    ))

    assert subscription["status"] == "ACTIVE"
    assert subscription["limits_removed"] is True
    refreshed = get_success_data(api_client.get_learner(learner["id"], headers))
    assert refreshed["hearts_available"] is None
    assert refreshed["energy_units"] is None


def test_missing_required_field_on_course_unit_create_is_refused(api, admin_headers):
    """PRD §3.1: "An operator seeds it by authoring a **CourseUnit** with a monotonic
    `unit_index` (index 1 is the first unit), a display `title`, a `cefr_band`
    drawn from `A1`, `A2`, `B1`, `B2` or `C1`, an `unlock_index` expressing how
    many completed units are required before it opens, and a declared
    `total_nodes`."
    PRD §2.10: "and finally, the presence of every required input field and the
    membership of every enum field in its declared set (`ERR_INVALID_REQUEST`,
    400)."

    Design: Corner/validations/required_field_missing_on_course_unit_create
    """
    validate_error(
        api_client.create_course_unit(
            {"unit_index": 1, "title": "Unit 1", "unlock_index": 0},
            admin_headers,
        ),
        "ERR_INVALID_REQUEST",
    )

    # Repeating the create with the band supplied proves nothing was minted.
    unit = get_success_data(api_client.create_course_unit(
        {"unit_index": 1, "title": "Unit 1", "cefr_band": "A1",
         "unlock_index": 0, "total_nodes": 1},
        admin_headers,
    ))
    assert unit["unit_index"] == 1


def test_cefr_band_outside_the_declared_set_is_refused(api, admin_headers):
    """PRD §3.1: "a `cefr_band` drawn from `A1`, `A2`, `B1`, `B2` or `C1`"
    PRD §2.10: "the membership of every enum field in its declared set
    (`ERR_INVALID_REQUEST`, 400)"

    Design: Corner/validations/enum_member_outside_declared_set_rejected
    """
    validate_error(
        api_client.create_course_unit(
            {"unit_index": 1, "title": "Unit 1", "cefr_band": "Z9",
             "unlock_index": 0, "total_nodes": 1},
            admin_headers,
        ),
        "ERR_INVALID_REQUEST",
    )

    unit = get_success_data(api_client.create_course_unit(
        {"unit_index": 1, "title": "Unit 1", "cefr_band": "B2",
         "unlock_index": 0, "total_nodes": 1},
        admin_headers,
    ))
    assert unit["cefr_band"] == "B2"


def test_learner_cannot_seed_the_course_tree(api):
    """PRD §2.1: "`PlatformAdmin` exclusively owns course unit and lesson node
    authoring, league settlement and re-opening, offer issuance, logical clock
    control, system sweep firing, and the payment-outcome and gem support
    injections."

    Design: Corner/rbac/learner_cannot_seed_course_tree
    """
    learner, headers = register_learner_headers(display_name="Ada",
                                                local_date_offset_days=0,
                                                program_tier="FREE")

    validate_error(
        api_client.create_course_unit(
            {"unit_index": 1, "title": "Unit 1", "cefr_band": "A1",
             "unlock_index": 0, "total_nodes": 1},
            headers,
        ),
        "ERR_UNAUTHORIZED",
    )