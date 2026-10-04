# Worklog — task_3144_closed_loop_social_care_referral_network_outcome

## Step 1: Create task directory — 2026-09-30T04:06:00.000Z

Pre-allocated directory `./tasks/task_3144_closed_loop_social_care_referral_network_outcome/` verified present with empty `workspace/` inside; used as-is per command args (no new index computed).

## Step 2: Generate scaffold — 2026-09-30T05:15:00.000Z

All three artifacts are written and the lint verdict is clean.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3144_closed_loop_social_care_referral_network_outcome/`):
- `SCAFFOLD.yaml` — §1.0–§1.7, no design keys embedded
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` key

**Counts:** 14 entities, 68 endpoints, 30 error codes, 30 ordered validations, 8 calculations, 9 state machines, 3 OCC concurrency rules, 4 roles. Difficulty design: 18 instances (exactly 2 per each of the 9 §0.5 rules). Corner design: 42 instances (31 active + 11 `excluded_because:` stubs), 897 total structured calls across both design files. All instance names unique across the union; every grounds reference resolves.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

**Notable design decisions (harder-than-expert levers applied):**
- **Archetype:** multi-party-negotiation × compliance-audit; segregation-of-duties role model with compound staff identities (`<org_id>#<staff_label>`) so reviewer ≠ approver is testable within one funder org (full `X-User-ID` compared against `PaymentClaim.reviewed_by_user_id`).
- **Dual-variant calcs on two domains:** claim quoting (PROVISIONAL ignores the funder monthly cap; FINAL applies a cap waterfall with pinned evaluation order gross→sum-prior-excluding-self→clamp) and funder-report rates (`closure_rate_percent` vs `resolution_rate_percent` diverge by NOT_REACHED outcomes).
- **Two depth-3/4 transitive cascades from different triggers:** agreement termination → consent revocation → referral cancellation → claim void → escrow reserve; org suspension → force-decline → reassignment overflow → auto-cancel.
- **Cyclic state machines on two entities:** Referral (ROUTED↔DECLINED, ROUTED→ESCALATED→ROUTED with separate `reassignment_count`/`reopen_count` counters) and Organization (ACTIVE↔SUSPENDED with asymmetric cascade — suspension pauses offerings, reactivation does not resume them).
- **Boundary pins:** strict `>` on escalation window and aging-days report threshold, inclusive `>=` on rate-card tier `min_units`, strict `<` income cap, exact-month calendar window rollover for caps, inclusive `<=` on agreement `effective_at`.
- **Compensating invariants:** `capacity_consumed` case-reservation count (route/cancel pair) and `network_escrow_cents + network_escrow_reserved_cents` money conservation under clawback.
- **Fix made mid-design:** referral expiry uses a dedicated `referral_expiry_days` config (default 60) decoupled from the aging-report threshold, so the clock-set sweep doesn't wrongly expire 30-day-old referrals in the aging-report corner test.
- No sibling task directories were inspected; no processes were killed.

## Step 3: Copy shared files — 2026-09-30T05:18:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3144_closed_loop_social_care_referral_network_outcome/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T05:33:00.000Z

