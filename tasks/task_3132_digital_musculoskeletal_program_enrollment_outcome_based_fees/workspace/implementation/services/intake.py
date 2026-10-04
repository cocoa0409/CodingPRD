"""Intake and clinical routing: clients, care tracks, roster files, members,
enrollments, clinical reviews, transition reviews and contract lifecycle.

Sources: SCAFFOLD 1.2 state machines M1-M5, 1.5 endpoints; PRD 3.1, 3.3.
"""

from db import STORE, create, member_red_flag_weight
from errors import ApiError, invalid_reference, invalid_state, not_found
from services import billing, common
from utils import d, fmt, parse_iso, week_of, years_between


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def client(ident):
    return STORE.need("ClientAccount", ident, "ClientAccount")


def eligibility_file(ident):
    return STORE.need("EligibilityFile", ident, "EligibilityFile")


def member(ident):
    return STORE.need("Member", ident, "Member")


def enrollment(ident):
    return STORE.need("Enrollment", ident, "Enrollment")


def clinician(ident):
    return STORE.need("Clinician", ident, "Clinician")


def track(ident):
    return STORE.need("ProgramTrack", ident, "ProgramTrack")


def review(ident):
    return STORE.need("ClinicalReview", ident, "ClinicalReview")


def care_transition(ident):
    return STORE.need("CareTransition", ident, "CareTransition")


def members_of_file(file_id):
    return [m for m in STORE.all("Member") if m["eligibility_file_id"] == file_id]


def enrollments_of_member(member_id):
    return [e for e in STORE.all("Enrollment") if e["member_id"] == member_id]


def _strictly_older(birth):
    """True when the clock instant is strictly more than 18 years after `birth`."""
    mark = birth.replace(year=birth.year + 18)
    return STORE.clock > mark


def is_adult(member_row):
    """Screening rule: "at least 18 years before the current logical clock instant"."""
    birth = parse_iso(member_row.get("date_of_birth"))
    if birth is None:
        return False
    return years_between(birth, STORE.clock) >= 18


def is_strictly_over_18(member_row):
    """Enrollment rule (PRD 3.3): the member must be STRICTLY older than 18 at the
    current logical clock instant, so a member who is exactly 18 today is refused."""
    birth = parse_iso(member_row.get("date_of_birth"))
    if birth is None:
        return False
    return _strictly_older(birth)


# ---------------------------------------------------------------------------
# M1 -- ClientAccount
# ---------------------------------------------------------------------------
def create_client(payload):
    legal_name = payload.get("legal_name")
    if not legal_name:
        raise invalid_reference("legal_name is required.")
    client_type = payload.get("client_type")
    if client_type not in ("EMPLOYER", "HEALTH_PLAN"):
        raise invalid_reference("client_type must be EMPLOYER or HEALTH_PLAN.")
    billing_model = payload.get("billing_model") or "ENGAGEMENT_MILESTONE"
    if billing_model not in ("ENGAGEMENT_MILESTONE", "OUTCOME_SHARED_SAVINGS"):
        raise invalid_reference("billing_model is not recognised.")
    savings_share_rate = d(payload.get("savings_share_rate", 0.30))
    if savings_share_rate < 0 or savings_share_rate > 1:
        raise invalid_reference("savings_share_rate must lie between 0 and 1.")
    expected = d(payload.get("expected_monthly_engagement_rate", 0.60))
    if expected < 0 or expected > 1:
        raise invalid_reference(
            "expected_monthly_engagement_rate must lie between 0 and 1."
        )
    row = create("ClientAccount", {
        "legal_name": legal_name,
        "client_type": client_type,
        "billing_model": billing_model,
        "savings_share_rate": float(savings_share_rate),
        "expected_monthly_engagement_rate": float(expected),
        "account_status": "ACTIVE",
        "week_schedule_cursor": 0,
        "red_flag_escalation_count": 0,
    })
    return row


