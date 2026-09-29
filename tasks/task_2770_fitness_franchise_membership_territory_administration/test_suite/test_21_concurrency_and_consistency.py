"""Two optimistic-concurrency guards, one rate threshold read one day apart, and the immediate
consistency the whole cascade discipline rests on.

The two version guards protect different parents with different fields and different codes, so
they are exercised on their own declared write endpoints rather than in the abstract. The
consistency tests take no second write and no retry: everything they read must already be true the
instant the triggering call returns.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_agreement_payload,
    create_member,
    create_transfer_request_payload,
    create_usage_settlement,
    freeze_agreement,
    inspect_club,
    make_club_manager_headers,
    place_in_collections_payload,
    post_dues,
    post_payment,
    post_payment_failure,
    read_agreement,
    read_agreement_version,
    read_club,
    read_club_version,
    read_franchisee,
    read_usage_settlement,
    schedule_inspection,
    score_inspection_payload,
    set_clock_date,
    setup_guest_usage_scenario,
    setup_home_and_host_clubs,
    setup_single_club_franchise,
    sign_active_agreement,
    sign_agreement,
    unfreeze_agreement,
)

BRAND = TEST_USERS["brand_administrator_headers"]
BILLING = TEST_USERS["billing_partner_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


def _a_club_whose_version_moved_after_the_read() -> dict:
    """The manager reads the club, an auditor scores an inspection against it, and the read the
    manager is still holding is now one revision behind."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
    )
    scenario["member"] = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    scenario["stale_version"] = read_club_version(scenario["club"]["id"])
    scenario["inspection"] = inspect_club(scenario["club"]["id"], "2026-07-15", 95, 92, 90, 12)
    return scenario


def _sign_quoting(scenario: dict, member_id: str, expected_club_version: int):
    return api_client.create_agreement(
        create_agreement_payload(
            member_id,
            scenario["club"]["id"],
            scenario["plan_template"]["id"],
            expected_club_version,
            "2026-08-01",
        ),
        make_club_manager_headers(scenario["club"]["id"]),
    )


def test_signing_against_a_club_version_that_an_inspection_has_overtaken_is_refused():
    """The body is otherwise perfect — a published plan, a real member, the club's own manager —
    and the single stale integer is enough to stop it.

    PRD 2.7: "Signing a membership agreement requires the non-optional input field
    `expected_club_version`, carrying the client's last observed `version` of the home `Club`. If
    that value does not equal the home club's current `version`, the create is rejected with
    `ERR_STALE_CLUB_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_rule_one_rejects_a_stale_club_version_then_accepts_a_fresh_one
    """
    scenario = _a_club_whose_version_moved_after_the_read()

    validate_error(
        _sign_quoting(scenario, scenario["member"]["id"], scenario["stale_version"]),
        ApiErrorId.ERR_STALE_CLUB_VERSION.value,
        412,
    )
    assert read_club_version(scenario["club"]["id"]) != scenario["stale_version"]


def test_a_freshly_read_version_signs_and_the_club_keeps_taking_memberships():
    """Nothing about the club forbade the sale; the guard was about the freshness of the caller's
    snapshot, and with a current one the same club signs member after member.

    PRD 2.7: "A club legitimately accepts any number of agreements, so nothing in the club's state
    blocks a second signing; the reason for the check is that the club's pricing posture
    (`guest_fee_cents`), its compliance posture (`equipment_compliance_state` and `status`) and its
    counters may all have moved between the read and the write, and an agreement quoted against a
    stale club snapshot must be refused rather than silently signed at the old posture."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_rule_one_rejects_a_stale_club_version_then_accepts_a_fresh_one
    """
    scenario = _a_club_whose_version_moved_after_the_read()

    validate_error(
        _sign_quoting(scenario, scenario["member"]["id"], scenario["stale_version"]),
        ApiErrorId.ERR_STALE_CLUB_VERSION.value,
        412,
    )
    first = validate_success(
        _sign_quoting(
            scenario, scenario["member"]["id"], read_club_version(scenario["club"]["id"])
        ),
        expected_status=201,
    )
    second_member = create_member(
        scenario["club"]["id"], full_name="Ben Oduya", email="ben.oduya@example.com"
    )
    second = validate_success(
        _sign_quoting(scenario, second_member["id"], read_club_version(scenario["club"]["id"])),
        expected_status=201,
    )
    assert first["id"] != second["id"]
    assert first["home_club_id"] == second["home_club_id"] == scenario["club"]["id"]


