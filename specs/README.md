# LabGuard+ — Spec-Driven Development (SDD) Roadmap

This directory tracks all feature iterations as **discrete, reviewable specifications**.
Each spec is implemented on its own git branch (`spec/0X-...`), verified against its **Acceptance Criteria**, reviewed by the project owner, and merged cleanly into `main` before starting the next spec.

---

## Orchestration Workflow

```text
1. Review & Approve Spec (specs/0X-*.md)
          │
          ▼
2. Orchestrator creates branch `spec/0X-<slug>`
          │
          ▼
3. Swarm / focused implementation scoped strictly to Spec 0X
          │
          ▼
4. Automated + Browser Verification against Spec Acceptance Criteria
          │
          ▼
5. User Review & Approval → Merge `spec/0X-<slug>` → `main` & push
```

---

## Specification Index

| Spec ID | Title | Branch | Depends On | Status |
| :--- | :--- | :--- | :--- | :--- |
| **[SPEC-01](./01-student-registration-and-admin-approval.md)** | Student Registration, School ID Photo Upload & Admin Approval | `spec/01-student-registration-approval` | Base (`main`) | `READY FOR REVIEW` |
| **[SPEC-02](./02-verified-checkout-account-and-instructions.md)** | Verified Student Checkout, Account Portal & Post-Checkout Item Instructions | `spec/02-verified-checkout-instructions` | `SPEC-01` | `DRAFT` |
| **[SPEC-03](./03-verified-equipment-return.md)** | Second-Verification Authenticated Equipment Return | `spec/03-verified-equipment-return` | `SPEC-01`, `SPEC-02` | `DRAFT` |
| **[SPEC-04](./04-raspberry-pi-2-3-gpio-locker-manager.md)** | Raspberry Pi 2/3 12-Channel Locker GPIO & Technical Admin Hardware UI | `spec/04-pi-2-3-gpio-locker-manager` | `SPEC-01`–`SPEC-03` | `DRAFT` |
| **[SPEC-05](./05-pi-2-3-installer-and-beginner-readme.md)** | Raspberry Pi 2/3 Installer Tuning & Beginner Step-by-Step README | `spec/05-pi-2-3-installer-readme` | `SPEC-01`–`SPEC-04` | `DRAFT` |

---

## Global Non-Negotiable Constraints (Apply to Every Spec)

1. **100% Offline-Ready on Raspberry Pi**: All templates load local `/css/labguard.css` (rebuilt via `npm run build:css`) and local `/images/*` — **zero external CDN or Google Fonts requests**.
2. **Backend Parity**: Primary Raspberry Pi runtime is `app.py` (Python 3 + Flask + SQLite3 WAL + `flask-sock`); `server.ts` (Node.js/Express) maintains API parity and passes `npm run lint` (`tsc --noEmit`).
3. **Raspberry Pi 2 & 3 Resource Safety**: Lightweight SQLite WAL storage, client-side compressed uploads (for SD card longevity & 1GB RAM headroom), and clean 800×480 kiosk viewport (`?kiosk=1`).
4. **No Spec Creep**: Each branch touches only files required by its spec and must pass every Acceptance Criterion before merge.
