import os

from flask import Flask, jsonify

from core import ApiError, envelope_error
import routes_members as rm
import routes_catalog as rc
import routes_commerce as rcom

app = Flask(__name__)


# ---------------- Error handling ----------------

@app.errorhandler(ApiError)
def handle_api_error(e):
    body, status = envelope_error(e.error_id, e.message, e.http_status)
    return jsonify(body), status


@app.errorhandler(404)
def handle_404(e):
    body, status = envelope_error("ERR_NOT_FOUND", "Referenced entity does not exist", 404)
    return jsonify(body), status


@app.errorhandler(405)
def handle_405(e):
    body, status = envelope_error("ERR_NOT_FOUND", "Referenced entity does not exist", 404)
    return jsonify(body), status


@app.errorhandler(400)
def handle_400(e):
    body, status = envelope_error("ERR_INVALID_REQUEST", "Invalid request payload", 400)
    return jsonify(body), status


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        body, status = envelope_error(e.error_id, e.message, e.http_status)
        return jsonify(body), status
    body, status = envelope_error("ERR_INVALID_REQUEST", str(e), 400)
    return jsonify(body), status


def wrap(fn):
    def handler(**kwargs):
        body, status = fn(**kwargs)
        return jsonify(body), status
    handler.__name__ = fn.__name__
    return handler


P = "/cinemas"

# ---------------- Clock ----------------
app.add_url_rule(f"{P}/_clock/set_current_utc", "set_clock", wrap(rm.set_clock), methods=["POST"])

# ---------------- Members ----------------
app.add_url_rule(f"{P}/members", "create_member", wrap(rm.create_member), methods=["POST"])
app.add_url_rule(f"{P}/members", "list_members", wrap(rm.list_members), methods=["GET"])
app.add_url_rule(f"{P}/members/<string:member_id>", "get_member", wrap(rm.get_member), methods=["GET"])
app.add_url_rule(f"{P}/members/<string:member_id>/activate", "activate_member", wrap(rm.activate_member), methods=["POST"])
app.add_url_rule(f"{P}/members/<string:member_id>/unsuspend", "unsuspend_member", wrap(rm.unsuspend_member_route), methods=["POST"])
app.add_url_rule(f"{P}/members/<string:member_id>/close", "close_member", wrap(rm.close_member), methods=["POST"])
app.add_url_rule(f"{P}/members/<string:member_id>/strikes", "list_member_strikes", wrap(rm.list_member_strikes), methods=["GET"])
app.add_url_rule(f"{P}/members/<string:member_id>/loyalty-ledger", "list_member_ledger", wrap(rm.list_member_ledger), methods=["GET"])
app.add_url_rule(f"{P}/members/<string:member_id>/loyalty-adjustments", "create_loyalty_adjustment", wrap(rm.create_loyalty_adjustment), methods=["POST"])
app.add_url_rule(f"{P}/members/<string:member_id>/subscriptions", "enroll", wrap(rm.enroll), methods=["POST"])
app.add_url_rule(f"{P}/members/<string:member_id>/subscriptions", "list_member_subscriptions", wrap(rm.list_member_subscriptions), methods=["GET"])
app.add_url_rule(f"{P}/members/<string:member_id>/reservations", "list_member_reservations", wrap(rc.list_member_reservations), methods=["GET"])
app.add_url_rule(f"{P}/members/<string:member_id>/concession-purchases", "list_member_concession_purchases", wrap(rcom.list_member_concession_purchases), methods=["GET"])

# ---------------- Subscription plans ----------------
app.add_url_rule(f"{P}/subscription-plans", "create_plan", wrap(rm.create_plan), methods=["POST"])
app.add_url_rule(f"{P}/subscription-plans/<string:plan_id>", "get_plan", wrap(rm.get_plan), methods=["GET"])
app.add_url_rule(f"{P}/subscription-plans/<string:plan_id>/publish", "publish_plan", wrap(rm.publish_plan), methods=["POST"])
app.add_url_rule(f"{P}/subscription-plans/<string:plan_id>/retire", "retire_plan", wrap(rm.retire_plan), methods=["POST"])
app.add_url_rule(f"{P}/subscription-plans/<string:plan_id>/subscriptions", "list_plan_subscriptions", wrap(rm.list_plan_subscriptions), methods=["GET"])

