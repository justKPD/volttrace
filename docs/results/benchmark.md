# Orchestration benchmark

## Noise seed set 0

| strategy | bugs_detected | sil_observable_detected | hil_only_detected | vehicle_only_detected | false_alarms_on_clean | mean_hil_minutes | mean_makespan_min | median_ttff_s | clean_change_makespan_min |
|---|---|---|---|---|---|---|---|---|---|
| A | 13/14 | 9/9 | 4/4 | 0/1 | 0/5 | 13.0 | 13.0 | 5.4 | 12.8 |
| B | 13/14 | 9/9 | 4/4 | 0/1 | 0/5 | 12.4 | 12.4 | 5.4 | 12.2 |
| C | 12/14 | 9/9 | 3/4 | 0/1 | 0/5 | 3.1 | 3.2 | 4.4 | 0.7 |

## Noise seed set 1

| strategy | bugs_detected | sil_observable_detected | hil_only_detected | vehicle_only_detected | false_alarms_on_clean | mean_hil_minutes | mean_makespan_min | median_ttff_s | clean_change_makespan_min |
|---|---|---|---|---|---|---|---|---|---|
| A | 12/14 | 9/9 | 3/4 | 0/1 | 0/5 | 13.0 | 13.0 | 5.1 | 12.8 |
| B | 12/14 | 9/9 | 3/4 | 0/1 | 0/5 | 12.4 | 12.4 | 5.1 | 12.2 |
| C | 12/14 | 9/9 | 3/4 | 0/1 | 0/5 | 3.1 | 3.2 | 4.4 | 0.7 |

## Noise seed set 2

| strategy | bugs_detected | sil_observable_detected | hil_only_detected | vehicle_only_detected | false_alarms_on_clean | mean_hil_minutes | mean_makespan_min | median_ttff_s | clean_change_makespan_min |
|---|---|---|---|---|---|---|---|---|---|
| A | 11/14 | 9/9 | 2/4 | 0/1 | 0/5 | 13.0 | 13.0 | 4.8 | 12.8 |
| B | 11/14 | 9/9 | 2/4 | 0/1 | 0/5 | 12.4 | 12.4 | 4.8 | 12.2 |
| C | 11/14 | 9/9 | 2/4 | 0/1 | 0/5 | 3.1 | 3.2 | 4.2 | 0.7 |

## Per change (seed set 0)

