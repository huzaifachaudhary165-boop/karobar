# Karobar on the web

The same app as the phone — same code, same orange, same screens. Flutter
builds it for the browser from `../mobile`, and this folder is what Vercel
serves.

Nothing here is a second copy of the app. Changing a screen changes it
everywhere; the only thing that lives in this folder is the built site and how
to serve it.

## Deploying it

Vercel has no Flutter SDK, so the site is built here and committed rather than
built on deploy. That keeps deploys instant and means a broken SDK upgrade can
never take the live site down.

**First time — on vercel.com:**

1. New Project → import this repository
2. **Root Directory: `webapp`** ← the one setting that matters
3. Framework preset: **Other**. Leave the build and install commands empty.
4. Deploy

Vercel reads `vercel.json` from this folder and serves `public/`.

The backend is a separate Vercel project in the same repo and is not touched by
any of this.

**Every time after:**

```powershell
.\build.ps1          # rebuild and refresh public/
git add webapp
git commit -m "Rebuild the web app"
git push
```

Vercel deploys on push.

## What `vercel.json` is doing

JSON has no comments and Vercel rejects the file outright if you invent a
`comment` key, so the reasoning lives here.

**The rewrite.** go_router puts real paths in the address bar, so refreshing on
`/invoices` asks the server for `/invoices`, which is not a file. Everything
falls back to `index.html`. Vercel matches a real file first, so this catches
only the app's own routes and never an asset.

**Two cache rules, because Flutter names its files two different ways.**
`main.dart.js` and `index.html` are rebuilt on every deploy and carry no hash
in their names, so they must revalidate — cached, a shopkeeper keeps running
last week's app and reports bugs fixed days ago. `canvaskit/` and the two drift
files change only when Flutter or drift is upgraded, and they are the heaviest
thing a shop on 3G downloads, so they are kept for a year.

**The security headers.** This is a shop's books. Nothing here should be framed
by another site or sniffed into a different content type.

## Pointing it at a different backend

The API address is baked in at build time.

```powershell
.\build.ps1 -Api "https://your-api.vercel.app/api/v1"
```

The backend already allows browser requests from any origin
(`CORS_ORIGINS` defaults to `*`). Before this is in front of real shops, set
that to the actual web address instead — the backend warns about it on startup
for exactly this reason.

## What the browser cannot do

Three things on the phone have no browser implementation at all, so the app
says so and names the alternative rather than offering a button that throws:

| | Phone | Browser |
|---|---|---|
| Bills, parties, items, expenses, reports | ✓ | ✓ |
| Works offline, uploads later | ✓ | ✓ |
| Assistant, including offline commands | ✓ | ✓ |
| Barcode scanning with the camera | ✓ | ✗ |
| Reading a supplier bill from a photo | ✓ | ✗ |
| Bluetooth thermal printing | ✓ | ✗ |

Everything else — including the outbox and the cached lists that make the app
usable with no signal — works the same, because the browser runs the same
SQLite the phone does, compiled to WebAssembly.

`sqlite3.wasm` and `drift_worker.js` sit in `../mobile/web/` and are copied into
`public/` by the build. They must stay next to `index.html`, and they must match
the `drift` and `sqlite3` versions in `mobile/pubspec.lock` — a mismatch fails
at startup, not at build time.

If the browser is old enough to have neither OPFS nor IndexedDB, drift falls
back to memory: the app still runs, but anything queued while offline is lost
on refresh. The shop's own records are on the server and are never at risk. It
says so in the browser console.

## First load is heavy

About 11 MB the first time — the app itself plus the rendering engine — then
almost nothing, because the service worker keeps it. On a slow connection that
first visit is a real wait, which is why `index.html` carries a Karobar loading
screen instead of the blank page Flutter would otherwise show.

Still far less than asking a shopkeeper to install a 112 MB APK from an unknown
source.

## After a Flutter or drift upgrade

`canvaskit/`, `sqlite3.wasm` and `drift_worker.js` are cached for a year, so
they will not pick themselves up. Re-download the two drift files to match the
new versions in `pubspec.lock`, rebuild, and hard-refresh once.
