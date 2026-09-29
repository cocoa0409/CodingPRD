"""What the endpoints themselves promise: a clock that really moves, reads that serve the
reconciled figures, and action routes that do only what they say.

Moving the logical clock changes what later temporal checks decide without recomputing a
single stored figure. A plain club read carries the score computed on another aggregate. A
guest batch is gated on the agreement's own flag, and closing a remediation file forgives
nothing.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    close_inspection,
    create_guest_usage_event_payload,
    create_member,
    create_royalty_report_payload,
    create_usage_settlement,
    inspect_club,
    make_club_manager_headers,
    make_franchise_owner_headers,
    post_dues,
    post_payment,
    read_agreement,
    read_club,
    read_franchisee,
    read_guest_usage_event,
    read_inspection,
    read_usage_settlement,
    record_guest_usage,
    set_clock_date,
    setup_home_and_host_clubs,
    setup_single_club_franchise,
    sign_active_agreement,
    sign_agreement,
)

BRAND = TEST_USERS["brand_administrator_headers"]


def _one_operator_with_one_paid_membership() -> dict:
    """A 650-bps operator with one OPEN CA club and one ACTIVE undiscounted membership whose
    August dues are settled in full."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
    )
    scenario["member"] = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    scenario["agreement"] = sign_active_agreement(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        due_on="2026-09-05",
    )
    return scenario


def _report_august(scenario: dict, reported_member_count: int = 1):
    return api_client.create_royalty_report(
        create_royalty_report_payload(
            scenario["franchisee"]["id"], "2026-08", reported_member_count
        ),
        make_franchise_owner_headers(scenario["franchisee"]["id"]),
    )


def _unpaid_charge_falling_due_in_september() -> dict:
    """One signed membership carrying a single 4500-cent charge due 2026-09-05 and no payment
    at all, so its ageing depends entirely on where the clock stands."""
    scenario = setup_single_club_franchise(
        legal_name="Ridgeway Athletics LLC",
        contact_email="ops@ridgewayath.example",
        club_name="Ridgeway Valley",
        opened_on="2024-06-01",
    )
    member = create_member(
        scenario["club"]["id"], full_name="Ben Oduya", email="ben.oduya@example.com"
    )
    scenario["agreement"] = sign_agreement(
        member["id"], scenario["club"]["id"], scenario["plan_template"]["id"]
    )
    post_dues(scenario["agreement"]["id"], 4500, occurred_on="2026-08-01", due_on="2026-09-05")
    return scenario


