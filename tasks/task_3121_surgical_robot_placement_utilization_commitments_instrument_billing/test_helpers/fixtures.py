"""Composite setup helpers.

Every helper builds its preconditions from scratch through declared endpoints, because
the server is restarted before every individual test and therefore starts against an
empty database. Helpers use the framework's lenient `get_success_data()` so a broken
setup reports "Setup step failed ..." rather than a misleading assertion failure.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_account_payload,
    create_agreement_payload,
    create_configuration_payload,
    create_credentialing_evidence_payload,
    create_procedure_case_payload,
    create_readiness_review_payload,
    create_training_record_payload,
)
from .test_users import TEST_USERS, make_account_owner_headers, make_compliance_officer_headers

PLATFORM = TEST_USERS["platform_admin_headers"]
RSD = TEST_USERS["regional_sales_director_headers"]
COL = TEST_USERS["clinical_operations_lead_headers"]
HPO = TEST_USERS["hospital_procurement_officer_headers"]
SE = TEST_USERS["service_engineer_headers"]
CO = TEST_USERS["compliance_officer_headers"]
IDN = TEST_USERS["idn_coordinator_headers"]
ANON = TEST_USERS["anonymous_headers"]

APPROVER_USER_ID = "co-1"

_SITE_COUNTER = {"n": 0}


class Ctx:
    """Attribute bag describing a fully built scenario."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __getitem__(self, key):
        return self.__dict__[key]

    def __repr__(self):
        return "Ctx(" + ", ".join(f"{k}={v!r}" for k, v in self.__dict__.items()) + ")"


def _next_site_code(prefix="SITE"):
    _SITE_COUNTER["n"] += 1
    return f"{prefix}-{_SITE_COUNTER['n']}"


# ═════════════════════════════════════════════════════════════════════════════
# Tier 0 — single-call primitives
# ═════════════════════════════════════════════════════════════════════════════

def set_clock(to_iso8601: str, headers=None) -> None:
    """Advance the logical clock. Anonymous is admitted here so fixtures can run from empty."""
    get_success_data(api_client.set_current_utc(to_iso8601, headers or ANON))


def create_account(user_id: str = None, headers=None, **overrides) -> dict:
    """POST /api/accounts. `hospital_owner_user_id` is stamped from the caller's X-User-ID."""
    hdrs = dict(headers or RSD)
    if user_id is not None:
        hdrs["X-User-ID"] = user_id
    res = api_client.create_account(create_account_payload(**overrides), hdrs)
    return get_success_data(res, 201)


def create_configuration(**overrides) -> dict:
    res = api_client.create_configuration(create_configuration_payload(**overrides), PLATFORM)
    return get_success_data(res, 201)


def create_review(account_id: str, configuration_id: str, verdict: str = None,
                  site_code: str = None, headers=None, **overrides) -> dict:
    """Open a readiness review; optionally submit a verdict immediately."""
    payload = create_readiness_review_payload(
        configuration_id, site_code=site_code or _next_site_code(), **overrides)
    review = get_success_data(
        api_client.create_readiness_review(account_id, payload, headers or COL), 201)
    if verdict is not None:
        review = submit_verdict(review, verdict)
    return review


def submit_verdict(review: dict, verdict: str) -> dict:
    res = api_client.submit_readiness_verdict(
        review["id"],
        {"verdict": verdict, "expected_review_version": review["version"]},
        COL)
    return get_success_data(res, 200)


def reject_review(review: dict, note: str = "Site must be re-measured.") -> dict:
    res = api_client.reject_readiness_review(
        review["id"],
        {"remediation_note": note, "expected_review_version": review["version"]},
        COL)
    return get_success_data(res, 200)


def return_review_to_review(review: dict, note: str = "Site remediated.") -> dict:
    res = api_client.return_readiness_review_to_review(
        review["id"],
        {"remediation_note": note, "expected_review_version": review["version"]},
        COL)
    return get_success_data(res, 200)


def create_training_record(account_id: str, **overrides) -> dict:
    res = api_client.create_training_record(
        account_id, create_training_record_payload(**overrides), COL)
    return get_success_data(res, 201)


