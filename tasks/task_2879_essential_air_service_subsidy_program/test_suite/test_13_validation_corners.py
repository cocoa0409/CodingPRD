"""Corner cases in the program's validation rules.

Completeness and contiguity gates, natural-key uniqueness, month sequencing,
conditional trigger fields, single-open-negotiation and cap boundaries, and the
order in which competing refusals answer.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_instant,
    assert_money,
    assert_obligation_identity,
    assert_one_decimal,
    assert_ratio,
    assert_versioned_row,
)
from test_helpers.constants import (
    AGREEMENT_ACTIVE,
    CARRIER_ACTIVE,
    CARRIER_SUSPENDED,
    COMMUNITY_ELIGIBLE,
    DEFAULT_CLOCK,
    EVAL_SELECTED,
    EVAL_UNDER_EVALUATION,
    PERIOD_OPEN,
    PERIOD_REPORTED,
    PROPOSAL_DRAFT,
    PROPOSAL_SUBMIT,
    PROPOSAL_SUBMITTED,
    RENEG_ACCEPT,
    RENEG_ACCEPTED,
    RENEG_REQUESTED,
    RENEG_WITHDRAW,
    RENEG_WITHDRAWN,
    SOLICITATION_AWARDED,
    SOLICITATION_CLOSED,
    STANDING_REINSTATE,
    STANDING_SUSPEND,
    TRIGGER_COST_INCREASE,
    TRIGGER_FUEL_INDEX,
    WITHHOLDING_PCT_SEVERE,
)
from test_helpers.test_users import (
    ADMIN,
    ADMIN_NEGOTIATOR,
    OFFICER,
    headers_empty_user_id,
    make_carrier_headers,
    make_community_rep_headers,
)


# ─── validations / preference_filing_must_rank_every_submitted_proposal_once ──

def test_incomplete_or_non_contiguous_preference_filings_are_refused(api: ApiClient):
    """An omitted proposal, a repeated rank and a skipped rank are each refused.

    "A filing that omits a submitted proposal, names one twice, skips a rank, or starts anywhere other than 1 is refused with `ERR_INVALID_PREFERENCE_RANKING`."

    Design: Corner/validations/preference_filing_must_rank_every_submitted_proposal_once
    """
    built = fx.build_two_candidate_solicitation(api, clock=DEFAULT_CLOCK)
    solicitation = built["solicitation"]
    version = solicitation["version"]
    headers = make_community_rep_headers(solicitation["community_id"])
    first = built["proposal_a"]["id"]
    second = built["proposal_b"]["id"]

    partial = api.file_preferences(
        solicitation["id"],
        f.preference_filing_payload(version, [{"proposal_id": first, "rank": 1}]),
        headers,
    )
    validate_error(partial, E.ERR_INVALID_PREFERENCE_RANKING, 422)

    duplicated = api.file_preferences(
        solicitation["id"],
        f.preference_filing_payload(
            version,
            [{"proposal_id": first, "rank": 1}, {"proposal_id": second, "rank": 1}],
        ),
        headers,
    )
    validate_error(duplicated, E.ERR_INVALID_PREFERENCE_RANKING, 422)

    gapped = api.file_preferences(
        solicitation["id"],
        f.preference_filing_payload(
            version,
            [{"proposal_id": first, "rank": 1}, {"proposal_id": second, "rank": 3}],
        ),
        headers,
    )
    validate_error(gapped, E.ERR_INVALID_PREFERENCE_RANKING, 422)

    unchanged = validate_success(api.get_solicitation(solicitation["id"], ADMIN))
    assert unchanged["preference_filing_count"] == 0
    assert_versioned_row(unchanged, version)
    rows, meta = validate_paginated(
        api.list_solicitation_preferences(solicitation["id"], ADMIN)
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_complete_contiguous_preference_filing_is_stored_as_one_filing(api: ApiClient):
    """Ranking both submitted proposals 1 and 2 is accepted and stamped as filing one.

    "An accepted filing increments the solicitation's `preference_filing_count` by 1, creates one preference row per ranking entry stamped with a `filing_sequence` equal to that new count, records `filed_by_user_id` as the acting `X-User-ID` — which is the community's own `id` — and increments the solicitation's `version` by 1."

    Design: Corner/validations/preference_filing_must_rank_every_submitted_proposal_once
    """
    built = fx.build_two_candidate_solicitation(api, clock=DEFAULT_CLOCK)
    solicitation = built["solicitation"]
    version = solicitation["version"]
    community_id = solicitation["community_id"]
    first = built["proposal_a"]["id"]
    second = built["proposal_b"]["id"]

    filed = validate_success(
        api.file_preferences(
            solicitation["id"],
            f.preference_filing_payload(version, f.ranking_entries(first, second)),
            make_community_rep_headers(community_id),
        ),
        201,
    )

    assert filed["id"] == solicitation["id"]
    assert filed["preference_filing_count"] == 1
    assert_versioned_row(filed, version + 1)

    rows, meta = validate_paginated(
        api.list_solicitation_preferences(solicitation["id"], ADMIN)
    )
    assert meta["total_count"] == 2
    assert [row["rank"] for row in rows] == [1, 2]
    assert [row["proposal_id"] for row in rows] == [first, second]
    for row in rows:
        assert row["filing_sequence"] == 1
        assert row["filed_by_user_id"] == community_id


# ─── validations / natural_keys_are_unique_per_collection ─────────────

def test_duplicate_natural_keys_are_refused_in_each_register(api: ApiClient):
    """A repeated community code, certificate number or aircraft code is refused.

    "A community `code`, a carrier `certificate_number`, an aircraft type `code` or a fuel `index_month` that duplicates an existing row is refused with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/natural_keys_are_unique_per_collection
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    community = validate_success(
        api.create_community(f.community_payload(code="HYS", name="Hays"), ADMIN), 201
    )
    carrier = validate_success(
        api.create_carrier(
            f.carrier_payload(name="Prairie Air", certificate_number="CERT-1001"), ADMIN
        ),
        201,
    )
    aircraft = validate_success(
        api.create_aircraft_type(f.aircraft_type_payload(code="B190"), ADMIN), 201
    )

    validate_error(
        api.create_community(
            f.community_payload(code="HYS", name="Hays Municipal"), ADMIN
        ),
        E.ERR_DUPLICATE_RESOURCE,
        409,
    )
    validate_error(
        api.create_carrier(
            f.carrier_payload(name="Prairie Air Two", certificate_number="CERT-1001"),
            ADMIN,
        ),
        E.ERR_DUPLICATE_RESOURCE,
        409,
    )
    validate_error(
        api.create_aircraft_type(
            f.aircraft_type_payload(code="B190", name="Beech 1900D"), ADMIN
        ),
        E.ERR_DUPLICATE_RESOURCE,
        409,
    )

    # The original rows are untouched and no second row was stored.
    stored_community = validate_success(api.get_community(community["id"], ADMIN))
    assert stored_community["name"] == "Hays"
    stored_carrier = validate_success(api.get_carrier(carrier["id"], ADMIN))
    assert stored_carrier["name"] == "Prairie Air"
    stored_aircraft = validate_success(api.get_aircraft_type(aircraft["id"], ADMIN))
    assert stored_aircraft["code"] == "B190"
    _, meta = validate_paginated(api.list_communities(ADMIN))
    assert meta["total_count"] == 1


