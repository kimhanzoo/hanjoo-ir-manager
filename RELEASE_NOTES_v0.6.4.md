# HanJoo IR 0.6.4

## Identification/Test improvements

- Protocol-family-only candidates (for example `Samsung32 family`) can now replay a freshly captured RAW command for a real hardware test even when no exact model is known yet.
- RAW replay verification is deliberately separated from exact model/profile verification: a successful replay proves capture/transmit works, but does not falsely claim the model is identified.
- Remote identification now automatically searches the detected brand/model hints across:
  - HanJoo Protocol Engine
  - saved/imported profiles
  - SmartIR
  - Flipper-IRDB
- Matching brand/model suggestions are shown directly below the recognition result, similar to the normal brand/model search page.
- Suggested profiles can be tested first and only become installable after the user confirms the physical device responded correctly.
- The previous dead-end error `The candidate has no valid test source` is avoided for recognition-only family candidates by using the captured RAW frame as the test source.

## Safety

- RAW test payloads are admin-only, limited to 6..20,000 timings and a 20..80 kHz carrier.
- Existing IR code validation still enforces maximum timing duration and total airtime.
- Brand/model suggestions do not increase recognition confidence and cannot trigger an automatic recommendation.

## Version

Add-on, bundled Manager, Brain fallback version and validation workflow are aligned at 0.6.4.
