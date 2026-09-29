"""
Composite setup helpers for the Building Trades Hiring Hall Dispatch API.

Every helper drives the public API only — there is no back door into the store.
Setup calls go through the lenient success reader so a broken precondition
reports the API's own error_id instead of an opaque assertion.

The helpers are deliberately single-purpose and composable. Where a helper
bundles several hops (a working dispatch, a laid-off dispatch, a grievance
under review) each hop is phased so that no later hop invalidates a state the
same helper established earlier, which keeps the helpers reusable inside one
test without tripping a state gate.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import HiringHallApiClient
from .constants import (
    CLASSIFICATION_JOURNEYWORKER,
    LAYOFF_LACK_OF_WORK,
    SLOT_JOURNEYWORKER,
)
from .test_users import (
    BUSINESS_MANAGER,
    DISPATCHER,
    HALL_ADMIN,
    make_contractor_rep_headers,
    make_member_headers,
)

# ─── Logical clock (§2.5) ─────────────────────────────────────────────────────


def set_clock(api: HiringHallApiClient, instant: str) -> Dict[str, Any]:
    """Park the logical hall clock at an exact instant."""
    return get_success_data(api.set_clock(f.clock_payload(instant), HALL_ADMIN))


# ─── Tier 1: the hall's own records ───────────────────────────────────────────


def add_local(api: HiringHallApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.create_local(payload, HALL_ADMIN))


def add_home_local(api: HiringHallApiClient, **overrides) -> Dict[str, Any]:
    return add_local(api, f.home_local_payload(**overrides))


def add_sister_local(api: HiringHallApiClient, **overrides) -> Dict[str, Any]:
    return add_local(api, f.sister_local_payload(**overrides))


def add_list_group(api: HiringHallApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.create_out_of_work_list(payload, HALL_ADMIN))


def add_ratio_policy(api: HiringHallApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_ratio_policy(f.ratio_policy_payload(**overrides), HALL_ADMIN)
    )


def add_member(api: HiringHallApiClient, home_local_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_member(f.member_payload(home_local_id, **overrides), HALL_ADMIN)
    )


def add_journeyworker(
    api: HiringHallApiClient, home_local_id: str, full_name: str, hours: int, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_member(
            f.journeyworker_payload(
                home_local_id,
                **{"full_name": full_name, "local_hours_in_trade": hours, **overrides},
            ),
            HALL_ADMIN,
        )
    )


def add_apprentice(
    api: HiringHallApiClient,
    home_local_id: str,
    full_name: str,
    period: int = 2,
    hours: int = 500,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_member(
            f.apprentice_payload(
                home_local_id,
                **{
                    "full_name": full_name,
                    "apprentice_period": period,
                    "local_hours_in_trade": hours,
                    **overrides,
                },
            ),
            HALL_ADMIN,
        )
    )


def add_endorsement(
    api: HiringHallApiClient, member_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_skill_endorsement(
            member_id, f.skill_endorsement_payload(**overrides), HALL_ADMIN
        )
    )


def set_standing(api: HiringHallApiClient, member_id: str, standing: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.patch_member_standing(
            member_id, f.standing_payload(standing), headers or BUSINESS_MANAGER
        )
    )


# ─── Tier 2: the standard hall bootstrap ──────────────────────────────────────


def standard_hall(
    api: HiringHallApiClient,
    clock: str = f.DEFAULT_TEST_CLOCK,
    with_policy: bool = True,
    groups: Sequence[str] = ("GROUP_1",),
) -> Dict[str, Any]:
    """
    The chain nearly every scenario needs: a parked clock, the HOME local, the
    requested list groups and an in-force apprentice-ratio schedule.

    Returns a dict of ids keyed by `home_local_id`, `<group_code lowercased>_id`
    and `policy_id`, plus the clock instant under `clock`.
    """
    set_clock(api, clock)
    hall: Dict[str, Any] = {"clock": clock}
    hall["home_local_id"] = add_home_local(api)["id"]
    builders = {
        "GROUP_1": f.group_one_payload,
        "GROUP_2": f.group_two_payload,
        "GROUP_3": f.group_three_payload,
        "GROUP_4": f.group_four_payload,
    }
    for code in groups:
        group = add_list_group(api, builders[code]())
        hall[f"{code.lower()}_id"] = group["id"]
    if with_policy:
        hall["policy_id"] = add_ratio_policy(api)["id"]
    return hall


# ─── Tier 2: signing the book (§3.3) ──────────────────────────────────────────


def sign_book(
    api: HiringHallApiClient,
    member_id: str,
    list_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_registration(
            f.registration_payload(member_id, list_id, **overrides),
            headers or DISPATCHER,
        )
    )


def register_journeyworkers(
    api: HiringHallApiClient, home_local_id: str, list_id: str,
    people: Sequence[Sequence[Any]]
) -> List[Dict[str, Any]]:
    """
    Enter and sign a run of journeyworkers in the order given.

    `people` is a sequence of `(full_name, local_hours_in_trade)` pairs; the
    return value keeps that order, so index 0 is the first signer.
    """
    rows: List[Dict[str, Any]] = []
    for full_name, hours in people:
        member = add_journeyworker(api, home_local_id, full_name, hours)
        registration = sign_book(api, member["id"], list_id)
        rows.append({"member": member, "registration": registration})
    return rows


# ─── Tier 2: the contractor side (§3.5) ───────────────────────────────────────


def add_contractor(api: HiringHallApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_contractor(f.contractor_payload(**overrides), HALL_ADMIN)
    )


def set_signatory_status(
    api: HiringHallApiClient, contractor_id: str, status: str,
    headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.patch_contractor_signatory_status(
            contractor_id, f.signatory_status_payload(status), headers or BUSINESS_MANAGER
        )
    )


def open_job_request(
    api: HiringHallApiClient, contractor_id: str, **overrides
) -> Dict[str, Any]:
    """Intake by the contractor's own representative, whose id is the contractor id."""
    return get_success_data(
        api.create_job_request(
            f.job_request_payload(contractor_id, **overrides),
            make_contractor_rep_headers(contractor_id),
        )
    )


