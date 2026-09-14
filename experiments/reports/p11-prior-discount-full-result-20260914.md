# P11 prior discount full-distribution result

The fixed `0.9` unknown-node prior discount is rejected. The preregistered
runner stopped at case 43 of 252 when the first irreversible gate failure was
observed.

| Field | Result |
| --- | --- |
| Rejection case | `legacy:ws_peace_majority:1:wide:24.0_7.0_-12.0` |
| Discounted P11 minus original P11 | `-12.694049` |
| Required worst pair | `>= -10` |
| Candidate status | aborted, rejected |
| Confirmation opened | no |

Both arms spent the same six-point probe budget and selected prompt 1. The
discount did not change prompt identification. It changed the later allocation:
the discounted planner replaced fresh first communications to nodes 40, 41 and
43 with repeated communications to observed nodes 32, 29 and 34. The observed
first-slot responses imply approximately `59.55` direct opinion gain for the
fresh group versus `44.92` for the replacement repeat slots. The terminal score
loss was `12.69`.

The earlier 36-pair base-amplitude screen therefore did not generalize to the
wide-amplitude peace-majority case. A fixed global shrinkage factor overweights
exploitation when strong unknown-node responses remain available. The
development-only subclass stays outside INLINE and canonical P11 remains on the
unscaled empirical prior. Full raw evidence is under
`experiments/raw/p11-prior-discount-full-development-20260914/`.
