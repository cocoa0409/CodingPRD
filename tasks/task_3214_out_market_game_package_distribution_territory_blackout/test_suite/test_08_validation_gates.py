"""Validation gates: purchase gates (season phase, offer window, student,
account kind), selection membership, duplicates, and structural rules."""
from test_helpers import (
    ApiErrorId,
    NONEXISTENT_UUID,
    create_game,
    create_grant,
    create_market,
    create_offer,
    create_season,
    create_slate,
    create_student_verification,
    make_subscriber_headers,
    make_support_agent_headers,
    make_venue_manager_headers,
    register_account,
    set_clock,
    setup_week4_game_account_sub,
    validate_error,
    validate_success,
)


def _post_season_with_expired_offer(api, league_ops_headers,
                                    platform_admin_headers):
    """Season advanced PRE_SALE -> REGULAR -> POST; BASE offer whose window
    expired by the moved clock; one account."""
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_slate(season["id"], week_index=1)
    adv1 = validate_success(
        api.advance_season_phase(season["id"], season["version"],
                                 league_ops_headers)
    )
    offer = create_offer(season["id"])
    validate_success(
        api.advance_season_phase(season["id"], adv1["version"], league_ops_headers)
    )
    account = register_account(email="late@x.com", billing_zip="10001")
    set_clock("2027-01-15T00:00:00Z")
    return offer, account


def test_post_season_purchase_rejected_even_with_offer_also_out_of_window(
    api, league_ops_headers, platform_admin_headers
):
    """PRD §3.2: "`POST` is terminal for sales: a purchase attempted against a
    season in `POST` is rejected with `ERR_SEASON_CLOSED` (HTTP 409), while
    purchases remain legal in both `PRE_SALE` and `REGULAR`."

    Design: Difficulty/priority_pair_validation_conflict/state_phase_gate_beats_business_temporal_offer_window
    """
    offer, account = _post_season_with_expired_offer(
        api, league_ops_headers, platform_admin_headers
    )
    resp = api.create_subscription(
        account["id"], offer["id"], make_subscriber_headers(account["id"])
    )
    assert resp.status_code == 409, (
        f"expected 409, got {resp.status_code}: {resp.text}"
    )
    assert resp.json()["data"]["error_id"] == (
        ApiErrorId.ERR_SEASON_CLOSED.value
    )


def test_post_season_purchase_rejected_for_in_window_offer(
    api, league_ops_headers, platform_admin_headers
):
    """PRD §3.2: "`POST` is terminal for sales: a purchase attempted against a
    season in `POST` is rejected with `ERR_SEASON_CLOSED` (HTTP 409), while
    purchases remain legal in both `PRE_SALE` and `REGULAR`."

    Design: Difficulty/priority_pair_validation_conflict/state_phase_gate_beats_business_temporal_offer_window
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_slate(season["id"], week_index=1)
    adv1 = validate_success(
        api.advance_season_phase(season["id"], season["version"],
                                 league_ops_headers)
    )
    offer = create_offer(season["id"], valid_until="2027-03-01T00:00:00Z")
    validate_success(
        api.advance_season_phase(season["id"], adv1["version"], league_ops_headers)
    )
    account = register_account(email="late2@x.com", billing_zip="10001")
    set_clock("2027-01-15T00:00:00Z")
    validate_error(
        api.create_subscription(
            account["id"], offer["id"], make_subscriber_headers(account["id"])
        ),
        ApiErrorId.ERR_SEASON_CLOSED,
    )


def test_billing_complaint_approve_past_window_reports_window_error(
    api, platform_admin_headers
):
    """PRD §2.8: "on complaint resolution the grace-window check (16) is
    evaluated before the category gate (17), which is evaluated before the
    refund-floor check (18)."

    Design: Difficulty/priority_pair_validation_conflict/referential_student_gate_beats_fiscal_refund_floor
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"], grace_days=7)
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    create_slate(season["id"], week_index=4)
    game = create_game(season["id"], week_index=4, away_team_code="KC",
                       home_team_code="DAL",
                       kickoff_at="2026-08-30T17:00:00Z",
                       home_market_code="DAL")
    offer = create_offer(season["id"])
    account = register_account(email="c@x.com", billing_zip="10001")
    sub = validate_success(
        api.create_subscription(account["id"], offer["id"],
                                make_subscriber_headers(account["id"])),
        expected_status=201,
    )
    validate_success(
        api.simulate_payment(sub["id"], "SUCCEEDED", platform_admin_headers)
    )
    case = validate_success(
        api.create_complaint_case(
            account["id"], sub["id"], game["id"], "BILLING",
            "charged twice?", make_subscriber_headers(account["id"]),
        ),
        expected_status=201,
    )
    # 19 days after purchase: grace window (7 days) has lapsed.
    set_clock("2026-09-20T00:00:00Z")
    validate_error(
        api.resolve_complaint_case(case["id"], "APPROVE",
                                   "double charge confirmed",
                                   make_support_agent_headers("sa-jane")),
        ApiErrorId.ERR_COMPLAINT_WINDOW_EXPIRED,
    )
    case_now = validate_success(
        api.get_complaint_case(case["id"], platform_admin_headers)
    )
    assert case_now["status"] == "OPEN"


