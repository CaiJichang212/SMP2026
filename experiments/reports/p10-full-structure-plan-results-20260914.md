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
