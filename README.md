# Smart Renamer

An internal tool that reads incoming files and gives them clear, consistent names:

```
Document1.pdf   →  2026-10-28_QUO_Precitool_PTC-Q-2026-0457_Progressive-Die-Contact-Spring-KR-5520.pdf
Book1.xlsx      →  2026-10-21_INV_Sri-Balaji-Metals_SBM-2026-27-1189_CuSn6-Strip-0-3-42-mm.xlsx
export.dxf      →  2026-09-15_DRW_Lumen-Auto_KR-4711-02-RevC_Contact-Spring-0-64-mm.dxf
scan_0034.pdf   →  2026-10-02_CERT_Wieland_MTC-88231_CuSn6-R420-Strip-0-30-42-0.pdf
```

There are two ways to use it:

* **Website:** drag files in, check the suggested names, then download them.
* **Browser button (Chrome/Edge):** click the icon, or press **Alt+Shift+R**, on any page with attachments. Every file on that page is renamed and saved to Downloads. You can also right-click a single link and choose *Rename & download*.

Everything runs on **one company server**. There are no cloud services, no AI APIs and no internet calls. Files are analysed in memory and then discarded. Only the names, a fingerprint (SHA-256) and the fields that were found are kept, for the history.

---

## 1. How it decides the name

The name pattern is `DATE_TYPE_COMPANY_REFERENCE_SUBJECT.ext`, and an admin can change it. Each part is found by explainable rules, not guesswork. Every suggestion shows **where** each value came from, for example *"labelled 'Invoice No', in document header"*.

| Step | What happens | Technology |
|---|---|---|
| 1. Identify the file | Checks the real file type from its bytes, not its extension. A `.pdf` that is really a Word file is handled correctly, and the right extension is put back. | Magic-byte signatures, `olefile` for old Office/Outlook files |
| 2. Safety check | Rejects zip bombs, damaged containers and unsafe paths. Parsing runs in a separate, time-limited, memory-limited process that is restarted regularly. | `pebble` process pool, OS resource limits |
| 3. Read the content | Extracts the text, tables, headers and footers, and the file properties. | PDF: `pypdf`. Word: `python-docx`. Excel: `openpyxl` and `xlrd`. PowerPoint: `python-pptx`. Outlook `.msg`: `extract-msg`. `.eml`: Python `email`. |
| 4. Scans and photos | When a PDF has no text layer, or the file is an image, the text is read optically (English + German). | Tesseract OCR with `pypdfium2` |
| 5. CAD | DXF title blocks give the drawing number, revision, title, customer and date. The STEP header gives the part number, name, organisation and date. IGES uses its global section. DWG is read through the free ODA File Converter if installed. | `ezdxf`, STEP/IGES header parsers |
| 6. Find the 5 fields | **Date:** found next to labels like *Date / Datum / Invoice date*. "Valid until" and "delivery date" are ignored. **Type:** 23 document types (quotation, PO, invoice, drawing, PPAP, 8D, certificate and more) are scored by English and German keywords, which count 3× in the title area. **Reference:** found after labels such as *Quotation No / Bestellnummer / Drawing No*. **Company:** from the letterhead, *To/From/Customer* labels, email domains and legal suffixes (GmbH, Pvt Ltd, AG …), always excluding Kramski itself. **Subject:** from the *Subject/Betreff* line, the email subject or the CAD title. | Rule file `app/engine/rules.json`, which can be edited without code |
| 7. Match to your own lists | Company names are matched to the customer/supplier master list, so *"ACME Gmbh."*, *"Acme GmbH & Co KG"* and *@acme.de* all become one short name. | `rapidfuzz` fuzzy matching against the imported ERP list |
| 8. Score and compose | Every value gets a confidence score. Names above the threshold are marked **Ready**. The rest show **Please check**. The name is made safe: no special characters, umlauts written out, Windows reserved names avoided, under 120 characters, and the extension can never be changed. | `app/engine/naming.py` |
| 9. Learn | Every correction a person makes is stored. *Admin → Corrections* shows the most frequent ones, so you know which alias or rule to add. | `corrections` table |

**The biggest accuracy boost is to import the customer and supplier list** (Admin → Customers & suppliers → CSV from the ERP). Then the company part of the name is always the official short name.

---

## 2. Install the server (one time)

You need a Windows or Linux PC or server that stays on, with **Python 3.11 or newer**.

### Windows
1. Install Python from python.org and tick **"Add python.exe to PATH"**.
2. *(Optional, for scanned documents)* Install Tesseract OCR from the UB Mannheim build, including the German language. Then set `TESSERACT_CMD` in `.env`.
3. Double-click **`setup.bat`**. It installs everything, creates an HTTPS certificate, and asks you to choose the admin password.
4. Open `.env` and set `ALLOWED_HOSTS` to the name people will type, for example `renamer.kramski.local,localhost`.
5. Double-click **`start.bat`**, then open `https://<server-name>:8443`.

