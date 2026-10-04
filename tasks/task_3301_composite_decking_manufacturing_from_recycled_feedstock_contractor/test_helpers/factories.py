"""Payload factories — one per entity, input fields only."""


def create_plant_payload(**overrides) -> dict:
    defaults = {
        "name": "Winchester",
        "daily_capacity_lf": 10000,
        "lines": 1,
        "pre_season_window_start": "01-01",
        "pre_season_window_end": "02-28",
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    defaults = {"name": "Sup S", "kind": "BROKER"}
    defaults.update(overrides)
    return defaults


def create_collection_program_payload(**overrides) -> dict:
    defaults = {"region": "Mid-Atlantic", "rebate_per_lb_cents": 10}
    defaults.update(overrides)
    return defaults


def create_feedstock_lot_payload(**overrides) -> dict:
    defaults = {
        "material": "WOOD_FLOUR",
        "weight_lbs": 100,
        "received_date": "2026-02-20",
        "moisture_pct": 5.0,
        "contamination_ppm": 100,
        "certificate_ref": "C-1",
    }
    defaults.update(overrides)
    return defaults


def create_formulation_payload(**overrides) -> dict:
    defaults = {
        "name": "F1",
        "lines": [
            {"material": "VIRGIN_PE", "weight_fraction_bp": 5000},
            {"material": "WOOD_FLOUR", "weight_fraction_bp": 5000},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_product_line_payload(**overrides) -> dict:
    defaults = {
        "name": "Transcend",
        "color": "Grey",
        "capped": False,
        "profile": "GROOVED",
        "emboss": "WOODGRAIN",
        "board_length_ft": 16,
    }
    defaults.update(overrides)
    return defaults


def create_dealer_payload(**overrides) -> dict:
    defaults = {
        "name": "Dealer D",
        "territory_code": "VA-N",
        "credit_limit_cents": 100000000,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_order_payload(**overrides) -> dict:
    defaults = {"lf": 100, "ship_week_start": "2026-03-02"}
    defaults.update(overrides)
    return defaults


def create_stocking_commitment_payload(**overrides) -> dict:
    defaults = {"territory_code": "VA-N", "committed_lf": 1000, "season_year": 2026}
    defaults.update(overrides)
    return defaults


def create_allocation_commitment_payload(**overrides) -> dict:
    defaults = {"reserved_lf": 100}
    defaults.update(overrides)
    return defaults


def create_production_run_payload(**overrides) -> dict:
    defaults = {
        "planned_lf": 100,
        "production_date": "2026-03-01",
        "run_kind": "SELLABLE",
    }
    defaults.update(overrides)
    return defaults


def create_contractor_payload(**overrides) -> dict:
    defaults = {"name": "Pro A", "email": "a@build.example"}
    defaults.update(overrides)
    return defaults


def create_training_module_payload(**overrides) -> dict:
    defaults = {
        "title": "Install Basics",
        "version_no": 1,
        "duration_hours": 4.0,
        "required_for_tier": "SILVER",
    }
    defaults.update(overrides)
    return defaults


def create_lead_referral_payload(**overrides) -> dict:
    defaults = {"homeowner_name": "H Owner", "zip_code": "22201"}
    defaults.update(overrides)
    return defaults


def create_install_registration_payload(**overrides) -> dict:
    defaults = {"install_date": "2026-03-01"}
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {"category": "STRUCTURAL"}
    defaults.update(overrides)
    return defaults


def create_sample_kit_payload(**overrides) -> dict:
    defaults = {"kit_type": "DISPLAY_BOARD"}
    defaults.update(overrides)
    return defaults


def create_color_chip_request_payload(**overrides) -> dict:
    defaults = {"quantity": 50}
    defaults.update(overrides)
    return defaults


def create_price_book_payload(**overrides) -> dict:
    defaults = {
        "name": "PB26",
        "effective_from": "2026-01-01",
        "tier_discounts_bp": {"STANDARD": 0, "PREFERRED": 1000},
    }
    defaults.update(overrides)
    return defaults
