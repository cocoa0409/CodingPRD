"""Corner coverage: response envelope shape, connect-time derivation and
pinning, the video-availability computed read, and immediate
read-after-write consistency (PRD §2.2, §2.5, §3.5, §3.7).
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    book_inmate,
    connect_call,
    create_facility_raw,
    create_session,
    deposit,
    get_account,
    get_video_availability,
    open_account,
    setup_active_facility,
    setup_call_ready_account,
    setup_funded_account,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_response_envelope_carries_meta_and_response_type(
    api, platform_admin_headers
):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints."

    Design: Corner/endpoints/response_envelope_carries_meta_and_response_type
    """
    facility = create_facility_raw(name="Envelope Facility")

    single = api.get_facility(facility["id"], platform_admin_headers)
    validate_success(single)
    single_body = single.json()
    assert single_body["response_type"] == "object"
    assert single_body["meta"]["api_request_id"]
    assert single_body["meta"]["api_request_timestamp"]

    listed = api.list_facilities(platform_admin_headers)
    rows, meta = validate_paginated(listed)
    assert listed.json()["response_type"] == "array"
    assert meta["limit"] == 10 and meta["offset"] == 0
    assert meta["total_count"] == 1 and meta["has_more"] is False
    assert len(rows) == 1

    missing = api.get_facility(NON_EXISTENT_UUID, platform_admin_headers)
    validate_error(missing, ApiErrorId.ERR_FACILITY_NOT_FOUND)
    error_body = missing.json()
    assert error_body["response_type"] == "error"
    assert set(error_body["data"].keys()) == {"error_id", "message"}
    assert set(error_body["meta"].keys()) == {
        "api_request_id",
        "api_request_timestamp",
    }


def test_call_create_derives_facility_and_pins_active_schedule(api):
    """PRD §3.5: "The new **CallRecord** derives its `facility_id` from the account, pins `rate_schedule_id` to the contract's then-active schedule, and snapshots `applied_per_minute_cents` as the lesser of the schedule's per-minute rate for the declared `call_type` and the jurisdiction's `max_per_minute_cents`, and `applied_connection_fee_cents` as the lesser of the schedule's `connection_fee_cents` and the jurisdiction's `max_connection_fee_cents`."
    PRD §3.5: "If the recipient's `privilege_status` is `PRIVILEGED` at that instant, `recording_status` is pinned to `EXEMPT_PRIVILEGED`; otherwise it is `RECORDED`. The `connected_at` field is stamped from the logical clock, the status is `CONNECTED`, and `cutoff_reason` starts at `NONE`."

    Design: Corner/endpoints/call_create_derives_facility_and_pins_active_schedule
    """
    env = setup_call_ready_account()
    call = connect_call(
        env["account"], env["inmate"], env["recipient"], call_type="LOCAL"
    )
    assert call["facility_id"] == env["facility"]["id"], (
        "facility_id is derived from the account, not supplied by the caller"
    )
    assert call["rate_schedule_id"] == env["schedule"]["id"]
    assert call["applied_per_minute_cents"] == 18
    assert call["applied_connection_fee_cents"] == 200
    assert call["recording_status"] == "RECORDED"
    assert call["cutoff_reason"] == "NONE"
    assert call["status"] == "CONNECTED"
    assert call["connected_at"].startswith("2026-09-01T00:00:00"), (
        "connected_at is stamped from the logical clock, not wall-clock time"
    )


def test_video_availability_computed_read_matches_budget_formula(api):
    """PRD §3.7: "For planning, the facility's video-availability view answers a `date` query with that `date`, the facility's `booth_count`, the `booked_minutes` already confirmed for that day, and the `bookable_minutes` remaining — computed as the booth count multiplied by the visiting window's length in minutes, minus the booked minutes — so that booked plus bookable always equals the full window budget."

    Design: Corner/endpoints/video_availability_computed_read_matches_budget_formula
    """
    env = setup_funded_account()
    facility = env["facility"]
    create_session(
        facility,
        env["inmate"],
        env["account"],
        scheduled_start="2026-09-22T10:00:00Z",
        scheduled_end="2026-09-22T10:30:00Z",
    )

    avail = get_video_availability(facility["id"], "2026-09-22")
    assert avail["date"] == "2026-09-22"
    assert avail["booth_count"] == 2
    assert avail["booked_minutes"] == 0, "a REQUESTED session consumes nothing"
    assert avail["bookable_minutes"] == 1440
    assert avail["booked_minutes"] + avail["bookable_minutes"] == 2 * (1200 - 480)


def test_immediate_consistency_write_response_matches_followup_read(
    api, compliance_officer_headers
):
    """PRD §2.5: "`version` is an integer that increments by one on every mutation, and it is the basis for the optimistic concurrency control described in §2.7."
    PRD §2.5: "An account's `balance_cents` is never written directly; it is the sum of the signed `amount_cents` values across the account's ledger."

    Design: Corner/consistency_model/immediate_consistency_write_response_matches_followup_read
    """
    env = setup_active_facility()
    inmate = book_inmate(env["facility"]["id"])
    account = open_account(env["facility"]["id"], inmate["id"])
    version_at_create = account["version"]

    write_response = deposit(account, 1025)
    assert write_response["balance_cents"] == 1000
    assert write_response["version"] == version_at_create + 1, (
        "the deposit mutation increments the account version by exactly one"
    )

    read_back = get_account(account["id"], headers=compliance_officer_headers)
    assert read_back["balance_cents"] == 1000, (
        "the follow-up read observes the deposit immediately"
    )
    assert read_back["version"] == write_response["version"]
    assert read_back["updated_at"] >= read_back["created_at"]
