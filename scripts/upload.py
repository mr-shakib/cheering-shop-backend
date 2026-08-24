#!/usr/bin/env python
"""Upload a real file through the CR Shop upload API, end to end.

    ./scripts/upload.py photo.jpg                       # anonymous, local
    ./scripts/upload.py photo.jpg --prod                 # anonymous, production
    ./scripts/upload.py logo.png --prod --token "$TOKEN" # as a signed-in user

Complements `smoke.py`: this drives the one flow that leaves the API entirely
mid-way. The backend never sees the bytes (spec §2) — it signs a URL, the client
PUTs straight to Cloudflare R2, and the object is then served from a different
host again. Three parties, two of them not us, so "the endpoint returned 200" is
not evidence the feature works. This checks all three legs and the bytes.

WITHOUT `--token` it uses `POST /vendor/applications/uploads`, which is
unauthenticated by design (applicants have no account yet) and rate limited to
30/hour per IP. That is the quickest way to prove storage is wired up.

WITH `--token` it uses `POST /uploads/presigned-url`, the endpoint vendors
actually call for logos and menu photos. Get a token with:

    curl -s -X POST https://api.cheeringshop.online/api/v1/auth/login \
      -H 'Content-Type: application/json' \
      -d '{"email":"you@example.com","password":"..."}' \
      | jq -r .data.tokens.access_token

Exit code 0 = the file is uploaded and publicly readable.
"""

from __future__ import annotations

import argparse
import mimetypes
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

# Only what the server will sign. Listing them here turns "403 from R2 twenty
# seconds later" into an immediate, readable error.
ALLOWED = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


def die(msg: str, detail: str = "") -> None:
    print(f"  {RED}✗{RESET} {msg}")
    if detail:
        print(f"    {DIM}{detail[:500]}{RESET}")
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", type=Path, help="the image or PDF to upload")
    ap.add_argument("--base", default="http://localhost:8000", help="API base URL")
    ap.add_argument("--prod", action="store_true", help="shorthand for the live API")
    ap.add_argument("--token", default="", help="access token; uses /uploads/presigned-url")
    ap.add_argument("--keep", action="store_true", help="do not warn about leaving the object")
    args = ap.parse_args()

    base = ("https://api.cheeringshop.online" if args.prod else args.base).rstrip("/")
    api = f"{base}/api/v1"

    if not args.file.is_file():
        die(f"no such file: {args.file}")
    data = args.file.read_bytes()
    if not data:
        die(f"{args.file} is empty")

    # The server signs Content-Type into the URL, so guessing it wrong here
    # fails at R2 with SignatureDoesNotMatch rather than anywhere useful.
    ctype = mimetypes.guess_type(args.file.name)[0] or ""
    if ctype == "image/jpg":  # mimetypes is inconsistent across platforms
        ctype = "image/jpeg"
    if ctype not in ALLOWED:
        die(
            f"{args.file.name} looks like {ctype or 'an unknown type'}",
            f"The API signs only: {', '.join(sorted(ALLOWED))}",
        )

    print(f"\n{DIM}{args.file}  {len(data):,} bytes  {ctype}{RESET}")
    print(f"{DIM}{base}{RESET}\n")

    if args.token:
        url, headers, who = f"{api}/uploads/presigned-url", {
            "Authorization": f"Bearer {args.token}"
        }, "authenticated"
    else:
        url, headers, who = f"{api}/vendor/applications/uploads", {}, "anonymous"

    with httpx.Client(timeout=60.0, follow_redirects=True) as c:
        # 1. Ask our API to sign a URL. It never sees the bytes.
        r = c.post(url, json={"file_type": ctype, "file_name": args.file.name}, headers=headers)
        if r.status_code == 503:
            die("storage is not configured on this server", r.text)
        if r.status_code == 401:
            die("token rejected — expired, or not a token for this environment", r.text)
        if r.status_code == 429:
            die("rate limited (30 uploads/hour per IP on the anonymous endpoint)", r.text)
        if r.status_code != 200:
            die(f"presign failed with {r.status_code}", r.text)
        d = r.json()["data"]
        key, upload_url, public_url = d["key"], d["upload_url"], d["public_url"]
        print(f"  {GREEN}✓{RESET} signed a URL ({who})")
        print(f"    {DIM}key    {key}{RESET}")
        print(f"    {DIM}upload {urlparse(upload_url).netloc}{RESET}")

        # 2. Straight to R2. Headers must be exactly what was signed.
        r = c.put(upload_url, content=data, headers=d["headers"])
        if r.status_code not in (200, 204):
            hint = ""
            if "SignatureDoesNotMatch" in r.text:
                hint = "Content-Type did not match the signature, or the URL expired (15 min)."
            die(f"upload rejected by R2 with {r.status_code}", hint or r.text)
        print(f"  {GREEN}✓{RESET} uploaded {len(data):,} bytes to R2")

        # 3. The leg most likely to be misconfigured: public delivery is a
        #    different host from the upload endpoint, and a bucket with no
        #    public domain bound returns 401 here while everything above passes.
        r = c.get(public_url)
        if r.status_code == 401:
            die(
                "uploaded, but the object is not publicly readable",
                "R2_PUBLIC_BASE_URL is pointing at the S3 endpoint instead of the "
                "r2.dev subdomain or a custom domain bound to the bucket.",
            )
        if r.status_code != 200:
            die(f"public URL returned {r.status_code}", r.text)
        if r.content != data:
            die(f"served {len(r.content):,} bytes, uploaded {len(data):,} — content differs")
        print(f"  {GREEN}✓{RESET} publicly readable, bytes identical")
        print(f"    {DIM}served as {r.headers.get('content-type')}{RESET}")

    print(f"\n{GREEN}public_url{RESET}  {public_url}")
    print(f"{DIM}Send that back as logo_url / cover_image_url / image_url.{RESET}")
    if not args.keep:
        print(
            f"{YELLOW}Note{RESET} this object now exists in the bucket; "
            "delete it if it was a test."
        )
    print()


if __name__ == "__main__":
    main()
