# SPEC-01: Student Registration, School ID Photo Upload & Admin Approval

- **Spec ID:** `SPEC-01`
- **Status:** `MERGED`
- **Target Branch:** `spec/01-student-registration-approval`
- **Dependencies:** `main` (commit `a56232d`)

---

## 1. Problem & Goal

Currently, LabGuard+ allows anyone to enter any student name/LRN without verifying identity. This spec introduces a **verified student credential foundation**:

1. Students must **register an account** with their personal details, a password, and a **photo of their official School ID**.
2. New accounts start as **`pending`** and **cannot log in, borrow, or return** until a Laboratory Admin inspects their School ID photo and clicks **Approve**.
3. Admin routes and uploaded School ID photos are protected by **real server-verified Admin authentication** (Bearer session token).

---

## 2. User Flows

### 2.1 Student Registration Flow (`/student/register`)
1. On the Kiosk Welcome screen, a new student taps **"New Student? Register Account / Account QR"** → scans the Registration QR code on their phone (opens `http://<pi-lan-ip>:5000/student/register`).
2. Student fills out:
   - Full Name
   - Student ID / LRN (normalized uppercase, e.g., `AUJRC-2026-0199`)
   - Strand / Faculty (`STEM`, `HUMSS`, `ABM`, `FACULTY`)
   - School Email (`@arellano.edu.ph`)
   - Password + Confirm Password (min 6 characters)
   - **School ID Picture** (phone rear camera capture via `capture="environment"` or gallery upload, client-side `<canvas>` resized to max `1200px` JPEG `0.82` quality with live preview)
3. Student submits → backend validates fields & image, hashes password (PBKDF2-HMAC-SHA256 + random salt), saves photo to `<LABGUARD_DATA_DIR>/id_photos/`, inserts account with `status = 'pending'`, and broadcasts `accounts_updated` over `/ws/kiosk`.
4. Student sees **"Registration Submitted — Pending Laboratory Admin Verification"** + can check their approval status anytime by entering their LRN/email.
5. If an admin previously **rejected** their registration (e.g., blurry ID photo), the student can **re-submit** with the same LRN/email and a clearer ID photo, resetting status back to `pending`.

### 2.2 Admin Login & ID Approval Flow (`/admin`)
1. Lab Admin logs in via `POST /api/admin/login` (credentials from `LABGUARD_ADMIN_EMAIL` / `LABGUARD_ADMIN_PASSWORD`, defaulting to `lara.puertollano@arellano.edu.ph` / `au-jrc-2026`), receiving a session Bearer token stored in `sessionStorage`.
2. Sidebar displays **"Student Accounts"** with an amber live count badge of `pending` applications.
3. Admin filters by `Pending Approval`, `Approved`, `Rejected`, `Suspended`, or `All`, and searches by Name / LRN / Email.
4. Clicking a student's **School ID thumbnail** opens a full-size **ID Verification Lightbox** showing the high-res ID photo side-by-side with their submitted Name, LRN, Strand, and Email, plus direct **Approve** and **Reject (with reason)** buttons.
5. Admin can also **Suspend**, **Re-Approve**, or **Delete** accounts. Rejecting or suspending immediately revokes any active sessions for that student.

---

## 3. Database Schema & Storage

### New Tables (`app.py` SQLite WAL + in-memory parity in `server.ts`)
- **`student_accounts`**:
  - `id INTEGER PRIMARY KEY AUTOINCREMENT`
  - `student_id_lrn TEXT NOT NULL UNIQUE` (uppercase trimmed)
  - `full_name TEXT NOT NULL`
  - `grade_section TEXT NOT NULL` (`STEM` | `HUMSS` | `ABM` | `FACULTY`)
  - `school_email TEXT NOT NULL UNIQUE` (lowercase trimmed)
  - `password_hash TEXT NOT NULL` (`pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`)
  - `id_photo_filename TEXT NOT NULL` (stored in `<LABGUARD_DATA_DIR>/id_photos/`)
  - `status TEXT NOT NULL DEFAULT 'pending'` (`pending` | `approved` | `rejected` | `suspended`)
  - `rejection_reason TEXT NOT NULL DEFAULT ''`
  - `reviewed_by TEXT`
  - `reviewed_at TEXT`
  - `created_at TEXT NOT NULL`
  - `updated_at TEXT NOT NULL`
