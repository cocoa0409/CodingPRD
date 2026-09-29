"""Licence lifecycle (PRD 3.6, 3.7) and coverage windows."""

from flask import Blueprint

import access
import calc
import db
import serializers
import services
from core import (
    BILLING_STATUSES,
    COVERAGE_STATUSES,
    REINSTATEMENT_BALANCE_LIMIT_CENTS,
    RENEWAL_OUTSTANDING_LIMIT_CENTS,
    ROLE_ADMIN,
    ROLE_AUDITOR,
    ROLE_OFFICER,
    ROLE_OPERATOR,
    SUSPENSION_REASONS,
    TERM_DAYS,
    WINDOW_KINDS,
    WINDOW_STATUSES,
    Ladder,
    P_AUDIT_HOLD,
    P_DEPARTURE_STATE,
    P_EFFECTIVE_SCHEDULE,
    P_INTERVAL,
    P_LICENSE_ACTIVE,
    P_NOT_RENEWED,
    P_REINSTATEMENT_BALANCE,
    P_RENEWAL_BALANCE,
    P_RENEWAL_TERM,
    P_REQUEST_SHAPE,
    P_STALE_PARENT,
    P_UNIQUENESS,
    P_VENUE_OPERATING,
    P_WINDOW_PLACEMENT,
    authenticate,
    conflict,
    invalid_interval,
    paginate,
    plus_days,
    precondition,
    query_enum,
    query_flag,
    query_str,
    read_body,
    read_pagination,
    respond_list,
    respond_object,
    validate_fields,
    whole_days,
)
from routes_applications import duplicate_active_license, terms_overlap

bp = Blueprint("licenses", __name__)

SUSPEND_SPEC = [("suspension_reason", "enum", {"required": True, "values": SUSPENSION_REASONS})]
TERMINATE_SPEC = [("void_unpaid_assessments", "bool", {"default": False})]
RENEW_SPEC = [
    ("requested_term_start", "instant", {"required": True}),
    ("expected_license_version", "int", {"required": True, "min": 0}),
]
WINDOW_SPEC = [
    ("window_kind", "enum", {"required": True, "values": WINDOW_KINDS}),
    ("window_start", "instant", {"required": True}),
    ("window_end", "instant", {"required": True}),
]


# ---------------------------------------------------------------------------
# PRD 3.6 -- activation
# ---------------------------------------------------------------------------