def _club_with_one_passing_inspection() -> dict:
    """A modern club inspected at 95 / 92 / 90 against a 12-month worst equipment age, which
    is a passing score on the standard refresh cycle."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
        with_plan=False,
    )
    scenario["inspection"] = inspect_club(scenario["club"]["id"], "2026-07-15", 95, 92, 90, 12)
    return scenario


def _membership_at_a_club_with_a_sibling(multi_club_access: bool) -> dict:
    """One franchisee with two OPEN CA clubs and one membership homed at the first, holding or
    lacking the multi-club right."""
    scenario = setup_home_and_host_clubs(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        home_club_name="Harborline Downtown",
        host_club_name="Harborline Northside",
    )
    scenario["member"] = create_member(
        scenario["home_club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    scenario["agreement"] = sign_active_agreement(
        scenario["member"]["id"],
        scenario["home_club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=multi_club_access,
    )
    return scenario


def _record_visits(scenario: dict, visit_count: int = 4):
    payload = create_guest_usage_event_payload(
        scenario["agreement"]["id"],
        scenario["host_club"]["id"],
        "2026-08",
        visit_count,
    )
    return api_client.create_guest_usage_event(
        payload, make_club_manager_headers(scenario["host_club"]["id"])
    )


def test_the_period_that_was_still_running_becomes_reportable_once_the_clock_moves():
    """At startup the clock stands inside 2026-08 and the report is refused; the only thing
    that changes before the accepted filing is where the clock stands.

    PRD 2.4: "The service never falls back to real wall-clock time. At server startup the
    logical clock reads exactly `2026-08-01T00:00:00Z`, and it continues to read that value
    until a `BrandAdministrator` moves it."

    Design: Corner/endpoints/corner_clock_action_moves_the_logical_now_for_every_later_read
    """
    scenario = _one_operator_with_one_paid_membership()

    refused = _report_august(scenario)
    assert refused.status_code == 409
    set_clock_date("2026-09-05")
    accepted = validate_success(_report_august(scenario), expected_status=201)
    assert accepted["period_month"] == "2026-08"
    assert accepted["status"] == "ACCEPTED"


def test_moving_the_clock_recomputes_no_stored_figure_by_itself():
    """The charge falls due on 2026-09-05 and the clock jumps a month past it, yet nothing
    re-runs, so the membership's stored ageing figures stand exactly where the last append
    left them.

    PRD 2.4: "The clock may be advanced or rewound freely, and moving it re-derives nothing:
    no stored balance, counter, score, or status is recomputed as a side effect of a clock
    move. Ageing therefore only becomes visible the next time some business operation re-runs
    a projection or evaluates a window."

    Design: Corner/endpoints/corner_clock_action_moves_the_logical_now_for_every_later_read
    """
    scenario = _unpaid_charge_falling_due_in_september()
    before = read_agreement(scenario["agreement"]["id"])

    set_clock_date("2026-10-06")
    after = read_agreement(scenario["agreement"]["id"])
    assert after["delinquency_days"] == before["delinquency_days"] == 0
    assert after["dues_status"] == before["dues_status"] == "CURRENT"
    assert after["outstanding_balance_cents"] == before["outstanding_balance_cents"] == 4500


def test_the_plain_club_read_serves_the_score_computed_on_the_inspection():
    """The figure was derived while scoring a different aggregate, and the club's own
    retrieval path hands back the reconciled trio rather than a stale snapshot.

    PRD 3.9: "The club's `last_inspection_score` is set to the new `score`, and its
    `equipment_compliance_state` is re-derived from that score alone: `COMPLIANT` at 85 or
    above, `WATCH` at 70 through 84, and `NON_COMPLIANT` below 70. A club that has just become
    `NON_COMPLIANT` and was `OPEN` moves to `SUSPENDED`; a club that was `SUSPENDED` and has
    just scored 70 or better moves back to `OPEN`."

    Design: Corner/endpoints/corner_get_club_computed_read_reflects_the_latest_inspection
    """
    scenario = _club_with_one_passing_inspection()

    club = validate_success(
        api_client.get_club(
            scenario["club"]["id"],
            make_franchise_owner_headers(scenario["franchisee"]["id"]),
        )
    )
    assert club["last_inspection_score"] == 91
    assert club["equipment_compliance_state"] == "COMPLIANT"
    assert club["status"] == "OPEN"
    assert club["franchisee_id"] == scenario["franchisee"]["id"]
    assert club["state_code"] == "CA"


def test_the_score_behind_that_read_is_the_weighted_sum_rounded_once():
    """38 plus 23 plus 18 plus 12 lands on 91 exactly, with the refresh term already an
    integer before it is weighted.

    PRD 3.9: "The `score` is then a single weighted sum, rounded half up to an integer exactly
    once, at the very end: `equipment_condition_pts` weighted at 0.40, plus `cleanliness_pts`
    at 0.25, plus `safety_pts` at 0.20, plus `refresh_pts` at 0.15."

    Design: Corner/endpoints/corner_get_club_computed_read_reflects_the_latest_inspection
    """
    scenario = _club_with_one_passing_inspection()

    inspection = read_inspection(scenario["inspection"]["id"])
    assert inspection["equipment_condition_pts"] == 95
    assert inspection["cleanliness_pts"] == 92
    assert inspection["safety_pts"] == 90
    assert inspection["refresh_pts"] == 80
    assert inspection["score"] == 91


def test_a_passing_inspection_files_itself_away_without_remediation():
    """91 is comfortably above the 70 mark, so the inspection resolves straight to its
    terminal state instead of demanding rework.

    PRD 3.9: "Finally the inspection auto-resolves: `SCORED → CLOSED` when the `score` is 70
    or higher, and `SCORED → REMEDIATION_REQUIRED` when it is below 70."

    Design: Corner/endpoints/corner_get_club_computed_read_reflects_the_latest_inspection
    """
    scenario = _club_with_one_passing_inspection()

    inspection = read_inspection(scenario["inspection"]["id"])
    assert inspection["status"] == "CLOSED"
    assert inspection["scored_by_user_id"] == "auditor-1"
    assert inspection["waived_by_user_id"] is None


def test_the_operator_behind_the_passing_club_keeps_a_perfect_standing():
    """No failing inspection, no club on collections watch and no disputed report means no
    penalty at all is subtracted from the starting hundred.

    PRD 3.9: "`compliance_score` then starts at 100 and subtracts 20 for each step of
    `inspection_fail_streak`, a flat 20 if `collections_watch_club_count` is greater than
    zero — one flat penalty no matter how many clubs are on watch, not 20 per club — and 10
    for each disputed royalty report, with the result clamped into 0 through 100."

    Design: Corner/endpoints/corner_get_club_computed_read_reflects_the_latest_inspection
    """
    scenario = _club_with_one_passing_inspection()

    franchisee = read_franchisee(scenario["franchisee"]["id"])
    assert franchisee["inspection_fail_streak"] == 0
    assert franchisee["collections_watch_club_count"] == 0
    assert franchisee["disputed_royalty_count"] == 0
    assert franchisee["compliance_score"] == 100
    assert franchisee["status"] == "ACTIVE"


def test_a_guest_batch_is_refused_when_the_agreement_lacks_multi_club_access():
    """Both clubs are open and compliant and the membership is active and paid up; the only
    thing missing is the right the agreement was sold without.

    PRD 3.7: "Recording is refused in three circumstances. If the agreement does not carry
    `multi_club_access` as true, or if the supplied `host_club_id` equals the agreement's
    current `home_club_id` — you cannot be a guest at your own club — the request is refused
    with `ERR_GUEST_VISIT_NOT_ALLOWED`."

    Design: Corner/endpoints/corner_guest_usage_event_requires_multi_club_access_on_the_agreement
    """
    scenario = _membership_at_a_club_with_a_sibling(multi_club_access=False)

    assert scenario["agreement"]["multi_club_access"] is False
    validate_error(_record_visits(scenario), ApiErrorId.ERR_GUEST_VISIT_NOT_ALLOWED.value)


def test_the_flag_is_the_only_difference_and_it_costs_one_and_a_half_percent():
    """The same membership sold with the multi-club right carries a 68-cent credit against a
    4500-cent list price, which is what the right is paid for.

    PRD 3.3: "`multi_club_credit_cents` is 0 when `multi_club_access` is false and otherwise
    the base multiplied by the multi-club credit rate of 0.015 — one and a half percent —
    rounded half up."

    Design: Corner/endpoints/corner_guest_usage_event_requires_multi_club_access_on_the_agreement
    """
    scenario = _membership_at_a_club_with_a_sibling(multi_club_access=False)
    without = scenario["agreement"]
    # A second member at the same club on the same published template, so the multi-club
    # flag really is the only difference between the two signings. Building a whole second
    # franchise instead would put a rival operator's circle on top of this one, which the
    # brand's radius protection correctly refuses.
    second_member = create_member(
        scenario["home_club"]["id"], full_name="Bruno Salas", email="bruno.salas@example.com"
    )
    with_access = sign_active_agreement(
        second_member["id"],
        scenario["home_club"]["id"],
        scenario["plan_template"]["id"],
        multi_club_access=True,
    )

    assert without["multi_club_credit_cents"] == 0
    assert without["effective_monthly_dues_cents"] == 4500
    assert with_access["multi_club_credit_cents"] == 68
    assert with_access["effective_monthly_dues_cents"] == 4432


def test_the_same_batch_is_recorded_once_the_agreement_carries_the_right():
    """With the flag set the visit batch is accepted and snapshots the host club's fee and the
    home club of the moment, unsettled until a settlement claims it.

    PRD 3.7: "`guest_fee_cents_at_visit` captures the host club's `guest_fee_cents` as it
    stands at that instant. And `usage_fee_cents` is `visit_count` multiplied by
    `guest_fee_cents_at_visit`. The batch is created unsettled, with `settlement_id` null, and
    it is immutable: it has no `version`, no `updated_at`, and no update operation."

    Design: Corner/endpoints/corner_guest_usage_event_requires_multi_club_access_on_the_agreement
    """
    scenario = _membership_at_a_club_with_a_sibling(multi_club_access=True)

    batch = validate_success(_record_visits(scenario), expected_status=201)
    assert batch["guest_fee_cents_at_visit"] == 1250
    assert batch["visit_count"] == 4
    assert batch["usage_fee_cents"] == 5000
    assert batch["home_club_id_at_visit"] == scenario["home_club"]["id"]
    assert batch["settlement_id"] is None


def _july_and_august_visits_at_a_sibling_club() -> dict:
    """A multi-club membership signed on 2026-07-01 that visits its sibling club once in July
    and twice in August, then an August settlement raised over the pair."""
    set_clock_date("2026-07-01")
    scenario = setup_home_and_host_clubs(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        home_club_name="Harborline Downtown",
        host_club_name="Harborline Northside",
    )
    scenario["member"] = create_member(
        scenario["home_club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    scenario["agreement"] = sign_agreement(
        scenario["member"]["id"],
        scenario["home_club"]["id"],
        scenario["plan_template"]["id"],
        signed_on="2026-07-01",
        multi_club_access=True,
    )
    agreement_id = scenario["agreement"]["id"]
    host_club_id = scenario["host_club"]["id"]
    scenario["july_batch"] = record_guest_usage(agreement_id, host_club_id, "2026-07", 10)
    set_clock_date("2026-08-01")
    scenario["first_august_batch"] = record_guest_usage(
        agreement_id, host_club_id, "2026-08", 50
    )
    scenario["second_august_batch"] = record_guest_usage(
        agreement_id, host_club_id, "2026-08", 34
    )
    scenario["settlement"] = create_usage_settlement(
        "2026-08", scenario["home_club"]["id"], host_club_id
    )
    return scenario


def test_the_settlement_names_the_paying_and_credited_clubs_and_skips_the_other_month():
    """The July batch sits at the same club pair with a null settlement flag and is left
    untouched, because its period does not match the settlement's month.

    PRD 3.7: "Creating a settlement names the `period_month`, the `home_club_id` that will
    pay, and the `host_club_id` that will be credited. The two must differ, or the request is
    refused with `ERR_SAME_CLUB_TRANSFER`. Only one settlement may exist per `period_month`,
    `home_club_id` and `host_club_id` triple: a second attempt while an `OPEN` or `POSTED`
    settlement already covers that triple is refused with `ERR_DUPLICATE_SETTLEMENT_PERIOD`.
    The sweep collects every guest usage batch whose `settlement_id` is null, whose
    `period_month` matches, whose `host_club_id` matches, and whose `home_club_id_at_visit`
    matches the settlement's `home_club_id`, considered in ascending `created_at` order."

    Design: Corner/endpoints/corner_settlement_create_links_both_clubs_and_sweeps_only_the_matching_period
    """
    scenario = _july_and_august_visits_at_a_sibling_club()

    settlement = scenario["settlement"]
    assert settlement["period_month"] == "2026-08"
    assert settlement["home_club_id"] == scenario["home_club"]["id"]
    assert settlement["host_club_id"] == scenario["host_club"]["id"]
    july = read_guest_usage_event(scenario["july_batch"]["id"])
    assert july["period_month"] == "2026-07"
    assert july["settlement_id"] is None


def test_the_settlement_waterfall_runs_gross_hold_net_tier_then_rebate():
    """84 visits at 1250 cents gross 105000; the hold is 8400, the net 96600 lands in the
    middle tier, and only then is the 3 percent rebate taken.

    PRD 3.7: "`event_count` is the number of swept rows and `visit_count` is the sum of their
    visit counts. `gross_fee_cents` is the sum of their `usage_fee_cents`. Step one, the
    brand's administration hold: `admin_hold_cents` is `gross_fee_cents` multiplied by 0.08 —
    eight percent — rounded half up to whole cents. Step two: `net_before_rebate_cents` is
    `gross_fee_cents` minus `admin_hold_cents`. Step three, tier selection, which is keyed on
    `net_before_rebate_cents` and on nothing else — never on `gross_fee_cents` and never on the
    final payable: `rebate_pct` is 0.00 when `net_before_rebate_cents` is below 50000 cents,
    0.03 when it is at least 50000 but below 100000 cents, and 0.06 when it is at or above
    100000 cents. Step four, and only now: `volume_rebate_cents` is `net_before_rebate_cents`
    multiplied by `rebate_pct`, rounded half up to whole cents. Finally `net_payable_cents` is
    `net_before_rebate_cents` minus `volume_rebate_cents`."

    Design: Corner/endpoints/corner_settlement_create_links_both_clubs_and_sweeps_only_the_matching_period
    """
    scenario = _july_and_august_visits_at_a_sibling_club()

    settlement = read_usage_settlement(scenario["settlement"]["id"])
    assert settlement["event_count"] == 2
    assert settlement["visit_count"] == 84
    assert settlement["gross_fee_cents"] == 105000
    assert settlement["admin_hold_cents"] == 8400
    assert settlement["net_before_rebate_cents"] == 96600
    assert settlement["rebate_pct"] == 0.03
    assert settlement["volume_rebate_cents"] == 2898
    assert settlement["net_payable_cents"] == 93702


def test_creation_stamps_every_swept_batch_and_moves_no_money_yet():
    """Both August batches now carry the settlement's identifier while the settlement itself
    is still an unposted claim.

    PRD 3.7: "Creation stamps the new settlement's identifier into the `settlement_id` of every
    swept batch and leaves the settlement `OPEN`, with `posted_on` and `reversed_on` null. No
    money has moved yet."

    Design: Corner/endpoints/corner_settlement_create_links_both_clubs_and_sweeps_only_the_matching_period
    """
    scenario = _july_and_august_visits_at_a_sibling_club()
    settlement_id = scenario["settlement"]["id"]

    for key in ("first_august_batch", "second_august_batch"):
        batch = read_guest_usage_event(scenario[key]["id"])
        assert batch["settlement_id"] == settlement_id
    settlement = read_usage_settlement(settlement_id)
    assert settlement["status"] == "OPEN"
    assert settlement["posted_on"] is None
    assert settlement["reversed_on"] is None
    assert read_club(scenario["home_club"]["id"])["settlement_ledger_cents"] == 0
    assert read_club(scenario["host_club"]["id"])["settlement_ledger_cents"] == 0


def test_each_swept_batch_priced_itself_at_the_fee_of_its_own_moment():
    """Ten, fifty and thirty-four visits at the host club's 1250-cent fee price out at 12500,
    62500 and 42500 cents.

    PRD 3.7: "`guest_fee_cents_at_visit` captures the host club's `guest_fee_cents` as it
    stands at that instant. And `usage_fee_cents` is `visit_count` multiplied by
    `guest_fee_cents_at_visit`."

    Design: Corner/endpoints/corner_settlement_create_links_both_clubs_and_sweeps_only_the_matching_period
    """
    scenario = _july_and_august_visits_at_a_sibling_club()

    expected = {"july_batch": 12500, "first_august_batch": 62500, "second_august_batch": 42500}
    for key, usage_fee_cents in expected.items():
        batch = read_guest_usage_event(scenario[key]["id"])
        assert batch["guest_fee_cents_at_visit"] == 1250
        assert batch["usage_fee_cents"] == usage_fee_cents


def _one_ledger_of_three_rows_beside_a_ledger_of_one() -> dict:
    """Two memberships at the same club: the first carries a charge and two part payments, the
    second only its opening charge."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
    )
    club_id = scenario["club"]["id"]
    plan_id = scenario["plan_template"]["id"]
    ana = create_member(club_id, full_name="Ana Reyes", email="ana.reyes@example.com")
    ben = create_member(club_id, full_name="Ben Oduya", email="ben.oduya@example.com")
    scenario["busy_agreement"] = sign_agreement(ana["id"], club_id, plan_id)
    scenario["quiet_agreement"] = sign_agreement(ben["id"], club_id, plan_id)
    busy_id = scenario["busy_agreement"]["id"]
    post_dues(busy_id, 4500, occurred_on="2026-08-01", due_on="2026-08-05")
    post_payment(busy_id, 2000, occurred_on="2026-08-02")
    post_payment(busy_id, 2500, occurred_on="2026-08-03")
    post_dues(
        scenario["quiet_agreement"]["id"], 4500, occurred_on="2026-08-01", due_on="2026-08-05"
    )
    return scenario


