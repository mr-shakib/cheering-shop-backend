# Image uploads with Cloudflare R2 — complete setup

Wiring `POST /uploads/presigned-url` and `POST /vendor/applications/uploads` to
actually issue working URLs, using [Cloudflare R2](https://developers.cloudflare.com/r2/).

Until this is done both endpoints return `503 STORAGE_NOT_CONFIGURED`, and the
error `details` name exactly which variables are missing. Everything else in the
API works without it.

---

## Read this first — the constraint that shapes everything

R2 speaks the S3 API, so the presigned URLs the backend signs are ordinary
SigV4. Three things are **not** like S3, and the third one is the one that
catches people:

1. **There is no region.** The signature scope is always `auto`. A real region
   name makes R2 reject the signature. There is deliberately no region setting.
2. **Addressing is path-style** — `<account>.r2.cloudflarestorage.com/<bucket>/<key>`
   — so the bucket lives in the path, not the hostname.
3. **The S3 endpoint is not publicly readable.** An R2 bucket is private, and
   the endpoint you upload to always demands authentication. Reads come from a
   *separate* domain that you bind to the bucket.

Point 3 is why `R2_PUBLIC_BASE_URL` exists and is **required**, not cosmetic. On
S3 the upload host and the read host were the same, so the backend could derive
one from the other. On R2 it cannot. Skip it and you get the worst kind of
failure: uploads succeed, and every image 401s for every user forever.

| | `upload_url` | `public_url` |
|---|---|---|
| Host | `<account>.r2.cloudflarestorage.com` | your r2.dev or CDN domain |
| Purpose | takes your `PUT` | serves reads |
| Lifetime | 15 minutes | permanent |
| Auth | signed query string | none |

The API returns both. Clients `PUT` to the first and send the second back as
`logo_url` / `cover_image_url` / `image_url`.

---

## Step 1 — Create the bucket

1. Cloudflare dashboard → **R2 Object Storage** → **Create bucket**
2. Name it (`cr-shop-media` is what the rest of this doc assumes)
3. Location: **Automatic**, unless you have a data-residency requirement — a
   jurisdiction-locked bucket changes the endpoint, see Step 5

Note your **Account ID**, shown in the R2 sidebar. It is the `R2_ACCOUNT_ID`.

## Step 2 — Create an API token scoped to that bucket

1. R2 → **Manage API tokens** → **Create API token**
2. Permission: **Object Read & Write**
3. Scope it to the single bucket, not "all buckets". The backend never needs to
   create, list or delete buckets, and a token that can do so is a token that
   can delete every image you own.
4. Copy the **Access Key ID** and **Secret Access Key** — the secret is shown
   once

These are `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY`.

## Step 3 — Give the bucket a public domain

This is the step that is easy to skip and expensive to skip. Pick one:

**Option A — managed `r2.dev` subdomain (fastest, fine for development)**

Bucket → **Settings** → **Public Development URL** → **Enable**. You get
`https://pub-<hash>.r2.dev`. Cloudflare rate-limits it and explicitly does not
support it for production traffic.

**Option B — custom domain (what production should use)**

Bucket → **Settings** → **Custom Domains** → **Connect Domain**, e.g.
`cdn.cheeringshop.online`. The domain must be on Cloudflare DNS; the record is
created for you. This gets you caching, no rate limit, and a URL that does not
change if you ever move providers.

Either way, the resulting origin — **no trailing slash, no bucket name** — is
`R2_PUBLIC_BASE_URL`. The backend appends the object key to it.

## Step 4 — Set the variables

```bash
R2_ACCOUNT_ID=your_account_id
R2_BUCKET=cr-shop-media
R2_ACCESS_KEY_ID=from_step_2
R2_SECRET_ACCESS_KEY=from_step_2
R2_PUBLIC_BASE_URL=https://cdn.cheeringshop.online
```

In Dokploy these go in the service's **Environment** tab; the compose file
already passes all five through.

## Step 5 — `R2_ENDPOINT_URL` (usually leave it unset)

The endpoint is derived from `R2_ACCOUNT_ID`. Set it explicitly only for:

- a **jurisdiction-locked** bucket — `https://<account>.eu.r2.cloudflarestorage.com`
- pointing a local stack at **MinIO** or another S3-compatible server

## Step 6 — Verify

```bash
curl -s https://api.cheeringshop.online/ready | jq .data.storage
```

`{"status": "ok", "provider": "cloudflare-r2", "bucket": "cr-shop-media"}` means
the variables are all present. `status: "error"` lists the missing ones. This
check is reported but does **not** gate readiness — an unprovisioned bucket must
not pull the node out of the load balancer when browsing and ordering work fine.

Then a real round trip:

```bash
# 1. ask for a URL (needs any logged-in user's token)
curl -s -X POST https://api.cheeringshop.online/api/v1/uploads/presigned-url \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"file_type":"image/jpeg","file_name":"test.jpg"}' | jq .data

# 2. upload with the EXACT header returned
curl -X PUT "$UPLOAD_URL" -H 'Content-Type: image/jpeg' --data-binary @test.jpg

# 3. the public URL must return 200 and the image
curl -I "$PUBLIC_URL"
```

Step 3 returning `401` means `R2_PUBLIC_BASE_URL` is pointing at the S3 endpoint
instead of a bound public domain. Step 2 returning `403 SignatureDoesNotMatch`
almost always means the `Content-Type` header did not match the one requested —
it is signed into the URL on purpose, so that a client cannot promise us a JPEG
and upload an HTML page onto our own domain.

---

## What is deliberately not here

- **No bucket lifecycle rules.** Nothing expires uploaded images yet. Worth
  adding once storage growth is measurable.
- **Application documents are public too.** Trade licences and NID scans go to
  the same bucket under `applications/…` and are readable by anyone with the
  URL — the keys are unguessable (UUID), but that is obscurity, not access
  control. If these need to be genuinely private, they want their own bucket
  with no public domain plus presigned **GET** URLs for admin review.
- **No image resizing.** Cloudflare Images or R2 + Image Resizing would do it;
  today the client uploads whatever it has and the app scales it for display.
