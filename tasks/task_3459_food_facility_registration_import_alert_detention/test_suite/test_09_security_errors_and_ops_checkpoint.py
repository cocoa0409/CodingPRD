"""Authentication/authorization surface, entity-specific 404s, derived-field
reconciliation, the registration gate, and the atomic ops checkpoint
(PRD §2.1, §2.9, §2.4, §3.1)."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    build_user_headers,
    classify_recall_payload,
    complete_inspection_payload,
    create_alert_petition_payload,
    create_entry,
    create_entry_payload,
    create_facility,
    create_facility_payload,
    create_import_alert_payload,
    create_importer,
    create_notice_and_entry,
    create_prior_notice,
    create_prior_notice_payload,
    get_entry,
    get_facility,
    get_prior_notice,
    make_facility_owner_headers,
    make_importer_headers,
    place_import_alert,
    record_sample_payload,
    record_sample_result_payload,
    refuse_entry,
    release_detained_entry,
    screen_entry,
    set_clock,
    setup_entry_detained_by_alert,
    submit_evidence_payload,
    validate_error,
    validate_paginated,
)


def test_request_with_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role other
    than these seven, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/request_with_unknown_role_returns_unauthenticated
    """
    resp = api.create_facility(
        create_facility_payload(
            legal_name="Ghost Co",
            facility_kind="DOMESTIC",
            country_code="US",
            ufi="UFI-US-2301",
        ),
        build_user_headers("ghost-1", "WarehouseBoss"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_facility_owner_cannot_create_import_alert(api):
    """PRD §2.1: "A well-formed caller whose role is not among an operation's
    authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403)".
    PRD §4: placing an import alert is authorized for `ComplianceOfficer` only.

    Design: Corner/rbac/facility_owner_cannot_create_import_alert
    """
    fac = create_facility(
        api=api,
        legal_name="Hanoi Robusta",
        facility_kind="FOREIGN",
        country_code="VN",
        ufi="UFI-VN-2501",
    )
    resp = api.create_import_alert(
        create_import_alert_payload(
            scope_type="COUNTRY_PRODUCT",
            country_code="VN",
            product_code="PC-COF-01",
            reason="Ochratoxin",
        ),
        make_facility_owner_headers(fac["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    rows, meta = validate_paginated(
        api.list_import_alerts(TEST_USERS["platform_admin_headers"])
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_platform_admin_cannot_register_facility(api):
    """PRD §3.1: "A food facility enters the system when a `FacilityOwner`
    principal registers it".
    PRD §2.1: "A well-formed caller whose role is not among an operation's
    authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403)".

    Design: Corner/rbac/platform_admin_cannot_register_facility
    """
    resp = api.create_facility(
        create_facility_payload(
            legal_name="Admin Snek",
            facility_kind="DOMESTIC",
            country_code="US",
            ufi="UFI-US-2502",
        ),
        TEST_USERS["platform_admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_unknown_ids_return_entity_specific_not_found(api):
    """PRD §2.9: "the system validates identifiers in a strict left-to-right
    order as they appear in the path, and rejects the request with the `404`
    error corresponding to the *first* identifier that does not resolve:
    `ERR_FACILITY_NOT_FOUND` for a Facility, `ERR_IMPORTER_NOT_FOUND` for an
    ImporterFirm, `ERR_PRIOR_NOTICE_NOT_FOUND` for a PriorNotice,
    `ERR_ENTRY_NOT_FOUND` for an ImportEntry, `ERR_SAMPLE_NOT_FOUND` for a
    SampleAnalysis, `ERR_IMPORT_ALERT_NOT_FOUND` for an ImportAlert,
    `ERR_ALERT_PETITION_NOT_FOUND` for an AlertPetition, `ERR_INSPECTION_NOT_FOUND`
    for an Inspection, and `ERR_RECALL_NOT_FOUND` for a Recall."
    PRD §2.9: "when a request body references a laboratory by its business code,
    that `lab_code` must name an existing Laboratory, or the request fails with
    `ERR_LAB_NOT_FOUND`."

    Design: Corner/errors/unknown_ids_return_entity_specific_not_found
    """
    fac = create_facility(
        api=api,
        legal_name="Tasmania Honey",
        facility_kind="FOREIGN",
        country_code="AU",
        ufi="UFI-AU-2401",
    )
    imp = create_importer(
        api=api, firm_name="Treasure Valley Foods", account_code="IMP-2401"
    )
    _, entry = create_notice_and_entry(
        imp,
        fac,
        api=api,
        product_code="PC-HON-01",
        product_risk_class="HIGH",
        transport_mode="VESSEL",
        arrival_eta="2026-09-03T00:00:00Z",
        declared_units=5,
        unit_value_cents=100,
        port_code="US-SEA",
    )
    screen_entry(entry, api=api)  # HIGH on a clean facility -> SAMPLE

    # Body-referenced importer that does not resolve (caller identity matches
    # the referenced importer, so the ownership check passes and existence is
    # the failing category).
    missing_importer = "00000000-0000-4000-8000-000000000001"
    resp = api.create_prior_notice(
        create_prior_notice_payload(
            importer_id=missing_importer,
            facility_id=fac["id"],
            product_code="PC-HON-02",
            product_risk_class="LOW",
            transport_mode="VESSEL",
            arrival_eta="2026-09-03T00:00:00Z",
            declared_units=5,
            unit_value_cents=100,
            port_code="US-SEA",
        ),
        make_importer_headers(missing_importer),
    )
    validate_error(resp, ApiErrorId.ERR_IMPORTER_NOT_FOUND)

    resp = api.create_entry(
        create_entry_payload("00000000-0000-4000-8000-000000000002"),
        make_importer_headers(imp["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRIOR_NOTICE_NOT_FOUND)

    resp = api.record_sample_result(
        "00000000-0000-4000-8000-000000000003",
        record_sample_result_payload("COMPLIANT"),
        TEST_USERS["entry_reviewer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SAMPLE_NOT_FOUND)

    resp = api.submit_petition_evidence(
        "00000000-0000-4000-8000-000000000004",
        submit_evidence_payload(["doc-z"]),
        make_facility_owner_headers(fac["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ALERT_PETITION_NOT_FOUND)

    resp = api.create_alert_petition(
        "00000000-0000-4000-8000-000000000005",
        create_alert_petition_payload(
            expected_import_alert_version=fac["version"], evidence_links=[]
        ),
        make_facility_owner_headers(fac["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_IMPORT_ALERT_NOT_FOUND)

    resp = api.complete_inspection(
        "00000000-0000-4000-8000-000000000006",
        complete_inspection_payload(0),
        TEST_USERS["field_inspector_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_FOUND)

    resp = api.classify_recall(
        "00000000-0000-4000-8000-000000000007",
        classify_recall_payload("CLASS_II"),
        TEST_USERS["recall_coordinator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_RECALL_NOT_FOUND)

    resp = api.record_sample(
        entry["id"],
        record_sample_payload("LAB-NOPE", 1, "2026-09-02"),
        TEST_USERS["entry_reviewer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_LAB_NOT_FOUND)

    resp = api.get_entry(
        "00000000-0000-4000-8000-000000000009", TEST_USERS["platform_admin_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_FOUND)


def test_open_detention_count_reconciles_across_detain_release_refuse(api):
    """PRD §3.6: "`units_held` is set to the full `declared_units`, and the
    facility's `open_detention_count` increases by 1."
    PRD §3.6: refusal "moves all held units into `units_refused`, zeroes
    `units_held`, decrements `open_detention_count`, increments the facility's
    `violation_count` by 1" while release "moves all held units into
    `units_released`, zeroes `units_held`, decrements
    `open_detention_count`".

    Design: Corner/cross_cutting_layers/open_detention_count_reconciles_across_detain_release_refuse
    """
    fac = create_facility(
        api=api,
        legal_name="Riga Rupjmaize",
        facility_kind="FOREIGN",
        country_code="LV",
        ufi="UFI-LV-2703",
    )
    imp = create_importer(
        api=api, firm_name="Piedmont Traders", account_code="IMP-2703"
    )
    _, ent_1 = create_notice_and_entry(
        imp, fac, api=api, product_code="PC-BRD-01", product_risk_class="LOW",
        declared_units=5, unit_value_cents=100, port_code="US-BAL",
    )
    _, ent_2 = create_notice_and_entry(
        imp, fac, api=api, product_code="PC-BRD-02", product_risk_class="LOW",
        declared_units=5, unit_value_cents=100, port_code="US-BAL",
    )
    place_import_alert(
        api=api, scope_type="FIRM", facility_id=fac["id"], reason="Filth"
    )
    f = get_facility(fac["id"], api=api)
    assert f["open_detention_count"] == 2, "both entries detained by the cascade"

    release_detained_entry(get_entry(ent_1["id"], api=api), api=api)
    f = get_facility(fac["id"], api=api)
    assert f["open_detention_count"] == 1
    assert f["violation_count"] == 0, "release is not a violation"

    refuse_entry(get_entry(ent_2["id"], api=api), api=api)
    f = get_facility(fac["id"], api=api)
    assert f["open_detention_count"] == 0
    assert f["violation_count"] == 1


def test_expired_facility_blocks_entry_filing(api):
    """PRD §3.1: "Filing a prior notice and creating an import entry both
    require the manufacturing facility to be `REGISTERED`; an `EXPIRED` or
    `SUSPENDED` facility causes the filing to fail with
    `ERR_REGISTRATION_NOT_ACTIVE` (HTTP 422)."

    Design: Corner/validations/expired_facility_blocks_entry_filing
    """
    fac = create_facility(
        api=api,
        legal_name="Kerala Spices",
        facility_kind="FOREIGN",
        country_code="IN",
        ufi="UFI-IN-2306",
    )
    imp = create_importer(api=api, firm_name="Palouse Traders", account_code="IMP-2306")
    pn = create_prior_notice(
        imp,
        fac,
        api=api,
        product_code="PC-SPC-01",
        product_risk_class="STANDARD",
        transport_mode="VESSEL",
        arrival_eta="2026-09-03T00:00:00Z",
        declared_units=14,
        unit_value_cents=150,
        port_code="US-NYC",
    )
    # The biennial expiry sweep flips the facility; the notice stays CONFIRMED.
    set_clock("2028-09-01T00:00:00Z", api=api)
    assert get_facility(fac["id"], api=api)["registration_status"] == "EXPIRED"
    resp = api.create_entry(
        create_entry_payload(pn["id"]), make_importer_headers(imp["id"])
    )
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_ACTIVE)
    assert get_prior_notice(pn["id"], api=api)["status"] == "CONFIRMED"


def test_sweep_response_lists_expired_and_auto_refused_ids_immediately(api):
    """PRD §2.4: "The response echoes the new `current_utc` together with
    `expired_facility_ids` and `auto_refused_entry_ids`, the two lists produced
    by the checkpoint below."
    PRD §2.4: "Advancing the clock atomically runs the **ops checkpoint**".

    Design: Corner/consistency_model/sweep_response_lists_expired_and_auto_refused_ids_immediately
    """
    ctx = setup_entry_detained_by_alert(
        api=api,
        facility_overrides={
            "legal_name": "Malmo Kottbullar",
            "country_code": "SE",
            "ufi": "UFI-SE-2801",
        },
        importer_overrides={
            "firm_name": "Redwood Imports",
            "account_code": "IMP-2801",
        },
        notice_overrides={
            "product_code": "PC-MEAT-02",
            "product_risk_class": "LOW",
            "declared_units": 4,
            "unit_value_cents": 100,
            "port_code": "US-OAK",
        },
        alert_reason="Residues",
    )
    # One clock advance trips both sweeps: facility expiry (2028-08-31 <
    # 2028-10-01) and the detention deadline + 24h grace (2026-09-12 <
    # 2028-10-01).
    sweep = set_clock("2028-10-01T00:00:00Z", api=api)
    assert ctx["facility"]["id"] in sweep["expired_facility_ids"]
    assert ctx["entry"]["id"] in sweep["auto_refused_entry_ids"]

    # Follow-up reads agree immediately — no reconciliation lag.
    f = get_facility(ctx["facility"]["id"], api=api)
    assert f["registration_status"] == "EXPIRED"
    e = get_entry(ctx["entry"]["id"], api=api)
    assert e["disposition_status"] == "REFUSED"
    assert e["units_refused"] == 4
    assert e["units_held"] == 0
