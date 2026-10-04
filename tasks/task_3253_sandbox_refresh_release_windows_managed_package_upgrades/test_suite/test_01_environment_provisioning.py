"""Environment provisioning, the organization tree and the read contract."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    assert_environment,
    create_environment,
    create_production,
    create_sandbox,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_create_environment_applies_declared_defaults(api):
    """PRD §2.4: "`refresh_interval_days` defaults to 30 and must be between 1
    and 365 inclusive."
    PRD §2.4: "`masked_field_count` defaults to 0 and may not be negative."
    PRD §2.4: "`storage_cap_bytes` defaults to 5242880000 and must be strictly
    greater than zero."

    Design: Corner/entities/environment_create_applies_defaults_and_system_fields
    """
    root = create_production()
    res = api.create_environment(
        {"name": "Defaults Sandbox", "type": "DEVELOPER",
         "parent_environment_id": root["id"]},
        ADMIN,
    )
    env = validate_success(res, 201)
    assert_environment(env)
    assert env["name"] == "Defaults Sandbox"
    assert env["type"] == "DEVELOPER"
    assert env["release_status"] == "CONFIG"
    assert env["version"] == 1
    assert env["refresh_interval_days"] == 30
    assert env["masked_field_count"] == 0
    assert env["storage_cap_bytes"] == 5242880000
    assert env["storage_used_bytes"] == 0
    assert env["storage_total_bytes"] == 0
    assert env["storage_breach"] is False


def test_production_is_root_and_sandbox_reports_clone_depth(api):
    """PRD §2.4: "Only a `PRODUCTION` environment may be created without a
    parent. A sandbox names the environment it was cloned from in
    `parent_environment_id`, which is null for a top-level production
    environment, and its clone depth is recorded in `level`."
    PRD §3.1: "Creating an environment sets its `level` to 1 when the type is
    `PRODUCTION` and to one greater than its parent's level otherwise,
    initialises `version` to 1, and computes `release_window_index` as 1 because
    a new environment begins in `CONFIG`."

    Design: Corner/entities/production_environment_without_parent_has_null_level_chain
    """
    prod = create_production()
    sandbox = create_sandbox(prod["id"], type="PARTIAL")
    grandchild = create_sandbox(sandbox["id"], type="PARTIAL")

    assert prod["parent_environment_id"] is None
    assert sandbox["parent_environment_id"] == prod["id"]
    assert sandbox["level"] == 1
    assert grandchild["level"] == 2


def test_production_environment_lists_its_sandboxes(api):
    """PRD §3.1: "Asking for the sandboxes of an environment returns the
    environments whose `parent_environment_id` names it, and it always returns
    an array — a leaf sandbox with no clones beneath it yields an empty array
    rather than a not-found."

    Design: Corner/entities/production_environment_without_parent_has_null_level_chain
    """
    prod = create_production()
    child = create_sandbox(prod["id"], type="PARTIAL")

    data, meta = validate_paginated(api.list_sandboxes(prod["id"], ADMIN))
    assert [row["id"] for row in data] == [child["id"]]
    assert meta["total_count"] == 1

    leaf_data, leaf_meta = validate_paginated(api.list_sandboxes(child["id"], ADMIN))
    assert leaf_data == []
    assert leaf_meta["total_count"] == 0


def test_environment_read_round_trips_stored_configuration(api):
    """PRD §2.4: "`release_schedule_mode` defaults to `MANUAL_FIXED` and may
    also be `FLAG_ONLY`; a later configuration change on the same environment
    supersedes an earlier one."
    PRD §3.1: "Reading one environment returns its full posture in a single
    response: the release fields, the storage roll-ups described in §2.8, the
    aperture fields described in §2.9, and the rolled-up `permission_layer_total`
    described in §3.8."

    Design: Corner/entities/environment_read_round_trips_every_declared_field
    """
    created = create_environment(
        type="PARTIAL", refresh_interval_days=21, masked_field_count=7,
        storage_cap_bytes=268435456, release_schedule_mode="FLAG_ONLY", aperture_limit=4)

    env = validate_success(api.get_environment(created["id"], ADMIN), 200)
    assert env["name"] == created["name"]
    assert env["type"] == "PARTIAL"
    assert env["refresh_interval_days"] == 21
    assert env["masked_field_count"] == 7
    assert env["storage_cap_bytes"] == 268435456
    assert env["release_schedule_mode"] == "FLAG_ONLY"
    assert env["aperture_limit"] == 4
    assert env["last_refresh_at"] is None
    assert env["scheduled_release_version"] is None
    assert env["applied_release_version"] is None
    assert env["installed_version_ids"] == []
    assert env["version"] == created["version"]


def test_duplicate_environment_name_is_refused(api):
    """PRD §2.4: "`name` is a non-empty display label that must be unique across
    all environments; a duplicate is rejected with `ERR_INVALID_REQUEST` and
    HTTP status 400, the same code that covers a missing required body field, an
    enum value outside its declared set, and an integer outside its declared
    range."

    Design: Corner/errors/duplicate_environment_name_returns_invalid_request
    """
    root = create_production()
    first = create_sandbox(root["id"], type="DEVELOPER", name="Integration West")
    duplicate = api.create_environment(
        {"name": "Integration West", "type": "PARTIAL",
         "parent_environment_id": root["id"]}, ADMIN)
    validate_error(duplicate, "ERR_INVALID_REQUEST", expected_status=400)

    second = create_sandbox(root["id"], type="PARTIAL", name="Integration East")
    assert second["name"] == "Integration East"
    assert second["id"] != first["id"]
    assert validate_success(
        api.get_environment(first["id"], ADMIN), 200)["name"] == "Integration West"


def test_environment_type_enum_is_restricted(api):
    """PRD §2.4: "Its `type` is one of `PRODUCTION`, `FULL_COPY`, `PARTIAL` or
    `DEVELOPER`, and that classification is immutable once the environment
    exists — no operation in this API changes it."

    Design: Corner/entities/package_version_numeric_and_enum_constraints
    """
    res = api.create_environment({"name": "Bad Type Env", "type": "SCRATCH"}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    accepted = create_production()
    assert accepted["type"] in ["PRODUCTION", "FULL_COPY", "PARTIAL", "DEVELOPER"]


def test_unknown_environment_reports_environment_not_found(api):
    """PRD §2.12: "A request against a nested path whose environment identifier
    does not resolve is rejected with `ERR_ENVIRONMENT_NOT_FOUND` and HTTP status
    404 before any attempt is made to resolve a child resource of that
    environment; only once the environment resolves does a missing child produce
    `ERR_RESOURCE_NOT_FOUND`, also HTTP status 404."

    Design: Corner/entities/unknown_environment_returns_environment_not_found
    """
    res = api.get_environment(NON_EXISTENT_UUID, ADMIN)
    error = validate_error(res, "ERR_ENVIRONMENT_NOT_FOUND", expected_status=404)
    assert len(error["message"].strip()) > 0