def test_the_nested_ledger_page_counts_only_the_rows_matching_its_scope():
    """Four ledger rows exist in the database and the busy membership's own page reports three,
    which is the count after its scope is applied and before any window.

    PRD 2.3: "List responses order their rows by `created_at` ascending — oldest record first —
    and this is the only ordering any list endpoint applies unless its own description in §4
    names a different one. The `meta` object of a list response carries `limit`, `offset`,
    `total_count` (the number of rows matching the filters before the page window is applied)
    and `has_more` (true when rows remain beyond the current window)."

    Design: Corner/endpoints/corner_agreement_billing_event_sub_resource_lists_only_its_own_ledger
    """
    scenario = _one_ledger_of_three_rows_beside_a_ledger_of_one()

    rows, meta = validate_paginated(
        api_client.list_agreement_billing_events(scenario["busy_agreement"]["id"], BRAND)
    )
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert len(rows) == 3


def test_the_nested_ledger_serves_its_own_rows_in_canonical_order():
    """Each membership sees exactly its own entries, oldest processing date first, with the
    neighbouring membership's charge nowhere in sight.

    PRD 3.4: "The full ledger of one agreement can be listed in its canonical ascending
    `occurred_on`, then ascending `created_at` order, and that listing is the only place the
    system-generated `TRANSFER_FEE_POSTED` and `COLLECTION_PLACED` rows become visible, since no
    creation response ever returns them."

    Design: Corner/endpoints/corner_agreement_billing_event_sub_resource_lists_only_its_own_ledger
    """
    scenario = _one_ledger_of_three_rows_beside_a_ledger_of_one()
    busy_id = scenario["busy_agreement"]["id"]
    quiet_id = scenario["quiet_agreement"]["id"]

    busy_rows, _ = validate_paginated(api_client.list_agreement_billing_events(busy_id, BRAND))
    assert [row["agreement_id"] for row in busy_rows] == [busy_id] * 3
    assert [row["occurred_on"] for row in busy_rows] == [
        "2026-08-01",
        "2026-08-02",
        "2026-08-03",
    ]
    assert [row["event_type"] for row in busy_rows] == [
        "DUES_POSTED",
        "PAYMENT_RECEIVED",
        "PAYMENT_RECEIVED",
    ]
    quiet_rows, quiet_meta = validate_paginated(
        api_client.list_agreement_billing_events(quiet_id, BRAND)
    )
    assert quiet_meta["total_count"] == 1
    assert quiet_rows[0]["agreement_id"] == quiet_id
    assert quiet_rows[0]["event_type"] == "DUES_POSTED"


