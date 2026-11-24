# LabGuard+ — Smart Science Laboratory Safety Station & QR Equipment Kiosk

**Arellano University – Jose Rizal Campus (SHS & General Science Laboratory)**

**LabGuard+** is an offline-ready laboratory apparatus borrowing, accountability logging, and LED safety-monitoring station built for Raspberry Pi touchscreens and local computers.

Instead of making students type personal information on a small shared screen, LabGuard+ synchronizes **three specialized web interfaces** in real time over local Wi-Fi (with **zero internet required** after setup):

| Interface | URL | Device | What It Does |
| :--- | :--- | :--- | :--- |
| **1. Touchscreen Kiosk** | `http://localhost:5000/kiosk?kiosk=1` | Raspberry Pi 7" (`800×480`) Touchscreen | Tap-to-begin attract screen, Borrow/Return flows, on-screen QWERTY search keyboard, apparatus basket, Checkout QR generator, and privacy-masked returns (press-and-hold Eye reveal). |
| **2. Student Mobile Form** | `http://<pi-ip>:5000/student/checkout/<token>` | Student Smartphone | Opened by scanning the Kiosk Checkout QR code. Shows selected apparatus + safety instructions, returning-borrower presets, Strand/Faculty selector, custom return date/time, and an animated Digital Pass Receipt. |
| **3. PC Admin Console** | `http://<pi-ip>:5000/admin` | Lab Custodian / Teacher PC | Credential-gated dashboard with KPI cards, searchable borrow logs, Excel-ready CSV export, Equipment Inventory CRUD, and live Station LED Safety controls (`SAFE` / `CAUTION` / `UNSAFE`). |

> **Default Demo Admin Login (`/admin`)**: `lara.puertollano@arellano.edu.ph` / `au-jrc-2026`

### Key Raspberry Pi Capabilities
- **Primary Pi Backend (`app.py`)**: Python 3 + Flask + `flask-sock` WebSockets + SQLite3 (WAL mode) + `hardware/led_controller.py` GPIO controller.
- **100% Offline-Ready**: All styles (`/css/labguard.css`) and SVG apparatus icons (`/images/equipment/*.svg`) are bundled locally — no CDN or internet needed during class.
- **Automatic LAN IP Detection**: Checkout QR codes automatically embed your Pi's active LAN IP (or a custom `APP_URL` such as `http://labguard.local:5000`) so smartphones on the same Wi-Fi/hotspot open the form immediately.
- **Persistent Database**: Stored at `/var/lib/labguard/labguard.db` on Raspberry Pi so logs and inventory survive app updates and reboots.
- **Real GPIO Safety LEDs + Buzzer**: Automatically lights physical Green/Yellow/Red LEDs and optional buzzer on a Raspberry Pi, and safely falls back to software simulation on macOS/Windows/Linux PCs.

---

## Supported Hardware & Checklist

### Supported Raspberry Pi Models & OS
- **Models**: Raspberry Pi Zero 2 W, Pi 3B+, Pi 4B (2/4/8 GB), Pi 5 (4/8 GB)
- **Operating Systems**: **Raspberry Pi OS with Desktop** — **Bullseye, Bookworm, and Trixie (32-bit & 64-bit)** (works on both Wayland `labwc`/`wayfire` and X11 `LXDE`)

### Hardware Checklist
| Component | Recommendation | Required? |
| :--- | :--- | :--- |
| **Raspberry Pi** | Pi 4B or Pi 5 (Pi 3B+ / Zero 2 W also supported) | Required |
| **microSD Card** | 16 GB+ Class 10 / A1 (32 GB recommended) | Required |
| **Power Supply** | Official Raspberry Pi USB-C / Micro-USB power supply | Required |
| **Touchscreen Display** | Official 7" (`800×480`) DSI Touchscreen or any HDMI touchscreen | Required for Kiosk mode (`--no-kiosk` for headless server) |
| **3-Color LEDs + Buzzer** | 1× Green LED, 1× Yellow LED, 1× Red LED, 3× **220Ω–330Ω resistors**, optional 3.3V/5V Active Buzzer, female-to-female/breadboard jumper wires | Optional (simulated automatically if not wired) |

---

