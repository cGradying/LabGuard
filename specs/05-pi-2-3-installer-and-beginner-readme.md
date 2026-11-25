# SPEC-05: Raspberry Pi 2/3 Installer Tuning & Beginner/Student Step-by-Step README

- **Spec ID:** `SPEC-05`
- **Status:** `MERGED`
- **Target Branch:** `spec/05-pi-2-3-installer-readme`
- **Dependencies:** `SPEC-01`, `SPEC-02`, `SPEC-03`, `SPEC-04`

---

## 1. Problem & Goal

1. **Raspberry Pi 2 & Pi 3 Hardware Optimization**: Pi 2B (32-bit ARMv7, 1GB RAM) and Pi 3B/3B+ (1GB RAM) have tighter memory and GPIO library differences compared to Pi 4/5. `setup_raspberry_pi.sh` must explicitly detect and optimize for 1GB RAM Pis and install Pi 2/3/4/5 GPIO packages cleanly.
2. **Amateur / Student-Proof `README.md`**: A student or beginner who has never used a Raspberry Pi, Linux terminal, breadboard, or relay board must be able to assemble, wire, install, configure, and operate every part of LabGuard+ step by step without guesswork or hardware damage.

---

## 2. Scope

### 2.1 `setup_raspberry_pi.sh` & `.env.example` Updates
- Install `python3-rpi.gpio` (Pi 2/3 Bullseye), `python3-rpi-lgpio` (Pi 2/3/4 Bookworm), and `python3-lgpio` (Pi 5) optionally via `apt_install_optional`.
- Create `/var/lib/labguard/id_photos` owned by `$TARGET_USER` with restricted permissions (`750`) for student ID photos.
- Detect low RAM (`<= 1100 MB`, i.e., Pi 2B / Pi 3B / Pi 3B+ / Zero 2 W):
  - Pass low-memory Chromium flags in `labguard_kiosk.sh` (`--disable-background-networking --disable-sync --disable-extensions --disable-default-apps --no-default-browser-check --js-flags="--max-old-space-size=256"`).
  - Warn if swap `< 512 MB` with exact `dphys-swapfile` steps to prevent Chromium OOM on 1GB Pis.
- Add `LABGUARD_DATA_DIR`, `LABGUARD_ADMIN_EMAIL`, and `LABGUARD_ADMIN_PASSWORD` to `/etc/default/labguard` and `.env.example`.

### 2.2 Beginner-Friendly Step-by-Step `README.md`
1. **Complete Parts & Safety Checklist**:
   - Pi 2B / Pi 3B / Pi 3B+ (explicit note: flash **32-bit Raspberry Pi OS with Desktop** for 1GB RAM stability), 16GB+ SD card, Pi 5V PSU, **separate 12V DC PSU for solenoid locks** *(bold safety warning: NEVER connect 12V to Raspberry Pi GPIO or 5V pins!)*, 12-channel (or 8+4-channel) 5V opto-isolated relay module, 12× 12V DC electric cabinet solenoid locks, 3× LEDs + 3× 220Ω–330Ω resistors, optional active buzzer, jumper wires, 7" touchscreen.
2. **Step-by-Step OS Flashing (Raspberry Pi Imager)**: Exact click-by-click screenshots/instructions for Device, 32-bit Desktop OS, Hostname `labguard`, Wi-Fi, SSH, and Desktop Auto-Login.
3. **Zero-Guesswork Hardware Wiring Guide**:
   - ASCII diagram of the 40-pin header (Physical Pins 1–40).
   - Full 16-pin table (12 Lockers + Green/Yellow/Red LEDs + Buzzer + GND) with BOTH BCM GPIO and Physical Pin numbers.
   - Step-by-step Relay + 12V Solenoid wiring (`Pi GPIO → Relay IN1..IN12`, `Pi GND → Relay GND`, `12V+ → Relay COM`, `Relay NO → Solenoid +`, `Solenoid - → 12V-`).
   - Plain-English explanation of **Active-LOW vs Active-HIGH** and LED resistor polarity.
4. **Copy-Paste Installation & Admin Password Security**: Exact terminal commands (`git clone`, `sudo bash setup_raspberry_pi.sh`, changing default admin password in `/etc/default/labguard`, `sudo reboot`).
5. **Step-by-Step User Manual for Every Role**:
   - **5.1 New Student Registration** (scanning Registration QR, taking clear School ID photo, checking approval status)
   - **5.2 Admin Approving Students** (opening Student Accounts tab, zooming ID photo, Approve/Reject)
   - **5.3 Borrowing Equipment** (picking apparatus → scanning Checkout QR → logging in → unlocking locker → **reading the embedded Proper-Use & Safety Precautions list on the Digital Pass**)
   - **5.4 Returning Equipment** (second-verification Return QR → logging in → ownership check preventing others from returning your items → Good/Damaged/Missing → unlocking locker)
   - **5.5 Managing Student Account (`/student/account`)** (reopening embedded item instructions, active loans, direct return, password change)
   - **5.6 Configuring & Testing All 12 GPIO Lock Pins in Admin Settings (Zero Coding!)** (remapping pins, flipping Active-LOW/HIGH, testing `Pulse`/`HIGH`/`LOW`, saving live)
6. **Offline Wi-Fi / Hotspot Setup, Maintenance & Beginner Troubleshooting** (inverted relay polarity, missing common GND, 1GB swap on Pi 2/3, AP isolation, DB reset, uninstall).

---

## 3. Files Touched

- `setup_raspberry_pi.sh`
- `.env.example`
- `README.md`

---

## 4. Acceptance Criteria (Must Pass Before Merging to `main`)

- [x] `bash -n setup_raspberry_pi.sh uninstall_raspberry_pi.sh run_local.sh` passes with 0 errors.
- [x] Every GPIO pin, URL, route, env var, and default demo credential documented in `README.md` matches the live codebase 100%.
- [x] All 5 specs are verified end-to-end together on `main` and pushed to `cGradying/LabGuard`.
