"""Managed package versions, installations, upgrades and the OCC gate that
serialises them."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    complete_refresh_job,
    create_environment,
    create_production,
    create_sandbox,
    get_environment,
    install_package,
    load_installation,
    publish_package_version,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RELEASE = TEST_USERS["release_manager_headers"]


def _installations(environment_id: str) -> list:
    rows, _ = validate_paginated(api_client.list_package_installations(environment_id, ADMIN))
    return rows


# ─── Package publishing ───────────────────────────────────────────────────────

def test_package_version_requires_a_name(api):
    """PRD §3.4: "A managed package version is published by a `PlatformAdmin`,
    who supplies the vendor's `namespace`, an integer `major_version` of at
    least 1, a human-readable `name`, and optionally the version it upgrades
    from in `supersedes_version_id`"

    Design: Corner/entities/package_version_requires_name_field
    """
    res = api.create_package_version(
        {"namespace": "acme", "major_version": 1}, ADMIN)
    error = validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)
    assert "error_id" in error
    assert "id" not in error


def test_package_version_major_version_must_be_at_least_one(api):
    """PRD §3.4: "A managed package version is published by a `PlatformAdmin`,
    who supplies the vendor's `namespace`, an integer `major_version` of at
    least 1, a human-readable `name`"

    Design: Corner/entities/package_version_numeric_and_enum_constraints
    """
    res = api.create_package_version(
        {"namespace": "acme", "major_version": 0, "name": "Zero Version"}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_publishing_a_successor_deprecates_the_predecessor(api):
    """PRD §3.4: "The publish itself extends the namespace's upgrade chain"
    PRD §3.4: "A published version starts with `deprecated` false."

    Design: Corner/endpoints/conditional_upgrade_refused_when_target_deprecated
    """
    v1 = publish_package_version("acme", 1)
    assert validate_success(api.get_package_version(v1["id"], ADMIN), 200)["deprecated"] is False

    publish_package_version("acme", 2, supersedes_version_id=v1["id"])

    assert validate_success(api.get_package_version(v1["id"], ADMIN), 200)["deprecated"] is True


# ─── Installation defaults and derived fields ─────────────────────────────────

def test_installation_derives_namespace_from_the_package_version(api):
    """PRD §3.4: "A successful install creates the installation in status
    `INSTALLED`, denormalising the installed version's namespace onto the
    installation so that the environment's installed namespaces are readable
    without joining back to the chain, and advances the environment's version."

    Design: Corner/entities/installed_package_namespace_is_derived_not_supplied
    """
    package = publish_package_version("orbit", 3)
    env = create_environment(type="PARTIAL")

    res = api.install_package(
        env["id"],
        {"package_version_id": package["id"], "expected_environment_version": env["version"]},
        RELEASE)
    installed = validate_success(res, 201)
    assert installed["namespace"] == "orbit"
    assert installed["status"] == "INSTALLED"
    assert installed["stale"] is False
    assert installed["refreshed_at"] is None


def test_installation_recomputes_package_install_count(api):
    """PRD §2.7: "The **package-installation cascade** begins with an
    installation mutation and runs the other way: hop 1 recomputes
    `PackageVersion.install_count`"

    Design: Corner/entities/installed_package_namespace_is_derived_not_supplied
    """
    package = publish_package_version("orbit", 3)
    env = create_environment(type="PARTIAL")
    install_package(env, package["id"])

    refreshed = validate_success(api.get_package_version(package["id"], ADMIN), 200)
    assert refreshed["install_count"] == 1


def test_installation_record_is_visible_in_the_environment_listing(api):
    """PRD §3.4: "Reading the installations of a version returns the
    **InstalledPackage** rows across every environment that reference it; a
    version nobody has installed returns an empty array rather than a
    not-found."

    Design: Corner/entities/installed_package_namespace_is_derived_not_supplied
    """
    package = publish_package_version("orbit", 3)
    empty, _ = validate_paginated(api.list_package_version_installations(package["id"], ADMIN))
    assert empty == []

    env = create_environment(type="PARTIAL")
    installed = install_package(env, package["id"])

    rows, _ = validate_paginated(api.list_package_version_installations(package["id"], ADMIN))
    assert [row["id"] for row in rows] == [installed["id"]]
    assert [row["id"] for row in _installations(env["id"])] == [installed["id"]]


# ─── Installation precondition ordering ───────────────────────────────────────

def test_dependency_floor_outranks_duplicate_namespace(api):
    """PRD §3.4: "The version's declared dependency must be satisfied: when it
    declares `requires_namespace`, the environment must already hold a
    non-`UNINSTALLED` installation of that namespace whose installed version's
    `major_version` is at least the `major_version` of the version named by
    `requires_min_version_id` — otherwise the install is refused with
    `ERR_PACKAGE_DEPENDENCY_UNMET` and HTTP status 422."
    PRD §3.4: "Then the environment must not already carry an installation of
    the same namespace that is not `UNINSTALLED`, because a namespace may be
    installed only once per environment; a repeat is refused with
    `ERR_PACKAGE_ALREADY_INSTALLED` and HTTP status 409."

    Design: Difficulty/cross_entity_state_dependency/upgrade_gated_by_sibling_installation_floor
    """
    core1 = publish_package_version("acme", 1)
    ui1 = publish_package_version("ui", 1)
    env = create_environment(type="PARTIAL")
    install_package(env, ui1["id"])

    ui2 = publish_package_version("ui", 2, supersedes_version_id=ui1["id"],
                                  requires_namespace="acme", requires_min_version_id=core1["id"])
    environment = get_environment(env["id"])
    res = api.install_package(
        env["id"],
        {"package_version_id": ui2["id"], "expected_environment_version": environment["version"]},
        RELEASE)
    validate_error(res, "ERR_PACKAGE_DEPENDENCY_UNMET", expected_status=422)


def test_deprecated_version_is_refused(api):
    """PRD §3.4: "Last, the version being installed must not be deprecated, or
    the install is refused with `ERR_VERSION_DEPRECATED` and HTTP status 409."

    Design: Corner/endpoints/conditional_upgrade_refused_when_target_deprecated
    """
    v1 = publish_package_version("acme", 1)
    publish_package_version("acme", 2, supersedes_version_id=v1["id"])
    env = create_environment(type="PARTIAL")

    res = api.install_package(
        env["id"],
        {"package_version_id": v1["id"], "expected_environment_version": env["version"]},
        RELEASE)
    validate_error(res, "ERR_VERSION_DEPRECATED", expected_status=409)


# ─── Upgrading an installation ────────────────────────────────────────────────

def test_upgrade_refused_while_sibling_dependency_is_absent(api):
    """PRD §3.4: "the target must not be deprecated, must belong to the same
    `namespace` as the installed version, and — when it declares
    `requires_namespace` — must find the environment's installation of that
    namespace at or above the required `major_version`; failures are reported as
    `ERR_VERSION_DEPRECATED`, `ERR_INVALID_STATE` and
    `ERR_PACKAGE_DEPENDENCY_UNMET` respectively."
    PRD §3.4: "Both a refresh completion and an applied platform release drive
    the system-initiated transition from `INSTALLED` to `NEEDS_UPGRADE`"

    Design: Difficulty/cross_entity_state_dependency/upgrade_gated_by_sibling_installation_floor
    """
    core1 = publish_package_version("acme", 1)
    ui1 = publish_package_version("ui", 1)
    env = create_environment(type="PARTIAL")
    ui_pkg = install_package(env, ui1["id"])

    ui2 = publish_package_version("ui", 2, supersedes_version_id=ui1["id"],
                                  requires_namespace="acme", requires_min_version_id=core1["id"])
    complete_refresh_job(env["id"], masked_field_count=2)
    assert load_installation(env["id"], ui_pkg["id"])["status"] == "NEEDS_UPGRADE"

    res = api.upgrade_installed_package(
        ui_pkg["id"], {"target_package_version_id": ui2["id"]}, RELEASE)
    validate_error(res, "ERR_PACKAGE_DEPENDENCY_UNMET", expected_status=422)
    assert load_installation(env["id"], ui_pkg["id"])["status"] == "NEEDS_UPGRADE"


def test_upgrade_succeeds_once_the_dependency_floor_is_met(api):
    """PRD §3.4: "The upgrade rewrites the installation's `package_version_id`
    to the target, clears `stale` to false, stamps `refreshed_at`, and advances
    the environment's version."

    Design: Difficulty/cross_entity_state_dependency/upgrade_gated_by_sibling_installation_floor
    """
    core1 = publish_package_version("acme", 1)
    ui1 = publish_package_version("ui", 1)
    env = create_environment(type="PARTIAL")
    ui_pkg = install_package(env, ui1["id"])

    ui2 = publish_package_version("ui", 2, supersedes_version_id=ui1["id"],
                                  requires_namespace="acme", requires_min_version_id=core1["id"])
    complete_refresh_job(env["id"], masked_field_count=2)
    assert load_installation(env["id"], ui_pkg["id"])["status"] == "NEEDS_UPGRADE"

    validate_error(api.upgrade_installed_package(
        ui_pkg["id"], {"target_package_version_id": ui2["id"]}, RELEASE),
        "ERR_PACKAGE_DEPENDENCY_UNMET")

    install_package(get_environment(env["id"]), core1["id"])

    upgraded = validate_success(api.upgrade_installed_package(
        ui_pkg["id"], {"target_package_version_id": ui2["id"]}, RELEASE), 200)
    assert upgraded["status"] == "UPGRADED"
    assert upgraded["package_version_id"] == ui2["id"]


def test_upgrade_onto_a_deprecated_version_is_refused(api):
    """PRD §3.4: "the target must not be deprecated, must belong to the same
    `namespace` as the installed version, and — when it declares
    `requires_namespace` — must find the environment's installation of that
    namespace at or above the required `major_version`; failures are reported as
    `ERR_VERSION_DEPRECATED`, `ERR_INVALID_STATE` and
    `ERR_PACKAGE_DEPENDENCY_UNMET` respectively."

    Design: Corner/endpoints/conditional_upgrade_refused_when_target_deprecated
    """
    v1 = publish_package_version("acme", 1)
    env = create_environment(type="PARTIAL")
    pkg = install_package(env, v1["id"])

    v2 = publish_package_version("acme", 2, supersedes_version_id=v1["id"])
    v3 = publish_package_version("acme", 3, supersedes_version_id=v2["id"])
    complete_refresh_job(env["id"], masked_field_count=2)
    assert load_installation(env["id"], pkg["id"])["status"] == "NEEDS_UPGRADE"

    res = api.upgrade_installed_package(
        pkg["id"], {"target_package_version_id": v2["id"]}, RELEASE)
    validate_error(res, "ERR_VERSION_DEPRECATED", expected_status=409)

    promoted = validate_success(api.upgrade_installed_package(
        pkg["id"], {"target_package_version_id": v3["id"]}, RELEASE), 200)
    assert promoted["status"] == "UPGRADED"
    assert promoted["package_version_id"] == v3["id"]
    assert promoted["stale"] is False


# ─── The stale marker and install counts ──────────────────────────────────────

def test_publish_marks_existing_installations_stale(api):
    """PRD §2.7: "The **package-installation cascade** begins with an
    installation mutation and runs the other way: hop 1 recomputes
    `PackageVersion.install_count`; hop 2, triggered by that counter write,
    re-derives `InstalledPackage.stale` across the environment's installations
    that share the package's namespace chain"

    Design: Difficulty/cascading_side_effects/package_publish_refreshes_every_installations_stale_marker
    """
    v1 = publish_package_version("acme", 1)
    root = create_production()
    env_a = create_sandbox(root["id"], type="DEVELOPER")
    env_b = create_sandbox(root["id"], type="PARTIAL")
    pkg_a = install_package(env_a, v1["id"])
    pkg_b = install_package(env_b, v1["id"])

    v2 = publish_package_version("acme", 2, supersedes_version_id=v1["id"])

    assert validate_success(api.get_package_version(v2["id"], ADMIN), 200)["install_count"] == 0
    assert validate_success(api.get_package_version(v1["id"], ADMIN), 200)["install_count"] == 2
    assert load_installation(env_a["id"], pkg_a["id"])["stale"] is True
    assert load_installation(env_b["id"], pkg_b["id"])["stale"] is True


def test_publish_leaves_installed_version_pointer_untouched(api):
    """PRD §3.4: "The publish also touches every environment: hop 1 stamps
    `refreshed_at` on every installation, across every environment, whose
    namespace is the published namespace."

    Design: Difficulty/cascading_side_effects/package_publish_refreshes_every_installations_stale_marker
    """
    v1 = publish_package_version("acme", 1)
    root = create_production()
    env = create_sandbox(root["id"], type="DEVELOPER")
    pkg = install_package(env, v1["id"])

    publish_package_version("acme", 2, supersedes_version_id=v1["id"])

    pkg_after = load_installation(env["id"], pkg["id"])
    assert pkg_after["package_version_id"] == v1["id"]
    assert pkg_after["status"] == "INSTALLED"


# ─── OCC on package installation ──────────────────────────────────────────────

def test_installation_rejects_a_stale_environment_version(api):
    """PRD §2.6: "The first is the managed-package installation against an
    environment: `POST /platform/environments/{id}/package-installations`
    requires a non-optional `expected_environment_version` field in its request
    body. If the value supplied does not match the target environment's current
    `version`, the request is rejected with `ERR_STALE_VERSION` and HTTP status
    412."

    Design: Difficulty/optimistic_concurrency/package_installation_rejects_stale_environment_version
    """
    acme = publish_package_version("acme", 1)
    orbit = publish_package_version("orbit", 1)
    env = create_environment(type="PARTIAL")
    initial_version = env["version"]

    validate_success(api.install_package(
        env["id"],
        {"package_version_id": acme["id"], "expected_environment_version": initial_version},
        RELEASE), 201)

    second = api.install_package(
        env["id"],
        {"package_version_id": orbit["id"], "expected_environment_version": initial_version},
        RELEASE)
    validate_error(second, "ERR_STALE_VERSION", expected_status=412)
    assert all(row["namespace"] != "orbit" for row in _installations(env["id"]))


def test_installation_advances_the_environment_version_and_is_replayable(api):
    """PRD §2.6: "Installing a second, different managed package into the same
    environment is entirely legitimate product behavior, and opening a new
    change set that supersedes an earlier one is likewise legitimate; in both
    cases nothing about the environment's state forbids the request, so the
    stale `expected_environment_version` the client supplied is the sole and
    complete reason for the rejection."

    Design: Difficulty/optimistic_concurrency/package_installation_rejects_stale_environment_version
    """
    acme = publish_package_version("acme", 1)
    orbit = publish_package_version("orbit", 1)
    env = create_environment(type="PARTIAL")
    initial_version = env["version"]

    validate_success(api.install_package(
        env["id"],
        {"package_version_id": acme["id"], "expected_environment_version": initial_version},
        RELEASE), 201)
    environment = get_environment(env["id"])
    assert environment["version"] > initial_version

    replay = api.install_package(
        env["id"],
        {"package_version_id": orbit["id"],
         "expected_environment_version": environment["version"]},
        RELEASE)
    validate_success(replay, 201)
    assert {row["namespace"] for row in _installations(env["id"])} == {"acme", "orbit"}


# ─── Conflict-policy selection (selector_policy) ──────────────────────────────

def test_promotion_lands_on_the_newest_sibling_of_a_shared_major_version(api):
    """PRD §3.4: "The competing rule, used on the audited replay path, ranks by
    the installation's recorded `installed_at` ascending instead, so that the
    winner is whichever version was installed first"
    PRD §3.4: "The upgrade rewrites the installation's `package_version_id` to
    the target, clears `stale` to false, stamps `refreshed_at`, and advances the
    environment's version."

    Design: Difficulty/selector_policy/package_conflict_winner_tie_broken_by_created_at_desc
    """
    from test_helpers import set_clock
    v1 = publish_package_version("acme", 1)
    env = create_environment(type="DEVELOPER")
    pkg = install_package(env, v1["id"])

    set_clock("2026-09-02T00:00:00Z")
    publish_package_version("acme", 2, name="Acme Core 2 branch A",
                            supersedes_version_id=v1["id"])
    set_clock("2026-09-03T00:00:00Z")
    newer = publish_package_version("acme", 2, name="Acme Core 2 branch B",
                                    supersedes_version_id=v1["id"])

    complete_refresh_job(env["id"], masked_field_count=2)
    assert load_installation(env["id"], pkg["id"])["status"] == "NEEDS_UPGRADE"

    promoted = validate_success(api.upgrade_installed_package(
        pkg["id"], {"target_package_version_id": newer["id"]}, RELEASE), 200)
    assert promoted["package_version_id"] == newer["id"]
    assert promoted["status"] == "UPGRADED"
    assert promoted["stale"] is False


def test_a_shared_major_version_leaves_both_branches_selectable(api):
    """PRD §3.4: "the winning candidate is the one with the greatest
    `major_version`, with ties among versions sharing that major version broken
    by the earliest creation timestamp; the installation is then stale exactly
    when that candidate's `major_version` is strictly greater than the
    `major_version` of the version currently installed. The same rule writes the
    environment's `installed_version_ids`"

    Design: Difficulty/selector_policy/package_conflict_winner_tie_broken_by_created_at_desc
    """
    from test_helpers import set_clock
    v1 = publish_package_version("acme", 1)
    env = create_environment(type="DEVELOPER")
    pkg = install_package(env, v1["id"])

    set_clock("2026-09-02T00:00:00Z")
    branch_a = publish_package_version("acme", 2, name="Acme Core 2 branch A",
                                       supersedes_version_id=v1["id"])
    set_clock("2026-09-03T00:00:00Z")
    branch_b = publish_package_version("acme", 2, name="Acme Core 2 branch B",
                                       supersedes_version_id=v1["id"])

    assert branch_a["id"] != branch_b["id"]
    assert validate_success(api.get_package_version(branch_b["id"], ADMIN),
                            200)["major_version"] == 2
    complete_refresh_job(env["id"], masked_field_count=2)
    assert load_installation(env["id"], pkg["id"])["status"] == "NEEDS_UPGRADE"


def test_promotion_lands_on_the_requested_version_of_a_deeper_chain(api):
    """PRD §3.4: "The upgrade rewrites the installation's `package_version_id`
    to the target, clears `stale` to false, stamps `refreshed_at`, and advances
    the environment's version."

    Design: Difficulty/selector_policy/package_conflict_winner_prefers_deeper_dependency_chain
    """
    core = publish_package_version("acme", 1)
    orbit = publish_package_version("orbit", 1)
    ui1 = publish_package_version("ui", 1, requires_namespace="orbit",
                                  requires_min_version_id=orbit["id"])
    env = create_environment(type="DEVELOPER")
    install_package(env, orbit["id"])
    ui_pkg = install_package(get_environment(env["id"]), ui1["id"])
    core_pkg = install_package(get_environment(env["id"]), core["id"])

    after = get_environment(env["id"])
    assert len(after["installed_version_ids"]) == 3
    assert load_installation(env["id"], core_pkg["id"])["stale"] is False
    assert load_installation(env["id"], ui_pkg["id"])["status"] == "INSTALLED"


def test_deepest_chain_member_is_the_conflict_winner(api):
    """PRD §3.4: "The conflict resolution rule collects the environment's
    non-deprecated versions, excluding any version whose installation is
    `UNINSTALLED`, and ranks each by a pair of keys in fixed order: first the
    length of the dependency chain that starts at that version — walking from
    its `requires_namespace` to the environment's installation of that
    namespace, then to that installation's own `requires_namespace`, and so on,
    giving zero when the version declares no dependency — and second its
    `major_version`."

    Design: Difficulty/selector_policy/package_conflict_winner_prefers_deeper_dependency_chain
    """
    orbit = publish_package_version("orbit", 1)
    ui1 = publish_package_version("ui", 1, requires_namespace="orbit",
                                  requires_min_version_id=orbit["id"])
    core = publish_package_version("acme", 5)
    env = create_environment(type="DEVELOPER")
    install_package(env, orbit["id"])
    install_package(get_environment(env["id"]), ui1["id"])
    core_pkg = install_package(get_environment(env["id"]), core["id"])

    after = get_environment(env["id"])
    assert len(after["installed_version_ids"]) == 3
    assert load_installation(env["id"], core_pkg["id"])["stale"] is False
    assert ui1["requires_namespace"] == "orbit"


def test_promotion_after_an_install_order_replay_chooses_the_requested_branch(api):
    """PRD §3.4: "for an environment holding `acme-core` at major version 2 and
    `acme-ui` at major version 3, where the user-interface package requires the
    core package, the chain-depth rule picks the deeper user-interface package
    while the replay rule picks whichever was installed first."

    Design: Corner/calculations/package_conflict_resolution_install_order_variant
    """
    core = publish_package_version("acme", 1)
    ui1 = publish_package_version("ui", 1)
    env = create_environment(type="DEVELOPER")
    install_package(env, core["id"])
    ui_pkg = install_package(get_environment(env["id"]), ui1["id"])
    ui2 = publish_package_version("ui", 2, supersedes_version_id=ui1["id"],
                                  requires_namespace="acme", requires_min_version_id=core["id"])

    complete_refresh_job(env["id"], masked_field_count=2)
    assert load_installation(env["id"], ui_pkg["id"])["status"] == "NEEDS_UPGRADE"

    promoted = validate_success(api.upgrade_installed_package(
        ui_pkg["id"], {"target_package_version_id": ui2["id"]}, RELEASE), 200)
    assert promoted["status"] == "UPGRADED"
    assert promoted["package_version_id"] == ui2["id"]


# ─── Best-effort batch semantics across an install sweep ──────────────────────

def test_duplicate_namespace_member_is_rejected_without_rollback(api):
    """PRD §3.4: "Then the environment must not already carry an installation of
    the same namespace that is not `UNINSTALLED`, because a namespace may be
    installed only once per environment; a repeat is refused with
    `ERR_PACKAGE_ALREADY_INSTALLED` and HTTP status 409."

    Design: Difficulty/bulk_operations/batch_install_partial_failure_keeps_successful_rows
    """
    acme1 = publish_package_version("acme", 1)
    orbit1 = publish_package_version("orbit", 1)
    nimbus1 = publish_package_version("nimbus", 1)
    env = create_environment(type="PARTIAL")
    acme_pkg = install_package(env, acme1["id"])

    orbit_pkg = install_package(get_environment(env["id"]), orbit1["id"])

    environment = get_environment(env["id"])
    duplicate = api.install_package(
        env["id"],
        {"package_version_id": acme1["id"], "expected_environment_version": environment["version"]},
        RELEASE)
    validate_error(duplicate, "ERR_PACKAGE_ALREADY_INSTALLED", expected_status=409)

    nimbus_pkg = install_package(get_environment(env["id"]), nimbus1["id"])

    assert load_installation(env["id"], acme_pkg["id"])["status"] == "INSTALLED"
    assert load_installation(env["id"], orbit_pkg["id"])["status"] == "INSTALLED"
    assert load_installation(env["id"], nimbus_pkg["id"])["status"] == "INSTALLED"


def test_rejected_duplicate_leaves_the_installed_set_unchanged(api):
    """PRD §3.4: "a namespace may be installed only once per environment; a
    repeat is refused with `ERR_PACKAGE_ALREADY_INSTALLED` and HTTP status 409."

    Design: Difficulty/bulk_operations/batch_install_partial_failure_keeps_successful_rows
    """
    acme1 = publish_package_version("acme", 1)
    orbit1 = publish_package_version("orbit", 1)
    nimbus1 = publish_package_version("nimbus", 1)
    env = create_environment(type="PARTIAL")
    install_package(env, acme1["id"])
    install_package(get_environment(env["id"]), orbit1["id"])

    environment = get_environment(env["id"])
    validate_error(api.install_package(
        env["id"],
        {"package_version_id": acme1["id"], "expected_environment_version": environment["version"]},
        RELEASE), "ERR_PACKAGE_ALREADY_INSTALLED")

    install_package(get_environment(env["id"]), nimbus1["id"])

    after = get_environment(env["id"])
    assert len(after["installed_version_ids"]) == 3


# ─── Duplicate namespace outranks the deprecated-version rule ─────────────────

def test_duplicate_namespace_outranks_deprecated_version(api):
    """PRD §3.4: "Then the environment must not already carry an installation of
    the same namespace that is not `UNINSTALLED`, because a namespace may be
    installed only once per environment; a repeat is refused with
    `ERR_PACKAGE_ALREADY_INSTALLED` and HTTP status 409."
    PRD §3.4: "Installing a managed package checks the dependency floor, then
    whether the namespace is already installed, then whether the target version
    is deprecated."

    Design: Corner/validations/duplicate_namespace_prefers_already_installed_error
    """
    v1 = publish_package_version("acme", 1)
    env = create_environment(type="PARTIAL")
    install_package(env, v1["id"])
    publish_package_version("acme", 2, supersedes_version_id=v1["id"])
    assert validate_success(api.get_package_version(v1["id"], ADMIN), 200)["deprecated"] is True

    environment = get_environment(env["id"])
    res = api.install_package(
        env["id"],
        {"package_version_id": v1["id"], "expected_environment_version": environment["version"]},
        RELEASE)
    validate_error(res, "ERR_PACKAGE_ALREADY_INSTALLED", expected_status=409)

    assert get_environment(env["id"])["installed_version_ids"] == [v1["id"]]


def test_duplicate_namespace_rejection_leaves_install_count_unchanged(api):
    """PRD §3.4: "a namespace may be installed only once per environment; a
    repeat is refused with `ERR_PACKAGE_ALREADY_INSTALLED` and HTTP status 409."

    Design: Corner/validations/duplicate_namespace_prefers_already_installed_error
    """
    v1 = publish_package_version("acme", 1)
    env = create_environment(type="PARTIAL")
    install_package(env, v1["id"])
    publish_package_version("acme", 2, supersedes_version_id=v1["id"])

    environment = get_environment(env["id"])
    validate_error(api.install_package(
        env["id"],
        {"package_version_id": v1["id"], "expected_environment_version": environment["version"]},
        RELEASE), "ERR_PACKAGE_ALREADY_INSTALLED")

    assert validate_success(api.get_package_version(v1["id"], ADMIN), 200)["install_count"] == 1


# ─── An all-admitted install sweep ────────────────────────────────────────────

def test_all_members_of_a_dependency_satisfied_sweep_install(api):
    """PRD §3.4: "A successful install creates the installation in status
    `INSTALLED`, denormalising the installed version's namespace onto the
    installation so that the environment's installed namespaces are readable
    without joining back to the chain, and advances the environment's version."

    Design: Corner/validations/full_package_sweep_all_members_admitted
    """
    acme1 = publish_package_version("acme", 1)
    orbit1 = publish_package_version("orbit", 1)
    nimbus1 = publish_package_version("nimbus", 1, requires_namespace="orbit",
                                      requires_min_version_id=orbit1["id"])
    env = create_environment(type="PARTIAL")

    install_package(env, acme1["id"])
    install_package(get_environment(env["id"]), orbit1["id"])
    install_package(get_environment(env["id"]), nimbus1["id"])

    after = get_environment(env["id"])
    assert len(after["installed_version_ids"]) == 3
    assert validate_success(api.get_package_version(acme1["id"], ADMIN), 200)["install_count"] == 1