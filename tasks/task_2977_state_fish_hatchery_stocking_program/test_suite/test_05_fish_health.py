"""
Fish health: sampling, treatment, retesting and certification.

Covers the segregation-of-duties gate on signing a certificate, the terminality
of a signed certificate, the strict lapse of a certificate on a clock advance,
the drug-withdrawal window as a gate on retesting, the narrow
pathogen-not-treatable carve-out, the bounded treat-and-retest loop and its
escalation on the third positive, and the five-level unwind a reportable finding
sets off.
"""

from test_helpers import (
    VET_ANNA_HEADERS,
    VET_BRUNO_HEADERS,
    VET_CARA_HEADERS,
    assert_appropriation_ledger,
    assert_instant_equals,
    assert_integer_equals,
    assert_is_none,
    assert_number_equals,
    validate_error,
    validate_success,
)
from test_helpers import api_errors as err
from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import VET_ANNA_USER_ID, VET_BRUNO_USER_ID

# A syntactically valid UUID that no inspection ever holds.
UNKNOWN_INSPECTION_ID = "22222222-2222-4222-8222-222222222222"

CERTIFIED_AT = f.instant(2026, 8, 25)
CERTIFICATE_EXPIRES_AT = f.instant(2026, 9, 24)


def test_certifying_veterinarian_cannot_be_the_sampler(api):
    """
    The veterinarian who drew the sample may not sign its certificate, and the
    refusal is the segregation-of-duties one rather than a state complaint.

    PRD 3.5: "A `FishHealthVeterinarian` signs the certificate on an inspection
    in `PASSED` status, and the acting `X-User-ID` must differ from the
    inspection's `sampled_by_user_id`; the sampling veterinarian signing their own
    certificate is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/certifying_veterinarian_cannot_be_the_sampler
    """
    ctx = fx.passed_inspection(api)
    inspection = ctx["inspection"]
    assert inspection["status"] == k.INSPECTION_PASSED
    assert inspection["sampled_by_user_id"] == VET_ANNA_USER_ID

    response = api.certify_inspection(inspection["id"], VET_ANNA_HEADERS)

    validate_error(response, err.ERR_SEGREGATION_OF_DUTIES, 403)

    unsigned = fx.read_inspection(api, inspection["id"])
    assert unsigned["status"] == k.INSPECTION_PASSED
    assert_is_none(unsigned["certified_by_user_id"], "certified_by_user_id")
    assert_is_none(unsigned["certified_at"], "certified_at")

    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert lot["health_status"] == k.HEALTH_UNDER_INSPECTION
    assert_is_none(lot["certificate_expires_at"], "certificate_expires_at")


def test_a_second_veterinarian_certification_sets_the_lot_certificate(api):
    """
    A second veterinarian's signature turns a passed inspection into a
    certificate, stamps it with the logical clock, dates its expiry thirty days
    out, and pushes both onto the lot while preserving the sampler on the record.

    PRD 3.5: "On success the inspection moves to `CERTIFIED`, records the signer
    as `certified_by_user_id`, stamps `certified_at` with the logical clock, and
    computes `certificate_expires_at` as `certified_at` advanced by 30 days. The
    certificate is then pushed onto the lot: the lot's `health_status` becomes
    `CERTIFIED`, the lot's own `certificate_expires_at` is set to the
    certificate's expiry, and the lot's `version` advances."

    Design: Corner/rbac/a_second_veterinarian_certification_sets_the_lot_certificate
    """
    ctx = fx.passed_inspection(api)

    certificate = validate_success(
        api.certify_inspection(ctx["inspection"]["id"], VET_BRUNO_HEADERS), 200
    )

    assert certificate["status"] == k.INSPECTION_CERTIFIED
    assert certificate["certified_by_user_id"] == VET_BRUNO_USER_ID
    assert certificate["sampled_by_user_id"] == VET_ANNA_USER_ID
    assert_instant_equals(certificate["certified_at"], CERTIFIED_AT, "certified_at")
    assert_instant_equals(
        certificate["certificate_expires_at"],
        CERTIFICATE_EXPIRES_AT,
        "certificate_expires_at",
    )

    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert lot["health_status"] == k.HEALTH_CERTIFIED
    assert_instant_equals(
        lot["certificate_expires_at"], CERTIFICATE_EXPIRES_AT, "certificate_expires_at"
    )


