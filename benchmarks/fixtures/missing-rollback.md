# Change Password Reset Flow

## Goal

Replace the current password reset email with a new branded template and a shorter token expiry.

## Acceptance Criteria

- Password reset emails use the new template.
- Reset tokens expire after 15 minutes.
- Existing valid tokens continue to work until they expire.

## Implementation

1. Update the email template.
2. Change the token expiry constant.
3. Update the token expiry test.

## Verification

Run the auth unit tests.

## Risks

Users may request a reset before deployment and click the link after deployment.
