# Explore loop: response uncertainty

Holdout exposed a loss on135: shield32 has predicted completion advantage only
0.544 but consumes a higher-performing alternative communication allocation.
Observed score proxy errors alone do not capture uncertainty about future hidden
node responses. Reopen Explore BEFORE application;126-143 now include inspected
failure cases and cannot be reused as fresh holdout for this refinement.

New alternative: evaluate communication-tail opportunity at0.5,1,1.5 times the
current estimate; rank/filter structures on worst advantage. Because tail value
is linear, worst advantage = future_advantage -0.5*abs(future_advantage-gain).
These are stress scenarios, not probability bounds or known hidden coefficients.
Retain nominal gains and alternative communications for LLM final choice.

Screen120-143 versus frozen incumbent/completion results. If promising, freeze
and use NEW holdout144-161 in simulation, with preregistered official subset
144,145,152,153,160,161 (all six topologies). Gate as before: positive paired mean,
>=4/6wins, natural mean exceeded, proxyMAE<=5/max<=20. Report regressions.
No tuning scenario endpoints on this new holdout. SingleCPU serial bounded runs.