def test_certify_twice_is_refused_on_the_second_call(api):
    """
    `CERTIFIED` is terminal, so a second signature — even from a third
    veterinarian with no other relationship to the lot — is refused, and neither
    the signer nor the expiry already on record moves.

    PRD 3.5: "Both `CERTIFIED` and `FAILED_REPORTABLE` are terminal statuses for
    an inspection."

    Design: Corner/state_machines/certify_twice_is_refused_on_the_second_call
    """
    ctx = fx.certified_yearling_lot(api)
    inspection = ctx["inspection"]
    assert inspection["status"] == k.INSPECTION_CERTIFIED

    response = api.certify_inspection(inspection["id"], VET_CARA_HEADERS)

    validate_error(response, err.ERR_INVALID_STATE, 409)

    unchanged = fx.read_inspection(api, inspection["id"])
    assert unchanged["status"] == k.INSPECTION_CERTIFIED
    assert unchanged["certified_by_user_id"] == VET_BRUNO_USER_ID
    assert_instant_equals(unchanged["certified_at"], CERTIFIED_AT, "certified_at")
    assert_instant_equals(
        unchanged["certificate_expires_at"],
        CERTIFICATE_EXPIRES_AT,
        "certificate_expires_at",
    )

    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert lot["health_status"] == k.HEALTH_CERTIFIED
    assert_instant_equals(
        lot["certificate_expires_at"], CERTIFICATE_EXPIRES_AT, "certificate_expires_at"
    )


def test_lot_certificate_lapses_to_unscreened_when_the_clock_passes_expiry(api):
    """
    A certificate lapses only once the clock has moved strictly past its expiry,
    and the lapse retains the expiry instant on the lot while leaving the
    inspection standing as the historical document.

    PRD 3.5: "On a clock advance, any lot whose `health_status` is `CERTIFIED` and
    whose `certificate_expires_at` the clock has moved strictly past falls back to
    `health_status` `UNSCREENED`. Crucially, the lapsed expiry instant is
    **retained** on the lot rather than cleared — that retained value is exactly
    what lets a load attempt distinguish a lot whose certificate ran out, which
    answers `ERR_HEALTH_CERTIFICATE_EXPIRED`, from a lot that was never certified
    at all and carries a null `certificate_expires_at`, which answers
    `ERR_LOT_NOT_CERTIFIED`. The inspection record itself stays `CERTIFIED` as the
    historical document of what was signed and when."

    Design: Corner/state_machines/lot_certificate_lapses_to_unscreened_when_the_clock_passes_expiry
    """
    ctx = fx.certified_yearling_lot(api)
    lot_id = ctx["lot"]["id"]

    fx.set_clock(api, CERTIFICATE_EXPIRES_AT)
    on_the_bound = fx.read_lot(api, ctx["hatchery"], lot_id)
    assert on_the_bound["health_status"] == k.HEALTH_CERTIFIED
    assert_instant_equals(
        on_the_bound["certificate_expires_at"],
        CERTIFICATE_EXPIRES_AT,
        "certificate_expires_at",
    )

    fx.set_clock(api, f.shift_instant(CERTIFICATE_EXPIRES_AT, seconds=1))

    lapsed = fx.read_lot(api, ctx["hatchery"], lot_id)
    assert lapsed["health_status"] == k.HEALTH_UNSCREENED
    assert_instant_equals(
        lapsed["certificate_expires_at"],
        CERTIFICATE_EXPIRES_AT,
        "certificate_expires_at",
    )

    historical = fx.read_inspection(api, ctx["inspection"]["id"])
    assert historical["status"] == k.INSPECTION_CERTIFIED
    assert historical["certified_by_user_id"] == VET_BRUNO_USER_ID


def test_unknown_inspection_id_returns_inspection_not_found(api):
    """
    An inspection id that resolves to nothing is a 404 from the inspections
    collection, decided before any rule that would need to read the row's sampler.

    PRD 2.11: "An identifier in the URL path is resolved against the collection
    the path addresses, and a value that resolves to nothing produces that
    collection's own 404: `ERR_HATCHERY_NOT_FOUND`, `ERR_WATER_NOT_FOUND`,
    `ERR_BROOD_STOCK_NOT_FOUND`, `ERR_SPAWN_EVENT_NOT_FOUND`,
    `ERR_LOT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
    `ERR_PLAN_NOT_FOUND`, `ERR_TRANSPORT_UNIT_NOT_FOUND` or
    `ERR_EVENT_NOT_FOUND`."

    Design: Corner/errors/unknown_inspection_id_returns_inspection_not_found
    """
    response = api.certify_inspection(UNKNOWN_INSPECTION_ID, VET_BRUNO_HEADERS)

    validate_error(response, err.ERR_INSPECTION_NOT_FOUND, 404)


