# SPEC-03: Second-Verification Authenticated Equipment Return

- **Spec ID:** `SPEC-03`
- **Status:** `DRAFT` *(begins after SPEC-02 is merged)*
- **Target Branch:** `spec/03-verified-equipment-return`
- **Dependencies:** `SPEC-01`, `SPEC-02`

---

## 1. Problem & Goal

Currently, anyone standing in front of the Kiosk touchscreen can tap **Return Equipment** on any active borrow record and mark **someone else's** borrowed equipment as returned.

This spec adds **second-layer account verification for returns**:
1. The Kiosk no longer performs unauthenticated direct returns. Tapping a record on the Kiosk generates a **Return Verification QR Code (`RET-XXXXXXXX`)**.
2. The student scans the QR code on their phone (or initiates return from `/student/account`), **logs in with their approved student account**, and the server strictly enforces **ownership**: **Student B CANNOT return Student A's borrowed equipment** (`403 Forbidden`).
3. Authenticated Lab Admins on `/admin` retain override authority to check in equipment via the Admin Console.

---

## 2. User Flows

### 2.1 Kiosk → Phone Verified Return Flow
1. On Kiosk **Return Equipment** tab, active loans are shown privacy-masked (`O*e ...`, `***********0101`) with the press-and-hold Eye toggle.
2. Student taps **"Verify & Return"** on their loan card → Kiosk calls `POST /api/kiosk/return-session` → opens **Return Verification QR Modal** displaying:
   - Security banner: *"Account Verification Required — Only the original borrower can return this equipment"*
   - Return QR Code (`http://<pi-lan-ip>:5000/student/return/RET-XXXXXXXX`) + clean LAN URL
3. Student scans QR on phone → opens `/student/return/<token>`:
   - **If not logged in**: Shows masked loan summary + **Sign In to Verify Your Account** form.
   - **If logged in as a DIFFERENT student (`is_owner === false`)**: Shows a bold red **"Account Ownership Mismatch"** block (*"This equipment belongs to a different student account. You can only return items checked out under your own account."*) + **"Sign Out & Switch Account"** button. Submit is blocked both in UI and on server (`403`).
   - **If logged in as the BORROWER (`is_owner === true`)**: Shows verified borrower badge, full item & compartment list, Condition selector (**`Good`**, **`Damaged`**, **`Missing`** with yellow CAUTION warning), optional return notes, and **"Confirm Verified Return"** button.
4. On submit (`POST /api/kiosk/return-session/<token>/complete`):
   - Server marks transaction `Returned / Logged Out`, records `returned_verified_by`, restores stock (unless `Missing`), sets `condition = 'Damaged'` if damaged, escalates LED Safety Status to `CAUTION` on Damaged/Missing, updates `return_sessions.status = 'completed'`, and broadcasts `return_completed` on `/ws/return/<token>` + `data_updated` on `/ws/kiosk`.
   - Kiosk Return QR modal **auto-closes** and displays a celebratory **"Verified Return Completed"** banner.
   - Phone displays a **Verified Return Receipt**.

### 2.2 Direct Verified Return from Student Account Portal (`/student/account`)
- Logged-in students can also tap **"Return This Equipment"** directly next to any of their own active loans in `/student/account` (submitting to `POST /api/kiosk/return-session/DIRECT/complete` with `{ transaction_id, return_condition, return_notes }`), using the exact same backend ownership enforcement.

### 2.3 Admin Custodian Override (`/admin`)
- `POST /api/kiosk/return` now requires a valid **Admin Bearer token** (`401` if unauthenticated) so Admin Dashboard **Check In & Log Out** works securely while unauthenticated kiosk scripts cannot bypass verification.

---

## 3. Database & WebSocket Changes

- **`return_sessions` table** (SQLite + Node memory parity):
  - `session_token TEXT PRIMARY KEY` (`RET-XXXXXXXX`)
  - `transaction_id INTEGER NOT NULL`
  - `qr_data_url TEXT NOT NULL`
  - `mobile_url TEXT NOT NULL`
  - `status TEXT NOT NULL` (`pending_verification` | `completed` | `expired`)
  - `created_at TEXT NOT NULL`, `expires_at TEXT NOT NULL` (10 minutes)
  - `completed_transaction_json TEXT`
- **`student_transactions` column** (auto-migration):
  - `returned_verified_by TEXT` (records `"Full Name (LRN)"` or `"Admin: Name"`)
- **WebSocket channel**: `/ws/return/<token>` pushing `{"event": "return_completed", "transaction": ..., "safety_status": ...}`.

---

## 4. API & Route Contract

- `GET /student/return/<token>`, `/student_return.html` → `templates/student_return.html`
- `POST /api/kiosk/return-session` (`{ transaction_id }` or `{ transaction_code }`) → `201 { session }`
- `GET /api/kiosk/return-session/<token>` (optional Student Bearer) → `{ session, transaction_preview, is_owner?, transaction?, safety_status }`
- `POST /api/kiosk/return-session/<token>/complete` (Student Bearer REQUIRED) → `{ return_condition, return_notes, transaction_id? }` → `200 { success, transaction, safety_status }` | `403 { error, ownership_mismatch: true }` | `400` if already returned
- `POST /api/kiosk/return` → **Admin Bearer REQUIRED** (`401` without Admin token)

---

## 5. Files Touched

- `app.py`
- `server.ts`
- `templates/kiosk.html` *(replace instant return modal with Return Verification QR modal + `/ws/return/<token>` listener)*
- `templates/student_return.html` *(new)*
- `templates/student_account.html` *(add direct Return button on student's own active loans)*
- `public/css/labguard.css`

---

## 6. Acceptance Criteria (Must Pass Before Merging to `main`)

- [ ] Unauthenticated `POST /api/kiosk/return` returns `401`.
- [ ] Kiosk Return button opens a Return Verification QR modal (`RET-XXXXXXXX`) with LAN URL (not `localhost`).
- [ ] Student B logged into `/student/return/<token>` for Student A's loan sees the ownership mismatch warning AND direct API submission returns `403 { ownership_mismatch: true }`.
- [ ] Student A logged into `/student/return/<token>` can return as `Good`, `Damaged`, or `Missing`; stock & LED `CAUTION` rules execute properly and `returned_verified_by` is logged.
- [ ] Kiosk Return QR modal auto-closes via `/ws/return/<token>` (or polling fallback) and refreshes active loans.
- [ ] Admin Dashboard Check-In continues working with Admin Bearer authentication.
