# Cheering Shop — Authentication API

**For the mobile/frontend team.** Covers customer signup and login, vendor
registration, and administrator approval.

Base URL: `https://api.cheeringshop.online/api/v1`
Interactive docs: `https://api.cheeringshop.online/docs`

> The server also answers on `https://srv1128440.hstgr.cloud` during the
> migration. **Use the `api.cheeringshop.online` address** — the other one will
> be retired once every client has moved.

Everything below is implemented, deployed and covered by tests. **Vendor
operations — storefront, menu, order queue, handoff, analytics — are documented
separately in [VENDOR-API.md](VENDOR-API.md)** and are also implemented. The
remainder of the API (restaurants, discovery, cart, orders) returns
`501 NOT_IMPLEMENTED` with the correct response shape, so you can build against
those contracts too.

---

## Contents

1. [Conventions](#1-conventions) — envelope, tokens, errors
2. [Registration](#2-registration) — the signup journey
3. [Login](#3-login) — password, biometric, Google, 2FA
4. [Forgot password](#4-forgot-password)
5. [Session management](#5-session-management) — refresh, logout
6. [Profile & security](#6-profile--security)
7. [Two-factor authentication](#7-two-factor-authentication)
8. [Biometric setup](#8-biometric-setup) — the crypto contract
9. [Error reference](#9-error-reference)
10. [Endpoint summary](#10-endpoint-summary)
11. [Vendor registration](#11-vendor-registration) — restaurant owners
12. [Roles](#12-roles) — who can create what

---

## 1. Conventions

### Every response has the same shape

**Success**
```json
{ "success": true, "data": { ... }, "meta": { ... } }
```

**Failure**
```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Invalid input provided",
    "details": ["password: String should have at least 8 characters"]
  }
}
```

Branch on `error.code`, never on `error.message` — messages may be reworded,
codes will not. `details` is present only for validation failures.

### Tokens

Successful authentication returns:

```json
{
  "tokens": {
    "access_token": "eyJhbGci...",
    "refresh_token": "eyJhbGci...",
    "token_type": "Bearer",
    "expires_in": 1800
  },
  "user": { "id": "...", "role": "CUSTOMER", "email": "...", ... }
}
```

| Token | Lifetime | Store in |
|---|---|---|
| `access_token` | **30 minutes** | memory / secure storage |
| `refresh_token` | **30 days** | Keychain (iOS) / EncryptedSharedPreferences (Android) |

Send the access token on every authenticated call:

```
Authorization: Bearer <access_token>
```

**Refresh tokens rotate.** Every call to `/auth/refresh` returns a *new* refresh
token and invalidates the old one. You must persist the new one immediately.

> ⚠️ **Reusing an old refresh token revokes the entire session family** and
> forces a full re-login. This is deliberate anti-theft behaviour — but it means
> a buggy client that retries a refresh with a stale token will log the user
> out. Serialise your refresh calls; never fire two at once.

### Request tracing

Every response carries `X-Request-ID`. **Log it.** When reporting a bug, send
that value — it ties directly to the server logs for that exact request.

---

## 2. Registration

> **User story**
> *As a new customer, I want to sign up with my email, choose a password, give
> my name and phone, and optionally turn on Face ID, so I can order food.*

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Enter email        → POST /auth/otp/send                 │
│ 2. Enter 4-digit code → POST /auth/otp/verify   ── tokens ──┤
│ 3. Choose password    → POST /users/me/password             │
│ 4. Name + phone       → PUT  /users/me/profile              │
│ 5. Enable Face ID     → POST /auth/biometrics/enable  (opt) │
│    Registration complete                                     │
└─────────────────────────────────────────────────────────────┘
```

You are **authenticated from step 2 onwards** — steps 3–5 all require the
`Authorization` header.

### Step 1 — Send the code

```http
POST /api/v1/auth/otp/send
Content-Type: application/json

{ "email": "customer@example.com" }
```

> Customer signup needs nothing else. Restaurant owners add
> `"role": "VENDOR"` here — see [§11](#11-vendor-registration). The role is
> fixed at creation and cannot be changed later.

```json
{ "success": true, "data": { "message": "OTP sent" } }
```

A **4-digit** code is emailed. It expires in **5 minutes**.

| Situation | Response |
|---|---|
| Sent | `200` |
| Requested again within 60s | `429` + `Retry-After` header |

Show a countdown from the `Retry-After` value before re-enabling "Resend code".

> The response is `200` whether or not the address already has an account —
> that is intentional, so nobody can use this endpoint to discover who is
> registered. Do not branch on it.

### Step 2 — Verify the code

```http
POST /api/v1/auth/otp/verify
Content-Type: application/json

{ "email": "customer@example.com", "code": "4821" }
```

```json
{
  "success": true,
  "data": {
    "tokens": { "access_token": "...", "refresh_token": "...", "expires_in": 1800 },
    "user": { "id": "...", "role": "CUSTOMER", "email": "customer@example.com",
              "is_email_verified": true, "full_name": null, "phone": null }
  }
}
```

**Store both tokens now.** The user is signed in.

| Situation | Response | `error.code` |
|---|---|---|
| Wrong code | `400` | `INVALID_OTP` |
| Expired | `400` | `INVALID_OTP` |
| 3 wrong guesses on one code | `429` | `RATE_LIMITED` |
| 10 guesses in an hour | `429` | `RATE_LIMITED` |

On `RATE_LIMITED`, send them back to step 1 for a fresh code.

**Shortcut:** you may pass `password` and `full_name` in this same call to
collapse steps 2–4 into one request. The stepwise flow below is what your
described UI does, so use whichever matches your screens.

### Step 3 — Choose a password

```http
POST /api/v1/users/me/password
Authorization: Bearer <access_token>

{ "new_password": "MyFirstPass1!" }
```

```json
{ "success": true, "data": { "message": "Password set", "sessions_revoked": 0, "tokens": null } }
```

`current_password` is **not required** here — the account has no password yet.

> **Your session survives this call.** `sessions_revoked` is `0` and `tokens` is
> `null`, meaning nothing changed about your session; keep using the tokens from
> step 2. (Changing an *existing* password behaves differently — see §6.)

Minimum 8 characters. Enforce it client-side too so users see the error before
a round trip.

### Step 4 — Name and phone

```http
PUT /api/v1/users/me/profile
Authorization: Bearer <access_token>

{ "full_name": "Rahim Uddin", "phone": "+8801712345678" }
```

```json
{
  "success": true,
  "data": { "id": "...", "full_name": "Rahim Uddin", "phone": "+8801712345678",
            "is_email_verified": true, "is_phone_verified": false }
}
```

> **`is_phone_verified` is `false`, and that is correct.** Typing a number is
> not proof of owning it. The number is stored so a rider can call — verifying
> it is a separate flow, not yet built.

| Situation | Response | `error.code` |
|---|---|---|
| Phone already on another account | `409` | `CONFLICT` |

⚠️ **This is a PUT: omitted fields are cleared.** Sending
`{"full_name": "Rahim"}` alone will wipe an existing phone number. Always send
the complete profile.

### Step 5 — Enable biometrics (optional)

See [§8](#8-biometric-setup) for the key generation contract. Once you have a
public key:

```http
POST /api/v1/auth/biometrics/enable
Authorization: Bearer <access_token>

{
  "device_id": "unique-per-install-uuid",
  "device_name": "Rahim's iPhone 15",
  "public_key": "<base64 DER SubjectPublicKeyInfo>",
  "algorithm": "ES256"
}
```

Registration is now complete.

---

## 3. Login

> **User story**
> *As a returning customer, I want to sign in with my password or with Face ID.*

### 3a. Email + password

```http
POST /api/v1/auth/login

{ "email": "customer@example.com", "password": "MyFirstPass1!" }
```

**Two possible success responses.** Check for `requires_2fa` before assuming
you have tokens:

```json
{ "success": true, "data": { "tokens": {...}, "user": {...} } }
```

```json
{ "success": true, "data": { "requires_2fa": true, "temp_token": "...", "expires_in": 300 } }
```

If `requires_2fa` is present, go to [§7](#7-two-factor-authentication).

| Situation | Response | `error.code` |
|---|---|---|
| Wrong password **or** no such account | `401` | `INVALID_CREDENTIALS` |
| 10 failures for one email in 15 min | `429` | `RATE_LIMITED` |

> Unknown-account and wrong-password return **byte-identical** responses, on
> purpose. Never show "no account with that email" — you cannot tell, and
> neither should an attacker.

### 3b. Biometric

Two calls: fetch a challenge, sign it, send the signature.

```http
POST /api/v1/auth/biometrics/challenge

{ "device_id": "unique-per-install-uuid" }
```

```json
{ "success": true, "data": { "challenge": "hK3n...random...", "expires_in": 120 } }
```

Prompt Face ID / fingerprint, sign the **raw UTF-8 challenge string** with the
device private key, then:

```http
POST /api/v1/auth/biometrics/login

{ "device_id": "unique-per-install-uuid", "signature": "<base64 signature>" }
```

Returns tokens, or a `requires_2fa` challenge if 2FA is enabled.

| Situation | Response | `error.code` |
|---|---|---|
| Challenge expired (>2 min) or reused | `401` | `INVALID_CREDENTIALS` |
| Bad signature / unknown device | `401` | `INVALID_CREDENTIALS` |
| 5 consecutive failures | `401` | `FORBIDDEN` — device locked, must re-enrol via password login |

> **Challenges are single-use.** Fetch a fresh one for every attempt; never
> cache. A captured signature cannot be replayed.

### 3c. Sign in with Google

> *As a new customer, I want to start ordering without waiting for a code in my
> inbox.*

This is the **server-side** flow: your app never handles a Google SDK, a client
secret, or an authorization code. It opens one URL and waits for a deep link.

**Step 1 — open the browser.**

```
GET https://api.cheeringshop.online/api/v1/auth/google/authorize
```

Open it in an **in-app browser tab** — `SFSafariViewController` on iOS,
Chrome Custom Tabs on Android, `flutter_web_auth_2` or `expo-web-browser` if
you would rather not wire those up yourself.

> **Not a WebView.** Google blocks sign-in from embedded WebViews
> (`disallowed_useragent`) precisely because the host app can read what is
> typed into one. A custom tab is a real browser and works.

The server answers `307` to Google's consent screen. Do not follow it yourself,
do not parse it, and do not rebuild this URL in the app — it carries a PKCE
challenge that is generated per attempt and held server-side.

**Step 2 — catch the deep link.**

When the user finishes, the browser lands on `/auth/google/callback`, which
does all the work and redirects to your app's custom scheme:

```
crshop://auth/callback#access_token=eyJ...&refresh_token=abc...&expires_in=1800&token_type=Bearer
```

Read the values from the URL **fragment** (everything after `#`) and store them
exactly as you store tokens from `/auth/login`. There is no difference from
that point on: the same access token, the same 30-day refresh token, the same
`/auth/refresh` and `/auth/logout`.

If the user taps **Cancel** on the consent screen you get the same deep link
with an error instead, so your spinner always gets dismissed:

```
crshop://auth/callback#error=access_denied
```

**Registering the scheme.** `crshop` is the default; the exact value is server
configuration (`GOOGLE_POST_AUTH_REDIRECTS`), so confirm it before shipping.

```xml
<!-- android/app/src/main/AndroidManifest.xml, inside <activity> -->
<intent-filter>
    <action android:name="android.intent.action.VIEW" />
    <category android:name="android.intent.category.DEFAULT" />
    <category android:name="android.intent.category.BROWSABLE" />
    <data android:scheme="crshop" android:host="auth" />
</intent-filter>
```

```xml
<!-- ios/Runner/Info.plist -->
<key>CFBundleURLTypes</key>
<array><dict>
    <key>CFBundleURLSchemes</key>
    <array><string>crshop</string></array>
</dict></array>
```

**What the account looks like afterwards.** A first-time Google sign-in creates
a `CUSTOMER` with `is_email_verified: true` and **no password**, so
`/users/me/security` returns `has_password: false` — hide "change password" and
offer "set a password" instead. `linked_providers` will contain `"google"`.

If the Google address already belongs to an account, the two are **linked**,
not duplicated: same user id, same order history, and password login keeps
working. This happens only when Google reports the address verified.

| Situation | Response | `error.code` |
|---|---|---|
| Server has no Google credentials configured | `501` | `NOT_IMPLEMENTED` |
| `?redirect=` is not on the server's allowlist | `400` | `VALIDATION_FAILED` |
| Callback replayed, or `state` older than 10 minutes | `401` | `UNAUTHORIZED` |
| Google's email is unverified | `400` | `VALIDATION_FAILED` |
| Account deactivated | `401` | `UNAUTHORIZED` |
| More than 30 `/authorize` calls in an hour from one IP | `429` | `RATE_LIMITED` |

> **2FA is not re-prompted.** Google has already applied whatever second factor
> the user set up with them, and the browser is on its way back to the app with
> nowhere left to prompt. A user with TOTP enabled still gets challenged on
> `/auth/login`.

---

---

## 4. Forgot password

> **User story**
> *As a customer who forgot their password, I want to reset it by email.*

```
1. Enter email      → POST /auth/password/forgot
2. Enter code       ┐
3. Enter new password ┴→ POST /auth/password/reset
4. Sign in again    → POST /auth/login
```

### Step 1 — Request a reset code

```http
POST /api/v1/auth/password/forgot

{ "email": "customer@example.com" }
```

```json
{ "success": true, "data": { "message": "If an account exists, a reset code has been sent" } }
```

> **Always `200`, always the same message** — even for an address with no
> account. Show that message verbatim; do not attempt to detect whether the
> account exists.

### Step 2 — Reset with the code

```http
POST /api/v1/auth/password/reset

{
  "email": "customer@example.com",
  "code": "4821",
  "new_password": "MyNewPass1!"
}
```

```json
{ "success": true, "data": { "message": "Password updated", "sessions_revoked": 3 } }
```

> **This does not sign the user in, and it signs them out everywhere else.**
> All existing sessions are revoked — if an attacker was in the account, they
> are now out. Clear any stored tokens and send the user to the login screen.

| Situation | Response | `error.code` |
|---|---|---|
| Wrong/expired code | `400` | `INVALID_OTP` |
| Too many attempts | `429` | `RATE_LIMITED` |

Note the reset uses the **same 4-digit code mechanism** as signup, not a magic
link.

---

## 5. Session management

### Refreshing an expired access token

Access tokens last 30 minutes. When any call returns `401` with
`error.code == "TOKEN_EXPIRED"`:

```http
POST /api/v1/auth/refresh

{ "refresh_token": "<stored refresh token>" }
```

Returns a **new pair**. Persist both immediately, then retry the original
request once.

```
┌────────────────────────────────────────────────────────┐
│ 401 TOKEN_EXPIRED                                      │
│   → POST /auth/refresh                                 │
│       200 → store new pair, retry original request     │
│       401 → clear tokens, show login screen            │
└────────────────────────────────────────────────────────┘
```

**Implement this with a mutex.** If five requests 401 at once and each fires its
own refresh, four of them present a token that has already been rotated — which
the server treats as theft and revokes every session. One refresh at a time;
queue the rest behind it.

### Logout

```http
POST /api/v1/auth/logout
Authorization: Bearer <access_token>

{ "refresh_token": "<stored refresh token>" }
```

Or to sign out every device (e.g. "log out everywhere" in settings):

```json
{ "all_devices": true }
```

Idempotent — calling it twice is not an error. Clear local tokens regardless of
the response; a network failure should not trap the user in a logged-in state.

---

## 6. Profile & security

### Who am I?

```http
GET /api/v1/users/me
Authorization: Bearer <access_token>
```

Call this on app launch when restoring a saved token — it confirms the token is
still valid and returns the current profile in one round trip.

### Change password (signed in)

```http
POST /api/v1/users/me/password
Authorization: Bearer <access_token>

{ "current_password": "MyFirstPass1!", "new_password": "MyNewPass1!" }
```

```json
{ "success": true,
  "data": { "message": "Password updated", "sessions_revoked": 2,
            "tokens": { "access_token": "...", "refresh_token": "..." } } }
```

> **Returns a fresh token pair — you must store it.** Every session including
> your own is revoked, then a new one is issued to the caller. Other devices are
> signed out; this one stays in. If you ignore `tokens`, your next request
> fails with `401`.

| Situation | Response | `error.code` |
|---|---|---|
| `current_password` missing when one exists | `400` | `VALIDATION_FAILED` |
| `current_password` wrong | `401` | `INVALID_CREDENTIALS` |

### Security state

```http
GET /api/v1/users/me/security
```

```json
{ "success": true,
  "data": { "is_2fa_enabled": false, "is_biometrics_enabled": true,
            "biometric_device_count": 1, "has_password": true,
            "linked_providers": ["google"] } }
```

Drives the toggles on your Security screen. `has_password` is useful for
OTP-only accounts that never set one, and for Google accounts, which start
without a password at all.

`linked_providers` lists federated logins on the account. An account with
`has_password: false` and a single entry here has exactly one way in — do not
offer to unlink it without first walking the user through setting a password,
or you will lock them out of their own account.

---

## 7. Two-factor authentication

### Enabling

```
1. POST /auth/2fa/generate  → { secret, qr_code_url }
2. Show the QR (qr_code_url is an otpauth:// URI) — also show `secret` for manual entry
3. User enters the 6-digit code from their authenticator
4. POST /auth/2fa/enable { code }
```

> 2FA is **not active** until step 4 succeeds. If the user abandons at step 2,
> nothing changes — deliberately, so a failed enrolment cannot lock them out.

### Logging in with 2FA active

```
POST /auth/login → { requires_2fa: true, temp_token, expires_in: 300 }
   ↓ user enters their 6-digit code
POST /auth/login/2fa { temp_token, code } → { tokens, user }
```

`temp_token` is valid for **5 minutes** and works only on `/auth/login/2fa`. It
is not an access token — do not send it as a Bearer header, it will be rejected.

### Disabling

```http
POST /api/v1/auth/2fa/disable
Authorization: Bearer <access_token>

{ "code": "123456" }
```

A current authenticator code is required. Being signed in is not enough —
otherwise a stolen phone could simply switch 2FA off.

---

## 8. Biometric setup

**The crypto contract. Get this exactly right or signatures will not verify.**

### Key generation

| Platform | Algorithm | Notes |
|---|---|---|
| **iOS** | `ES256` | Secure Enclave supports P-256 ECDSA **only** |
| **Android** | `ES256` or `ED25519` | Keystore, `setUserAuthenticationRequired(true)` |

Generate a key pair that requires biometric authentication to use. The private
key never leaves the secure hardware; you only ever send the public key.

### Public key format

**Base64-encoded DER `SubjectPublicKeyInfo`.**

- **Android**: `publicKey.getEncoded()` is already SPKI → base64 it. Done.
- **iOS**: `SecKeyCopyExternalRepresentation` returns a **raw EC point**
  (`04 || X || Y`), *not* SPKI. You must wrap it in the SPKI ASN.1 header before
  sending. This is the single most common integration bug — if the server
  rejects your key, this is why.

### Signing

- Message: the **raw UTF-8 challenge string**, exactly as received. Not a hash
  of it, not the base64 of it.
- `ES256`: SHA-256 digest, **DER-encoded** signature (iOS
  `.ecdsaSignatureMessageX962SHA256` produces this).
- `ED25519`: raw 64-byte signature.
- Send it base64-encoded.

### `device_id`

Any stable string unique per app install. It is the lookup key for the enrolled
credential, so it must survive app restarts but should change on reinstall.

### Re-enrolment

Calling `/auth/biometrics/enable` again for the same `device_id` replaces the
key and clears any lockout. That is the recovery path for a device locked after
5 failed attempts: sign in with a password, then re-enrol.

---

## 9. Error reference

| HTTP | `error.code` | Meaning | What the app should do |
|---|---|---|---|
| 400 | `VALIDATION_FAILED` | Malformed body | Show `details[]` against the fields |
| 400 | `INVALID_OTP` | Wrong or expired code | Let them retry or resend |
| 401 | `UNAUTHORIZED` | Missing/invalid token | Refresh, then log in |
| 401 | `TOKEN_EXPIRED` | Access token aged out | Refresh and retry once |
| 401 | `INVALID_CREDENTIALS` | Wrong password / signature | Generic "incorrect" message |
| 403 | `FORBIDDEN` | Wrong role, or device locked | Explain, don't retry |
| 404 | `NOT_FOUND` | No such resource | — |
| 409 | `CONFLICT` | Phone taken, 2FA already on | Show a specific message |
| 429 | `RATE_LIMITED` | Too many attempts | Back off using `Retry-After` |
| 500 | `INTERNAL_ERROR` | Server fault | Generic error + the `X-Request-ID` |
| 501 | `NOT_IMPLEMENTED` | Endpoint not built yet | Feature-flag it off |

---

## 10. Endpoint summary

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/otp/send` | — | Send a 4-digit code |
| POST | `/auth/otp/verify` | — | Verify → tokens |
| POST | `/auth/login` | — | Email + password |
| POST | `/auth/login/2fa` | temp | Complete 2FA login |
| POST | `/auth/biometrics/challenge` | — | Get a nonce to sign |
| POST | `/auth/biometrics/login` | — | Sign in with a biometric |
| GET | `/auth/google/authorize` | — | Start Sign in with Google (open in a browser tab) |
| GET | `/auth/google/callback` | — | Google returns here; deep-links tokens to the app |
| POST | `/auth/refresh` | — | Rotate tokens |
| POST | `/auth/logout` | ✓ | End session(s) |
| POST | `/auth/password/forgot` | — | Request a reset code |
| POST | `/auth/password/reset` | — | Reset with the code |
| POST | `/auth/biometrics/enable` | ✓ | Enrol a device key |
| DELETE | `/auth/biometrics/disable` | ✓ | Un-enrol (`X-Device-Id` header optional) |
| POST | `/auth/2fa/generate` | ✓ | Get TOTP secret + QR |
| POST | `/auth/2fa/enable` | ✓ | Turn 2FA on |
| POST | `/auth/2fa/disable` | ✓ | Turn 2FA off |
| GET | `/users/me` | ✓ | Current user |
| GET | `/users/me/security` | ✓ | 2FA / biometric state |
| PUT | `/users/me/profile` | ✓ | Name, phone, avatar |
| POST | `/users/me/password` | ✓ | Set or change password |
| POST | `/auth/register/vendor` | — | Register a vendor + restaurant (fast path) |
| POST | `/vendor/applications` | — | Submit a partner application |
| GET | `/vendor/applications/{no}` | — | Application status (`?email=` required) |
| POST | `/vendor/applications/uploads` | — | Upload URL for application documents |
| GET | `/admin/restaurants/pending` | admin | Approval queue (restaurants) |
| POST | `/admin/restaurants/{id}/verify` | admin | Approve or suspend |
| PATCH | `/admin/restaurants/{id}/commission` | admin | Set the commission rate |
| GET | `/admin/vendor-applications` | admin | Application review queue |
| GET | `/admin/vendor-applications/{id}` | admin | Application detail |
| POST | `/admin/vendor-applications/{id}/approve` | admin | Approve an application |
| POST | `/admin/vendor-applications/{id}/reject` | admin | Reject with a reason |

---

## 11. Vendor registration

> **User story**
> *As a restaurant owner, I want to register my restaurant so I can start
> taking orders.*

There are **two ways in**, sharing one account model:

- **The partner application** (§11.1) — what the Partner app's registration
  screens implement: a five-step form, an application number, a human review,
  then credentials. No password is collected up front.
- **The fast path** (§11.2) — one call with a password, tokens back
  immediately. Useful for tooling and for teams not shipping the application
  form UI.

Either way the restaurant starts **unverified and CLOSED**, and customers
cannot see it until an administrator approves it.

### 11.1 The partner application

The flow behind the *Become a partner* screens:

```
1. Owner Information  → POST /auth/otp/send   { "email": ..., "role": "VENDOR" }
                        (the code arrives by email — keep it for step 3)
2. Document step      → POST /vendor/applications/uploads   per file,
                        then PUT the bytes to upload_url
3. Review & Submit    → POST /vendor/applications            ── application_no ──
4. Wait 2–3 days      → GET /vendor/applications/{no}?email=...
5. Approved email     → POST /auth/password/forgot + /auth/password/reset
6. Sign in            → POST /auth/login, then PATCH /vendor/store/status
```

Submission (step 3) — the nested blocks mirror the form's steps:

```http
POST /api/v1/vendor/applications

{
  "otp_code": "3314",
  "business": {
    "name": "Kolpatha Restaurant",
    "business_type": "RESTAURANT",        // RESTAURANT | GROCERY | PHARMACY
    "business_category": "Street Food",
    "branch_count": 1,
    "cuisine_types": ["Fast Food"]
  },
  "location": {
    "address_line": "Road 12, House 42, Nikunja 2, Dhaka",
    "area": "Nikunja 2",
    "latitude": 23.8481,
    "longitude": 90.4148
  },
  "owner": {
    "full_name": "Hamid Islam",
    "email": "contact@hamidislam.com",
    "phone": "+8801712447567",
    "national_id": "454654644564"
  },
  "documents": {
    "shop_image":    "https://…/applications/…/a1.jpg",
    "owner_nid":     "https://…/applications/…/b2.jpg",
    "menu_list":     "https://…/applications/…/c3.jpg",
    "trade_license": "https://…/applications/…/d4.pdf"   // optional
  },
  "payout": {
    "method": "BKASH",                    // BANK | BKASH | NAGAD | ROCKET
    "account_name": "Hamid Islam",
    "account_number": "01712447567",
    "bank_name": null,                    // BANK only
    "branch_name": null
  },
  "agreed_to_terms": true
}
```

`201 Created`:

```json
{
  "success": true,
  "data": {
    "application_no": "PTN-88291",
    "status": "PENDING",
    "restaurant_id": "…",
    "submitted_at": "2026-08-19T10:15:00Z",
    "message": "Application submitted! We'll review it and get back to you within 2–3 business days by email."
  }
}
```

Show `application_no` on the success screen and store it — the status
endpoint needs it, and support will ask for it.

Things to know:

- **No tokens are returned.** The account exists but has no password, so it
  cannot be signed into. Approval emails the owner instructions to set one
  via the §4 forgot-password flow; nothing stops them doing that earlier.
- **Documents upload before submission.** `POST /vendor/applications/uploads`
  is the unauthenticated twin of `POST /uploads/presigned-url`: same
  presigned-PUT mechanics, PDF allowed on top of the image types (trade
  licences are scans), keys under `applications/…`. Rate limited per IP.
- **Status checks need the reference AND the email.** A wrong email is the
  same `404` as a wrong reference, so the reference space cannot be walked.
  `review_note` appears only on a `REJECTED` application — it carries the
  reason, which is also emailed.
- **Decisions are final.** A rejected applicant who fixes the problem applies
  again with a different email today, or replies to the rejection email —
  see Known limitations.

| Situation | Response | `error.code` |
|---|---|---|
| Wrong or expired `otp_code` | `400` | `INVALID_OTP` |
| `agreed_to_terms` not `true` (OTP is **not** burned) | `400` | `VALIDATION_FAILED` |
| Email already a customer account | `409` | `CONFLICT` |
| Email already has an application (the message carries its `application_no`) | `409` | `CONFLICT` |
| Phone already on another account | `409` | `CONFLICT` |
| More than 5 submissions/hour from one IP | `429` | `RATE_LIMITED` |

**For the admin console:** `GET /admin/vendor-applications` is the review
queue (oldest first, `?status=PENDING` by default), the `{id}` detail carries
everything above plus the document URLs, and
`POST /admin/vendor-applications/{id}/approve` / `…/reject` decide it. Approval
verifies the restaurant and emails the owner their sign-in steps; rejection
emails the `note` as the reason, so write it for the applicant.

### 11.1b Pricing a restaurant — commission

```http
PATCH /api/v1/admin/restaurants/{restaurant_id}/commission
Authorization: Bearer <ADMIN_ACCESS_TOKEN>

{ "commission_rate": 0.18, "note": "renegotiated for volume" }
```

`commission_rate` is a **fraction, not a percentage**: `0.18` is 18%, four
decimal places, `0` to `1`. Sending `18` is a `400` rather than a 1800% cut.
`note` is optional and goes to the server log.

```json
{
  "success": true,
  "data": {
    "message": "Commission set to 18.00%",
    "restaurant_id": "…",
    "name": "Karim's Kitchen",
    "commission_rate": 0.18
  }
}
```

Three things follow from where this number lives:

- **Nothing else writes it.** Approval does not take a rate, and the vendor is
  refused the field on `PATCH /vendor/profile` — a vendor who could set their
  own commission could set it to zero.
- **New restaurants are not created at 0%.** Both signup paths start a
  restaurant on the platform default (`DEFAULT_COMMISSION_BASIS_POINTS`,
  1500 == 15%), so a vendor approved before anyone gets to pricing still bills
  correctly.
- **It only applies forward.** Each order snapshots the commission it was
  charged, so repricing changes the next order, never the last one. That also
  means a restaurant left at the wrong rate cannot be corrected retroactively
  — the orders it already took keep the old number.

The vendor reads their own rate back on `GET /vendor/profile`
(`commission_rate`), and what it cost them per order on
`GET /vendor/orders/{id}` (`commission_amount`, `vendor_payout`).

### 11.2 The fast path

**Note `role: "VENDOR"` on step 1** — without it the account is created as a
customer, and roles are fixed at creation.

```
1. Enter email       → POST /auth/otp/send   { "email": ..., "role": "VENDOR" }
2. Code + password + restaurant details
                     → POST /auth/register/vendor      ── tokens ──
3. Build the menu    (available immediately)
4. Wait for approval (an administrator verifies the restaurant)
5. Open the store    → PATCH /vendor/store/status
```

```http
POST /api/v1/auth/register/vendor

{
  "email": "owner@restaurant.com",
  "code": "4821",
  "password": "VendorPass1!",
  "full_name": "Karim Ahmed",
  "restaurant": {
    "name": "Karim's Kitchen",
    "description": "Authentic Bengali cuisine",
    "phone": "+8801712345678",
    "address_line": "House 12, Road 8, Dhanmondi, Dhaka",
    "latitude": 23.7936,
    "longitude": 90.4064,
    "cuisine_types": ["Bengali", "Biryani"]
  }
}
```

`201 Created`:

```json
{
  "success": true,
  "data": {
    "tokens": { "access_token": "...", "refresh_token": "..." },
    "user": { "role": "VENDOR", "email": "owner@restaurant.com" },
    "restaurant": { "id": "...", "slug": "karims-kitchen",
                    "is_verified": false, "status": "CLOSED" },
    "next_step": "Your restaurant is awaiting approval..."
  }
}
```

> **`is_verified: false` is expected.** The vendor is signed in and can build
> their menu immediately, but customers cannot see the restaurant until an
> administrator approves it. Show the `next_step` message and a pending badge.

| Situation | Response | `error.code` |
|---|---|---|
| Email already a **customer** account | `409` | `CONFLICT` |
| Account already has a restaurant | `409` | `CONFLICT` |
| `role` of `ADMIN` or `RIDER` on step 1 | `400` | `VALIDATION_FAILED` |

Rider and admin accounts are **not** self-service — they are created by an
administrator.

---

## 12. Roles

The system has four roles. **A role is fixed when the account is created** and
cannot be changed afterwards — the database enforces this with composite
foreign keys, so an account that owns a restaurant cannot quietly become a
customer.

| Role | How an account is created | Status |
|---|---|---|
| `CUSTOMER` | Self-service — `/auth/otp/send` (default) | ✅ available |
| `VENDOR` | Self-service — `role: "VENDOR"`, then admin approval | ✅ available |
| `ADMIN` | Server shell only (`scripts/create_admin.py`) | ✅ available |
| `RIDER` | **Not yet implemented** | ❌ blocked |

Practical consequence for your UI: **one email address is one role.** Someone
who signed up as a customer and later wants to run a restaurant must use a
different address. Say so plainly at the point of failure — the `409` message
already explains it, so surface `error.message` rather than a generic string.

The access token carries the role, and `GET /users/me` returns it. Use it to
decide which app shell to render if you ship a single binary for customers and
vendors.

---

## Known limitations

Be aware of these when planning screens:

1. **Email only.** `/auth/otp/send` will accept a phone number and return
   `200`, but **no SMS is sent** — no provider is connected yet. Registration
   must use an email address for now.

   The field is named **`email`**. For backward compatibility the server also
   accepts `identifier` and `phone` as aliases for the same value, so no client
   breaks when SMS support lands and `phone` becomes the documented name for
   that path. **Use `email` today.**
2. **Phone numbers are never verified.** `is_phone_verified` is always `false`.
   There is no verify-my-phone flow yet.
3. **No email change flow.** The signup email is permanent.
4. **No account deletion.** Apple and Google both **require** an in-app
   deletion path for any app that offers account creation — submission gets
   rejected without it. Flag this early if you have a store date.
5. **No Sign in with Apple.** Now that [Google sign-in](#3c-sign-in-with-google)
   exists, this stops being optional: App Store review requires Sign in with
   Apple from any iOS app offering a third-party login. The backend is shaped
   for it — `auth_identities` already accepts `apple` as a provider — but the
   endpoint is not built. Neither this nor the point above blocks development;
   both block an iOS submission.
6. **No rider accounts.** There is no way to create a `RIDER`, so the rider app
   has no signup. Delivery assignment and live tracking depend on it — and so
   does the vendor handoff, which cannot complete without an assigned rider.
7. **No push notification registration.** Spec §9 lists `POST /users/me/devices`
   for FCM tokens; it is not built. No order-status pushes, and no vendor alert
   when the tablet app is backgrounded.
8. **No 2FA recovery codes.** A user who loses their authenticator is
   permanently locked out — recovery currently needs manual database access.
   Consider hiding the 2FA toggle until this exists.
9. **Customer commerce still returns 501.** Discovery, cart, checkout and order
   placement are routed and documented but not implemented, so nothing can yet
   place an order for a vendor to receive. Auth and vendor operations
   (see [VENDOR-API.md](VENDOR-API.md)) are implemented.

---

## Questions

Anything ambiguous, or a response that doesn't match this document: send the
`X-Request-ID` from the response and the exact request body.