def _walk_training_to_credentialed(record: dict, account_id: str,
                                   approved_evidence_expires: str = None,
                                   proctor_case_ids=None) -> dict:
    """NOT_STARTED → SIMULATION_COMPLETE → PROCTORING → CREDENTIALED with evidence.

    `proctor_case_ids` supplies the ids minted by the logging calls when the
    training-record serializer does not echo them back (the PATCH-style logging
    responses carry the record, while the ids belong to the logged cases).
    """
    record = get_success_data(api_client.complete_simulation(
        record["id"],
        {"simulation_modules_completed": 3,
         "expected_training_record_version": record["version"]}, COL), 200)
    record = get_success_data(api_client.begin_proctoring(
        record["id"],
        {"required_proctored_cases": 1,
         "expected_training_record_version": record["version"]}, RSD), 200)
    apply_payload = create_credentialing_evidence_payload()
    if approved_evidence_expires:
        apply_payload["expires_utc"] = approved_evidence_expires
    get_success_data(api_client.create_credentialing_evidence(
        record["id"], apply_payload, make_account_owner_headers(account_id)), 201)

    first_log = api_client.log_proctor_case(
        record["id"],
        {"case_observation_ref": "OBS-1", "occurred_at_utc": "2026-08-20T00:00:00Z"}, COL)
    first_record = get_success_data(first_log, 201)
    first_id = _discover_proctor_case_id(first_log, first_record)
    second_log = api_client.log_proctor_case(
        record["id"],
        {"case_observation_ref": "OBS-2", "occurred_at_utc": "2026-08-21T00:00:00Z"}, COL)
    record = get_success_data(second_log, 201)
    second_id = _discover_proctor_case_id(second_log, record)
    proctor_case_id = second_id or first_id
    if proctor_case_id is None:
        ids = proctor_case_ids or []
        if not ids:
            raise AssertionError(
                "Could not discover a proctor case id: the log response exposed neither an "
                "id nor a proctor-case collection, and none was supplied.")
        proctor_case_id = ids[-1]
    record = get_success_data(api_client.approve_proctor_case(
        proctor_case_id,
        {"expected_training_record_version": record["version"]},
        make_compliance_officer_headers(APPROVER_USER_ID)), 200)
    return record


def _discover_proctor_case_id(response, record: dict):
    """Read the id of a freshly logged proctor case from a log response."""
    try:
        body = response.json()
    except Exception:  # pragma: no cover - defensive
        body = {}
    data = body.get("data") or {}
    if isinstance(data, dict):
        for key in ("proctor_case_id", "id"):
            value = data.get(key)
            if isinstance(value, str) and key == "proctor_case_id":
                return value
        cases = data.get("proctor_cases")
        if isinstance(cases, list) and cases:
            last = cases[-1]
            return last if isinstance(last, str) else last.get("id")
    for key in ("proctor_case_ids", "proctor_cases"):
        cases = record.get(key)
        if isinstance(cases, list) and cases:
            last = cases[-1]
            return last if isinstance(last, str) else last["id"]
    return None


def create_credentialed_surgeon(account_id: str, **overrides) -> tuple:
    """Full credentialing pathway. Returns (record, evidence_list)."""
    record = create_training_record(account_id, **overrides)
    record = _walk_training_to_credentialed(record, account_id)
    evidence = get_success_data(
        api_client.list_record_evidence(record["id"], CO), 200)
    return record, evidence


def draft_agreement(account_id: str, configuration_id: str, review_id: str,
                    **overrides) -> dict:
    res = api_client.create_agreement(
        create_agreement_payload(account_id, configuration_id, review_id, **overrides), RSD)
    return get_success_data(res, 201)


def submit_agreement(agreement: dict) -> dict:
    res = api_client.submit_agreement(
        agreement["id"], {"expected_agreement_version": agreement["version"]}, RSD)
    return get_success_data(res, 200)


def accept_agreement(agreement: dict, account: dict) -> dict:
    res = api_client.accept_agreement(
        agreement["id"],
        {"expected_agreement_version": agreement["version"],
         "expected_hospital_account_version": account["version"]},
        HPO)
    return get_success_data(res, 200)


