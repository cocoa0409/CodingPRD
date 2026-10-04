"""Entity lookup and serialization helpers."""
from __future__ import annotations

from db import db
from errors import err_not_found


def serialize(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_or_404(table: dict, rid, label: str):
    rec = table.get(rid)
    if rec is None:
        raise err_not_found(f"{label} not found: {rid}")
    return rec


def get_agreement(rid):
    return get_or_404(db.agreements, rid, "LicenseAgreement")


def get_athlete(rid):
    return get_or_404(db.athletes, rid, "Athlete")


def get_grant(rid):
    return get_or_404(db.likeness_grants, rid, "LikenessGrant")


def get_season(rid):
    return get_or_404(db.seasons, rid, "LiveSeason")


def get_batch(rid):
    return get_or_404(db.roster_batches, rid, "RosterBatch")


def get_drop(rid):
    return get_or_404(db.content_drops, rid, "ContentDrop")


def get_wallet(rid):
    return get_or_404(db.wallets, rid, "PlayerWallet")


def get_program(rid):
    return get_or_404(db.tournaments, rid, "TournamentProgram")


def get_asset(rid):
    return get_or_404(db.audio_assets, rid, "AudioAsset")


def get_audio_license(rid):
    return get_or_404(db.audio_licenses, rid, "AudioLicense")


def get_edition(rid):
    return get_or_404(db.editions, rid, "RegionalEdition")


def get_statement(rid):
    return get_or_404(db.royalty_statements, rid, "RoyaltyStatement")


def get_case(rid):
    return get_or_404(db.audit_cases, rid, "AuditCase")


def list_paginated(records, filters, limit, offset):
    """filters: list of (value, field) — apply equality when value is not None."""
    rows = list(records)
    for value, field in filters:
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    rows.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(rows)
    page = rows[offset:offset + limit]
    return [serialize(r) for r in page], total