## Step-by-Step Raspberry Pi Installation (From Scratch)

### Step 1: Flash Raspberry Pi OS with Desktop
1. Download and open **Raspberry Pi Imager** on your computer.
2. Choose **Raspberry Pi Device** (your Pi model).
3. Choose **Operating System** → **Raspberry Pi OS (64-bit)** (with Desktop; use 32-bit for Pi Zero 2 W / 3B+ if preferred).
4. Choose your **microSD card**, click **Next**, and select **Edit Settings** (OS Customisation):
   - **Hostname**: `labguard` (allows accessing `http://labguard.local:5000`)
   - **Username & Password**: e.g., `pi` (remember these credentials)
   - **Configure Wireless LAN**: Enter your lab Wi-Fi SSID, password, and country (`PH`)
   - **Services**: Enable **SSH** (Use password authentication) so you can manage the Pi from another PC
5. Flash the SD card, insert it into the Raspberry Pi, and boot.
6. Verify **Desktop Auto-Login** is enabled (default on Raspberry Pi OS with Desktop; if needed, run `sudo raspi-config` → **System Options** → **Boot / Auto Login** → **Desktop Autologin**).

---

### Step 2: Connect the Display & Optional GPIO LEDs

Connect your 7" DSI or HDMI touchscreen before powering on.

If you are building the physical **3-Color LED Safety Status Display**, wire the LEDs while the Pi is powered off using the pin mapping below:

| Function | LabGuard+ Status | BCM GPIO | Physical Pin | Notes |
| :--- | :--- | :---: | :---: | :--- |
| **Green LED** | `SAFE` | `GPIO 17` | **Pin 11** | Connect through a **220Ω–330Ω resistor** |
| **Yellow LED** | `CAUTION` | `GPIO 27` | **Pin 13** | Connect through a **220Ω–330Ω resistor** |
| **Red LED** | `UNSAFE` | `GPIO 22` | **Pin 15** | Connect through a **220Ω–330Ω resistor** |
| **Active Buzzer** *(optional)* | Status / Checkout chirp | `GPIO 23` | **Pin 16** | Positive (`+`) leg to Pin 16, negative (`-`) to GND |
| **Common Ground** | `GND` | `GND` | **Pin 6, 9, or 14** | Connects to all LED cathodes (short legs) & buzzer `-` |

> **Important Wiring Reminder:** Always place a **220Ω–330Ω current-limiting resistor** in series with each LED (GPIO pin → resistor → LED long leg / anode `+` → LED short leg / cathode `-` → GND). Connecting an LED directly without a resistor can damage the Raspberry Pi GPIO pin.
>
> Don't have LEDs yet? No problem — LabGuard+ runs cleanly without them and displays live LED status on screen.

---

### Step 3: Clone LabGuard+ on the Raspberry Pi

Open a terminal on the Raspberry Pi (or SSH into it: `ssh pi@labguard.local`) and run:

```bash
git clone https://github.com/cGradying/LabGuard.git
cd LabGuard
```

