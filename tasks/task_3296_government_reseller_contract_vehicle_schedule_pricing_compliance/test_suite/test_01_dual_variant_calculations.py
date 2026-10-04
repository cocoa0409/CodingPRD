"""Dual-variant calculations: TAA origin and MFC floor diverge by vehicle kind."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_price_list,
    create_active_agreement,
    create_authorized_vehicle,
    create_cleared_order,
    create_manufacturer,
    create_order,
    get_success_data,
    set_clock,
    setup_active_chain,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["contracts_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
OPS = TEST_USERS["reseller_ops_headers"]


def _make_fed_taa_chain(api):
    """Manufacturer attesting BR + FED_SCHEDULE vehicle (taa_required) with an
    ACTIVE price list whose line has origin BR — admissible because the
    manufacturer-attested variant whitelists BR."""
    set_clock("2026-10-01T00:00:00Z")
    manufacturer = create_manufacturer(
        legal_name="M Corp", designated_countries=["US", "BR"],
    )
    _, agreement = create_active_agreement(
        manufacturer_id=manufacturer["id"],
        scope_tiers=["FEDERAL", "STATE"],
        product_scope=["SW-"],
    )
    v_fed = create_authorized_vehicle(
        agreement["id"], vehicle_kind="FED_SCHEDULE", buyer_tiers=["FEDERAL"],
        taa_required=True,
    )
    lines = [{"sku": "SW-1", "basis_price_cents": 20000,
              "offered_price_cents": 10000, "origin_country": "BR"}]
    pl_fed = create_active_price_list(v_fed["id"], lines=lines)
    return manufacturer, agreement, v_fed, pl_fed


def _make_state_coop_taa_chain(api):
    """Manufacturer attesting BR + STATE_COOP vehicle (taa_required) with a
    SUBMITTED price list whose line has origin BR. Activation is left to the
    test: per PRD §3.3/§3.7 the line-evidence variant rejects BR."""
    set_clock("2026-10-01T00:00:00Z")
    manufacturer = create_manufacturer(
        legal_name="M Corp", designated_countries=["US", "BR"],
    )
    _, agreement = create_active_agreement(
        manufacturer_id=manufacturer["id"],
        scope_tiers=["FEDERAL", "STATE"],
        product_scope=["SW-"],
    )
    v_st = create_authorized_vehicle(
        agreement["id"], vehicle_kind="STATE_COOP", buyer_tiers=["STATE"],
        taa_required=True,
    )
    from test_helpers import create_submitted_price_list
    lines = [{"sku": "SW-1", "basis_price_cents": 20000,
              "offered_price_cents": 10000, "origin_country": "BR"}]
    pl_st = create_submitted_price_list(v_st["id"], lines=lines)
    return manufacturer, agreement, v_st, pl_st


class TestTaaDualVariantDivergence:
    def test_br_origin_passes_federal_clears_order(self, api):
        """PRD §3.7: "On a FED_SCHEDULE vehicle, the manufacturer-attested
        variant runs: the order passes when every line's origin_country is a
        member of the manufacturer's designated_countries list."

        Design: Difficulty/dual_variant_calc/taa_manufacturer_attested_vs_line_evidence_divergence
        """
        _, _, v_fed, pl_fed = _make_fed_taa_chain(api)
        resp = api.create_order(
            {"vehicle_id": v_fed["id"], "price_list_id": pl_fed["id"],
             "buyer_tier": "FEDERAL", "lines": [{"sku": "SW-1", "qty": 1}]},
            OPS,
        )
        order = validate_success(resp, expected_status=201)
        resp = api.submit_order(order["id"], OPS)
        order = validate_success(resp)
        assert order["origin_flag"] == "TAA_PASS"
        assert order["compliance_status"] == "CLEARED"

    def test_br_origin_fails_state_coop_blocks_activation(self, api):
        """PRD §3.7: "On a STATE_COOP, AGENCY_SPECIFIC, or COOP_PURCHASING
        vehicle, the line-evidence variant runs: the order passes when every
        line's origin_country is a member of the fixed statutory
        designated-countries list, which is exactly the twelve codes US, CA,
        MX, GB, DE, FR, JP, AU, IL, KR, NO, CH."
        PRD §3.3: "Activation re-validates four things against every price
        line, plus a uniqueness check on the vehicle, in this order: the
        vehicle is still AUTHORIZED; every line satisfies the MFC floor;
        every line's origin_country passes the vehicle's TAA rules; ..."
        PRD §2.10: "TAA origin — when the vehicle requires TAA, every order
        line's origin must pass the vehicle's TAA variant; failure yields
        ERR_TAA_ORIGIN_VIOLATION (HTTP 422)."

        Design: Difficulty/dual_variant_calc/taa_manufacturer_attested_vs_line_evidence_divergence
        """
        _, _, v_st, pl_st = _make_state_coop_taa_chain(api)
        resp = api.activate_price_list(pl_st["id"], CO)
        validate_error(resp, ApiErrorId.ERR_TAA_ORIGIN_VIOLATION)
        pl = validate_success(api.get_price_list(pl_st["id"], CM))
        assert pl["status"] == "SUBMITTED"

    def test_same_line_diverges_across_variants(self, api):
        """PRD §3.7: "Both variants consume the same order lines; their
        results can diverge when a manufacturer attests a country not on the
        statutory list or vice versa."

        Design: Difficulty/dual_variant_calc/taa_manufacturer_attested_vs_line_evidence_divergence
        """
        _, _, v_fed, pl_fed = _make_fed_taa_chain(api)
        _, _, v_st, pl_st = _make_state_coop_taa_chain(api)
        o_fed = create_cleared_order(v_fed["id"], pl_fed["id"])
        assert o_fed["origin_flag"] == "TAA_PASS"
        resp = api.activate_price_list(pl_st["id"], CO)
        validate_error(resp, ApiErrorId.ERR_TAA_ORIGIN_VIOLATION)


def _make_mfc_pair(api):
    """Agreement mfc_discount_pct=0.40 with FED_SCHEDULE + STATE_COOP
    vehicles, each holding a SUBMITTED list with offered = 75% of basis."""
    set_clock("2026-10-01T00:00:00Z")
    _, agreement = create_active_agreement(
        scope_tiers=["FEDERAL", "STATE"],
        mfc_discount_pct=0.40,
        product_scope=["HW-"],
    )
    v_fed = create_authorized_vehicle(
        agreement["id"], vehicle_kind="FED_SCHEDULE", buyer_tiers=["FEDERAL"],
    )
    v_st = create_authorized_vehicle(
        agreement["id"], vehicle_kind="STATE_COOP", buyer_tiers=["STATE"],
    )
    return agreement, v_fed, v_st


def _submit_mfc_list(api, vehicle_id):
    from test_helpers import create_submitted_price_list
    return create_submitted_price_list(
        vehicle_id,
        lines=[{"sku": "HW-1", "basis_price_cents": 100000,
                "offered_price_cents": 75000, "origin_country": "US"}],
    )


class TestMfcFloorVariantDivergence:
    def test_federal_floor_rejects_75pct_offer(self, api):
        """PRD §3.3: "On a FED_SCHEDULE vehicle, the agreement's
        mfc_discount_pct applies as stated."
        PRD §3.3: "Equality with the floor is allowed; one cent above the
        floor is rejected with ERR_MFC_FLOOR_VIOLATION."

        Design: Difficulty/dual_variant_calc/mfc_floor_federal_vs_state_coop_variant_divergence
        """
        _, v_fed, _ = _make_mfc_pair(api)
        pl_fed = _submit_mfc_list(api, v_fed["id"])
        # floor(100000 * (1 - 0.40)) = 60000; offered 75000 > 60000.
        resp = api.activate_price_list(pl_fed["id"], CO)
        validate_error(resp, ApiErrorId.ERR_MFC_FLOOR_VIOLATION)
        pl = validate_success(api.get_price_list(pl_fed["id"], CM))
        assert pl["status"] == "SUBMITTED"

    def test_state_coop_cap_admits_75pct_offer(self, api):
        """PRD §3.3: "On a STATE_COOP or COOP_PURCHASING vehicle, the
        effective discount used in the floor computation is the lesser of the
        agreement's mfc_discount_pct and 0.25 — the state-cooperative cap — so
        offered prices may sit above the federal floor without violating this
        variant."

        Design: Difficulty/dual_variant_calc/mfc_floor_federal_vs_state_coop_variant_divergence
        """
        _, _, v_st = _make_mfc_pair(api)
        pl_st = _submit_mfc_list(api, v_st["id"])
        # effective discount = min(0.40, 0.25) = 0.25; floor(100000*0.75)=75000; offered==floor.
        resp = api.activate_price_list(pl_st["id"], CO)
        pl = validate_success(resp)
        assert pl["status"] == "ACTIVE"

    def test_identical_offer_diverges_across_vehicle_kinds(self, api):
        """PRD §3.3: "The rule has two variants keyed off vehicle_kind."

        Design: Difficulty/dual_variant_calc/mfc_floor_federal_vs_state_coop_variant_divergence
        """
        _, v_fed, v_st = _make_mfc_pair(api)
        pl_fed = _submit_mfc_list(api, v_fed["id"])
        pl_st = _submit_mfc_list(api, v_st["id"])
        resp_fed = api.activate_price_list(pl_fed["id"], CO)
        validate_error(resp_fed, ApiErrorId.ERR_MFC_FLOOR_VIOLATION)
        resp_st = api.activate_price_list(pl_st["id"], CO)
        pl = validate_success(resp_st)
        assert pl["status"] == "ACTIVE"
        pl_fed_after = validate_success(api.get_price_list(pl_fed["id"], CM))
        assert pl_fed_after["status"] == "SUBMITTED"
