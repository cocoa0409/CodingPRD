"""Non-linear state machines: the appointment's parallel clearance dimension and
the cyclic licence review loop that inverts the segregation-of-duties
counterparty.
"""

from test_helpers import (
    ApiErrorId,
    assert_list_count,
    assert_same_instant,
    assert_state_pair,
    make_compliance_headers,
    make_director_headers,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.constants import CANON_START_AT, CLOCK_STARTUP_DEFAULT
from test_helpers import factories as f
from test_helpers import fixtures as fx

SCREENER_2 = "co-7"
OVERRIDER = "dir-9"


def _world_with_flagged_second_intake():
    """A CONFIRMED × CLEARED appointment, then a second intake form for the same
    guest declaring PREGNANCY_FIRST_TRIMESTER, submitted but not yet screened."""
    world = fx.world_with_confirmed_appointment()
    guest = world.fetch_guest()
    guest_headers = world.guest_headers
    second = validate_success(api_client.create_intake_form(
        world.guest_id,
        f.intake_form_payload(guest["version"],
                              condition_codes=["PREGNANCY_FIRST_TRIMESTER"],
                              medications=["LABETALOL"]),
        guest_headers), 201)
    validate_success(api_client.sign_consent(
        second["id"], f.consent_payload(), guest_headers))
    validate_success(api_client.submit_intake_form(second["id"], {}, guest_headers))
    fx.set_clock(CANON_START_AT)
    return world, second


def test_flagged_screening_blocks_clearance_while_schedule_status_stays_confirmed():
    """A different entity's transition moves only the clearance dimension.

    PRD §2.10: "They advance independently: an appointment may legitimately sit
    at `CONFIRMED` with `BLOCKED` clearance, at `CONFIRMED` with `CLEARED`
    clearance, or at `CHECKED_IN` with `BLOCKED` clearance, and it is the **pair**
    that decides which transitions are legal."

    PRD §3.6: "A `SpaCoordinator` checks a guest in only from `CONFIRMED`, and
    only while `clearance_status` is `CLEARED`; a blocked appointment is refused
    with `ERR_APPOINTMENT_NOT_CLEARED` even though its `schedule_status` is
    perfectly valid, which is the whole point of the parallel dimension."

    Design: Difficulty/non_linear_state_machine/appointment_clearance_dimension_blocks_and_reclears_independently
    """
    world, second = _world_with_flagged_second_intake()
    appointment_id = world.appointments["a"]["id"]

    screened = validate_success(api_client.screen_intake_form(
        second["id"], {}, make_compliance_headers(SCREENER_2)))
    assert screened["status"] == "SCREENED_FLAGGED"
    assert screened["flagged_condition_codes"] == ["PREGNANCY_FIRST_TRIMESTER"]

    first_form = validate_success(api_client.get_intake_form(
        world.intake["id"], world.guest_headers))
    assert first_form["status"] == "SUPERSEDED", (
        "the guest's previous authoritative form transitions to SUPERSEDED")
    guest = world.fetch_guest()
    assert guest["authoritative_intake_form_id"] == second["id"]

    appointment = world.fetch_appointment(appointment_id)
    assert_state_pair(appointment, "CONFIRMED", "BLOCKED", "INTAKE_FLAGGED")

    response = api_client.check_in_appointment(appointment_id, {}, fx.COORDINATOR)
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_NOT_CLEARED.value, 409)

    assert_list_count(api_client.list_settlements(appointment_id, fx.DIRECTOR), 0,
                      "settlement rows after a refused check-in")
    assert world.fetch_guest()["folio_balance_cents"] == 0, (
        "neither the settlement row nor the posting is written")


def test_override_reclears_the_appointment_and_check_in_then_proceeds():
    """The clearance dimension returns to CLEARED with the schedule untouched.

    PRD §3.4: "The first is a `SpaDirector` override, which moves the form
    `SCREENED_FLAGGED → OVERRIDDEN`, requires an `override_reason` in the payload,
    records `overridden_by_user_id`, and is refused with
    `ERR_SEGREGATION_OF_DUTIES` when the overriding user is the same user recorded
    as `screened_by_user_id`."

    PRD §2.10: "`clearance_block_reason` is null whenever `clearance_status` is
    `PENDING` or `CLEARED`."

    Design: Difficulty/non_linear_state_machine/appointment_clearance_dimension_blocks_and_reclears_independently
    """
    world, second = _world_with_flagged_second_intake()
    appointment_id = world.appointments["a"]["id"]
    validate_success(api_client.screen_intake_form(
        second["id"], {}, make_compliance_headers(SCREENER_2)))

    overridden = validate_success(api_client.override_intake_form(
        second["id"], f.override_payload("OB clearance letter on file"),
        make_director_headers(OVERRIDER)))
    assert overridden["status"] == "OVERRIDDEN"
    assert overridden["overridden_by_user_id"] == OVERRIDER, (
        f"{OVERRIDER} differs from screened_by_user_id {SCREENER_2}, so the "
        "segregation-of-duties rule is satisfied")

    appointment = world.fetch_appointment(appointment_id)
    assert_state_pair(appointment, "CONFIRMED", "CLEARED", None)

    checked_in = validate_success(
        api_client.check_in_appointment(appointment_id, {}, fx.COORDINATOR))
    assert checked_in["schedule_status"] == "CHECKED_IN"
    row = assert_list_count(
        api_client.list_settlements(appointment_id, fx.DIRECTOR), 1,
        "settlement rows")[0]
    assert row["variant"] == "PROVISIONAL"
    assert row["folio_total_cents"] == 50504
    assert world.fetch_guest()["folio_balance_cents"] == 50504


