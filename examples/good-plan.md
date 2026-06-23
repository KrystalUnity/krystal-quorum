# Add Export Button

## Goal

Add an export button to the dashboard so users can download the currently visible data as CSV.

## Non-goals

- Do not add scheduled exports.
- Do not change dashboard filters.
- Do not add new backend storage.

## Implementation

1. Add an export button beside the existing dashboard actions.
2. Serialize the currently visible table rows to CSV.
3. Download the file as `dashboard-export.csv`.
4. Show a disabled state while the export is being prepared.

## Acceptance Criteria

- The button is visible when the dashboard has rows.
- The downloaded CSV contains the same columns and rows currently visible in the dashboard.
- Empty dashboards show the button disabled.
- Existing dashboard tests still pass.

## Rollback Plan

Remove the export button and CSV helper if the feature causes regressions.

## Verification

Run the dashboard unit tests and manually export a filtered dashboard.