def test_each_signing_consumes_the_club_version_it_quoted():
    """The guard is self-renewing: a signature that succeeds invalidates the very number it was
    quoted against, so the same integer can never be spent twice.

    PRD 3.3: "The home club's `version` increments by 1, which is exactly why the next signing at
    the same club needs a freshly read `expected_club_version`."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_rule_one_rejects_a_stale_club_version_then_accepts_a_fresh_one
    """
    scenario = _a_club_whose_version_moved_after_the_read()
    club_id = scenario["club"]["id"]

    fresh = read_club_version(club_id)
    validate_success(
        _sign_quoting(scenario, scenario["member"]["id"], fresh), expected_status=201
    )
    assert read_club_version(club_id) == fresh + 1
    second_member = create_member(
        club_id, full_name="Ben Oduya", email="ben.oduya@example.com"
    )
    validate_error(
        _sign_quoting(scenario, second_member["id"], fresh),
        ApiErrorId.ERR_STALE_CLUB_VERSION.value,
        412,
    )


def _an_agreement_whose_version_moved_after_the_read() -> dict:
    """A live membership at the home club, read once, then frozen and unfrozen — two revisions
    the holder of that first read never saw."""
    scenario = setup_home_and_host_clubs(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        home_club_name="Harborline Downtown",
        host_club_name="Harborline Northside",
    )
    member = create_member(
        scenario["home_club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    agreement = sign_active_agreement(
        member["id"], scenario["home_club"]["id"], scenario["plan_template"]["id"]
    )
    scenario["member"] = member
    scenario["agreement"] = agreement
    scenario["stale_version"] = read_agreement_version(agreement["id"])
    freeze_agreement(agreement["id"], scenario["home_club"]["id"])
    unfreeze_agreement(agreement["id"], scenario["home_club"]["id"])
    return scenario


def _file_transfer_quoting(scenario: dict, expected_agreement_version: int):
    return api_client.create_transfer_request(
        create_transfer_request_payload(
            scenario["agreement"]["id"],
            scenario["home_club"]["id"],
            scenario["host_club"]["id"],
            expected_agreement_version,
            reason="Member relocated across town.",
        ),
        make_club_manager_headers(scenario["home_club"]["id"]),
    )


def test_a_transfer_quoting_a_pre_freeze_agreement_version_is_refused_with_its_own_code():
    """A different parent, a different field and a different code from the club guard: the freeze
    and unfreeze round trip is enough to age the caller's read out of validity.

    PRD 2.7: "Opening a transfer request requires the non-optional input field
    `expected_agreement_version`, carrying the client's last observed `version` of the
    `MembershipAgreement`. If that value does not equal the agreement's current `version`, the
    create is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_rule_two_rejects_a_stale_agreement_version_on_transfer_create
    """
    scenario = _an_agreement_whose_version_moved_after_the_read()

    validate_error(
        _file_transfer_quoting(scenario, scenario["stale_version"]),
        ApiErrorId.ERR_STALE_AGREEMENT_VERSION.value,
        412,
    )
    assert read_agreement_version(scenario["agreement"]["id"]) != scenario["stale_version"]


def test_the_unfrozen_agreement_is_perfectly_transferable_once_the_version_is_re_read():
    """The refusal said nothing about the membership's eligibility to move: it is back in service
    with its dues current, and a re-read version files the transfer at once.

    PRD 2.7: "An agreement may carry many transfer requests over its life, so no state
    precondition blocks a second one; the reason for the check is that a billing event, a freeze,
    or an earlier completed transfer may have moved the agreement's `home_club_id` or its
    `dues_status` in the meantime, which would make both the `from_club_id` supplied on the new
    request and its arrears eligibility stale."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_rule_two_rejects_a_stale_agreement_version_on_transfer_create
    """
    scenario = _an_agreement_whose_version_moved_after_the_read()

    validate_error(
        _file_transfer_quoting(scenario, scenario["stale_version"]),
        ApiErrorId.ERR_STALE_AGREEMENT_VERSION.value,
        412,
    )
    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["home_club_id"] == scenario["home_club"]["id"]
    request = validate_success(
        _file_transfer_quoting(scenario, agreement["version"]), expected_status=201
    )
    assert request["from_club_id"] == scenario["home_club"]["id"]
    assert request["to_club_id"] == scenario["host_club"]["id"]


def _arrears_fifty_nine_days_old() -> dict:
    """A 9000-cent charge due 2026-09-05 with 100 cents paid against it, aged to 2026-11-03 —
    one day short of the collections threshold."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
    )
    scenario["member"] = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    agreement = sign_agreement(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        "2026-08-01",
    )
    post_dues(agreement["id"], 9000, "2026-08-01", due_on="2026-09-05")
    post_payment(agreement["id"], 100, "2026-08-02")
    set_clock_date("2026-11-03")
    post_payment_failure(agreement["id"], "2026-11-03")
    scenario["agreement"] = read_agreement(agreement["id"])
    return scenario


def _offer_to_collections(agreement_id: str):
    return api_client.place_in_collections(
        agreement_id, place_in_collections_payload(agency_reference="AGY-2026-0011"), BILLING
    )


def test_arrears_one_day_short_of_the_threshold_are_not_placeable():
    """The account is squarely `DELINQUENT` and the caller is the billing partner itself, so the
    only thing standing in the way is the age of the debt.

    PRD 3.4: "It moves the collections dimension `DELINQUENT → IN_COLLECTIONS`, and both of its
    preconditions are checked: an account not currently in `DELINQUENT` is refused with
    `ERR_INVALID_DUES_STATE`, and an account whose `delinquency_days` is below 60 — two months of
    unpaid dues — is refused with `ERR_COLLECTIONS_THRESHOLD_NOT_MET`."

    Design: Corner/cross_cutting_complexity_layers/corner_collections_rate_threshold_at_fifty_nine_then_sixty_days
    """
    scenario = _arrears_fifty_nine_days_old()

    assert scenario["agreement"]["dues_status"] == "DELINQUENT"
    assert scenario["agreement"]["delinquency_days"] < 60
    validate_error(
        _offer_to_collections(scenario["agreement"]["id"]),
        ApiErrorId.ERR_COLLECTIONS_THRESHOLD_NOT_MET.value,
        409,
    )
    assert read_agreement(scenario["agreement"]["id"])["dues_status"] == "DELINQUENT"


def test_one_further_day_of_ageing_carries_the_same_account_over_the_threshold():
    """Nothing is paid, nothing is written off and no new charge is raised: the clock advances by a
    single day and the identical request is accepted.

    PRD 3.4: "It moves the collections dimension `DELINQUENT → IN_COLLECTIONS`, and both of its
    preconditions are checked: an account not currently in `DELINQUENT` is refused with
    `ERR_INVALID_DUES_STATE`, and an account whose `delinquency_days` is below 60 — two months of
    unpaid dues — is refused with `ERR_COLLECTIONS_THRESHOLD_NOT_MET`."

    Design: Corner/cross_cutting_complexity_layers/corner_collections_rate_threshold_at_fifty_nine_then_sixty_days
    """
    scenario = _arrears_fifty_nine_days_old()
    agreement_id = scenario["agreement"]["id"]

    validate_error(
        _offer_to_collections(agreement_id),
        ApiErrorId.ERR_COLLECTIONS_THRESHOLD_NOT_MET.value,
        409,
    )
    set_clock_date("2026-11-04")
    post_payment_failure(agreement_id, "2026-11-04")
    aged = read_agreement(agreement_id)
    assert aged["dues_status"] == "DELINQUENT"
    assert aged["delinquency_days"] >= 60
    placed = validate_success(_offer_to_collections(agreement_id))
    assert placed["dues_status"] == "IN_COLLECTIONS"


def _a_scheduled_inspection_about_to_fail() -> dict:
    """An open, compliant club and a scheduled walk-through, with the club's and the franchisee's
    revisions noted so the cascade can be seen to have landed."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
        with_plan=False,
    )
    scenario["inspection"] = schedule_inspection(scenario["club"]["id"], "2026-07-15")
    scenario["club_version_before"] = read_club(scenario["club"]["id"])["version"]
    scenario["franchisee_version_before"] = read_franchisee(scenario["franchisee"]["id"])[
        "version"
    ]
    return scenario


