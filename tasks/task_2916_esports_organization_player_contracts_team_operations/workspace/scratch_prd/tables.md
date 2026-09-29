
## 4. Endpoint Definitions

Creation endpoints return HTTP 201 with the created resource; every other successful operation, including state transitions, computed reads and list reads, returns HTTP 200 with the affected or requested resource. The table below is the authoritative mapping from method and path to authorised roles; request payloads, response contents and side effects are not repeated here and must be taken from the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/leagues` | Register a league with its calendar, roster limits and player-association terms | `LeagueAdmin` |
| GET | `/leagues/{id}` | Read one league, including the derived roster_lock_active flag | `LeagueAdmin`, `GeneralManager`, `PlayerAgent`, `FinanceOfficer` |
| GET | `/leagues` | List leagues | `LeagueAdmin`, `GeneralManager`, `PlayerAgent`, `FinanceOfficer` |
| PATCH | `/leagues/{id}` | Adjust league calendar, caps and association terms | `LeagueAdmin` |
| GET | `/leagues/{id}/organizations` | List the organizations competing in this league (FK reverse for Organization.league_id) | `LeagueAdmin`, `FinanceOfficer` |
| POST | `/organizations` | Register an organization under a league with its salary budget and prize share | `LeagueAdmin` |
| GET | `/organizations/{id}` | Read one organization with its derived salary and roster counters | `LeagueAdmin`, `GeneralManager`, `FinanceOfficer`, `OpsManager`, `SponsorshipManager` |
| GET | `/organizations` | List organizations, optionally filtered by league | `LeagueAdmin`, `FinanceOfficer` |
| PATCH | `/organizations/{id}` | Adjust an organization's salary budget or prize share | `LeagueAdmin` |
| GET | `/organizations/{id}/roster` | List the players whose current_organization_id or last_release_organization_id is this organization (FK reverse for both Player -> Organization keys) | `LeagueAdmin`, `GeneralManager`, `CoachingStaff`, `PerformanceSupport`, `Scout` |
| GET | `/organizations/{id}/team-houses` | List this organization's facilities (FK reverse for TeamHouse.organization_id) | `LeagueAdmin`, `GeneralManager`, `OpsManager`, `CoachingStaff` |
| GET | `/organizations/{id}/sponsorship-deals` | List this organization's sponsorship deals (FK reverse for SponsorshipDeal.organization_id) | `LeagueAdmin`, `GeneralManager`, `SponsorshipManager` |
| GET | `/organizations/{id}/cap-summary` | Computed read: both salary-cap variants side by side for this organization | `LeagueAdmin`, `GeneralManager`, `FinanceOfficer` |
| POST | `/players` | Register a scouted prospect; age_years, is_minor and guardian_consent_status are derived | `Scout` |
| GET | `/players/{id}` | Read one player with derived minor status | `LeagueAdmin`, `GeneralManager`, `PlayerAgent`, `Scout`, `CoachingStaff`, `PerformanceSupport`, `GuardianRepresentative` |
| GET | `/players` | List players, filterable by lifecycle state and organization | `LeagueAdmin`, `GeneralManager`, `Scout` |
| PATCH | `/players/{id}` | Update player profile, education enrolment or the guardian's weekly cap | `Scout`, `GuardianRepresentative` |
| POST | `/players/{id}/guardian-consent` | Guardian records consent for a minor player and may pin a stricter weekly cap | `GuardianRepresentative` |
| POST | `/contract-offers` | Send a contract offer to a player; optionally supersedes an earlier open offer | `GeneralManager` |
| GET | `/contract-offers/{id}` | Read one offer; lazy expiry is applied before the read is served | `LeagueAdmin`, `GeneralManager`, `PlayerAgent` |
| GET | `/contract-offers` | List offers filtered by organization, player, supersede chain or status (FK reverse for all three ContractOffer keys) | `LeagueAdmin`, `GeneralManager`, `PlayerAgent` |
| POST | `/contract-offers/{id}/counter` | Agent counters the offer with revised salary, prize split and streaming terms | `PlayerAgent` |
| POST | `/contract-offers/{id}/revise` | Organization answers a counter with new headline terms, restarting the response window | `GeneralManager` |
| POST | `/contract-offers/{id}/accept` | Agent accepts the offer, creating the PlayerContract and consuming provisional cap space | `PlayerAgent` |
| POST | `/contract-offers/{id}/decline` | Agent declines the offer | `PlayerAgent` |
| GET | `/contracts/{id}` | Read one contract with both status dimensions and its frozen money fields | `LeagueAdmin`, `GeneralManager`, `PlayerAgent`, `FinanceOfficer`, `PerformanceSupport` |
| GET | `/contracts` | List contracts filtered by organization, player, originating offer or status (FK reverse for all three PlayerContract keys) | `LeagueAdmin`, `GeneralManager`, `PlayerAgent`, `FinanceOfficer` |
| POST | `/contracts/{id}/suspend` | League suspends an active contract, freezing the player's scheduled work | `LeagueAdmin` |
| POST | `/contracts/{id}/wellness-report` | Performance support files a self-reported load and streaming figure, refreshing the burnout score | `PerformanceSupport` |
| GET | `/contracts/{id}/obligation-summary` | Computed read: both burnout variants, the player's weekly cap arithmetic and both cap-charge variants | `LeagueAdmin`, `GeneralManager`, `PerformanceSupport` |
| GET | `/contracts/{id}/prize-allocations` | List the prize rows paid against this contract (FK reverse for PrizeAllocation.contract_id) | `LeagueAdmin`, `PlayerAgent`, `FinanceOfficer` |
| POST | `/organizations/{id}/team-houses` | Open a team house or practice facility for the organization | `OpsManager` |
| GET | `/team-houses/{id}` | Read one facility with its buffer and seat capacity | `GeneralManager`, `OpsManager`, `CoachingStaff` |
| PATCH | `/team-houses/{id}` | Adjust a facility's turnaround buffer or seat capacity | `OpsManager` |
| POST | `/practice-blocks` | Book a scrim, review, individual session or tryout into a team house | `CoachingStaff` |
| GET | `/practice-blocks/{id}` | Read one practice block | `GeneralManager`, `OpsManager`, `CoachingStaff`, `PerformanceSupport` |
| GET | `/practice-blocks` | List blocks filtered by organization, house, type, status or window (FK reverse for both PracticeBlock keys) | `GeneralManager`, `OpsManager`, `CoachingStaff`, `PerformanceSupport` |
| POST | `/practice-blocks/{id}/complete` | Mark the block as held, feeding its minutes into the burnout scores | `CoachingStaff` |
| POST | `/practice-blocks/{id}/cancel` | Cancel a scheduled block, freeing the room slot and the players' weekly minutes | `CoachingStaff` |
| POST | `/sponsorship-deals` | Draft a sponsorship deal with a fee, a deliverable quota and an exclusivity category | `SponsorshipManager` |
| GET | `/sponsorship-deals/{id}` | Read one deal with its assignment and approval counters | `LeagueAdmin`, `GeneralManager`, `SponsorshipManager` |
| GET | `/sponsorship-deals` | List deals filtered by organization, status or exclusivity category (FK reverse for SponsorshipDeal.organization_id) | `LeagueAdmin`, `GeneralManager`, `SponsorshipManager` |
| POST | `/sponsorship-deals/{id}/activate` | Activate a drafted deal after the exclusivity check clears | `SponsorshipManager` |
| POST | `/sponsorship-deals/{id}/deliverables` | Place a content deliverable on one player's contract; requires the deal's current version | `SponsorshipManager` |
| GET | `/sponsorship-deals/{id}/deliverables` | List this deal's deliverables (FK reverse for DeliverableAssignment.sponsorship_deal_id) | `LeagueAdmin`, `GeneralManager`, `SponsorshipManager` |
| GET | `/deliverable-assignments/{id}` | Read one deliverable assignment | `GeneralManager`, `PlayerAgent`, `SponsorshipManager` |
| GET | `/deliverable-assignments` | List assignments filtered by deal, contract or status (FK reverse for DeliverableAssignment.contract_id) | `GeneralManager`, `PlayerAgent`, `SponsorshipManager` |
| POST | `/deliverable-assignments/{id}/submit` | Agent submits the produced content for review; a rejected item may be resubmitted | `PlayerAgent` |
| POST | `/deliverable-assignments/{id}/review` | Sponsorship manager approves or rejects a submitted deliverable | `SponsorshipManager` |
| POST | `/prize-distributions` | Record a tournament result and the gross prize to be split | `FinanceOfficer` |
| GET | `/prize-distributions/{id}` | Read one distribution with its waterfall figures | `LeagueAdmin`, `GeneralManager`, `FinanceOfficer` |
| GET | `/prize-distributions` | List distributions filtered by organization, league or status (FK reverse for both PrizeDistribution keys) | `LeagueAdmin`, `GeneralManager`, `FinanceOfficer` |
| POST | `/prize-distributions/{id}/calculate` | Run the prize waterfall and freeze one PrizeAllocation row per eligible contract | `FinanceOfficer` |
| POST | `/prize-distributions/{id}/approve` | League signs off the calculated split; a different user than the calculator must do it | `LeagueAdmin` |
| POST | `/prize-distributions/{id}/void` | Compensating action: void the distribution and unwind every allocation | `FinanceOfficer` |
| GET | `/prize-distributions/{id}/allocations` | List the frozen per-player rows of this distribution (FK reverse for PrizeAllocation.prize_distribution_id) | `LeagueAdmin`, `PlayerAgent`, `FinanceOfficer` |
| POST | `/roster-moves` | File a signing, release or outgoing transfer for league decision; requires the organization's current version | `GeneralManager` |
| GET | `/roster-moves/{id}` | Read one roster move with its settlement figures | `LeagueAdmin`, `GeneralManager`, `PlayerAgent` |
| GET | `/roster-moves` | List moves filtered by organization, player, contract, destination or status (FK reverse for all four RosterMove keys) | `LeagueAdmin`, `GeneralManager`, `PlayerAgent` |
| POST | `/roster-moves/{id}/decision` | League approves or rejects a pending move; a SIGN approval re-tests the cap with the full-season variant | `LeagueAdmin` |
| POST | `/roster-moves/{id}/execute` | Execute an approved move, settling the transfer money and releasing cap space | `GeneralManager` |
| POST | `/roster-moves/{id}/reverse` | Compensating action: unwind an executed release or transfer and restore the contract | `LeagueAdmin` |
| POST | `/_clock/set_current_utc` | Set the server's logical clock. Before any call the clock reads exactly 2026-08-01T00:00:00Z; it never falls back to wall-clock time. | `LeagueAdmin` |

## 5. Error Code Catalogue

Every rejection carries one of the identifiers below in the `error_id` field of the error envelope described in §2.2, with the HTTP status shown. The conditions that trigger each identifier are not repeated here; they are stated where the rule they enforce is described, and their relative precedence is fixed by the thirteen bands of §2.6.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_LEAGUE_NOT_FOUND` | 404 |
| `ERR_ORGANIZATION_NOT_FOUND` | 404 |
| `ERR_PLAYER_NOT_FOUND` | 404 |
| `ERR_OFFER_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_TEAM_HOUSE_NOT_FOUND` | 404 |
| `ERR_PRACTICE_BLOCK_NOT_FOUND` | 404 |
| `ERR_DEAL_NOT_FOUND` | 404 |
| `ERR_DELIVERABLE_NOT_FOUND` | 404 |
| `ERR_DISTRIBUTION_NOT_FOUND` | 404 |
| `ERR_ROSTER_MOVE_NOT_FOUND` | 404 |
| `ERR_DEAL_VERSION_STALE` | 412 |
| `ERR_ORGANIZATION_VERSION_STALE` | 412 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_OFFER_NOT_OPEN` | 409 |
| `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` | 409 |
| `ERR_PLAYER_ALREADY_SIGNED` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_BLOCK_NOT_SCHEDULED` | 409 |
| `ERR_DEAL_NOT_ACTIVE` | 409 |
| `ERR_ASSIGNMENT_NOT_SUBMITTED` | 409 |
| `ERR_DISTRIBUTION_NOT_DRAFT` | 409 |
| `ERR_DISTRIBUTION_NOT_CALCULATED` | 409 |
| `ERR_MOVE_NOT_PENDING` | 409 |
| `ERR_MOVE_NOT_APPROVED` | 409 |
| `ERR_MOVE_NOT_EXECUTED` | 409 |
| `ERR_MOVE_NOT_REVERSIBLE` | 422 |
| `ERR_GUARDIAN_CONSENT_REQUIRED` | 422 |
| `ERR_MINOR_CATEGORY_FORBIDDEN` | 422 |
| `ERR_EDUCATION_HOURS_RESERVED` | 422 |
| `ERR_WEEKLY_HOUR_CAP_EXCEEDED` | 422 |
| `ERR_WELLNESS_HOLD_ACTIVE` | 409 |
| `ERR_OBLIGATION_BREACH_BLOCKS_ASSIGNMENT` | 422 |
| `ERR_ROSTER_LOCK_ACTIVE` | 422 |
| `ERR_TRANSFER_WINDOW_CLOSED` | 422 |
| `ERR_FREE_AGENCY_COOLDOWN` | 422 |
| `ERR_EFFECTIVE_AT_OUTSIDE_SEASON` | 422 |
| `ERR_DELIVERABLE_DUE_OUTSIDE_DEAL` | 422 |
| `ERR_BLOCK_NOT_FINISHED` | 409 |
| `ERR_FACILITY_SLOT_CONFLICT` | 409 |
| `ERR_PLAYER_DOUBLE_BOOKED` | 409 |
| `ERR_FACILITY_CAPACITY_EXCEEDED` | 422 |
| `ERR_DELIVERABLE_QUOTA_EXCEEDED` | 422 |
| `ERR_TRYOUT_REQUIRED` | 422 |
| `ERR_ROSTER_SIZE_EXCEEDED` | 422 |
| `ERR_ROSTER_SIZE_BELOW_MINIMUM` | 422 |
| `ERR_EXCLUSIVITY_CONFLICT` | 409 |
| `ERR_BELOW_MINIMUM_SALARY` | 422 |
| `ERR_PRIZE_SPLIT_BELOW_ASSOCIATION_MIN` | 422 |
| `ERR_STREAMING_HOURS_EXCEED_ASSOCIATION_MAX` | 422 |
| `ERR_SALARY_CAP_EXCEEDED` | 422 |
| `ERR_NEGATIVE_SETTLEMENT` | 422 |
| `ERR_NO_ELIGIBLE_CONTRACTS` | 422 |
