"""Requests whose legality is decided by the state of a row they barely mention."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import (
    assert_cents,
    assert_four_dp,
    assert_stock_line,
    assert_two_dp,
    assert_version_unchanged,
)
from test_helpers.constants import (
    AGREEMENT_IN_SETTLEMENT,
    AGREEMENT_SETTLED,
    AVAILABILITY_DOWN_MAJOR,
    AVAILABILITY_FAULTED,
    AVAILABILITY_ONLINE,
    CREW_ON_SHIFT,
    CURTAILMENT_UNCONSTRAINED,
    REPLACEMENT_PLANNED,
    SETTLEMENT_DRAFT,
    STOCK_IN_STOCK,
    STOCK_OUT_OF_STOCK,
    TRIAGE_CLEARED,
    TRIAGE_RESET_PENDING,
    WO_IN_PROGRESS,
    WO_SCHEDULED,
)
from test_helpers.factories import (
    landowner_settlement_payload,
    replacement_payload,
    scada_payload,
)
from test_helpers.fixtures import (
    read_crew,
    read_farm,
    read_fault_event,
    read_spare_part,
    read_turbine,
    read_work_order,
    setup_force_stopped_reset_candidate,
    setup_force_stopped_scheduled_order,
    setup_settlement_freeze_farm,
    setup_stock_gated_replacement,
)
from test_helpers.test_users import (
    make_commercial_headers,
    make_control_room_headers,
    make_crew_lead_headers,
    make_planner_headers,
    make_site_admin_headers,
)


def _gearbox_replacement(api, site, part_key="sp_gb"):
    """The one unchanging replacement payload, posted as a planner."""
    return api.create_component_replacement(
        replacement_payload(
            site["order"]["id"],
            site[part_key]["id"],
            component_type="GEARBOX",
            estimated_lift_hours=12,
            uptower_labor_hours=40,
        ),
        make_planner_headers(),
    )


def test_one_unchanged_payload_is_accepted_refused_then_accepted_again(api):
    """Only the referenced stock line moves, and it decides the request every time.

    The contract states: "The named part's `component_type` must equal the
    replacement's `component_type`, failing which the request is refused with
    `ERR_SPARE_PART_TYPE_MISMATCH`, and the part must have at least one unit of
    `quantity_on_hand` available, failing which it is refused with
    `ERR_SPARE_PART_UNAVAILABLE`."  It continues: "Planning creates the replacement
    in `state` `PLANNED` with `execution_path` null, `crane_mobilization_id` null and
    `allocated_crane_cost_cents` at 0, and moves exactly one unit from the part's
    `quantity_on_hand` into its `quantity_reserved` — leaving `total_units_accounted`
    unchanged — then re-derives the part's `status` and `procurement_flag` from the
    reduced on-hand balance."  Of a receipt it states: "A goods receipt, also a
    `SiteAdmin` action, adds a `quantity_received` to `quantity_on_hand` and to
    `total_units_accounted`, and re-derives `status` and `procurement_flag` from the
    new balance — this is the only event in the system that raises the conserved
    total."

    Design: Difficulty/cross_entity_state_dependency/replacement_creation_legality_is_decided_by_the_spare_parts_stock_state
    """
    site = setup_stock_gated_replacement(api)

    first = validate_success(_gearbox_replacement(api, site), 201)
    assert first["state"] == REPLACEMENT_PLANNED
    assert first["execution_path"] is None
    assert first["crane_mobilization_id"] is None
    assert_cents(first["allocated_crane_cost_cents"], 0, "replacement.allocated_crane_cost_cents")
    assert_stock_line(
        read_spare_part(api, site["sp_gb"]["id"]),
        0,
        1,
        0,
        1,
        status=STOCK_OUT_OF_STOCK,
        procurement_flag=True,
    )

    second = _gearbox_replacement(api, site)
    validate_error(second, "ERR_SPARE_PART_UNAVAILABLE", 422)

    validate_success(
        api.receive_spare_part(site["sp_gb"]["id"], 1, make_site_admin_headers())
    )
    assert_stock_line(
        read_spare_part(api, site["sp_gb"]["id"]),
        1,
        1,
        0,
        2,
        status=STOCK_IN_STOCK,
        procurement_flag=False,
    )

    third = validate_success(_gearbox_replacement(api, site), 201)
    assert third["state"] == REPLACEMENT_PLANNED
    assert_stock_line(
        read_spare_part(api, site["sp_gb"]["id"]),
        0,
        2,
        0,
        2,
        status=STOCK_OUT_OF_STOCK,
        procurement_flag=True,
    )


def test_the_type_mismatch_outranks_the_empty_stock_line_on_the_same_part(api):
    """A payload that breaks both gates on one part reports the referential one.

    The contract states: "When a single request violates more than one rule, the
    response must carry the error belonging to the earliest rung of the ladder
    below."  Rung 17 reads: "**Referential consistency.** In order: crew-to-farm
    match (`ERR_CREW_FARM_MISMATCH`, on scheduling), crane-to-farm match
    (`ERR_CRANE_FARM_MISMATCH`, on crane reservation), spare-part component-type
    match (`ERR_SPARE_PART_TYPE_MISMATCH`, on replacement planning), and up-tower
    eligibility (`ERR_UPTOWER_NOT_PERMITTED`, on taking the up-tower branch)."  Rung
    18 places spare-part availability later: "**Quota, capacity and fiscal gates.**
    In order: reset eligibility (`ERR_RESET_NOT_PERMITTED`, which applies both to a
    triage disposition of `REMOTE_RESET` and to a remote-reset attempt), reset quota
    (`ERR_RESET_QUOTA_EXHAUSTED`, on a remote-reset attempt), crew daily capacity
    (`ERR_CREW_CAPACITY_EXCEEDED`, on scheduling), spare-part availability
    (`ERR_SPARE_PART_UNAVAILABLE`, on replacement planning), landowner budget
    headroom (`ERR_MINIMUM_PAYMENT_ABOVE_CAP`, on settlement drafting), service-due
    eligibility (`ERR_SERVICE_NOT_DUE`, on raising a scheduled-service work order),
    the revision bound (`ERR_REVISION_LIMIT_EXCEEDED`, on requesting a revision), and
    finally the non-empty availability denominator (`ERR_NO_TURBINES_IN_SERVICE`, on
    settling a service agreement)."

    Design: Difficulty/cross_entity_state_dependency/replacement_creation_legality_is_decided_by_the_spare_parts_stock_state
    """
    site = setup_stock_gated_replacement(api)

    both_broken = _gearbox_replacement(api, site, part_key="sp_bl")
    validate_error(both_broken, "ERR_SPARE_PART_TYPE_MISMATCH", 422)

    assert_stock_line(read_spare_part(api, site["sp_bl"]["id"]), 0, 0, 0, 0)
    assert_stock_line(
        read_spare_part(api, site["sp_gb"]["id"]), 1, 0, 0, 1, status=STOCK_IN_STOCK
    )
    assert_version_unchanged(site["sp_bl"], read_spare_part(api, site["sp_bl"]["id"]))


def test_a_force_stopped_turbine_refuses_a_remote_reset_until_the_order_is_released(api):
    """The reset gate reads the curtailment dimension, not the availability dimension.

    The contract states: "Only then is eligibility tested, and it requires three
    things simultaneously: the event's `severity_class_pinned` is `RESETTABLE`, its
    `reset_attempt_count` is **strictly** below its `max_remote_resets_pinned`, and
    the turbine's `curtailment_state` is not `FORCED_STOP`."  It continues: "A count
    exactly equal to the pinned maximum is not eligible and is refused with
    `ERR_RESET_QUOTA_EXHAUSTED`; an ineligible severity class or a dispatch-only code
    is refused with `ERR_RESET_NOT_PERMITTED`; and a force-stopped turbine is refused
    with `ERR_TURBINE_FORCE_STOPPED`, because a turbine held down for icing or
    wildlife protection must not be spun back up from a desk."  Of a release it
    states: "The curtailment dimension is likewise re-derived: `UNCONSTRAINED` when
    no active order remains, which covers both `FORCED_STOP → UNCONSTRAINED` and
    `CURTAILED → UNCONSTRAINED`; `FORCED_STOP` when any remaining active order still
    caps power at 0; and `CURTAILED` otherwise."  It also states: "A rejected request
    writes nothing at all — no counter moves, no `version` advances, no partial
    cascade survives."

    Design: Difficulty/cross_entity_state_dependency/forced_stop_on_the_curtailment_dimension_blocks_reset_and_start_on_the_availability_dimension
    """
    site = setup_force_stopped_reset_candidate(api)
    event_id = site["fault_event"]["id"]

    refused = api.remote_reset(event_id, "SUCCEEDED", make_control_room_headers())
    validate_error(refused, "ERR_TURBINE_FORCE_STOPPED", 409)

    held = read_fault_event(api, event_id)
    assert held["triage_state"] == TRIAGE_RESET_PENDING
    assert held["reset_attempt_count"] == 0

    validate_success(
        api.release_curtailment_order(
            site["co1"]["id"], "2026-06-01T06:00:00Z", make_control_room_headers()
        )
    )
    released = read_turbine(api, site["t1"]["id"])
    assert released["curtailment_state"] == CURTAILMENT_UNCONSTRAINED
    assert released["active_curtailment_count"] == 0
    assert released["availability_state"] == AVAILABILITY_FAULTED

    accepted = validate_success(
        api.remote_reset(event_id, "SUCCEEDED", make_control_room_headers())
    )
    assert accepted["triage_state"] == TRIAGE_CLEARED
    assert read_turbine(api, site["t1"]["id"])["availability_state"] == AVAILABILITY_ONLINE


def test_a_force_stopped_turbine_refuses_a_start_even_while_it_reads_online(api):
    """The start interlock survives an ONLINE availability dimension.

    The contract states: "A turbine whose `curtailment_state` is `FORCED_STOP`
    cannot have work started on it at all, and the attempt is refused with
    `ERR_TURBINE_FORCE_STOPPED`."  It also states: "A rejected request writes nothing
    at all — no counter moves, no `version` advances, no partial cascade survives."
    Of an accepted start it states: "The start writes the availability dimension
    according to work type, and each branch is a distinct declared transition: a
    `FAULT_DISPATCH` order drives `FAULTED → DOWN_DISPATCH`, a `SCHEDULED_SERVICE` or
    `BLADE_REPAIR` order drives `ONLINE → DOWN_SERVICE`, and a `MAJOR_COMPONENT`
    order drives `ONLINE → DOWN_MAJOR`."  It adds: "In every branch the curtailment
    dimension is left exactly as it was."

    Design: Difficulty/cross_entity_state_dependency/forced_stop_on_the_curtailment_dimension_blocks_reset_and_start_on_the_availability_dimension
    """
    site = setup_force_stopped_scheduled_order(api)
    order_id = site["order"]["id"]
    crew_headers = make_crew_lead_headers(site["crew"]["id"])

    before_start = read_turbine(api, site["t1"]["id"])
    assert before_start["availability_state"] == AVAILABILITY_ONLINE

    refused = api.start_work_order(order_id, crew_headers)
    validate_error(refused, "ERR_TURBINE_FORCE_STOPPED", 409)

    held = read_work_order(api, order_id)
    assert held["state"] == WO_SCHEDULED
    assert read_crew(api, site["crew"]["id"])["status"] == CREW_ON_SHIFT

    validate_success(
        api.release_curtailment_order(
            site["co2"]["id"], "2026-06-20T05:00:00Z", make_control_room_headers()
        )
    )
    started = validate_success(api.start_work_order(order_id, crew_headers))
    assert started["state"] == WO_IN_PROGRESS

    working = read_turbine(api, site["t1"]["id"])
    assert working["availability_state"] == AVAILABILITY_DOWN_MAJOR
    assert working["curtailment_state"] == CURTAILMENT_UNCONSTRAINED


def test_settling_one_agreement_freezes_telemetry_and_drafting_across_the_whole_farm(api):
    """A turbine the agreement never mentions is frozen too, and nothing is written.

    The contract states: "Settlement also freezes the farm's telemetry: while any
    agreement on the farm sits in `IN_SETTLEMENT`, a telemetry post on any of the
    farm's turbines is refused with `ERR_AGREEMENT_IN_SETTLEMENT`, and so is drafting
    a new landowner settlement for that farm."  It also states: "A rejected request
    writes nothing at all — no counter moves, no `version` advances, no partial
    cascade survives."  Of the two figures it states: "`time_based_availability_pct`
    is then 100 multiplied by the quantity one minus counted downtime divided by that
    denominator, rounded half up to four decimal places."  And:
    "`energy_based_availability_pct` reads only telemetry: it is 100 multiplied by the
    sum of `period_actual_energy_kwh` across the turbine set divided by the sum of
    `period_potential_energy_kwh` across the same set, rounded half up to four decimal
    places — except that when the potential sum is exactly 0 the figure is `100.0000`
    by definition rather than a division."

    Design: Difficulty/cross_entity_state_dependency/agreement_settlement_state_freezes_and_unfreezes_telemetry_and_landowner_drafting
    """
    site = setup_settlement_freeze_farm(api)
    telemetry = scada_payload(720, 1000000, 1440000)

    validate_success(api.scada_sync(site["t1"]["id"], telemetry, make_control_room_headers()))
    assert_two_dp(
        read_turbine(api, site["t1"]["id"])["period_actual_energy_kwh"],
        1000000,
        "t1.period_actual_energy_kwh",
    )

    settled = validate_success(
        api.settle_agreement(site["agreement"]["id"], make_commercial_headers())
    )
    assert settled["state"] == AGREEMENT_IN_SETTLEMENT
    assert_four_dp(settled["time_based_availability_pct"], 100.0000, "time_based_availability_pct")
    assert_four_dp(
        settled["energy_based_availability_pct"], 69.4444, "energy_based_availability_pct"
    )

    frozen_telemetry = api.scada_sync(
        site["t2"]["id"], scada_payload(720, 1400000, 1440000), make_control_room_headers()
    )
    validate_error(frozen_telemetry, "ERR_AGREEMENT_IN_SETTLEMENT", 409)
    assert_two_dp(
        read_turbine(api, site["t2"]["id"])["period_actual_energy_kwh"],
        0,
        "t2.period_actual_energy_kwh",
    )

    before_draft = read_farm(api, site["farm"]["id"])
    frozen_draft = api.create_landowner_settlement(
        site["farm"]["id"],
        landowner_settlement_payload(
            site["farm_version"],
            parcel_code="P-9",
            royalty_basis="METERED_ONLY",
            period_start_utc="2026-06-01T00:00:00Z",
            period_end_utc="2026-07-01T00:00:00Z",
            royalty_pct=4.0,
            minimum_payment_cents=0,
            energy_price_cents_per_kwh=6,
            road_damage_assessment_cents=0,
        ),
        make_commercial_headers(),
    )
    validate_error(frozen_draft, "ERR_AGREEMENT_IN_SETTLEMENT", 409)
    assert_version_unchanged(before_draft, read_farm(api, site["farm"]["id"]))


def test_finalizing_thaws_both_endpoints_and_the_draft_then_sees_all_the_energy(api):
    """The thawed telemetry lands, and the royalty chain reads both turbines.

    The contract states: "Finalizing drives the agreement `IN_SETTLEMENT → SETTLED`,
    clears `at_risk_flag`, releases the telemetry freeze, and leaves
    `assessed_lda_cents`, `time_based_availability_pct` and
    `energy_based_availability_pct` frozen at their settled values."  Of the royalty
    chain it states: "`metered_kwh` is the sum of `period_actual_energy_kwh` across
    the farm's turbines whose `availability_state` is not `DECOMMISSIONED`."  And:
    "The royalty base in kilowatt-hours is `metered_kwh` plus `deemed_kwh`;
    `royalty_cents` is that base multiplied by `energy_price_cents_per_kwh`,
    multiplied by `royalty_pct`, divided by 100, and rounded half up to a whole cent —
    the energy figures keep full precision until this single rounding."  And:
    "`payment_cents` is the larger of `minimum_payment_cents` and `royalty_cents`."
    And: "`road_levy_cents` is `payment_cents` multiplied by the farm's `road_levy_pct`
    divided by 100, rounded half up to a whole cent, and `community_levy_cents` is
    `payment_cents` multiplied by the farm's `community_levy_pct` divided by 100,
    likewise rounded half up."

    Design: Difficulty/cross_entity_state_dependency/agreement_settlement_state_freezes_and_unfreezes_telemetry_and_landowner_drafting
    """
    site = setup_settlement_freeze_farm(api)
    validate_success(
        api.scada_sync(
            site["t1"]["id"], scada_payload(720, 1000000, 1440000), make_control_room_headers()
        )
    )
    validate_success(api.settle_agreement(site["agreement"]["id"], make_commercial_headers()))

    finalized = validate_success(
        api.finalize_agreement(site["agreement"]["id"], make_commercial_headers())
    )
    assert finalized["state"] == AGREEMENT_SETTLED
    assert finalized["at_risk_flag"] is False
    assert_four_dp(
        finalized["time_based_availability_pct"], 100.0000, "time_based_availability_pct"
    )
    assert_four_dp(
        finalized["energy_based_availability_pct"], 69.4444, "energy_based_availability_pct"
    )

    validate_success(
        api.scada_sync(
            site["t2"]["id"], scada_payload(720, 1400000, 1440000), make_control_room_headers()
        )
    )
    assert_two_dp(
        read_turbine(api, site["t2"]["id"])["period_actual_energy_kwh"],
        1400000,
        "t2.period_actual_energy_kwh",
    )

    drafted = validate_success(
        api.create_landowner_settlement(
            site["farm"]["id"],
            landowner_settlement_payload(
                read_farm(api, site["farm"]["id"])["version"],
                parcel_code="P-9",
                royalty_basis="METERED_ONLY",
                period_start_utc="2026-06-01T00:00:00Z",
                period_end_utc="2026-07-01T00:00:00Z",
                royalty_pct=4.0,
                minimum_payment_cents=0,
                energy_price_cents_per_kwh=6,
                road_damage_assessment_cents=0,
            ),
            make_commercial_headers(),
        ),
        201,
    )
    assert drafted["state"] == SETTLEMENT_DRAFT
    assert_two_dp(drafted["metered_kwh"], 2400000, "settlement.metered_kwh")
    assert_two_dp(drafted["deemed_kwh"], 0, "settlement.deemed_kwh")
    assert_cents(drafted["royalty_cents"], 576000, "settlement.royalty_cents")
    assert_cents(drafted["payment_cents"], 576000, "settlement.payment_cents")
    assert_cents(drafted["road_levy_cents"], 14400, "settlement.road_levy_cents")
    assert_cents(drafted["community_levy_cents"], 8640, "settlement.community_levy_cents")
