"""Donor registry, donations with matching, and reallocation choice."""
from flask import request

import store
from envelope import ok, page_payload
from errors import bad_request, conflict, forbidden, invalid_state, not_found, stale, unprocessable
from security import actor, require_roles
from serializers import donation_json, donor_json
from services import funding as funding_service
from services import matching
from validators import as_enum, as_int, as_str, json_body, pagination_args, require_present


def _get_donation(donation_id):
    donation = store.donations.get(donation_id)
    if donation is None:
        raise not_found("Donation not found")
    return donation


def register(app):
    @app.route("/giving/donors", methods=["POST"])
    def create_donor():
        data = json_body()
        display_name = as_str(require_present(data, "display_name"), "display_name")
        email = as_str(require_present(data, "email"), "email")
        _, role = actor()
        require_roles(role, ("Anonymous",))
        if any(d["email"] == email for d in store.donors.values()):
            raise bad_request("email must be unique across donors")
        rec = store.base_record()
        rec.update({
            "display_name": display_name,
            "email": email,
            "lifetime_donated_cents": 0,
            "lifetime_refunded_cents": 0,
            "lifetime_reallocated_cents": 0,
        })
        store.donors[rec["id"]] = rec
        return ok(donor_json(rec), 201)

    @app.route("/giving/donors/<donor_id>", methods=["GET"])
    def get_donor(donor_id):
        user_id, role = actor()
        require_roles(role, ("PlatformAdmin", "Donor"))
        donor = store.donors.get(donor_id)
        if donor is None:
            raise not_found("Donor not found")
        if role == "Donor" and user_id != donor_id:
            raise forbidden("A donor may only read their own record")
        return ok(donor_json(donor), 200)

    @app.route("/giving/projects/<project_id>/donations", methods=["POST"])
    def create_donation(project_id):
        data = json_body()
        amount = as_int(require_present(data, "amount_cents"), "amount_cents")
        if amount < 1:
            raise bad_request("amount_cents must be at least 1")
        campaign_id = data.get("match_campaign_id")
        if campaign_id is not None:
            campaign_id = as_str(campaign_id, "match_campaign_id")
        user_id, role = actor()
        require_roles(role, ("Donor",))
        project = store.projects.get(project_id)
        if project is None:
            raise not_found("Project not found")
        donor = store.donors.get(user_id)
        if donor is None:
            raise not_found("Donor not found")
        campaign = None
        if campaign_id is not None:
            campaign = store.match_campaigns.get(campaign_id)
            if campaign is None:
                raise not_found("Match campaign not found")
        if project["status"] != "FUNDING":
            raise invalid_state("Donations land only on a FUNDING project")
        if campaign is not None and campaign["status"] != "ACTIVE":
            raise invalid_state("The named match campaign is not ACTIVE")
        now = store.logical_now()
        if not (now < project["funding_deadline"]):
            raise conflict("ERR_FUNDING_WINDOW_CLOSED", "The project's funding window has closed")
        if campaign is not None and not (campaign["starts_at"] <= now < campaign["ends_at"]):
            raise conflict("ERR_MATCH_WINDOW_CLOSED", "The campaign window does not cover now")
        if campaign is not None:
            school = store.schools.get(project["school_id"])
            target_type = campaign["target_type"]
            target_value = campaign["target_value"]
            matched_target = (
                (target_type == "SCHOOL" and target_value == project["school_id"])
                or (target_type == "SUBJECT" and target_value == project["subject"])
                or (
                    target_type == "STATE"
                    and school is not None
                    and target_value == school["state_code"]
                )
            )
            if not matched_target:
                raise unprocessable(
                    "ERR_MATCH_TARGET_MISMATCH", "The campaign target does not match the project"
                )
        remaining_need = project["goal_cents"] - funding_service.funded_cents(project)
        if amount < 100 or amount > remaining_need:
            raise unprocessable(
                "ERR_DONATION_EXCEEDS_REMAINING",
                "amount_cents is below 100 or exceeds the remaining need",
            )
        if campaign is not None and amount < campaign["min_donation_cents"]:
            raise unprocessable(
                "ERR_DONATION_BELOW_MATCH_MIN",
                "amount_cents is below the campaign's min_donation_cents",
            )
        rec = store.base_record()
        rec.update({
            "project_id": project_id,
            "donor_id": user_id,
            "kind": "DONOR",
            "amount_cents": amount,
            "match_campaign_id": campaign_id,
            "matched_cents": 0,
            "equity_fund_id": None,
            "status": "CAPTURED",
            "choice_deadline": None,
            "refund_reason": None,
        })
        store.donations[rec["id"]] = rec
        if campaign is not None:
            matching.apply_match(rec, campaign)
        donor["lifetime_donated_cents"] += amount
        store.touch(donor)
        funding_service.check_funded(project, now)
        return ok(donation_json(rec), 201)

    @app.route("/giving/donations/<donation_id>", methods=["GET"])
    def get_donation(donation_id):
        _, role = actor()
        require_roles(role, ("PlatformAdmin", "Donor", "Teacher", "Reviewer"))
        return ok(donation_json(_get_donation(donation_id)), 200)

    @app.route("/giving/donations", methods=["GET"])
    def list_donations():
        _, role = actor()
        require_roles(role, ("PlatformAdmin", "Donor"))
        donor_id = request.args.get("donor_id")
        project_id = request.args.get("project_id")
        status = request.args.get("status")
        match_campaign_id = request.args.get("match_campaign_id")
        equity_fund_id = request.args.get("equity_fund_id")
        rows = list(store.donations.values())
        if donor_id is not None:
            rows = [d for d in rows if d["donor_id"] == donor_id]
        if project_id is not None:
            rows = [d for d in rows if d["project_id"] == project_id]
        if status is not None:
            rows = [d for d in rows if d["status"] == status]
        if match_campaign_id is not None:
            rows = [d for d in rows if d["match_campaign_id"] == match_campaign_id]
        if equity_fund_id is not None:
            rows = [d for d in rows if d["equity_fund_id"] == equity_fund_id]
        rows.sort(key=lambda d: (d["created_at"], d["_seq"]))
        limit, offset = pagination_args()
        page, meta = page_payload([donation_json(d) for d in rows], limit, offset)
        return ok(page, 200, pagination=meta)

    @app.route("/giving/donations/<donation_id>/reallocation-choice", methods=["POST"])
    def reallocation_choice(donation_id):
        data = json_body()
        choice = as_enum(require_present(data, "choice"), "choice", ("REFUND", "REALLOCATE"))
        expected = as_int(
            require_present(data, "expected_donation_version"), "expected_donation_version"
        )
        fund_id = data.get("equity_fund_id")
        if fund_id is not None:
            fund_id = as_str(fund_id, "equity_fund_id")
        user_id, role = actor()
        require_roles(role, ("Donor",))
        donation = _get_donation(donation_id)
        if donation["donor_id"] != user_id:
            raise forbidden("A donor may only choose on their own donation")
        if expected != donation["version"]:
            raise stale("expected_donation_version does not match the donation version")
        if donation["status"] != "CHOICE_PENDING":
            raise invalid_state("A reallocation choice applies only from CHOICE_PENDING")
        now = store.logical_now()
        if not (now < donation["choice_deadline"]):
            raise conflict("ERR_CHOICE_WINDOW_EXPIRED", "The choice window has expired")
        donor = store.donors.get(user_id)
        if choice == "REFUND":
            donation["status"] = "REFUNDED"
            donation["refund_reason"] = "EXPIRED_CHOICE"
            if donor is not None:
                donor["lifetime_refunded_cents"] += donation["amount_cents"]
                store.touch(donor)
            store.touch(donation)
            return ok(donation_json(donation), 200)
        # REALLOCATE
        if fund_id is None:
            raise unprocessable(
                "ERR_INVALID_REALLOCATION_TARGET", "REALLOCATE requires equity_fund_id"
            )
        fund = store.equity_funds.get(fund_id)
        if fund is None:
            raise not_found("Equity fund not found")
        if fund["status"] != "ACTIVE" or not (fund["window_start"] <= now <= fund["window_end"]):
            raise unprocessable(
                "ERR_INVALID_REALLOCATION_TARGET",
                "Target fund is not ACTIVE or its window does not cover now",
            )
        donation["status"] = "REALLOCATED"
        donation["equity_fund_id"] = fund["id"]
        fund["remaining_cents"] += donation["amount_cents"]
        if (
            fund["status"] == "DEPLETED"
            and fund["remaining_cents"] > 0
            and fund["window_start"] <= now <= fund["window_end"]
        ):
            fund["status"] = "ACTIVE"
        store.touch(fund)
        if donor is not None:
            donor["lifetime_reallocated_cents"] += donation["amount_cents"]
            store.touch(donor)
        store.touch(donation)
        return ok(donation_json(donation), 200)
