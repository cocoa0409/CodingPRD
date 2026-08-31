"""Composite setup helpers.

Most interesting claims in this API need the shop in a state that takes ten or
more calls to reach: a tool has to be registered, qualified on a press through
a run-at-rate trial, quoted, won, taken through a PPAP package to
``PPAP_APPROVED``, given a released resin lot, and only then can a job be
opened, scheduled, staged, started and reported against.  These helpers build
those preambles once.

Every helper uses the lenient success reader so a broken setup surfaces as a
setup failure rather than as a confusing assertion deep inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS as D
from .factories import (
    create_capacity_commit_payload,
    create_maintenance_order_payload,
    create_mold_payload,
    create_ppap_submission_payload,
    create_press_payload,
    create_press_qualification_payload,
    create_production_job_payload,
    create_production_report_payload,
    create_quote_payload,
    create_resin_lot_payload,
    create_tool_transfer_payload,
    schedule_run_at_rate_payload,
    submit_ppap_payload,
)
from .test_users import (
    QE_REVIEWER_USER_ID,
    QE_SUBMITTER_USER_ID,
    TEST_USERS,
    make_customer_rep_headers,
)

PA = TEST_USERS["plant_admin_headers"]
SE = TEST_USERS["sales_engineer_headers"]
PE = TEST_USERS["process_engineer_headers"]
QE = TEST_USERS["quality_engineer_headers"]        # qe-alice, the submitter
QE_REVIEWER = TEST_USERS["quality_reviewer_headers"]  # qe-bob, the endorser
TT = TEST_USERS["toolroom_tech_headers"]


def _merged(base: dict, overrides):
    if overrides:
        base = dict(base)
        base.update(overrides)
    return base


# ----------------------------------------------------- single-step helpers ---

def set_clock(to_iso8601: str = None) -> str:
    """Move the logical clock and return the new current_utc."""
    to_iso8601 = to_iso8601 or D["CLOCK"]
    data = get_success_data(api_client.set_clock(to_iso8601, PA))
    return data.get("current_utc", to_iso8601)


def create_customer(**overrides) -> dict:
    payload = _merged(
        {"name": D["CUSTOMER_NAME"], "code": D["CUSTOMER_CODE"]}, overrides
    )
    return get_success_data(api_client.create_customer(payload, PA))


def create_second_customer(**overrides) -> dict:
    payload = _merged(
        {"name": D["SECOND_CUSTOMER_NAME"], "code": D["SECOND_CUSTOMER_CODE"]},
        overrides,
    )
    return get_success_data(api_client.create_customer(payload, PA))


def create_press(**overrides) -> dict:
    return get_success_data(
        api_client.create_press(_merged(create_press_payload(), overrides), PA)
    )


def create_mold(customer_id: str, **overrides) -> dict:
    payload = _merged(create_mold_payload(customer_id), overrides)
    return get_success_data(api_client.create_mold(payload, PA))


def read_press(press_id: str) -> dict:
    return get_success_data(api_client.get_press(press_id, PE))


def read_mold(mold_id: str) -> dict:
    return get_success_data(api_client.get_mold(mold_id, PA))


def read_job(job_id: str) -> dict:
    return get_success_data(api_client.get_production_job(job_id, PE))


def read_quote(quote_id: str) -> dict:
    return get_success_data(api_client.get_quote(quote_id, SE))


def read_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_resin_lot(lot_id, QE))


def read_qualification(qualification_id: str) -> dict:
    return get_success_data(api_client.get_press_qualification(qualification_id, PE))


def read_ppap(submission_id: str) -> dict:
    return get_success_data(api_client.get_ppap_submission(submission_id, QE))


def read_transfer(transfer_id: str) -> dict:
    return get_success_data(api_client.get_tool_transfer(transfer_id, PA))


def read_maintenance_order(order_id: str) -> dict:
    return get_success_data(api_client.get_maintenance_order(order_id, TT))


def read_capacity_commit(commit_id: str) -> dict:
    return get_success_data(api_client.get_capacity_commit(commit_id, PA))


def read_report(report_id: str) -> dict:
    return get_success_data(api_client.get_production_report(report_id, QE))


def press_version(press_id: str) -> int:
    return read_press(press_id)["version"]


def mold_version(mold_id: str) -> int:
    return read_mold(mold_id)["version"]


def job_version(job_id: str) -> int:
    return read_job(job_id)["version"]


# ------------------------------------------------------------ qualification --

def open_qualification(mold_id: str, press_id: str) -> dict:
    return get_success_data(
        api_client.create_press_qualification(
            create_press_qualification_payload(mold_id, press_id), PE
        )
    )


def book_run_at_rate(qualification_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.schedule_run_at_rate(
            qualification_id, _merged(schedule_run_at_rate_payload(), overrides), PE
        )
    )


def record_run_at_rate(qualification_id: str, actual_parts_per_hour: int) -> dict:
    return get_success_data(
        api_client.record_run_at_rate(
            qualification_id, {"actual_parts_per_hour": actual_parts_per_hour}, QE
        )
    )


def qualify_pair(mold_id: str, press_id: str,
                 target_parts_per_hour: int = None,
                 actual_parts_per_hour: int = None,
                 **trial_overrides) -> dict:
    """Open a junction row and drive it to QUALIFIED (or FAILED) via one trial."""
    target = target_parts_per_hour or D["TRIAL_TARGET_PARTS_PER_HOUR"]
    actual = (
        actual_parts_per_hour
        if actual_parts_per_hour is not None
        else D["TRIAL_PASSING_PARTS_PER_HOUR"]
    )
    qualification = open_qualification(mold_id, press_id)
    book_run_at_rate(
        qualification["id"], target_parts_per_hour=target, **trial_overrides
    )
    return record_run_at_rate(qualification["id"], actual)


# -------------------------------------------------------------------- quote --

def create_quote(customer_id: str, mold_id: str, **overrides) -> dict:
    payload = _merged(create_quote_payload(customer_id, mold_id), overrides)
    return get_success_data(api_client.create_quote(payload, SE))


def price_quote(quote_id: str, press_id: str = None) -> dict:
    payload = {"press_id": press_id} if press_id else {}
    return get_success_data(api_client.price_quote(quote_id, payload, SE))


def submit_quote(quote_id: str) -> dict:
    return get_success_data(api_client.submit_quote(quote_id, SE))


def accept_quote(quote_id: str, customer_id: str, mold_id: str, **overrides) -> dict:
    payload = _merged(
        {"decision": "ACCEPT", "expected_mold_version": mold_version(mold_id)},
        overrides,
    )
    return get_success_data(
        api_client.quote_customer_decision(
            quote_id, payload, make_customer_rep_headers(customer_id)
        )
    )


def create_priced_submitted_quote(customer_id: str, mold_id: str, press_id: str = None,
                                  **quote_overrides) -> dict:
    """DRAFT -> PRICED -> SUBMITTED in one call."""
    quote = create_quote(customer_id, mold_id, **quote_overrides)
    price_quote(quote["id"], press_id)
    return submit_quote(quote["id"])


def create_accepted_quote(customer_id: str, mold_id: str, press_id: str = None,
                          **quote_overrides) -> dict:
    """Drive a new quote all the way to ACCEPTED, so the tool reaches SAMPLING."""
    quote = create_priced_submitted_quote(
        customer_id, mold_id, press_id, **quote_overrides
    )
    return accept_quote(quote["id"], customer_id, mold_id)


# --------------------------------------------------------------------- PPAP --

def create_ppap(mold_id: str, quote_id: str, **overrides) -> dict:
    payload = _merged(create_ppap_submission_payload(mold_id, quote_id), overrides)
    return get_success_data(api_client.create_ppap_submission(payload, QE))


def file_ppap(submission_id: str, **overrides) -> dict:
    payload = _merged(submit_ppap_payload(), overrides)
    return get_success_data(api_client.submit_ppap(submission_id, payload, QE))


def endorse_ppap(submission_id: str, **overrides) -> dict:
    """Endorse as qe-bob, who is never the submitter qe-alice."""
    payload = _merged({"decision": "ENDORSE"}, overrides)
    return get_success_data(
        api_client.ppap_internal_review(submission_id, payload, QE_REVIEWER)
    )


def ppap_customer_decision(submission_id: str, customer_id: str, mold_id: str,
                           decision: str = "APPROVE", **overrides) -> dict:
    payload = _merged(
        {"decision": decision, "expected_mold_version": mold_version(mold_id)},
        overrides,
    )
    return get_success_data(
        api_client.ppap_customer_decision(
            submission_id, payload, make_customer_rep_headers(customer_id)
        )
    )


def create_ppap_under_review(mold_id: str, quote_id: str, **ppap_overrides) -> dict:
    """DRAFT -> SUBMITTED (by qe-alice) -> UNDER_REVIEW (endorsed by qe-bob)."""
    submission = create_ppap(mold_id, quote_id, **ppap_overrides)
    file_ppap(submission["id"])
    return endorse_ppap(submission["id"])


# ---------------------------------------------------------------- resin lot --

def create_resin_lot(**overrides) -> dict:
    payload = _merged(create_resin_lot_payload(), overrides)
    return get_success_data(api_client.create_resin_lot(payload, PA))


def disposition_lot(lot_id: str, decision: str, **overrides) -> dict:
    payload = _merged({"decision": decision}, overrides)
    return get_success_data(api_client.resin_lot_disposition(lot_id, payload, QE))


def create_released_lot(**overrides) -> dict:
    lot = create_resin_lot(**overrides)
    return disposition_lot(lot["id"], "RELEASE")


# ----------------------------------------------------------- production job --

def create_job(quote_id: str, **overrides) -> dict:
    payload = _merged(create_production_job_payload(quote_id), overrides)
    return get_success_data(api_client.create_production_job(payload, PE))


def schedule_job(job_id: str, press_id: str) -> dict:
    return get_success_data(
        api_client.schedule_job(
            job_id, {"expected_press_version": press_version(press_id)}, PE
        )
    )


def stage_job(job_id: str, lot_id: str) -> dict:
    return get_success_data(
        api_client.stage_material(job_id, {"resin_lot_id": lot_id}, PE)
    )


def start_job(job_id: str) -> dict:
    return get_success_data(api_client.start_job(job_id, PE))


def complete_job(job_id: str) -> dict:
    return get_success_data(api_client.complete_job(job_id, PE))


def unblock_job(job_id: str, press_id: str) -> dict:
    return get_success_data(
        api_client.unblock_job(
            job_id, {"expected_press_version": press_version(press_id)}, PE
        )
    )


def post_report(job_id: str, **overrides) -> dict:
    """Post a shift report, reading the job's current version for the echo."""
    expected = overrides.pop("expected_job_version", None)
    if expected is None:
        expected = job_version(job_id)
    payload = _merged(create_production_report_payload(job_id, expected), overrides)
    return get_success_data(api_client.create_production_report(payload, PE))


