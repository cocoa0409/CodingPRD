"""Eligibility window boundary precision at application submission.

The logical clock is never touched in this file: it reads the startup default
2026-09-01T00:00:00Z, so a member's days-until-separation is fixed by the
separation date alone.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId, factories, fixtures, make_service_member_headers


def _member(api, inst_id, name, separation_date):
    return fixtures.create_member(
        api, inst_id, full_name=name, service_branch="ARMY", pay_grade="E5",
        separation_date=separation_date, skills=["LOGISTICS"],
    )


def test_eligibility_window_upper_bound_inclusive(api):
    """PRD §3.2: "Finally, the eligibility window (`ELIGIBILITY_WINDOW_MIN_DAYS` 30
    to `ELIGIBILITY_WINDOW_MAX_DAYS` 180 days) requires `days_until_separation` at
    submission to be at least 30 and at most 180, both bounds inclusive — exactly
    30 days and exactly 180 days are eligible, while 29 or 181 days are rejected
    with `ERR_OUTSIDE_ELIGIBILITY_WINDOW`."

    Design: Difficulty/boundary_precision_check/eligibility_window_inclusive_bounds
    """
    inst = fixtures.create_installation(api)
    m180 = _member(api, inst["id"], "Max Bound", "2027-02-28")
    m181 = _member(api, inst["id"], "Over Bound", "2027-03-01")
    assert m180["days_until_separation"] == 180
    assert m181["days_until_separation"] == 181

    app180 = fixtures.submit_application(api, m180["id"])
    assert app180["status"] == "SUBMITTED", "180 days is the inclusive upper bound"
    assert app180["days_until_separation_at_submission"] == 180

    over = api.create_application(
        factories.create_application_payload(m181["id"]),
        make_service_member_headers(m181["id"]),
    )
    validate_error(over, ApiErrorId.ERR_OUTSIDE_ELIGIBILITY_WINDOW)


def test_eligibility_window_lower_bound_inclusive(api):
    """PRD §3.2: "Finally, the eligibility window (`ELIGIBILITY_WINDOW_MIN_DAYS` 30
    to `ELIGIBILITY_WINDOW_MAX_DAYS` 180 days) requires `days_until_separation` at
    submission to be at least 30 and at most 180, both bounds inclusive — exactly
    30 days and exactly 180 days are eligible, while 29 or 181 days are rejected
    with `ERR_OUTSIDE_ELIGIBILITY_WINDOW`."

    Design: Difficulty/boundary_precision_check/eligibility_window_inclusive_bounds
    """
    inst = fixtures.create_installation(api)
    m30 = _member(api, inst["id"], "Min Bound", "2026-10-01")
    m29 = _member(api, inst["id"], "Under Bound", "2026-09-30")
    assert m30["days_until_separation"] == 30
    assert m29["days_until_separation"] == 29

    app30 = fixtures.submit_application(api, m30["id"])
    assert app30["status"] == "SUBMITTED", "30 days is the inclusive lower bound"
    assert app30["days_until_separation_at_submission"] == 30

    under = api.create_application(
        factories.create_application_payload(m29["id"]),
        make_service_member_headers(m29["id"]),
    )
    validate_error(under, ApiErrorId.ERR_OUTSIDE_ELIGIBILITY_WINDOW)
