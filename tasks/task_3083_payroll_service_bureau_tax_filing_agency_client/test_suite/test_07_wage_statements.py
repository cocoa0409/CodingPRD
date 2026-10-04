"""Year-end wage statements, correction chains, and annual summaries (PRD §3.10)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_wage_statement_payload,
    get_success_data,
    make_client_admin_headers,
    set_clock,
    setup_active_client,
    validate_error,
    validate_paginated,
    validate_success,
)


def _create_statement(client_id, **overrides):
    return get_success_data(
        api_client.create_wage_statement(
            create_wage_statement_payload(client_id=client_id, **overrides),
            TEST_USERS["filer_alpha_headers"],
        )
    )


def test_wage_summary_as_issued_vs_as_filed_history():
    """PRD §3.10: "The default **as-issued view** reports `total_wages_cents` and
    `total_withheld_cents` as the sums over `ISSUED` statements only,
    `active_statement_count` as the number of `ISSUED` statements, and
    `voided_total_cents` as the sum of `wages_cents` over `VOIDED` statements —
    always reported, but excluded from the totals."
    PRD §3.10: "Passing `include_voided` as true selects the **as-filed-history
    view**, an audit perspective that folds the `VOIDED` rows into
    `total_wages_cents` and `total_withheld_cents` as well."

    Design: Difficulty/dual_variant_calc/wage_summary_as_issued_vs_as_filed_history
    """
    setup = setup_active_client()
    client = setup["client"]
    set_clock("2027-01-15T00:00:00Z")  # tax year 2026 closed

    orig = _create_statement(
        client["id"], employee_ref="E-100", wages_cents=5000000, withheld_cents=1000000
    )
    validate_success(
        api_client.issue_wage_statement(orig["id"], TEST_USERS["filer_alpha_headers"])
    )
    corr = _create_statement(
        client["id"],
        employee_ref="E-100",
        wages_cents=6000000,
        withheld_cents=1200000,
        corrects_statement_id=orig["id"],
    )
    validate_success(
        api_client.issue_wage_statement(corr["id"], TEST_USERS["filer_alpha_headers"])
    )
    validate_success(
        api_client.void_wage_statement(orig["id"], TEST_USERS["filer_alpha_headers"])
    )
    e200 = _create_statement(
        client["id"], employee_ref="E-200", wages_cents=3000000, withheld_cents=600000
    )
    validate_success(
        api_client.issue_wage_statement(e200["id"], TEST_USERS["filer_alpha_headers"])
    )

    summary = validate_success(
        api_client.wage_statement_summary(
            client["id"], TEST_USERS["filer_alpha_headers"], params={"tax_year": 2026}
        )
    )
    assert summary["total_wages_cents"] == 9000000  # 6000000 corr + 3000000 E-200
    assert summary["total_withheld_cents"] == 1800000
    assert summary["active_statement_count"] == 2
    assert summary["voided_total_cents"] == 5000000

    history = validate_success(
        api_client.wage_statement_summary(
            client["id"],
            TEST_USERS["filer_alpha_headers"],
            params={"tax_year": 2026, "include_voided": "true"},
        )
    )
    assert history["total_wages_cents"] == 14000000  # 9000000 + 5000000 voided
    assert history["total_withheld_cents"] == 2800000
    assert history["total_wages_cents"] != summary["total_wages_cents"]


def test_wage_summary_counts_only_issued_statements():
    """PRD §3.10: "A statement counts as active for summary purposes exactly when
    its status is `ISSUED` — `CORRECTED` rows are superseded predecessors, `DRAFT`
    rows are unpublished, and `VOIDED` rows are dead."

    Design: Difficulty/dual_variant_calc/wage_summary_as_issued_vs_as_filed_history
    """
    setup = setup_active_client()
    client = setup["client"]
    set_clock("2027-01-15T00:00:00Z")
    # DRAFT statement must not contribute.
    _create_statement(
        client["id"], employee_ref="E-300", wages_cents=111111, withheld_cents=22222
    )
    issued = _create_statement(
        client["id"], employee_ref="E-400", wages_cents=700000, withheld_cents=140000
    )
    validate_success(
        api_client.issue_wage_statement(issued["id"], TEST_USERS["filer_alpha_headers"])
    )
    summary = validate_success(
        api_client.wage_statement_summary(
            client["id"], TEST_USERS["filer_alpha_headers"], params={"tax_year": 2026}
        )
    )
    assert summary["total_wages_cents"] == 700000
    assert summary["total_withheld_cents"] == 140000
    assert summary["active_statement_count"] == 1
    assert summary["voided_total_cents"] == 0


def test_correction_cycle_conserves_active_statement_count_per_key():
    """PRD §3.10: "Issuing a `CORRECTION` additionally flips its target statement
    from `ISSUED` to `CORRECTED` in the same transition, so exactly one statement
    is ever active per employee key — the correction chain can extend further
    (issue original, issue correction, issue a correction of the correction) and
    only the newest issued row remains active."

    Design: Difficulty/compensating_invariant/correction_cycle_conserves_active_statement_count_per_key
    """
    setup = setup_active_client()
    client = setup["client"]
    set_clock("2027-01-15T00:00:00Z")

    s1 = _create_statement(
        client["id"], employee_ref="E-100", wages_cents=5000000, withheld_cents=1000000
    )
    validate_success(
        api_client.issue_wage_statement(s1["id"], TEST_USERS["filer_alpha_headers"])
    )
    s2 = _create_statement(
        client["id"],
        employee_ref="E-100",
        wages_cents=6000000,
        withheld_cents=1200000,
        corrects_statement_id=s1["id"],
    )
    validate_success(
        api_client.issue_wage_statement(s2["id"], TEST_USERS["filer_alpha_headers"])
    )
    s3 = _create_statement(
        client["id"],
        employee_ref="E-100",
        wages_cents=6500000,
        withheld_cents=1300000,
        corrects_statement_id=s2["id"],
    )
    validate_success(
        api_client.issue_wage_statement(s3["id"], TEST_USERS["filer_alpha_headers"])
    )

    st1 = validate_success(
        api_client.get_wage_statement(s1["id"], TEST_USERS["filer_alpha_headers"])
    )
    st2 = validate_success(
        api_client.get_wage_statement(s2["id"], TEST_USERS["filer_alpha_headers"])
    )
    st3 = validate_success(
        api_client.get_wage_statement(s3["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert st1["status"] == "CORRECTED"
    assert st2["status"] == "CORRECTED"
    assert st3["status"] == "ISSUED"
    assert st3["corrects_statement_id"] == s2["id"]

    summary = validate_success(
        api_client.wage_statement_summary(
            client["id"], TEST_USERS["filer_alpha_headers"], params={"tax_year": 2026}
        )
    )
    assert summary["active_statement_count"] == 1
    assert summary["total_wages_cents"] == 6500000

    rows, meta = validate_paginated(
        api_client.list_wage_statements(
            TEST_USERS["filer_alpha_headers"],
            params={"client_id": client["id"], "tax_year": 2026, "employee_ref": "E-100"},
        )
    )
    assert meta["total_count"] == 3  # history preserved


def test_correction_flips_target_in_same_transition():
    """PRD §3.10: "Issuing a `CORRECTION` additionally flips its target statement
    from `ISSUED` to `CORRECTED` in the same transition, so exactly one statement
    is ever active per employee key."

    Design: Difficulty/compensating_invariant/correction_cycle_conserves_active_statement_count_per_key
    """
    setup = setup_active_client()
    client = setup["client"]
    set_clock("2027-01-15T00:00:00Z")
    orig = _create_statement(
        client["id"], employee_ref="E-100", wages_cents=5000000, withheld_cents=1000000
    )
    validate_success(
        api_client.issue_wage_statement(orig["id"], TEST_USERS["filer_alpha_headers"])
    )
    corr = _create_statement(
        client["id"],
        employee_ref="E-100",
        wages_cents=5500000,
        withheld_cents=1100000,
        corrects_statement_id=orig["id"],
    )
    validate_success(
        api_client.issue_wage_statement(corr["id"], TEST_USERS["filer_alpha_headers"])
    )
    target = validate_success(
        api_client.get_wage_statement(orig["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert target["status"] == "CORRECTED"
    replacement = validate_success(
        api_client.get_wage_statement(corr["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert replacement["status"] == "ISSUED"
    summary = validate_success(
        api_client.wage_statement_summary(
            client["id"], TEST_USERS["filer_alpha_headers"], params={"tax_year": 2026}
        )
    )
    assert summary["active_statement_count"] == 1


def test_wage_statement_active_key_exclusion_vs_correction_channel():
    """PRD §3.10: "no other statement in `ISSUED` or `CORRECTED` status may
    already exist for the same (client, tax year, employee) key, else
    `ERR_DUPLICATE_ACTIVE_STATEMENT` (HTTP 409), a check that also applies when an
    `ORIGINAL` is created while one is active."
    PRD §3.10: "supplying `corrects_statement_id` sets `statement_kind` to
    `CORRECTION`, and the target of a correction must currently be `ISSUED` —
    targeting anything else is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/resource_temporal_overlap/wage_statement_active_key_exclusion_vs_correction_channel
    """
    setup = setup_active_client()
    client = setup["client"]
    set_clock("2027-01-15T00:00:00Z")
    orig = _create_statement(
        client["id"], employee_ref="E-100", wages_cents=5000000, withheld_cents=1000000
    )
    validate_success(
        api_client.issue_wage_statement(orig["id"], TEST_USERS["filer_alpha_headers"])
    )

    # A second ORIGINAL for the same key collides.
    resp = api_client.create_wage_statement(
        create_wage_statement_payload(
            client_id=client["id"],
            employee_ref="E-100",
            wages_cents=5500000,
            withheld_cents=1100000,
        ),
        TEST_USERS["filer_alpha_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_STATEMENT, 409)

    # The CORRECTION channel is admitted because it retires the incumbent.
    corr = get_success_data(
        api_client.create_wage_statement(
            create_wage_statement_payload(
                client_id=client["id"],
                employee_ref="E-100",
                wages_cents=6000000,
                withheld_cents=1200000,
                corrects_statement_id=orig["id"],
            ),
            TEST_USERS["filer_alpha_headers"],
        )
    )
    assert corr["statement_kind"] == "CORRECTION"
    assert corr["corrects_statement_id"] == orig["id"]
    validate_success(
        api_client.issue_wage_statement(corr["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert validate_success(
        api_client.get_wage_statement(orig["id"], TEST_USERS["filer_alpha_headers"])
    )["status"] == "CORRECTED"
    assert validate_success(
        api_client.get_wage_statement(corr["id"], TEST_USERS["filer_alpha_headers"])
    )["status"] == "ISSUED"
    summary = validate_success(
        api_client.wage_statement_summary(
            client["id"], TEST_USERS["filer_alpha_headers"], params={"tax_year": 2026}
        )
    )
    assert summary["active_statement_count"] == 1


def test_correction_target_must_be_issued():
    """PRD §3.10: "supplying `corrects_statement_id` sets `statement_kind` to
    `CORRECTION`, and the target of a correction must currently be `ISSUED` —
    targeting anything else is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/resource_temporal_overlap/wage_statement_active_key_exclusion_vs_correction_channel
    """
    setup = setup_active_client()
    client = setup["client"]
    set_clock("2027-01-15T00:00:00Z")
    draft = _create_statement(client["id"], employee_ref="E-100")  # never issued
    resp = api_client.create_wage_statement(
        create_wage_statement_payload(
            client_id=client["id"],
            employee_ref="E-100",
            corrects_statement_id=draft["id"],
        ),
        TEST_USERS["filer_alpha_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_year_end_statement_issue_before_jan1_rejected():
    """PRD §3.10: "the logical clock must be on or after January 1 of the year
    following the `tax_year` — an earlier attempt is rejected with
    `ERR_YEAR_NOT_CLOSED` (HTTP 409)."

    Design: Corner/validations/v_year_end_statement_issue_before_jan1_rejected
    """
    setup = setup_active_client()
    client = setup["client"]
    ws = _create_statement(
        client["id"], employee_ref="E-YNC", wages_cents=1000000, withheld_cents=200000
    )
    set_clock("2026-12-31T12:00:00Z")
    resp = api_client.issue_wage_statement(ws["id"], TEST_USERS["filer_alpha_headers"])
    validate_error(resp, ApiErrorId.ERR_YEAR_NOT_CLOSED, 409)
    set_clock("2027-01-01T00:00:00Z")
    issued = validate_success(
        api_client.issue_wage_statement(ws["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert issued["status"] == "ISSUED"


def test_statement_issue_on_jan1_boundary_succeeds():
    """PRD §3.10: "the logical clock must be on or after January 1 of the year
    following the `tax_year` — an earlier attempt is rejected with
    `ERR_YEAR_NOT_CLOSED` (HTTP 409)."

    Design: Corner/validations/v_year_end_statement_issue_before_jan1_rejected
    """
    setup = setup_active_client()
    client = setup["client"]
    ws = _create_statement(client["id"], employee_ref="E-BND")
    set_clock("2027-01-01T00:00:00Z")  # exactly the boundary instant
    issued = validate_success(
        api_client.issue_wage_statement(ws["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert issued["status"] == "ISSUED"
    assert issued.get("issued_at"), "issued_at stamped on issue"


def test_statement_create_status_input_ignored():
    """PRD §3.10: "New statements start in `DRAFT`."
    PRD §3.10: "A statement created without a `corrects_statement_id` has
    `statement_kind` `ORIGINAL`."

    Design: Corner/entities/e_statement_create_status_input_ignored
    """
    setup = setup_active_client()
    client = setup["client"]
    payload = create_wage_statement_payload(
        client_id=client["id"], employee_ref="E-9", wages_cents=100000, withheld_cents=20000
    )
    payload["status"] = "ISSUED"
    payload["version"] = 42
    resp = api_client.create_wage_statement(payload, TEST_USERS["filer_alpha_headers"])
    ws = validate_success(resp, expected_status=201)
    assert ws["status"] == "DRAFT"
    assert ws["statement_kind"] == "ORIGINAL"
    assert ws["version"] == 1


def test_statement_create_kind_input_ignored():
    """PRD §3.10: "New statements start in `DRAFT`."
    PRD §3.10: "A statement created without a `corrects_statement_id` has
    `statement_kind` `ORIGINAL`."

    Design: Corner/entities/e_statement_create_status_input_ignored
    """
    setup = setup_active_client()
    client = setup["client"]
    payload = create_wage_statement_payload(client_id=client["id"], employee_ref="E-10")
    payload["statement_kind"] = "CORRECTION"
    resp = api_client.create_wage_statement(payload, TEST_USERS["filer_alpha_headers"])
    ws = validate_success(resp, expected_status=201)
    assert ws["status"] == "DRAFT"
    assert ws["statement_kind"] == "ORIGINAL"
