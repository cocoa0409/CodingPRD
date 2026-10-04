"""Station par adjustment protocol: apply-on-approve, segregation of duties,
and the OCC guard on proposals."""

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    set_clock, create_restaurant, create_manager, create_cook,
    create_prep_item, create_station, create_station_par,
    make_kitchen_manager_headers, make_line_cook_headers,
)


def _par_env(api):
    """Restaurant + manager + line cook + SAUTE station + ACTIVE par 20."""
    set_clock("2026-09-01T00:00:00Z")
    rest = create_restaurant()
    mgr = create_manager(rest["id"], certified_station_types=["SAUTE"])
    line = create_cook(rest["id"], mgr["id"], name="Leo Line",
                       certified_station_types=["SAUTE"])
    item = create_prep_item(name="P", station_type="SAUTE")
    station = create_station(rest["id"], mgr["id"], name="Saute 1",
                             station_type="SAUTE", rack_slot_capacity=100)
    par = create_station_par(station["id"], item["id"], mgr["id"],
                             par_quantity=20)
    return {
        "rest": rest, "mgr": mgr,
        "mh": make_kitchen_manager_headers(mgr["id"]),
        "line": line, "lch": make_line_cook_headers(line["id"]),
        "item": item, "station": station, "par": par,
    }


class TestApproveAppliesProposedQuantity:
    def test_approve_applies_and_records_identities(self, api):
        """PRD section 3.5: "A successful approval copies
        `proposed_par_quantity` into `par_quantity`, clears
        `proposed_par_quantity` back to null, records the approver's identity
        in `approved_by_cook_id`, and moves the adjustment to `APPROVED`."

        Design: Corner/state_machines/par_adjustment_approve_applies_proposed_quantity
        """
        env = _par_env(api)
        par, mh, lch = env["par"], env["mh"], env["lch"]
        proposed = validate_success(api.propose_adjustment(
            par["id"],
            {"proposed_par_quantity": 35,
             "expected_station_par_version": par["version"]}, lch))
        assert proposed["adjustment_status"] == "PENDING"
        assert proposed["requested_by_cook_id"] == env["line"]["id"]
        approved = validate_success(api.approve_adjustment(par["id"], mh))
        assert approved["adjustment_status"] == "APPROVED"
        assert approved["par_quantity"] == 35
        assert approved["proposed_par_quantity"] is None
        assert approved["approved_by_cook_id"] == env["mgr"]["id"]
        assert approved["requested_by_cook_id"] == env["line"]["id"]

    def test_reject_clears_proposal_and_keeps_par(self, api):
        """PRD section 3.5: "Rejecting a pending adjustment — which likewise
        requires the `PENDING` state, failing with
        `ERR_PAR_ADJUSTMENT_NOT_PENDING` otherwise — simply clears
        `proposed_par_quantity` to null and moves the adjustment to
        `REJECTED`, leaving the effective `par_quantity` untouched."

        Design: Corner/state_machines/par_adjustment_approve_applies_proposed_quantity
        """
        env = _par_env(api)
        par, mh, lch = env["par"], env["mh"], env["lch"]
        validate_success(api.propose_adjustment(
            par["id"],
            {"proposed_par_quantity": 35,
             "expected_station_par_version": par["version"]}, lch))
        rejected = validate_success(api.reject_adjustment(par["id"], mh))
        assert rejected["adjustment_status"] == "REJECTED"
        assert rejected["proposed_par_quantity"] is None
        assert rejected["par_quantity"] == 20


class TestSegregationOfDuties:
    def test_self_approval_blocked_second_manager_approves(self, api):
        """PRD section 2.10: "A station par adjustment may be proposed by the
        cooks who work the station, but only a `KitchenManager` may approve
        or reject it, and the approving manager must not be the same cook who
        proposed it: if the approver's `X-User-ID` equals the par's
        `requested_by_cook_id`, the approval is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_of_duties_blocks_self_approval
        """
        set_clock("2026-09-01T00:00:00Z")
        rest = create_restaurant()
        mgr1 = create_manager(rest["id"], name="Kara Manager",
                              certified_station_types=["SAUTE"])
        mgr1h = make_kitchen_manager_headers(mgr1["id"])
        mgr2 = create_cook(rest["id"], mgr1["id"], name="Marcus Manager",
                           certified_station_types=["SAUTE"])
        mgr2h = make_kitchen_manager_headers(mgr2["id"])
        item = create_prep_item(name="P", station_type="SAUTE")
        station = create_station(rest["id"], mgr1["id"], name="Saute 1",
                                 station_type="SAUTE", rack_slot_capacity=100)
        par = create_station_par(station["id"], item["id"], mgr1["id"],
                                 par_quantity=20)
        validate_success(api.propose_adjustment(
            par["id"],
            {"proposed_par_quantity": 35,
             "expected_station_par_version": par["version"]}, mgr1h))
        resp = api.approve_adjustment(par["id"], mgr1h)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        pending = validate_success(api.get_station_par(par["id"], mgr1h))
        assert pending["adjustment_status"] == "PENDING"
        approved = validate_success(api.approve_adjustment(par["id"], mgr2h))
        assert approved["adjustment_status"] == "APPROVED"
        assert approved["par_quantity"] == 35
        assert approved["approved_by_cook_id"] == mgr2["id"]


class TestProposeOcc:
    def test_stale_version_proposal_rejected(self, api):
        """PRD section 2.8: "Proposing a station par adjustment likewise
        requires `expected_station_par_version` matching the par's current
        `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP
        412), protecting the baseline `par_quantity` the client proposed
        against."

        Design: Corner/cross_cutting_complexity_layers/occ_station_par_propose_stale_version
        """
        env = _par_env(api)
        par, mh, lch = env["par"], env["mh"], env["lch"]
        v0 = par["version"]
        validate_success(api.propose_adjustment(
            par["id"],
            {"proposed_par_quantity": 30,
             "expected_station_par_version": v0}, lch))
        validate_success(api.reject_adjustment(par["id"], mh))
        resp = api.propose_adjustment(
            par["id"],
            {"proposed_par_quantity": 35,
             "expected_station_par_version": v0}, lch)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        now = validate_success(api.get_station_par(par["id"], mh))
        assert now["adjustment_status"] == "REJECTED"
        assert now["proposed_par_quantity"] is None

    def test_current_version_proposal_succeeds(self, api):
        """PRD section 3.5: "On acceptance, the par's
        `proposed_par_quantity` is set from the request,
        `requested_by_cook_id` is taken from the proposer's `X-User-ID`
        header — never from the request body — the `adjustment_status` moves
        to `PENDING`, and the par's `version` advances by one."

        Design: Corner/cross_cutting_complexity_layers/occ_station_par_propose_stale_version
        """
        env = _par_env(api)
        par, lch = env["par"], env["lch"]
        proposed = validate_success(api.propose_adjustment(
            par["id"],
            {"proposed_par_quantity": 30,
             "expected_station_par_version": par["version"]}, lch))
        assert proposed["adjustment_status"] == "PENDING"
        assert proposed["proposed_par_quantity"] == 30
        assert proposed["requested_by_cook_id"] == env["line"]["id"]
        assert proposed["version"] == par["version"] + 1
