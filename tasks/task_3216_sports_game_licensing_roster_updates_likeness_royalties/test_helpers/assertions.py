"""Entity assertions and domain invariant checkers (PRD §2.5)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AgreementStatus,
    AssetStatus,
    AthleteStatus,
    AuditStatus,
    BatchStatus,
    DropStatus,
    EditionStatus,
    AudioLicenseStatus,
    GrantStatus,
    LedgerEntryStatus,
    PrizeStatus,
    ProgramStatus,
    RosterEntryStatus,
    SeasonStatus,
    StatementStatus,
    TournamentEntryStatus,
    WalletStatus,
)


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def _assert_append_only_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, f"{entity} must not expose updated_at"
    assert "version" not in data, f"{entity} must not expose version"


def assert_license_agreement(data: dict):
    _assert_common_fields(data, "LicenseAgreement")
    assert data["licensor_type"] in ("LEAGUE", "PLAYERS_ASSOCIATION", "COLLEGE_BODY")
    assert data["exclusivity_scope"] in ("NONE", "CATEGORY", "FULL")
    assert data["royalty_model"] in ("PERCENT_OF_NET", "PER_UNIT", "HYBRID")
    assert isinstance(data["royalty_rate_bps"], int)
    assert isinstance(data["minimum_guarantee_cents"], int)
    assert isinstance(data["mg_recoupable"], bool)
    assert isinstance(data["audit_window_days"], int)
    assert data["agreement_status"] in [s.value for s in AgreementStatus]
    assert isinstance(data["outstanding_royalty_cents"], int)
    assert isinstance(data["recouped_against_mg_cents"], int)


def assert_athlete(data: dict):
    _assert_common_fields(data, "Athlete")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["athlete_class"] in ("ACTIVE_PRO", "RETIRED", "COLLEGE")
    assert isinstance(data["college_opt_in"], bool)
    assert data["athlete_status"] in [s.value for s in AthleteStatus]
    assert data.get("current_overall_rating") is None or (
        isinstance(data["current_overall_rating"], int)
        and 40 <= data["current_overall_rating"] <= 99
    )


def assert_likeness_grant(data: dict):
    _assert_common_fields(data, "LikenessGrant")
    assert data["grant_kind"] in ("GROUP_PA", "INDIVIDUAL_RETIRED", "NIL_COLLEGE")
    assert isinstance(data["royalty_share_bps"], int)
    assert data["grant_status"] in [s.value for s in GrantStatus]


def assert_live_season(data: dict):
    _assert_common_fields(data, "LiveSeason")
    assert data["season_status"] in [s.value for s in SeasonStatus]
    assert isinstance(data["roster_epoch"], int) and data["roster_epoch"] >= 0


def assert_roster_batch(data: dict):
    _assert_common_fields(data, "RosterBatch")
    assert data["batch_status"] in [s.value for s in BatchStatus]
    assert isinstance(data["submitted_by"], str)


def assert_roster_entry(data: dict):
    _assert_common_fields(data, "RosterEntry")
    assert data["entry_kind"] in (
        "ADD", "UPDATE_ATTRIBUTE", "TRANSACTION", "REMOVE", "APPEARANCE"
    )
    assert data["entry_status"] in [s.value for s in RosterEntryStatus]


def assert_content_drop(data: dict):
    _assert_common_fields(data, "ContentDrop")
    assert data["drop_kind"] in ("ITEM_PACK", "PLAYER_CARD", "VANITY", "STADIUM_THEME")
    assert isinstance(data["price_vc"], int) and data["price_vc"] >= 0
    assert data["drop_status"] in [s.value for s in DropStatus]


def assert_player_wallet(data: dict):
    _assert_common_fields(data, "PlayerWallet")
    assert data["wallet_status"] in [s.value for s in WalletStatus]
    assert isinstance(data["vc_balance"], int) and data["vc_balance"] >= 0


def assert_wallet_ledger_entry(data: dict):
    _assert_append_only_fields(data, "WalletLedgerEntry")
    assert data["direction"] in ("CREDIT", "DEBIT")
    assert isinstance(data["amount_vc"], int) and data["amount_vc"] > 0
    assert data["reason_code"] in (
        "GRANT", "PURCHASE", "SPEND_DROP", "REFUND", "CLAWBACK", "PRIZE_PAYOUT"
    )
    assert data["entry_status"] == LedgerEntryStatus.POSTED.value


def assert_tournament_program(data: dict):
    _assert_common_fields(data, "TournamentProgram")
    assert isinstance(data["league_sanctioned"], bool)
    assert isinstance(data["entry_fee_vc"], int) and data["entry_fee_vc"] >= 0
    assert data["program_status"] in [s.value for s in ProgramStatus]


def assert_tournament_entry(data: dict):
    _assert_append_only_fields(data, "TournamentEntry")
    assert isinstance(data["fee_paid"], bool)
    assert data["entry_status"] in [s.value for s in TournamentEntryStatus]


def assert_tournament_prize(data: dict):
    _assert_common_fields(data, "TournamentPrize")
    assert isinstance(data["placement"], int) and data["placement"] >= 1
    assert isinstance(data["share_bps"], int)
    assert data["prize_status"] in [s.value for s in PrizeStatus]


def assert_audio_asset(data: dict):
    _assert_common_fields(data, "AudioAsset")
    assert data["asset_kind"] in ("COMMENTARY_LINE", "MUSIC_TRACK", "STADIUM_SOUND")
    assert data["asset_status"] in [s.value for s in AssetStatus]


def assert_audio_license(data: dict):
    _assert_common_fields(data, "AudioLicense")
    assert data["usage_scope"] in ("MENU_ONLY", "IN_GAME", "BROADCAST_SIM", "ALL")
    assert data["license_status"] in [s.value for s in AudioLicenseStatus]


def assert_regional_edition(data: dict):
    _assert_common_fields(data, "RegionalEdition")
    assert data["edition_status"] in [s.value for s in EditionStatus]
    assert isinstance(data["censorship_flags"], list)


def assert_royalty_statement(data: dict):
    _assert_common_fields(data, "RoyaltyStatement")
    assert data["statement_status"] in [s.value for s in StatementStatus]
    for field in (
        "gross_sales_cents", "returns_cents", "pending_sales_cents",
        "accrued_royalty_cents", "held_royalty_cents", "paid_royalty_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_audit_case(data: dict):
    _assert_common_fields(data, "AuditCase")
    assert data["opened_by_role"] in ("LEAGUE_AUDITOR", "UNION_AUDITOR")
    assert data["audit_status"] in [s.value for s in AuditStatus]


def assert_wallet_invariants(wallet: dict, ledger_entries: list):
    """The PRD's compensating invariant: vc_balance = credits - debits >= 0."""
    credits = sum(
        e["amount_vc"] for e in ledger_entries
        if e["direction"] == "CREDIT" and e["entry_status"] == "POSTED"
    )
    debits = sum(
        e["amount_vc"] for e in ledger_entries
        if e["direction"] == "DEBIT" and e["entry_status"] == "POSTED"
    )
    assert wallet["vc_balance"] == credits - debits, (
        f"vc_balance {wallet['vc_balance']} != ledger-derived {credits - debits}"
    )
    assert wallet["vc_balance"] >= 0
