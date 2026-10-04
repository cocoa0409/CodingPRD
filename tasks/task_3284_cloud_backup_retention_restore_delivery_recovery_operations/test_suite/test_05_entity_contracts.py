"""Corner claims about entity creation, retrieval and shape."""
import pytest

from test_helpers import (
    api_client as api,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
    is_valid_uuid,
    ApiErrorId,
    GB_10,
    GB_50,
    GB_100,
    BACKUP,
    SYS,
    create_account,
    create_group,
    create_policy,
    create_agent,
    activate_agent,
    create_set,
    complete_initial,
    open_billing_period,
    close_billing_period,
    record_version,
    set_clock,
    setup_personal_scenario,
    NON_EXISTENT_UUID,
)


def test_account_creation_returns_every_declared_field_and_starts_active():
    """PRD §3.1: "On creation the account's `status` is `ACTIVE`, its
    `retention_days` is seeded to the tier default, and its
    `deposit_held_cents` is 0."
    PRD §2.4: "Every primary resource in the system is addressed by an `id`
    string that is a server-minted UUID carrying no type prefix"

    Design: Corner/entities/account_create_returns_every_declared_field_and_starts_active
    """
    set_clock()
    response = api.create_account(
        {"name": "Northwind Personal", "account_type": "PERSONAL", "region": "US_WEST",
         "storage_tier": "PLUS", "encryption_key_id": "aes-256-key-personal", "usage_gb": 0},
        SYS)
    account = validate_success(response, 201)

    assert response.json()["response_type"] == "object"
    assert account["name"] == "Northwind Personal"
    assert account["account_type"] == "PERSONAL"
    assert account["region"] == "US_WEST"
    assert account["storage_tier"] == "PLUS"
    assert account["status"] == "ACTIVE"
    assert account["version"] == 1
    assert account["deposit_held_cents"] == 0
    assert account["usage_gb"] == 0
    assert account["restore_download_gb"] == 0
    assert is_valid_uuid(account["id"])
    assert account["created_at"] and account["updated_at"]


def test_backup_set_read_returns_the_stored_configuration_unchanged():
    """PRD §3.2: "A new set starts in `PROVISIONING` and receives an
    agent-scoped monotonic `created_seq`."
    PRD §3.3: "`is_initial_flush` is true while the set is in `INITIAL_RUNNING`"
    PRD §3.2: "`retention_floor_utc` is the oldest change instant still
    recoverable"

    Design: Corner/entities/backup_set_get_returns_the_stored_configuration_unchanged
    """
    scenario = setup_personal_scenario(durability_class="DEEP_ARCHIVE")
    fetched = get_success_data(api.get_backup_set(scenario["set"]["id"], BACKUP))

    assert fetched["state"] == "PROVISIONING"
    assert fetched["durability_class"] == "DEEP_ARCHIVE"
    assert fetched["is_initial_flush"] is False
    assert fetched["version_chain_depth"] == 0
    assert fetched["retention_floor_utc"] is None
    assert fetched["agent_id"] == scenario["agent"]["id"]
    assert fetched["account_id"] == scenario["account"]["id"]