# ─── validations / reporting_months_are_unique_and_contiguous ─────────

def test_reopening_the_same_reporting_month_is_refused(api: ApiClient):
    """A month the agreement already has may not be opened twice.

    "Any other month is refused with `ERR_PERIOD_SEQUENCE_GAP`, and re-opening a month that the agreement already has is refused with `ERR_DUPLICATE_PERIOD`."

    Design: Corner/validations/reporting_months_are_unique_and_contiguous
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    fx.open_period(api, award.agreement_id, "2026-08")

    validate_error(
        api.create_service_period(
            f.service_period_payload(award.agreement_id, "2026-08"), ADMIN
        ),
        E.ERR_DUPLICATE_PERIOD,
        409,
    )

    rows, meta = validate_paginated(
        api.list_service_periods(ADMIN, {"agreement_id": award.agreement_id})
    )
    assert meta["total_count"] == 1
    assert [row["period_month"] for row in rows] == ["2026-08"]


def test_skipping_a_reporting_month_is_refused_then_the_next_month_opens(api: ApiClient):
    """October cannot follow August, but September opens cleanly at zero.

    "A fresh period opens with `status` `OPEN`, all six reported figures at 0, no `period_completion_factor`, and an `amendment_count` of 0."

    Design: Corner/validations/reporting_months_are_unique_and_contiguous
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    fx.open_period(api, award.agreement_id, "2026-08")

    validate_error(
        api.create_service_period(
            f.service_period_payload(award.agreement_id, "2026-10"), ADMIN
        ),
        E.ERR_PERIOD_SEQUENCE_GAP,
        409,
    )

    september = validate_success(
        api.create_service_period(
            f.service_period_payload(award.agreement_id, "2026-09"), ADMIN
        ),
        201,
    )
    assert september["period_month"] == "2026-09"
    assert september["status"] == PERIOD_OPEN
    assert september["scheduled_departures"] == 0
    assert september["completed_departures"] == 0
    assert september["cancelled_carrier_departures"] == 0
    assert september["cancelled_weather_departures"] == 0
    assert september["seats_offered"] == 0
    assert september["passengers_enplaned"] == 0
    assert september["period_completion_factor"] in (None, "")
    assert september["amendment_count"] == 0

    rows, meta = validate_paginated(
        api.list_service_periods(ADMIN, {"agreement_id": award.agreement_id})
    )
    assert meta["total_count"] == 2
    assert [row["period_month"] for row in rows] == ["2026-08", "2026-09"]


