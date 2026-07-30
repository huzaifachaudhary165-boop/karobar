# Deploying Karobar

Two things ship separately: the **API** (a container or serverless function) and
the **app** (an APK you hand out or publish). The database and file storage are
already Supabase.

---

## Read this before choosing Vercel

Vercel runs Python as **serverless functions**. Karobar is a long-lived FastAPI
service with a database pool, and that mismatch shows up in four specific places:

| What | On a container host | On Vercel |
|---|---|---|
| Cold start | never | first request after idle pays ~2–5 s of import time |
| Request ceiling | none | 60 s (Pro) / 10 s (Hobby) — the assistant can exceed 10 s |
| DB connections | one warm pool | a new connection per invocation unless you use the transaction pooler |
| Uploaded files | disk works | no disk survives — Supabase Storage is mandatory |
| Rate limiting | works | in-process counters reset every invocation, so limits do not hold |

**On the Hobby plan the AI assistant will time out.** A chat turn is 1–8 s of
Groq plus several database round trips; against a 10 s ceiling that is a coin
flip. Everything else — billing, stock, reports, sync — fits comfortably.

`python -m app.cli check` prints these as warnings when it detects a serverless
host, so you are not relying on remembering this page.

### The function region is the biggest number in this whole document

**Put the function in the same AWS region as the database.** For a Supabase
project on `aws-1-ap-south-1` that is Vercel's `bom1` (Mumbai).

Measured on the live deployment with the function in `iad1` (Washington DC) and
the database in Mumbai:

| Request | Time |
|---|---|
| A route that touches no database | ~560 ms |
| One database round trip | ~3.6 s |
| A list endpoint | ~6.8 s |
| The dashboard (27 queries) | ~18.6 s |
| Creating an invoice | ~23 s |
| An assistant reply | **times out at 60 s** |

That is roughly **3 s to open a connection plus 570 ms per query**, and the
serverless engine uses `NullPool`, so a connection is opened per request rather
than reused. In-region both costs fall to single-digit milliseconds — which is
also what brings the assistant back under the timeout, since its cost is mostly
database round trips rather than Groq.

Set it in **Settings → Functions → Function Region**, then redeploy.

> **Do not put a `regions` key in `vercel.json` on Hobby** — it fails the build.
> And do not add a `"//"` key for comments either: `vercel.json` is validated
> against a strict schema and any unknown top-level property fails the build.
> Both failures are quiet. Vercel keeps serving the last good deployment, so the
> site stays healthy while every push silently stops landing — six deployments
> in a row failed that way before anyone looked at the deployments list. Notes
> about deployment belong in this file, not in that one.

### If you want a container instead

`render.com`, `railway.app` and `fly.io` all have free tiers, run the included
`backend/Dockerfile` unchanged, and remove every row in the table above. There is
nothing to port: the same image is what `docker-compose.yml` already builds.

Vercel remains a good fit for a **web** dashboard later. It is a poor fit for
this API today, and the app is set up for it anyway because that is what was
asked for.

---

## 1. API on Vercel

The repository already contains what Vercel needs:

```
vercel.json        runtime, 60 s ceiling, routes everything to the function
api/index.py       re-exports backend/app/main.py as `app`
requirements.txt   points at backend/requirements.txt
```

Deploy:

```bash
npm i -g vercel
vercel            # first run links the project
vercel --prod
```

Then set the environment variables in **Project → Settings → Environment
Variables**. The three marked ⚠ are the ones that differ from local:

```ini
ENVIRONMENT=production
DEBUG=false
SECRET_KEY=<python -c "import secrets;print(secrets.token_urlsafe(64))">

# ⚠ port 6543, the *transaction* pooler — not 5432. Serverless invocations must
#   not hold a session open, and 6543 is what tolerates that.
DATABASE_URL=postgresql+asyncpg://postgres.<ref>:<password>@aws-1-<region>.pooler.supabase.com:6543/postgres

# ⚠ there is no disk on a serverless host
STORAGE_BACKEND=supabase
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_KEY=<service_role key>
SUPABASE_BUCKET=karobar

# ⚠ counters cannot be shared between invocations, so this only adds overhead
RATE_LIMIT_ENABLED=false

GROQ_API_KEY=gsk_...
OTP_DEV_MODE=false
CORS_ORIGINS=https://your-app-domain
```

