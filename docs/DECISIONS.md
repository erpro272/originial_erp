# Decisions

Short records of choices and the reason for each. Newest at the bottom.

1. **Planning has 6 tabs** (mockup), not the 7 steps on slide 10. What-if analysis is
   covered by Plan comparison. *Owner confirmed.*
2. **Dashboard** is a 7th top-nav item at the end; "Coming soon" until the owner specifies it.
   *Owner request.*
3. **Brand name** is a neutral placeholder ("Brand"), configurable via `VITE_BRAND_NAME`.
   *Owner request.*
4. **Multi-tenancy with two security layers** (owner's diagram): user → backend authorisation
   (membership + role) → Layer 1 PostgreSQL RLS → Layer 2 AES-256-GCM per company.
   - RLS is `FORCE`d and the API connects as `erp_app` (NOSUPERUSER, NOBYPASSRLS), so a
     missing `WHERE tenant_id = …` can't leak data. The tenant is set with
     `set_config('app.tenant_id', …, true)`, so it is local to the transaction and can't
     leak through pooled connections.
   - `users` and `tenants` are global identity tables. `memberships` and `tenants` have
     their own RLS policies (visible to the bound company, or to the signed-in user).
   - Background jobs list tenants through a `SECURITY DEFINER` function that returns ids
     only, then process each tenant with RLS still on. No role bypasses RLS at runtime.
   - Envelope encryption: each company's data key is stored wrapped by the master key
     (AAD = tenant id). Field ciphertext is bound to tenant + field (AAD), so copying
     ciphertext between rows, fields or companies fails to decrypt.
   - Encryption is applied to sensitive fields (bank account, UPI, …), not whole rows:
     the rest must stay queryable, sortable and reportable, and RLS already isolates it.
5. **Money** is stored as integer paise (`BIGINT`).
6. **Refresh token in an httpOnly cookie, access token in memory**: JavaScript can't read
   the long-lived token; the cookie is SameSite=Strict and scoped to `/api/auth`.
7. **Audit log is append-only at the database level** (the app role has no UPDATE/DELETE),
   and sensitive keys are redacted before writing.
8. **MinIO image**: the official images are no longer on Docker Hub, so we use the
   community-maintained `pgsty/minio` pinned by digest. Any S3-compatible store works.
9. **TypeScript 5.9**: openapi-typescript requires TS 5, and typescript-eslint doesn't
   support TS 7 yet.
10. **Invoice extraction model** is `claude-sonnet-5-5`, as specified by the owner, with the
    API's server-side refusal fallback enabled.