def suspend_client(client_id, reason):
    row = client(client_id)
    if not reason:
        raise invalid_reference("A suspension reason is required.")
    if row["account_status"] == "CLOSED":
        raise invalid_state("A closed client account cannot be suspended.")
    row["account_status"] = "SUSPENDED"
    STORE.touch("ClientAccount", row)

    for invoice in billing.invoices_of_client(client_id):
        if invoice["invoice_status"] == "DRAFT":
            invoice["invoice_status"] = "VOID"
            STORE.touch("FeeInvoice", invoice)

    for transition in STORE.all("CareTransition"):
        owned = STORE.get("Enrollment", transition.get("enrollment_id"))
        if not owned or common.member_of(owned) is None:
            continue
        owner = STORE.get("Member", owned["member_id"])
        if owner["client_account_id"] != client_id:
            continue
        if transition["transition_status"] == "PENDING":
            transition["transition_reason"] = "NO_ENGAGEMENT"
            STORE.touch("CareTransition", transition)

    for item in enrollments_of_client(client_id):
        if item["enrollment_status"] != "AWAITING_TRANSITION_REVIEW":
            continue
        item["enrollment_status"] = "ACTIVE"
        item["transition_reason"] = None
        item["pending_transition_clinician_id"] = None
        item["pain_reduction_points"] = 0.0
        item["function_gain_points"] = 0.0
        item["attributed_savings_cents"] = 0
        item["completed_week"] = None
        STORE.touch("Enrollment", item)
    return row


def reinstate_client(client_id):
    row = client(client_id)
    if row["account_status"] != "SUSPENDED":
        raise invalid_state("Only a suspended client account can be reinstated.")
    row["account_status"] = "ACTIVE"
    STORE.touch("ClientAccount", row)
    return row


def close_client(client_id):
    row = client(client_id)
    if row["account_status"] == "CLOSED":
        raise invalid_state("A closed client account cannot be closed again.")
    for file_row in STORE.all("EligibilityFile"):
        if file_row["client_account_id"] != client_id:
            continue
        if file_row["file_status"] == "SCREENED":
            raise invalid_state(
                "A client with a SCREENED roster file cannot be closed."
            )
    for invoice in billing.invoices_of_client(client_id):
        if invoice["invoice_status"] == "DRAFT":
            raise invalid_state(
                "A client with a DRAFT invoice cannot be closed."
            )
    row["account_status"] = "CLOSED"
    STORE.touch("ClientAccount", row)

    for file_row in STORE.all("EligibilityFile"):
        if file_row["client_account_id"] != client_id:
            continue
        if file_row["file_status"] != "CLOSED":
            file_row["file_status"] = "CLOSED"
            STORE.touch("EligibilityFile", file_row)

    for member_row in STORE.all("Member"):
        if member_row["client_account_id"] != client_id:
            continue
        if member_row["member_status"] not in ("PENDING_ELIGIBILITY", "ELIGIBLE"):
            continue
        member_row["member_status"] = "INELIGIBLE"
        member_row["eligibility_basis"] = "COVERAGE_TERM"
        STORE.touch("Member", member_row)
        # Depth-3 hop: caused by the member change, not by the close call.
        for item in enrollments_of_member(member_row["id"]):
            if item["enrollment_status"] in (
                "PENDING_SCREENING", "PENDING_CLINICAL_REVIEW"
            ):
                item["enrollment_status"] = "ACTIVATION_FAILED"
                STORE.touch("Enrollment", item)
    return row


def recompute_engagement_tier(client_id):
    row = client(client_id)
    summary = billing.milestone_summary(client_id, strict=False)
    row["engagement_tier_member_count"] = summary["milestone_member_count"]
    row["engagement_tier_amount_cents"] = summary[
        "milestone_engagement_component_cents"
    ]
    STORE.touch("ClientAccount", row)
    return row


def enrollments_of_client(client_id):
    out = []
    for item in STORE.all("Enrollment"):
        owner = STORE.get("Member", item["member_id"])
        if owner and owner["client_account_id"] == client_id:
            out.append(item)
    return out


