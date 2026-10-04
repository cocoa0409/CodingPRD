"""The complete route table: 48 operations under the /api prefix."""

from flask import Blueprint

import services_hosts as hosts
import services_members as members
import services_records as records
import services_reviews as reviews
import services_stays as stays
import services_windows as windows
import validation as v

api = Blueprint("api", __name__, url_prefix="/api")


def _body():
    return v.json_body()


# --- HostBusiness ----------------------------------------------------------

@api.post("/hosts")
def post_hosts():
    return hosts.create_host(v.principal(), _body())


@api.get("/hosts")
def get_hosts():
    return hosts.list_hosts(v.principal())


@api.get("/hosts/<host_id>")
def get_host(host_id):
    return hosts.get_host(v.principal(), host_id)


@api.get("/hosts/<host_id>/capacity_summary")
def get_host_capacity_summary(host_id):
    return hosts.capacity_summary(v.principal(), host_id)


@api.post("/hosts/<host_id>/decisions")
def post_host_decision(host_id):
    return hosts.host_decision(v.principal(), host_id, _body())


@api.patch("/hosts/<host_id>")
def patch_host(host_id):
    return hosts.patch_host(v.principal(), host_id, _body())


# --- HostParkingSite -------------------------------------------------------

@api.post("/hosts/<host_id>/parking-sites")
def post_parking_site(host_id):
    return hosts.create_site(v.principal(), host_id, _body())


@api.get("/hosts/<host_id>/parking-sites")
def get_parking_sites(host_id):
    return hosts.list_sites(v.principal(), host_id)


@api.patch("/hosts/<host_id>/parking-sites/<site_id>")
def patch_parking_site(host_id, site_id):
    return hosts.patch_site(v.principal(), host_id, site_id, _body())


@api.get("/hosts/<host_id>/parking-sites/<site_id>/availability")
def get_parking_site_availability(host_id, site_id):
    actor = v.principal()
    from_raw = v.query("from_date")
    to_raw = v.query("to_date")
    from_date = v.date_param(from_raw, "from_date") if from_raw is not None else None
    to_date = v.date_param(to_raw, "to_date") if to_raw is not None else None
    return hosts.site_availability(actor, host_id, site_id, from_date, to_date)


# --- Member ----------------------------------------------------------------

@api.post("/members")
def post_members():
    return members.create_member(v.principal(), _body())


@api.get("/members")
def get_members():
    return members.list_members(v.principal())


@api.get("/members/<member_id>")
def get_member(member_id):
    return members.get_member(v.principal(), member_id)


@api.post("/members/<member_id>/subscription_actions")
def post_subscription_action(member_id):
    return members.subscription_action(v.principal(), member_id, _body())


@api.post("/members/<member_id>/cancellations")
def post_member_cancellation(member_id):
    return members.cancel_subscription(v.principal(), member_id, _body())


# --- MemberVehicle ---------------------------------------------------------

@api.post("/members/<member_id>/vehicles")
def post_vehicle(member_id):
    return members.create_vehicle(v.principal(), member_id, _body())


@api.get("/members/<member_id>/vehicles")
def get_vehicles(member_id):
    return members.list_vehicles(v.principal(), member_id)


@api.patch("/members/<member_id>/vehicles/<vehicle_id>")
def patch_vehicle(member_id, vehicle_id):
    return members.patch_vehicle(v.principal(), member_id, vehicle_id, _body())


# --- HostAvailabilityWindow ------------------------------------------------

@api.post("/availability-windows")
def post_availability_window():
    return windows.create_window(v.principal(), _body())


@api.get("/hosts/<host_id>/availability-windows")
def get_host_availability_windows(host_id):
    return windows.list_host_windows(v.principal(), host_id)


@api.get("/availability-windows/<window_id>")
def get_availability_window(window_id):
    return windows.get_window(v.principal(), window_id)


