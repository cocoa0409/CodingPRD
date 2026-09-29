"""Cross-entity cascades: substitution, publication, withdrawal, roll-ups."""

from decimal import Decimal

from db import (
    MEDIA_NOTIFY_DELTA,
    SOURCE_PRECEDENCE,
    collection,
    d,
    lookup,
    new_row,
    parse_iso,
    q2,
    rows,
    store,
    touch,
)
from services import calc, scoring

FILING_NUMERIC_FIELDS = [
    "total_expense_cents",
    "program_expense_cents",
    "fundraising_expense_cents",
    "admin_expense_cents",
    "contributions_cents",
    "total_revenue_cents",
    "net_assets_cents",
    "total_liabilities_cents",
    "grants_paid_cents",
    "membership_services_cents",
    "joint_cost_allocated_cents",
]
FILING_COPY_FIELDS = ["fiscal_year", "source_kind"] + FILING_NUMERIC_FIELDS

GOVERNANCE_FIELDS = [
    "board_member_count",
    "independent_board_member_count",
    "conflict_of_interest_policy_on_file",
    "coi_policy_reviewed_at",
    "board_meetings_last_year",
    "audit_committee_exists",
    "whistleblower_policy",
    "ceo_compensation_reviewed",
    "impact_report_on_file",
    "outcome_measures_count",
    "third_party_evaluation_on_file",
]

INT_GOVERNANCE_FIELDS = {
    "board_member_count",
    "independent_board_member_count",
    "board_meetings_last_year",
    "outcome_measures_count",
}
BOOL_GOVERNANCE_FIELDS = {
    "conflict_of_interest_policy_on_file",
    "audit_committee_exists",
    "whistleblower_policy",
    "ceo_compensation_reviewed",
    "impact_report_on_file",
    "third_party_evaluation_on_file",
}


def _coerce_int(text, fallback=0):
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        try:
            return int(float(str(text).strip()))
        except (TypeError, ValueError):
            return fallback


def _coerce_bool(text):
    return str(text).strip().lower() in ("true", "1", "yes")


# ---------------------------------------------------------------- roll-ups


def refresh_substantiated_count(organization):
    organization["substantiated_complaint_count"] = sum(
        1
        for c in rows("Complaint")
        if c["organization_id"] == organization["id"] and c["status"] == "SUBSTANTIATED"
    )


def publication_rows_for(organization_id):
    out = [
        r for r in rows("PublicationRecord") if r["organization_id"] == organization_id
    ]
    out.sort(key=lambda r: r["sequence_number"])
    return out


def refresh_publication_rollups(organization, record):
    organization["latest_published_score"] = record["published_score"]
    organization["latest_published_grade"] = record["published_grade"]
    organization["published_cycle_count"] = record["sequence_number"]
    if record["change_direction"] == "FIRST_PUBLICATION":
        organization["trend_direction"] = "NOT_APPLICABLE"
    else:
        organization["trend_direction"] = record["change_direction"]


def refresh_active_grace(organization):
    active = [
        g
        for g in rows("TransitionGrant")
        if g["organization_id"] == organization["id"] and g["status"] == "ACTIVE"
    ]
    if not active:
        organization["transition_grace_until"] = None


# ---------------------------------------------------------------- substitution


def apply_substitution(cycle, correction):
    """The accepted change lands by substitution, never by mutation in place."""
    if correction["target_kind"] == "FILING_FINANCIAL":
        target = None
        for filing in rows("FilingRecord"):
            if (
                filing["organization_id"] == cycle["organization_id"]
                and filing["fiscal_year"] == correction["target_fiscal_year"]
                and filing["source_kind"] == correction["target_source_kind"]
                and filing["status"] == "VALIDATED"
            ):
                target = filing
                break
        if target is None:
            return
        target["status"] = "SUPERSEDED"
        target["superseded_at"] = store.now()
        touch(target)

        payload = {field: target[field] for field in FILING_COPY_FIELDS}
        field = correction["target_field_name"]
        if field in FILING_NUMERIC_FIELDS or field == "fiscal_year":
            payload[field] = _coerce_int(correction["proposed_value"], payload.get(field, 0))
        elif field == "source_kind":
            payload["source_kind"] = correction["proposed_value"]
        new_row(
            "FilingRecord",
            dict(
                organization_id=cycle["organization_id"],
                source_precedence=SOURCE_PRECEDENCE.get(payload["source_kind"], 3),
                status="VALIDATED",
                origin="CORRECTION_APPLIED",
                validated_at=store.now(),
                rejection_code=None,
                superseded_at=None,
                **payload
            ),
        )
        return

    # GOVERNANCE_DISCLOSURE
    profile = scoring.profile_for_cycle(cycle)
    if profile is None:
        return
    field = correction["target_field_name"]
    value = correction["proposed_value"]
    if field in INT_GOVERNANCE_FIELDS:
        profile[field] = _coerce_int(value, profile.get(field, 0))
    elif field in BOOL_GOVERNANCE_FIELDS:
        profile[field] = _coerce_bool(value)
    elif field == "coi_policy_reviewed_at":
        profile[field] = parse_iso(value)
    profile["evaluation_status"] = "PENDING"
    profile["evaluated_at"] = None
    for row in list(scoring.standard_rows(profile)):
        collection("StandardEvaluation").pop(row["id"], None)
    profile["standards_met_count"] = 0
    profile["standards_not_met_count"] = 0
    profile["standards_waived_count"] = 0
    profile["standards_not_applicable_count"] = 0
    touch(profile)


