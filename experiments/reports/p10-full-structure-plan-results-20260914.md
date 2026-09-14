# P10 unrestricted full structural-plan development

## Scope and decision

P10 is development-only. It does not modify the qualified bounded P9 policy,
runtime, submission configuration, or artifact. Both cohorts were already used
for development: the six P8 families at repetition 501 and the original six
families at repetition 1. No new confirmation repetition was opened.

The first protocol compared depth 4 and depth 6 with the original strict
five-scenario selection plus eight-scenario audit rule. The second protocol was
registered before its run and compared depth 12 strict with a new
`mean_audited` arm. The latter requires positive means in both the selection
and unused audit scenarios but reports and permits individual predicted losses.
The old strict result was not relabelled.

The mean-audited depth-12 arm is the stronger development candidate. It needs a
new frozen confirmation design before any production consideration. These local
gains are not converted to an official score.

## Algorithm

At the fully scanned public state, the search considers every legal shield and
cut. It applies no persona, sign, direction, positive-graph, or singleton-ROI
filter. This includes negative-negative cuts and low-positive/low-positive cuts
excluded by the current structural direction gate.

Each beam state is ranked by the exact component terminal score after its whole
structural prefix and a bounded mean-response persuasion allocation. Equal
terminal topologies are deduplicated. A node that has participated in a cut is
not later shielded, preventing a cut whose effect would be erased. A bounded
delete-or-exchange pass refines the best beam plan.

The persuasion allocation is used to value the structural state. The risk
rollout and real execution force only the complete structure prefix, then return
to bounded P9 so later communication decisions can use actual public responses.
Rejected plans execute the exact bounded P9 fallback.

## Results

| Development arm | Cases | Mean delta vs P9 | Win / tie / loss | Minimum | Accepted | Mean wall time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| depth4 strict, P8-501 | 6 | +0.802976 | 1 / 5 / 0 | 0 | 1 | 16.39 s |
| depth6 strict, P8-501 | 6 | +0.802976 | 1 / 5 / 0 | 0 | 1 | 18.37 s |
| depth12 strict, both cohorts | 12 | +3.777558 | 2 / 10 / 0 | 0 | 2 | 12.23 s |
| depth12 mean-audited, both cohorts | 12 | +7.508684 | 6 / 6 / 0 | 0 | 7 | 9.99 s |

Depth-12 mean-audited gained +6.826744 on the P8-501 cohort and +8.190625
on legacy repetition 1. Its individual gains were +22.803857 and +22.526844
on the two negative-hub cases, +14.751084 on P8-501 violent-cluster SBM,
+21.331530 on legacy negative-bridge SBM, and +3.405521/+5.285374 on the two
sparse-component cases. One accepted P8-501 negative-bridge plan tied P9.

All 24 depth-12 arm cases had zero failed actions, nonnegative remaining budget,
at most 117 steps, and exact action-cost accounting. All 15 rejected arm cases
matched bounded P9 in action sequence, counts, budget, and score. The search
considered 118--228 legal root structure actions and expanded 4,721--9,041
topology states where a positive plan existed. Mean search time was 5.03 seconds
and maximum search time was 8.96 seconds; reported arm wall time includes search.

## Failure attribution

The shallow screen found only four to six early shields on the negative-hub
case and improved by +4.817858. Depth 12 selected nine shields and improved by
about +22.5 to +22.8 on both distributions. The binding limit was therefore the
prefix length, not root candidate coverage.

The main realized loss in bounded P9 is action interaction across time. In five
of the six positive mean-audited cases, P9 communicated one or two times with a
node it later shielded. The complete prefix reduced such wasted communications
from 1--2 to zero. On P8-501 violent-cluster SBM, P10 and P9 ultimately shielded
the same nine nodes, but P10 shielded them before persuasion and gained
+14.751084. On the two negative-hub cases, P10 also spent five to ten more
budget points on shielding and removed an additional harmful node.

The sparse P8-501 gain used the previously excluded mixed plan `cut 7-8`,
`shield 20`, `shield 38`; it changed the terminal portfolio from one shield and
35 communications to one cut, two shields, and 31 communications.
The cut endpoints were both publicly negative (`-7.786097` neutral and
`-27.052188` violent), directly confirming the negative-negative coverage gap.

Mean-audited admitted substantial predicted downside in some scenarios. The
accepted legacy negative-bridge plan had selection/audit minima -24.558884 and
-24.183034; the accepted P8 sparse plan reached -19.523484. Their realized
development gains were positive, but this small consumed sample does not bound
future downside. A future confirmation must preserve the mean objective while
reporting the full loss tail and action legality.

#### Isolated CaseVO runtime trial

`P10RuntimeController` is an experiment-only subclass and is absent from the
submission build and configuration. It searches exactly once after the full
scan. A P10 candidate reason contains the complete structure sequence, total
cost, selection and audit means and minima, and states that selecting its ID
approves the whole prefix. The baseline remains a separate selectable ID.

After explicit LLM approval, the controller queues one prefix action at a time.
Every host step revalidates the current action against public state and budget,
and advances the prefix only after a successful environment return. A failed
middle action clears the remainder and returns to P9 with the environment's
actual debited budget. When the prefix completes, P9 replans persuasion from
the observed responses. Missing or invalid LLM output and an explicit baseline
choice cannot start the prefix.

