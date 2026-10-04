"""Boundary precision: stream caps, download allowances, resolution entitlement."""
from test_helpers import (
    ApiErrorId,
    create_account_with_device,
    get_success_data,
    validate_error,
    validate_paginated,
)


def test_stream_limit_exact_boundary_admission(api):
    """PRD §3.7: "the account-wide count of `ACTIVE` playback sessions across all
    members of the account must be strictly below the tier's stream cap — 1 for
    `BASIC`, 2 for `STANDARD`, 4 for `PREMIUM` — or the request is rejected with
    `ERR_STREAM_LIMIT_REACHED` (HTTP 409); at the boundary, a session is admitted
    when the active count is exactly one below the cap and rejected when it equals
    the cap."

    Design: Difficulty/boundary_precision_check/stream_limit_exact_boundary
    """
    account, household, device, owner_h = create_account_with_device(
        email="bp1@x.com", plan_tier="STANDARD", trust=True
    )
    owner_id = account["owner_member_id"]
    payload = {"device_id": device["id"], "requested_resolution": "HD"}

    s1 = get_success_data(api.start_playback(owner_id, payload, owner_h))
    s2 = get_success_data(api.start_playback(owner_id, payload, owner_h))
    assert s1["status"] == "ACTIVE"
    assert s2["status"] == "ACTIVE"

    resp = api.start_playback(owner_id, payload, owner_h)
    validate_error(resp, ApiErrorId.ERR_STREAM_LIMIT_REACHED)

    owner_after = get_success_data(api.get_member(owner_id, owner_h))
    assert owner_after["current_streams"] == 2


def test_stream_limit_rejection_leaves_sessions_untouched(api):
    """PRD §3.7: "An admitted session is created `ACTIVE` with `started_at` set to
    the current logical time, `ended_at` null, and `resolution_granted` equal to
    the requested resolution, and the member's `current_streams` increments by
    1." A rejected admission at the cap creates no session.

    Design: Difficulty/boundary_precision_check/stream_limit_exact_boundary
    """
    account, household, device, owner_h = create_account_with_device(
        email="bp1b@x.com", plan_tier="BASIC", trust=True
    )
    owner_id = account["owner_member_id"]
    payload = {"device_id": device["id"], "requested_resolution": "SD"}

    s1 = get_success_data(api.start_playback(owner_id, payload, owner_h))
    assert s1["status"] == "ACTIVE"

    resp = api.start_playback(owner_id, payload, owner_h)
    validate_error(resp, ApiErrorId.ERR_STREAM_LIMIT_REACHED)

    sessions, meta = validate_paginated(api.list_member_sessions(owner_id, owner_h))
    assert meta["total_count"] == 1, "only the admitted session exists"
    owner_after = get_success_data(api.get_member(owner_id, owner_h))
    assert owner_after["current_streams"] == 1


def test_download_allowance_zero_remaining(api):
    """PRD §3.7: "the account-wide count of downloads with status `ACTIVE` whose
    `billing_month` equals the current `YYYY-MM` from the logical clock must be
    strictly below the tier's monthly allowance — 5 for `BASIC`, 25 for
    `STANDARD`, 100 for `PREMIUM` — or the request is rejected with
    `ERR_DOWNLOAD_LIMIT_REACHED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/download_allowance_zero_remaining
    """
    account, household, device, owner_h = create_account_with_device(
        email="bp2@x.com", plan_tier="BASIC", trust=True, device_type="MOBILE"
    )
    owner_id = account["owner_member_id"]
    last = None
    for i in range(5):
        last = get_success_data(
            api.create_download(owner_id, {"device_id": device["id"], "title_id": f"t{i+1}"}, owner_h)
        )
        assert last["status"] == "ACTIVE"

    resp = api.create_download(owner_id, {"device_id": device["id"], "title_id": "t6"}, owner_h)
    validate_error(resp, ApiErrorId.ERR_DOWNLOAD_LIMIT_REACHED)

    owner_after = get_success_data(api.get_member(owner_id, owner_h))
    assert owner_after["downloads_used_this_month"] == 5


def test_download_allowance_one_below_cap_admitted(api):
    """PRD §3.7: "must be strictly below the tier's monthly allowance — 5 for
    `BASIC`" — the fifth download (count 4 before the request) is admitted and the
    sixth is rejected.

    Design: Difficulty/boundary_precision_check/download_allowance_zero_remaining
    """
    account, household, device, owner_h = create_account_with_device(
        email="bp2b@x.com", plan_tier="BASIC", trust=True, device_type="MOBILE"
    )
    owner_id = account["owner_member_id"]
    for i in range(4):
        get_success_data(
            api.create_download(owner_id, {"device_id": device["id"], "title_id": f"t{i+1}"}, owner_h)
        )
    fifth = get_success_data(
        api.create_download(owner_id, {"device_id": device["id"], "title_id": "t5"}, owner_h)
    )
    assert fifth["status"] == "ACTIVE"
    assert fifth["billing_month"] == "2026-09"

    resp = api.create_download(owner_id, {"device_id": device["id"], "title_id": "t6"}, owner_h)
    validate_error(resp, ApiErrorId.ERR_DOWNLOAD_LIMIT_REACHED)


def test_standard_tier_uhd_rejected_hd_granted(api):
    """PRD §3.7: "the requested resolution must not exceed the plan tier's maximum
    — `BASIC` permits at most `SD`, `STANDARD` at most `HD`, `PREMIUM` at most
    `UHD`, with the ordering `SD` below `HD` below `UHD` — or the request is
    rejected with `ERR_RESOLUTION_NOT_ENTITLED` (HTTP 403)" and "an admitted
    session is created `ACTIVE` ... `resolution_granted` equal to the requested
    resolution".

    Design: Corner/calculations/standard_tier_uhd_rejected_hd_granted
    """
    account, household, device, owner_h = create_account_with_device(
        email="corner-res@x.com", plan_tier="STANDARD", trust=True
    )
    owner_id = account["owner_member_id"]

    resp = api.start_playback(owner_id, {"device_id": device["id"], "requested_resolution": "UHD"}, owner_h)
    validate_error(resp, ApiErrorId.ERR_RESOLUTION_NOT_ENTITLED)

    session = get_success_data(
        api.start_playback(owner_id, {"device_id": device["id"], "requested_resolution": "HD"}, owner_h)
    )
    assert session["resolution_granted"] == "HD"

    owner_after = get_success_data(api.get_member(owner_id, owner_h))
    assert owner_after["current_streams"] == 1
