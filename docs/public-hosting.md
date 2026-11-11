# Free public demonstration deployment

**English** | [Español](es/public-hosting.md)

The deployment profile targets a single Render Free web service and a separate Neon Free PostgreSQL 16 project. It is intended for a small synthetic demonstration. Repository configuration is not proof of a live deployment: acceptance requires a real provider URL, successful HTTPS role entry, worker progress, verified export, and a no-charge account review.

## Hosting choices

| Platform | Fit for the existing application |
|---|---|
| [Render](https://render.com/docs/free) | Runs the existing Docker/Python stack; the API and worker share one Free web-service container |
| [Vercel](https://vercel.com/docs/frameworks/backend/fastapi) | Supports FastAPI as a function; the durable worker would need a function-oriented execution/recovery design |
| [Netlify](https://www.netlify.com/platform/core/functions/) | Hosts the interface; native functions use JavaScript/TypeScript/Go, so the Python backend needs another host or adaptation |
| [Neon](https://neon.com/docs/introduction/plans) | Separate persistent PostgreSQL; use the direct TLS endpoint, not the pooled endpoint |

Render's Free web service sleeps after 15 minutes without inbound traffic and can take about a minute to wake. Its filesystem is ephemeral. Free Render Postgres expires after 30 days, so this profile uses Neon instead. Render's free-hour, build, and transfer allowances are finite; **free instances can still incur excess charges when a payment method is present**. Use only Free/Hobby selections and an account with no payment method; stop if the provider requires payment or an upgrade. No paid worker, disk, database, custom domain, or keep-alive service is included. See [Render's current limits](https://render.com/docs/free) and [billing FAQ](https://render.com/docs/faq).

Neon Free currently lists 100 CU-hours, 1 GB storage per project, and 5 GB public transfer per project, with scale-to-zero. These limits and availability can change. Remain on the Free plan and verify the dashboard before deployment. Polling consumes database compute while Render is awake. Suspension can delay work; neither provider offers an uninterrupted demo under this profile.

## Runtime boundaries

`render.yaml` defines one Free web service, manual deployments, `/readyz`, and the existing Docker image. `python -m credit_support.hosted_demo` starts one API and one worker, forwards shutdown to both, and exits if either process stops. PostgreSQL leases retain restart safety. When Render suspends the container, both processes stop; jobs wait for a later wake-up.

The supervisor requires a direct TLS URL for `cds_runtime` and checks that the connected role has no elevated flags, memberships, schema/database ownership, or public-schema creation rights. It requires the current migration and a published policy. It does not run migrations with an owner credential in the public service.

Child processes receive an allowlisted environment. OpenAI access is disabled, the provider key is empty, and static identities are empty. Public-mode settings reject live-model access, provider keys, or static credentials; they ignore local `.env` files. The local project's OpenAI ledger and private configuration remain separate and must not be copied to hosting.

The public page exposes guided sessions, not the advanced token form. Case isolation, expiry, immutable review, and report checks remain in effect. The blueprint limits admission to five active and 100 retained sessions. Retention includes ended/expired sessions; there is no automatic purge. Capacity exhaustion requires operator review, not a database reset or budget replenishment.

The browser's `Origin` must match the explicit HTTPS public origin (`CDS_PUBLIC_ORIGIN`, otherwise Render's `RENDER_EXTERNAL_URL`). Uvicorn proxy-header rewriting remains disabled. The existing peer limiter may group visitors behind a shared provider proxy; it is a conservative process-local limit, not a distributed abuse control. Do not trust arbitrary forwarded headers to bypass it.

## Private database preparation

Create a new isolated Neon Free project with PostgreSQL 16. Keep its owner URL private and select the **direct** connection. [SQL-created roles](https://neon.com/docs/manage/roles) avoid the elevated privileges assigned to console-created roles. [Pooled endpoints](https://neon.com/docs/connect/connection-errors) can reject this application's startup timeout options.

Create the ignored local `.env.hosting` file:

```dotenv
CDS_MIGRATION_DATABASE_URL=postgresql+psycopg://OWNER:PASSWORD@DIRECT_HOST/neondb?sslmode=require
```

Replace the placeholders privately; do not paste credentials into chat, issues, Git, or command arguments. Preserve any additional TLS parameters supplied by Neon. From the repository root:

```sh
uv run python scripts/provision_public_demo.py
```

The helper refuses an existing output file or runtime role. In one database transaction it creates the restricted role, applies migrations using the supplied owner connection, and publishes the synthetic policy. It writes only the restricted URL to ignored `.env.hosting.runtime` with exclusive creation, then commits. It never resets a role password or overwrites credentials. If commit delivery becomes uncertain, retain any written private runtime file for recovery and inspect the project before retrying; no automatic destructive repair is attempted. This path must be exercised against the actual Neon project before publication is accepted.

## Render setup

1. Use a Free Render account/workspace with no payment method. Account creation, provider terms, and GitHub permissions must be completed by the account owner.
2. Connect only the `credit-decision-support` repository, without changing its visibility. Import the blueprint from the accepted deployment commit on `main`.
3. Verify that the resource list contains **one Free web service**, no Render database or paid resource, and automatic deployments are off. Set `CDS_DATABASE_URL` to the restricted URL from `.env.hosting.runtime`. Do not upload `.env`, the owner URL, or any OpenAI key.
4. Deploy manually. Render supplies the HTTPS origin and port. Wait for migration/policy/role preflight, API readiness, and both supervised processes.
5. Open the returned `onrender.com` URL. Start a guided analyst session, inspect source evidence, switch to Reviewer, record a reason, switch to Auditor, and export both report formats. Verify an unrelated demo cannot read the case and paid-provider requests remain rejected.
6. Confirm the service plan, billing state, and Neon plan are still free. Record the real URL, deployed commit, observed cold-start behavior, and test result separately from local measurements.

No real public URL or successful provider-side provisioning is claimed until these steps are observed. If account access or provider authorization is unavailable, the deployable preparation can be reviewed without publishing.