def install_system(system: dict) -> dict:
    res = api_client.install_robot_system(
        system["id"], {"expected_robot_system_version": system["version"]}, COL)
    return get_success_data(res, 200)


def commission_system(system: dict) -> dict:
    res = api_client.commission_robot_system(
        system["id"], {"expected_robot_system_version": system["version"]}, COL)
    return get_success_data(res, 200)


def get_system(system_id: str) -> dict:
    return get_success_data(api_client.get_robot_system(system_id, SE), 200)


def get_account(account_id: str) -> dict:
    return get_success_data(api_client.get_account(account_id, RSD), 200)


def get_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, CO), 200)


def create_case(system_id: str, account_id: str, training_record_id: str,
                **overrides) -> dict:
    res = api_client.create_procedure_case(
        system_id, create_procedure_case_payload(training_record_id, **overrides),
        make_account_owner_headers(account_id))
    return get_success_data(res, 201)


def complete_case(case: dict, account_id: str) -> dict:
    res = api_client.mark_case_completed(
        case["id"], {"expected_case_version": case["version"]},
        make_account_owner_headers(account_id))
    return get_success_data(res, 200)


def cancel_case(case: dict, account_id: str = None) -> dict:
    headers = (make_account_owner_headers(account_id) if account_id
               else TEST_USERS["hospital_procurement_officer_headers"])
    res = api_client.cancel_procedure_case(
        case["id"], {"expected_case_version": case["version"]}, headers)
    return get_success_data(res, 200)


def month_close(as_of_utc: str = None) -> None:
    payload = {"as_of_utc": as_of_utc} if as_of_utc else {}
    get_success_data(api_client.run_month_close(PLATFORM, payload), 200)


# ═════════════════════════════════════════════════════════════════════════════
# Tier 1 — State progression
# ═════════════════════════════════════════════════════════════════════════════

def drive_account_to_readiness(account: dict) -> dict:
    """PROSPECT → READINESS, the client-driven step PRD §2.5 requires before a
    placement agreement can be drafted for the account.

    `READINESS` to `CONTRACTED` is evaluated only after a placement agreement is
    drafted, and it requires the account to still be `READINESS`
    (`ERR_ACCOUNT_NOT_IN_ELIGIBLE_STATE`, checked first). An account left in
    `PROSPECT` therefore rejects every draft, so any fixture that goes on to
    draft an agreement must activate the account first. Activation needs at least
    one readiness review and at least one surgeon training record on file
    (`ERR_READINESS_REVIEW_REQUIRED`, `ERR_TRAINING_PATH_UNINITIALIZED`), which
    `setup_account_with_review` has already created by the time this is called.
    """
    account = get_success_data(api_client.activate_account_readiness(
        _first_review_of(account["id"])["id"],
        {"expected_account_version": account["version"]}, COL), 200)
    return account


def _first_review_of(account_id: str) -> dict:
    reviews = get_success_data(
        api_client.list_account_readiness_reviews(account_id, PLATFORM), 200)
    if not reviews:
        raise AssertionError(
            "Setup chain expected a readiness review on the account before activation.")
    return reviews[0]


