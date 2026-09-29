"""Path and body identifier resolution (ladder steps 4 and 6)."""

import store
from errors import ApiError


def _get(collection, ident, error_id, label):
    if not isinstance(ident, str):
        raise ApiError(error_id, "%s was not found." % label)
    rec = collection.get(ident)
    if rec is None:
        raise ApiError(error_id, "%s '%s' was not found." % (label, ident))
    return rec


def program(ident):
    return _get(store.programs, ident, "ERR_PROGRAM_NOT_FOUND", "Breeding program")


def objective(ident):
    return _get(store.objectives, ident, "ERR_OBJECTIVE_NOT_FOUND", "Breeding objective")


def nursery_block(ident):
    return _get(store.nursery_blocks, ident, "ERR_NURSERY_BLOCK_NOT_FOUND", "Nursery block")


def crossing_block(ident):
    return _get(store.crossing_blocks, ident, "ERR_CROSSING_BLOCK_NOT_FOUND", "Crossing block")


def line(ident):
    return _get(store.lines, ident, "ERR_LINE_NOT_FOUND", "Breeding line")


def planting(ident):
    return _get(store.plantings, ident, "ERR_PLANTING_NOT_FOUND", "Nursery planting")


def site(ident):
    return _get(store.sites, ident, "ERR_TRIAL_SITE_NOT_FOUND", "Trial site")


def series(ident):
    return _get(store.series, ident, "ERR_TRIAL_SERIES_NOT_FOUND", "Trial series")


def entry(ident):
    return _get(store.entries, ident, "ERR_TRIAL_ENTRY_NOT_FOUND", "Trial entry")


def decision(ident):
    return _get(store.decisions, ident, "ERR_DECISION_NOT_FOUND", "Advancement decision")


def agreement(ident):
    return _get(store.agreements, ident, "ERR_AGREEMENT_NOT_FOUND", "Stewardship agreement")


def lot(ident):
    return _get(store.lots, ident, "ERR_SEED_LOT_NOT_FOUND", "Seed increase lot")


def project(ident):
    return _get(store.projects, ident, "ERR_BACKCROSS_NOT_FOUND", "Backcross project")


def program_open(program_record):
    """Ladder step 9."""
    if program_record is not None and program_record["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_CLOSED",
                       "The breeding programme behind this resource is CLOSED.")


def line_not_discarded(line_record):
    """Ladder step 16."""
    if line_record is not None and line_record["pipeline_stage"] == "DISCARDED":
        raise ApiError("ERR_LINE_DISCARDED", "The breeding line has been DISCARDED.")
