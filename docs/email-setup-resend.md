# Email OTP delivery with Resend — complete setup

Wiring `POST /auth/otp/send` to actually deliver a code, using
[Resend](https://resend.com).

> **Note on naming:** this is **Resend** (resend.com, an email API), not
> **Render** (render.com, a hosting platform). Easy to mix up.

---

## Read this first — the constraint that shapes everything

Resend's own documentation is unambiguous:

> "You must add and verify at least one domain to send emails with Resend."

There is one escape hatch, and it is narrow. The test sender
`onboarding@resend.dev` **can only send to the email address registered on your
Resend account.** Send to any other recipient and the API returns a 403.

**You do not currently own a domain.** `srv1128440.hstgr.cloud` belongs to
Hostinger — you cannot add DNS records to it, so it cannot be verified.

That splits the work into two phases:

| | Phase 1 — today | Phase 2 — before real users |
|---|---|---|
| Sender | `onboarding@resend.dev` | `noreply@yourdomain.com` |
| Can email | **only your own address** | anyone |
| Costs | £0 | a domain, ~$10–15/year |
| Good for | building and testing the whole flow | actual customers |
| Setup time | 15 min | +30 min, plus DNS propagation |

Phase 1 is genuinely useful: it unblocks end-to-end development, and every line
of code written for it works unchanged in Phase 2. Only the `from` address
changes.

**Phase 2 is not optional before launch.** Without it, no customer can ever
receive a signup code.

### Free tier (verified 2026-08)

| | |
|---|---|
| Emails per month | 3,000 |
| Emails per day | **100** |
| Domains | 1 |
| Next tier | Pro, $20/mo, 50,000 emails |

100/day is fine for development and a soft launch. Watch it: one OTP per signup,
one per password reset, and a resend costs another. A busy launch day can pass
100 quickly.

---

# PHASE 1 — Working email today (15 minutes)

## Step 1 — Create the Resend account

1. Browser → **<https://resend.com/signup>**
2. Sign up with GitHub, or with email + password.
3. **Remember exactly which email address you used.** In Phase 1 that is the
   *only* address you can send to. Write it down.
4. Verify the address from the confirmation email Resend sends you.

## Step 2 — Create an API key

1. In the Resend dashboard, left sidebar → **API Keys**
2. Click **Create API Key** (top right)
3. Fill in:
   - **Name**: `cr-shop-production`
   - **Permission**: **Sending access** (not Full access — this key only needs
     to send. If it leaks, the blast radius is limited to sending mail, not
     reading or deleting your account data.)
   - **Domain**: leave as *All domains*
4. Click **Add**
5. **Copy the key immediately** — it starts `re_` and is shown exactly once.
   Paste it into your password manager now.

## Step 3 — Send a test from the dashboard

Prove the account works before touching any code.

1. Left sidebar → **Emails** → **Send test email** (or use the API playground)
2. **From**: `onboarding@resend.dev`
3. **To**: the email address you signed up with
4. Send, then check your inbox — including spam.

If it arrives, Phase 1 is viable. If not, stop here and fix the account before
writing code.

## Step 4 — Configure the backend

Two new settings. Locally, add to `.env`:

```env
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxx
EMAIL_FROM=onboarding@resend.dev
EMAIL_FROM_NAME=CR Shop
```

In production — Dokploy → your service → **Environment** → add the same three
lines → **Save** → **Deploy**.

> **A variable in Dokploy's Environment tab does not automatically reach the
> container.** Compose only passes what the service's `environment:` block
> lists; the tab merely makes it available for `${VAR}` interpolation. These
> three are already listed in `deploy/docker-compose.dokploy.yml`, but if you
> add a *new* setting later, add it there too — otherwise the app silently
> falls back to its default and your change looks ignored.

> Never commit the key. `.env` is gitignored; the Dokploy value lives only in
> Dokploy.

## Step 5 — Test the real flow

```bash
# locally
make dev
curl -X POST http://localhost:8000/api/v1/auth/otp/send \
  -H 'Content-Type: application/json' \
  -d '{"identifier":"THE_EMAIL_YOU_SIGNED_UP_WITH@example.com"}'
```

An email should arrive within a few seconds. Locally the response also contains
`debug_code`, so you can compare the two and confirm they match.

Then complete the signup:

```bash
curl -X POST http://localhost:8000/api/v1/auth/otp/verify \
  -H 'Content-Type: application/json' \
  -d '{"identifier":"THE_EMAIL@example.com","code":"THE_CODE_FROM_THE_EMAIL"}'
```

You get back an access/refresh pair. **That is the first time the full signup
journey has worked end to end.**

### Expected failure in Phase 1

Sending to any other address returns:

```json
{"statusCode":403,"message":"You can only send testing emails to your own email address"}
```

That is Resend working as designed, not a bug in your code. It is also exactly
why Phase 2 exists.

---

# PHASE 2 — Emailing real customers (30 min + DNS wait)

## Step 6 — Buy a domain

Any registrar. Namecheap, Porkbun, Cloudflare Registrar (sells at cost) — around
$10–15/year for a `.com`. Hostinger sells them too, which keeps everything in
one dashboard.

Pick the domain you actually want for the product; you will also use it for the
API and the customer-facing site later.

**Tip:** point the domain's nameservers at **Cloudflare** (free). Their DNS
editor is faster and clearer than most registrar panels, and you will be adding
several records.

## Step 7 — Add the domain to Resend

1. Resend dashboard → left sidebar → **Domains** → **Add Domain**
2. Enter your domain, e.g. `crshop.com`
3. Choose the region closest to your users
4. Click **Add**

Resend now shows a table of DNS records to create. **Leave this page open.**

## Step 8 — Add the DNS records

In your DNS provider (Cloudflare, or your registrar's DNS panel), create exactly
what Resend lists. There are three:

| Type | Name / Host | Purpose |
|---|---|---|
| **MX** | `send` | Routes bounce/complaint feedback back to Resend. Priority `10`. |
| **TXT** | `send` | **SPF** — authorises Resend's servers to send as your domain |
| **TXT** | `resend._domainkey` | **DKIM** — cryptographically signs your mail |

Copy each **Value** verbatim from the Resend page.

### The mistake almost everyone makes

Enter the name as **`send`**, not `send.crshop.com`.

Most DNS panels append your domain automatically. Typing the full name creates
`send.crshop.com.crshop.com`, which silently never verifies and gives you no
error to chase.

**On Cloudflare specifically:** set the proxy status to **DNS only** (grey
cloud, not orange) for these records. Proxying breaks mail records.

## Step 9 — Verify

1. Back on the Resend Domains page, click **Verify DNS Records**
2. Status goes `Pending` → `Verified`

Usually a few minutes. Resend's docs allow **up to 72 hours**. If it is still
pending after an hour, check your records from outside your own network:

```bash
dig +short TXT resend._domainkey.crshop.com @1.1.1.1
dig +short TXT send.crshop.com @1.1.1.1
dig +short MX  send.crshop.com @1.1.1.1
```

Empty output means the record is missing or misnamed — revisit Step 8.

## Step 10 — Switch the sender

Change one environment variable, in Dokploy and in your local `.env`:

```env
EMAIL_FROM=noreply@crshop.com
```

Redeploy. You can now send to any address.

> `noreply@` does not need to be a real mailbox — SPF and DKIM authorise the
> *domain*, not an individual account. That said, a monitored `support@` in the
> email body is worth having; a no-reply-only sender annoys customers and hurts
> deliverability.

## Step 11 — Add DMARC (recommended, not required)

Once verified and sending, add one more TXT record:

| Type | Name | Value |
|---|---|---|
| TXT | `_dmarc` | `v=DMARC1; p=none; rua=mailto:you@crshop.com` |

`p=none` means "monitor, don't reject" — it is safe to add immediately and tells
you who is sending as your domain. Tighten to `p=quarantine` after a few weeks
of clean reports.

Gmail and Yahoo increasingly deprioritise mail from domains with no DMARC
record. For OTP emails, which are worthless if they land in spam, this matters.

---

## Step 12 — Deliverability checks before launch

- [ ] Send yourself an OTP; confirm it lands in **inbox**, not spam
- [ ] Test Gmail, Outlook and any local provider your customers use
- [ ] Check headers show `SPF: pass` and `DKIM: pass`
      (Gmail → open message → ⋮ → *Show original*)
- [ ] Watch the Resend dashboard for bounces and complaints in week one
- [ ] Confirm the 100/day free-tier ceiling is above your expected signup rate

---

## Operational notes

**Delivery is sent inline, not queued.** I originally planned to push it onto
`arq`, and changed course while implementing: an OTP is worthless five minutes
after it is requested and the user is watching a spinner, so a queue adds a
failure mode with no upside — a stopped worker would mean every signup silently
receives nothing while the API returns 200. A 10-second timeout bounds the
latency instead. Bulk mail (receipts, summaries) should still go through arq
when it arrives.

**Failures are logged, never surfaced.** If Resend rejects a send, the API still
returns `200 OK` and the stored code stays valid, so a resend recovers. Telling
a caller "that address doesn't exist" would turn the endpoint into an
account-enumeration oracle — exactly the leak `/auth/password/forgot` is written
to avoid. There is a test (`test_otp_send_survives_a_provider_outage`) that
fails the build if this regresses.

**Rate limits still apply.** The 60-second resend cooldown protects your Resend
quota as well as your users' inboxes.

**SMS is a separate job.** Bangladeshi customers will overwhelmingly sign up
with a phone number, not an email. This guide covers email only; SMS needs a
provider (a local aggregator is usually far cheaper than Twilio for BD numbers,
and BD generally requires a registered sender ID — confirm current rules with
whichever provider you choose). The service interface is written so adding an
SMS channel is one more implementation behind the same call.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `403 You can only send testing emails to your own email address` | Phase 1 restriction | Expected. Complete Phase 2 |
| Domain stuck on `Pending` | Record name includes the domain twice | Step 8 — use `send`, not `send.crshop.com` |
| Verified, but mail goes to spam | No DMARC, or a cold domain | Add DMARC (Step 11); volume builds reputation over days |
| `401 Unauthorized` from Resend | Wrong or revoked API key | Regenerate in **API Keys**, update the env var, redeploy |
| Nothing sends, no error | `RESEND_API_KEY` not set in Dokploy | Check **Environment**, then redeploy — env changes need a restart |
| Works locally, not in production | Env var added but not deployed | Dokploy → **Deploy** |
| Hit 100 emails in a day | Free-tier daily cap | Wait for reset, or upgrade to Pro |

---

## Sources

- [Resend — Domains introduction](https://resend.com/docs/dashboard/domains/introduction)
- [Resend — 403 error using resend.dev domain](https://resend.com/docs/knowledge-base/403-error-resend-dev-domain)
- [Resend — DNS records for verification](https://resend.com/docs/dashboard/domains/cloudflare)
- [Resend — Pricing](https://resend.com/pricing)
