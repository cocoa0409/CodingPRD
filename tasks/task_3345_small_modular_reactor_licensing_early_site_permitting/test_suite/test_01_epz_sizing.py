"""EPZ sizing calculations: dual variants, clamping, and the permit freeze."""

from test_helpers import (
    assert_dca,
    create_certified_dca,
    create_dca,
    create_site_permit,
)


class TestEpzDualVariant:
    """The deterministic and dose-based variants diverge on the same inputs."""

    def test_variants_diverge_on_low_source_term(self, api):
        """PRD §3.1: "The dose-consequence variant `epz_radius_dose_based_miles`
        combines two terms: a dose term equal to twice the square root of
        `site_boundary_miles` (a coefficient of 2.0), plus a margin term equal
        to 5.0 times the complement of the source term fraction (one minus the
        fraction); their sum is floored at 0.5 miles. The conservative
        selection `epz_radius_selected_miles` takes the larger of the two
        variants, then applies the same 0.5-mile floor and a hard cap of 10.0
        miles."

        Design: Difficulty/dual_variant_calc/epz_deterministic_vs_dose_based_divergence
        """
        dca = create_dca(
            api,
            docket_number="52-001",
            source_term_fraction=0.20,
            site_boundary_miles=4.0,
            plant_net_capacity_mw=160,
        )
        assert_dca(dca)
        # deterministic: 10.0 * 0.20 = 2.00
        assert dca["epz_radius_deterministic_miles"] == 2.00
        # dose-based: max(0.5, 2*sqrt(4.0) + 5*0.80) = max(0.5, 4.0 + 4.0) = 8.00
        assert dca["epz_radius_dose_based_miles"] == 8.00
        # selected: max of both, floored and capped -> 8.00
        assert dca["epz_radius_selected_miles"] == 8.00
        assert dca["epz_radius_deterministic_miles"] != dca["epz_radius_dose_based_miles"]

    def test_dose_based_margin_term_dominates_at_low_fraction(self, api):
        """PRD §3.1: "The dose-based variant dominates at low source-term
        fractions because of the margin term, while the deterministic variant
        dominates when the fraction is high."

        Design: Difficulty/dual_variant_calc/epz_deterministic_vs_dose_based_divergence
        """
        dca = create_dca(
            api,
            docket_number="52-002",
            source_term_fraction=0.20,
            site_boundary_miles=4.0,
        )
        # The margin term (5 * (1 - 0.2) = 4.0) alone already exceeds the
        # deterministic radius (2.0), so the dose-based variant wins.
        assert dca["epz_radius_dose_based_miles"] > dca["epz_radius_deterministic_miles"]
        assert dca["epz_radius_selected_miles"] == dca["epz_radius_dose_based_miles"]


class TestEpzClamping:
    """The conservative selection is floored at 0.5 miles and capped at 10."""

    def test_margin_term_keeps_low_fraction_dca_above_floor(self, api):
        """PRD §3.1: "The conservative selection `epz_radius_selected_miles`
        takes the larger of the two variants, then applies the same 0.5-mile
        floor and a hard cap of 10.0 miles."

        Design: Corner/calculations/epz_floor_and_cap_clamping
        """
        dca = create_dca(
            api,
            docket_number="52-930",
            source_term_fraction=0.01,
            site_boundary_miles=0.25,
        )
        # deterministic: 10.0 * 0.01 = 0.10
        assert dca["epz_radius_deterministic_miles"] == 0.10
        # dose-based: max(0.5, 2*sqrt(0.25) + 5*0.99) = max(0.5, 5.95) = 5.95
        assert dca["epz_radius_dose_based_miles"] == 5.95
        assert dca["epz_radius_selected_miles"] == 5.95

    def test_cap_binds_at_full_source_term(self, api):
        """PRD §3.1: "The conservative selection `epz_radius_selected_miles`
        takes the larger of the two variants, then applies the same 0.5-mile
        floor and a hard cap of 10.0 miles."

        Design: Corner/calculations/epz_floor_and_cap_clamping
        """
        dca = create_dca(
            api,
            docket_number="52-931",
            source_term_fraction=1.0,
            site_boundary_miles=100.0,
        )
        # deterministic: 10.0 * 1.0 = 10.00
        assert dca["epz_radius_deterministic_miles"] == 10.00
        # dose-based: max(0.5, 2*10 + 0) = 20.00
        assert dca["epz_radius_dose_based_miles"] == 20.00
        # selected: min(10.0, max(10.00, 20.00)) = 10.00 — the cap binds
        assert dca["epz_radius_selected_miles"] == 10.00


class TestEpzSiteFreeze:
    """ESP freezes the deterministic radius; COL freezes the selected one."""

    def test_esp_and_col_freeze_different_variants(self, api):
        """PRD §3.6: "an Early Site Permit freezes the application's
        deterministic radius `epz_radius_deterministic_miles`, while a Combined
        License freezes the conservative selected radius
        `epz_radius_selected_miles` — the larger of the two variants, floored
        at 0.5 and capped at 10.0 miles, at two decimal places."

        Design: Corner/endpoints/site_permit_epz_freeze_variant_selection
        """
        # source_term 0.2, boundary 4.0 -> deterministic 2.00,
        # dose-based max(0.5, 2*2 + 5*0.8) = 8.00, selected 8.00
        world = create_certified_dca(
            api,
            subscriptions=(("u1", 50),),
            docket_number="52-951",
            source_term_fraction=0.2,
            site_boundary_miles=4.0,
        )
        dca = world["dca"]
        assert dca["status"] == "CERTIFIED"
        esp = create_site_permit(api, "ESP", dca["id"], site_name="Site ESP")
        col = create_site_permit(api, "COL", dca["id"], site_name="Site COL")
        assert esp["epz_radius_miles"] == 2.00
        assert col["epz_radius_miles"] == 8.00

    def test_frozen_radius_tracks_dca_values_at_creation(self, api):
        """PRD §3.6: "Creation freezes the emergency-planning-zone radius into
        `epz_radius_miles`, and the two permit flavors freeze different
        variants: an Early Site Permit freezes the application's deterministic
        radius `epz_radius_deterministic_miles`, while a Combined License
        freezes the conservative selected radius `epz_radius_selected_miles` —
        the larger of the two variants, floored at 0.5 and capped at 10.0
        miles, at two decimal places."

        Design: Corner/endpoints/site_permit_epz_freeze_variant_selection
        """
        world = create_certified_dca(
            api,
            subscriptions=(("u1", 50),),
            docket_number="52-952",
            source_term_fraction=0.2,
            site_boundary_miles=4.0,
        )
        dca = world["dca"]
        esp = create_site_permit(api, "ESP", dca["id"], site_name="ESP Track")
        col = create_site_permit(api, "COL", dca["id"], site_name="COL Track")
        assert esp["epz_radius_miles"] == dca["epz_radius_deterministic_miles"]
        assert col["epz_radius_miles"] == dca["epz_radius_selected_miles"]