def reverse_report(report_id: str, reason: str = "shift report keyed against the wrong job") -> dict:
    return get_success_data(
        api_client.reverse_production_report(report_id, {"reason": reason}, QE)
    )


# ---------------------------------------------------------- toolroom orders --

def open_maintenance_order(mold_id: str, **overrides) -> dict:
    payload = _merged(create_maintenance_order_payload(mold_id), overrides)
    return get_success_data(api_client.create_maintenance_order(payload, TT))


def close_maintenance_order(order_id: str, mold_id: str, reset_shot_counter: bool = True) -> dict:
    payload = {
        "reset_shot_counter": reset_shot_counter,
        "expected_mold_version": mold_version(mold_id),
    }
    return get_success_data(api_client.close_maintenance_order(order_id, payload, TT))


# ---------------------------------------------------------- tool transfers ---

def request_transfer(mold_id: str, to_customer_id: str, **overrides) -> dict:
    payload = _merged(create_tool_transfer_payload(mold_id, to_customer_id), overrides)
    return get_success_data(api_client.create_tool_transfer(payload, PA))


def decide_transfer(transfer_id: str, decision: str = "APPROVE", **overrides) -> dict:
    payload = _merged({"decision": decision}, overrides)
    return get_success_data(api_client.tool_transfer_decision(transfer_id, payload, PA))