def test_each_membership_projects_only_its_own_ledger_into_money():
    """The busy membership's two part payments retire its charge exactly, while the quiet
    membership's untouched charge stands at its full amount.

    PRD 3.4: "`dues_paid_cents` is the sum of `amount_cents` over every `PAYMENT_RECEIVED`
    entry. The write-off total is the sum of `amount_cents` over every `WRITE_OFF` entry.
    `outstanding_balance_cents` is the sum of the charge amounts minus the payment total minus
    the write-off total, and it may legitimately go to zero or below."

    Design: Corner/endpoints/corner_agreement_billing_event_sub_resource_lists_only_its_own_ledger
    """
    scenario = _one_ledger_of_three_rows_beside_a_ledger_of_one()

    busy = read_agreement(scenario["busy_agreement"]["id"])
    assert busy["dues_paid_cents"] == 4500
    assert busy["outstanding_balance_cents"] == 0
    quiet = read_agreement(scenario["quiet_agreement"]["id"])
    assert quiet["dues_paid_cents"] == 0
    assert quiet["outstanding_balance_cents"] == 4500


def test_the_ledger_of_a_missing_agreement_is_a_parent_not_found_rather_than_an_empty_page():
    """The parent segment is resolved first, so a stranger's identifier in the parent position
    fails outright instead of yielding a page of nothing.

    PRD 2.6: "Path segments are resolved strictly left to right. When a path names a parent and
    then a child — the dues ledger of one agreement, for example — the parent identifier is
    resolved before the child scope is considered, and a parent that does not exist produces the
    parent's own not-found error rather than an empty list."

    Design: Corner/endpoints/corner_agreement_billing_event_sub_resource_lists_only_its_own_ledger
    """
    _one_ledger_of_three_rows_beside_a_ledger_of_one()

    response = api_client.list_agreement_billing_events(NON_EXISTENT_UUID, BRAND)
    validate_error(response, ApiErrorId.ERR_MEMBERSHIP_RECORD_NOT_FOUND.value, 404)