def test_loading_a_never_certified_lot_reports_lot_not_certified(api):
    """
    The certificate is a gate at loading, not at scheduling: a trip books happily
    against an unscreened lot, and the load is refused for want of a certificate
    rather than for an expired one.

    PRD 3.8: "a lot whose `health_status` is `UNDER_INSPECTION` or `RESTRICTED`,
    or `UNSCREENED` with a null `certificate_expires_at` because it was never
    certified, answers `ERR_LOT_NOT_CERTIFIED` (HTTP 422)"

    Design: Corner/errors/loading_a_never_certified_lot_reports_lot_not_certified
    """
    ctx = fx.scheduled_trip(api, certify_lot=False)
    event, unit = ctx["event"], ctx["unit"]
    assert event["status"] == k.EVENT_SCHEDULED

    unscreened = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert unscreened["health_status"] == k.HEALTH_UNSCREENED
    assert_is_none(unscreened["certificate_expires_at"], "certificate_expires_at")

    response = api.load_stocking_event(
        event["id"],
        f.load_payload(f.instant(2026, 9, 1, 9), 12.0),
        ctx["manager"],
    )

    validate_error(response, err.ERR_LOT_NOT_CERTIFIED, 422)

    still_scheduled = fx.read_event(api, event["id"])
    assert still_scheduled["status"] == k.EVENT_SCHEDULED
    assert_is_none(still_scheduled["max_fish_allowed"], "max_fish_allowed")

    idle = fx.read_unit(api, unit["id"])
    assert idle["status"] == k.UNIT_AVAILABLE
    assert_is_none(idle["current_event_id"], "current_event_id")


def test_retest_inside_the_drug_withdrawal_window_reports_withdrawal_period_active(api):
    """
    A clean retest is still refused while the drug-withdrawal window stands open,
    and the very same call succeeds once the clock reaches the clearing instant.

    PRD 3.5: "A `NEGATIVE` retest moves the inspection to `PASSED`, but only once
    the drug-withdrawal window has cleared: if the clock is still before
    `withdrawal_clears_at`, the retest is refused with
    `ERR_WITHDRAWAL_PERIOD_ACTIVE`."

    Design: Corner/errors/retest_inside_the_drug_withdrawal_window_reports_withdrawal_period_active
    """
    ctx = fx.sampled_lot(api)
    inspection_id = ctx["inspection"]["id"]

    treatable = fx.record_result(
        api, inspection_id, k.RESULT_POSITIVE_TREATABLE, k.PATHOGEN_IPNV
    )
    assert treatable["status"] == k.INSPECTION_FAILED_TREATABLE

    treated = fx.record_treatment(
        api,
        inspection_id,
        treatment_code=k.TREATMENT_CODE_FORMALIN,
        withdrawal_days=21,
        treatment_completed_at=f.instant(2026, 8, 25),
    )
    assert treated["status"] == k.INSPECTION_RETEST_DUE
    assert_integer_equals(treated["retest_count"], 1, "retest_count")
    assert_instant_equals(
        treated["withdrawal_clears_at"], f.instant(2026, 9, 15), "withdrawal_clears_at"
    )

    fx.set_clock(api, f.instant(2026, 9, 1, 8))
    response = api.record_result(
        inspection_id, f.record_result_payload(k.RESULT_NEGATIVE), VET_ANNA_HEADERS
    )

    validate_error(response, err.ERR_WITHDRAWAL_PERIOD_ACTIVE, 422)

    held = fx.read_inspection(api, inspection_id)
    assert held["status"] == k.INSPECTION_RETEST_DUE
    assert_integer_equals(held["retest_count"], 1, "retest_count")
    assert_instant_equals(
        held["withdrawal_clears_at"], f.instant(2026, 9, 15), "withdrawal_clears_at"
    )
    assert (
        fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])["health_status"]
        == k.HEALTH_RESTRICTED
    )

    fx.set_clock(api, f.instant(2026, 9, 15))
    cleared = validate_success(
        api.record_result(
            inspection_id, f.record_result_payload(k.RESULT_NEGATIVE), VET_ANNA_HEADERS
        ),
        200,
    )
    assert cleared["status"] == k.INSPECTION_PASSED