# ---------------------------------------------------------------------------
# ProgramTrack
# ---------------------------------------------------------------------------
def create_track(payload, owner=None):
    track_code = payload.get("track_code")
    if track_code not in ("ACUTE", "CHRONIC", "SURGERY_AVOIDANCE"):
        raise invalid_reference("track_code is not recognised.")
    weights = payload.get("severity_weights")
    if not isinstance(weights, dict) or set(weights.keys()) != {"LOW", "HIGH"}:
        raise invalid_reference(
            "severity_weights must carry exactly the keys LOW and HIGH."
        )
    fields = {
        "track_code": track_code,
        "base_fee_per_member_cents": int(
            payload.get("base_fee_per_member_cents", 0)
        ),
        "expected_sessions_per_week": int(
            payload.get("expected_sessions_per_week", 0)
        ),
        "pain_reduction_target_points": payload.get(
            "pain_reduction_target_points", 0
        ),
        "function_gain_target_points": payload.get(
            "function_gain_target_points", 0
        ),
        "min_adherence_rate": float(payload.get("min_adherence_rate", 0.70)),
        "severity_weights": {
            "LOW": float(weights["LOW"]),
            "HIGH": float(weights["HIGH"]),
        },
        "client_account_id": owner,
    }
    from db import new_record

    row = new_record("ProgramTrack", fields)
    STORE.insert("ProgramTrack", row)
    return row


# ---------------------------------------------------------------------------
# M3 -- EligibilityFile intake and screening
# ---------------------------------------------------------------------------
def create_roster_file(payload):
    client_id = payload.get("client_account_id")
    owner = client(client_id)
    period = payload.get("file_period")
    if not isinstance(period, str) or len(period) != 7 or period[4] != "-":
        raise invalid_reference("file_period must match YYYY-MM.")
    try:
        month = int(period[5:])
        if not 1 <= month <= 12:
            raise ValueError
        int(period[:4])
    except ValueError:
        raise invalid_reference("file_period must match YYYY-MM.")
    roster_format = payload.get("roster_format")
    if roster_format not in ("STANDARD", "LEGACY"):
        raise invalid_reference("roster_format must be STANDARD or LEGACY.")
    # Recency guard (PRD 3.1): a new file's period must be strictly later than the
    # client's greatest existing roster period.  It is a temporal-window check and
    # so outranks the fiscal ERR_CLIENT_NOT_ACTIVE check below.
    greatest = None
    for file_row in STORE.all("EligibilityFile"):
        if file_row["client_account_id"] != client_id:
            continue
        if file_row["file_period"] > (greatest or ""):
            greatest = file_row["file_period"]
    if greatest is not None and period <= greatest:
        raise ApiError(
            "ERR_FILE_PERIOD_REGRESSION",
            "The roster period %s is not strictly later than %s."
            % (period, greatest),
        )
    if owner["account_status"] != "ACTIVE":
        raise ApiError(
            "ERR_CLIENT_NOT_ACTIVE",
            "Roster files may only be ingested for an ACTIVE client.",
        )
    row = create("EligibilityFile", {
        "client_account_id": client_id,
        "file_period": period,
        "roster_format": roster_format,
        "file_status": "INGESTED",
        "member_row_count": 0,
        "eligible_member_count": 0,
        "ineligible_member_count": 0,
        "screened_member_count": 0,
        "total_monthly_fee_cents": 0,
        "provisional_total_monthly_fee_cents": 0,
        "fee_variance_cents": 0,
    }, increments=[("ClientAccount", owner)])
    return row


