# LabGuard+ — Technical Architecture & Function-by-Function Guide

> **Purpose of this Document:** A concise, critical engineering reference explaining **what programming languages and tools built LabGuard+**, **why each architectural decision was made for Raspberry Pi 2/3**, and **what every backend, hardware, database, and frontend function does**.
>
> Each section below is **collapsible** so you can jump directly to the topic you need without scrolling through a wall of text.

### Quick Jump Index
- [1. Languages, Frameworks & Critical "Why" Matrix](#1-languages-frameworks--critical-why-matrix)
- [2. Repository File-by-File Map](#2-repository-file-by-file-map)
- [3. Backend Server (`app.py`) — Function-by-Function Reference](#3-backend-server-apppy--function-by-function-reference)
- [4. Hardware GPIO Engine (`hardware/gpio_manager.py`) — Function-by-Function Reference](#4-hardware-gpio-engine-hardwaregpio_managerpy--function-by-function-reference)
- [5. SQLite3 Database Schema (`labguard.db` — All 9 Tables)](#5-sqlite3-database-schema-labguarddb--all-9-tables)
- [6. Frontend Interfaces (`templates/*.html`) — JS Function Reference](#6-frontend-interfaces-templateshtml--js-function-reference)
- [7. Security Architecture & Critical Threat Model](#7-security-architecture--critical-threat-model)
- [8. Deployment, Offline CSS Pipeline & Node.js Parity](#8-deployment-offline-css-pipeline--nodejs-parity)
- [9. Critical Engineering Trade-Offs & Defense Q&A](#9-critical-engineering-trade-offs--defense-qa)

---

## 1. Languages, Frameworks & Critical "Why" Matrix

| Layer | Language / Technology | Exact Role in LabGuard+ | Critical Reason It Was Chosen |
| :--- | :--- | :--- | :--- |
| **Primary Pi Server** | **Python 3** + **Flask** (`>=3.1`) | Serves all 6 HTML templates, static assets, REST APIs, and sessions (`app.py`). | Pre-installed on every Raspberry Pi OS; tiny RAM footprint (~35–45 MB vs ~200 MB+ for Node/React SSR), leaving RAM for Chromium on **1 GB Raspberry Pi 2/3**. |
| **Real-Time Sync** | **`flask-sock`** (WebSockets) | Pushes instant checkout, return, safety LED, account, and GPIO updates over `/ws/*`. | Pure-Python `simple-websocket` (zero C compilation on ARMv7); replaces wasteful 1-second HTTP polling while keeping a fallback poll if WS drops. |
| **Database** | **SQLite 3** (WAL Mode) | Single-file ACID database (`labguard.db`) storing equipment, accounts, sessions, loans, and GPIO config. | Zero separate DB daemon RAM overhead; Write-Ahead Logging (`PRAGMA journal_mode=WAL`) handles concurrent reads/writes and lowers SD-card corruption risk on sudden Pi power loss. |
| **Hardware GPIO** | **Python `gpiozero`** + `RPi.GPIO` / `rpi-lgpio` / `lgpio` | Drives 12 locker lock pins (`HIGH`/`LOW`), 3 safety LEDs, and buzzer (`hardware/gpio_manager.py`). | Automatically abstracts Pi 2/3 (`RPi.GPIO` / `rpi-lgpio`) and Pi 4/5 (`lgpio`) behind one API and falls back to software simulation on Mac/Windows/Linux PCs. |
| **QR Generation** | **Python `qrcode[pil]`** + **Pillow** | Generates Base64 PNG QR codes in memory pointing to the Pi's LAN IP. | Works 100% offline with zero external QR APIs; fast even on Pi 2's quad-core 900 MHz ARMv7 CPU. |
| **Frontend Markup** | **HTML5** (Jinja/static templates) | 6 purpose-built pages: Kiosk, Register, Checkout, Return, Student Account, Admin. | Zero heavy client-side React hydration overhead on Pi 2/3 Chromium; instant paint at `800×480`. |
| **Styling** | **CSS3** via **Tailwind CSS v4 CLI** | Pre-compiled into a single minified offline stylesheet (`public/css/labguard.css`, ~60 KB). | Eliminates Play CDN JavaScript compilation lag (~1–2s freeze on Pi 2/3) and guarantees **100% offline styling** with no internet. |
| **Client Logic** | **Vanilla ES6+ JavaScript** | Virtual QWERTY keyboard, privacy masking, `<canvas>` ID compression, 40-pin GPIO editor, CSV export. | Zero framework bundle bloat; runs natively in Chromium & smartphone browsers with predictable memory usage. |
| **Dev Parity Server** | **TypeScript** + **Node.js** + **Express** + **`ws`** | Optional local dev server (`server.ts`) mirroring `app.py` endpoints + `npm run build:css`. | Keeps compatibility with web dev workflows and provides the Tailwind CSS v4 build toolchain. |
| **Pi Automation** | **Bash** + **`systemd`** + **Avahi mDNS** | Auto-installer (`setup_raspberry_pi.sh`), background daemon (`labguard.service`), kiosk launcher. | Turns a fresh Raspberry Pi OS flash into a self-healing fullscreen appliance that auto-starts on boot and advertises `labguard.local`. |

---

## 2. Repository File-by-File Map

<details>
<summary><strong>Click to expand: Complete file map (production runtime vs. hardware vs. templates vs. tooling)</strong></summary>

```text
LabGuard/
├── app.py                          # Primary Raspberry Pi Flask + SQLite3 + WebSocket server
├── hardware/
│   ├── gpio_manager.py             # Thread-safe 12-locker + 3-LED + buzzer GPIO controller
│   └── led_controller.py           # Backward-compatible SafetyLEDController wrapper
├── templates/
│   ├── kiosk.html                  # Surface 1: 7" 800×480 Touchscreen Kiosk UI
│   ├── student_register.html       # Surface 2: Mobile registration + camera School ID upload
│   ├── student_form.html           # Surface 3: Verified QR Checkout + embedded item instructions
│   ├── student_return.html         # Surface 4: Second-verification ownership-checked return
│   ├── student_account.html        # Surface 5: Student profile, active loans, history & password
│   └── admin.html                  # Surface 6: Admin logs, ID approval, inventory & 12-pin GPIO console
├── public/
│   ├── css/labguard.css            # Pre-compiled offline Tailwind CSS + cGradying watermark/badges
│   └── images/
│       ├── au_seal.jpg             # Institutional seal asset
│       └── equipment/LG-EQ-*.svg   # 11 offline vector apparatus illustrations
├── src/
│   ├── styles/templates.css        # Tailwind v4 CSS input + watermark/badge rules
│   ├── types.ts                    # Shared TypeScript interfaces
│   └── data/                       # Seed catalog & SVG source map (for Node parity)
├── server.ts                       # Optional Node.js/Express parity server
├── setup_raspberry_pi.sh           # Automated Pi 2/3/4/5 installer (Bullseye/Bookworm/Trixie)
├── uninstall_raspberry_pi.sh       # Clean Pi uninstaller (preserves DB unless --purge-data)
├── run_local.sh / run_local.bat    # One-click local macOS/Linux/Windows Python runners
├── requirements.txt                # Python dependencies (Flask, flask-sock, qrcode[pil])
├── specs/                          # Spec-Driven Development specifications (SPEC-01..05)
└── LICENSE                         # Private Contract License (All Rights Reserved — cGradying)
```

</details>

---

## 3. Backend Server (`app.py`) — Function-by-Function Reference

`app.py` is the authoritative server on Raspberry Pi. Click any subsystem below to inspect its exact functions:

<details>
<summary><strong>3.1 Configuration, Cryptography & Secure Photo Storage</strong></summary>

| Function | What It Does | Critical Engineering Detail |
| :--- | :--- | :--- |
| `get_server_port()`, `get_db_path()`, `get_data_dir()`, `get_id_photos_dir()` | Reads runtime paths/ports from environment variables (`PORT`, `LABGUARD_DB_PATH`, `LABGUARD_DATA_DIR`). | Separates mutable data (`/var/lib/labguard/`) from application code (`/opt/labguard/`) so `git pull` / re-install never wipes student records or ID photos. |
| `hash_password(password)` | Generates a 16-byte cryptographic random salt and hashes with **PBKDF2-HMAC-SHA256 (120,000 iterations)**. | Stores `pbkdf2_sha256$120000$<salt>$<hex>`; uses stdlib `hashlib` so zero fragile C packages (`bcrypt`/`argon2`) need compiling on ARMv7 Pi 2. |
| `verify_password(password, stored_hash)` | Re-derives PBKDF2 hash and compares via `hmac.compare_digest()`. | Constant-time comparison prevents timing side-channel leaks. |
| `_save_id_photo_from_data_url(data_url, lrn)` | Validates MIME prefix (`jpeg`/`png`/`webp`/`svg+xml`), decodes Base64, enforces a **4 MB hard cap**, and writes a sanitized filename (`<LRN>_<rand>.<ext>`). | Rejects oversized payloads before writing to SD card; ignores client-provided filenames entirely. |
| `_resolve_safe_photo_path(filename)` | Resolves filename inside `id_photos/` using `os.path.realpath()` and verifies prefix containment. | Blocks `../` directory traversal attacks completely. |

</details>

<details>
<summary><strong>3.2 Automatic LAN IP Detection & QR Generation</strong></summary>

| Function | What It Does | Critical Engineering Detail |
| :--- | :--- | :--- |
| `detect_lan_ip()` / `_is_usable_lan_ip(ip)` | Opens a non-sending UDP socket to discover the Pi's active Wi-Fi/Ethernet IPv4 address (filtering out loopback `127.x` and link-local `169.254.x`). | Solves the classic kiosk bug: Chromium on the Pi loads `localhost:5000`, which would generate broken `localhost` QR codes for phones unless substituted with the Pi's LAN IP. |
| `resolve_public_base_url(req)` | Checks `APP_URL` / `LABGUARD_PUBLIC_URL` first; otherwise replaces loopback host with `detect_lan_ip()` while keeping LAN IP or `.local` mDNS hostnames intact. | Lets schools pin `http://labguard.local:5000` or `http://10.42.0.1:5000` (hotspot) via `/etc/default/labguard`. |
| `make_qr_data_url(url_text)` | Renders an Arellano Royal Blue (`#003087`) PNG QR code into an in-memory `BytesIO` buffer and Base64-encodes it. | Zero temporary PNG files written to the SD card per checkout. |

</details>

<details>
<summary><strong>3.3 SQLite Database Initialization, Auto-Migration & Real-Time WebSockets</strong></summary>

| Function | What It Does | Critical Engineering Detail |
| :--- | :--- | :--- |
| `get_db()` | Opens SQLite with `timeout=15`, `sqlite3.Row` dict access, `PRAGMA journal_mode=WAL`, and `PRAGMA synchronous=NORMAL`. | WAL lets concurrent kiosk/phone/admin reads proceed without blocking writes; `timeout=15` absorbs brief SD-card write spikes on Pi 2/3. |
| `init_db(force_reset=False)` | Creates all 9 tables, runs idempotent `PRAGMA table_info` + `ALTER TABLE` schema migrations for older DBs, seeds 11 items + 4 demo students + 4 sample transactions, loads saved `gpio_config`, and syncs physical LEDs on boot. | Upgrading an existing Pi never breaks old databases; `POST /api/reset` preserves `admin_sessions` and `gpio_config` so resetting demo logs doesn't log out the admin or erase wiring! |
| `broadcast_global_update()`, `broadcast_checkout_update()`, `broadcast_return_update()` | Thread-safe (`threading.Lock`) fan-out over `/ws/kiosk`, `/ws/hardware`, `/ws/checkout/<token>`, and `/ws/return/<token>`. | Automatically prunes broken/closed sockets so disconnected phones never leak memory on 1 GB Pis. |

</details>

<details>
<summary><strong>3.4 Authentication, Registration & Admin Approval Routes</strong></summary>

| Function & Route | Purpose | Key Rules Enforced |
| :--- | :--- | :--- |
| `extract_bearer_token()`, `get_authenticated_admin()`, `require_admin_auth()`, `get_authenticated_student()` | Central auth guards parsing `Authorization: Bearer <token>` (plus `?token=` strictly for Admin ID-photo `<img>` loads) and validating expiry in SQLite. | Every `/api/admin/*` route, `/api/reset`, and `/api/kiosk/return` fails closed with `401`. |
| `api_student_register()` (`POST /api/students/register`) | Registers a student with personal info, hashed password, and School ID photo as `pending`. | Allows a previously `rejected` student to re-submit with the same LRN/email; blocks active duplicates with `409`; broadcasts `accounts_updated`. |
| `api_student_status()` (`GET /api/students/status`) | Returns `{ found, status, rejection_reason, student_id_lrn }`. | Deliberately omits full name and email so strangers cannot enumerate student PII. |
| `api_student_login()` (`POST /api/students/login`) | Authenticates by LRN or email + password. | Issues 7-day `STU-*` token **only** when `status == 'approved'`; returns `403` with `account_status` for `pending`, `rejected`, or `suspended`. |
| `api_student_me()` / `api_student_change_password()` / `api_student_logout()` | Powers `/student/account` (profile, active loans with instructions, history, password rotation, session revocation). | Backfills item instructions from current catalog if older seeded records lacked them. |
| `api_admin_list_students()`, `api_admin_student_id_photo()`, `api_admin_approve_student()`, `api_admin_reject_student()`, `api_admin_suspend_student()`, `api_admin_delete_student()` | Admin ID verification queue & lifecycle controls. | Rejecting or suspending immediately deletes all `student_sessions` rows for that student, instantly locking them out. |

</details>

<details>
<summary><strong>3.5 Verified Borrow Checkout, Second-Verification Return & Hardware Routes</strong></summary>

| Function & Route | Purpose | Key Rules Enforced |
| :--- | :--- | :--- |
| `api_create_checkout_session()` (`POST /api/kiosk/checkout-session`) | Validates stock & `safety_status != 'UNSAFE'`, creates 15-minute `CHK-*` session + LAN QR. | Rejects checkout with `403` whenever Station LED is `RED (UNSAFE)`. |
| `api_complete_checkout_session()` (`POST /api/kiosk/checkout-session/<token>/complete`) | Completes verified borrow checkout. | **Requires approved Student Bearer token**; ignores spoofed name/LRN/email from body; snapshots `usage_instructions` + `prerequisites` into `items_json`; deducts stock; upgrades `SAFE → CAUTION` if borrowing caution apparatus; calls `gpio_manager.unlock_for_compartments()`; broadcasts `checkout_completed`. |
| `api_create_return_session()` (`POST /api/kiosk/return-session`) | Creates 10-minute `RET-*` Return Verification QR with server-masked borrower preview (`mask_student_name`, `mask_student_id`). | Prevents borrower PII leak before authentication. |
| `api_complete_return_session()` (`POST /api/kiosk/return-session/<token>/complete`) | Completes verified return (both QR `RET-*` and `DIRECT` from `/student/account`). | **Strict ownership check (`is_transaction_owner`)**: returns `403 { ownership_mismatch: true }` if logged-in student is not the borrower! Executes `_execute_transaction_return()`, restores stock (unless `Missing`), escalates LED to `CAUTION` on `Damaged`/`Missing`, pulses locker unlock, and broadcasts `return_completed`. |
| `api_return_equipment()` (`POST /api/kiosk/return`) | Custodian override return from `/admin`. | Locked behind `@require_admin_auth()`; stamps `returned_verified_by = "Admin: <name>"`. |
| `api_admin_get_gpio_config()`, `api_admin_update_gpio_config()`, `api_admin_reset_gpio_config()`, `api_admin_gpio_test_locker()`, `api_admin_gpio_test_led()`, `api_admin_gpio_unlock_all()`, `api_admin_gpio_lock_all()` | Live technical GPIO settings & diagnostic endpoints. | Validates zero duplicate pins (`400`), saves JSON into SQLite `gpio_config`, live-reloads hardware without restarting server, broadcasts `gpio_updated`. |

</details>

---

## 4. Hardware GPIO Engine (`hardware/gpio_manager.py`) — Function-by-Function Reference

<details>
<summary><strong>Click to expand: 12-Locker + LED + Buzzer GPIO Controller architecture & methods</strong></summary>

`hardware/gpio_manager.py` isolates all Raspberry Pi electrical logic from Flask HTTP routes.

| Symbol / Method | What It Does | Critical Hardware Detail |
| :--- | :--- | :--- |
| `BCM_TO_PHYSICAL` & `BUS_WARNINGS` | Maps BCM `2..27` to 40-pin J8 physical pins and tags `I2C1` (`2,3`), `SPI0` (`7–11`), `UART` (`14,15`), `PWM0` (`18`). | Default 16-pin layout avoids ALL reserved bus pins so SPI touchscreens, I2C sensors, and UART console never collide with lockers. |
| `get_default_gpio_config()` | Produces the 12 Active-LOW locker defaults (`BCM 5,6,13,19,26,12,16,20,21,24,25,4`) + 3 Active-HIGH LEDs (`17,27,22`) + Buzzer (`23`). | Active-LOW default matches standard 5V opto-isolated relay boards (`LOW = Relay ON / Solenoid UNLOCKED`, `HIGH = LOCKED`). |
| `validate_gpio_config(cfg)` | Validates mode, pulse limits (`0.5–60s`), BCM pin range (`2–27`, forbidding EEPROM `0,1`), and **checks every enabled channel for duplicate BCM pins**. | Prevents electrical shorting / driver contention by refusing duplicate enabled pins with an error naming both channels. |
| `_logical_to_electrical()` / `_electrical_to_logical()` | Translates logical `UNLOCKED/LOCKED` ↔ raw electrical `HIGH (3.3V) / LOW (0V)` according to `active_high`. | Ensures Admin diagnostics show exact voltage levels regardless of relay vs. MOSFET wiring. |
| `GPIOManager._bind_devices_locked()` & `apply_config()` | Under a re-entrant lock (`threading.RLock`), cancels active timers, closes old `gpiozero.DigitalOutputDevice` handles, binds new pins, initializes all lockers to **LOCKED**, and restores the active safety LED. | Enables live pin remapping from `/admin` with **zero server restart or reboot**. Falls back to `simulation` cleanly on non-Pi hosts. |
| `control_locker(locker_id, action, duration_seconds, source)` | Executes `pulse`, `unlock`, `lock`, `high`, or `low` on any of Lockers 1–12 and appends to the 50-event diagnostic ring buffer. | `pulse` spawns a token-guarded daemon `threading.Timer` calling `_auto_relock_locker()` so 12V solenoid coils are **never left energized indefinitely** (preventing coil burnout). Re-pulsing cancels any stale timer cleanly. |
| `unlock_for_compartments(compartments, source, trigger_type)` | Matches borrowed/returned items' `storage_compartment` strings (case-insensitive, deduplicated) to enabled lockers and pulses them if auto-unlock is enabled. | Lets a multi-item borrow across 2 shelves unlock both target lockers in parallel while leaving all other lockers sealed. |
| `set_safety_level()`, `control_led_channel()`, `beep()` | Drives Green/Yellow/Red LEDs, runs 1s diagnostic LED tests (auto-restoring safety state via `_auto_restore_led()`), and plays non-blocking buzzer chirps on background threads. | Non-blocking buzzer thread prevents HTTP requests from stalling during multi-beep alerts. |
| `unlock_all_lockers()`, `lock_all_lockers()`, `cleanup()` | Master emergency unlock / force relock and `atexit` safe shutdown releasing all GPIO pins in locked/off state. | Guarantees pins don't stay energized if the service stops cleanly. |

</details>

---

## 5. SQLite3 Database Schema (`labguard.db` — All 9 Tables)

<details>
<summary><strong>Click to expand: Exact table breakdown and relationships</strong></summary>

| Table | Primary Key | What It Stores | Key Integrity / Persistence Notes |
| :--- | :--- | :--- | :--- |
| **`equipment`** | `id` (AUTOINCREMENT) | Lab apparatus catalog (`qr_code`, `name`, `category`, `storage_compartment`, `total_qty`, `available_qty`, `condition`, `safety_level`, `prerequisites_json`, `usage_instructions_json`). | Stores both **Proper / General Use Instructions** and **Safety Precautions** as JSON arrays editable via Admin. |
| **`student_accounts`** | `id` (AUTOINCREMENT) | Registered students (`student_id_lrn` UNIQUE, `full_name`, `grade_section`, `school_email` UNIQUE, `password_hash`, `id_photo_filename`, `status`, `rejection_reason`, `reviewed_by`, `reviewed_at`). | Enforces unique LRN & email; `status` gates all borrow/return access (`pending` / `approved` / `rejected` / `suspended`). |
| **`student_sessions`** | `token` (`STU-*`) | Active student login sessions (`student_id`, `created_at`, `expires_at` = 7 days). | Immediately deleted for a student whenever Admin rejects or suspends their account. |
| **`admin_sessions`** | `token` (`ADM-*`) | Active Admin Console sessions (`email`, `name`, `created_at`, `expires_at` = 24 hours). | Preserved across `POST /api/reset` so Admin isn't kicked out when resetting demo data. |
| **`checkout_sessions`** | `session_token` (`CHK-*`) | Short-lived (15 min) Kiosk → Phone borrow QR sessions (`basket_json`, `qr_data_url`, `mobile_url`, `status`, `completed_transaction_json`). | Prevents double-deduction via idempotent completion check. |
| **`return_sessions`** | `session_token` (`RET-*`) | Short-lived (10 min) Kiosk → Phone second-verification return sessions (`transaction_id`, `qr_data_url`, `mobile_url`, `status`, `completed_transaction_json`). | Links a specific active loan to a phone login & ownership check. |
| **`student_transactions`** | `id` (AUTOINCREMENT) | Immutable borrow/return accountability log (`transaction_code`, `student_account_id`, student details, `items_json` with snapshotted instructions, `time_in`, `expected_return`, `time_out`, `return_condition`, `returned_verified_by`, `unlocked_lockers_json`, `status`). | Snapshots item instructions at checkout time so students always keep the exact guide for borrowed items even if catalog changes later. |
| **`safety_status`** | `id = 1` (singleton) | Current Lab LED state (`SAFE` / `CAUTION` / `UNSAFE`, `headline`, `message`, `updated_by`, `updated_at`). | Read on boot to immediately synchronize physical Raspberry Pi LEDs. |
| **`gpio_config`** | `id = 1` (singleton) | Serialized JSON configuration of all 12 lockers + 3 LEDs + buzzer (`config_json`, `updated_at`, `updated_by`). | Persists custom Admin pin mappings across reboots and `POST /api/reset`. |

</details>

---

## 6. Frontend Interfaces (`templates/*.html`) — JS Function Reference

All 6 interfaces use **zero external CDNs** (loading local `/css/labguard.css` + `/images/*`) and **Vanilla ES6+ JavaScript** for instant responsiveness on Raspberry Pi 2/3.

<details>
<summary><strong>6.1 Touchscreen Kiosk (`templates/kiosk.html`)</strong></summary>

- **Viewport & Kiosk Detection**: `detectKioskMode()` checks `?kiosk=1`, fullscreen media query, or `<= 900×560`; `checkNativeRpiDimensions()` locks `#kiosk-lcd-viewport` to `800×480` (`h-screen w-screen overflow-hidden`) and hides `#simulator-toolbar` & `#proto-route-helper` on real Pi kiosks.
- **Idle Security Timer**: `startIdleTracker()` & `resetIdleTimer()` auto-return to Screen 0 (`goToAttractScreen()`) after 45s of touch/pointer inactivity, closing open modals, virtual keyboard, and search filters.
- **Touchscreen Search & Basket**: `toggleTouchKeyboard()`, `pressKey()`, `pressBackspace()`, `syncSearchUI()` power the on-screen QWERTY drawer; `setItemQty()`, `animateBasketAddition()`, `renderBasket()`, and `toggleBasketPopup()` manage the basket without needing a physical keyboard.
- **QR Checkout & Auto-Close Sync**: `createCheckoutQrSession()` opens the QR modal; `watchCheckoutSession()` subscribes to `/ws/checkout/<token>` (plus 3s polling fallback) to auto-close the modal and trigger `showCheckoutConfirmedToast()` with unlocked locker compartments!
- **Privacy Masking & Verified Return QR**: `maskStudentName()`, `maskStudentId()`, `revealStudentName()` / `hideStudentName()` implement press-and-hold Eye reveal; `openReturnQrSession()` & `watchReturnSession()` generate `RET-*` verification QRs and auto-close on `/ws/return/<token>` completion.
- **Registration QR & Global WS**: `openRegisterQrModal()` displays `/student/register` QR; `connectGlobalKioskSocket()` syncs live inventory & LED status with a 10s fallback poll (`startGlobalKioskFallbackPoll()`).

</details>

<details>
<summary><strong>6.2 Student Registration (`templates/student_register.html`)</strong></summary>

- **Client-Side ID Photo Compression**: `compressImageFile(file)` draws camera/gallery images onto an offscreen HTML5 `<canvas>`, scales them down to max `1200px` wide, and exports JPEG (`quality = 0.82`) — shrinking a 6 MB smartphone photo to ~150 KB before sending over lab Wi-Fi to a Raspberry Pi 2/3!
- **Preview & Submission**: `handleIdPhotoSelect()`, `setIdPhotoPreview()`, and `submitStudentRegistration()` validate matching passwords and upload to `POST /api/students/register`.
- **Approval Status Lookup**: `checkApprovalStatus()` queries `GET /api/students/status` and renders color-coded `pending` / `approved` / `rejected` (with `focusResubmitFromStatus()` shortcut) / `suspended` cards.

</details>

<details>
<summary><strong>6.3 Verified Student Borrow Checkout (`templates/student_form.html`)</strong></summary>

- **Auth Gate**: `initCheckoutPage()` runs `verifyStudentToken()` (`GET /api/students/me`) + `fetchCheckoutSessionDetails()` (`GET /api/kiosk/checkout-session/<token>`). Unauthenticated phones see `#student-login-gate` (`handleStudentGateLogin()` + `showLoginStatusError()`).
- **Custom Loan Scheduling**: `initReturnDateTime()` & `handleCustomDateTimeChange()` calculate exact hour/day loan durations for same-day or multi-day capstone loans and reject past timestamps.
- **Verified Submit & Embedded Post-Checkout Instructions**: `submitStudentCheckoutForm()` posts with `Authorization: Bearer <token>`; `showCompletedReceipt()` calls `renderReceiptUnlockedLockers()` (showing which locker opened!) AND `renderReceiptInstructions()` (embedding expandable **Proper / General Use Steps** + **Safety Precautions Before Use** for every borrowed item right on the Digital Pass!).

</details>

<details>
<summary><strong>6.4 Second-Verification Return (`templates/student_return.html`)</strong></summary>

- **State Machine Routing**: `initReturnPage()` & `routeByState()` inspect both the `RET-*` session and the student's Bearer token to route cleanly to one of 4 states:
  1. `showLoginGateView()` (not signed in yet)
  2. `showOwnershipMismatchView()` (signed in as wrong student → bold red block + `handleSwitchAccount()`)
  3. `showVerifiedOwnerForm()` (verified original borrower → `selectVerifiedReturnCondition()` Good/Damaged/Missing + `submitVerifiedReturn()`)
  4. `showCompletedReturnReceipt()` (confirmed receipt + `renderReturnUnlockedLockers()`).

</details>

<details>
<summary><strong>6.5 Student Account Portal (`templates/student_account.html`)</strong></summary>

- **Account Management**: `handleAccountLogin()`, `refreshAccountData()`, `renderActiveLoans()` (with expandable embedded usage & safety instructions per item), `renderPastLoans()`, and `handleChangePassword()`.
- **Direct Verified Return**: `openAccountReturnModal()`, `selectAccountReturnCondition()`, and `submitAccountReturn()` let a logged-in student return their own active loans directly via `POST /api/kiosk/return-session/DIRECT/complete`.

</details>

<details>
<summary><strong>6.6 PC Admin Console (`templates/admin.html`)</strong></summary>

- **Authenticated API Wrapper**: `handleAdminLogin()`, `verifyExistingAdminSession()`, and `adminFetch()` automatically attach the Admin Bearer token and force re-login on any `401`.
- **Student ID Approval Queue**: `fetchAdminStudents()`, `renderStudentsTable()`, `openIdPhotoModal()`, `toggleIdPhotoZoom()` (150% inspection zoom), `approveStudentAccount()`, `submitRejectStudent()`, `suspendStudentAccount()`, and `deleteStudentAccount()`.
- **Equipment & Instructions Editor**: `submitNewEquipment()`, `openEditInstructionsModal()`, `submitEditInstructions()`, `adjustStock()`, `deleteEquipment()`, and `handlePcImageUpload()`.
- **Technical 12-Pin GPIO Console**: `fetchGpioConfig()`, `computeDraftPinAssignments()` (live client-side conflict detection before saving), `renderGpioHeaderDiagram()` (interactive 40-pin J8 map), `renderGpioLockersTable()`, `renderGpioLedsTable()`, `renderGpioDiagnosticLog()`, `saveAndApplyGpioConfig()`, `testLockerPin()` (`pulse`/`high`/`low`), `testLedChannel()`, `emergencyUnlockAllLockers()`, `forceRelockAllLockers()`, `exportGpioConfigJson()`, and `importGpioConfigJson()`.
- **Institutional Reporting**: `exportLogsCsv()` builds a UTF-8 BOM (`\uFEFF`) Excel-compatible 17-column accountability CSV report with institutional & `cGradying` license headers.

</details>

---

## 7. Security Architecture & Critical Threat Model

<details>
<summary><strong>Click to expand: What LabGuard+ protects — and honest security boundaries to understand</strong></summary>

### Implemented Security Controls
1. **Salted Password Hashing**: Every student password uses PBKDF2-HMAC-SHA256 (`120,000` iterations, unique 16-byte random salt per user) and constant-time verification (`hmac.compare_digest`). Plaintext passwords are never stored or returned in JSON.
2. **Human-in-the-Loop Identity Verification**: Self-registration alone grants zero borrowing privileges; a Lab Admin must visually inspect the uploaded AU School ID photo before setting `status = 'approved'`.
3. **Server-Side Anti-Spoofing**: Checkout completion ignores identity fields in the JSON payload and binds transactions exclusively to the server-verified `student_sessions` token.
4. **Return Ownership Isolation**: Unauthenticated kiosk returns are disabled; returning an item requires an approved student session matching `student_account_id` / `student_id_lrn` (other students receive `403 ownership_mismatch`), while Lab Admins retain an Admin-authenticated override.
5. **Protected PII & ID Photos**: Uploaded School ID photos live outside `public/` (in `/var/lib/labguard/id_photos`, `chmod 750`), cannot be fetched without a valid Admin token, and are protected against path traversal (`_resolve_safe_photo_path`).
6. **Hardware Safety Guards**: Solenoid lock pulses enforce bounded durations (`0.5–60s`) with automatic relock timers, duplicate GPIO pin assignments are blocked both client- and server-side, and `/etc/default/labguard` is restricted to `chmod 640`.

### Honest Security Boundaries (Be Transparent During Defense!)
- **Local LAN HTTP vs. HTTPS**: Because LabGuard+ runs offline on a private local lab Wi-Fi/hotspot without public domain certificates, traffic runs over local HTTP. **Mitigation**: Deploy strictly on an isolated laboratory Wi-Fi router or the Pi's own WPA2 hotspot — never expose port `5000` directly to the public internet without a reverse proxy (Caddy/Nginx + TLS).
- **Single Admin Account**: Admin credentials are stored as environment variables in `/etc/default/labguard` (`chmod 640`). Always change the default demo password (`au-jrc-2026`) before school deployment.
- **Physical Access to the Raspberry Pi**: Anyone with physical access to remove the Pi's microSD card can read `labguard.db` or `/etc/default/labguard`. Mount the Raspberry Pi and relay board inside a **locked service enclosure** behind the cabinet.
- **No Automated Login Rate-Limiting**: Designed for trusted classroom LANs; if deployed on an open campus network, adding per-IP rate limiting in front of `/api/*/login` is recommended.

</details>

---

## 8. Deployment, Offline CSS Pipeline & Node.js Parity

<details>
<summary><strong>Click to expand: How installation, offline CSS compilation, and Node parity work</strong></summary>

1. **Offline CSS Build (`npm run build:css`)**:
   - Tailwind CSS v4 CLI (`@tailwindcss/cli`) scans `templates/*.html` via `@source "../../templates"` in `src/styles/templates.css` and compiles only the exact utility classes used — plus the inline-SVG `cGradying` watermark and `#0B1120`/`#10B981` badge rules — into one minified `public/css/labguard.css` file.
   - The Raspberry Pi **never needs Node.js or `npm`** at runtime; it simply serves the committed `public/css/labguard.css` directly from Flask.
2. **Raspberry Pi Automated Installer (`setup_raspberry_pi.sh`)**:
   - Installs OS packages (`python3-venv`, `python3-gpiozero`, `python3-rpi.gpio`/`python3-rpi-lgpio`/`python3-lgpio`, `avahi-daemon`, `chromium`/`chromium-browser`).
   - Uses `python3 -m venv --system-site-packages /opt/labguard/.venv` so pip obeys Debian Bookworm/Trixie PEP 668 while still inheriting pre-compiled ARM system packages (`gpiozero`, `lgpio`, `PIL`).
   - Registers `labguard.service` (`Restart=always`) and configures XDG kiosk autostart (`labguard_kiosk.sh`) with automatic **low-RAM Chromium flags** when total RAM `<= 1100 MB` (Pi 2B / Pi 3B / 3B+).
3. **Node.js / TypeScript Parity (`server.ts`)**:
   - Mirrors the entire REST + WebSocket API contract in TypeScript/Express (`npm run dev`) with an in-memory store and simulated 12-locker GPIO controller for rapid web/UI iteration on laptops. **Production Raspberry Pi deployments always use `app.py`** for SQLite persistence, low RAM usage, and real GPIO.

</details>

---

## 9. Critical Engineering Trade-Offs & Defense Q&A

<details>
<summary><strong>Click to expand: Common panel / client questions & concise engineering answers</strong></summary>

1. **Q: Why use Python Flask + Vanilla JS instead of React/Next.js + PostgreSQL?**
   - **A:** Raspberry Pi 2 Model B and Pi 3 Model B/B+ only have **1 GB of RAM**, and Chromium fullscreen kiosk already consumes ~350–500 MB. Running PostgreSQL + Node/Next.js + React hydration on 1 GB RAM causes swap thrashing and OOM crashes. Flask + SQLite3 WAL uses ~40 MB RAM, boots in ~2 seconds, talks natively to Raspberry Pi GPIO, and Vanilla HTML/JS + pre-compiled CSS renders instantly offline.
2. **Q: Why decouple typing onto the student's smartphone via QR code instead of doing everything on the 7" kiosk?**
   - **A:** Three critical reasons: (1) Students can take a real photo of their School ID using their phone camera, (2) entering passwords and account credentials on a shared public touchscreen leaks passwords to onlookers, and (3) a 7" `800×480` screen stays fast and uncluttered while smartphones handle personal form entry and keep the **embedded usage & safety instructions** portable right at the lab bench!
3. **Q: Why do all 12 locker pins default to Active-LOW with a 5-second timed pulse?**
   - **A:** Standard 5V opto-isolated relay boards use Active-LOW optocouplers (`LOW` energizes the relay coil). More importantly, 12V DC cabinet solenoid locks are intermittent-duty coils — leaving one energized continuously will overheat and burn out the coil, so `GPIOManager` enforces a timed pulse (`5.0s` default) with a server-side auto-relock timer.
4. **Q: Why not hardcode the 12 GPIO pins in Python?**
   - **A:** Real student-built cabinets frequently rewire channels or swap Active-LOW vs. Active-HIGH relay modules during assembly. Storing `gpio_config` in SQLite with live `apply_config()` reload, duplicate-pin conflict checks, and per-pin `Pulse`/`HIGH`/`LOW` tests eliminates risky SSH code edits in the lab.
5. **Q: What happens if a WebSocket disconnects on weak classroom Wi-Fi?**
   - **A:** Every WebSocket client (`kiosk.html`, `admin.html`) automatically schedules reconnection **and** falls back to lightweight HTTP polling (`3s` during active QR modals, `10s` idle) so the station never freezes even on noisy Wi-Fi.

</details>

---

<div align="center">

[![Author: cGradying](https://img.shields.io/badge/cGradying-AUTHOR-10B981?style=for-the-badge&labelColor=0B1120)](https://github.com/cGradying)
[![License: Private Contract](https://img.shields.io/badge/License-Private%20Contract-10B981?style=for-the-badge&labelColor=0B1120)](../LICENSE)

</div>
