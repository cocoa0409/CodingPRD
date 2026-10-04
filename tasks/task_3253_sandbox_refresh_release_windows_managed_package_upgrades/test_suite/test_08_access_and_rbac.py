"""Layered-access governance, the tenant isolation of the permission model and
role separation across operations."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    close_audit,
    create_environment,
    create_ledger,
    get_environment,
    grant_permission,
    install_package,
    open_audit,
    publish_package_version,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RELEASE = TEST_USERS["release_manager_headers"]
ENV_ADMIN = TEST_USERS["environment_admin_headers"]
STORAGE = TEST_USERS["storage_archivist_headers"]
AUDITOR = TEST_USERS["security_auditor_headers"]
DEVELOPER = TEST_USERS["app_developer_headers"]


def _permissions(environment_id: str, params=None) -> list:
    rows, _ = validate_paginated(api_client.list_permissions(environment_id, ADMIN, params))
    return rows


# ─── The layer sum and the overreach budget ───────────────────────────────────

def test_single_layer_operator_does_not_overreach(api):
    """PRD §3.7: "The layer sum is the number of distinct layers present, and
    the operator overreaches when that sum is strictly greater than the standard
    access-layer budget, which is 2."

    Design: Corner/rbac/environment_admin_cannot_open_access_audit
    """
    env = create_environment(type="DEVELOPER")
    grant = grant_permission(env["id"], "PROFILE", "PeerProfile", "0050a0000b0001")
    audit = open_audit(env["id"], [grant["id"]])
    assert audit["status"] == "OPEN"
    assert audit["overreach_count"] == 0


def test_two_layer_operator_stays_below_the_overreach_budget(api):
    """PRD §3.7: "Three accumulated layers are therefore required before
    overreach is reported: an operator holding both a profile and a permission
    set, or either of those plus a sharing layer, does not overreach."

    Design: Corner/rbac/shared_permission_grant_available_to_two_roles
    """
    env = create_environment(type="DEVELOPER")
    first = grant_permission(env["id"], "PROFILE", "SharedOne", "0050a0000c0001")
    second = grant_permission(env["id"], "PROFILE", "SharedTwo", "0050a0000c0002")
    assert first["sharing_rule_scope"] == "PRIVATE"
    assert second["sharing_rule_scope"] == "PRIVATE"

    audit = open_audit(env["id"], [first["id"], second["id"]])
    assert audit["overreach_count"] == 0


def test_sharing_layer_comes_from_the_installed_namespace(api):
    """PRD §3.7: "A sharing layer is present only when the operator holds a
    grant whose `object_prefix` matches the namespace of a non-`UNINSTALLED`
    installation of the same environment, and — importantly — that prefix must
    not be the empty string; an environment with nothing installed can never
    produce a sharing layer at all."

    Design: Difficulty/cascading_side_effects/permission_grant_derives_scope_from_installed_namespace
    """
    package = publish_package_version("acme", 1)
    env = create_environment(type="PARTIAL")
    grant = grant_permission(env["id"], "PERMISSION_SET", "AcmeObjectsAccess",
                             "0050a000030001", object_prefix="acme")
    assert grant["sharing_rule_scope"] == "PRIVATE"

    environment = get_environment(env["id"])
    install_package(environment, package["id"])

    rows = _permissions(env["id"])
    grant_after = next(row for row in rows if row["id"] == grant["id"])
    assert grant_after["sharing_rule_scope"] == "NAMESPACE_READ"


def test_environments_installed_set_matches_the_install(api):
    """PRD §2.7: "The **package-installation cascade** begins with an
    installation mutation and runs the other way: hop 1 recomputes
    `PackageVersion.install_count`; hop 2, triggered by that counter write,
    re-derives `InstalledPackage.stale` across the environment's installations
    that share the package's namespace chain; hop 3, triggered by the stale
    rewrite, re-derives `PermissionAssignment.sharing_rule_scope` to
    `NAMESPACE_READ` for the grants in that environment whose `object_prefix`
    equals the installed namespace."

    Design: Difficulty/cascading_side_effects/permission_grant_derives_scope_from_installed_namespace
    """
    package = publish_package_version("acme", 1)
    env = create_environment(type="PARTIAL")
    grant_permission(env["id"], "PERMISSION_SET", "AcmeObjectsAccess",
                     "0050a000030001", object_prefix="acme")

    install_package(get_environment(env["id"]), package["id"])

    assert get_environment(env["id"])["installed_version_ids"] == [package["id"]]


# ─── Closing an audit with a revoke finding ───────────────────────────────────

def test_audit_revoke_flips_only_the_overreaching_operator(api):
    """PRD §3.7: "a `REVOKE` finding sets `revoked` to true on every in-scope
    assignment judged to overreach, permanently removing those layers from every
    subsequent computation, while a `RETAIN` finding leaves the grants in place
    and records only the grade."

    Design: Corner/validations/audit_revoke_finding_flips_in_scope_grants_only
    """
    package = publish_package_version("acme", 1)
    env = create_environment(type="PARTIAL")
    install_package(env, package["id"])

    profile = grant_permission(env["id"], "PROFILE", "CondProfile", "0050a000070001")
    permission_set = grant_permission(env["id"], "PERMISSION_SET", "CondSet", "0050a000070001")
    sharing = grant_permission(env["id"], "PERMISSION_SET", "CondSharing",
                               "0050a000070001", object_prefix="acme")
    solo = grant_permission(env["id"], "PROFILE", "SoloProfile", "0050a000070002")

    audit = open_audit(env["id"], [profile["id"], permission_set["id"],
                                   sharing["id"], solo["id"]])
    closed = close_audit(audit["id"], "REVOKE")
    assert closed["status"] == "CLOSED"
    assert len(closed["findings"]) == 4

    rows = {row["id"]: row for row in _permissions(env["id"])}
    assert rows[profile["id"]]["revoked"] is True
    assert rows[permission_set["id"]]["revoked"] is True
    assert rows[sharing["id"]]["revoked"] is True
    assert rows[solo["id"]]["revoked"] is False


def test_audit_grade_is_derived_from_the_overreach_count(api):
    """PRD §3.7: "Its `grade` is `BLOCKED` when that count reaches 3,
    `ATTENTION` when the count is at least 1 but below 3, and `PASS` when it is
    zero."

    Design: Corner/validations/audit_revoke_finding_flips_in_scope_grants_only
    """
    env = create_environment(type="DEVELOPER")
    grant = grant_permission(env["id"], "PROFILE", "GradeProfile", "0050a000070003")
    audit = open_audit(env["id"], [grant["id"]])

    closed = close_audit(audit["id"], "RETAIN")
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"] is not None
    assert closed["grade"] == "PASS"
    assert len(closed["findings"]) == 1
    entry = closed["findings"][0]
    assert entry["assignment_id"] == grant["id"]
    assert entry["user_id"] == "0050a000070003"
    assert entry["overreach"] is False


def test_closed_audit_cannot_be_closed_again(api):
    """PRD §2.12: "Closing an audit checks only its state, but the closing
    disposition must be supplied and must be `REVOKE` or `RETAIN`."

    Design: Corner/state_machines/access_audit_terminal_state_lockdown
    """
    env = create_environment(type="DEVELOPER")
    first = grant_permission(env["id"], "PROFILE", "LayeredProfile", "0050a000060001")
    second = grant_permission(env["id"], "PERMISSION_SET", "LayeredSet", "0050a000060001")
    audit = open_audit(env["id"], [first["id"], second["id"]])
    closed = close_audit(audit["id"], "RETAIN")

    res = api.close_access_audit(audit["id"], {"finding": "REVOKE"}, AUDITOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    rows = {row["id"]: row for row in _permissions(env["id"])}
    assert rows[first["id"]]["revoked"] is False
    assert rows[second["id"]]["revoked"] is False
    assert closed["finding"] == "RETAIN"


# ─── Tenant isolation of the permission model ─────────────────────────────────

def test_grant_listing_is_isolated_to_the_owning_environment(api):
    """PRD §2.8: "Storage accounting is expressed as a set of **StorageLedger**
    rows, each belonging to one environment through `environment_id`."

    Design: Difficulty/multi_tenancy/grant_scope_isolated_to_owning_environment
    """
    tenant_a = create_environment(type="DEVELOPER")
    tenant_b = create_environment(type="DEVELOPER")
    grant_a = grant_permission(tenant_a["id"], "PROFILE", "TenantAProfile", "0050a000090001")
    grant_b = grant_permission(tenant_b["id"], "PERMISSION_SET", "TenantBSet", "0050a000090002")

    rows_a, meta_a = validate_paginated(api_client.list_permissions(tenant_a["id"], ADMIN))
    assert [row["id"] for row in rows_a] == [grant_a["id"]]
    assert meta_a["total_count"] == 1
    assert all(row["id"] != grant_b["id"] for row in rows_a)


def test_audit_cannot_review_another_environments_grant(api):
    """PRD §2.12: "Opening an access audit adds a stricter existence rule on the
    contents of the request rather than the path: every identifier in
    `reviewed_assignment_ids` must resolve to a permission assignment belonging
    to the audited environment, and a permission assignment whose `user_id`
    resolves to no grant in that environment is likewise unusable, both reported
    as `ERR_ACCESS_TRACE_INCOMPLETE` with HTTP status 404."

    Design: Difficulty/multi_tenancy/grant_scope_isolated_to_owning_environment
    """
    tenant_a = create_environment(type="DEVELOPER")
    tenant_b = create_environment(type="DEVELOPER")
    grant_a = grant_permission(tenant_a["id"], "PROFILE", "TenantAProfile", "0050a000090001")
    grant_b = grant_permission(tenant_b["id"], "PERMISSION_SET", "TenantBSet", "0050a000090002")

    res = api.create_access_audit(
        {"environment_id": tenant_b["id"], "reviewed_assignment_ids": [grant_a["id"]]},
        AUDITOR)
    validate_error(res, "ERR_ACCESS_TRACE_INCOMPLETE", expected_status=404)
    assert grant_b["environment_id"] == tenant_b["id"]


# ─── Role separation ──────────────────────────────────────────────────────────

def test_missing_or_unknown_role_is_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or that presents an
    `X-User-Role` value outside the recognized role set, is rejected with
    `ERR_UNAUTHENTICATED` and HTTP status 401."

    Design: Corner/validations/missing_headers_return_unauthenticated
    """
    env = create_environment(type="DEVELOPER")
    res = api.get_environment(env["id"], {"X-User-ID": "op-1", "X-User-Role": "NotARole"})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_requests_without_headers_are_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying
    the calling operator, and `X-User-Role`, naming the capacity in which they
    act."

    Design: Corner/validations/missing_headers_return_unauthenticated
    """
    env = create_environment(type="DEVELOPER")
    res = api.get_environment(env["id"], {})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_app_developer_cannot_schedule_a_release(api):
    """PRD §2.1: "A request whose role is recognized but is not listed among the
    authorized roles for the addressed operation is rejected with
    `ERR_UNAUTHORIZED` and HTTP status 403."
    PRD §2.1: "`ReleaseManager` owns the seasonal release train and the
    deployment pipeline."

    Design: Corner/validations/app_developer_cannot_schedule_release
    """
    env = create_environment(type="DEVELOPER")
    res = api.schedule_release(
        env["id"], {"target_release_version": "SP26"}, DEVELOPER)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)

    after = get_environment(env["id"])
    assert after["release_status"] == "CONFIG"
    assert after["scheduled_release_version"] is None
    assert validate_success(api.get_environment(env["id"], DEVELOPER), 200)["id"] == env["id"]


def test_release_manager_cannot_publish_a_package_version(api):
    """PRD §2.1: "`PlatformAdmin` provisions environments, publishes managed
    package versions, approves change sets, accepts or rejects governor-limit
    requests"
    PRD §2.1: "A request whose role is recognized but is not listed among the
    authorized roles for the addressed operation is rejected with
    `ERR_UNAUTHORIZED` and HTTP status 403."

    Design: Corner/rbac/release_manager_cannot_publish_package_version
    """
    package = publish_package_version("orbit", 1)
    env = create_environment(type="DEVELOPER")

    res = api.create_package_version(
        {"namespace": "nimbus", "major_version": 1, "name": "Nimbus Core 1"}, RELEASE)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)

    installed = validate_success(api.install_package(
        env["id"],
        {"package_version_id": package["id"], "expected_environment_version": env["version"]},
        RELEASE), 201)
    assert installed["status"] == "INSTALLED"

    allowed = api.create_package_version(
        {"namespace": "nimbus", "major_version": 1, "name": "Nimbus Core 1"}, ADMIN)
    validate_success(allowed, 201)


def test_shared_grant_operation_is_available_to_both_declared_roles(api):
    """PRD §2.1: "`SecurityAuditor` opens and closes layered-access audits and may
    also grant permission layers."
    PRD §2.1: "Their identities are all of the same kind: each is an opaque
    operator identifier, so `X-User-ID` is never compared against the `id` of a
    persisted entity and ownership checks are never performed against it."

    Design: Corner/rbac/shared_permission_grant_available_to_two_roles
    """
    env = create_environment(type="DEVELOPER")
    by_auditor = validate_success(api.grant_permission(
        env["id"],
        {"principal_type": "PROFILE", "principal_name": "SharedOne", "user_id": "0050a0000c0001"},
        AUDITOR), 201)
    by_admin = validate_success(api.grant_permission(
        env["id"],
        {"principal_type": "PROFILE", "principal_name": "SharedTwo", "user_id": "0050a0000c0002"},
        ADMIN), 201)
    assert by_auditor["sharing_rule_scope"] == "PRIVATE"
    assert by_admin["sharing_rule_scope"] == "PRIVATE"

    refused = api.grant_permission(
        env["id"],
        {"principal_type": "PROFILE", "principal_name": "SharedThree", "user_id": "0050a0000c0003"},
        STORAGE)
    validate_error(refused, "ERR_UNAUTHORIZED", expected_status=403)
    assert len(_permissions(env["id"])) == 2


def test_environment_admin_cannot_open_an_access_audit(api):
    """PRD §2.1: "`EnvironmentAdmin` owns the mechanics of sandbox refresh jobs
    and the terminal steps of deployment jobs."
    PRD §2.1: "`SecurityAuditor` opens and closes layered-access audits and may
    also grant permission layers."

    Design: Corner/rbac/environment_admin_cannot_open_access_audit
    """
    env = create_environment(type="DEVELOPER")
    grant = grant_permission(env["id"], "PROFILE", "PeerProfile", "0050a0000a0001")

    refused_audit = api.create_access_audit(
        {"environment_id": env["id"], "reviewed_assignment_ids": [grant["id"]]}, ENV_ADMIN)
    validate_error(refused_audit, "ERR_UNAUTHORIZED", expected_status=403)

    refused_refresh = api.create_refresh_job(
        {"environment_id": env["id"], "partition": "ACCOUNT_PARTIAL",
         "masked_field_count": 2}, AUDITOR)
    validate_error(refused_refresh, "ERR_UNAUTHORIZED", expected_status=403)

    audit = open_audit(env["id"], [grant["id"]])
    assert audit["status"] == "OPEN"
    assert audit["overreach_count"] == 0


def test_storage_operations_are_exclusive_to_the_storage_role(api):
    """PRD §2.1: "`StorageArchivist` owns the storage ledger, the archival
    window and restoration."
    PRD §2.1: "A request whose role is recognized but is not listed among the
    authorized roles for the addressed operation is rejected with
    `ERR_UNAUTHORIZED` and HTTP status 403."

    Design: Corner/rbac/storage_archivist_exclusive_ledger_operations
    """
    env = create_environment(type="DEVELOPER", storage_cap_bytes=104857600)

    refused = api.create_storage_ledger(
        env["id"], {"kind": "DATA", "bytes": 1048576, "rank_index": 1}, RELEASE)
    validate_error(refused, "ERR_UNAUTHORIZED", expected_status=403)

    ledger = create_ledger(env["id"], "DATA", 1048576, 1)
    assert ledger["status"] == "LIVE"

    archive = api.archive_storage(env["id"], {"from_rank": 1, "to_rank": 1}, STORAGE)
    validate_error_is_one_of(archive, ["ERR_ARCHIVE_WINDOW_CLOSED", "ERR_ARCHIVE_BATCH_EXCEEDED"])
    assert ledger["archivable"] is False


def test_opaque_roles_accept_any_operator_identifier(api):
    """PRD §2.1: "Their identities are all of the same kind: each is an opaque
    operator identifier, so `X-User-ID` is never compared against the `id` of a
    persisted entity and ownership checks are never performed against it."

    Design: Corner/rbac/opaque_identity_roles_accept_any_operator_identifier
    """
    env = create_environment(type="DEVELOPER")
    first = validate_success(api.create_refresh_job(
        {"environment_id": env["id"], "partition": "ACCOUNT_PARTIAL",
         "masked_field_count": 2},
        {"X-User-ID": "operator-one", "X-User-Role": "EnvironmentAdmin",
         "Content-Type": "application/json"}), 201)
    second = validate_success(api.create_refresh_job(
        {"environment_id": env["id"], "partition": "ACCOUNT_PARTIAL",
         "masked_field_count": 2},
        {"X-User-ID": "operator-two", "X-User-Role": "EnvironmentAdmin",
         "Content-Type": "application/json"}), 201)

    assert first["status"] == "PENDING"
    assert second["status"] == "PENDING"
    rows, _ = validate_paginated(
        api_client.list_refresh_jobs_of_environment(env["id"], ADMIN))
    assert len(rows) == 2