def create_member(payload):
    client_id = payload.get("client_account_id")
    owner = client(client_id)
    file_id = payload.get("eligibility_file_id")
    file_row = eligibility_file(file_id)
    reference = payload.get("external_member_ref")
    if not reference:
        raise invalid_reference("external_member_ref is required.")
    for other in STORE.all("Member"):
        if (other["client_account_id"] == client_id
                and other["external_member_ref"] == reference):
            raise invalid_reference(
                "external_member_ref must be unique within the client."
            )
    condition = payload.get("musculo_condition_code")
    if condition not in (
        "KNEE_OA", "LOW_BACK", "SHOULDER", "HIP", "NECK", "OTHER"
    ):
        raise invalid_reference("musculo_condition_code is not recognised.")
    baseline_pain = d(payload.get("baseline_pain_score", 0))
    if baseline_pain < 0 or baseline_pain > 10:
        raise ApiError(
            "ERR_VITALS_OUT_OF_RANGE", "baseline_pain_score must be within [0, 10]."
        )
    baseline_function = d(payload.get("baseline_function_score", 0))
    if baseline_function < 0 or baseline_function > 100:
        raise ApiError(
            "ERR_VITALS_OUT_OF_RANGE",
            "baseline_function_score must be within [0, 100].",
        )
    row = create("Member", {
        "client_account_id": client_id,
        "eligibility_file_id": file_id,
        "external_member_ref": reference,
        "full_name": payload.get("full_name"),
        "date_of_birth": fmt(parse_iso(payload.get("date_of_birth")))
        if payload.get("date_of_birth") else None,
        "musculo_condition_code": condition,
        "baseline_pain_score": float(baseline_pain),
        "baseline_function_score": float(baseline_function),
        "red_flag_multipliers": list(payload.get("red_flag_multipliers") or []),
        "red_flag_weight": 0.0,
        "coach_escalated": False,
        "member_status": "PENDING_ELIGIBILITY",
        "eligibility_basis": None,
        "last_escalated_week": None,
    }, increments=[("EligibilityFile", file_row)])
    row["red_flag_weight"] = member_red_flag_weight(row)
    return row


def recompute_eligibility(member_id):
    row = member(member_id)
    if row["eligibility_basis"] == "COVERAGE_TERM":
        raise invalid_state(
            "A member whose basis is COVERAGE_TERM is not revisited."
        )
    if row["member_status"] not in (
        "PENDING_ELIGIBILITY", "ELIGIBLE", "INELIGIBLE", "ENROLLED"
    ):
        raise invalid_state("This member cannot be re-evaluated.")
    if row["member_status"] == "ENROLLED":
        # The demographic rule moves the member's status only in the ways the
        # workflow declares; an engaged member's ENROLLED axis is not disturbed
        # by a basis-axis move (PRD 3.1).
        row["eligibility_basis"] = "DEMOGRAPHICS"
        STORE.touch("Member", row)
        return row
    if is_adult(row):
        row["member_status"] = "ELIGIBLE"
    else:
        row["member_status"] = "INELIGIBLE"
    row["eligibility_basis"] = "DEMOGRAPHICS"
    STORE.touch("Member", row)
    return row


def screen_eligibility_file(file_id):
    file_row = eligibility_file(file_id)
    if file_row["file_status"] != "INGESTED":
        raise invalid_state("Only an INGESTED roster file can be screened.")
    rows = members_of_file(file_id)
    if not rows:
        raise invalid_state("A roster file with no member rows cannot be screened.")
    client_row = client(file_row["client_account_id"])
    for member_row in rows:
        if member_row["member_status"] != "PENDING_ELIGIBILITY":
            continue
        if (member_row["musculo_condition_code"] != "OTHER"
                and is_adult(member_row)):
            member_row["member_status"] = "ELIGIBLE"
            member_row["eligibility_basis"] = "MSK_FLAG"
        else:
            member_row["member_status"] = "INELIGIBLE"
            member_row["eligibility_basis"] = "NO_MSK_FLAG"
        STORE.touch("Member", member_row)

    variants = billing.roster_fee_variants(file_row)
    file_row["member_row_count"] = variants["member_row_count"]
    file_row["eligible_member_count"] = variants["eligible_member_count"]
    file_row["ineligible_member_count"] = variants["ineligible_member_count"]
    file_row["screened_member_count"] = variants["screened_member_count"]
    file_row["total_monthly_fee_cents"] = variants["total_monthly_fee_cents"]
    file_row["provisional_total_monthly_fee_cents"] = variants[
        "provisional_total_monthly_fee_cents"
    ]
    file_row["fee_variance_cents"] = variants["fee_variance_cents"]
    file_row["file_status"] = "SCREENED"
    STORE.touch("EligibilityFile", file_row)
    STORE.touch("ClientAccount", client_row)
    return file_row


