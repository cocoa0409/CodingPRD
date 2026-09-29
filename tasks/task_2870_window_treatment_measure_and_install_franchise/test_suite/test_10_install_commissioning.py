"""Two independent dimensions on one install job, joined only at sign-off."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_COMMISSIONING_NOT_VERIFIED
from test_helpers.fixtures import (
    accept_quote,
    book_consultation,
    build_quote,
    charter_territory,
    configure_opening,
    hire_designer,
    intake_lead,
    onboard_vendor,
    place_order,
    present_quote,
    read_install_job,
    read_opening,
    read_quote,
    read_territory,
    receive_order,
    record_opening,
    schedule_install,
    set_clock,
    ship_order,
)
from test_helpers.test_users import designer_headers

BIG = {
    "width_top_in": 60.000, "width_middle_in": 60.000, "width_bottom_in": 60.000,
    "height_left_in": 84.000, "height_center_in": 84.000,
    "height_right_in": 84.000, "depth_in": 3.000,
}
SMALL = {
    "width_top_in": 24.000, "width_middle_in": 24.000, "width_bottom_in": 24.000,
    "height_left_in": 48.000, "height_center_in": 48.000,
    "height_right_in": 48.000, "depth_in": 3.000,
}


def _two_motorized_channels_on_one_job(api):
    """One received order carrying two motorized openings, and its install job.

    The order freezes `motorized_channel_count` at two — a hardwired slider and a
    battery transom — so the commissioning dimension starts `PENDING` while the
    install dimension starts `SCHEDULED`. The clock ends inside the appointment.
    """
    territory = charter_territory(api, royalty_rate_pct=0.055,
                                 lead_capacity_per_week=5,
                                 credit_limit_cents=2000000,
                                 liability_window="ROLLING_180D")
    designer = hire_designer(api, territory, certifications=["MOTORIZATION"])
    vendor = onboard_vendor(api, base_lead_time_days=10,
                            motorization_extra_days=3, cutoff_hour_utc=15,
                            remake_policy="SHARED_50_50",
                            concurrent_capacity=2,
                            supported_lift_systems=["CORDED", "CORDLESS",
                                                    "MOTORIZED"],
                            supported_hub_platforms=["MATTER", "HOMEKIT"])
    lead = intake_lead(api, territory, customer_name="Ana Ruiz",
                       source="WEB_FORM",
                       requested_at="2026-08-03T00:00:00.000Z",
                       child_occupied_dwelling=False)
    consultation = book_consultation(api, designer, lead)
    slider = record_opening(api, designer, consultation,
                            label="Great room slider", room_type="LIVING_ROOM",
                            mount_type="INSIDE", **BIG)
    transom = record_opening(api, designer, consultation,
                             label="Landing transom", room_type="OFFICE",
                             mount_type="INSIDE", **SMALL)
    configure_opening(api, designer, slider, fabric_code="WD-FAUX",
                      lift_system="MOTORIZED", motorization_option="HARDWIRED")
    configure_opening(api, designer, transom, fabric_code="LT-SHEER",
                      lift_system="MOTORIZED", motorization_option="BATTERY")
    quote = build_quote(api, designer, consultation)
    set_clock(api, "2026-08-03T16:00:00.000Z")
    present_quote(api, designer, quote)
    quote = accept_quote(api, designer, quote)
    order = place_order(api, territory, quote,
                        [slider["id"], transom["id"]], vendor)
    ship_order(api, vendor, order)
    set_clock(api, "2026-08-17T09:00:00.000Z")
    receive_order(api, territory, order)
    job = schedule_install(api, territory, order, designer,
                           scheduled_start_at="2026-08-20T09:00:00.000Z",
                           scheduled_end_at="2026-08-20T12:00:00.000Z")
    set_clock(api, "2026-08-20T09:30:00.000Z")
    return {"territory": territory, "designer": designer, "vendor": vendor,
            "quote": quote, "slider": slider, "transom": transom,
            "order": order, "job": job}


def test_a_partial_pairing_and_its_failed_verification_leave_the_job_scheduled(api):
    """`PENDING → PAIRED → FAILED` runs while `install_status` never moves.

    "An accepted pair call stores `hub_platform` and `paired_channel_count`, increments
    `commissioning_attempt_count`, and drives `PENDING → PAIRED` or `FAILED → PAIRED`.
    `install_status` is untouched: the two dimensions really do advance independently."

    "When `paired_channel_count` is less than `motorized_channel_count` the job moves
    `PAIRED → FAILED` and the call still returns HTTP 200 — a failed verification is a
    **recorded field observation**, not a request error."

    Design: Difficulty/non_linear_state_machine/commissioning_dimension_cycles_through_failed_while_install_status_stays_scheduled
    """
    world = _two_motorized_channels_on_one_job(api)
    job, designer = world["job"], world["designer"]
    dsg = designer_headers(designer["id"])

    assert job["motorized_channel_count"] == 2
    assert job["commissioning_status"] == "PENDING"
    assert job["install_status"] == "SCHEDULED"

    paired = validate_success(api.pair_commissioning(
        job["id"], f.pair_payload(1, "MATTER"), dsg))
    assert paired["commissioning_status"] == "PAIRED"
    assert paired["paired_channel_count"] == 1
    assert paired["commissioning_attempt_count"] == 1
    assert paired["hub_platform"] == "MATTER"
    assert paired["install_status"] == "SCHEDULED"

    failed = validate_success(api.verify_commissioning(job["id"], dsg))
    assert failed["commissioning_status"] == "FAILED"
    assert failed["install_status"] == "SCHEDULED"
    assert failed["completed_at"] is None


def test_sign_off_is_blocked_while_the_second_dimension_is_unresolved(api):
    """`FAILED` is one of the three commissioning states that block the join.

    "It requires `install_status` to be `SCHEDULED`, the acting designer to be the
    assigned one, the referenced order to be `RECEIVED`, and `commissioning_status` to
    be either `NOT_REQUIRED` or `VERIFIED` — `PENDING`, `PAIRED` and `FAILED` all block
    completion with `ERR_COMMISSIONING_NOT_VERIFIED`."

    Design: Difficulty/non_linear_state_machine/commissioning_dimension_cycles_through_failed_while_install_status_stays_scheduled
    """
    world = _two_motorized_channels_on_one_job(api)
    job, designer = world["job"], world["designer"]
    dsg = designer_headers(designer["id"])

    validate_success(api.pair_commissioning(job["id"],
                                            f.pair_payload(1, "MATTER"), dsg))
    validate_success(api.verify_commissioning(job["id"], dsg))

    validate_error(api.complete_install_job(job["id"], dsg),
                   ERR_COMMISSIONING_NOT_VERIFIED, 409)

    blocked = read_install_job(api, designer, job["id"])
    assert blocked["install_status"] == "SCHEDULED"
    assert blocked["commissioning_status"] == "FAILED"
    assert blocked["completed_at"] is None
    assert read_opening(api, designer,
                        world["slider"]["id"])["install_outcome"] == "PENDING"


def test_the_retry_verifies_and_only_then_does_sign_off_join_them(api):
    """`FAILED → PAIRED → VERIFIED` on the second attempt, then one completion.

    "From `FAILED` the designer may pair again, giving the retry cycle `PAIRED → FAILED
    → PAIRED`, bounded by the three-attempt cap."

    "When `paired_channel_count` equals `motorized_channel_count` the job moves `PAIRED
    → VERIFIED`, which satisfies the completion guard on the first dimension without
    changing `install_status`."

    Design: Difficulty/non_linear_state_machine/commissioning_dimension_cycles_through_failed_while_install_status_stays_scheduled
    """
    world = _two_motorized_channels_on_one_job(api)
    job, designer, territory = world["job"], world["designer"], world["territory"]
    dsg = designer_headers(designer["id"])

    validate_success(api.pair_commissioning(job["id"],
                                            f.pair_payload(1, "MATTER"), dsg))
    validate_success(api.verify_commissioning(job["id"], dsg))

    retried = validate_success(api.pair_commissioning(
        job["id"], f.pair_payload(2, "HOMEKIT"), dsg))
    assert retried["commissioning_status"] == "PAIRED"
    assert retried["paired_channel_count"] == 2
    assert retried["commissioning_attempt_count"] == 2
    assert retried["hub_platform"] == "HOMEKIT"

    verified = validate_success(api.verify_commissioning(job["id"], dsg))
    assert verified["commissioning_status"] == "VERIFIED"
    assert verified["install_status"] == "SCHEDULED"

    signed = validate_success(api.complete_install_job(job["id"], dsg))
    assert signed["install_status"] == "COMPLETED"
    assert signed["commissioning_status"] == "VERIFIED"
    assert signed["commissioning_attempt_count"] == 2

    for key in ("slider", "transom"):
        assert read_opening(api, designer,
                           world[key]["id"])["install_outcome"] == "INSTALLED"

    restated = read_quote(api, territory, world["quote"]["id"])
    assert restated["net_sales_cents"] == 86282
    assert restated["recognized_net_sales_cents"] == 86282
    assert read_territory(api, territory)["royalty_accrued_cents"] == 4746