- **`student_sessions`**: `token TEXT PRIMARY KEY`, `student_id INTEGER NOT NULL`, `created_at TEXT NOT NULL`, `expires_at TEXT NOT NULL` (7 days).
- **`admin_sessions`**: `token TEXT PRIMARY KEY`, `email TEXT NOT NULL`, `name TEXT NOT NULL`, `created_at TEXT NOT NULL`, `expires_at TEXT NOT NULL` (24 hours).

### Seeded Demo Accounts (Inserted only when `student_accounts` is empty)
| LRN | Full Name | Strand | Email | Demo Password | Initial Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `AUJRC-2026-0101` | One Enrique Sebastian G. Abalos | `STEM` | `one.abalos@arellano.edu.ph` | `student123` | `approved` |
| `AUJRC-2026-0102` | Christine S. Contreras | `STEM` | `christine.contreras@arellano.edu.ph` | `student123` | `approved` |
| `AUJRC-2026-0103` | Queen Hannah A. Dones | `HUMSS` | `queenhannah.dones@arellano.edu.ph` | `student123` | `approved` |
| `AUJRC-2026-0105` | Ashlyjicks B. Pangilinan | `STEM` | `ashlyjicks.pangilinan@arellano.edu.ph` | `student123` | `pending` *(with sample SVG School ID)* |

---

## 4. API & Route Contract

### Template Routes
- `GET /student/register`, `/student_register.html` → `templates/student_register.html`

### Public / Student Auth Endpoints
- `GET /api/kiosk/registration-qr` → `{ register_url, account_url, qr_data_url, account_qr_data_url }`
- `POST /api/students/register` → `{ full_name, student_id_lrn, grade_section, school_email, password, id_photo_data_url }` → `201 { success, student }` (`409` if non-rejected duplicate)
- `GET /api/students/status?identifier=<lrn_or_email>` → `{ found, status?, rejection_reason?, student_id_lrn? }` (no sensitive PII leaked)
- `POST /api/students/login` → `{ identifier, password }` → `200 { success, token, student }` if `approved`; `403 { error, account_status, rejection_reason? }` if `pending`/`rejected`/`suspended`; `401` on wrong credentials
- `GET /api/students/me` (Student Bearer) → `{ student }`
- `POST /api/students/logout` (Student Bearer) → `{ success: true }`

### Admin Auth & Approval Endpoints (Protected by Admin Bearer Token)
- `POST /api/admin/login` (`{ email, password }`) → `200 { success, token, admin: { email, name } }` | `401`
- `GET /api/admin/me` & `POST /api/admin/logout`
- All `/api/admin/*` routes + `POST /api/reset` require `Authorization: Bearer <admin_token>` (`401` if missing/expired).
- `GET /api/admin/students` (optional `?status=...`) → `{ students: [...], counts: { total, pending, approved, rejected, suspended } }`
- `GET /api/admin/students/<id>/id-photo` (Admin Bearer header OR `?token=<admin_token>` for `<img>`) → serves image with valid `Content-Type`
- `POST /api/admin/students/<id>/approve`
- `POST /api/admin/students/<id>/reject` (`{ reason }`)
- `POST /api/admin/students/<id>/suspend`
- `DELETE /api/admin/students/<id>`

---

## 5. Files Touched

- `app.py`
- `server.ts`
- `templates/student_register.html` *(new)*
- `templates/kiosk.html` *(add Register/Account QR modal button on Welcome screen)*
- `templates/admin.html` *(real Admin Bearer auth + Student Accounts tab + ID Verification Lightbox)*
- `public/css/labguard.css` *(rebuilt via `npm run build:css`)*

---

## 6. Acceptance Criteria (Must Pass Before Merging to `main`)

- [x] A new student can register at `/student/register` with personal details, password, and uploaded School ID image; image is persisted to `<data_dir>/id_photos/`.
- [x] Attempting to log in while `pending` returns `403` with `account_status: "pending"` and does NOT issue a token.
- [x] Unauthenticated requests to `/api/admin/students` and `/api/admin/students/<id>/id-photo` return `401`.
- [x] Logged-in Admin sees the pending count badge, can open the zoomable School ID Lightbox, and can **Approve** or **Reject** (with reason).
- [x] Rejected student cannot log in (`403` showing rejection reason) and can re-submit registration to return to `pending`.
- [x] Approved student logs in successfully (`200`), receives a Bearer token, and `/api/students/me` returns their verified profile.
- [x] All templates have zero external CDN requests; `npm run build:css`, `npm run lint`, `py_compile`, and automated acceptance tests pass.