def assign_tracks(file_id, payload):
    file_row = eligibility_file(file_id)
    if file_row["file_status"] != "SCREENED":
        raise invalid_state("Only a SCREENED roster file can be assigned.")
    client_row = client(file_row["client_account_id"])
    if "expected_client_account_version" not in payload:
        raise invalid_reference("expected_client_account_version is required.")
    expected = int(payload["expected_client_account_version"])
    if expected != client_row["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "The client account has moved since version %d." % expected,
        )
    if file_row["eligible_member_count"] < 1:
        raise invalid_state("A roster file with no eligible member can be assigned.")

    created = []
    now = fmt(STORE.clock)
    for member_row in members_of_file(file_id):
        if member_row["member_status"] != "ELIGIBLE":
            continue
        item = common.create_enrollment(member_row, file_id, "PENDING_SCREENING")
        # Auto-advance PENDING_SCREENING -> PENDING_CLINICAL_REVIEW.
        item["enrollment_status"] = "PENDING_CLINICAL_REVIEW"
        item["review_pending_since"] = now
        item["version"] = 2
        item["updated_at"] = now
        created.append(item)
    file_row["file_status"] = "ASSIGNED"
    STORE.touch("EligibilityFile", file_row)
    STORE.touch("ClientAccount", client_row)
    return file_row


def close_file(file_id):
    file_row = eligibility_file(file_id)
    if file_row["file_status"] != "ASSIGNED":
        raise invalid_state("Only an ASSIGNED roster file can be closed.")
    for item in STORE.all("Enrollment"):
        if item.get("eligibility_file_id") != file_id:
            continue
        if item["enrollment_status"] == "PENDING_SCREENING":
            raise invalid_state(
                "A roster file with an enrollment still in screening cannot close."
            )
    file_row["file_status"] = "CLOSED"
    STORE.touch("EligibilityFile", file_row)
    return file_row


# ---------------------------------------------------------------------------
# M4 -- Enrollment
# ---------------------------------------------------------------------------
def open_enrollment(payload):
    member_row = member(payload.get("member_id"))
    file_id = payload.get("eligibility_file_id")
    if file_id is not None:
        eligibility_file(file_id)
    if not is_strictly_over_18(member_row):
        raise ApiError(
            "ERR_PATIENT_UNDERAGE",
            "A member under 18 years at the current clock instant cannot enroll.",
        )
    item = common.create_enrollment(
        member_row, file_id, "PENDING_CLINICAL_REVIEW", fmt(STORE.clock)
    )
    STORE.touch("Member", member_row)
    return item


def drop_enrollment(enrollment_id):
    item = enrollment(enrollment_id)
    member_row = member(item["member_id"])
    if item["enrollment_status"] != "ACTIVE":
        if item["enrollment_status"] != "DROPPED":
            raise invalid_state("Only an ACTIVE enrollment can be dropped.")
        if member_row["member_status"] == "ENROLLED":
            # CYCLIC EDGE: a dropped enrollment releases its member to ELIGIBLE.
            member_row["member_status"] = "ELIGIBLE"
            STORE.touch("Member", member_row)
        # A further drop on an enrollment that is already DROPPED is a no-op that
        # still reports success; the member axis has already been released.
        return item

    # The droppable window is the enrollment's first four MEASURED weeks: the
    # enrollment week itself is the anchor and weeks 1 through 4 are the four
    # weeks that follow it, so week 5 and beyond are outside (PRD 3.9 with the
    # scaffold's week_index 1..4 outreach evidence window).
    elapsed = week_of(STORE.clock) - item["enrolled_week"] - 1
    if elapsed >= 4:
        raise ApiError(
            "ERR_DROPOUT_WINDOW_CLOSED",
            "Drops are only available inside the first four measured weeks.",
        )
    missed = common.consecutive_missed(item)
    failed = common.failed_outreach_count(item)
    if missed < 3 and failed < 2:
        raise ApiError(
            "ERR_DROPOUT_CRITERIA_NOT_MET",
            "Neither the consecutive-missed nor the failed-outreach criterion holds.",
        )
    item["enrollment_status"] = "DROPPED"
    item["dropout_week"] = week_of(STORE.clock)
    STORE.touch("Enrollment", item)
    member_row["member_status"] = "DROPPED"
    STORE.touch("Member", member_row)
    return item


