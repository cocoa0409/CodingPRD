"""Dealer, dealer-package and dealer cash-adjustment routes."""

from flask import request

import db
import middleware
import response
import serializers
from errors import ApiError
from routes._common import endpoint, q
from services import calculations as calc
from services import factory, queries, workflows
from util import add_days, fmt_ts

CHANNEL_MANAGER = ["ChannelManager"]
FUNDING = ["FundingAnalyst"]
DEALER = ["Dealer"]
READ_DEALERS = ["ChannelManager", "FundingAnalyst", "PlatformAdmin"]
READ_PACKAGES = ["Dealer", "FundingAnalyst", "ChannelManager", "PlatformAdmin"]


def register(app):

    # --- Dealers ----------------------------------------------------------

    @endpoint(app, "POST", "/alarm-funding/dealers", ["ChannelManager", "PlatformAdmin"])
    def create_dealer(actor):
        body = middleware.body_or_empty(request)
        middleware.required(body, "dealer_code", "legal_name", "holdback_rate", "quality_tier")
        dealer_code = middleware.as_str(body["dealer_code"], "dealer_code")
        legal_name = middleware.as_str(body["legal_name"], "legal_name")
        holdback_rate = middleware.as_number(body["holdback_rate"], "holdback_rate", 0.0, 0.5)
        quality_tier = middleware.as_enum(body["quality_tier"], "quality_tier",
                                          {"TIER_1", "TIER_2", "TIER_3"})
        # Priority 9 — the ceiling is a fiscal gate on the dealer's own registration.
        if holdback_rate > 0.5:
            raise ApiError("ERR_HOLDBACK_RATE_EXCEEDS_CEILING")
        dealer = factory.make_dealer(dealer_code, legal_name, holdback_rate, quality_tier)
        return response.envelope_object(serializers.serialize("dealer", dealer)), 201

    @endpoint(app, "GET", "/alarm-funding/dealers", READ_DEALERS)
    def list_dealers(actor):
        rows = db.state.all("dealers")
        code = q("dealer_code")
        standing = q("standing")
        if code is not None:
            rows = [r for r in rows if r.get("dealer_code") == code]
        if standing is not None:
            rows = [r for r in rows if r.get("standing") == standing]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("dealer", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/dealers/<id>", READ_DEALERS + ["Dealer"])
    def read_dealer(actor, id):
        dealer = middleware.resolve("dealers", id)
        return response.envelope_object(serializers.serialize("dealer", dealer)), 200

    @endpoint(app, "POST", "/alarm-funding/dealers/<id>/chargeback-rate-recompute", FUNDING)
    def recompute_rate(actor, id):
        dealer = middleware.resolve("dealers", id)
        body = middleware.body_or_empty(request)
        expected = body.get("expected_dealer_version")
        if expected is not None and int(expected) != dealer.get("version"):
            raise ApiError("ERR_STALE_VERSION")
        calc.dealer_chargeback_rate(dealer)
        calc.dealer_standing_derivation(dealer)
        db.bump(dealer)
        return response.envelope_object(serializers.serialize("dealer", dealer)), 200

    @endpoint(app, "POST", "/alarm-funding/dealers/<id>/suspend", FUNDING)
    def suspend_dealer(actor, id):
        dealer = middleware.resolve("dealers", id)
        if dealer.get("standing") not in ("ACTIVE", "WATCH"):
            raise ApiError("ERR_INVALID_STATE")
        dealer["standing"] = "SUSPENDED"
        db.bump(dealer)
        return response.envelope_object(serializers.serialize("dealer", dealer)), 200

    @endpoint(app, "POST", "/alarm-funding/dealers/<id>/reinstate", FUNDING)
    def reinstate_dealer(actor, id):
        dealer = middleware.resolve("dealers", id)
        if dealer.get("standing") != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE")
        if dealer.get("chargeback_balance_due_cents", 0) != 0:
            raise ApiError("ERR_INVALID_STATE",
                           "The dealer balance due must be exactly zero before reinstatement.")
        calc.dealer_chargeback_rate(dealer)
        calc.dealer_standing_derivation(dealer)
        db.bump(dealer)
        return response.envelope_object(serializers.serialize("dealer", dealer)), 200

    @endpoint(app, "POST", "/alarm-funding/dealers/<id>/holdback-releases", FUNDING)
    def holdback_release(actor, id):
        dealer = middleware.resolve("dealers", id)
        body = middleware.body_or_empty(request)
        middleware.required(body, "amount_cents")
        amount = middleware.as_int(body["amount_cents"], "amount_cents")
        moved = min(amount, dealer.get("holdback_reserve_cents", 0))
        dealer["holdback_reserve_cents"] = dealer.get("holdback_reserve_cents", 0) - moved
        dealer["chargeback_balance_due_cents"] = dealer.get("chargeback_balance_due_cents", 0) + moved
        calc.dealer_standing_derivation(dealer)
        db.bump(dealer)
        return response.envelope_object(serializers.serialize("dealer", dealer)), 200

    @endpoint(app, "POST", "/alarm-funding/dealers/<id>/holdback-reversals", FUNDING)
    def holdback_reversal(actor, id):
        dealer = middleware.resolve("dealers", id)
        body = middleware.body_or_empty(request)
        middleware.required(body, "amount_cents")
        amount = middleware.as_int(body["amount_cents"], "amount_cents")
        moved = min(amount, dealer.get("chargeback_balance_due_cents", 0))
        dealer["chargeback_balance_due_cents"] = dealer.get("chargeback_balance_due_cents", 0) - moved
        dealer["holdback_reserve_cents"] = dealer.get("holdback_reserve_cents", 0) + moved
        calc.dealer_standing_derivation(dealer)
        db.bump(dealer)
        return response.envelope_object(serializers.serialize("dealer", dealer)), 200

    # --- Dealer packages --------------------------------------------------

    @endpoint(app, "POST", "/alarm-funding/dealer-packages", ["Dealer", "FundingAnalyst"])
    def create_package(actor):
        body = middleware.body_or_empty(request)
        middleware.required(body, "package_reference")
        package_reference = middleware.as_str(body["package_reference"], "package_reference")
        supplied_dealer_id = body.get("dealer_id")
        if supplied_dealer_id is not None:
            dealer = middleware.require_fk("dealers", supplied_dealer_id, "dealer_id")
        else:
            if actor.role != "Dealer":
                raise ApiError("ERR_INVALID_REQUEST",
                               "dealer_id is required unless the acting role is Dealer.")
            dealer = db.state.get("dealers", actor.user_id)
            if dealer is None:
                raise ApiError("ERR_ENTITY_NOT_FOUND")
        # Priority 6 before priority 7, 9 (PRD §2.10).
        if dealer.get("standing") == "SUSPENDED":
            raise ApiError("ERR_DEALER_PACKAGE_SUSPENDED")
        _assert_rate_cap(dealer)
        for package in db.state.dealer_packages.values():
            if package.get("dealer_id") == dealer["id"] and package.get("package_reference") == package_reference:
                raise ApiError("ERR_PACKAGE_REFERENCE_DUPLICATE")
        package = factory.make_dealer_package(dealer["id"], package_reference)
        return response.envelope_object(serializers.serialize("dealer_package", package)), 201

    @endpoint(app, "GET", "/alarm-funding/dealer-packages", READ_PACKAGES)
    def list_packages(actor):
        rows = db.state.all("dealer_packages")
        dealer_id = q("dealer_id")
        status = q("package_status")
        if dealer_id is not None:
            rows = [r for r in rows if r.get("dealer_id") == dealer_id]
        if status is not None:
            rows = [r for r in rows if r.get("package_status") == status]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("dealer_package", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/dealer-packages/<id>", READ_PACKAGES)
    def read_package(actor, id):
        package = middleware.resolve("dealer_packages", id)
        return response.envelope_object(serializers.serialize("dealer_package", package)), 200

    @endpoint(app, "POST", "/alarm-funding/dealer-packages/<id>/submit", DEALER)
    def submit_package(actor, id):
        package = middleware.resolve("dealer_packages", id)
        dealer = db.state.get("dealers", package["dealer_id"])
        if package.get("package_status") != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        if dealer is not None and dealer.get("standing") == "SUSPENDED":
            raise ApiError("ERR_DEALER_PACKAGE_SUSPENDED")
        if dealer is not None:
            _assert_rate_cap(dealer)
        if not queries.children_of_package(package["id"]):
            raise ApiError("ERR_INVALID_STATE",
                           "A package may be submitted only when at least one child contract exists.")
        package["package_status"] = "UNDER_REVIEW"
        package["submitted_at"] = fmt_ts(db.now())
        db.bump(package)
        return response.envelope_object(serializers.serialize("dealer_package", package)), 200

    @endpoint(app, "POST", "/alarm-funding/dealer-packages/<id>/withdraw", DEALER)
    def withdraw_package(actor, id):
        package = middleware.resolve("dealer_packages", id)
        if package.get("package_status") != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE")
        for child in queries.children_of_package(package["id"]):
            if child.get("contract_status") in ("CANCELLED", "ASSUMED"):
                raise ApiError("ERR_INVALID_STATE",
                               "A package may be withdrawn only while no child is terminal.")
        package["package_status"] = "DRAFT"
        package["submitted_at"] = None
        db.bump(package)
        return response.envelope_object(serializers.serialize("dealer_package", package)), 200

    @endpoint(app, "POST", "/alarm-funding/dealer-packages/<id>/approve", FUNDING)
    def approve_package(actor, id):
        package = middleware.resolve("dealer_packages", id)
        body = middleware.body_or_empty(request)
        expected = body.get("expected_dealer_package_version")
        if expected is not None and int(expected) != package.get("version"):
            raise ApiError("ERR_STALE_VERSION")
        if package.get("package_status") != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE")
        if not queries.children_of_package(package["id"]):
            raise ApiError("ERR_MONITORING_ACCOUNT_NOT_FOUND")
        dealer = db.state.get("dealers", package["dealer_id"])
        if dealer is not None and dealer.get("standing") == "SUSPENDED":
            raise ApiError("ERR_DEALER_STANDING_SUSPENDED")
        for other in db.state.dealer_packages.values():
            if other["id"] == package["id"]:
                continue
            if other.get("dealer_id") == package["dealer_id"] \
                    and other.get("package_reference") == package.get("package_reference"):
                raise ApiError("ERR_PACKAGE_REFERENCE_DUPLICATE")
        children = queries.children_of_package(package["id"])
        for child in children:
            if child.get("capex_cents", 0) == 0:
                calc.funding_fee(child, dealer)
        calc.allowed_holdback_rate_floor_ceiling_binding(package, dealer)
        posture, holdback = calc.package_funding_posture(package)
        package["package_holdback_cents"] = holdback
        package["expires_at"] = fmt_ts(add_days(db.now(), calc.FUNDING_WINDOW_DAYS))
        package["package_status"] = "APPROVED"
        db.bump(package)
        return response.envelope_object(serializers.serialize("dealer_package", package)), 200

    @endpoint(app, "POST", "/alarm-funding/dealer-packages/<id>/reopen", FUNDING)
    def reopen_package(actor, id):
        package = middleware.resolve("dealer_packages", id)
        if package.get("package_status") != "APPROVED":
            raise ApiError("ERR_INVALID_STATE")
        if package.get("funded_count", 0) != 0:
            raise ApiError("ERR_INVALID_STATE",
                           "A package may be reopened only while its funded count is zero.")
        package["package_status"] = "UNDER_REVIEW"
        package["expires_at"] = None
        db.bump(package)
        return response.envelope_object(serializers.serialize("dealer_package", package)), 200

    @endpoint(app, "POST", "/alarm-funding/dealer-packages/<id>/fund", FUNDING)
    def fund_package(actor, id):
        package = middleware.resolve("dealer_packages", id)
        body = middleware.body_or_empty(request)
        expected = body.get("expected_dealer_package_version")
        if expected is not None and int(expected) != package.get("version"):
            raise ApiError("ERR_STALE_VERSION")

        workflows.observe_package_expiry(package)
        if package.get("package_status") == "EXPIRED":
            raise ApiError("ERR_FUNDING_WINDOW_EXPIRED")
        if package.get("package_status") != "APPROVED":
            raise ApiError("ERR_PACKAGE_NOT_APPROVED")
        children = queries.children_of_package(package["id"])
        if not children:
            raise ApiError("ERR_MONITORING_ACCOUNT_NOT_FOUND")
        expires_at = middleware.as_timestamp(package.get("expires_at"), "expires_at") \
            if package.get("expires_at") else None
        if expires_at is not None and db.now() > expires_at:
            raise ApiError("ERR_FUNDING_WINDOW_EXPIRED")

        posture = workflows.fund_package_cascade(package)
        if posture == "DECLINED":
            # PRD §3.3 — a fund attempt in a DECLINED posture is refused outright; the
            # gate-failing children stay frozen but no child is activated.
            raise ApiError("ERR_NO_FUNDABLE_CONTRACT")
        calc.refresh_package_rollups(package)
        package["closed_at"] = fmt_ts(db.now())
        package["package_status"] = "FUNDED"
        dealer = db.state.get("dealers", package["dealer_id"])
        if dealer is not None:
            dealer["funded_package_count"] = len([
                p for p in db.state.dealer_packages.values()
                if p.get("dealer_id") == dealer["id"] and p.get("package_status") == "FUNDED"
            ])
            db.bump(dealer)
        db.bump(package)
        return response.envelope_object(serializers.serialize("dealer_package", package)), 200

    @endpoint(app, "POST", "/alarm-funding/dealer-packages/<id>/decline", FUNDING)
    def decline_package(actor, id):
        package = middleware.resolve("dealer_packages", id)
        if package.get("package_status") != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE")
        workflows.decline_package_cascade(package)
        package["closed_at"] = fmt_ts(db.now())
        package["package_status"] = "DECLINED"
        calc.refresh_package_rollups(package)
        db.bump(package)
        return response.envelope_object(serializers.serialize("dealer_package", package)), 200

    @endpoint(app, "POST", "/alarm-funding/dealer-packages/<id>/contracts",
              ["Dealer", "FundingAnalyst"])
    def declare_contract(actor, id):
        package = middleware.resolve("dealer_packages", id)
        from routes.contracts import build_contract
        contract = build_contract(package["dealer_id"], "DEALER", package["id"])
        package["submitted_contract_count"] = len(queries.children_of_package(package["id"]))
        db.bump(package)
        return response.envelope_object(serializers.serialize("contract", contract)), 201


def _assert_rate_cap(dealer):
    rate = calc.dealer_rate_from_counters(dealer)
    if dealer.get("funding_package_count_12mo", 0) > 0 and rate > float(calc.DEALER_CHARGEBACK_RATE_CAP_PERCENT):
        raise ApiError("ERR_DEALER_CHARGEBACK_RATE_EXCEEDED")