| Change | Strategy | Detected in | HiL min | Makespan min | TTFF s |
|---|---|---|---|---|---|
| M01NoColdDerating | A | TC-007@hil_mock, TC-007@sil | 12.7 | 12.7 | 7.3 |
| M01NoColdDerating | B | TC-007@hil_mock, TC-007@sil | 12.1 | 12.1 | 7.3 |
| M01NoColdDerating | C | TC-007@sil | 0.0 | 0.1 | 6.0 |
| M02RegenUsesDischargeMap | A | TC-002@hil_mock, TC-002@sil | 12.8 | 12.8 | 2.5 |
| M02RegenUsesDischargeMap | B | TC-002@hil_mock, TC-002@sil | 12.2 | 12.2 | 2.5 |
| M02RegenUsesDischargeMap | C | TC-002@sil | 0.7 | 0.7 | 2.5 |
| M03NoFrictionCompensation | A | FZ-003-CX2@hil_mock, FZ-003-CX2@sil, FZ-003-CX@hil_mock, FZ-003-CX@sil, TC-001@hil_mock, TC-001@sil, TC-004@hil_mock, TC-004@sil, TC-008@hil_mock, TC-008@sil | 14.1 | 14.1 | 2.2 |
| M03NoFrictionCompensation | B | FZ-003-CX2@hil_mock, FZ-003-CX2@sil, FZ-003-CX@hil_mock, FZ-003-CX@sil, TC-001@hil_mock, TC-001@sil, TC-004@hil_mock, TC-004@sil, TC-008@hil_mock, TC-008@sil | 13.5 | 13.5 | 2.2 |
| M03NoFrictionCompensation | C | FZ-003-CX2@sil, FZ-003-CX@sil, TC-001@sil, TC-004@sil, TC-008@sil | 0.9 | 0.9 | 2.2 |
| M04CanTimeoutInMs | A | TC-005@hil_mock, TC-005@sil | 12.8 | 12.8 | 4.6 |
| M04CanTimeoutInMs | B | TC-005@hil_mock, TC-005@sil | 12.2 | 12.2 | 4.6 |
| M04CanTimeoutInMs | C | TC-005@sil | 11.6 | 11.6 | 4.6 |
| M05DerateRampInverted | A | TC-004@hil_mock, TC-004@sil | 12.2 | 12.2 | 6.4 |
| M05DerateRampInverted | B | TC-004@hil_mock, TC-004@sil | 11.6 | 11.6 | 6.4 |
| M05DerateRampInverted | C | TC-004@sil | 0.0 | 0.1 | 4.2 |
| M06RateLimiterPerMs | A | TC-001@hil_mock, TC-001@sil, TC-004@hil_mock, TC-004@sil | 12.8 | 12.8 | 4.8 |
| M06RateLimiterPerMs | B | TC-001@hil_mock, TC-001@sil, TC-004@hil_mock, TC-004@sil | 12.2 | 12.2 | 4.8 |
| M06RateLimiterPerMs | C | TC-001@sil, TC-004@sil | 0.0 | 0.1 | 4.8 |
| M07VoltageGuardSign | A | TC-003@hil_mock, TC-003@sil | 12.5 | 12.5 | 5.4 |
| M07VoltageGuardSign | B | TC-003@hil_mock, TC-003@sil | 11.9 | 11.9 | 5.4 |
| M07VoltageGuardSign | C | TC-003@sil | 2.8 | 2.9 | 3.1 |
| M09SopAssumesNewPack | A | FZ-003-CX@hil_mock, FZ-003-CX@sil, TC-008@hil_mock, TC-008@sil | 12.8 | 12.8 | 2.2 |
| M09SopAssumesNewPack | B | FZ-003-CX@hil_mock, FZ-003-CX@sil, TC-008@hil_mock, TC-008@sil | 12.2 | 12.2 | 2.2 |
| M09SopAssumesNewPack | C | FZ-003-CX@sil, TC-008@sil | 0.0 | 0.1 | 2.2 |
| M10NoBrakeReleaseRampOut | A | FZ-003-CX2@hil_mock, FZ-003-CX2@sil | 12.8 | 12.8 | 2.2 |
| M10NoBrakeReleaseRampOut | B | FZ-003-CX2@hil_mock, FZ-003-CX2@sil | 12.2 | 12.2 | 2.2 |
| M10NoBrakeReleaseRampOut | C | FZ-003-CX2@sil | 0.0 | 0.1 | 2.2 |
| M11CanTimeoutTooTight | A | FZ-003-CX2@hil_mock, FZ-003-CX@hil_mock, TC-001@hil_mock, TC-002@hil_mock, TC-003@hil_mock, TC-004@hil_mock, TC-007@hil_mock, TC-008@hil_mock | 15.1 | 15.1 | 42.0 |
| M11CanTimeoutTooTight | B | FZ-003-CX2@hil_mock, FZ-003-CX@hil_mock, TC-001@hil_mock, TC-002@hil_mock, TC-003@hil_mock, TC-004@hil_mock, TC-007@hil_mock, TC-008@hil_mock | 14.5 | 14.5 | 42.0 |
| M11CanTimeoutTooTight | C | FZ-003-CX2@hil_mock, FZ-003-CX@hil_mock, TC-001@hil_mock, TC-002@hil_mock, TC-003@hil_mock, TC-004@hil_mock, TC-007@hil_mock, TC-008@hil_mock | 14.5 | 14.5 | 44.2 |
| M12PlausibilityNoDebounce | A | TC-001@hil_mock | 13.8 | 13.8 | 314.0 |
| M12PlausibilityNoDebounce | B | TC-001@hil_mock | 13.2 | 13.2 | 314.0 |
| M12PlausibilityNoDebounce | C | TC-001@hil_mock | 13.2 | 13.2 | 408.2 |
| M13ResistanceEstimatorNoGate | A | TC-008@hil_mock | 12.8 | 12.8 | 769.3 |
| M13ResistanceEstimatorNoGate | B | TC-008@hil_mock | 12.2 | 12.2 | 733.4 |
| M13ResistanceEstimatorNoGate | C | - | 0.0 | 0.1 |  |
| M14MissingVoltageAsZero | A | TC-001@hil_mock | 12.9 | 12.9 | 254.8 |
| M14MissingVoltageAsZero | B | TC-001@hil_mock | 12.3 | 12.3 | 254.8 |
| M14MissingVoltageAsZero | C | TC-001@hil_mock | 12.3 | 12.3 | 349.0 |
| M08NoRegenFade | A | - | 12.8 | 12.8 |  |
| M08NoRegenFade | B | - | 12.2 | 12.2 |  |
| M08NoRegenFade | C | - | 0.7 | 0.7 |  |
| C01RefactorBlendFriction | A | - | 12.8 | 12.8 |  |
| C01RefactorBlendFriction | B | - | 12.2 | 12.2 |  |
| C01RefactorBlendFriction | C | - | 0.0 | 0.1 |  |
| C02GuardRecoveryTweak | A | - | 12.8 | 12.8 |  |
| C02GuardRecoveryTweak | B | - | 12.2 | 12.2 |  |
| C02GuardRecoveryTweak | C | - | 2.8 | 2.9 |  |
| C03DerateExitTweak | A | - | 12.8 | 12.8 |  |
| C03DerateExitTweak | B | - | 12.2 | 12.2 |  |
| C03DerateExitTweak | C | - | 0.0 | 0.1 |  |
| C04RefactorRegenFade | A | - | 12.8 | 12.8 |  |
| C04RefactorRegenFade | B | - | 12.2 | 12.2 |  |
| C04RefactorRegenFade | C | - | 0.0 | 0.1 |  |
| C05ReleaseRateTweak | A | - | 12.8 | 12.8 |  |
| C05ReleaseRateTweak | B | - | 12.2 | 12.2 |  |
| C05ReleaseRateTweak | C | - | 0.0 | 0.1 |  |