@api.post("/availability-windows/<window_id>/amend")
def post_availability_window_amend(window_id):
    return windows.amend_window(v.principal(), window_id, _body())


@api.post("/availability-windows/<window_id>/cancellations")
def post_availability_window_cancellation(window_id):
    return windows.cancel_window(v.principal(), window_id, _body())


# --- StayRequest -----------------------------------------------------------

@api.post("/stay-requests")
def post_stay_requests():
    return stays.create_stay(v.principal(), _body())


@api.get("/stay-requests")
def get_stay_requests():
    return stays.list_stays(v.principal())


@api.get("/stay-requests/<request_id>")
def get_stay_request(request_id):
    return stays.get_stay(v.principal(), request_id)


@api.post("/stay-requests/<request_id>/decisions")
def post_stay_decision(request_id):
    return stays.decide_stay(v.principal(), request_id, _body())


@api.post("/stay-requests/<request_id>/cancellations")
def post_stay_cancellation(request_id):
    return stays.cancel_stay(v.principal(), request_id, _body())


@api.post("/stay-requests/<request_id>/counter_requests")
def post_counter_request(request_id):
    return stays.counter_request(v.principal(), request_id, _body())


@api.post("/stay-requests/<request_id>/check_ins")
def post_check_in(request_id):
    return stays.check_in(v.principal(), request_id, _body())


@api.post("/stay-requests/<request_id>/check_outs")
def post_check_out(request_id):
    return stays.check_out(v.principal(), request_id, _body())


@api.post("/stay-requests/<request_id>/no_show_records")
def post_no_show(request_id):
    return stays.record_no_show(v.principal(), request_id, _body())


# --- HostReview ------------------------------------------------------------

@api.post("/reviews")
def post_reviews():
    return reviews.create_review(v.principal(), _body())


@api.get("/reviews")
def get_reviews():
    return reviews.list_reviews(v.principal())


@api.get("/reviews/<review_id>")
def get_review(review_id):
    return reviews.get_review(v.principal(), review_id)


@api.post("/reviews/<review_id>/withdrawals")
def post_review_withdrawal(review_id):
    return reviews.withdraw_review(v.principal(), review_id, _body())


# --- Incident and ConductDisposition ---------------------------------------

@api.post("/incidents")
def post_incidents():
    return members.file_incident(v.principal(), _body())


@api.get("/incidents")
def get_incidents():
    return members.list_incidents(v.principal())


@api.get("/incidents/<incident_id>")
def get_incident(incident_id):
    return members.get_incident(v.principal(), incident_id)


@api.post("/incidents/<incident_id>/dispositions")
def post_incident_disposition(incident_id):
    return members.rule_on_incident(v.principal(), incident_id, _body())


@api.get("/members/<member_id>/dispositions")
def get_member_dispositions(member_id):
    return members.list_member_dispositions(v.principal(), member_id)


@api.get("/incidents/<incident_id>/dispositions")
def get_incident_dispositions(incident_id):
    return members.list_incident_dispositions(v.principal(), incident_id)


# --- HostPatronizationRecord ----------------------------------------------

@api.get("/patronization-records")
def get_patronization_records():
    return records.list_records(v.principal())


@api.post("/patronization-records")
def post_patronization_record():
    return records.create_record(v.principal(), _body())


@api.get("/patronization-records/<record_id>")
def get_patronization_record(record_id):
    return records.get_record(v.principal(), record_id)


@api.post("/patronization-records/<record_id>/verification")
def post_patronization_verification(record_id):
    return records.verify_record(v.principal(), record_id, _body())


# --- PlatformAdmin test-driving namespace ----------------------------------

@api.post("/_clock/set_current_utc")
def post_set_clock():
    return windows.set_clock(v.principal(), _body())


@api.post("/_members/<member_id>/conduct_injections")
def post_conduct_injection(member_id):
    return members.conduct_injection(v.principal(), member_id, _body())