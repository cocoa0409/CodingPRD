"""Error-condition coverage: the per-kind 404 codes, the authentication and
brand-scope gates, the five uniqueness keys, the ordered approval gates, the
hangtag gates, the redelivery window and the suspended-posture block.
"""
import pytest

from test_helpers import *  # noqa: F401,F403


# --- file-local helpers ---------------------------------------------------

def _raw_headers(user_id=None, role=None):
    """Header dict built by hand so a test can omit or blank a header that
    build_user_headers always supplies."""
    headers = {"Content-Type": "application/json"}
    if user_id is not None:
        headers["X-User-ID"] = user_id
    if role is not None:
        headers["X-User-Role"] = role
    return headers


def _hangtag_body(parent, **overrides):
    """A hangtag payload whose printed strings default to the parent's, so a
    test can diverge exactly one field at a time."""
    payload = hangtag_payload(parent["version"])
    payload["market_codes"] = list(parent["market_codes"])
    payload["languages"] = list(parent["languages"])
    payload["fiber_content_text"] = parent["fiber_content_text"]
    payload["origin_text"] = parent["origin_text"]
    payload.update(overrides)
    return payload


def _bundle_of(market, brand, style, determination, fiber_test, care_test):
    """The bundle shape label_payload_for consumes, for the few tests that must
    build their laboratory evidence in a hand-picked order."""
    return {
        "markets": [market],
        "market": market,
        "brand": brand,
        "style": read_style(style["id"]),
        "determination": determination,
        "fiber_test": fiber_test,
        "care_test": care_test,
    }


VN_GRAPH = [
    {"stage": "YARN", "country_code": "VN", "value_added_usd": 100.00,
     "weight_grams": 400.0},
    {"stage": "CUT_AND_SEW", "country_code": "VN", "value_added_usd": 200.00,
     "weight_grams": 500.0, "_parent": 0},
]


# =========================================================================
# every_unknown_id_returns_its_own_not_found_error
# =========================================================================

_PER_KIND_READS = [
    ("get_brand", ApiErrorId.ERR_BRAND_NOT_FOUND),
    ("get_style", ApiErrorId.ERR_STYLE_NOT_FOUND),
    ("get_material_input", ApiErrorId.ERR_MATERIAL_INPUT_NOT_FOUND),
    ("get_lab_test", ApiErrorId.ERR_LAB_TEST_NOT_FOUND),
    ("get_origin_determination", ApiErrorId.ERR_ORIGIN_DETERMINATION_NOT_FOUND),
    ("get_label_spec", ApiErrorId.ERR_LABEL_SPEC_NOT_FOUND),
    ("get_import_shipment", ApiErrorId.ERR_IMPORT_SHIPMENT_NOT_FOUND),
    ("get_compliance_audit", ApiErrorId.ERR_COMPLIANCE_AUDIT_NOT_FOUND),
    ("get_audit_finding", ApiErrorId.ERR_AUDIT_FINDING_NOT_FOUND),
]


@pytest.mark.parametrize("getter,expected_error", _PER_KIND_READS,
                         ids=[name for name, _ in _PER_KIND_READS])
def test_unresolved_path_id_raises_the_404_of_its_own_kind(api, getter, expected_error):
    """PRD 2.6: "Identifiers embedded in a URL path are resolved strictly left to right, and the first one that does not resolve to a live row decides the 404."

    Design: Corner/errors/every_unknown_id_returns_its_own_not_found_error
    """
    resp = getattr(api, getter)(NON_EXISTENT_UUID,
                               TEST_USERS["compliance_admin_headers"])
    validate_error(resp, expected_error)


def test_an_unregistered_market_code_in_the_body_raises_the_market_404(api):
    """PRD 2.6: "A market code supplied anywhere — in a style's `target_market_codes`, in a label artifact's `market_codes`, or as a shipment's `entry_market_code` — must resolve to a registered market regime; if it does not, the request is rejected with `ERR_MARKET_REQUIREMENT_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/every_unknown_id_returns_its_own_not_found_error
    """
    admin = TEST_USERS["compliance_admin_headers"]
    brand = register_brand()

    payload = style_payload(brand["id"], style_code="NL-ZZ-1",
                            target_market_codes=["ZZ"])
    resp = api.create_style(payload, admin)
    validate_error(resp, ApiErrorId.ERR_MARKET_REQUIREMENT_NOT_FOUND)

    _, meta = validate_paginated(api.list_brand_styles(brand["id"], admin))
    assert meta["total_count"] == 0, (
        "A style create refused on an unregistered market code must persist "
        f"no style row, got total_count={meta['total_count']}"
    )


# =========================================================================
# a_missing_or_unknown_role_header_is_unauthenticated_before_any_other_check
# =========================================================================

_DEFECTIVE_AUTH = [
    ("no_role_header", _raw_headers(user_id="op-compliance-admin-1")),
    # A whitespace-only value cannot be put on the wire (an HTTP header value may
    # not begin with whitespace), so the blank case is expressed as the empty
    # value, which is likewise "blank after trimming" per PRD 2.1.
    ("blank_user_id", _raw_headers(user_id="", role="ComplianceAdmin")),
    ("no_user_id_header", _raw_headers(role="ComplianceAdmin")),
    ("undeclared_role", _raw_headers(user_id="op-compliance-admin-1",
                                     role="SuperUser")),
]


@pytest.mark.parametrize("headers", [h for _, h in _DEFECTIVE_AUTH],
                         ids=[name for name, _ in _DEFECTIVE_AUTH])
