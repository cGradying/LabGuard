# SPEC-04: Raspberry Pi 2 & 3 12-Channel Locker GPIO & Technical Admin Hardware UI

- **Spec ID:** `SPEC-04`
- **Status:** `MERGED`
- **Target Branch:** `spec/04-pi-2-3-gpio-locker-manager`
- **Dependencies:** `SPEC-01`, `SPEC-02`, `SPEC-03`

---

## 1. Problem & Goal

The physical LabGuard+ cabinet runs on a **Raspberry Pi 2 Model B or Raspberry Pi 3 Model B/B+** (also supporting Pi 4/5/Zero 2 W) and controls **~12 electric locker lock pins** (`HIGH` / `LOW` digital outputs driving opto-isolated relay boards or MOSFETs) plus the **3 Safety Status LEDs** and **Active Buzzer**.

Instead of hardcoding pin numbers in Python files, Lab Administrators and technical staff need a **dedicated technical GPIO Hardware Settings console** inside `/admin` to remap pins, flip Active-LOW / Active-HIGH polarity, tune unlock pulse durations, inspect live electrical states (`HIGH` / `LOW`), and test every pin individually — persisted in SQLite and applied live with zero reboot!

---

## 2. Raspberry Pi 2 / 3 Conflict-Free 16-Pin Default Map

Leaves **I2C (`GPIO 2, 3`)**, **UART (`GPIO 14, 15`)**, **SPI0 (`GPIO 7, 8, 9, 10, 11`)**, **PWM0 (`GPIO 18`)**, and **EEPROM (`GPIO 0, 1`)** completely free so SPI touchscreens, I2C sensors, or serial consoles never collide with locker pins:

| Channel | Default Compartment / Role | BCM GPIO | Physical Pin | Default Logic |
| :--- | :--- | :---: | :---: | :--- |
| **Locker 1** | `1st - 1st Section` | `GPIO 5` | Pin 29 | Active-LOW *(Relay: LOW = Unlock)* |
| **Locker 2** | `2nd - 1st Section` | `GPIO 6` | Pin 31 | Active-LOW |
| **Locker 3** | `3rd - 1st Section` | `GPIO 13` | Pin 33 | Active-LOW |
| **Locker 4** | `4th - 1st Section` | `GPIO 19` | Pin 35 | Active-LOW |
| **Locker 5** | `1st - 2nd Section` | `GPIO 26` | Pin 37 | Active-LOW |
| **Locker 6** | `2nd - 2nd Section` | `GPIO 12` | Pin 32 | Active-LOW |
| **Locker 7** | `3rd - 2nd Section` | `GPIO 16` | Pin 36 | Active-LOW |
| **Locker 8** | `4th - 2nd Section` | `GPIO 20` | Pin 38 | Active-LOW |
| **Locker 9** | `1st - 3rd Section` | `GPIO 21` | Pin 40 | Active-LOW |
| **Locker 10** | `2nd - 3rd Section` | `GPIO 24` | Pin 18 | Active-LOW |
| **Locker 11** | `3rd - 3rd Section` | `GPIO 25` | Pin 22 | Active-LOW |
| **Locker 12** | `4th - 3rd Section` | `GPIO 4` | Pin 7 | Active-LOW |
| **Green LED** | `SAFE` Indicator | `GPIO 17` | Pin 11 | Active-HIGH |
| **Yellow LED** | `CAUTION` Indicator | `GPIO 27` | Pin 13 | Active-HIGH |
| **Red LED** | `UNSAFE` Indicator | `GPIO 22` | Pin 15 | Active-HIGH |
| **Active Buzzer** | Status / Checkout Chirp | `GPIO 23` | Pin 16 | Active-HIGH |

---

## 3. Hardware Controller Architecture (`hardware/gpio_manager.py`)

- Built on `gpiozero.DigitalOutputDevice` — automatically supports:
  - **Raspberry Pi 2B & Pi 3B/3B+** (`RPi.GPIO` on Bullseye / `rpi-lgpio` on Bookworm)
  - **Raspberry Pi 4B & Pi 5** (`rpi-lgpio` / `lgpio`)
  - **PC / Mac Simulation Mode** (automatic fallback with identical electrical `HIGH`/`LOW` state tracking!)
- **Thread-Safe Runtime Reload (`apply_config`)**:
  - Validates `bcm_pin` in `2..27`, rejects ANY duplicate `bcm_pin` across enabled lockers/LEDs/buzzer with a clear conflict message naming both channels.
  - Cleanly releases old GPIO handles and binds new pins live without restarting `labguard.service`.
- **Per-Locker Controls**:
  - `pulse` (energizes lock for `pulse_seconds` — default `5.0s` — then auto-relocks via timer to prevent solenoid coil overheating!)
  - `unlock` / `lock` (logical state based on `active_high`)
  - `high` / `low` (direct raw electrical `3.3V` / `0V` override for multimeter & relay diagnostics!)
