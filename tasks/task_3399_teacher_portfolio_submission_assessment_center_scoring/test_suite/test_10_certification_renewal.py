"""Certification renewal: the inclusive filing window, the 45-hour evidence
floor, the RETURNED-application revision loop, and validity extension."""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    BOARD,
    RENEWAL_LOOKBACK_DAYS,
    VALIDITY_DAYS,
    ApiErrorId,
    CertificationStatus,
    RenewalStatus,
    assert_certification_validity_window,
    assert_renewal,
    create_certified_scenario,
    create_eligible_candidate,
    create_open_cycle,
    create_renewal_payload,
    create_submission,
    evidence_item,
    get_certification_for,
    get_success_data,
    make_candidate_headers,
    review_renewal,
    review_renewal_payload,
    set_logical_clock,
    validate_created,
    validate_error,
    validate_success,
)

YEARS_BEFORE_WINDOW = "2028-06-01T00:00:00Z"  # long before any valid_until - 90d


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_renewal_total_hours_boundary_and_validity_extension(api):
    """PRD §3.7: "The application carries `evidence_items`, an array that must
    contain at least one item — an empty array is `ERR_INVALID_REQUEST` — where
    each item names an `evidence_type`, a `description`, and `hours` of at least 0;
    the application's `total_hours` is the sum of those hours."
    PRD §3.7: "APPROVE requires `total_hours` of at least 45 hours of
    continued-practice evidence — exactly 45 passes, fewer fails with
    `ERR_RENEWAL_HOURS_INSUFFICIENT` (HTTP 422) — and moves the application to
    `APPROVED`, the terminal state for applications, while the certification
    transitions to `RENEWED` and its `valid_until` extends by another 1825 days."
    PRD §3.7: "Only one application per certification may be in flight: filing
    while another application of the same certification is `SUBMITTED` fails with
    `ERR_ACTIVE_RENEWAL_EXISTS` (HTTP 409). Refiling against a `RETURNED`
    application instead reuses it — the application flips from `RETURNED` back to
    `SUBMITTED` with the new `evidence_items` and recomputed `total_hours`
    replacing the old."
    PRD §3.7: "A `BoardAdministrator` reviews each application, and the review is
    legal only from `SUBMITTED` or `RETURNED` — otherwise
    `ERR_RENEWAL_NOT_REVIEWABLE` (HTTP 409)."
    PRD §2.7: "The renewal window is the exception to half-open discipline: it is
    **inclusive at both ends**, running from 90 days before a certification's
    `valid_until` through 30 days after it. A filing exactly at either boundary is
    inside the window."

    Re-derived literals: the design recipe's fixture dates (window-open clock
    2032-03-01T00:00:00Z; post-renewal valid_until 2037-05-29T00:00:00Z) descend
    from a valid_until that drifted off the PRD rule — certified_at
    2027-01-20T15:00:00Z plus 1825 days is 2032-01-19T15:00:00Z, so the inclusive
    window-open instant is 2031-10-21T15:00:00Z, and the recipe's clock would land
    past the window's far edge. This test derives the filing clock as
    valid_until - 90 days and the post-renewal window as valid_until + 1825 days
    from the certification's own fields at runtime.

    Design: Corner/calculations/renewal_total_hours_boundary_and_validity_extension
    """
    scenario = create_certified_scenario()
    certification = scenario["certification"]
    candidate = scenario["candidate"]
    pre_renewal_valid_until = certification["valid_until"]

    # File exactly at valid_until - 90 days: the window's inclusive lower bound.
    window_open = _parse_iso(pre_renewal_valid_until) - timedelta(
        days=RENEWAL_LOOKBACK_DAYS
    )
    set_logical_clock(_format_iso(window_open))

    renewal = validate_created(
        api.create_renewal(
            certification["id"],
            create_renewal_payload(
                evidence_items=[
                    evidence_item("WORKSHOP", "25h workshop series", 25),
                    evidence_item("MENTORING", "19h mentoring", 19),
                ]
            ),
            make_candidate_headers(candidate["id"]),
        )
    )
    assert_renewal(renewal)
    assert renewal["status"] == RenewalStatus.SUBMITTED.value
    assert renewal["total_hours"] == 44

    duplicate = api.create_renewal(
        certification["id"],
        create_renewal_payload(
            evidence_items=[evidence_item("WORKSHOP", "duplicate filing", 50)]
        ),
        make_candidate_headers(candidate["id"]),
    )
    validate_error(duplicate, ApiErrorId.ERR_ACTIVE_RENEWAL_EXISTS)

    under = api.review_renewal(
        renewal["id"], review_renewal_payload("APPROVE"), BOARD
    )
    validate_error(under, ApiErrorId.ERR_RENEWAL_HOURS_INSUFFICIENT)

    returned = review_renewal(renewal["id"], "RETURN", note="need one more hour")
    assert returned["status"] == RenewalStatus.RETURNED.value

    refiled = get_success_data(
        api.create_renewal(
            certification["id"],
            create_renewal_payload(
                evidence_items=[
                    evidence_item("WORKSHOP", "25h workshop series", 25),
                    evidence_item("MENTORING", "20h mentoring", 20),
                ]
            ),
            make_candidate_headers(candidate["id"]),
        )
    )
    assert refiled["id"] == renewal["id"], "refiling reuses the RETURNED application"
    assert refiled["status"] == RenewalStatus.SUBMITTED.value
    assert refiled["total_hours"] == 45

    approved = review_renewal(renewal["id"], "APPROVE")
    assert approved["status"] == RenewalStatus.APPROVED.value

    late_review = api.review_renewal(
        renewal["id"], review_renewal_payload("RETURN", note="too late"), BOARD
    )
    validate_error(late_review, ApiErrorId.ERR_RENEWAL_NOT_REVIEWABLE)

    renewed_cert = validate_success(api.get_certification(certification["id"], BOARD))
    assert renewed_cert["status"] == CertificationStatus.RENEWED.value
    assert_certification_validity_window(
        renewed_cert, pre_renewal_valid_until, VALIDITY_DAYS
    )


