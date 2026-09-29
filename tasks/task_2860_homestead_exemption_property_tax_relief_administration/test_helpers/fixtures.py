"""Composite state builders.

Every builder drives the public API only, and every setup call is checked with
the lenient success validator so a broken precondition surfaces as a clear setup
failure rather than as a mysterious assertion later.

The builders are layered:

* level 1 primitives — clock, programme, parcel, taxpayer, ownership, registry;
* level 2 — an application parked in a chosen lifecycle state;
* level 3 — a minted grant, with the parcel already repriced;
* level 4 — accumulated money state: retroactive claims, fraud recoveries;
* level 5 — terminal and hand-off state: revocations, dockets, appeals.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import ADDR_ELM, ADDR_OAK, DEFAULT_CLOCK_UTC
from .test_users import (
    ADMIN,
    ANALYST,
    CLERK,
    HEARING_CLERK,
    INVESTIGATOR,
    RECOVERY,
    REVIEWER,
    REVIEWER_2,
    make_taxpayer_headers,
)

# ------------------------------------------------------------ level 1


def set_clock(api: ApiClient, to_iso8601: str = DEFAULT_CLOCK_UTC) -> Dict[str, Any]:
    """Place the logical clock at a known instant."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def create_program(api: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.create_relief_program(payload, ADMIN))


def create_parcel(api: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.create_parcel(payload, ANALYST))


def create_taxpayer(api: ApiClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api.create_taxpayer_account(payload, CLERK))


def add_ownership(
    api: ApiClient, parcel_id: str, taxpayer_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_ownership_record(
            f.ownership_record(parcel_id, taxpayer_id, **overrides), ANALYST
        )
    )


def inject_registry(
    api: ApiClient, taxpayer_id: str, source: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_registry_record(
            f.registry_record(taxpayer_id, source, **overrides), ADMIN
        )
    )


def inject_matching_residency(
    api: ApiClient, taxpayer_id: str, address: str = ADDR_OAK
) -> None:
    """Give the taxpayer voter and deed rows at the address that will be claimed.

    These are the two sources whose latest row must be a match before an approval
    may be issued, so both are seeded at the same address.
    """
    inject_registry(api, taxpayer_id, "VOTER_REGISTRY", address_normalized=address)
    inject_registry(api, taxpayer_id, "DEED_REGISTRY", address_normalized=address)


def create_certification(
    api: ApiClient, taxpayer_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_income_certification(
            f.income_certification(taxpayer_id, **overrides), CLERK
        )
    )


# ------------------------------------------------------------ level 2


