"""Detention lifecycle: terminal lockdown, role-by-state release gate, response
deadline, reconditioning bond math, and unit conservation (PRD §3.6, §2.8, §2.4)."""

from test_helpers import (
    DEFAULT_DETENTION_DEADLINE,
    TEST_USERS,
    ApiErrorId,
    assert_entry_units_conserved,
    create_facility,
    create_importer,
    create_notice_and_entry,
    get_entry,
    get_facility,
    make_importer_headers,
    make_lot,
    place_import_alert,
    record_reconditioning_outcome,
    record_reconditioning_outcome_payload,
    request_reconditioning,
    request_reconditioning_payload,
    set_clock,
    setup_entry_detained_by_alert,
    setup_entry_with_bond,
    setup_screened_entry,
    validate_error,
)


def test_terminal_entry_rejects_further_actions(api):
    """PRD §3.4: "Because such an entry is already terminal, a later explicit
    release call on it is rejected with `ERR_ENTRY_INVALID_STATE`."
    PRD §3.6: "The only precondition is that the entry is still `DETAINED`;
    otherwise the refusal fails with `ERR_ENTRY_INVALID_STATE`."
    PRD §3.6: "While detained, the importing firm has two self-service exits".

    Design: Corner/state_machines/terminal_entry_rejects_further_actions
    """
    ctx = setup_screened_entry(
        "LOW",
        api=api,
        facility_overrides={
            "legal_name": "Algarve Citrus",
            "country_code": "PT",
            "ufi": "UFI-PT-2102",
        },
        importer_overrides={
            "firm_name": "High Plains Pantry",
            "account_code": "IMP-2102",
        },
        notice_overrides={
            "product_code": "PC-ORG-01",
            "declared_units": 9,
            "unit_value_cents": 90,
            "port_code": "US-MIA",
        },
    )
    entry = ctx["entry"]
    assert entry["disposition_status"] == "RELEASED"

    rel = api.release_entry(entry["id"], TEST_USERS["compliance_officer_two_headers"])
    validate_error(rel, ApiErrorId.ERR_ENTRY_INVALID_STATE)
    ref = api.refuse_entry(entry["id"], TEST_USERS["compliance_officer_two_headers"])
    validate_error(ref, ApiErrorId.ERR_ENTRY_INVALID_STATE)
    exp = api.export_entry(entry["id"], make_importer_headers(ctx["importer"]["id"]))
    validate_error(exp, ApiErrorId.ERR_ENTRY_INVALID_STATE)

    after = get_entry(entry["id"], api=api)
    assert after["disposition_status"] == "RELEASED"
    assert after["units_released"] == 9
    assert after["units_held"] == 0


