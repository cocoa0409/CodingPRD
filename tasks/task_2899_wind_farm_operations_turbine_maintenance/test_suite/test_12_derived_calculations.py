"""Derived figures: outage arithmetic, the rounding rule and the empty denominator."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_NO_TURBINES_IN_SERVICE
from test_helpers.assertions import (
    assert_cents,
    assert_four_dp,
    assert_instant_equals,
    assert_two_dp,
    assert_turbine_dimensions,
    assert_version_unchanged,
)
from test_helpers.constants import (
    AGREEMENT_ACTIVE,
    AVAILABILITY_DECOMMISSIONED,
    AVAILABILITY_ONLINE,
    CURTAILMENT_UNCONSTRAINED,
    DISPOSITION_REMOTE_RESET,
    RESET_OUTCOME_SUCCEEDED,
    TRIAGE_CLOSED,
)
from test_helpers.fixtures import (
    close_fault,
    raise_fault,
    read_agreement,
    read_farm,
    read_fault_event,
    read_turbine,
    remote_reset,
    set_clock,
    setup_exclusion_pair_site,
    setup_precision_fault_site,
    setup_retired_farm_with_agreement,
    triage,
)
from test_helpers.test_users import make_commercial_headers, make_engineer_headers


def test_outage_hours_run_to_the_clear_instant_and_the_exclusion_flag_splits_the_accumulators(api):
    """Two outages on one turbine: both add lost energy, only the counted one adds hours.

    Each event is closed a while after its reset, so the elapsed span the contract names
    can only be reproduced by measuring to the reset instant.

    PRD §3.2: "A `reset_outcome` of `SUCCEEDED` moves the event `RESET_PENDING → CLEARED`,
    stamps `cleared_at` with the current logical clock, clears the turbine's
    `active_fault_code` to null, and drives the availability dimension `FAULTED → ONLINE`."
    PRD §3.2: "Closure is a `ReliabilityEngineer` decision that admits the event's downtime
    into the availability accounts, moving it `CLEARED → CLOSED`."
    PRD §3.2: "At that moment `downtime_hours` is computed as the elapsed time from
    `raised_at` to `cleared_at` expressed in hours, and `lost_energy_kwh` is that figure
    multiplied by the turbine's `expected_kwh_per_hour`, rounded half up to two decimal
    places."
    PRD §3.2: "First, the turbine's `cumulative_lost_energy_kwh` rises by the event's
    `lost_energy_kwh` unconditionally, while its `counted_downtime_hours_period` rises by
    `downtime_hours` only when the event's `contractual_exclusion_pinned` is false — an
    excluded code adds nothing to counted downtime, though it still adds its lost energy."

    Design: Corner/calculations/fault_downtime_and_lost_energy_are_derived_from_the_clear_instant_and_filtered_by_the_exclusion_flag
    """
    site = setup_exclusion_pair_site(api)
    turbine_id = site["turbine"]["id"]

    counted = raise_fault(api, turbine_id, "F-3001", "2026-08-01T01:00:00Z")
    assert counted["contractual_exclusion_pinned"] is False
    set_clock(api, "2026-08-01T03:00:00Z")
    triage(api, counted["id"], DISPOSITION_REMOTE_RESET)
    cleared = remote_reset(api, counted["id"], RESET_OUTCOME_SUCCEEDED)
    assert_instant_equals(cleared["cleared_at"], "2026-08-01T03:00:00Z", "counted.cleared_at")
    after_reset = read_turbine(api, turbine_id)
    assert_turbine_dimensions(after_reset, AVAILABILITY_ONLINE)
    assert after_reset["active_fault_code"] is None

    set_clock(api, "2026-08-01T03:30:00Z")
    closed = close_fault(api, counted["id"])
    assert closed["triage_state"] == TRIAGE_CLOSED
    assert_instant_equals(closed["cleared_at"], "2026-08-01T03:00:00Z", "counted.cleared_at")
    assert_two_dp(closed["downtime_hours"], 2.0, "counted.downtime_hours")
    assert_two_dp(closed["lost_energy_kwh"], 4000.00, "counted.lost_energy_kwh")

    set_clock(api, "2026-08-01T04:00:00Z")
    excluded = raise_fault(api, turbine_id, "F-7002", "2026-08-01T04:00:00Z")
    assert excluded["contractual_exclusion_pinned"] is True
    set_clock(api, "2026-08-01T05:30:00Z")
    triage(api, excluded["id"], DISPOSITION_REMOTE_RESET)
    remote_reset(api, excluded["id"], RESET_OUTCOME_SUCCEEDED)
    set_clock(api, "2026-08-01T06:00:00Z")
    excluded_closed = close_fault(api, excluded["id"])
    assert excluded_closed["triage_state"] == TRIAGE_CLOSED
    assert_instant_equals(
        excluded_closed["cleared_at"], "2026-08-01T05:30:00Z", "excluded.cleared_at"
    )
    assert_two_dp(excluded_closed["downtime_hours"], 1.5, "excluded.downtime_hours")
    assert_two_dp(excluded_closed["lost_energy_kwh"], 3000.00, "excluded.lost_energy_kwh")

    turbine = read_turbine(api, turbine_id)
    assert_two_dp(turbine["cumulative_lost_energy_kwh"], 7000.00, "cumulative_lost_energy_kwh")
    assert_two_dp(turbine["counted_downtime_hours_period"], 2.0, "counted_downtime_hours_period")
    assert_turbine_dimensions(turbine, AVAILABILITY_ONLINE, CURTAILMENT_UNCONSTRAINED)
    assert turbine["active_fault_code"] is None

    assert read_fault_event(api, counted["id"])["triage_state"] == TRIAGE_CLOSED
    assert read_fault_event(api, excluded["id"])["triage_state"] == TRIAGE_CLOSED


def test_lost_energy_rounds_half_up_at_the_second_decimal_place(api):
    """A 45-second outage on a 1234 kWh/h turbine lands exactly on the half-cent tie.

    The product is 15.425 kWh, the one input on which rounding half up and rounding to
    even disagree, and the hour figure itself must survive un-rounded to produce it.

    PRD §3.2: "At that moment `downtime_hours` is computed as the elapsed time from
    `raised_at` to `cleared_at` expressed in hours, and `lost_energy_kwh` is that figure
    multiplied by the turbine's `expected_kwh_per_hour`, rounded half up to two decimal
    places."
    PRD §2.3: "Lost-energy and curtailed-energy amounts are rounded half up to two decimal
    places."
    PRD §3.2: "First, the turbine's `cumulative_lost_energy_kwh` rises by the event's
    `lost_energy_kwh` unconditionally, while its `counted_downtime_hours_period` rises by
    `downtime_hours` only when the event's `contractual_exclusion_pinned` is false — an
    excluded code adds nothing to counted downtime, though it still adds its lost energy."

    Design: Corner/calculations/lost_energy_rounds_half_up_at_the_second_decimal_place
    """
    site = setup_precision_fault_site(api)
    event_id = site["event"]["id"]

    set_clock(api, "2026-08-01T01:00:45Z")
    triage(api, event_id, DISPOSITION_REMOTE_RESET)
    reset = remote_reset(api, event_id, RESET_OUTCOME_SUCCEEDED)
    assert_instant_equals(reset["cleared_at"], "2026-08-01T01:00:45Z", "cleared_at")

    closed = validate_success(api.close_fault_event(event_id, make_engineer_headers()))
    assert closed["triage_state"] == TRIAGE_CLOSED
    assert_four_dp(closed["downtime_hours"], 0.0125, "downtime_hours")
    assert closed["lost_energy_kwh"] == 15.43, closed["lost_energy_kwh"]

    turbine = read_turbine(api, site["turbine"]["id"])
    assert turbine["cumulative_lost_energy_kwh"] == 15.43, (
        turbine["cumulative_lost_energy_kwh"]
    )
    assert_four_dp(
        turbine["counted_downtime_hours_period"], 0.0125, "counted_downtime_hours_period"
    )


def test_settling_a_farm_with_no_turbine_in_service_is_refused_before_any_division(api):
    """The availability denominator is empty, so the settle run is refused, not approximated.

    PRD §3.9: "Settling the period drives the agreement `ACTIVE → IN_SETTLEMENT`, and it is
    permitted only once the logical clock has reached or passed `period_end_utc` and only
    while the farm has at least one turbine whose `availability_state` is not
    `DECOMMISSIONED`."
    PRD §3.9: "A farm with no turbine in service would produce a zero denominator, and the
    request is refused with `ERR_NO_TURBINES_IN_SERVICE` before any division is attempted."
    PRD §3.9: "A new agreement is created in `state` `ACTIVE` with `at_risk_flag` false and
    with `projected_shortfall_pct`, `time_based_availability_pct`,
    `energy_based_availability_pct` and `assessed_lda_cents` all at 0."
    PRD §3.1: "It then decrements the farm's `turbine_count` by 1 and subtracts the model's
    `rated_power_kw` from the farm's `installed_capacity_kw`, and from that moment the
    turbine is excluded from every availability denominator and from every landowner
    metered-energy sum."
    PRD §2.12: "A rejected request writes nothing at all — no counter moves, no `version`
    advances, no partial cascade survives."

    Design: Corner/calculations/settlement_run_is_rejected_when_every_turbine_on_the_farm_is_decommissioned
    """
    site = setup_retired_farm_with_agreement(api)
    agreement_id = site["agreement"]["id"]
    before = read_agreement(api, agreement_id)

    validate_error(
        api.settle_agreement(agreement_id, make_commercial_headers()),
        ERR_NO_TURBINES_IN_SERVICE,
        expected_status=422,
    )

    after = read_agreement(api, agreement_id)
    assert after["state"] == AGREEMENT_ACTIVE
    assert after["at_risk_flag"] is False
    assert_four_dp(after["time_based_availability_pct"], 0, "time_based_availability_pct")
    assert_four_dp(after["energy_based_availability_pct"], 0, "energy_based_availability_pct")
    assert_two_dp(after["projected_shortfall_pct"], 0, "projected_shortfall_pct")
    assert_cents(after["assessed_lda_cents"], 0, "assessed_lda_cents")
    assert_version_unchanged(before, after)

    farm = read_farm(api, site["farm"]["id"])
    assert farm["turbine_count"] == 0
    assert farm["installed_capacity_kw"] == 0

    turbine = read_turbine(api, site["turbine"]["id"])
    assert_turbine_dimensions(turbine, AVAILABILITY_DECOMMISSIONED)