def complete_transfer(transfer_id: str, mold_id: str) -> dict:
    return get_success_data(
        api_client.complete_tool_transfer(
            transfer_id, {"expected_mold_version": mold_version(mold_id)}, PA
        )
    )


def request_and_approve_transfer(mold_id: str, to_customer_id: str, **overrides) -> dict:
    transfer = request_transfer(mold_id, to_customer_id, **overrides)
    return decide_transfer(
        transfer["id"], "APPROVE", reason="buy-out agreed in the 2026 master agreement"
    )


# -------------------------------------------------------- capacity commits ---

def create_capacity_commit(customer_id: str, press_id: str, **overrides) -> dict:
    payload = _merged(create_capacity_commit_payload(customer_id, press_id), overrides)
    return get_success_data(api_client.create_capacity_commit(payload, SE))


# =========================================================================== #
# Tier 2-5 composite scenarios                                                #
# =========================================================================== #

def setup_qualified_shop(clock: str = None,
                         customer_overrides: dict = None,
                         press_overrides: dict = None,
                         mold_overrides: dict = None,
                         trial_actual: int = None,
                         qualify: bool = True) -> dict:
    """Clock + customer + press + tool, with the pair driven through one trial.

    Returns a dict with ``customer``, ``press``, ``mold`` and (when a trial was
    run) ``qualification``.
    """
    set_clock(clock)
    customer = create_customer(**(customer_overrides or {}))
    press = create_press(**(press_overrides or {}))
    mold = create_mold(customer["id"], **(mold_overrides or {}))
    shop = {"customer": customer, "press": press, "mold": mold}
    if qualify:
        shop["qualification"] = qualify_pair(
            mold["id"], press["id"], actual_parts_per_hour=trial_actual
        )
    return shop