def test_entry_reviewer_cannot_release_detained_entry_returns_forbidden(api):
    """PRD §3.6: "Releasing from `DETAINED` is reserved to a
    `ComplianceOfficer`: an `EntryReviewer` attempting it is rejected with
    `ERR_FORBIDDEN` (HTTP 403), per §2.1."

    Design: Corner/validations/entry_reviewer_cannot_release_detained_entry_returns_forbidden
    """
    ctx = setup_entry_detained_by_alert(
        api=api,
        facility_overrides={
            "legal_name": "Guadalajara Agave",
            "country_code": "MX",
            "ufi": "UFI-MX-2304",
        },
        importer_overrides={
            "firm_name": "Rio Grande Trading",
            "account_code": "IMP-2304",
        },
        notice_overrides={
            "product_code": "PC-AGV-01",
            "product_risk_class": "STANDARD",
            "declared_units": 6,
            "unit_value_cents": 300,
            "port_code": "US-LAX",
        },
        alert_reason="Unapproved additive",
    )
    entry = ctx["entry"]
    assert entry["disposition_status"] == "DETAINED"
    resp = api.release_entry(entry["id"], TEST_USERS["entry_reviewer_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_entry(entry["id"], api=api)["disposition_status"] == "DETAINED"


def test_detention_deadline_action_window(api):
    """PRD §3.6: "each closing at the response deadline — once the logical time
    passes `response_deadline_at`, both fail with
    `ERR_DETENTION_RESPONSE_DEADLINE_PASSED` (HTTP 422)".
    PRD §2.4: "This comparison is also strict: a detention whose
    deadline-plus-24-hour grace instant is exactly equal to the new time is not
    auto-refused."

    Design: Corner/validations/detention_deadline_action_window
    """
    fac = create_facility(
        api=api,
        legal_name="Shenzhen Snack Co",
        facility_kind="FOREIGN",
        country_code="CN",
        ufi="UFI-CN-2308",
    )
    imp = create_importer(api=api, firm_name="Wasatch Trading", account_code="IMP-2308")
    _, ent_1 = create_notice_and_entry(
        imp,
        fac,
        api=api,
        product_code="PC-SNK-01",
        product_risk_class="LOW",
        declared_units=10,
        unit_value_cents=100,
        port_code="US-LAX",
    )
    _, ent_2 = create_notice_and_entry(
        imp,
        fac,
        api=api,
        product_code="PC-SNK-02",
        product_risk_class="LOW",
        declared_units=10,
        unit_value_cents=100,
        port_code="US-LAX",
    )
    place_import_alert(
        api=api, scope_type="FIRM", facility_id=fac["id"], reason="Label violation"
    )
    e1 = get_entry(ent_1["id"], api=api)
    assert e1["disposition_status"] == "DETAINED"
    assert e1["response_deadline_at"] == DEFAULT_DETENTION_DEADLINE

    # At exactly the deadline the reconditioning request still succeeds.
    set_clock(DEFAULT_DETENTION_DEADLINE, api=api)
    bonded = request_reconditioning(e1, imp, lots=[make_lot(10, 100)], api=api)
    assert bonded["bond_amount_cents"] == 15100, (
        f"per-lot bond 100 + 10 days x 1500 storage must be 15100, got "
        f"{bonded['bond_amount_cents']}"
    )
    assert bonded["disposition_status"] == "DETAINED"

    # One hour past the deadline: rejected, and the entry is still DETAINED
    # because the 24h sweep grace has not elapsed.
    set_clock("2026-09-11T01:00:00Z", api=api)
    late = api.request_reconditioning(
        ent_2["id"],
        request_reconditioning_payload([make_lot(10, 100)]),
        make_importer_headers(imp["id"]),
    )
    validate_error(late, ApiErrorId.ERR_DETENTION_RESPONSE_DEADLINE_PASSED)
    assert get_entry(ent_2["id"], api=api)["disposition_status"] == "DETAINED"

    # At deadline + 24h + 1s the sweep auto-refuses both entries.
    sweep = set_clock("2026-09-12T00:00:01Z", api=api)
    assert set(sweep["auto_refused_entry_ids"]) == {ent_1["id"], ent_2["id"]}
    for entry_id in (ent_1["id"], ent_2["id"]):
        e = get_entry(entry_id, api=api)
        assert e["disposition_status"] == "REFUSED"
        assert e["units_refused"] == 10
        assert e["units_held"] == 0
    f = get_facility(fac["id"], api=api)
    assert f["open_detention_count"] == 0
    assert f["violation_count"] == 2


def test_reconditioning_units_must_sum_to_held(api):
    """PRD §3.6: "the reported `units_passed` and `units_failed` must each be
    zero or greater and must sum exactly to `units_held`, or the report fails
    with `ERR_UNITS_ACCOUNTING_MISMATCH` (HTTP 422)."

    Design: Corner/validations/reconditioning_units_must_sum_to_held
    """
    ctx = setup_entry_with_bond(
        lots=[make_lot(10, 100)],
        api=api,
        facility_overrides={
            "legal_name": "Casablanca Sardines",
            "country_code": "MA",
            "ufi": "UFI-MA-2312",
        },
        importer_overrides={
            "firm_name": "Gulf Shrimp Co",
            "account_code": "IMP-2312",
        },
        notice_overrides={
            "product_code": "PC-SAR-01",
            "product_risk_class": "LOW",
            "declared_units": 10,
            "unit_value_cents": 100,
            "port_code": "US-HOU",
        },
        alert_reason="Decomposition",
    )
    entry = ctx["entry"]
    assert entry["units_held"] == 10
    resp = api.record_reconditioning_outcome(
        entry["id"],
        record_reconditioning_outcome_payload(6, 3),  # 6 + 3 != 10
        TEST_USERS["compliance_officer_two_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_UNITS_ACCOUNTING_MISMATCH)
    after = get_entry(entry["id"], api=api)
    assert after["units_held"] == 10, "nothing may move on a rejected outcome"
    assert after["units_released"] == 0
    assert after["units_destroyed"] == 0
    assert after["disposition_status"] == "DETAINED"


def test_reconditioning_bond_storage_component(api):
    """PRD §3.6: "Separately, the days detained are the whole 24-hour days
    elapsed since `detained_at` (any partial day discarded, never negative),
    and storage is those days multiplied by 1500 cents. The bond is the summed
    lot shares plus the storage charge."

    Design: Corner/calculations/reconditioning_bond_storage_component
    """
    ctx = setup_entry_detained_by_alert(
        api=api,
        facility_overrides={
            "legal_name": "Danubia Konzerv",
            "country_code": "HU",
            "ufi": "UFI-HU-2205",
        },
        importer_overrides={
            "firm_name": "Badger State Foods",
            "account_code": "IMP-2205",
        },
        notice_overrides={
            "product_code": "PC-PAP-01",
            "product_risk_class": "LOW",
            "declared_units": 3,
            "unit_value_cents": 105,
            "port_code": "US-CHS",
        },
        alert_reason="Metal fragments",
    )
    # 36h after detention: floor(36/24) == 1 storage day (still within the 240h deadline).
    set_clock("2026-09-02T12:00:00Z", api=api)
    bonded = request_reconditioning(
        ctx["entry"],
        ctx["importer"],
        lots=[make_lot(1, 105), make_lot(1, 105), make_lot(1, 105)],
        api=api,
    )
    assert bonded["bond_amount_cents"] == 1533, (
        f"33 per-lot bond + 1 x 1500 storage must be 1533, got "
        f"{bonded['bond_amount_cents']}"
    )
    assert bonded["disposition_status"] == "DETAINED"
    assert bonded["units_held"] == 3


def test_reconditioning_bond_round_order(api):
    """PRD §3.6: "For example, three lots each of `quantity` 1 and
    `unit_value_cents` 105 yield a per-lot bond of 11 cents (10.5 rounded half
    up), hence 33 cents in total — summing first and rounding once would
    wrongly produce 32."

    Design: Difficulty/combinatorial_formula/reconditioning_bond_round_order
    """
    ctx = setup_entry_detained_by_alert(
        api=api,
        facility_overrides={
            "legal_name": "Weser Delikatessen",
            "country_code": "DE",
            "ufi": "UFI-DE-301",
        },
        importer_overrides={
            "firm_name": "Gulf Coast Foods",
            "account_code": "IMP-301",
        },
        notice_overrides={
            "product_code": "PC-CRacker-01",
            "product_risk_class": "LOW",
            "declared_units": 3,
            "unit_value_cents": 105,
            "port_code": "US-HOU",
        },
        alert_reason="Listeria findings",
    )
    entry = ctx["entry"]
    assert entry["disposition_status"] == "DETAINED"
    assert entry["detained_under_alert_id"] == ctx["alert"]["id"]
    # Detention and bond request share the same logical instant: 0 storage days.
    bonded = request_reconditioning(
        entry,
        ctx["importer"],
        lots=[make_lot(1, 105), make_lot(1, 105), make_lot(1, 105)],
        api=api,
    )
    assert bonded["bond_amount_cents"] == 33, (
        f"3 x round_half_up(105 x 0.10) must be 33, got {bonded['bond_amount_cents']}"
    )
    assert bonded["units_held"] == 3
    assert bonded["units_released"] == 0


def test_entry_units_conserved_through_reconditioning(api):
    """PRD §2.8: "For every import entry, `units_held` + `units_released` +
    `units_refused` + `units_exported` + `units_destroyed` always equals the
    entry's `declared_units`."
    PRD §3.6: "When any unit failed, the *entire entry* counts as a refusal for
    compliance purposes even though the destroyed units sit in the destroyed
    bucket: the disposition becomes `REFUSED`, the facility's `violation_count`
    increases by 1".

    Design: Difficulty/compensating_invariant/entry_units_conserved_through_reconditioning
    """
    ctx = setup_entry_detained_by_alert(
        api=api,
        facility_overrides={
            "legal_name": "Galicia Mariscos",
            "country_code": "ES",
            "ufi": "UFI-ES-1401",
        },
        importer_overrides={
            "firm_name": "Coastal Harvest Trading",
            "account_code": "IMP-1401",
        },
        notice_overrides={
            "product_code": "PC-TUNA-01",
            "product_risk_class": "LOW",
            "declared_units": 10,
            "unit_value_cents": 500,
            "port_code": "US-SAV",
        },
        alert_reason="Histamine",
    )
    entry = ctx["entry"]
    assert entry["units_held"] == 10
    assert entry["units_released"] == 0
    assert entry["units_refused"] == 0
    assert entry["units_exported"] == 0
    assert entry["units_destroyed"] == 0
    assert_entry_units_conserved(entry)

    # A bond request moves no units.
    bonded = request_reconditioning(
        entry, ctx["importer"], lots=[make_lot(6, 500), make_lot(4, 500)], api=api
    )
    assert bonded["bond_amount_cents"] == 500, (
        f"round(3000 x 0.10) + round(2000 x 0.10) must be 500, got "
        f"{bonded['bond_amount_cents']}"
    )
    assert bonded["units_held"] == 10
    assert_entry_units_conserved(bonded)

    # Split outcome: 6 passed / 4 failed -> any failure makes it a refusal.
    outcome = record_reconditioning_outcome(bonded, 6, 4, api=api)
    assert outcome["units_released"] == 6
    assert outcome["units_destroyed"] == 4
    assert outcome["units_held"] == 0
    assert_entry_units_conserved(outcome)
    assert outcome["disposition_status"] == "REFUSED"
    f = get_facility(ctx["facility"]["id"], api=api)
    assert f["violation_count"] == 1
    assert f["open_detention_count"] == 0