def complete_enrollment(enrollment_id):
    item = enrollment(enrollment_id)
    if item["enrollment_status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE enrollment can be completed.")
    finalized = common.measurements_of(enrollment_id, statuses=("FINALIZED",))
    if len(finalized) != 1:
        raise ApiError(
            "ERR_NO_FINALIZED_MEASUREMENT",
            "The enrollment must carry exactly one FINALIZED measurement.",
        )
    item["enrollment_status"] = "COMPLETED"
    item["completed_week"] = finalized[0]["measurement_week"]
    STORE.touch("Enrollment", item)
    member_row = member(item["member_id"])
    member_row["member_status"] = "GRADUATED"
    STORE.touch("Member", member_row)
    return item


def transition_request(enrollment_id, payload, acting_clinician_id):
    item = enrollment(enrollment_id)
    if item["enrollment_status"] != "PENDING_CLINICAL_REVIEW":
        raise invalid_state(
            "A transition review can only be registered while the enrollment is "
            "PENDING_CLINICAL_REVIEW."
        )
    if item["clinical_review_outcome"] == "APPROVED":
        raise invalid_state(
            "An enrollment with an approving outcome is already on the handoff queue."
        )
    reason = payload.get("reason")
    if reason not in ("CLINICIAN_REQUEST", "NO_ENGAGEMENT", "ADVERSE_EVENT"):
        raise invalid_reference("reason is not recognised.")
    item["enrollment_status"] = "AWAITING_TRANSITION_REVIEW"
    item["transition_reason"] = reason
    item["pending_transition_clinician_id"] = acting_clinician_id
    STORE.touch("Enrollment", item)
    return item


# ---------------------------------------------------------------------------
# M5 -- ClinicalReview
# ---------------------------------------------------------------------------
def seed_review(payload):
    item = enrollment(payload.get("enrollment_id"))
    reviewer_id = payload.get("reviewer_id")
    if reviewer_id is not None:
        clinician(reviewer_id)
    row = create("ClinicalReview", {
        "enrollment_id": item["id"],
        "reviewer_id": reviewer_id,
        "reviewed_track_id": None,
        "review_decision": None,
        "review_notes": payload.get("review_notes"),
        "review_status": "SUBMITTED",
        "review_opened_at": fmt(STORE.clock),
        "conducted_at": None,
    })
    return row


def conduct_review(review_id, payload, acting_clinician_id):
    row = review(review_id)
    item = row["enrollment_id"] and STORE.get("Enrollment", row["enrollment_id"])
    if item is None:
        raise not_found("Enrollment")
    decision = payload.get("review_decision")
    if decision == "REJECT":
        if row["review_status"] != "SUBMITTED":
            raise ApiError(
                "ERR_REVIEW_ALREADY_CONDUCTED",
                "This clinical review has already been conducted.",
            )
        row["review_status"] = "CONDUCTED"
        row["review_decision"] = "REJECT"
        row["conducted_at"] = fmt(STORE.clock)
        if payload.get("reviewer_id"):
            row["reviewer_id"] = payload["reviewer_id"]
        STORE.touch("ClinicalReview", row)
        item["clinical_review_outcome"] = "REJECTED"
        STORE.touch("Enrollment", item)
        return row

    if decision not in (None, "APPROVE"):
        raise invalid_reference("review_decision must be APPROVE or REJECT.")
    # The refused edge that hangs off the review's own lifecycle is evaluated
    # first: a review that is already CONDUCTED is refused as such regardless of
    # where the enrollment has moved to in the meantime (PRD 2.10).
    if row["review_status"] != "SUBMITTED":
        raise ApiError(
            "ERR_REVIEW_ALREADY_CONDUCTED",
            "This clinical review has already been conducted.",
        )
    # Then the cross-entity gate: the enrollment must still be in the queue.
    if item["enrollment_status"] != "PENDING_CLINICAL_REVIEW":
        raise ApiError(
            "ERR_ENROLLMENT_NOT_IN_REVIEW",
            "The enrollment is not awaiting a clinical review.",
        )
    reviewed_track = track(payload.get("reviewed_track_id"))

    reviewer_id = payload.get("reviewer_id") or acting_clinician_id or row[
        "reviewer_id"
    ]
    row["review_status"] = "CONDUCTED"
    row["review_decision"] = "APPROVE"
    row["reviewed_track_id"] = reviewed_track["id"]
    row["reviewer_id"] = reviewer_id
    row["conducted_at"] = fmt(STORE.clock)
    STORE.touch("ClinicalReview", row)

    item["program_track_id"] = reviewed_track["id"]
    item["clinical_review_outcome"] = "APPROVED"
    item["clinical_reviewing_clinician_id"] = reviewer_id
    item["enrollment_status"] = "AWAITING_TRANSITION_REVIEW"
    item["transition_reason"] = "CLINICIAN_REQUEST"
    item["pending_transition_clinician_id"] = reviewer_id
    STORE.touch("Enrollment", item)
    return row