# ---------------- Subscriptions ----------------
app.add_url_rule(f"{P}/subscriptions", "list_subscriptions", wrap(rm.list_subscriptions), methods=["GET"])
app.add_url_rule(f"{P}/subscriptions/<string:subscription_id>", "get_subscription", wrap(rm.get_subscription), methods=["GET"])
app.add_url_rule(f"{P}/subscriptions/<string:subscription_id>/pause", "pause_subscription", wrap(rm.pause_subscription), methods=["POST"])
app.add_url_rule(f"{P}/subscriptions/<string:subscription_id>/resume", "resume_subscription", wrap(rm.resume_subscription_route), methods=["POST"])
app.add_url_rule(f"{P}/subscriptions/<string:subscription_id>/cancel", "cancel_subscription", wrap(rm.cancel_subscription_route), methods=["POST"])
app.add_url_rule(f"{P}/subscriptions/<string:subscription_id>/change-plan", "change_plan", wrap(rm.change_plan), methods=["POST"])
app.add_url_rule(f"{P}/subscriptions/<string:subscription_id>/credit-buckets", "list_subscription_buckets", wrap(rm.list_subscription_buckets), methods=["GET"])
app.add_url_rule(f"{P}/subscriptions/<string:subscription_id>/reservations", "list_subscription_reservations", wrap(rc.list_subscription_reservations), methods=["GET"])

# ---------------- Credit buckets ----------------
app.add_url_rule(f"{P}/credit-buckets", "list_buckets", wrap(rm.list_buckets), methods=["GET"])
app.add_url_rule(f"{P}/credit-buckets/<string:bucket_id>", "get_bucket", wrap(rm.get_bucket), methods=["GET"])
app.add_url_rule(f"{P}/credit-buckets/<string:bucket_id>/reservations", "list_bucket_reservations", wrap(rc.list_bucket_reservations), methods=["GET"])

# ---------------- Theaters / auditoriums / showtimes ----------------
app.add_url_rule(f"{P}/theaters", "create_theater", wrap(rc.create_theater), methods=["POST"])
app.add_url_rule(f"{P}/theaters/<string:theater_id>", "get_theater", wrap(rc.get_theater), methods=["GET"])
app.add_url_rule(f"{P}/theaters/<string:theater_id>/auditoriums", "create_auditorium", wrap(rc.create_auditorium), methods=["POST"])
app.add_url_rule(f"{P}/theaters/<string:theater_id>/auditoriums", "list_theater_auditoriums", wrap(rc.list_theater_auditoriums), methods=["GET"])
app.add_url_rule(f"{P}/theaters/<string:theater_id>/concession-purchases", "list_theater_concession_purchases", wrap(rcom.list_theater_concession_purchases), methods=["GET"])
app.add_url_rule(f"{P}/theaters/<string:theater_id>/settlement-reports", "create_settlement_report", wrap(rcom.create_settlement_report), methods=["POST"])
app.add_url_rule(f"{P}/theaters/<string:theater_id>/settlement-reports", "list_theater_settlement_reports", wrap(rcom.list_theater_settlement_reports), methods=["GET"])
app.add_url_rule(f"{P}/auditoriums", "list_auditoriums", wrap(rc.list_auditoriums), methods=["GET"])
app.add_url_rule(f"{P}/auditoriums/<string:auditorium_id>", "get_auditorium", wrap(rc.get_auditorium), methods=["GET"])
app.add_url_rule(f"{P}/auditoriums/<string:auditorium_id>/showtimes", "list_auditorium_showtimes", wrap(rc.list_auditorium_showtimes), methods=["GET"])
app.add_url_rule(f"{P}/showtimes", "create_showtime", wrap(rc.create_showtime), methods=["POST"])
app.add_url_rule(f"{P}/showtimes", "list_showtimes", wrap(rc.list_showtimes), methods=["GET"])
app.add_url_rule(f"{P}/showtimes/<string:showtime_id>", "get_showtime", wrap(rc.get_showtime), methods=["GET"])
app.add_url_rule(f"{P}/showtimes/<string:showtime_id>/open_sales", "open_sales", wrap(rc.open_sales), methods=["POST"])
app.add_url_rule(f"{P}/showtimes/<string:showtime_id>/cancel", "cancel_showtime", wrap(rc.cancel_showtime), methods=["POST"])
app.add_url_rule(f"{P}/showtimes/<string:showtime_id>/reservations", "list_showtime_reservations", wrap(rc.list_showtime_reservations), methods=["GET"])
app.add_url_rule(f"{P}/showtimes/<string:showtime_id>/settlement-lines", "list_showtime_settlement_lines", wrap(rcom.list_showtime_settlement_lines), methods=["GET"])

