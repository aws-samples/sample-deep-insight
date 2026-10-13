# Deep Insight Ops — Admin Authentication

> Cognito JWT authentication for the admin dashboard.

**Last Updated**: 2026-03

---

## Key Terms

| Term | What It Is |
|------|-----------|
| **JWT** (JSON Web Token) | A compact, URL-safe token format used to pass verified identity information between parties. Consists of three Base64-encoded parts separated by dots: `header.payload.signature`. The server can verify the token without storing session state. |
| **JWKS** (JSON Web Key Set) | A public endpoint that publishes the RSA public keys used to verify JWT signatures. Our server fetches these keys from Cognito and caches them locally. No shared secret needed — only Cognito has the private key to sign tokens. |
| **RS256** | The signing algorithm (RSA + SHA-256). Asymmetric — Cognito signs with its private key, our server verifies with the public key from JWKS. More secure than symmetric algorithms (like HS256) because the verification key can be public. |
| **kid** (Key ID) | An identifier in the JWT header that tells the server which public key (from JWKS) to use for verification. Cognito rotates keys periodically; the kid ensures the correct key is used. |
| **IdToken** | One of three tokens Cognito returns on login (IdToken, AccessToken, RefreshToken). The IdToken contains user identity claims (email, username) and is what we store in the cookie. |
| **Cognito User Pool** | An AWS service that provides user directory, authentication, and token management. Think of it as a managed user database with built-in password policies, MFA support, and JWT issuance. |
| **HTTP-only Cookie** | A cookie flag that prevents JavaScript from reading the cookie value via `document.cookie`. The browser still sends it automatically on every request. This protects the token from XSS (cross-site scripting) attacks. |
| **SameSite=Lax** | A cookie attribute that prevents the browser from sending the cookie on cross-origin POST requests. Protects against CSRF (cross-site request forgery) while still allowing normal navigation links. |

---

## Architecture

```
ops/auth.py          — JWT validation (JWKS public key verification)
ops/admin_router.py  — Login/logout routes + protected API routes
```

- **Cognito User Pool**: `deep-insight-ops-admins` (no self-signup, admin-created users only)
- **App Client**: `deep-insight-ops-web` (no client secret, USER_PASSWORD_AUTH flow)
- **Token storage**: HTTP-only cookie (not localStorage — XSS-safe)
- **Token type**: Cognito IdToken (JWT, RS256 signed)

---

## Auth Flow: First Login (NEW_PASSWORD_REQUIRED)

When the infra team creates an admin user, Cognito sends a temporary password via email.

```
Admin receives Cognito email with temporary password
  │
  ▼
GET /admin/login
  │  Browser renders login.html
  ▼
POST /admin/login  { username, password (temporary) }
  │  admin_router.py → Cognito InitiateAuth (USER_PASSWORD_AUTH)
  │  Cognito returns ChallengeName: "NEW_PASSWORD_REQUIRED" + Session token
  ▼
Response: { challenge: "NEW_PASSWORD_REQUIRED", session: "...", username: "..." }
  │  Browser shows change-password form
  ▼
POST /admin/change-password  { username, session, new_password }
  │  admin_router.py → Cognito RespondToAuthChallenge
  │  Cognito validates new password against policy (min 12 chars, mixed case, numbers, symbols)
  │  Cognito returns AuthenticationResult with IdToken (JWT)
  ▼
Response: Set-Cookie: token=<JWT>; HttpOnly; SameSite=Lax; Path=/admin
  │  Browser redirects to /admin/dashboard
  ▼
GET /admin/dashboard
  │  auth.py require_admin() reads cookie → validates JWT → serves page
  ▼
Dashboard rendered
```

---

## Auth Flow: Normal Login

```
GET /admin/login
  │  Browser renders login.html
  ▼
POST /admin/login  { username, password }
  │  admin_router.py → Cognito InitiateAuth (USER_PASSWORD_AUTH)
  │  Cognito returns AuthenticationResult with IdToken (JWT)
  ▼
Response: Set-Cookie: token=<JWT>; HttpOnly; SameSite=Lax; Path=/admin
  │  Browser redirects to /admin/dashboard
  ▼
GET /admin/dashboard  (cookie sent automatically by browser)
  │  auth.py require_admin() reads cookie → validates JWT → serves page
  ▼
Dashboard rendered
```

---

## JWT Validation Detail (auth.py)

Every request to a protected route goes through `require_admin()`:

```
Request arrives with cookie "token"
  │
  ▼
Extract JWT header → get "kid" (key ID)
  │
  ▼
Look up RSA public key in JWKS cache
  │  Cache: in-memory dict, 1 hour TTL
  │  Cache miss? → Fetch from Cognito JWKS endpoint:
  │    https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/jwks.json
  │  Key ID not found? → Force refresh cache, retry once (handles key rotation)
  ▼
jwt.decode() verifies:
  │  ✓ Signature (RS256 — asymmetric, only Cognito can sign)
  │  ✓ Issuer (must match our Cognito User Pool)
  │  ✓ Audience (must match our App Client ID)
  │  ✓ Expiry (token valid for 1 hour)
  ▼
Valid → return claims dict (contains username, email, token expiry)
Invalid/Expired → HTTP 401
```

