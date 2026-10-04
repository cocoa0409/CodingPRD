"""Brand-equity ledger: dilution cost formula edges, fiscal gates at brand
review, pinned novelty-baseline evaluation order, and the discontinue refund."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, validate_error, validate_success,
)
from test_helpers import fixtures as fx

BM = TEST_USERS["brand_manager_headers"]
SP = TEST_USERS["supply_planner_headers"]


def test_dilution_gate_evaluation_order_novelty_baseline_excludes_candidate():
    """PRD §3.2: "The evaluation baseline is pinned: only the brand's other lines that are already `LAUNCHED` at the moment this line's launch arithmetic is evaluated count, and the candidate line is never part of its own baseline."
    PRD §3.2: "A core line always costs 0. Any other line costs 400 basis points, plus 150 basis points for every target channel beyond the first, plus a 200-basis-point **novelty** surcharge when at least one of the line's pack formats (in any status except `RETIRED`) uses a `delivery_system` that no pack format (again excluding `RETIRED`) of any *other* `LAUNCHED` line of the same brand uses — capped in total at 1000 basis points."

    Design: Difficulty/combinatorial_formula/dilution_gate_evaluation_order_novelty_baseline_excludes_candidate
    """
    core = fx.setup_launched_line(
        line_overrides={"line_code": "CORE", "name": "Core Multi-Use",
                        "is_core": True})
    brand_id = core["brand"]["id"]
    mfr1, mfr2 = core["mfr1"], core["mfr2"]

    def build_extension(line_code, name):
        line = fx.create_product_line(
            brand_id, line_code=line_code, name=name, is_core=False,
            target_channels=["HARDWARE", "AUTOMOTIVE"])
        form = fx.create_and_seal_formulation(line["id"])
        pack = fx.create_pack_format_record(
            line["id"], size_ml=200, delivery_system="PUMP",
            channel_restrictions=["HARDWARE"], case_pack_qty=6)
        approved = fx.approve_line_to_pilot(line["id"])
        fx.create_active_grant(mfr1["id"], form["id"],
                               component_scope=["C1", "C2"])
        fx.create_active_grant(mfr2["id"], form["id"],
                               component_scope=["C3", "C4"])
        validate_success(api_client.tool_pack_format(pack["id"], SP))
        fx.create_price_list_record(pack["id"])
        validate_success(api_client.enter_production_pack_format(pack["id"], SP))
        launched = validate_success(api_client.launch_product_line(line["id"], BM))
        return line, approved, launched

    line_d, approved_d, launched_d = build_extension("EXT-D", "Pump Extension D")
    assert approved_d["dilution_cost_bps"] == 750, \
        "400 base + 150 extra channel + 200 PUMP-novel vs a baseline holding only AEROSOL"
    assert launched_d["dilution_cost_bps"] == 750, "frozen at PILOT entry"

    line_e, approved_e, launched_e = build_extension("EXT-E", "Pump Extension E")
    assert approved_e["dilution_cost_bps"] == 550, \
        "PUMP entered the baseline when EXT-D launched, so EXT-E gets no novelty"
    assert launched_e["dilution_cost_bps"] == 550

    brand = validate_success(api_client.get_brand(brand_id, BM))
    assert brand["dilution_consumed_bps"] == 1300, "0 core + 750 + 550"
    assert brand["core_identity_share_bps"] == 8700


def test_equity_budget_exceeded_at_brand_review():
    """PRD §3.2: "Then the two fiscal gates fire, in this order: the brand's `dilution_consumed_bps` plus the candidate line's live dilution cost must not exceed `equity_budget_bps` (`ERR_EQUITY_BUDGET_EXCEEDED`, HTTP 422), and the brand's `core_identity_share_bps` minus that same candidate cost must remain at least 7000 (`ERR_CORE_IDENTITY_DILUTION`, HTTP 422)."

    Design: Corner/errors/equity_budget_exceeded_at_brand_review
    """
    brand = fx.create_brand(name="Budget Brand",
                            legal_entity_name="Budget Products Co",
                            equity_budget_bps=1000)
    ext1 = fx.create_product_line(brand["id"], line_code="EXT-1",
                                  name="First Extension", is_core=False,
                                  target_channels=["HARDWARE", "AUTOMOTIVE"])
    fx.create_and_seal_formulation(ext1["id"])
    approved1 = fx.approve_line_to_pilot(ext1["id"])
    assert approved1["dilution_cost_bps"] == 550, "400 base + 150 extra channel"

    ext2 = fx.create_product_line(brand["id"], line_code="EXT-2",
                                  name="Second Extension", is_core=False,
                                  target_channels=["HARDWARE", "AUTOMOTIVE"])
    fx.create_and_seal_formulation(ext2["id"])
    resp = api_client.brand_review(ext2["id"], "APPROVE", BM)
    validate_error(resp, ApiErrorId.ERR_EQUITY_BUDGET_EXCEEDED)

    line = validate_success(api_client.get_product_line(ext2["id"], BM))
    assert line["status"] == "FORMULATION", "a rejected approval leaves FORMULATION"
    brand_after = validate_success(api_client.get_brand(brand["id"], BM))
    assert brand_after["dilution_consumed_bps"] == 550, \
        "the rejected line's cost was never frozen into consumption"


def test_identity_floor_breach_at_brand_review():
    """PRD §3.2: "Then the two fiscal gates fire, in this order: the brand's `dilution_consumed_bps` plus the candidate line's live dilution cost must not exceed `equity_budget_bps` (`ERR_EQUITY_BUDGET_EXCEEDED`, HTTP 422), and the brand's `core_identity_share_bps` minus that same candidate cost must remain at least 7000 (`ERR_CORE_IDENTITY_DILUTION`, HTTP 422)."
    PRD §3.2: "Any other line costs 400 basis points, plus 150 basis points for every target channel beyond the first, plus a 200-basis-point **novelty** surcharge when at least one of the line's pack formats (in any status except `RETIRED`) uses a `delivery_system` that no pack format (again excluding `RETIRED`) of any *other* `LAUNCHED` line of the same brand uses — capped in total at 1000 basis points." (Each extension below approves against an empty LAUNCHED baseline, so its pack's delivery system is novel: 400 + 150*3 + 200 = 1050, capped to 1000.)

    Design: Corner/errors/identity_floor_breach_at_brand_review
    """
    brand = fx.create_brand()
    specs = [("EXT-1", "PRECISION_PEN", 8), ("EXT-2", "PUMP", 200),
             ("EXT-3", "TRIGGER_SPRAY", 450)]
    for code, delivery, size in specs:
        line = fx.create_product_line(
            brand["id"], line_code=code, name=code, is_core=False,
            target_channels=["HARDWARE", "AUTOMOTIVE", "INDUSTRIAL", "MASS"])
        fx.create_and_seal_formulation(line["id"])
        fx.create_pack_format_record(line["id"], size_ml=size,
                                     delivery_system=delivery,
                                     channel_restrictions=["HARDWARE"])
        approved = fx.approve_line_to_pilot(line["id"])
        assert approved["dilution_cost_bps"] == 1000, "1050 capped at 1000"

    brand_mid = validate_success(api_client.get_brand(brand["id"], BM))
    assert brand_mid["dilution_consumed_bps"] == 3000

    e4 = fx.create_product_line(
        brand["id"], line_code="EXT-4", name="Bulk", is_core=False,
        target_channels=["HARDWARE", "AUTOMOTIVE", "INDUSTRIAL", "MASS"])
    fx.create_and_seal_formulation(e4["id"])
    fx.create_pack_format_record(e4["id"], size_ml=3785,
                                 delivery_system="BULK_CONTAINER",
                                 channel_restrictions=["HARDWARE"])
    resp = api_client.brand_review(e4["id"], "APPROVE", BM)
    validate_error(resp, ApiErrorId.ERR_CORE_IDENTITY_DILUTION)

    line = validate_success(api_client.get_product_line(e4["id"], BM))
    assert line["status"] == "FORMULATION"


def test_dilution_cost_edges_base_and_cap():
    """PRD §3.2: "A core line always costs 0. Any other line costs 400 basis points, plus 150 basis points for every target channel beyond the first, plus a 200-basis-point **novelty** surcharge when at least one of the line's pack formats (in any status except `RETIRED`) uses a `delivery_system` that no pack format (again excluding `RETIRED`) of any *other* `LAUNCHED` line of the same brand uses — capped in total at 1000 basis points."

    Design: Corner/calculations/dilution_cost_edges_base_and_cap
    """
    core = fx.setup_launched_line(
        line_overrides={"line_code": "CORE", "name": "Core Multi-Use",
                        "is_core": True})
    brand_id = core["brand"]["id"]

    ext1 = fx.create_product_line(brand_id, line_code="EXT-1",
                                  name="Plain Extension", is_core=False,
                                  target_channels=["HARDWARE"])
    fx.create_and_seal_formulation(ext1["id"])
    approved1 = fx.approve_line_to_pilot(ext1["id"])
    assert approved1["dilution_cost_bps"] == 400, \
        "base 400, one channel, no pack formats so no novelty"

    ext2 = fx.create_product_line(
        brand_id, line_code="EXT-2", name="Pen Extension", is_core=False,
        target_channels=["HARDWARE", "AUTOMOTIVE", "INDUSTRIAL", "MASS"])
    fx.create_and_seal_formulation(ext2["id"])
    fx.create_pack_format_record(ext2["id"], size_ml=8,
                                 delivery_system="PRECISION_PEN",
                                 channel_restrictions=["HARDWARE"],
                                 case_pack_qty=24)
    approved2 = fx.approve_line_to_pilot(ext2["id"])
    assert approved2["dilution_cost_bps"] == 1000, \
        "400 + 150*3 + 200 novelty = 1050, capped at 1000"

    brand = validate_success(api_client.get_brand(brand_id, BM))
    assert brand["dilution_consumed_bps"] == 1400, "0 core + 400 + 1000"
    assert brand["core_identity_share_bps"] == 8600


def test_discontinued_line_refunds_half_its_frozen_cost():
    """PRD §3.2: "Discontinuation recomputes the brand's dilution consumption and identity share; a discontinued line that had reached `PILOT` continues to consume half of its frozen cost, rounded down, forever."
    PRD §3.1: "`core_identity_share_bps` is whatever remains of the 10000-point whole after consumption, floored at zero: it is the greater of zero and 10000 minus `dilution_consumed_bps`."

    Design: Corner/calculations/discontinued_line_refunds_half_its_frozen_cost
    """
    brand = fx.create_brand()
    line = fx.create_product_line(brand["id"], line_code="EXT-1",
                                  name="Trigger Extension", is_core=False,
                                  target_channels=["HARDWARE", "AUTOMOTIVE"])
    form = fx.create_and_seal_formulation(line["id"])
    pack = fx.create_pack_format_record(line["id"], size_ml=450,
                                        delivery_system="TRIGGER_SPRAY",
                                        channel_restrictions=["HARDWARE"],
                                        case_pack_qty=6)
    approved = fx.approve_line_to_pilot(line["id"])
    assert approved["dilution_cost_bps"] == 750, \
        "400 + 150 extra channel + 200 novelty on an empty LAUNCHED baseline"

    mfr1 = fx.create_qualified_manufacturer(legal_name="Alpha Blending Co",
                                            capabilities=["BLENDING"])
    mfr2 = fx.create_qualified_manufacturer(legal_name="Beta Filling Inc",
                                            capabilities=["AEROSOL_FILL"])
    fx.create_active_grant(mfr1["id"], form["id"], component_scope=["C1", "C2"])
    fx.create_active_grant(mfr2["id"], form["id"], component_scope=["C3", "C4"])
    validate_success(api_client.tool_pack_format(pack["id"], SP))
    fx.create_price_list_record(pack["id"])
    validate_success(api_client.enter_production_pack_format(pack["id"], SP))
    validate_success(api_client.launch_product_line(line["id"], BM))

    brand_mid = validate_success(api_client.get_brand(brand["id"], BM))
    assert brand_mid["dilution_consumed_bps"] == 750

    gone = validate_success(api_client.discontinue_product_line(line["id"], BM))
    assert gone["status"] == "DISCONTINUED"
    brand_end = validate_success(api_client.get_brand(brand["id"], BM))
    assert brand_end["dilution_consumed_bps"] == 375, "floor(750 / 2)"
    assert brand_end["core_identity_share_bps"] == 9625
