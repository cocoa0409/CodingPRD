"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared
endpoints; the test runner restarts the server before each test, so nothing
carries over between tests. All roles are opaque — only the explicit
segregation-of-duties rules (publish vs submit, approve vs submit, settle vs
open) compare operator ids, and every SoD-gated call threads explicit ids.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agreement_payload,
    create_athlete_payload,
    create_content_drop_payload,
    create_edition_payload,
    create_ledger_entry_payload,
    create_likeness_grant_payload,
    create_roster_batch_payload,
    create_roster_entry_payload,
    create_royalty_statement_payload,
    create_season_payload,
    create_tournament_payload,
    create_wallet_payload,
)
from .test_users import (
    make_compliance_reviewer_headers,
    make_finance_controller_headers,
    make_league_auditor_headers,
    make_licensing_admin_headers,
    make_liveops_manager_headers,
    make_rights_officer_headers,
    make_roster_operator_headers,
    make_roster_reviewer_headers,
)

ADMIN = make_licensing_admin_headers("test-admin-1")
RIGHTS = make_rights_officer_headers("test-rights-1")
LIVEOPS = make_liveops_manager_headers("test-liveops-1")
FINANCE = make_finance_controller_headers("test-finance-1")
DEFAULT_OPERATOR_ID = "op-1"
DEFAULT_REVIEWER_ID = "reviewer-1"


def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_active_agreement(**overrides) -> dict:
    """Create + activate an agreement. Returns the activated agreement."""
    agreement = get_success_data(
        api_client.create_agreement(create_agreement_payload(**overrides), ADMIN)
    )
    return get_success_data(api_client.activate_agreement(agreement["id"], ADMIN))


def create_eligible_athlete(agreement_id, *, grant_kind="GROUP_PA",
                            royalty_share_bps=100, **athlete_overrides) -> dict:
    """Register an athlete + grant a likeness under an ACTIVE agreement.
    Returns (athlete, grant)."""
    athlete = get_success_data(
        api_client.create_athlete(create_athlete_payload(**athlete_overrides), RIGHTS)
    )
    grant = get_success_data(
        api_client.create_likeness_grant(
            create_likeness_grant_payload(
                athlete["id"], agreement_id,
                grant_kind=grant_kind, royalty_share_bps=royalty_share_bps,
            ),
            RIGHTS,
        )
    )
    grant = get_success_data(api_client.grant_likeness(grant["id"], RIGHTS))
    return athlete, grant


def create_published_batch(season_id, entries, *,
                           operator_id=DEFAULT_OPERATOR_ID,
                           reviewer_id=DEFAULT_REVIEWER_ID) -> dict:
    """Create batch -> add entries -> validate -> publish. Returns the
    PUBLISHED batch. Operator and reviewer ids differ per PRD §2.9."""
    op_headers = make_roster_operator_headers(operator_id)
    batch = get_success_data(
        api_client.create_roster_batch(
            create_roster_batch_payload(season_id, submitted_by=operator_id),
            op_headers,
        )
    )
    for entry in entries:
        get_success_data(api_client.add_roster_entry(batch["id"], entry, op_headers))
    get_success_data(api_client.validate_roster_batch(batch["id"], op_headers))
    season = get_success_data(api_client.get_season(season_id, LIVEOPS))
    return get_success_data(
        api_client.publish_roster_batch(
            batch["id"],
            {"expected_season_version": season["version"]},
            make_roster_reviewer_headers(reviewer_id),
        )
    )


def create_live_season(agreement_id, athlete_id=None, *,
                       initial_rating=80,
                       operator_id=DEFAULT_OPERATOR_ID,
                       reviewer_id=DEFAULT_REVIEWER_ID, **season_overrides) -> dict:
    """Create season -> publish a launch batch (ADD entry for the athlete) ->
    launch. Returns the LIVE season."""
    season = get_success_data(
        api_client.create_season(
            create_season_payload(agreement_id, **season_overrides), LIVEOPS
        )
    )
    if athlete_id is not None:
        create_published_batch(
            season["id"],
            [create_roster_entry_payload(athlete_id, entry_kind="ADD",
                                         overall_rating=initial_rating)],
            operator_id=operator_id,
            reviewer_id=reviewer_id,
        )
    return get_success_data(api_client.launch_season(season["id"], LIVEOPS))


def setup_live_season_scenario(**kwargs) -> dict:
    """Active agreement + eligible athlete + LIVE season with the athlete
    rostered. Returns a dict of the created resources."""
    agreement = create_active_agreement(**kwargs.pop("agreement_overrides", {}))
    athlete, grant = create_eligible_athlete(
        agreement["id"], **kwargs.pop("athlete_overrides", {})
    )
    season = create_live_season(agreement["id"], athlete["id"],
                                **kwargs.pop("season_overrides", {}))
    return {"agreement": agreement, "athlete": athlete, "grant": grant,
            "season": season}


