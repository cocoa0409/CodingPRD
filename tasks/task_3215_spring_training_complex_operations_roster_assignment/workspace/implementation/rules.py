"""Constants, the endpoint registry and the role map.

The registry is a declarative read over the scaffold endpoint table; every
route the scaffold declares has an entry here and exactly one handler.
"""

# Dimension conversions -----------------------------------------------------
DAY = 86400
HOUR = 3600
MINUTE = 60

# Numeric constants ---------------------------------------------------------
DURATION_UNITS = 3600          # seconds spanned by one game duration unit
RESTRICTED_PCT_OF_EFFECTIVE = 95
RESTRICTED_PCT_OF_RAW = 85
TRAVEL_RADIUS_LIMIT_MILES = 250

TIER_MULTIPLIER_PERMILLE = {"LOCAL": 100, "REGIONAL": 130, "NATIONAL": 165}
MATCH_POINTS_DIVISOR = 10
COMMITMENT_POINTS_DIVISOR = 100
FINAL_DIVISOR = 1000
JV_POINTS_CAP = 5000
REHAB_POINTS_DEBIT = 100
COMMITMENT_POINTS_CAP = 2000
MAJOR_WEIGHT = 5
MINOR_WEIGHT = 2

MODE_RADIUS_DISCOUNT = {
    "AUTO": {100: 0, 300: 10, 1000: 20},
    "AIR": {100: 0, 300: 5, 1000: 10},
    "BUS": {100: 0, 300: 15, 1000: 30},
}
HOLDBACK_PERMILLE = 50

OPTION_EQUIVALENT_YEARS_OFFSET = 0
OPTION_DECISION_BURDEN_CAP = 2
OPTION_ELIGIBILITY_THRESHOLD = 3

WAIVER_RULE_DAYS_LONG = 15
WAIVER_RULE_DAYS_SHORT = 8
WAIVER_BUMP_DIVISOR_CENTS = 30000
WAIVER_CLAIM_CAP_DAYS = 21
WAIVERS_REQUIRED_CREDIT_THRESHOLD = 5
MINOR_BUCKET_CREDIT = 3
MAJOR_BUCKET_CREDIT = 5

PHASE_CATCH_ALLOWANCE_PERMILLE = {
    "PHASE_1": 100,
    "PHASE_2": 105,
    "PHASE_3": 125,
    "PHASE_4": 150,
    "PHASE_LIVE": 175,
    "SHUTDOWN": 0,
}
STEP_TOLERANCE_PER_UNIT = 2
DAY_OF_GAME_REQUIRED_THROWS = 30
AGE_CAP_DAYS = 7

DEFAULT_REPORT_BASE_DATE = "2026-02-10T00:00:00Z"
PITCHER_CATCHER_LEAD_DAYS = 14
POSITION_PLAYER_LEAD_DAYS = 21
GUEST_INSTRUCTOR_EXTRA_DAYS = 7
FINAL_GRACE_BASE_DAYS = 14
REHAB_GRACE_DIVISOR = 10

BREAKOUT_BAILOUT_DAYS = 90

PHYSICAL_LEAD_DAYS = 5
PHYSICAL_CLEARANCE_BUFFER_DAYS = 2

ROLES = (
    "PlatformAdmin",
    "ComplexDirector",
    "CommunityLiaison",
    "FieldCoordinator",
    "PitchingCoordinator",
    "TravelCoordinator",
    "TeamPhysician",
    "RosterManager",
    "MinorLeagueCoordinator",
    "Analytics",
    "Player",
)

ROLE_MAP = {
    "platform_admin": "PlatformAdmin",
    "complex_director": "ComplexDirector",
    "community_liaison": "CommunityLiaison",
    "field_coordinator": "FieldCoordinator",
    "pitching_coordinator": "PitchingCoordinator",
    "travel_coordinator": "TravelCoordinator",
    "team_physician": "TeamPhysician",
    "roster_manager": "RosterManager",
    "minor_league_coordinator": "MinorLeagueCoordinator",
    "analytics": "Analytics",
    "player": "Player",
}