# ─── validations / renegotiation_cooling_off_window_is_inclusive_at_the_boundary ──

def _award_with_later_fuel_index(api: ApiClient):
    """An award whose rate starts on the default clock, plus a 2027-01 index."""
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    assert_instant(award.agreement["rate_effective_from"], DEFAULT_CLOCK,
                   "rate_effective_from")
    assert_ratio(award.agreement["baseline_fuel_index_usd"], 2.4000,
                 "baseline_fuel_index_usd")
    fx.publish_fuel_index(api, "2027-01", 3.0000)
    return award


def test_filing_one_day_inside_the_cooling_off_window_is_refused(api: ApiClient):
    """A fuel filing 179 days after the rate took effect is still too early.

    "A rate may not be reopened during its cooling-off period: the logical clock must be at or after the agreement's `rate_effective_from` advanced by 180 days, with a filing exactly at that boundary accepted and anything earlier refused with `ERR_RENEGOTIATION_COOLING_OFF`."

    Design: Corner/validations/renegotiation_cooling_off_window_is_inclusive_at_the_boundary
    """
    award = _award_with_later_fuel_index(api)
    # 2026-08-01 advanced by 180 days is 2027-01-28, so this is one day short.
    fx.set_clock(api, "2027-01-27T00:00:00Z")

    refused = api.create_rate_renegotiation(
        f.fuel_renegotiation_payload(award.agreement_id, "2027-01", 1650000.00),
        award.carrier_headers,
    )
    validate_error(refused, E.ERR_RENEGOTIATION_COOLING_OFF, 422)

    rows, meta = validate_paginated(api.list_rate_renegotiations(ADMIN))
    assert rows == []
    assert meta["total_count"] == 0


def test_filing_exactly_on_the_cooling_off_boundary_is_admitted_and_repriced(api: ApiClient):
    """A fuel filing on day 180 is accepted and passes through four fifths of the swing.

    "`fuel_cost_delta_usd` is that per-gallon movement multiplied by the annual gallons, rounded half-up to cents, and `justified_delta_usd` is 80 percent of that annual fuel cost change, again rounded half-up to cents — the program passes through four fifths of a fuel swing, not all of it."

    Design: Corner/validations/renegotiation_cooling_off_window_is_inclusive_at_the_boundary
    """
    award = _award_with_later_fuel_index(api)
    # 12 round trips * 2 * 52 weeks * 1.5 hours == 1872.0 block hours a year.
    assert_one_decimal(award.agreement["annual_block_hours"], 1872.0,
                       "annual_block_hours")
    fx.set_clock(api, "2027-01-28T00:00:00Z")

    filed = validate_success(
        api.create_rate_renegotiation(
            f.fuel_renegotiation_payload(award.agreement_id, "2027-01", 1650000.00),
            award.carrier_headers,
        ),
        201,
    )
    assert filed["status"] == RENEG_REQUESTED
    assert filed["trigger_type"] == TRIGGER_FUEL_INDEX
    assert filed["revision_count"] == 0
    assert_ratio(filed["current_fuel_index_usd"], 3.0000,
                 "current_fuel_index_usd")
    # 1872.0 block hours * 68.0 gal/hour == 127296.00 gallons at +0.6000 a gallon.
    assert_money(filed["fuel_cost_delta_usd"], 76377.60, "fuel_cost_delta_usd")
    assert_money(filed["justified_delta_usd"], 61102.08, "justified_delta_usd")
    # The 15 percent cap of 240000.00 does not bite, so the ceiling is the sum.
    assert_money(filed["ceiling_annual_subsidy_usd"], 1661102.08,
                 "ceiling_annual_subsidy_usd")

    accepted = validate_success(
        api.renegotiation_action(
            filed["id"], f.renegotiation_action_payload(RENEG_ACCEPT), ADMIN_NEGOTIATOR
        )
    )
    assert accepted["status"] == RENEG_ACCEPTED
    # The carrier asked for less than the ceiling, so the ask is what it gets.
    assert_money(accepted["approved_annual_subsidy_usd"], 1650000.00,
                 "approved_annual_subsidy_usd")
    assert_instant(accepted["effective_at"], "2027-01-28T00:00:00Z", "effective_at")

    agreement = award.reload()
    assert_money(agreement["annual_subsidy_usd"], 1650000.00, "annual_subsidy_usd")
    assert_instant(agreement["rate_effective_from"], "2027-01-28T00:00:00Z",
                   "rate_effective_from")
    # No month is settled, so all 24 months are repriced: 50000.00 * 24 / 12.
    assert_money(agreement["total_committed_usd"], 3300000.00,
                 "total_committed_usd")
    assert_money(agreement["obligated_remaining_usd"], 3300000.00,
                 "obligated_remaining_usd")
    assert_obligation_identity(agreement)