def create_released_drop(season_id, *, featured_athlete_id=None, **overrides) -> dict:
    """Schedule + release a content drop on a LIVE season. Returns RELEASED drop."""
    drop = get_success_data(
        api_client.create_content_drop(
            create_content_drop_payload(
                season_id, featured_athlete_id=featured_athlete_id, **overrides
            ),
            LIVEOPS,
        )
    )
    return get_success_data(api_client.release_content_drop(drop["id"], LIVEOPS))


def create_funded_wallet(season_id, amount_vc=1000, *, owner_tag="test-player") -> dict:
    """Open a wallet and post a GRANT credit. Returns the wallet dict."""
    wallet = get_success_data(
        api_client.create_wallet(
            create_wallet_payload(season_id, owner_tag=owner_tag), LIVEOPS
        )
    )
    if amount_vc > 0:
        get_success_data(
            api_client.post_ledger_entry(
                wallet["id"],
                create_ledger_entry_payload(direction="CREDIT", amount_vc=amount_vc,
                                            reason_code="GRANT"),
                LIVEOPS,
            )
        )
    return get_success_data(api_client.get_wallet(wallet["id"], LIVEOPS))


def create_open_tournament(season_id, prize_rows=((1, 10000),), **overrides) -> dict:
    """Announce a tournament, define prize rows, open registration.
    Returns the REGISTRATION_OPEN program."""
    program = get_success_data(
        api_client.create_tournament(
            create_tournament_payload(season_id, **overrides), LIVEOPS
        )
    )
    for placement, share_bps in prize_rows:
        get_success_data(
            api_client.add_prize_row(
                program["id"], {"placement": placement, "share_bps": share_bps},
                LIVEOPS,
            )
        )
    return get_success_data(api_client.open_registration(program["id"], LIVEOPS))


def register_entry(program_id, wallet_id) -> dict:
    return get_success_data(
        api_client.register_tournament_entry(program_id, {"wallet_id": wallet_id},
                                             LIVEOPS)
    )


def create_provisional_statement(agreement_id, *, clock_after_period=None,
                                 **overrides) -> dict:
    """Open a royalty statement and compute its PROVISIONAL accrual."""
    statement = get_success_data(
        api_client.create_royalty_statement(
            create_royalty_statement_payload(agreement_id, **overrides), FINANCE
        )
    )
    statement = get_success_data(api_client.compute_provisional(statement["id"], FINANCE))
    if clock_after_period:
        set_clock(clock_after_period)
    return statement


def create_finalized_statement(agreement_id, *,
                               finalize_clock="2026-09-10T00:00:00Z",
                               **overrides) -> dict:
    """Open -> compute provisional -> advance clock past period end -> finalize."""
    statement = create_provisional_statement(agreement_id, **overrides)
    set_clock(finalize_clock)
    return get_success_data(api_client.finalize_statement(statement["id"], FINANCE))


def create_open_audit_case(agreement_id, statement_id, *,
                           auditor_role="LEAGUE_AUDITOR",
                           auditor_id="league-aud-1") -> dict:
    headers = make_league_auditor_headers(auditor_id)
    if auditor_role == "UNION_AUDITOR":
        from .test_users import make_union_auditor_headers
        headers = make_union_auditor_headers(auditor_id)
    return get_success_data(
        api_client.create_audit_case(
            {"agreement_id": agreement_id, "statement_id": statement_id,
             "opened_by_role": auditor_role},
            headers,
        )
    )


def create_approved_edition(season_id, *, operator_id="ops-7",
                            reviewer_id="cr-1", **overrides) -> dict:
    """Create edition -> submit-review -> approve (SoD: reviewer != submitter).
    Returns the APPROVED edition."""
    edition = get_success_data(
        api_client.create_edition(create_edition_payload(season_id, **overrides),
                                  LIVEOPS)
    )
    get_success_data(
        api_client.submit_edition_review(
            edition["id"], make_liveops_manager_headers(operator_id)
        )
    )
    return get_success_data(
        api_client.approve_edition(
            edition["id"], make_compliance_reviewer_headers(reviewer_id)
        )
    )


def setup_cascade_scenario(*, royalty_share_bps=1000, gross_sales_cents=1000000,
                           returns_cents=100000, drop_price_vc=100,
                           with_statement=True) -> dict:
    """Full cascade-ready scenario: active agreement, granted athlete, LIVE
    season, RELEASED PLAYER_CARD drop featuring the athlete, and (optionally)
    a PROVISIONAL royalty statement. Used by suspend/reinstate/revoke tests."""
    agreement = create_active_agreement(licensor_type="PLAYERS_ASSOCIATION",
                                        licensor_name="PA")
    athlete, grant = create_eligible_athlete(
        agreement["id"], royalty_share_bps=royalty_share_bps
    )
    season = create_live_season(agreement["id"], athlete["id"], initial_rating=80)
    drop = create_released_drop(
        season["id"],
        drop_kind="PLAYER_CARD",
        featured_athlete_id=athlete["id"],
        price_vc=drop_price_vc,
    )
    ctx = {"agreement": agreement, "athlete": athlete, "grant": grant,
           "season": season, "drop": drop}
    if with_statement:
        ctx["statement"] = create_provisional_statement(
            agreement["id"],
            gross_sales_cents=gross_sales_cents,
            returns_cents=returns_cents,
        )
    return ctx
