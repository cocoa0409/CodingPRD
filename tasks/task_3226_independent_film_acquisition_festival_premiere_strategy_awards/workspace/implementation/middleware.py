# Auth middleware: X-User-ID / X-User-Role, plus RBAC registry.

from flask import request

from errors import ApiError

ROLES = {
    "PlatformAdmin",
    "AcquisitionExec",
    "FestivalProgrammer",
    "DistributionExec",
    "AwardsStrategist",
    "TalentCoordinator",
    "ParticipationAccountant",
}

ALL_ROLES = sorted(ROLES)

ADMIN_ONLY = ["PlatformAdmin"]

# (METHOD, normalized PATH with {params}) -> allowed roles
ROLE_MAP = {
    ("POST", "/_clock/set_current_utc"): ["PlatformAdmin"],
    ("POST", "/films"): ["PlatformAdmin"],
    ("GET", "/films"): ALL_ROLES,
    ("GET", "/films/{film_id}"): ALL_ROLES,
    ("GET", "/films/{film_id}/premiere-slots"):
        ["PlatformAdmin", "AcquisitionExec", "FestivalProgrammer", "DistributionExec"],
    ("POST", "/films/{film_id}/pass"): ["AcquisitionExec"],
    ("POST", "/films/{film_id}/archive"): ["DistributionExec"],
    ("POST", "/films/{film_id}/offers"): ["AcquisitionExec"],
    ("GET", "/films/{film_id}/offers"):
        ["AcquisitionExec", "PlatformAdmin", "ParticipationAccountant"],
    ("GET", "/films/{film_id}/offers/{offer_id}"):
        ["AcquisitionExec", "PlatformAdmin", "ParticipationAccountant"],
    ("POST", "/films/{film_id}/offers/{offer_id}/counter"): ["AcquisitionExec"],
    ("POST", "/films/{film_id}/offers/{offer_id}/accept"): ["AcquisitionExec"],
    ("POST", "/films/{film_id}/offers/{offer_id}/reject"): ["AcquisitionExec"],
    ("POST", "/films/{film_id}/offers/{offer_id}/withdraw"): ["AcquisitionExec"],
    ("POST", "/territories"): ["PlatformAdmin"],
    ("GET", "/territories"): ["PlatformAdmin", "AcquisitionExec", "DistributionExec"],
    ("GET", "/territories/{territory_id}"):
        ["PlatformAdmin", "AcquisitionExec", "DistributionExec"],
    ("POST", "/festivals"): ["PlatformAdmin"],
    ("GET", "/festivals/{festival_id}"):
        ["PlatformAdmin", "FestivalProgrammer", "AcquisitionExec", "DistributionExec"],
    ("POST", "/festivals/{festival_id}/premiere-slots"): ["FestivalProgrammer"],
    ("GET", "/festivals/{festival_id}/premiere-slots"):
        ["PlatformAdmin", "FestivalProgrammer", "AcquisitionExec", "DistributionExec"],
    ("GET", "/festivals/{festival_id}/premiere-slots/{slot_id}"):
        ["PlatformAdmin", "FestivalProgrammer", "AcquisitionExec", "DistributionExec"],
    ("POST", "/festivals/{festival_id}/premiere-slots/{slot_id}/hold"): ["FestivalProgrammer"],
    ("POST", "/festivals/{festival_id}/premiere-slots/{slot_id}/book"): ["FestivalProgrammer"],
    ("POST", "/festivals/{festival_id}/premiere-slots/{slot_id}/release-hold"): ["FestivalProgrammer"],
    ("POST", "/festivals/{festival_id}/premiere-slots/{slot_id}/cancel"): ["FestivalProgrammer"],
    ("GET", "/premiere-slots/{slot_id}"):
        ["PlatformAdmin", "FestivalProgrammer", "AcquisitionExec", "DistributionExec"],
    ("GET", "/premiere-slots"):
        ["PlatformAdmin", "FestivalProgrammer", "AcquisitionExec", "DistributionExec"],
    ("GET", "/offers/{offer_id}"):
        ["PlatformAdmin", "AcquisitionExec", "ParticipationAccountant"],
    ("GET", "/offers"):
        ["PlatformAdmin", "AcquisitionExec", "ParticipationAccountant"],
    ("GET", "/rights-grants/{grant_id}"):
        ["PlatformAdmin", "AcquisitionExec", "DistributionExec", "ParticipationAccountant"],
    ("GET", "/rights-grants"):
        ["PlatformAdmin", "AcquisitionExec", "DistributionExec", "ParticipationAccountant"],
    ("GET", "/deals/{deal_id}"):
        ["PlatformAdmin", "AcquisitionExec", "DistributionExec", "AwardsStrategist",
         "ParticipationAccountant"],
    ("GET", "/deals"):
        ["PlatformAdmin", "AcquisitionExec", "DistributionExec", "AwardsStrategist",
         "ParticipationAccountant"],
    ("GET", "/films/{film_id}/deals"):
        ["PlatformAdmin", "AcquisitionExec", "DistributionExec", "AwardsStrategist",
         "ParticipationAccountant"],
    ("POST", "/deals/{deal_id}/report-theatrical-spend"): ["DistributionExec"],
    ("GET", "/deals/{deal_id}/rights-grants"):
        ["PlatformAdmin", "AcquisitionExec", "DistributionExec", "ParticipationAccountant"],
    ("POST", "/films/{film_id}/release-plans"): ["DistributionExec"],
    ("GET", "/films/{film_id}/release-plans"):
        ["PlatformAdmin", "DistributionExec", "AwardsStrategist"],
    ("GET", "/films/{film_id}/release-plans/{plan_id}"):
        ["PlatformAdmin", "DistributionExec", "AwardsStrategist"],
    ("POST", "/films/{film_id}/release-plans/{plan_id}/open"): ["DistributionExec"],
    ("POST", "/films/{film_id}/release-plans/{plan_id}/pull"): ["DistributionExec"],
    ("GET", "/release-plans/{plan_id}"):
        ["PlatformAdmin", "DistributionExec", "AwardsStrategist"],
    ("GET", "/release-plans"):
        ["PlatformAdmin", "DistributionExec", "AwardsStrategist"],
    ("POST", "/release-plans/{plan_id}/market-screenings"): ["DistributionExec"],
    ("GET", "/release-plans/{plan_id}/market-screenings"):
        ["PlatformAdmin", "DistributionExec"],
    ("POST", "/release-plans/{plan_id}/market-screenings/{screening_id}/report"):
        ["DistributionExec"],
    ("GET", "/market-screenings/{screening_id}"): ["PlatformAdmin", "DistributionExec"],
    ("GET", "/market-screenings"): ["PlatformAdmin", "DistributionExec"],
    ("POST", "/films/{film_id}/awards-campaigns"): ["AwardsStrategist"],
    ("GET", "/films/{film_id}/awards-campaigns"):
        ["PlatformAdmin", "AwardsStrategist", "TalentCoordinator", "ParticipationAccountant"],
    ("GET", "/awards-campaigns/{campaign_id}"):
        ["PlatformAdmin", "AwardsStrategist", "TalentCoordinator", "ParticipationAccountant"],
    ("GET", "/awards-campaigns"):
        ["PlatformAdmin", "AwardsStrategist", "TalentCoordinator", "ParticipationAccountant"],
    ("POST", "/films/{film_id}/awards-campaigns/{campaign_id}/activate"): ["AwardsStrategist"],
    ("POST", "/films/{film_id}/awards-campaigns/{campaign_id}/submit"): ["AwardsStrategist"],
    ("POST", "/films/{film_id}/awards-campaigns/{campaign_id}/conclude"): ["AwardsStrategist"],
    ("POST", "/awards-campaigns/{campaign_id}/spends"): ["AwardsStrategist"],
    ("GET", "/awards-campaigns/{campaign_id}/spends"):
        ["PlatformAdmin", "AwardsStrategist", "ParticipationAccountant"],
    ("GET", "/campaign-spends/{spend_id}"):
        ["PlatformAdmin", "AwardsStrategist", "ParticipationAccountant"],
    ("GET", "/campaign-spends"):
        ["PlatformAdmin", "AwardsStrategist", "ParticipationAccountant"],
    ("POST", "/films/{film_id}/talent-obligations"): ["TalentCoordinator"],
    ("GET", "/films/{film_id}/talent-obligations"):
        ["PlatformAdmin", "TalentCoordinator", "AwardsStrategist"],
    ("POST", "/films/{film_id}/talent-obligations/{obligation_id}/confirm"): ["TalentCoordinator"],
    ("POST", "/films/{film_id}/talent-obligations/{obligation_id}/fulfill"): ["TalentCoordinator"],
    ("POST", "/films/{film_id}/talent-obligations/{obligation_id}/waive"): ["AwardsStrategist"],
    ("GET", "/talent-obligations/{obligation_id}"):
        ["PlatformAdmin", "TalentCoordinator", "AwardsStrategist"],
    ("GET", "/talent-obligations"):
        ["PlatformAdmin", "TalentCoordinator", "AwardsStrategist"],
    ("POST", "/films/{film_id}/statements"): ["ParticipationAccountant"],
    ("GET", "/films/{film_id}/statements"):
        ["PlatformAdmin", "ParticipationAccountant"],
    ("GET", "/films/{film_id}/statements/{statement_id}"):
        ["PlatformAdmin", "ParticipationAccountant"],
    ("POST", "/films/{film_id}/statements/{statement_id}/finalize"): ["ParticipationAccountant"],
    ("GET", "/statements/{statement_id}"):
        ["PlatformAdmin", "ParticipationAccountant"],
    ("GET", "/statements"):
        ["PlatformAdmin", "ParticipationAccountant"],
}


def authenticate():
    """Return (user_id, role) or raise ApiError."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "Missing or invalid X-User-Role / X-User-ID headers",
        )
    return user_id, role


def authorize(path_template):
    """Check role against ROLE_MAP for the given (method, path_template)."""
    user_id, role = authenticate()
    allowed = ROLE_MAP.get((request.method, path_template))
    if allowed is None:
        raise ApiError("ERR_NOT_FOUND", "resource not found")
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", "Role not permitted for this endpoint")
    return user_id, role