def _score_it(scenario: dict):
    return api_client.score_inspection(
        scenario["inspection"]["id"], score_inspection_payload(60, 60, 60, 60), AUDITOR
    )


def test_the_scoring_call_returns_only_the_inspection_yet_both_aggregates_have_already_moved():
    """No clock move, no second write and no retry: the club and the franchisee are re-read once
    and are already carrying the consequences of the score.

    PRD 2.10: "Derived counters in this system are never incremented on faith; they are recomputed
    from the records that define them, and the recomputation happens inside the same request that
    disturbed them. When a single operation therefore touches several entities, every touched
    entity's `version` increments and its `updated_at` refreshes, and the response returns only the
    primary resource — the caller must re-read the other entities to observe the cascade."

    Design: Corner/consistency_model/corner_immediate_consistency_every_cascade_is_visible_in_the_triggering_response
    """
    scenario = _a_scheduled_inspection_about_to_fail()

    scored = validate_success(_score_it(scenario))
    assert scored["id"] == scenario["inspection"]["id"]
    assert "club" not in scored
    assert "franchisee" not in scored
    assert read_club(scenario["club"]["id"])["version"] > scenario["club_version_before"]
    assert (
        read_franchisee(scenario["franchisee"]["id"])["version"]
        > scenario["franchisee_version_before"]
    )


