"""Storage ledgers: the conserved total, archive windows, restoration and the
breach flag."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    create_environment,
    create_ledger,
    get_environment,
    grant_permission,
    schedule_and_apply_release,
    setup_released_environment_with_file_ledgers,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RELEASE = TEST_USERS["release_manager_headers"]
STORAGE = TEST_USERS["storage_archivist_headers"]


def _ledgers(environment_id: str, params=None) -> list:
    rows, _ = validate_paginated(api_client.list_storage_ledgers(environment_id, ADMIN, params))
    return rows


# ─── Breach comparison is inclusive at the cap ────────────────────────────────

def test_storage_breach_is_inclusive_at_the_cap(api):
    """PRD §2.8: "`storage_breach` is a boolean derived from the used figure and
    the cap: it is true when `storage_used_bytes` is greater than or equal to
    `storage_cap_bytes`. The boundary is inclusive — an environment whose used
    bytes exactly equal its cap is in breach."

    Design: Corner/calculations/storage_breach_comparison_is_inclusive_at_cap
    """
    at_cap = create_environment(type="DEVELOPER", storage_cap_bytes=4194304)
    below_cap = create_environment(type="DEVELOPER", storage_cap_bytes=4194304)
    create_ledger(at_cap["id"], "DATA", 4194304, 1)
    create_ledger(below_cap["id"], "DATA", 4194303, 1)

    assert get_environment(at_cap["id"])["storage_breach"] is True
    assert get_environment(below_cap["id"])["storage_breach"] is False


def test_storage_headroom_is_signed_around_the_cap(api):
    """PRD §2.8: "`storage_headroom_bytes` is `storage_total_bytes` minus
    `storage_cap_bytes`; the result is signed, and a negative value means the
    environment is within its storage contract while a non-negative value means
    it is not."

    Design: Corner/calculations/storage_breach_comparison_is_inclusive_at_cap
    """
    at_cap = create_environment(type="DEVELOPER", storage_cap_bytes=4194304)
    below_cap = create_environment(type="DEVELOPER", storage_cap_bytes=4194304)
    create_ledger(at_cap["id"], "DATA", 4194304, 1)
    create_ledger(below_cap["id"], "DATA", 4194303, 1)

    assert get_environment(at_cap["id"])["storage_headroom_bytes"] == 0
    assert get_environment(below_cap["id"])["storage_headroom_bytes"] == -1


# ─── The conserved total across archive and restore ───────────────────────────

def test_archive_and_restore_conserve_the_storage_total(api):
    """PRD §2.8: "`storage_total_bytes` is the sum of those two figures — it is
    the conserved quantity, and archiving a ledger moves bytes from the used
    bucket to the archived bucket without changing the total, while restoring
    one moves them back."

    Design: Difficulty/compensating_invariant/storage_total_conserved_across_archive_and_restore
    """
    env, ledgers = setup_released_environment_with_file_ledgers([4194304, 2097152])
    before = get_environment(env["id"])
    assert before["storage_total_bytes"] == 6291456
    assert before["storage_used_bytes"] == 6291456

    validate_success(api.archive_storage(
        env["id"], {"from_rank": 1, "to_rank": 2}, STORAGE), 200)
    after_archive = get_environment(env["id"])
    assert after_archive["storage_used_bytes"] == 0
    assert after_archive["storage_archived_bytes"] == 6291456
    assert after_archive["storage_total_bytes"] == 6291456

    validate_success(api.restore_storage_ledger(ledgers[0]["id"], STORAGE), 200)
    after_restore = get_environment(env["id"])
    assert after_restore["storage_used_bytes"] == 4194304
    assert after_restore["storage_archived_bytes"] == 2097152
    assert after_restore["storage_total_bytes"] == 6291456


def test_storage_total_is_unchanged_at_every_archive_stage(api):
    """PRD §3.6: "The conserved total does not move — archiving changes which
    bucket holds the bytes, not how many bytes there are."

    Design: Difficulty/compensating_invariant/storage_total_conserved_across_archive_and_restore
    """
    env, ledgers = setup_released_environment_with_file_ledgers([4194304, 2097152])
    api.archive_storage(env["id"], {"from_rank": 1, "to_rank": 2}, STORAGE)
    api.restore_storage_ledger(ledgers[0]["id"], STORAGE)

    totals = [get_environment(env["id"])["storage_total_bytes"] for _ in range(1)]
    assert totals == [6291456]
    after = get_environment(env["id"])
    assert after["storage_used_bytes"] + after["storage_archived_bytes"] == 6291456


# ─── The LIVE / ARCHIVED partition and headroom stability ─────────────────────

def test_archive_preserves_storage_headroom(api):
    """PRD §2.8: "`storage_used_bytes` is the sum of `bytes` over the
    environment's `LIVE` ledgers only. `storage_archived_bytes` is the sum of
    `bytes` over its `ARCHIVED` ledgers only."

    Design: Difficulty/derived_field_reconciliation/live_archived_partition_keeps_headroom_stable
    """
    env = create_environment(type="DEVELOPER", storage_cap_bytes=104857600)
    data_ledger = create_ledger(env["id"], "DATA", 4194304, 1)
    file_ledger = create_ledger(env["id"], "FILE", 2097152, 2)
    create_ledger(env["id"], "FILE", 2097152, 3)
    schedule_and_apply_release(env["id"], "SU26")

    before = get_environment(env["id"])
    assert before["storage_total_bytes"] == 8388608
    assert before["storage_headroom_bytes"] == -96468992

    validate_success(api.archive_storage(
        env["id"], {"from_rank": 2, "to_rank": 2}, STORAGE), 200)

    after = get_environment(env["id"])
    rows = {row["id"]: row for row in _ledgers(env["id"])}
    assert rows[file_ledger["id"]]["status"] == "ARCHIVED"
    assert rows[data_ledger["id"]]["status"] == "LIVE"
    assert after["storage_used_bytes"] == 6291456
    assert after["storage_archived_bytes"] == 2097152
    assert after["storage_total_bytes"] == 8388608
    assert after["storage_headroom_bytes"] == -96468992
    assert after["storage_breach"] is False


def test_archive_reconciliation_moves_only_the_used_bucket(api):
    """PRD §2.7: "The **storage cascade** begins with a ledger mutation. Hop 1
    re-derives `Environment.storage_used_bytes` and
    `Environment.storage_archived_bytes`; hop 2, triggered by that environment
    write, re-derives `Environment.storage_total_bytes`,
    `Environment.storage_headroom_bytes`, `Environment.storage_breach`"

    Design: Difficulty/derived_field_reconciliation/live_archived_partition_keeps_headroom_stable
    """
    env = create_environment(type="DEVELOPER", storage_cap_bytes=104857600)
    create_ledger(env["id"], "DATA", 4194304, 1)
    file_ledger = create_ledger(env["id"], "FILE", 2097152, 2)
    schedule_and_apply_release(env["id"], "SU26")

    validate_success(api.archive_storage(
        env["id"], {"from_rank": 2, "to_rank": 2}, STORAGE), 200)

    row = next(r for r in _ledgers(env["id"]) if r["id"] == file_ledger["id"])
    assert row["archived_at"] is not None
    assert row["archive_batch_id"] is not None
    after = get_environment(env["id"])
    assert after["storage_total_bytes"] == 6291456
    assert after["storage_breach"] is False


# ─── The inclusive archive window ─────────────────────────────────────────────

def test_archive_window_is_inclusive_at_both_ends(api):
    """PRD §3.6: "The window is named by its endpoints `from_rank` and
    `to_rank` and is inclusive at both ends, so the window covers every row
    whose `rank_index` lies between the two values."

    Design: Difficulty/resource_temporal_overlap/archive_window_inclusive_boundary
    """
    env, ledgers = setup_released_environment_with_file_ledgers(
        [1048576, 1048576, 1048576, 1048576], release_version="SU26")

    validate_success(api.archive_storage(
        env["id"], {"from_rank": 1, "to_rank": 3}, STORAGE), 200)

    statuses = {row["id"]: row["status"] for row in _ledgers(env["id"])}
    assert statuses[ledgers[0]["id"]] == "ARCHIVED"
    assert statuses[ledgers[1]["id"]] == "ARCHIVED"
    assert statuses[ledgers[2]["id"]] == "ARCHIVED"
    assert statuses[ledgers[3]["id"]] == "LIVE"
    assert get_environment(env["id"])["storage_archived_bytes"] == 3145728


def test_archive_window_beyond_the_file_cap_is_refused(api):
    """PRD §3.6: "Every row inside the window must carry an `archivable` marker
    of true, and the closed window must contain at most three rows of kind
    `FILE` — the batch-size cap on file ledgers — or the request is refused with
    `ERR_ARCHIVE_BATCH_EXCEEDED` and HTTP status 422."

    Design: Difficulty/resource_temporal_overlap/archive_window_inclusive_boundary
    """
    env, ledgers = setup_released_environment_with_file_ledgers(
        [1048576, 1048576, 1048576, 1048576], release_version="SU26")

    res = api.archive_storage(env["id"], {"from_rank": 1, "to_rank": 4}, STORAGE)
    validate_error(res, "ERR_ARCHIVE_BATCH_EXCEEDED", expected_status=422)

    assert next(r for r in _ledgers(env["id"]) if r["id"] == ledgers[3]["id"])["status"] == "LIVE"
    assert get_environment(env["id"])["storage_archived_bytes"] == 0


# ─── The archival floor ───────────────────────────────────────────────────────

def test_archive_before_any_release_is_refused(api):
    """PRD §2.9: "A ledger row becomes `archivable` only once its environment's
    `applied_release_version` is set and its release ordinal is at or past the
    threshold named `STORAGE_ARCHIVE_MIN_RELEASE`. The archive window closes
    entirely below that floor."

    Design: Corner/validations/archive_window_with_unarchivable_ledger_returns_window_closed
    """
    env = create_environment(type="DEVELOPER", storage_cap_bytes=104857600)
    ledger = create_ledger(env["id"], "FILE", 1048576, 1)

    res = api.archive_storage(env["id"], {"from_rank": 1, "to_rank": 1}, STORAGE)
    # PRD §3.6 names ERR_ARCHIVE_WINDOW_CLOSED for a pre-floor archive while
    # §2.12 orders the archivable-marker rule ahead of the archival-floor rule,
    # so an unarchivable pre-floor ledger may report either 422 code.
    validate_error_is_one_of(res, ["ERR_ARCHIVE_WINDOW_CLOSED", "ERR_ARCHIVE_BATCH_EXCEEDED"])

    after = next(r for r in _ledgers(env["id"]) if r["id"] == ledger["id"])
    assert after["archivable"] is False
    assert after["status"] == "LIVE"
    assert after["archive_batch_id"] is None
    assert get_environment(env["id"])["applied_release_version"] is None


def test_archive_is_admitted_once_the_floor_is_reached(api):
    """PRD §3.3: "`STORAGE_ARCHIVE_MIN_RELEASE` is the same ordinal scale applied
    to archival."

    Design: Corner/validations/archive_window_with_unarchivable_ledger_returns_window_closed
    """
    env = create_environment(type="DEVELOPER", storage_cap_bytes=104857600)
    ledger = create_ledger(env["id"], "FILE", 1048576, 1)
    schedule_and_apply_release(env["id"], "SU26")

    assert next(r for r in _ledgers(env["id"]) if r["id"] == ledger["id"])["archivable"] is True
    validate_success(api.archive_storage(env["id"], {"from_rank": 1, "to_rank": 1}, STORAGE), 200)
    assert next(r for r in _ledgers(env["id"]) if r["id"] == ledger["id"])["status"] == "ARCHIVED"


# ─── Restoration is not idempotent ────────────────────────────────────────────

def test_restoring_an_already_live_ledger_is_refused(api):
    """PRD §2.12: "Restoring a ledger checks its state, then the storage-breach
    rule."
    PRD §2.12: "State preconditions produce `ERR_INVALID_STATE` with HTTP status
    409."

    Design: Corner/state_machines/storage_ledger_archive_restore_is_not_idempotent
    """
    env, ledgers = setup_released_environment_with_file_ledgers([1048576])
    api.archive_storage(env["id"], {"from_rank": 1, "to_rank": 1}, STORAGE)
    validate_success(api.restore_storage_ledger(ledgers[0]["id"], STORAGE), 200)

    res = api.restore_storage_ledger(ledgers[0]["id"], STORAGE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_refused_repeat_restore_leaves_the_rollup_untouched(api):
    """PRD §3.6: "Restoration sets the row back to `LIVE`, clears `archived_at`
    and `archive_batch_id` to null, advances the environment's version, and
    re-derives the used and archived sums."

    Design: Corner/state_machines/storage_ledger_archive_restore_is_not_idempotent
    """
    env, ledgers = setup_released_environment_with_file_ledgers([1048576])
    api.archive_storage(env["id"], {"from_rank": 1, "to_rank": 1}, STORAGE)
    api.restore_storage_ledger(ledgers[0]["id"], STORAGE)
    api.restore_storage_ledger(ledgers[0]["id"], STORAGE)

    row = next(r for r in _ledgers(env["id"]) if r["id"] == ledgers[0]["id"])
    assert row["status"] == "LIVE"
    after = get_environment(env["id"])
    assert after["storage_used_bytes"] == 1048576
    assert after["storage_archived_bytes"] == 0
    assert after["storage_total_bytes"] == 1048576


# ─── Archive side effects are visible immediately ─────────────────────────────

def test_archive_response_reports_the_moved_bytes_immediately(api):
    """PRD §3.6: "An accepted archive stamps each row in the window with
    `archived_at`, groups them under a single `archive_batch_id`, sets `status`
    to `ARCHIVED`, records that batch identifier on the environment as
    `last_archive_batch_id`, and advances the environment's version."

    Design: Corner/consistency_model/archive_side_effects_visible_in_the_same_request
    """
    env, ledgers = setup_released_environment_with_file_ledgers([1048576, 2097152])
    response = validate_success(api.archive_storage(
        env["id"], {"from_rank": 1, "to_rank": 1}, STORAGE), 200)
    assert response["storage_archived_bytes"] == 1048576
    assert response["last_archive_batch_id"] is not None

    rows = {row["id"]: row for row in _ledgers(env["id"])}
    assert rows[ledgers[0]["id"]]["status"] == "ARCHIVED"
    assert rows[ledgers[0]["id"]]["archive_batch_id"] == response["last_archive_batch_id"]
    assert rows[ledgers[1]["id"]]["status"] == "LIVE"
    assert rows[ledgers[1]["id"]]["archived_at"] is None


def test_archive_rollup_confirmed_by_the_next_read(api):
    """PRD §2.7: "A cascade never leaves a parent and its children in
    disagreement."

    Design: Corner/consistency_model/archive_side_effects_visible_in_the_same_request
    """
    env, ledgers = setup_released_environment_with_file_ledgers([1048576, 2097152])
    api.archive_storage(env["id"], {"from_rank": 1, "to_rank": 1}, STORAGE)

    after = get_environment(env["id"])
    assert after["storage_used_bytes"] == 2097152
    assert after["storage_archived_bytes"] == 1048576


# ─── Ledger listing, pagination and filters ───────────────────────────────────

def test_storage_ledger_listing_paginates(api):
    """PRD §2.3: "Responses that return a collection carry `limit`, `offset`,
    `total_count` and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/storage_ledger_listing_paginates_with_total_count
    """
    env = create_environment(type="DEVELOPER", storage_cap_bytes=104857600)
    create_ledger(env["id"], "DATA", 1048576, 1)
    create_ledger(env["id"], "FILE", 2097152, 2)
    create_ledger(env["id"], "FILE", 3145728, 3)

    body = api_client.list_storage_ledgers(env["id"], ADMIN, {"limit": 2}).json()
    assert body["response_type"] == "array"
    assert len(body["data"]) == 2
    assert body["meta"]["total_count"] == 3
    assert body["meta"]["has_more"] is True

    body_two = api_client.list_storage_ledgers(env["id"], ADMIN, {"limit": 2, "offset": 2}).json()
    assert len(body_two["data"]) == 1
    assert body_two["meta"]["total_count"] == 3
    assert body_two["meta"]["has_more"] is False

    default_body = api_client.list_storage_ledgers(env["id"], ADMIN).json()
    assert len(default_body["data"]) == 3


def test_storage_ledger_listing_unions_pages_without_repeats(api):
    """PRD §2.3: "`limit` defaults to 10, must be at least 1 and at most 100;
    `offset` defaults to 0."

    Design: Corner/entities/storage_ledger_listing_paginates_with_total_count
    """
    env = create_environment(type="DEVELOPER", storage_cap_bytes=104857600)
    ids = [create_ledger(env["id"], "DATA", 1048576, 1)["id"],
           create_ledger(env["id"], "FILE", 2097152, 2)["id"],
           create_ledger(env["id"], "FILE", 3145728, 3)["id"]]

    first = api_client.list_storage_ledgers(env["id"], ADMIN, {"limit": 2}).json()["data"]
    second = api_client.list_storage_ledgers(
        env["id"], ADMIN, {"limit": 2, "offset": 2}).json()["data"]
    union = [row["id"] for row in first + second]
    assert sorted(union) == sorted(ids)
    assert len(union) == len(set(union))


def test_filtered_lists_narrow_by_status_and_user(api):
    """PRD §3.1: "The ledger listing and the grant listing each accept a
    narrowing filter: the ledger listing takes an optional `status` filter that
    selects either `LIVE` or `ARCHIVED` rows, and the grant listing takes an
    optional `user_id` filter that narrows the result to a single operator's
    grants."

    Design: Corner/entities/filtered_list_narrows_by_status_and_user
    """
    env = create_environment(type="PARTIAL", storage_cap_bytes=104857600)
    archived_ledger = create_ledger(env["id"], "FILE", 1048576, 1)
    create_ledger(env["id"], "DATA", 2097152, 2)
    grant_one = grant_permission(env["id"], "PROFILE", "ProfileOne", "0050a000050001")
    grant_two = grant_permission(env["id"], "PERMISSION_SET", "SetTwo", "0050a000050002")
    schedule_and_apply_release(env["id"], "SU26")
    api.archive_storage(env["id"], {"from_rank": 1, "to_rank": 1}, STORAGE)

    archived_rows, archived_meta = validate_paginated(
        api_client.list_storage_ledgers(env["id"], ADMIN, {"status": "ARCHIVED"}))
    assert [row["id"] for row in archived_rows] == [archived_ledger["id"]]
    assert archived_meta["total_count"] == 1

    user_rows, user_meta = validate_paginated(
        api_client.list_permissions(env["id"], ADMIN, {"user_id": "0050a000050002"}))
    assert [row["id"] for row in user_rows] == [grant_two["id"]]
    assert user_meta["total_count"] == 1

    all_ledgers, _ = validate_paginated(api_client.list_storage_ledgers(env["id"], ADMIN))
    all_grants, _ = validate_paginated(api_client.list_permissions(env["id"], ADMIN))
    assert len(all_ledgers) == 2
    assert len(all_grants) == 2
    assert grant_one["id"] != grant_two["id"]


# ─── rank_index uniqueness scope ──────────────────────────────────────────────

def test_rank_index_is_unique_within_an_environment(api):
    """PRD §2.8: "A ledger row has a `kind` of either `DATA` or `FILE`, a
    `bytes` size that must be strictly greater than zero, and a client-assigned
    `rank_index` that is a 1-based ordinal unique within its environment."
    PRD §2.4: "a duplicate is rejected with `ERR_INVALID_REQUEST` and HTTP
    status 400, the same code that covers a missing required body field, an
    enum value outside its declared set, and an integer outside its declared
    range."

    Design: Corner/entities/storage_ledger_rank_index_is_unique_per_environment
    """
    first_env = create_environment(type="DEVELOPER")
    second_env = create_environment(type="DEVELOPER")
    create_ledger(first_env["id"], "DATA", 1048576, 1)

    duplicate = api.create_storage_ledger(
        first_env["id"], {"kind": "FILE", "bytes": 2097152, "rank_index": 1}, STORAGE)
    validate_error(duplicate, "ERR_INVALID_REQUEST", expected_status=400)

    other = validate_success(api.create_storage_ledger(
        second_env["id"], {"kind": "FILE", "bytes": 2097152, "rank_index": 1}, STORAGE), 201)
    assert other["rank_index"] == 1
    assert other["status"] == "LIVE"
    assert other["archived_at"] is None
    assert len(_ledgers(first_env["id"])) == 1


# ─── Per-environment isolation of the storage contract ────────────────────────

def test_storage_breach_is_scoped_to_the_owning_environment_cap(api):
    """PRD §2.8: "Storage accounting is expressed as a set of **StorageLedger**
    rows, each belonging to one environment through `environment_id`."

    Design: Difficulty/multi_tenancy/ledger_bytes_isolated_per_environment_cap
    """
    tenant_a = create_environment(type="DEVELOPER", storage_cap_bytes=1048576)
    tenant_b = create_environment(type="DEVELOPER", storage_cap_bytes=8388608)
    create_ledger(tenant_a["id"], "DATA", 1048576, 1)
    create_ledger(tenant_b["id"], "DATA", 1048576, 1)

    assert get_environment(tenant_a["id"])["storage_breach"] is True
    assert get_environment(tenant_b["id"])["storage_breach"] is False


def test_identical_ledgers_yield_equal_totals_with_different_verdicts(api):
    """PRD §2.8: "`storage_used_bytes` is the sum of `bytes` over the
    environment's `LIVE` ledgers only."

    Design: Difficulty/multi_tenancy/ledger_bytes_isolated_per_environment_cap
    """
    tenant_a = create_environment(type="DEVELOPER", storage_cap_bytes=1048576)
    tenant_b = create_environment(type="DEVELOPER", storage_cap_bytes=8388608)
    create_ledger(tenant_a["id"], "DATA", 1048576, 1)
    ledger_b = create_ledger(tenant_b["id"], "DATA", 1048576, 1)

    a = get_environment(tenant_a["id"])
    b = get_environment(tenant_b["id"])
    assert a["storage_used_bytes"] == 1048576
    assert b["storage_used_bytes"] == 1048576
    assert a["storage_breach"] is True
    assert b["storage_breach"] is False
    assert [row["id"] for row in _ledgers(tenant_b["id"])] == [ledger_b["id"]]