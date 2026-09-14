# P11 high-influence probe selector development result

This 36-pair experiment used only consumed legacy repetition-1 graphs and all
six permutations of `[15,10,-5]`. The frozen P11 runtime, prompt sequence,
eligibility, one-node probe cost, LLM protocol, and downstream policy were
identical. The candidate changed only the probe-node selector from lowest
public degree to highest public component settlement influence.

The result had a large positive average but failed the preregistered worst-case
gate:

| Metric | High minus low |
| --- | ---: |
| Symmetric mean | +39.3036 |
| Minimum / maximum | -22.4697 / +95.3589 |
| Win / tie / loss | 27 / 1 / 8 |
| Prompt-1-best mean | +42.0487 |
| Prompt-1-best win / tie / loss | 10 / 1 / 1 |

Family means were highly heterogeneous:

| Family | Mean |
| --- | ---: |
| `er_balanced` | -9.8756 |
| `ba_negative_hubs` | +94.8977 |
| `ws_peace_majority` | +5.9758 |
| `sbm_negative_bridges` | -0.7041 |
| `sbm_violent_cluster` | +67.6940 |
| `three_sparse_components` | +77.8339 |

Four gates passed: overall mean greater than 1, prompt-1-best mean positive,
four of six family means nonnegative, and zero identity/resource/action/planner
failures. The minimum-pair requirement `>= -10` failed twice as strongly at
`-22.4697`. Development selection therefore fails and no 1401-1403 holdout is
opened.

The candidate selected a different probe node in all 36 cases. Communications
later erased by shielding fell from 42 actions (84 budget units) under the low
selector to 16 actions (32 units) under the high selector. That reduction helps
explain large gains on BA, violent-SBM and sparse-component graphs, but it is
not a pure probe-value effect. The reference node changes the learned response
magnitude, which changes communication/structure ordering and target reuse. ER
losses persisted even when both arms later erased the same node's persuasion.

Against the unchanged no-probe P9 ZIP, low-selector P11 averaged `+140.7822`
with minimum `-140.3027`; high-selector P11 averaged `+180.0858` with minimum
`-66.0768`. Those averages do not override the direct high-versus-low gate.
This selector remains a rejected development experiment and is not combined
with the separately evaluated unknown-prior discount.

Machine report:
`experiments/reports/p11-high-influence-probe-development-20260914.json`,
SHA-256 `10f72633da3b44572d1a97beb0d7202cbfde80b421748975f37166ceeeec2348`.

Frozen identities:

- selector SHA-256: `be1a83fa07eec2df64df6e2a5cdcbae966d873c2a71850c59a33b2fa2dbeeaa1`
- runner SHA-256: `38881975b106acce099c45908881667f7a80a694df32e4dc41324b1b5925c012`
- P11 runtime SHA-256: `98ae3471bd5eb9d024bd96ac678f19a6807877cccb45df53622b70a614880612`
- raw report SHA-256: `0a16d268da46535ac0fba647162483130fe75518cf540917430af287f548f769`
