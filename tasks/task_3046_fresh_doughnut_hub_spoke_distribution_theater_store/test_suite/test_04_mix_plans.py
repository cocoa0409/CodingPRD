"""Mix plans: license quota boundary, expired-variety rejection, OCC on
publish, and cross-entity state dependency on the door."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_network_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_door,
    create_mix_plan,
    create_network,
    create_published_mix_plan,
    create_variety,
    mix_plan_version,
    publish_mix_plan,
    setup_hub_with_line,
    upsert_line,
)
from test_helpers.test_users import make_door_manager_headers as dmh

NA = TEST_USERS["network_admin_headers"]


def _door_and_plan(api, network_code, door_kind="THEATER", region="R"):
    network = create_network(network_code=network_code)
    door = create_door(network["id"], door_kind=door_kind, ownership="COMPANY", region=region)
    return network, door


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/license_quota_exactly_25_percent_passes
# ---------------------------------------------------------------------------

def test_license_quota_exactly_25_percent_passes(api):
    """PRD §3.4: "with a non-empty plan, `license_quota_dozens` must not
    exceed one quarter of `total_planned_dozens` rounded down to a whole
    number, and a breach is rejected with `ERR_LICENSE_QUOTA_EXCEEDED`" — the
    comparison admits exactly-at-quota (10 <= floor(0.25*40) == 10).

    Design: Difficulty/boundary_precision_check/license_quota_exactly_25_percent_passes
    """
    network, door = _door_and_plan(api, "N11", region="R11")
    core = create_variety(network["id"], variety_code="GLZ", collection_kind="CORE")
    lic = create_variety(
        network["id"], variety_code="LIC1", collection_kind="LICENSED", unit_cost_cents=120
    )
    plan = create_mix_plan(network["id"], door["id"])
    upsert_line(network["id"], door["id"], plan["id"], core["id"], 30)
    upsert_line(network["id"], door["id"], plan["id"], lic["id"], 10)

    published = publish_mix_plan(network["id"], door["id"], plan["id"])
    assert published["mix_plan_status"] == "PUBLISHED", (
        "license_quota_dozens 10 <= floor(0.25*40) == 10 must publish successfully"
    )


def test_license_quota_exactly_25_percent_records_quota(api):
    """PRD §3.4: "Every upsert or removal recomputes the plan's
    `total_planned_dozens` (the sum of all line dozens) and
    `license_quota_dozens` (the sum over lines whose variety is `LICENSED`)."

    Design: Difficulty/boundary_precision_check/license_quota_exactly_25_percent_passes
    """
    network, door = _door_and_plan(api, "N11B", region="R11")
    core = create_variety(network["id"], variety_code="GLZ", collection_kind="CORE")
    lic = create_variety(
        network["id"], variety_code="LIC1", collection_kind="LICENSED", unit_cost_cents=120
    )
    plan = create_mix_plan(network["id"], door["id"])
    upsert_line(network["id"], door["id"], plan["id"], core["id"], 30)
    upsert_line(network["id"], door["id"], plan["id"], lic["id"], 10)

    fetched = validate_success(api.get_mix_plan(network["id"], door["id"], plan["id"], dmh(door["id"])))
    assert fetched["total_planned_dozens"] == 40
    assert fetched["license_quota_dozens"] == 10


# ---------------------------------------------------------------------------
# Corner/validations/license_quota_over_25_percent_rejected
# ---------------------------------------------------------------------------

def test_license_quota_over_25_percent_rejected(api):
    """PRD §3.4: "with a non-empty plan, `license_quota_dozens` must not
    exceed one quarter of `total_planned_dozens` rounded down to a whole
    number, and a breach is rejected with `ERR_LICENSE_QUOTA_EXCEEDED`".

    Design: Corner/validations/license_quota_over_25_percent_rejected
    """
    network, door = _door_and_plan(api, "NLQ", region="RLQ")
    core = create_variety(network["id"], variety_code="GLZ", collection_kind="CORE")
    lic = create_variety(
        network["id"], variety_code="LICX", collection_kind="LICENSED", unit_cost_cents=120
    )
    plan = create_mix_plan(network["id"], door["id"])
    upsert_line(network["id"], door["id"], plan["id"], core["id"], 29)
    upsert_line(network["id"], door["id"], plan["id"], lic["id"], 11)

    resp = api.publish_mix_plan(
        network["id"], door["id"], plan["id"],
        {"expected_mix_plan_version": mix_plan_version(network["id"], door["id"], plan["id"])},
        dmh(door["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_QUOTA_EXCEEDED)

    after = validate_success(api.get_mix_plan(network["id"], door["id"], plan["id"], dmh(door["id"])))
    assert after["mix_plan_status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner/validations/mix_plan_publish_with_expired_variety_rejected
# ---------------------------------------------------------------------------

def test_mix_plan_publish_with_expired_variety_rejected(api):
    """PRD §3.4: "every line's variety is `ACTIVE` for the plan's effective
    date — a line pointing at a variety whose window has expired for that
    date is rejected with `ERR_VARIETY_EXPIRED`".

    Design: Corner/validations/mix_plan_publish_with_expired_variety_rejected
    """
    network, door = _door_and_plan(api, "NVE", region="RVE")
    expired = create_variety(
        network["id"], variety_code="OLD", collection_kind="SEASONAL",
        active_from="2026-01-01T00:00:00Z", active_until="2026-08-01T00:00:00Z",
        unit_cost_cents=90,
    )
    plan = create_mix_plan(network["id"], door["id"], effective_date="2026-09-01")
    upsert_line(network["id"], door["id"], plan["id"], expired["id"], 5)

    resp = api.publish_mix_plan(
        network["id"], door["id"], plan["id"],
        {"expected_mix_plan_version": mix_plan_version(network["id"], door["id"], plan["id"])},
        dmh(door["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VARIETY_EXPIRED)

    after = validate_success(api.get_mix_plan(network["id"], door["id"], plan["id"], dmh(door["id"])))
    assert after["mix_plan_status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner/cross_cutting_complexity_layers/occ_stale_mix_plan_version_on_publish
# ---------------------------------------------------------------------------

def test_occ_stale_mix_plan_version_on_publish(api):
    """PRD §2.9: "Publishing a mix plan requires the request to carry
    `expected_mix_plan_version` holding the client's last observed `version`
    of the target mix plan. If the plan's current `version` has advanced
    since that observation ... the publish is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_mix_plan_version_on_publish
    """
    network, door = _door_and_plan(api, "NOM", region="ROM")
    core = create_variety(network["id"], variety_code="GLZ", collection_kind="CORE")
    plan = create_mix_plan(network["id"], door["id"])
    v0 = plan["version"]  # snapshot at creation, before the line upsert
    upsert_line(network["id"], door["id"], plan["id"], core["id"], 10)

    resp = api.publish_mix_plan(
        network["id"], door["id"], plan["id"],
        {"expected_mix_plan_version": v0},
        dmh(door["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    after = validate_success(api.get_mix_plan(network["id"], door["id"], plan["id"], dmh(door["id"])))
    assert after["mix_plan_status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/mix_plan_publish_blocked_when_door_suspended
# ---------------------------------------------------------------------------

def test_mix_plan_publish_blocked_when_door_suspended(api):
    """PRD §3.4: "Publish is permitted only when the door is `ACTIVE`".
    PRD §3.1: "A `NetworkAdmin` may also suspend a door manually".

    Design: Difficulty/cross_entity_state_dependency/mix_plan_publish_blocked_when_door_suspended
    """
    network, hub, _line = setup_hub_with_line(network_code="N14", hub_code="H14", region="R14")
    door = create_door(
        network["id"], door_kind="SPOKE", ownership="FRANCHISE", region="R14", hub_id=hub["id"]
    )
    core = create_variety(network["id"], variety_code="GLZ", collection_kind="CORE")
    plan = create_mix_plan(network["id"], door["id"])
    upsert_line(network["id"], door["id"], plan["id"], core["id"], 10)

    validate_success(api.suspend_door(network["id"], door["id"], NA))
    resp = api.publish_mix_plan(
        network["id"], door["id"], plan["id"],
        {"expected_mix_plan_version": mix_plan_version(network["id"], door["id"], plan["id"])},
        dmh(door["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_mix_plan(network["id"], door["id"], plan["id"], dmh(door["id"])))
    assert after["mix_plan_status"] == "DRAFT"


def test_mix_plan_publish_blocked_when_door_suspended_keeps_draft_and_door_suspended(api):
    """PRD §3.4: "Publish is permitted only when the door is `ACTIVE`" — a
    rejected publish must not advance the plan out of `DRAFT`.
    PRD §3.1: "A `NetworkAdmin` may also suspend a door manually, which
    triggers a posture recompute".

    Design: Difficulty/cross_entity_state_dependency/mix_plan_publish_blocked_when_door_suspended
    """
    network, hub, _line = setup_hub_with_line(network_code="N14B", hub_code="H14B", region="R14")
    door = create_door(
        network["id"], door_kind="SPOKE", ownership="FRANCHISE", region="R14", hub_id=hub["id"]
    )
    core = create_variety(network["id"], variety_code="GLZ", collection_kind="CORE")
    plan = create_mix_plan(network["id"], door["id"])
    upsert_line(network["id"], door["id"], plan["id"], core["id"], 10)

    validate_success(api.suspend_door(network["id"], door["id"], NA))
    resp = api.publish_mix_plan(
        network["id"], door["id"], plan["id"],
        {"expected_mix_plan_version": mix_plan_version(network["id"], door["id"], plan["id"])},
        dmh(door["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    door_after = validate_success(api.get_door(network["id"], door["id"], NA))
    assert door_after["door_status"] == "SUSPENDED"
    plan_after = validate_success(api.get_mix_plan(network["id"], door["id"], plan["id"], dmh(door["id"])))
    assert plan_after["mix_plan_status"] == "DRAFT"