def test_acceptance_restarts_the_cooling_off_window_from_the_new_rate_date(api: ApiClient):
    """The next filing must wait another 180 days from the repriced rate date.

    "Acceptance moves the renegotiation to the terminal `ACCEPTED` state — `REQUESTED → ACCEPTED` or `COUNTERED → ACCEPTED` — and writes `approved_annual_subsidy_usd` as the smaller of `ceiling_annual_subsidy_usd` and `requested_annual_subsidy_usd` — the carrier never gets more than it asked for, nor more than the program's ceiling — stamps `effective_at` with the logical clock reading, replaces the agreement's `annual_subsidy_usd` with the approved figure, and advances the agreement's `rate_effective_from` to that same clock reading."

    Design: Corner/validations/renegotiation_cooling_off_window_is_inclusive_at_the_boundary
    """
    award = _award_with_later_fuel_index(api)
    fx.set_clock(api, "2027-01-28T00:00:00Z")
    filed = fx.file_fuel_renegotiation(api, award, "2027-01", 1650000.00)
    fx.set_clock(api, "2027-01-28T00:00:00Z")
    validate_success(
        api.renegotiation_action(
            filed["id"], f.renegotiation_action_payload(RENEG_ACCEPT), ADMIN_NEGOTIATOR
        )
    )

    # 2027-01-28 advanced by 180 days is 2027-07-27.
    fx.set_clock(api, "2027-07-26T00:00:00Z")
    too_early = api.create_rate_renegotiation(
        f.cost_renegotiation_payload(award.agreement_id, 0.0500, 1700000.00),
        award.carrier_headers,
    )
    validate_error(too_early, E.ERR_RENEGOTIATION_COOLING_OFF, 422)

    fx.set_clock(api, "2027-07-27T00:00:00Z")
    second = validate_success(
        api.create_rate_renegotiation(
            f.cost_renegotiation_payload(award.agreement_id, 0.0500, 1700000.00),
            award.carrier_headers,
        ),
        201,
    )
    assert second["status"] == RENEG_REQUESTED
    assert second["trigger_type"] == TRIGGER_COST_INCREASE
    assert second["current_fuel_index_usd"] in (None, "")
    assert second["fuel_cost_delta_usd"] in (None, "")
    # 5 percent of the 1650000.00 now in force.
    assert_money(second["justified_delta_usd"], 82500.00, "justified_delta_usd")
    assert_money(second["ceiling_annual_subsidy_usd"], 1732500.00,
                 "ceiling_annual_subsidy_usd")


# ─── validations / renegotiation_trigger_fields_are_conditionally_required ──

def test_trigger_type_and_its_companion_field_must_agree(api: ApiClient):
    """Omitting or duplicating the trigger-specific field is refused either way.

    "Exactly one trigger-specific field accompanies it: a `FUEL_INDEX` request must carry `fuel_index_month` and must omit `documented_cost_increase_pct`, while a `COST_INCREASE` request must carry `documented_cost_increase_pct` — a non-negative fraction of the current annual rate carried to four decimal places — and must omit `fuel_index_month`."

    Design: Corner/validations/renegotiation_trigger_fields_are_conditionally_required
    """
    award = _award_with_later_fuel_index(api)
    fx.set_clock(api, "2027-02-01T00:00:00Z")
    headers = award.carrier_headers

    without_month = f.fuel_renegotiation_payload(
        award.agreement_id, "2027-01", 1700000.00
    )
    without_month.pop("fuel_index_month")
    missing_month = api.create_rate_renegotiation(without_month, headers)
    validate_error(missing_month, E.ERR_MISSING_FUEL_INDEX, 422)

    fuel_with_cost = api.create_rate_renegotiation(
        f.fuel_renegotiation_payload(
            award.agreement_id, "2027-01", 1700000.00,
            documented_cost_increase_pct=0.0500,
        ),
        headers,
    )
    validate_error(fuel_with_cost, E.ERR_MISSING_FUEL_INDEX, 422)

    without_pct = f.cost_renegotiation_payload(
        award.agreement_id, 0.0500, 1700000.00
    )
    without_pct.pop("documented_cost_increase_pct")
    missing_pct = api.create_rate_renegotiation(without_pct, headers)
    validate_error(missing_pct, E.ERR_MISSING_FUEL_INDEX, 422)

    cost_with_month = api.create_rate_renegotiation(
        f.cost_renegotiation_payload(
            award.agreement_id, 0.0500, 1700000.00, fuel_index_month="2027-01"
        ),
        headers,
    )
    validate_error(cost_with_month, E.ERR_MISSING_FUEL_INDEX, 422)

    rows, meta = validate_paginated(api.list_rate_renegotiations(ADMIN))
    assert rows == []
    assert meta["total_count"] == 0


