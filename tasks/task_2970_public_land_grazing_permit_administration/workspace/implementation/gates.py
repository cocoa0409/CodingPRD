"""The numbered business gates of PRD 2.6 that more than one route needs."""

from datetime import date

import calc
import derive
from errors import ApiError
import store


def state(error_id, message):
    raise ApiError(error_id, message)


def closed(allotment):
    """Priority 9."""
    if allotment["allotment_status"] == "CLOSED":
        raise ApiError("ERR_ALLOTMENT_CLOSED",
                       "the allotment is closed to livestock")


def has_effective_stocking_adjustment(allotment_id):
    for decision in store.rows("decisions"):
        if decision["allotment_id"] == allotment_id \
                and decision["decision_type"] == "STOCKING_ADJUSTMENT" \
                and decision["decision_status"] == "EFFECTIVE":
            return True
    return False


def health(allotment):
    """Priority 10."""
    if allotment["health_determination"] == "NOT_MEETING" \
            and not has_effective_stocking_adjustment(allotment["id"]):
        raise ApiError("ERR_HEALTH_STANDARDS_NOT_MET",
                       "the allotment is not meeting rangeland health standards")


def qualified(base_property, aums):
    """Priority 16."""
    if base_property is None \
            or aums > calc.qualified_aums(base_property["base_property_type"],
                                          base_property["carrying_capacity_aums"]):
        raise ApiError("ERR_INSUFFICIENT_QUALIFIED_AUMS",
                       "the base property does not qualify that many AUMs")


def debt(permittee_id):
    """Priority 28."""
    if derive.outstanding_balance_cents(permittee_id) > 0:
        raise ApiError("ERR_OUTSTANDING_BALANCE",
                       "the permittee carries an outstanding balance")


def capacity(allotment, aums):
    """Priority 30."""
    if aums > derive.open_aums(allotment):
        raise ApiError("ERR_ALLOTMENT_CAPACITY_EXCEEDED",
                       "the allotment has insufficient open AUMs")


def season_window(allotment, grazing_year):
    """The allotment's recurring MM-DD season resolved against a grazing year."""
    start_month, start_day = allotment["season_start"].split("-")
    end_month, end_day = allotment["season_end"].split("-")
    return (date(grazing_year, int(start_month), int(start_day)),
            date(grazing_year, int(end_month), int(end_day)))


def season(message):
    raise ApiError("ERR_SEASON_OF_USE_VIOLATION", message)
