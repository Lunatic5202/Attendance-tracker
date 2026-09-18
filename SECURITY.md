# BT Projects Attendance Tracker Security

## Operating model

The system has two experiences. The **face-scan kiosk** is the employee experience: employees do not create accounts, remember passwords, or handle API keys. A recognized and active enrolled face is the only identity accepted by the public scan endpoint. The **administrator console** is restricted by an administrator password and a short-lived, signed, HttpOnly session cookie. Only administrators can view logs, create or edit employees, enroll or replace faces, disable employees, delete records, or use manual attendance overrides.

Enrollment is never available from the public kiosk. An administrator must first register the employee in the admin console and then complete the face capture from that employee's enrollment flow. A person who is not enrolled cannot create an attendance record even if they know an employee ID.

## Data protection

Employee profile fields, attendance timestamps, and biometric templates are encrypted at rest with Fernet authenticated encryption. Set a long, random `ATTENDANCE_MASTER_KEY` in the deployment environment. The key is not stored in the repository or database. Losing the key makes encrypted data unrecoverable, so store it in the company's secrets manager and maintain a protected backup under the company's own access policy.

The service must run behind HTTPS in production. Set `ENVIRONMENT=production`, configure `ALLOWED_ORIGINS` to the exact company hostname, and never use `*` for CORS. Set a strong administrator password through the environment; it is for administrators only, not employees. Do not commit `.env` files, the database, or the `data/faces` directory.

The default four-hour minimum between check-in and check-out is enforced on the server through `MIN_CHECKOUT_HOURS=4`. Changing the visible UI cannot bypass this rule. An early second scan is rejected and returns the remaining wait time.

## Recommended rollout

Deploy one kiosk browser on a company-controlled device and open the scan route. Keep the administrator console on a restricted company network or protected hostname. Have an administrator register employees during onboarding, capture one or more good face templates according to the company's privacy notice and consent process, and verify a real check-in followed by an early rejected check-out before opening the kiosk to staff.

Back up the encrypted database and encrypted face-template directory together with the master key. Test restoration periodically. Rotate the administrator password when administrators change; rotate the encryption key only through a planned re-encryption migration because existing records depend on the current key.

## Important limitations

Face recognition is biometric processing and should be deployed only after BT Projects has completed its employee notice, consent, retention, access, and applicable employment/privacy-law review. OpenCV LBPH is a practical local recognition engine, not a full anti-spoofing system. Add liveness detection and a documented fallback process before treating this as a high-assurance security boundary.
