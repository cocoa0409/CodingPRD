"""Harvest lots: creation defaults, temporal gates, cold-chain evaluation,
receive-response immediacy, list filters, and the planting auto-transition."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_harvest_lot_payload, receive_lot_payload, grade_payload,
    CLOCK_PLANT,
    set_clock, get_planting, get_harvest_lot, create_lot_in_transit,
    receive_lot, submit_grade, certify_lot, complete_planting,
    setup_planting_confirmed, setup_lot_in_transit, setup_lot_certified,
    make_grower_principal_headers, make_quality_grader_headers,
    make_cooling_operator_headers, get_success_data,
    COOLING_OP_1, GRADER_SUBMITTER, GRADER_CERTIFIER,
)

ADMIN = TEST_USERS["platform_admin_headers"]
GRADER = TEST_USERS["quality_grader_headers"]


def test_harvest_lot_tare_defaults_to_zero_and_net_computed(api):
    """PRD section 3.6: "optionally the packaging `tare_weight_kg` — which
    defaults to 0, may never be negative, and must always be strictly less than
    `gross_weight_kg`".
    PRD section 3.6: "A new harvest lot is created with `lot_status`
    `IN_TRANSIT` and `grade_status` `UNGRADED` — two parallel dimensions that
    thereafter evolve independently — and its `net_kg` is computed as
    `gross_weight_kg` minus `tare_weight_kg`."

    Design: Corner/entities/harvest_lot_tare_defaults_to_zero_and_net_computed
    """
    bundle = setup_planting_confirmed()
    set_clock("2026-10-06T06:30:00Z")
    current = get_planting(bundle["planting"]["id"])
    payload = create_harvest_lot_payload(bundle["planting"]["id"],
                                         current["version"],
                                         gross_weight_kg=1200)
    payload.pop("tare_weight_kg", None)  # omitted entirely → server default
    data = validate_success(api.create_harvest_lot(
        payload, make_grower_principal_headers(bundle["grower"]["id"])), 201)
    assert data["tare_weight_kg"] == 0
    assert data["net_kg"] == 1200
    assert data["lot_status"] == "IN_TRANSIT"
    assert data["grade_status"] == "UNGRADED"
    assert data["grade_version"] == 0
    assert data["grade"] is None
    assert data["pack_designation"] is None
    assert get_planting(bundle["planting"]["id"])["status"] == "HARVESTING"


def test_harvest_before_planting_rejected(api):
    """PRD section 3.6: "The fruit cannot predate the planting: a
    `harvested_at` earlier than the planting's `planted_on` is rejected with
    `ERR_HARVEST_BEFORE_PLANTING`".

    Design: Corner/validations/harvest_before_planting_rejected
    """
    bundle = setup_planting_confirmed()  # planted_on 2026-08-01
    current = get_planting(bundle["planting"]["id"])
    resp = api.create_harvest_lot(
        create_harvest_lot_payload(bundle["planting"]["id"], current["version"],
                                   harvested_at="2026-07-15T06:00:00Z",
                                   gross_weight_kg=100),
        make_grower_principal_headers(bundle["grower"]["id"]))
    validate_error(resp, ApiErrorId.ERR_HARVEST_BEFORE_PLANTING)
    rows, meta = validate_paginated(api.list_harvest_lots(
        ADMIN, params={"planting_id": bundle["planting"]["id"]}))
    assert rows == [] and meta["total_count"] == 0


def test_harvest_lot_hard_reject_above_10c_but_not_at_10c(api):
    """PRD section 3.6: "If `pulp_temp_c_at_receipt` exceeds 10.0 °C, the lot is
    hard-rejected: its `lot_status` becomes `REJECTED` instead of `RECEIVED`,
    its `grade_status` remains `UNGRADED` and locks there, and no grading is
    ever possible for the lot."
    PRD section 3.6: "`cold_chain_compliant` is set to true only when the
    rounded `precool_hours` is at most 8.0 hours and `pulp_temp_c_at_receipt`
    is at most 4.0 °C."

    Design: Corner/state_machines/harvest_lot_hard_reject_above_10c_but_not_at_10c
    """
    bundle = setup_planting_confirmed()
    set_clock("2026-10-06T06:30:00Z")
    hx = create_lot_in_transit(bundle["planting"], bundle["grower"],
                               gross_weight_kg=200, tare_weight_kg=10)
    hy = create_lot_in_transit(bundle["planting"], bundle["grower"],
                               gross_weight_kg=200, tare_weight_kg=10)
    set_clock("2026-10-06T12:30:00Z")
    hot = receive_lot(hx["id"], pulp_temp_c_at_receipt=10.5)
    assert hot["lot_status"] == "REJECTED"
    assert hot["grade_status"] == "UNGRADED"
    resp = api.grade_harvest_lot(hx["id"], grade_payload(),
                                 make_quality_grader_headers(GRADER_SUBMITTER))
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_RECEIVED)
    edge = receive_lot(hy["id"], pulp_temp_c_at_receipt=10.0)
    assert edge["lot_status"] == "RECEIVED", "10.0 does not exceed 10.0"
    assert edge["cold_chain_compliant"] is False, "10.0 > 4.0 breaches"


def test_precool_exactly_8h_compliant(api):
    """PRD section 3.6: "`cold_chain_compliant` is set to true only when the
    rounded `precool_hours` is at most 8.0 hours and `pulp_temp_c_at_receipt`
    is at most 4.0 °C."

    Design: Difficulty/boundary_precision_check/precool_boundary_exactly_8h
    """
    bundle = setup_planting_confirmed()
    set_clock("2026-10-06T04:30:00Z")
    lot = create_lot_in_transit(bundle["planting"], bundle["grower"],
                                harvested_at="2026-10-06T04:00:00Z",
                                gross_weight_kg=1100, tare_weight_kg=100)
    set_clock("2026-10-06T12:30:00Z")
    received = receive_lot(lot["id"], received_at="2026-10-06T12:00:00Z",
                           pulp_temp_c_at_receipt=3.0)
    assert received["precool_hours"] == pytest.approx(8.0, abs=5e-3)
    assert received["cold_chain_compliant"] is True, "the 8.0h bound is inclusive"


def test_precool_8h01m_breaches(api):
    """PRD section 3.6: "computes `precool_hours` as the elapsed time from
    `harvested_at` to `received_at` — the difference in seconds divided by
    3600, rounded half-up to 2 decimal places — and evaluates the cold chain
    on that rounded value."

    Design: Difficulty/boundary_precision_check/precool_boundary_exactly_8h
    """
    bundle = setup_planting_confirmed()
    set_clock("2026-10-06T04:30:00Z")
    lot = create_lot_in_transit(bundle["planting"], bundle["grower"],
                                harvested_at="2026-10-06T04:00:00Z",
                                gross_weight_kg=1100, tare_weight_kg=100)
    set_clock("2026-10-06T12:30:00Z")
    received = receive_lot(lot["id"], received_at="2026-10-06T12:01:00Z",
                           pulp_temp_c_at_receipt=3.0)
    assert received["precool_hours"] == pytest.approx(8.02, abs=5e-3)
    assert received["cold_chain_compliant"] is False


def test_receive_response_carries_computed_fields_immediately(api):
    """PRD section 2.9: "Consistency is immediate: when a single request
    triggers a cascade — a grower exit, a recall enforcement, a pool settlement
    — every effect of that cascade is committed within the same request and
    visible in the same response".
    PRD section 3.6: "Receipt records `received_by_user_id` from the operator's
    `X-User-ID`, computes `precool_hours` as the elapsed time from
    `harvested_at` to `received_at` — the difference in seconds divided by
    3600, rounded half-up to 2 decimal places — and evaluates the cold chain
    on that rounded value."

    Design: Corner/consistency/receive_response_carries_computed_fields_immediately
    """
    bundle = setup_lot_in_transit()  # harvested 06:00, clock now 06:30
    set_clock("2026-10-06T12:30:00Z")
    data = receive_lot(bundle["harvest_lot"]["id"], operator_id=COOLING_OP_1,
                       received_at="2026-10-06T12:00:00Z",
                       pulp_temp_c_at_receipt=3.5)
    assert data["lot_status"] == "RECEIVED"
    assert data["precool_hours"] == pytest.approx(6.0, abs=5e-3)
    assert data["cold_chain_compliant"] is True
    assert data["net_kg"] == 1150
    assert data["received_at"].startswith("2026-10-06T12:00:00")
    assert data["received_by_user_id"] == "co-1"
    assert data["updated_at"].startswith("2026-10-06T12:30:00")
    assert data["version"] == 2


def test_harvest_lots_list_filters_combine(api):
    """PRD section 3.6: "Harvest lots can be listed with filters on
    `planting_id`, `pool_period_id`, `grade`, `lot_status`, or `grade_status`,
    and retrieved individually."

    Design: Corner/endpoints/harvest_lots_list_filters_combine
    """
    bundle = setup_lot_certified()  # H1 GRADED / CERTIFIED / PREMIUM
    set_clock("2026-10-11T18:30:00Z")
    hy = create_lot_in_transit(bundle["planting"], bundle["grower"],
                               harvested_at="2026-10-11T18:00:00Z",
                               gross_weight_kg=900, tare_weight_kg=100)
    set_clock("2026-10-12T00:00:00Z")
    hy = receive_lot(hy["id"], received_at="2026-10-12T00:00:00Z",
                     pulp_temp_c_at_receipt=3.0)
    hy = submit_grade(hy["id"], flavor_brix=9.5, firmness_g=320,
                      appearance_score=75, defect_pct=4.0)  # SUBMITTED STANDARD
    pid = bundle["planting"]["id"]
    rows, meta = validate_paginated(api.list_harvest_lots(
        GRADER, params={"planting_id": pid}))
    assert len(rows) == 2 and meta["total_count"] == 2
    rows, _ = validate_paginated(api.list_harvest_lots(
        GRADER, params={"grade": "PREMIUM"}))
    assert len(rows) == 1 and rows[0]["id"] == bundle["harvest_lot"]["id"]
    rows, _ = validate_paginated(api.list_harvest_lots(
        GRADER, params={"grade_status": "SUBMITTED"}))
    assert len(rows) == 1 and rows[0]["id"] == hy["id"]
    rows, meta = validate_paginated(api.list_harvest_lots(
        GRADER, params={"lot_status": "IN_TRANSIT"}))
    assert rows == [] and meta["total_count"] == 0


def test_planting_harvesting_auto_and_complete_gate(api):
    """PRD section 3.6: "Every harvest-lot recording increments the planting's
    `version` by 1, and the first lot recorded against a planting additionally
    flips that planting `PLANTED → HARVESTING`."
    PRD section 3.5: "completion by the owning `GrowerPrincipal` —
    `ERR_NOT_OWN_RESOURCE` otherwise — moves it `HARVESTING → COMPLETED`, but
    only when every harvest lot of the planting has reached a resolved
    `lot_status` of `GRADED`, `SETTLED`, or `REJECTED`; any lot still in
    flight rejects the completion with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/planting_harvesting_auto_and_complete_gate
    """
    bundle = setup_lot_in_transit()  # H1 IN_TRANSIT; planting auto-flipped
    planting = get_planting(bundle["planting"]["id"])
    assert planting["status"] == "HARVESTING"
    grower_headers = make_grower_principal_headers(bundle["grower"]["id"])
    resp = api.complete_planting(bundle["planting"]["id"], grower_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    set_clock("2026-10-06T12:30:00Z")
    receive_lot(bundle["harvest_lot"]["id"])
    submit_grade(bundle["harvest_lot"]["id"])
    certify_lot(bundle["harvest_lot"]["id"])
    done = complete_planting(get_planting(bundle["planting"]["id"]),
                             bundle["grower"])
    assert done["status"] == "COMPLETED"
    assert done["completed_at"] is not None
    lot = get_harvest_lot(bundle["harvest_lot"]["id"])
    assert lot["grade"] == "PREMIUM"
    assert lot["pack_designation"] == "PREMIUM"
    assert lot["lot_status"] == "GRADED"