def setup_sampling_tool(**kwargs) -> dict:
    """A qualified shop whose quote has been ACCEPTED, so the tool is SAMPLING.

    Accepts every :func:`setup_qualified_shop` keyword plus ``quote_overrides``
    and ``pin_rate_press`` (default True -- pin the shop's own press).
    """
    quote_overrides = kwargs.pop("quote_overrides", None) or {}
    pin_rate_press = kwargs.pop("pin_rate_press", True)
    shop = setup_qualified_shop(**kwargs)
    press_id = shop["press"]["id"] if pin_rate_press else None
    shop["quote"] = create_accepted_quote(
        shop["customer"]["id"], shop["mold"]["id"], press_id, **quote_overrides
    )
    shop["mold"] = read_mold(shop["mold"]["id"])
    return shop


def setup_ppap_under_review(**kwargs) -> dict:
    """A SAMPLING tool whose PPAP package sits in UNDER_REVIEW."""
    ppap_overrides = kwargs.pop("ppap_overrides", None) or {}
    shop = setup_sampling_tool(**kwargs)
    shop["ppap"] = create_ppap_under_review(
        shop["mold"]["id"], shop["quote"]["id"], **ppap_overrides
    )
    return shop


def setup_approved_tool(decision: str = "APPROVE",
                        interim_expiry_shots: int = None,
                        with_lot: bool = True,
                        lot_overrides: dict = None,
                        **kwargs) -> dict:
    """The standard approval chain, all the way to an approved tool.

    Clock, customer, press, QUALIFIED junction row, priced/submitted/accepted
    quote, PPAP package filed by qe-alice, endorsed by qe-bob and decided by
    the customer.  ``decision`` may be ``APPROVE`` (the tool lands in
    ``PPAP_APPROVED``) or ``INTERIM_APPROVE`` (``INTERIM_APPROVED``, with
    ``interim_expiry_shots`` supplied).  Optionally receives and releases a
    resin lot as ``lot``.
    """
    shop = setup_ppap_under_review(**kwargs)
    extra = {}
    if interim_expiry_shots is not None:
        extra["interim_expiry_shots"] = interim_expiry_shots
    shop["ppap"] = ppap_customer_decision(
        shop["ppap"]["id"],
        shop["customer"]["id"],
        shop["mold"]["id"],
        decision,
        **extra,
    )
    shop["mold"] = read_mold(shop["mold"]["id"])
    if with_lot:
        shop["lot"] = create_released_lot(**(lot_overrides or {}))
    return shop


def setup_scheduled_job(job_overrides: dict = None, pin_press: bool = True,
                        **kwargs) -> dict:
    """The standard approval chain plus one job driven DRAFT -> SCHEDULED."""
    shop = setup_approved_tool(**kwargs)
    overrides = dict(job_overrides or {})
    if pin_press and "press_id" not in overrides:
        overrides["press_id"] = shop["press"]["id"]
    shop["job"] = create_job(shop["quote"]["id"], **overrides)
    shop["job"] = schedule_job(shop["job"]["id"], shop["press"]["id"])
    return shop


def setup_staged_job(**kwargs) -> dict:
    """A SCHEDULED job with the released lot bound to its material axis."""
    shop = setup_scheduled_job(**kwargs)
    shop["job"] = stage_job(shop["job"]["id"], shop["lot"]["id"])
    return shop


def setup_running_job(**kwargs) -> dict:
    """A SCHEDULED, STAGED job advanced to RUNNING and ready for reports."""
    shop = setup_staged_job(**kwargs)
    shop["job"] = start_job(shop["job"]["id"])
    return shop


def add_job(shop: dict, scheduled_start: str, scheduled_end: str,
            schedule: bool = False, stage: bool = False, start: bool = False,
            **job_overrides) -> dict:
    """Open a second (or third) job on the same quote, press and tool."""
    overrides = dict(job_overrides)
    overrides.setdefault("press_id", shop["press"]["id"])
    overrides["scheduled_start"] = scheduled_start
    overrides["scheduled_end"] = scheduled_end
    job = create_job(shop["quote"]["id"], **overrides)
    if schedule:
        job = schedule_job(job["id"], shop["press"]["id"])
    if stage:
        job = stage_job(job["id"], shop["lot"]["id"])
    if start:
        job = start_job(job["id"])
    return job
