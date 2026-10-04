"""Corner queue B, sections=cross_cutting_layers + consistency_model (3 instances)."""
from test_helpers import (
    ADMIN,
    FINANCE,
    RIGHTS,
    create_active_agreement,
    create_agreement_payload,
    create_eligible_athlete,
    create_published_batch,
    create_roster_batch_payload,
    create_roster_entry_payload,
    get_success_data,
    setup_cascade_scenario,
    validate_error,
    validate_paginated,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_roster_operator_headers, make_roster_reviewer_headers

LIVEOPS = TEST_USERS["liveops_manager_headers"]


def test_occ_stale_season_version_rejected(api):
    """PRD §2.8: "If the season's current version no longer matches — for
    example because another reviewer has just published a different batch,
    which legitimately superseded the prior published batch and advanced the
    season — the publish is rejected with ERR_STALE_SEASON_VERSION (HTTP 412),
    preventing the caller from overwriting a season state it has not observed."

    Design: Corner/cross_cutting_layers/occ_stale_season_version_rejected
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
    op = make_roster_operator_headers("op-1")
    b1 = get_success_data(api_client.create_roster_batch(
        create_roster_batch_payload(season["id"], batch_label="B1"), op))
    get_success_data(api_client.add_roster_entry(
        b1["id"], create_roster_entry_payload(athlete["id"], entry_kind="ADD",
                                              overall_rating=80), op))
    get_success_data(api_client.validate_roster_batch(b1["id"], op))

    b2 = get_success_data(api_client.create_roster_batch(
        create_roster_batch_payload(season["id"], batch_label="B2"), op))
    get_success_data(api_client.add_roster_entry(
        b2["id"], create_roster_entry_payload(athlete["id"], entry_kind="UPDATE_ATTRIBUTE",
                                              overall_rating=81), op))
    get_success_data(api_client.validate_roster_batch(b2["id"], op))

    stale_version = get_success_data(api_client.get_season(season["id"], LIVEOPS))["version"]
    get_success_data(api_client.publish_roster_batch(
        b1["id"], {"expected_season_version": stale_version},
        make_roster_reviewer_headers("reviewer-1"),
    ))

    resp = api_client.publish_roster_batch(
        b2["id"], {"expected_season_version": stale_version},
        make_roster_reviewer_headers("reviewer-2"),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_SEASON_VERSION.value)

    b2_after = get_success_data(
        api_client.get_roster_batch(b2["id"], make_roster_reviewer_headers("reviewer-2"))
    )
    assert b2_after["batch_status"] == "VALIDATED"


def test_cascading_reinstate_restores_held_drops_and_held_royalty(api):
    """PRD §3.1: "Reinstating a SUSPENDED agreement — permitted only while the
    clock date is still on or before term_end_on, else ERR_TEMPORAL_CONFLICT —
    restores grants whose suspended_reason is AGREEMENT_SUSPENDED back to
    GRANTED, returns the affected HELD drops to RELEASED, and unwinds
    held_royalty_cents correspondingly."

    Design: Corner/cross_cutting_layers/cascading_reinstate_restores_held_drops_and_held_royalty
    """
    ctx = setup_cascade_scenario(royalty_share_bps=1000)
    get_success_data(api_client.suspend_agreement(ctx["agreement"]["id"], ADMIN))

    held = get_success_data(
        api_client.get_royalty_statement(ctx["statement"]["id"], FINANCE)
    )
    assert held["held_royalty_cents"] == 9000

    get_success_data(api_client.reinstate_agreement(ctx["agreement"]["id"], ADMIN))

    grant = get_success_data(api_client.get_likeness_grant(ctx["grant"]["id"], RIGHTS))
    assert grant["grant_status"] == "GRANTED"

    drop = get_success_data(api_client.get_content_drop(ctx["drop"]["id"], LIVEOPS))
    assert drop["drop_status"] == "RELEASED"

    statement = get_success_data(
        api_client.get_royalty_statement(ctx["statement"]["id"], FINANCE)
    )
    assert statement["held_royalty_cents"] == 0, (
        f"reinstate must fully unwind the 9000 held; got "
        f"{statement['held_royalty_cents']}"
    )


def test_pagination_defaults_applied_when_params_omitted(api):
    """PRD §2.3: "The limit parameter caps the number of items returned; it
    defaults to 10 when omitted, accepts a minimum of 1, and refuses values
    above 100. The offset parameter skips a number of leading items and
    defaults to 0."

    Design: Corner/cross_cutting_layers/pagination_defaults_applied_when_params_omitted
    """
    get_success_data(
        api_client.create_agreement(
            create_agreement_payload(licensor_name="Pg"), ADMIN
        )
    )
    data, meta = validate_paginated(api_client.list_agreements(ADMIN))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_immediate_consistency_after_publish(api):
    """PRD §3.3: "On a successful publish the season's roster_epoch increments
    by 1 and the batch's published_epoch is set to the new value; ... and for
    every ADD or UPDATE_ATTRIBUTE entry the athlete's current_overall_rating is
    set to the entry's overall_rating."

    Design: Corner/consistency_model/immediate_consistency_after_publish
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
    op = make_roster_operator_headers("op-1")
    batch = get_success_data(api_client.create_roster_batch(
        create_roster_batch_payload(season["id"], batch_label="IMM"), op))
    get_success_data(api_client.add_roster_entry(
        batch["id"], create_roster_entry_payload(athlete["id"], entry_kind="ADD",
                                                 overall_rating=88), op))
    get_success_data(api_client.validate_roster_batch(batch["id"], op))
    season_now = get_success_data(api_client.get_season(season["id"], LIVEOPS))
    get_success_data(api_client.publish_roster_batch(
        batch["id"], {"expected_season_version": season_now["version"]},
        make_roster_reviewer_headers("reviewer-1"),
    ))
    athlete_after = get_success_data(api_client.get_athlete(athlete["id"], RIGHTS))
    assert athlete_after["current_overall_rating"] == 88, (
        f"the read immediately after publish must reflect the new rating; "
        f"got {athlete_after['current_overall_rating']}"
    )