def test_defective_auth_headers_are_unauthenticated_rather_than_not_found(api, headers):
    """PRD 2.1: "If either header is absent or blank after trimming, or if `X-User-Role` is not one of the seven role names defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This is the very first check the service performs, ahead of every other validation in this document."

    Design: Corner/errors/a_missing_or_unknown_role_header_is_unauthenticated_before_any_other_check
    """
    resp = api.get_brand(NON_EXISTENT_UUID, headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_authentication_answers_before_the_body_shape_and_existence_checks(api):
    """PRD 2.1: "If either header is absent or blank after trimming, or if `X-User-Role` is not one of the seven role names defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This is the very first check the service performs, ahead of every other validation in this document."

    Design: Corner/errors/a_missing_or_unknown_role_header_is_unauthenticated_before_any_other_check
    """
    payload = {
        "brand_id": NON_EXISTENT_UUID,
        "style_code": "NL-X",
        "product_class": "NOT_A_CLASS",
        "target_market_codes": [],
        "net_weight_grams": -1.0,
    }
    resp = api.create_style(payload, _raw_headers(user_id="op-1", role="SuperUser"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# =========================================================================
# a_brand_admin_cannot_touch_a_style_of_another_brand
# =========================================================================

def test_a_foreign_brand_admin_cannot_append_a_material_input(api):
    """PRD 2.1: "Concretely, for a `BrandAdmin` the brand chain must resolve to the acting brand id along all four routes the service knows: a style's `brand_id` directly, a material input's `style_id` resolved to its style's `brand_id`, a shipment's `importer_brand_id`, and an audit finding's `style_id` resolved to its style's `brand_id`."

    Design: Corner/errors/a_brand_admin_cannot_touch_a_style_of_another_brand
    """
    register_market("US")
    owner = register_brand(legal_name="Northline Apparel Co")
    intruder = register_brand(legal_name="Harborline Brands Inc", rn_number="RN67890")
    style = create_style(owner["id"], style_code="NL-4410")

    node = material_input_payload(stage="FIBER", country_code="IN",
                                  value_added_usd=2.00, weight_grams=500.0)
    refused = api.create_material_input(style["id"], node,
                                        make_brand_admin_headers(intruder["id"]))
    validate_error(refused, ApiErrorId.ERR_BRAND_SCOPE_VIOLATION)

    accepted = api.create_material_input(style["id"], node,
                                         make_brand_admin_headers(owner["id"]))
    created = validate_success(accepted, 201)
    assert created["style_id"] == style["id"], (
        "The owning BrandAdmin must be accepted on the identical append"
    )

    _, meta = validate_paginated(api.list_material_inputs(
        TEST_USERS["compliance_admin_headers"], params={"style_id": style["id"]}))
    assert meta["total_count"] == 1, (
        f"Only the owning brand's node may persist, got total_count={meta['total_count']}"
    )


def test_a_brand_admin_cannot_create_a_style_for_another_brand(api):
    """PRD 2.1: "A mismatch on any of these is rejected with `ERR_BRAND_SCOPE_VIOLATION` (HTTP 403). This scope check guards exactly six write operations: style creation, fiber-declaration replacement, material-input append, hangtag creation, import-shipment filing and import-shipment correction."

    Design: Corner/errors/a_brand_admin_cannot_touch_a_style_of_another_brand
    """
    register_market("US")
    owner = register_brand(legal_name="Northline Apparel Co")
    intruder = register_brand(legal_name="Harborline Brands Inc", rn_number="RN67890")

    payload = style_payload(owner["id"], style_code="NL-9999")
    resp = api.create_style(payload, make_brand_admin_headers(intruder["id"]))
    validate_error(resp, ApiErrorId.ERR_BRAND_SCOPE_VIOLATION)

    _, meta = validate_paginated(api.list_brand_styles(
        owner["id"], TEST_USERS["compliance_admin_headers"]))
    assert meta["total_count"] == 0, (
        "A style create refused on brand scope must persist no style row, got "
        f"total_count={meta['total_count']}"
    )


# =========================================================================
# duplicate_market_code_style_code_entry_number_reservation_and_finding_are_all_rejected
# =========================================================================

def test_a_second_market_registration_at_the_same_code_is_rejected(api):
    """PRD 2.10: "Each registered row governs one sales market, keyed by a `market_code` of 2 to 8 characters drawn from uppercase letters and the underscore — `US`, `CA`, `MX`, `EU_FR` — and unique across all rows; a second attempt at the same code is rejected with `ERR_DUPLICATE_MARKET_CODE`."

    Design: Corner/errors/duplicate_market_code_style_code_entry_number_reservation_and_finding_are_all_rejected
    """
    admin = TEST_USERS["compliance_admin_headers"]
    register_market("US", fiber_tolerance_pp=3.0, min_durability_cycles=20)

    clash = market_requirement_payload(
        market_code="US", fiber_tolerance_pp=4.0, absolute_claim_tolerance_pp=0.5,
        min_durability_cycles=30, marking_duty_rate=0.200,
        requires_identity_disclosure=False, requires_origin_statement=False)
    validate_error(api.create_market_requirement(clash, admin),
                   ApiErrorId.ERR_DUPLICATE_MARKET_CODE)

    rows, meta = validate_paginated(
        api.list_market_requirements(admin, params={"market_code": "US"}))
    assert meta["total_count"] == 1, "The refused duplicate must create no second row"
    assert rows[0]["fiber_tolerance_pp"] == pytest.approx(3.0, abs=0.01), (
        "The refused duplicate must not overwrite the registered regime"
    )
    assert rows[0]["min_durability_cycles"] == 20, (
        "The refused duplicate must not overwrite the registered regime"
    )


def test_a_repeated_style_code_within_one_brand_is_rejected(api):
    """PRD 3.2: "It names its owning party through a `brand_id` in the creation payload, carries a brand-facing `style_code` of 1 to 32 characters that must be unique within that party — a repeat is rejected with `ERR_DUPLICATE_STYLE_CODE` — and declares a `product_class` from `WOVEN_OUTERWEAR`, `KNIT_TOP`, `HOSIERY` and `HOME_TEXTILE`."

    Design: Corner/errors/duplicate_market_code_style_code_entry_number_reservation_and_finding_are_all_rejected
    """
    admin = TEST_USERS["compliance_admin_headers"]
    register_market("US")
    brand = register_brand()
    create_style(brand["id"], style_code="NL-4410")

    clash = style_payload(brand["id"], style_code="NL-4410",
                          product_class="KNIT_TOP", net_weight_grams=200.0,
                          declared_fibers=[])
    validate_error(api.create_style(clash, admin),
                   ApiErrorId.ERR_DUPLICATE_STYLE_CODE)

    _, meta = validate_paginated(api.list_brand_styles(brand["id"], admin))
    assert meta["total_count"] == 1, (
        f"The refused duplicate style must not persist, got {meta['total_count']} rows"
    )


def test_a_repeated_entry_number_across_all_entries_is_rejected(api):
    """PRD 3.8: "A customs entry is filed by a `BrandAdmin` or a `ComplianceAdmin` and names the `importer_brand_id` of the importer of record, the `style_id` the entry covers, a customs `entry_number` of 1 to 24 characters that must be unique across all entries — a repeat is rejected with `ERR_DUPLICATE_ENTRY_NUMBER` — a `quantity_units` count greater than zero, a `declared_value_usd` greater than 0.00 at 2 decimal places, and an `entry_market_code` naming the port of entry, which is what supplies the marking-duty rate later."

    Design: Corner/errors/duplicate_market_code_style_code_entry_number_reservation_and_finding_are_all_rejected
    """
    admin = TEST_USERS["compliance_admin_headers"]
    register_market("US")
    brand = register_brand()
    style_one = create_style(brand["id"], style_code="NL-4410")
    style_two = create_style(brand["id"], style_code="NL-4411")
    file_shipment(brand["id"], style_one["id"], entry_number="ENT-1001")

    clash = import_shipment_payload(brand["id"], style_two["id"],
                                    entry_number="ENT-1001", quantity_units=500,
                                    declared_value_usd=9000.00)
    validate_error(api.create_import_shipment(clash, admin),
                   ApiErrorId.ERR_DUPLICATE_ENTRY_NUMBER)

    _, meta = validate_paginated(api.list_import_shipments(admin))
    assert meta["total_count"] == 1, (
        f"The refused duplicate entry must not persist, got {meta['total_count']} rows"
    )


def test_a_second_live_reservation_of_the_same_test_type_on_one_style_is_rejected(api):
    """PRD 3.4: "Separately, a style may hold at most one reservation per test type at a time; a second one while the first is still `BENCH_RESERVED` is rejected with `ERR_TEST_ALREADY_RESERVED`."

    Design: Corner/errors/duplicate_market_code_style_code_entry_number_reservation_and_finding_are_all_rejected
    """
    register_market("US")
    brand = register_brand()
    style_one = create_style(brand["id"], style_code="NL-4410")
    style_two = create_style(brand["id"], style_code="NL-4411")
    first = reserve_care_test(style_one["id"], lab_code="LAB-ATL-1",
                              method="AATCC_135", wash_temp_c=30,
                              specimen_received_at="2026-08-03T09:00:00Z",
                              results_due_at="2026-08-05T09:00:00Z")
    assert first["state"] == "BENCH_RESERVED"

    clash = care_test_payload(style_one["id"], lab_code="LAB-BOS-2",
                              method="AATCC_135", wash_temp_c=40,
                              specimen_received_at="2026-08-20T09:00:00Z",
                              results_due_at="2026-08-22T09:00:00Z")
    validate_error(api.create_lab_test(clash, TEST_USERS["accredited_lab_headers"]),
                   ApiErrorId.ERR_TEST_ALREADY_RESERVED)

    sibling = care_test_payload(style_two["id"], lab_code="LAB-ATL-1",
                                method="AATCC_135", wash_temp_c=30,
                                specimen_received_at="2026-08-03T09:00:00Z",
                                results_due_at="2026-08-05T09:00:00Z")
    accepted = validate_success(
        api.create_lab_test(sibling, TEST_USERS["accredited_lab_headers"]), 201)
    assert accepted["style_id"] == style_two["id"], (
        "The reservation key is scoped per style, so another style may reserve "
        "the same test type"
    )


def test_a_second_live_finding_of_the_same_code_on_one_style_is_rejected(api):
    """PRD 3.9: "The same style may not carry two live findings of the same code inside one audit: a second one while an existing finding of that style and code sits in `OPEN` or `REMEDIATED` is rejected with `ERR_DUPLICATE_OPEN_FINDING`."

    Design: Corner/errors/duplicate_market_code_style_code_entry_number_reservation_and_finding_are_all_rejected
    """
    auditor = TEST_USERS["auditor_headers"]
    register_market("US")
    brand = register_brand()
    style_one = create_style(brand["id"], style_code="NL-4410")
    style_two = create_style(brand["id"], style_code="NL-4411")
    audit = open_audit(brand["id"])
    raise_finding(audit["id"], style_one["id"],
                  finding_code="CARE_UNSUBSTANTIATED", units_affected=100)

    clash = audit_finding_payload(style_one["id"],
                                  finding_code="CARE_UNSUBSTANTIATED",
                                  units_affected=250)
    validate_error(api.create_audit_finding(audit["id"], clash, auditor),
                   ApiErrorId.ERR_DUPLICATE_OPEN_FINDING)

    sibling = audit_finding_payload(style_two["id"],
                                    finding_code="CARE_UNSUBSTANTIATED",
                                    units_affected=60)
    accepted = validate_success(
        api.create_audit_finding(audit["id"], sibling, auditor), 201)
    assert accepted["style_id"] == style_two["id"], (
        "The live-finding key is scoped per style, so the same code may be "
        "raised against another style of the audit"
    )


# =========================================================================
# four_sibling_labels_each_fail_approval_on_their_own_gate
# =========================================================================

def _us_and_ca_label_ready_style():
    """A fully substantiated style targeting US and CA, whose CA regime demands
    both English and French and 25 durability cycles."""
    return setup_label_ready_style(markets=[
        {"market_code": "US"},
        {"market_code": "CA", "required_languages": ["en", "fr"],
         "absolute_claim_tolerance_pp": 0.3, "min_durability_cycles": 25},
    ])


def test_a_wash_temperature_the_care_run_never_tested_fails_approval(api):
    """PRD 3.6: "The pinned care-performance run must be a `PASSED` care-performance row of the same style whose `wash_temp_c` equals the artifact's own `wash_temp_c`; a mismatch means the printed care instruction was never wash-tested and is rejected with `ERR_CARE_NOT_SUBSTANTIATED`."

    Design: Corner/errors/four_sibling_labels_each_fail_approval_on_their_own_gate
    """
    bundle = _us_and_ca_label_ready_style()
    substantiated_temp = bundle["care_test"]["wash_temp_c"]
    printed_temp = 20 if substantiated_temp != 20 else 30
    _, label = setup_pending_permanent_label(
        bundle, label_overrides={"wash_temp_c": printed_temp})

    resp = api.approve_label_spec(label["id"], TEST_USERS["labeling_approver_headers"])
    validate_error(resp, ApiErrorId.ERR_CARE_NOT_SUBSTANTIATED)

    after = read_label(label["id"])
    assert after["state"] == "PENDING_APPROVAL", (
        f"A refused approval must leave the artifact pending, got {after['state']}"
    )
    assert after["approved_by_user_id"] is None, (
        "A refused approval must not record an approver"
    )


def test_a_not_permanent_placement_on_a_permanent_label_fails_approval(api):
    """PRD 3.6: "Step two is placement: a permanent label whose `placement_code` is `NOT_PERMANENT` is rejected with `ERR_PLACEMENT_NOT_PERMANENT`."

    Design: Corner/errors/four_sibling_labels_each_fail_approval_on_their_own_gate
    """
    bundle = _us_and_ca_label_ready_style()
    _, label = setup_pending_permanent_label(
        bundle, label_overrides={"placement_code": "NOT_PERMANENT"})

    resp = api.approve_label_spec(label["id"], TEST_USERS["labeling_approver_headers"])
    validate_error(resp, ApiErrorId.ERR_PLACEMENT_NOT_PERMANENT)

    after = read_label(label["id"])
    assert after["state"] == "PENDING_APPROVAL", (
        f"A refused approval must leave the artifact pending, got {after['state']}"
    )
    assert after["version"] == label["version"], (
        "A refused approval mutates nothing, so the version must not move"
    )


def test_a_fiber_string_that_is_not_the_canonical_one_fails_approval(api):
    """PRD 3.6: "Step three is the content match, and it compares the printed strings against the facts as they stand *at approval time* rather than as they stood when the draft was authored: the normalized `fiber_content_text` must equal the style's normalized `effective_fiber_content_text`, and the normalized `origin_text` must equal the words `MADE IN` followed by a single space and the `determined_country` of the pinned determination — read from the pinned row even if that row has since become superseded or void."

    Design: Corner/errors/four_sibling_labels_each_fail_approval_on_their_own_gate
    """
    bundle = _us_and_ca_label_ready_style()
    canonical = bundle["style"]["effective_fiber_content_text"]
    assert canonical, "The bundle style must carry a canonical printable string"
    _, label = setup_pending_permanent_label(
        bundle, label_overrides={"fiber_content_text": "60% COTTON"})
    assert normalize(label["fiber_content_text"]) != normalize(canonical), (
        "The printed string must genuinely differ from the canonical one"
    )

    resp = api.approve_label_spec(label["id"], TEST_USERS["labeling_approver_headers"])
    validate_error(resp, ApiErrorId.ERR_LABEL_CONTENT_MISMATCH)

    after = read_label(label["id"])
    assert after["state"] == "PENDING_APPROVAL", (
        f"A refused approval must leave the artifact pending, got {after['state']}"
    )


def test_a_market_whose_language_is_absent_from_the_label_fails_approval(api):
    """PRD 3.6: "Step four is language coverage: the union of `required_languages` across the regimes of the artifact's `market_codes` must be a subset of the artifact's `languages`, and a shortfall is rejected with `ERR_LANGUAGE_REQUIREMENT_UNMET`."

    Design: Corner/errors/four_sibling_labels_each_fail_approval_on_their_own_gate
    """
    bundle = _us_and_ca_label_ready_style()
    _, label = setup_pending_permanent_label(
        bundle, label_overrides={"market_codes": ["US", "CA"], "languages": ["en"]})
    assert "fr" not in label["languages"], "The label must omit the French requirement"

    resp = api.approve_label_spec(label["id"], TEST_USERS["labeling_approver_headers"])
    validate_error(resp, ApiErrorId.ERR_LANGUAGE_REQUIREMENT_UNMET)

    _, meta = validate_paginated(api.list_label_specs(
        TEST_USERS["compliance_admin_headers"],
        params={"style_id": bundle["style"]["id"], "state": "APPROVED"}))
    assert meta["total_count"] == 0, (
        f"No artifact of the style may reach APPROVED, got {meta['total_count']}"
    )


# =========================================================================
# an_rn_display_mode_on_a_brand_with_no_rn_number_fails_the_identity_gate
# =========================================================================

def test_rn_display_mode_without_a_registered_number_fails_the_identity_gate(api):
    """PRD 3.6: "For every market on the artifact whose regime sets `requires_identity_disclosure` to true, the disclosure must actually be available: if `identity_display_mode` is `RN` and the party's `rn_number` is null, or if the mode is `COMPANY_NAME` and the party's `legal_name` is blank after trimming, the approval is rejected with `ERR_IDENTITY_DISCLOSURE_MISSING`."

    Design: Corner/errors/an_rn_display_mode_on_a_brand_with_no_rn_number_fails_the_identity_gate
    """
    approver = TEST_USERS["labeling_approver_headers"]
    specialist = TEST_USERS["labeling_specialist_headers"]
    bundle = setup_label_ready_style(
        brand_overrides={"legal_name": "Harborline Brands Inc", "rn_number": None},
        style_overrides={"style_code": "NL-NORN-1"})
    assert bundle["brand"]["rn_number"] is None, (
        "rn_number is optional on brand registration, so it must read null here"
    )
    assert bundle["market"]["requires_identity_disclosure"] is True, (
        "The US regime under test must demand identity disclosure"
    )
    _, label = setup_pending_permanent_label(
        bundle, label_overrides={"identity_display_mode": "RN"})

    validate_error(api.approve_label_spec(label["id"], approver),
                   ApiErrorId.ERR_IDENTITY_DISCLOSURE_MISSING)

    validate_success(api.request_revision_label_spec(
        label["id"], "switch the identity disclosure to the legal name", approver))
    validate_success(api.update_label_spec(
        label["id"], {"identity_display_mode": "COMPANY_NAME"}, specialist))
    submit_label(label["id"])
    approved = validate_success(api.approve_label_spec(label["id"], approver))
    assert approved["state"] == "APPROVED", (
        "The identical label must approve once the disclosure is the legal name"
    )
    assert approved["identity_display_mode"] == "COMPANY_NAME", (
        "Only the display mode changed between the refusal and the approval"
    )


# =========================================================================
# care_evidence_is_valid_up_to_its_horizon_and_expired_one_second_later
# =========================================================================

def _style_with_care_horizon_binding():
    """A label-ready style whose care evidence was received on 2026-08-03 and
    whose fiber evidence was received nearly two years later, so the care run's
    730-day horizon is the binding one. Returns the bundle."""
    market = register_market("US")
    brand = register_brand()
    style = create_style(brand["id"], style_code="NL-EXP-1")
    determination = setup_issued_origin(style["id"])
    care = pass_care_test(style["id"], reserve_overrides={
        "specimen_received_at": "2026-08-03T09:00:00Z",
        "results_due_at": "2026-08-05T09:00:00Z", "wash_temp_c": 40})
    set_clock("2028-06-01T00:00:00Z")
    fiber = pass_fiber_test(style["id"], reserve_overrides={
        "specimen_received_at": "2028-06-01T09:00:00Z",
        "results_due_at": "2028-06-03T09:00:00Z"})
    return _bundle_of(market, brand, style, determination, fiber, care)


def test_a_care_horizon_is_730_days_after_the_specimen_instant(api):
    """PRD 3.4: "That horizon is derived from `specimen_received_at` and nothing else, so it never depends on the instant at which the laboratory posted the result: a fiber-content row expires one year — 365 days — after its specimen was received, and a care-performance row expires two years — 730 days — after its specimen was received."

    Design: Corner/errors/care_evidence_is_valid_up_to_its_horizon_and_expired_one_second_later
    """
    bundle = _style_with_care_horizon_binding()
    care = bundle["care_test"]
    fiber = bundle["fiber_test"]

    expected = shift_instant(care["specimen_received_at"], days=730)
    assert care["valid_until"] == expected, (
        f"A care-performance horizon must be 730 days after "
        f"{care['specimen_received_at']}, expected {expected}, "
        f"got {care['valid_until']}"
    )
    assert fiber["valid_until"] == shift_instant(fiber["specimen_received_at"],
                                                days=365), (
        "A fiber-content horizon must be 365 days after its specimen instant"
    )
    assert parse_instant(fiber["valid_until"]) > parse_instant(care["valid_until"]), (
        "The care run must be the binding evidence in this fixture"
    )


def test_care_evidence_is_valid_at_its_horizon_and_expired_one_second_later(api):
    """PRD 3.6: "The pinned care test's `valid_until` must be at or after the logical clock — evidence whose horizon is strictly in the past is rejected with `ERR_TEST_EVIDENCE_EXPIRED`, and the same applies to the validity horizon of the style's passed fiber test."

    Design: Corner/errors/care_evidence_is_valid_up_to_its_horizon_and_expired_one_second_later
    """
    approver = TEST_USERS["labeling_approver_headers"]
    bundle = _style_with_care_horizon_binding()
    horizon = bundle["care_test"]["valid_until"]
    first = draft_permanent_label(bundle)
    second = draft_permanent_label(bundle)
    submit_label(first["id"])
    submit_label(second["id"])

    set_clock(horizon)
    at_horizon = validate_success(api.approve_label_spec(first["id"], approver))
    assert at_horizon["state"] == "APPROVED", (
        f"Evidence whose horizon is exactly the clock instant {horizon} is still "
        f"valid, got state {at_horizon['state']}"
    )

    set_clock(shift_instant(horizon, seconds=1))
    validate_error(api.approve_label_spec(second["id"], approver),
                   ApiErrorId.ERR_TEST_EVIDENCE_EXPIRED)
    after = read_label(second["id"])
    assert after["state"] == "PENDING_APPROVAL", (
        "The two artifacts differ only in their identifiers, so only the clock "
        f"can explain the refusal, got state {after['state']}"
    )


# =========================================================================
# market_subset_answers_before_the_empty_declaration_gate
# =========================================================================

def _undeclared_but_otherwise_ready_style():
    """A style with an empty fiber declaration that nonetheless holds an issued
    determination and a passed care run, plus a registered but untargeted MX
    regime. Returns the bundle."""
    bundle = setup_label_ready_style(
        markets=[{"market_code": "US"},
                 {"market_code": "MX", "min_durability_cycles": 15}],
        style_overrides={"style_code": "NL-UND-1", "declared_fibers": [],
                         "target_market_codes": ["US"]},
        skip_fiber=True)
    assert bundle["style"]["declared_fibers"] == [], (
        "The declaration array may be supplied empty at style creation"
    )
    return bundle


def test_a_fiber_reservation_on_an_undeclared_style_is_refused(api):
    """PRD 3.4: "A fiber-content reservation against a style whose declaration array is empty is rejected with `ERR_FIBER_DECLARATION_EMPTY`."

    Design: Corner/errors/market_subset_answers_before_the_empty_declaration_gate
    """
    bundle = _undeclared_but_otherwise_ready_style()
    style_id = bundle["style"]["id"]

    validate_error(api.create_lab_test(fiber_test_payload(style_id), LAB),
                   ApiErrorId.ERR_FIBER_DECLARATION_EMPTY)

    care = validate_success(api.create_lab_test(
        care_test_payload(style_id, specimen_received_at="2026-08-10T09:00:00Z",
                          results_due_at="2026-08-12T09:00:00Z"), LAB), 201)
    assert care["state"] == "BENCH_RESERVED", (
        "Only the fiber-content reservation reads the declaration, so a care "
        f"reservation on the same undeclared style stands, got {care['state']}"
    )


def test_the_market_subset_gate_answers_before_the_empty_declaration_gate(api):
    """PRD 2.7: "The service therefore evaluates checks in one fixed order and returns the error of the **earliest** applicable check — never the most obvious defect, and never the last one discovered."

    Design: Corner/errors/market_subset_answers_before_the_empty_declaration_gate
    """
    bundle = _undeclared_but_otherwise_ready_style()
    payload = label_payload_for(bundle, market_codes=["MX"])

    validate_error(api.create_label_spec(payload, SPECIALIST),
                   ApiErrorId.ERR_MARKET_NOT_TARGETED)

    data, meta = validate_paginated(api.list_label_specs(ADMIN))
    assert meta["total_count"] == 0, (
        "A doubly defective draft must not be persisted"
    )


def test_drafting_against_an_undeclared_style_is_refused_until_it_is_declared(api):
    """PRD 3.6: "Drafting is refused with `ERR_FIBER_DECLARATION_EMPTY` when the style's declaration array is empty, and refused with `ERR_REFERENCE_NOT_ELIGIBLE` when a pinned reference is the wrong kind or in the wrong state per §2.6."

    Design: Corner/errors/market_subset_answers_before_the_empty_declaration_gate
    """
    bundle = _undeclared_but_otherwise_ready_style()
    payload = label_payload_for(bundle, market_codes=["US"])

    validate_error(api.create_label_spec(payload, SPECIALIST),
                   ApiErrorId.ERR_FIBER_DECLARATION_EMPTY)

    replace_declaration(bundle["style"]["id"], DEFAULT_FIBERS)
    bundle["style"] = read_style(bundle["style"]["id"])
    accepted = validate_success(api.create_label_spec(
        label_payload_for(bundle, market_codes=["US"]), SPECIALIST), 201)
    assert accepted["state"] == "DRAFT", (
        "The identical draft must be accepted once the style is declared, got "
        f"state {accepted['state']}"
    )
    assert accepted["fiber_content_text"] == DEFAULT_FIBER_TEXT, (
        "The accepted draft prints the declaration that was just supplied"
    )


# =========================================================================
# an_unsupported_claim_answers_before_the_hangtag_text_comparison
# =========================================================================

def _vn_parent_label():
    """A DRAFT permanent label whose determination resolves to VN and whose
    pinned care run shrank by exactly 2.0 percent. Returns the parent row."""
    bundle = setup_label_ready_style(
        graph=VN_GRAPH, style_overrides={"style_code": "NL-VN-1"},
        care_results={"dimensional_change_pct": 2.0})
    assert bundle["determination"]["determined_country"] == "VN", (
        "A wholly Vietnamese supply graph must determine VN"
    )
    parent = draft_permanent_label(bundle)
    assert parent["origin_text"] == "Made in VN", (
        f"The parent prints its own determined country, got {parent['origin_text']}"
    )
    return read_label(parent["id"])


def test_a_made_in_usa_claim_on_a_vietnamese_parent_is_unsupported(api):
    """PRD 3.7: "`MADE_IN_USA` is supported only when the parent's normalized `origin_text` is exactly the string `MADE IN US`."

    Design: Corner/errors/an_unsupported_claim_answers_before_the_hangtag_text_comparison
    """
    parent = _vn_parent_label()
    body = _hangtag_body(parent, marketing_claims=["MADE_IN_USA"])

    validate_error(api.create_hangtag(parent["id"], body, SPECIALIST),
                   ApiErrorId.ERR_HANGTAG_CLAIM_UNSUPPORTED)


def test_a_hangtag_whose_fiber_string_diverges_is_inconsistent(api):
    """PRD 3.7: "A divergence on either string makes the artifact inconsistent, and the operation is rejected with `ERR_HANGTAG_INCONSISTENT` — both when the hangtag is created and again when it is approved."

    Design: Corner/errors/an_unsupported_claim_answers_before_the_hangtag_text_comparison
    """
    parent = _vn_parent_label()
    body = _hangtag_body(parent, marketing_claims=[],
                         fiber_content_text="100.0% COTTON")

    validate_error(api.create_hangtag(parent["id"], body, SPECIALIST),
                   ApiErrorId.ERR_HANGTAG_INCONSISTENT)


def test_a_doubly_defective_hangtag_reports_the_unsupported_claim(api):
    """PRD 3.7: "An unsupported claim is rejected with `ERR_HANGTAG_CLAIM_UNSUPPORTED`, on hangtag creation and on approval alike — and because claim support sits above text consistency on the ladder of §2.7, a hangtag that is wrong in both respects reports the unsupported claim rather than the text divergence."

    Design: Corner/errors/an_unsupported_claim_answers_before_the_hangtag_text_comparison
    """
    parent = _vn_parent_label()
    body = _hangtag_body(parent, marketing_claims=["MADE_IN_USA"],
                         fiber_content_text="100.0% COTTON",
                         origin_text="Made in US")

    validate_error(api.create_hangtag(parent["id"], body, SPECIALIST),
                   ApiErrorId.ERR_HANGTAG_CLAIM_UNSUPPORTED)

    after = read_label(parent["id"])
    assert after["version"] == parent["version"], (
        "A refused hangtag create must not bump the parent's version, expected "
        f"{parent['version']}, got {after['version']}"
    )
    data, meta = validate_paginated(api.list_label_specs(
        ADMIN, params={"parent_label_spec_id": parent["id"]}))
    assert meta["total_count"] == 0, (
        "No hangtag row may survive a refused create"
    )


def test_a_wrinkle_free_claim_at_exactly_two_percent_shrinkage_is_supported(api):
    """PRD 3.7: "`WRINKLE_FREE` is supported only when the care-performance run the parent pinned is in state `PASSED` and its `dimensional_change_pct` is at most 2.0 percent."

    Design: Corner/errors/an_unsupported_claim_answers_before_the_hangtag_text_comparison
    """
    parent = _vn_parent_label()
    body = _hangtag_body(parent, marketing_claims=["WRINKLE_FREE"])

    hangtag = validate_success(api.create_hangtag(parent["id"], body, SPECIALIST), 201)
    assert hangtag["consistency_state"] == "CONSISTENT", (
        "A shrinkage of exactly 2.0 percent supports WRINKLE_FREE, so the "
        f"hangtag must read CONSISTENT, got {hangtag['consistency_state']}"
    )
    assert hangtag["marketing_claims"] == ["WRINKLE_FREE"], (
        "The claim under test must survive on the created hangtag"
    )


# =========================================================================
# a_correction_filed_one_second_past_the_redelivery_deadline_is_refused
# =========================================================================

def _deficient_entry_with_a_published_corrective_label():
    """One entry driven through a deficient marking review, plus a PUBLISHED
    permanent label of the same style to correct against. Returns
    (corrective_label, reviewed_entry)."""
    bundle, label = setup_published_permanent_label(
        style_overrides={"style_code": "NL-RD-1"})
    entry = file_shipment(bundle["brand"]["id"], bundle["style"]["id"])
    return label, review_shipment(entry["id"])


def test_the_redelivery_deadline_is_thirty_days_after_the_review(api):
    """PRD 3.8: "The row also derives `redelivery_deadline_at` as `review_decided_at` plus a redelivery window of 30 days."

    Design: Corner/errors/a_correction_filed_one_second_past_the_redelivery_deadline_is_refused
    """
    label, entry = _deficient_entry_with_a_published_corrective_label()
    expected = shift_instant(entry["review_decided_at"], days=30)
    assert entry["redelivery_deadline_at"] == expected, (
        f"A review decided at {entry['review_decided_at']} must set a deadline of "
        f"{expected}, got {entry['redelivery_deadline_at']}"
    )

    set_clock(entry["redelivery_deadline_at"])
    corrected = validate_success(api.correct_import_shipment(
        entry["id"], {"corrective_label_spec_id": label["id"],
                      "corrected_units": entry["quantity_units"]}, ADMIN))
    assert corrected["marking_state"] == "MARKING_CORRECTED", (
        "A correction filed at exactly the deadline is still inside the window, "
        f"got state {corrected['marking_state']}"
    )
    assert corrected["corrected_units"] == entry["quantity_units"], (
        "The whole entry was re-marked, so corrected_units must equal the entry "
        "quantity"
    )


def test_a_correction_one_second_past_the_deadline_is_refused(api):
    """PRD 3.8: "The logical clock must be at or before `redelivery_deadline_at`; a correction filed after that instant has passed is rejected with `ERR_REDELIVERY_WINDOW_EXPIRED`."

    Design: Corner/errors/a_correction_filed_one_second_past_the_redelivery_deadline_is_refused
    """
    label, entry = _deficient_entry_with_a_published_corrective_label()

    set_clock(shift_instant(entry["redelivery_deadline_at"], seconds=1))
    validate_error(api.correct_import_shipment(
        entry["id"], {"corrective_label_spec_id": label["id"],
                      "corrected_units": entry["quantity_units"]}, ADMIN),
        ApiErrorId.ERR_REDELIVERY_WINDOW_EXPIRED)

    after = validate_success(api.get_import_shipment(entry["id"], ADMIN))
    assert after["marking_state"] == "REDELIVERY_ORDERED", (
        "A refused correction leaves the entry awaiting redelivery, got state "
        f"{after['marking_state']}"
    )
    assert after["corrected_units"] == 0, (
        "A refused correction records no re-marked units"
    )
    assert after["corrective_label_spec_id"] is None, (
        "A refused correction pins no corrective label"
    )


# =========================================================================
# a_suspended_posture_blocks_both_approval_and_publication_until_the_penalty
# _is_mitigated
# =========================================================================

def _suspended_brand_with_three_artifacts():
    """One brand carrying three artifacts authored while its posture was OPEN —
    a published US label, an approved MX label and a pending US label — and then
    driven to SUSPENDED by a single large assessment. Returns a dict."""
    bundle = setup_label_ready_style(
        markets=[{"market_code": "US", "marking_duty_rate": 0.500},
                 {"market_code": "MX", "min_durability_cycles": 15}],
        style_overrides={"style_code": "NL-SUS-1"})
    brand_id = bundle["brand"]["id"]
    bundle, published = setup_published_permanent_label(
        bundle=bundle, label_overrides={"market_codes": ["US"]})
    bundle, approved = setup_approved_permanent_label(
        bundle=bundle, label_overrides={"market_codes": ["MX"]})
    bundle, pending = setup_pending_permanent_label(
        bundle=bundle, label_overrides={"market_codes": ["US"]})

    entry = assess_penalty_of(brand_id, bundle["style"]["id"], 25_000.01,
                              quantity_units=100_000)
    brand = read_brand(brand_id)
    assert brand["outstanding_penalty_usd"] == pytest.approx(25_000.01, abs=0.01), (
        f"The ledger must read 25000.01, got {brand['outstanding_penalty_usd']}"
    )
    assert brand["posture"] == "SUSPENDED", (
        "A ledger strictly greater than USD 25,000.00 suspends the party, got "
        f"{brand['posture']}"
    )
    return {"brand": brand, "entry": entry, "published": published,
            "approved": approved, "pending": pending}


def test_a_suspended_posture_blocks_publication_of_an_approved_artifact(api):
    """PRD 3.6: "The brand of record's posture must not be `SUSPENDED`; note that a `RESTRICTED` posture blocks approval but still permits publication of an already approved artifact."

    Design: Corner/errors/a_suspended_posture_blocks_both_approval_and_publication_until_the_penalty_is_mitigated
    """
    state = _suspended_brand_with_three_artifacts()
    approved = state["approved"]

    validate_error(api.publish_label_spec(
        approved["id"], "2026-09-01T00:00:00Z", "2026-12-01T00:00:00Z", APPROVER),
        ApiErrorId.ERR_BRAND_POSTURE_SUSPENDED)

    after = read_label(approved["id"])
    assert after["state"] == "APPROVED", (
        f"The refused artifact stays approved, got state {after['state']}"
    )
    assert after["effective_from"] is None and after["effective_to"] is None, (
        "A refused publication stores no effective window"
    )


def test_a_suspended_posture_blocks_approval_of_a_pending_artifact(api):
    """PRD 3.6: "And the posture of the brand of record must be neither `SUSPENDED`, which is rejected with `ERR_BRAND_POSTURE_SUSPENDED`, nor `RESTRICTED`, which is rejected with `ERR_BRAND_POSTURE_RESTRICTED`; both sit near the very bottom of the ladder, with the suspension check evaluated before the restriction check."

    Design: Corner/errors/a_suspended_posture_blocks_both_approval_and_publication_until_the_penalty_is_mitigated
    """
    state = _suspended_brand_with_three_artifacts()
    pending = state["pending"]

    validate_error(api.approve_label_spec(pending["id"], APPROVER),
                   ApiErrorId.ERR_BRAND_POSTURE_SUSPENDED)

    after = read_label(pending["id"])
    assert after["state"] == "PENDING_APPROVAL", (
        f"The refused artifact stays pending, got state {after['state']}"
    )
    assert after["approved_by_user_id"] is None, (
        "A refused approval records no approver"
    )


def test_mitigating_the_penalty_reopens_approval_and_publication(api):
    """PRD 3.8: "On success the entry moves to the terminal state `MARKING_CORRECTED`, stores `corrective_label_spec_id` and `corrected_units`, and the brand-of-record's `outstanding_penalty_usd` is recomputed — dropping by the mitigated amount — followed by its `posture`, which may fall back from `SUSPENDED`."

    Design: Corner/errors/a_suspended_posture_blocks_both_approval_and_publication_until_the_penalty_is_mitigated
    """
    state = _suspended_brand_with_three_artifacts()
    entry = state["entry"]

    corrected = validate_success(api.correct_import_shipment(
        entry["id"], {"corrective_label_spec_id": state["published"]["id"],
                      "corrected_units": entry["quantity_units"]}, ADMIN))
    assert corrected["marking_state"] == "MARKING_CORRECTED", (
        f"A complete, prompt correction must land, got {corrected['marking_state']}"
    )
    brand = read_brand(state["brand"]["id"])
    assert brand["outstanding_penalty_usd"] == pytest.approx(0.00, abs=0.01), (
        "A complete and prompt correction mitigates the whole assessment, so the "
        f"ledger must fall to 0.00, got {brand['outstanding_penalty_usd']}"
    )
    assert brand["posture"] == "OPEN", (
        f"An empty ledger returns the party to OPEN, got {brand['posture']}"
    )

    reapproved = validate_success(api.approve_label_spec(
        state["pending"]["id"], APPROVER))
    assert reapproved["state"] == "APPROVED", (
        "The very approval refused under suspension must now land"
    )
    republished = validate_success(api.publish_label_spec(
        state["approved"]["id"], "2027-01-01T00:00:00Z", "2027-04-01T00:00:00Z",
        APPROVER))
    assert republished["state"] == "PUBLISHED", (
        "The very publication refused under suspension must now land"
    )
