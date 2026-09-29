"""Shared collection lookups, always in creation order."""

import db


def releases_of_deal(deal_id):
    return db.ordered([
        r for r in db.store.releases.values() if r["deal_id"] == deal_id
    ])


def agreements_of_release(release_id):
    return db.ordered([
        a for a in db.store.agreements.values() if a["release_id"] == release_id
    ])


def agreements_of_deal(deal_id):
    ids = set(r["id"] for r in db.store.releases.values() if r["deal_id"] == deal_id)
    return db.ordered([
        a for a in db.store.agreements.values() if a["release_id"] in ids
    ])


def spends_of_release(release_id):
    return db.ordered([
        s for s in db.store.spends.values() if s["release_id"] == release_id
    ])


def spends_of_deal(deal_id):
    ids = set(r["id"] for r in db.store.releases.values() if r["deal_id"] == deal_id)
    return db.ordered([
        s for s in db.store.spends.values() if s["release_id"] in ids
    ])


def runs_of_release(release_id):
    return db.ordered([
        r for r in db.store.runs.values() if r["release_id"] == release_id
    ])


def runs_of_deal(deal_id):
    ids = set(r["id"] for r in db.store.releases.values() if r["deal_id"] == deal_id)
    return db.ordered([
        r for r in db.store.runs.values() if r["release_id"] in ids
    ])


def reports_of_deal(deal_id):
    return db.ordered([
        r for r in db.store.reports.values() if r["deal_id"] == deal_id
    ])


def lines_of_report(report_id):
    return db.ordered([
        l for l in db.store.lines.values() if l["report_id"] == report_id
    ])


def lines_of_release(release_id):
    return db.ordered([
        l for l in db.store.lines.values() if l["release_id"] == release_id
    ])


def statements_of_agreement(agreement_id):
    return db.ordered([
        s for s in db.store.statements.values()
        if s["artist_agreement_id"] == agreement_id
    ])


def statements_of_deal(deal_id):
    ids = set(a["id"] for a in agreements_of_deal(deal_id))
    return db.ordered([
        s for s in db.store.statements.values()
        if s["artist_agreement_id"] in ids
    ])


def deal_of_release(release):
    return db.store.deals.get(release["deal_id"])


def release_of_agreement(agreement):
    return db.store.releases.get(agreement["release_id"])


def deal_of_agreement(agreement):
    release = release_of_agreement(agreement)
    if release is None:
        return None
    return deal_of_release(release)


def deal_of_run(run):
    release = db.store.releases.get(run["release_id"])
    if release is None:
        return None
    return deal_of_release(release)


def deal_of_spend(spend):
    release = db.store.releases.get(spend["release_id"])
    if release is None:
        return None
    return deal_of_release(release)


def agreement_of_statement(statement):
    return db.store.agreements.get(statement["artist_agreement_id"])