@bp.post("/licensing/licenses/<license_id>/activate")
def activate_license(license_id):
    user_id, role = authenticate([ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    license_row = access.fetch("licenses", license_id, access.ERR_LICENSE, narrow=False)
    venue = db.venue(license_row["venue_id"])
    state = {}

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if license_row["coverage_status"] != "PENDING_ACTIVATION":
            raise conflict(
                "ERR_LICENSE_STATE_INVALID", "Only a PENDING_ACTIVATION licence may be activated."
            )

    @ladder.check(P_VENUE_OPERATING)
    def _operating():
        if venue["status"] != "OPERATING":
            raise conflict("ERR_LICENSE_STATE_INVALID", "The venue is not OPERATING.")

    @ladder.check(P_AUDIT_HOLD)
    def _hold():
        if venue["audit_hold"]:
            raise conflict("ERR_AUDIT_HOLD_ACTIVE", "The venue is under an audit hold.")

    @ladder.check(P_UNIQUENESS)
    def _unique():
        if duplicate_active_license(
            license_row["venue_id"],
            license_row["society_id"],
            license_row["term_start"],
            license_row["term_end"],
            exclude_id=license_row["id"],
        ):
            raise conflict(
                "ERR_DUPLICATE_ACTIVE_LICENSE",
                "Another live licence of this venue and society overlaps this term.",
            )

    @ladder.check(P_EFFECTIVE_SCHEDULE)
    def _schedule():
        if calc.select_schedule(license_row["society_id"], venue["venue_category"]) is None:
            raise conflict(
                "ERR_NO_EFFECTIVE_RATE_SCHEDULE",
                "No EFFECTIVE rate schedule covers this society and venue category.",
            )

    ladder.run()
    del state

    society = db.society(license_row["society_id"])
    # (1) Re-rate against the *currently pinned* schedule (PRD 3.6).
    pinned = db.schedule(license_row["rate_schedule_id"])
    license_row["coverage_status"] = "ACTIVE"
    license_row["annual_fee_cents"] = calc.verified_fee(
        pinned, society, venue, license_row["license_type"]
    )
    license_row["verified_fee_delta_cents"] = (
        license_row["annual_fee_cents"] - license_row["provisional_annual_fee_cents"]
    )
    # The billing dimension advances in the same act as the coverage move.  PRD
    # 3.6 documents exactly one increment for activation -- the re-rate's -- and
    # PRD 2.11 says that when one call advances both dimensions of the same
    # licence "each documented increment applies", so the UNBILLED -> INVOICED
    # move is written into this mutation instead of adding a second one.
    if license_row["license_type"] != "BGM_EXEMPT":
        services.bill_on_activation(license_row, touch=False)
    db.touch(license_row)

    # (2) The inseparable annual coverage window.
    db.new_row(
        "coverage_windows",
        {
            "license_id": license_row["id"],
            "window_kind": "ANNUAL_TERM",
            "window_start": license_row["term_start"],
            "window_end": license_row["term_end"],
            "covered_day_count": TERM_DAYS,
            "rider_fee_cents": 0,
            "status": "ACTIVE",
        },
    )

    # (3) Billing -- unless the licence is exempt.  The licence's own
    # billing_status already moved with the re-rate above; what remains here is
    # the assessment the issuance raises.
    if license_row["license_type"] != "BGM_EXEMPT":
        kind = "INITIAL" if license_row["renewal_of_license_id"] is None else "RENEWAL"
        if license_row["annual_fee_cents"] >= 1:
            services.issue_assessment(
                venue, license_row["id"], None, kind, license_row["annual_fee_cents"]
            )

    # (4) The venue's ledger and coverage posture.
    services.recompute_venue(venue, ledger=True, coverage=True)

    # (5) The delinquency sweep.
    services.delinquency_sweep(venue)

    # (6) Conditional retirement of the predecessor.
    predecessor_id = license_row["renewal_of_license_id"]
    if predecessor_id is not None:
        predecessor = db.license_row(predecessor_id)
        if (
            predecessor is not None
            and predecessor["coverage_status"] == "ACTIVE"
            and db.now() >= predecessor["term_end"]
        ):
            predecessor["coverage_status"] = "EXPIRED"
            db.touch(predecessor)
            services.recompute_venue(venue, coverage=True)

    return respond_object(serializers.license_json(license_row))


# ---------------------------------------------------------------------------
# PRD 3.7 -- suspension, reinstatement, termination
# ---------------------------------------------------------------------------


@bp.post("/licensing/licenses/<license_id>/suspend")
def suspend_license(license_id):
    user_id, role = authenticate([ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    license_row = access.fetch("licenses", license_id, access.ERR_LICENSE, narrow=False)
    body = read_body()
    state = {}

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        state["fields"] = validate_fields(body, SUSPEND_SPEC)

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if license_row["coverage_status"] != "ACTIVE":
            raise conflict(
                "ERR_LICENSE_STATE_INVALID", "Only an ACTIVE licence may be suspended."
            )

    ladder.run()
    license_row["coverage_status"] = "SUSPENDED"
    license_row["suspension_reason"] = state["fields"]["suspension_reason"]
    db.touch(license_row)
    # Suspension voids no windows; it only stops the licence from counting.
    services.recompute_venue(db.venue(license_row["venue_id"]), coverage=True)
    return respond_object(serializers.license_json(license_row))


@bp.post("/licensing/licenses/<license_id>/reinstate")
def reinstate_license(license_id):
    user_id, role = authenticate([ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    license_row = access.fetch("licenses", license_id, access.ERR_LICENSE, narrow=False)
    venue = db.venue(license_row["venue_id"])

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if license_row["coverage_status"] != "SUSPENDED":
            raise conflict(
                "ERR_LICENSE_STATE_INVALID", "Only a SUSPENDED licence may be reinstated."
            )

    @ladder.check(P_AUDIT_HOLD)
    def _hold():
        if venue["audit_hold"]:
            raise conflict("ERR_AUDIT_HOLD_ACTIVE", "The venue is under an audit hold.")

    @ladder.check(P_REINSTATEMENT_BALANCE)
    def _balance():
        if license_row["suspension_reason"] != "NONPAYMENT":
            return
        if venue["outstanding_balance_cents"] > REINSTATEMENT_BALANCE_LIMIT_CENTS:
            raise conflict(
                "ERR_OUTSTANDING_BALANCE_BLOCKS_REINSTATEMENT",
                "The venue owes too much for a non-payment reinstatement.",
            )

    ladder.run()
    license_row["coverage_status"] = "ACTIVE"
    license_row["suspension_reason"] = None
    db.touch(license_row)
    services.recompute_venue(venue, coverage=True)
    return respond_object(serializers.license_json(license_row))


@bp.post("/licensing/licenses/<license_id>/terminate")
def terminate_license(license_id):
    user_id, role = authenticate([ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    license_row = access.fetch("licenses", license_id, access.ERR_LICENSE, narrow=False)
    venue = db.venue(license_row["venue_id"])
    body = read_body()
    state = {}

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        state["fields"] = validate_fields(body if body is not None else {}, TERMINATE_SPEC)

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if license_row["coverage_status"] not in ("ACTIVE", "SUSPENDED"):
            raise conflict(
                "ERR_LICENSE_STATE_INVALID",
                "Only an ACTIVE or SUSPENDED licence may be terminated.",
            )

    ladder.run()
    license_row["coverage_status"] = "TERMINATED"
    # PRD 3.7 documents one increment for termination -- the coverage move's --
    # and the terminal WRITTEN_OFF the switch triggers carries none of its own,
    # so both dimensions move inside this single mutation (PRD 2.11: "each
    # documented increment applies").
    if state["fields"]["void_unpaid_assessments"]:
        license_row["billing_status"] = "WRITTEN_OFF"
    db.touch(license_row)

    # Every ACTIVE window of the licence reaches the terminal VOIDED.
    for window in db.windows_of_license(license_row["id"]):
        if window["status"] == "ACTIVE":
            window["status"] = "VOIDED"
            db.touch(window)

    if state["fields"]["void_unpaid_assessments"]:
        # The forgiven remainder moves to voided_amount_cents rather than
        # vanishing, which is what keeps the ledger identity of PRD 2.9 intact.
        for assessment in db.where("assessments", license_id=license_row["id"]):
            if assessment["status"] != "ISSUED":
                continue
            assessment["status"] = "VOIDED"
            db.touch(assessment)

    services.recompute_venue(venue, ledger=True, coverage=True)
    return respond_object(serializers.license_json(license_row))


@bp.post("/licensing/licenses/<license_id>/renew")
def renew_license(license_id):
    user_id, role = authenticate([ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    predecessor = access.fetch("licenses", license_id, access.ERR_LICENSE, narrow=False)
    venue = db.venue(predecessor["venue_id"])
    body = read_body()
    state = {}

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        state["fields"] = validate_fields(body, RENEW_SPEC)

    @ladder.check(P_STALE_PARENT)
    def _stale():
        if state["fields"]["expected_license_version"] != predecessor["version"]:
            raise precondition(
                "ERR_STALE_LICENSE_VERSION",
                "The licence has been revised since it was last read.",
            )

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if predecessor["coverage_status"] not in ("ACTIVE", "EXPIRED"):
            raise conflict(
                "ERR_LICENSE_STATE_INVALID", "Only an ACTIVE or EXPIRED licence may be renewed."
            )

    @ladder.check(P_AUDIT_HOLD)
    def _hold():
        if venue["audit_hold"]:
            raise conflict("ERR_AUDIT_HOLD_ACTIVE", "The venue is under an audit hold.")

    @ladder.check(P_RENEWAL_TERM)
    def _continuity():
        if state["fields"]["requested_term_start"] != predecessor["term_end"]:
            raise conflict(
                "ERR_RENEWAL_TERM_MISMATCH",
                "A renewal term must begin exactly at the predecessor's term_end.",
            )

    @ladder.check(P_NOT_RENEWED)
    def _once():
        if predecessor["renewal_issued_at"] is not None:
            raise conflict(
                "ERR_LICENSE_ALREADY_RENEWED", "This licence has already issued a successor."
            )

    @ladder.check(P_UNIQUENESS)
    def _unique():
        term_start = state["fields"]["requested_term_start"]
        if duplicate_active_license(
            predecessor["venue_id"],
            predecessor["society_id"],
            term_start,
            plus_days(term_start, TERM_DAYS),
            exclude_id=predecessor["id"],
        ):
            raise conflict(
                "ERR_DUPLICATE_ACTIVE_LICENSE",
                "Another live licence of this venue and society overlaps the successor term.",
            )

    @ladder.check(P_EFFECTIVE_SCHEDULE)
    def _schedule():
        schedule = calc.select_schedule(predecessor["society_id"], venue["venue_category"])
        if schedule is None:
            raise conflict(
                "ERR_NO_EFFECTIVE_RATE_SCHEDULE",
                "No EFFECTIVE rate schedule covers this society and venue category.",
            )
        state["schedule"] = schedule

    @ladder.check(P_RENEWAL_BALANCE)
    def _balance():
        if venue["outstanding_balance_cents"] > RENEWAL_OUTSTANDING_LIMIT_CENTS:
            raise conflict(
                "ERR_OUTSTANDING_BALANCE_BLOCKS_RENEWAL",
                "The venue owes too much to renew.",
            )

    ladder.run()
    schedule = state["schedule"]
    society = db.society(predecessor["society_id"])
    term_start = state["fields"]["requested_term_start"]

    predecessor["renewal_issued_at"] = db.now()
    db.touch(predecessor)

    # A renewal has no operator declaration to be provisional about, so both fee
    # figures come from the verified variant and the delta is 0.
    fee = calc.verified_fee(schedule, society, venue, predecessor["license_type"])
    successor = db.new_row(
        "licenses",
        {
            "venue_id": predecessor["venue_id"],
            "society_id": predecessor["society_id"],
            "application_id": predecessor["application_id"],
            "rate_schedule_id": schedule["id"],
            "renewal_of_license_id": predecessor["id"],
            "pinned_schedule_version": schedule["schedule_version"],
            "license_type": predecessor["license_type"],
            "term_start": term_start,
            "term_end": plus_days(term_start, TERM_DAYS),
            "provisional_annual_fee_cents": fee,
            "annual_fee_cents": fee,
            "verified_fee_delta_cents": 0,
            "coverage_status": "PENDING_ACTIVATION",
            "billing_status": "UNBILLED",
            "suspension_reason": None,
            "reporting_required": calc.reporting_required(predecessor["license_type"], venue),
            "accepted_report_count": 0,
            "renewal_issued_at": None,
        },
    )
    return respond_object(serializers.license_json(successor), 201)


# ---------------------------------------------------------------------------
# PRD 3.6 -- coverage windows
# ---------------------------------------------------------------------------


@bp.post("/licensing/licenses/<license_id>/coverage-windows")
def create_window(license_id):
    user_id, role = authenticate([ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    license_row = access.fetch("licenses", license_id, access.ERR_LICENSE, narrow=False)
    body = read_body()
    state = {}

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        state["fields"] = validate_fields(body, WINDOW_SPEC)

    @ladder.check(P_LICENSE_ACTIVE)
    def _active():
        if license_row["coverage_status"] != "ACTIVE":
            raise conflict(
                "ERR_LICENSE_NOT_ACTIVE", "Windows may only be attached to an ACTIVE licence."
            )

    @ladder.check(P_INTERVAL)
    def _interval():
        if state["fields"]["window_start"] >= state["fields"]["window_end"]:
            raise invalid_interval("window_start must be strictly before window_end.")

    @ladder.check(P_WINDOW_PLACEMENT)
    def _placement():
        start = state["fields"]["window_start"]
        end = state["fields"]["window_end"]
        if start < license_row["term_start"] or end > license_row["term_end"]:
            raise conflict(
                "ERR_WINDOW_OUTSIDE_TERM", "The window must sit inside the licence's own term."
            )
        kind = state["fields"]["window_kind"]
        for other in db.windows_of_license(license_row["id"]):
            if other["status"] != "ACTIVE" or other["window_kind"] != kind:
                continue
            if terms_overlap(start, end, other["window_start"], other["window_end"]):
                raise conflict(
                    "ERR_COVERAGE_WINDOW_OVERLAP",
                    "An ACTIVE window of the same window_kind already covers that span.",
                )

    ladder.run()
    fields = state["fields"]
    venue = db.venue(license_row["venue_id"])
    covered_day_count = whole_days(fields["window_start"], fields["window_end"])
    if fields["window_kind"] == "ANNUAL_TERM":
        rider_fee_cents = 0
    else:
        # Priced off annual_fee_cents as it stands right now; a later re-rating
        # never reaches back into an existing rider (PRD 3.6).
        rider_fee_cents = calc.rider_fee(license_row["annual_fee_cents"], covered_day_count)

    window = db.new_row(
        "coverage_windows",
        {
            "license_id": license_row["id"],
            "window_kind": fields["window_kind"],
            "window_start": fields["window_start"],
            "window_end": fields["window_end"],
            "covered_day_count": covered_day_count,
            "rider_fee_cents": rider_fee_cents,
            "status": "ACTIVE",
        },
    )

    if rider_fee_cents > 0:
        services.issue_assessment(
            venue, license_row["id"], None, "SEASONAL_RIDER", rider_fee_cents
        )
        services.recompute_venue(venue, ledger=True)
        services.bill_on_activation(license_row)
        services.bill_on_extra_assessment(license_row)
        services.delinquency_sweep(venue)

    # PRD 3.6 recomputes only the four ledger totals here, and only for a
    # priced rider: attaching a window inside an already-covered term cannot
    # move covered_share_bp, so no coverage recomputation is owed.
    return respond_object(serializers.window_json(window), 201)


@bp.get("/licensing/licenses/<license_id>/coverage-windows")
def list_windows_of_license(license_id):
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR])
    license_row = access.fetch("licenses", license_id, access.ERR_LICENSE)
    limit, offset = read_pagination()
    rows = db.windows_of_license(license_row["id"])
    page, total = paginate(rows, limit, offset)
    return respond_list([serializers.window_json(row) for row in page], limit, offset, total)


@bp.get("/licensing/coverage-windows")
def list_windows():
    authenticate([ROLE_ADMIN, ROLE_AUDITOR])
    limit, offset = read_pagination()
    license_id = query_str("license_id")
    window_kind = query_enum("window_kind", WINDOW_KINDS)
    status = query_enum("status", WINDOW_STATUSES)
    rows = []
    for row in db.ordered("coverage_windows"):
        if license_id is not None and row["license_id"] != license_id:
            continue
        if window_kind is not None and row["window_kind"] != window_kind:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return respond_list([serializers.window_json(row) for row in page], limit, offset, total)


@bp.get("/licensing/coverage-windows/<coverage_window_id>")
def read_window(coverage_window_id):
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR])
    row = access.fetch("coverage_windows", coverage_window_id, access.ERR_WINDOW)
    return respond_object(serializers.window_json(row))


# ---------------------------------------------------------------------------
# Licence reads
# ---------------------------------------------------------------------------


@bp.get("/licensing/licenses")
def list_licenses():
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR, ROLE_OFFICER])
    limit, offset = read_pagination()
    filters = {
        "venue_id": query_str("venue_id"),
        "society_id": query_str("society_id"),
        "application_id": query_str("application_id"),
        "rate_schedule_id": query_str("rate_schedule_id"),
        "renewal_of_license_id": query_str("renewal_of_license_id"),
        "coverage_status": query_enum("coverage_status", COVERAGE_STATUSES),
        "billing_status": query_enum("billing_status", BILLING_STATUSES),
    }
    rows = []
    for row in access.narrow_rows("licenses", db.ordered("licenses")):
        keep = True
        for name, wanted in filters.items():
            if wanted is not None and row[name] != wanted:
                keep = False
                break
        if keep:
            rows.append(row)
    page, total = paginate(rows, limit, offset)
    return respond_list([serializers.license_json(row) for row in page], limit, offset, total)


@bp.get("/licensing/licenses/<license_id>")
def read_license(license_id):
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR, ROLE_OFFICER])
    row = access.fetch("licenses", license_id, access.ERR_LICENSE)
    return respond_object(serializers.license_json(row))
