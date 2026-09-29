"""Talkgroup administration and the heavily guarded interoperability patch.

Every test in this module translates exactly one design instance and carries a
verbatim PRD citation for the rule it pins.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_AGENCY_SCOPE_VIOLATION,
    ERR_ALREADY_TERMINAL,
    ERR_COVERAGE_CLASS_INSUFFICIENT,
    ERR_ENCRYPTION_MODE_MISMATCH,
    ERR_INTEROP_PRIVILEGE_INSUFFICIENT,
    ERR_INVALID_REQUEST,
    ERR_PATCH_AUTHORITY_REQUIRED,
    ERR_PATCH_WINDOW_OVERLAP,
    ERR_SELF_PATCH_NOT_PERMITTED,
    ERR_TALKGROUP_LOCKED,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_coverage_result,
    assert_fields,
    assert_instant_equals,
    assert_nulls,
    assert_pagination_meta,
)
from test_helpers.constants import (
    AGENCY_TYPE_FIRE,
    AGENCY_TYPE_LAW,
    BACKUP_GENERATOR,
    COVERAGE_GENERAL,
    COVERAGE_MISSION_CRITICAL,
    DERATE_A,
    DERATE_B,
    ENC_CLEAR,
    ENC_ENCRYPTED,
    ENC_SELECTABLE,
    INTEROP_MONITOR,
    INTEROP_PATCH_AUTHORITY,
    LOCK_REASON_MANUAL,
    LOCK_REASON_NONE,
    PATCH_ACTIVE,
    PATCH_DECISION_ACTIVATE,
    PATCH_RELEASED,
    PATCH_REQUESTED,
    RELEASE_REASON_NONE,
    RELEASE_REASON_OPERATOR,
    TG_ACTION_DECOMMISSION,
    TG_ACTION_LOCK,
    TG_ACTION_UNLOCK,
    TG_ACTIVE,
    TG_DECOMMISSIONED,
    TG_KIND_ANNOUNCEMENT,
    TG_KIND_DISPATCH,
    TG_KIND_INTEROP,
    TG_KIND_TACTICAL,
    TG_LOCKED,
)
from test_helpers.test_users import (
    RF_ENGINEER,
    SYSTEM_ADMIN,
    make_agency_radio_manager_headers,
    make_dispatcher_headers,
)


def _agency_and_site(
    api: ApiClient,
    *,
    name: str,
    agency_code: str,
    site_code: str,
    site_name: str,
    channel_capacity: int,
    agency_type: str = AGENCY_TYPE_LAW,
    interop_privilege=INTEROP_PATCH_AUTHORITY,
    recorder_retention_days: int = 180,
):
    """One member agency plus one `GENERATOR`-backed site, the shared opening
    position of nearly every patch scenario.

    `interop_privilege=None` leaves the input off the payload so the registered
    default applies.
    """
    agency = fx.register_agency(
        api,
        name=name,
        agency_code=agency_code,
        agency_type=agency_type,
        interop_privilege=interop_privilege,
        recorder_retention_days=recorder_retention_days,
    )
    site = fx.register_site(
        api,
        site_code=site_code,
        name=site_name,
        channel_capacity=channel_capacity,
        backup_power_type=BACKUP_GENERATOR,
    )
    return agency, site


def test_talkgroup_retrieval_returns_stored_row(api: ApiClient, clock_at_start: str):
    """A freshly created talkgroup reads back with every declared opening value,
    including the `priority_level` default the caller never supplied.

    PRD 3.6: "An optional `priority_level`, an integer from 1 to 10 where 1 is
    highest, defaults to 5."

    PRD 3.6: "A new talkgroup opens `ACTIVE` with `lock_reason` `NONE` and
    `active_patch_count` 0, where `active_patch_count` is the number of
    interoperability patches naming this talkgroup as either source or target
    whose status is `REQUESTED` or `ACTIVE`."

    PRD 2.1: "Every read endpoint in the system is available to all eight roles."

    Design: Corner/entities/talkgroup_retrieval_returns_stored_row
    """
    agency, site = _agency_and_site(
        api,
        name="Retrieval Agency",
        agency_code="RET01",
        agency_type=AGENCY_TYPE_FIRE,
        interop_privilege=None,
        recorder_retention_days=90,
        site_code="RET-1",
        site_name="Retrieval One",
        channel_capacity=4,
    )
    created = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="TG-RET",
        tg_decimal_id=601,
        kind=TG_KIND_ANNOUNCEMENT,
        encryption_mode=ENC_SELECTABLE,
    )

    # A Dispatcher of the owning agency reads the row back.
    stored = validate_success(
        api.get_talkgroup(created["id"], make_dispatcher_headers(agency["id"])), 200
    )

    assert_common_fields(stored, expected_version=1)
    assert_fields(
        stored,
        id=created["id"],
        owner_agency_id=agency["id"],
        home_site_id=site["id"],
        alias="TG-RET",
        tg_decimal_id=601,
        kind=TG_KIND_ANNOUNCEMENT,
        encryption_mode=ENC_SELECTABLE,
        priority_level=5,
        status=TG_ACTIVE,
        lock_reason=LOCK_REASON_NONE,
        active_patch_count=0,
    )


def test_talkgroup_creation_rejects_out_of_range_tg_decimal_id(
    api: ApiClient, clock_at_start: str
):
    """`tg_decimal_id` 70000 is outside the declared P25 range and is refused as a
    body-validation failure, while the inclusive upper bound 65535 is accepted.

    PRD 3.6: "The creation payload names the `owner_agency_id` that will own and
    administer it, the `home_site_id` of the site whose coverage class gates
    encrypted patching of this talkgroup, an `alias` of 1 to 16 characters as
    shown on radios and consoles, and the `tg_decimal_id`, a P25 talkgroup
    decimal identifier of at least 1 and at most 65535 that must be unique across
    all talkgroups — a collision is rejected with `ERR_DUPLICATE_TALKGROUP_ID`."

    PRD 2.4: "The body parses, required fields are present, enum values are
    members of their declared sets, integers lie inside their declared ranges,
    and datetime fields are ISO-8601 UTC instants ending in `Z` — otherwise
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/talkgroup_creation_rejects_out_of_range_tg_decimal_id
    """
    agency, site = _agency_and_site(
        api,
        name="Range Check Agency",
        agency_code="RNG01",
        agency_type=AGENCY_TYPE_FIRE,
        interop_privilege=None,
        recorder_retention_days=90,
        site_code="RNG-1",
        site_name="Range One",
        channel_capacity=4,
    )
    manager = make_agency_radio_manager_headers(agency["id"])

    rejected = api.create_talkgroup(
        f.talkgroup_payload(
            agency["id"],
            site["id"],
            alias="TOO-BIG",
            tg_decimal_id=70000,
            kind=TG_KIND_DISPATCH,
            encryption_mode=ENC_CLEAR,
        ),
        manager,
    )
    validate_error(rejected, ERR_INVALID_REQUEST, 400)

    # Nothing was persisted by the refused call.
    rows, meta = validate_paginated(
        api.list_talkgroups(SYSTEM_ADMIN, {"owner_agency_id": agency["id"]})
    )
    assert_pagination_meta(meta, total_count=0)
    assert rows == [], f"the refused creation must persist nothing, got {rows!r}"

    # The identical call at the inclusive upper bound is accepted.
    accepted = validate_success(
        api.create_talkgroup(
            f.talkgroup_payload(
                agency["id"],
                site["id"],
                alias="TOO-BIG",
                tg_decimal_id=65535,
                kind=TG_KIND_DISPATCH,
                encryption_mode=ENC_CLEAR,
            ),
            manager,
        ),
        201,
    )
    assert_fields(accepted, tg_decimal_id=65535, status=TG_ACTIVE)


def test_interop_patch_junction_links_two_talkgroups_of_one_agency(
    api: ApiClient, clock_at_start: str
):
    """A patch is the junction row between two talkgroups: it opens with all four
    lifecycle stamps null and immediately shows up in both talkgroups' counters
    and in the requesting agency's counter.

    PRD 3.6: "A `Dispatcher` requests one by naming the `source_talkgroup_id`
    that initiates the patch, the `target_talkgroup_id` to be patched to it, the
    `requesting_agency_id` exercising patch authority, and the window bounded by
    an inclusive `scheduled_start` and an exclusive `scheduled_end` that must be
    strictly after it."

    PRD 3.6: "A patch that survives all of that opens in `REQUESTED` with
    `activated_at`, `released_at`, `duration_minutes`, and
    `recorder_retention_days_at_activation` all null and `release_reason` `NONE`;
    `active_patch_count` is then recomputed on both talkgroups and
    `active_patch_request_count` on the requesting agency."

    Design: Corner/entities/interop_patch_junction_links_two_talkgroups_of_one_agency
    """
    agency, site = _agency_and_site(
        api,
        name="Junction County Police",
        agency_code="JNC01",
        site_code="JN-1",
        site_name="Junction One",
        channel_capacity=8,
    )
    source = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="JN-A",
        tg_decimal_id=701,
        kind=TG_KIND_DISPATCH,
        encryption_mode=ENC_CLEAR,
    )
    target = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="JN-B",
        tg_decimal_id=702,
        kind=TG_KIND_INTEROP,
        encryption_mode=ENC_CLEAR,
    )

    patch = fx.request_patch(
        api,
        source["id"],
        target["id"],
        agency["id"],
        scheduled_start="2026-08-01T00:00:00Z",
        scheduled_end="2026-08-01T04:00:00Z",
    )

    assert_common_fields(patch, expected_version=1)
    assert_fields(
        patch,
        source_talkgroup_id=source["id"],
        target_talkgroup_id=target["id"],
        requesting_agency_id=agency["id"],
        status=PATCH_REQUESTED,
        release_reason=RELEASE_REASON_NONE,
    )
    assert_instant_equals(patch["scheduled_start"], "2026-08-01T00:00:00Z", "scheduled_start")
    assert_instant_equals(patch["scheduled_end"], "2026-08-01T04:00:00Z", "scheduled_end")
    assert_nulls(
        patch,
        "activated_at",
        "released_at",
        "duration_minutes",
        "recorder_retention_days_at_activation",
    )

    # Both ends of the junction, and the requester, now count the live request.
    assert_fields(fx.read_talkgroup(api, source["id"]), active_patch_count=1)
    assert_fields(fx.read_talkgroup(api, target["id"]), active_patch_count=1)
    assert_fields(fx.read_agency(api, agency["id"]), active_patch_request_count=1)

    rows, meta = validate_paginated(
        api.list_interop_patches(SYSTEM_ADMIN, {"source_talkgroup_id": source["id"]})
    )
    assert_pagination_meta(meta, total_count=1)
    assert_fields(rows[0], id=patch["id"], status=PATCH_REQUESTED)


def test_talkgroup_lock_releases_requested_patch_with_operator_reason(
    api: ApiClient, clock_at_start: str
):
    """One `LOCK` fires the whole side-effect list: the talkgroup locks `MANUAL`,
    the `REQUESTED` patch riding on it is released with reason `OPERATOR`, and
    both counters settle back to zero — while the untouched partner stays `ACTIVE`.

    PRD 3.6: "`LOCK` moves an `ACTIVE` talkgroup to `LOCKED` and sets
    `lock_reason` to `MANUAL`; every patch naming this talkgroup whose `status` is
    `REQUESTED` or `ACTIVE` becomes `RELEASED` with `released_at` stamped at now
    and `release_reason` set to `OPERATOR`, after which `active_patch_count` is
    recomputed."

    PRD 3.6: "When either `activated_at` or `released_at` is null the value stays
    null — a patch released straight out of `REQUESTED` without ever having been
    activated therefore never acquires a duration."

    Design: Corner/state_machines/talkgroup_lock_releases_requested_patch_with_operator_reason
    """
    agency, site = _agency_and_site(
        api,
        name="Lockdown County Sheriff",
        agency_code="LKD01",
        site_code="LK-1",
        site_name="Lockdown One",
        channel_capacity=8,
    )
    source = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="LK-A",
        tg_decimal_id=801,
        kind=TG_KIND_DISPATCH,
        encryption_mode=ENC_CLEAR,
    )
    target = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="LK-B",
        tg_decimal_id=802,
        kind=TG_KIND_INTEROP,
        encryption_mode=ENC_CLEAR,
    )
    patch = fx.request_patch(
        api,
        source["id"],
        target["id"],
        agency["id"],
        scheduled_start="2026-08-01T00:00:00Z",
        scheduled_end="2026-08-01T06:00:00Z",
    )
    assert_fields(patch, status=PATCH_REQUESTED)

    locked = fx.talkgroup_action(api, source["id"], agency["id"], TG_ACTION_LOCK)

    assert_fields(locked, status=TG_LOCKED, lock_reason=LOCK_REASON_MANUAL)

    released = validate_success(api.get_interop_patch(patch["id"], SYSTEM_ADMIN), 200)
    assert_fields(
        released, status=PATCH_RELEASED, release_reason=RELEASE_REASON_OPERATOR
    )
    assert_instant_equals(released["released_at"], "2026-08-01T00:00:00Z", "released_at")
    # It was never activated, so the duration rule leaves the value null.
    assert_nulls(released, "activated_at", "duration_minutes")

    assert_fields(fx.read_talkgroup(api, source["id"]), active_patch_count=0)
    assert_fields(fx.read_agency(api, agency["id"]), active_patch_request_count=0)

    # Only the locked talkgroup changed state; its partner merely lost the patch.
    partner = fx.read_talkgroup(api, target["id"])
    assert_fields(
        partner,
        status=TG_ACTIVE,
        lock_reason=LOCK_REASON_NONE,
        active_patch_count=0,
    )


def test_talkgroup_decommission_blocks_subsequent_lock(
    api: ApiClient, clock_at_start: str
):
    """`DECOMMISSIONED` is the talkgroup's only terminal state, so the terminality
    check fires ahead of the transition check and every later action — `LOCK` or
    `UNLOCK` alike — is refused as already terminal.

    PRD 3.6: "`DECOMMISSION` moves a talkgroup from either `ACTIVE` or `LOCKED` to
    `DECOMMISSIONED`, which is terminal; decommissioning something already
    `DECOMMISSIONED` is rejected with `ERR_ALREADY_TERMINAL`."

    PRD 2.4: "The target resource is not already in a terminal state for the
    requested operation — otherwise `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/talkgroup_decommission_blocks_subsequent_lock
    """
    agency, site = _agency_and_site(
        api,
        name="Terminal Agency",
        agency_code="TRM01",
        agency_type=AGENCY_TYPE_FIRE,
        interop_privilege=None,
        recorder_retention_days=90,
        site_code="TRM-1",
        site_name="Terminal One",
        channel_capacity=4,
    )
    talkgroup = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="TRM-A",
        tg_decimal_id=901,
        kind=TG_KIND_DISPATCH,
        encryption_mode=ENC_CLEAR,
    )
    decommissioned = fx.talkgroup_action(
        api, talkgroup["id"], agency["id"], TG_ACTION_DECOMMISSION
    )
    assert_fields(
        decommissioned, status=TG_DECOMMISSIONED, lock_reason=LOCK_REASON_NONE
    )

    manager = make_agency_radio_manager_headers(agency["id"])

    lock_attempt = api.talkgroup_status(
        talkgroup["id"], f.talkgroup_status_payload(TG_ACTION_LOCK), manager
    )
    validate_error(lock_attempt, ERR_ALREADY_TERMINAL, 409)

    unlock_attempt = api.talkgroup_status(
        talkgroup["id"], f.talkgroup_status_payload(TG_ACTION_UNLOCK), manager
    )
    validate_error(unlock_attempt, ERR_ALREADY_TERMINAL, 409)

    settled = fx.read_talkgroup(api, talkgroup["id"])
    assert_fields(
        settled,
        status=TG_DECOMMISSIONED,
        lock_reason=LOCK_REASON_NONE,
        version=decommissioned["version"],
    )


def test_patch_duration_floors_to_whole_minutes(api: ApiClient, clock_at_start: str):
    """105 seconds of airtime logs 1 whole minute: the partial minute is discarded
    downward rather than rounded up or kept as a fraction.

    PRD 3.6: "Otherwise it is the number of whole minutes from `activated_at` to
    `released_at`, with any partial minute discarded downward, so a patch released
    in the same logical minute it was activated logs 0 rather than null."

    PRD 3.6: "On success `activated_at` is stamped with now and
    `recorder_retention_days_at_activation` snapshots the requesting agency's
    `recorder_retention_days` as it stands at that instant — a later console
    reconfiguration does not rewrite the snapshot, which is what makes the
    retention obligation on the recorded audio auditable after the fact."

    Design: Corner/calculations/patch_duration_floors_to_whole_minutes
    """
    agency, site = _agency_and_site(
        api,
        name="Duration County Police",
        agency_code="DUR01",
        site_code="DUR-1",
        site_name="Duration One",
        channel_capacity=8,
    )
    source = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="DUR-A",
        tg_decimal_id=1301,
        kind=TG_KIND_DISPATCH,
        encryption_mode=ENC_CLEAR,
    )
    target = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="DUR-B",
        tg_decimal_id=1302,
        kind=TG_KIND_INTEROP,
        encryption_mode=ENC_CLEAR,
    )
    patch = fx.request_patch(
        api,
        source["id"],
        target["id"],
        agency["id"],
        scheduled_start="2026-08-01T00:00:00Z",
        scheduled_end="2026-08-01T06:00:00Z",
    )
    activated = fx.decide_patch(
        api, patch["id"], agency["id"], PATCH_DECISION_ACTIVATE
    )
    assert_fields(
        activated,
        status=PATCH_ACTIVE,
        recorder_retention_days_at_activation=180,
    )
    assert_instant_equals(
        activated["activated_at"], "2026-08-01T00:00:00Z", "activated_at"
    )
    assert_nulls(activated, "duration_minutes", "released_at")

    fx.set_clock(api, "2026-08-01T00:01:45Z")
    released = fx.release_patch(api, patch["id"], agency["id"])

    assert_fields(
        released,
        status=PATCH_RELEASED,
        release_reason=RELEASE_REASON_OPERATOR,
        duration_minutes=1,
    )
    assert_instant_equals(released["released_at"], "2026-08-01T00:01:45Z", "released_at")
    assert released["duration_minutes"] != 2, (
        "105 seconds must floor to 1 whole minute, never round up to 2"
    )

    assert_fields(fx.read_talkgroup(api, source["id"]), active_patch_count=0)
    assert_fields(fx.read_talkgroup(api, target["id"]), active_patch_count=0)
    assert_fields(fx.read_agency(api, agency["id"]), active_patch_request_count=0)


def test_self_patch_rejected(api: ApiClient, clock_at_start: str):
    """A talkgroup may not be patched to itself, and the refusal stands even
    though the requester holds every privilege the later checks would look for.

    PRD 3.6: "The two talkgroups must be distinct — a `source_talkgroup_id` equal
    to the `target_talkgroup_id` is rejected with `ERR_SELF_PATCH_NOT_PERMITTED`."

    Design: Corner/validations/self_patch_rejected
    """
    agency, site = _agency_and_site(
        api,
        name="Self Patch Police",
        agency_code="SLF01",
        site_code="SLF-1",
        site_name="Self One",
        channel_capacity=6,
    )
    talkgroup = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="SLF-A",
        tg_decimal_id=1501,
        kind=TG_KIND_DISPATCH,
        encryption_mode=ENC_CLEAR,
    )

    attempt = api.create_interop_patch(
        f.interop_patch_payload(
            talkgroup["id"],
            talkgroup["id"],
            agency["id"],
            scheduled_start="2026-08-01T00:00:00Z",
            scheduled_end="2026-08-01T02:00:00Z",
        ),
        make_dispatcher_headers(agency["id"]),
    )
    validate_error(attempt, ERR_SELF_PATCH_NOT_PERMITTED, 422)

    assert_fields(fx.read_talkgroup(api, talkgroup["id"]), active_patch_count=0)
    assert_fields(fx.read_agency(api, agency["id"]), active_patch_request_count=0)

    rows, meta = validate_paginated(
        api.list_interop_patches(SYSTEM_ADMIN, {"requesting_agency_id": agency["id"]})
    )
    assert_pagination_meta(meta, total_count=0)
    assert rows == [], f"no patch row may exist after the refusal, got {rows!r}"


def test_patch_requested_by_agency_owning_neither_talkgroup_rejected(
    api: ApiClient, clock_at_start: str
):
    """Validity turns on another entity's ownership: a fully privileged agency is
    refused while it owns neither end of the patch, and succeeds the moment one
    end is its own.

    PRD 3.6: "The requesting agency must own at least one of the two talkgroups;
    an agency trying to patch two talkgroups that both belong to others is
    rejected with `ERR_INTEROP_PRIVILEGE_INSUFFICIENT`."

    Design: Corner/validations/patch_requested_by_agency_owning_neither_talkgroup_rejected
    """
    owner, site = _agency_and_site(
        api,
        name="Owner County Police",
        agency_code="OWN01",
        site_code="OWN-1",
        site_name="Owner One",
        channel_capacity=8,
    )
    outsider = fx.register_agency(
        api,
        name="Outsider County Police",
        agency_code="OUT01",
        agency_type=AGENCY_TYPE_LAW,
        interop_privilege=INTEROP_PATCH_AUTHORITY,
        recorder_retention_days=180,
    )
    own_a = fx.create_talkgroup(
        api,
        owner["id"],
        site["id"],
        alias="OWN-A",
        tg_decimal_id=1601,
        kind=TG_KIND_DISPATCH,
        encryption_mode=ENC_CLEAR,
    )
    own_b = fx.create_talkgroup(
        api,
        owner["id"],
        site["id"],
        alias="OWN-B",
        tg_decimal_id=1602,
        kind=TG_KIND_INTEROP,
        encryption_mode=ENC_CLEAR,
    )
    out_a = fx.create_talkgroup(
        api,
        outsider["id"],
        site["id"],
        alias="OUT-A",
        tg_decimal_id=1603,
        kind=TG_KIND_INTEROP,
        encryption_mode=ENC_CLEAR,
    )
    outsider_dispatcher = make_dispatcher_headers(outsider["id"])

    foreign = api.create_interop_patch(
        f.interop_patch_payload(
            own_a["id"],
            own_b["id"],
            outsider["id"],
            scheduled_start="2026-08-01T00:00:00Z",
            scheduled_end="2026-08-01T02:00:00Z",
        ),
        outsider_dispatcher,
    )
    validate_error(foreign, ERR_INTEROP_PRIVILEGE_INSUFFICIENT, 403)

    # The identical window with one talkgroup of its own is accepted.
    accepted = validate_success(
        api.create_interop_patch(
            f.interop_patch_payload(
                out_a["id"],
                own_b["id"],
                outsider["id"],
                scheduled_start="2026-08-01T00:00:00Z",
                scheduled_end="2026-08-01T02:00:00Z",
            ),
            outsider_dispatcher,
        ),
        201,
    )
    assert_fields(accepted, status=PATCH_REQUESTED, requesting_agency_id=outsider["id"])

    # Only the second patch was booked.
    assert_fields(fx.read_talkgroup(api, own_a["id"]), active_patch_count=0)
    assert_fields(fx.read_talkgroup(api, own_b["id"]), active_patch_count=1)
    assert_fields(fx.read_talkgroup(api, out_a["id"]), active_patch_count=1)
    assert_fields(fx.read_agency(api, outsider["id"]), active_patch_request_count=1)
    assert_fields(fx.read_agency(api, owner["id"]), active_patch_request_count=0)


def test_patch_window_overlap_rejected(api: ApiClient, clock_at_start: str):
    """Overlap is judged on the shared talkgroup across half-open intervals: a
    window straddling an existing reservation is refused, while the back-to-back
    window sharing only the endpoint is accepted.

    PRD 3.6: "The requested window must not overlap any patch whose `status` is
    `REQUESTED` or `ACTIVE` that names either the source or the target talkgroup.
    Overlap is judged on half-open intervals, so two back-to-back windows sharing
    an endpoint are both accepted; a genuine overlap is rejected with
    `ERR_PATCH_WINDOW_OVERLAP`."

    Design: Corner/validations/patch_window_overlap_rejected
    """
    agency, site = _agency_and_site(
        api,
        name="Overlap County Police",
        agency_code="OVL01",
        site_code="OVL-1",
        site_name="Overlap One",
        channel_capacity=8,
    )
    tg_a = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="OVL-A",
        tg_decimal_id=1701,
        kind=TG_KIND_DISPATCH,
        encryption_mode=ENC_CLEAR,
    )
    tg_b = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="OVL-B",
        tg_decimal_id=1702,
        kind=TG_KIND_INTEROP,
        encryption_mode=ENC_CLEAR,
    )
    tg_c = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="OVL-C",
        tg_decimal_id=1703,
        kind=TG_KIND_INTEROP,
        encryption_mode=ENC_CLEAR,
    )
    first = fx.request_patch(
        api,
        tg_a["id"],
        tg_b["id"],
        agency["id"],
        scheduled_start="2026-08-01T00:00:00Z",
        scheduled_end="2026-08-01T06:00:00Z",
    )
    assert_fields(first, status=PATCH_REQUESTED)
    dispatcher = make_dispatcher_headers(agency["id"])

    # [03:00, 09:00) genuinely straddles the reserved [00:00, 06:00) on OVL-A.
    straddling = api.create_interop_patch(
        f.interop_patch_payload(
            tg_a["id"],
            tg_c["id"],
            agency["id"],
            scheduled_start="2026-08-01T03:00:00Z",
            scheduled_end="2026-08-01T09:00:00Z",
        ),
        dispatcher,
    )
    validate_error(straddling, ERR_PATCH_WINDOW_OVERLAP, 409)

    # [06:00, 09:00) only touches the exclusive end of the first window.
    adjacent = validate_success(
        api.create_interop_patch(
            f.interop_patch_payload(
                tg_a["id"],
                tg_c["id"],
                agency["id"],
                scheduled_start="2026-08-01T06:00:00Z",
                scheduled_end="2026-08-01T09:00:00Z",
            ),
            dispatcher,
        ),
        201,
    )
    assert_fields(adjacent, status=PATCH_REQUESTED)
    assert adjacent["id"] != first["id"], "the adjacent window is a second patch row"

    assert_fields(fx.read_talkgroup(api, tg_a["id"]), active_patch_count=2)
    assert_fields(fx.read_talkgroup(api, tg_b["id"]), active_patch_count=1)
    assert_fields(fx.read_talkgroup(api, tg_c["id"]), active_patch_count=1)
    assert_fields(fx.read_agency(api, agency["id"]), active_patch_request_count=2)


def test_error_talkgroup_locked_blocks_patch_creation(
    api: ApiClient, clock_at_start: str
):
    """A `LOCKED` participant is refused by the availability guard, which sits at
    the head of the patch checklist; unlocking it makes the identical request pass.

    PRD 3.6: "Both named talkgroups must be `ACTIVE`; a `LOCKED` or
    `DECOMMISSIONED` participant is rejected with `ERR_TALKGROUP_LOCKED`."

    PRD 3.6: "A talkgroup locked with `lock_reason` `MANUAL` carries no such
    requirement."

    Design: Corner/errors/error_talkgroup_locked_blocks_patch_creation
    """
    agency, site = _agency_and_site(
        api,
        name="Locked Talkgroup Police",
        agency_code="TLK01",
        site_code="TLK-1",
        site_name="Locked One",
        channel_capacity=6,
    )
    source = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="TLK-A",
        tg_decimal_id=2001,
        kind=TG_KIND_DISPATCH,
        encryption_mode=ENC_CLEAR,
    )
    target = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="TLK-B",
        tg_decimal_id=2002,
        kind=TG_KIND_INTEROP,
        encryption_mode=ENC_CLEAR,
    )
    fx.talkgroup_action(api, target["id"], agency["id"], TG_ACTION_LOCK)

    payload = f.interop_patch_payload(
        source["id"],
        target["id"],
        agency["id"],
        scheduled_start="2026-08-01T00:00:00Z",
        scheduled_end="2026-08-01T03:00:00Z",
    )
    dispatcher = make_dispatcher_headers(agency["id"])

    blocked = api.create_interop_patch(payload, dispatcher)
    validate_error(blocked, ERR_TALKGROUP_LOCKED, 409)

    assert_fields(
        fx.read_talkgroup(api, target["id"]),
        status=TG_LOCKED,
        lock_reason=LOCK_REASON_MANUAL,
        active_patch_count=0,
    )
    assert_fields(fx.read_talkgroup(api, source["id"]), active_patch_count=0)
    assert_fields(fx.read_agency(api, agency["id"]), active_patch_request_count=0)

    # A MANUAL lock carries no keyed-radio requirement, so the unlock succeeds
    # and the identical patch request is then accepted.
    unlocked = fx.talkgroup_action(api, target["id"], agency["id"], TG_ACTION_UNLOCK)
    assert_fields(unlocked, status=TG_ACTIVE, lock_reason=LOCK_REASON_NONE)

    accepted = validate_success(api.create_interop_patch(payload, dispatcher), 201)
    assert_fields(accepted, status=PATCH_REQUESTED)
    assert_fields(fx.read_talkgroup(api, target["id"]), active_patch_count=1)


def test_error_patch_authority_required_for_monitor_privilege_agency(
    api: ApiClient, clock_at_start: str
):
    """Owning both talkgroups and holding 180-day retention is not enough: an
    agency left at the registered default `MONITOR` may not patch at all.

    PRD 3.1: "Four further inputs are optional at registration and each has a
    defined default: `fee_basis`, which is either `SNAPSHOT` or `PRORATED` and
    defaults to `SNAPSHOT`; `interop_privilege`, which is `NONE`, `MONITOR`, or
    `PATCH_AUTHORITY` and defaults to `MONITOR`; `console_position_count`, which
    defaults to 1; and `recorder_retention_days`, which defaults to 90."

    PRD 3.6: "The requesting agency's `interop_privilege` must be
    `PATCH_AUTHORITY`; an agency standing at `NONE` or `MONITOR` is rejected with
    `ERR_PATCH_AUTHORITY_REQUIRED`."

    Design: Corner/errors/error_patch_authority_required_for_monitor_privilege_agency
    """
    agency, site = _agency_and_site(
        api,
        name="Monitor Only Police",
        agency_code="MON01",
        interop_privilege=None,
        site_code="MON-1",
        site_name="Monitor One",
        channel_capacity=6,
    )
    assert_fields(agency, interop_privilege=INTEROP_MONITOR, recorder_retention_days=180)

    source = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="MON-A",
        tg_decimal_id=2101,
        kind=TG_KIND_DISPATCH,
        encryption_mode=ENC_CLEAR,
    )
    target = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="MON-B",
        tg_decimal_id=2102,
        kind=TG_KIND_INTEROP,
        encryption_mode=ENC_CLEAR,
    )

    attempt = api.create_interop_patch(
        f.interop_patch_payload(
            source["id"],
            target["id"],
            agency["id"],
            scheduled_start="2026-08-01T00:00:00Z",
            scheduled_end="2026-08-01T03:00:00Z",
        ),
        make_dispatcher_headers(agency["id"]),
    )
    validate_error(attempt, ERR_PATCH_AUTHORITY_REQUIRED, 403)

    assert_fields(
        fx.read_agency(api, agency["id"]),
        interop_privilege=INTEROP_MONITOR,
        active_patch_request_count=0,
    )
    rows, meta = validate_paginated(
        api.list_interop_patches(SYSTEM_ADMIN, {"requesting_agency_id": agency["id"]})
    )
    assert_pagination_meta(meta, total_count=0)
    assert rows == [], f"a MONITOR agency books no patch row, got {rows!r}"


def test_rbac_peer_agency_cannot_lock_another_agencys_talkgroup(
    api: ApiClient, clock_at_start: str
):
    """Two `AgencyRadioManager`s hold the same role but are peers, not superiors:
    the write is scoped to the owning agency while the read is shared.

    PRD 3.6: "Availability is managed by the owning agency through a single
    operation taking an `action` of `LOCK`, `UNLOCK`, or `DECOMMISSION`; in all
    three cases the acting `X-User-ID` must equal the talkgroup's
    `owner_agency_id`, and each successful action increments the talkgroup's
    `version` by one."

    PRD 2.4: "For `AgencyRadioManager` and `Dispatcher`, the resource's
    owning-agency field equals `X-User-ID` — otherwise
    `ERR_AGENCY_SCOPE_VIOLATION`."

    PRD 2.1: "Every read endpoint in the system is available to all eight roles."

    Design: Corner/rbac/rbac_peer_agency_cannot_lock_another_agencys_talkgroup
    """
    peer_a = fx.register_agency(
        api,
        name="Peer Agency A",
        agency_code="PRA01",
        agency_type=AGENCY_TYPE_LAW,
        recorder_retention_days=180,
    )
    peer_b = fx.register_agency(
        api,
        name="Peer Agency B",
        agency_code="PRB01",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
    )
    site = fx.register_site(
        api,
        site_code="PRB-1",
        name="Peer One",
        channel_capacity=4,
        backup_power_type=BACKUP_GENERATOR,
    )
    talkgroup = fx.create_talkgroup(
        api,
        peer_a["id"],
        site["id"],
        alias="PRA-A",
        tg_decimal_id=2401,
        kind=TG_KIND_DISPATCH,
        encryption_mode=ENC_CLEAR,
    )

    intruder = api.talkgroup_status(
        talkgroup["id"],
        f.talkgroup_status_payload(TG_ACTION_LOCK),
        make_agency_radio_manager_headers(peer_b["id"]),
    )
    validate_error(intruder, ERR_AGENCY_SCOPE_VIOLATION, 403)

    # The read, by contrast, is a shared operation across peers.
    read_by_peer = validate_success(
        api.get_talkgroup(
            talkgroup["id"], make_agency_radio_manager_headers(peer_b["id"])
        ),
        200,
    )
    assert_fields(
        read_by_peer,
        id=talkgroup["id"],
        owner_agency_id=peer_a["id"],
        status=TG_ACTIVE,
        version=talkgroup["version"],
    )

    # The owner's identical call goes through.
    locked = fx.talkgroup_action(api, talkgroup["id"], peer_a["id"], TG_ACTION_LOCK)
    assert_fields(
        locked,
        status=TG_LOCKED,
        lock_reason=LOCK_REASON_MANUAL,
        version=talkgroup["version"] + 1,
    )


def _kilo_general_grade_site(api: ApiClient):
    """Site `GEN-1` surveyed to `GENERAL` grade, plus agency K owning one `CLEAR`
    and one `ENCRYPTED` talkgroup homed on it.

    Returns `(agency, site, clear_talkgroup, encrypted_talkgroup)`. The patch
    request that follows carries two independent defects at once: the home site is
    not `MISSION_CRITICAL` and the two encryption postures are incompatible.
    """
    site = fx.register_site(
        api,
        site_code="GEN-1",
        name="General Grade One",
        channel_capacity=10,
        backup_power_type=BACKUP_GENERATOR,
        generator_fuel_hours=24,
    )
    # raw 94.00 is at least 90.00 and below 97.00, so tier B derates 1.5pp.
    surveyed = fx.survey_site(api, site["id"], 940, 1000)
    assert_coverage_result(surveyed, 92.5, DERATE_B, COVERAGE_GENERAL)

    agency = fx.register_agency(
        api,
        name="Kilo City Police",
        agency_code="LAWK1",
        agency_type=AGENCY_TYPE_LAW,
        interop_privilege=INTEROP_PATCH_AUTHORITY,
        recorder_retention_days=180,
    )
    clear_talkgroup = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="CLR1",
        tg_decimal_id=301,
        kind=TG_KIND_DISPATCH,
        encryption_mode=ENC_CLEAR,
    )
    encrypted_talkgroup = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias="SEC1",
        tg_decimal_id=302,
        kind=TG_KIND_TACTICAL,
        encryption_mode=ENC_ENCRYPTED,
    )
    return agency, surveyed, clear_talkgroup, encrypted_talkgroup


def test_patch_coverage_safety_outranks_encryption_mode_mismatch(
    api: ApiClient, clock_at_start: str
):
    """Two independent defects sit on one patch request — an insufficient coverage
    class and an incompatible encryption pairing — and the fixed group-13 order
    surfaces the coverage failure alone.

    PRD 3.6: "When either talkgroup's `encryption_mode` is `ENCRYPTED`, the home
    site of **both** talkgroups must have a `coverage_class` of exactly
    `MISSION_CRITICAL`; anything less is rejected with
    `ERR_COVERAGE_CLASS_INSUFFICIENT`."

    PRD 2.4: "Within group 13 the relative order is likewise fixed: the
    retired-unit guard (`ERR_UNIT_RETIRED`), then the keyset-active guard
    (`ERR_KEYSET_NOT_ACTIVE`), then the template-published guard
    (`ERR_TEMPLATE_NOT_PUBLISHED`), then the talkgroup-availability guard
    (`ERR_TALKGROUP_LOCKED`), then the site-on-air guard (`ERR_SITE_OFF_AIR`),
    then coverage sufficiency (`ERR_COVERAGE_CLASS_INSUFFICIENT`), then recorder
    retention (`ERR_RECORDER_RETENTION_BELOW_MINIMUM`), then emergency and
    priority entitlement (`ERR_EMERGENCY_PREEMPTION_NOT_PERMITTED`), then the
    temporal window rules in the order `ERR_OTAR_WINDOW_OVERLAP`,
    `ERR_PATCH_WINDOW_OVERLAP`, `ERR_MAINTENANCE_BUFFER_VIOLATION`,
    `ERR_MAINTENANCE_CONCURRENCY_CAP`, then the referential rules in the order
    `ERR_TEMPLATE_VERSION_STALE`, `ERR_ENCRYPTION_MODE_MISMATCH`,
    `ERR_SELF_PATCH_NOT_PERMITTED`, `ERR_INTEROP_PRIVILEGE_INSUFFICIENT`, then
    `ERR_PATCH_AUTHORITY_REQUIRED`, then `ERR_OTAR_WINDOW_OUTSIDE_CRYPTO_PERIOD`,
    then the uniqueness rules `ERR_DUPLICATE_RADIO_ID` and
    `ERR_DUPLICATE_TALKGROUP_ID`, then `ERR_TEMPLATE_SLOT_CAPACITY_EXCEEDED`, then
    `ERR_REVISION_LIMIT_EXCEEDED`, then the fiscal rules in the order
    `ERR_AGENCY_VOTING_SUSPENDED`, `ERR_FEE_PERIOD_INVALID`,
    `ERR_PAYMENT_EXCEEDS_BALANCE`, and finally the capacity rule
    `ERR_NO_PREEMPTABLE_TALKPATH`."

    Design: Difficulty/priority_pair_validation_conflict/patch_coverage_safety_outranks_encryption_mode_mismatch
    """
    agency, site, clear_talkgroup, encrypted_talkgroup = _kilo_general_grade_site(api)
    assert_fields(site, coverage_class=COVERAGE_GENERAL)

    conflicted = api.create_interop_patch(
        f.interop_patch_payload(
            clear_talkgroup["id"],
            encrypted_talkgroup["id"],
            agency["id"],
            scheduled_start="2026-08-01T00:00:00Z",
            scheduled_end="2026-08-01T06:00:00Z",
        ),
        make_dispatcher_headers(agency["id"]),
    )
    error = validate_error(conflicted, ERR_COVERAGE_CLASS_INSUFFICIENT, 422)
    assert error["error_id"] != ERR_ENCRYPTION_MODE_MISMATCH, (
        "coverage sufficiency precedes the referential encryption rule in group 13"
    )

    # Nothing was booked by the refused request.
    assert_fields(fx.read_talkgroup(api, clear_talkgroup["id"]), active_patch_count=0)
    assert_fields(
        fx.read_talkgroup(api, encrypted_talkgroup["id"]), active_patch_count=0
    )
    assert_fields(fx.read_agency(api, agency["id"]), active_patch_request_count=0)


def test_patch_encryption_mismatch_surfaces_once_coverage_is_mission_critical(
    api: ApiClient, clock_at_start: str
):
    """Re-surveying the same site to `MISSION_CRITICAL` clears the outranking
    guard, and the identical request now fails on the encryption pairing — proving
    the lower-priority defect was real all along and merely masked.

    PRD 3.6: "The two encryption postures must be compatible: if either talkgroup
    is `ENCRYPTED`, the other must be `ENCRYPTED` or `SELECTABLE`."

    PRD 3.6: "A `CLEAR` talkgroup may never be patched to an `ENCRYPTED` one, and
    the attempt is rejected with `ERR_ENCRYPTION_MODE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/patch_coverage_safety_outranks_encryption_mode_mismatch
    """
    agency, site, clear_talkgroup, encrypted_talkgroup = _kilo_general_grade_site(api)
    payload = f.interop_patch_payload(
        clear_talkgroup["id"],
        encrypted_talkgroup["id"],
        agency["id"],
        scheduled_start="2026-08-01T00:00:00Z",
        scheduled_end="2026-08-01T06:00:00Z",
    )
    dispatcher = make_dispatcher_headers(agency["id"])

    # Baseline: while the site is only GENERAL, the coverage guard answers first.
    validate_error(
        api.create_interop_patch(payload, dispatcher),
        ERR_COVERAGE_CLASS_INSUFFICIENT,
        422,
    )

    # raw 98.50 selects tier A and derates 0.5pp to 98.0, at least 97.0.
    resurveyed = validate_success(
        api.submit_coverage(
            site["id"], f.coverage_payload(985, 1000, site["version"]), RF_ENGINEER
        ),
        200,
    )
    assert_coverage_result(resurveyed, 98.0, DERATE_A, COVERAGE_MISSION_CRITICAL)

    unmasked = api.create_interop_patch(payload, dispatcher)
    validate_error(unmasked, ERR_ENCRYPTION_MODE_MISMATCH, 422)

    assert_fields(fx.read_talkgroup(api, clear_talkgroup["id"]), active_patch_count=0)
    assert_fields(
        fx.read_talkgroup(api, encrypted_talkgroup["id"]), active_patch_count=0
    )
    assert_fields(fx.read_agency(api, agency["id"]), active_patch_request_count=0)