def test_treating_a_reportable_finding_reports_pathogen_not_treatable(api):
    """
    A reportable pathogen may not be treated out. The refusal is the specific
    422 rather than the generic state 409 the missing edge would otherwise
    produce, and that carve-out is narrow: a treatment against an inspection still
    awaiting its first result is a plain state complaint.

    PRD 3.5: "Attempting to record a treatment against an inspection that has
    reached `FAILED_REPORTABLE` answers `ERR_PATHOGEN_NOT_TREATABLE` (HTTP 422) —
    a reportable pathogen may not be treated out — while every other illegal
    originating status answers `ERR_INVALID_STATE`."

    Design: Corner/errors/treating_a_reportable_finding_reports_pathogen_not_treatable
    """
    ctx = fx.sampled_lot(api)
    inspection_id = ctx["inspection"]["id"]
    treatment = f.record_treatment_payload(
        treatment_code=k.TREATMENT_CODE_FORMALIN,
        withdrawal_days=21,
        treatment_completed_at=f.instant(2026, 8, 25),
    )

    too_early = api.record_treatment(inspection_id, treatment, VET_ANNA_HEADERS)
    validate_error(too_early, err.ERR_INVALID_STATE, 409)

    reportable = fx.record_result(
        api, inspection_id, k.RESULT_POSITIVE_REPORTABLE, k.PATHOGEN_WHIRLING_DISEASE
    )
    assert reportable["status"] == k.INSPECTION_FAILED_REPORTABLE

    response = api.record_treatment(inspection_id, treatment, VET_ANNA_HEADERS)

    validate_error(response, err.ERR_PATHOGEN_NOT_TREATABLE, 422)

    untreated = fx.read_inspection(api, inspection_id)
    assert untreated["status"] == k.INSPECTION_FAILED_REPORTABLE
    assert_is_none(untreated["treatment_code"], "treatment_code")
    assert_integer_equals(untreated["retest_count"], 0, "retest_count")

    assert (
        fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])["health_status"]
        == k.HEALTH_QUARANTINED
    )


def _cycle_once(api, inspection_id, completed_at):
    """
    Run one turn of the treat-and-retest loop: a treatable finding, then the
    therapeutant that closes it and opens a five-day withdrawal window.
    """
    finding = fx.record_result(
        api, inspection_id, k.RESULT_POSITIVE_TREATABLE, k.PATHOGEN_FLAVO_PSY
    )
    treated = fx.record_treatment(
        api,
        inspection_id,
        treatment_code=k.TREATMENT_CODE_FORMALIN,
        withdrawal_days=5,
        treatment_completed_at=completed_at,
    )
    return finding, treated


def test_the_treat_and_retest_loop_may_run_twice_without_escalating(api):
    """
    The cycle is a bounded loop, not a one-way street: an identical treatable
    finding may drive the inspection back to `FAILED_TREATABLE` while the retest
    counter is still below its ceiling, and it is the counter — not the payload —
    that rises each time.

    PRD 3.5: "A `POSITIVE_TREATABLE` retest, while `retest_count` is still below
    the ceiling of two, cycles the inspection back to `FAILED_TREATABLE` and
    drives the lot's `health_status` back to `RESTRICTED` — this is the loop, and
    it may run twice."

    Design: Difficulty/non_linear_state_machine/inspection_retest_cycle_escalates_on_third_positive
    """
    ctx = fx.sampled_lot(api)
    inspection_id, lot_id = ctx["inspection"]["id"], ctx["lot"]["id"]

    first_finding, first_treatment = _cycle_once(api, inspection_id, f.instant(2026, 8, 25))
    assert first_finding["status"] == k.INSPECTION_FAILED_TREATABLE
    assert first_finding["escalated_from_retests"] is False
    assert first_treatment["status"] == k.INSPECTION_RETEST_DUE
    assert_integer_equals(first_treatment["retest_count"], 1, "retest_count")
    assert_instant_equals(
        first_treatment["withdrawal_clears_at"],
        f.instant(2026, 8, 30),
        "withdrawal_clears_at",
    )

    fx.set_clock(api, f.instant(2026, 8, 31))
    second_finding, second_treatment = _cycle_once(
        api, inspection_id, f.instant(2026, 8, 31)
    )

    assert second_finding["status"] == k.INSPECTION_FAILED_TREATABLE
    assert second_finding["escalated_from_retests"] is False
    assert_integer_equals(second_finding["retest_count"], 1, "retest_count")
    assert second_finding["pathogen_code"] == k.PATHOGEN_FLAVO_PSY

    restricted = fx.read_lot(api, ctx["hatchery"], lot_id)
    assert restricted["health_status"] == k.HEALTH_RESTRICTED
    assert_is_none(restricted["certificate_expires_at"], "certificate_expires_at")

    assert second_treatment["status"] == k.INSPECTION_RETEST_DUE
    assert_integer_equals(second_treatment["retest_count"], 2, "retest_count")
    assert_instant_equals(
        second_treatment["withdrawal_clears_at"],
        f.instant(2026, 9, 5),
        "withdrawal_clears_at",
    )
    assert second_treatment["escalated_from_retests"] is False


