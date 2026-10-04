"""Corner coverage: entity creation responses and computed-field derivation."""
from test_helpers import (
    api, validate_success, get_success_data, TEST_USERS, make_partner_ops_headers,
    startup_clock, create_certified_blueprint, create_validated_partner,
    create_partner, create_product, create_supply_node, create_stack_license,
    create_and_commit_allocation_hold, get_product, is_valid_uuid,
    is_iso8601_timestamp,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestPartnerCreation:
    """Registration lands the account in APPLIED with an unqualified priority class."""

    def test_registration_defaults_and_system_fields(self):
        """PRD §3.2: "Registration places the account in `APPLIED` qualification with
        `ACTIVE` standing and an `UNQUALIFIED` priority class."
        PRD §2.10: "The `id` field is a server-minted UUID with no type prefix."

        Design: Corner/entities/partner_create_returns_system_fields_and_lands_unqualified
        """
        startup_clock()
        data = validate_success(api.create_partner({
            "legal_name": "Helios Cloud Systems",
            "partner_type": "CLOUD_PROVIDER",
            "destination_country": "US",
            "export_restriction_tier": "LICENSE_EXCEPTION",
            "origin_epoch_index": 5,
        }, TEST_USERS["partner_ops_headers"]), 201)

        assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert data["qualification_status"] == "APPLIED"
        assert data["allocation_priority_class"] == "UNQUALIFIED"
        assert data["status"] == "ACTIVE"
        assert data["entitlement_units_held"] == 0
        assert data["capacity_ledger_net"] == 0
        assert data["qualification_attempt_count"] == 0
        assert data["version"] == 1


class TestProductCreation:
    """Creation applies the declared density band and initialises free units."""

    def test_sku_opens_at_preview_with_the_declared_density(self):
        """PRD §3.1: "The SKU opens at `lifecycle_stage` `PREVIEW` with its
        `available_units` initialised to its full supply ceiling, and its export
        performance density is set by the declared variant described in §2.5."
        PRD §2.5: "a declared 1350 watts stays `LOW` at creation".

        Design: Corner/entities/allocation_create_applies_declared_band_and_derives_free_units
        """
        startup_clock()
        data = validate_success(api.create_product({
            "sku_code": "AC-100-PCIE",
            "product_family": "DATACENTER",
            "form_factor": "PCLE",
            "hbm_capacity_gb": 80,
            "tdp_watts": 1350,
            "supply_ceiling_units": 10000,
            "long_term_availability_through": "2029-01-01T00:00:00Z",
        }, ADMIN), 201)

        assert data["lifecycle_stage"] == "PREVIEW"
        assert data["available_units"] == 10000, (
            "available units start at the full supply ceiling"
        )
        assert data["reserved_evaluation_units"] == 0
        assert data["allocated_units"] == 0
        assert data["export_performance_density"] == 1350, (
            "the declared variant uses tdp_watts verbatim rather than rounding up to 1400"
        )


class TestProductUpdate:
    """Adjusting the supply ceiling re-derives the available units."""

    def test_raising_the_ceiling_re_derives_available_units(self):
        """PRD §3.1: "An operator may adjust a SKU's supply ceiling or its promised
        availability horizon, which re-derives the available units without re-running
        any hold ranking".

        Design: Corner/entities/allocation_update_re_derives_available_units
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        create_and_commit_allocation_hold(product["id"], node["id"], 400, partner["id"])

        data = validate_success(api.update_product(product["id"],
                                                   {"supply_ceiling_units": 12000}, ADMIN))
        assert data["supply_ceiling_units"] == 12000
        assert data["available_units"] == 11600, (
            f"12000 - 400 allocated - 0 ring-fenced is 11600, got {data['available_units']}"
        )
        assert get_product(product["id"])["allocated_units"] == 400, (
            "the already-committed allocation is not disturbed by the ceiling change"
        )