# P11 anchor resource and target clarification

The completed 36-case screen used one informative low probe node in every case,
so its measured calibration cost was exactly 6 probe budget plus 2 anchor budget
(`8` total). The general anchor subclass can inherit frozen P11 cases that need
a second probe node after all-zero, clipping, or failure. Its true worst-case
bound is therefore 12 probe budget plus 2 anchor budget (`14` total), not 8.

The anchor target is the highest public component-influence eligible node after
excluding every node already reserved in `p11_probe_nodes`. With the measured
one-node cohort that excludes only the used low probe. In a two-node fallback
episode it also excludes the reserved second probe node, even if early evidence
later makes that node unnecessary. Reports and future protocols must say
"highest among remaining eligible non-probe nodes", not "highest untouched node"
without qualification.

This clarification does not alter the frozen P11 runtime, the completed 36-case
actions, scores, preregistered gates, or the anchor subclass source. The full
252-case protocol records the corrected 8 ordinary / 14 worst-case bounds and
tests the resource limit directly.