**Migrations do not run on Vercel.** The transaction pooler cannot execute them,
and a serverless function is the wrong place to alter a schema. Run them from
your own machine, against port **5432**, before deploying:

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://...@...pooler.supabase.com:5432/postgres \
  python -m alembic upgrade head
```

Check it came up:

```bash
curl https://<your-deployment>/health/ready
```

---

## 2. API in a container (recommended)

```bash
docker compose up --build        # local
```

or point Render/Railway/Fly at `backend/Dockerfile`. Same environment variables
as above, except:

```ini
DATABASE_URL=...pooler.supabase.com:5432/postgres   # session pooler is fine
RATE_LIMIT_ENABLED=true                             # works, keep it on
```

With more than one instance, move the rate limiter to Redis — the swap point is
`_Backend` in `app/core/rate_limit.py`, and no call site changes.

---

## 3. The Android app

The app has to know where the API lives; the default is a loopback address that
only works on an emulator.

```bash
cd mobile
flutter build apk --release \
  --dart-define=API_BASE_URL=https://<your-deployment>/api/v1 \
  --dart-define=GOOGLE_SERVER_CLIENT_ID=<web client id>.apps.googleusercontent.com
```

The APK lands in `build/app/outputs/flutter-apk/app-release.apk`. Copy it to a
phone and install it (Android will ask you to allow installing from that source).

While developing, `scripts/run-on-phone.ps1` is quicker: it builds, installs,
launches, and tunnels the API over the USB cable so no firewall rule is needed.

Two things that will break a release build if you touch the Android config:

* **`android:postSplashScreenTheme` is not a framework attribute.** It belongs to
  the AndroidX splashscreen library; under the `android:` namespace it fails
  resource linking with "attribute not found".
* **R8 needs the ML Kit rules in `android/app/proguard-rules.pro`.** The text
  recognition plugin references every script variant (Chinese, Japanese, Korean,
  Devanagari) while only Latin is bundled, and the shrinker treats the absent
  ones as an error.

Leave `GOOGLE_SERVER_CLIENT_ID` out and the "Continue with Google" button hides
itself — email, phone and password sign-in still work.

**Windows needs Developer Mode on** before `flutter build` will link plugins:

```
start ms-settings:developers
```

### A smaller APK

`--split-per-abi` produces one APK per CPU architecture instead of a universal
one, roughly halving the download:

```bash
flutter build apk --release --split-per-abi --dart-define=...
```

Install `app-arm64-v8a-release.apk` on any phone from the last several years.

### Signing

The release build currently signs with the debug key (see
`android/app/build.gradle.kts`), which is fine for handing an APK to a colleague
and **not** fine for the Play Store. For that, generate an upload keystore and
point a `signingConfigs.release` block at it.

---

## 4. Google Sign-In setup

Three ids, and the confusing part is that Android needs the **web** one:

1. Google Cloud Console → APIs & Services → Credentials.
2. Create an **OAuth client ID → Web application**. This id is what the ID token
   is minted for; it goes into both `GOOGLE_CLIENT_ID` on the server and
   `GOOGLE_SERVER_CLIENT_ID` in the APK build.
3. Create a second **OAuth client ID → Android**, with your package name
   (`app.karobar.karobar`) and the SHA-1 of your signing key. You never reference
   this id in code — Google uses it to verify the app's identity.

```bash
# SHA-1 of the debug key
keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey \
        -storepass android -keypass android
```

Sign-in failing with a configuration error almost always means the SHA-1 in step
3 does not match the key the APK was actually signed with.

---

## 5. What to check after deploying

```bash
curl https://<host>/health/ready         # database reachable
curl https://<host>/docs                 # interactive API docs
```

From the app: sign up, add a customer, make a bill, then turn on aeroplane mode
and make another one — it should save locally and upload when you reconnect.

`python -m app.cli check` against production settings prints every remaining
configuration warning, including the serverless-specific ones.