# ---------------------------------------------------------------------------
# The cyclic licence machine
# ---------------------------------------------------------------------------

def _pending_license():
    """A PENDING_REVIEW licence submitted by co-1, on the startup clock."""
    therapist = fx.create_therapist(
        full_name="Kai Mahelona", commission_tier="MASTER",
        base_hourly_cost_cents=6000)
    return fx.submit_license(
        therapist["id"], submit_user="co-1", license_number="HI-LMT-7781",
        issued_on="2023-01-01", expires_on="2027-06-30",
        current_period_start_on="2024-01-01", ce_hours_required=0)


def test_reviewing_a_rejected_license_is_refused_on_state_before_any_sod_check():
    """State legality outranks segregation of duties on the ladder.

    PRD §3.3: "reviewing a licence that is not `PENDING_REVIEW` is refused with
    `ERR_INVALID_LICENSE_STATE`"

    PRD §3.3: "A `REJECTED` decision moves the licence
    `PENDING_REVIEW → REJECTED`, records `reviewed_by_user_id` and the supplied
    `review_note` (null when omitted), leaves `verified_at` null and leaves
    `credited_ce_hours` untouched."

    Design: Difficulty/non_linear_state_machine/license_reject_resubmit_verify_cycle_swaps_sod_counterparty
    """
    license_row = _pending_license()
    rejected = validate_success(api_client.review_license(
        license_row["id"], f.review_payload("REJECTED", "state seal illegible"),
        make_compliance_headers("co-2")))
    assert rejected["verification_status"] == "REJECTED"
    assert rejected["reviewed_by_user_id"] == "co-2"
    assert rejected["review_note"] == "state seal illegible"
    assert rejected["verified_at"] is None

    response = api_client.review_license(
        license_row["id"], f.review_payload("VERIFIED"),
        make_compliance_headers("co-2"))
    validate_error(response, ApiErrorId.ERR_INVALID_LICENSE_STATE.value, 409)


def test_resubmission_inverts_the_segregation_of_duties_counterparty():
    """Walking the loop swaps which officer may review the licence.

    PRD §3.3: "Resubmission writes `submitted_by_user_id` with the resubmitter's
    `X-User-ID`, which re-arms the segregation-of-duties check for the next
    review, and resets `reviewed_by_user_id`, `review_note` and `verified_at` all
    back to null."

    PRD §2.7 rung 11: "**Segregation of duties** — the licence reviewer differs
    from `submitted_by_user_id`, and the intake overrider differs from
    `screened_by_user_id`."

    Design: Difficulty/non_linear_state_machine/license_reject_resubmit_verify_cycle_swaps_sod_counterparty
    """
    license_row = _pending_license()
    license_id = license_row["id"]
    validate_success(api_client.review_license(
        license_id, f.review_payload("REJECTED", "state seal illegible"),
        make_compliance_headers("co-2")))

    resubmitted = validate_success(api_client.resubmit_license(
        license_id,
        {"license_number": "HI-LMT-7781R", "expires_on": "2027-06-30"},
        make_compliance_headers("co-2")))
    assert resubmitted["verification_status"] == "PENDING_REVIEW"
    assert resubmitted["license_number"] == "HI-LMT-7781R"
    assert resubmitted["submitted_by_user_id"] == "co-2"
    assert resubmitted["reviewed_by_user_id"] is None
    assert resubmitted["verified_at"] is None

    barred = api_client.review_license(
        license_id, f.review_payload("VERIFIED"), make_compliance_headers("co-2"))
    validate_error(barred, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)

    verified = validate_success(api_client.review_license(
        license_id, f.review_payload("VERIFIED"),
        make_compliance_headers("co-1")))
    assert verified["verification_status"] == "VERIFIED", (
        "co-1 was barred before the loop and is the legal reviewer after it")
    assert verified["reviewed_by_user_id"] == "co-1"
    assert_same_instant(verified["verified_at"], CLOCK_STARTUP_DEFAULT,
                        "verified_at")
    assert float(verified["credited_ce_hours"]) == 0.0
