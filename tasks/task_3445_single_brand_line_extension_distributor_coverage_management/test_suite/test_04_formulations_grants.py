"""Trade-secret formulations and confidentiality grants: storage round-trip,
creation gates, the compartmentalization cap, expiry sweep and clock gates."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, api_client,
    assert_formulation, validate_error, validate_paginated, validate_success,
)
from test_helpers import fixtures as fx

BM = TEST_USERS["brand_manager_headers"]
TSO = TEST_USERS["trade_secret_officer_headers"]
CA = TEST_USERS["compliance_auditor_headers"]


def test_formulation_get_roundtrips_stored_fields():
    """PRD §3.3: "A `TradeSecretOfficer` authors a **Formulation** under a product line, giving it a free-form `version_label`, a `component_codes` array of trade-secret component identifiers, and a `voc_class` of `STANDARD` or `LOW_VOC` (`LOW_VOC` being the only class a `STRICT` market will register)."
    PRD §3.3: "Passing a `master_formulation_id` — which must reference an existing formulation — declares the new record a local market variant of that master; a master formulation itself carries null there. Formulations begin in `DRAFT` with `sealed_at` unset, and can be listed with optional `product_line_id`, `master_formulation_id` and `status` filters."

    Design: Corner/entities/formulation_get_roundtrips_stored_fields
    """
    brand = fx.create_brand()
    line = fx.create_product_line(brand["id"])
    form = fx.create_formulation(line["id"])

    got = validate_success(api_client.get_formulation(form["id"], TSO))
    assert_formulation(got)
    assert got["version_label"] == "v1"
    assert got["component_codes"] == ["C1", "C2", "C3", "C4"]
    assert got["voc_class"] == "STANDARD"
    assert got["master_formulation_id"] is None
    assert got["status"] == "DRAFT"
    assert got["sealed_at"] is None
    assert got["product_line_id"] == line["id"]


def test_grant_requires_sealed_formulation():
    """PRD §3.3: "Creation further requires the manufacturer to be `QUALIFIED` (`ERR_MANUFACTURER_NOT_QUALIFIED`, HTTP 409) and the formulation to be `SEALED` or `COMPARTMENTALIZED` (`ERR_FORMULATION_NOT_SEALED`, HTTP 409)."

    Design: Corner/errors/grant_requires_sealed_formulation
    """
    brand = fx.create_brand()
    line = fx.create_product_line(brand["id"])
    form = fx.create_formulation(line["id"])  # stays DRAFT
    mfr = fx.create_qualified_manufacturer()

    resp = api_client.create_confidentiality_grant(
        {"manufacturer_id": mfr["id"], "formulation_id": form["id"],
         "component_scope": ["C1"], "expires_on": "2027-12-31T00:00:00Z",
         "grant_reason": "PRODUCTION"}, TSO)
    validate_error(resp, ApiErrorId.ERR_FORMULATION_NOT_SEALED)


def test_grant_scope_must_be_subset_of_components():
    """PRD §3.3: "naming a `component_scope` — a non-empty subset of that formulation's `component_codes`, failing `ERR_SCOPE_NOT_SUBSET` (HTTP 422)".

    Design: Corner/errors/grant_scope_must_be_subset_of_components
    """
    sc = fx.setup_line_with_sealed_formulation()
    mfr = fx.create_qualified_manufacturer()

    resp = api_client.create_confidentiality_grant(
        {"manufacturer_id": mfr["id"], "formulation_id": sc["formulation"]["id"],
         "component_scope": ["C9"], "expires_on": "2027-12-31T00:00:00Z",
         "grant_reason": "PRODUCTION"}, TSO)
    validate_error(resp, ApiErrorId.ERR_SCOPE_NOT_SUBSET)


def test_grant_create_with_unknown_formulation_reference_returns_422():
    """PRD §2.6: "Identifiers referenced inside the request body — `formulation_id`, `market_id`, `product_line_id`, `pack_format_id`, `coverage_assignment_id`, `master_formulation_id` — must exist (`ERR_INVALID_REFERENCE`, 422)."

    Design: Corner/validations/grant_create_with_unknown_formulation_reference_returns_422
    """
    fx.create_brand()
    mfr = fx.create_qualified_manufacturer()

    resp = api_client.create_confidentiality_grant(
        {"manufacturer_id": mfr["id"], "formulation_id": NON_EXISTENT_UUID,
         "component_scope": ["C1"], "expires_on": "2027-12-31T00:00:00Z",
         "grant_reason": "PRODUCTION"}, TSO)
    validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE)


def test_compartment_cap_allows_exactly_half():
    """PRD §3.3: "taking the union of this manufacturer's component scopes on this same formulation across grants already in `GRANTED` or `ACTIVE`, plus the candidate scope, the size of that union multiplied by two must not exceed the formulation's total component count — a manufacturer may never hold disclosure over more than half of a formulation's recipe, and a breach is rejected with `ERR_COMPARTMENT_SCOPE_EXCEEDED` (HTTP 422)."

    Design: Corner/calculations/compartment_cap_allows_exactly_half
    """
    sc = fx.setup_line_with_sealed_formulation()
    form_id = sc["formulation"]["id"]
    mfr1 = fx.create_qualified_manufacturer(legal_name="Alpha Blending Co",
                                            capabilities=["BLENDING"])
    mfr2 = fx.create_qualified_manufacturer(legal_name="Beta Filling Inc",
                                            capabilities=["AEROSOL_FILL"])

    g1 = fx.create_granted_grant(mfr1["id"], form_id,
                                 component_scope=["C1", "C2"])
    assert g1["status"] == "GRANTED", "a 2-of-4 union is exactly half and allowed"

    g_over = fx.create_grant_request(mfr1["id"], form_id,
                                     component_scope=["C3"],
                                     grant_reason="SECOND_SOURCE")
    resp = api_client.grant_confidentiality_grant(g_over["id"], TSO)
    validate_error(resp, ApiErrorId.ERR_COMPARTMENT_SCOPE_EXCEEDED)
    stuck = validate_success(api_client.get_confidentiality_grant(g_over["id"], TSO))
    assert stuck["status"] == "REQUESTED", \
        "the rejected grant action did not advance the grant"

    g2 = fx.create_granted_grant(mfr2["id"], form_id,
                                 component_scope=["C3", "C4"])
    assert g2["status"] == "GRANTED", "the cap is per manufacturer, not global"


def test_grant_safety_error_trumps_temporal_window_error():
    """PRD §2.6: "Every request is evaluated against an ordered validation pipeline, and the first failing check determines the error returned — later checks are never reached once an earlier one fails."
    PRD §2.6: "9. **Brand-protection and trade-secret gates.** Lockdown, critical posture, manufacturer qualification, the compartmentalization scope cap, segregation of duties, the VOC regime, the genericization publish gate and the recent-breach requalification block (`ERR_BRAND_IN_LOCKDOWN`, `ERR_POSTURE_CRITICAL`, `ERR_MANUFACTURER_NOT_QUALIFIED`, `ERR_COMPARTMENT_SCOPE_EXCEEDED`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_AUDITOR_CONFLICT`, `ERR_VOC_REGIME_MISMATCH`, `ERR_GENERICIZATION_RISK`, `ERR_RECENT_BREACH`)."
    PRD §3.3: "Creation further requires the manufacturer to be `QUALIFIED` (`ERR_MANUFACTURER_NOT_QUALIFIED`, HTTP 409) and the formulation to be `SEALED` or `COMPARTMENTALIZED` (`ERR_FORMULATION_NOT_SEALED`, HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/grant_safety_error_trumps_temporal_window_error
    """
    sc = fx.setup_line_with_sealed_formulation()
    mfr = fx.create_manufacturer(legal_name="Unvetted Packers LLC",
                                 capabilities=["PACKAGING"])  # stays VETTING

    resp = api_client.create_confidentiality_grant(
        {"manufacturer_id": mfr["id"], "formulation_id": sc["formulation"]["id"],
         "component_scope": ["C1"], "expires_on": "2020-01-01T00:00:00Z",
         "grant_reason": "PRODUCTION"}, TSO)
    validate_error(resp, ApiErrorId.ERR_MANUFACTURER_NOT_QUALIFIED)

    rows, meta = validate_paginated(api_client.list_confidentiality_grants(
        TSO, params={"manufacturer_id": mfr["id"]}))
    assert rows == [] and meta["total_count"] == 0, "no grant row was persisted"


def test_grant_activate_revoke_conserves_disclosed_components():
    """PRD §3.3: "Each manufacturer also exposes the computed `disclosed_component_count`: the number of distinct formulation-and-component pairs its `GRANTED` or `ACTIVE` grants currently cover."
    PRD §3.3: "When the revocation is for cause and the manufacturer is `QUALIFIED`, the full **for-cause cascade** fires" — a non-cause revocation fires no cascade and leaves the manufacturer QUALIFIED.

    Design: Difficulty/compensating_invariant/grant_activate_revoke_conserves_disclosed_components
    """
    sc = fx.setup_compartmentalized_line()
    mfr3 = fx.create_qualified_manufacturer(legal_name="Gamma Co-Packers",
                                            capabilities=["LIQUID_FILL"])
    before = validate_success(api_client.get_contract_manufacturer(mfr3["id"], TSO))
    assert before["disclosed_component_count"] == 0

    g3 = fx.create_active_grant(mfr3["id"], sc["formulation"]["id"],
                                component_scope=["C1"], grant_reason="SECOND_SOURCE")
    mid = validate_success(api_client.get_contract_manufacturer(mfr3["id"], TSO))
    assert mid["disclosed_component_count"] == 1

    revoked = api_client.revoke_confidentiality_grant(g3["id"], False, CA)
    assert validate_success(revoked)["status"] == "REVOKED"

    after = validate_success(api_client.get_contract_manufacturer(mfr3["id"], TSO))
    assert after["disclosed_component_count"] == 0
    assert after["status"] == "QUALIFIED", "for_cause=false fires no cascade"

    form = validate_success(api_client.get_formulation(sc["formulation"]["id"], TSO))
    assert form["status"] == "COMPARTMENTALIZED", \
        "the original two manufacturers still cover every component"
    brand = validate_success(api_client.get_brand(sc["brand"]["id"], BM))
    assert brand["protection_posture"] == "NORMAL"


def test_grant_expiry_sweep_regresses_formulation():
    """PRD §2.4: "Confidentiality grants in `GRANTED` or `ACTIVE` move to `EXPIRED` when the current time reaches their `expires_on`."
    PRD §3.3: "an `ACTIVE` grant doing so additionally re-evaluates formulation coverage, regressing the formulation if coverage broke."

    Design: Corner/state_machines/grant_expiry_sweep_regresses_formulation
    """
    sc = fx.setup_line_with_sealed_formulation()
    form_id = sc["formulation"]["id"]
    mfr1 = fx.create_qualified_manufacturer(legal_name="Alpha Blending Co",
                                            capabilities=["BLENDING"])
    mfr2 = fx.create_qualified_manufacturer(legal_name="Beta Filling Inc",
                                            capabilities=["AEROSOL_FILL"])
    g1 = fx.create_active_grant(mfr1["id"], form_id, component_scope=["C1", "C2"])
    g2 = fx.create_active_grant(mfr2["id"], form_id, component_scope=["C3", "C4"],
                                expires_on="2026-10-01T00:00:00Z")
    assert validate_success(api_client.get_formulation(form_id, TSO))["status"] \
        == "COMPARTMENTALIZED"

    fx.advance_clock("2026-10-02T00:00:00Z")

    g2_after = validate_success(api_client.get_confidentiality_grant(g2["id"], TSO))
    assert g2_after["status"] == "EXPIRED"
    form_after = validate_success(api_client.get_formulation(form_id, TSO))
    assert form_after["status"] == "SEALED", "coverage of C3 and C4 was lost"
    g1_after = validate_success(api_client.get_confidentiality_grant(g1["id"], TSO))
    assert g1_after["status"] == "ACTIVE", "its expiry is 2027-12-31"
    mfr2_after = validate_success(api_client.get_contract_manufacturer(mfr2["id"], TSO))
    assert mfr2_after["disclosed_component_count"] == 0


def test_grant_action_after_expiry_returns_grant_expired():
    """PRD §3.3: "The grant action moves `REQUESTED` → `GRANTED`. It re-verifies that `expires_on` is still strictly after the current logical time (`ERR_GRANT_EXPIRED`, HTTP 409) and then enforces **compartmentalization**".
    PRD §2.4: "Confidentiality grants in `GRANTED` or `ACTIVE` move to `EXPIRED` when the current time reaches their `expires_on`." — a REQUESTED grant is not swept.

    Design: Corner/errors/grant_action_after_expiry_returns_grant_expired
    """
    sc = fx.setup_line_with_sealed_formulation()
    mfr = fx.create_qualified_manufacturer()
    grant = fx.create_grant_request(mfr["id"], sc["formulation"]["id"],
                                    component_scope=["C1"],
                                    expires_on="2026-10-01T00:00:00Z",
                                    grant_reason="PILOT_SUPPLY")
    fx.advance_clock("2026-10-02T00:00:00Z")

    resp = api_client.grant_confidentiality_grant(grant["id"], TSO)
    validate_error(resp, ApiErrorId.ERR_GRANT_EXPIRED)

    after = validate_success(api_client.get_confidentiality_grant(grant["id"], TSO))
    assert after["status"] == "REQUESTED", \
        "the sweep expires only GRANTED or ACTIVE grants"