def test_fuel_filing_naming_an_unpublished_month_is_refused(api: ApiClient):
    """A coherent fuel filing still fails when that month has no published index.

    "Supplying the wrong field, omitting the required one, or naming a month for which no fuel index has been published is refused with `ERR_MISSING_FUEL_INDEX`."

    Design: Corner/validations/renegotiation_trigger_fields_are_conditionally_required
    """
    award = _award_with_later_fuel_index(api)
    fx.set_clock(api, "2027-02-01T00:00:00Z")

    refused = api.create_rate_renegotiation(
        f.fuel_renegotiation_payload(award.agreement_id, "2026-12", 1700000.00),
        award.carrier_headers,
    )
    validate_error(refused, E.ERR_MISSING_FUEL_INDEX, 422)

    rows, meta = validate_paginated(api.list_rate_renegotiations(ADMIN))
    assert rows == []
    assert meta["total_count"] == 0
    indices, _ = validate_paginated(api.list_fuel_indices(ADMIN))
    assert [row["index_month"] for row in indices] == ["2026-08", "2027-01"]


# ─── validations / only_one_renegotiation_may_be_open_per_agreement ────

def _award_ready_to_renegotiate(api: ApiClient):
    """An award whose cooling-off period has already elapsed."""
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    fx.set_clock(api, "2027-02-01T00:00:00Z")
    return award