# ---------------- Reservations ----------------
app.add_url_rule(f"{P}/reservations", "create_reservation", wrap(rc.create_reservation), methods=["POST"])
app.add_url_rule(f"{P}/reservations", "list_reservations", wrap(rc.list_reservations), methods=["GET"])
app.add_url_rule(f"{P}/reservations/<string:reservation_id>", "get_reservation", wrap(rc.get_reservation), methods=["GET"])
app.add_url_rule(f"{P}/reservations/<string:reservation_id>/confirm", "confirm_reservation", wrap(rc.confirm_reservation), methods=["POST"])
app.add_url_rule(f"{P}/reservations/<string:reservation_id>/cancel", "cancel_reservation", wrap(rc.cancel_reservation), methods=["POST"])
app.add_url_rule(f"{P}/reservations/<string:reservation_id>/check_in", "check_in_reservation", wrap(rc.check_in_reservation), methods=["POST"])
app.add_url_rule(f"{P}/reservations/<string:reservation_id>/strikes", "list_reservation_strikes", wrap(rc.list_reservation_strikes), methods=["GET"])
app.add_url_rule(f"{P}/reservations/<string:reservation_id>/settlement-lines", "list_reservation_settlement_lines", wrap(rcom.list_reservation_settlement_lines), methods=["GET"])

# ---------------- Strikes ----------------
app.add_url_rule(f"{P}/strikes", "list_strikes", wrap(rc.list_strikes), methods=["GET"])
app.add_url_rule(f"{P}/strikes/<string:strike_id>", "get_strike", wrap(rc.get_strike), methods=["GET"])
app.add_url_rule(f"{P}/strikes/<string:strike_id>/reverse", "reverse_strike", wrap(rc.reverse_strike), methods=["POST"])

# ---------------- Concessions ----------------
app.add_url_rule(f"{P}/concession-purchases", "create_concession_purchase", wrap(rcom.create_concession_purchase), methods=["POST"])
app.add_url_rule(f"{P}/concession-purchases", "list_concession_purchases", wrap(rcom.list_concession_purchases), methods=["GET"])
app.add_url_rule(f"{P}/concession-purchases/<string:purchase_id>", "get_concession_purchase", wrap(rcom.get_concession_purchase), methods=["GET"])

# ---------------- Loyalty ledger ----------------
app.add_url_rule(f"{P}/loyalty-ledger", "list_ledger", wrap(rcom.list_ledger), methods=["GET"])
app.add_url_rule(f"{P}/loyalty-ledger/<string:entry_id>", "get_ledger_entry", wrap(rcom.get_ledger_entry), methods=["GET"])

# ---------------- Settlement ----------------
app.add_url_rule(f"{P}/settlement-reports", "list_settlement_reports", wrap(rcom.list_settlement_reports), methods=["GET"])
app.add_url_rule(f"{P}/settlement-reports/<string:report_id>", "get_settlement_report", wrap(rcom.get_settlement_report), methods=["GET"])
app.add_url_rule(f"{P}/settlement-reports/<string:report_id>/lines", "add_settlement_line", wrap(rcom.add_settlement_line), methods=["POST"])
app.add_url_rule(f"{P}/settlement-reports/<string:report_id>/lines", "list_report_lines", wrap(rcom.list_report_lines), methods=["GET"])
app.add_url_rule(f"{P}/settlement-reports/<string:report_id>/submit", "submit_settlement_report", wrap(rcom.submit_settlement_report), methods=["POST"])
app.add_url_rule(f"{P}/settlement-reports/<string:report_id>/acknowledge", "acknowledge_settlement_report", wrap(rcom.acknowledge_settlement_report), methods=["POST"])
app.add_url_rule(f"{P}/settlement-reports/<string:report_id>/dispute", "dispute_settlement_report", wrap(rcom.dispute_settlement_report), methods=["POST"])
app.add_url_rule(f"{P}/settlement-reports/<string:report_id>/revise", "revise_settlement_report", wrap(rcom.revise_settlement_report), methods=["POST"])
app.add_url_rule(f"{P}/settlement-lines", "list_settlement_lines", wrap(rcom.list_settlement_lines), methods=["GET"])
app.add_url_rule(f"{P}/settlement-lines/<string:line_id>", "get_settlement_line", wrap(rcom.get_settlement_line), methods=["GET"])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
