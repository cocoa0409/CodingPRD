"""Security (RBAC), validation, not-found, trade partners, and the posture cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    approve_contract,
    create_community,
    create_community_payload,
    create_incentive,
    create_partner_with_commitment,
    create_product_series_payload,
    create_series,
    create_trade_partner_payload,
    get_success_data,
    make_trade_partner_headers,
    open_community,
    setup_ready_community,
    start_home,
    validate_error,
)
from test_helpers import TEST_USERS

_CM = TEST_USERS["community_manager_headers"]
_DP = TEST_USERS["division_president_headers"]
_LM = TEST_USERS["land_manager_headers"]
_SA = TEST_USERS["sales_agent_headers"]


class TestValidation:
    def test_missing_required_field_returns_400(self, api, division_president_headers):
        """PRD §2.9: "A malformed payload — a missing required field, an invalid
        enum value, or a mistyped value — is rejected with `ERR_VALIDATION`
        (HTTP 400)."

        Design: Corner/validations/create_community_missing_required_field_returns_400
        """
        resp = api.create_community(
            {"name": "Community A", "market_code": "DFW", "months_supply_target": 3.0},
            division_president_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_invalid_trade_enum_rejected(self, api, division_president_headers):
        """PRD §2.9: "A malformed payload — a missing required field, an invalid
        enum value, or a mistyped value — is rejected with `ERR_VALIDATION`
        (HTTP 400)." and PRD §3.10: "A `DIVISION_PRESIDENT` registers a trade
        partner with its `name` and its `trade` — one of `FRAMING`, `PLUMBING`,
        `ELECTRICAL`, `HVAC`, or `MASONRY`."

        Design: Corner/entities/trade_partner_invalid_enum_rejected
        """
        resp = api.create_trade_partner({"name": "PaintCo", "trade": "PAINTING"},
                                        division_president_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestNotFound:
    def test_get_unknown_home_returns_404(self, api, community_manager_headers):
        """PRD §2.5: "Path resource identifiers are validated left to right: the
        server first confirms the leftmost id exists, then the next, and so on.
        The first id that does not exist produces `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_home_not_found_returns_404
        """
        resp = api.get_home(NON_EXISTENT_UUID, community_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestSeriesBands:
    def test_overlapping_band_rejected_touching_allowed(self, api, community_manager_headers):
        """PRD §3.5: "Bands may not overlap: a new series whose band intersects
        an existing series' band in the same community is rejected with
        `ERR_SERIES_BAND_OVERLAP` (HTTP 422)."

        Design: Corner/validations/series_band_overlap_rejected
        """
        community = create_community(api)
        create_series(api, community["id"])  # CLASSIC [30,000,000, 50,000,000]
        overlap = api.create_product_series(community["id"], create_product_series_payload(
            series_code="VENTURE", min_price_cents=45_000_000, max_price_cents=60_000_000), _CM)
        validate_error(overlap, ApiErrorId.ERR_SERIES_BAND_OVERLAP, 422)
        ok = api.create_product_series(community["id"], create_product_series_payload(
            series_code="VENTURE", min_price_cents=50_000_001, max_price_cents=60_000_000), _CM)
        assert ok.status_code == 201

    def test_home_gross_outside_series_band_rejected(self, api, community_manager_headers):
        """PRD §3.5: "The band is enforced again at home-start time: a home whose
        gross price falls outside its series' band is rejected with
        `ERR_PRICE_OUT_OF_SERIES_BAND` (HTTP 422)."

        Design: Corner/validations/home_price_out_of_series_band_rejected
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        from test_helpers import create_home_payload
        resp = api.create_home(env["community"]["id"], create_home_payload(
            lot_id=env["lot_ids"][0], product_series_id=env["series"]["id"],
            base_price_cents=51_000_000), community_manager_headers)
        validate_error(resp, ApiErrorId.ERR_PRICE_OUT_OF_SERIES_BAND, 422)


class TestRbac:
    def test_sales_agent_cannot_approve(self, api, sales_agent_headers,
                                        community_manager_headers):
        """PRD §3.9: "Approval belongs to the `COMMUNITY_MANAGER`" and PRD §2.1:
        "A request whose role is authenticated but not permitted to perform the
        operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/sales_agent_cannot_approve_forbidden
        """
        env = setup_ready_community(api, lot_count=5, max_starts=10, committed_units=10)
        home = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        sc = get_success_data(api.create_sales_contract(
            {"home_id": home["id"], "buyer_name": "Buyer A",
             "contract_price_cents": 40_000_000}, _SA))
        resp = api.approve_sales_contract(sc["id"], sales_agent_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        sc_after = get_success_data(api.get_sales_contract(sc["id"], community_manager_headers))
        assert sc_after["state"] == "PENDING"

    def test_trade_partner_cannot_reduce_others_commitment(self, api):
        """PRD §2.1: "A `TRADE_PARTNER` acting on another partner's resources —
        where the path's trade-partner id does not equal `X-User-ID`, or the
        targeted commitment belongs to a different partner — is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/trade_partner_cannot_reduce_others_commitment
        """
        community = create_community(api)
        partner_a = get_success_data(api.create_trade_partner(
            create_trade_partner_payload(name="FrameCoA"), _DP))
        cap_b = create_partner_with_commitment(api, community["id"], committed_units=10)
        resp = api.reduce_capacity_commitment(cap_b["commitment"]["id"],
                                              {"new_committed_units": 5},
                                              make_trade_partner_headers(partner_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_land_manager_cannot_create_community(self, api, land_manager_headers):
        """PRD §2.1: "`DIVISION_PRESIDENT` — division executive. Owns community
        creation, phase advancement, pacing plan publication, trade partner
        creation, and the logical clock." and "A request whose role is
        authenticated but not permitted to perform the operation is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/land_manager_cannot_create_community_forbidden
        """
        resp = api.create_community(create_community_payload(), land_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestTerminateCascade:
    def _setup_overheld_scenario(self, api):
        """Homes A,B,D standing; C SOLD via APPROVED contract; flagged incentive
        whose window starts tomorrow. Terminating C flips posture OVERHELD."""
        env = setup_ready_community(api, lot_count=10, max_starts=20, committed_units=20)
        inc = create_incentive(api, env["community"]["id"], value_cents=1_000_000,
                               window_start="2026-09-02T00:00:00Z",
                               window_end="2026-09-30T00:00:00Z",
                               auto_activate_on_overheld=True)
        h_a = start_home(api, env["community"]["id"], env["lot_ids"][0], env["series"]["id"])
        start_home(api, env["community"]["id"], env["lot_ids"][1], env["series"]["id"])
        h_c = start_home(api, env["community"]["id"], env["lot_ids"][2], env["series"]["id"])
        start_home(api, env["community"]["id"], env["lot_ids"][3], env["series"]["id"])
        sc = get_success_data(api.create_sales_contract(
            {"home_id": h_c["id"], "buyer_name": "Buyer C",
             "contract_price_cents": 40_000_000}, _SA))
        approve_contract(api, sc["id"])
        return env, inc, h_a, sc

    def test_terminate_flips_posture_to_overheld(self, api, community_manager_headers):
        """PRD §3.9: "1. The home returns to `UNSOLD` — from `RESERVED` when the
        terminated contract was `PENDING`, from `SOLD` when it was `APPROVED`.
        2. The community's `standing_spec_count` increases by 1 and its posture
        is recomputed. 3. If that recomputation flips the community's posture to
        `OVERHELD`, every incentive in the community flagged with
        `auto_activate_on_overheld` whose window has not passed becomes
        `ACTIVE`, and the applicable homes' stacks and net effective prices
        recompute."

        Design: Difficulty/transitive_cascade/terminate_cascade_home_to_posture_to_incentive
        """
        env, inc, h_a, sc = self._setup_overheld_scenario(api)
        get_success_data(api.terminate_sales_contract(sc["id"], _SA))
        community = get_success_data(api.get_community(env["community"]["id"],
                                                       community_manager_headers))
        assert community["standing_spec_count"] == 4
        assert community["months_of_supply"] == pytest.approx(4.0)
        assert community["posture"] == "OVERHELD"

    def test_overheld_flip_auto_activates_flagged_incentive(self, api, community_manager_headers):
        """PRD §3.9: "3. If that recomputation flips the community's posture to
        `OVERHELD`, every incentive in the community flagged with
        `auto_activate_on_overheld` whose window has not passed becomes
        `ACTIVE`, and the applicable homes' stacks and net effective prices
        recompute."

        Design: Difficulty/transitive_cascade/terminate_cascade_home_to_posture_to_incentive
        """
        env, inc, h_a, sc = self._setup_overheld_scenario(api)
        before = get_success_data(api.get_home(h_a["id"], community_manager_headers))
        assert before["net_effective_price_cents"] == 40_000_000
        get_success_data(api.terminate_sales_contract(sc["id"], _SA))
        listed = get_success_data(api.list_incentives(env["community"]["id"],
                                                      community_manager_headers))
        assert listed[0]["status"] == "ACTIVE"
        after = get_success_data(api.get_home(h_a["id"], community_manager_headers))
        assert after["net_effective_price_cents"] == 39_000_000


class TestTradePartnerRegistration:
    def test_register_partner_with_each_valid_trade(self, api, division_president_headers):
        """PRD §3.10: "A `DIVISION_PRESIDENT` registers a trade partner with its
        `name` and its `trade` — one of `FRAMING`, `PLUMBING`, `ELECTRICAL`,
        `HVAC`, or `MASONRY`."

        Design: Corner/entities/trade_partner_invalid_enum_rejected
        """
        for trade in ["FRAMING", "PLUMBING", "ELECTRICAL", "HVAC", "MASONRY"]:
            resp = api.create_trade_partner({"name": f"{trade}Co", "trade": trade},
                                            division_president_headers)
            assert resp.status_code == 201, f"trade {trade} should be accepted"