def test_the_club_is_already_demoted_and_suspended_when_the_score_returns():
    """One walk-through, and the club's posture is re-derived from the new score alone rather than
    from anything the auditor said about it.

    PRD 3.9: "The club's `last_inspection_score` is set to the new `score`, and its
    `equipment_compliance_state` is re-derived from that score alone: `COMPLIANT` at 85 or above,
    `WATCH` at 70 through 84, and `NON_COMPLIANT` below 70. A club that has just become
    `NON_COMPLIANT` and was `OPEN` moves to `SUSPENDED`"

    Design: Corner/consistency_model/corner_immediate_consistency_every_cascade_is_visible_in_the_triggering_response
    """
    scenario = _a_scheduled_inspection_about_to_fail()

    scored = validate_success(_score_it(scenario))
    assert scored["score"] < 70
    club = read_club(scenario["club"]["id"])
    assert club["last_inspection_score"] == scored["score"]
    assert club["equipment_compliance_state"] == "NON_COMPLIANT"
    assert club["status"] == "SUSPENDED"


def test_the_franchisees_compliance_score_is_already_recomputed_from_its_counters():
    """The third link of the chain has fired too: the franchisee's standing is a pure function of
    the three counters it reports, and it agrees with them the moment the score lands.

    PRD 3.9: "`compliance_score` then starts at 100 and subtracts 20 for each step of
    `inspection_fail_streak`, a flat 20 if `collections_watch_club_count` is greater than zero —
    one flat penalty no matter how many clubs are on watch, not 20 per club — and 10 for each
    disputed royalty report, with the result clamped into 0 through 100."

    Design: Corner/consistency_model/corner_immediate_consistency_every_cascade_is_visible_in_the_triggering_response
    """
    scenario = _a_scheduled_inspection_about_to_fail()

    validate_success(_score_it(scenario))
    franchisee = read_franchisee(scenario["franchisee"]["id"])
    expected = 100 - 20 * franchisee["inspection_fail_streak"]
    if franchisee["collections_watch_club_count"] > 0:
        expected -= 20
    expected -= 10 * franchisee["disputed_royalty_count"]
    expected = max(0, min(100, expected))
    assert franchisee["compliance_score"] == expected
    assert franchisee["compliance_score"] == 80


