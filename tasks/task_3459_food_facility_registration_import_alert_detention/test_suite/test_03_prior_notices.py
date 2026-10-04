"""Prior notice filing, timing windows, amendment, and notice state gates
(PRD §3.3, §2.6)."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    amend_prior_notice,
    amend_prior_notice_payload,
    assert_prior_notice,
    create_entry,
    create_entry_payload,
    create_facility,
    create_importer,
    create_prior_notice,
    create_prior_notice_payload,
    get_prior_notice,
    make_importer_headers,
    refuse_inspection_entry,
    schedule_inspection,
    set_clock,
    setup_facility_and_importer,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_prior_notice_missing_arrival_eta_returns_invalid_request(api):
    """PRD §2.6: "12. **Request shape** — missing required fields, invalid enum
    values, range violations, inconsistent alert scope fields
    (`ERR_INVALID_REQUEST`, 400)."
    PRD §3.3: "its `Importer` files a prior notice carrying the full data set:
    the `importer_id` of the filing firm — which must equal the caller's
    `X-User-ID`, or the filing fails with `ERR_OWNERSHIP_VIOLATION` — the
    `facility_id` of the foreign manufacturing facility, the article's
    `product_code`, its `product_risk_class` (one of `LOW`, `STANDARD`, or
    `HIGH`), the `transport_mode` (`VESSEL`, `AIR`, `RAIL`, or `ROAD`), the
    expected `arrival_eta`, the `declared_units` (greater than 0), the
    `unit_value_cents` (zero or greater), and the `port_code` of the port of
    entry."

    Design: Corner/entities/prior_notice_missing_required_field_returns_invalid_request
    """
    fac, imp = setup_facility_and_importer(
        api=api,
        facility_overrides={
            "legal_name": "Ebro Vegetales",
            "country_code": "ES",
            "ufi": "UFI-ES-2001",
        },
        importer_overrides={
            "firm_name": "Copper State Imports",
            "account_code": "IMP-2001",
        },
    )
    payload = create_prior_notice_payload(
        importer_id=imp["id"],
        facility_id=fac["id"],
        product_code="PC-VEG-01",
        product_risk_class="STANDARD",
        transport_mode="VESSEL",
        arrival_eta="2026-09-03T00:00:00Z",
        declared_units=10,
        unit_value_cents=100,
        port_code="US-NYC",
    )
    del payload["arrival_eta"]
    resp = api.create_prior_notice(payload, make_importer_headers(imp["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(
        api.list_prior_notices(
            TEST_USERS["platform_admin_headers"], params={"importer_id": imp["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_prior_notice_invalid_enum_transport_mode_returns_invalid_request(api):
    """PRD §3.3: "the `transport_mode` (`VESSEL`, `AIR`, `RAIL`, or `ROAD`)".
    PRD §2.6: "12. **Request shape** — missing required fields, invalid enum
    values, range violations, inconsistent alert scope fields
    (`ERR_INVALID_REQUEST`, 400)."

    Design: Corner/entities/prior_notice_invalid_enum_transport_mode_returns_invalid_request
    """
    fac, imp = setup_facility_and_importer(
        api=api,
        facility_overrides={
            "legal_name": "Thai Rice Mills",
            "country_code": "TH",
            "ufi": "UFI-TH-2003",
        },
        importer_overrides={"firm_name": "Bay Area Foods", "account_code": "IMP-2003"},
    )
    resp = api.create_prior_notice(
        create_prior_notice_payload(
            importer_id=imp["id"],
            facility_id=fac["id"],
            product_code="PC-RICE-02",
            product_risk_class="STANDARD",
            transport_mode="HORSE",
            arrival_eta="2026-09-03T00:00:00Z",
            declared_units=10,
            unit_value_cents=100,
            port_code="US-OAK",
        ),
        make_importer_headers(imp["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_notice_too_early_boundary(api):
    """PRD §3.3: "The lead may not exceed 720 hours either; a farther-out
    arrival is rejected with `ERR_NOTICE_TOO_EARLY` (HTTP 422). Both boundaries
    are inclusive: a lead exactly equal to the mode minimum passes, and a lead
    of exactly 720.0 hours passes."

    Design: Corner/validations/notice_too_early_boundary
    """
    set_clock("2026-10-01T12:00:00Z", api=api)
    fac, imp = setup_facility_and_importer(
        api=api,
        facility_overrides={
            "legal_name": "Colima Mango",
            "country_code": "MX",
            "ufi": "UFI-MX-2307",
        },
        importer_overrides={"firm_name": "Tucson Produce", "account_code": "IMP-2307"},
    )
    ok_resp = api.create_prior_notice(
        create_prior_notice_payload(
            importer_id=imp["id"],
            facility_id=fac["id"],
            product_code="PC-MAN-01",
            product_risk_class="STANDARD",
            transport_mode="VESSEL",
            arrival_eta="2026-10-31T12:00:00Z",  # exactly 720h00m of lead
            declared_units=10,
            unit_value_cents=100,
            port_code="US-LAX",
        ),
        make_importer_headers(imp["id"]),
    )
    pn_ok = validate_success(ok_resp, 201)
    assert pn_ok["status"] == "CONFIRMED"
    early_resp = api.create_prior_notice(
        create_prior_notice_payload(
            importer_id=imp["id"],
            facility_id=fac["id"],
            product_code="PC-MAN-01",
            product_risk_class="STANDARD",
            transport_mode="VESSEL",
            arrival_eta="2026-10-31T12:01:00Z",  # 720h01m of lead
            declared_units=10,
            unit_value_cents=100,
            port_code="US-LAX",
        ),
        make_importer_headers(imp["id"]),
    )
    validate_error(early_resp, ApiErrorId.ERR_NOTICE_TOO_EARLY)


def test_importer_cannot_amend_another_importers_notice(api):
    """PRD §3.3: "Plans change, and a notice still in `CONFIRMED` may be
    amended by its owning importer (again `X-User-ID` must equal the notice's
    `importer_id`; a notice in any other status fails with
    `ERR_PN_NOT_CONFIRMED`, HTTP 409)."
    PRD §2.1: "A failed entity-backed ownership comparison is rejected with
    `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

    Design: Corner/validations/importer_cannot_amend_another_importers_notice
    """
    fac = create_facility(
        api=api,
        legal_name="Busan Sujebi",
        facility_kind="FOREIGN",
        country_code="KR",
        ufi="UFI-KR-2303",
    )
    imp_a = create_importer(
        api=api, firm_name="Acadia Imports", account_code="IMP-2303A"
    )
    imp_b = create_importer(
        api=api, firm_name="Big Sky Imports", account_code="IMP-2303B"
    )
    pn = create_prior_notice(
        imp_a,
        fac,
        api=api,
        product_code="PC-NOO-01",
        product_risk_class="STANDARD",
        transport_mode="VESSEL",
        arrival_eta="2026-09-03T00:00:00Z",
        declared_units=10,
        unit_value_cents=100,
        port_code="US-SEA",
    )
    resp = api.amend_prior_notice(
        pn["id"],
        amend_prior_notice_payload(arrival_eta="2026-09-03T06:00:00Z"),
        make_importer_headers(imp_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION)
    assert get_prior_notice(pn["id"], api=api)["status"] == "CONFIRMED"


def test_compromised_notice_rejects_entry_filing(api):
    """PRD §3.3: "if its facility is suspended through an inspection refusal,
    every one of the facility's still-`CONFIRMED` notices is compromised to
    `COMPROMISED` (§3.8)."
    PRD §3.3: "`SUPERSEDED`, `COMPROMISED`, and `CONSUMED` are all terminal; any
    operation that requires a `CONFIRMED` notice rejects the others with
    `ERR_PN_NOT_CONFIRMED`."

    Design: Corner/state_machines/compromised_notice_rejects_entry_filing
    """
    fac = create_facility(
        api=api,
        legal_name="Cork Meats",
        facility_kind="FOREIGN",
        country_code="IE",
        ufi="UFI-IE-2106",
    )
    imp = create_importer(
        api=api, firm_name="Finger Lakes Foods", account_code="IMP-2106"
    )
    pn = create_prior_notice(
        imp,
        fac,
        api=api,
        product_code="PC-BEF-01",
        product_risk_class="STANDARD",
        transport_mode="VESSEL",
        arrival_eta="2026-09-03T00:00:00Z",
        declared_units=20,
        unit_value_cents=700,
        port_code="US-NYC",
    )
    insp = schedule_inspection(fac["id"], api=api)
    refuse_inspection_entry(insp, fac, api=api)
    assert get_prior_notice(pn["id"], api=api)["status"] == "COMPROMISED"
    resp = api.create_entry(
        create_entry_payload(pn["id"]), make_importer_headers(imp["id"])
    )
    validate_error(resp, ApiErrorId.ERR_PN_NOT_CONFIRMED)


def test_notice_window_initial_vs_amendment(api):
    """PRD §3.3: "Amendments are judged under a relaxed timing variant: the
    minimum lead is half the transport mode's minimum, rounded up to a whole
    hour — 4 hours for `VESSEL`, 2 for `AIR`, 2 for `RAIL`, and 1 for `ROAD` —
    while the 720-hour maximum is unchanged. Consider a vessel shipment whose
    ETA is 6 hours out: an initial filing would be rejected as too late, but
    the same lead is acceptable on an amendment."
    PRD §3.3: "every field not supplied is inherited from the superseded
    notice."

    Design: Difficulty/dual_variant_calc/notice_window_initial_vs_amendment
    """
    set_clock("2026-10-01T12:00:00Z", api=api)
    fac = create_facility(
        api=api,
        legal_name="Hafen Foods GmbH",
        facility_kind="FOREIGN",
        country_code="DE",
        ufi="UFI-DE-001",
    )
    imp = create_importer(
        api=api, firm_name="Atlantic Import Co", account_code="IMP-001"
    )
    pn1 = create_prior_notice(
        imp,
        fac,
        api=api,
        product_code="PC-FISH-01",
        product_risk_class="STANDARD",
        transport_mode="VESSEL",
        arrival_eta="2026-10-11T12:00:00Z",  # 240h lead
        declared_units=100,
        unit_value_cents=500,
        port_code="US-NYC",
    )

    # Identical 6h VESSEL lead: initial filing is too late (minimum 8h)...
    late_resp = api.create_prior_notice(
        create_prior_notice_payload(
            importer_id=imp["id"],
            facility_id=fac["id"],
            product_code="PC-FISH-01",
            product_risk_class="STANDARD",
            transport_mode="VESSEL",
            arrival_eta="2026-10-01T18:00:00Z",
            declared_units=50,
            unit_value_cents=500,
            port_code="US-NYC",
        ),
        make_importer_headers(imp["id"]),
    )
    validate_error(late_resp, ApiErrorId.ERR_NOTICE_TOO_LATE)

    # ...but the same lead is acceptable on an amendment (minimum 4h).
    amend_resp = api.amend_prior_notice(
        pn1["id"],
        amend_prior_notice_payload(arrival_eta="2026-10-01T18:00:00Z"),
        make_importer_headers(imp["id"]),
    )
    pn2 = validate_success(amend_resp, 201)
    assert_prior_notice(pn2)
    assert pn2["status"] == "CONFIRMED"
    assert pn2["is_amendment"] is True
    assert pn2["parent_pn_id"] == pn1["id"]
    assert pn2["declared_units"] == 100, "unlisted field must be inherited"
    assert pn2["unit_value_cents"] == 500, "unlisted field must be inherited"
    assert pn2["port_code"] == "US-NYC", "unlisted field must be inherited"
    assert get_prior_notice(pn1["id"], api=api)["status"] == "SUPERSEDED"


def test_notice_lead_time_exact_minimum(api):
    """PRD §3.3: "A lead shorter than the applicable minimum is rejected with
    `ERR_NOTICE_TOO_LATE` (HTTP 422)."
    PRD §3.3: "Both boundaries are inclusive: a lead exactly equal to the mode
    minimum passes, and a lead of exactly 720.0 hours passes."
    PRD §2.8: "Prior-notice lead times are computed to whole minutes and
    compared at minute granularity."

    Design: Difficulty/boundary_precision_check/notice_lead_time_exact_minimum
    """
    set_clock("2026-10-01T12:00:00Z", api=api)
    fac = create_facility(
        api=api,
        legal_name="Lofoten Fiskeri",
        facility_kind="FOREIGN",
        country_code="NO",
        ufi="UFI-NO-801",
    )
    imp = create_importer(
        api=api, firm_name="Great Lakes Imports", account_code="IMP-801"
    )
    ok_resp = api.create_prior_notice(
        create_prior_notice_payload(
            importer_id=imp["id"],
            facility_id=fac["id"],
            product_code="PC-COD-01",
            product_risk_class="STANDARD",
            transport_mode="VESSEL",
            arrival_eta="2026-10-01T20:00:00Z",  # exactly 8h00m of lead
            declared_units=12,
            unit_value_cents=900,
            port_code="US-BOS",
        ),
        make_importer_headers(imp["id"]),
    )
    pn_ok = validate_success(ok_resp, 201)
    assert pn_ok["status"] == "CONFIRMED"
    late_resp = api.create_prior_notice(
        create_prior_notice_payload(
            importer_id=imp["id"],
            facility_id=fac["id"],
            product_code="PC-COD-01",
            product_risk_class="STANDARD",
            transport_mode="VESSEL",
            arrival_eta="2026-10-01T19:59:00Z",  # 7h59m of lead
            declared_units=12,
            unit_value_cents=900,
            port_code="US-BOS",
        ),
        make_importer_headers(imp["id"]),
    )
    validate_error(late_resp, ApiErrorId.ERR_NOTICE_TOO_LATE)
