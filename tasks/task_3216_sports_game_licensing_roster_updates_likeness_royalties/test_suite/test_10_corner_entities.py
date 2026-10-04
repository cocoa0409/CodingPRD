"""Corner queue B, section=entities (5 instances)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    RIGHTS,
    create_active_agreement,
    create_agreement_payload,
    create_athlete_payload,
    create_eligible_athlete,
    create_likeness_grant_payload,
    create_season_payload,
    create_wallet_payload,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["licensing_admin_headers"]
LIVEOPS = TEST_USERS["liveops_manager_headers"]


def test_create_agreement_missing_required_field_returns_invalid_input(api):
    """PRD §3.1: "A LicensingAdmin opens a relationship with a league, players
    association, or college body by creating a LicenseAgreement. The creation
    payload carries the licensor_type (one of LEAGUE, PLAYERS_ASSOCIATION, or
    COLLEGE_BODY), the human-facing licensor_name, the exclusivity_scope (one
    of NONE, CATEGORY, or FULL), the sport_category the agreement covers (for
    example AMFOOT_PRO, BASKET_PRO, or SOCCER_INTL), the inclusive term bounds
    term_start_on and term_end_on, the royalty_model (one of PERCENT_OF_NET,
    PER_UNIT, or HYBRID), the base royalty_rate_bps, the
    minimum_guarantee_cents owed over the term, whether the guarantee
    mg_recoupable against future accruals, and the audit_window_days the
    licensor retains after each statement finalizes."

    Design: Corner/entities/create_agreement_missing_required_field_returns_invalid_input
    """
    payload = create_agreement_payload()
    del payload["royalty_model"]
    resp = api_client.create_agreement(payload, ADMIN)
    assert resp.status_code == 400, (
        f"missing royalty_model must be a 400 validation error; "
        f"got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["error_id"], str)


def test_athlete_defaults_status_ineligible_until_granted(api):
    """PRD §3.2: "A newly registered athlete has athlete_status of INELIGIBLE
    and a null current_overall_rating; only roster publication populates the
    rating."

    Design: Corner/entities/athlete_defaults_status_ineligible_until_granted
    """
    athlete = validate_success(
        api_client.create_athlete(
            create_athlete_payload(full_name="Rookie"), RIGHTS
        ),
        expected_status=201,
    )
    assert athlete["athlete_status"] == "INELIGIBLE"
    assert athlete["current_overall_rating"] is None

    fetched = get_success_data(api_client.get_athlete(athlete["id"], RIGHTS))
    assert fetched["athlete_status"] == "INELIGIBLE"
    assert fetched["current_overall_rating"] is None


def test_get_nonexistent_agreement_returns_not_found(api):
    """PRD §2.6: "the first identifier that fails to resolve produces
    ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_nonexistent_agreement_returns_not_found
    """
    resp = api_client.get_agreement(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_ledger_entry_immutable_append_only(api):
    """PRD §2.5: "WalletLedgerEntry is an append-only posting with no in-place
    mutation, so it carries only id and created_at; updated_at and version are
    absent."

    Design: Corner/entities/ledger_entry_immutable_append_only
    """
    agreement = create_active_agreement()
    season = get_success_data(
        api_client.create_season(create_season_payload(agreement["id"]), LIVEOPS)
    )
    wallet = get_success_data(
        api_client.create_wallet(
            create_wallet_payload(season["id"], owner_tag="imm"), LIVEOPS
        )
    )
    entry = validate_success(
        api_client.post_ledger_entry(
            wallet["id"],
            {"direction": "CREDIT", "amount_vc": 100, "reason_code": "GRANT"},
            LIVEOPS,
        ),
        expected_status=201,
    )
    assert entry["entry_status"] == "POSTED"
    assert "version" not in entry, "append-only entry must not expose version"
    assert "updated_at" not in entry, "append-only entry must not expose updated_at"

    entries, meta = validate_paginated(
        api_client.list_ledger_entries(wallet["id"], LIVEOPS)
    )
    assert meta["total_count"] == 1
    listed = entries[0]
    assert listed["id"] == entry["id"]
    assert "version" not in listed and "updated_at" not in listed
    assert listed["entry_status"] == "POSTED"


def test_college_athlete_grant_requires_opt_in(api):
    """PRD §3.2: "Granting the likeness — the explicit PENDING → GRANTED step —
    requires three things in order: the referenced agreement must currently be
    ACTIVE (otherwise ERR_REFERENCE_STATE); the athlete must exist and, when
    the athlete's class is COLLEGE, college_opt_in must be true (a missing
    opt-in surfaces ERR_COLLEGE_OPT_IN_REQUIRED)."

    Design: Corner/entities/college_athlete_grant_requires_opt_in
    """
    agreement = create_active_agreement(
        licensor_type="COLLEGE_BODY", licensor_name="College Assoc",
        royalty_rate_bps=800, audit_window_days=60,
    )
    athlete = get_success_data(
        api_client.create_athlete(
            create_athlete_payload(full_name="College QB",
                                   athlete_class="COLLEGE", college_opt_in=False),
            RIGHTS,
        )
    )
    grant = get_success_data(
        api_client.create_likeness_grant(
            create_likeness_grant_payload(
                athlete["id"], agreement["id"], grant_kind="NIL_COLLEGE",
                royalty_share_bps=300, payment_destination="nil-trust-1",
            ),
            RIGHTS,
        )
    )
    resp = api_client.grant_likeness(grant["id"], RIGHTS)
    validate_error(resp, ApiErrorId.ERR_COLLEGE_OPT_IN_REQUIRED.value)

    grant_after = get_success_data(api_client.get_likeness_grant(grant["id"], RIGHTS))
    assert grant_after["grant_status"] == "PENDING"