def _an_open_august_settlement_between_two_clubs() -> dict:
    """Eighty-four August visits at the host club, swept into one open settlement, with both
    clubs' revisions noted before any money moves."""
    scenario = setup_guest_usage_scenario(
        period_visits=[("2026-08", 50), ("2026-08", 34)],
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        home_club_name="Harborline Downtown",
        host_club_name="Harborline Northside",
    )
    scenario["settlement"] = create_usage_settlement(
        "2026-08", scenario["home_club"]["id"], scenario["host_club"]["id"]
    )
    scenario["home_version_before"] = read_club(scenario["home_club"]["id"])["version"]
    scenario["host_version_before"] = read_club(scenario["host_club"]["id"])["version"]
    return scenario


def _post_it(scenario: dict):
    return api_client.post_usage_settlement(
        scenario["settlement"]["id"], {"note": "August inter-club settlement."}, BRAND
    )


def test_posting_moves_the_money_as_a_matched_pair_of_equal_and_opposite_legs():
    """One call debits one club and credits another by the same figure, and the network-wide sum of
    settlement ledgers is left where it started.

    PRD 3.7: "The home club's `settlement_ledger_cents` decreases by `net_payable_cents` and the
    host club's increases by the same amount, `status` advances `OPEN → POSTED`, `posted_on`
    records the logical clock date, and the settlement's `version` plus both clubs' `version`
    values each increment by 1."

    Design: Corner/consistency_model/corner_immediate_consistency_settlement_post_shows_both_ledger_legs_at_once
    """
    scenario = _an_open_august_settlement_between_two_clubs()

    posted = validate_success(_post_it(scenario))
    assert posted["status"] == "POSTED"
    assert posted["posted_on"] == "2026-08-01"
    home = read_club(scenario["home_club"]["id"])
    host = read_club(scenario["host_club"]["id"])
    assert home["settlement_ledger_cents"] == -posted["net_payable_cents"]
    assert host["settlement_ledger_cents"] == posted["net_payable_cents"]
    assert home["settlement_ledger_cents"] + host["settlement_ledger_cents"] == 0
    assert home["version"] == scenario["home_version_before"] + 1
    assert host["version"] == scenario["host_version_before"] + 1


def test_both_ledger_legs_are_readable_the_instant_the_posting_returns():
    """The posting hands back the settlement and nothing else, so the two clubs must be re-read —
    and neither of them is waiting on a reconciliation pass.

    PRD 2.10: "Derived counters in this system are never incremented on faith; they are recomputed
    from the records that define them, and the recomputation happens inside the same request that
    disturbed them. When a single operation therefore touches several entities, every touched
    entity's `version` increments and its `updated_at` refreshes, and the response returns only the
    primary resource — the caller must re-read the other entities to observe the cascade."

    Design: Corner/consistency_model/corner_immediate_consistency_settlement_post_shows_both_ledger_legs_at_once
    """
    scenario = _an_open_august_settlement_between_two_clubs()

    posted = validate_success(_post_it(scenario))
    assert posted["id"] == scenario["settlement"]["id"]
    assert "home_club" not in posted
    assert "host_club" not in posted
    assert read_club(scenario["home_club"]["id"])["settlement_ledger_cents"] != 0
    assert read_club(scenario["host_club"]["id"])["settlement_ledger_cents"] != 0
    assert read_club(scenario["home_club"]["id"])["version"] > scenario["home_version_before"]
    assert read_club(scenario["host_club"]["id"])["version"] > scenario["host_version_before"]
    assert read_usage_settlement(scenario["settlement"]["id"])["status"] == "POSTED"