def _a_failing_inspection_that_suspended_its_club() -> dict:
    """A modern club scored 60 / 60 / 60 against a five-year-old floor, which fails hard enough
    to suspend the club and open a remediation file."""
    scenario = setup_single_club_franchise(
        legal_name="Ridgeway Athletics LLC",
        contact_email="ops@ridgewayath.example",
        club_name="Ridgeway Valley",
        opened_on="2024-06-01",
        with_plan=False,
    )
    scenario["inspection"] = inspect_club(scenario["club"]["id"], "2026-07-20", 60, 60, 60, 60)
    return scenario


def test_the_failing_score_is_the_standard_cycle_arithmetic_on_an_over_age_floor():
    """A 60-month floor exactly exhausts the brand-standard 60-month cycle, so the refresh term
    contributes nothing and the weighted sum lands at 51.

    PRD 3.9: "Then `refresh_pts` is computed: multiply 100 by `equipment_age_months_max`, divide
    by `refresh_cycle_months_applied`, round that quotient half up to a whole number, subtract it
    from 100, and floor the result at 0, so an over-age floor earns zero refresh points rather
    than negative ones."

    Design: Corner/endpoints/corner_closing_a_remediation_inspection_does_not_lift_the_club_suspension
    """
    scenario = _a_failing_inspection_that_suspended_its_club()

    inspection = read_inspection(scenario["inspection"]["id"])
    assert inspection["variant_applied"] == "STANDARD_CYCLE"
    assert inspection["refresh_cycle_months_applied"] == 60
    assert inspection["refresh_pts"] == 0
    assert inspection["score"] == 51
    assert inspection["status"] == "REMEDIATION_REQUIRED"


