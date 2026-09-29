"""Talkpath allocation: the waterfall, preemption, release, and grade of service.

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
    ERR_EMERGENCY_PREEMPTION_NOT_PERMITTED,
    ERR_NO_PREEMPTABLE_TALKPATH,
    ERR_SITE_OFF_AIR,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_nulls,
    assert_one_decimal_place,
    assert_pagination_meta,
    assert_pct,
    assert_site_capacity_counters,
)
from test_helpers.constants import (
    AGENCY_TYPE_EMS,
    AGENCY_TYPE_FIRE,
    AGENCY_TYPE_PUBLIC_WORKS,
    BACKUP_BATTERY_ONLY,
    BACKUP_GENERATOR,
    CAPACITY_EMERGENCY_ONLY,
    CAPACITY_NORMAL,
    CAPACITY_PRIORITY_ONLY,
    CAUSE_COMMERCIAL_POWER_LOSS,
    ENC_CLEAR,
    EVENT_ESCALATED,
    EVENT_SURGE_ACTIVE,
    KIND_EMERGENCY,
    KIND_NORMAL,
    KIND_PRIORITY,
    MODEL_MOBILE,
    MODEL_PORTABLE,
    OUTCOME_BUSIED,
    OUTCOME_GRANTED,
    OUTCOME_RELEASED,
    SITE_IN_SERVICE,
    SITE_OFF_AIR,
    STANDARD_P25_PHASE1,
    STANDARD_P25_PHASE2,
    TG_KIND_DISPATCH,
)
from test_helpers.test_users import SYSTEM_ADMIN, make_dispatcher_headers


def _fleet_on_channel_pool(
    api: ApiClient,
    *,
    agency_name: str,
    agency_code: str,
    agency_type: str,
    recorder_retention_days: int,
    site_code: str,
    site_name: str,
    channel_capacity: int,
    template_name: str,
    target_standard: str,
    tg_alias: str,
    tg_decimal_id: int,
    units,
    backup_power_type: str = BACKUP_GENERATOR,
    generator_fuel_hours=None,
    battery_runtime_minutes=None,
):
    """One agency, one site with a channel pool, one published template, one
    `CLEAR` `DISPATCH` talkgroup homed on that site, and one `ASSIGNED` radio per
    entry of ``units``.

    Each ``units`` entry is a keyword dict forwarded to the unit payload, so the
    optional provisioning inputs are omitted whenever a caller wants the declared
    defaults to apply. Returns ``(agency, site, talkgroup, unit_rows)``.
    """
    agency = fx.register_agency(
        api,
        name=agency_name,
        agency_code=agency_code,
        agency_type=agency_type,
        recorder_retention_days=recorder_retention_days,
    )
    site = fx.register_site(
        api,
        site_code=site_code,
        name=site_name,
        channel_capacity=channel_capacity,
        backup_power_type=backup_power_type,
        generator_fuel_hours=generator_fuel_hours,
        battery_runtime_minutes=battery_runtime_minutes,
    )
    template = fx.published_template(
        api,
        template_name=template_name,
        target_standard=target_standard,
        talkgroup_slot_count=4,
    )
    talkgroup = fx.create_talkgroup(
        api,
        agency["id"],
        site["id"],
        alias=tg_alias,
        tg_decimal_id=tg_decimal_id,
        kind=TG_KIND_DISPATCH,
        encryption_mode=ENC_CLEAR,
    )
    unit_rows = [
        fx.assigned_unit(api, agency["id"], template["id"], **spec) for spec in units
    ]
    return agency, site, talkgroup, unit_rows


def test_grade_of_service_rounds_half_up_to_one_decimal(
    api: ApiClient, clock_at_start: str
):
    """Two grants and one busy on a two-usable-channel site give 100 * 2 / 3 ==
    66.666..., which the site must store as exactly 66.7 — one decimal place,
    rounded half up, never 66.6 and never 66.67.

    PRD 3.8: "`grade_of_service_pct` is then one hundred multiplied by
    `granted_request_count` divided by the sum of `granted_request_count` and
    `busied_request_count`, rounded half up to one decimal place — and exactly
    100.0 when that sum is zero, which is why a brand-new site reports perfect
    service."

    PRD 3.8: "The site's **usable** channel count is its `channel_capacity` less
    the one channel permanently reserved as the control channel."

    Design: Corner/calculations/grade_of_service_precision_rounds_half_up_to_one_decimal
    """
    agency, site, talkgroup, units = _fleet_on_channel_pool(
        api,
        agency_name="Grade Of Service Agency",
        agency_code="GOS01",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
        site_code="GOS-1",
        site_name="Grade One",
        channel_capacity=3,
        template_name="GOS-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        tg_alias="GOS-A",
        tg_decimal_id=1201,
        units=[
            {"serial_number": "GOS0001", "radio_id": 29001, "model": MODEL_PORTABLE},
            {"serial_number": "GOS0002", "radio_id": 29002, "model": MODEL_PORTABLE},
            {"serial_number": "GOS0003", "radio_id": 29003, "model": MODEL_PORTABLE},
        ],
    )
    assert_site_capacity_counters(
        site,
        busy_talkpaths=0,
        peak_talkpaths=0,
        granted_request_count=0,
        busied_request_count=0,
        grade_of_service_pct=100.0,
    )

    # Channel capacity 3 leaves two usable channels once the control channel is
    # taken out, so the headroom walks 2 -> 1 -> 0 across three NORMAL requests.
    first = fx.request_talkpath(
        api, site["id"], talkgroup["id"], units[0]["id"], agency["id"]
    )
    assert_fields(
        first,
        outcome=OUTCOME_GRANTED,
        available_talkpaths_at_decision=2,
        reserve_talkpaths_at_decision=0,
    )

    second = fx.request_talkpath(
        api, site["id"], talkgroup["id"], units[1]["id"], agency["id"]
    )
    assert_fields(
        second,
        outcome=OUTCOME_GRANTED,
        available_talkpaths_at_decision=1,
        reserve_talkpaths_at_decision=0,
    )

    # The third request is refused for want of a channel, yet it is persisted and
    # still answered 201 -- `request_talkpath` asserts that status itself.
    third = fx.request_talkpath(
        api, site["id"], talkgroup["id"], units[2]["id"], agency["id"]
    )
    assert_fields(
        third,
        outcome=OUTCOME_BUSIED,
        available_talkpaths_at_decision=0,
        reserve_talkpaths_at_decision=0,
    )
    assert_nulls(third, "granted_at")

    settled = fx.read_site(api, site["id"])
    assert_site_capacity_counters(
        settled,
        busy_talkpaths=2,
        peak_talkpaths=2,
        granted_request_count=2,
        busied_request_count=1,
    )
    assert_pct(settled["grade_of_service_pct"], 66.7, "grade_of_service_pct")
    assert_one_decimal_place(settled["grade_of_service_pct"], "grade_of_service_pct")
    assert settled["grade_of_service_pct"] != 66.6, "66.666... must not truncate down"


def test_emergency_request_from_unit_without_button_rejected(
    api: ApiClient, clock_at_start: str
):
    """The emergency button is a provisioning privilege, not a request flag: a
    radio without it is refused outright even though the site is idle and has
    every channel free, and the refused request is never persisted.

    PRD 3.8: "An `EMERGENCY` request is the emergency button, and it is entitled
    to take a channel away from somebody else. Only a radio whose
    `emergency_button_enabled` flag is true may originate one; a radio without
    that provisioning is refused with `ERR_EMERGENCY_PREEMPTION_NOT_PERMITTED`."

    Design: Corner/validations/emergency_request_from_unit_without_button_rejected
    """
    agency, site, talkgroup, units = _fleet_on_channel_pool(
        api,
        agency_name="Emergency Button Agency",
        agency_code="EMB01",
        agency_type=AGENCY_TYPE_EMS,
        recorder_retention_days=90,
        site_code="EMB-1",
        site_name="Emergency One",
        channel_capacity=6,
        template_name="EMB-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        tg_alias="EMB-A",
        tg_decimal_id=1801,
        units=[
            {
                "serial_number": "EMB0001",
                "radio_id": 32001,
                "model": MODEL_PORTABLE,
                "emergency_button_enabled": False,
            }
        ],
    )
    unit = units[0]
    assert_fields(unit, emergency_button_enabled=False)

    refused = api.create_talkpath_request(
        f.talkpath_payload(
            site["id"], talkgroup["id"], unit["id"], request_kind=KIND_EMERGENCY
        ),
        make_dispatcher_headers(agency["id"]),
    )
    validate_error(refused, ERR_EMERGENCY_PREEMPTION_NOT_PERMITTED, 422)

    # A rejected request is not a BUSIED request: nothing at all is written.
    rows, meta = validate_paginated(
        api.list_talkpath_requests(SYSTEM_ADMIN, {"site_id": site["id"]})
    )
    assert_pagination_meta(meta, total_count=0)
    assert rows == [], f"a refused EMERGENCY request must not be persisted: {rows}"
    assert_site_capacity_counters(
        fx.read_site(api, site["id"]),
        busy_talkpaths=0,
        granted_request_count=0,
        busied_request_count=0,
        grade_of_service_pct=100.0,
    )

    # The very same radio, talkgroup and site succeed as ordinary traffic, which
    # isolates the refusal to the request class rather than the fleet setup.
    ordinary = fx.request_talkpath(
        api,
        site["id"],
        talkgroup["id"],
        unit["id"],
        agency["id"],
        request_kind=KIND_NORMAL,
    )
    assert_fields(ordinary, outcome=OUTCOME_GRANTED, request_kind=KIND_NORMAL)


def test_priority_request_above_priority_class_max_rejected(
    api: ApiClient, clock_at_start: str
):
    """`PRIORITY` is gated on the radio's importance and the threshold is 3: a
    `priority_class` 5 radio is refused while a `priority_class` 3 radio on the
    same idle site is granted, so the comparison is strictly greater than three.

    PRD 3.8: "A `PRIORITY` request may eat into the surge reserve but may never
    displace anybody. It is only available to sufficiently important radios: when
    the originating unit's `priority_class` is greater than 3, the request is
    refused outright with `ERR_EMERGENCY_PREEMPTION_NOT_PERMITTED`."

    PRD 3.8: "A granted request stamps `granted_at` with now and snapshots the
    originating unit's `priority_class` into `priority_class_at_grant`, which is
    the ranking key any future preemption will consult."

    Design: Corner/validations/priority_request_above_priority_class_max_rejected
    """
    agency, site, talkgroup, units = _fleet_on_channel_pool(
        api,
        agency_name="Priority Class Agency",
        agency_code="PRC01",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
        site_code="PRC-1",
        site_name="Priority One",
        channel_capacity=6,
        template_name="PRC-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        tg_alias="PRC-A",
        tg_decimal_id=1901,
        units=[
            {
                "serial_number": "PRC0005",
                "radio_id": 33005,
                "model": MODEL_PORTABLE,
                "priority_class": 5,
            },
            {
                "serial_number": "PRC0003",
                "radio_id": 33003,
                "model": MODEL_PORTABLE,
                "priority_class": 3,
            },
        ],
    )
    class_five, class_three = units
    assert_fields(class_five, priority_class=5)
    assert_fields(class_three, priority_class=3)

    refused = api.create_talkpath_request(
        f.talkpath_payload(
            site["id"], talkgroup["id"], class_five["id"], request_kind=KIND_PRIORITY
        ),
        make_dispatcher_headers(agency["id"]),
    )
    validate_error(refused, ERR_EMERGENCY_PREEMPTION_NOT_PERMITTED, 422)

    granted = fx.request_talkpath(
        api,
        site["id"],
        talkgroup["id"],
        class_three["id"],
        agency["id"],
        request_kind=KIND_PRIORITY,
    )
    assert_fields(
        granted,
        outcome=OUTCOME_GRANTED,
        request_kind=KIND_PRIORITY,
        priority_class_at_grant=3,
    )

    # Only the accepted request moved the counters; the refusal left no trace.
    assert_site_capacity_counters(
        fx.read_site(api, site["id"]),
        busy_talkpaths=1,
        granted_request_count=1,
        busied_request_count=0,
        grade_of_service_pct=100.0,
    )


def test_error_no_preemptable_talkpath_when_only_emergency_grants_hold_channels(
    api: ApiClient, clock_at_start: str
):
    """The preemption victim pool is narrow by design: on a one-usable-channel
    site whose only grant is itself an `EMERGENCY` talkpath, a second emergency
    finds nobody it is allowed to displace and is refused rather than busied.

    PRD 3.8: "The candidate set is every talkpath request on the *same site*
    whose `outcome` is `GRANTED`, whose `released_at` is still null, and whose
    `request_kind` is `NORMAL`; `PRIORITY` and `EMERGENCY` grants are never
    victims and already-released rows are excluded."

    PRD 3.8: "If the candidate set is empty, the emergency request is refused
    with `ERR_NO_PREEMPTABLE_TALKPATH` at HTTP 409."

    Design: Corner/errors/error_no_preemptable_talkpath_when_only_emergency_grants_hold_channels
    """
    agency, site, talkgroup, units = _fleet_on_channel_pool(
        api,
        agency_name="No Preemption Agency",
        agency_code="NPT01",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
        site_code="NPT-1",
        site_name="No Preempt One",
        channel_capacity=2,
        template_name="NPT-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        tg_alias="NPT-A",
        tg_decimal_id=2201,
        units=[
            {
                "serial_number": "NPT0001",
                "radio_id": 41001,
                "model": MODEL_PORTABLE,
                "emergency_button_enabled": True,
            },
            {
                "serial_number": "NPT0002",
                "radio_id": 41002,
                "model": MODEL_PORTABLE,
                "emergency_button_enabled": True,
            },
        ],
    )
    holder, challenger = units

    # Baseline: the site's single usable channel is taken by an EMERGENCY grant,
    # which the waterfall handed over without needing a victim at all.
    held = fx.request_talkpath(
        api,
        site["id"],
        talkgroup["id"],
        holder["id"],
        agency["id"],
        request_kind=KIND_EMERGENCY,
    )
    assert_fields(
        held, outcome=OUTCOME_GRANTED, available_talkpaths_at_decision=1
    )
    assert_nulls(held, "preempted_request_id")
    assert_site_capacity_counters(fx.read_site(api, site["id"]), busy_talkpaths=1)

    refused = api.create_talkpath_request(
        f.talkpath_payload(
            site["id"], talkgroup["id"], challenger["id"], request_kind=KIND_EMERGENCY
        ),
        make_dispatcher_headers(agency["id"]),
    )
    validate_error(refused, ERR_NO_PREEMPTABLE_TALKPATH, 409)

    # The sitting emergency grant is untouched -- a failed hunt for a victim must
    # not half-release the incumbent.
    incumbent = validate_success(api.get_talkpath_request(held["id"], SYSTEM_ADMIN), 200)
    assert_fields(incumbent, outcome=OUTCOME_GRANTED)
    assert_nulls(incumbent, "released_at", "preempted_request_id", "hold_seconds")

    assert_site_capacity_counters(
        fx.read_site(api, site["id"]),
        busy_talkpaths=1,
        granted_request_count=1,
        busied_request_count=0,
        grade_of_service_pct=100.0,
    )

    # A refusal is not a busy signal, so no row exists for the challenger and the
    # grade-of-service statistic never sees the attempt.
    _rows, meta = validate_paginated(
        api.list_talkpath_requests(SYSTEM_ADMIN, {"unit_id": challenger["id"]})
    )
    assert_pagination_meta(meta, total_count=0)


def test_error_site_off_air_blocks_talkpath_request(
    api: ApiClient, clock_at_start: str
):
    """A `BATTERY_ONLY` site with no battery at all is out of backup time the
    instant backup engages, so the first `ESCALATE` lands on tier 3 and takes the
    site `OFF_AIR` — after which the channel pool refuses every request.

    PRD 3.7: "First, the parent site's `capacity_mode` becomes `EMERGENCY_ONLY`,
    and its `status` becomes `OFF_AIR` when `backup_minutes_remaining` has reached
    exactly 0 or `DEGRADED` when some backup time is still left."

    PRD 3.8: "The originating unit must not be `RETIRED` (otherwise
    `ERR_UNIT_RETIRED`), the talkgroup must be `ACTIVE` (otherwise
    `ERR_TALKGROUP_LOCKED`), and the site must not be `OFF_AIR` (otherwise
    `ERR_SITE_OFF_AIR`)."

    Design: Corner/errors/error_site_off_air_blocks_talkpath_request
    """
    agency, site, talkgroup, units = _fleet_on_channel_pool(
        api,
        agency_name="Off Air Agency",
        agency_code="OFA01",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
        site_code="OFA-1",
        site_name="Off Air One",
        channel_capacity=4,
        backup_power_type=BACKUP_BATTERY_ONLY,
        battery_runtime_minutes=0,
        template_name="OFA-BASE-1",
        target_standard=STANDARD_P25_PHASE2,
        tg_alias="OFA-A",
        tg_decimal_id=2301,
        units=[{"serial_number": "OFA0001", "radio_id": 42001, "model": MODEL_PORTABLE}],
    )
    unit = units[0]

    _opened, on_backup = fx.outage_on_backup(
        api, site["id"], cause=CAUSE_COMMERCIAL_POWER_LOSS
    )
    assert_fields(on_backup, backup_minutes_remaining=0, escalation_tier=0)

    escalated = fx.escalate(api, on_backup["id"])
    assert_fields(
        escalated,
        status=EVENT_ESCALATED,
        escalation_tier=3,
        backup_minutes_remaining=0,
        preempted_talkpath_count=0,
    )
    dark_site = fx.read_site(api, site["id"])
    assert_fields(
        dark_site, status=SITE_OFF_AIR, capacity_mode=CAPACITY_EMERGENCY_ONLY
    )

    refused = api.create_talkpath_request(
        f.talkpath_payload(
            site["id"],
            talkgroup["id"],
            unit["id"],
            request_kind=KIND_NORMAL,
            site_event_id=escalated["id"],
        ),
        make_dispatcher_headers(agency["id"]),
    )
    validate_error(refused, ERR_SITE_OFF_AIR, 409)

    # The refusal happens before the waterfall, so no counter -- not even the
    # busied counter -- records the attempt.
    assert_site_capacity_counters(
        fx.read_site(api, site["id"]),
        busy_talkpaths=0,
        granted_request_count=0,
        busied_request_count=0,
        grade_of_service_pct=100.0,
    )
    _rows, meta = validate_paginated(
        api.list_talkpath_requests(SYSTEM_ADMIN, {"site_id": site["id"]})
    )
    assert_pagination_meta(meta, total_count=0)


def _surge_site_at_zero_headroom(api: ApiClient):
    """Site `SUR-1` under a declared surge with exactly one free channel and a
    surge reserve of exactly one, so the `NORMAL` headroom is exactly zero.

    Channel capacity 5 leaves 4 usable channels; three `NORMAL` grants take the
    busy figure to 3, leaving available 1; the surge then sets the reserve to
    ``min(floor(4 * 25 / 100), 4) == 1``. Returns
    ``(agency, site, talkgroup, units, surge_event)`` with the logical clock at
    `2026-08-01T00:00:00Z`.
    """
    agency, site, talkgroup, units = _fleet_on_channel_pool(
        api,
        agency_name="Lima Fire Rescue",
        agency_code="FIRL1",
        agency_type=AGENCY_TYPE_FIRE,
        recorder_retention_days=90,
        site_code="SUR-1",
        site_name="Surge One",
        channel_capacity=5,
        generator_fuel_hours=24,
        template_name="LIMA-BASE-1",
        target_standard=STANDARD_P25_PHASE1,
        tg_alias="LFD-DISP",
        tg_decimal_id=401,
        units=[
            {
                "serial_number": "SNL001",
                "radio_id": 8001,
                "model": MODEL_PORTABLE,
                "priority_class": 7,
            },
            {
                "serial_number": "SNL002",
                "radio_id": 8002,
                "model": MODEL_PORTABLE,
                "priority_class": 7,
            },
            {
                "serial_number": "SNL003",
                "radio_id": 8003,
                "model": MODEL_MOBILE,
                "priority_class": 7,
            },
            {
                "serial_number": "SNL004",
                "radio_id": 8004,
                "model": MODEL_MOBILE,
                "priority_class": 2,
            },
        ],
    )
    for radio in units[:3]:
        granted = fx.request_talkpath(
            api, site["id"], talkgroup["id"], radio["id"], agency["id"]
        )
        assert_fields(granted, outcome=OUTCOME_GRANTED)

    loaded = fx.read_site(api, site["id"])
    assert_site_capacity_counters(
        loaded, busy_talkpaths=3, granted_request_count=3, grade_of_service_pct=100.0
    )
    assert_fields(loaded, capacity_mode=CAPACITY_NORMAL, status=SITE_IN_SERVICE)

    surge_event = fx.declare_surge(api, site["id"])
    assert_fields(surge_event, status=EVENT_SURGE_ACTIVE)
    surged_site = fx.read_site(api, site["id"])
    assert_fields(
        surged_site, capacity_mode=CAPACITY_PRIORITY_ONLY, status=SITE_IN_SERVICE
    )
    return agency, site, talkgroup, units, surge_event


def test_normal_request_busied_at_exactly_zero_surge_headroom(
    api: ApiClient, clock_at_start: str
):
    """One free channel against a surge reserve of one is headroom of exactly
    zero, and the endpoint of that range is closed against the caller: the
    comparison is `> 0`, never `>= 0`, so the call is busied while the channel it
    could physically have used sits idle.

    PRD 3.8: "The **surge reserve** is 0 whenever the site's `capacity_mode` is
    `NORMAL`; otherwise it is a quarter of the usable count with any fraction
    discarded downward, capped at 4 channels, whichever is smaller."

    PRD 3.8: "The comparison is strictly greater than zero: a site with exactly
    zero channels of headroom above its reserve busies the call."

    PRD 3.8: "Both of the latter two figures are snapshotted onto the request
    itself as `available_talkpaths_at_decision` and
    `reserve_talkpaths_at_decision`, and they are recorded whatever the outcome,
    so a refused request still tells an auditor exactly how tight the site was."

    Design: Difficulty/boundary_precision_check/normal_talkpath_busied_at_exact_zero_surge_headroom
    """
    agency, site, talkgroup, units, surge_event = _surge_site_at_zero_headroom(api)

    busied = fx.request_talkpath(
        api,
        site["id"],
        talkgroup["id"],
        units[0]["id"],
        agency["id"],
        request_kind=KIND_NORMAL,
        site_event_id=surge_event["id"],
    )
    assert_fields(
        busied,
        outcome=OUTCOME_BUSIED,
        available_talkpaths_at_decision=1,
        reserve_talkpaths_at_decision=1,
        site_event_id=surge_event["id"],
    )
    assert_nulls(busied, "granted_at")

    # available - reserve == 1 - 1 == 0, and zero does not clear the bar.
    assert (
        busied["available_talkpaths_at_decision"]
        - busied["reserve_talkpaths_at_decision"]
        == 0
    ), "the scenario must sit exactly on the boundary, not inside it"

    # The busy signal never took a channel, but it did enter the statistic.
    assert_site_capacity_counters(
        fx.read_site(api, site["id"]),
        busy_talkpaths=3,
        peak_talkpaths=3,
        granted_request_count=3,
        busied_request_count=1,
        grade_of_service_pct=75.0,
    )


def test_priority_request_consumes_the_reserve_the_normal_request_could_not(
    api: ApiClient, clock_at_start: str
):
    """The same one free channel and the same reserve of one, and the outcome
    flips purely on the request class: `PRIORITY` does not subtract the reserve,
    so it takes the channel the `NORMAL` request was just refused.

    PRD 3.8: "Otherwise it is `GRANTED` when the available headroom is greater
    than zero — the reserve is not subtracted for this class — and `BUSIED`
    otherwise."

    PRD 3.8: "A busied request leaves `granted_at` null, adds one to
    `busied_request_count`, and triggers the same grade-of-service recomputation;
    the row is still persisted and still answered with 201, because refused calls
    are exactly what a grade-of-service statistic is made of."

    PRD 3.7: "Its only consequence is that the site's `capacity_mode` becomes
    `PRIORITY_ONLY`; the site's `status` is deliberately left unchanged, because a
    surge is a demand problem rather than an infrastructure fault."

    Design: Difficulty/boundary_precision_check/normal_talkpath_busied_at_exact_zero_surge_headroom
    """
    agency, site, talkgroup, units, surge_event = _surge_site_at_zero_headroom(api)

    busied = fx.request_talkpath(
        api,
        site["id"],
        talkgroup["id"],
        units[0]["id"],
        agency["id"],
        request_kind=KIND_NORMAL,
        site_event_id=surge_event["id"],
    )
    assert_fields(busied, outcome=OUTCOME_BUSIED)

    # Same site, same instant, same snapshotted headroom -- different class.
    priority = fx.request_talkpath(
        api,
        site["id"],
        talkgroup["id"],
        units[3]["id"],
        agency["id"],
        request_kind=KIND_PRIORITY,
        site_event_id=surge_event["id"],
    )
    assert_fields(
        priority,
        outcome=OUTCOME_GRANTED,
        available_talkpaths_at_decision=1,
        reserve_talkpaths_at_decision=1,
        priority_class_at_grant=2,
    )
    assert_nulls(priority, "preempted_request_id", "released_at", "hold_seconds")
    assert_instant_equals(priority["granted_at"], clock_at_start, "granted_at")

    final = fx.read_site(api, site["id"])
    assert_site_capacity_counters(
        final,
        busy_talkpaths=4,
        peak_talkpaths=4,
        granted_request_count=4,
        busied_request_count=1,
        grade_of_service_pct=80.0,
    )
    assert_fields(final, capacity_mode=CAPACITY_PRIORITY_ONLY, status=SITE_IN_SERVICE)


def _occupancy_site_with_three_grants(api: ApiClient):
    """Site `OCC-1` holding three `NORMAL` grants, with the clock then advanced
    ninety seconds past the moment they were taken.

    Channel capacity 8 leaves 7 usable channels and the site stays in
    `capacity_mode` `NORMAL`, so the surge reserve is 0 and none of the three
    requests is anywhere near the boundary. Returns
    ``(agency, site, talkgroup, grants)`` with the logical clock at
    `2026-08-01T00:01:30Z`.
    """
    agency, site, talkgroup, units = _fleet_on_channel_pool(
        api,
        agency_name="Romeo Public Works",
        agency_code="PWKR1",
        agency_type=AGENCY_TYPE_PUBLIC_WORKS,
        recorder_retention_days=30,
        site_code="OCC-1",
        site_name="Occupancy One",
        channel_capacity=8,
        generator_fuel_hours=12,
        template_name="ROMEO-BASE-1",
        target_standard=STANDARD_P25_PHASE1,
        tg_alias="PW-DISP",
        tg_decimal_id=501,
        units=[
            {
                "serial_number": "SNR001",
                "radio_id": 10001,
                "model": MODEL_MOBILE,
                "priority_class": 6,
            },
            {
                "serial_number": "SNR002",
                "radio_id": 10002,
                "model": MODEL_MOBILE,
                "priority_class": 6,
            },
            {
                "serial_number": "SNR003",
                "radio_id": 10003,
                "model": MODEL_PORTABLE,
                "priority_class": 6,
            },
        ],
    )
    assert_fields(fx.read_site(api, site["id"]), capacity_mode=CAPACITY_NORMAL)

    grants = []
    for radio in units:
        granted = fx.request_talkpath(
            api, site["id"], talkgroup["id"], radio["id"], agency["id"]
        )
        assert_fields(
            granted, outcome=OUTCOME_GRANTED, reserve_talkpaths_at_decision=0
        )
        assert_instant_equals(granted["granted_at"], "2026-08-01T00:00:00Z", "granted_at")
        grants.append(granted)

    fx.set_clock(api, "2026-08-01T00:01:30Z")
    return agency, site, talkgroup, grants


def _live_grant_count(api: ApiClient, site_id: str) -> int:
    """Count the site's talkpath rows that still hold a channel, straight from the
    list endpoint rather than from the denormalized counter under test."""
    rows, _meta = validate_paginated(
        api.list_talkpath_requests(
            SYSTEM_ADMIN, {"site_id": site_id, "outcome": OUTCOME_GRANTED}
        )
    )
    live = [row for row in rows if row["released_at"] is None]
    assert len(live) == len(rows), (
        "a row filtered as GRANTED must not already carry a released_at: "
        f"{[row['id'] for row in rows if row['released_at'] is not None]}"
    )
    return len(live)


def test_talkpath_release_conserves_site_channel_occupancy(
    api: ApiClient, clock_at_start: str
):
    """Channel occupancy is a conserved quantity: `busy_talkpaths` equals the
    number of live grants before the release and after it, so returning one of
    three channels takes the site from three to exactly two — recomputed from
    history, not decremented on faith.

    PRD 3.8: "`busy_talkpaths` is the number of requests for the site whose
    `outcome` is `GRANTED` and whose `released_at` is null."

    PRD 3.8: "On release, `released_at` is stamped with now, `hold_seconds` is
    computed as the number of whole seconds from `granted_at` to `released_at`
    with any partial second discarded downward, the site's `busy_talkpaths` falls
    by one, `grade_of_service_pct` is recomputed, and `peak_talkpaths` is
    deliberately left where it is."

    Design: Difficulty/compensating_invariant/talkpath_grant_then_release_conserves_site_occupancy
    """
    agency, site, talkgroup, grants = _occupancy_site_with_three_grants(api)

    before = fx.read_site(api, site["id"])
    assert_site_capacity_counters(
        before,
        busy_talkpaths=3,
        peak_talkpaths=3,
        granted_request_count=3,
        busied_request_count=0,
        grade_of_service_pct=100.0,
    )
    assert before["busy_talkpaths"] == _live_grant_count(api, site["id"]), (
        "the invariant must already hold before the release"
    )

    released = fx.release_talkpath(api, grants[2]["id"], agency["id"])
    assert_fields(released, outcome=OUTCOME_RELEASED, hold_seconds=90)
    assert_instant_equals(released["released_at"], "2026-08-01T00:01:30Z", "released_at")
    assert_instant_equals(released["granted_at"], clock_at_start, "granted_at")

    after = fx.read_site(api, site["id"])
    assert after["busy_talkpaths"] == 2, (
        f"occupancy must fall to 2, got {after['busy_talkpaths']}"
    )
    assert after["busy_talkpaths"] == _live_grant_count(api, site["id"]), (
        "the invariant must still hold after the release"
    )
    assert_fields(
        fx.read_talkgroup(api, talkgroup["id"]), home_site_id=site["id"]
    )


def test_talkpath_release_leaves_the_peak_and_the_grant_history_alone(
    api: ApiClient, clock_at_start: str
):
    """Two of the four counters are deliberately not conserved: the peak is a
    monotonic high-water mark that stays at three, and the released grant still
    counts as delivered service, so the grade of service stays 100.0 rather than
    being penalised for a hang-up.

    PRD 3.8: "`peak_talkpaths` is the greater of its previous value and the
    freshly computed busy figure — monotonic, and never lowered."

    PRD 3.8: "`granted_request_count` is the number of requests for the site whose
    `outcome` is `GRANTED`, `PREEMPTED`, or `RELEASED`; preempted and released rows
    still count as grants because the channel really was delivered."

    PRD 3.8: "`hold_seconds` stays null while a talkpath is still held and for any
    request that was `BUSIED`."

    Design: Difficulty/compensating_invariant/talkpath_grant_then_release_conserves_site_occupancy
    """
    agency, site, _talkgroup, grants = _occupancy_site_with_three_grants(api)

    fx.release_talkpath(api, grants[2]["id"], agency["id"])

    settled = fx.read_site(api, site["id"])
    assert_site_capacity_counters(
        settled,
        busy_talkpaths=2,
        peak_talkpaths=3,
        granted_request_count=3,
        busied_request_count=0,
        grade_of_service_pct=100.0,
    )

    # The two survivors are untouched: still held, so still no hold_seconds.
    for grant in grants[:2]:
        survivor = validate_success(
            api.get_talkpath_request(grant["id"], SYSTEM_ADMIN), 200
        )
        assert_fields(survivor, outcome=OUTCOME_GRANTED)
        assert_nulls(survivor, "released_at", "hold_seconds")
