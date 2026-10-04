"""Corner queue B, section=calculations (2 instances)."""
from test_helpers import (
    RIGHTS,
    create_active_agreement,
    create_eligible_athlete,
    create_provisional_statement,
    create_roster_batch_payload,
    create_roster_entry_payload,
    get_success_data,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS, make_roster_operator_headers, make_roster_reviewer_headers

LIVEOPS = TEST_USERS["liveops_manager_headers"]


def test_roster_last_write_wins_chronological(api):
    """PRD §3.3: "When the same athlete is rated by multiple entries in one
    batch, the entries apply in created_at ascending order and the
    chronologically last write wins — ties are broken only by created_at,
    never by id."

    Design: Corner/calculations/roster_last_write_wins_chronological
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
    batch = get_success_data(
        api_client.create_roster_batch(
            create_roster_batch_payload(season["id"], batch_label="CHRONO"), op
        )
    )
    get_success_data(api_client.add_roster_entry(
        batch["id"], create_roster_entry_payload(athlete["id"], entry_kind="ADD",
                                                 overall_rating=70), op))
    get_success_data(api_client.add_roster_entry(
        batch["id"], create_roster_entry_payload(athlete["id"], entry_kind="UPDATE_ATTRIBUTE",
                                                 overall_rating=77), op))
    get_success_data(api_client.add_roster_entry(
        batch["id"], create_roster_entry_payload(athlete["id"], entry_kind="UPDATE_ATTRIBUTE",
                                                 overall_rating=74), op))
    get_success_data(api_client.validate_roster_batch(batch["id"], op))
    season_now = get_success_data(api_client.get_season(season["id"], LIVEOPS))
    get_success_data(api_client.publish_roster_batch(
        batch["id"], {"expected_season_version": season_now["version"]},
        make_roster_reviewer_headers("reviewer-1"),
    ))
    athlete_after = get_success_data(api_client.get_athlete(athlete["id"], RIGHTS))
    assert athlete_after["current_overall_rating"] == 74, (
        f"chronologically last entry (74) must win over 70 and 77; "
        f"got {athlete_after['current_overall_rating']}"
    )


def test_mg_recoupment_reduces_payable_accrual(api):
    """PRD §3.7: "Recoupment then applies: when the agreement's mg_recoupable is
    true and recouped_against_mg_cents is still below minimum_guarantee_cents,
    the payable accrual is the raw accrual minus the remaining recoupment room,
    floored at zero; otherwise the payable accrual equals the raw accrual."

    Design: Corner/calculations/mg_recoupment_reduces_payable_accrual
    """
    agreement = create_active_agreement(
        royalty_rate_bps=1000, minimum_guarantee_cents=100000,
        mg_recoupable=True, audit_window_days=90,
    )
    statement = create_provisional_statement(
        agreement["id"], gross_sales_cents=500000, returns_cents=0,
        pending_sales_cents=0,
    )
    # raw accrual = 500000*1000/10000 = 50000; room = 100000; payable = 0
    assert statement["accrued_royalty_cents"] == 0, (
        f"recoupment must absorb the full 50000 raw accrual; "
        f"got {statement['accrued_royalty_cents']}"
    )