def reopen_review(review_id):
    row = review(review_id)
    if row["review_status"] != "CONDUCTED":
        raise invalid_state("Only a CONDUCTED review can be reopened.")
    item = enrollment(row["enrollment_id"])
    if item["enrollment_status"] != "AWAITING_TRANSITION_REVIEW":
        raise invalid_state(
            "The enrollment must be AWAITING_TRANSITION_REVIEW to reopen its review."
        )
    row["review_status"] = "SUBMITTED"
    row["conducted_at"] = None
    STORE.touch("ClinicalReview", row)

    item["clinical_review_outcome"] = None
    item["program_track_id"] = None
    item["enrollment_status"] = "PENDING_CLINICAL_REVIEW"
    item["review_pending_since"] = fmt(STORE.clock)
    item["transition_reason"] = None
    item["pending_transition_clinician_id"] = None
    STORE.touch("Enrollment", item)
    return row


# ---------------------------------------------------------------------------
# Transition reviews (the path segment is the ENROLLMENT)
# ---------------------------------------------------------------------------
def approve_transition(enrollment_id, payload, acting_clinician_id):
    item = enrollment(enrollment_id)
    approver = payload.get("approving_clinician_id") or acting_clinician_id
    if approver is not None:
        clinician(approver)
    # Priority 5: segregation of duties -- safety before state.
    if (item.get("clinical_reviewing_clinician_id") is not None
            and approver == item["clinical_reviewing_clinician_id"]):
        raise ApiError(
            "ERR_CLINICIAN_DUAL_ROLE",
            "The reviewing clinician may not also approve the in-person handoff.",
        )
    if item["enrollment_status"] not in (
        "PENDING_CLINICAL_REVIEW", "AWAITING_TRANSITION_REVIEW"
    ):
        raise ApiError(
            "ERR_TRANSITION_NOT_PENDING",
            "No transition review is pending on this enrollment.",
        )
    file_row = None
    if item.get("eligibility_file_id"):
        file_row = eligibility_file(item["eligibility_file_id"])
    if "expected_eligibility_file_version" not in payload:
        raise invalid_reference("expected_eligibility_file_version is required.")
    expected = int(payload["expected_eligibility_file_version"])
    if file_row is None:
        if expected != 1:
            raise ApiError(
                "ERR_STALE_VERSION",
                "The expected eligibility file version does not match.",
            )
    elif expected != file_row["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "The eligibility file has moved since version %d." % expected,
        )

    now = fmt(STORE.clock)
    item["enrollment_status"] = "ACTIVE"
    item["enrolled_at"] = now
    item["enrolled_week"] = week_of(STORE.clock)
    item["pain_reduction_points"] = 0.0
    item["function_gain_points"] = 0.0
    item["attributed_savings_cents"] = 0
    item["completed_week"] = None
    item["transition_reason"] = None
    item["pending_transition_clinician_id"] = None
    item["weeks_active"] = 0
    item["adherence_rate"] = 0.0
    item["dropout_risk_score"] = 0
    item["coach_escalation_required"] = False
    STORE.touch("Enrollment", item)

    create("CareTransition", {
        "enrollment_id": item["id"],
        "approving_clinician_id": approver,
        "transition_status": "PENDING",
        "transitioned_at": None,
        "transition_reason": None,
        "handoff_referral_count": 0,
    })

    member_row = member(item["member_id"])
    if all(e["enrollment_status"] == "ACTIVE"
           for e in enrollments_of_member(member_row["id"])):
        member_row["member_status"] = "ENROLLED"
        STORE.touch("Member", member_row)
    if file_row is not None:
        STORE.touch("EligibilityFile", file_row)
    return item