*(Forked from [intmatt-0/AU-LabGuard-](https://github.com/intmatt-0/AU-LabGuard-).)*

---

### Step 4: Run the Automated Installer

Run the installer with `sudo`:

```bash
sudo bash setup_raspberry_pi.sh
```

What this automatically does:
- Installs Python 3, `venv`, `gpiozero` (+ `lgpio` on Pi 5), Pillow, `rsync`, `avahi-daemon`, and Chromium (`chromium` on Bookworm/Trixie or `chromium-browser` on Bullseye).
- Deploys the app to `/opt/labguard` with an isolated PEP 668–compliant `.venv` (inheriting system GPIO libraries) and persistent database directory `/var/lib/labguard`.
- Creates `/etc/default/labguard` (preserving your edits on future re-runs).
- Registers, enables, and starts `labguard.service` via `systemd` and checks `http://localhost:5000/api/health`.
- Configures fullscreen Chromium kiosk autostart (`~/labguard_kiosk.sh` + `~/.config/autostart/labguard-kiosk.desktop`) targeting `http://localhost:5000/kiosk?kiosk=1` (hides desktop simulator toolbars automatically) and disables screen blanking.

#### Optional Installer Flags
```bash
# Headless / server-only Pi (no Chromium kiosk autostart)
sudo bash setup_raspberry_pi.sh --no-kiosk

# Custom port and fixed mDNS QR URL
sudo bash setup_raspberry_pi.sh --port 8080 --app-url http://labguard.local:8080
```

---

### Step 5: Reboot & Verify Everything

```bash
sudo reboot
```

After reboot:
1. **Touchscreen Kiosk**: The 7" screen boots straight into the LabGuard+ Kiosk (`http://localhost:5000/kiosk?kiosk=1`) with no browser address bar or desktop toolbar.
2. **Student Phone QR Checkout**:
   - Connect a smartphone to the **same Wi-Fi network (or hotspot)** as the Raspberry Pi.
   - On the kiosk, tap **Borrow Equipment**, add an item, tap **Generate Checkout QR**, and scan the QR code with the phone's camera.
   - Submit the mobile form — the kiosk updates in real time!
3. **PC Admin Console**:
   - On a teacher/custodian PC on the same network, open `http://labguard.local:5000/admin` (or `http://<pi-ip>:5000/admin`).
   - Sign in with `lara.puertollano@arellano.edu.ph` / `au-jrc-2026`.
   - Test toggling `SAFE`, `CAUTION`, and `UNSAFE` to see both the kiosk banner and physical GPIO LEDs update immediately.
4. **Health & Hardware Status APIs**:
   - `curl http://localhost:5000/api/health`
   - `curl http://localhost:5000/api/hardware/status`

---

## Configuring `/etc/default/labguard`

All Raspberry Pi runtime settings live in `/etc/default/labguard`:

```bash
sudo nano /etc/default/labguard
```

```ini
# HTTP server port
PORT=5000

# Fixed public URL for Checkout QR codes (blank = auto-detect LAN IP)
# Uncomment if you want QR codes to always use mDNS or a fixed hotspot IP:
# APP_URL=http://labguard.local:5000

# Persistent SQLite database path
LABGUARD_DB_PATH=/var/lib/labguard/labguard.db

# GPIO LED & Buzzer settings (BCM pin numbers)
LABGUARD_GPIO_ENABLED=auto   # auto | 1 | 0 (set 0 to disable physical GPIO)
LABGUARD_LED_GREEN_PIN=17
LABGUARD_LED_YELLOW_PIN=27
LABGUARD_LED_RED_PIN=22
LABGUARD_BUZZER_PIN=23       # set to 0 or none to disable buzzer pin
LABGUARD_BUZZER_ENABLED=1
LABGUARD_LED_ACTIVE_HIGH=1   # set to 0 for active-low relay modules
```

Apply any changes by restarting the service:

```bash
sudo systemctl restart labguard
```

---

## Optional: Offline / Local Wi-Fi Hotspot Tips (No Internet Required)

Once installed, LabGuard+ needs **zero internet access**. All CSS, SVG apparatus icons, QR generation, and SQLite data run locally on the Pi.

If your school laboratory has **no Wi-Fi** — or if school Wi-Fi blocks phone-to-Pi connections (**AP / Client Isolation**) — use one of these two offline setups:

1. **Dedicated Local Wi-Fi Router (Simplest)**:
   - Plug in any inexpensive Wi-Fi router in the lab (no WAN/internet cable needed).
   - Connect the Raspberry Pi, Admin PC, and student phones to that router's Wi-Fi.
2. **Built-in Raspberry Pi Wi-Fi Hotspot (Bookworm / Trixie NetworkManager)**:
   - Turn the Pi itself into a standalone lab access point:
     ```bash
     sudo nmcli device wifi hotspot ifname wlan0 ssid LabGuard-Station password labguard2026
     ```
   - Set `APP_URL=http://10.42.0.1:5000` in `/etc/default/labguard` (NetworkManager's default hotspot gateway IP) and run `sudo systemctl restart labguard`.
   - Students connect their phones to `LabGuard-Station` and scan the Kiosk QR code with zero internet needed!

---

## Running Locally on macOS, Linux, or Windows

### Option A: Python Backend (`app.py`) — Matches Raspberry Pi (Recommended)

**macOS / Linux:**
```bash
chmod +x run_local.sh
./run_local.sh
```

**Windows:**
Double-click `run_local.bat` (or run `run_local.bat` in Command Prompt / PowerShell).

Both scripts automatically create a local `.venv`, install `requirements.txt`, start `app.py` on `http://localhost:5000`, and open the Kiosk UI in your browser.
- Kiosk UI: `http://localhost:5000/kiosk` (append `?kiosk=1` to preview the clean Pi fullscreen mode)
- Admin Console: `http://localhost:5000/admin`
- Hardware status: runs safely in software simulation mode on non-Pi computers.

### Option B: Node.js / TypeScript Backend (`server.ts`)
```bash
npm install
npm run dev
```

### Rebuilding Offline Tailwind CSS (For Developers Editing Templates/Styles)
The templates load the pre-compiled offline stylesheet at `public/css/labguard.css`. If you modify utility classes in `templates/*.html` or `src/styles/templates.css`, rebuild the bundle with:
```bash
npm run build:css
```

---

## Day-to-Day Management & Troubleshooting

### Service & Log Commands
```bash
sudo systemctl status labguard      # Check if backend is running
sudo systemctl restart labguard     # Restart after config changes
sudo systemctl stop labguard        # Stop backend
journalctl -u labguard -f           # Stream live server & GPIO logs
```

### Updating LabGuard+ on the Raspberry Pi
Re-running the installer updates `/opt/labguard` while **preserving** `/var/lib/labguard/labguard.db` and `/etc/default/labguard`:
```bash
cd ~/LabGuard
git pull
sudo bash setup_raspberry_pi.sh
```

### Exiting Fullscreen Kiosk Mode on the Pi
- Press **`Alt + F4`** or **`Ctrl + W`** on a connected keyboard to close Chromium.
- Press **`Ctrl + Alt + T`** to open a terminal, or SSH in from another PC (`ssh pi@labguard.local`).

### Resetting the Database to Factory Seed Data
```bash
sudo systemctl stop labguard
sudo rm -f /var/lib/labguard/labguard.db /var/lib/labguard/labguard.db-wal /var/lib/labguard/labguard.db-shm
sudo systemctl start labguard
```
LabGuard+ automatically recreates and re-seeds the SQLite database on next start.

### Troubleshooting

- **Phone cannot open the scanned QR code URL:**
  1. Confirm the phone and Raspberry Pi are on the **exact same Wi-Fi network**.
  2. Check what URL the Pi is advertising: `curl http://localhost:5000/api/health` (look at `lan_url`).
  3. Some school Wi-Fi networks enable **AP / Client Isolation** (blocking devices from talking to each other). Use a dedicated local router or Pi Wi-Fi Hotspot (see section above).
  4. If your network uses a firewall (`ufw`), allow port 5000: `sudo ufw allow 5000/tcp`.
  5. To force a specific host/IP in QR codes, set `APP_URL=http://<pi-ip>:5000` or `APP_URL=http://labguard.local:5000` in `/etc/default/labguard` and restart `labguard`.
- **GPIO LEDs do not light up:**
  1. Check `curl http://localhost:5000/api/hardware/status` — verify `hardware_mode` is `"raspberry_pi_gpio"` (not `"simulation"`).
  2. Verify the Pi user is in the `gpio` group (`groups`) and reboot after first install.
  3. Double-check **BCM GPIO numbers vs Physical Pin numbers** in the wiring table, LED polarity (long leg `+`, short leg `-` to GND), and 220Ω–330Ω resistors.
  4. If using an active-low relay module instead of direct LEDs, set `LABGUARD_LED_ACTIVE_HIGH=0` in `/etc/default/labguard` and restart.
- **Screen still turns black after idle:**
  - Run `sudo raspi-config` → **Display Options** → **Screen Blanking** → **No**, then reboot.

### Uninstalling from Raspberry Pi
```bash
# Removes service, kiosk autostart, and /opt/labguard (asks before deleting database)
sudo bash uninstall_raspberry_pi.sh

# Or remove everything including /var/lib/labguard/labguard.db and /etc/default/labguard
sudo bash uninstall_raspberry_pi.sh --purge-data
```
