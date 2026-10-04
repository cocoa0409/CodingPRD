"""Boundary precision: the minimum cell size is inclusive-pass at twenty, and
a zero-size segment submission is refused while size one passes."""

from test_helpers import (
    account_with_contract,
    create_report,
    create_segment,
    get_success_data,
    ingest_category_households,
    ingest_households,
    read_contract,
    submit_segment,
    validate_error,
)
from test_helpers import ApiErrorId, factories
from test_helpers.test_users import TEST_USERS


def _report_world(api, household_count):
    """Contract with SNACKS scope plus ``household_count`` SNACKS households."""
    world = account_with_contract(
        api, name="Iota Ice", tier="TIER_PORTFOLIO", scope_category="SNACKS", scope_brands=["ACME"]
    )
    ingest_category_households(api, household_count, "b")
    return world


def test_report_with_nineteen_households_is_suppressed(api):
    """Nineteen households fall below the privacy threshold and the report is suppressed.

    PRD: "The boundary is inclusive-pass: a count of exactly twenty passes, a count of nineteen is suppressed."
    PRD: "If any cell falls below twenty households, the entire report moves to `SUPPRESSED` and its reserved credits are refunded in full — suppression never finalizes a charge."
    Design: Difficulty/boundary_precision_check/cell_size_exactly_at_minimum_passes
    """
    world = _report_world(api, 19)
    report = create_report(api, world["contract"]["id"], world["analyst_headers"])
    generated = get_success_data(api.generate_report(report["id"], world["analyst_headers"]))
    assert generated["status"] == "SUPPRESSED"
    assert generated["household_count"] == 19


def test_report_with_exactly_twenty_households_passes_on_regeneration(api):
    """Adding the twentieth household lets regeneration pass and finalize the credit.

    PRD: "The boundary is inclusive-pass: a count of exactly twenty passes, a count of nineteen is suppressed."
    PRD: "If all cells pass, the report moves to `READY` and the reservation finalizes: the reserved counter decreases by `credit_cost` and the consumed counter increases by the same amount."
    Design: Difficulty/boundary_precision_check/cell_size_exactly_at_minimum_passes
    """
    world = _report_world(api, 19)
    report = create_report(api, world["contract"]["id"], world["analyst_headers"])
    first = get_success_data(api.generate_report(report["id"], world["analyst_headers"]))
    assert first["status"] == "SUPPRESSED"
    ingest_category_households(api, 1, "b20x", category_code="SNACKS")
    second = get_success_data(api.generate_report(report["id"], world["analyst_headers"]))
    assert second["status"] == "READY"
    assert second["household_count"] == 20
    contract = read_contract(api, world["contract"]["id"])
    assert contract["report_credits_consumed"] == 1


def _empty_segment_world(api):
    """Contract with SNACKS scope but no NW-region SNACKS households."""
    return account_with_contract(api, name="Kappa Kale", scope_category="SNACKS", scope_brands=["ACME"])


def test_zero_size_segment_submit_rejected(api):
    """A segment whose recomputed size is zero cannot leave DRAFT.

    PRD: "submitting recomputes `size` from the current panel, and if the recomputed size is zero the submission is refused with `ERR_SEGMENT_EMPTY` and no state change occurs."
    Design: Difficulty/boundary_precision_check/zero_size_segment_submit_rejected
    """
    world = _empty_segment_world(api)
    segment = create_segment(
        api, world["contract"]["id"], world["analyst_headers"], segment_name="NW Snackers", region="NW"
    )
    resp = api.submit_segment(segment["id"], world["analyst_headers"])
    validate_error(resp, ApiErrorId.SEGMENT_EMPTY.value, 422)
    observed = get_success_data(api.get_segment(segment["id"], world["analyst_headers"]))
    assert observed["status"] == "DRAFT"


def test_segment_submit_with_one_matching_household_passes(api):
    """Once one household matches, submission succeeds and reports size one.

    PRD: "submitting recomputes `size` from the current panel, and if the recomputed size is zero the submission is refused with `ERR_SEGMENT_EMPTY` and no state change occurs."
    PRD: "Otherwise the segment moves to `PENDING_APPROVAL`."
    Design: Difficulty/boundary_precision_check/zero_size_segment_submit_rejected
    """
    world = _empty_segment_world(api)
    segment = create_segment(
        api, world["contract"]["id"], world["analyst_headers"], segment_name="NW Snackers", region="NW"
    )
    validate_error(
        api.submit_segment(segment["id"], world["analyst_headers"]),
        ApiErrorId.SEGMENT_EMPTY.value,
        422,
    )
    ingest_households(api, [factories.household_payload("nw1", region="NW", category_codes=["SNACKS"])])
    submitted = submit_segment(api, segment["id"], world["analyst_headers"])
    assert submitted["status"] == "PENDING_APPROVAL"
    assert submitted["size"] == 1
