"""Corner queue B, section=state_machines (6 instances)."""
from test_helpers import (
    ADMIN,
    FINANCE,
    RIGHTS,
    create_active_agreement,
    create_audit_case_payload,
    create_eligible_athlete,
    create_finalized_statement,
    create_funded_wallet,
    create_live_season,
    create_open_tournament,
    create_published_batch,
    create_released_drop,
    create_roster_batch_payload,
    create_roster_entry_payload,
    get_success_data,
    register_entry,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    TEST_USERS,
    make_league_auditor_headers,
    make_roster_operator_headers,
    make_roster_reviewer_headers,
)

LIVEOPS = TEST_USERS["liveops_manager_headers"]


def test_terminal_agreement_rejects_further_transitions(api):
    """PRD §3.1: "Termination is a separate, deliberate act: a SUSPENDED
    agreement may be moved to the terminal TERMINATED state by a
    LicensingAdmin."

    Design: Corner/state_machines/terminal_agreement_rejects_further_transitions
    """
    agreement = create_active_agreement()
    get_success_data(api_client.suspend_agreement(agreement["id"], ADMIN))
    terminated = get_success_data(api_client.terminate_agreement(agreement["id"], ADMIN))
    assert terminated["agreement_status"] == "TERMINATED"

    resp = api_client.reinstate_agreement(agreement["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = get_success_data(api_client.get_agreement(agreement["id"], ADMIN))
    assert after["agreement_status"] == "TERMINATED"


def test_rollback_only_on_head_batch(api):
    """PRD §3.3: "A batch may roll back only while it is PUBLISHED and is the
    head — its published_epoch equals the season's current roster_epoch.
    Attempting rollback on any other batch is ERR_ROLLBACK_NOT_HEAD."

    Design: Corner/state_machines/rollback_only_on_head_batch
    """
    agreement = create_active_agreement()
    athlete, _ = create_eligible_athlete(agreement["id"])
    season = get_success_data(
        api_client.create_season(
            {"title_code": "PIGSKIN26", "sport_category": "AMFOOT_PRO",
             "season_label": "2026-27", "agreement_id": agreement["id"],
             "season_opens_on": "2026-08-01", "season_closes_on": "2027-02-01"},
            LIVEOPS,
        )
    )
    b1 = create_published_batch(
        season["id"],
        [create_roster_entry_payload(athlete["id"], entry_kind="ADD",
                                     overall_rating=80)],
    )
    b2 = create_published_batch(
        season["id"],
        [create_roster_entry_payload(athlete["id"], entry_kind="UPDATE_ATTRIBUTE",
                                     overall_rating=82)],
    )
    resp = api_client.rollback_roster_batch(b1["id"], make_roster_reviewer_headers("reviewer-1"))
    validate_error(resp, ApiErrorId.ERR_ROLLBACK_NOT_HEAD.value)

    b1_after = get_success_data(
        api_client.get_roster_batch(b1["id"], make_roster_reviewer_headers("reviewer-1"))
    )
    assert b1_after["batch_status"] == "SUPERSEDED"


def test_grant_revoke_from_granted_rejected(api):
    """PRD §3.2: "Revocation is terminal and one-way: only a SUSPENDED grant may
    be moved to REVOKED."

    Design: Corner/state_machines/grant_revoke_from_granted_rejected
    """
    agreement = create_active_agreement(licensor_type="PLAYERS_ASSOCIATION",
                                        licensor_name="PA")
    _, grant = create_eligible_athlete(agreement["id"])
    resp = api_client.revoke_likeness_grant(grant["id"], RIGHTS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    grant_after = get_success_data(api_client.get_likeness_grant(grant["id"], RIGHTS))
    assert grant_after["grant_status"] == "GRANTED"


def test_agreement_terminate_blocked_by_open_audit(api):
    """PRD §3.1: "a SUSPENDED agreement may be moved to the terminal TERMINATED
    state by a LicensingAdmin, but only when no AuditCase on the agreement sits
    in OPEN or FINDINGS_FILED — otherwise the request fails with
    ERR_AUDIT_BLOCKS_TERMINATION."

    Design: Corner/state_machines/agreement_terminate_blocked_by_open_audit
    """
    agreement = create_active_agreement(audit_window_days=90)
    statement = create_finalized_statement(
        agreement["id"], gross_sales_cents=100000, returns_cents=0,
        pending_sales_cents=0, finalize_clock="2026-09-10T00:00:00Z",
    )
    case = get_success_data(
        api_client.create_audit_case(
            create_audit_case_payload(agreement["id"], statement["id"],
                                      opened_by_role="LEAGUE_AUDITOR"),
            make_league_auditor_headers("league-aud-1"),
        )
    )
    assert case["audit_status"] == "OPEN"

    get_success_data(api_client.suspend_agreement(agreement["id"], ADMIN))
    resp = api_client.terminate_agreement(agreement["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_AUDIT_BLOCKS_TERMINATION.value)

    after = get_success_data(api_client.get_agreement(agreement["id"], ADMIN))
    assert after["agreement_status"] == "SUSPENDED"


def test_sunset_season_cascades_drops_wallets_tournaments(api):
    """PRD §3.3: "Sunsetting a LIVE season — either by explicit operator action
    or as a cascade from agreement expiry — ends every RELEASED drop, freezes
    every OPEN wallet, and cancels every tournament program still in ANNOUNCED
    or REGISTRATION_OPEN, refunding entry fees via REFUND credits."

    Design: Corner/state_machines/sunset_season_cascades_drops_wallets_tournaments
    """
    agreement = create_active_agreement()
    athlete, _ = create_eligible_athlete(agreement["id"])
    season = create_live_season(agreement["id"], athlete["id"])
    drop = create_released_drop(season["id"], drop_kind="VANITY", drop_label="V",
                                price_vc=100)
    wallet = create_funded_wallet(season["id"], 2000, owner_tag="sunset-player")
    program = create_open_tournament(
        season["id"], prize_rows=((1, 10000),), program_label="SUNSET_CUP",
        league_sanctioned=True, entry_fee_vc=500,
    )
    entry = register_entry(program["id"], wallet["id"])
    mid = get_success_data(api_client.get_wallet(wallet["id"], LIVEOPS))
    assert mid["vc_balance"] == 1500

    get_success_data(api_client.sunset_season(season["id"], LIVEOPS))

    drop_after = get_success_data(api_client.get_content_drop(drop["id"], LIVEOPS))
    assert drop_after["drop_status"] == "ENDED"

    wallet_after = get_success_data(api_client.get_wallet(wallet["id"], LIVEOPS))
    assert wallet_after["wallet_status"] == "FROZEN"
    assert wallet_after["vc_balance"] == 2000, (
        f"the 500 entry fee must be refunded via a REFUND credit; "
        f"got {wallet_after['vc_balance']}"
    )

    program_after = get_success_data(api_client.get_tournament(program["id"], LIVEOPS))
    assert program_after["program_status"] == "CANCELED"

    entries, _ = validate_paginated(
        api_client.list_tournament_entries(program["id"], LIVEOPS)
    )
    ours = [e for e in entries if e["id"] == entry["id"]]
    assert ours and ours[0]["entry_status"] == "REFUNDED"
