# Deploying Hop for free (and understanding what's going on)

Right now Hop runs on **your laptop** (`http://localhost:8000`). Deploying means running the same code on a computer in a data centre, so you can open it from your phone or any browser at an address like `https://hop-xyz.onrender.com`.

```
 your browser / 🐇 button
        │  HTTPS (encrypted)
        ▼
 ┌─────────────────────────┐        ┌──────────────────────┐
 │ Render (free)           │        │ Neon (free)          │
 │ runs Hop in a container │ ─────▶ │ PostgreSQL database  │
 │ (built from Dockerfile) │        │ users, history, log  │
 └─────────────────────────┘        └──────────────────────┘
        ▲
        │ git push = new version deployed automatically
 GitHub (your code)
```

**Why two services?** Render's free plan has an *ephemeral* disk: every restart wipes it, so the local SQLite file would vanish. The database therefore lives on Neon, which keeps it safe.

> ⚠️ **Before you put it online:** anyone on the internet can now *see* the sign-in page, so use a strong admin password.
> Files you rename travel over HTTPS to Render's server. They are read in memory and never stored, but they do leave your laptop.
> That's fine for your own files. **Keep your dad's company files on the local version.**

---

## Step 1: Put the code on GitHub (5 min)

1. Create a **private** repository on github.com called `hop`.
2. In VS Code's terminal, inside your Hop folder:
   ```bash
   git add .
   git commit -m "Hop ready for deploy"
   git branch -M main
   git remote add origin https://github.com/<your-username>/hop.git
   git push -u origin main
   ```
3. Check on GitHub that **`.env`, `data/`, `certs/` and `.venv/` are NOT there**. `.gitignore` keeps them out, because they hold secrets or your private data.

## Step 2: Create the database on Neon (3 min)

1. Sign up at **neon.com** (no card needed). Create a project named `hop` and pick the **AWS Asia Pacific (Singapore)** region, which is closest to India.
2. Copy the **connection string**. It looks like
   `postgresql://user:password@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`
   It contains a password, so treat it like one and never put it in git.

## Step 3: Run Hop on Render (10 min)

1. Sign up at **render.com** with GitHub. Render may ask for a card to verify you; the free plan isn't charged.
2. Click **New → Blueprint** and pick your `hop` repo. Render reads **`render.yaml`**, which already describes everything.
3. Render asks for the two secrets:
   - `DATABASE_URL`: paste the Neon string
   - `ADMIN_PASSWORD`: your first admin password (12+ characters, three kinds of characters, e.g. `Hop-Bunny-Carrot-2026!`)
4. Click **Apply**. The first build takes about 5–8 minutes while it installs Python, Tesseract and the libraries.
5. When the dashboard says **Live**, open your address (`https://hop-xxxx.onrender.com`) and sign in as `admin` with that password.
6. Back in Render → **Environment**, **delete `ADMIN_PASSWORD`**. It was only needed once.

## Step 4: Point the 🐇 button at it (1 min)

Open the extension's **Settings** and enter the address `https://hop-xxxx.onrender.com`. Click **Connect** and allow the permission, then press **Allow** in the tab that opens.

To switch back to your laptop version, set the address to `http://localhost:8000` and Connect again.

## Updating

Change code → `git push` → Render rebuilds and redeploys by itself. Watch it under **Events / Logs**.

---

## What each piece does (the learning part)

| Piece | What it is | Why Hop needs it |
|---|---|---|
| `Dockerfile` | A recipe for a mini Linux computer: *start from Python 3.12, install Tesseract, install requirements, copy the app, run `python run.py` as a non-admin user* | Render builds this recipe into an **image** and runs it as a **container**. It's the same everywhere, so "it works on my machine" becomes "it works everywhere". |
| `render.yaml` | "Infrastructure as code": the Render settings written in a file | Anyone can re-create your exact setup with one click. Secrets are marked `sync: false` so they never go into git. |
| Environment variables | Settings given to the program from outside (`DATABASE_URL`, `ADMIN_PASSWORD`, …) | The same code runs locally (SQLite) and in the cloud (Postgres) without code changes. Secrets stay out of the source code. |
| `DATABASE_URL` | Address + username + password of the database | `app/config.py` reads it. Without it, Hop falls back to the local SQLite file. |
| HTTPS | Encryption between browser and server | Render provides the certificate automatically. That's why `COOKIE_SECURE=true` works: cookies are only ever sent encrypted. |
| `TRUST_PROXY=true` | Render's load balancer sits in front of Hop and tells it the visitor's real IP in the `X-Forwarded-For` header | Rate limiting, the audit log and the button's pairing all need the real IP. Only turn this on behind a proxy, because otherwise anyone could fake that header. |
| Health check `/api/health` | Render pings this to know the app is alive | Failed pings → Render restarts it. |
| `RENDER_EXTERNAL_HOSTNAME` | Render tells the app its own address | Hop only answers requests for its real address (Host-header check), which blocks some spoofing tricks. |
| `AUDIT_KEY` | A random secret generated by Render | Seals the audit log so edits can be detected, and stays the same across restarts. |

## Free-plan limits (late 2026, check the sites as they change)

- **Render free:** 512 MB RAM and 0.1 CPU. It **falls asleep after 15 minutes without visits**, and the first visit after that takes about a minute to wake it. There are 750 free hours a month, enough for one app. No terminal access, which is why the admin is created from `ADMIN_PASSWORD`.
  On 0.1 CPU, scanned PDFs (OCR) are slow, so keep uploads small. `MAX_UPLOAD_MB` is set to 25.
- **Neon free:** 0.5 GB storage and 100 compute-hours per month. It sleeps when idle and wakes in under a second. Hop only stores names and history, so 0.5 GB lasts a very long time.

## Level 2: your own free Linux server (to really learn)

**Oracle Cloud Always Free** gives you a real virtual machine that never sleeps (an ARM Ampere VM; since June 2026 the free share is 2 CPUs and 12 GB RAM). You need a card for verification, and free capacity can be "out of stock" in busy regions. On it you'd learn:

1. **SSH** into the server: `ssh ubuntu@<ip>`
2. Install **Docker**, copy Hop, and run `docker compose up -d`
3. Put **Caddy** in front: it gets free HTTPS certificates from Let's Encrypt automatically
4. Open only ports 80/443 in the **firewall**, then add **backups** and **updates**

That's how real servers are run, and the same Dockerfile works there unchanged.

## Troubleshooting

| You see | Fix |
|---|---|
| Page loads for about a minute, then works | Normal: the free app was asleep. |
| "Invalid host header" | You're using a different address than Render's (e.g. your own domain). Add it to an `ALLOWED_HOSTS` environment variable. |
| Can't sign in on the first deploy | Check the Render **Logs**: if `ADMIN_PASSWORD` was too weak, the log says why. Fix it, then use **Manual Deploy → Restart**. |
| Forgot the online admin password | In Render → Environment set `ADMIN_PASSWORD` to a new strong password **and** `ADMIN_RESET` = `true`, save (Render restarts), sign in, then delete both variables. |
| Build fails | Read the last red lines of the build log. Usually a typo in an environment variable, or a library version. |
| 🐇 button says "Hop isn't running" | The app is asleep: open the website once to wake it, then click Connect again. |
