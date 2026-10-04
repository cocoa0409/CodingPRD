"""Pack certification workflow: cycle, lockdown, segregation, compatibility sets."""
from test_helpers import (
    ApiErrorId,
    assert_battery_pack,
    create_certified_pack,
    create_pack,
    create_platform,
    create_tool,
    decide_pack,
    get_pack,
    get_tool,
    issue_bulletin,
    pack_payload,
    set_clock,
    submit_pack,
    tool_model_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_cycle_pack():
    """Platform + one gen-1 pack rejected in round 1. Returns (platform, pack)."""
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_pack(pf["id"], sku="P-CYC", pack_generation=1, cell_format="C18650",
                     rated_capacity_wh=80, max_charge_rate_w=150, replacement_price_cents=15000)
    submit_pack(pk["id"], "pe-ana")
    decide_pack(pk["id"], "REJECTED", "ce-bob")
    return pf, pk


def test_pack_certification_reject_resubmit_cycle_resubmission(api):
    """PRD §3.2: "A `ProductEngineer` submits a pack in `DESIGN` — or resubmits
    one in `REJECTED` — moving it to `SUBMITTED`; the caller's `X-User-ID` is
    stamped into `submitted_by_user_id` and the pack's `version` increments."

    Design: Difficulty/non_linear_state_machine/pack_certification_reject_resubmit_cycle
    """
    pf, pk = _setup_cycle_pack()
    rejected = get_pack(pk["id"])
    assert rejected["certification_status"] == "REJECTED"
    assert rejected["version"] == 3  # create 1, submit 2, reject 3
    resub = submit_pack(pk["id"], "pe-chen")
    assert resub["certification_status"] == "SUBMITTED"
    assert resub["submitted_by_user_id"] == "pe-chen", "resubmission re-stamps the submitter"
    assert resub["version"] == 4


def test_pack_certification_reject_resubmit_cycle_certified_regeneration(api, product_engineer_headers):
    """PRD §3.2: "Certification to `CERTIFIED` recomputes the platform's
    `current_generation` and bumps the platform's `version` by 1 in addition to
    the pack's own increment"
    PRD §3.1: "The platform's `current_generation` is a computed aggregate: the
    maximum `pack_generation` over this platform's packs whose
    `certification_status` is `CERTIFIED`, or 0 when no such pack exists."

    Design: Difficulty/non_linear_state_machine/pack_certification_reject_resubmit_cycle
    """
    pf, pk = _setup_cycle_pack()
    submit_pack(pk["id"], "pe-chen")
    certified = decide_pack(pk["id"], "CERTIFIED", "ce-bob")
    assert certified["certification_status"] == "CERTIFIED"
    assert certified["version"] == 5
    # Platform current_generation is 1 (observable through the generation
    # ratchet): a gen-2 pack is now allowed, a gen-3 pack is not.
    ok = api.create_pack(pack_payload(pf["id"], sku="P-CYC-G2", pack_generation=2),
                         product_engineer_headers)
    validate_success(ok, 201)
    too_far = api.create_pack(pack_payload(pf["id"], sku="P-CYC-G3", pack_generation=3),
                              product_engineer_headers)
    validate_error(too_far, ApiErrorId.ERR_PACK_GENERATION_VIOLATION)


def test_pack_decide_from_design_returns_invalid_state(api, compliance_engineer_headers):
    """PRD §3.2: "A `ComplianceEngineer` then decides a `SUBMITTED` pack by
    supplying a `decision` of `CERTIFIED` or `REJECTED`"
    PRD §2.8: "State validity: the entity is in a valid from-state for the
    requested transition (including terminal-state lockdown and rejection of
    stage-skipping targets)"

    Design: Corner/state_machines/pack_decide_from_design_returns_invalid_state
    """
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_pack(pf["id"], sku="P-LST")
    resp = api.decide_pack_certification(pk["id"], {"decision": "CERTIFIED"},
                                         compliance_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_pack(pk["id"])["certification_status"] == "DESIGN"


def test_pack_recalled_terminal_lockdown(api, product_engineer_headers):
    """PRD §3.2: "A `CERTIFIED` pack moves to the terminal `RECALLED` state only
    through the `RECALL` bulletin cascade"
    PRD §2.8: "State validity: the entity is in a valid from-state for the
    requested transition (including terminal-state lockdown and rejection of
    stage-skipping targets)"

    Design: Corner/state_machines/pack_recalled_terminal_lockdown
    """
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_certified_pack(pf["id"], sku="P-LST")
    issue_bulletin(pf["id"], battery_pack_ids=[pk["id"]], severity="RECALL",
                   title="recall", effective_from="2026-09-01T00:00:00Z")
    assert get_pack(pk["id"])["certification_status"] == "RECALLED"
    resp = api.submit_pack_certification(pk["id"], product_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_pack(pk["id"])["certification_status"] == "RECALLED"


def test_pack_decide_by_submitting_user_returns_forbidden(api):
    """PRD §3.2: "if the decider's `X-User-ID` equals the recorded
    `submitted_by_user_id`, the decision is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/pack_decide_by_submitting_user_returns_forbidden
    """
    from test_helpers import ce_headers
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_pack(pf["id"], sku="P-LST")
    submit_pack(pk["id"], "shared-user")
    resp = api.decide_pack_certification(pk["id"], {"decision": "CERTIFIED"},
                                         ce_headers("shared-user"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_pack(pk["id"])["certification_status"] == "SUBMITTED"


def _setup_compatibility_sets():
    """Platform with P1 gen1 CERTIFIED, P2 gen2 SUBMITTED, P3 gen2 REJECTED,
    and a tool with pack window [1,3]. Returns (platform, p1, p2, p3, tool)."""
    from test_helpers import charger_payload  # noqa: F401  (kept for parity)
    set_clock()
    pf = create_platform(code="MX18")
    p1 = create_pack(pf["id"], sku="P-G1", pack_generation=1)
    submit_pack(p1["id"])
    decide_pack(p1["id"], "CERTIFIED")
    p2 = create_pack(pf["id"], sku="P-G2", pack_generation=2, rated_capacity_wh=150,
                     max_charge_rate_w=300, replacement_price_cents=26000)
    submit_pack(p2["id"])
    p3 = create_pack(pf["id"], sku="P-G2R", pack_generation=2, cell_supplier_code="LG",
                     rated_capacity_wh=150, max_charge_rate_w=300, replacement_price_cents=26000)
    submit_pack(p3["id"])
    decide_pack(p3["id"], "REJECTED")
    tm = create_tool(pf["id"], model_code="T-2953", trade="ELECTRICAL", category="SAW",
                     tier="PROFESSIONAL", avg_power_draw_w=400,
                     min_pack_generation=1, max_pack_generation=3,
                     replacement_price_cents=25000, warranty_days=360, free_replacement_days=60,
                     torque_min_nm=5, torque_max_nm=150)
    return pf, p1, p2, p3, tm


def test_compatibility_regulatory_set_counts_certified_only(api, product_engineer_headers):
    """PRD §3.3: "The REGULATORY variant — the one that matters for the launch
    gate, for `regulatory_compatible_pack_count`, for `best_runtime_min`, and
    for channel listing certification checks — keeps only packs that are
    `CERTIFIED` and not on `safety_hold`"
    PRD §3.3: "`regulatory_compatible_pack_count` is the size of the REGULATORY
    set."

    Design: Difficulty/dual_variant_calc/compatibility_regulatory_vs_engineering_set_divergence
    """
    pf, p1, p2, p3, tm = _setup_compatibility_sets()
    tool = get_tool(tm["id"])
    assert tool["regulatory_compatible_pack_count"] == 1, (
        "only the CERTIFIED in-range pack counts"
    )
    certified_rows, meta = validate_paginated(api.list_packs(
        product_engineer_headers,
        params={"platform_id": pf["id"], "certification_status": "CERTIFIED"},
    ))
    assert [r["id"] for r in certified_rows] == [p1["id"]]
    assert meta["total_count"] == 1


def test_compatibility_engineering_set_is_superset_via_filters(api, product_engineer_headers):
    """PRD §3.3: "The ENGINEERING variant, observable by enumerating the pack
    catalogue with `certification_status` filters during development, keeps
    `CERTIFIED` and `SUBMITTED` packs and ignores `safety_hold`, making it a
    superset of REGULATORY whenever a `SUBMITTED` in-range pack exists."

    Design: Difficulty/dual_variant_calc/compatibility_regulatory_vs_engineering_set_divergence
    """
    pf, p1, p2, p3, tm = _setup_compatibility_sets()
    submitted_rows, meta_s = validate_paginated(api.list_packs(
        product_engineer_headers,
        params={"platform_id": pf["id"], "certification_status": "SUBMITTED"},
    ))
    assert [r["id"] for r in submitted_rows] == [p2["id"]]
    assert meta_s["total_count"] == 1
    # ENGINEERING set = CERTIFIED + SUBMITTED in range = {P1, P2}, size 2,
    # strictly larger than the REGULATORY size 1; P3 (REJECTED) is in neither.
    rejected_rows, meta_r = validate_paginated(api.list_packs(
        product_engineer_headers,
        params={"platform_id": pf["id"], "certification_status": "REJECTED"},
    ))
    assert [r["id"] for r in rejected_rows] == [p3["id"]]
    assert 1 + 1 == 2 > get_tool(tm["id"])["regulatory_compatible_pack_count"]


def _setup_charge_estimate():
    """Platform, certified gen-1 pack (ratchet), gen-2 pack (100 Wh, 200 W),
    gen-1 and gen-2 chargers (400 W). Returns (platform, pack2, ch_old, ch_new)."""
    from test_helpers import create_charger
    set_clock()
    pf = create_platform(code="MX18")
    p1 = create_certified_pack(pf["id"], sku="P-LST", pack_generation=1)
    pk2 = create_pack(pf["id"], sku="P-G2", pack_generation=2, rated_capacity_wh=100,
                      max_charge_rate_w=200, replacement_price_cents=26000)
    ch_old = create_charger(pf["id"], model_code="C-OLD", charger_generation=1,
                            max_charge_rate_w=400)
    ch_new = create_charger(pf["id"], model_code="C-NEW", charger_generation=2,
                            max_charge_rate_w=400)
    return pf, pk2, ch_old, ch_new


def test_charge_estimate_legacy_charger_derate(api, product_engineer_headers):
    """PRD §3.2: "For a compatible pair, the effective charge power is the lesser
    of the charger's `max_charge_rate_w` and the pack's `max_charge_rate_w`; if
    the charger's `charger_generation` is strictly older than the pack's
    `pack_generation`, a legacy derate of 0.5 applies — the effective power is
    halved and rounded half up to whole watts. `charge_estimate_minutes` is then
    the pack's `rated_capacity_wh` divided by that effective rate, multiplied by
    60, rounded half up to whole minutes."

    Design: Corner/calculations/charge_estimate_legacy_charger_derate
    """
    pf, pk2, ch_old, ch_new = _setup_charge_estimate()
    legacy = validate_success(api.get_pack(pk2["id"], product_engineer_headers,
                                           params={"charger_id": ch_old["id"]}))
    assert legacy["charger_compatible"] is True
    assert legacy["charge_estimate_minutes"] == 60  # min(400,200)=200 -> 100 W derated
    modern = validate_success(api.get_pack(pk2["id"], product_engineer_headers,
                                           params={"charger_id": ch_new["id"]}))
    assert modern["charger_compatible"] is True
    assert modern["charge_estimate_minutes"] == 30  # full 200 W


def test_charge_estimate_cross_platform_rejected(api, product_engineer_headers):
    """PRD §3.2: "`charger_compatible` is true exactly when the charger and the
    pack share a platform; when they do not, the request is rejected outright
    with `ERR_INCOMPATIBLE_PAIRING`."

    Design: Corner/calculations/charge_estimate_cross_platform_rejected
    """
    from test_helpers import create_charger
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_pack(pf["id"], sku="P-LST")
    pf2 = create_platform(code="MX12", interface_key="INTERFACE_B", chemistry_family="LFP",
                          backward_commitment_years=8)
    ch = create_charger(pf2["id"], model_code="C-12", charger_generation=1,
                        max_charge_rate_w=200)
    resp = api.get_pack(pk["id"], product_engineer_headers, params={"charger_id": ch["id"]})
    validate_error(resp, ApiErrorId.ERR_INCOMPATIBLE_PAIRING)