def deny_transition(enrollment_id, payload, acting_clinician_id):
    item = enrollment(enrollment_id)
    approver = payload.get("approving_clinician_id") or acting_clinician_id
    if item["enrollment_status"] != "AWAITING_TRANSITION_REVIEW":
        raise ApiError(
            "ERR_TRANSITION_NOT_PENDING",
            "No transition review is pending on this enrollment.",
        )
    if approver != item["pending_transition_clinician_id"]:
        raise ApiError(
            "ERR_TRANSITION_REVIEWER_MISMATCH",
            "Only the clinician who registered the review may deny it.",
        )
    item["enrollment_status"] = "PENDING_CLINICAL_REVIEW"
    item["review_pending_since"] = fmt(STORE.clock)
    item["transition_reason"] = None
    item["pending_transition_clinician_id"] = None
    # The enrollment is back in the review queue without an approving decision:
    # PRD 3.3 requires that a denied handoff can be re-registered, and the
    # registration route refuses an enrollment that still carries an approving
    # outcome, so the stale decision is cleared with the queue return.
    item["clinical_review_outcome"] = None
    STORE.touch("Enrollment", item)
    return item


# ---------------------------------------------------------------------------
# M12 -- CareTransition
# ---------------------------------------------------------------------------
def open_care_transition(payload):
    item = enrollment(payload.get("enrollment_id"))
    approver = payload.get("approving_clinician_id")
    if approver is not None:
        clinician(approver)
    if item["enrollment_status"] != "ACTIVE":
        raise invalid_state("A handoff can only be opened on an ACTIVE enrollment.")
    row = create("CareTransition", {
        "enrollment_id": item["id"],
        "approving_clinician_id": approver,
        "transition_status": "PENDING",
        "transitioned_at": None,
        "transition_reason": None,
        "handoff_referral_count": 0,
    })
    STORE.touch("Enrollment", item)
    return row


def complete_care_transition(transition_id, acting_clinician_id=None):
    row = care_transition(transition_id)
    item = enrollment(row["enrollment_id"])
    if row["transition_status"] != "PENDING":
        raise ApiError(
            "ERR_TRANSITION_NOT_PENDING",
            "This handoff is not pending.",
        )
    # Segregation of duties guards completion as well as activation.
    if (item.get("clinical_reviewing_clinician_id") is not None
            and row.get("approving_clinician_id")
            and row["approving_clinician_id"]
            == item["clinical_reviewing_clinician_id"]):
        raise ApiError(
            "ERR_CLINICIAN_DUAL_ROLE",
            "The reviewing clinician may not also complete the in-person handoff.",
        )
    if item["enrollment_status"] != "ACTIVE":
        raise invalid_state("The enrollment must be ACTIVE to complete a handoff.")
    row["transition_status"] = "COMPLETED"
    row["transitioned_at"] = fmt(STORE.clock)
    # The referral counter accumulates across every handoff of the enrollment
    # rather than being reset, so an enrollment handed off, reverted and handed
    # off again reports two referrals (PRD 3.9).
    completed_rows = [
        t for t in STORE.all("CareTransition")
        if t["enrollment_id"] == item["id"]
    ]
    row["handoff_referral_count"] = 1 + sum(
        int(t.get("handoff_referral_count") or 0)
        for t in completed_rows
        if t["id"] != row["id"] and t["transition_status"] == "COMPLETED"
    )
    STORE.touch("CareTransition", row)
    item["enrollment_status"] = "TRANSITIONED"
    STORE.touch("Enrollment", item)
    member_row = member(item["member_id"])
    member_row["member_status"] = "ELIGIBLE"
    STORE.touch("Member", member_row)
    return row