def test_student_purchase_without_verification_rejected(api):
    """PRD §3.5: "A `STUDENT` offer additionally requires the account to hold
    a `StudentVerification` whose `status` is `VERIFIED` and whose
    `valid_through` is strictly in the future of the logical clock — otherwise
    `ERR_STUDENT_NOT_VERIFIED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/referential_student_gate_beats_fiscal_refund_floor
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    offer = create_offer(season["id"], plan_tier="STUDENT",
                         base_price_cents=16000)
    account = register_account(email="nover@x.com", billing_zip="75001")
    validate_error(
        api.create_subscription(account["id"], offer["id"],
                                make_subscriber_headers(account["id"])),
        ApiErrorId.ERR_STUDENT_NOT_VERIFIED,
    )


def test_revoked_verification_blocks_student_purchase_without_touching_prior(
    api, compliance_auditor_headers
):
    """PRD §3.9: "A `ComplianceAuditor` may also revoke a verification
    outright, `VERIFIED` → `REVOKED`, terminal." PRD §3.5: "A `STUDENT` offer
    additionally requires the account to hold a `StudentVerification` whose
    `status` is `VERIFIED` and whose `valid_through` is strictly in the future
    of the logical clock — otherwise `ERR_STUDENT_NOT_VERIFIED` (HTTP 422)."

    Design: Corner/validations/cross_entity_student_gate_valid_and_invalid
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    offer = create_offer(season["id"], plan_tier="STUDENT",
                         base_price_cents=16000)
    account = register_account(email="stu2@x.com", billing_zip="10001")
    sv = create_student_verification(account["id"])

    sub = validate_success(
        api.create_subscription(account["id"], offer["id"],
                                make_subscriber_headers(account["id"])),
        expected_status=201,
    )
    assert sub["status"] == "PENDING_PAYMENT"

    validate_success(
        api.revoke_student_verification(sv["id"], compliance_auditor_headers)
    )
    validate_error(
        api.create_subscription(account["id"], offer["id"],
                                make_subscriber_headers(account["id"])),
        ApiErrorId.ERR_STUDENT_NOT_VERIFIED,
    )


def test_verified_and_unexpired_verification_admits_student_purchase(api):
    """PRD §3.5: "A `STUDENT` offer additionally requires the account to hold
    a `StudentVerification` whose `status` is `VERIFIED` and whose
    `valid_through` is strictly in the future of the logical clock — otherwise
    `ERR_STUDENT_NOT_VERIFIED` (HTTP 422)."

    Design: Corner/validations/cross_entity_student_gate_valid_and_invalid
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    offer = create_offer(season["id"], plan_tier="STUDENT",
                         base_price_cents=16000)
    account = register_account(email="stu3@x.com", billing_zip="10001")
    create_student_verification(account["id"])
    sub = validate_success(
        api.create_subscription(account["id"], offer["id"],
                                make_subscriber_headers(account["id"])),
        expected_status=201,
    )
    assert sub["plan_tier"] == "STUDENT"
    assert sub["status"] == "PENDING_PAYMENT"


def test_account_kind_gate_runs_both_directions(api):
    """PRD §3.5: "And the account-kind gate (`ERR_ACCOUNT_KIND_MISMATCH`, HTTP
    422) runs in both directions: a `COMMERCIAL` account may not purchase any
    retail offer (`BASE`, `PREMIUM`, or `STUDENT`), and a `RESIDENTIAL`
    account may not hold a venue license (§3.8)."

    Design: Corner/validations/conditional_validation_commercial_kind_blocks_retail_purchase
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    offer = create_offer(season["id"])
    res = register_account(email="res3@x.com", billing_zip="10001")
    com = register_account(email="com3@x.com", account_kind="COMMERCIAL",
                           billing_zip="75001")

    sub_res = validate_success(
        api.create_subscription(res["id"], offer["id"],
                                make_subscriber_headers(res["id"])),
        expected_status=201,
    )
    assert sub_res["status"] == "PENDING_PAYMENT"

    validate_error(
        api.create_subscription(com["id"], offer["id"],
                                make_venue_manager_headers(com["id"])),
        ApiErrorId.ERR_ACCOUNT_KIND_MISMATCH,
    )
    validate_error(
        api.create_venue_license(
            {
                "account_id": res["id"],
                "venue_name": "Home Bar",
                "venue_zip": "10001",
                "fire_code_occupancy": 50,
            },
            make_venue_manager_headers(res["id"]),
        ),
        ApiErrorId.ERR_ACCOUNT_KIND_MISMATCH,
    )
    lic = validate_success(
        api.create_venue_license(
            {
                "account_id": com["id"],
                "venue_name": "Real Bar",
                "venue_zip": "75001",
                "fire_code_occupancy": 50,
            },
            make_venue_manager_headers(com["id"]),
        ),
        expected_status=201,
    )
    assert lic["status"] == "PENDING"


