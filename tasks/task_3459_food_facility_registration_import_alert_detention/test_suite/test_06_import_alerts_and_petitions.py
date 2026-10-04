"""Import alerts, petition filing/adjudication, compliance streaks, and the
alert-lift release cascade (PRD §3.7, §2.7)."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    adjudicate_petition,
    adjudicate_petition_payload,
    build_compliant_streak,
    create_alert_petition_payload,
    create_facility,
    create_importer,
    create_laboratory,
    create_notice_and_entry,
    create_recall,
    file_petition,
    find_petition,
    get_entry,
    get_facility,
    get_import_alert,
    list_alert_petition_rows,
    make_compliance_officer_headers,
    make_facility_owner_headers,
    place_import_alert,
    refuse_entry,
    refuse_high_entry_via_violative_sample,
    release_detained_entry,
    release_low_entry,
    screen_entry,
    set_clock,
    setup_alert_with_compliant_streak,
    setup_lifted_alert,
    validate_error,
    validate_paginated,
)


def test_adjudicate_on_denied_petition_returns_petition_not_reviewable(api):
    """PRD §3.7: "Once the petition leaves `EVIDENCE_REVIEW`, both evidence
    submission and adjudication fail with `ERR_PETITION_NOT_REVIEWABLE`
    (HTTP 409)."
    PRD §3.7: "On denial, the petition becomes `DENIED` with its streak stored,
    and the alert remains `ACTIVE`."

    Design: Corner/state_machines/adjudicate_on_denied_petition_returns_petition_not_reviewable
    """
    fac = create_facility(
        api=api,
        legal_name="Wien Backwaren",
        facility_kind="FOREIGN",
        country_code="AT",
        ufi="UFI-AT-2103",
    )
    alert = place_import_alert(
        api=api,
        scope_type="FIRM",
        facility_id=fac["id"],
        reason="Mycotoxins",
    )
    pet = file_petition(alert, fac, evidence_links=["doc-1"], api=api)
    denied = adjudicate_petition(pet, "DENY", api=api)
    assert denied["status"] == "DENIED"

    resp = api.adjudicate_petition(
        pet["id"],
        adjudicate_petition_payload("DENY"),
        TEST_USERS["compliance_officer_two_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PETITION_NOT_REVIEWABLE)
    assert find_petition(alert["id"], pet["id"], api=api)["status"] == "DENIED"
    assert get_import_alert(alert["id"], api=api)["status"] == "ACTIVE"


def test_alert_petition_recall_initial_states(api):
    """PRD §3.7: "An alert is created `ACTIVE`" and "The petition is created in
    `EVIDENCE_REVIEW` status".
    PRD §3.9: "The recall is created `INITIATED` with `classification` `NONE`".

    Design: Corner/state_machines/alert_petition_recall_initial_states
    """
    fac = create_facility(
        api=api,
        legal_name="Prahova Fructe",
        facility_kind="FOREIGN",
        country_code="RO",
        ufi="UFI-RO-2107",
    )
    alert = place_import_alert(
        api=api, scope_type="FIRM", facility_id=fac["id"], reason="Filth"
    )
    assert alert["status"] == "ACTIVE"
    pet = file_petition(alert, fac, evidence_links=[], api=api)
    assert pet["status"] == "EVIDENCE_REVIEW"
    rec = create_recall(
        fac, api=api, product_code="PC-FRT-01", quantity_distributed=300
    )
    assert rec["status"] == "INITIATED"
    assert rec["classification"] == "NONE"


def test_petition_scope_mismatch_rejected(api):
    """PRD §3.7: "The filer must lie inside the alert's scope: for a `FIRM`
    alert, the caller's `X-User-ID` must equal the alert's `facility_id`; for a
    `COUNTRY_PRODUCT` alert, the filing facility's `country_code` must equal
    the alert's `country_code` *and* the filer must have at least one prior
    notice or import entry bearing the alert's `product_code`. A filer outside
    the scope is rejected with `ERR_ALERT_SCOPE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/petition_scope_mismatch_rejected
    """
    fac_a = create_facility(
        api=api,
        legal_name="Osaka Kombu",
        facility_kind="FOREIGN",
        country_code="JP",
        ufi="UFI-JP-2309",
    )
    fac_b = create_facility(
        api=api,
        legal_name="Nagano Miso",
        facility_kind="FOREIGN",
        country_code="JP",
        ufi="UFI-JP-2310",
    )
    alert = place_import_alert(
        api=api,
        scope_type="FIRM",
        facility_id=fac_a["id"],
        reason="Undeclared allergen",
    )
    resp = api.create_alert_petition(
        alert["id"],
        create_alert_petition_payload(
            expected_import_alert_version=alert["version"],
            evidence_links=["doc-x"],
        ),
        make_facility_owner_headers(fac_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ALERT_SCOPE_MISMATCH)
    assert list_alert_petition_rows(alert["id"], api=api) == []
    assert get_import_alert(alert["id"], api=api)["version"] == alert["version"]


def test_alert_creator_cannot_adjudicate_own_alert(api):
    """PRD §3.7: "the adjudicator's `X-User-ID` must differ from the alert's
    `created_by_user_id`, or the adjudication fails with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — the officer who placed the alert
    may never judge the petition against it."
    PRD §2.6 places segregation of duties (category 9) ahead of petition
    approval sufficiency (category 11).

    Design: Corner/validations/alert_creator_cannot_adjudicate_own_alert
    """
    fac = create_facility(
        api=api,
        legal_name="Limerick Dairies",
        facility_kind="FOREIGN",
        country_code="IE",
        ufi="UFI-IE-2311",
    )
    alert = place_import_alert(
        api=api,
        creator_headers=TEST_USERS["compliance_officer_headers"],  # co-1
        scope_type="FIRM",
        facility_id=fac["id"],
        reason="Antibiotics",
    )
    pet = file_petition(alert, fac, evidence_links=["doc-y"], api=api)

    # The creator may not adjudicate — even though the streak here is 0, the
    # segregation-of-duties failure is the one reported.
    resp = api.adjudicate_petition(
        pet["id"],
        adjudicate_petition_payload("APPROVE"),
        TEST_USERS["compliance_officer_headers"],  # co-1, the creator
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    # A different officer may adjudicate the same petition.
    denied = adjudicate_petition(
        pet, "DENY", api=api, officer_headers=TEST_USERS["compliance_officer_two_headers"]
    )
    assert denied["status"] == "DENIED"


def test_country_product_alert_cascade_matches_scope(api):
    """PRD §3.7: "Every import entry matching the alert's scope whose
    disposition is still `PENDING` — whatever its `review_status` — is detained
    without physical examination: for a `FIRM` alert, entries whose
    `facility_id` equals the alert's `facility_id`; for a `COUNTRY_PRODUCT`
    alert, entries whose facility's `country_code` equals the alert's
    `country_code` and whose own `product_code` equals the alert's
    `product_code`."

    Design: Corner/endpoints/country_product_alert_cascade_matches_scope
    """
    fac_de1 = create_facility(
        api=api, legal_name="Koln Senf", country_code="DE", ufi="UFI-DE-2601"
    )
    fac_de2 = create_facility(
        api=api, legal_name="Aachen Printen", country_code="DE", ufi="UFI-DE-2602"
    )
    fac_fr1 = create_facility(
        api=api, legal_name="Lyon Moutarde", country_code="FR", ufi="UFI-FR-2603"
    )
    imp = create_importer(api=api, firm_name="Ozark Imports", account_code="IMP-2601")
    _, ent_1 = create_notice_and_entry(
        imp, fac_de1, api=api, product_code="PC-A", product_risk_class="LOW",
        declared_units=5, unit_value_cents=100,
    )
    _, ent_2 = create_notice_and_entry(
        imp, fac_de2, api=api, product_code="PC-B", product_risk_class="LOW",
        declared_units=5, unit_value_cents=100,
    )
    _, ent_3 = create_notice_and_entry(
        imp, fac_fr1, api=api, product_code="PC-A", product_risk_class="LOW",
        declared_units=5, unit_value_cents=100,
    )

    alert = place_import_alert(
        api=api,
        scope_type="COUNTRY_PRODUCT",
        country_code="DE",
        product_code="PC-A",
        reason="Pesticide MRL",
    )

    e1 = get_entry(ent_1["id"], api=api)
    assert e1["disposition_status"] == "DETAINED", "DE + PC-A must match"
    assert e1["detained_under_alert_id"] == alert["id"]
    e2 = get_entry(ent_2["id"], api=api)
    assert e2["disposition_status"] == "PENDING", "DE but PC-B must not match"
    e3 = get_entry(ent_3["id"], api=api)
    assert e3["disposition_status"] == "PENDING", "PC-A but FR must not match"
    assert get_facility(fac_de1["id"], api=api)["open_detention_count"] == 1
    assert get_facility(fac_de2["id"], api=api)["open_detention_count"] == 0
    assert get_facility(fac_fr1["id"], api=api)["open_detention_count"] == 0


def test_petition_approval_releases_remaining_detentions(api):
    """PRD §3.7: "Lifting cascades: every import entry still `DETAINED` under
    this alert (`detained_under_alert_id` equal to it) is released exactly as
    in §3.6's compliance release — held units move to `units_released`,
    `open_detention_count` decrements, `disposition_completed_at` is set — with
    the importer's standing recomputed per released entry."

    Design: Corner/endpoints/petition_approval_releases_remaining_detentions
    """
    ctx = setup_alert_with_compliant_streak(
        streak=3,
        evidence_links=["doc-remediation"],
        api=api,
        facility_overrides={
            "legal_name": "Cebu Dried Mango",
            "country_code": "PH",
            "ufi": "UFI-PH-2602",
        },
        importer_overrides={
            "firm_name": "Willamette Foods",
            "account_code": "IMP-2602",
        },
        notice_overrides={
            "product_risk_class": "LOW",
            "declared_units": 6,
            "unit_value_cents": 100,
            "port_code": "US-LAX",
        },
        alert_reason="Sulfites",
    )
    # A fourth entry screened to DETAIN and still held under the alert.
    _, ent_r4 = create_notice_and_entry(
        ctx["importer"],
        ctx["facility"],
        api=api,
        product_code="PC-MNG-04",
        product_risk_class="LOW",
        declared_units=6,
        unit_value_cents=100,
        port_code="US-LAX",
    )
    screen_entry(ent_r4, api=api)
    held = get_entry(ent_r4["id"], api=api)
    assert held["disposition_status"] == "DETAINED"
    assert held["detained_under_alert_id"] == ctx["alert"]["id"]

    approved = adjudicate_petition(ctx["petition"], "APPROVE", api=api)
    assert approved["status"] == "APPROVED"
    alert_after = get_import_alert(ctx["alert"]["id"], api=api)
    assert alert_after["status"] == "LIFTED"
    assert alert_after["lifted_at"] is not None

    released = get_entry(ent_r4["id"], api=api)
    assert released["disposition_status"] == "RELEASED"
    assert released["units_released"] == 6
    assert released["units_held"] == 0
    rows, meta = validate_paginated(
        api.list_entries(
            TEST_USERS["platform_admin_headers"],
            params={
                "detained_under_alert_id": ctx["alert"]["id"],
                "disposition_status": "DETAINED",
            },
        )
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert get_facility(ctx["facility"]["id"], api=api)["open_detention_count"] == 0


def test_petition_with_stale_alert_version_returns_stale_version(api):
    """PRD §2.7: petition filing "requires `expected_import_alert_version`,
    holding the alert `version` the petitioner last observed. A mismatch with
    the alert's current `version` is likewise rejected with `ERR_STALE_VERSION`
    (HTTP 412), because petition evidence is assembled against a specific
    revision of the alert's content."
    PRD §3.7: "Filing a petition increments the *alert's* `version` by 1".

    Design: Corner/cross_cutting_layers/petition_with_stale_alert_version_returns_stale_version
    """
    fac = create_facility(
        api=api,
        legal_name="Oaxaca Chocolate",
        facility_kind="FOREIGN",
        country_code="MX",
        ufi="UFI-MX-2702",
    )
    alert = place_import_alert(
        api=api, scope_type="FIRM", facility_id=fac["id"], reason="Salmonella"
    )
    pet1 = file_petition(
        alert,
        fac,
        evidence_links=["doc-1"],
        expected_import_alert_version=alert["version"],
        api=api,
    )
    assert pet1["status"] == "EVIDENCE_REVIEW"
    assert get_import_alert(alert["id"], api=api)["version"] == alert["version"] + 1

    # The second filing still carries the now-stale v1.
    resp = api.create_alert_petition(
        alert["id"],
        create_alert_petition_payload(
            expected_import_alert_version=alert["version"],
            evidence_links=["doc-2"],
        ),
        make_facility_owner_headers(fac["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    rows = list_alert_petition_rows(alert["id"], api=api)
    assert len(rows) == 1


def test_streak_trailing_run_resets_on_post_alert_refusal(api):
    """PRD §3.7: "The streak is the length of the *trailing* run of entries
    whose terminal disposition is `RELEASED` or `RECONDITIONED`; any `REFUSED`
    or `EXPORTED` entry breaks the run."
    PRD §3.7: "restricted to entries whose `disposition_completed_at` is set and
    falls at or after the alert's `created_at`."

    Design: Corner/calculations/streak_trailing_run_resets_on_post_alert_refusal
    """
    fac = create_facility(
        api=api,
        legal_name="Valencia Naranjas",
        facility_kind="FOREIGN",
        country_code="ES",
        ufi="UFI-ES-2202",
    )
    imp = create_importer(api=api, firm_name="Sonoran Imports", account_code="IMP-2202")
    lab = create_laboratory(api=api, lab_code="LAB-S", daily_sample_capacity=10)

    # Pre-alert history at 00:00: two releases, then one refusal.
    release_low_entry(
        imp, fac, api=api, product_code="PC-ORA-01", declared_units=4,
        unit_value_cents=100, port_code="US-MIA",
    )
    release_low_entry(
        imp, fac, api=api, product_code="PC-ORA-02", declared_units=4,
        unit_value_cents=100, port_code="US-MIA",
    )
    refuse_high_entry_via_violative_sample(
        imp, fac, lab["lab_code"], api=api, product_code="PC-ORA-03",
        declared_units=4, unit_value_cents=100, port_code="US-MIA",
    )

    # Alert created at 01:00; entry d released at 01:00 (counts, then reset).
    set_clock("2026-09-01T01:00:00Z", api=api)
    alert = place_import_alert(
        api=api, scope_type="FIRM", facility_id=fac["id"], reason="Repeated violations"
    )
    _, ent_d = create_notice_and_entry(
        imp, fac, api=api, product_code="PC-ORA-04", product_risk_class="LOW",
        declared_units=4, unit_value_cents=100, port_code="US-MIA",
    )
    screen_entry(ent_d, api=api)  # DETAIN under the active alert
    release_detained_entry(ent_d, api=api)

    # Entry g refused at 02:00: the post-alert refusal breaks the run.
    set_clock("2026-09-01T02:00:00Z", api=api)
    _, ent_g = create_notice_and_entry(
        imp, fac, api=api, product_code="PC-ORA-05", product_risk_class="LOW",
        declared_units=4, unit_value_cents=100, port_code="US-MIA",
    )
    screen_entry(ent_g, api=api)
    refuse_entry(get_entry(ent_g["id"], api=api), api=api)

    # Entries h, i, j released at 03:00: the trailing run is exactly these 3.
    set_clock("2026-09-01T03:00:00Z", api=api)
    for code in ("PC-ORA-06", "PC-ORA-07", "PC-ORA-08"):
        _, e = create_notice_and_entry(
            imp, fac, api=api, product_code=code, product_risk_class="LOW",
            declared_units=4, unit_value_cents=100, port_code="US-MIA",
        )
        screen_entry(e, api=api)
        release_detained_entry(e, api=api)

    pet = file_petition(alert, fac, evidence_links=["doc-cap"], api=api)
    approved = adjudicate_petition(pet, "APPROVE", api=api)
    assert approved["status"] == "APPROVED"
    assert approved["consecutive_compliant_count"] == 3, (
        "only h/i/j count: d is before the post-alert refusal g (trailing-run "
        "reset) and the pre-alert refusal completed before alert creation "
        "(window exclusion)"
    )


def test_alert_activation_cascade(api):
    """PRD §3.7: "Placement has immediate teeth. Every import entry matching
    the alert's scope whose disposition is still `PENDING` — whatever its
    `review_status` — is detained without physical examination".
    PRD §3.7: "An alert is created `ACTIVE`, records its creator's `X-User-ID`
    in `created_by_user_id`".

    Design: Difficulty/transitive_cascade/alert_activation_cascade
    """
    fac_f1 = create_facility(
        api=api, legal_name="Eifel Molkerei", country_code="DE", ufi="UFI-DE-601"
    )
    fac_f2 = create_facility(
        api=api, legal_name="Harz Konserven", country_code="DE", ufi="UFI-DE-602"
    )
    imp6 = create_importer(
        api=api, firm_name="Ozark Provisions", account_code="IMP-601"
    )
    _, ent_f1 = create_notice_and_entry(
        imp6, fac_f1, api=api, product_code="PC-MLK-01", product_risk_class="STANDARD",
        declared_units=25, unit_value_cents=400, port_code="US-PHI",
    )
    _, ent_f2 = create_notice_and_entry(
        imp6, fac_f2, api=api, product_code="PC-MLK-01", product_risk_class="STANDARD",
        declared_units=25, unit_value_cents=400, port_code="US-PHI",
    )

    alert = place_import_alert(
        api=api,
        creator_headers=make_compliance_officer_headers("co-9"),
        scope_type="FIRM",
        facility_id=fac_f1["id"],
        reason="Antibiotic residues",
    )

    e1 = get_entry(ent_f1["id"], api=api)
    assert e1["disposition_status"] == "DETAINED"
    assert e1["detained_under_alert_id"] == alert["id"]
    assert e1["response_deadline_at"] == "2026-09-11T00:00:00Z"
    assert get_facility(fac_f1["id"], api=api)["open_detention_count"] == 1

    e2 = get_entry(ent_f2["id"], api=api)
    assert e2["disposition_status"] == "PENDING", "non-matching entry untouched"
    assert get_facility(fac_f2["id"], api=api)["open_detention_count"] == 0

    assert alert["status"] == "ACTIVE"
    assert alert["created_by_user_id"] == "co-9"


def test_petition_streak_exactly_three(api):
    """PRD §3.7: "An `APPROVE` decision carries two further sufficiency
    requirements, evaluated only for approvals: the alert scope must show a
    **consecutive compliant streak** of at least 3, and `evidence_links` must
    be non-empty; either shortfall rejects the approval with
    `ERR_INSUFFICIENT_COMPLIANT_SHIPMENTS` (HTTP 422)."
    PRD §3.7: "restricted to entries whose `disposition_completed_at` is set and
    falls at or after the alert's `created_at`."

    Design: Difficulty/boundary_precision_check/petition_streak_exactly_three
    """
    fac_m = create_facility(
        api=api,
        legal_name="Andaluz Aceites",
        facility_kind="FOREIGN",
        country_code="ES",
        ufi="UFI-ES-901",
    )
    imp9 = create_importer(
        api=api, firm_name="Mission Foods Trade", account_code="IMP-901"
    )
    alert_a1 = place_import_alert(
        api=api, scope_type="FIRM", facility_id=fac_m["id"], reason="Pesticide residues"
    )
    # Three post-alert entries detained then CO-released: trailing streak == 3.
    build_compliant_streak(
        alert_a1,
        fac_m,
        imp9,
        count=3,
        api=api,
        notice_overrides={
            "product_risk_class": "LOW",
            "declared_units": 5,
            "unit_value_cents": 100,
            "port_code": "US-MIA",
        },
    )
    pet_1 = file_petition(alert_a1, fac_m, evidence_links=["doc-corrective-a"], api=api)
    set_clock("2026-09-01T01:00:00Z", api=api)
    approved = adjudicate_petition(pet_1, "APPROVE", api=api)
    assert approved["status"] == "APPROVED"
    assert approved["consecutive_compliant_count"] == 3, (
        "exactly REQUIRED_STREAK must approve (inclusive boundary)"
    )
    assert get_import_alert(alert_a1["id"], api=api)["status"] == "LIFTED"

    # Second episode: A2 created at 01:00, so the 00:00 completions fall outside
    # its window; only the two fresh releases count (streak 2 < 3).
    alert_a2 = place_import_alert(
        api=api, scope_type="FIRM", facility_id=fac_m["id"], reason="Second episode"
    )
    build_compliant_streak(
        alert_a2,
        fac_m,
        imp9,
        count=2,
        api=api,
        notice_overrides={
            "product_risk_class": "LOW",
            "declared_units": 5,
            "unit_value_cents": 100,
            "port_code": "US-MIA",
        },
    )
    pet_2 = file_petition(alert_a2, fac_m, evidence_links=["doc-corrective-b"], api=api)
    resp = api.adjudicate_petition(
        pet_2["id"],
        adjudicate_petition_payload("APPROVE"),
        TEST_USERS["compliance_officer_two_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_COMPLIANT_SHIPMENTS)
    assert get_import_alert(alert_a2["id"], api=api)["status"] == "ACTIVE"
    assert (
        find_petition(alert_a2["id"], pet_2["id"], api=api)["status"]
        == "EVIDENCE_REVIEW"
    )


def test_petition_requires_active_alert(api):
    """PRD §3.7: "A `FacilityOwner` files a petition against an alert that is
    still `ACTIVE` (filing against a `LIFTED` alert fails with
    `ERR_IMPORT_ALERT_NOT_ACTIVE`, HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/petition_requires_active_alert
    """
    ctx = setup_lifted_alert(
        api=api,
        facility_overrides={
            "legal_name": "Thuringia Wurst",
            "country_code": "DE",
            "ufi": "UFI-DE-1101",
        },
        importer_overrides={
            "firm_name": "Front Range Foods",
            "account_code": "IMP-1101",
        },
        notice_overrides={
            "product_risk_class": "LOW",
            "declared_units": 8,
            "unit_value_cents": 600,
            "port_code": "US-HOU",
        },
        alert_reason="Salmonella",
        evidence_links=["doc-fix"],
    )
    assert ctx["alert"]["status"] == "LIFTED", "precondition: petition approved, alert lifted"
    resp = api.create_alert_petition(
        ctx["alert"]["id"],
        create_alert_petition_payload(
            expected_import_alert_version=ctx["alert"]["version"],
            evidence_links=["doc-second"],
        ),
        make_facility_owner_headers(ctx["facility"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_IMPORT_ALERT_NOT_ACTIVE)
