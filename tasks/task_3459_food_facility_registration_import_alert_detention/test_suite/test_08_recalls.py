"""Recall classification, safety gate, effectiveness verification, and
termination thresholds (PRD §3.9, §3.4, §2.8)."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_recall_quantities_conserved,
    classify_recall,
    classify_recall_payload,
    create_entry,
    create_entry_payload,
    create_facility,
    create_importer,
    create_notice_and_entry,
    create_prior_notice,
    create_recall,
    get_recall,
    make_importer_headers,
    record_effectiveness_payload,
    record_effectiveness_round,
    setup_classified_recall,
    terminate_recall,
    validate_error,
)


def test_classify_on_classified_recall_returns_recall_invalid_state(api):
    """PRD §3.9: "Classification is a distinct act: while the recall is
    `INITIATED` (otherwise `ERR_RECALL_INVALID_STATE`, HTTP 409), the
    coordinator assigns a `classification` of `CLASS_I`, `CLASS_II`, or
    `CLASS_III`".

    Design: Corner/state_machines/classify_on_classified_recall_returns_recall_invalid_state
    """
    fac = create_facility(
        api=api,
        legal_name="Yakima Valley Packing",
        facility_kind="DOMESTIC",
        country_code="US",
        ufi="UFI-US-2105",
    )
    rec = create_recall(
        fac, api=api, product_code="PC-APC-01", quantity_distributed=500
    )
    classified = classify_recall(rec, "CLASS_II", api=api)
    assert classified["status"] == "CLASSIFIED"
    resp = api.classify_recall(
        rec["id"],
        classify_recall_payload("CLASS_I"),
        TEST_USERS["recall_coordinator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_RECALL_INVALID_STATE)
    r = get_recall(rec["id"], api=api)
    assert r["classification"] == "CLASS_II"
    assert r["status"] == "CLASSIFIED"


def test_class_i_recall_blocks_entry_but_initiated_does_not(api):
    """PRD §3.4: "when a recall exists in `CLASSIFIED` status with
    classification `CLASS_I` for the same `facility_id` and `product_code` as
    the new entry, creation is rejected with `ERR_ACTIVE_RECALL_BLOCKS_ENTRY`
    (HTTP 422). Recalls still `INITIATED` or already `TERMINATED` do not
    block".

    Design: Corner/validations/class_i_recall_blocks_entry_but_initiated_does_not
    """
    fac = create_facility(
        api=api,
        legal_name="Wisconsin Dairy Co",
        facility_kind="DOMESTIC",
        country_code="US",
        ufi="UFI-US-2305",
    )
    imp = create_importer(
        api=api, firm_name="Evergreen Imports", account_code="IMP-2305"
    )
    rec = create_recall(
        fac, api=api, product_code="PC-BBY-01", quantity_distributed=200
    )

    # While the recall is INITIATED the gate is inactive.
    _, ent_pre = create_notice_and_entry(
        imp,
        fac,
        api=api,
        product_code="PC-BBY-01",
        product_risk_class="STANDARD",
        transport_mode="ROAD",
        arrival_eta="2026-09-01T06:00:00Z",
        declared_units=10,
        unit_value_cents=100,
        port_code="US-MSP",
    )
    assert ent_pre["review_status"] == "PENDING_SCREENING"

    # CLASS_I classification activates the gate for facility + product_code.
    classify_recall(rec, "CLASS_I", api=api)
    pn_post = create_prior_notice(
        imp,
        fac,
        api=api,
        product_code="PC-BBY-01",
        product_risk_class="STANDARD",
        transport_mode="ROAD",
        arrival_eta="2026-09-01T08:00:00Z",
        declared_units=10,
        unit_value_cents=100,
        port_code="US-MSP",
    )
    blocked = api.create_entry(
        create_entry_payload(pn_post["id"]), make_importer_headers(imp["id"])
    )
    validate_error(blocked, ApiErrorId.ERR_ACTIVE_RECALL_BLOCKS_ENTRY)

    # A different product_code on the same facility still files.
    _, ent_other = create_notice_and_entry(
        imp,
        fac,
        api=api,
        product_code="PC-BBY-99",
        product_risk_class="STANDARD",
        transport_mode="ROAD",
        arrival_eta="2026-09-01T08:00:00Z",
        declared_units=10,
        unit_value_cents=100,
        port_code="US-MSP",
    )
    assert ent_other["review_status"] == "PENDING_SCREENING"


def test_recall_terminate_below_threshold_then_at_threshold(api):
    """PRD §3.9: "a `CLASS_III` recall requires `effectiveness_pct` of at
    least 90.0. Terminating early fails with
    `ERR_EFFECTIVENESS_THRESHOLD_NOT_MET` (HTTP 422)."
    PRD §3.9: "their sum not exceeding the recall's current
    `quantity_outstanding`; an over-report fails with
    `ERR_UNITS_ACCOUNTING_MISMATCH` (HTTP 422)."

    Design: Corner/validations/recall_terminate_below_threshold_then_at_threshold
    """
    ctx = setup_classified_recall(
        "CLASS_III",
        quantity_distributed=100,
        api=api,
        facility_overrides={"legal_name": "Boulder Granola", "ufi": "UFI-US-2313"},
        product_code="PC-GRA-01",
    )
    rec = ctx["recall"]
    rec = record_effectiveness_round(
        rec,
        delta_recovered=89,
        delta_corrected=0,
        delta_destroyed=0,
        consignees_contacted=5,
        consignees_total=5,
        api=api,
    )
    assert rec["effectiveness_pct"] == 89.0
    assert rec["quantity_outstanding"] == 11

    # 89.0 < 90.0: termination rejected.
    early = api.terminate_recall(rec["id"], TEST_USERS["recall_coordinator_headers"])
    validate_error(early, ApiErrorId.ERR_EFFECTIVENESS_THRESHOLD_NOT_MET)

    # An effectiveness delta larger than quantity_outstanding is rejected.
    over = api.record_recall_effectiveness(
        rec["id"],
        record_effectiveness_payload(12, 0, 0, 0, 5),
        TEST_USERS["recall_coordinator_headers"],
    )
    validate_error(over, ApiErrorId.ERR_UNITS_ACCOUNTING_MISMATCH)

    # +1 unit reaches exactly 90.0; the threshold is inclusive.
    rec = record_effectiveness_round(
        rec,
        delta_recovered=1,
        delta_corrected=0,
        delta_destroyed=0,
        consignees_contacted=0,
        consignees_total=5,
        api=api,
    )
    assert rec["effectiveness_pct"] == 90.0
    assert rec["quantity_outstanding"] == 10
    assert_recall_quantities_conserved(rec)
    done = terminate_recall(rec, api=api)
    assert done["status"] == "TERMINATED"


def test_recall_quantities_conserved_through_effectiveness_rounds(api):
    """PRD §2.8: "For every recall, `quantity_recovered` +
    `quantity_corrected` + `quantity_destroyed` + `quantity_outstanding` always
    equals the recall's `quantity_distributed`."
    PRD §3.9: "`effectiveness_pct` is the accounted share — recovered plus
    corrected plus destroyed — expressed as a percentage of
    `quantity_distributed`, rounded half up to 1 decimal place.
    `consignee_contact_pct` is `consignees_contacted` as a percentage of
    `consignees_total`, likewise rounded half up to 1 decimal place".

    Design: Difficulty/compensating_invariant/recall_quantities_conserved_through_effectiveness_rounds
    """
    ctx = setup_classified_recall(
        "CLASS_III",
        quantity_distributed=1000,
        api=api,
        facility_overrides={"legal_name": "Iowa Nut Roasters", "ufi": "UFI-US-1501"},
        product_code="PC-NUT-01",
    )
    rec = ctx["recall"]

    r1 = record_effectiveness_round(
        rec,
        delta_recovered=400,
        delta_corrected=100,
        delta_destroyed=50,
        consignees_contacted=8,
        consignees_total=10,
        api=api,
    )
    assert_recall_quantities_conserved(r1)
    assert r1["quantity_outstanding"] == 450
    assert r1["effectiveness_pct"] == 55.0, (
        f"round_half_up(100 x 550 / 1000, 1) must be 55.0, got "
        f"{r1['effectiveness_pct']}"
    )
    assert r1["consignee_contact_pct"] == 80.0

    r2 = record_effectiveness_round(
        rec,
        delta_recovered=350,
        delta_corrected=0,
        delta_destroyed=0,
        consignees_contacted=2,
        consignees_total=10,
        api=api,
    )
    assert_recall_quantities_conserved(r2)
    assert r2["quantity_outstanding"] == 100
    assert r2["effectiveness_pct"] == 90.0
    assert r2["consignee_contact_pct"] == 100.0, (
        "consignee deltas accumulate: 8 + 2 == 10 of total 10"
    )
