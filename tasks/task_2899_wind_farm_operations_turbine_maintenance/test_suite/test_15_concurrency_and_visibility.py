"""Version guards, the rolling reset window and the freshness of a first read."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_STALE_FARM_VERSION, ERR_STALE_TURBINE_VERSION
from test_helpers.assertions import (
    assert_instant_equals,
    assert_total_count,
    assert_turbine_dimensions,
    assert_two_dp,
    created,
)
from test_helpers.constants import (
    AVAILABILITY_ONLINE,
    CURTAILMENT_ACTIVE,
    CURTAILMENT_CURTAILED,
    CURTAILMENT_PENDING,
    CURTAILMENT_REASON_NOISE,
    CURTAILMENT_REASON_WILDLIFE,
    CURTAILMENT_RELEASED,
    CURTAILMENT_UNCONSTRAINED,
    DISPOSITION_REMOTE_RESET,
    RESET_OUTCOME_FAILED,
    RESET_OUTCOME_SUCCEEDED,
    SETTLEMENT_DRAFT,
    TRIAGE_CLEARED,
    TRIAGE_RESET_PENDING,
)
from test_helpers.factories import (
    curtailment_payload,
    landowner_settlement_payload,
    turbine_payload,
)
from test_helpers.fixtures import (
    raise_fault,
    read_farm,
    read_fault_event,
    read_turbine,
    remote_reset,
    set_clock,
    setup_faultable_site,
    setup_farm_and_model,
    setup_stale_version_parents,
    triage,
)
from test_helpers.test_users import (
    make_commercial_headers,
    make_control_room_headers,
    make_site_admin_headers,
)


def test_both_version_guards_refuse_a_stale_view_with_their_own_code(api):
    """One stale farm version and one stale turbine version, two different refusals.

    Each parent moved on through an ordinary business write, and each retry sends the very
    same body with nothing but the version field refreshed.

    PRD §2.7: "Drafting a landowner settlement — the request handled by
    `POST /wind-ops/farms/{id}/landowner-settlements` — requires a non-optional
    `expected_wind_farm_version` field carrying the client's last observed `version` of the
    target `WindFarm`."
    PRD §2.7: "If that value does not equal the farm's current `version`, the request is
    rejected with `ERR_STALE_FARM_VERSION` (HTTP 412) and nothing is written."
    PRD §2.7: "A successful draft creation increments the farm's `version` by 1, which means a
    client drafting two settlements in sequence must re-read the farm between them."
    PRD §2.7: "Issuing a curtailment instruction — the request handled by
    `POST /wind-ops/turbines/{id}/curtailment-orders` — requires a non-optional
    `expected_turbine_version` field carrying the client's last observed `version` of the
    target `Turbine`."
    PRD §2.7: "If that value does not equal the turbine's current `version`, the request is
    rejected with `ERR_STALE_TURBINE_VERSION` (HTTP 412)."
    PRD §2.4: "`updated_at` is refreshed on every mutation of the row, and `version` starts at
    1 when the row is created and increments by exactly 1 on every mutation of that row,
    including mutations that reach the row by cascade from an operation that named a different
    resource."
    PRD §3.9: "A drafted settlement sits in `state` `DRAFT` with `void_reason` null, and it
    posts **nothing** to the farm ledger — a draft is not part of `opex_accrued_cents`."
    PRD §3.8: "Issuance requires `expected_turbine_version` per §2.7, creates the order in
    `state` `PENDING` with `curtailed_hours` and `lost_energy_kwh` at 0, and increments the
    turbine's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_versions_are_rejected_on_both_declared_occ_rules
    """
    site = setup_stale_version_parents(api)
    farm_id = site["farm"]["id"]
    turbine_id = site["turbine"]["id"]

    stale_settlement = landowner_settlement_payload(
        site["farm_version_seen"],
        parcel_code="P-11",
        period_start_utc="2026-07-01T00:00:00Z",
        period_end_utc="2026-08-01T00:00:00Z",
        minimum_payment_cents=100000,
        road_damage_assessment_cents=0,
    )
    validate_error(
        api.create_landowner_settlement(farm_id, stale_settlement, make_commercial_headers()),
        ERR_STALE_FARM_VERSION,
        expected_status=412,
    )

    stale_curtailment = curtailment_payload(
        site["turbine_version_seen"],
        reason=CURTAILMENT_REASON_NOISE,
        start_utc="2026-08-02T00:00:00Z",
        end_utc="2026-08-02T06:00:00Z",
        power_limit_kw=1500,
        deemed_kwh_per_hour=500,
    )
    validate_error(
        api.create_curtailment_order(turbine_id, stale_curtailment, make_control_room_headers()),
        ERR_STALE_TURBINE_VERSION,
        expected_status=412,
    )

    fresh_farm_version = read_farm(api, farm_id)["version"]
    fresh_turbine_version = read_turbine(api, turbine_id)["version"]
    assert fresh_farm_version > site["farm_version_seen"], fresh_farm_version
    assert fresh_turbine_version > site["turbine_version_seen"], fresh_turbine_version

    assert_total_count(
        api.list_landowner_settlements(make_commercial_headers(), wind_farm_id=farm_id), 1
    )
    assert_total_count(
        api.list_curtailment_orders(make_control_room_headers(), turbine_id=turbine_id), 0
    )

    accepted_settlement = created(
        api.create_landowner_settlement(
            farm_id,
            dict(stale_settlement, expected_wind_farm_version=fresh_farm_version),
            make_commercial_headers(),
        )
    )
    assert accepted_settlement["state"] == SETTLEMENT_DRAFT

    accepted_curtailment = created(
        api.create_curtailment_order(
            turbine_id,
            dict(stale_curtailment, expected_turbine_version=fresh_turbine_version),
            make_control_room_headers(),
        )
    )
    assert accepted_curtailment["state"] == CURTAILMENT_PENDING


def test_the_rolling_reset_window_rolls_at_exactly_twenty_four_hours_and_counts_the_trigger(api):
    """One second short of the edge accumulates; landing on the edge restarts the window at 1.

    The window is brought up to date before the quota is read, so the attempt that trips the
    roll is itself the first attempt of the new window rather than a zeroth one.

    PRD §3.2: "Before the quota is examined, the rolling window is brought up to date: if the
    turbine's `reset_window_start_utc` is null, or if the logical clock has reached or passed
    that instant plus 24 hours, then `reset_window_start_utc` is set to the current logical
    clock and `remote_reset_count_24h` is reset to 0."
    PRD §3.2: "An eligible attempt always increments both counters — the event's
    `reset_attempt_count` by 1 and the turbine's `remote_reset_count_24h` by 1 — and then
    branches on the outcome with equal weight on each branch."
    PRD §3.2: "A `reset_outcome` of `FAILED` leaves the event in `RESET_PENDING` and the
    turbine in `FAULTED`, deliberately so: any remaining quota can still be spent on a further
    attempt from the same state, and escalation to `DISPATCH_REQUIRED` is a separate triage
    call rather than an automatic consequence of failure."
    PRD §3.2: "A `reset_outcome` of `SUCCEEDED` moves the event `RESET_PENDING → CLEARED`,
    stamps `cleared_at` with the current logical clock, clears the turbine's
    `active_fault_code` to null, and drives the availability dimension `FAULTED → ONLINE`."
    PRD §3.2: "Only then is eligibility tested, and it requires three things simultaneously:
    the event's `severity_class_pinned` is `RESETTABLE`, its `reset_attempt_count` is
    **strictly** below its `max_remote_resets_pinned`, and the turbine's `curtailment_state` is
    not `FORCED_STOP`."

    Design: Corner/cross_cutting_complexity_layers/remote_reset_counter_rolls_over_at_exactly_twenty_four_hours
    """
    site = setup_faultable_site(api)
    turbine_id = site["turbine"]["id"]

    first = raise_fault(api, turbine_id, "F-3001", "2026-08-01T00:00:00Z")
    triage(api, first["id"], DISPOSITION_REMOTE_RESET)
    failed = remote_reset(api, first["id"], RESET_OUTCOME_FAILED)
    assert failed["triage_state"] == TRIAGE_RESET_PENDING
    assert failed["reset_attempt_count"] == 1
    opened = read_turbine(api, turbine_id)
    assert opened["remote_reset_count_24h"] == 1, opened["remote_reset_count_24h"]
    assert_instant_equals(
        opened["reset_window_start_utc"], "2026-08-01T00:00:00Z", "reset_window_start_utc"
    )

    cleared = remote_reset(api, first["id"], RESET_OUTCOME_SUCCEEDED)
    assert cleared["triage_state"] == TRIAGE_CLEARED
    assert cleared["reset_attempt_count"] == 2
    inside = read_turbine(api, turbine_id)
    assert inside["remote_reset_count_24h"] == 2, inside["remote_reset_count_24h"]
    assert_instant_equals(
        inside["reset_window_start_utc"], "2026-08-01T00:00:00Z", "reset_window_start_utc"
    )

    set_clock(api, "2026-08-01T23:59:59Z")
    second = raise_fault(api, turbine_id, "F-3001", "2026-08-01T23:59:59Z")
    triage(api, second["id"], DISPOSITION_REMOTE_RESET)
    second_cleared = remote_reset(api, second["id"], RESET_OUTCOME_SUCCEEDED)
    assert second_cleared["reset_attempt_count"] == 1
    one_second_short = read_turbine(api, turbine_id)
    assert one_second_short["remote_reset_count_24h"] == 3, (
        one_second_short["remote_reset_count_24h"]
    )
    assert_instant_equals(
        one_second_short["reset_window_start_utc"],
        "2026-08-01T00:00:00Z",
        "reset_window_start_utc",
    )

    set_clock(api, "2026-08-02T00:00:00Z")
    third = raise_fault(api, turbine_id, "F-3001", "2026-08-02T00:00:00Z")
    triage(api, third["id"], DISPOSITION_REMOTE_RESET)
    third_cleared = remote_reset(api, third["id"], RESET_OUTCOME_SUCCEEDED)
    assert third_cleared["reset_attempt_count"] == 1
    rolled = read_turbine(api, turbine_id)
    assert rolled["remote_reset_count_24h"] == 1, rolled["remote_reset_count_24h"]
    assert_instant_equals(
        rolled["reset_window_start_utc"], "2026-08-02T00:00:00Z", "reset_window_start_utc"
    )
    assert_turbine_dimensions(rolled, AVAILABILITY_ONLINE)
    assert rolled["active_fault_code"] is None

    for event_id in (first["id"], second["id"], third["id"]):
        assert read_fault_event(api, event_id)["triage_state"] == TRIAGE_CLEARED


def test_activation_and_release_effects_are_complete_in_the_very_next_read(api):
    """Every derived figure is correct in the first read after the write that moved it.

    The farm's rollups are right in the read taken straight after the turbine is
    commissioned, and the curtailment ceiling is right in the first read after activation and
    again after release, with no intervening write to settle anything.

    PRD §3.1: "Commissioning sets `availability_state` to `ONLINE` and `curtailment_state` to
    `UNCONSTRAINED`, sets `active_curtailment_count` to 0 and `effective_power_limit_kw` to the
    model's `rated_power_kw`, computes the three service-due figures described in the next
    subsection, increments the farm's `turbine_count` by 1 and adds the model's
    `rated_power_kw` to the farm's `installed_capacity_kw`."
    PRD §3.1: "`turbine_count` is the count of the farm's turbines whose `availability_state`
    is anything other than `DECOMMISSIONED`, and `installed_capacity_kw` is the sum of
    `rated_power_kw` over that same set of turbines — both recomputed whenever a turbine joins
    or leaves service."
    PRD §3.8: "The `compensable` flag is derived, never supplied: it is true exactly when
    `reason` is `GRID`, and false for `NOISE`, `ICING` and `WILDLIFE`."
    PRD §3.8: "Activation increments the turbine's `active_curtailment_count` by 1 and sets its
    `effective_power_limit_kw` to the smallest `power_limit_kw` across all of that turbine's
    active orders — the most restrictive instruction wins."
    PRD §3.8: "The availability dimension is not written at all."
    PRD §3.8: "This is the one place where accrual is measured from what actually happened
    rather than from what was planned: `curtailed_hours` is the elapsed time from `start_utc`
    to `released_at` expressed in hours, **not** from `start_utc` to the order's `end_utc`, so
    an early release accrues strictly less than the order asked for."
    PRD §3.8: "`lost_energy_kwh` is `curtailed_hours` multiplied by `deemed_kwh_per_hour`,
    rounded half up to two decimal places."
    PRD §3.8: "The turbine's `active_curtailment_count` is decremented by 1, and
    `effective_power_limit_kw` is recomputed as the smallest `power_limit_kw` across the orders
    that remain active, or as the model's `rated_power_kw` — the uncurtailed nameplate ceiling
    — when none remain."
    PRD §3.8: "When `compensable` is false, the released `curtailed_hours` is added to the
    turbine's `counted_downtime_hours_period`, and nothing is added when it is true."
    PRD §2.12: "Derived fields are **recomputed, not patched**."

    Design: Corner/consistency_model/activation_effects_are_visible_in_the_same_request_with_no_re_read_delay
    """
    site = setup_farm_and_model(api)
    farm_id = site["farm"]["id"]

    turbine = created(
        api.create_turbine(
            farm_id, turbine_payload(site["model"]["id"]), make_site_admin_headers()
        )
    )
    farm = read_farm(api, farm_id)
    assert farm["turbine_count"] == 1, farm["turbine_count"]
    assert farm["installed_capacity_kw"] == 4200, farm["installed_capacity_kw"]

    order = created(
        api.create_curtailment_order(
            turbine["id"],
            curtailment_payload(
                turbine["version"],
                reason=CURTAILMENT_REASON_WILDLIFE,
                start_utc="2026-08-01T00:00:00Z",
                end_utc="2026-08-01T04:00:00Z",
                power_limit_kw=1200,
                deemed_kwh_per_hour=800,
            ),
            make_control_room_headers(),
        )
    )
    assert order["state"] == CURTAILMENT_PENDING
    assert order["compensable"] is False

    activated = validate_success(
        api.activate_curtailment_order(order["id"], make_control_room_headers())
    )
    assert activated["state"] == CURTAILMENT_ACTIVE

    curtailed = read_turbine(api, turbine["id"])
    assert_turbine_dimensions(curtailed, AVAILABILITY_ONLINE, CURTAILMENT_CURTAILED)
    assert curtailed["active_curtailment_count"] == 1, curtailed["active_curtailment_count"]
    assert curtailed["effective_power_limit_kw"] == 1200, curtailed["effective_power_limit_kw"]

    released = validate_success(
        api.release_curtailment_order(
            order["id"], "2026-08-01T04:00:00Z", make_control_room_headers()
        )
    )
    assert released["state"] == CURTAILMENT_RELEASED
    assert_two_dp(released["curtailed_hours"], 4, "curtailed_hours")
    assert_two_dp(released["lost_energy_kwh"], 3200.00, "lost_energy_kwh")

    restored = read_turbine(api, turbine["id"])
    assert_turbine_dimensions(restored, AVAILABILITY_ONLINE, CURTAILMENT_UNCONSTRAINED)
    assert restored["active_curtailment_count"] == 0, restored["active_curtailment_count"]
    assert restored["effective_power_limit_kw"] == 4200, restored["effective_power_limit_kw"]
    assert_two_dp(
        restored["counted_downtime_hours_period"], 4, "counted_downtime_hours_period"
    )
