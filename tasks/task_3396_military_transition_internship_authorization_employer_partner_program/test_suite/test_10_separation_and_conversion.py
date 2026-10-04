"""The member separation sweep and the post-separation conversion record."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId, factories, fixtures, make_employer_rep_headers


def test_member_separation_sweep_voids_proposed_match(api):
    """PRD §3.1: "When a clock-set call moves the logical clock date to or past a
    member's `separation_date`, the separation sweep flips `service_status` from
    `ACTIVE_DUTY` to `SEPARATED`. Every match of that member in `PROPOSED` or
    `INSTALLATION_APPROVED` moves to `MATCH_VOIDED`; every match in `ACTIVE` moves
    to `TERMINATED_EARLY` with `termination_reason` set to `SEPARATION`. The
    affected openings' `filled_count` values are recomputed, and the member's
    `active_match_count` is recomputed to 0."

    Design: Corner/state_machines/member_separation_sweep_voids_proposed_match
    """
    ns = fixtures.setup_match(
        api, advance_to="proposed", member_overrides={"separation_date": "2026-11-15"}
    )
    sweep = fixtures.set_clock(api, "2026-11-15T00:00:00Z")
    assert sweep["members_separated"] == 1

    member = fixtures.get_member(api, ns.member["id"])
    assert member["service_status"] == "SEPARATED"
    assert member["active_match_count"] == 0
    assert fixtures.get_match(api, ns.match["id"])["match_status"] == "MATCH_VOIDED"
    assert fixtures.get_opening(api, ns.opening["id"])["filled_count"] == 0


def test_conversion_record_rules(api):
    """PRD §3.7: "An `offer_accepted` of true requires `offer_made` of true, else
    `ERR_VALIDATION`."
    PRD §3.7: "The `conversion_date` must fall on or after the member's
    `separation_date` and no later than `separation_date` plus the 90-day
    conversion window (`CONVERSION_WINDOW_DAYS`), both bounds inclusive, else
    `ERR_CONVERSION_WINDOW_EXPIRED`. At most one conversion record exists per
    match; a second filing is `ERR_CONVERSION_ALREADY_RECORDED`."
    PRD §3.7: "The record's computed `hired` flag is true exactly when both
    `offer_made` and `offer_accepted` are true, and only hired records count as
    conversions in the hiring rate."

    Member separation is 2027-01-15, so the window closes at 2027-04-15.

    Design: Corner/validations/conversion_record_rules
    """
    ns = fixtures.setup_completed_match(api)
    match_id, employer_id = ns.match["id"], ns.employer["id"]

    accepted_without_offer = api.create_conversion_record(
        factories.conversion_record_payload(match_id, "2027-02-01", offer_made=False, offer_accepted=True),
        make_employer_rep_headers(employer_id),
    )
    validate_error(accepted_without_offer, ApiErrorId.ERR_VALIDATION)

    past_window = api.create_conversion_record(
        factories.conversion_record_payload(match_id, "2027-04-16", offer_made=True, offer_accepted=True),
        make_employer_rep_headers(employer_id),
    )
    validate_error(past_window, ApiErrorId.ERR_CONVERSION_WINDOW_EXPIRED)

    on_boundary = fixtures.record_conversion(
        api, match_id, employer_id, "2027-04-15", offer_made=True, offer_accepted=True
    )
    assert on_boundary["hired"] is True, "the inclusive upper bound is accepted"

    second = api.create_conversion_record(
        factories.conversion_record_payload(match_id, "2027-02-01", offer_made=True, offer_accepted=False),
        make_employer_rep_headers(employer_id),
    )
    validate_error(second, ApiErrorId.ERR_CONVERSION_ALREADY_RECORDED)