def test_the_third_positive_escalates_the_inspection_and_quarantines_the_lot(api):
    """
    The third treatable finding — the identical payload that cycled twice — does
    not cycle again. It escalates to a reportable failure, flags the escalation as
    such, and quarantines the lot, while the growth dimension stays where it was.

    PRD 3.5: "a `POSITIVE_TREATABLE` retest arriving when `retest_count` has
    already reached two does **not** cycle again — the third positive escalates the
    inspection to `FAILED_REPORTABLE`, and in exactly that case the service sets
    `escalated_from_retests` to true on the inspection"

    Design: Difficulty/non_linear_state_machine/inspection_retest_cycle_escalates_on_third_positive
    """
    ctx = fx.sampled_lot(api)
    inspection_id, lot_id = ctx["inspection"]["id"], ctx["lot"]["id"]

    _cycle_once(api, inspection_id, f.instant(2026, 8, 25))
    fx.set_clock(api, f.instant(2026, 8, 31))
    _, twice_cycled = _cycle_once(api, inspection_id, f.instant(2026, 8, 31))
    assert_integer_equals(twice_cycled["retest_count"], 2, "retest_count")

    fx.set_clock(api, f.instant(2026, 9, 6))
    escalated = validate_success(
        api.record_result(
            inspection_id,
            f.record_result_payload(k.RESULT_POSITIVE_TREATABLE, k.PATHOGEN_FLAVO_PSY),
            VET_ANNA_HEADERS,
        ),
        200,
    )

    assert escalated["status"] == k.INSPECTION_FAILED_REPORTABLE
    assert escalated["escalated_from_retests"] is True
    assert_integer_equals(escalated["retest_count"], 2, "retest_count")

    quarantined = fx.read_lot(api, ctx["hatchery"], lot_id)
    assert quarantined["health_status"] == k.HEALTH_QUARANTINED
    assert_is_none(quarantined["certificate_expires_at"], "certificate_expires_at")
    assert quarantined["rearing_stage"] == k.STAGE_YEARLING


def _in_transit_trip_under_inspection(api):
    """
    A trip already `IN_TRANSIT` whose lot has just been re-sampled, so the lot is
    `UNDER_INSPECTION` and one record-result call away from quarantine.
    """
    ctx = fx.in_transit_trip(api)
    ctx["inspection"] = fx.open_inspection(
        api,
        ctx["lot"]["id"],
        VET_ANNA_HEADERS,
        inspection_type=k.INSPECTION_TYPE_ROUTINE,
        sample_size=30,
        sampled_at=f.instant(2026, 9, 1, 8),
    )
    return ctx