def submitted_application(
    api: ApiClient,
    parcel_id: str,
    taxpayer_id: str,
    program_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """An application taken from draft to review by a submit."""
    created = get_success_data(
        api.create_application(
            f.application(parcel_id, taxpayer_id, program_id, **overrides), CLERK
        )
    )
    return get_success_data(api.submit_application(created["id"], CLERK))


def run_checks(
    api: ApiClient, application_id: str, sources: List[str], headers=REVIEWER
) -> List[Dict[str, Any]]:
    """Record one cross-match per named source, in order."""
    return [
        get_success_data(
            api.create_verification_check(
                application_id, f.verification_check(source), headers
            )
        )
        for source in sources
    ]


def application_ready_for_approval(
    api: ApiClient,
    parcel_id: str,
    taxpayer_id: str,
    program_id: str,
    extra_sources: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """An application under review whose voter and deed cross-matches both match."""
    application = submitted_application(
        api, parcel_id, taxpayer_id, program_id, **overrides
    )
    run_checks(api, application["id"], ["VOTER_REGISTRY", "DEED_REGISTRY"])
    if extra_sources:
        run_checks(api, application["id"], extra_sources)
    return get_success_data(api.get_application(application["id"], REVIEWER))


# ------------------------------------------------------------ level 3

_CLEAN = "clean"
_DAMNING = "damning"


def approval_world(
    api: ApiClient,
    clock: Optional[str] = DEFAULT_CLOCK_UTC,
    program: Optional[Dict[str, Any]] = None,
    program_id: Optional[str] = None,
    parcel: Optional[Dict[str, Any]] = None,
    taxpayer: Optional[Dict[str, Any]] = None,
    ownership: Optional[Dict[str, Any]] = None,
    application: Optional[Dict[str, Any]] = None,
    certification: Optional[Dict[str, Any]] = None,
    income_registry: bool = True,
    reported_income_cents: Optional[int] = None,
    check_log: str = _CLEAN,
    approve: bool = True,
    determined_by=REVIEWER,
) -> Dict[str, Any]:
    """One claimant, one parcel, one application taken as far as asked for.

    The programme, parcel, account, ownership record, application and income
    certification are each built from the supplied payload or from the module
    default, and the claimed address always mirrors the parcel's
    ``situs_address_normalized`` so a cross-match against a registry row at that
    address agrees.

    ``check_log`` selects the cross-match history:

    * ``"clean"`` records one voter and one deed check, each against a registry
      row at the parcel address, so the latest word on both gating sources is a
      match;
    * ``"damning"`` records a voter check against a foreign address first and
      only then corrects it, adds a postal forwarding row and contradicts the
      certification with the revenue figure — the latest voter and deed rows
      still match, so an approval is still admissible, but the replayed history
      carries three latched mismatches.

    When a certification is supplied an income check is recorded too; with
    ``income_registry`` false no revenue row is injected at all, so that check
    finds no record and the certification stays uncertified.
    """
    if clock is not None:
        set_clock(api, clock)
    if program_id is None:
        program_row = create_program(api, program or f.homestead_basic_program())
        program_id = program_row["id"]
    else:
        program_row = None
    parcel_row = create_parcel(api, parcel or f.parcel())
    situs = parcel_row["situs_address_normalized"]
    taxpayer_row = create_taxpayer(api, taxpayer or f.taxpayer_account())
    ownership_row = add_ownership(
        api, parcel_row["id"], taxpayer_row["id"], **(ownership or {})
    )
    application_overrides = dict(application or {})
    application_overrides.setdefault("claimed_address_normalized", situs)
    application_overrides.setdefault(
        "claimed_occupancy_date", ownership_row["occupancy_start_date"]
    )
    application_row = submitted_application(
        api,
        parcel_row["id"],
        taxpayer_row["id"],
        program_id,
        **application_overrides,
    )
    app_id = application_row["id"]

    certification_row = None
    if certification is not None:
        certification_row = create_certification(
            api, taxpayer_row["id"], **certification
        )

    if check_log == _DAMNING:
        # A voter row at a foreign address, cross-matched before it is corrected.
        inject_registry(
            api, taxpayer_row["id"], "VOTER_REGISTRY", address_normalized=ADDR_ELM
        )
        run_checks(api, app_id, ["VOTER_REGISTRY"])
        inject_registry(
            api,
            taxpayer_row["id"],
            "VOTER_REGISTRY",
            record_effective_date="2026-02-10",
            address_normalized=situs,
        )
        run_checks(api, app_id, ["VOTER_REGISTRY"])
        inject_registry(
            api, taxpayer_row["id"], "DEED_REGISTRY", address_normalized=situs
        )
        run_checks(api, app_id, ["DEED_REGISTRY"])
        inject_registry(
            api,
            taxpayer_row["id"],
            "USPS_NCOA",
            record_effective_date="2026-02-15",
            address_normalized=ADDR_ELM,
        )
        run_checks(api, app_id, ["USPS_NCOA"])
    else:
        inject_registry(
            api, taxpayer_row["id"], "VOTER_REGISTRY", address_normalized=situs
        )
        inject_registry(
            api, taxpayer_row["id"], "DEED_REGISTRY", address_normalized=situs
        )
        run_checks(api, app_id, ["VOTER_REGISTRY", "DEED_REGISTRY"])

    if certification_row is not None:
        if income_registry:
            if reported_income_cents is None:
                reported_income_cents = (
                    9000000
                    if check_log == _DAMNING
                    else certification_row["household_income_cents"]
                )
            inject_registry(
                api,
                taxpayer_row["id"],
                "INCOME_DOR",
                record_effective_date="2026-02-20",
                reported_income_cents=reported_income_cents,
            )
        run_checks(api, app_id, ["INCOME_DOR"])
        certification_row = read_certification(
            api, taxpayer_row["id"], certification_row["id"]
        )

    world: Dict[str, Any] = {
        "program": program_row,
        "program_id": program_id,
        "parcel": parcel_row,
        "parcel_version_at_determination": parcel_row["version"],
        "situs": situs,
        "taxpayer": taxpayer_row,
        "taxpayer_headers": make_taxpayer_headers(taxpayer_row["id"]),
        "ownership": ownership_row,
        "application": get_success_data(api.get_application(app_id, REVIEWER)),
        "application_id": app_id,
        "certification": certification_row,
        "grant": None,
        "grant_id": None,
        "grant_version": None,
    }
    if not approve:
        return world

    determined = get_success_data(
        api.determine_application(
            app_id, f.approve_determination(parcel_row["version"]), determined_by
        )
    )
    grant = get_success_data(api.get_grant(determined["resulting_grant_id"], REVIEWER))
    world["application"] = determined
    world["grant"] = grant
    world["grant_id"] = grant["id"]
    world["grant_version"] = grant["version"]
    return world


def read_certification(
    api: ApiClient, taxpayer_id: str, certification_id: str
) -> Dict[str, Any]:
    """Re-read one of a taxpayer's certifications after a cross-match touched it."""
    response = api.list_income_certifications(taxpayer_id, CLERK, limit=100)
    body = response.json()
    assert response.status_code == 200, f"certification read failed: {response.text}"
    for row in body["data"]:
        if row["id"] == certification_id:
            return row
    raise AssertionError(f"certification {certification_id} disappeared from the list")


def approved_homestead_world(api: ApiClient, **parcel_overrides: Any) -> Dict[str, Any]:
    """A whole-share basic homestead grant on a capped parcel.

    The parcel's capped value is 33600000, the programme exempts 2500 basis
    points of it and the 10000000 ceiling does not bind, so the grant carries a
    benefit of 8400000 and the parcel settles at exempt 8400000 / taxable
    25200000.
    """
    return approval_world(api, parcel=f.parcel(**parcel_overrides))


def mismatching_check_world(
    api: ApiClient,
    certification_year: int = 2026,
    recertification_due_date: str = "2026-12-31",
) -> Dict[str, Any]:
    """A homestead grant whose cross-match log is deliberately damning.

    The voter row first sits at a foreign address and only later moves to the
    parcel, the postal row reports a forward and the income row contradicts the
    certification, so the replayed log latches an address, a postal and an income
    mismatch while the latest voter and deed rows still permit the approval.
    """
    return approval_world(
        api,
        check_log=_DAMNING,
        certification={
            "certification_year": certification_year,
            "recertification_due_date": recertification_due_date,
            "household_income_cents": 5000000,
            "countable_asset_cents": 1000000,
            "household_size": 2,
        },
    )


RIDGE_ADDRESS = "900 RIDGE RD NORTHFIELD ST 10009"


def waterfall_parcel_world(
    api: ApiClient, approve_second: bool = False
) -> Dict[str, Any]:
    """A small parcel carrying a residence claim and a farm claim at once.

    The parcel's base year equals its tax year, so no cap growth occurs and the
    assessed basis is 1000000. The residence programme exempts 9000 basis points of
    that and the farm programme 5000, so the two benefits together — 900000 and
    500000 — ask for more than the basis can supply.

    The residence occupancy interval is closed at 2030-01-01 and the agricultural
    one is open-ended, so neither record supersedes the other: only an open-ended
    predecessor is truncated. The second application is left under review unless
    ``approve_second`` asks for it to be determined too.
    """
    set_clock(api)
    homestead = create_program(api, f.homestead_basic_program(relief_pct_bps=9000))
    agricultural = create_program(
        api,
        f.agricultural_use_program(
            relief_pct_bps=5000, max_exempt_value_cents=5000000, priority_rank=40
        ),
    )
    parcel = create_parcel(
        api,
        f.parcel(
            apn="P-0009",
            situs_address_normalized=RIDGE_ADDRESS,
            county_zone="WEST",
            base_year=2026,
            base_year_value_cents=1000000,
            market_value_cents=1200000,
        ),
    )
    taxpayer = create_taxpayer(
        api, f.taxpayer_account(mailing_address_normalized=RIDGE_ADDRESS)
    )
    add_ownership(
        api,
        parcel["id"],
        taxpayer["id"],
        occupancy_start_date="2019-06-01",
        occupancy_end_date="2030-01-01",
    )
    add_ownership(
        api,
        parcel["id"],
        taxpayer["id"],
        occupancy_type="AGRICULTURAL",
        deed_recorded_date="2019-01-01",
        occupancy_start_date="2019-01-01",
    )
    inject_matching_residency(api, taxpayer["id"], address=RIDGE_ADDRESS)

    first_application = application_ready_for_approval(
        api,
        parcel["id"],
        taxpayer["id"],
        homestead["id"],
        claimed_address_normalized=RIDGE_ADDRESS,
    )
    first_determined = get_success_data(
        api.determine_application(
            first_application["id"], f.approve_determination(parcel["version"]), REVIEWER
        )
    )
    second_application = application_ready_for_approval(
        api,
        parcel["id"],
        taxpayer["id"],
        agricultural["id"],
        claimed_address_normalized=RIDGE_ADDRESS,
        claimed_occupancy_date="2019-01-01",
    )
    world: Dict[str, Any] = {
        "homestead": homestead,
        "agricultural": agricultural,
        "parcel": parcel,
        "taxpayer": taxpayer,
        "first_grant_id": first_determined["resulting_grant_id"],
        "second_application_id": second_application["id"],
        "second_grant_id": None,
    }
    if not approve_second:
        return world

    repriced = get_success_data(api.get_parcel(parcel["id"], ANALYST))
    second_determined = get_success_data(
        api.determine_application(
            second_application["id"],
            f.approve_determination(repriced["version"]),
            REVIEWER,
        )
    )
    world["second_grant_id"] = second_determined["resulting_grant_id"]
    return world


def approved_freeze_world(
    api: ApiClient,
    clock: str = "2026-04-01T00:00:00Z",
    destinations: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """A freeze-enabled senior grant plus unencumbered destination parcels.

    The source parcel's assessed value of 33600000 is frozen at approval, so the
    whole 33600000 is available to port, and a relief rate of 1000 basis points
    puts the benefit at 3360000.

    A claimant may hold only one primary residence at a time, so the occupancy
    intervals are laid out end to end: the source runs to 2026-03-01 and each
    destination picks up where the previous interval stopped.  ``destinations``
    names the successor parcels as ``{"payload": ..., "occupancy": (start, end)}``
    entries, with an end of ``None`` leaving the last interval open.
    """
    if destinations is None:
        destinations = [
            {"payload": f.destination_parcel(), "occupancy": ("2026-03-01", None)}
        ]
    world = approval_world(
        api,
        clock=clock,
        program=f.senior_freeze_program(),
        ownership={"occupancy_end_date": "2026-03-01"},
        approve=False,
    )
    created: List[Dict[str, Any]] = []
    for spec in destinations:
        destination = create_parcel(api, spec["payload"])
        start, end = spec["occupancy"]
        add_ownership(
            api,
            destination["id"],
            world["taxpayer"]["id"],
            deed_recorded_date=start,
            occupancy_start_date=start,
            **({"occupancy_end_date": end} if end else {}),
        )
        created.append(destination)
    determined = get_success_data(
        api.determine_application(
            world["application_id"],
            f.approve_determination(world["parcel"]["version"]),
            REVIEWER,
        )
    )
    grant = get_success_data(api.get_grant(determined["resulting_grant_id"], REVIEWER))
    world["application"] = determined
    world["grant"] = grant
    world["grant_id"] = grant["id"]
    world["grant_version"] = grant["version"]
    world["destination"] = created[0]
    world["destinations"] = created
    return world


# ------------------------------------------------------------ level 4


def pending_claim(
    api: ApiClient, grant_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A filed retroactive claim carrying only its provisional gross refund."""
    return get_success_data(
        api.create_retroactive_claim(f.retroactive_claim(grant_id, **overrides), CLERK)
    )


def open_fraud_case(
    api: ApiClient, grant_id: str, taxpayer_id: str, **overrides: Any
) -> Dict[str, Any]:
    """An opened investigation, which suspends the grant and flags the account."""
    return get_success_data(
        api.create_fraud_case(f.fraud_case(grant_id, taxpayer_id, **overrides), INVESTIGATOR)
    )


def substantiated_fraud_case(
    api: ApiClient, grant_id: str, taxpayer_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A substantiated investigation with its recovery ledger already frozen."""
    case = open_fraud_case(api, grant_id, taxpayer_id, **overrides)
    return get_success_data(
        api.decide_fraud_case(
            case["id"],
            f.fraud_decision(
                "SUBSTANTIATE",
                "Address and postal cross-match establish the improper years.",
            ),
            INVESTIGATOR,
        )
    )


def pay_recovery(
    api: ApiClient, case_id: str, amount_cents: int, reason: str = "Partial collection"
) -> Dict[str, Any]:
    """Collect a named amount against an assessed recovery balance."""
    return get_success_data(
        api.fraud_recovery_action(
            case_id, f.recovery_action("PAY", amount_cents, reason), RECOVERY
        )
    )


# ------------------------------------------------------------ level 5


def revoke_grant(
    api: ApiClient,
    grant_id: str,
    reason: str = "Occupancy audit found the parcel vacant.",
    headers=REVIEWER_2,
) -> Dict[str, Any]:
    """Drive a grant straight to its revoked terminal state."""
    return get_success_data(
        api.grant_compliance_action(
            grant_id, f.compliance_action("REVOKE", reason), headers
        )
    )


def denial_notice_world(api: ApiClient, claimants: int = 1) -> Dict[str, Any]:
    """One parcel with the named number of denied applications, each with a notice.

    Each claimant is a distinct taxpayer account, so each denial notice belongs to
    a distinct owner and can be appealed independently.
    """
    set_clock(api)
    program = create_program(api, f.homestead_basic_program())
    parcel = create_parcel(api, f.parcel())
    taxpayers: List[Dict[str, Any]] = []
    notices: List[Dict[str, Any]] = []
    applications: List[Dict[str, Any]] = []
    for index in range(claimants):
        taxpayer = create_taxpayer(
            api,
            f.taxpayer_account(
                full_name=f"APPELLANT {index + 1}",
                date_of_birth=f"196{index + 6}-0{index + 2}-0{index + 2}",
                ssn_last4=f"100{index + 1}",
            ),
        )
        application = submitted_application(
            api, parcel["id"], taxpayer["id"], program["id"]
        )
        # A single voter cross-match with no registry row behind it leaves
        # residency unverified, which is the denial ground.
        run_checks(api, application["id"], ["VOTER_REGISTRY"], headers=CLERK)
        denied = get_success_data(
            api.determine_application(
                application["id"],
                f.deny_determination(parcel["version"]),
                REVIEWER,
            )
        )
        rows, _meta = _page(api.list_notices(taxpayer["id"], CLERK, notice_type="DENIAL"))
        taxpayers.append(taxpayer)
        applications.append(denied)
        notices.append(rows[0])
    return {
        "program": program,
        "parcel": parcel,
        "taxpayers": taxpayers,
        "applications": applications,
        "notices": notices,
    }


def _page(response):
    """Decode a collection response into its rows and its pagination meta."""
    body = response.json()
    assert response.status_code == 200, f"collection read failed: {response.text}"
    return body["data"], body["meta"]


def file_appeal(api: ApiClient, notice_id: str, taxpayer_id: str, **overrides: Any):
    """File an appeal as the taxpayer the notice was mailed to."""
    return get_success_data(
        api.create_appeal(
            f.appeal(notice_id, **overrides), make_taxpayer_headers(taxpayer_id)
        )
    )


def open_docket(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """An open hearing docket session."""
    return get_success_data(api.create_hearing_docket(f.hearing_docket(**overrides), HEARING_CLERK))


def schedule(
    api: ApiClient, appeal_id: str, docket_id: str, start_utc: str, end_utc: str
) -> Dict[str, Any]:
    """Reserve a hearing interval for an appeal."""
    return get_success_data(
        api.schedule_appeal(
            appeal_id, f.hearing_slot(docket_id, start_utc, end_utc), HEARING_CLERK
        )
    )


def appeal_world(api: ApiClient, claimants: int = 2, capacity: int = 4) -> Dict[str, Any]:
    """Denied applications, filed appeals and an open docket, ready for scheduling.

    The clock is advanced to a date well inside the thirty-day appeal window
    before the appeals are filed, so the deadline is never the blocking rule.
    """
    world = denial_notice_world(api, claimants=claimants)
    set_clock(api, "2026-08-05T00:00:00Z")
    appeals = [
        file_appeal(api, notice["id"], taxpayer["id"])
        for notice, taxpayer in zip(world["notices"], world["taxpayers"])
    ]
    world["appeals"] = appeals
    world["docket"] = open_docket(api, capacity=capacity)
    return world
