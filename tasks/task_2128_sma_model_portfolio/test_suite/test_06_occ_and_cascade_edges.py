"""Optimistic concurrency on parent rows, conditional cascade hops, sleeve pinning
and the composition of list filters with pagination."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_version,
    create_active_distribution,
    create_approved_version,
    create_distribution_payload,
    create_harvest_proposal_payload,
    create_sponsor,
    get_account,
    get_model_version,
    open_account,
    setup_harvest_ready_account,
    setup_platform,
    sleeve,
    sleeves_payload,
    submit_version,
    suspend_account,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
MANAGER_HEADERS = TEST_USERS["portfolio_manager_headers"]


def _list_ids(response):
    rows, meta = validate_paginated(response)
    return [row["id"] for row in rows], meta


def test_distribution_creation_rejects_a_stale_model_version_view(api):
    """PRD §2.7: "If that number does not equal the model version's current `version` at the moment the request is processed, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_model_version_rejects_the_second_distribution
    """
    env = setup_platform(
        securities=[("ALFA", "Alfa Industrials", 10000)],
        sleeves=[("ALFA", 10000)],
    )
    northline = env["sponsor"]
    southline = create_sponsor(
        platform_code="SOUT", name="Southline Advisors", revenue_share_bps=2500
    )
    version_id = env["model_version"]["id"]
    observed_version = env["model_version"]["version"]

    first = api.create_distribution(
        create_distribution_payload(
            northline["id"],
            version_id,
            observed_version,
            "2026-01-01T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    validate_success(first, 201)

    stale = api.create_distribution(
        create_distribution_payload(
            southline["id"],
            version_id,
            observed_version,
            "2026-01-01T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

    after_refusal = get_model_version(version_id)
    assert after_refusal["distribution_count"] == 1
    assert after_refusal["version"] == observed_version + 1

    retry = api.create_distribution(
        create_distribution_payload(
            southline["id"],
            version_id,
            after_refusal["version"],
            "2026-01-01T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    second = validate_success(retry, 201)
    assert second["sponsor_id"] == southline["id"]
    assert get_model_version(version_id)["distribution_count"] == 2


def test_harvest_proposal_creation_rejects_a_stale_account_view(api):
    """PRD §2.7: "If that number does not equal the account's current `version`, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_account_rejects_the_second_harvest_proposal
    """
    env = setup_harvest_ready_account(
        securities=[("ALFA", "Alfa Industrials", 10000), ("BETA", "Beta Materials", 10000)],
        sleeves=[("ALFA", 5000), ("BETA", 5000)],
        harvest_budget_cents=500000,
        positions=[
            ("ALFA", 100, 1200000, "TRANSFER_IN"),
            ("BETA", 100, 1200000, "TRANSFER_IN"),
        ],
    )
    account_id = env["account"]["id"]
    alfa = env["securities"]["ALFA"]
    beta = env["securities"]["BETA"]
    observed_version = get_account(account_id)["version"]

    first = api.create_harvest_proposal(
        create_harvest_proposal_payload(account_id, alfa["id"], 100, observed_version),
        MANAGER_HEADERS,
    )
    first_proposal = validate_success(first, 201)

    stale = api.create_harvest_proposal(
        create_harvest_proposal_payload(account_id, beta["id"], 100, observed_version),
        MANAGER_HEADERS,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)

    ids, meta = _list_ids(
        api.list_harvest_proposals(MANAGER_HEADERS, params={"account_id": account_id})
    )
    assert meta["total_count"] == 1
    assert ids == [first_proposal["id"]]

    refreshed_version = get_account(account_id)["version"]
    assert refreshed_version == observed_version + 1

    retry = api.create_harvest_proposal(
        create_harvest_proposal_payload(account_id, beta["id"], 100, refreshed_version),
        MANAGER_HEADERS,
    )
    second_proposal = validate_success(retry, 201)
    assert second_proposal["security_id"] == beta["id"]
    assert second_proposal["status"] == "PROPOSED"

    still_open = validate_success(
        api.get_harvest_proposal(first_proposal["id"], MANAGER_HEADERS), 200
    )
    assert still_open["status"] == "PROPOSED"


def test_publication_fan_out_skips_an_account_that_is_already_suspended(api):
    """PRD §3.3: "This cascade is conditional, not blanket: an account already in `SUSPENDED` or already in `PENDING_IMPLEMENTATION` is skipped entirely and none of those fields are written."

    Design: Corner/cross_cutting_layers/publish_cascade_skips_a_suspended_account
    """
    env = setup_platform(
        securities=[("ALFA", "Alfa Industrials", 10000)],
        sleeves=[("ALFA", 10000)],
        sponsor_overrides={"implementation_lag_days": 2, "min_account_value_cents": 0},
    )
    v1 = env["model_version"]
    distribution = create_active_distribution(env["sponsor"]["id"], v1["id"])
    synced = open_account(env, "ACC-001")
    frozen = open_account(env, "ACC-002")
    suspend_account(frozen["id"])

    v2 = create_approved_version(
        env["model"]["id"], [("ALFA", 10000)], env["securities"]
    )
    published = validate_success(
        api.publish_model_version(v2["id"], MANAGER_HEADERS), 200
    )
    assert published["status"] == "PUBLISHED"

    lapsed = validate_success(
        api.get_distribution(distribution["id"], MANAGER_HEADERS), 200
    )
    assert lapsed["status"] == "LAPSED"

    notified = get_account(synced["id"])
    assert notified["implementation_status"] == "PENDING_IMPLEMENTATION"
    assert notified["pending_model_version_id"] == v2["id"]
    assert notified["notified_at"] == "2026-08-01T00:00:00.000Z"
    assert notified["implementation_deadline"] == "2026-08-03T00:00:00.000Z"

    skipped = get_account(frozen["id"])
    assert skipped["implementation_status"] == "SUSPENDED"
    assert skipped["pending_model_version_id"] is None
    assert skipped["notified_at"] is None
    assert skipped["implementation_deadline"] is None
    assert skipped["current_model_version_id"] == v1["id"]

    ids, meta = _list_ids(
        api.list_accounts(ADMIN_HEADERS, params={"pending_model_version_id": v2["id"]})
    )
    assert meta["total_count"] == 1
    assert ids == [synced["id"]]


def test_sleeve_edit_is_unreachable_once_the_version_has_been_approved(api):
    """PRD §2.6: "Opening an account against a model that has never published a version fails with `ERR_MODEL_NOT_PUBLISHED`; requesting a rebalance on an account whose `implementation_status` is not `DRIFTED` fails with `ERR_ACCOUNT_NOT_DRIFTED`; every other from-state mismatch, including requesting an implementation on an account that is not in `PENDING_IMPLEMENTATION`, fails with `ERR_INVALID_STATE`."

    Design: Corner/cross_cutting_layers/approved_model_version_rejects_a_sleeve_edit
    """
    env = setup_platform(
        securities=[("ALFA", "Alfa Industrials", 10000), ("BETA", "Beta Materials", 5000)],
        sleeves=[("ALFA", 6000), ("BETA", 4000)],
        publish=False,
    )
    alfa = env["securities"]["ALFA"]
    beta = env["securities"]["BETA"]
    version_id = env["model_version"]["id"]

    submit_version(version_id)
    approved = approve_version(version_id)
    version_after_approval = approved["version"]

    edit = api.replace_sleeves(
        version_id,
        sleeves_payload(
            [sleeve(alfa["id"], 9000), sleeve(beta["id"], 1000)]
        ),
        MANAGER_HEADERS,
    )
    validate_error(edit, ApiErrorId.ERR_INVALID_STATE.value)

    unchanged = get_model_version(version_id)
    assert unchanged["status"] == "APPROVED"
    assert unchanged["sleeve_count"] == 2
    assert unchanged["total_target_weight_bps"] == 10000
    assert unchanged["version"] == version_after_approval

    stored = {s["security_id"]: s["target_weight_bps"] for s in unchanged["sleeves"]}
    assert stored[alfa["id"]] == 6000
    assert stored[beta["id"]] == 4000


def test_account_list_filter_and_page_window_compose(api):
    """PRD §2.3: "For every list response, the `meta` object carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` counts every row matching the filters before the page window is applied and `has_more` is true when rows remain beyond the current window."

    Design: Corner/cross_cutting_layers/accounts_list_filters_by_state_dimension_and_paginates
    """
    env = setup_platform(
        securities=[("ALFA", "Alfa Industrials", 10000)],
        sleeves=[("ALFA", 10000)],
    )
    sponsor_id = env["sponsor"]["id"]
    first = open_account(env, "ACC-001")
    second = open_account(env, "ACC-002")
    third = open_account(env, "ACC-003")
    suspend_account(second["id"])

    reader = env["sponsor_headers"]

    filtered_ids, filtered_meta = _list_ids(
        api.list_accounts(
            reader,
            params={"sponsor_id": sponsor_id, "implementation_status": "SYNCED"},
        )
    )
    assert len(filtered_ids) == 2
    assert filtered_meta["total_count"] == 2
    assert filtered_meta["has_more"] is False
    assert filtered_ids[0] == first["id"]
    assert filtered_ids == [first["id"], third["id"]]

    page1_ids, page1_meta = _list_ids(
        api.list_accounts(
            reader, params={"sponsor_id": sponsor_id, "limit": 2, "offset": 0}
        )
    )
    assert len(page1_ids) == 2
    assert page1_meta["total_count"] == 3
    assert page1_meta["limit"] == 2
    assert page1_meta["offset"] == 0
    assert page1_meta["has_more"] is True
    assert page1_ids == [first["id"], second["id"]]

    page2_ids, page2_meta = _list_ids(
        api.list_accounts(
            reader, params={"sponsor_id": sponsor_id, "limit": 2, "offset": 2}
        )
    )
    assert len(page2_ids) == 1
    assert page2_meta["total_count"] == 3
    assert page2_meta["offset"] == 2
    assert page2_meta["has_more"] is False
    assert page2_ids == [third["id"]]
