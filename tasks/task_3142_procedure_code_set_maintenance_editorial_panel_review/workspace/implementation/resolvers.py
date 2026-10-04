"""Left-to-right existence resolution (PRD.md 2.6).

A path-identified resource or a referenced body foreign key that does not
resolve produces ERR_NOT_FOUND at 404, and this runs before any business
constraint.  Path identifiers are resolved strictly from left to right, so the
caller must fetch the outer identifier before the inner one.
"""

import store
from errors import ERR_NOT_FOUND, ApiError


def resolve(table, row_id, label):
    record = table.get(row_id) if row_id else None
    if record is None:
        raise ApiError(ERR_NOT_FOUND, "%s not found" % label)
    return record


def resolve_optional(table, row_id):
    if row_id is None or row_id == "":
        return None
    return table.get(row_id)


def society(row_id):
    return resolve(store.societies, row_id, "SpecialtySociety")


def applicant(row_id):
    return resolve(store.applicants, row_id, "ChangeApplicant")


def code_change(row_id):
    return resolve(store.code_changes, row_id, "CodeChange")


def committee_review(row_id):
    return resolve(store.committee_reviews, row_id, "AdvisoryCommitteeReview")


def meeting(row_id):
    return resolve(store.meetings, row_id, "EditorialPanelMeeting")


def public_comment(row_id):
    return resolve(store.public_comments, row_id, "PublicComment")


def vote(row_id):
    return resolve(store.editorial_votes, row_id, "EditorialVote")


def valuation(row_id):
    return resolve(store.valuations, row_id, "RUCValueRecommendation")


def code_value(row_id):
    return resolve(store.code_values, row_id, "CodeValue")


def errata_notice(row_id):
    return resolve(store.errata_notices, row_id, "ErrataNotice")


def release_cycle(row_id):
    return resolve(store.release_cycles, row_id, "ReleaseCycle")


def license(row_id):
    return resolve(store.licenses, row_id, "LicensingAgreement")


def territory(row_id):
    return resolve(store.territories, row_id, "DistributionTerritory")


def delivery(row_id):
    return resolve(store.deliveries, row_id, "ContentDeliveryOrder")


def education(row_id):
    return resolve(store.education_activities, row_id, "CodingEducationActivity")


def interpretation(row_id):
    return resolve(store.interpretation_requests, row_id, "InterpretationRequest")


def errata_review(row_id):
    return resolve(store.errata_reviews, row_id, "ReviewErratum")


def fk(table, row_id, label):
    """Resolve a body-supplied foreign key; None stays None for nullable FKs."""
    if row_id is None or row_id == "":
        return None
    return resolve(table, row_id, label)