# P8 computation equivalence

Commit `3f8c0c7` removes an unused counterfactual settlement calculation for
communication candidates from `ExperimentalPublicGreedyPlanner`. Their gain
was already computed as the public component coefficient multiplied by the
estimated response; the discarded `after` score was not used. Structural
counterfactual calculations and every candidate's gain/ranking are unchanged.

Compared with the exact class loaded from commit `a5c5450`, 240 random graphs
with 2--30 nodes, mixed signs/personas, 0--3 communication slots, and varying
conservative/communication-deferral flags produced identical candidate lists,
including every dataclass field and ordering. Seed: `20260913`. Aggregate
candidate-generation time in this local microbenchmark was 2.5259 seconds
before and 1.9540 seconds after; concurrent experiment load means this is not
a production latency estimate. All 14 structural tests passed.

The positive graph performance regression test now expects only one settlement
score call (the initial state), rather than that call plus three unused
communication counterfactuals. P8 screen jobs already running used the older
dependency loaded in memory; subsequent runs can use the equivalent faster
dependency. P8 candidate policy source itself was not changed by this commit.
This optimization has no claimed score gain.
