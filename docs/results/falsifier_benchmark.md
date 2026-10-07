# Falsifier efficiency: random search vs cross-entropy method

8 seeds per cell, budget 40 simulations, stop at the first counterexample. Median is over the seeds that found one.

| Template | Mutant (fault hypothesis) | random: found | random: median sims | CEM: found | CEM: median sims |
|---|---|---|---|---|---|
| FZ-001 | M07VoltageGuardSign | 8/8 | 2.0 | 8/8 | 2.5 |
| FZ-001 | M01NoColdDerating | 0/8 | None | 0/8 | None |
| FZ-003 | M09SopAssumesNewPack | 7/8 | 9 | 8/8 | 19.0 |
| FZ-003 | M10NoBrakeReleaseRampOut | 7/8 | 8 | 6/8 | 14.0 |
| FZ-003 | M02RegenUsesDischargeMap | 8/8 | 4.5 | 7/8 | 11 |
| FZ-002 | M05DerateRampInverted | 0/8 | None | 0/8 | None |