def setup_account_with_review(verdict: str = "PASSED", owner_user_id: str = None,
                              account_overrides: dict = None,
                              config_overrides: dict = None,
                              review_overrides: dict = None,
                              activated: bool = False,
                              training_record: bool = True) -> Ctx:
    """Account + configuration + readiness review at `verdict` + one surgeon record.

    `activated=False` leaves the account in `PROSPECT`, which is what the
    activation-precondition tests assert against. Fixtures that go on to draft an
    agreement pass `activated=True` (or call `drive_account_to_readiness`) so the
    `READINESS → CONTRACTED` step the draft triggers has a `READINESS` account.
    `training_record=False` omits the surgeon record, which activation requires
    (`ERR_TRAINING_PATH_UNINITIALIZED`).
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account(user_id=owner_user_id, **(account_overrides or {}))
    config = create_configuration(**(config_overrides or {}))
    review = create_review(account["id"], config["id"], verdict=verdict,
                           **(review_overrides or {}))
    surgeon = create_training_record(account["id"]) if training_record else None
    if activated:
        account = drive_account_to_readiness(account)
    return Ctx(account=account, config=config, review=review, surgeon=surgeon,
               account_headers=make_account_owner_headers(account["id"]))


def setup_agreement(verdict: str = "PASSED", submitted: bool = True, accepted: bool = False,
                    owner_user_id: str = None, account_overrides: dict = None,
                    config_overrides: dict = None, review_overrides: dict = None,
                    agreement_overrides: dict = None) -> Ctx:
    """Account + review + credentialed surgeon + agreement, optionally submitted/accepted."""
    ctx = setup_account_with_review(
        verdict=verdict, owner_user_id=owner_user_id,
        account_overrides=account_overrides, config_overrides=config_overrides,
        review_overrides=review_overrides, activated=True)
    agreement = draft_agreement(ctx.account["id"], ctx.config["id"], ctx.review["id"],
                                **(agreement_overrides or {}))
    if submitted or accepted:
        agreement = submit_agreement(agreement)
    sys_obj = contract = None
    if accepted:
        agreement = accept_agreement(agreement, ctx.account)
        systems = get_success_data(
            api_client.list_agreement_robot_systems(agreement["id"], RSD), 200)
        sys_obj = systems[0]
        contract = get_success_data(
            api_client.get_service_contract(agreement["synthesized_service_contract_id"], SE),
            200)
    ctx.agreement = agreement
    ctx.system = sys_obj
    ctx.contract = contract
    return ctx


# ═════════════════════════════════════════════════════════════════════════════
# Tier 2/3 — Hierarchies and full lifecycle shortcuts
# ═════════════════════════════════════════════════════════════════════════════

def setup_commissioned_system(account_overrides: dict = None,
                              config_overrides: dict = None,
                              agreement_overrides: dict = None,
                              review_overrides: dict = None,
                              owner_user_id: str = None,
                              credited: bool = True) -> Ctx:
    """The standard stack: account → configuration → PASSED review → credentialed surgeon
    → agreement → submit → accept → install → commission.

    Returns a Ctx carrying account, config, review, surgeon, agreement, system, contract
    and current utilization cycle.
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account(user_id=owner_user_id, **(account_overrides or {}))
    config = create_configuration(**(config_overrides or {}))
    review = create_review(account["id"], config["id"], verdict="PASSED",
                           **(review_overrides or {}))
    if credited:
        surgeon, _ = create_credentialed_surgeon(account["id"])
    else:
        surgeon = create_training_record(account["id"])
    # PROSPECT → READINESS must happen before the draft, because the draft triggers
    # READINESS → CONTRACTED and rejects an account that is not yet in READINESS.
    account = drive_account_to_readiness(account)
    agreement = draft_agreement(account["id"], config["id"], review["id"],
                                **(agreement_overrides or {}))
    agreement = submit_agreement(agreement)
    agreement = accept_agreement(agreement, account)
    system = get_success_data(
        api_client.list_agreement_robot_systems(agreement["id"], RSD), 200)[0]
    contract = get_success_data(
        api_client.get_service_contract(agreement["synthesized_service_contract_id"], SE), 200)
    system = install_system(system)
    system = commission_system(system)
    cycle = get_success_data(
        api_client.get_current_utilization_cycle(system["id"], COL), 200)
    account = get_account(account["id"])
    return Ctx(account=account, account_headers=make_account_owner_headers(account["id"]),
               config=config, review=review, surgeon=surgeon, agreement=agreement,
               system=system, contract=contract, cycle=cycle)


def setup_installed_system(account_overrides: dict = None,
                           config_overrides: dict = None,
                           agreement_overrides: dict = None) -> Ctx:
    """Standard stack through install, not yet commissioned."""
    ctx = setup_commissioned_system(account_overrides=account_overrides,
                                    config_overrides=config_overrides,
                                    agreement_overrides=agreement_overrides)
    return ctx