Clean — no fuzzy wording, no pseudocode operators. The PRD is complete at 302 lines.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3144_closed_loop_social_care_referral_network_outcome/workspace/PRD.md` (302 lines)

**Sections written:**
- §1 Introduction (2 paragraphs, problem/business-context angle)
- §2 Global Specifications — 2.1 RBAC (4 roles, opaque vs entity-backed identity with `<org_id>#<staff_label>` compound form), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Logical Clock & Aging Sweep (default `2026-09-01T00:00:00Z`), 2.5 Common Resource Properties (incl. explicit absence of `updated_at`/`version` on `ReferralNote`/`OutcomeRecord`), 2.6 Nested Retrieval & Validation Order, 2.7 Integer-Cents Precision (1-decimal round-half-up only for report percentages), 2.8 OCC (all three rules: `expected_referral_version`, `expected_claim_version`, `expected_org_version` → `ERR_STALE_VERSION` 412), 2.9 Network-Level Configuration (all defaults, escrow-hold invariant)
- §3 Business Logic — 9 subsections: taxonomy; org onboarding/lifecycle (Cascade A 3-hop suspension); offerings & capacity (case-reservation invariant); agreements & consent (Cascade B + 3-hop Cascade C with atomic `ERR_ESCROW_EXHAUSTED`); clients & referral lifecycle (routing gate, decline/reassign/escalate/cancel/expire); notes, delivery & outcome confirmation; claims & adjudication (tiered quote PROVISIONAL/FINAL, cap waterfall with fixed evaluation order, segregation of duties); voids/escrow/disbursements (clawback waterfall, all-or-nothing saga with `simulate_failure`); funder reporting (dual closure/resolution rates, unresolved/aging counts, k=5 suppression with `SUPPRESSED` bucket rules, sealed-report invariant)
- §4 Endpoint table — 68 rows, 4 columns, all scaffold paths present
- §5 Error catalogue — 30 rows, 2 columns, no trigger conditions

**Coverage/Zero-Silence audit:**
- Contract 1 (field-name coverage): 100 required identifiers (entities + endpoint inputs + clock/sweep outputs), 0 missing after adding `organization_id` — PASS
- Contract 2 (rule coverage): all validation priorities, OCC rules, cascades A/B/C with every hop, all calculations (eligibility 365.25-day year with inclusive age bounds and exclusive income cap, tiered claim quote with `>= min_units` boundary, capacity invariant, aging strict-> thresholds with halved URGENT window, dual closure rates, k-anonymity suppression, escrow clawback waterfall), all state transitions with preconditions/side-effects, and all 30 error IDs appear in §2/§3 prose — PASS
- Contract 3 (§3 path purity): 0 violations (no `/`-prefixed tokens, no bare HTTP methods, no method+path combos in §3) — PASS
- All 4 role names, all state enum values, and all field enum values (gender, race, ethnicity, org_type, funder_type, urgency, outcome codes, note visibility, consent scope) verified present in backticks; no fuzzy/approximating words; no pseudocode operators.

## Step 5: Generate unit tests — 2026-09-30T05:55:00.000Z

Done. Summary:

## Files written

