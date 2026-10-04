"""Site agreement lifecycle: renewal window cycle, renewal rejection
outside the window, and optimistic concurrency on activation."""
from test_helpers import (
    ApiClient,
    ApiErrorId,
    TEST_USERS,
    activate_agreement,
    create_center,
    create_center_with_active_agreement,
    draft_agreement,
    get_center,
    renew_agreement,
    run_ops,
    set_clock,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["admin_headers"]
MGR = TEST_USERS["manager_headers"]


def test_agreement_renewal_cycle(api: ApiClient):
    """PRD §3.1: "When the number of days from the current clock date to `end_date` falls between 0 and 60 inclusive, an `ACTIVE` agreement is flagged `RENEWAL_DUE`."
    PRD §3.1: "Renewal is open only in that window: a `PlatformAdmin` presents a `new_end_date` strictly later than the current `end_date` — anything else is `ERR_VALIDATION` — and the agreement returns to `ACTIVE` with its `end_date` extended and the center's posture recomputed."

    Design: Difficulty/non_linear_state_machine/agreement_renewal_cycle
    """
    set_clock()
    center = create_center(
        name="Epsilon Center",
        airport_code="SEA",
        occupancy_cap=30,
        required_daily_confirmed_assignments=2,
    )
    agreement = draft_agreement(center["id"], end_date="2026-10-15")
    activate_agreement(agreement["id"], center["version"])

    # 2026-09-20 is 25 days before end_date 2026-10-15: inside the 60-day window.
    set_clock("2026-09-20T00:00:00Z")
    run_ops(center["id"])
    rows, _meta = validate_paginated(api.list_site_agreements(center["id"], MGR))
    assert len(rows) == 1 and rows[0]["id"] == agreement["id"]
    assert rows[0]["status"] == "RENEWAL_DUE", (
        f"agreement inside the renewal window must be flagged RENEWAL_DUE, "
        f"got {rows[0]['status']!r}"
    )

    renewed = renew_agreement(agreement["id"], "2027-10-15")
    assert renewed["status"] == "ACTIVE", (
        f"renewal returns the agreement to ACTIVE, got {renewed['status']!r}"
    )
    assert renewed["end_date"] == "2027-10-15", (
        f"renewal extends end_date, got {renewed['end_date']!r}"
    )


def test_renew_rejected_outside_window(api: ApiClient):
    """PRD §3.1: "Attempting renewal on an agreement that is not `RENEWAL_DUE`, including one still plainly inside its active term, is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`."

    Design: Corner/validations/renew_rejected_outside_window
    """
    set_clock()
    center, agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Mem Center",
            "airport_code": "MSY",
            "occupancy_cap": 10,
            "required_daily_confirmed_assignments": 1,
        },
        agreement_overrides={"end_date": "2027-08-31"},
    )
    assert agreement["status"] == "ACTIVE"
    resp = api.renew_site_agreement(
        agreement["id"], {"new_end_date": "2028-08-31"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN)
    rows, _meta = validate_paginated(api.list_site_agreements(center["id"], MGR))
    assert rows[0]["status"] == "ACTIVE"
    assert rows[0]["end_date"] == "2027-08-31", (
        f"a rejected renewal must not move end_date, got {rows[0]['end_date']!r}"
    )


def test_occ_agreement_activate_stale_version(api: ApiClient):
    """PRD §2.5: "Activating a site agreement requires `expected_center_version` matching the center's current `version`, because activation supersedes any currently active agreement of the same center."
    PRD §2.5: "In all three cases, if the parent entity's `version` has advanced since the client last read it, the write is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is applied."
    PRD §3.1: "On success, any other `ACTIVE` agreement of the same center cascades to `TERMINATED`, the center's `active_agreement_id` is set to the newly activated agreement, posture is recomputed against current coverage, and the center's `version` increments by one."

    Design: Corner/complexity_layers/occ_agreement_activate_stale_version
    """
    set_clock()
    center = create_center(
        name="Mem2 Center",
        airport_code="SPS",
        occupancy_cap=10,
        required_daily_confirmed_assignments=1,
    )
    stale_version = center["version"]
    a1 = draft_agreement(center["id"])
    activate_agreement(a1["id"], stale_version)
    a2 = draft_agreement(
        center["id"],
        facility_space_sqft=400,
        utilities_included=False,
        access_terms="badge-plus",
    )

    # The first activation bumped Center.version, so the pre-activation
    # version the client still holds is stale.
    resp = api.activate_site_agreement(
        a2["id"], {"expected_center_version": stale_version}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    rows, _meta = validate_paginated(api.list_site_agreements(center["id"], ADMIN))
    by_id = {row["id"]: row for row in rows}
    assert by_id[a1["id"]]["status"] == "ACTIVE", (
        "a stale-version rejection applies nothing: the first agreement "
        "must remain ACTIVE"
    )
    assert by_id[a2["id"]]["status"] == "SUBMITTED", (
        "a stale-version rejection applies nothing: the second agreement "
        "must remain SUBMITTED (no supersede)"
    )
    assert get_center(center["id"])["active_agreement_id"] == a1["id"]
