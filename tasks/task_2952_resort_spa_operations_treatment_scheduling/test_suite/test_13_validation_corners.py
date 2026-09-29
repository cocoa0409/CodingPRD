"""Validation corners: the thirty-four-rung ladder decided by priority alone,
the three clinical rungs kept distinct, the two licence rungs, the two
continuing-education rungs in cascade, the five scheduling rungs, the retail and
gratuity rungs, both segregation-of-duties rules, and one booking that sits on
five inclusive boundaries at once.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    DIRECTOR_USER_ID,
    assert_ce_hours,
    assert_ledgers,
    assert_list_count,
    assert_same_instant,
    assert_state_pair,
    make_compliance_headers,
    make_director_headers,
    make_therapist_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.constants import CANON_CONSENT_VERSION
from test_helpers import factories as f
from test_helpers import fixtures as fx

# ---------------------------------------------------------------------------
# The DRY 60-minute menu item, whose list price is its base price: the DRY
# room-class multiplier is 10,000 basis points, the 10:00-11:00 slot is outside
# the peak band, `high_demand` is omitted so it defaults to false, and the guest
# carries no loyalty tier.
# ---------------------------------------------------------------------------
DRY60_TYPE = {
    "code": "DRY60",
    "name": "Signature Dry Massage",
    "duration_minutes": 60,
    "room_class_required": "DRY",
    "required_skill_code": "SWEDISH",
    "required_scope_level": "BASIC",
    "base_price_cents": 18000,
    "contraindication_codes": None,
    "high_demand": None,
}
DRY60_SCREENED = dict(DRY60_TYPE, code="DRY60C",
                      contraindication_codes=["ACUTE_HYPERTENSION"])
DRY60_BODY_RETAIL = dict(DRY60_TYPE, retail_product_line="BODY")

DRY_ROOM = {"room_class": "DRY", "turnover_buffer_minutes": 15,
            "hourly_fixed_cost_cents": 2500}
SWEDISH_BASIC = {"skill_code": "SWEDISH", "scope_level": "BASIC"}
NO_LOYALTY = {"loyalty_tier": None}

DRY_LIST_PRICE_CENTS = 18000
DRY_ROOM_MINUTES = 75                    # 60 scheduled + 15 turnover
DRY_THERAPIST_MINUTES = 60               # turnover belongs to the room
GRATUITY_CAP_CENTS = 9000                # round_half_up(18000 * 5000 / 10000)


def _dry_world(treatment_type=None, certification=None, room_codes=("DRY-1",),
               **kwargs):
    """The canonical world rebuilt around DRY60 in a DRY room with a
    BASIC/SWEDISH certification and a guest on no loyalty tier."""
    return fx.build_world(
        room_codes=room_codes,
        treatment_type_overrides=treatment_type or DRY60_TYPE,
        room_overrides=DRY_ROOM,
        certification_overrides=certification or SWEDISH_BASIC,
        guest_overrides=NO_LOYALTY,
        **kwargs)


def _book(world, start_at, therapist_id=None, room_code=None, guest_id=None,
          headers=None):
    """One raw booking attempt, returned unvalidated so the caller may assert
    either the accepted row or the refused rung."""
    return api_client.create_appointment(
        f.appointment_payload(
            guest_id or world.guest_id, world.treatment_type_id,
            world.room_id if room_code is None else world.room_of(room_code),
            start_at, therapist_id or world.therapist_id),
        headers or fx.COORDINATOR)


# ---------------------------------------------------------------------------
# validation_ladder_auth_shape_path_and_body_fk_precede_business_safety
# ---------------------------------------------------------------------------

LADDER_CLOCK = "2026-08-01T09:00:00.000Z"
MALFORMED_START_AT = "2026-08-10 10:00"      # not an ISO 8601 UTC instant
WELL_FORMED_START_AT = "2026-08-10T10:00:00.000Z"
# Exactly the empty string in both headers, never a whitespace string.
BLANK_HEADERS = {"X-User-ID": "", "X-User-Role": ""}
INVERTED_WINDOW_FROM_AT = "2026-08-20T00:00:00.000Z"
INVERTED_WINDOW_TO_AT = "2026-08-10T00:00:00.000Z"


def _ladder_world():
    """A therapist holding no licence, no certification and no shift block, and a
    guest that has never filed an intake form, so a booking naming both of them
    violates rungs 12, 15, 19 and 23 simultaneously."""
    fx.set_clock(LADDER_CLOCK)
    world = fx.SpaWorld()
    world.treatment_type = fx.create_treatment_type(**DRY60_TYPE)
    world.rooms["DRY-1"] = fx.create_room(code="DRY-1", **DRY_ROOM)
    world.therapists["bare"] = fx.create_therapist(full_name="Unlicensed Therapist")
    world.guest = fx.create_guest(full_name="No Intake Guest",
                                  resort_room_number="1501", **NO_LOYALTY)
    return world


def test_the_authentication_rung_outranks_the_shape_and_body_reference_rungs():
    """One request violates rungs 1, 3 and 5 at once and only rung 1 is reported.

    PRD §2.1: "If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."

    PRD §2.7: "The server walks the ladder from the top and returns the error of
    the **first** rung the request violates; lower rungs are not evaluated once a
    rung has failed."

    Design: Corner/validations/validation_ladder_auth_shape_path_and_body_fk_precede_business_safety
    """
    world = _ladder_world()
    payload = f.appointment_payload(
        NON_EXISTENT_UUID, world.treatment_type_id, world.room_id,
        MALFORMED_START_AT, world.therapists["bare"]["id"])

    validate_error(api_client.create_appointment(payload, BLANK_HEADERS),
                   ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    # The same payload with real headers proves the shape violation was genuine
    # and merely masked by the higher rung.
    validate_error(api_client.create_appointment(payload, fx.COORDINATOR),
                   ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    assert_list_count(api_client.list_appointments(fx.COORDINATOR), 0,
                      "appointments after the refused probes")


def test_the_role_rung_outranks_the_report_window_rung():
    """An unauthorised role hides an inverted report window behind a 403.

    PRD §2.7 rung 2: "**Role authorisation** — `X-User-Role` is one of the five
    roles and that role is authorised for the endpoint. Applies to every endpoint.
    Violation: `ERR_ROLE_NOT_PERMITTED` (403)."

    PRD §3.10: "Both reports reject a window whose `from_at` is not strictly
    earlier than its `to_at`, and both reject a window spanning more than 92 days,
    with `ERR_INVALID_REPORT_WINDOW` (HTTP 422)."

    Design: Corner/validations/validation_ladder_auth_shape_path_and_body_fk_precede_business_safety
    """
    params = f.report_window(INVERTED_WINDOW_FROM_AT, INVERTED_WINDOW_TO_AT)

    validate_error(
        api_client.get_room_utilization_report(
            make_compliance_headers(fx.CO_SUBMIT), params=params),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    # The very same window read by a permitted role surfaces the rung-32 error,
    # so the 403 above really did pre-empt a live violation.
    validate_error(
        api_client.get_room_utilization_report(fx.DIRECTOR, params=params),
        ApiErrorId.ERR_INVALID_REPORT_WINDOW.value, 422)


def test_the_shape_rung_outranks_path_existence_and_body_reference_existence():
    """A malformed body is judged before any identifier is resolved.

    PRD §2.7 rung 3: "**Request shape** — required fields present, enum values
    legal, integers within their declared ranges, datetimes valid ISO 8601 UTC
    instants, dates valid calendar dates, `limit` within 1 through 100 and
    `offset` not negative."

    PRD §2.7 rung 4: "**Path existence** — every identifier in the URL path
    resolves, checked strictly left to right, so the guest, therapist, licence or
    appointment segment is resolved before any segment nested to its right."

    Design: Corner/validations/validation_ladder_auth_shape_path_and_body_fk_precede_business_safety
    """
    world = _ladder_world()

    # (a) consent on a non-existent form with no `consent_version` at all.
    validate_error(api_client.sign_consent(NON_EXISTENT_UUID, {}, fx.COORDINATOR),
                   ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    # (b) completion on a non-existent appointment with no delivered minutes.
    validate_error(
        api_client.complete_appointment(
            NON_EXISTENT_UUID, {},
            make_therapist_headers(world.therapists["bare"]["id"])),
        ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    # (c) a booking whose `start_at` is malformed and whose `guest_id` is unknown.
    validate_error(
        api_client.create_appointment(
            f.appointment_payload(NON_EXISTENT_UUID, world.treatment_type_id,
                                  world.room_id, MALFORMED_START_AT,
                                  world.therapists["bare"]["id"]),
            fx.COORDINATOR),
        ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    # The control: with a well-formed body the identical unresolvable path is a
    # 404, which is the rung the three probes above kept out of sight.
    validate_error(
        api_client.sign_consent(NON_EXISTENT_UUID, f.consent_payload(),
                                fx.COORDINATOR),
        ApiErrorId.ERR_INTAKE_FORM_NOT_FOUND.value, 404)


def test_the_body_reference_rung_outranks_the_clinical_and_credential_rungs():
    """A missing guest is a 404 and a real but uncleared guest is the lowest
    violated business rung, not the loudest one.

    PRD §2.7 rung 5: "**Body reference existence** — every identifier supplied in
    a request body resolves, checked in the body-field order `guest_id`, then
    `treatment_type_id`, then `room_id`, then `therapist_id`. Applies to
    appointment booking."

    PRD §2.7: "First, on a booking a clinical rejection always wins over a
    scheduling rejection: a guest with an unscreened intake form receives
    `ERR_INTAKE_NOT_CLEARED` even when the requested slot is also outside the
    therapist's shift window and the lead time is also too short."

    Design: Corner/validations/validation_ladder_auth_shape_path_and_body_fk_precede_business_safety
    """
    world = _ladder_world()
    therapist_id = world.therapists["bare"]["id"]

    validate_error(
        api_client.create_appointment(
            f.appointment_payload(NON_EXISTENT_UUID, world.treatment_type_id,
                                  world.room_id, WELL_FORMED_START_AT,
                                  therapist_id),
            fx.COORDINATOR),
        ApiErrorId.ERR_GUEST_NOT_FOUND.value, 404)

    error = validate_error(
        api_client.create_appointment(
            f.appointment_payload(world.guest_id, world.treatment_type_id,
                                  world.room_id, WELL_FORMED_START_AT,
                                  therapist_id),
            fx.COORDINATOR),
        ApiErrorId.ERR_INTAKE_NOT_CLEARED.value, 409)
    for masked in (ApiErrorId.ERR_LICENSE_NOT_VERIFIED,
                   ApiErrorId.ERR_SCOPE_OF_PRACTICE_VIOLATION,
                   ApiErrorId.ERR_OUTSIDE_SHIFT_WINDOW):
        assert error["error_id"] != masked.value, (
            f"{masked.value} is also violated but sits below rung 12")

    guest = validate_success(api_client.get_guest(world.guest_id, fx.COORDINATOR))
    assert guest["authoritative_intake_form_id"] is None
    assert guest["version"] == 1, (
        "none of the refused probes mutated the guest")
    assert_list_count(api_client.list_appointments(fx.COORDINATOR), 0,
                      "appointments after all six probes")
    assert_ledgers(world.fetch_room(),
                   validate_success(api_client.get_therapist(therapist_id,
                                                             fx.DIRECTOR)),
                   0, 0)


# ---------------------------------------------------------------------------
# intake_clearance_consent_and_contraindication_are_three_distinct_rungs
# ---------------------------------------------------------------------------

STALE_CONSENT_VERSION = "2025.2"


def _intake_probe_world():
    """DRY60C contraindicates ACUTE_HYPERTENSION and demands consent 2026.1; the
    guests are built one at a time so each form stops at a different point."""
    return _dry_world(treatment_type=DRY60_SCREENED, with_guest=False)


def _guest_with_intake(full_name, resort_room_number, condition_codes=None,
                       medications=None, consent_version=CANON_CONSENT_VERSION,
                       sign_consent=True, screen=True, override=False):
    guest = fx.create_guest(full_name=full_name,
                            resort_room_number=resort_room_number, **NO_LOYALTY)
    form = fx.screened_intake(
        guest["id"], guest["version"], condition_codes=condition_codes,
        medications=medications, consent_version=consent_version,
        sign_consent=sign_consent, screen=screen)
    if override:
        form = validate_success(api_client.override_intake_form(
            form["id"], f.override_payload("cleared by resort physician"),
            fx.DIRECTOR))
    return guest, form


def test_an_unscreened_form_fails_rung_twelve_and_a_screened_one_fails_thirteen():
    """Two guests, two different clinical errors, one identical treatment type.

    PRD §2.7 rung 12: "**Intake cleared** — the guest has an authoritative intake
    form whose `status` is `SCREENED_CLEAR` or `OVERRIDDEN`. Applies to appointment
    booking and appointment confirmation. Violation: `ERR_INTAKE_NOT_CLEARED`
    (409)."

    PRD §2.7 rung 13: "**Consent on file** — that same form's `consent_signed_at`
    is set and its `consent_version` equals the treatment type's
    `required_consent_version`. Applies to appointment booking and appointment
    confirmation. Violation: `ERR_CONSENT_MISSING` (409)."

    PRD §3.4: "Consent is orthogonal to that flow: recording a signature is legal
    from either `DRAFT` or `SUBMITTED`, before or after screening, and it writes
    the supplied `consent_version` onto the form and stamps `consent_signed_at`
    with the logical clock."

    Design: Corner/validations/intake_clearance_consent_and_contraindication_are_three_distinct_rungs
    """
    world = _intake_probe_world()
    submitted_guest, submitted_form = _guest_with_intake(
        "Guest Submitted Only", "1601", screen=False)
    consentless_guest, consentless_form = _guest_with_intake(
        "Guest No Consent", "1602", sign_consent=False)

    # Signing consent before submission is legal and does not by itself clear the
    # guest: the form is still SUBMITTED and never became authoritative.
    assert submitted_form["status"] == "SUBMITTED"
    assert submitted_form["consent_version"] == CANON_CONSENT_VERSION
    assert submitted_form["consent_signed_at"] is not None
    assert validate_success(api_client.get_guest(
        submitted_guest["id"], fx.COORDINATOR))["authoritative_intake_form_id"] \
        is None

    validate_error(
        _book(world, "2026-08-10T10:00:00.000Z",
              guest_id=submitted_guest["id"]),
        ApiErrorId.ERR_INTAKE_NOT_CLEARED.value, 409)

    # The second guest cleared rung 12 on a SCREENED_CLEAR form and fails rung 13
    # on the presence clause alone.
    assert consentless_form["status"] == "SCREENED_CLEAR"
    assert consentless_form["consent_signed_at"] is None
    assert consentless_form["consent_version"] is None
    assert validate_success(api_client.get_guest(
        consentless_guest["id"], fx.COORDINATOR))[
            "authoritative_intake_form_id"] == consentless_form["id"]

    validate_error(
        _book(world, "2026-08-10T12:00:00.000Z",
              guest_id=consentless_guest["id"]),
        ApiErrorId.ERR_CONSENT_MISSING.value, 409)

    assert_list_count(api_client.list_appointments(fx.COORDINATOR), 0,
                      "appointments after the two clinical refusals")


def test_the_consent_version_equality_clause_is_its_own_way_to_fail_rung_thirteen():
    """A signed but superseded consent version fails the same rung as no signature.

    PRD §3.5: "Clinically, the guest must have an authoritative intake form in
    `SCREENED_CLEAR` or `OVERRIDDEN` (`ERR_INTAKE_NOT_CLEARED`), that form must
    carry a consent signature whose `consent_version` matches the treatment type's
    `required_consent_version` (`ERR_CONSENT_MISSING`), and the guest's
    `screened_condition_codes` must share no code with the treatment type's
    `contraindication_codes` (`ERR_CONTRAINDICATION_PRESENT`)."

    Design: Corner/validations/intake_clearance_consent_and_contraindication_are_three_distinct_rungs
    """
    world = _intake_probe_world()
    stale_guest, stale_form = _guest_with_intake(
        "Guest Stale Consent Version", "1603",
        consent_version=STALE_CONSENT_VERSION)

    assert stale_form["status"] == "SCREENED_CLEAR"
    assert stale_form["consent_version"] == STALE_CONSENT_VERSION
    assert stale_form["consent_signed_at"] is not None, (
        "the presence clause is satisfied, so only the equality clause can fire")

    validate_error(
        _book(world, "2026-08-10T14:00:00.000Z", guest_id=stale_guest["id"]),
        ApiErrorId.ERR_CONSENT_MISSING.value, 409)

    # The control: an otherwise identical guest whose signature quotes 2026.1
    # clears every rung of the same booking.
    current_guest, current_form = _guest_with_intake(
        "Guest Current Consent Version", "1604")
    assert current_form["consent_version"] == CANON_CONSENT_VERSION
    accepted = validate_success(
        _book(world, "2026-08-10T14:00:00.000Z", guest_id=current_guest["id"]),
        201)
    assert_state_pair(accepted, "REQUESTED", "PENDING")
    assert accepted["quoted_price_cents"] == DRY_LIST_PRICE_CENTS


def test_an_overridden_form_clears_rungs_twelve_and_thirteen_and_fails_fourteen():
    """The override opens the clinical gate without erasing the recorded codes.

    PRD §2.7 rung 14: "**Contraindication screening** — the guest's
    `screened_condition_codes` shares no code with the treatment type's
    `contraindication_codes`. Applies to appointment booking and appointment
    confirmation. Violation: `ERR_CONTRAINDICATION_PRESENT` (409)."

    PRD §3.4: "Both screening outcomes rewrite `authoritative_intake_form_id` to
    the freshly screened form and copy that form's full `condition_codes` — not
    merely the flagged subset — into the guest's `screened_condition_codes`, which
    is the input set every contraindication check reads."

    PRD §3.4: "Each screening increments the guest's `version` by 1."

    Design: Corner/validations/intake_clearance_consent_and_contraindication_are_three_distinct_rungs
    """
    world = _intake_probe_world()
    guest, form = _guest_with_intake(
        "Guest Overridden Flag", "1605",
        condition_codes=["ACUTE_HYPERTENSION"], medications=["LISINOPRIL"],
        override=True)

    assert form["status"] == "OVERRIDDEN"
    assert form["flagged_condition_codes"] == ["ACUTE_HYPERTENSION"], (
        "the declared medication is recorded but never screened")
    assert form["overridden_by_user_id"] == DIRECTOR_USER_ID

    validate_error(
        _book(world, "2026-08-10T10:00:00.000Z", guest_id=guest["id"]),
        ApiErrorId.ERR_CONTRAINDICATION_PRESENT.value, 409)

    guest_row = validate_success(api_client.get_guest(guest["id"], fx.COORDINATOR))
    assert guest_row["authoritative_intake_form_id"] == form["id"]
    assert guest_row["screened_condition_codes"] == ["ACUTE_HYPERTENSION"], (
        "the override does not clear the recorded codes")
    assert guest_row["version"] == 3, (
        "one increment for opening the form and one for screening it")
    assert_list_count(api_client.list_appointments(fx.COORDINATOR), 0,
                      "appointments after the contraindicated probe")


# ---------------------------------------------------------------------------
# license_gate_unverified_then_verified_but_expired_on_the_clock_date
# ---------------------------------------------------------------------------

LICENCE_PROBE_CLOCK = "2026-08-06T09:00:00.000Z"
LAPSED_EXPIRES_ON = "2026-08-05"            # one day before the probe clock date
PENDING_THERAPIST = "Therapist Pending Licence"
LAPSING_THERAPIST = "Therapist Lapsing Licence"
LICENSED_THERAPIST = "Therapist Fully Licensed"


def _licence_probe_world():
    """Three therapists that differ only in licence posture. All three hold an
    ACTIVE BASIC SWEDISH grant and an AVAILABLE block covering the probe slot, so
    rungs 19 and 23 cannot pre-empt the licence rungs, and every licence requires
    0 continuing-education hours so the CE rungs stay inert at review time."""
    world = _dry_world(therapist_names=())
    roster = ((PENDING_THERAPIST, "2027-06-30", False),
              (LAPSING_THERAPIST, LAPSED_EXPIRES_ON, True),
              (LICENSED_THERAPIST, "2027-06-30", True))
    for index, (name, expires_on, verify) in enumerate(roster):
        therapist = fx.create_therapist(full_name=name)
        world.therapists[name] = therapist
        licence = fx.submit_license(
            therapist["id"], submit_user=f"co-1{index}",
            license_number=f"HI-LMT-100{index}", expires_on=expires_on)
        world.licenses[name] = licence
        if verify:
            world.licenses[name] = fx.review_license(
                licence["id"], "VERIFIED", review_user=f"co-2{index}")
        fx.grant_certification(therapist["id"], user=f"co-2{index}",
                               **SWEDISH_BASIC)
        fx.add_shift_block(therapist["id"],
                           start_at="2026-08-10T09:00:00.000Z",
                           end_at="2026-08-10T18:00:00.000Z")
    return world


def test_a_pending_licence_fails_rung_fifteen_and_a_lapsed_one_fails_rung_sixteen():
    """The lapsed licence is still stored as VERIFIED, so only the date comparison
    can explain its refusal.

    PRD §2.7 rung 15: "**Licence verified** — the therapist holds a licence whose
    `verification_status` is `VERIFIED` and whose `state_code` equals the
    therapist's `practice_state_code`. Applies to appointment booking and
    appointment confirmation. Violation: `ERR_LICENSE_NOT_VERIFIED` (409)."

    PRD §2.7 rung 16: "**Licence unexpired** — that licence's `expires_on` falls on
    or after the current logical-clock date. Booking and confirmation check
    *current* validity only; a licence that lapses between booking and service is
    caught later by the compliance sweep, which blocks the appointment's clearance
    dimension rather than retroactively invalidating the booking."

    Design: Corner/validations/license_gate_unverified_then_verified_but_expired_on_the_clock_date
    """
    world = _licence_probe_world()
    fx.set_clock(LICENCE_PROBE_CLOCK)

    validate_error(
        _book(world, WELL_FORMED_START_AT,
              therapist_id=world.therapist_of(PENDING_THERAPIST)),
        ApiErrorId.ERR_LICENSE_NOT_VERIFIED.value, 409)

    validate_error(
        _book(world, WELL_FORMED_START_AT,
              therapist_id=world.therapist_of(LAPSING_THERAPIST)),
        ApiErrorId.ERR_LICENSE_EXPIRED.value, 409)

    lapsed = validate_success(api_client.get_license(
        world.licenses[LAPSING_THERAPIST]["id"], fx.DIRECTOR))
    assert lapsed["verification_status"] == "VERIFIED", (
        "no compliance sweep has run, so the stored status is untouched")
    assert lapsed["expires_on"] == LAPSED_EXPIRES_ON
    lapsing_therapist = world.fetch_therapist(LAPSING_THERAPIST)
    assert lapsing_therapist["status"] == "ACTIVE"
    assert lapsing_therapist["suspension_reason"] is None

    pending = validate_success(api_client.get_license(
        world.licenses[PENDING_THERAPIST]["id"], fx.DIRECTOR))
    assert pending["verification_status"] == "PENDING_REVIEW"
    assert_list_count(api_client.list_appointments(fx.COORDINATOR), 0,
                      "appointments after the two credential refusals")


def test_the_unexpired_verified_licence_books_and_moves_only_its_own_ledgers():
    """The third therapist clears rungs 12 through 26 on the identical slot.

    PRD §3.5: "On credentials, the assigned therapist must hold a `VERIFIED`
    licence for their `practice_state_code` (`ERR_LICENSE_NOT_VERIFIED`) whose
    `expires_on` is on or after the current logical-clock date
    (`ERR_LICENSE_EXPIRED`), must hold an `ACTIVE`, unexpired certification grant
    for the treatment's `required_skill_code` at or above the required scope rank
    (`ERR_SCOPE_OF_PRACTICE_VIOLATION`), and must themselves be `ACTIVE`
    (`ERR_THERAPIST_NOT_ACTIVE`)."

    PRD §3.5: "Credential validity is judged against the clock at booking time, not
    against the appointment's `start_at`; a credential that lapses in between is
    caught later by the compliance sweep."

    Design: Corner/validations/license_gate_unverified_then_verified_but_expired_on_the_clock_date
    """
    world = _licence_probe_world()
    fx.set_clock(LICENCE_PROBE_CLOCK)

    validate_error(
        _book(world, WELL_FORMED_START_AT,
              therapist_id=world.therapist_of(PENDING_THERAPIST)),
        ApiErrorId.ERR_LICENSE_NOT_VERIFIED.value, 409)
    validate_error(
        _book(world, WELL_FORMED_START_AT,
              therapist_id=world.therapist_of(LAPSING_THERAPIST)),
        ApiErrorId.ERR_LICENSE_EXPIRED.value, 409)

    accepted = validate_success(
        _book(world, WELL_FORMED_START_AT,
              therapist_id=world.therapist_of(LICENSED_THERAPIST)), 201)
    assert_state_pair(accepted, "REQUESTED", "PENDING")
    assert accepted["assignment_mode"] == "EXPLICIT"
    assert accepted["quoted_price_cents"] == DRY_LIST_PRICE_CENTS
    assert_same_instant(accepted["end_at"], "2026-08-10T11:00:00.000Z", "end_at")

    assert_ledgers(world.fetch_room(),
                   world.fetch_therapist(LICENSED_THERAPIST),
                   DRY_ROOM_MINUTES, DRY_THERAPIST_MINUTES)
    for refused in (PENDING_THERAPIST, LAPSING_THERAPIST):
        assert world.fetch_therapist(refused)["assigned_minutes_total"] == 0, (
            f"{refused} was refused and must carry no committed minutes")
    assert_list_count(api_client.list_appointments(fx.COORDINATOR), 1,
                      "appointments after the accepted booking")


# ---------------------------------------------------------------------------
# ce_gate_hours_shortfall_then_ethics_minimum_at_license_review
# ---------------------------------------------------------------------------

CE_CLOCK = "2026-08-01T09:00:00.000Z"
CE_EXPIRES_ON = "2027-06-30"
CE_PERIOD_START_ON = "2024-01-01"
CE_HOURS_REQUIRED = 12.0


def _ce_license():
    """A PENDING_REVIEW licence demanding twelve continuing-education hours whose
    calendar window is wide enough that every record filed below falls inside it,
    so only the cap and the ethics minimum can decide the review."""
    therapist = fx.create_therapist(full_name="Therapist CE Candidate")
    return fx.submit_license(therapist["id"], license_number="HI-LMT-2001",
                             expires_on=CE_EXPIRES_ON,
                             current_period_start_on=CE_PERIOD_START_ON,
                             ce_hours_required=CE_HOURS_REQUIRED)


def _review(license_id, review_note=None):
    return api_client.review_license(
        license_id, f.review_payload("VERIFIED", review_note),
        make_compliance_headers(fx.CO_REVIEW))


def _compliance(license_id):
    return validate_success(api_client.get_ce_compliance(
        license_id, make_compliance_headers(fx.CO_REVIEW)))


def test_the_per_category_cap_keeps_a_twelve_hour_licence_short_of_its_requirement():
    """Twelve raw CLINICAL hours credit only eight, so the shortfall rung fires
    twice on a licence that looks arithmetically compliant.

    PRD §3.3: "the calendar-window continuing-education evaluation must report a
    shortfall of exactly zero hours, or the review is refused with
    `ERR_CE_HOURS_INSUFFICIENT`"

    PRD §3.3: "For each of the three categories separately, the raw category total
    is the sum of `ce_hours` over the in-window records in that category, and the
    credited category figure is the smaller of that raw total and the per-category
    cap of 8 hours; a record outside the window contributes nothing to any total,
    including its own category's raw sum."

    PRD §3.3: "This read never writes: `credited_ce_hours` on the licence is
    updated only by a `VERIFIED` review."

    Design: Corner/validations/ce_gate_hours_shortfall_then_ethics_minimum_at_license_review
    """
    fx.set_clock(CE_CLOCK)
    licence = _ce_license()

    validate_error(_review(licence["id"]),
                   ApiErrorId.ERR_CE_HOURS_INSUFFICIENT.value, 409)
    stored = validate_success(api_client.get_license(licence["id"], fx.DIRECTOR))
    assert stored["verification_status"] == "PENDING_REVIEW"
    assert stored["reviewed_by_user_id"] is None
    assert stored["verified_at"] is None
    assert stored["credited_ce_hours"] == 0

    fx.add_ce_record(licence["id"], course_code="CLIN-201", category="CLINICAL",
                     ce_hours=8.0, completed_on="2025-03-01")
    fx.add_ce_record(licence["id"], course_code="CLIN-202", category="CLINICAL",
                     ce_hours=4.0, completed_on="2025-04-01")

    report = _compliance(licence["id"])
    assert report["variant"] == "CALENDAR_WINDOW"
    assert report["window_start_on"] == CE_PERIOD_START_ON
    assert report["window_end_on"] == CE_EXPIRES_ON
    assert report["ce_hours_required"] == CE_HOURS_REQUIRED
    assert_ce_hours(report["credited_hours"], "credited_hours")
    assert report["credited_hours"] == 8.0, (
        "the twelve raw CLINICAL hours are capped at 8 for the category")
    assert report["shortfall_hours"] == 4.0
    assert report["compliant"] is False

    validate_error(_review(licence["id"]),
                   ApiErrorId.ERR_CE_HOURS_INSUFFICIENT.value, 409)
    assert validate_success(api_client.get_license(
        licence["id"], fx.DIRECTOR))["credited_ce_hours"] == 0, (
        "the computed read left the stored figure alone")


def test_clearing_the_shortfall_uncovers_the_ethics_minimum_rung_beneath_it():
    """Spreading the hours across CLINICAL and SAFETY reaches twelve credited hours
    with zero ethics hours, which moves the refusal one rung down.

    PRD §3.3: "and when `ce_hours_required` is greater than zero, that evaluation's
    credited ethics hours must be at least the two-hour ethics minimum, or the
    review is refused with `ERR_CE_ETHICS_REQUIREMENT_UNMET`"

    PRD §3.3: "`ethics_requirement_met` is true whenever `ce_hours_required` is 0,
    and otherwise true only when `ethics_hours_credited` is at least the two-hour
    ethics minimum."

    Design: Corner/validations/ce_gate_hours_shortfall_then_ethics_minimum_at_license_review
    """
    fx.set_clock(CE_CLOCK)
    licence = _ce_license()
    fx.add_ce_record(licence["id"], course_code="CLIN-201", category="CLINICAL",
                     ce_hours=8.0, completed_on="2025-03-01")
    fx.add_ce_record(licence["id"], course_code="CLIN-202", category="CLINICAL",
                     ce_hours=4.0, completed_on="2025-04-01")
    validate_error(_review(licence["id"]),
                   ApiErrorId.ERR_CE_HOURS_INSUFFICIENT.value, 409)

    fx.add_ce_record(licence["id"], course_code="SAFE-101", category="SAFETY",
                     ce_hours=4.0, completed_on="2025-05-01")

    report = _compliance(licence["id"])
    assert report["credited_hours"] == 12.0, "8 capped CLINICAL plus 4 SAFETY"
    assert report["shortfall_hours"] == 0.0
    assert report["ethics_hours_credited"] == 0.0
    assert report["ethics_requirement_met"] is False
    assert report["compliant"] is False, (
        "zero shortfall is not enough while the ethics minimum is unmet")

    validate_error(_review(licence["id"]),
                   ApiErrorId.ERR_CE_ETHICS_REQUIREMENT_UNMET.value, 409)
    stored = validate_success(api_client.get_license(licence["id"], fx.DIRECTOR))
    assert stored["verification_status"] == "PENDING_REVIEW"
    assert stored["verified_at"] is None
    assert stored["credited_ce_hours"] == 0


def test_the_fourth_filing_carries_the_review_through_and_stamps_credited_hours():
    """Two ethics hours flip `compliant` and the review writes the credited figure
    the evaluation produced at that moment — fourteen, not the required twelve.

    PRD §3.3: "A licence that clears all three moves `PENDING_REVIEW → VERIFIED`,
    stamps `verified_at` with the logical clock, records `reviewed_by_user_id` and
    `review_note`, and writes `credited_ce_hours` with the credited hours figure
    that the calendar-window evaluation produced at that moment."

    PRD §3.3: "`compliant` is true only when `shortfall_hours` is 0 and
    `ethics_requirement_met` is true."

    Design: Corner/validations/ce_gate_hours_shortfall_then_ethics_minimum_at_license_review
    """
    fx.set_clock(CE_CLOCK)
    licence = _ce_license()
    validate_error(_review(licence["id"]),
                   ApiErrorId.ERR_CE_HOURS_INSUFFICIENT.value, 409)
    fx.add_ce_record(licence["id"], course_code="CLIN-201", category="CLINICAL",
                     ce_hours=8.0, completed_on="2025-03-01")
    fx.add_ce_record(licence["id"], course_code="CLIN-202", category="CLINICAL",
                     ce_hours=4.0, completed_on="2025-04-01")
    validate_error(_review(licence["id"]),
                   ApiErrorId.ERR_CE_HOURS_INSUFFICIENT.value, 409)
    fx.add_ce_record(licence["id"], course_code="SAFE-101", category="SAFETY",
                     ce_hours=4.0, completed_on="2025-05-01")
    validate_error(_review(licence["id"]),
                   ApiErrorId.ERR_CE_ETHICS_REQUIREMENT_UNMET.value, 409)

    fx.add_ce_record(licence["id"], course_code="ETH-101", category="ETHICS",
                     ce_hours=2.0, completed_on="2025-06-01")
    report = _compliance(licence["id"])
    assert report["credited_hours"] == 14.0
    assert report["ethics_hours_credited"] == 2.0
    assert report["ethics_requirement_met"] is True
    assert report["shortfall_hours"] == 0.0
    assert report["compliant"] is True

    verified = validate_success(_review(licence["id"], "CE complete"))
    assert verified["verification_status"] == "VERIFIED"
    assert_same_instant(verified["verified_at"], CE_CLOCK, "verified_at")
    assert verified["reviewed_by_user_id"] == fx.CO_REVIEW
    assert verified["review_note"] == "CE complete"
    assert_ce_hours(verified["credited_ce_hours"], "credited_ce_hours")
    assert verified["credited_ce_hours"] == 14.0, (
        "the stamped figure is the credited hours, not the required 12")
    assert verified["version"] == 2, (
        "one mutation has been applied to the filed licence")


# ---------------------------------------------------------------------------
# room_class_availability_shift_window_double_booking_and_lead_time_rungs
# ---------------------------------------------------------------------------

SCHED_CLOCK = "2026-08-01T09:00:00.000Z"
SCHED_BEFORE_SHIFT_AT = "2026-08-10T06:00:00.000Z"
SCHED_FIRST_AT = "2026-08-10T12:00:00.000Z"
SCHED_OVERLAPPING_AT = "2026-08-10T12:30:00.000Z"
SCHED_ONE_MINUTE_SHORT_AT = "2026-08-01T10:59:00.000Z"
SCHED_EXACTLY_TWO_HOURS_AT = "2026-08-01T11:00:00.000Z"


def _scheduling_probe_world():
    """Three DRY rooms plus one HYDRO room, one therapist whose AVAILABLE blocks
    cover 08:00-22:00 on both probe dates, and DRY-3 taken out of service."""
    world = _dry_world(room_codes=("DRY-1", "DRY-2", "DRY-3"), clock=SCHED_CLOCK)
    world.rooms["HYDRO-1"] = fx.create_room(code="HYDRO-1")
    fx.add_shift_block(world.therapist_id,
                       start_at="2026-08-01T08:00:00.000Z",
                       end_at="2026-08-01T22:00:00.000Z")
    fx.set_room_status(world.room_of("DRY-3"), "MAINTENANCE")
    return world


def test_the_room_class_rung_is_checked_before_the_room_status_rung():
    """A HYDRO room and a room under maintenance fail on different rungs, and
    neither refusal leaves a trace.

    PRD §2.7 rung 21: "**Room class** — the room's `room_class` equals the treatment
    type's `room_class_required` and the room's `capacity_guests` is at least 1.
    Applies to appointment booking. Violation: `ERR_ROOM_CLASS_MISMATCH` (409)."

    PRD §2.7 rung 22: "**Room available** — the room's `status` is `ACTIVE`. Applies
    to appointment booking and appointment confirmation. Violation:
    `ERR_ROOM_UNAVAILABLE` (409)."

    Design: Corner/validations/room_class_availability_shift_window_double_booking_and_lead_time_rungs
    """
    world = _scheduling_probe_world()

    validate_error(_book(world, SCHED_FIRST_AT, room_code="HYDRO-1"),
                   ApiErrorId.ERR_ROOM_CLASS_MISMATCH.value, 409)
    validate_error(_book(world, SCHED_FIRST_AT, room_code="DRY-3"),
                   ApiErrorId.ERR_ROOM_UNAVAILABLE.value, 409)

    assert_list_count(api_client.list_appointments(fx.COORDINATOR), 0,
                      "appointments after the two resource refusals")
    for code in ("DRY-1", "DRY-2", "DRY-3", "HYDRO-1"):
        assert world.fetch_room(code)["booked_minutes_total"] == 0, (
            f"{code} must carry no committed minutes")
    assert world.fetch_therapist()["assigned_minutes_total"] == 0


def test_shift_containment_is_checked_before_the_therapist_conflict_rung():
    """A slot outside every block fails on containment; a second room does not save
    a therapist who is already committed at that hour.

    PRD §2.7 rung 23: "**Shift containment** — an `AVAILABLE` shift block of the
    assigned therapist contains the appointment's interval with both bounds
    inclusive. Applies to appointment booking. Violation:
    `ERR_OUTSIDE_SHIFT_WINDOW` (409)."

    PRD §3.5: "The therapist must also be free: no `BREAK` or `ADMIN` block of
    theirs and no other appointment of theirs in `REQUESTED`, `CONFIRMED`,
    `CHECKED_IN` or `IN_SERVICE` may intersect the appointment's interval, where
    intersection is judged with both intervals closed at both ends, so merely
    touching at an endpoint counts as a conflict (`ERR_THERAPIST_DOUBLE_BOOKED`)."

    Design: Corner/validations/room_class_availability_shift_window_double_booking_and_lead_time_rungs
    """
    world = _scheduling_probe_world()

    validate_error(_book(world, SCHED_BEFORE_SHIFT_AT, room_code="DRY-1"),
                   ApiErrorId.ERR_OUTSIDE_SHIFT_WINDOW.value, 409)

    accepted = validate_success(_book(world, SCHED_FIRST_AT, room_code="DRY-1"), 201)
    assert_state_pair(accepted, "REQUESTED", "PENDING")
    assert_same_instant(accepted["end_at"], "2026-08-10T13:00:00.000Z", "end_at")

    validate_error(_book(world, SCHED_OVERLAPPING_AT, room_code="DRY-2"),
                   ApiErrorId.ERR_THERAPIST_DOUBLE_BOOKED.value, 409)

    assert_ledgers(world.fetch_room("DRY-1"), world.fetch_therapist(),
                   DRY_ROOM_MINUTES, DRY_THERAPIST_MINUTES)
    assert world.fetch_room("DRY-2")["booked_minutes_total"] == 0, (
        "the refused second booking touched no ledger of its own")
    assert_list_count(api_client.list_appointments(fx.COORDINATOR), 1,
                      "appointments after the conflict refusal")


def test_the_lead_time_rung_admits_exactly_one_hundred_and_twenty_minutes():
    """One minute short is refused; the boundary itself is accepted.

    PRD §2.7 rung 26: "**Booking lead time** — `start_at` is at least the minimum
    lead time after the logical clock. Applies to appointment booking. Violation:
    `ERR_BOOKING_LEAD_TIME` (409)."

    PRD §3.5: "Finally the slot must be far enough out — `start_at` must be at least
    two hours, that is 120 minutes, after the logical clock
    (`ERR_BOOKING_LEAD_TIME`) — and the guest's `booking_privilege` must be `OPEN`
    (`ERR_GUEST_BOOKING_RESTRICTED`)."

    Design: Corner/validations/room_class_availability_shift_window_double_booking_and_lead_time_rungs
    """
    world = _scheduling_probe_world()

    validate_error(_book(world, SCHED_ONE_MINUTE_SHORT_AT, room_code="DRY-1"),
                   ApiErrorId.ERR_BOOKING_LEAD_TIME.value, 409)
    assert_list_count(api_client.list_appointments(fx.COORDINATOR), 0,
                      "appointments after the 119-minute refusal")

    accepted = validate_success(
        _book(world, SCHED_EXACTLY_TWO_HOURS_AT, room_code="DRY-1"), 201)
    assert_state_pair(accepted, "REQUESTED", "PENDING")
    assert_same_instant(accepted["start_at"], SCHED_EXACTLY_TWO_HOURS_AT, "start_at")
    assert accepted["quoted_price_cents"] == DRY_LIST_PRICE_CENTS
    assert_ledgers(world.fetch_room("DRY-1"), world.fetch_therapist(),
                   DRY_ROOM_MINUTES, DRY_THERAPIST_MINUTES)


# ---------------------------------------------------------------------------
# retail_product_line_and_gratuity_cap_rungs_on_service_endpoints
# ---------------------------------------------------------------------------

RETAIL_CLOCK = "2026-08-09T09:00:00.000Z"
RETAIL_START_AT = "2026-08-10T10:00:00.000Z"
RETAIL_ARRIVAL_CLOCK = "2026-08-10T09:45:00.000Z"
RETAIL_SERVICE_CLOCK = "2026-08-10T10:00:00.000Z"
RETAIL_AMOUNT_CENTS = 7400
DRY60_DELIVERED_MINUTES = 60


def _in_service_world():
    """A DRY60 whose retail line is BODY, driven to IN_SERVICE so both the retail
    endpoint and the completion endpoint are reachable."""
    world = _dry_world(treatment_type=DRY60_BODY_RETAIL, clock=RETAIL_CLOCK)
    appointment = _book(world, RETAIL_START_AT)
    appointment_id = validate_success(appointment, 201)["id"]
    fx.confirm(appointment_id)
    fx.set_clock(RETAIL_ARRIVAL_CLOCK)
    fx.check_in(appointment_id)
    fx.set_clock(RETAIL_SERVICE_CLOCK)
    world.appointments["a"] = fx.start_service(appointment_id, world.therapist_id)
    return world


def test_a_mismatched_retail_line_is_refused_and_the_matching_one_posts_nothing():
    """The product line is checked against the treatment type, and even an accepted
    recommendation is not a sale.

    PRD §3.7: "The `product_line` must equal the appointment's treatment type's
    `retail_product_line`, or the request is refused with
    `ERR_PRODUCT_LINE_MISMATCH` — a body-lotion recommendation cannot ride along on
    a treatment whose retail line is aromatherapy."

    PRD §3.7: "A new recommendation lands in `status` `RECOMMENDED` with
    `resolved_by_user_id` and `resolved_at` both null, and it posts nothing to the
    folio; it is a tracked recommendation, not a sale."

    Design: Corner/validations/retail_product_line_and_gratuity_cap_rungs_on_service_endpoints
    """
    world = _in_service_world()
    appointment_id = world.appointments["a"]["id"]
    therapist_headers = make_therapist_headers(world.therapist_id)

    validate_error(api_client.create_retail_attachment(
        appointment_id,
        f.retail_attachment_payload("FACE-SERUM-01", "FACE", RETAIL_AMOUNT_CENTS),
        therapist_headers), ApiErrorId.ERR_PRODUCT_LINE_MISMATCH.value, 409)
    assert_list_count(
        api_client.list_retail_attachments(appointment_id, therapist_headers), 0,
        "attachments after the mismatched line")

    created = validate_success(api_client.create_retail_attachment(
        appointment_id,
        f.retail_attachment_payload("BODY-LOTION-01", "BODY", RETAIL_AMOUNT_CENTS),
        therapist_headers), 201)
    assert created["status"] == "RECOMMENDED"
    assert created["resolved_by_user_id"] is None
    assert created["resolved_at"] is None
    assert created["amount_cents"] == RETAIL_AMOUNT_CENTS

    rows, meta = validate_paginated(
        api_client.list_retail_attachments(appointment_id, therapist_headers))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [row["product_sku"] for row in rows] == ["BODY-LOTION-01"]

    postings = validate_paginated(api_client.list_appointment_folio_charges(
        appointment_id, fx.DIRECTOR))[0]
    assert [posting for posting in postings if posting["kind"] == "RETAIL"] == [], (
        "an unresolved recommendation posts nothing to the folio")


def test_the_gratuity_cap_rejects_one_cent_over_half_the_frozen_quote():
    """5,000 basis points of 18000 is 9000; 9001 is a 422 and 9000 is accepted.

    PRD §3.6: "The gratuity is capped at 5,000 basis points of the frozen
    `quoted_price_cents` — half the quoted price, rounded half up — and a larger
    figure is rejected with `ERR_GRATUITY_LIMIT_EXCEEDED` (HTTP 422)."

    PRD §3.6: "Completion writes both submitted values onto the appointment and
    stops there: **no settlement is cut at completion**."

    Design: Corner/validations/retail_product_line_and_gratuity_cap_rungs_on_service_endpoints
    """
    world = _in_service_world()
    appointment_id = world.appointments["a"]["id"]
    therapist_headers = make_therapist_headers(world.therapist_id)
    assert world.appointments["a"]["quoted_price_cents"] == DRY_LIST_PRICE_CENTS

    validate_error(api_client.complete_appointment(
        appointment_id,
        f.complete_payload(DRY60_DELIVERED_MINUTES, GRATUITY_CAP_CENTS + 1),
        therapist_headers),
        ApiErrorId.ERR_GRATUITY_LIMIT_EXCEEDED.value, 422)

    untouched = world.fetch_appointment(appointment_id)
    assert untouched["schedule_status"] == "IN_SERVICE"
    assert untouched["gratuity_cents"] == 0
    assert untouched["actual_duration_minutes"] is None
    assert untouched["realized_price_cents"] is None

    completed = validate_success(api_client.complete_appointment(
        appointment_id,
        f.complete_payload(DRY60_DELIVERED_MINUTES, GRATUITY_CAP_CENTS),
        therapist_headers))
    assert completed["schedule_status"] == "COMPLETED"
    assert completed["gratuity_cents"] == GRATUITY_CAP_CENTS
    assert completed["actual_duration_minutes"] == DRY60_DELIVERED_MINUTES
    assert completed["realized_price_cents"] is None, (
        "the final settlement is a separate, director-driven act"
    )


# ---------------------------------------------------------------------------
# segregation_of_duties_blocks_self_review_and_self_override
# ---------------------------------------------------------------------------

SOD_CLOCK = "2026-08-01T09:00:00.000Z"
FLAGGING_CONDITION_CODE = "ACUTE_HYPERTENSION"


def _sod_license(ce_hours_required=0):
    therapist = fx.create_therapist(full_name="Therapist Under Review")
    return fx.submit_license(therapist["id"], submit_user=fx.CO_SUBMIT,
                             license_number="HI-LMT-3001",
                             expires_on="2027-06-30",
                             ce_hours_required=ce_hours_required)


def test_the_filing_officer_may_not_review_their_own_licence():
    """The refusal is decided by the recorded identifier pair alone, and a second
    officer then carries the identical decision through.

    PRD §2.7 rung 11: "**Segregation of duties** — the licence reviewer differs from
    `submitted_by_user_id`, and the intake overrider differs from
    `screened_by_user_id`. Applies to licence review and intake override. Violation:
    `ERR_SEGREGATION_OF_DUTIES` (409)."

    PRD §3.3: "The filed licence lands in `verification_status` `PENDING_REVIEW`
    with `credited_ce_hours` at 0, `reviewed_by_user_id`, `review_note` and
    `verified_at` all null, and `submitted_by_user_id` set to the filing officer's
    `X-User-ID` — which is exactly what bars that officer from reviewing it."

    Design: Corner/validations/segregation_of_duties_blocks_self_review_and_self_override
    """
    fx.set_clock(SOD_CLOCK)
    licence = _sod_license()
    assert licence["submitted_by_user_id"] == fx.CO_SUBMIT

    validate_error(api_client.review_license(
        licence["id"], f.review_payload("VERIFIED", "self approved"),
        make_compliance_headers(fx.CO_SUBMIT)),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)

    untouched = validate_success(api_client.get_license(licence["id"], fx.DIRECTOR))
    assert untouched["verification_status"] == "PENDING_REVIEW"
    assert untouched["reviewed_by_user_id"] is None
    assert untouched["review_note"] is None
    assert untouched["verified_at"] is None
    assert untouched["version"] == 1, "the refused review wrote nothing at all"

    verified = fx.review_license(licence["id"], "VERIFIED",
                                 review_user=fx.CO_REVIEW)
    assert verified["verification_status"] == "VERIFIED"
    assert verified["reviewed_by_user_id"] == fx.CO_REVIEW
    assert_same_instant(verified["verified_at"], SOD_CLOCK, "verified_at")


def test_the_screening_officer_may_not_override_the_form_they_flagged():
    """Wearing the director role does not launder the identity: the comparison is
    against `screened_by_user_id`, not against the role.

    PRD §3.4: "The first is a `SpaDirector` override, which moves the form
    `SCREENED_FLAGGED → OVERRIDDEN`, requires an `override_reason` in the payload,
    records `overridden_by_user_id`, and is refused with
    `ERR_SEGREGATION_OF_DUTIES` when the overriding user is the same user recorded
    as `screened_by_user_id`."

    PRD §2.1: "Where two such recorded identifiers are compared with each other,
    that comparison is a segregation-of-duties rule, not an ownership rule."

    Design: Corner/validations/segregation_of_duties_blocks_self_review_and_self_override
    """
    fx.set_clock(SOD_CLOCK)
    guest = fx.create_guest(**NO_LOYALTY)
    form = fx.screened_intake(guest["id"], guest["version"],
                              condition_codes=[FLAGGING_CONDITION_CODE],
                              screen_user=fx.CO_SCREEN)
    assert form["status"] == "SCREENED_FLAGGED"
    assert form["screened_by_user_id"] == fx.CO_SCREEN

    validate_error(api_client.override_intake_form(
        form["id"], f.override_payload("I stand by my own screening"),
        make_director_headers(fx.CO_SCREEN)),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)

    untouched = validate_success(api_client.get_intake_form(
        form["id"], fx.DIRECTOR))
    assert untouched["status"] == "SCREENED_FLAGGED"
    assert untouched["overridden_by_user_id"] is None
    assert untouched["override_reason"] is None
    assert untouched["flagged_condition_codes"] == [FLAGGING_CONDITION_CODE]

    overridden = validate_success(api_client.override_intake_form(
        form["id"], f.override_payload("cleared by resort physician"),
        fx.DIRECTOR))
    assert overridden["status"] == "OVERRIDDEN"
    assert overridden["overridden_by_user_id"] == DIRECTOR_USER_ID
    assert overridden["override_reason"] == "cleared by resort physician"


def test_segregation_of_duties_is_decided_before_the_continuing_education_gates():
    """A licence demanding twelve hours with no records filed still answers the
    self-reviewer with the duties error; the shortfall was real all along, as the
    independent reviewer proves.

    PRD §2.7: "The server walks the ladder from the top and returns the error of the
    **first** rung the request violates; lower rungs are not evaluated once a rung
    has failed."

    PRD §3.3: "reviewing a licence that is not `PENDING_REVIEW` is refused with
    `ERR_INVALID_LICENSE_STATE`, and a reviewer whose `X-User-ID` equals
    `submitted_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`"

    Design: Corner/validations/segregation_of_duties_blocks_self_review_and_self_override
    """
    fx.set_clock(SOD_CLOCK)
    licence = _sod_license(ce_hours_required=12.0)

    validate_error(api_client.review_license(
        licence["id"], f.review_payload("VERIFIED"),
        make_compliance_headers(fx.CO_SUBMIT)),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)

    validate_error(api_client.review_license(
        licence["id"], f.review_payload("VERIFIED"),
        make_compliance_headers(fx.CO_REVIEW)),
        ApiErrorId.ERR_CE_HOURS_INSUFFICIENT.value, 409)

    stored = validate_success(api_client.get_license(licence["id"], fx.DIRECTOR))
    assert stored["verification_status"] == "PENDING_REVIEW"
    assert stored["credited_ce_hours"] == 0
    assert stored["version"] == 1, "neither refusal mutated the licence"


# ---------------------------------------------------------------------------
# satisfaction_pass_with_every_gate_armed_at_its_inclusive_boundary
# ---------------------------------------------------------------------------

BOUNDARY_CLOCK = "2026-08-09T09:00:00.000Z"
BOUNDARY_EXPIRY = "2026-08-09"                 # the clock date exactly
BOUNDARY_START_AT = "2026-08-09T11:00:00.000Z"  # exactly 120 minutes out
BOUNDARY_END_AT = "2026-08-09T12:00:00.000Z"
BOUNDARY_ONE_MINUTE_PAST = "2026-08-09T11:01:00.000Z"
NON_CONTRAINDICATED_CONDITION_CODE = "RECENT_SURGERY_90D"


def _boundary_world():
    """Every gate sits exactly on its inclusive boundary: the licence and the
    certification expire on the clock date, the single AVAILABLE block coincides
    with the appointment interval, the slot is exactly 120 minutes out, and the
    guest's one flagged condition is not among the treatment's contraindications so
    the director override is what clears the clinical block."""
    world = _dry_world(
        treatment_type=DRY60_SCREENED, clock=BOUNDARY_CLOCK,
        condition_codes=[NON_CONTRAINDICATED_CONDITION_CODE],
        license_overrides={"expires_on": BOUNDARY_EXPIRY},
        certification=dict(SWEDISH_BASIC, expires_on=BOUNDARY_EXPIRY),
        shift_block_overrides={"start_at": BOUNDARY_START_AT,
                               "end_at": BOUNDARY_END_AT})
    assert world.intake["status"] == "SCREENED_FLAGGED"
    world.intake = validate_success(api_client.override_intake_form(
        world.intake["id"], f.override_payload("cleared by resort physician"),
        fx.DIRECTOR))
    return world


def test_every_gate_passes_on_its_boundary_while_one_minute_past_it_fails():
    """The control probe one minute later proves the shift window really is the
    binding constraint, and the boundary booking then clears all of rungs 12 to 26.

    PRD §3.5: "The therapist's calendar must contain the work: some `AVAILABLE`
    shift block of theirs must contain the appointment's interval with both bounds
    inclusive, meaning the block's `start_at` is at or before the appointment's
    `start_at` and the block's `end_at` is at or after the appointment's `end_at`
    (`ERR_OUTSIDE_SHIFT_WINDOW`)."

    PRD §2.7 rung 16: "**Licence unexpired** — that licence's `expires_on` falls on
    or after the current logical-clock date."

    PRD §3.5: "A successful booking lands with `schedule_status` `REQUESTED` and
    `clearance_status` `PENDING` with `clearance_block_reason` null: the appointment
    exists but is neither confirmed nor clinically cleared."

    Design: Corner/validations/satisfaction_pass_with_every_gate_armed_at_its_inclusive_boundary
    """
    world = _boundary_world()

    validate_error(_book(world, BOUNDARY_ONE_MINUTE_PAST),
                   ApiErrorId.ERR_OUTSIDE_SHIFT_WINDOW.value, 409)

    accepted = validate_success(_book(world, BOUNDARY_START_AT), 201)
    assert_state_pair(accepted, "REQUESTED", "PENDING")
    assert accepted["assignment_mode"] == "EXPLICIT"
    assert accepted["quoted_price_cents"] == DRY_LIST_PRICE_CENTS
    assert_same_instant(accepted["start_at"], BOUNDARY_START_AT, "start_at")
    assert_same_instant(accepted["end_at"], BOUNDARY_END_AT, "end_at")
    assert accepted["high_demand_slot"] is False

    licence = validate_success(api_client.get_license(
        world.license_id, fx.DIRECTOR))
    assert licence["expires_on"] == BOUNDARY_EXPIRY, (
        "the licence expires on the clock date and is still valid today")
    grants = assert_list_count(api_client.list_certifications(
        world.therapist_id, fx.DIRECTOR), 1, "certification grants")
    assert grants[0]["expires_on"] == BOUNDARY_EXPIRY
    assert grants[0]["status"] == "ACTIVE"
    assert world.fetch_guest()["screened_condition_codes"] == \
        [NON_CONTRAINDICATED_CONDITION_CODE], (
        "the flagged condition is recorded but is not a contraindication of DRY60C")
    assert_ledgers(world.fetch_room(), world.fetch_therapist(),
                   DRY_ROOM_MINUTES, DRY_THERAPIST_MINUTES)


def test_confirmation_re_runs_the_clinical_and_credential_gates_only():
    """The shift window that would now reject the booking is not re-evaluated, and
    the frozen quote survives the transition untouched.

    PRD §3.6: "The room-class, shift-window, turnover, lead-time and
    booking-privilege rules are booking-time rules and are not re-evaluated at
    confirmation."

    PRD §3.6: "Confirmation is also the transition that advances the second
    dimension: `clearance_status` moves `PENDING → CLEARED` and
    `clearance_block_reason` is set to null."

    Design: Corner/validations/satisfaction_pass_with_every_gate_armed_at_its_inclusive_boundary
    """
    world = _boundary_world()
    accepted = validate_success(_book(world, BOUNDARY_START_AT), 201)

    confirmed = validate_success(
        api_client.confirm_appointment(accepted["id"], {}, fx.COORDINATOR))
    assert_state_pair(confirmed, "CONFIRMED", "CLEARED")
    assert confirmed["quoted_price_cents"] == accepted["quoted_price_cents"], (
        "the quote is frozen at booking and confirmation does not requote")
    assert_same_instant(confirmed["end_at"], BOUNDARY_END_AT, "end_at")
    assert confirmed["version"] == accepted["version"] + 1
    assert confirmed["actual_duration_minutes"] is None
    assert confirmed["realized_price_cents"] is None
    assert_ledgers(world.fetch_room(), world.fetch_therapist(),
                   DRY_ROOM_MINUTES, DRY_THERAPIST_MINUTES)
