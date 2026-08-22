"""Authentication, role authorisation, the program clock and discovery listings."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_same_instant,
    payment_payload, create_session_booking_payload,
    set_clock, create_zone, create_pitch, create_performer, create_application,
    submit_application, review_application, run_epoch_advance,
    setup_permit_pending_fee, setup_active_permit, setup_audition_scheduled,
    file_complaint, draft_closure, read_application, read_permit,
    first_permit_invoice, permit_version,
    make_officer_headers, make_performer_headers, make_resident_headers,
    CLOCK_START_UTC_ISO, OFFICER_ALPHA,
)
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict /
#          state_permit_not_active_outranks_fiscal_invoice_past_due
# ---------------------------------------------------------------------------

def _unpaid_permit_with_a_past_due_invoice():
    zone = create_zone()
    pitch = create_pitch(zone["id"], code="RP-01", tier="STANDARD",
                         noise_cap_db=82, amplification_allowed=True)
    ctx = setup_permit_pending_fee(zone["id"])
    ctx.update(zone=zone, pitch=pitch)
    set_clock("2026-08-20T00:00:00Z")
    ctx["report"] = run_epoch_advance()
    return ctx


def test_permit_not_active_outranks_the_past_due_invoice_on_a_booking(api):
    """PRD §2.6: "11. The permit's lifecycle axis is `ACTIVE`, otherwise
    `ERR_PERMIT_NOT_ACTIVE`. Applies to session booking and to lottery entry
    filing."
    PRD §2.6: "42. No invoice on the permit is past due, otherwise
    `ERR_INVOICE_PAST_DUE`. Applies to session booking and to lottery entry
    filing."
    PRD §2.6: "A request is validated as an ordered sequence of checks, and the
    **first** check that fails decides the response; no later check may mask an
    earlier one, and no earlier check may be skipped because a later one would
    also fail."

    Design: Difficulty/priority_pair_validation_conflict/state_permit_not_active_outranks_fiscal_invoice_past_due
    """
    ctx = _unpaid_permit_with_a_past_due_invoice()

    resp = api.create_session_booking(
        create_session_booking_payload(ctx["permit"]["id"], ctx["pitch"]["id"],
                                       "2026-08-25T10:00:00Z",
                                       "2026-08-25T11:00:00Z",
                                       permit_version(ctx["permit"]["id"])),
        make_performer_headers(ctx["performer"]["id"]))
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)
    assert resp.json()["data"]["error_id"] != "ERR_INVOICE_PAST_DUE", \
        "the earlier state check must not be masked by the fiscal one"


def test_the_swept_invoice_is_past_due_while_the_permit_stays_pending_fee(api):
    """PRD §3.9: "Step two sweeps money: every invoice still `PENDING` whose
    `due_at` is strictly before the clock moves `PENDING → PAST_DUE`, which
    immediately blocks that permit from new bookings and new lottery entries."
    PRD §3.5: "A permit issued by an approval is not yet a licence to perform —
    it sits in `PENDING_FEE` until its invoice is settled."

    Design: Difficulty/priority_pair_validation_conflict/state_permit_not_active_outranks_fiscal_invoice_past_due
    """
    ctx = _unpaid_permit_with_a_past_due_invoice()
    assert ctx["report"]["invoices_past_due_count"] == 1

    invoice = first_permit_invoice(ctx["permit"]["id"])
    assert invoice["status"] == "PAST_DUE"

    permit = read_permit(ctx["permit"]["id"])
    assert permit["lifecycle_status"] == "PENDING_FEE", \
        "both refusal conditions are live on the same permit"
    assert permit["season_minutes_used"] == 0


# ---------------------------------------------------------------------------
# Queue B: authentication and role authorisation
# ---------------------------------------------------------------------------

def test_missing_authentication_headers_outrank_path_existence(api):
    """PRD §2.1: "Every request to the API — including reads — must carry two
    headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming
    the role that user is acting in. If either header is absent, or if
    `X-User-Role` is not exactly one of the five role names below, the request is
    rejected with `ERR_UNAUTHENTICATED` and HTTP 401."
    PRD §2.6: "1. Both authentication headers present and `X-User-Role` a known
    role, otherwise `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/corner_missing_auth_headers_outrank_existence
    """
    resp = api.get_pitch(NON_EXISTENT_UUID, {"Content-Type": "application/json"})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_forbidden_role_outranks_path_existence(api):
    """PRD §2.1: "If both headers are well formed but the named role is not one
    of the roles authorised for the endpoint being called (the authorised set for
    each endpoint is listed in section 4), the request is rejected with
    `ERR_FORBIDDEN_ROLE` and HTTP 403."
    PRD §2.6: "3. Every identifier appearing in the URL path resolves to a live
    row, validated left to right, otherwise the matching not-found error."

    Design: Corner/validations/corner_forbidden_role_outranks_existence
    """
    resp = api.get_permit(NON_EXISTENT_UUID, make_resident_headers("resident-1"))
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_a_performer_may_not_pick_up_their_own_application_for_review(api):
    """PRD §2.1: "If both headers are well formed but the named role is not one
    of the roles authorised for the endpoint being called (the authorised set for
    each endpoint is listed in section 4), the request is rejected with
    `ERR_FORBIDDEN_ROLE` and HTTP 403."
    PRD §3.2: "When an officer picks the application up, the same review action
    lands in two different places purely on that computed flag: an application
    whose `requires_audition` is false goes `SUBMITTED → UNDER_REVIEW` and may be
    decided directly, while one whose `requires_audition` is true goes `SUBMITTED
    → AUDITION_REQUIRED` and cannot be approved until a panel has passed it."

    Design: Corner/roles/corner_performer_cannot_review_an_application
    """
    zone = create_zone()
    performer = create_performer()
    application = create_application(performer["id"], zone["id"])
    submit_application(application["id"], performer["id"])

    resp = api.review_application(application["id"],
                                  make_performer_headers(performer["id"]))
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    reread = read_application(application["id"])
    assert reread["status"] == "SUBMITTED"
    assert reread["reviewed_by_user_id"] is None


def test_every_collection_reports_its_own_not_found_error(api):
    """PRD §2.11: "Identifiers inside a URL are resolved left to right, and the
    first one that does not resolve determines the error."
    PRD §2.11: "The not-found errors are `ERR_ZONE_NOT_FOUND`,
    `ERR_PITCH_NOT_FOUND`, `ERR_PERFORMER_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_AUDITION_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_DRAW_NOT_FOUND`,
    `ERR_ENTRY_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`
    and `ERR_CLOSURE_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/corner_every_path_id_not_found_error_is_triggerable
    """
    officer = make_officer_headers(OFFICER_ALPHA)
    cases = [
        (api.get_zone(NON_EXISTENT_UUID, officer),
         ApiErrorId.ERR_ZONE_NOT_FOUND),
        (api.get_performer(NON_EXISTENT_UUID, officer),
         ApiErrorId.ERR_PERFORMER_NOT_FOUND),
        (api.get_application(NON_EXISTENT_UUID, officer),
         ApiErrorId.ERR_APPLICATION_NOT_FOUND),
        (api.get_audition(NON_EXISTENT_UUID, officer),
         ApiErrorId.ERR_AUDITION_NOT_FOUND),
        (api.get_permit(NON_EXISTENT_UUID, officer),
         ApiErrorId.ERR_PERMIT_NOT_FOUND),
        (api.pay_invoice(NON_EXISTENT_UUID, payment_payload(100), officer),
         ApiErrorId.ERR_INVOICE_NOT_FOUND),
        (api.get_lottery_draw(NON_EXISTENT_UUID, officer),
         ApiErrorId.ERR_DRAW_NOT_FOUND),
        (api.get_lottery_entry(NON_EXISTENT_UUID, officer),
         ApiErrorId.ERR_ENTRY_NOT_FOUND),
        (api.get_session_booking(NON_EXISTENT_UUID, officer),
         ApiErrorId.ERR_BOOKING_NOT_FOUND),
        (api.get_complaint(NON_EXISTENT_UUID, officer),
         ApiErrorId.ERR_COMPLAINT_NOT_FOUND),
        (api.get_closure_order(NON_EXISTENT_UUID, officer),
         ApiErrorId.ERR_CLOSURE_NOT_FOUND),
    ]
    for response, expected_error in cases:
        assert response.status_code == 404, (
            f"Expected 404 for {expected_error}, got {response.status_code}")
        validate_error(response, expected_error)
        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str)


# ---------------------------------------------------------------------------
# Queue B: the program clock and the discovery listings
# ---------------------------------------------------------------------------

def test_the_logical_clock_starts_at_the_declared_default(api):
    """PRD §2.5: "The server holds a single logical UTC clock that starts at
    exactly `2026-08-01T00:00:00Z` when the process boots and stays there until
    it is moved explicitly; it must never fall back to the host's real time, not
    even before the first move."
    PRD §2.5: "An operations-facing test-driving capability moves the clock: the
    caller supplies the target instant as `to_iso8601`, and the response reports
    the new `current_utc` alongside the `previous_utc` it replaced."

    Design: Corner/endpoints/corner_logical_clock_starts_at_the_declared_default
    """
    resp = api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"},
                         make_officer_headers(OFFICER_ALPHA))
    data = validate_success(resp, 200)
    assert_same_instant(data["previous_utc"], CLOCK_START_UTC_ISO, "previous_utc")
    assert_same_instant(data["current_utc"], "2026-09-01T00:00:00.000Z",
                        "current_utc")


def test_permit_listing_narrows_on_performer_and_on_lifecycle_status(api):
    """PRD §2.11: "Permit listings — the only way to find a permit that an
    approval cascade created — filter on `performer_id`, on `application_id`, on
    `lifecycle_status`, on `compliance_status` and on `season_year`."
    PRD §2.3: "Filter query parameters are combined conjunctively: a listing that
    receives several filters returns only rows matching all of them."

    Design: Corner/endpoints/corner_permits_list_filters_by_performer_and_lifecycle_status
    """
    zone = create_zone()
    paid = setup_active_permit(zone["id"])
    unpaid = setup_permit_pending_fee(
        zone["id"], performer_overrides={"legal_name": "Eli Marsh",
                                         "stage_name": "Eli M",
                                         "email": "eli@example.org"})

    active_rows, active_meta = validate_paginated(api.list_permits(
        make_officer_headers(), params={"lifecycle_status": "ACTIVE"}))
    assert active_meta["total_count"] == 1
    assert active_rows[0]["id"] == paid["permit"]["id"]

    pending_rows, pending_meta = validate_paginated(api.list_permits(
        make_officer_headers(), params={"lifecycle_status": "PENDING_FEE"}))
    assert pending_meta["total_count"] == 1
    assert pending_rows[0]["id"] == unpaid["permit"]["id"]

    by_performer, performer_meta = validate_paginated(api.list_permits(
        make_officer_headers(),
        params={"performer_id": unpaid["performer"]["id"]}))
    assert performer_meta["total_count"] == 1
    assert by_performer[0]["id"] == unpaid["permit"]["id"]

    assert read_permit(paid["permit"]["id"])["net_fees_paid_cents"] == 5400
    assert read_permit(unpaid["permit"]["id"])["net_fees_paid_cents"] == 0


def test_filtered_listings_serve_every_declared_foreign_key(api):
    """PRD §2.11: "Application listings filter on `performer_id`, on
    `requested_zone_id`, on `status` and on `season_year`. Audition listings
    filter on `application_id` and on `status`."
    PRD §2.11: "Complaint listings filter on `permit_id`, on `booking_id`, on
    `status` and on `severity`. Closure listings filter on `zone_id`, on
    `pitch_id` and on `status`."
    PRD §2.3: "`total_count` is the number of rows matching the request's filters
    before pagination is applied, and `has_more` is true when rows remain beyond
    the current page."

    Design: Corner/endpoints/corner_filtered_list_endpoints_serve_every_declared_foreign_key
    """
    zone = create_zone()
    create_pitch(zone["id"], code="RP-01", tier="STANDARD", noise_cap_db=82,
                 amplification_allowed=True)
    vetted = setup_audition_scheduled(zone["id"])
    holder = setup_active_permit(zone["id"])
    complaint = file_complaint(holder["permit"]["id"], "resident-1",
                               category="NOISE", description="Evening volume")
    closure = draft_closure(zone["id"], "2026-09-05T08:00:00Z",
                            "2026-09-05T18:00:00Z", reason="PARADE")

    rows, meta = validate_paginated(api.list_applications(
        make_officer_headers(),
        params={"performer_id": vetted["performer"]["id"]}))
    assert meta["total_count"] == 1 and rows[0]["id"] == vetted["application"]["id"]

    rows, meta = validate_paginated(api.list_auditions(
        make_officer_headers(),
        params={"application_id": vetted["application"]["id"]}))
    assert meta["total_count"] == 1 and rows[0]["id"] == vetted["audition"]["id"]

    rows, meta = validate_paginated(api.list_complaints(
        make_officer_headers(), params={"permit_id": holder["permit"]["id"]}))
    assert meta["total_count"] == 1 and rows[0]["id"] == complaint["id"]

    rows, meta = validate_paginated(api.list_closure_orders(
        make_officer_headers(), params={"zone_id": zone["id"]}))
    assert meta["total_count"] == 1 and rows[0]["id"] == closure["id"]

    empty, empty_meta = validate_paginated(api.list_auditions(
        make_officer_headers(),
        params={"application_id": holder["application"]["id"]}))
    assert empty == [], "a filter with no matches returns an empty array"
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False

    assert read_application(vetted["application"]["id"])["status"] == "AUDITION_SCHEDULED"
    assert complaint["status"] == "OPEN"
    assert closure["status"] == "DRAFT"