R = ROLE_MAP

# Every read role shares one operational roster.
ALL_READ = ["PlatformAdmin", "ComplexDirector", "CommunityLiaison", "FieldCoordinator",
            "PitchingCoordinator", "TravelCoordinator", "TeamPhysician", "RosterManager",
            "MinorLeagueCoordinator", "Analytics", "Player"]

# Registry entries:
#   (method, pattern, roles, handler, response_type, status, paginated)
# A handler returning None leaves the data payload empty.
ENDPOINT_TABLE = [
    # --- logical clock -----------------------------------------------------
    ("POST", "/camp-ops/_clock/set_current_utc", [R["platform_admin"]],
     "set_clock", "object", 200, False),

    # --- Complex -----------------------------------------------------------
    ("POST", "/camp-ops/complexes", [R["platform_admin"]],
     "create_complex", "object", 201, False),
    ("GET", "/camp-ops/complexes/<complex_id>", ALL_READ,
     "get_complex", "object", 200, False),
    ("GET", "/camp-ops/complexes", [R["platform_admin"], R["complex_director"], R["analytics"]],
     "list_complexes", "array", 200, True),
    ("POST", "/camp-ops/complexes/<complex_id>/field-maintenance", [R["complex_director"]],
     "field_maintenance", "object", 200, False),
    ("POST", "/camp-ops/complexes/<complex_id>/posture-sweeps",
     [R["complex_director"], R["platform_admin"]],
     "posture_sweep", "object", 200, False),

    # --- CommunityAgreement ------------------------------------------------
    ("POST", "/camp-ops/community-agreements", [R["community_liaison"], R["platform_admin"]],
     "create_community_agreement", "object", 201, False),
    ("GET", "/camp-ops/community-agreements/<agreement_id>",
     [R["community_liaison"], R["platform_admin"], R["complex_director"], R["analytics"]],
     "get_community_agreement", "object", 200, False),
    ("GET", "/camp-ops/community-agreements",
     [R["community_liaison"], R["platform_admin"], R["analytics"]],
     "list_community_agreements", "array", 200, True),
    ("GET", "/camp-ops/complexes/<complex_id>/community-agreements",
     [R["community_liaison"], R["platform_admin"], R["complex_director"]],
     "list_complex_community_agreements", "array", 200, False),
    ("POST", "/camp-ops/community-agreements/<agreement_id>/activate", [R["community_liaison"]],
     "activate_agreement", "object", 200, False),
    ("POST", "/camp-ops/community-agreements/<agreement_id>/revert-to-draft", [R["community_liaison"]],
     "revert_agreement_to_draft", "object", 200, False),
    ("POST", "/camp-ops/community-agreements/<agreement_id>/terminate", [R["community_liaison"]],
     "terminate_agreement", "object", 200, False),

    # --- Player ------------------------------------------------------------
    ("POST", "/camp-ops/players", [R["platform_admin"], R["roster_manager"]],
     "create_player", "object", 201, False),
    ("GET", "/camp-ops/players/<player_id>", ALL_READ,
     "get_player", "object", 200, False),
    ("GET", "/camp-ops/players", [R["platform_admin"], R["roster_manager"], R["analytics"]],
     "list_players", "array", 200, True),
    ("GET", "/camp-ops/complexes/<complex_id>/players",
     [R["platform_admin"], R["roster_manager"], R["complex_director"], R["analytics"]],
     "list_complex_players", "array", 200, False),
    ("POST", "/camp-ops/players/<player_id>/clearance/pend", [R["team_physician"]],
     "pend_clearance", "object", 200, False),

    # --- PlayerRosterRecord ------------------------------------------------
    ("POST", "/camp-ops/players/<player_id>/roster-record", [R["roster_manager"]],
     "create_roster_record", "object", 201, False),
    ("GET", "/camp-ops/roster-records/<record_id>",
     [R["platform_admin"], R["roster_manager"], R["minor_league_coordinator"], R["analytics"]],
     "get_roster_record", "object", 200, False),
    ("GET", "/camp-ops/roster-records",
     [R["platform_admin"], R["roster_manager"], R["analytics"]],
     "list_roster_records", "array", 200, True),
    ("GET", "/camp-ops/players/<player_id>/roster-records",
     [R["platform_admin"], R["roster_manager"], R["minor_league_coordinator"]],
     "list_player_roster_records", "array", 200, False),
    ("POST", "/camp-ops/players/<player_id>/roster-record/select-active-roster", [R["roster_manager"]],
     "select_active_roster", "object", 200, False),
    ("POST", "/camp-ops/players/<player_id>/roster-record/decide", [R["roster_manager"]],
     "roster_decide", "object", 200, False),
    ("POST", "/camp-ops/players/<player_id>/roster-record/request-waivers", [R["roster_manager"]],
     "request_waivers", "object", 200, False),
    ("POST", "/camp-ops/players/<player_id>/roster-record/record-waiver-outcome", [R["roster_manager"]],
     "record_waiver_outcome", "object", 200, False),
    ("POST", "/camp-ops/players/<player_id>/roster-record/finalize-decision", [R["roster_manager"]],
     "finalize_decision", "object", 200, False),
    ("POST", "/camp-ops/players/<player_id>/roster-record/void-decision", [R["roster_manager"]],
     "void_decision", "object", 200, False),
    ("POST", "/camp-ops/roster-records/<record_id>/break-out-camp", [R["minor_league_coordinator"]],
     "break_out_camp", "object", 200, False),

    # --- PlayerProgramProfile ---------------------------------------------
    ("POST", "/camp-ops/players/<player_id>/program-profile",
     [R["team_physician"], R["roster_manager"]],
     "create_program_profile", "object", 201, False),
    ("GET", "/camp-ops/program-profiles/<profile_id>",
     [R["platform_admin"], R["team_physician"], R["roster_manager"], R["analytics"]],
     "get_program_profile", "object", 200, False),
    ("GET", "/camp-ops/program-profiles",
     [R["platform_admin"], R["team_physician"], R["analytics"]],
     "list_program_profiles", "array", 200, True),
    ("GET", "/camp-ops/players/<player_id>/program-profiles",
     [R["platform_admin"], R["team_physician"], R["roster_manager"]],
     "list_player_program_profiles", "array", 200, False),
    ("POST", "/camp-ops/players/<player_id>/program-profile/reinstate", [R["team_physician"]],
     "reinstate_profile", "object", 200, False),

    # --- HostCommunityRecord ----------------------------------------------
    ("POST", "/camp-ops/community-agreements/<agreement_id>/host-community-record",
     [R["community_liaison"]],
     "create_host_community_record", "object", 201, False),
    ("GET", "/camp-ops/host-community-records/<record_id>",
     [R["community_liaison"], R["platform_admin"], R["analytics"]],
     "get_host_community_record", "object", 200, False),
    ("GET", "/camp-ops/community-agreements/<agreement_id>/host-community-records",
     [R["community_liaison"], R["platform_admin"], R["analytics"]],
     "list_agreement_host_records", "array", 200, False),
    ("GET", "/camp-ops/host-community-records",
     [R["community_liaison"], R["platform_admin"], R["analytics"]],
     "list_host_community_records", "array", 200, True),
    ("POST", "/camp-ops/host-community-records/<record_id>/open-ticketing", [R["community_liaison"]],
     "open_ticketing", "object", 200, False),
    ("POST", "/camp-ops/host-community-records/<record_id>/close-ticketing", [R["community_liaison"]],
     "close_ticketing", "object", 200, False),
    ("POST", "/camp-ops/host-community-records/<record_id>/sell-tickets", [R["community_liaison"]],
     "sell_tickets", "object", 200, False),
    ("GET", "/camp-ops/host-community-records/<record_id>/ledger",
     [R["community_liaison"], R["platform_admin"], R["complex_director"], R["analytics"]],
     "get_ledger", "object", 200, False),

    # --- Sponsorship -------------------------------------------------------
    ("POST", "/camp-ops/host-community-records/<record_id>/sponsorships", [R["community_liaison"]],
     "create_sponsorship", "object", 201, False),
    ("GET", "/camp-ops/sponsorships/<sponsorship_id>",
     [R["community_liaison"], R["platform_admin"], R["analytics"]],
     "get_sponsorship", "object", 200, False),
    ("GET", "/camp-ops/host-community-records/<record_id>/sponsorships",
     [R["community_liaison"], R["platform_admin"], R["analytics"]],
     "list_record_sponsorships", "array", 200, False),
    ("GET", "/camp-ops/sponsorships",
     [R["community_liaison"], R["platform_admin"], R["analytics"]],
     "list_sponsorships", "array", 200, True),
    ("POST", "/camp-ops/sponsorships/<sponsorship_id>/contribute", [R["community_liaison"]],
     "contribute_sponsorship", "object", 200, False),
    ("POST", "/camp-ops/sponsorships/<sponsorship_id>/settle", [R["community_liaison"]],
     "settle_sponsorship", "object", 200, False),
    ("POST", "/camp-ops/sponsorships/<sponsorship_id>/recognize", [R["community_liaison"]],
     "recognize_sponsorship", "object", 200, False),
    ("POST", "/camp-ops/sponsorships/<sponsorship_id>/void-settlement", [R["community_liaison"]],
     "void_settlement", "object", 200, False),

    # --- WorkoutGroup ------------------------------------------------------
    ("POST", "/camp-ops/complexes/<complex_id>/workout-groups",
     [R["complex_director"], R["field_coordinator"]],
     "create_workout_group", "object", 201, False),
    ("GET", "/camp-ops/workout-groups/<group_id>",
     [R["platform_admin"], R["complex_director"], R["field_coordinator"],
      R["pitching_coordinator"], R["analytics"]],
     "get_workout_group", "object", 200, False),
    ("GET", "/camp-ops/complexes/<complex_id>/workout-groups",
     [R["platform_admin"], R["complex_director"], R["field_coordinator"]],
     "list_complex_workout_groups", "array", 200, False),
    ("GET", "/camp-ops/workout-groups",
     [R["platform_admin"], R["complex_director"], R["field_coordinator"], R["analytics"]],
     "list_workout_groups", "array", 200, True),
    ("POST", "/camp-ops/workout-groups/<group_id>/publish", [R["complex_director"]],
     "publish_workout_group", "object", 200, False),
    ("POST", "/camp-ops/workout-groups/<group_id>/disband", [R["complex_director"]],
     "disband_workout_group", "object", 200, False),
    ("POST", "/camp-ops/workout-groups/<group_id>/sessions", [R["field_coordinator"]],
     "create_workout_group_session", "object", 201, False),
    ("GET", "/camp-ops/workout-groups/<group_id>/sessions",
     [R["platform_admin"], R["complex_director"], R["field_coordinator"],
      R["pitching_coordinator"]],
     "list_group_sessions", "array", 200, False),
    ("GET", "/camp-ops/workout-group-sessions",
     [R["platform_admin"], R["complex_director"], R["field_coordinator"], R["analytics"]],
     "list_workout_group_sessions", "array", 200, True),
    ("GET", "/camp-ops/workout-group-sessions/<session_id>",
     [R["platform_admin"], R["complex_director"], R["field_coordinator"],
      R["pitching_coordinator"]],
     "get_workout_group_session", "object", 200, False),
    ("POST", "/camp-ops/workout-groups/<group_id>/sessions/<session_id>/publish-session",
     [R["field_coordinator"]],
     "publish_group_session", "object", 200, False),

    # --- GroupAssignment ---------------------------------------------------
    ("POST", "/camp-ops/workout-groups/<group_id>/assignments",
     [R["field_coordinator"], R["pitching_coordinator"]],
     "create_group_assignment", "object", 201, False),
    ("GET", "/camp-ops/group-assignments/<assignment_id>",
     [R["platform_admin"], R["field_coordinator"], R["pitching_coordinator"], R["analytics"]],
     "get_group_assignment", "object", 200, False),
    ("GET", "/camp-ops/group-assignments",
     [R["platform_admin"], R["field_coordinator"], R["pitching_coordinator"], R["analytics"]],
     "list_group_assignments", "array", 200, True),
    ("GET", "/camp-ops/workout-groups/<group_id>/assignments",
     [R["platform_admin"], R["field_coordinator"], R["pitching_coordinator"]],
     "list_group_assignments_of_group", "array", 200, False),
    ("POST", "/camp-ops/group-assignments/<assignment_id>/call-up", [R["field_coordinator"]],
     "call_up_assignment", "object", 200, False),
    ("POST", "/camp-ops/group-assignments/<assignment_id>/withdraw",
     [R["field_coordinator"], R["pitching_coordinator"]],
     "withdraw_assignment", "object", 200, False),

    # --- ThrowProgram ------------------------------------------------------
    ("POST", "/camp-ops/group-assignments/<assignment_id>/throw-programs",
     [R["pitching_coordinator"]],
     "create_throw_program", "object", 201, False),
    ("GET", "/camp-ops/throw-programs/<program_id>",
     [R["platform_admin"], R["pitching_coordinator"], R["field_coordinator"], R["analytics"]],
     "get_throw_program", "object", 200, False),
    ("GET", "/camp-ops/throw-programs",
     [R["platform_admin"], R["pitching_coordinator"], R["analytics"]],
     "list_throw_programs", "array", 200, True),
    ("GET", "/camp-ops/group-assignments/<assignment_id>/throw-programs",
     [R["platform_admin"], R["pitching_coordinator"], R["field_coordinator"]],
     "list_assignment_throw_programs", "array", 200, False),
    ("POST", "/camp-ops/throw-programs/<program_id>/sessions", [R["pitching_coordinator"]],
     "log_throw_session", "object", 201, False),
    ("GET", "/camp-ops/throw-programs/<program_id>/sessions",
     [R["platform_admin"], R["pitching_coordinator"], R["analytics"]],
     "list_program_sessions", "array", 200, False),
    ("GET", "/camp-ops/throw-program-sessions",
     [R["platform_admin"], R["pitching_coordinator"], R["analytics"]],
     "list_throw_program_sessions", "array", 200, True),
    ("GET", "/camp-ops/throw-program-sessions/<session_id>",
     [R["platform_admin"], R["pitching_coordinator"], R["analytics"]],
     "get_throw_program_session", "object", 200, False),
    ("POST", "/camp-ops/throw-programs/<program_id>/advance-phase", [R["pitching_coordinator"]],
     "advance_phase", "object", 200, False),
    ("POST", "/camp-ops/throw-programs/<program_id>/shutdown", [R["pitching_coordinator"]],
     "shutdown_program", "object", 200, False),
    ("POST", "/camp-ops/throw-programs/<program_id>/reinstate", [R["pitching_coordinator"]],
     "reinstate_program", "object", 200, False),

    # --- CampInvitation ----------------------------------------------------
    ("POST", "/camp-ops/players/<player_id>/camp-invitations",
     [R["travel_coordinator"], R["roster_manager"]],
     "create_camp_invitation", "object", 201, False),
    ("GET", "/camp-ops/camp-invitations/<invitation_id>",
     [R["platform_admin"], R["travel_coordinator"], R["roster_manager"],
      R["community_liaison"], R["analytics"], R["player"]],
     "get_camp_invitation", "object", 200, False),
    ("GET", "/camp-ops/camp-invitations",
     [R["platform_admin"], R["travel_coordinator"], R["roster_manager"], R["analytics"]],
     "list_camp_invitations", "array", 200, True),
    ("GET", "/camp-ops/players/<player_id>/camp-invitations",
     [R["platform_admin"], R["travel_coordinator"], R["roster_manager"]],
     "list_player_camp_invitations", "array", 200, False),
    ("POST", "/camp-ops/camp-invitations/<invitation_id>/send-letter", [R["travel_coordinator"]],
     "send_letter", "object", 200, False),
    ("POST", "/camp-ops/camp-invitations/<invitation_id>/acknowledge", [R["player"]],
     "acknowledge_invitation", "object", 200, False),
    ("POST", "/camp-ops/camp-invitations/<invitation_id>/arrive", [R["travel_coordinator"]],
     "arrive_invitation", "object", 200, False),
    ("POST", "/camp-ops/camp-invitations/<invitation_id>/mark-visa-blocked", [R["travel_coordinator"]],
     "mark_visa_blocked", "object", 200, False),
    ("POST", "/camp-ops/camp-invitations/<invitation_id>/travel-arrangement", [R["travel_coordinator"]],
     "arrange_travel", "object", 200, False),

    # --- TravelArrangement -------------------------------------------------
    ("POST", "/camp-ops/travel-arrangements", [R["travel_coordinator"]],
     "create_travel_arrangement", "object", 201, False),
    ("GET", "/camp-ops/travel-arrangements/<arrangement_id>",
     [R["platform_admin"], R["travel_coordinator"], R["community_liaison"], R["analytics"]],
     "get_travel_arrangement", "object", 200, False),
    ("GET", "/camp-ops/travel-arrangements",
     [R["platform_admin"], R["travel_coordinator"], R["analytics"]],
     "list_travel_arrangements", "array", 200, True),
    ("GET", "/camp-ops/camp-invitations/<invitation_id>/travel-arrangements",
     [R["platform_admin"], R["travel_coordinator"], R["community_liaison"]],
     "list_invitation_travel_arrangements", "array", 200, False),
    ("POST", "/camp-ops/travel-arrangements/<arrangement_id>/revert", [R["travel_coordinator"]],
     "revert_travel_arrangement", "object", 200, False),
    ("POST", "/camp-ops/travel-arrangements/<arrangement_id>/cancel",
     [R["travel_coordinator"], R["community_liaison"]],
     "cancel_travel_arrangement", "object", 200, False),

    # --- Physical ----------------------------------------------------------
    ("POST", "/camp-ops/players/<player_id>/physicals", [R["team_physician"]],
     "create_physical", "object", 201, False),
    ("GET", "/camp-ops/physicals/<physical_id>",
     [R["platform_admin"], R["team_physician"], R["roster_manager"], R["analytics"]],
     "get_physical", "object", 200, False),
    ("GET", "/camp-ops/players/<player_id>/physicals",
     [R["platform_admin"], R["team_physician"], R["roster_manager"]],
     "list_player_physicals", "array", 200, False),
    ("GET", "/camp-ops/physicals",
     [R["platform_admin"], R["team_physician"], R["roster_manager"], R["analytics"]],
     "list_physicals", "array", 200, True),
    ("POST", "/camp-ops/physicals/<physical_id>/perform", [R["team_physician"]],
     "perform_physical", "object", 200, False),
    ("POST", "/camp-ops/physicals/<physical_id>/void", [R["team_physician"]],
     "void_physical", "object", 200, False),

    # --- GameSchedule ------------------------------------------------------
    ("POST", "/camp-ops/complexes/<complex_id>/games", [R["complex_director"]],
     "create_game", "object", 201, False),
    ("GET", "/camp-ops/games/<game_id>",
     [R["platform_admin"], R["complex_director"], R["field_coordinator"], R["analytics"]],
     "get_game", "object", 200, False),
    ("GET", "/camp-ops/games",
     [R["platform_admin"], R["complex_director"], R["analytics"]],
     "list_games", "array", 200, True),
    ("GET", "/camp-ops/complexes/<complex_id>/games",
     [R["platform_admin"], R["complex_director"], R["field_coordinator"]],
     "list_complex_games", "array", 200, False),
    ("POST", "/camp-ops/games/<game_id>/publish", [R["complex_director"]],
     "publish_game", "object", 200, False),
    ("POST", "/camp-ops/games/<game_id>/revert-to-draft", [R["complex_director"]],
     "revert_game_to_draft", "object", 200, False),
    ("POST", "/camp-ops/games/<game_id>/record-result", [R["complex_director"]],
     "record_game_result", "object", 200, False),
    ("POST", "/camp-ops/games/<game_id>/cancel", [R["complex_director"]],
     "cancel_game", "object", 200, False),

    # --- GameParticipation -------------------------------------------------
    ("POST", "/camp-ops/games/<game_id>/participations", [R["field_coordinator"]],
     "create_game_participation", "object", 201, False),
    ("GET", "/camp-ops/game-participations/<participation_id>",
     [R["platform_admin"], R["field_coordinator"], R["analytics"]],
     "get_game_participation", "object", 200, False),
    ("GET", "/camp-ops/game-participations",
     [R["platform_admin"], R["field_coordinator"], R["analytics"]],
     "list_game_participations", "array", 200, True),
    ("GET", "/camp-ops/games/<game_id>/participations",
     [R["platform_admin"], R["field_coordinator"], R["complex_director"]],
     "list_game_participations_of_game", "array", 200, False),
    ("POST", "/camp-ops/games/<game_id>/participations/<participation_id>/confirm",
     [R["field_coordinator"]],
     "confirm_participation", "object", 200, False),
    ("POST", "/camp-ops/games/<game_id>/participations/<participation_id>/withdraw",
     [R["field_coordinator"]],
     "withdraw_participation", "object", 200, False),
    ("POST", "/camp-ops/games/<game_id>/package-roster", [R["complex_director"]],
     "package_roster", "object", 200, False),

    # --- SpringTrail -------------------------------------------------------
    ("POST", "/camp-ops/players/<player_id>/spring-trails", [R["minor_league_coordinator"]],
     "create_spring_trail", "object", 201, False),
    ("GET", "/camp-ops/spring-trails/<trail_id>",
     [R["platform_admin"], R["minor_league_coordinator"], R["analytics"]],
     "get_spring_trail", "object", 200, False),
    ("GET", "/camp-ops/players/<player_id>/spring-trails",
     [R["platform_admin"], R["minor_league_coordinator"], R["roster_manager"]],
     "list_player_spring_trails", "array", 200, False),
    ("GET", "/camp-ops/spring-trails",
     [R["platform_admin"], R["minor_league_coordinator"], R["analytics"]],
     "list_spring_trails", "array", 200, True),
    ("POST", "/camp-ops/spring-trails/<trail_id>/end", [R["minor_league_coordinator"]],
     "end_spring_trail", "object", 200, False),

    # --- MinorLeagueAssignment --------------------------------------------
    ("POST", "/camp-ops/players/<player_id>/minor-league-assignments",
     [R["minor_league_coordinator"]],
     "create_minor_league_assignment", "object", 201, False),
    ("GET", "/camp-ops/minor-league-assignments/<assignment_id>",
     [R["platform_admin"], R["minor_league_coordinator"], R["analytics"]],
     "get_minor_league_assignment", "object", 200, False),
    ("GET", "/camp-ops/players/<player_id>/minor-league-assignments",
     [R["platform_admin"], R["minor_league_coordinator"], R["roster_manager"]],
     "list_player_minor_league_assignments", "array", 200, False),
    ("GET", "/camp-ops/minor-league-assignments",
     [R["platform_admin"], R["minor_league_coordinator"], R["analytics"]],
     "list_minor_league_assignments", "array", 200, True),
    ("POST", "/camp-ops/minor-league-assignments/<assignment_id>/settle",
     [R["minor_league_coordinator"]],
     "settle_minor_league_assignment", "object", 200, False),
    ("POST", "/camp-ops/minor-league-assignments/<assignment_id>/void-breakout",
     [R["minor_league_coordinator"]],
     "void_minor_league_assignment", "object", 200, False),

    # --- ops runs ----------------------------------------------------------
    ("POST", "/camp-ops/ops-runs", [R["platform_admin"], R["complex_director"]],
     "run_ops_checkpoint", "object", 200, False),
]