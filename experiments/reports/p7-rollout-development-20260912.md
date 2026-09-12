# P7 public-state rollout development report

P7 is an isolated offline experiment. It is not connected to the production
controller or submission build, and the scores below are not platform scores.

## Registered variants

- `mean`: one deterministic public-prior scenario (`r = 0.85`).
- `sampled`: three fixed public-prior scenarios. Samples are keyed only by
  node ID and scenario index, never by the local environment seed or hidden
  response factor.
- Each decision compares at most three first actions: current public-greedy,
  the first structural action from the P6 budget plan when available, and the
  highest immediate-gain shield/cut when available. P6 uses `depth=1,width=2`.
- All alternatives use the same paired scenarios. An alternative replaces the
  baseline only when mean simulated gain is positive and worst simulated gain
  is nonnegative.

Unknown responses remain private to each rollout scenario and become visible
to that rollout's greedy policy only after the simulated communication action.
Hypotheses use `PredictiveState` and a dedicated read-only projection object;
they never enter `Blackboard`.

## Development results

The repetition-301 screen favored `mean`: mean delta `+11.1545`, minimum
paired delta `-0.2979`, versus sampled mean delta `+10.2167` and minimum
`-4.3505`. Because sampled was weaker in both aggregate and lower-tail result,
only mean was expanded to repetitions 302-303. This was an experiment-budget
decision; sampled has only 13 development cases and is not a complete 39-case
cohort.

Across the complete 13-family, repetition 301-303 mean cohort:

- 39 paired cases: 19 wins, 18 ties, 2 losses.
- Mean delta: `+9.3665`.
- Minimum / maximum paired delta: `-9.3245 / +73.6736`.
- Every family mean was nonnegative.
- Family bootstrap 95% interval: `[+2.9743, +17.2559]`.
- Resource audit and the preregistered statistical gate passed.
- Candidate execution time totaled 326.1 seconds; the slowest case was 56.7
  seconds, with 513 rollout evaluations across the cohort.

Machine-readable audit:
`p7-rollout-mean-dev-r301-r303-summary-20260912.json`.

The positive local gate supports further independent or remote validation. It
does not by itself authorize production promotion.
