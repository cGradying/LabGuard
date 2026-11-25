# LabGuard+ — Smart Science Laboratory Safety Station, QR Equipment Kiosk & 12-Locker GPIO Controller

**Arellano University – Jose Rizal Campus (Senior High School & General Science Laboratory)**

> **Beginner-Friendly Setup, Wiring & User Manual** — Written so a Senior High School student, teacher, or first-time Raspberry Pi builder who has **never** used Linux, a breadboard, or a relay board before can assemble, wire, install, configure, and run **LabGuard+** safely from start to finish without guesswork.

---

## Quick Navigation

- [Overview & How LabGuard+ Works](#overview--how-labguard-works)
- [Part 1: Complete Parts & Electrical Safety Checklist (Pi 2 & Pi 3 Focus)](#part-1-complete-parts--electrical-safety-checklist-pi-2--pi-3-focus)
- [Part 2: Step-by-Step Raspberry Pi OS Setup (For Total Beginners)](#part-2-step-by-step-raspberry-pi-os-setup-for-total-beginners)
- [Part 3: Zero-Guesswork Hardware Wiring Guide (Pi 2 / 3 / 4 / 5)](#part-3-zero-guesswork-hardware-wiring-guide-pi-2--3--4--5)
- [Part 4: Step-by-Step Software Installation (Copy & Paste)](#part-4-step-by-step-software-installation-copy--paste)
- [Part 5: Complete Step-by-Step User Manual (How to Use Every Feature)](#part-5-complete-step-by-step-user-manual-how-to-use-every-feature)
- [Part 6: Offline Wi-Fi / Hotspot, Local PC Runs, Maintenance & Beginner Troubleshooting](#part-6-offline-wi-fi--hotspot-local-pc-runs-maintenance--beginner-troubleshooting)

---

## Overview & How LabGuard+ Works

**LabGuard+** turns a Raspberry Pi into a **100% offline-ready Smart Science Laboratory Station**. Instead of writing in paper logbooks or typing personal details on a tiny shared touchscreen, students tap what they need on the 7-inch kiosk, scan a QR code with their own smartphone to verify their school account, unlock the exact apparatus locker automatically, and receive step-by-step **Proper Use Instructions & Safety Precautions** right on their phone.

```text
┌───────────────────────────┐      Local Lab Wi-Fi / Hotspot      ┌──────────────────────────────┐
│  7" Touchscreen Kiosk     │◄───────── (No Internet Needed) ────►│  Student Smartphone          │
│  /kiosk?kiosk=1           │                                     │  • /student/register         │
│  • Tap Borrow / Return    │                                     │  • /student/checkout/<token> │
│  • Generate QR Codes      │                                     │  • /student/return/<token>   │
│  • Live Safety LED Banner │                                     │  • /student/account          │
└─────────────┬─────────────┘                                     └──────────────┬───────────────┘
              │                                                                  │
              ▼                                                                  ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│                  Raspberry Pi (Pi 2B / 3B / 3B+ / 4B / 5) — LabGuard+ Server                   │
│             Python 3 + Flask + WebSockets + SQLite3 (WAL) + Live GPIO Manager                  │
├──────────────────────────────────────────┬─────────────────────────────────────────────────────┤
│  Physical Cabinet Hardware (16 Pins)     │  Teacher / Lab Custodian PC Console                 │
│  • 12× Locker Lock Relays (12V Solenoid) │  • /admin                                           │
│  • 3× Safety Status LEDs (G / Y / R)     │  • Approve Student School IDs, Edit Item Guides,    │
│  • 1× Active Buzzer                      │    Control Safety LEDs & Configure All 12 GPIO Pins │
└──────────────────────────────────────────┴─────────────────────────────────────────────────────┘
```

### All 6 LabGuard+ Web Interfaces & URLs

Replace `<pi-ip>` with your Raspberry Pi's IP address (for example `192.168.1.50`) or use `labguard.local` on networks that support mDNS.

| # | Interface | URL | Device | What It Does |
| :-: | :--- | :--- | :--- | :--- |
| **1** | **Touchscreen Kiosk** | `http://localhost:5000/kiosk?kiosk=1` | Raspberry Pi 7" (`800×480`) Touchscreen | Attract screen, **Borrow Equipment**, **Return Equipment**, New Student Registration QR button, on-screen QWERTY search keyboard, apparatus basket, QR code modals, privacy-masked return cards (press-and-hold Eye reveal), and live LED Safety banner. |
| **2** | **Student Registration + School ID Upload** | `http://<pi-ip>:5000/student/register` | Student Smartphone | First-time account signup with Full Name, Student ID/LRN, Strand/Faculty, School Email, password, and a live camera/gallery **AU School ID photo upload** (auto-compressed on the phone), plus a live **Check Status** lookup box. |
| **3** | **Student Mobile Verified Borrow Checkout** | `http://<pi-ip>:5000/student/checkout/<token>` | Student Smartphone | Opened by scanning the Kiosk Checkout QR. Requires approved student login, captures Subject, Supervising Teacher, Return Date/Time, and Safety Pledge, unlocks the physical locker(s), and immediately shows **Embedded Proper Use Instructions & Safety Precautions** on the Digital Pass. |
| **4** | **Student Mobile Second-Verification Return** | `http://<pi-ip>:5000/student/return/<token>` | Student Smartphone | Opened by scanning the Kiosk Return QR. Enforces **strict borrower ownership** (students can ONLY return their own borrowed equipment — other accounts are blocked with HTTP `403`), logs `Good` / `Damaged` / `Missing` condition, and unlocks the locker for drop-off. |
| **5** | **Student Account Portal** | `http://<pi-ip>:5000/student/account` | Student Smartphone / PC | Personal dashboard for approved students to view Active Borrowed Equipment, reopen embedded Usage & Safety Instructions anytime, perform direct verified returns, inspect borrow/return history, and change their password. |
| **6** | **PC Admin Console** | `http://<pi-ip>:5000/admin` | Lab Custodian / Teacher PC | Password-protected dashboard with KPI cards, searchable borrow logs & CSV export, **Student Accounts** (zoomable School ID Lightbox + Approve/Reject/Suspend), **Kiosk Lab Items** (inventory + **Edit Guide** for item instructions), **LED Safety Status Control** (`SAFE`/`CAUTION`/`UNSAFE`), and the **GPIO & Locker Hardware** live configuration console. |

### Key Security, Safety & Hardware Highlights

- **School ID Photo Registration + Admin Approval Gate**: Every new student uploads a photo of their official AU-JRC School ID. Accounts stay `pending` until a teacher/custodian verifies the ID photo and clicks **Approve** — `pending`, `rejected`, and `suspended` accounts are strictly blocked from borrowing or returning equipment.
- **Verified Borrow Checkout + Embedded Proper-Use Instructions**: As soon as a student confirms checkout, their Digital Pass automatically lists step-by-step **Proper / General Use Instructions** and **Safety Precautions Before Use** tailored to each borrowed apparatus (and saves them in **Student Account** for reference during the experiment).
- **Second-Verification Authenticated Returns**: Returning equipment requires logging into the **same student account** that checked the apparatus out, preventing accidental or unauthorized returns by classmates. Reporting `Damaged` or `Missing` automatically raises the Station Safety LED to **`YELLOW (CAUTION)`**.
- **12 Locker Lock GPIO Channels + 3 Safety LEDs + Active Buzzer (Zero Coding Needed)**: All 12 locker lock pins (`Active-LOW` relay or `Active-HIGH` direct, pulse `0.5–60s`, raw `HIGH`/`LOW` & `Pulse` test controls) plus the 3 LEDs and Buzzer are **100% configurable live in `/admin` → GPIO & Locker Hardware** without editing code or rebooting.
- **100% Offline-Ready After Installation**: Local pre-compiled `/css/labguard.css`, local apparatus icons `/images/equipment/*.svg`, local QR code generation, and persistent SQLite3 database in WAL mode (`/var/lib/labguard/labguard.db`) — **zero internet or external CDN requests** needed in class.

---

## Part 1: Complete Parts & Electrical Safety Checklist (Pi 2 & Pi 3 Focus)

LabGuard+ is engineered specifically to run smoothly on **Raspberry Pi 2 Model B** and **Raspberry Pi 3 Model B / B+** (1 GB RAM boards commonly available in schools), and also works seamlessly on **Raspberry Pi 4B**, **Raspberry Pi 5**, and **Raspberry Pi Zero 2 W**.

> [!IMPORTANT]
> **Why 32-bit Raspberry Pi OS with Desktop is strongly recommended for Pi 2 & Pi 3:**
> - **Raspberry Pi 2 Model B** has a 32-bit ARMv7 CPU — 64-bit OS images **will not boot** on Pi 2B.
> - **Raspberry Pi 3 Model B / B+** only has **1 GB of RAM**. Running **32-bit Raspberry Pi OS (with Desktop)** uses noticeably less memory than 64-bit, leaving plenty of headroom for Chromium Touchscreen Kiosk mode so it stays fast and doesn't crash!

### Complete Hardware & Parts Checklist

| Component | Recommended Specification | Required? | Notes for Beginners |
| :--- | :--- | :---: | :--- |
| **Raspberry Pi** | **Raspberry Pi 2 Model B** or **Raspberry Pi 3 Model B / B+** *(Pi 4B, Pi 5, and Pi Zero 2 W also supported)* | **Required** | Use a Wi-Fi USB dongle if using a Pi 2B (Pi 3B/3B+/4/5 have built-in Wi-Fi), or connect Pi 2B via Ethernet cable to your lab router. |
| **microSD Card** | **16 GB – 32 GB** Class 10 / A1 (SanDisk, Samsung, Kingston) | **Required** | 32 GB A1 gives longer lifespan for SQLite logs and student School ID photos. |
| **Pi Power Supply (5V)** | **Dedicated 5V 2.5A+** Micro-USB PSU (for Pi 2/3/Zero 2 W) or USB-C 5V 3A+ PSU (for Pi 4/5) | **Required** | Avoid cheap phone chargers — under-voltage causes random reboots and SD corruption. |
| **7" Touchscreen Display** | Official **7" (`800×480`) DSI Touchscreen** or any **7" HDMI Touchscreen** | **Required for Kiosk** | Optional if running headless server-only mode (`--no-kiosk`). |
| **12V Lock Power Supply** | **SEPARATE 12V DC 5A–10A Power Supply** (with DC barrel jack or screw terminals) | **Required for Locks** | Powers ONLY the 12V electric solenoid cabinet locks. **NEVER connect to the Raspberry Pi!** |
| **5V Relay Module (12 Ch)** | **12-Channel** (or **8-Channel + 4-Channel**) **5V Opto-Isolated Relay Module** | **Required for Locks** | Recommended: add a small separate **5V 2A power adapter** for the relay coils (`JD-VCC`) so firing multiple relays at once never dips the Pi's 5V rail. |
| **12× Electric Cabinet Locks** | **12× 12V DC Electric Solenoid Cabinet Locks** (**Fail-Secure / Normally Locked**) | **Required for Locks** | Fail-secure locks stay **LOCKED** when power is off, and retract open during a 5-second 12V pulse. |
| **3-Color Safety LEDs** | **1× Green, 1× Yellow, 1× Red** (5mm standard LEDs) | Optional | Simulated automatically on screen if not wired yet. |
| **LED Resistors** | **3× 220Ω – 330Ω** (1/4W) current-limiting resistors | **Required with LEDs** | **Mandatory** — one resistor per LED protects the Pi's 3.3V GPIO pins from burning out! |
| **Active Buzzer** | **1× 3.3V / 5V Active Buzzer** (2-pin or 3-pin module) | Optional | Chirps softly on verified checkouts, returns, and safety alerts. |
| **Wiring & Connectors** | Female-to-Female & Male-to-Female **DuPont jumper wires**, mini breadboard (for LEDs), and **18–22 AWG wire** + screw terminal blocks (for 12V lock wiring) | **Required for Hardware** | Use thicker wire (18–22 AWG) on the 12V solenoid power lines; standard jumper wires are fine for the 3.3V Pi GPIO signal pins. |

> [!CAUTION]
> **CRITICAL ELECTRICAL SAFETY WARNING — READ BEFORE WIRING!**
> 1. **NEVER connect 12V power (or the 12V power supply `+` wire) to ANY Raspberry Pi pin** — not GPIO pins (max 3.3V), not the 5V pin, and not the 3.3V pin. Even a split-second 12V touch will **permanently fry and destroy the Raspberry Pi!**
> 2. **NEVER try to power 12V solenoid cabinet locks from the Raspberry Pi's 5V pin.** Solenoid locks draw heavy current (~0.6A–1.5A each) and produce voltage spikes; they MUST use their own **separate 12V DC power supply** isolated on the screw-terminal (`COM` / `NO`) side of the relay module.
> 3. **ALWAYS unplug BOTH power supplies (5V Pi PSU and 12V Lock PSU)** before connecting, moving, or troubleshooting any wire.
> 4. **Keep solenoid unlock pulses short (3–10 seconds, default `5.0s`).** Small 12V cabinet solenoids are designed for brief unlock pulses — leaving them continuously energized for minutes can overheat or damage the solenoid coil.

---

## Part 2: Step-by-Step Raspberry Pi OS Setup (For Total Beginners)

Follow these exact clicks on any regular Windows, macOS, or Linux computer to prepare your Raspberry Pi's microSD card.

### Step 1: Download & Open Raspberry Pi Imager
1. Go to [raspberrypi.com/software](https://www.raspberrypi.com/software/) and install **Raspberry Pi Imager** on your computer.
2. Insert your **16 GB–32 GB microSD card** into your computer (using a USB card reader if needed).
3. Open **Raspberry Pi Imager**.

### Step 2: Select Device, OS, and Storage
1. Click **Choose Device** → select **Raspberry Pi 2** or **Raspberry Pi 3** (or whichever Pi model you have).
2. Click **Choose OS** → select **Raspberry Pi OS (32-bit)** *(the default recommended Desktop version — look for "with the Raspberry Pi Desktop")*.
   - **Do NOT choose "Lite"** if you are connecting a 7-inch touchscreen kiosk (Lite has no graphical desktop).
   - **Why 32-bit?** Required for Pi 2B, and strongly recommended for Pi 3B/3B+ to keep RAM usage low on 1 GB boards.
3. Click **Choose Storage** → select your microSD card *(double-check it's the SD card and not an external hard drive!)*.

### Step 3: Pre-Configure Wi-Fi, Hostname & SSH (OS Customisation)
1. Click **Next** → when asked *"Would you like to apply OS customisation settings?"*, click **Edit Settings**.
2. On the **General** tab:
   - ✅ **Set hostname**: type `labguard` *(this lets teachers and phones open `http://labguard.local:5000`)*
   - ✅ **Set username and password**:
     - Username: `pi`
     - Password: choose a password you will remember and write it down!
   - ✅ **Configure wireless LAN**:
     - **SSID**: enter your laboratory Wi-Fi network name *(exact spelling & capitalization)*
     - **Password**: enter your Wi-Fi password
     - **Wireless LAN country**: select **`PH`** *(Philippines — or your local country code)*
   - ✅ **Set locale settings**: Time zone `Asia/Manila`, Keyboard layout `us`
3. Click the **Services** tab at the top:
   - ✅ Check **Enable SSH** → select **Use password authentication** *(lets you manage the Pi remotely from a teacher PC if needed)*.
4. Click **Save** → click **Yes** to apply customisation settings → click **Yes** to erase and write the SD card.
5. Wait for Raspberry Pi Imager to finish writing and verifying, then safely eject the microSD card.

### Step 4: First Boot & Confirm Desktop Auto-Login
1. Insert the microSD card into the underside of the Raspberry Pi.
2. Connect your **7" touchscreen**, a temporary USB keyboard/mouse (for initial setup), and plug in the **5V 2.5A+ Pi power supply**.
3. Wait 1–2 minutes for the Raspberry Pi Desktop to appear.
4. Confirm **Desktop Auto-Login** is turned ON (so the touchscreen kiosk starts automatically whenever the Pi is powered on):
   - Open the Terminal icon (`>_` in the top toolbar) and run:
     ```bash
     sudo raspi-config
     ```
   - Use the arrow keys and Enter to choose:
     **`1 System Options`** → **`S5 Boot / Auto Login`** → **`B4 Desktop Autologin`**
   - Press **`Tab`** → **`Finish`** (reboot if prompted).

---

## Part 3: Zero-Guesswork Hardware Wiring Guide (Pi 2 / 3 / 4 / 5)

> [!TIP]
> **Don't have the relays, 12V locks, or LEDs wired yet?**
> You can **skip Part 3 for now** and jump straight to [Part 4: Software Installation](#part-4-step-by-step-software-installation-copy--paste)! LabGuard+ automatically runs cleanly in **Simulation Mode** until your hardware is connected, so you can test the entire kiosk, phone QR flows, and admin console immediately without a single wire.

### First: Understand "BCM GPIO Number" vs "Physical Pin Number"

Every Raspberry Pi 2, 3, 4, 5, and Zero 2 W shares the exact same **40-pin J8 header** (two rows of 20 metal pins):
- **Physical Pin Number (`Pin 1` – `Pin 40`)**: The physical spot you count on the metal header (`Pin 1` is at the top-left corner nearest the microSD card slot; odd pins `1, 3, 5...39` are on the left column, even pins `2, 4, 6...40` are on the right column).
- **BCM GPIO Number (`GPIO 2` – `GPIO 27`)**: The internal chip number that software uses (for example, **`GPIO 17`** is on **Physical Pin 11** — NOT Pin 17!).

Always use **Physical Pin Number** when plugging in a wire, and **BCM GPIO Number** when viewing/editing settings in the LabGuard+ Admin Console.

---

### Visual 40-Pin J8 Header Map (Raspberry Pi 2 / 3 / 4 / 5)

Hold your Raspberry Pi with the **microSD card slot at the TOP** and the **USB / Ethernet ports at the BOTTOM**. The 40-pin header is along the right edge:

```text
                           [ microSD Card Side — TOP ]
                       ┌─────────────────────────────────┐
      3.3V Power       │  1  ●   ●  2  │ 5V Power
   FREE [I2C1 SDA]  G2 │  3  ●   ●  4  │ 5V Power
   FREE [I2C1 SCL]  G3 │  5  ●   ●  6  │ GND  (Common Ground)
  ► L12 (4th-3rd)   G4 │  7  ●   ●  8  │ G14  FREE [UART TX]
      GND              │  9  ●   ● 10  │ G15  FREE [UART RX]
  ► G-LED (SAFE)   G17 │ 11  ●   ● 12  │ G18  FREE [PWM0 / PCM]
  ► Y-LED (CAUT.)  G27 │ 13  ●   ● 14  │ GND  (Common Ground)
  ► R-LED (UNSAFE) G22 │ 15  ●   ● 16  │ G23  BUZ (Active Buzzer) ◄
      3.3V Power       │ 17  ●   ● 18  │ G24  L10 (2nd-3rd)       ◄
   FREE [SPI0 MOSI]G10 │ 19  ●   ● 20  │ GND  (Common Ground)
   FREE [SPI0 MISO] G9 │ 21  ●   ● 22  │ G25  L11 (3rd-3rd)       ◄
   FREE [SPI0 SCLK]G11 │ 23  ●   ● 24  │ G8   FREE [SPI0 CE0]
      GND              │ 25  ●   ● 26  │ G7   FREE [SPI0 CE1]
      ID_SD (EEPROM)   │ 27  ●   ● 28  │ ID_SC (EEPROM)
  ► L1 (1st-1st)    G5 │ 29  ●   ● 30  │ GND  (Common Ground)
  ► L2 (2nd-1st)    G6 │ 31  ●   ● 32  │ G12  L6 (2nd-2nd)        ◄
  ► L3 (3rd-1st)   G13 │ 33  ●   ● 34  │ GND  (Common Ground)
  ► L4 (4th-1st)   G19 │ 35  ●   ● 36  │ G16  L7 (3rd-2nd)        ◄
  ► L5 (1st-2nd)   G26 │ 37  ●   ● 38  │ G20  L8 (4th-2nd)        ◄
      GND              │ 39  ●   ● 40  │ G21  L9 (1st-3rd)        ◄
                       └─────────────────────────────────┘
                        [ USB & Ethernet Ports — BOTTOM ]
```

> [!NOTE]
> **100% Conflict-Free Bus Design:** Notice that **I2C (`GPIO 2, 3`)**, **UART (`GPIO 14, 15`)**, **SPI0 (`GPIO 7, 8, 9, 10, 11`)**, **PWM0 (`GPIO 18`)**, and **HAT EEPROM (`ID_SD, ID_SC`)** are all left **completely FREE** for future sensors (such as gas/smoke sensors, RFID readers, or OLED displays)!

---

### Complete 16-Pin LabGuard+ Wiring Table

This table matches the exact defaults in `hardware/gpio_manager.py`. Every pin can also be customized later in `/admin` → **GPIO & Locker Hardware**.

| Channel | Cabinet Compartment & Default Apparatus | BCM GPIO | Physical Pin | Default Logic | Default Pulse / Wire Destination |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Locker 1 (`L1`)** | `1st - 1st Section` *(Beaker)* | **BCM 5** | **Pin 29** | `Active-LOW` | `5.0s` → Relay `IN1` |
| **Locker 2 (`L2`)** | `2nd - 1st Section` *(Graduated Cylinder)* | **BCM 6** | **Pin 31** | `Active-LOW` | `5.0s` → Relay `IN2` |
| **Locker 3 (`L3`)** | `3rd - 1st Section` *(Florence Flask)* | **BCM 13** | **Pin 33** | `Active-LOW` | `5.0s` → Relay `IN3` |
| **Locker 4 (`L4`)** | `4th - 1st Section` *(Glass Funnel)* | **BCM 19** | **Pin 35** | `Active-LOW` | `5.0s` → Relay `IN4` |
| **Locker 5 (`L5`)** | `1st - 2nd Section` *(Erlenmeyer Flask)* | **BCM 26** | **Pin 37** | `Active-LOW` | `5.0s` → Relay `IN5` |
| **Locker 6 (`L6`)** | `2nd - 2nd Section` *(Test Tube, Holder & Rack Set)* | **BCM 12** | **Pin 32** | `Active-LOW` | `5.0s` → Relay `IN6` |
| **Locker 7 (`L7`)** | `3rd - 2nd Section` *(Tripod Stand)* | **BCM 16** | **Pin 36** | `Active-LOW` | `5.0s` → Relay `IN7` |
| **Locker 8 (`L8`)** | `4th - 2nd Section` *(Bell Jar)* | **BCM 20** | **Pin 38** | `Active-LOW` | `5.0s` → Relay `IN8` |
| **Locker 9 (`L9`)** | `1st - 3rd Section` *(Laboratory Gown)* | **BCM 21** | **Pin 40** | `Active-LOW` | `5.0s` → Relay `IN9` |
| **Locker 10 (`L10`)** | `2nd - 3rd Section` *(Stirring Rod & PPE Kit)* | **BCM 24** | **Pin 18** | `Active-LOW` | `5.0s` → Relay `IN10` |
| **Locker 11 (`L11`)** | `3rd - 3rd Section` *(Compound Light Microscope)* | **BCM 25** | **Pin 22** | `Active-LOW` | `5.0s` → Relay `IN11` |
| **Locker 12 (`L12`)** | `4th - 3rd Section` *(Spare / Admin-Added Items)* | **BCM 4** | **Pin 7** | `Active-LOW` | `5.0s` → Relay `IN12` |
| **Green LED (`G-LED`)** | Station Status: **`SAFE`** | **BCM 17** | **Pin 11** | `Active-HIGH` | Through **220Ω–330Ω resistor** → Green LED `+` |
| **Yellow LED (`Y-LED`)** | Station Status: **`CAUTION`** | **BCM 27** | **Pin 13** | `Active-HIGH` | Through **220Ω–330Ω resistor** → Yellow LED `+` |
| **Red LED (`R-LED`)** | Station Status: **`UNSAFE`** | **BCM 22** | **Pin 15** | `Active-HIGH` | Through **220Ω–330Ω resistor** → Red LED `+` |
| **Active Buzzer (`BUZ`)** | Optional Checkout / Return / Alert Chirp | **BCM 23** | **Pin 16** | `Active-HIGH` | Active Buzzer `+` leg (negative `-` to GND) |
| **Common Ground (`GND`)** | Shared Ground Reference | **GND** | **Pins 6, 9, 14, 20, 25, 30, 34, 39** | `0V` | Connects to Relay `GND`, all LED `-` legs & Buzzer `-` |

---

### Step-by-Step: Wiring the 5V Relay Module & 12V Solenoid Locks

Think of each relay channel as an **electrically isolated remote switch**. The Raspberry Pi controls the tiny low-voltage side on the left; the separate 12V power supply runs ONLY on the screw-terminal side on the right. **The two sides NEVER touch electrically!**

```text
  LOW-VOLTAGE CONTROL SIDE (3.3V / 5V)         ║     HIGH-POWER LOAD SIDE (12V DC ONLY)
                                               ║     ⚠ NEVER CONNECT TO RASPBERRY PI!
  ┌──────────────────┐     ┌───────────────────╫───────────────────┐
  │  Raspberry Pi    │     │  5V Opto-Isolated ║ Relay Screw Term. │
  │                  │     │   Relay Module    ║  (Channel 1..12)  │
  │  Pin 29 (GPIO 5) ├────►│ IN1  (Locker 1)   ║                   │     ┌──────────────────┐
  │  Pin 31 (GPIO 6) ├────►│ IN2  (Locker 2)   ║   [COM] ◄─────────┼─────┤ (+) 12V DC PSU   │
  │   ... (IN3..12)  ├────►│ IN3 .. IN12       ║     │ (switch)    │     │     (5A – 10A)   │
  │  Pin 6  (GND)    ├────►│ GND               ║   [NO]  ──────────┼────►│ (+) Solenoid     │
  │  Pin 2  (5V)*    ├────►│ VCC (opto logic)  ║   [NC]  (unused)  │     │     Cabinet Lock │
  └──────────────────┘     │                   ║                   │     │ (-) Solenoid     │
                           │ [Remove JD-VCC    ║                   │     └────────┬─────────┘
  *For 12 relays, power    │  jumper!]         ║                   │              │
   relay coils safely:     │  JD-VCC ◄─── (+)  ║                   │              ▼
   Separate 5V 2A PSU ────►│  GND    ◄─── (-)  ║                   │       (-) 12V DC PSU
                           └───────────────────╫───────────────────┘
```

#### Wiring Checklist (Power OFF While Wiring!)

1. **Control Side (Raspberry Pi → Relay Header Pins):**
   - Connect **Pi Physical Pins** from the table above (`Pin 29`, `31`, `33`, `35`, `37`, `32`, `36`, `38`, `40`, `18`, `22`, `7`) to **`IN1` through `IN12`** on your relay board(s).
   - Connect **Raspberry Pi `GND` (e.g., Pin 6 or Pin 30)** to the relay board's **`GND`** pin. *(If you use an 8-channel + 4-channel pair, connect Pi `GND` to BOTH relay boards!)*
   - **Powering Relay Coils Safely (Important for 12 Channels!):**
     - **Recommended (Best Stability on Pi 2/3):** Pull off the yellow/black **`JD-VCC`–`VCC` jumper** on the relay board. Connect a small separate **5V 2A power adapter** to **`JD-VCC` (+)** and **`GND` (-)** on the relay board, and connect **Pi Pin 2 (`5V`)** ONLY to the logic **`VCC`** pin. This ensures even firing all 12 relays during *Emergency Unlock All* will never make the Raspberry Pi reboot!
     - *(Note: If your relay board uses a 12V coil input like `DC+`/`DC-` with optical isolation, power `DC+`/`DC-` from the 12V supply per the board's silkscreen, and connect ONLY `IN1..IN12` and signal `GND` to the Pi.)*
2. **Load Side (Separate 12V DC Supply → Relay Screw Terminals → 12V Solenoid Locks):**
   - For each locker channel (`1` through `12`):
     1. Connect **`12V PSU (+)`** to the **`COM`** (Common — middle screw terminal) of the relay. You can daisy-chain `12V (+)` across `COM1` → `COM2` → … → `COM12` using 18–20 AWG wire.
     2. Connect the **`NO` (Normally Open)** screw terminal of the relay to the **Solenoid Lock `(+)` red wire**. *(Leave `NC` empty!)*
     3. Connect the **Solenoid Lock `(-)` black wire** back to **`12V PSU (-)`**.
   - **Why `NO` (Normally Open)?** When the Pi is turned off or idle, the relay switch stays OPEN → `0V` goes to the solenoid → the locker stays **fail-secure (LOCKED)**. When a verified student borrows or returns an item, the relay closes for 5 seconds → `12V` retracts the lock bolt → locker pops open!

> [!IMPORTANT]
> **Plain-English Guide: Active-LOW vs Active-HIGH (Don't Panic if Relays Are Backwards!)**
> - **Active-LOW (`Active-LOW (Relay)` — LabGuard+ Default for Lockers):** Most blue 5V opto-isolated relay boards turn **ON (click)** when the Raspberry Pi drives the pin to **`LOW (0V)`**, and stay **OFF (locked)** when the pin is **`HIGH (3.3V)`**. LabGuard+ starts all 12 lockers at `HIGH (3.3V)` so every locker stays safely **LOCKED** on boot.
> - **Active-HIGH (`Active-HIGH (Direct)`):** Some relay boards and MOSFET lock drivers turn **ON** when the pin goes **`HIGH (3.3V)`** and stay **OFF** at **`LOW (0V)`**.
> - **If your relays behave backwards** (locks stay unlocked while idle and lock when pulsing), **do NOT rewire or edit code!** Just open `/admin` → **GPIO & Locker Hardware**, switch that channel's dropdown from `Active-LOW (Relay)` to `Active-HIGH (Direct)`, and click **Save & Apply Live**!

---

### Step-by-Step: Wiring the 3-Color Safety LEDs & Active Buzzer

Each LED has two metal legs:
- **Long leg (`+` Anode)** → connects through a **220Ω–330Ω resistor** to the Raspberry Pi GPIO pin.
- **Short leg (`-` Cathode / flat edge on plastic rim)** → connects directly to Raspberry Pi **`GND`**.

```text
  Raspberry Pi Pin              220Ω–330Ω Resistor        5mm LED               Raspberry Pi GND
  ────────────────              ──────────────────        ───────               ────────────────
  Pin 11 (GPIO 17) ──────────► [ 220Ω–330Ω ] ──────────► (+) [GREEN]  (-) ──┐
  Pin 13 (GPIO 27) ──────────► [ 220Ω–330Ω ] ──────────► (+) [YELLOW] (-) ──┼──► Pin 14 (GND)
  Pin 15 (GPIO 22) ──────────► [ 220Ω–330Ω ] ──────────► (+) [RED]    (-) ──┘

  Pin 16 (GPIO 23) ────────────────────────────────────► (+) [BUZZER] (-) ─────► Pin 9 or 14 (GND)
```

> [!WARNING]
> Always put a **220Ω–330Ω resistor** in series with every LED! Connecting a bare LED directly between a GPIO pin and GND draws too much current and can permanently burn out that Raspberry Pi GPIO pin.

---

## Part 4: Step-by-Step Software Installation (Copy & Paste)

Make sure your Raspberry Pi is connected to the internet for this one-time installation (after installation finishes, **no internet is needed**).

### Step 1: Clone the Repository & Run the Automated Installer

Open a Terminal on the Raspberry Pi (or SSH from another PC with `ssh pi@labguard.local`) and copy-paste these three commands:

```bash
git clone https://github.com/cGradying/LabGuard.git
cd LabGuard
sudo bash setup_raspberry_pi.sh
```

*(Forked from [intmatt-0/AU-LabGuard-](https://github.com/intmatt-0/AU-LabGuard-).)*

**What `setup_raspberry_pi.sh` automatically sets up for you:**
1. Detects your Raspberry Pi model, CPU architecture, RAM, and swap space (printing a clear summary for Pi 2B / 3B / 3B+ / 4B / 5).
2. Installs Python 3, `venv`, Pillow, `gpiozero`, Pi 2/3/4/5 GPIO libraries (`python3-rpi.gpio`, `python3-rpi-lgpio`, `python3-lgpio`), `rsync`, `avahi-daemon` (for `labguard.local`), and Chromium (`chromium` or `chromium-browser`).
3. Copies LabGuard+ to `/opt/labguard` with an isolated `.venv` (inheriting system GPIO drivers) and creates `/var/lib/labguard/labguard.db` plus restricted `/var/lib/labguard/id_photos` (`chmod 750`) for student School ID photos.
4. Creates `/etc/default/labguard` (`chmod 640` to protect your Admin password, preserving your edits on future updates) and starts `labguard.service` via `systemd`.
5. Configures fullscreen Chromium kiosk autostart (`~/labguard_kiosk.sh` + `~/.config/autostart/labguard-kiosk.desktop`) opening `http://localhost:5000/kiosk?kiosk=1`, automatically adding low-memory Chromium flags on 1 GB RAM Pis (`<= 1100 MB`, like Pi 2B & Pi 3B/3B+) and disabling screen blanking.

#### Optional Installer Flags

```bash
# Headless / server-only Pi (skip Chromium kiosk desktop autostart)
sudo bash setup_raspberry_pi.sh --no-kiosk

# Run on a custom TCP port (e.g. 8080) with a fixed QR base URL
sudo bash setup_raspberry_pi.sh --port 8080 --app-url http://labguard.local:8080
```

---

### Step 2: Change the Default Admin Password (Important Before Class Deployment!)

All Raspberry Pi runtime settings live in `/etc/default/labguard`. Open it with `nano`:

```bash
sudo nano /etc/default/labguard
```

Update `LABGUARD_ADMIN_EMAIL` and `LABGUARD_ADMIN_PASSWORD` (and any optional settings):

```ini
# HTTP server port
PORT=5000

# Optional fixed public base URL embedded in Checkout / Registration / Return QR codes.
# Leave blank to auto-detect your Pi's active LAN IPv4 address.
# Example: APP_URL=http://labguard.local:5000
APP_URL=

# Persistent data folder (stores labguard.db and id_photos/)
LABGUARD_DATA_DIR=/var/lib/labguard
LABGUARD_DB_PATH=/var/lib/labguard/labguard.db

# Admin Console Login Credentials — CHANGE THESE BEFORE DEPLOYING IN SCHOOL!
LABGUARD_ADMIN_EMAIL=lara.puertollano@arellano.edu.ph
LABGUARD_ADMIN_PASSWORD=au-jrc-2026
LABGUARD_ADMIN_NAME="Ms. Lara Marie A. Puertollano"

# Raspberry Pi GPIO driver mode: auto | 1 (force GPIO) | 0 (simulation)
# Note: All 12 locker lock pins + 3 LEDs + Buzzer can be edited LIVE inside
#       /admin -> GPIO & Locker Hardware (persisted in SQLite) without editing this file!
LABGUARD_GPIO_ENABLED=auto
LABGUARD_LED_GREEN_PIN=17
LABGUARD_LED_YELLOW_PIN=27
LABGUARD_LED_RED_PIN=22
LABGUARD_BUZZER_PIN=23
LABGUARD_BUZZER_ENABLED=1
LABGUARD_LED_ACTIVE_HIGH=1
```

**How to save and exit `nano` (for Linux beginners):**
1. Press **`Ctrl + O`** (letter O) → press **`Enter`** to save.
2. Press **`Ctrl + X`** to exit back to the terminal.

Apply your new settings and restart the service, then reboot into the fullscreen Touchscreen Kiosk:

```bash
sudo systemctl restart labguard
sudo reboot
```

### Step 3: Verify Health & GPIO Status

After reboot, the 7" touchscreen boots straight into the fullscreen LabGuard+ Kiosk. You can verify the server and GPIO status from any terminal:

```bash
curl http://localhost:5000/api/health
curl http://localhost:5000/api/hardware/status
```

### Built-In Demo Accounts (For Immediate Testing)

When LabGuard+ starts with a fresh database, it includes ready-to-test demo accounts:

| Role | Where to Log In | Username / Student ID (or Email) | Default Password | Status |
| :--- | :--- | :--- | :--- | :---: |
| **Lab Admin** | `/admin` | `lara.puertollano@arellano.edu.ph` | `au-jrc-2026` | Active Admin |
| **Demo Student 1** | Checkout / Return / Account | `AUJRC-2026-0101` *(or `one.abalos@arellano.edu.ph`)* | `student123` | `approved` (STEM) |
| **Demo Student 2** | Checkout / Return / Account | `AUJRC-2026-0102` *(or `christine.contreras@arellano.edu.ph`)* | `student123` | `approved` (STEM) |
| **Demo Student 3** | Checkout / Return / Account | `AUJRC-2026-0103` *(or `queenhannah.dones@arellano.edu.ph`)* | `student123` | `approved` (HUMSS) |
| **Pending Sample Student** | Test Admin ID Approval! | `AUJRC-2026-0105` *(or `ashlyjicks.pangilinan@arellano.edu.ph`)* | `student123` | `pending` (STEM) |

---

## Part 5: Complete Step-by-Step User Manual (How to Use Every Feature)

### 5.1 How a New Student Registers (First Time Only)

Every student registers once and uploads their official AU-JRC School ID for teacher verification.

1. Connect your smartphone to the **same Wi-Fi network (or LabGuard hotspot)** as the Raspberry Pi.
2. On the 7" Kiosk Welcome Screen, tap **"New Student? Register Account & Upload School ID →"** *(or open `http://<pi-ip>:5000/student/register` directly)*.
3. Scan the Registration QR code using your phone's camera.
4. Fill in the registration form:
   - **Full Name** (matching your official School ID)
   - **Student ID / LRN** (e.g., `AUJRC-2026-0210`)
   - **Strand / Faculty** (`STEM`, `HUMSS`, `ABM`, or `FACULTY`)
   - **School Email** (`@arellano.edu.ph`)
   - **Account Password** (minimum 6 characters) and **Confirm Password**
5. Under **Official School ID Photo**, tap **"Tap to Take Photo or Upload School ID"** and snap a bright, clear photo of the front of your AU-JRC School ID with your face, Full Name, and ID/LRN clearly readable. *(LabGuard+ automatically compresses the image on your phone — max 4 MB JPEG/PNG/WebP — to save Raspberry Pi storage.)*
6. Tap **"Submit Registration for Admin Approval →"**.
7. **Check Your Approval Status Anytime**: Scroll down to **"Already Registered? Check Status"** on `/student/register` and enter your Student ID/LRN or school email.
   - `pending`: Waiting for Lab Admin verification (borrowing is blocked until approved).
   - `approved`: Ready to borrow and return equipment!
   - `rejected`: Shows the teacher's exact reason — simply re-submit on `/student/register` using the **same LRN & email** with a clearer School ID photo to request re-verification.

---

### 5.2 How the Teacher / Lab Admin Approves Students

1. On a teacher/custodian PC (or tablet/phone on the same Wi-Fi), open **`http://labguard.local:5000/admin`** *(or `http://<pi-ip>:5000/admin`)*.
2. Sign in using your Admin email and password.
3. Click **Student Accounts** in the left sidebar (the badge shows how many `Pending` registrations are waiting).
4. Click a student's **School ID photo thumbnail** to open the **zoomable ID Photo Lightbox**.
5. Verify that the student's face, Full Name, and LRN/Student ID match their official AU-JRC School ID.
6. Take action right inside the Lightbox or table row:
   - Click **Approve** / **Approve Account** → the student can immediately sign in to borrow and return equipment.
   - Click **Reject** / **Reject with Reason** → pick a quick preset (e.g., *"Blurry / unreadable School ID photo"*, *"Name or LRN does not match School ID"*) or type a custom note, then click **Confirm Rejection**.
   - You can also click **Suspend** anytime to temporarily pause an approved account.

---

### 5.3 How a Student Borrows Equipment (+ Reading Embedded Usage & Safety Instructions!)

1. **On the Kiosk Touchscreen**:
   - Tap the Attract Screen to enter the Welcome Screen, then tap **Borrow Equipment**.
   - Browse by category or tap the search bar to use the on-screen QWERTY keyboard.
   - Tap items to add them to your **Basket** (adjust quantities as needed).
   - Tap **Checkout & Generate QR →** — the kiosk displays your unique Checkout QR code.
2. **On Your Smartphone**:
   - Scan the Checkout QR code with your phone camera to open `/student/checkout/<token>`.
   - **Sign in with your approved Student ID / LRN (or School Email) & Password**. *(Pending, rejected, or suspended accounts are blocked with a clear notice.)*
   - Fill in **Subject / Laboratory Activity**, **Supervising Teacher**, and **Expected Return Date & Time**.
   - Check the **Safety Pledge** box and tap **Confirm Verified Checkout →**.
3. **Physical Locker Unlocks Automatically**:
   - The Raspberry Pi pulses the locker relay(s) matching the compartment(s) of your borrowed apparatus (default **5.0 seconds**) and sounds a confirmation chirp!
   - Open the unlocked locker(s), collect your apparatus carefully, and **close the locker door** so it latches shut.
   - The 7" Kiosk automatically confirms checkout in real time and resets for the next student.
4. **Read Your Embedded Proper-Use Instructions & Safety Precautions**:
   - Right after checkout confirmation, your **Digital Pass Receipt** automatically expands **Embedded Apparatus Instructions & Safety Precautions** for every borrowed item:
     - **Proper / General Use Instructions** — exact step-by-step operating guide for that specific apparatus.
     - **Safety Precautions Before Use** — mandatory PPE and handling rules.
   - **Read these before starting your experiment!** You can reopen them anytime from **`/student/account`**.

> [!NOTE]
> If Laboratory Personnel set the Station LED Safety Status to **`UNSAFE` (RED)** (for example during a chemical spill or breakage cleanup), equipment checkout is automatically paused until cleared back to `SAFE` or `CAUTION`.

---

### 5.4 How a Student Returns Equipment (Second Account Verification)

To keep accountability airtight, **only the student whose account borrowed an item can return it**. There are two easy ways to return equipment:

#### Option A: Return at the 7" Kiosk Touchscreen
1. On the Kiosk Welcome Screen, tap **Return Equipment**.
2. Locate your active borrow record — names and IDs are privacy-masked by default; **press and hold the Eye icon** on a card to briefly reveal the full name and confirm it is your record.
3. Tap **Verify & Return →** on your record — the kiosk generates a single-use **Return Verification QR code** (`/student/return/<token>`, valid for 10 minutes).
4. Scan the QR code with your smartphone and sign in using **your own student account** (the exact account that borrowed the items).
   - **Ownership Protection**: If a classmate scans your QR code while logged into *their* account, LabGuard+ blocks the return with **`403 Account Ownership Verification Failed`** and displays a **Sign Out & Switch to Correct Account** button.
5. Inspect the apparatus and select the accurate return condition:
   - **`Good`** — clean, intact, and complete.
   - **`Damaged`** or **`Missing`** — add brief remarks; LabGuard+ automatically switches the Station Safety LED to **`YELLOW (CAUTION)`** to notify the Lab Custodian!
6. Tap **Confirm Verified Equipment Return →**.
7. **Physical Locker Unlocks**: The Pi unlocks the compartment locker(s) for 5 seconds — place the rinsed/dried apparatus back in its section and close the door firmly.

#### Option B: Return Directly From Your Phone (`/student/account`)
1. Open **`http://<pi-ip>:5000/student/account`** on your phone and log in.
2. Under **Active Borrowed Equipment**, tap **Return This Equipment →** on the loan you are returning.
3. Choose **`Good`**, **`Damaged`**, or **`Missing`**, enter optional notes, and confirm — the locker unlocks and the record moves to your **Past Borrow & Return History**.

---

### 5.5 How a Student Manages Their Account (`/student/account`)

Students can bookmark **`http://labguard.local:5000/student/account`** *(or `http://<pi-ip>:5000/student/account`)* on their phone to:
- View their **Account Verification Badge**, Student ID/LRN, and Strand/Faculty.
- Check all **Active Borrowed Equipment** and due times.
- Tap **Usage Instructions & Safety Precautions** on any borrowed item to reopen its step-by-step Proper Use & Safety guide anytime during class.
- Trigger a direct verified return (**Return This Equipment →**).
- Review **Past Borrow & Return History** (dates, transaction codes, and logged return conditions).
- Update their password via **Change Password** or **Sign Out** on a shared device.

---

### 5.6 How Lab Admin Edits Equipment Instructions & Manages Inventory

In **`/admin`**, teachers and lab custodians have full control over apparatus and instructions:
1. Click **Kiosk Lab Items (Add/Remove)** in the left sidebar.
2. **Customize Item Instructions (No Coding!)**:
   - Click **Edit Guide** on any apparatus card.
   - Edit **Proper / General Use Instructions** *(one step per line)* and **Safety Precautions Before Use** *(one precaution per line)*, then save.
   - Students immediately see the updated instructions on every new Digital Pass and inside `/student/account`!
3. **Add New Laboratory Equipment**:
   - Click **+ Add New Lab Item to Kiosk**.
   - Enter Name, Category, **Storage Compartment** *(matching one of your 12 locker compartments, e.g., `4th - 3rd Section` for Locker 12)*, Total Quantity, Safety Level, Usage & Safety lines, and optionally upload an apparatus photo directly from your PC.
4. **Logs, Exports & Safety LEDs**:
   - Use **Live Monitor & Borrow Logs** to search all active/overdue/returned transactions and download an Excel-ready CSV report.
   - Use **LED Safety Status Control** to switch the station between **`SAFE` (Green)**, **`CAUTION` (Yellow)**, and **`UNSAFE` (Red)** — updating both the Kiosk banner and physical GPIO LEDs in real time.

---

### 5.7 Technical Guide — Modifying & Testing All 12 GPIO Lock Pins in Admin Settings (Zero Coding!)

Open **`/admin`** → click **GPIO & Locker Hardware** in the sidebar. Every pin, relay polarity, pulse duration, and hardware test is controlled right in your browser and saved directly to SQLite!

1. **Board & Pin Factory Telemetry Header**:
   - Confirms detected board model (e.g., `Raspberry Pi 3 Model B Plus`), CPU architecture (`armv7l`), active `gpiozero` pin factory, and live mode badge (**`● Raspberry Pi GPIO Active`** in green vs **`○ Simulation Mode`** in amber).
2. **Interactive 40-Pin J8 Header Pinout Map**:
   - Displays all 40 physical pins (`1`–`40`) with live assignment badges (`L1`–`L12`, `G-LED`, `Y-LED`, `R-LED`, `BUZ`), live electrical voltage dots (`HIGH 3.3V` / `LOW 0V`), and peripheral bus badges (`I2C`, `SPI`, `UART`, `PWM`).
   - **Pre-Save Conflict Guard**: If you accidentally assign two enabled channels to the same BCM pin, both pins highlight in bright red and the backend blocks saving until the conflict is fixed.
3. **Global GPIO Controller Settings**:
   - **GPIO Driver Mode**: `auto` *(real Pi GPIO on Raspberry Pi, simulation on PC — recommended)*, `enabled` *(force Pi GPIO)*, or `simulation` *(software-only testing without firing relays)*.
   - **Default Unlock Pulse Duration**: `0.5` to `60.0` seconds (default **`5.0s`**). Keep pulses short (3–10s) so 12V solenoid coils never overheat!
   - **Auto-Unlock on Borrow / Return**: Toggle whether verified student checkouts and returns automatically pulse the matching locker channel.
4. **12-Channel Locker Lock Matrix & Status LED / Buzzer Map**:
   - For every locker (`1`–`12`) and indicator (`Green`, `Yellow`, `Red`, `Buzzer`), you can edit:
     - **BCM GPIO Pin**: Choose `BCM 2..27` or `Disabled`. The dropdown automatically displays the matching **Physical Pin** and warns you if a pin overlaps `[I2C1]`, `[SPI0]`, `[UART]`, or `[PWM0]`.
     - **Polarity**: Switch between **`Active-LOW (Relay)`** and **`Active-HIGH (Direct)`** per channel!
     - **Pulse (s)**: Custom unlock duration for each locker (`0.5–60s`).
     - **Enabled**: Uncheck to disable unused lockers cleanly.
   - **Bench-Test Buttons (Use While Wiring!):**
     - **`Pulse`** — Sends a timed unlock pulse (and auto-relocks when finished). Listen for the relay click and watch the solenoid bolt retract!
     - **`HIGH`** — Drives the GPIO pin directly to **`3.3V (HIGH)`** for multimeter / polarity checks.
     - **`LOW`** — Drives the GPIO pin directly to **`0V (LOW)`** to verify an Active-LOW relay engages.
   - Click **Save & Apply Live** — LabGuard+ saves your config to SQLite and rebinds the Raspberry Pi GPIO handles **immediately with zero reboot**!
5. **Emergency Controls, JSON Backups & Live Diagnostic Console**:
   - **Emergency Unlock All (5s)**: Pulses all enabled lockers open for 5 seconds (auto-relocks) — useful for cabinet inspection or lock jams.
   - **Force Relock All**: Cancels all active timers and immediately returns every locker to `LOCKED`.
   - **Reset Pi 2/3 Defaults**: Restores the conflict-free 16-pin default wiring table.
   - **Export JSON / Import JSON**: Download `labguard_gpio_config.json` as a backup or copy your exact wiring map onto another Raspberry Pi station.
   - **Live GPIO Diagnostic Event Console**: Streams the latest 30 GPIO events with exact UTC timestamp, channel, BCM pin, action, raw electrical level (`HIGH`/`LOW`), logical state (`UNLOCKED`/`LOCKED`), and source (`borrow`, `return`, `admin_test`, etc.).

---

## Part 6: Offline Wi-Fi / Hotspot, Local PC Runs, Maintenance & Beginner Troubleshooting

### Offline Lab Wi-Fi / Hotspot Setup (Zero Internet Required)

Once installed, LabGuard+ requires **zero internet access**. If your school laboratory has **no Wi-Fi** — or if school Wi-Fi blocks phone-to-Pi traffic (**AP / Client Isolation**) — choose either offline option:

#### Option 1: Dedicated Local Lab Wi-Fi Router (Easiest & Most Reliable)
1. Plug in any inexpensive Wi-Fi router in the laboratory (**no internet/WAN cable needed**).
2. Connect the Raspberry Pi (Wi-Fi or Ethernet cable), the Teacher/Admin PC, and student phones to that router's Wi-Fi.
3. Students scan the Kiosk QR codes and everything runs instantaneously over local Wi-Fi!

#### Option 2: Built-In Raspberry Pi Wi-Fi Hotspot (Pi 3B / 3B+ / 4B / 5 on Bookworm/Trixie)
Turn the Raspberry Pi itself into a standalone offline Wi-Fi access point using `nmcli`:

```bash
sudo nmcli device wifi hotspot ifname wlan0 ssid LabGuard-Station password labguard2026
```

Then lock QR codes to NetworkManager's default hotspot IP (`10.42.0.1`) in `/etc/default/labguard`:

```bash
sudo nano /etc/default/labguard
# Set:
#   APP_URL=http://10.42.0.1:5000
```

Restart LabGuard+:

```bash
sudo systemctl restart labguard
```

Students connect their smartphones to Wi-Fi **`LabGuard-Station`** (password `labguard2026`) and scan QR codes with zero internet needed!

---

### Running Locally on macOS, Linux, or Windows (No Raspberry Pi Needed)

Great for classroom demos, teacher training, or testing changes on a laptop — GPIO runs safely in **Simulation Mode**.

#### Option A: Python Backend (`app.py`) — Exact Raspberry Pi Runtime (Recommended)

- **macOS / Linux:**
  ```bash
  chmod +x run_local.sh
  ./run_local.sh
  ```
- **Windows:**
  Double-click **`run_local.bat`** (or run `run_local.bat` in Command Prompt / PowerShell).

Both scripts automatically create `.venv`, install `requirements.txt`, launch `app.py` on `http://localhost:5000`, and open the Kiosk UI (`?kiosk=1` previews the clean 7" Pi fullscreen layout).

#### Option B: Node.js / TypeScript Backend (`server.ts`)
```bash
npm install
npm run dev
```

#### Rebuilding the Offline Tailwind CSS Bundle (For Developers)
All templates load the local offline stylesheet at `public/css/labguard.css`. After editing Tailwind utility classes in `templates/*.html` or `src/styles/templates.css`, rebuild it with:

```bash
npm run build:css
```

---

### Everyday Raspberry Pi Service & Maintenance Commands

```bash
# Check backend status, restart after edits, or stop server
sudo systemctl status labguard
sudo systemctl restart labguard
sudo systemctl stop labguard

# Watch live server, QR checkout, and GPIO logs
journalctl -u labguard -f
```

- **Exit Fullscreen Kiosk on the Pi**: Plug in a USB keyboard and press **`Alt + F4`** or **`Ctrl + W`** to close Chromium. Press **`Ctrl + Alt + T`** to open a terminal, or SSH in from a PC (`ssh pi@labguard.local`).
- **Update LabGuard+ (Preserves Database, ID Photos & Settings)**:
  ```bash
  cd ~/LabGuard
  git pull
  sudo bash setup_raspberry_pi.sh
  ```
- **Reset Database to Factory Seed Data**:
  ```bash
  sudo systemctl stop labguard
  sudo rm -f /var/lib/labguard/labguard.db /var/lib/labguard/labguard.db-wal /var/lib/labguard/labguard.db-shm
  sudo systemctl start labguard
  ```
  *(LabGuard+ automatically recreates and re-seeds the SQLite database on next start.)*
- **Uninstall from Raspberry Pi**:
  ```bash
  # Removes service, kiosk autostart, and /opt/labguard (preserves DB & ID photos unless confirmed)
  sudo bash uninstall_raspberry_pi.sh

  # Or permanently delete everything including /var/lib/labguard (DB + id_photos/) and /etc/default/labguard
  sudo bash uninstall_raspberry_pi.sh --purge-data
  ```

---

### Beginner Troubleshooting FAQ

#### 1. Student's phone cannot open the scanned QR code URL ("Site can't be reached")
1. Make sure the phone and Raspberry Pi are connected to the **exact same Wi-Fi network** (turn OFF mobile data on the phone if it keeps switching away from offline lab Wi-Fi).
2. Check what URL the Pi is embedding in QR codes:
   ```bash
   curl http://localhost:5000/api/health
   ```
   Look at the `"lan_url"` field (e.g., `http://192.168.1.50:5000`).
3. **School Wi-Fi AP / Client Isolation**: Many campus Wi-Fi networks block phones from talking directly to other local devices. Fix this by using a **dedicated local lab router** or the **Pi Wi-Fi Hotspot** (see [Offline Lab Wi-Fi Setup](#offline-lab-wi-fi--hotspot-setup-zero-internet-required)).
4. If you enabled a firewall (`ufw`), allow port `5000`:
   ```bash
   sudo ufw allow 5000/tcp
   ```
5. To force a fixed IP or hostname in QR codes, set `APP_URL=http://<pi-ip>:5000` (or `APP_URL=http://labguard.local:5000`) in `/etc/default/labguard` and run `sudo systemctl restart labguard`.

#### 2. Relays behave backwards (locks stay UNLOCKED normally, and LOCK when pulsing!)
- Your relay board is **Active-HIGH** instead of Active-LOW (or vice versa).
- **Fix (10 seconds, zero wiring change)**: Open **`/admin`** → **GPIO & Locker Hardware** → switch the locker's Polarity dropdown between **`Active-LOW (Relay)`** and **`Active-HIGH (Direct)`** → click **Save & Apply Live**! Test with the **`Pulse`** button to confirm it clicks open for 5 seconds and then relocks.

#### 3. Relays don't click at all (or LEDs stay completely dark)
1. **Check the Common `GND` Wire!** Make sure a jumper wire connects a **Raspberry Pi `GND` pin (e.g. Pin 6)** to the **Relay Board `GND` pin** (and LED `-` short legs). Without a shared ground, the 3.3V GPIO signal has no return path and relays will never trigger!
2. **Check Separate Power Supplies**: Confirm the relay coils have **5V power (`JD-VCC` + `GND`)** and the solenoid lock screw terminals (`COM`/`NO`) have **12V DC power** turned ON.
3. **Check `hardware_mode`**: Run `curl http://localhost:5000/api/hardware/status` — confirm `"hardware_mode": "raspberry_pi_gpio"`. If it says `"simulation"`:
   - Open `/admin` → **GPIO & Locker Hardware** and make sure **GPIO Driver Mode** is set to `auto` or `enabled` (not `simulation`).
   - Run `groups` in the Pi terminal and verify `gpio` is listed — if you just installed LabGuard+, **reboot once** (`sudo reboot`) so the new `gpio` group membership takes effect.
4. **Double-Check BCM GPIO vs Physical Pin Numbers**: For example, Locker 1 is **BCM 5 = Physical Pin 29** (NOT Pin 5!). Re-check the [40-Pin Header Diagram](#visual-40-pin-j8-header-map-raspberry-pi-2--3--4--5).

#### 4. Raspberry Pi 2 or Pi 3 feels sluggish, or Chromium Kiosk closes unexpectedly (1 GB RAM)
1. Confirm you flashed **32-bit Raspberry Pi OS (with Desktop)** (`uname -m` should show `armv7l` or `armv6l` on 32-bit).
2. Increase swap memory to **1024 MB** so Chromium never runs out of memory on 1 GB RAM Pis:
   ```bash
   sudo dphys-swapfile swapoff
   sudo sed -i 's/^#\?CONF_SWAPSIZE=.*/CONF_SWAPSIZE=1024/' /etc/dphys-swapfile
   sudo dphys-swapfile setup
   sudo dphys-swapfile swapon
   free -m
   ```
   Confirm `Swap:` shows `~1024` MB in the `free -m` output, then reboot (`sudo reboot`).

#### 5. Student forgot their password, account is rejected, or account is suspended
- **Rejected Registration**: Ask the student to open `/student/register`, read the rejection reason using **Check Status**, and re-submit using the **exact same Student ID/LRN & school email** with a clearer School ID photo.
- **Pending or Suspended Account**: Open `/admin` → **Student Accounts**, find the student, and click **Approve** to activate or reinstate access.
- **Forgot Password**: If the student cannot log in to use **Change Password** in `/student/account`, the Lab Admin can open `/admin` → **Student Accounts**, remove the locked registration entry (or ask the student to re-register with a new password and approve their School ID again).

#### 6. Touchscreen still turns black / sleeps after being idle
Run `raspi-config` and disable display blanking system-wide, then reboot:

```bash
sudo raspi-config
```
Navigate to: **`2 Display Options`** → **`D4 Screen Blanking`** → select **`No`** → **`Finish`** → **`sudo reboot`**.