def contractor_with_call(
    api: HiringHallApiClient, **overrides
) -> Dict[str, Any]:
    """A signatory contractor plus one open job request against it."""
    contractor = add_contractor(api)
    job_request = open_job_request(api, contractor["id"], **overrides)
    return {"contractor": contractor, "job_request": job_request}


def job_request_version(api: HiringHallApiClient, job_request_id: str) -> int:
    """Re-read the request to pin `expected_job_request_version` (§2.8)."""
    data = get_success_data(api.get_job_request(job_request_id, DISPATCHER))
    return data["version"]


def read_job_request(api: HiringHallApiClient, job_request_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_job_request(job_request_id, DISPATCHER))


# ─── Tier 3: referral lifecycle (§3.6, §3.7) ──────────────────────────────────


def issue_referral(
    api: HiringHallApiClient,
    job_request_id: str,
    headers: Optional[Dict[str, str]] = None,
    version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """
    Issue one referral, pinning the request's current version unless a caller
    deliberately supplies a stale one.
    """
    pinned = version if version is not None else job_request_version(api, job_request_id)
    return get_success_data(
        api.create_referral(
            job_request_id, f.referral_payload(pinned, **overrides), headers or DISPATCHER
        )
    )


def accept_referral(
    api: HiringHallApiClient, referral_id: str, member_id: str
) -> Dict[str, Any]:
    """The member answers their own referral, which creates the dispatch."""
    return get_success_data(
        api.accept_referral(referral_id, make_member_headers(member_id))
    )


def refuse_referral(
    api: HiringHallApiClient, referral_id: str, member_id: str,
    good_cause: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.refuse_referral(
            referral_id, f.refusal_payload(good_cause), make_member_headers(member_id)
        )
    )


def withdraw_referral(
    api: HiringHallApiClient, referral_id: str, reason: str = "Contractor pulled the call."
) -> Dict[str, Any]:
    return get_success_data(
        api.withdraw_referral(referral_id, f.withdraw_payload(reason), DISPATCHER)
    )


def read_referral(api: HiringHallApiClient, referral_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_referral(referral_id, DISPATCHER))


def read_registration(api: HiringHallApiClient, registration_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_registration(registration_id, DISPATCHER))


def read_list_group(api: HiringHallApiClient, list_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_out_of_work_list(list_id, DISPATCHER))


def read_member(api: HiringHallApiClient, member_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_member(member_id, DISPATCHER))


def referrals_on(api: HiringHallApiClient, job_request_id: str) -> List[Dict[str, Any]]:
    response = api.list_referrals(DISPATCHER, {"job_request_id": job_request_id})
    return get_success_data(response)


def registrations_on(api: HiringHallApiClient, list_id: str, status: Optional[str] = None
                      ) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"list_id": list_id, "limit": 100}
    if status is not None:
        params["status"] = status
    return get_success_data(api.list_registrations(DISPATCHER, params))


def ledger_rows(api: HiringHallApiClient, **filters) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": 100}
    params.update(filters)
    return get_success_data(api.list_ledger_entries(HALL_ADMIN, params))


# ─── Tier 4: a member on the job (§3.7, §3.8) ─────────────────────────────────