def test_second_filing_while_one_is_requested_is_refused(api: ApiClient):
    """A carrier may not stack a second renegotiation on a live one.

    "An agreement may carry only one live negotiation: if it already has a renegotiation whose `status` is `REQUESTED` or `COUNTERED`, the new filing is refused with `ERR_RENEGOTIATION_ALREADY_OPEN`."

    Design: Corner/validations/only_one_renegotiation_may_be_open_per_agreement
    """
    award = _award_ready_to_renegotiate(api)
    first = validate_success(
        api.create_rate_renegotiation(
            f.cost_renegotiation_payload(award.agreement_id, 0.0800, 1750000.00),
            award.carrier_headers,
        ),
        201,
    )
    assert first["status"] == RENEG_REQUESTED
    # 8 percent of 1600000.00 is 128000.00, under the 15 percent cap of 240000.00.
    assert_money(first["justified_delta_usd"], 128000.00, "justified_delta_usd")
    assert_money(first["ceiling_annual_subsidy_usd"], 1728000.00,
                 "ceiling_annual_subsidy_usd")

    second = api.create_rate_renegotiation(
        f.cost_renegotiation_payload(award.agreement_id, 0.0600, 1700000.00),
        award.carrier_headers,
    )
    validate_error(second, E.ERR_RENEGOTIATION_ALREADY_OPEN, 409)

    rows, meta = validate_paginated(
        api.list_rate_renegotiations(ADMIN, {"agreement_id": award.agreement_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["status"] == RENEG_REQUESTED
    assert_money(rows[0]["ceiling_annual_subsidy_usd"], 1728000.00,
                 "ceiling_annual_subsidy_usd")


def test_withdrawing_the_open_renegotiation_frees_the_agreement(api: ApiClient):
    """Once the live filing is withdrawn the carrier may file again.

    "A `ProgramAdmin` may **reject** a renegotiation from either `REQUESTED` or `COUNTERED`, moving it to `REJECTED`, and the `Carrier` may **withdraw** it from either of the same two states, moving it to `WITHDRAWN`; both are terminal and neither touches the agreement."

    Design: Corner/validations/only_one_renegotiation_may_be_open_per_agreement
    """
    award = _award_ready_to_renegotiate(api)
    first = fx.file_cost_renegotiation(api, award, 0.0800, 1750000.00)

    withdrawn = validate_success(
        api.renegotiation_action(
            first["id"],
            f.renegotiation_action_payload(RENEG_WITHDRAW),
            award.carrier_headers,
        )
    )
    assert withdrawn["status"] == RENEG_WITHDRAWN
    assert withdrawn["approved_annual_subsidy_usd"] in (None, "")
    assert withdrawn["effective_at"] in (None, "")

    refiled = validate_success(
        api.create_rate_renegotiation(
            f.cost_renegotiation_payload(award.agreement_id, 0.0800, 1750000.00),
            award.carrier_headers,
        ),
        201,
    )
    assert refiled["status"] == RENEG_REQUESTED
    assert_money(refiled["ceiling_annual_subsidy_usd"], 1728000.00,
                 "ceiling_annual_subsidy_usd")

    # Neither the withdrawal nor the refiling touched the money on the agreement.
    agreement = award.reload()
    assert_money(agreement["annual_subsidy_usd"], 1600000.00, "annual_subsidy_usd")
    assert_money(agreement["total_committed_usd"], 3200000.00,
                 "total_committed_usd")
    _, meta = validate_paginated(
        api.list_rate_renegotiations(ADMIN, {"agreement_id": award.agreement_id})
    )
    assert meta["total_count"] == 2


# ─── validations / cancellation_adjustment_cap_boundary_blocks_certification ──

def test_adjustment_one_cent_over_the_ceiling_blocks_certification(api: ApiClient):
    """Fifty-three carrier cancellations price an adjustment above the 25 percent cap.

    "The adjustment is capped for fairness: if it would exceed 25 percent of `monthly_entitlement_usd` — that ceiling itself rounded half-up to cents — certification is refused with `ERR_ADJUSTMENT_EXCEEDS_CAP` rather than producing a punitive payment."

    Design: Corner/validations/cancellation_adjustment_cap_boundary_blocks_certification
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2026-08",
        scheduled_departures=100, completed_departures=47,
        cancelled_carrier_departures=53, cancelled_weather_departures=0,
        seats_offered=1900, passengers_enplaned=700,
    )
    assert_ratio(period["period_completion_factor"], 0.4700,
                 "period_completion_factor")

    # 1333.33 * (53 - 2) * 0.5 == 33999.92 against a ceiling of 33333.33.
    refused = api.certify_service_period(period["id"], f.certify_payload(), ADMIN)
    validate_error(refused, E.ERR_ADJUSTMENT_EXCEEDS_CAP, 422)

    unchanged = validate_success(api.get_service_period(period["id"], ADMIN))
    assert unchanged["status"] == PERIOD_REPORTED
    rows, meta = validate_paginated(api.list_subsidy_payments(ADMIN))
    assert rows == []
    assert meta["total_count"] == 0


def test_amending_to_the_cap_boundary_lets_certification_through(api: ApiClient):
    """One cancellation fewer lands the adjustment exactly under the ceiling.

    "An accepted amendment increases `amendment_count` by 1, rewrites `period_completion_factor` from the new figures, and re-bases the agreement by first subtracting the period's previously stored four counts from the four cumulative counters and then adding the four new ones — never by adding alone."

    Design: Corner/validations/cancellation_adjustment_cap_boundary_blocks_certification
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2026-08",
        scheduled_departures=100, completed_departures=47,
        cancelled_carrier_departures=53, cancelled_weather_departures=0,
        seats_offered=1900, passengers_enplaned=700,
    )
    version = award.reload()["version"]

    amended = validate_success(
        api.amend_service_period(
            period["id"],
            f.amend_payload(
                version,
                scheduled_departures=100, completed_departures=48,
                cancelled_carrier_departures=52, cancelled_weather_departures=0,
                seats_offered=1900, passengers_enplaned=700,
            ),
            award.carrier_headers,
        )
    )
    assert amended["status"] == PERIOD_REPORTED
    assert amended["amendment_count"] == 1
    assert_ratio(amended["period_completion_factor"], 0.4800,
                 "period_completion_factor")
    assert_versioned_row(award.reload(), version + 1)

    fx.certify_period(api, period["id"])
    payment = fx.payment_for_period(api, period["id"])

    # 1333.33 * (52 - 2) * 0.5 == 33333.25, one boundary step under 33333.33.
    assert_money(payment["cancellation_adjustment_usd"], 33333.25,
                 "cancellation_adjustment_usd")
    assert payment["credited_departures"] == 48
    assert_money(payment["gross_subsidy_usd"], 63999.84, "gross_subsidy_usd")
    assert_ratio(payment["withholding_pct"], WITHHOLDING_PCT_SEVERE,
                 "withholding_pct")
    assert_money(payment["performance_withholding_usd"], 3066.66,
                 "performance_withholding_usd")
    assert_money(payment["net_payment_usd"], 27599.93, "net_payment_usd")


# ─── validations / selection_order_requires_a_live_candidate ──────────

def _closed_round_with_one_candidate(api: ApiClient):
    """A CLOSED solicitation carrying exactly one candidate proposal."""
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    solicitation = fx.open_solicitation(api, ref.community_id)
    proposal = fx.submitted_proposal(
        api, solicitation["id"], ref.carrier_id, ref.aircraft_type_id
    )
    solicitation = fx.close_solicitation(api, solicitation["id"])
    return ref, solicitation, proposal


def test_suspending_the_only_bidder_empties_the_candidate_set(api: ApiClient):
    """A suspended carrier's proposal leaves the order with nothing to award.

    "The **candidate set** is formed by an explicit filter: a proposal qualifies only if it belongs to this solicitation, its `submission_state` is `SUBMITTED`, its `evaluation_state` is `UNDER_EVALUATION`, and its carrier's `status` is `ACTIVE` or `PROBATION`."

    Design: Corner/validations/selection_order_requires_a_live_candidate
    """
    ref, solicitation, proposal = _closed_round_with_one_candidate(api)
    suspended = validate_success(
        api.carrier_standing_action(
            ref.carrier_id, f.carrier_standing_payload(STANDING_SUSPEND), ADMIN
        )
    )
    assert suspended["status"] == CARRIER_SUSPENDED

    refused = api.create_selection_order(
        solicitation["id"], f.selection_order_payload(), OFFICER
    )
    validate_error(refused, E.ERR_NO_ELIGIBLE_PROPOSALS, 409)

    still_closed = validate_success(api.get_solicitation(solicitation["id"], ADMIN))
    assert still_closed["status"] == SOLICITATION_CLOSED
    assert still_closed["selected_proposal_id"] in (None, "")
    assert still_closed["candidate_count_at_award"] in (None, "")

    unscored = validate_success(api.get_proposal(proposal["id"], ADMIN))
    assert unscored["submission_state"] == PROPOSAL_SUBMITTED
    assert unscored["evaluation_state"] == EVAL_UNDER_EVALUATION
    assert unscored["composite_score"] in (None, "")

    community = validate_success(api.get_community(ref.community_id, ADMIN))
    assert community["status"] == COMMUNITY_ELIGIBLE
    assert community["active_agreement_count"] == 0
    _, meta = validate_paginated(api.list_service_agreements(ADMIN))
    assert meta["total_count"] == 0


def test_reinstating_the_bidder_restores_the_candidate_and_the_award(api: ApiClient):
    """Reinstatement puts the carrier back in contention and the order books.

    "Reinstating moves a carrier `PROBATION → ACTIVE` or `SUSPENDED → ACTIVE` and resets `consecutive_watch_count` to 0; reinstating a carrier that is already `ACTIVE` is refused with `ERR_CARRIER_NOT_ACTIONABLE`."

    Design: Corner/validations/selection_order_requires_a_live_candidate
    """
    ref, solicitation, proposal = _closed_round_with_one_candidate(api)
    validate_success(
        api.carrier_standing_action(
            ref.carrier_id, f.carrier_standing_payload(STANDING_SUSPEND), ADMIN
        )
    )
    reinstated = validate_success(
        api.carrier_standing_action(
            ref.carrier_id, f.carrier_standing_payload(STANDING_REINSTATE), ADMIN
        )
    )
    assert reinstated["status"] == CARRIER_ACTIVE
    assert reinstated["consecutive_watch_count"] == 0

    agreement = validate_success(
        api.create_selection_order(
            solicitation["id"], f.selection_order_payload(), OFFICER
        ),
        201,
    )
    assert agreement["status"] == AGREEMENT_ACTIVE
    assert agreement["proposal_id"] == proposal["id"]
    assert agreement["carrier_id"] == ref.carrier_id

    awarded = validate_success(api.get_solicitation(solicitation["id"], ADMIN))
    assert awarded["status"] == SOLICITATION_AWARDED
    assert awarded["selected_proposal_id"] == proposal["id"]
    assert awarded["candidate_count_at_award"] == 1
    selected = validate_success(api.get_proposal(proposal["id"], ADMIN))
    assert selected["evaluation_state"] == EVAL_SELECTED


# ─── validations / submission_floors_read_the_community_service_minimums ──

def _open_round(api: ApiClient):
    """Reference data and an OPEN solicitation for the eligible community."""
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    return ref, fx.open_solicitation(api, ref.community_id)


def test_one_round_trip_short_of_the_community_minimum_is_refused(api: ApiClient):
    """Eleven weekly round trips miss the community's floor of twelve.

    "The offered `weekly_round_trips` must be at least the community's `min_required_weekly_round_trips`, or the submission is refused with `ERR_FREQUENCY_BELOW_MINIMUM`."

    Design: Corner/validations/submission_floors_read_the_community_service_minimums
    """
    ref, solicitation = _open_round(api)
    proposal = fx.draft_proposal(
        api, solicitation["id"], ref.carrier_id, ref.aircraft_type_id,
        weekly_round_trips=11,
    )

    refused = api.proposal_action(
        proposal["id"], f.proposal_action_payload(PROPOSAL_SUBMIT), ref.carrier_headers
    )
    validate_error(refused, E.ERR_FREQUENCY_BELOW_MINIMUM, 422)

    unchanged = validate_success(api.get_proposal(proposal["id"], ADMIN))
    assert unchanged["submission_state"] == PROPOSAL_DRAFT


def test_weekly_seat_floor_is_crossed_between_sixteen_and_seventeen_seats(api: ApiClient):
    """384 weekly seats are refused while 408 are accepted and priced.

    "Weekly one-way seats — the offered round trips multiplied by two and then by `seats_per_departure` — must be at least the community's `min_required_weekly_seats`, and `seats_per_departure` must not exceed the `seats` certificated on the named aircraft type; either failure is refused with `ERR_SEATS_BELOW_MINIMUM`."

    Design: Corner/validations/submission_floors_read_the_community_service_minimums
    """
    ref, solicitation = _open_round(api)
    # 12 * 2 * 16 == 384 weekly seats against a floor of 400.
    short = fx.draft_proposal(
        api, solicitation["id"], ref.carrier_id, ref.aircraft_type_id,
        weekly_round_trips=12, seats_per_departure=16,
    )
    refused = api.proposal_action(
        short["id"], f.proposal_action_payload(PROPOSAL_SUBMIT), ref.carrier_headers
    )
    validate_error(refused, E.ERR_SEATS_BELOW_MINIMUM, 422)
    assert validate_success(
        api.get_proposal(short["id"], ADMIN)
    )["submission_state"] == PROPOSAL_DRAFT

    # 12 * 2 * 17 == 408 weekly seats, which clears the floor.
    ample = fx.draft_proposal(
        api, solicitation["id"], ref.second_carrier_id, ref.aircraft_type_id,
        weekly_round_trips=12, seats_per_departure=17,
        annual_subsidy_request_usd=1500000.00,
    )
    submitted = validate_success(
        api.proposal_action(
            ample["id"],
            f.proposal_action_payload(PROPOSAL_SUBMIT),
            make_carrier_headers(ref.second_carrier_id),
        )
    )
    assert submitted["submission_state"] == PROPOSAL_SUBMITTED
    # 12 * 2 * 52 * 17 * 0.375 == 7956.0 projected passengers.
    assert submitted["projected_annual_passengers"] == 7956
    # 1500000.00 / 7956 == 188.5369... which rounds to 188.54.
    assert_money(submitted["subsidy_per_passenger_usd"], 188.54,
                 "subsidy_per_passenger_usd")


def test_seats_per_departure_above_the_certificated_count_is_refused(api: ApiClient):
    """Twenty seats on a nineteen-seat type is refused even with ample weekly seats.

    "Weekly one-way seats — the offered round trips multiplied by two and then by `seats_per_departure` — must be at least the community's `min_required_weekly_seats`, and `seats_per_departure` must not exceed the `seats` certificated on the named aircraft type; either failure is refused with `ERR_SEATS_BELOW_MINIMUM`."

    Design: Corner/validations/submission_floors_read_the_community_service_minimums
    """
    ref, solicitation = _open_round(api)
    assert ref.aircraft_type["seats"] == 19
    # 12 * 2 * 20 == 480 weekly seats, so only the certificated cap can bite.
    proposal = fx.draft_proposal(
        api, solicitation["id"], ref.carrier_id, ref.aircraft_type_id,
        weekly_round_trips=12, seats_per_departure=20,
    )

    refused = api.proposal_action(
        proposal["id"], f.proposal_action_payload(PROPOSAL_SUBMIT), ref.carrier_headers
    )
    validate_error(refused, E.ERR_SEATS_BELOW_MINIMUM, 422)

    unchanged = validate_success(api.get_proposal(proposal["id"], ADMIN))
    assert unchanged["submission_state"] == PROPOSAL_DRAFT


# ─── validations / higher_priority_rules_answer_first ─────────────────

def test_authentication_answers_before_existence(api: ApiClient):
    """A blank user id on a read of a missing community reports authentication.

    "When a request violates more than one rule, exactly one error is returned, and which one is fully determined by the ladder below."

    Design: Corner/validations/higher_priority_rules_answer_first
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    refused = api.get_community(NON_EXISTENT_UUID, headers_empty_user_id())
    validate_error(refused, E.ERR_UNAUTHENTICATED, 401)


def test_request_shape_answers_before_existence(api: ApiClient):
    """A malformed month on an unknown agreement reports the shape failure.

    "Checks are evaluated in this order and the first failure wins."

    Design: Corner/validations/higher_priority_rules_answer_first
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    refused = api.create_service_period(
        {"agreement_id": NON_EXISTENT_UUID, "period_month": "2026-8"}, ADMIN
    )
    validate_error(refused, E.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(api.list_service_periods(ADMIN))
    assert rows == []
    assert meta["total_count"] == 0


def test_frequency_floor_answers_before_the_seat_floor(api: ApiClient):
    """A proposal failing both service floors reports the frequency one.

    "The offered `weekly_round_trips` must be at least the community's `min_required_weekly_round_trips`, or the submission is refused with `ERR_FREQUENCY_BELOW_MINIMUM`."

    Design: Corner/validations/higher_priority_rules_answer_first
    """
    ref, solicitation = _open_round(api)
    # 11 round trips misses the frequency floor and 11 * 2 * 16 == 352 misses the
    # seat floor of 400, so both gates would fire.
    proposal = fx.draft_proposal(
        api, solicitation["id"], ref.carrier_id, ref.aircraft_type_id,
        weekly_round_trips=11, seats_per_departure=16,
    )

    refused = api.proposal_action(
        proposal["id"], f.proposal_action_payload(PROPOSAL_SUBMIT), ref.carrier_headers
    )
    validate_error(refused, E.ERR_FREQUENCY_BELOW_MINIMUM, 422)

    unchanged = validate_success(api.get_proposal(proposal["id"], ADMIN))
    assert unchanged["submission_state"] == PROPOSAL_DRAFT