def test_a_reportable_finding_aborts_the_trip_and_returns_the_fish_and_the_money(api):
    """
    One laboratory result walks four links: the inspection fails reportably, the
    lot is quarantined, the in-transit trip is aborted with the quarantine reason,
    and the fish, the truck and the committed money all come back.

    PRD 3.5: "Because the lot is quarantined, every stocking event on that lot in
    `SCHEDULED` or `IN_TRANSIT` status transitions to `ABORTED`, stamping
    `aborted_at` with the logical clock, setting `abort_reason` to
    `LOT_QUARANTINED` and `released_count` to zero, returning that event's
    `fish_count` out of the lot's `reserved_count`, releasing that event's
    `transport_cost_cents` from the station's `budget_committed_cents`, and
    returning the truck to `AVAILABLE` with its `current_event_id` cleared to
    null."

    Design: Difficulty/transitive_cascade/reportable_pathogen_unwinds_the_whole_trip
    """
    ctx = _in_transit_trip_under_inspection(api)
    event, unit = ctx["event"], ctx["unit"]
    assert event["status"] == k.EVENT_IN_TRANSIT
    assert_integer_equals(event["transport_cost_cents"], 81000, "transport_cost_cents")

    reportable = validate_success(
        api.record_result(
            ctx["inspection"]["id"],
            f.record_result_payload(k.RESULT_POSITIVE_REPORTABLE, k.PATHOGEN_VHSV),
            VET_ANNA_HEADERS,
        ),
        200,
    )

    assert reportable["status"] == k.INSPECTION_FAILED_REPORTABLE
    assert reportable["escalated_from_retests"] is False

    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert lot["health_status"] == k.HEALTH_QUARANTINED
    assert_is_none(lot["certificate_expires_at"], "certificate_expires_at")
    assert_integer_equals(lot["reserved_count"], 0, "reserved_count")
    assert_integer_equals(lot["count_on_hand"], 16000, "count_on_hand")

    aborted = fx.read_event(api, event["id"])
    assert aborted["status"] == k.EVENT_ABORTED
    assert aborted["abort_reason"] == k.ABORT_REASON_QUARANTINE
    assert_instant_equals(
        aborted["aborted_at"], f.instant(2026, 9, 1, 8), "aborted_at"
    )
    assert_integer_equals(aborted["released_count"], 0, "released_count")

    returned = fx.read_unit(api, unit["id"])
    assert returned["status"] == k.UNIT_AVAILABLE
    assert_is_none(returned["current_event_id"], "current_event_id")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(
        station["budget_committed_cents"], 0, "budget_committed_cents"
    )
    assert_integer_equals(station["budget_spent_cents"], 0, "budget_spent_cents")
    assert_integer_equals(
        station["budget_available_cents"], 50000000, "budget_available_cents"
    )
    assert_appropriation_ledger(station)


def test_the_quarantine_cascade_surrenders_the_grant_and_the_waters_progress(api):
    """
    The far end of the same cascade is the demand side: the granting request falls
    back to deferred with the quarantine's own reason, the destination water gives
    up the grant it had counted, and the growth dimension of the lot is untouched
    throughout.

    PRD 3.5: "Because each of those events is aborted, its granting stocking
    request falls from `ALLOCATED` back to `DEFERRED` with `allocated_count` reset
    to zero and `deferral_reason` set to `EVENT_ABORTED`. And because each of those
    grants is surrendered, each affected water has the surrendered grant subtracted
    from its `allocated_count_ytd`, with `plan_shortfall_count` and `plan_fill_pct`
    recomputed."

    Design: Difficulty/transitive_cascade/reportable_pathogen_unwinds_the_whole_trip
    """
    ctx = _in_transit_trip_under_inspection(api)

    granted = fx.read_request(api, ctx["request"]["id"])
    assert granted["status"] == k.REQUEST_ALLOCATED
    assert_integer_equals(granted["allocated_count"], 2400, "allocated_count")

    committed = fx.read_water(api, ctx["water"]["id"])
    assert_integer_equals(committed["allocated_count_ytd"], 2400, "allocated_count_ytd")
    assert_integer_equals(committed["plan_shortfall_count"], 0, "plan_shortfall_count")
    assert_number_equals(committed["plan_fill_pct"], 120.00, 2, "plan_fill_pct")

    validate_success(
        api.record_result(
            ctx["inspection"]["id"],
            f.record_result_payload(k.RESULT_POSITIVE_REPORTABLE, k.PATHOGEN_VHSV),
            VET_ANNA_HEADERS,
        ),
        200,
    )

    deferred = fx.read_request(api, ctx["request"]["id"])
    assert deferred["status"] == k.REQUEST_DEFERRED
    assert_integer_equals(deferred["allocated_count"], 0, "allocated_count")
    assert deferred["deferral_reason"] == k.DEFERRAL_EVENT_ABORTED

    surrendered = fx.read_water(api, ctx["water"]["id"])
    assert_integer_equals(surrendered["allocated_count_ytd"], 0, "allocated_count_ytd")
    assert_integer_equals(surrendered["released_count_ytd"], 0, "released_count_ytd")
    assert_integer_equals(
        surrendered["plan_shortfall_count"], 2000, "plan_shortfall_count"
    )
    assert_number_equals(surrendered["plan_fill_pct"], 0.00, 2, "plan_fill_pct")

    assert (
        fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])["rearing_stage"]
        == k.STAGE_YEARLING
    )