def working_dispatch(
    api: HiringHallApiClient,
    clock: str = f.DEFAULT_TEST_CLOCK,
    hours: int = 9000,
    full_name: str = "Finn Ortiz",
    **job_request_overrides,
) -> Dict[str, Any]:
    """
    The whole chain from an empty hall to one member in `WORKING` status:
    clock, HOME local, GROUP_1, ratio policy, one journeyworker signed on, a
    signatory contractor, an open call, a list-order referral and its
    acceptance. Returns every intermediate record.
    """
    hall = standard_hall(api, clock=clock)
    member = add_journeyworker(api, hall["home_local_id"], full_name, hours)
    registration = sign_book(api, member["id"], hall["group_1_id"])
    contractor = add_contractor(api)
    job_request = open_job_request(api, contractor["id"], **job_request_overrides)
    referral = issue_referral(
        api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    dispatch = accept_referral(api, referral["id"], member["id"])
    return {
        "hall": hall,
        "member": member,
        "registration": registration,
        "contractor": contractor,
        "job_request": job_request,
        "referral": referral,
        "dispatch": dispatch,
    }


def lay_off(
    api: HiringHallApiClient,
    dispatch_id: str,
    contractor_id: str,
    hours_worked: int = 40,
    layoff_reason: str = LAYOFF_LACK_OF_WORK,
) -> Dict[str, Any]:
    """The contractor's own representative closes the employment record."""
    return get_success_data(
        api.layoff_dispatch(
            dispatch_id,
            f.layoff_payload(hours_worked, layoff_reason),
            make_contractor_rep_headers(contractor_id),
        )
    )


def laid_off_dispatch(
    api: HiringHallApiClient,
    clock: str = f.DEFAULT_TEST_CLOCK,
    layoff_clock: str = "2026-09-27T07:00:00.000Z",
    hours_worked: int = 40,
    layoff_reason: str = LAYOFF_LACK_OF_WORK,
    **overrides,
) -> Dict[str, Any]:
    """
    A working dispatch advanced to `LAID_OFF`, which opens the recall window.

    The layoff hop runs last and touches nothing the earlier hops rely on, so
    the returned ids stay usable for recall and re-registration legs.
    """
    scenario = working_dispatch(api, clock=clock, **overrides)
    set_clock(api, layoff_clock)
    scenario["laid_off"] = lay_off(
        api,
        scenario["dispatch"]["id"],
        scenario["contractor"]["id"],
        hours_worked,
        layoff_reason,
    )
    scenario["layoff_clock"] = layoff_clock
    return scenario


# ─── Tier 5: grievance progression (§3.9) ─────────────────────────────────────


def file_grievance(
    api: HiringHallApiClient, referral_id: str, grievant_member_id: str, **overrides
) -> Dict[str, Any]:
    """`grievant_member_id` is taken from `X-User-ID`, never from the body."""
    return get_success_data(
        api.create_grievance(
            f.grievance_payload(referral_id, **overrides),
            make_member_headers(grievant_member_id),
        )
    )


def open_for_review(
    api: HiringHallApiClient, grievance_id: str,
    headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.review_grievance(grievance_id, headers or BUSINESS_MANAGER)
    )


def grievance_under_review(
    api: HiringHallApiClient, referral_id: str, grievant_member_id: str, **overrides
) -> Dict[str, Any]:
    """File, then open for review — the state adjudication requires."""
    grievance = file_grievance(api, referral_id, grievant_member_id, **overrides)
    reviewed = open_for_review(api, grievance["id"])
    return reviewed


def run_sweep(api: HiringHallApiClient,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """The housekeeping sweep of §3.4, evaluated against the current clock."""
    return get_success_data(api.run_dispatch_run(headers or HALL_ADMIN))


# ─── Convenience projections ──────────────────────────────────────────────────


def positions_by_member(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Map member id to `position_number` for a list payload of registrations."""
    return {row["member_id"]: row["position_number"] for row in rows}


def journeyworker_names(count: int) -> List[str]:
    """Stable distinct names for a run of journeyworkers."""
    pool = [
        "Ana Cortes", "Bo Nilsen", "Cy Boyd", "Dee Kwan", "Elle Fry",
        "Finn Ortiz", "Gia Roux", "Hal Reyes", "Ivy Munoz", "Jo Park",
        "Kai Lin", "Lex Ruiz", "Mo Vance", "Nils Aberg", "Ola Bright",
    ]
    assert count <= len(pool), "Not enough distinct names for this scenario"
    return pool[:count]


CLASSIFICATIONS = (CLASSIFICATION_JOURNEYWORKER,)
