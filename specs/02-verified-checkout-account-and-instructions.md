# SPEC-02: Verified Student Checkout, Account Portal & Post-Checkout Embedded Item Instructions

- **Spec ID:** `SPEC-02`
- **Status:** `DRAFT` *(begins after SPEC-01 is merged)*
- **Target Branch:** `spec/02-verified-checkout-instructions`
- **Dependencies:** `SPEC-01`

---

## 1. Problem & Goal

1. **Authenticated Borrow Checkout**: After scanning the Checkout QR code from the kiosk, students must **log in with their approved LabGuard+ account** (not type arbitrary names/LRNs). Their verified identity is permanently bound to the borrow transaction (`student_account_id`).
2. **Student Account Management (`/student/account`)**: Students get a mobile account portal where they manage their profile, view active borrowed equipment, review borrow history, change their password, and sign out.
3. **Embedded Proper-Use & Safety Instruction List (Post-Checkout)**:
   - Every laboratory equipment item includes a structured **Usage & Safety Instruction List**:
     - **`usage_instructions`** (array of clear general / proper-use steps — since apparatus can serve multiple lab activities)
     - **`safety_precautions`** (`prerequisites`, array of mandatory before-use safety checks & PPE precautions)
   - Lab Admins can **view and edit** both lists per equipment item in Admin Inventory.
   - **Immediately after a student completes QR checkout & confirmation**, the confirmed Digital Pass embeds a dedicated **"Proper Use & Safety Precautions Guide"** card for EVERY borrowed apparatus in that checkout — AND snapshots those exact instructions inside the transaction record so the student can revisit them anytime from **My Account → Active Borrowed Equipment** while using the apparatus in the lab!

---

## 2. User Flows

### 2.1 Verified Borrow Checkout Flow (`/student/checkout/<token>`)
1. Student selects apparatus on Kiosk → taps **Checkout & Generate QR** → scans QR on phone.
2. Phone opens `/student/checkout/<token>`:
   - **If not logged in**: Displays the **Student Log-In Gate** (Student ID/LRN or Email + Password), plus a direct link to `/student/register` (preserving `?next=/student/checkout/<token>`). Shows clear pending/rejected status errors if account is not approved.
   - **If logged in (approved)**: Displays a green **Verified Student Identity Banner** (Full Name, LRN, Strand, Email, `My Account` button, `Switch Account` button).
3. Student reviews their scanned equipment basket, enters **Subject & Lab Activity**, **Supervising Teacher**, **Custom Return Date & Time**, accepts the **Safety & Accountability Pledge**, and taps **Confirm Verified Checkout**.
4. Backend verifies Student Bearer token + `status == 'approved'`, binds transaction to `student_account_id` using server-side account fields (cannot be spoofed!), snapshots each borrowed item's `usage_instructions` and `safety_precautions`, deducts stock, and broadcasts `checkout_completed` to `/ws/checkout/<token>` & `data_updated` to `/ws/kiosk`.
5. **Confirmed Digital Pass Receipt + Embedded Instructions**:
   - Displays celebratory checkmark, Pass Code (`LG-JRC-XXX`), Due Back date/time, and borrower details.
   - Directly embedded underneath the confirmation summary is the **"Before You Begin — Apparatus Instructions & Safety Precautions"** section listing each borrowed item with:
     - **Proper / General Use Steps** (numbered bullet list)
     - **Safety Precautions Before Use** (highlighted amber/blue warning checklist)
   - Student can expand/collapse each item's guide and jump to **My Account** where those same guides stay pinned to their active loan.

### 2.2 Student Account Portal (`/student/account`)
- Sign In / Sign Out (uses same `localStorage` student session token).
- **Profile Tab / Header**: Verified badge, Full Name, LRN, Strand/Faculty, School Email.
- **Active Borrowed Equipment**: Shows each active loan with due countdown/date, storage compartment, and an expandable **"View Usage Instructions & Safety Precautions"** drawer for every borrowed item!
- **Borrow & Return History**: Past completed loans with timestamps and return conditions.
- **Security**: Change Password form (`POST /api/students/change-password`).

### 2.3 Admin Editable Instructions per Apparatus (`/admin` → Kiosk Lab Items)
- Equipment add & edit modals include multi-line inputs for:
  - **Proper / General Use Instructions** (one step per line → `usage_instructions[]`)
  - **Safety Precautions Before Use** (one precaution per line → `prerequisites[]`)

---

## 3. Data Model Changes

- **`equipment` table** (SQLite auto-migration if column missing):
  - Add `usage_instructions_json TEXT NOT NULL DEFAULT '[]'`
  - Seed rich, accurate, multi-step **Proper / General Use Instructions** + **Safety Precautions Before Use** for all 11 AU-JRC items (`LG-EQ-001` .. `LG-EQ-011`).
- **`student_transactions` table** (auto-migration):
  - Add `student_account_id INTEGER` (FK to `student_accounts.id`)
  - Each item in `items_json` embeds both `usage_instructions: string[]` and `prerequisites: string[]` (safety precautions) at checkout time.

---

## 4. API & Route Contract

- `GET /student/account`, `/student_account.html` → `templates/student_account.html`
- `GET /api/students/me` (expanded) → `{ student, active_transactions, past_transactions }`
- `POST /api/students/change-password` (Student Bearer) → `{ current_password, new_password }` → `200 { success: true }`
- `POST /api/kiosk/checkout-session/<token>/complete`:
  - **Requires** `Authorization: Bearer <student_token>` (`401` if missing, `403` if not approved).
  - Ignores untrusted identity fields in request body; populates student info strictly from authenticated `student_accounts` record.
  - Embeds `usage_instructions` and `prerequisites` (safety precautions) on every item in the returned `transaction.items`.
- `POST /api/admin/equipment` & `PATCH /api/admin/equipment/:id`:
  - Accept `usage_instructions: string[]` in addition to `prerequisites: string[]`.

---

## 5. Files Touched

- `app.py`
- `server.ts`
- `src/types.ts` & `src/data/seedData.ts`
- `templates/student_form.html`
- `templates/student_account.html` *(new)*
- `templates/admin.html` *(add/edit equipment instructions fields)*
- `public/css/labguard.css`

---

## 6. Acceptance Criteria (Must Pass Before Merging to `main`)

- [ ] Unauthenticated `POST /api/kiosk/checkout-session/<token>/complete` returns `401`.
- [ ] Pending/rejected student cannot complete checkout (`403`).
- [ ] Approved student scans QR → logs in on `/student/checkout/<token>` → completes checkout; server records their verified account details (even if forged fields are sent in JSON).
- [ ] Confirmed Digital Pass receipt immediately displays the embedded **Proper / General Use Instructions** and **Safety Precautions Before Use** for every borrowed item.
- [ ] `/student/account` displays the student's active loans with their embedded usage & safety instructions, past history, and working Change Password flow.
- [ ] Admin can add/edit an equipment item's `usage_instructions` and `prerequisites` and see them appear on the next student checkout receipt.
- [ ] Kiosk QR modal still auto-closes via WebSocket when the student completes checkout on their phone.
