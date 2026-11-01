# Hop 🐇

Hop turns messy downloads into clear, consistent file names. It runs on your own computer, with no cloud and no AI services.

```
DA3.pdf           →  2026-10-28_ASSIGN_BCSE202L_Assignment-3_Linked-Lists-and-Stacks.pdf
1706.03762v5.pdf  →  2017-12-06_PAPER_Vaswani-et-al_arXiv-1706-03762_Attention-Is-All-You-Need.pdf
lec07.pptx        →  2026-10-01_SLIDES_CS301_Lecture-7_Dynamic-Programming.pptx
QP.pdf            →  2025-11-19_EXAM_MAT2002_Applications-of-Differential-and-Difference-Equations.pdf
Untitled.ipynb    →  2026-10-31_NB_Linear-Regression-from-Scratch.ipynb
main.py           →  2026-10-31_CODE_Dijkstra-Shortest-Path-on-a-Weighted-Graph.py
certificate.pdf   →  2026-09-12_CERT_Coursera_8XK2QPL7M4ZA_Machine-Learning-Specialization.pdf
ticket.pdf        →  2026-11-12_TICKET_4521367890_Chennai-Central-to-Katpadi-Jn.pdf
```

The pattern is `DATE_TYPE_FROM_NUMBER_TITLE`. Parts that don't apply are left out, and you can change the pattern under Admin → Naming rules.

There are two ways to use it:
* **Website:** drag files onto the page, check the names, and download.
* **🐇 button:** one click on any page with files (a course page, an email, a portal) renames every file and saves it to `Downloads/Hop`. The shortcut is **Alt+Shift+R**. You can also right-click any link and choose *Rename & download with Hop*.

---

## Start Hop (Windows)

1. Install **Python 3.11+** from python.org and tick **"Add python.exe to PATH"**.
2. Double-click **`run_local.bat`**. The first run takes a few minutes while it installs things.
3. The browser opens at **http://localhost:8000**. Sign in with **admin / Smart-Rename-2026!**, then change the password under Account.

Keep the black window open while you use Hop. Closing it stops Hop. If you can't sign in, double-click **`create_admin.bat`**.

Optional: install **Tesseract OCR** to read scanned PDFs and photos of documents.

## Add the 🐇 button (Chrome / Edge, one time)

1. Go to `chrome://extensions` (or `edge://extensions`) and turn on **Developer mode** (top right).
2. Click **Load unpacked** and pick the **`extension`** folder.
3. A tab opens by itself asking *"Connect the Hop button?"*. Click **Allow**. Done.

Pin the 🐇 icon to the toolbar using the puzzle-piece icon. If Hop wasn't running when you installed the button, start Hop, click 🐇 and press **Connect**.

---

## How Hop decides the name

There's no AI involved, only transparent rules. On the website, every part of the name shows **where it was found**.

| Step | What happens | Technology |
|---|---|---|
| Identify | Checks the file's real type from its bytes, not its extension. Programs and scripts (`.exe`, `.bat`, `.hta`, macro files …) are refused, even when disguised as a PDF. Source code is fine. | magic-byte signatures, `olefile` |
| Read | Pulls out the text, tables, slide titles, notebook headings, email sender, subject and date, and file properties. | `pypdf`, `python-docx`, `openpyxl`, `python-pptx`, `extract-msg`, Python `email`, `ezdxf` |
| Title | Takes the **largest text at the top of page 1** (paper and assignment titles), the first slide title, the first notebook heading, or a code file's docstring. | font-size analysis in `pypdf` |
| Type | Scores 25+ document types by keywords, counting 3× near the top. Types include paper, slides, notes, assignment, lab, exam, syllabus, report, book, resume, certificate, grade card, offer letter, letter, form, receipt, invoice, ticket, bank statement, agreement, guide, code, notebook, dataset and screenshot. | `app/engine/rules.json` (edit it freely) |
| From | Course codes (`BCSE202L`, `CS 301`), colleges as short forms (*Vellore Institute of Technology* → `VIT`), issuers at the top (`Coursera`, `Spotify`), a paper's first author (`Vaswani et al`), the email sender, or the website the file came from. | rules + `rapidfuzz` matching |
| Number | Assignment, lab or lecture numbers (`Assignment-3`, `Exp-5`, `Lecture-7`), arXiv IDs and DOIs, invoice, transaction, PNR and credential numbers. | label rules |
| Date | Dates next to labels like *Date / Date of Exam / Date of Journey*. Due dates and dates of birth are ignored. It falls back to the date in the file name, then the file properties, then today's date. | regex date parser (day-first by default) |
| Safe name | No special characters or spaces, at most 120 characters. You can edit names, but the file extension can never be changed. | `app/engine/naming.py` |

**Optional:** Admin → Known sources lets you teach Hop names it should always write the same way, for example *Vellore Institute of Technology → VIT*, or anything from `@vit.ac.in`.

## Security

* **Stays on your computer:** Hop only listens on `127.0.0.1`, so other devices can't reach it. It makes no internet calls, and file contents are never stored.
* **Accounts:** Argon2id password hashing, a 12+ character password policy, sign-in throttling, and the same error for wrong usernames and wrong passwords.
* **Sessions:** secure `HttpOnly` / `SameSite=Strict` cookies, idle timeout and CSRF tokens.
* **🐇 button connection:** a one-click pairing code that is random, expires in 5 minutes and is only accepted from the same computer. The key is handed over once and stored hashed. You can revoke it under Account, and it's revoked automatically on a password change. The button can only rename your own files.
* **Hostile files:** programs and scripts are refused, along with zip bombs and oversize files. Files are read in separate, time- and memory-limited processes, and macros are never run.
* **Web hardening:** strict Content-Security-Policy, all data shown as text (no XSS), and anti-clickjacking headers.
* **Tamper-evident history:** a hash-chained audit log. Admin → Security log → *Check log integrity* proves nothing was edited.

## Put it online (free)

See **[DEPLOY.md](DEPLOY.md)**: GitHub → Neon (database) → Render (app), with an explanation of every piece.

## Tests

```bash
python scripts/make_samples.py   # realistic sample files (made-up people and courses)
python -m pytest -q              # 33 tests: naming accuracy + security
```

## Project layout

```
app/engine/   naming engine: detect, extract, fields, naming, rules.json, worker
app/api/      auth, files, admin, pair (button connection)
app/static/   website (no external libraries)
extension/    the 🐇 button (Chrome/Edge, Manifest V3)
tests/        automated tests
```