def setup_system_in_service_action(account_overrides: dict = None,
                                   config_overrides: dict = None,
                                   agreement_overrides: dict = None) -> Ctx:
    """Commissioned system then placed into SERVICE_ACTION_REQUIRED."""
    ctx = setup_commissioned_system(account_overrides=account_overrides,
                                    config_overrides=config_overrides,
                                    agreement_overrides=agreement_overrides)
    system = get_success_data(api_client.open_service_action(
        ctx.system["id"], {"expected_robot_system_version": ctx.system["version"]}, SE), 200)
    ctx.system = system
    ctx.account = get_account(ctx.account["id"])
    ctx.agreement = get_agreement(ctx.agreement["id"])
    return ctx


def setup_commissioned_system_with_cases(case_count: int, family: str = "UROLOGY",
                                         complete: bool = False,
                                         first_day: int = 2,
                                         duration_minutes: int = 60,
                                         instrument_load: int = 1,
                                         account_overrides: dict = None,
                                         config_overrides: dict = None,
                                         agreement_overrides: dict = None) -> Ctx:
    """Commissioned system with `case_count` cases on consecutive days from 2026-09-<first_day>."""
    ctx = setup_commissioned_system(account_overrides=account_overrides,
                                    config_overrides=config_overrides,
                                    agreement_overrides=agreement_overrides)
    cases = []
    for i in range(case_count):
        case = create_case(
            ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
            procedure_family=family,
            case_started_at=f"2026-09-{first_day + i:02d}T08:00:00Z",
            duration_minutes=duration_minutes,
            instrument_load=instrument_load)
        cases.append(case)
    if complete:
        cases = [complete_case(c, ctx.account["id"]) for c in cases]
    ctx.cases = cases
    ctx.cycle = get_success_data(
        api_client.get_current_utilization_cycle(ctx.system["id"], COL), 200)
    ctx.agreement = get_agreement(ctx.agreement["id"])
    return ctx


def setup_usage_based_system(minimum_procedures_per_cycle: int = 12,
                             placement_fee_cents: int = 1000000,
                             usage_rate_basis_points: int = 400,
                             case_count: int = 0,
                             complete: bool = False,
                             account_overrides: dict = None,
                             config_overrides: dict = None) -> Ctx:
    """USAGE_BASED agreement commissioned system, optionally with cases."""
    ctx = setup_commissioned_system(
        account_overrides=account_overrides, config_overrides=config_overrides,
        agreement_overrides={
            "arrangement_type": "USAGE_BASED",
            "base_monthly_fee_cents": 0,
            "minimum_procedures_per_cycle": minimum_procedures_per_cycle,
            "interval_months": 1,
            "placement_fee_cents": placement_fee_cents,
            "usage_rate_basis_points": usage_rate_basis_points,
        })
    ctx.cases = []
    for i in range(case_count):
        case = create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                           case_started_at=f"2026-09-{2 + i:02d}T08:00:00Z")
        if complete:
            case = complete_case(case, ctx.account["id"])
        ctx.cases.append(case)
    ctx.agreement = get_agreement(ctx.agreement["id"])
    return ctx


# ═════════════════════════════════════════════════════════════════════════════
# Tier 4 — Accumulation / threshold targeting
# ═════════════════════════════════════════════════════════════════════════════

def setup_system_at_completed_case_count(target_count: int, family: str = "UROLOGY",
                                         config_overrides: dict = None,
                                         account_overrides: dict = None) -> Ctx:
    """Commissioned system whose cycle holds exactly `target_count` COMPLETED cases.

    Used for band-boundary tests: build the count, then read the band.
    """
    return setup_commissioned_system_with_cases(
        case_count=target_count, family=family, complete=True,
        config_overrides={"max_instrument_lives": 60, **(config_overrides or {})},
        account_overrides=account_overrides)


def setup_system_with_scheduled_cases(case_count: int, family: str = "UROLOGY",
                                      config_overrides: dict = None) -> Ctx:
    """Commissioned system with `case_count` SCHEDULED cases (nothing completed)."""
    return setup_commissioned_system_with_cases(
        case_count=case_count, family=family, complete=False,
        config_overrides={"max_instrument_lives": 60, **(config_overrides or {})})