def clear_review_track(cycle):
    cycle["review_opened_at"] = None
    cycle["correction_deadline_at"] = None
    cycle["appeal_deadline_at"] = None


def clear_provisional(cycle):
    cycle["weighted_sum_provisional"] = None
    cycle["provisional_composite_score"] = None
    cycle["provisional_grade"] = None


def open_corrections(cycle):
    return [
        c
        for c in rows("CorrectionRequest")
        if c["rating_cycle_id"] == cycle["id"]
        and c["status"] in ("SUBMITTED", "UNDER_ANALYST_REVIEW")
    ]


def open_appeals(cycle):
    return [
        a
        for a in rows("Appeal")
        if a["rating_cycle_id"] == cycle["id"]
        and a["status"] in ("FILED", "PANEL_ASSIGNED")
    ]


def cascade_reject_corrections(cycle, note):
    for correction in open_corrections(cycle):
        correction["status"] = "REJECTED"
        correction["decision_note"] = note
        correction["decided_by_user_id"] = None
        correction["decided_at"] = store.now()
        touch(correction)


def cascade_dismiss_appeals(cycle, note):
    for appeal in open_appeals(cycle):
        appeal["status"] = "DISMISSED"
        appeal["decision_note"] = note
        appeal["decided_by_user_id"] = None
        appeal["decided_at"] = store.now()
        touch(appeal)


# ---------------------------------------------------------------- publication


def publish(cycle, reviewer_user_id):
    organization = lookup("Organization", cycle["organization_id"])
    methodology = scoring.methodology_for(cycle)

    # hop 1 - recompute the final family from the current rows, then publish
    scoring.refresh_row_weights(cycle)
    scoring.finalize_scores(cycle, False, True)
    cycle["published_at"] = store.now()
    cycle["publishing_reviewer_user_id"] = reviewer_user_id
    cycle["status"] = "PUBLISHED"
    touch(cycle)

    # hop 2 - append the immutable ledger row
    existing = publication_rows_for(organization["id"])
    sequence_number = len(existing) + 1
    published_score = cycle["final_composite_score"]
    previous_score = None
    delta = None
    if sequence_number == 1:
        direction = "FIRST_PUBLICATION"
    else:
        predecessor = None
        for row in existing:
            if row["sequence_number"] == sequence_number - 1:
                predecessor = row
                break
        previous_score = predecessor["published_score"] if predecessor else None
        if previous_score is None:
            delta = None
            direction = "UNCHANGED"
        else:
            delta = q2(d(published_score) - d(previous_score))
            if delta > 0:
                direction = "IMPROVED"
            elif delta < 0:
                direction = "DECLINED"
            else:
                direction = "UNCHANGED"

    notified = ["RATED_ORGANIZATION"]
    if direction != "FIRST_PUBLICATION" and delta is not None:
        if abs(delta) >= MEDIA_NOTIFY_DELTA:
            notified.append("MEDIA")

    record = new_row(
        "PublicationRecord",
        dict(
            rating_cycle_id=cycle["id"],
            organization_id=organization["id"],
            sequence_number=sequence_number,
            published_score=published_score,
            published_grade=cycle["grade"],
            previous_published_score=previous_score,
            score_delta=delta,
            change_direction=direction,
            methodology_version_label=methodology["version_label"],
            weighted_sum_final=cycle["weighted_sum_final"],
            standards_penalty_points=cycle["standards_penalty_points"],
            notified_recipient_kinds=notified,
            published_at=cycle["published_at"],
        ),
        versioned=False,
    )

    # hop 3 - roll-ups
    refresh_publication_rollups(organization, record)
    touch(organization)
    return record


def accept_and_rewind(cycle, correction):
    """The acceptance cascade shared by a correction ACCEPT and an appeal GRANT."""
    # hop 2 - the cycle rewinds to data collection
    cycle["status"] = "DATA_COLLECTION"
    cycle["correction_round"] = int(cycle["correction_round"] or 0) + 1
    clear_review_track(cycle)
    clear_provisional(cycle)
    # hop 3 - the substitution the target_kind selects, then stale rows
    apply_substitution(cycle, correction)
    scoring.mark_rows_stale(cycle)
    # hop 4 - only the governance path deleted standard rows
    if correction["target_kind"] == "GOVERNANCE_DISCLOSURE":
        cycle["failed_standard_count"] = 0
    touch(cycle)
