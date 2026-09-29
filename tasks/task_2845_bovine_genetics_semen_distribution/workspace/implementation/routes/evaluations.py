"""Genomic evaluation, publication and the valuation cascade (PRD 3.6)."""

from flask import Blueprint

import auth
import calc
import cascades
import config
import envelope
import resolve
import serializers
import store
import validate
from errors import fail
from validate import F

bp = Blueprint("evaluations", __name__)


def _published_evaluation_of(sire_id):
    for rec in store.rows("genomic_evaluations"):
        if rec["sire_id"] == sire_id and rec["status"] == "PUBLISHED":
            return rec
    return None


@bp.post("/sires/<sire_id>/genomic-evaluations")
def file_evaluation(sire_id):
    values = validate.parse([
        F("milk_kg", "number", required=True),
        F("fat_kg", "number", required=True),
        F("protein_kg", "number", required=True),
        F("somatic_cell_score", "number", required=True),
        F("fertility_pct", "number", required=True),
        F("longevity_months", "number", required=True),
        F("reliability_pct", "number", required=True, min=0, max=99),
        F("progeny_daughter_count", "integer", required=True, min=0),
        F("effective_at", "datetime", required=True),
        F("expected_sire_version", "integer", required=True),
    ])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR)
    sire = resolve.need("sires", sire_id)
    if int(values["expected_sire_version"]) != int(sire["version"]):
        fail("ERR_STALE_SIRE_VERSION",
             "expected_sire_version does not match the bull's current version.")
    scored = calc.score_evaluation(values, sire)
    rec = store.new_record("genomic_evaluations", {
        "sire_id": sire["id"],
        "milk_kg": values["milk_kg"],
        "fat_kg": values["fat_kg"],
        "protein_kg": values["protein_kg"],
        "somatic_cell_score": values["somatic_cell_score"],
        "fertility_pct": values["fertility_pct"],
        "longevity_months": values["longevity_months"],
        "reliability_pct": values["reliability_pct"],
        "progeny_daughter_count": values["progeny_daughter_count"],
        "effective_at": store.iso(values["effective_at"]),
        "evaluation_basis": scored["evaluation_basis"],
        "parent_average_index": calc.num(scored["parent_average_index"]),
        "parent_average_weight": calc.num(scored["parent_average_weight"]),
        "production_index": calc.num(scored["production_index"]),
        "health_index": calc.num(scored["health_index"]),
        "composite_index": calc.num(scored["composite_index"]),
        "status": "DRAFT",
        "supersedes_evaluation_id": None,
        "published_at": None,
        "revaluation_delta_cents": 0,
        "_revalued_lot_ids": [],
    })
    store.touch(sire)
    return envelope.created(serializers.genomic_evaluation(rec))


@bp.get("/genomic-evaluations/<evaluation_id>")
def read_evaluation(evaluation_id):
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_BREEDING_ADVISOR,
                      config.ROLE_EXPORT_COORD)
    rec = resolve.need("genomic_evaluations", evaluation_id)
    return envelope.ok(serializers.genomic_evaluation(rec))


@bp.get("/genomic-evaluations")
def list_evaluations():
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_BREEDING_ADVISOR,
                      config.ROLE_EXPORT_COORD)
    limit, offset = validate.pagination()
    sire_id = validate.qstr("sire_id")
    status = validate.qenum("status", config.EVALUATION_STATUSES)
    supersedes_evaluation_id = validate.qstr("supersedes_evaluation_id")
    items = []
    for rec in store.rows("genomic_evaluations"):
        if sire_id is not None and rec["sire_id"] != sire_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        if (supersedes_evaluation_id is not None
                and rec["supersedes_evaluation_id"] != supersedes_evaluation_id):
            continue
        items.append(rec)
    return envelope.listing(items, limit, offset, serializers.genomic_evaluation)


@bp.post("/genomic-evaluations/<evaluation_id>/publish")
def publish_evaluation(evaluation_id):
    validate.parse([F("publication_note", "string", default=None)])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR)
    rec = resolve.need("genomic_evaluations", evaluation_id)
    if rec["status"] not in ("DRAFT", "SUPERSEDED"):
        fail("ERR_EVALUATION_STATE", "Publication requires a DRAFT or SUPERSEDED evaluation.")
    sire = store.get("sires", rec["sire_id"])
    incumbent_effective_at = sire["published_evaluation_effective_at"] if sire else None
    if incumbent_effective_at is not None:
        if store.dt_of(rec["effective_at"]) <= store.dt_of(incumbent_effective_at):
            fail("ERR_EVALUATION_STATE",
                 "A proof may not be back-dated over the incumbent published proof.")
    previous = _published_evaluation_of(rec["sire_id"])
    rec["status"] = "PUBLISHED"
    rec["published_at"] = store.clock_iso()
    rec["supersedes_evaluation_id"] = previous["id"] if previous is not None else None
    store.touch(rec)
    if previous is not None:
        previous["status"] = "SUPERSEDED"
        store.touch(previous)
    # Hop 1 then hop 2; hops 3 and 4 are derived from the lots' new unit value.
    cascades.apply_published_snapshot(sire, rec)
    cascades.revalue_for_publication(sire, rec)
    return envelope.ok(serializers.genomic_evaluation(rec))


@bp.post("/genomic-evaluations/<evaluation_id>/rollback")
def rollback_evaluation(evaluation_id):
    values = validate.parse([F("rollback_reason", "string", required=True)])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR)
    rec = resolve.need("genomic_evaluations", evaluation_id)
    if rec["status"] != "PUBLISHED":
        fail("ERR_EVALUATION_STATE", "Only a PUBLISHED proof may be rolled back.")
    sire = store.get("sires", rec["sire_id"])
    rec["status"] = "ROLLED_BACK"
    rec["rollback_reason"] = values["rollback_reason"]
    store.touch(rec)
    reinstated = store.get("genomic_evaluations", rec["supersedes_evaluation_id"]) \
        if rec["supersedes_evaluation_id"] else None
    if reinstated is not None:
        reinstated["status"] = "PUBLISHED"
        store.touch(reinstated)
        cascades.apply_published_snapshot(sire, reinstated)
    else:
        cascades.clear_published_snapshot(sire)
    cascades.restore_for_rollback(rec)
    return envelope.ok(serializers.genomic_evaluation(rec))