def test_closing_the_remediation_file_leaves_the_club_suspended():
    """Headquarters files the finding away and the inspection reaches its terminal state, but
    the club it suspended stays shut and non-compliant.

    PRD 3.9: "A `BrandAdministrator` files an inspection away from either `REMEDIATION_REQUIRED`
    or `REMEDIATION_WAIVED` to `CLOSED`, optionally with a `note`, incrementing the inspection's
    `version`; closing from any other state is refused with `ERR_INVALID_INSPECTION_STATE`.
    Closing a `REMEDIATION_REQUIRED` inspection is purely administrative and does not lift the
    club's suspension — only a waiver or a passing re-inspection does that. `CLOSED` is
    terminal."

    Design: Corner/endpoints/corner_closing_a_remediation_inspection_does_not_lift_the_club_suspension
    """
    scenario = _a_failing_inspection_that_suspended_its_club()

    closed = close_inspection(scenario["inspection"]["id"])
    assert closed["status"] == "CLOSED"
    assert closed["waived_by_user_id"] is None
    assert closed["waiver_reason"] is None
    club = read_club(scenario["club"]["id"])
    assert club["status"] == "SUSPENDED"
    assert club["equipment_compliance_state"] == "NON_COMPLIANT"
    assert club["last_inspection_score"] == 51


def test_the_closed_file_still_counts_against_the_franchisee_standing():
    """One trailing failure costs twenty points and no more, which keeps the operator above the
    demotion line even after the file is closed.

    PRD 3.9: "`compliance_score` then starts at 100 and subtracts 20 for each step of
    `inspection_fail_streak`, a flat 20 if `collections_watch_club_count` is greater than zero —
    one flat penalty no matter how many clubs are on watch, not 20 per club — and 10 for each
    disputed royalty report, with the result clamped into 0 through 100."

    Design: Corner/endpoints/corner_closing_a_remediation_inspection_does_not_lift_the_club_suspension
    """
    scenario = _a_failing_inspection_that_suspended_its_club()

    close_inspection(scenario["inspection"]["id"])
    franchisee = read_franchisee(scenario["franchisee"]["id"])
    assert franchisee["inspection_fail_streak"] == 1
    assert franchisee["collections_watch_club_count"] == 0
    assert franchisee["disputed_royalty_count"] == 0
    assert franchisee["compliance_score"] == 80
    assert franchisee["status"] == "ACTIVE"