def test_commercial_purchase_rejected_while_residential_succeeds(api):
    """PRD §3.5: "a `COMMERCIAL` account may not purchase any retail offer
    (`BASE`, `PREMIUM`, or `STUDENT`)".

    Design: Corner/validations/conditional_validation_commercial_kind_blocks_retail_purchase
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    offer = create_offer(season["id"], plan_tier="PREMIUM",
                         base_price_cents=30000, includes_multiview=True,
                         includes_companion=True)
    com = register_account(email="com4@x.com", account_kind="COMMERCIAL",
                           billing_zip="75001")
    validate_error(
        api.create_subscription(com["id"], offer["id"],
                                make_venue_manager_headers(com["id"])),
        ApiErrorId.ERR_ACCOUNT_KIND_MISMATCH,
    )


def test_withdrawn_offer_and_out_of_window_offer_both_rejected(
    api, platform_admin_headers
):
    """PRD §3.5: "A purchase against a withdrawn offer, or against the logical
    clock outside the window, fails with `ERR_OFFER_NOT_AVAILABLE` (HTTP
    409)."

    Design: Corner/validations/aggregate_validation_offer_window_and_status_both_required
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    offer_ok = create_offer(season["id"])
    offer_withdrawn = create_offer(season["id"], plan_tier="PREMIUM",
                                   base_price_cents=30000,
                                   includes_multiview=True,
                                   includes_companion=True)
    validate_success(api.withdraw_offer(offer_withdrawn["id"], platform_admin_headers))
    account = register_account(email="agg@x.com", billing_zip="10001")

    sub = validate_success(
        api.create_subscription(account["id"], offer_ok["id"],
                                make_subscriber_headers(account["id"])),
        expected_status=201,
    )
    assert sub["status"] == "PENDING_PAYMENT"

    validate_error(
        api.create_subscription(account["id"], offer_withdrawn["id"],
                                make_subscriber_headers(account["id"])),
        ApiErrorId.ERR_OFFER_NOT_AVAILABLE,
    )


def test_out_of_window_active_offer_rejected(api):
    """PRD §3.5: "the offer is purchasable at or after `valid_from` and
    strictly before `valid_until`" and "A purchase against a withdrawn offer,
    or against the logical clock outside the window, fails with
    `ERR_OFFER_NOT_AVAILABLE` (HTTP 409)."

    Design: Corner/validations/aggregate_validation_offer_window_and_status_both_required
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    offer = create_offer(season["id"], valid_from="2026-08-01T00:00:00Z",
                         valid_until="2026-08-20T00:00:00Z")
    account = register_account(email="win@x.com", billing_zip="10001")
    validate_error(
        api.create_subscription(account["id"], offer["id"],
                                make_subscriber_headers(account["id"])),
        ApiErrorId.ERR_OFFER_NOT_AVAILABLE,
    )


def test_removing_unselected_game_conflicts_even_on_empty_set(
    api, league_ops_headers
):
    """PRD §3.4: "Adding a game already present in `national_game_ids`, or
    removing one that is not present, is `ERR_NATIONAL_SELECTION_CONFLICT`
    (HTTP 409) — the national list never holds duplicates."

    Design: Difficulty/boundary_precision_check/multiview_cap_boundary_and_empty_selection_edge
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    slate = create_slate(season["id"], week_index=4)
    game = create_game(season["id"], week_index=4, away_team_code="KC",
                       home_team_code="DAL",
                       kickoff_at="2026-08-30T17:00:00Z",
                       home_market_code="DAL")
    validate_error(
        api.slate_selection(slate["id"], game["id"], "REMOVE",
                            slate["version"], league_ops_headers),
        ApiErrorId.ERR_NATIONAL_SELECTION_CONFLICT,
    )
    slate_now = validate_success(api.get_week_slate(slate["id"], league_ops_headers))
    assert slate_now["national_game_ids"] == []


