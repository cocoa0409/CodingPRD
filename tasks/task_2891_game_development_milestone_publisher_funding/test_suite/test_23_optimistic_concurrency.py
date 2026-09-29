"""The two version-guarded writes: change-order creation and royalty-statement
creation, each of which silently supersedes a row and so cannot be guarded by any
state precondition.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal
from test_helpers.fixtures import DEFAULT_CRITERIA_1, setup_single_alpha


def test_corner_occ_change_order_create_rejects_a_stale_agreement_version(api):
    """The same proposal body is refused with 412 on the pre-write version and
    accepted once the version is re-read, and the accepted second proposal is what
    supersedes the first.

    PRD §2.7 says "Two write operations require the client to prove it is working
    from a current view of the agreement, because in both cases a fresh write
    legitimately supersedes an existing row and therefore cannot be blocked by any
    state precondition. Both use the same mechanism: a mandatory
    `expected_agreement_version` field in the request body carrying the `version`
    of the parent `DevelopmentAgreement` as the client last observed it. If that
    value does not equal the agreement's current `version`, the request is
    rejected with `ERR_STALE_AGREEMENT_VERSION` and HTTP 412, and nothing is
    written." PRD §3.7 supplies the cascade being guarded: "A proposal is written
    in state `PROPOSED`, and creating it cascades: any other change order with the
    same `target_milestone_id` still sitting in `PROPOSED` is moved to
    `SUPERSEDED` immediately ... The agreement's `version` increments on creation,
    which is exactly why the version check exists: without it a client could
    unknowingly displace a proposal it had never read."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_change_order_create_rejects_a_stale_agreement_version
    """
    scenario = setup_single_alpha(
        api,
        title="Aurora Solo",
        advance_total_cents=3600000,
        contractor_budget_cents=0,
        acceptance_criteria=DEFAULT_CRITERIA_1,
        live_ops_quarterly_funding_cents=100000,
    )
    reg = scenario.reg
    v_read = scenario.agreement["version"]

    first = validate_success(
        api.create_change_order(
            f.change_order_payload(
                scenario.agreement_id, scenario.m1["id"], "FUNDING_UPLIFT", v_read,
                "First proposal on a freshly read version",
                requested_amount_cents=200000, ship_date_delta_days=0,
            ),
            reg.dev,
        ),
        expected_status=201,
    )
    assert first["state"] == "PROPOSED", first
    after_first = scenario.read_agreement()["version"]
    assert after_first == v_read + 1, (
        f"creation must increment the agreement version once: {v_read} -> {after_first}"
    )

    # The blind supersede attempt still names the pre-write version.
    validate_error(
        api.create_change_order(
            f.change_order_payload(
                scenario.agreement_id, scenario.m1["id"], "FUNDING_UPLIFT", v_read,
                "Blind supersede attempt on the pre-write version",
                requested_amount_cents=350000, ship_date_delta_days=0,
            ),
            reg.finance,
        ),
        "ERR_STALE_AGREEMENT_VERSION",
        412,
    )
    assert validate_success(api.get_change_order(first["id"], reg.finance))["state"] == (
        "PROPOSED"
    ), "the refused write superseded the proposal anyway"
    only_row = get_success_data(
        api.list_change_orders(reg.finance, {"agreement_id": scenario.agreement_id})
    )
    assert len(only_row) == 1 and only_row[0]["id"] == first["id"], only_row
    assert scenario.read_agreement()["version"] == after_first, (
        "the refused write moved the agreement version"
    )

    v_fresh = scenario.read_agreement()["version"]
    second = validate_success(
        api.create_change_order(
            f.change_order_payload(
                scenario.agreement_id, scenario.m1["id"], "FUNDING_UPLIFT", v_fresh,
                "Informed supersede on the current version",
                requested_amount_cents=350000, ship_date_delta_days=0,
            ),
            reg.dev,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        second,
        {"requested_amount_cents": 350000, "state": "PROPOSED"},
        "second change order",
    )
    assert scenario.read_agreement()["version"] == v_fresh + 1

    superseded = validate_success(api.get_change_order(first["id"], reg.finance))
    assert superseded["state"] == "SUPERSEDED", superseded

    rows = get_success_data(
        api.list_change_orders(reg.finance, {"agreement_id": scenario.agreement_id})
    )
    assert len(rows) == 2, rows
    assert [r["state"] for r in rows].count("PROPOSED") == 1, rows


def test_corner_occ_royalty_statement_create_rejects_a_stale_agreement_version(api):
    """Two statements for the identical `period_label` are separated only by the
    version they carry: the stale one is refused with 412, the informed one is
    written and supersedes the first, whose provisional figures stay frozen.

    PRD §2.7 says "If that value does not equal the agreement's current `version`,
    the request is rejected with `ERR_STALE_AGREEMENT_VERSION` and HTTP 412, and
    nothing is written", and PRD §2.10 rule 21 scopes the check to "change-order
    creation and royalty-statement creation". PRD §3.9 supplies the cascade:
    "Creation also cascades: any other statement of the same agreement and the
    same `period_label` still in `DRAFT` moves to `SUPERSEDED`, and a superseded
    statement can never be finalized. The agreement's `version` increments." The
    figures follow the §3.9 provisional waterfall: a 1000000 net less its 3000 bps
    platform fee distributes 700000, and with nothing recouped the royalty base is
    also 700000, of which 2500 bps is 175000; the 800000 line distributes 560000
    and yields 140000.

    Design: Corner/cross_cutting_complexity_layers/corner_occ_royalty_statement_create_rejects_a_stale_agreement_version
    """
    scenario = setup_single_alpha(
        api,
        title="Ledgerline",
        advance_total_cents=3600000,
        contractor_budget_cents=0,
        acceptance_criteria=DEFAULT_CRITERIA_1,
        live_ops_quarterly_funding_cents=100000,
    )
    reg = scenario.reg
    v_read = scenario.agreement["version"]
    assert scenario.read_agreement()["unrecouped_advance_cents"] == 0

    first = validate_success(
        api.create_royalty_statement(
            f.royalty_statement_payload(
                scenario.agreement_id, "2027-Q1", v_read,
                [f.revenue_line("PC-GLOBAL", 1000000, 0)], 0,
            ),
            reg.finance,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        first,
        {
            "state": "DRAFT",
            "distributable_total_cents": 700000,
            "provisional_royalty_payable_cents": 175000,
        },
        "first statement",
    )

    validate_error(
        api.create_royalty_statement(
            f.royalty_statement_payload(
                scenario.agreement_id, "2027-Q1", v_read,
                [f.revenue_line("PC-GLOBAL", 800000, 0)], 0,
            ),
            reg.finance,
        ),
        "ERR_STALE_AGREEMENT_VERSION",
        412,
    )
    assert validate_success(api.get_royalty_statement(first["id"], reg.finance))["state"] == (
        "DRAFT"
    ), "the refused write superseded the DRAFT anyway"
    assert len(
        get_success_data(
            api.list_agreement_royalty_statements(scenario.agreement_id, reg.finance)
        )
    ) == 1

    v_fresh = scenario.read_agreement()["version"]
    second = validate_success(
        api.create_royalty_statement(
            f.royalty_statement_payload(
                scenario.agreement_id, "2027-Q1", v_fresh,
                [f.revenue_line("PC-GLOBAL", 800000, 0)], 0,
            ),
            reg.finance,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        second,
        {
            "state": "DRAFT",
            "distributable_total_cents": 560000,
            "provisional_royalty_payable_cents": 140000,
        },
        "second statement",
    )

    frozen = validate_success(api.get_royalty_statement(first["id"], reg.dev))
    assert_fields_equal(
        frozen,
        {
            "state": "SUPERSEDED",
            "distributable_total_cents": 700000,
            "provisional_royalty_payable_cents": 175000,
        },
        "superseded statement",
    )

    rows = get_success_data(
        api.list_agreement_royalty_statements(scenario.agreement_id, reg.finance)
    )
    assert len(rows) == 2, rows
    assert [r["state"] for r in rows].count("DRAFT") == 1, rows