On the consumed `ba_negative_hubs/501` seed, the mock CaseVO commander approved
the nine-shield prefix and reproduced `303.687560 -> 326.491418`, a
`+22.803857` gain. All nine prefix actions succeeded, the controller searched
once, and no action or planning error occurred. The same runtime with the mock
commander selecting the P9 baseline reproduced `303.687560` exactly, with zero
approved or completed prefixes. The plan payload reported structure cost 45,
selection mean/minimum `70.439829/56.279610`, and audit mean/minimum
`71.356061/41.243251`.

An optional experiment-local response ledger hook can supply P10's terminal
persuasion estimator and receive successful, uncensored first public responses.
The default is `None`, preserving P9 estimates. The hook does not silently
alter the P9 fallback; a future combined arm requires its own preregistration.

#### Plan, response and combined runtime arms

The follow-up runtime protocol separated `plan_only`, `response_only`, and
`combined` without changing P9. P10 stores the complete candidate map returned
by P9 for deterministic fallback. Its LLM terminal comparison exposes only the
new plan, the PG reference, and an existing P8 terminal proposal when present.
P8 and P10 scores are equal-resource continuation gains relative to PG, and
their displayed ROI divides by current total budget. Immediate candidate scores
cannot numerically suppress a complete plan.

The fixed mock ranker selects the largest terminal gain among PG, P8 and P10,
rather than selecting P10 by identity. Invalid or missing model output rebuilds
P9's deterministic fallback from the stored original candidate map. A valid
model may select the original PG or P8 alternative to reject the new plan.

The previously completed 18-case gated-ledger experiment gained +19.647184
against the fixed estimator (`8/10/0`) and remained exactly equal on all six
legacy-independent cases. The CaseVO comparison therefore used those six
legacy repetition-1 seeds for four strictly paired runtime arms:

| Runtime arm vs P9 | Cases | Mean delta | Win / tie / loss | Minimum |
| --- | ---: | ---: | ---: | ---: |
| plan_only | 6 | +7.309729 | 2 / 4 / 0 | 0 |
| response_only | 6 | 0.000000 | 0 / 6 / 0 | 0 |
| combined | 6 | +7.309729 | 2 / 4 / 0 | 0 |

Every response-only action hash matched P9, and every combined action hash
matched plan-only. The response gate stayed closed in all legacy-independent
cases. This proves the initial combined plan used P9's original estimator and
that an unactivated ledger does not change root search. Plan-only and combined
selected P10 only for `ba_negative_hubs` (+22.526844) and
`sbm_negative_bridges` (+21.331530); all other families retained P9.

All 24 runtime sessions had zero action, P8-planning, P10-planning, prefix, or
response-estimator failures and nonnegative remaining budget. Plan-only and
combined searched exactly once per case; response-only and P9 never searched.
Full action logs remain in ignored `experiments/raw/`; the committed compact
report stores their SHA-256 identities and first divergences.

#### Complete 18-case development selection

The frozen combined-development protocol required all 18 consumed cases, so
the six legacy rows above were reused by exact raw/source hash and extended
with four resampled topology families under centered-independent,
persona-aligned and persona-inverse responses. Each case ran P9, plan-only,
response-only and combined through the same CaseVO path and terminal-gain mock
ranker. Two workers ran different paired cases; all four arms of one case stayed
together.

| Arm vs P9 | Cases | Mean delta | Win / tie / loss | Minimum |
| --- | ---: | ---: | ---: | ---: |
| plan_only | 18 | +6.467053 | 8 / 7 / 3 | -18.197513 |
| response_only | 18 | +20.157102 | 8 / 10 / 0 | 0 |
| combined | 18 | +26.018476 | 13 / 4 / 1 | -18.197513 |

The preregistered selection takes the highest positive mean and prefers a
simpler arm only when means differ by less than one point. Combined exceeds
response-only by +5.861374, so **combined is the development winner**. This is
not a confirmation or production decision.

| Response group | plan_only | response_only | combined |
| --- | ---: | ---: | ---: |
| legacy independent, 6 | +7.309729 | 0.000000 | +7.309729 |
| centered independent, 4 | +4.408261 | 0.000000 | +4.408261 |
| persona aligned, 4 | +14.291369 | +33.552403 | +48.642792 |
| persona inverse, 4 | -0.562487 | +57.154555 | +53.067495 |

The response gate activated in all eight aligned/inverse cases and in none of
the ten independent cases. It was never disabled by an exception. Plan-only
and combined each received 11 explicit plan approvals. Across 72 sessions,
there were no action, P8-planning, P10-planning, prefix, response-estimator,
budget, or step-limit failures; maximum action attempts were 87.

All losses remain visible. Plan-only lost -18.197513 on ER centered-independent,
-2.249946 on BA inverse, and -1.387069 on SBM aligned. Combined retained only
the ER centered-independent loss of -18.197513; response-only had no losses.
On inverse cases, combining plans reduced response-only's mean by 4.087060,
while on aligned cases it added 15.090389. This interaction is why the selected
combined arm requires a genuinely fresh, stratified confirmation rather than
adding the two marginal means.