**`test_helpers/`** (9 files, ~1600 lines):
- `types.py` — TypedDicts + status/role enums; `ReferralNote` and `OutcomeRecord` correctly omit `updated_at`/`version` (lean per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per PRD endpoint under `/care-network`
- `api_errors.py` — all 30 error IDs with HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + escrow/capacity/balance invariant checkers
- `factories.py`, `constants.py` — payload factories (unique EINs via counter), network defaults, `K_ANONYMITY_THRESHOLD`
- `test_users.py` — opaque coordinator constant + per-instance `make_*_headers(org_id, staff_label=None)` builders for the three entity-backed roles (with `#staff_label` suffix support for segregation of duties)
- `fixtures.py` — composite builders: `setup_referral_scenario` (funder optional), `setup_routed_referral`, `setup_completed_referral`, `setup_submitted_claim`, `setup_approved_claim`, `setup_two_receiver_scenario`, OCC-fresh `approve_claim`/`suspend_org`

**`test_suite/`** — `conftest.py` + 11 test files, **70 tests total**, all collecting cleanly.

## Coverage (Stage 2 audit: PASS)

- **Queue A (Difficulty): all 18 instances × ≥2 tests** — dual_variant_calc (claim cap-clamp + report rate divergence), combinatorial_formula (cap evaluation order + income boundary), non_linear_state_machine (referral counters + org suspend cycle), transitive_cascade (agreement depth-4 + suspension overflow), priority_pair (stale-version-beats-SoD + agreement-beats-capacity), boundary_precision (72h escalate window + max-reassignment boundary), cross_entity (offering-resume + disbursement-run), resource_temporal_overlap (monthly-cap rollover + effective_at gate), compensating_invariant (case-reservation route/cancel + escrow hold).
- **Queue B (Corner): all 31 non-stub instances × ≥1 test** across entities, state_machines, calculations, validations, errors, rbac, cross_cutting, endpoints.
- **11 `excluded_because` stubs not translated** — all cross-references verified to resolve to real difficulty instances that assert the cited behavior.

## Skipped instances

None. Every non-stub instance passed the PRD-first two-condition filter. Notes: two corner assertions were deliberately de-scoped for unique derivability (dropped `version == 1` on org creation — PRD says only "initial value"; dropped exact `revoked_at` string equality — ISO-8601 formatting is unspecified; prefix check retained). One difficulty instance's infeasible APPROVED-claim-shortfall arithmetic was implemented via the instance's own pinned fallback (SUBMITTED-claim consent-revocation void), matching its literal `setup_api_calls`.

## Self-audit verdict

PASS — 70/70 tests carry exactly one `Design:` line resolving to a real instance; every citation survives verbatim grep of PRD.md (27 distinctive substrings verified, 1 hit each); no `skip`/`skipif`/`xfail`; no scaffold section references in generated code; all files byte-compile and pytest-collect.

## Step 6: Generate implementation — 2026-09-30T06:20:00.000Z

All done. Summary of the delivered implementation:

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_3144_closed_loop_social_care_referral_network_outcome/workspace/implementation/app.py` — complete Flask server (single-file, ~1300 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3144_closed_loop_social_care_referral_network_outcome/workspace/implementation/start.sh` — executable launcher, guarded `pip install` (no-op when flask already present), `exec python3 app.py` in foreground, `0.0.0.0:$PORT` (default 10000)
- `/home/ubuntu/github/CodingPRD/tasks/task_3144_closed_loop_social_care_referral_network_outcome/workspace/implementation/requirements.txt` — `flask>=3.0,<4.0`

## Endpoint count
52 endpoints implemented, covering the full SCAFFOLD §1.5 table: clock set, networks (2), taxonomy (4), organizations (6), offerings (5), clients (2), agreements (6), consents (5), referrals (13 incl. route/accept/decline/reassign/escalate/start-service/confirm-outcome/cancel/aging-sweep), notes (3), outcomes (2), rate cards (3), claims (7), disbursements (4), reports (4).

## Key behaviors implemented
- Envelope exactly per §2.2 (`meta.api_request_id`/`api_request_timestamp`, `response_type` object/array/error, `data.error_id`/`message`; pagination `limit`/`offset`/`total_count`/`has_more` in meta, defaults 10/0, min 1, max 100)
- Auth via `X-User-ID`/`X-User-Role` with 4 roles; entity-backed identity with `<org_id>#<staff_label>` prefix matching for ownership, full-string compare for segregation of duties
- OCC on exactly the 3 specified endpoints (`expected_referral_version`, `expected_claim_version`, `expected_org_version` → `ERR_STALE_VERSION` 412)
- Logical clock defaulting to `2026-09-01T00:00:00Z`; aging sweep on clock-set and on demand (strict `>` expiry days)
- All cascades: suspend (force-decline + reservation release + overflow auto-cancel), agreement termination → consent revocation → referral cancellation + claim void with escrow reserve (atomic `ERR_ESCROW_EXHAUSTED`), referral decline/reassign/escalate capacity swaps, decline overflow auto-cancel
- Calculations: eligibility (365.25-day year, inclusive age bounds, strict income cap), tiered claim quote (tier2 at `>= min_units`, PROVISIONAL vs FINAL with monthly-cap waterfall), dual closure/resolution rates (1-decimal ROUND_HALF_UP via Decimal), k-anonymity suppression (k=5, SUPPRESSED bucket only when ≥5), escrow clawback waterfall (never-negative balance)
- Sealed reports freeze metrics; DRAFT reports recompute live
- In-memory dicts only, **no seeding** — verified a fresh boot lists zero orgs/taxonomy

## Boot verification
Booted via `bash start.sh` on port 19344 (and a fresh second boot on 19399 to confirm empty-store cold start), exercised end-to-end happy path plus edge paths (decline→reassign with new consent, OCC staleness, reassignment loop, escalation window strictness, segregation-of-duties, monthly-cap clamp, disbursement payout, paid-claim void block, consent-revocation claim voiding, suspend cascade, aging-sweep expiry) — all returned expected statuses/error IDs. All server processes I started were killed by exact PID afterwards.

## Step 7: Run tests and iterate — 2026-09-30T06:45:00.000Z

All 8 rounds pass 70/70. Clean sweep achieved.

## Summary

- **Iterations run:** 2 (first sweep: 63/70 with 7 deterministic failures; second sweep after fixes: 70/70 in all 8 parallel rounds).
- **Tests deleted:** none. All 7 failing tests traced to verbatim PRD rules and were faithful in setup, request, and assertion.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `implementation/`** (all in `/home/ubuntu/github/CodingPRD/tasks/task_3144_closed_loop_social_care_referral_network_outcome/workspace/implementation/app.py`):
  1. `create_referral` — eager consent validation was checking the sender-receiver pair match at creation, but PRD §3.5 assigns the pair-match failure (`ERR_CONSENT_REQUIRED`) to the routing gate; creation prose only says consent is "validated eagerly". Relaxed creation to require only that the named consent is ACTIVE. (Fixed `test_route_with_wrong_consent_pair_returns_consent_required`.)
  2. `routing_gate` — consent check used only the referral's recorded `consent_id`; PRD §3.5 states "an `ACTIVE` consent must match the sender-receiver pair" (existential), and reassignment "re-runs the full routing gate against the new target" — since reassign overwrites only `receiver_org_id`/`service_offering_id` (never `consent_id`), the gate must search the client's ACTIVE consents for one covering the (sender, new receiver) pair. (Fixed the 5 reassign-flow failures: `test_decline_reassign_cycle_counters`, `test_decline_reassign_cycle_reservation_swap`, `test_decline_past_max_count_auto_cancels`, `test_error_stale_version_on_reassign`, `test_reassign_with_current_version_succeeds_after_stale_rejection`.)
  3. `revoke_consent` — hard-required a CareNetwork to exist (404) even when no claims needed voiding; PRD's revocation cascade touches network escrow only for SUBMITTED/UNDER_REVIEW claims, so the escrow requirement now applies only when there are claims to void (reserve > 0). (Fixed `test_consent_revoked_at_null_until_revoked`.)

## Step 8: Finalize PRD — 2026-09-30T06:55:00.000Z

Done. Three minimal inline patches, no new sections, all other prose verbatim.

## Summary

**Line counts:** PRD.md 302 lines; PRD_FINALIZED.md 302 lines (0% line-count delta — all edits are in-place sentence extensions within existing paragraphs).

**Changes (one bullet each):**

- **§3.4 (consent revocation)** — insert — after the `ERR_ESCROW_EXHAUSTED` atomicity sentence, added that the escrow requirement applies only when the total clawback reserve is nonzero, so revocation with no claims to void proceeds even without a network/escrow — `workspace/implementation/app.py:559-566` (`revoke_consent` guards escrow existence and sufficiency only inside `if claims_to_void:`).
- **§3.5 (referral creation)** — insert — pinned that eager creation-time consent validation checks only that the named consent exists and is `ACTIVE` (else `ERR_CONSENT_REQUIRED`); the sender-receiver pair match is exclusively a routing-gate rule — `app.py:1340-1347` (`create_referral` checks `consent["status"] != "ACTIVE"` only, no `consent_covers` call).
- **§3.5 (decline/escalation reassign)** — revise — pinned that the re-run routing gate's consent check is existential over the client's `ACTIVE` consents for the (sender, new receiver) pair, since reassign overwrites only `receiver_org_id`/`service_offering_id` and the recorded `consent_id` still names the old pair — `app.py:1417-1436` (`routing_gate` falls back to scanning all client consents when no explicit `consent_id` is given; `reassign_referral` at `app.py:1577-1580` overwrites only receiver/offering unless `new_consent_id` is supplied).

**Per-edit pre-edit search log:**

1. **§3.4 escrow-on-revocation edit.**
   (a) Subject: when consent revocation requires network escrow.
   (b) Enumerated impl paths: `revoke_consent` (app.py:543-576, both cascade callers — direct endpoint `revoke_consent_ep` at 1296-1303 and `terminate_agreement_internal`), `void_claim` endpoint (1985-2004, separate escrow check, untouched), `void_claim` helper (503-523), `get_network`/`require_network` (298-306), `cancel_referral_for_consent` (526-540).
   (c) Wording scoped explicitly to "the escrow requirement applies only when the total reserve is nonzero" — avoiding any claim about the standalone void endpoint (which always requires the network) or about the case where claims-to-void exist (network required, `ERR_ESCROW_EXHAUSTED` when absent, matching "cannot cover the total reserve").

2. **§3.5 creation-time consent validation edit.**
   (a) Subject: what "validated eagerly" at referral creation covers.
   (b) Enumerated impl paths: `create_referral` (1310-1358), `routing_gate` (1406-1474), `route_referral` (1478-1495), claim submission consent check (1841-1844) and approval consent check (1919-1922) — both use the recorded consent, unaffected.
   (c) Initial draft named the old-pair existential behavior at creation; on review against `create_referral` (which does *not* search for a matching consent — creation with only a wrong-pair consent succeeds as DRAFT) the wording was tightened to: creation requires only that the named consent exists and is ACTIVE; pair match is deferred to the routing gate. Error attribution (`ERR_CONSENT_REQUIRED`, 422) matches impl.

3. **§3.5 reassign consent re-check edit.**
   (a) Subject: how the routing gate locates the matching consent during reassignment.
   (b) Enumerated impl paths: `routing_gate` existential scan (1417-1436) and `consent_covers` (369-371, exact (sender, receiver) equality — directional), `reassign_referral` (1541-1590, including the undocumented `new_consent_id` fast path), `route_referral` (1483-1484, same gate with `consent_id=None`), decline auto-cancel and suspension force-decline cascades (1513-1538, 954-972 — no consent check, no re-route through the gate), claim submit/approve recorded-consent checks.
   (c) Initial draft claimed the plain (non-escalation) re-route re-reserves capacity on the old offering; verified false at app.py:1582-1584 (`reassignment_count`/`reopen_count` and old-offering release only `if from_escalated`) and removed the clause. Final wording says only that the recorded `consent_id` is not overwritten (true when `new_consent_id` is omitted) and that the check "does not rely on the recorded `consent_id` alone" — true for both the default existential path and the `new_consent_id` path, without asserting anything about the undocumented body field.

## Step 9: Complete PRD — 2026-09-30T07:05:00.000Z

**Source vs output**
- Source: `/home/ubuntu/github/CodingPRD/tasks/task_3144_closed_loop_social_care_referral_network_outcome/workspace/PRD_FINALIZED.md` (302 lines, 48581 chars)
- Output: `PRD_COMPLETED.md` (302 lines, 51901 chars; char-delta +3320)

**Counts:** 15 ambiguity-pins, 9 mismatch-revisions (24 changed passages total).

**Changes** (all inline edits, no new sections):
- §2.1 — revise — ambiguity — unrecognized `X-User-Role` value is treated as malformed → `ERR_UNAUTHENTICATED` 401 (app.py:165)
- §2.5 — revise — ambiguity — `id` pinned to standard hyphenated UUID (app.py:346 `str(uuid.uuid4())`)
- §2.8 — revise — ambiguity — missing/non-integer OCC version field → `ERR_INVALID_REQUEST` 400 (app.py:278-285)
- §2.9 — insert — ambiguity — network knobs and escrow seed must be non-negative integers (app.py:797-803)
- §3.1 — insert — ambiguity — duplicate taxonomy `code` → `ERR_INVALID_REQUEST` (app.py:831-833)
- §3.2 — insert — ambiguity — duplicate `ein` → `ERR_INVALID_REQUEST` (app.py:884-886)
- §3.2 — insert — ambiguity — `funder_type` accepted as declared for any org_type, no cross-validation (app.py:883)
- §3.2 — revise — mismatch — suspension pauses only the org's `ACTIVE` offerings (app.py:950-953)
- §3.2 — revise — mismatch — termination locks only `ACTIVE` offerings to `PAUSED` (app.py:998-1001)
- §3.3 — insert — ambiguity — unknown `category_code` on offering create → `ERR_INVALID_REQUEST` (app.py:1032-1033)
- §3.3 — insert — ambiguity — `min_client_age` must be non-negative; `eligible_genders` default `["ANY"]` (app.py:1021,1025)
- §3.5 — revise — mismatch — routing-gate business-rule order pinned to impl: consent → agreement → offering/category → eligibility → capacity → receiver-CBO → org-active (app.py:1406-1473)
- §3.5 — revise — mismatch — reassign: optional `new_consent_id` (validated, rewrites `consent_id`); decline-reassign does NOT increment `reassignment_count`/`reopen_count` (app.py:1545-1585)
- §3.5 — insert — ambiguity — URGENT escalation window halved via integer division (app.py:1601-1602)
- §3.5 — insert — ambiguity — `aging_only` true for `true|1|yes` case-insensitive; per-offering referral list restricted to ROUTED/ACCEPTED/IN_SERVICE (app.py:1371-1377, 1385-1387)
- §3.6 — insert — ambiguity — coordinator-authored note records full `X-User-ID` as `author_org_id` (app.py:1704)
- §3.6 — insert — ambiguity — confirm-outcome returns the updated referral object, not the OutcomeRecord (app.py:1665)
- §3.7 — insert — ambiguity — rate card org-type failure is `ERR_ORG_NOT_ACTIVE`; `min_units` minimum 1 (app.py:1767-1778)
- §3.7 — revise — mismatch — claim submission gate order pinned to impl (consent → agreement → units → duplicate → billable); missing rate card → `ERR_INVALID_REQUEST` (app.py:1839-1863)
- §3.7 — revise — mismatch — review/approve/deny enforce caller-org == claim funder (`ERR_FORBIDDEN_ORG`); approve checks consent before SoD; paid-to-date derived from claims by approval month (no stored accumulator); voided claims contribute net amount (app.py:1897-1955)
- §3.8 — revise — mismatch — removed "funder's monthly paid-to-date accumulator is reduced by the approved amount" (no such mutation in impl; cap recovery via net-of-reserve rule) (app.py:503-523)
- §3.8 — insert — ambiguity — disbursement starts with `total_amount_cents` 0; run restricted to funder's own FunderAdmin; `failure_reason` defaults to "Simulated failure"; successful run ends batch in `PAID` (app.py:2032,2060,2070,2091)
- §3.9 — revise — mismatch — DRAFT reports re-sync on every get/list; population = period referrals whose receiver shares an ACTIVE agreement with the funder at evaluation time; outcome counts via outcome record regardless of record date; reimbursed = period-approved minus clawback reserves (app.py:386-434, 2132-2147)
- §3.9 — revise — mismatch — demographic breakdown keys pinned to `gender|race|ethnicity|veteran_status|language` pipe format with lowercase boolean (app.py:441-444)
- §3.9 — revise — mismatch — seal restricted to report's own funder org; `baseline_snapshot_cents` sums `approved_amount_cents` over all claims network-wide (app.py:2153-2165)

No changes were needed for §2.2–2.4, §2.6–2.7, §3.4 (consent cascade), the endpoint table paths/roles (other than the one description fix), or the error catalogue — impl already matches.
