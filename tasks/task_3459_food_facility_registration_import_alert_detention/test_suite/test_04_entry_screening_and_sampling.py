"""Entry screening review, scoring variants, sampling, and laboratory capacity
(PRD §3.4, §3.5, §2.3)."""

from test_helpers import (
    CLOCK_DEFAULT_UTC,
    DEFAULT_DETENTION_DEADLINE,
    TEST_USERS,
    ApiErrorId,
    amend_prior_notice,
    complete_inspection,
    create_entries_batch,
    create_entry,
    create_entry_payload,
    create_facility,
    create_importer,
    create_laboratory,
    create_notice_and_entry,
    create_prior_notice,
    get_entry,
    get_facility,
    get_prior_notice,
    list_entry_sample_rows,
    make_compliance_officer_headers,
    make_importer_headers,
    order_sample,
    place_import_alert,
    record_sample_payload,
    schedule_inspection,
    screen_entry,
    set_clock,
    setup_facility_and_importer,
    setup_screened_entry,
    validate_error,
    validate_paginated,
)


def test_entries_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned: it defaults to 10 when omitted, accepts a minimum of 1, and is
    capped at a maximum of 100. The `offset` parameter sets the number of items
    skipped and defaults to 0."
    PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`,
    and `has_more`."

    Design: Corner/entities/entries_list_paginates_with_total_count_and_has_more
    """
    fac, imp = setup_facility_and_importer(
        api=api,
        facility_overrides={
            "legal_name": "Puno Quinoa",
            "country_code": "PE",
            "ufi": "UFI-PE-2004",
        },
        importer_overrides={
            "firm_name": "Mesa Verde Imports",
            "account_code": "IMP-2004",
        },
    )
    create_entries_batch(
        imp,
        fac,
        3,
        api=api,
        product_risk_class="LOW",
        transport_mode="VESSEL",
        arrival_eta="2026-09-03T00:00:00Z",
        declared_units=5,
        unit_value_cents=100,
        port_code="US-LAX",
    )
    reader = TEST_USERS["compliance_officer_headers"]

    rows, meta = validate_paginated(
        api.list_entries(reader, params={"limit": 2, "offset": 0})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rows, meta = validate_paginated(
        api.list_entries(reader, params={"limit": 2, "offset": 2})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    # No pagination params: defaults limit 10 / offset 0.
    rows, meta = validate_paginated(
        api.list_entries(reader, params={"importer_id": imp["id"]})
    )
    assert len(rows) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0

    rows, meta = validate_paginated(
        api.list_entries(reader, params={"disposition_status": "PENDING"})
    )
    assert len(rows) == 3
    rows, meta = validate_paginated(
        api.list_entries(reader, params={"disposition_status": "RELEASED"})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_entry_double_screen_returns_entry_invalid_state(api):
    """PRD §3.4: "Screening is performed by an `EntryReviewer` and is allowed
    only while `review_status` is `PENDING_SCREENING`; a second screening
    attempt fails with `ERR_ENTRY_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/entry_double_screen_returns_entry_invalid_state
    """
    ctx = setup_screened_entry(
        "LOW",
        api=api,
        facility_overrides={
            "legal_name": "Otago Orchards",
            "country_code": "NZ",
            "ufi": "UFI-NZ-2101",
        },
        importer_overrides={
            "firm_name": "Inland Empire Foods",
            "account_code": "IMP-2101",
        },
        notice_overrides={
            "product_code": "PC-APL-01",
            "declared_units": 7,
            "unit_value_cents": 120,
            "port_code": "US-LAX",
        },
    )
    entry = ctx["entry"]
    assert entry["review_status"] == "SCREENED"
    resp = api.screen_entry(entry["id"], TEST_USERS["entry_reviewer_headers"])
    validate_error(resp, ApiErrorId.ERR_ENTRY_INVALID_STATE)
    after = get_entry(entry["id"], api=api)
    assert after["review_status"] == "SCREENED"
    assert after["disposition_status"] == "RELEASED"
    assert after["screening_score"] == 10


def test_importer_cannot_screen_entries_returns_forbidden(api):
    """PRD §2.1: "A well-formed caller whose role is not among an operation's
    authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403)".
    PRD §4: screening is authorized for `EntryReviewer` only.

    Design: Corner/validations/importer_cannot_screen_entries_returns_forbidden
    """
    fac, imp = setup_facility_and_importer(
        api=api,
        facility_overrides={
            "legal_name": "Antwerp Chocolade",
            "country_code": "BE",
            "ufi": "UFI-BE-2302",
        },
        importer_overrides={
            "firm_name": "Coeur d'Alene Candies",
            "account_code": "IMP-2302",
        },
    )
    _, entry = create_notice_and_entry(
        imp,
        fac,
        api=api,
        product_code="PC-CHO-01",
        product_risk_class="STANDARD",
        transport_mode="VESSEL",
        arrival_eta="2026-09-03T00:00:00Z",
        declared_units=11,
        unit_value_cents=200,
        port_code="US-NYC",
    )
    resp = api.screen_entry(entry["id"], make_importer_headers(imp["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    after = get_entry(entry["id"], api=api)
    assert after["review_status"] == "PENDING_SCREENING"
    assert after["disposition_status"] == "PENDING"


def test_screening_score_base_vs_history_weighted(api):
    """PRD §3.4: "For a worked contrast, take a `STANDARD` article whose
    facility has `violation_count` 1 with a clean importer and no alert: the
    `BASE` arithmetic would total 38 and release, but the history means the
    `HISTORY_WEIGHTED` variant actually applies, totalling 46 and routing the
    entry to sampling."
    PRD §3.4: "When the facility's `violation_count` is 0 *and* the importer's
    `refusal_count` is 0 at screening time, the `BASE` variant applies with
    weights 8 and 12."

    Design: Difficulty/dual_variant_calc/screening_score_base_vs_history_weighted
    """
    fac_a = create_facility(
        api=api,
        legal_name="Bremen Cannery",
        facility_kind="FOREIGN",
        country_code="DE",
        ufi="UFI-DE-101",
    )
    fac_b = create_facility(
        api=api,
        legal_name="Ostsee Packers",
        facility_kind="FOREIGN",
        country_code="DE",
        ufi="UFI-DE-102",
    )
    imp = create_importer(
        api=api, firm_name="Prairie Imports LLC", account_code="IMP-101"
    )
    insp_a = schedule_inspection(fac_a["id"], api=api)
    complete_inspection(insp_a, 1, api=api)

    _, ent_a = create_notice_and_entry(
        imp,
        fac_a,
        api=api,
        product_code="PC-CAN-01",
        product_risk_class="STANDARD",
        transport_mode="VESSEL",
        arrival_eta="2026-09-03T00:00:00Z",
        declared_units=10,
        unit_value_cents=1000,
        port_code="US-BAL",
    )
    _, ent_b = create_notice_and_entry(
        imp,
        fac_b,
        api=api,
        product_code="PC-CAN-01",
        product_risk_class="STANDARD",
        transport_mode="VESSEL",
        arrival_eta="2026-09-03T00:00:00Z",
        declared_units=10,
        unit_value_cents=1000,
        port_code="US-BAL",
    )

    screened_a = screen_entry(ent_a, api=api)
    screened_b = screen_entry(ent_b, api=api)

    assert screened_a["screening_score"] == 46, (
        f"30 + 16*1 must be 46, got {screened_a['screening_score']}"
    )
    assert screened_a["scoring_variant_applied"] == "HISTORY_WEIGHTED"
    assert screened_a["probation_adjustment_applied"] == 0
    assert screened_a["screening_decision"] == "SAMPLE"
    assert screened_a["disposition_status"] == "PENDING"

    assert screened_b["screening_score"] == 30
    assert screened_b["scoring_variant_applied"] == "BASE"
    assert screened_b["screening_decision"] == "RELEASE"
    assert screened_b["disposition_status"] == "RELEASED"
    assert screened_b["units_released"] == 10

    assert get_facility(fac_a["id"], api=api)["violation_count"] == 1


def test_screening_score_threshold_routing(api):
    """PRD §3.4: "With no alert match, a score of 40 or more yields `SAMPLE`;
    anything below 40 yields `RELEASE`."
    PRD §3.4: "**Circumstance terms** add 35 when an `ACTIVE` import alert
    matches the entry's scope, 10 when `is_amendment_pn` is true, and 15 when
    the importer's `standing` is `PROBATION`."

    Design: Difficulty/combinatorial_formula/screening_score_threshold_routing
    """
    fac_c = create_facility(
        api=api,
        legal_name="Lyonnaise Confitures",
        facility_kind="FOREIGN",
        country_code="FR",
        ufi="UFI-FR-201",
    )
    imp2 = create_importer(api=api, firm_name="Bayou Trading", account_code="IMP-201")
    pn1 = create_prior_notice(
        imp2,
        fac_c,
        api=api,
        product_code="PC-JAM-01",
        product_risk_class="STANDARD",
        transport_mode="VESSEL",
        arrival_eta="2026-09-03T00:00:00Z",
        declared_units=20,
        unit_value_cents=200,
        port_code="US-NOL",
    )
    pn1a = amend_prior_notice(
        pn1, imp2, api=api, arrival_eta="2026-09-03T00:00:00Z", declared_units=20
    )
    ent_1 = create_entry(imp2, pn1a, api=api)
    _, ent_2 = create_notice_and_entry(
        imp2,
        fac_c,
        api=api,
        product_code="PC-JAM-02",
        product_risk_class="STANDARD",
        transport_mode="VESSEL",
        arrival_eta="2026-09-03T00:00:00Z",
        declared_units=20,
        unit_value_cents=200,
        port_code="US-NOL",
    )

    s1 = screen_entry(ent_1, api=api)
    s2 = screen_entry(ent_2, api=api)

    # Amended notice: 30 base + 10 amendment term == 40, and 40 >= 40 -> SAMPLE.
    assert s1["screening_score"] == 40
    assert s1["screening_decision"] == "SAMPLE", (
        "score == SAMPLE_THRESHOLD must route SAMPLE (inclusive boundary)"
    )
    assert s1["disposition_status"] == "PENDING"
    # Identical non-amended entry: 30 < 40 -> RELEASE.
    assert s2["screening_score"] == 30
    assert s2["screening_decision"] == "RELEASE"
    assert s2["disposition_status"] == "RELEASED"


def test_entry_parallel_dims_evolve_independently(api):
    """PRD §3.6: "The entry's `disposition_status` becomes `DETAINED` while
    `review_status` is left untouched, the parallel dimensions evolving
    independently."
    PRD §3.6: "`detained_at` records the logical instant detention began, and
    `response_deadline_at` is computed as `detained_at` plus 240 hours — ten
    24-hour days."

    Design: Difficulty/non_linear_state_machine/entry_parallel_dims_evolve_independently
    """
    fac_g = create_facility(
        api=api,
        legal_name="Frisia Feinkost",
        facility_kind="FOREIGN",
        country_code="DE",
        ufi="UFI-DE-402",
    )
    imp4 = create_importer(api=api, firm_name="Delta Pantry", account_code="IMP-401")
    _, ent_g = create_notice_and_entry(
        imp4,
        fac_g,
        api=api,
        product_code="PC-RAW-01",
        product_risk_class="HIGH",
        transport_mode="AIR",
        arrival_eta="2026-09-02T00:00:00Z",
        declared_units=40,
        unit_value_cents=800,
        port_code="US-ATL",
    )

    mid = screen_entry(ent_g, api=api)
    assert mid["review_status"] == "SCREENED"
    assert mid["disposition_status"] == "PENDING"
    assert mid["screening_decision"] == "SAMPLE"  # score 60 >= 40

    alert = place_import_alert(
        api=api,
        creator_headers=make_compliance_officer_headers("co-1"),
        scope_type="FIRM",
        facility_id=fac_g["id"],
        reason="Residue violations",
    )
    end = get_entry(ent_g["id"], api=api)
    assert end["disposition_status"] == "DETAINED"
    assert end["review_status"] == "SCREENED", "review dimension must be untouched"
    assert end["screening_decision"] == "SAMPLE", "screening decision must be preserved"
    assert end["detained_under_alert_id"] == alert["id"]
    assert end["detained_at"] == CLOCK_DEFAULT_UTC
    assert end["response_deadline_at"] == DEFAULT_DETENTION_DEADLINE


def test_entry_requires_confirmed_prior_notice(api):
    """PRD §3.3: "`SUPERSEDED`, `COMPROMISED`, and `CONSUMED` are all terminal;
    any operation that requires a `CONFIRMED` notice rejects the others with
    `ERR_PN_NOT_CONFIRMED`."
    PRD §3.3: "Creating an import entry consumes it (§3.4), flipping it to
    `CONSUMED` — and exactly one entry may ever consume a notice".

    Design: Difficulty/cross_entity_state_dependency/entry_requires_confirmed_prior_notice
    """
    fac = create_facility(
        api=api,
        legal_name="Sicilia Agrumi",
        facility_kind="FOREIGN",
        country_code="IT",
        ufi="UFI-IT-1001",
    )
    imp = create_importer(
        api=api, firm_name="Sunbelt Distributing", account_code="IMP-1001"
    )
    pn1 = create_prior_notice(
        imp,
        fac,
        api=api,
        product_code="PC-CIT-01",
        product_risk_class="STANDARD",
        transport_mode="VESSEL",
        arrival_eta="2026-09-03T00:00:00Z",
        declared_units=15,
        unit_value_cents=250,
        port_code="US-NYC",
    )
    pn1a = amend_prior_notice(pn1, imp, api=api, arrival_eta="2026-09-03T06:00:00Z")

    # Filing against the SUPERSEDED original fails...
    bad = api.create_entry(
        create_entry_payload(pn1["id"]), make_importer_headers(imp["id"])
    )
    validate_error(bad, ApiErrorId.ERR_PN_NOT_CONFIRMED)

    # ...while the superseding CONFIRMED notice accepts the entry.
    entry = create_entry(imp, pn1a, api=api)
    assert entry["review_status"] == "PENDING_SCREENING"
    assert entry["disposition_status"] == "PENDING"
    assert get_prior_notice(pn1a["id"], api=api)["status"] == "CONSUMED"


def test_sample_temporal_error_beats_capacity_error(api):
    """PRD §2.6: "a sample analysis dated in the past reports
    `ERR_SAMPLE_DATE_PAST` even when the laboratory's day capacity is also
    exhausted."

    Design: Difficulty/priority_pair_validation_conflict/sample_temporal_beats_capacity
    """
    set_clock("2026-09-30T12:00:00Z", api=api)
    fac_k = create_facility(
        api=api,
        legal_name="Mekong Rice Co",
        facility_kind="FOREIGN",
        country_code="VN",
        ufi="UFI-VN-702",
    )
    imp7 = create_importer(
        api=api, firm_name="Cascade Commodities", account_code="IMP-701"
    )
    create_laboratory(api=api, lab_code="LAB-FULL", daily_sample_capacity=1)
    _, ent_k = create_notice_and_entry(
        imp7,
        fac_k,
        api=api,
        product_code="PC-RICE-01",
        product_risk_class="HIGH",
        transport_mode="VESSEL",
        arrival_eta="2026-10-02T12:00:00Z",
        declared_units=80,
        unit_value_cents=100,
        port_code="US-SEA",
    )
    screened = screen_entry(ent_k, api=api)
    assert screened["screening_decision"] == "SAMPLE"
    # Fill the 2026-09-30 lab-day bucket to capacity while it is not in the past.
    order_sample(screened, "LAB-FULL", sample_units=1, analysis_date="2026-09-30", api=api)

    # Advance past 2026-09-30: the same order now violates the temporal check
    # AND the capacity check; the temporal error must be reported.
    set_clock("2026-10-01T12:00:00Z", api=api)
    resp = api.record_sample(
        ent_k["id"],
        record_sample_payload("LAB-FULL", 1, "2026-09-30"),
        TEST_USERS["entry_reviewer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SAMPLE_DATE_PAST)
    rows = list_entry_sample_rows(ent_k["id"], api=api)
    assert len(rows) == 1, "no second sample may be created"


def test_lab_daily_aggregate_capacity(api):
    """PRD §3.5: "Capacity is the aggregate kind: the sum of `sample_units`
    already scheduled for that laboratory on that UTC date, plus the new
    order's `sample_units`, must not exceed the laboratory's
    `daily_sample_capacity`, or the order fails with
    `ERR_LAB_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/lab_daily_aggregate_capacity
    """
    set_clock("2026-10-01T12:00:00Z", api=api)
    fac_r = create_facility(
        api=api,
        legal_name="Kyoto Shoyu",
        facility_kind="FOREIGN",
        country_code="JP",
        ufi="UFI-JP-1301",
    )
    imp12 = create_importer(
        api=api, firm_name="Pacific Rim Imports", account_code="IMP-1301"
    )
    create_laboratory(api=api, lab_code="LAB-X", daily_sample_capacity=3)
    _, ent_r = create_notice_and_entry(
        imp12,
        fac_r,
        api=api,
        product_code="PC-SOY-01",
        product_risk_class="HIGH",
        transport_mode="VESSEL",
        arrival_eta="2026-10-03T12:00:00Z",
        declared_units=90,
        unit_value_cents=150,
        port_code="US-OAK",
    )
    screened = screen_entry(ent_r, api=api)
    assert screened["screening_decision"] == "SAMPLE"

    # 1 + 2 == capacity 3 on 2026-10-02 passes (aggregate is inclusive at equality).
    order_sample(screened, "LAB-X", sample_units=1, analysis_date="2026-10-02", api=api)
    order_sample(screened, "LAB-X", sample_units=2, analysis_date="2026-10-02", api=api)

    # One more unit on that date overflows.
    over = api.record_sample(
        ent_r["id"],
        record_sample_payload("LAB-X", 1, "2026-10-02"),
        TEST_USERS["entry_reviewer_headers"],
    )
    validate_error(over, ApiErrorId.ERR_LAB_CAPACITY_EXCEEDED)

    # The next UTC day is a fresh bucket.
    ok = order_sample(screened, "LAB-X", sample_units=1, analysis_date="2026-10-03", api=api)
    assert ok["status"] == "SCHEDULED"
    rows = list_entry_sample_rows(ent_r["id"], api=api)
    assert len(rows) == 3