- **Automatic Transaction Integration**:
  - When `auto_unlock_on_borrow` is enabled, verified Checkout (`SPEC-02`) pulses the locker pin(s) matching borrowed items' `storage_compartment` and returns `unlocked_lockers[]` in the receipt & WS toast!
  - When `auto_unlock_on_return` is enabled, verified Return (`SPEC-03`) pulses the locker pin(s) matching returned items' `storage_compartment` so the student can place items back inside!
- **Diagnostic Event Ring Buffer**: Records the last 50 GPIO state transitions (timestamp, channel, BCM pin, action, `HIGH`/`LOW`, logical state, source).

---

## 4. Technical Admin UI (`templates/admin.html` → "GPIO & Locker Hardware" Tab)

1. **Board & Driver Telemetry Bar**: Pi board model (`/proc/device-tree/model`), CPU arch (`armv7l`/`aarch64`), active driver/pin factory, mode selector (`auto` / `enabled` / `simulation`), default unlock pulse duration, Auto-Unlock toggles, **Save & Apply Live**, **Reset Pi 2/3 Defaults**, **Unlock All**, **Force Relock All**, and **Export / Import JSON**.
2. **Interactive 40-Pin Header Pinout Map**: Visual 2×20 pin grid (Pins 1–40) displaying `3V3`, `5V`, `GND`, bus tags (`I2C`, `SPI`, `UART`), and live badges (`L1`..`L12`, `G-LED`, `Y-LED`, `R-LED`, `BUZ`) with real-time `HIGH`/`LOW` indicator dots.
3. **12-Channel Locker Pin Matrix Table**:
   - Inline editing for Compartment Name, BCM GPIO Pin dropdown (showing `BCM X (Pin Y)` + bus warnings), Polarity (`Active-LOW · Relay` vs `Active-HIGH · Direct`), Pulse Duration (`0.5–60s`), Enabled toggle.
   - Live Electrical State badge (`HIGH 3.3V` / `LOW 0V` + `LOCKED` / `UNLOCKED`).
   - Instant diagnostic buttons: **`Pulse`**, **`HIGH`**, **`LOW`**.
4. **LED & Buzzer Pin Table**: Inline BCM pin, polarity, enabled toggle, live state, and **`Test (1s)`** button.
5. **Live GPIO Diagnostic Event Console**: Dark monospace live stream of recent pin transitions.

---

## 5. Database & API Contract

- **SQLite `gpio_config` table**: `id = 1`, `config_json`, `updated_at`, `updated_by`.
- **Admin-protected GPIO endpoints** (all require Admin Bearer token):
  - `GET /api/admin/gpio-config`
  - `PUT /api/admin/gpio-config` *(validates conflicts, persists to SQLite, reloads live, broadcasts `gpio_updated`)*
  - `POST /api/admin/gpio-config/reset`
  - `POST /api/admin/gpio/test-locker` (`{ locker_id, action: "pulse"|"unlock"|"lock"|"high"|"low", duration_seconds? }`)
  - `POST /api/admin/gpio/test-led` (`{ channel: "green"|"yellow"|"red"|"buzzer", action: "pulse"|"high"|"low", duration_seconds? }`)
  - `POST /api/admin/gpio/unlock-all` & `POST /api/admin/gpio/lock-all`

---

## 6. Files Touched

- `hardware/gpio_manager.py` *(new)*
- `hardware/led_controller.py` *(compatibility wrapper)*
- `app.py` & `server.ts`
- `templates/admin.html`
- `templates/kiosk.html`, `templates/student_form.html`, `templates/student_return.html` *(show unlocked locker compartment callouts on borrow/return confirmation)*
- `public/css/labguard.css`

---

## 7. Acceptance Criteria (Must Pass Before Merging to `main`)

- [x] Default 16-pin mapping has zero duplicate BCM pins and zero collisions with I2C/SPI0/UART/EEPROM.
- [x] `PUT /api/admin/gpio-config` rejects duplicate enabled pins with HTTP `400` naming both conflicting channels.
- [x] Saving valid custom BCM pin / polarity / pulse changes persists across server restart and updates the 40-pin visual diagram immediately.
- [x] `Pulse`, `HIGH`, and `LOW` buttons toggle the live electrical state accurately for both `Active-LOW` and `Active-HIGH` channels, and `Pulse` auto-relocks after the configured duration.
- [x] Verified Checkout and Verified Return automatically pulse the matching compartment locker(s) and show the unlocked compartment on the receipt & kiosk toast.
- [x] Runs cleanly in `simulation` mode on macOS/Windows/Linux and in `raspberry_pi_gpio` mode on Pi 2/3/4/5.
