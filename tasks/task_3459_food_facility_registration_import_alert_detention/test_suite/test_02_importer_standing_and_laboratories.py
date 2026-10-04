"""Importer onboarding/standing and laboratory registration (PRD §3.2)."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_entry,
    create_facility,
    create_importer,
    create_importer_payload,
    create_laboratory,
    create_laboratory_payload,
    create_prior_notice,
    create_prior_notice_payload,
    get_entry,
    get_facility,
    make_importer_headers,
    order_sample,
    record_sample_result,
    refuse_entry,
    release_low_entry,
    refuse_high_entry_via_violative_sample,
    screen_entry,
    validate_error,
)


def test_importer_duplicate_account_code_rejected(api):
    """PRD §3.2: "Importer firms are onboarded by a `PlatformAdmin`, who
    supplies the firm's `firm_name` and an `account_code` that must be unique
    across importers (duplicates are rejected with
    `ERR_DUPLICATE_ACCOUNT_CODE`, HTTP 409)."

    Design: Corner/entities/importer_duplicate_account_code_rejected
    """
    create_importer(
        api=api, firm_name="Northwoods Trading", account_code="IMP-2002"
    )
    resp = api.create_importer(
        create_importer_payload(
            firm_name="Northwoods Trading II", account_code="IMP-2002"
        ),
        TEST_USERS["platform_admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACCOUNT_CODE)


def test_laboratory_duplicate_lab_code_rejected(api):
    """PRD §3.2: "A `PlatformAdmin` registers each laboratory with a `lab_code`
    — unique across laboratories, with duplicates rejected as
    `ERR_DUPLICATE_LAB_CODE` (HTTP 409)".

    Design: Corner/entities/laboratory_duplicate_lab_code_rejected
    """
    create_laboratory(api=api, lab_code="LAB-DUP", daily_sample_capacity=10)
    resp = api.create_laboratory(
        create_laboratory_payload(lab_code="LAB-DUP", daily_sample_capacity=5),
        TEST_USERS["platform_admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_LAB_CODE)


def test_importer_standing_progression_probation_then_revoked(api):
    """PRD §3.2: "Third, the new standing is assigned: `REVOKED` when
    `refusal_count` has reached 4 or the ratio is at least one-half; otherwise
    `PROBATION` when `refusal_count` has reached 2 or the ratio is at least
    one-fifth; otherwise `GOOD_STANDING`."
    PRD §3.2: "A `PROBATION` importer is not blocked, but every screening score
    computed for its entries carries a 15-point uplift (see §3.4)."
    PRD §3.2: "A `REVOKED` importer can no longer file prior notices or create
    entries — both attempts fail with `ERR_IMPORTER_REVOKED` (HTTP 409)."

    Design: Corner/calculations/importer_standing_progression_probation_then_revoked
    """
    fac1 = create_facility(
        api=api,
        legal_name="Porto Vinhos",
        facility_kind="FOREIGN",
        country_code="PT",
        ufi="UFI-PT-2203",
    )
    fac2 = create_facility(
        api=api,
        legal_name="Azores Lacticinios",
        facility_kind="FOREIGN",
        country_code="PT",
        ufi="UFI-PT-2204",
    )
    imp = create_importer(
        api=api, firm_name="Snake River Traders", account_code="IMP-2203"
    )
    lab = create_laboratory(api=api, lab_code="LAB-P", daily_sample_capacity=10)

    # Three terminal releases (terminal_entry_count 3, no refusals).
    for i in range(3):
        release_low_entry(
            imp,
            fac1,
            api=api,
            product_code=f"PC-VIN-0{i + 1}",
            declared_units=3,
            unit_value_cents=100,
        )
    # Two refusals via violative samples -> refusal_count 2 of 5 terminal:
    # ratio 0.4 >= 1/5 -> PROBATION.
    for i in range(2):
        refuse_high_entry_via_violative_sample(
            imp,
            fac1,
            lab["lab_code"],
            api=api,
            product_code=f"PC-VIN-0{i + 4}",
            declared_units=3,
            unit_value_cents=100,
        )

    # A STANDARD entry on the clean facility, created but not yet screened.
    pn_probe = create_prior_notice(
        imp,
        fac2,
        api=api,
        product_code="PC-LEI-01",
        product_risk_class="STANDARD",
        transport_mode="VESSEL",
        arrival_eta="2026-09-03T00:00:00Z",
        declared_units=3,
        unit_value_cents=100,
        port_code="US-NYC",
    )
    ent_probe = create_entry(imp, pn_probe, api=api)

    # A third HIGH entry on fac1, screened and sampled, result pending.
    pn_h3 = create_prior_notice(
        imp,
        fac1,
        api=api,
        product_code="PC-VIN-06",
        product_risk_class="HIGH",
        transport_mode="VESSEL",
        arrival_eta="2026-09-03T00:00:00Z",
        declared_units=3,
        unit_value_cents=100,
        port_code="US-NYC",
    )
    ent_h3 = create_entry(imp, pn_h3, api=api)
    screened_h3 = screen_entry(ent_h3, api=api)
    samp_h3 = order_sample(screened_h3, lab["lab_code"], api=api)

    # Screen the probe at PROBATION: HISTORY_WEIGHTED (refusal_count 2 > 0):
    # 30 + 24*2 + 15 = 93 -> SAMPLE.
    screened_probe = screen_entry(ent_probe, api=api)
    assert screened_probe["screening_score"] == 93, (
        f"expected 30 + 24*2 + 15 == 93, got {screened_probe['screening_score']}"
    )
    assert screened_probe["scoring_variant_applied"] == "HISTORY_WEIGHTED"
    assert screened_probe["probation_adjustment_applied"] == 15
    assert screened_probe["screening_decision"] == "SAMPLE"

    # Third refusal: refusal_count 3, terminal 6, ratio 0.5 >= 1/2 -> REVOKED.
    record_sample_result(samp_h3, result="VIOLATIVE", api=api)
    refuse_entry(get_entry(ent_h3["id"], api=api), api=api)

    resp = api.create_prior_notice(
        create_prior_notice_payload(
            importer_id=imp["id"],
            facility_id=fac1["id"],
            product_code="PC-VIN-07",
            product_risk_class="LOW",
            transport_mode="VESSEL",
            arrival_eta="2026-09-03T00:00:00Z",
            declared_units=3,
            unit_value_cents=100,
            port_code="US-NYC",
        ),
        make_importer_headers(imp["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_IMPORTER_REVOKED)

    assert get_facility(fac1["id"], api=api)["violation_count"] == 3
    assert get_facility(fac2["id"], api=api)["violation_count"] == 0