def test_agent_list_paginates_and_reports_total_count_and_has_more():
    """PRD §2.3: "`limit` caps the number of records returned, defaulting to 10
    when it is not supplied, with a minimum of 1 and a maximum of 100. `offset`
    gives the number of leading records to skip and defaults to 0."
    PRD §2.3: "List responses repeat the pagination state in the response
    envelope's `meta` object through four fields: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/agents_list_paginates_and_reports_total_count_and_has_more
    """
    scenario = setup_personal_scenario()
    account_id = scenario["account"]["id"]
    create_agent(account_id, scenario["group"]["id"], hostname="nw-laptop-02", os_type="WINDOWS")
    create_agent(account_id, scenario["group"]["id"], hostname="nw-laptop-03", os_type="LINUX")

    page, meta = validate_paginated(api.list_agents(
        BACKUP, {"account_id": account_id, "limit": 2, "offset": 0}))
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    page2, meta2 = validate_paginated(api.list_agents(
        BACKUP, {"account_id": account_id, "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    filtered, meta_filter = validate_paginated(api.list_agents(
        BACKUP, {"account_id": account_id}))
    assert len(filtered) == 3
    assert meta_filter["total_count"] == 3

    defaulted, meta_default = validate_paginated(api.list_agents(
        BACKUP, {"account_id": account_id}))
    assert meta_default["limit"] == 10
    assert meta_default["offset"] == 0


def test_storage_pod_get_with_unknown_id_returns_storage_pod_not_found():
    """PRD §2.9: "At the third level, every identifier referenced by the
    request — in the path and in the body — must resolve to an existing
    resource; the not-found family is `ERR_ACCOUNT_NOT_FOUND`,
    `ERR_GROUP_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_BACKUP_SET_NOT_FOUND`,
    `ERR_RESTORE_REQUEST_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_RETENTION_CHANGE_NOT_FOUND`, `ERR_DELETION_REQUEST_NOT_FOUND`,
    `ERR_STORAGE_POD_NOT_FOUND`, `ERR_FILE_VERSION_NOT_FOUND`,
    `ERR_POLICY_NOT_FOUND`, and `ERR_BILLING_PERIOD_NOT_FOUND`, all at HTTP 404."

    Design: Corner/entities/storage_pod_get_with_unknown_id_returns_storage_pod_not_found
    """
    set_clock()
    response = api.get_storage_pod("00000000-0000-4000-8000-000000000000", SYS)
    error = validate_error(response, ApiErrorId.ERR_STORAGE_POD_NOT_FOUND)
    assert error["error_id"] == "ERR_STORAGE_POD_NOT_FOUND"
    assert response.json()["response_type"] == "error"
    assert error.get("message")


def test_file_version_creation_without_content_hash_is_rejected_as_malformed():
    """PRD §2.9: "A malformed body, an unknown field, or an out-of-range value
    is rejected at the request-shape boundary with `ERR_INVALID_REQUEST`,
    independently of the seven levels above."
    PRD §3.3: "A `BackupOperator` records one by supplying the `file_path` —
    the absolute client path of the changed file — a `version_number`, an
    `operation` of `CREATE`, `MODIFY`, or `DELETE`, a `size_bytes` count that is
    0 for a `DELETE`, a `content_hash`, and the `event_utc` instant"

    Design: Corner/entities/file_version_create_missing_content_hash_returns_invalid_request
    """
    scenario = setup_personal_scenario()
    set_id = scenario["set"]["id"]
    record_version(set_id, "/home/u/archive.tar", 1, "CREATE", GB_100,
                   "sha256-arc-v1", "2026-09-10T00:00:00Z")

    response = api.create_file_version(
        set_id,
        {"file_path": "/home/u/second.bin", "version_number": 1, "operation": "CREATE",
         "size_bytes": 1024, "event_utc": "2026-09-11T00:00:00Z"},
        BACKUP)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    rows = get_success_data(api.list_file_versions(set_id, BACKUP))
    assert len(rows) == 1
    backup_set = get_success_data(api.get_backup_set(set_id, BACKUP))
    assert backup_set["version_chain_depth"] == 1


def test_account_created_without_a_storage_tier_defaults_to_basic_pricing():
    """PRD §3.1: "A customer relationship begins when an `AccountOwner` or a
    `SystemOperator` creates an account with a customer-facing `name`, an
    `account_type`, a `region`, a server-side `encryption_key_id`, and an
    optional `storage_tier` that defaults to `BASIC`."
    PRD §3.1: "it selects the per-gigabyte monthly storage rate: `BASIC` bills
    at 6 cents per gigabyte-month, `PLUS` at 5, and `PRO` at 4."

    Design: Corner/entities/account_create_omitting_storage_tier_defaults_to_basic
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account(name="Northwind Default", region="US_EAST",
                             storage_tier=None, encryption_key_id="aes-256-key-default")
    group = create_group(account["id"], name="Default Group", retention_days_override=None)
    create_policy(group["id"])
    agent = create_agent(account["id"], group["id"], hostname="nw-laptop-09", os_type="LINUX")
    activate_agent(agent["id"])
    backup_set = create_set(agent["id"], account["id"])
    record_version(backup_set["id"], "/home/u/ten.bin", 1, "CREATE", GB_10,
                   "sha256-ten-v1", "2026-09-02T00:00:00Z")
    complete_initial(backup_set["id"])

    fetched = get_success_data(api.get_account(account["id"], SYS))
    assert fetched["storage_tier"] == "BASIC"

    period = open_billing_period(account["id"])
    closed = close_billing_period(period["id"])
    assert closed["usage_gb_avg"] == pytest.approx(10.0, abs=0.01)
    assert closed["storage_fee_cents"] == 0
    assert closed["initial_upload_credit_cents"] == 60


def test_backup_set_storage_gb_is_recomputed_on_read_after_a_larger_modify():
    """PRD §3.2: "`storage_gb` is the sum of its live file-version sizes divided
    by `GB_BYTES` and floored to two decimal places"
    PRD §3.1: "The `usage_gb` value is the live byte total divided by `GB_BYTES`
    and rounded half up to two decimal places, and `peak_usage_gb` is the larger
    of its own prior value and the freshly computed `usage_gb`."

    Design: Corner/entities/backup_set_storage_gb_is_computed_on_read_and_never_stored
    """
    scenario = setup_personal_scenario()
    set_id = scenario["set"]["id"]
    account_id = scenario["account"]["id"]
    record_version(set_id, "/home/u/a.bin", 1, "CREATE", GB_50, "sha256-a-v1",
                   "2026-09-02T00:00:00Z")
    record_version(set_id, "/home/u/b.bin", 1, "CREATE", GB_50, "sha256-b-v1",
                   "2026-09-02T00:00:00Z")
    complete_initial(set_id)

    before = get_success_data(api.get_backup_set(set_id, BACKUP))
    assert before["storage_gb"] == pytest.approx(100.0, abs=0.01)

    record_version(set_id, "/home/u/a.bin", 2, "MODIFY", 85899345920, "sha256-a-v2",
                   "2026-09-03T00:00:00Z")
    after = get_success_data(api.get_backup_set(set_id, BACKUP))
    account = get_success_data(api.get_account(account_id, SYS))

    assert after["storage_gb"] == pytest.approx(130.0, abs=0.01)
    assert account["usage_gb"] == pytest.approx(130.0, abs=0.01)
    assert account["peak_usage_gb"] == pytest.approx(130.0, abs=0.01)


def test_file_version_creation_ignores_a_client_supplied_identity():
    """PRD §2.4: "The twelfth entity, `FileVersion`, is immutable after
    creation and therefore carries only `id` and `created_at`; it has neither
    `updated_at` nor `version`."
    PRD §3.3: "Its `recoverable_until_utc` instant is its `event_utc` plus the
    effective retention window — the group's `group_retention_days`"

    Design: Corner/entities/file_version_create_client_supplied_identity_is_ignored_input
    """
    scenario = setup_personal_scenario()
    set_id = scenario["set"]["id"]
    response = api.create_file_version(
        set_id,
        {"file_path": "/home/u/ignored.bin", "version_number": 1, "operation": "CREATE",
         "size_bytes": 1024, "content_hash": "sha256-ign-v1",
         "event_utc": "2026-09-10T00:00:00Z", "version": 99,
         "id": "00000000-0000-4000-8000-0000000000ff"},
        BACKUP)
    created = validate_success(response, 201)

    assert created["id"] != "00000000-0000-4000-8000-0000000000ff"
    assert is_valid_uuid(created["id"])
    assert created["is_deleted"] is False
    assert created["is_expired"] is False
    # PRD 3.3: recoverable_until_utc is event_utc (2026-09-10) plus the group's
    # 45-day window.  PRD does not pin this computed field's serialization
    # precision, so compare the instant rather than the raw string.
    from datetime import datetime
    assert datetime.fromisoformat(
        created["recoverable_until_utc"].replace("Z", "+00:00")) == datetime.fromisoformat(
        "2026-10-25T00:00:00+00:00")
    assert created["version_number"] == 1
    assert created.get("updated_at") is None
    assert created.get("version") is None


def test_agent_creation_with_an_out_of_enum_os_type_is_rejected():
    """PRD §3.2: "The `os_type` is `WINDOWS`, `MACOS`, or `LINUX`."
    PRD §2.9: "A malformed body, an unknown field, or an out-of-range value is
    rejected at the request-shape boundary with `ERR_INVALID_REQUEST`"

    Design: Corner/entities/agent_create_with_out_of_enum_os_type_returns_invalid_request
    """
    scenario = setup_personal_scenario(create_backup_set=False, activate=False)
    response = api.create_agent(
        {"account_id": scenario["account"]["id"], "group_id": scenario["group"]["id"],
         "hostname": "nw-bad-os", "os_type": "SOLARIS", "license_type": "PERSONAL",
         "throttle_month": 202609},
        BACKUP)
    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    assert error["error_id"] == "ERR_INVALID_REQUEST"

    # PRD 3.2: enumeration is a *closed* enum of agency states; the fixture has
    # already registered the account's one legitimate agent, so the rejected
    # create leaves exactly that one row rather than adding a SOLARIS agent.
    rows = get_success_data(api.list_agents(
        BACKUP, {"account_id": scenario["account"]["id"], "status": "SOLARIS"}))
    assert rows == []
    group = get_success_data(api.get_backup_group(scenario["group"]["id"], BACKUP))
    assert group["agent_count"] == 0


def test_backup_set_creation_with_an_unknown_agent_reports_the_agent_as_missing():
    """PRD §2.10: "the identifiers carried in a payload are validated left to
    right in path order and then in the order the input fields are declared."
    PRD §2.10: "the request is rejected at the first identifier that does not
    resolve, with the not-found error corresponding to that specific resource."

    Design: Corner/entities/backup_set_create_with_unknown_agent_returns_agent_not_found
    """
    set_clock()
    response = api.create_backup_set(
        {"agent_id": "00000000-0000-4000-8000-000000000001",
         "account_id": "00000000-0000-4000-8000-000000000002",
         "durability_class": "STANDARD"},
        BACKUP)
    error = validate_error(response, ApiErrorId.ERR_AGENT_NOT_FOUND)
    assert error["error_id"] != "ERR_ACCOUNT_NOT_FOUND"

    rows = get_success_data(api.list_backup_sets(
        BACKUP, {"account_id": "00000000-0000-4000-8000-000000000002"}))
    assert rows == []