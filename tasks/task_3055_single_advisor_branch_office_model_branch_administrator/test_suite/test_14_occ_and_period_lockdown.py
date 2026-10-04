"""Endpoint rules: branch OCC, finalized-period lockdown, FK reachability."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, validate_paginated,
    get_success_data, api_client, ApiErrorId,
    create_territory, create_branch, create_period,
    post_charge, set_clock,
)

ADMIN = TEST_USERS["home_office_admin_headers"]


def test_patch_branch_stale_version_occ():
    """PRD §2.4: "Updating a branch's book attributes requires the request to
    carry `expected_branch_version` equal to the branch's current `version`;
    if another writer has since updated the branch — advancing its version and
    possibly recomputing its tier — the update is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/endpoints/patch_branch_stale_version_occ
    """
    territory = create_territory()
    branch, _ = create_branch(territory["id"])
    original_version = branch["version"]

    first = validate_success(api_client.patch_branch(
        branch["id"],
        {"expected_branch_version": original_version, "household_count": 10},
        ADMIN,
    ))
    assert first["version"] == original_version + 1
    assert first["household_count"] == 10

    validate_error(
        api_client.patch_branch(
            branch["id"],
            {"expected_branch_version": original_version, "household_count": 20},
            ADMIN,
        ),
        ApiErrorId.ERR_STALE_VERSION,
    )
    assert get_success_data(
        api_client.get_branch(branch["id"], ADMIN)
    )["household_count"] == 10


def test_charge_post_to_finalized_period():
    """PRD §3.5: "A charge may never post to a `FINALIZED` period — such
    attempts are rejected with `ERR_PERIOD_FINALIZED`."

    Design: Corner/endpoints/charge_post_to_finalized_period
    """
    territory = create_territory()
    branch, _ = create_branch(territory["id"])
    p1 = create_period(branch["id"], "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
    p2 = create_period(branch["id"], "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z")

    set_clock("2026-10-02T00:00:00Z")
    validate_success(api_client.close_period(p1["id"], ADMIN))
    validate_success(api_client.finalize_period(p1["id"], ADMIN))

    validate_error(
        api_client.post_charge(
            p1["id"],
            {
                "branch_id": branch["id"],
                "charge_type": "EQUIPMENT",
                "amount_cents": 5000,
            },
            ADMIN,
        ),
        ApiErrorId.ERR_PERIOD_FINALIZED,
    )

    # The identical charge on the OPEN period succeeds.
    charge = validate_success(
        api_client.post_charge(
            p2["id"],
            {
                "branch_id": branch["id"],
                "charge_type": "EQUIPMENT",
                "amount_cents": 5000,
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert charge["status"] == "POSTED"


def test_branch_children_reverse_reachability():
    """PRD §4: "GET `/branch-office/branches/{id}/financial-periods` — List
    the branch's financial periods."
    PRD §4: "GET `/branch-office/branches/{id}/goodwill-transfers` — List
    goodwill transfers of the branch."
    PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."

    Design: Corner/endpoints/fk_reverse_reachability_branch_children
    """
    territory = create_territory()
    branch_a, _ = create_branch(territory["id"])
    branch_b, _ = create_branch(territory["id"])
    period = create_period(branch_a["id"])

    periods, meta = validate_paginated(
        api_client.list_branch_financial_periods(branch_a["id"], ADMIN)
    )
    assert meta["total_count"] == 1
    assert periods[0]["id"] == period["id"]
    assert periods[0]["branch_id"] == branch_a["id"]

    transfers, meta2 = validate_paginated(
        api_client.list_branch_goodwill_transfers(branch_b["id"], ADMIN)
    )
    assert transfers == []
    assert meta2["total_count"] == 0