def test_renewal_before_window_opens_rejected(api):
    """PRD §3.7: "The candidate files a renewal application under the
    certification's `certification_id` while the certification is `CERTIFIED` or
    `RENEWED` — against any other status the filing is
    `ERR_CERTIFICATION_NOT_RENEWABLE` (HTTP 409) — and while the logical clock sits
    inside the renewal window from 90 days before `valid_until` through 30 days
    after it, both bounds inclusive; outside the window the filing is
    `ERR_RENEWAL_WINDOW_NOT_OPEN` (HTTP 422)."

    The 2028-06-01 filing lands years before the window's lower bound.

    Design: Corner/validations/renewal_before_window_opens_rejected
    """
    scenario = create_certified_scenario()
    certification = scenario["certification"]
    candidate = scenario["candidate"]
    set_logical_clock(YEARS_BEFORE_WINDOW)

    response = api.create_renewal(
        certification["id"],
        create_renewal_payload(),
        make_candidate_headers(candidate["id"]),
    )

    validate_error(response, ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN)


def test_renewal_on_pending_certification_rejected(api):
    """PRD §3.7: "The candidate files a renewal application under the
    certification's `certification_id` while the certification is `CERTIFIED` or
    `RENEWED` — against any other status the filing is
    `ERR_CERTIFICATION_NOT_RENEWABLE` (HTTP 409)".

    The certification is auto-created in PENDING by the candidate's first
    submission and nothing has been scored.

    Design: Corner/validations/renewal_on_pending_certification_rejected
    """
    cycle = create_open_cycle()
    candidate = create_eligible_candidate()
    create_submission(cycle["id"], candidate, "P1")
    certification = get_certification_for(candidate["id"], cycle["id"])
    assert certification["status"] == CertificationStatus.PENDING.value

    response = api.create_renewal(
        certification["id"],
        create_renewal_payload(),
        make_candidate_headers(candidate["id"]),
    )

    validate_error(response, ApiErrorId.ERR_CERTIFICATION_NOT_RENEWABLE)