def setup_system_at_instrument_lives(max_instrument_lives: int,
                                     consumed: int = 0) -> Ctx:
    """Commissioned system whose accessory set has `max_instrument_lives` and an
    optional manual posting of `consumed` loads already recorded."""
    ctx = setup_commissioned_system(config_overrides={
        "max_instrument_lives": max_instrument_lives,
        "model_code": "DA_V1",
        "base_placement_fee_cents": 4800000,
        "integration_tier": 1,
    })
    if consumed:
        ctx.system = get_success_data(api_client.decrement_instrument_lives(
            ctx.system["id"], {"approved_load": consumed}, SE), 200)
    ctx.system = get_system(ctx.system["id"])
    return ctx


def setup_multi_family_completed_cases(families) -> Ctx:
    """Commissioned system with one COMPLETED case per distinct procedure family."""
    ctx = setup_commissioned_system(config_overrides={"max_instrument_lives": 60})
    cases = []
    for i, family in enumerate(families):
        case = create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                           procedure_family=family,
                           case_started_at=f"2026-09-{2 + i:02d}T08:00:00Z")
        cases.append(complete_case(case, ctx.account["id"]))
    ctx.cases = cases
    ctx.account = get_account(ctx.account["id"])
    return ctx


# ═════════════════════════════════════════════════════════════════════════════
# IDN pool
# ═════════════════════════════════════════════════════════════════════════════

def setup_idn_pair(idn_group_code: str = "IDN-ZEPHYR",
                   commitment: int = 12,
                   region_code: str = "SOUTH") -> Ctx:
    """Two accounts in one IDN group, each carrying a consumption ledger."""
    set_clock("2026-09-01T00:00:00Z")
    source = create_account(account_name="Zephyr Group North", idn_group_code=idn_group_code,
                            region_code=region_code, maximum_procedure_commitment=commitment)
    destination = create_account(account_name="Zephyr Group South", idn_group_code=idn_group_code,
                                 region_code=region_code,
                                 maximum_procedure_commitment=commitment)
    src_ledger = get_success_data(api_client.create_consumption_ledger(
        source["id"], {"maximum_procedure_commitment": commitment}, IDN), 201)
    dst_ledger = get_success_data(api_client.create_consumption_ledger(
        destination["id"], {"maximum_procedure_commitment": commitment}, IDN), 201)
    return Ctx(source=source, destination=destination,
               src_ledger=src_ledger, dst_ledger=dst_ledger,
               idn_group_code=idn_group_code)


# ═════════════════════════════════════════════════════════════════════════════
# Tier 5 — Finalization / terminal state
# ═════════════════════════════════════════════════════════════════════════════

def setup_terminated_agreement() -> Ctx:
    """Commissioned system then its agreement terminated (full cascade applied)."""
    ctx = setup_commissioned_system()
    agreement = get_success_data(api_client.terminate_agreement(
        ctx.agreement["id"], {"expected_agreement_version": ctx.agreement["version"]},
        PLATFORM), 200)
    ctx.agreement = agreement
    ctx.system = get_system(ctx.system["id"])
    ctx.account = get_account(ctx.account["id"])
    return ctx


def setup_closed_account() -> Ctx:
    """An account carried all the way to CLOSED, holding no agreement in ACTIVE or SUSPENDED.

    The account is driven PROSPECT → READINESS → CONTRACTED → ACTIVE, its agreement is
    then backed out to DRAFT, and only then is the account closed.
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account()
    config = create_configuration()
    review = create_review(account["id"], config["id"], verdict="PASSED")
    create_training_record(account["id"])
    account = drive_account_to_readiness(account)
    agreement = draft_agreement(account["id"], config["id"], review["id"])
    agreement = submit_agreement(agreement)
    account = get_account(account["id"])
    agreement = accept_agreement(agreement, account)
    account = get_account(account["id"])
    agreement = get_success_data(api_client.reject_agreement(
        agreement["id"], {"expected_agreement_version": agreement["version"]}, HPO), 200)
    account = get_account(account["id"])
    account = get_success_data(api_client.close_account(
        account["id"], {"expected_account_version": account["version"]}, PLATFORM), 200)
    return Ctx(account=account, agreement=agreement, config=config, review=review,
               account_headers=make_account_owner_headers(account["id"]))