### Linux
```bash
sudo apt install python3-venv tesseract-ocr tesseract-ocr-deu
./setup.sh
. .venv/bin/activate && python run.py
```
For a permanent service, use systemd or Docker (`docker compose up -d`; see `docker-compose.yml`).

### First steps as admin
1. Sign in as `admin`.
2. **Admin → Naming rules:** check the company names and email domains that belong to Kramski.
3. **Admin → Customers & suppliers:** import the CSV (`code,name,short_name,aliases,domains,kind`).
4. **Admin → Users:** add each person. They must choose their own password at first sign-in.

---

## 3. Install the browser button

**For one person (testing):** open `chrome://extensions` (or `edge://extensions`) and turn on **Developer mode**. Click **Load unpacked** and choose the `extension` folder.

**For everyone (IT):** pack the folder and deploy it with Group Policy (`ExtensionInstallForcelist`). It is internal, so it is not published in any public store.

Then each person does the following once:
1. On the website, go to **Account → Browser button → Create key** and copy the key.
2. In the extension **Settings**, enter the server address and the key, then click **Save and test**. Chrome asks for permission to contact that one server.
3. Open an email or page with attachments and click the icon. Done.

If attachments are stored on a different site than the page (common in webmail), the popup shows **Allow and retry** once for that site.

---

## 4. Security

| Area | What is done |
|---|---|
| Data stays inside | Runs on a company server. No external calls, CDNs, fonts or telemetry. File contents are never stored. |
| Passwords | Argon2id hashing. At least 12 characters, using 3 character types, and not containing the username. Forced change at first sign-in. |
| Brute force | 5 wrong attempts from one computer pause sign-in for that username on that computer for 15 minutes. There are also per-IP and per-username caps. A stranger cannot lock a real person out, and unknown usernames get the same answer and the same timing as wrong passwords. |
| Sessions | Random tokens, stored only as SHA-256 hashes. `HttpOnly`, `Secure`, `SameSite=Strict`, `__Host-` cookie. 8-hour lifetime and 60-minute idle timeout. Changing a password signs out other devices. |
| CSRF | Every change needs a per-session token header, and cross-origin requests are refused. |
| Browser button | Personal keys, stored hashed, expire after 180 days and can be revoked. They are revoked automatically when the password changes or is reset. A key can only rename the owner's own files: it can never manage accounts or settings, or see other people's history. The extension talks only to the configured server, and only after a click. |
| Server load | Concurrent analyses are capped globally and per person, so one user cannot exhaust the server's memory. |
| Hostile files | Programs, scripts and macro files (`.exe`, `.hta`, `.js`, `.docm` …) are refused, even when disguised as a PDF. True-type detection, zip-bomb limits, a 50 MB cap and a decompression-bomb guard for images. Parsing happens in isolated worker processes with time and memory limits. Macros are never executed. XML is parsed safely. |
| Web hardening | Strict Content-Security-Policy (no inline scripts), clickjacking protection, `nosniff`, no-referrer, HSTS, host-header allow-list and generic error messages. All data is displayed as text, never as HTML, which prevents XSS. |
| Accountability | Every sign-in, analysis, rename, key and setting change goes into an **HMAC hash-chained audit log**. *Admin → Security log → Check log integrity* detects any edited or deleted entry. The CSV export is protected against Excel formula injection. |
| Renaming | People can edit a name, but the extension stays the one detected, so a PDF can never become `.exe`. Path characters are stripped. |

**Still needed at deployment (by IT):** HTTPS with a certificate from the company CA, a firewall rule that allows only the office network to reach port 8443, encrypted disk on the server (BitLocker or LUKS), nightly backups of the `data` folder, and a review or penetration test before company-wide use.

---

## 5. Tests

```bash
python scripts/make_samples.py   # realistic sample files (fictional companies)
python -m pytest -q              # 26 tests: naming accuracy + security
```

The tests cover login, CSRF, sign-in throttling, executable blocking, key revocation, permissions, extension keys, upload limits, zip bombs, safe names and audit-log tamper detection.

## 6. Known limits

* **Native CAD files** (SolidWorks, Creo, CATIA, NX) are closed formats. Their names come from the email and page context. DWG needs the free ODA File Converter (`ODA_FILE_CONVERTER` in `.env`).
* **Password-protected PDFs** and encrypted Office files can't be read. They are named from their context and marked *Please check*.
* **Handwritten or poor scans** give lower confidence and are flagged for review.
* **Webmail:** Gmail and most webmail and portal pages work. A few apps (for example some Outlook Web views) generate attachments in ways an extension can't reach. Drag-and-drop on the website always works.

## 7. Project layout

```
app/engine/      naming engine: detect.py, extract.py, fields.py, naming.py, rules.json, worker.py
app/api/         auth.py, files.py, admin.py
app/static/      website (HTML/CSS/JS, no external libraries)
app/security.py  sessions, CSRF, tokens, rate limits, headers
app/audit.py     tamper-evident audit log
extension/       Chrome/Edge extension (Manifest V3)
tests/           automated tests
```
# File_rename_tool