def test_adding_already_selected_game_conflicts(api, league_ops_headers):
    """PRD §3.4: "Adding a game already present in `national_game_ids`, or
    removing one that is not present, is `ERR_NATIONAL_SELECTION_CONFLICT`
    (HTTP 409) — the national list never holds duplicates."

    Design: Difficulty/boundary_precision_check/multiview_cap_boundary_and_empty_selection_edge
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    slate = create_slate(season["id"], week_index=4)
    game = create_game(season["id"], week_index=4, away_team_code="KC",
                       home_team_code="DAL",
                       kickoff_at="2026-08-30T17:00:00Z",
                       home_market_code="DAL")
    slate_now = validate_success(api.get_week_slate(slate["id"], league_ops_headers))
    moved = validate_success(
        api.slate_selection(slate["id"], game["id"], "ADD",
                            slate_now["version"], league_ops_headers)
    )
    validate_error(
        api.slate_selection(slate["id"], game["id"], "ADD",
                            moved["version"], league_ops_headers),
        ApiErrorId.ERR_NATIONAL_SELECTION_CONFLICT,
    )
    slate_after = validate_success(
        api.get_week_slate(slate["id"], league_ops_headers)
    )
    assert slate_after["national_game_ids"] == [game["id"]]


def test_multiview_second_session_admitted_third_rejected(
    api, platform_admin_headers
):
    """PRD §3.11: "the account must hold fewer than two active multiview
    sessions, the hard cap. An account already holding two active sessions is
    rejected with `ERR_MULTIVIEW_CAP_REACHED` (HTTP 409); holding exactly one,
    the start succeeds."

    Design: Difficulty/boundary_precision_check/multiview_cap_boundary_and_empty_selection_edge
    """
    ctx = setup_week4_game_account_sub(
        email="mv@x.com", billing_zip="10001",
        offer_overrides={"plan_tier": "PREMIUM", "base_price_cents": 30000,
                         "includes_multiview": True, "includes_companion": True},
    )
    sub_id = ctx["subscription"]["id"]
    headers = make_subscriber_headers(ctx["account"]["id"])

    first = validate_success(
        api.start_multiview_session(sub_id, headers), expected_status=201
    )
    assert first["active_count"] == 1
    second = validate_success(
        api.start_multiview_session(sub_id, headers), expected_status=201
    )
    assert second["active_count"] == 2
    validate_error(
        api.start_multiview_session(sub_id, headers),
        ApiErrorId.ERR_MULTIVIEW_CAP_REACHED,
    )


def test_ending_session_frees_cap_slot(api, platform_admin_headers):
    """PRD §3.11: "ending a session frees the slot and likewise reports the
    resulting `active_count`."

    Design: Difficulty/boundary_precision_check/multiview_cap_boundary_and_empty_selection_edge
    """
    ctx = setup_week4_game_account_sub(
        email="mv2@x.com", billing_zip="10001",
        offer_overrides={"plan_tier": "PREMIUM", "base_price_cents": 30000,
                         "includes_multiview": True, "includes_companion": True},
    )
    sub_id = ctx["subscription"]["id"]
    headers = make_subscriber_headers(ctx["account"]["id"])

    first = validate_success(
        api.start_multiview_session(sub_id, headers), expected_status=201
    )
    validate_success(api.start_multiview_session(sub_id, headers),
                     expected_status=201)
    ended = validate_success(
        api.end_multiview_session(first["multiview_session_id"], headers)
    )
    assert ended["active_count"] == 1
    third = validate_success(
        api.start_multiview_session(sub_id, headers), expected_status=201
    )
    assert third["active_count"] == 2
