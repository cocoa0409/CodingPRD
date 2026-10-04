"""Corner queue B, section=errors (5 instances)."""
from test_helpers import (
    FINANCE,
    RIGHTS,
    create_active_agreement,
    create_approved_edition,
    create_audio_asset_payload,
    create_audio_license_payload,
    create_content_drop_payload,
    create_eligible_athlete,
    create_funded_wallet,
    create_likeness_grant_payload,
    create_live_season,
    create_open_tournament,
    create_athlete_payload,
    get_success_data,
    register_entry,
    validate_error,
    validate_paginated,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS

LIVEOPS = TEST_USERS["liveops_manager_headers"]


def test_error_grant_term_outside_agreement(api):
    """PRD §3.2: "the grant's inclusive term must be contained within the
    agreement's inclusive term — a grant whose start precedes the agreement's
    start or whose end follows the agreement's end is rejected with
    ERR_GRANT_TERM_OUTSIDE_AGREEMENT."

    Design: Corner/errors/error_grant_term_outside_agreement
    """
    agreement = create_active_agreement(
        licensor_type="PLAYERS_ASSOCIATION", licensor_name="PA",
        term_start_on="2026-08-01", term_end_on="2026-10-31",
    )
    athlete = get_success_data(
        api_client.create_athlete(
            create_athlete_payload(full_name="Retired Legend",
                                   athlete_class="RETIRED"),
            RIGHTS,
        )
    )
    grant = get_success_data(
        api_client.create_likeness_grant(
            create_likeness_grant_payload(
                athlete["id"], agreement["id"], grant_kind="INDIVIDUAL_RETIRED",
                term_start_on="2026-01-01", term_end_on="2026-12-31",
                royalty_share_bps=400, payment_destination="estate-1",
            ),
            RIGHTS,
        )
    )
    resp = api_client.grant_likeness(grant["id"], RIGHTS)
    validate_error(resp, ApiErrorId.ERR_GRANT_TERM_OUTSIDE_AGREEMENT.value)

    grant_after = get_success_data(api_client.get_likeness_grant(grant["id"], RIGHTS))
    assert grant_after["grant_status"] == "PENDING"


def test_error_unsanctioned_payout_rejected(api):
    """PRD §3.5: "Payout finalization belongs to the FinanceController and is
    the fiscally sensitive step. The program must be COMPLETED, the
    league_sanctioned flag must be true (finalizing an unsanctioned program is
    ERR_UNSANCTIONED_PAYOUT, HTTP 422)."

    Design: Corner/errors/error_unsanctioned_payout_rejected
    """
    program, entries = _completed_program(api, league_sanctioned=False,
                                          label="UNSANCTIONED",
                                          prize_rows=((1, 10000),))
    current = get_success_data(api_client.get_tournament(program["id"], LIVEOPS))
    resp = api_client.finalize_payout(
        program["id"], {"expected_program_version": current["version"]}, FINANCE
    )
    validate_error(resp, ApiErrorId.ERR_UNSANCTIONED_PAYOUT.value)

    after = get_success_data(api_client.get_tournament(program["id"], LIVEOPS))
    assert after["program_status"] == "COMPLETED"


def test_error_prize_shares_must_total_10000(api):
    """PRD §3.5: "the share_bps values across the program's prize rows must
    total exactly 10000 — a violation is ERR_PRIZE_SHARES_INVALID (HTTP 422)."

    Design: Corner/errors/error_prize_shares_must_total_10000
    """
    agreement = create_active_agreement()
    athlete, _ = create_eligible_athlete(agreement["id"])
    season = create_live_season(agreement["id"], athlete["id"])
    program = create_open_tournament(
        season["id"], prize_rows=((1, 9000),), program_label="BADSUM",
        league_sanctioned=True, entry_fee_vc=100,
    )
    wallet = create_funded_wallet(season["id"], 500, owner_tag="v1")
    entry = register_entry(program["id"], wallet["id"])
    get_success_data(api_client.close_registration(program["id"], LIVEOPS))

    resp = api_client.record_results(
        program["id"],
        {"placements": [{"entry_id": entry["id"], "placement": 1}]},
        LIVEOPS,
    )
    validate_error(resp, ApiErrorId.ERR_PRIZE_SHARES_INVALID.value)

    after = get_success_data(api_client.get_tournament(program["id"], LIVEOPS))
    assert after["program_status"] == "REGISTRATION_CLOSED"


def test_error_audio_uncovered_operation(api):
    """PRD §3.6: "a RightsOfficer may move an ACTIVE license to the terminal
    TERMINATED state early. In both cases the referenced asset moves from
    CLEARED to BLOCKED when no other ACTIVE license covers it." and "A BLOCKED
    asset may be retired outright, moving to the terminal RETIRED."

    Design: Corner/errors/error_audio_uncovered_operation
    """
    asset = get_success_data(
        api_client.create_audio_asset(
            create_audio_asset_payload(asset_kind="MUSIC_TRACK",
                                       asset_title="Anthem",
                                       rights_holder="Label X"),
            RIGHTS,
        )
    )
    license_ = get_success_data(
        api_client.create_audio_license(
            create_audio_license_payload(asset["id"], usage_scope="ALL",
                                         region_scope="GLOBAL"),
            RIGHTS,
        )
    )
    # Retire while the asset is CLEARED (covered) is not a legal transition.
    resp = api_client.retire_audio_asset(asset["id"], RIGHTS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    get_success_data(api_client.terminate_audio_license(license_["id"], RIGHTS))
    asset_after = get_success_data(api_client.get_audio_asset(asset["id"], RIGHTS))
    assert asset_after["asset_status"] == "BLOCKED"

    retired = get_success_data(api_client.retire_audio_asset(asset["id"], RIGHTS))
    assert retired["asset_status"] == "RETIRED"


def test_error_censorship_conflict_on_release(api):
    """PRD §3.4: "A further global constraint guards regional compliance: no
    RELEASED RegionalEdition of the parent season may carry a censorship flag
    that conflicts with the drop's content; releasing into such a conflict is
    ERR_CENSORSHIP_CONFLICT."

    Design: Corner/errors/error_censorship_conflict_on_release
    """
    agreement = create_active_agreement()
    athlete, _ = create_eligible_athlete(agreement["id"])
    season = create_live_season(agreement["id"], athlete["id"])
    edition = create_approved_edition(
        season["id"], region_code="CN",
        censorship_flags=["NO_REAL_PLAYER_NAMES"], embargo_until_on="2026-09-01",
    )
    get_success_data(api_client.release_edition(edition["id"], LIVEOPS))
    drop = get_success_data(
        api_client.create_content_drop(
            create_content_drop_payload(
                season["id"], drop_kind="PLAYER_CARD",
                drop_label="CN Blocked Card",
                featured_athlete_id=athlete["id"], price_vc=100,
            ),
            LIVEOPS,
        )
    )
    resp = api_client.release_content_drop(drop["id"], LIVEOPS)
    validate_error(resp, ApiErrorId.ERR_CENSORSHIP_CONFLICT.value)

    drop_after = get_success_data(api_client.get_content_drop(drop["id"], LIVEOPS))
    assert drop_after["drop_status"] == "SCHEDULED"


def _completed_program(api, *, league_sanctioned, label, prize_rows):
    """Season LIVE; program with one confirmed entry and results recorded."""
    agreement = create_active_agreement()
    athlete, _ = create_eligible_athlete(agreement["id"])
    season = create_live_season(agreement["id"], athlete["id"])
    program = create_open_tournament(
        season["id"], prize_rows=prize_rows, program_label=label,
        league_sanctioned=league_sanctioned, entry_fee_vc=100,
    )
    wallet = create_funded_wallet(season["id"], 500, owner_tag="u1")
    entry = register_entry(program["id"], wallet["id"])
    get_success_data(api_client.close_registration(program["id"], LIVEOPS))
    get_success_data(api_client.record_results(
        program["id"],
        {"placements": [{"entry_id": entry["id"], "placement": 1}]},
        LIVEOPS,
    ))
    return program, [entry]