### JWKS Caching Strategy

```
First request          → fetch JWKS, cache keys, set timestamp
Subsequent requests    → use cached keys (no network call)
After 1 hour           → re-fetch JWKS on next request
Unknown kid in token   → force re-fetch once, retry lookup
Fetch failure          → use stale cache if available, else 503
```

This ensures:
- **No per-request network overhead** (keys cached for 1 hour)
- **Graceful key rotation** (unknown kid triggers refresh)
- **Resilience** (stale cache used if Cognito endpoint is temporarily down)

---

## Cookie Security

| Flag | Value | Purpose |
|------|-------|---------|
| `HttpOnly` | `true` | JavaScript cannot read the cookie (XSS protection) |
| `SameSite` | `Lax` | Cross-origin POST blocked (CSRF protection) |
| `Path` | `/admin` | Cookie only sent on `/admin/*` requests |
| `Secure` | `false` | Phase 2: `true` when HTTPS added |
| `Max-Age` | `3600` | 1 hour, matches Cognito IdToken expiry |

### Security Analysis

| Threat | Mitigation | Phase 2 Upgrade |
|--------|-----------|-----------------|
| **XSS** (steal token) | `HttpOnly` cookie — JS cannot read | — |
| **CSRF** (forged POST) | `SameSite=Lax` blocks cross-origin POST | Add CSRF tokens for mutations |
| **Token theft** (network sniffing) | VPN-only access (HTTP plaintext) | HTTPS + `Secure` cookie flag |
| **Cookie scope** (leaks to Web UI) | `Path=/admin` — not sent on `/` requests | — |
| **Username enumeration** | Same error for wrong-user and wrong-password | — |
| **Brute force** | Cognito built-in throttling | MFA |

**Phase 1 acceptable risk**: Read-only dashboard, VPN-only access, 1-3 admin users.

---

## Route Protection

| Route | Auth Required | Handler |
|-------|--------------|---------|
| `GET /admin/login` | No | Serve login page |
| `POST /admin/login` | No | Cognito InitiateAuth |
| `POST /admin/change-password` | No | Cognito RespondToAuthChallenge |
| `POST /admin/logout` | No | Clear cookie |
| `GET /admin/dashboard` | **Yes** | Serve jobs list page |
| `GET /admin/dashboard/{job_id}` | **Yes** | Redirect to `/admin/dashboard?job={job_id}` (old job page URL; opens the side panel) |
| `GET /admin/api/jobs` | **Yes** | Jobs list JSON |
| `GET /admin/api/jobs/{job_id}` | **Yes** | Single job JSON |
| `GET /admin/api/jobs/{job_id}/trace` | **Yes** | Agent trace (events.jsonl records) |
| `GET /admin/api/jobs/{job_id}/files` | **Yes** | Artifacts and input files |
| `GET /admin/api/jobs/{job_id}/files/{area}/{name}` | **Yes** | File proxy (images/text inline with CSP sandbox, else download) |

Protected routes use FastAPI's dependency injection:

```python
@admin_router.get("/api/jobs")
def list_jobs(claims: dict = Depends(require_admin)):
    # Only executes if JWT is valid
    # claims contains: username, email, token_use, exp, etc.
```

Unauthenticated requests to protected routes return HTTP 401 before any page content or data is served.

---

## Environment Variables

| Variable | Source | Used By |
|----------|--------|---------|
| `COGNITO_USER_POOL_ID` | `deploy_ops.sh` Step 12 → ECS env var | `auth.py`, `admin_router.py` |
| `COGNITO_CLIENT_ID` | `deploy_ops.sh` Step 12 → ECS env var | `auth.py`, `admin_router.py` |

Both are optional — if not set, auth endpoints return 503 ("Cognito not configured"). The Web UI continues to function normally.

---

## References

- [JWT Introduction](https://jwt.io/introduction) — Visual explanation of JWT structure (header, payload, signature)
- [RFC 7519 — JSON Web Token](https://datatracker.ietf.org/doc/html/rfc7519) — Official JWT specification
- [RFC 7517 — JSON Web Key](https://datatracker.ietf.org/doc/html/rfc7517) — Official JWKS specification
- [Amazon Cognito User Pools](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-identity-pools.html) — AWS Cognito documentation
- [Cognito Token Endpoint](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html) — How to verify Cognito JWTs
- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) — Cookie security best practices
- [SameSite Cookies Explained](https://web.dev/articles/samesite-cookies-explained) — How SameSite attribute works
- [PyJWT Documentation](https://pyjwt.readthedocs.io/en/stable/) — Python JWT library used in `auth.py`
