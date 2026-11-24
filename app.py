#!/usr/bin/env python3
"""
LabGuard+: A Smart Science Laboratory Safety Station with QR Code Equipment Tracking,
QR-Based User Log-In Monitoring, and LED Safety Status Display
Arellano University - Jose Rizal Campus (Senior High School Department)

Full-Blown Python Flask + SQLite3 + WebSocket + Raspberry Pi GPIO Web Application
serving 3 separate HTML files:
  1. templates/kiosk.html        -> GET /, /kiosk, /kiosk.html (Student Kiosk UI)
  2. templates/student_form.html -> GET /student/checkout/<token>, /student_form.html (QR Mobile Form)
  3. templates/admin.html        -> GET /admin, /admin.html (Admin & Lab Personnel Dashboard)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html as html_lib
import io
import json
import logging
import os
import random
import re
import secrets
import socket
import sqlite3
import string
import threading
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Dict, Optional, Set, Tuple
from urllib.parse import urlsplit

from flask import Flask, Response, g, jsonify, render_template, request, send_from_directory

from hardware.led_controller import SafetyLEDController

try:
    import qrcode
except ImportError:
    qrcode = None

try:
    from flask_sock import Sock
except ImportError:
    Sock = None  # type: ignore

logging.basicConfig(
    level=os.environ.get("LABGUARD_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("labguard.server")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "labguard.db")
PUBLIC_DIR = os.path.join(BASE_DIR, "public")

DEFAULT_ADMIN_EMAIL = "lara.puertollano@arellano.edu.ph"
DEFAULT_ADMIN_PASSWORD = "au-jrc-2026"
DEFAULT_ADMIN_NAME = "Ms. Lara Marie A. Puertollano"

PBKDF2_ITERATIONS = 120000
MAX_ID_PHOTO_BYTES = 4 * 1024 * 1024  # 4 MB
ADMIN_SESSION_HOURS = 24
STUDENT_SESSION_DAYS = 7
VALID_GRADE_SECTIONS = ("STEM", "HUMSS", "ABM", "FACULTY")
VALID_STUDENT_STATUSES = ("pending", "approved", "rejected", "suspended")

IMAGE_DATA_URL_RE = re.compile(
    r"^data:image/(jpeg|jpg|png|webp|svg\+xml);base64,([A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
MIME_TO_EXT = {
    "jpeg": "jpg",
    "jpg": "jpg",
    "png": "png",
    "webp": "webp",
    "svg+xml": "svg",
}
EXT_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB max JSON payload for 4 MB base64 images
sock = Sock(app) if Sock is not None else None

# Hardware GPIO / Simulation LED & Buzzer controller
led_controller = SafetyLEDController()

# Thread-safe WebSocket client registries
_ws_lock = threading.Lock()
_global_ws_clients: Set[Any] = set()
_checkout_ws_clients: Dict[str, Set[Any]] = {}

# Lazy/startup DB initialization guard (keyed by resolved DB path)
_db_init_lock = threading.Lock()
_db_initialized_path: Optional[str] = None

SAFETY_PRESETS = {
    "SAFE": {
        "headline": "LED STATUS: GREEN — LABORATORY SAFE FOR OPERATION",
        "message": "Standard laboratory operations active. Scan equipment QR codes and complete student log-in before handling science materials.",
    },
    "CAUTION": {
        "headline": "LED STATUS: YELLOW — CAUTION · PPE & SUPERVISION REQUIRED",
        "message": "Caution alert active: inspect reported damaged/missing apparatus or supervise active thermal and glassware experiments. Laboratory PPE is mandatory.",
    },
    "UNSAFE": {
        "headline": "LED STATUS: RED — UNSAFE · RESTRICTED LABORATORY ACCESS",
        "message": "Breakage, chemical spill, or maintenance alert reported. Equipment checkout is paused until cleared by Laboratory Personnel.",
    },
}

STUDENT_PRESETS = [
    {
        "id": 1,
        "student_name": "One Enrique Sebastian G. Abalos",
        "student_id_lrn": "AUJRC-2026-0101",
        "grade_section": "STEM",
        "school_email": "one.abalos@arellano.edu.ph",
        "default_subject": "General Biology 1 — Microscopy & Cell Structure",
        "default_teacher": "Ms. Lara Marie Agustin Puertollano",
    },
    {
        "id": 2,
        "student_name": "Christine S. Contreras",
        "student_id_lrn": "AUJRC-2026-0102",
        "grade_section": "STEM",
        "school_email": "christine.contreras@arellano.edu.ph",
        "default_subject": "General Chemistry 2 — Solution Prep & Heating Lab",
        "default_teacher": "Ms. Lara Marie Agustin Puertollano",
    },
    {
        "id": 3,
        "student_name": "Queen Hannah A. Dones",
        "student_id_lrn": "AUJRC-2026-0103",
        "grade_section": "HUMSS",
        "school_email": "queenhannah.dones@arellano.edu.ph",
        "default_subject": "General Science — Volumetric Measurement Lab",
        "default_teacher": "Ms. Lara Marie Agustin Puertollano",
    },
    {
        "id": 4,
        "student_name": "Collin Lenard M. Marcos",
        "student_id_lrn": "AUJRC-2026-0104",
        "grade_section": "ABM",
        "school_email": "collin.marcos@arellano.edu.ph",
        "default_subject": "Applied Research — Material Inventory Accounting",
        "default_teacher": "Ms. Lara Marie Agustin Puertollano",
    },
    {
        "id": 5,
        "student_name": "Ashlyjicks B. Pangilinan",
        "student_id_lrn": "AUJRC-2026-0105",
        "grade_section": "STEM",
        "school_email": "ashlyjicks.pangilinan@arellano.edu.ph",
        "default_subject": "General Chemistry 1 — Quantitative Solution Prep",
        "default_teacher": "Ms. Lara Marie Agustin Puertollano",
    },
    {
        "id": 6,
        "student_name": "Ms. Lara Marie Puertollano",
        "student_id_lrn": "AUJRC-FAC-0001",
        "grade_section": "FACULTY",
        "school_email": "lara.puertollano@arellano.edu.ph",
        "default_subject": "Science Laboratory Demonstration & Research",
        "default_teacher": "Self / Laboratory In-Charge",
    },
]

INITIAL_EQUIPMENT_SEED = [
    (
        1,
        "LG-EQ-001",
        "Beaker",
        "Glassware & Measuring",
        "/images/equipment/LG-EQ-001.svg",
        "Heat-resistant borosilicate glass beaker for mixing, heating, and approximate liquid volume measurement.",
        "1st - 1st Section",
        12,
        10,
        "pc",
        "Good",
        "SAFE",
        json.dumps([
            "Inspect glassware for chips or hairline cracks before pouring liquids",
            "Use wire gauze on a tripod stand when heating over a flame",
            "Rinse and dry thoroughly prior to returning to 1st - 1st Section",
        ]),
    ),
    (
        2,
        "LG-EQ-002",
        "Graduated Cylinder",
        "Glassware & Measuring",
        "/images/equipment/LG-EQ-002.svg",
        "Calibrated cylindrical glassware with hexagonal stability base for precise liquid volume measurement.",
        "2nd - 1st Section",
        10,
        9,
        "pc",
        "Good",
        "SAFE",
        json.dumps([
            "Place on a level laboratory bench and read the bottom of the meniscus at eye level",
            "Never heat graduated cylinders directly over a burner",
            "Rinse with distilled water before returning to 2nd - 1st Section",
        ]),
    ),
    (
        3,
        "LG-EQ-003",
        "Florence Flask",
        "Glassware & Measuring",
        "/images/equipment/LG-EQ-003.svg",
        "Round-bodied borosilicate boiling flask with slender neck designed for uniform heating and swirling of liquids.",
        "3rd - 1st Section",
        8,
        8,
        "pc",
        "Good",
        "CAUTION",
        json.dumps([
            "Wear buttoned laboratory gown and chemical splash goggles",
            "Support on wire gauze over a tripod stand or clamp neck securely",
            "Allow hot flask to cool completely before handling or returning to 3rd - 1st Section",
        ]),
    ),
    (
        4,
        "LG-EQ-004",
        "Glass Funnel",
        "Glassware & Measuring",
        "/images/equipment/LG-EQ-004.svg",
        "Conical borosilicate glass funnel with narrow stem for clean liquid transfer and gravity filtration.",
        "4th - 1st Section",
        10,
        10,
        "pc",
        "Good",
        "SAFE",
        json.dumps([
            "Seat folded filter paper snugly inside the cone when filtering mixtures",
            "Support funnel stem cleanly inside receiving flask to prevent tipping",
            "Wash and dry after reagent transfer before returning to 4th - 1st Section",
        ]),
    ),
    (
        5,
        "LG-EQ-005",
        "Erlenmeyer Flask",
        "Glassware & Measuring",
        "/images/equipment/LG-EQ-005.svg",
        "Conical flat-bottomed laboratory flask ideal for titration, swirling solutions, and preventing reagent splash.",
        "1st - 2nd Section",
        12,
        10,
        "pc",
        "Good",
        "SAFE",
        json.dumps([
            "Inspect rim and base for cracks prior to use",
            "Swirl gently by holding the narrow neck to mix reagents without spilling",
            "Rinse and place dry flask back in 1st - 2nd Section",
        ]),
    ),
    (
        6,
        "LG-EQ-006",
        "Test Tube, Holder & Rack Set",
        "Glassware & Measuring",
        "/images/equipment/LG-EQ-006.svg",
        "Complete small-scale reaction kit including glass test tubes, spring-wire test tube holder clamp, and multi-slot rack.",
        "2nd - 2nd Section",
        8,
        8,
        "set",
        "Good",
        "SAFE",
        json.dumps([
            "Always keep test tubes upright in the rack when unattended",
            "Use the test tube holder when warming samples and point opening away from peers",
            "Clean all tubes and return complete set to 2nd - 2nd Section",
        ]),
    ),
    (
        7,
        "LG-EQ-007",
        "Tripod Stand",
        "Heating & Thermal",
        "/images/equipment/LG-EQ-007.svg",
        "Heavy-duty cast-iron three-legged laboratory support stand used to hold beakers and flasks during heating.",
        "3rd - 2nd Section",
        8,
        7,
        "unit",
        "Good",
        "CAUTION",
        json.dumps([
            "Place on a level, heat-resistant workbench away from flammable items",
            "Center wire gauze securely on top ring before placing glassware",
            "Allow iron frame to cool completely before returning to 3rd - 2nd Section",
        ]),
    ),
    (
        8,
        "LG-EQ-008",
        "Bell Jar",
        "Glassware & Measuring",
        "/images/equipment/LG-EQ-008.svg",
        "Thick-walled domed glass bell jar with top knob handle for vacuum, pressure, and sealed atmospheric demonstrations.",
        "4th - 2nd Section",
        4,
        4,
        "unit",
        "Good",
        "SAFE",
        json.dumps([
            "Lift firmly with both hands using the top knob and lower rim",
            "Ensure smooth rim seal on the base plate before air evacuation",
            "Handle carefully and store upright inside 4th - 2nd Section",
        ]),
    ),
    (
        9,
        "LG-EQ-009",
        "Laboratory Gown",
        "Safety & PPE",
        "/images/equipment/LG-EQ-009.svg",
        "Protective white long-sleeve laboratory coat designed to shield clothing and skin from chemical splashes.",
        "1st - 3rd Section",
        15,
        13,
        "pc",
        "Good",
        "SAFE",
        json.dumps([
            "Button the laboratory gown completely from collar to hem before working",
            "Check sleeves and pockets are clear of loose flammable items",
            "Fold neatly and hang back inside 1st - 3rd Section after session",
        ]),
    ),
    (
        10,
        "LG-EQ-010",
        "Stirring Rod & PPE Kit (Glasses, Facemask, Gloves)",
        "Safety & PPE",
        "/images/equipment/LG-EQ-010.svg",
        "Combined reagent-handling and personal protection kit containing borosilicate stirring rod, PPE safety glasses, facemask, and gloves.",
        "2nd - 3rd Section",
        15,
        14,
        "kit",
        "Good",
        "SAFE",
        json.dumps([
            "Put on PPE glasses, facemask, and gloves before handling any chemicals",
            "Use glass stirring rod gently—do not strike beaker walls or bottom",
            "Sanitize PPE glasses and stirring rod before returning to 2nd - 3rd Section",
        ]),
    ),
    (
        11,
        "LG-EQ-011",
        "Compound Light Microscope",
        "Optical & Microscopy",
        "/images/equipment/LG-EQ-011.svg",
        "Binocular biological compound microscope with 4x, 10x, 40x, and 100x objectives and LED stage illumination.",
        "3rd - 3rd Section",
        8,
        6,
        "unit",
        "Good",
        "SAFE",
        json.dumps([
            "Carry microscope with two hands (one on arm, one under base)",
            "Clean objective lenses with optical lens paper only",
            "Lower stage to bottom, select 4x objective, and return to 3rd - 3rd Section",
        ]),
    ),
]


# ==============================================================================
# NETWORK & CONFIGURATION HELPERS
# ==============================================================================
def get_server_port() -> int:
    raw = os.environ.get("PORT") or os.environ.get("FLASK_PORT") or "5000"
    try:
        return int(raw)
    except ValueError:
        return 5000


def get_db_path() -> str:
    env_path = (os.environ.get("LABGUARD_DB_PATH") or "").strip()
    return env_path if env_path else DEFAULT_DB_PATH


def get_data_dir() -> str:
    env_dir = (os.environ.get("LABGUARD_DATA_DIR") or "").strip()
    if env_dir:
        return os.path.abspath(env_dir)
    db_dir = os.path.dirname(os.path.abspath(get_db_path()))
    return db_dir or BASE_DIR


def get_id_photos_dir() -> str:
    photos_dir = os.path.join(get_data_dir(), "id_photos")
    os.makedirs(photos_dir, exist_ok=True)
    return photos_dir


def get_admin_email() -> str:
    return (os.environ.get("LABGUARD_ADMIN_EMAIL") or DEFAULT_ADMIN_EMAIL).strip()


def get_admin_password() -> str:
    return os.environ.get("LABGUARD_ADMIN_PASSWORD") or DEFAULT_ADMIN_PASSWORD


def get_admin_name() -> str:
    return (os.environ.get("LABGUARD_ADMIN_NAME") or DEFAULT_ADMIN_NAME).strip()


def _parse_iso_utc(iso_str: Optional[str]) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with a 16-byte random salt."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time verification of a PBKDF2-HMAC-SHA256 password hash."""
    try:
        algo, iter_str, salt_hex, expected_hex = stored_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
        if iterations < 1:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
        if not salt or not expected:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _build_sample_school_id_svg(
    full_name: str,
    student_id_lrn: str,
    grade_section: str,
    school_email: str,
    status: str,
) -> str:
    parts = [p for p in full_name.strip().split() if p]
    if len(parts) >= 2:
        initials = (parts[0][0] + parts[-1][0]).upper()
    else:
        initials = (full_name[:2] or "AU").upper()

    badge_color = "#16A34A" if status == "approved" else "#F5A623"
    badge_label = "VERIFIED STUDENT ID" if status == "approved" else "SAMPLE ID · PENDING REVIEW"

    esc_name = html_lib.escape(full_name)
    esc_lrn = html_lib.escape(student_id_lrn)
    esc_strand = html_lib.escape(grade_section)
    esc_email = html_lib.escape(school_email)
    esc_initials = html_lib.escape(initials)
    esc_badge = html_lib.escape(badge_label)

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 400" width="640" height="400">\n'
        "  <defs>\n"
        '    <linearGradient id="auHdr" x1="0" y1="0" x2="1" y2="1">\n'
        '      <stop offset="0%" stop-color="#002366"/>\n'
        '      <stop offset="100%" stop-color="#003087"/>\n'
        "    </linearGradient>\n"
        "  </defs>\n"
        '  <rect width="640" height="400" rx="22" fill="#F8FAFC" stroke="#CBD5E1" stroke-width="4"/>\n'
        '  <path d="M22 0 H618 A22 22 0 0 1 640 22 V102 H0 V22 A22 22 0 0 1 22 0 Z" fill="url(#auHdr)"/>\n'
        '  <rect x="0" y="102" width="640" height="8" fill="#C8102E"/>\n'
        '  <circle cx="58" cy="52" r="30" fill="#FFFFFF" stroke="#F5A623" stroke-width="4"/>\n'
        '  <text x="58" y="59" text-anchor="middle" font-family="system-ui, -apple-system, sans-serif" font-size="22" font-weight="800" fill="#003087">AU</text>\n'
        '  <text x="104" y="44" font-family="system-ui, -apple-system, sans-serif" font-size="22" font-weight="800" fill="#FFFFFF" letter-spacing="0.5">ARELLANO UNIVERSITY</text>\n'
        '  <text x="104" y="68" font-family="system-ui, -apple-system, sans-serif" font-size="13" font-weight="600" fill="#DBEAFE">JOSE RIZAL CAMPUS · SENIOR HIGH SCHOOL DEPARTMENT</text>\n'
        '  <text x="104" y="88" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" fill="#FDE68A" letter-spacing="1.2">OFFICIAL STUDENT IDENTIFICATION CARD · S.Y. 2025-2026</text>\n'
        '  <rect x="28" y="132" width="142" height="174" rx="14" fill="#E2E8F0" stroke="#94A3B8" stroke-width="2"/>\n'
        '  <circle cx="99" cy="190" r="34" fill="#003087"/>\n'
        '  <path d="M52 288 C52 248 146 248 146 288 Z" fill="#003087"/>\n'
        f'  <text x="99" y="199" text-anchor="middle" font-family="system-ui, -apple-system, sans-serif" font-size="24" font-weight="800" fill="#FFFFFF">{esc_initials}</text>\n'
        '  <rect x="28" y="316" width="142" height="28" rx="8" fill="#003087"/>\n'
        f'  <text x="99" y="335" text-anchor="middle" font-family="system-ui, -apple-system, sans-serif" font-size="13" font-weight="800" fill="#FFFFFF">{esc_strand}</text>\n'
        '  <text x="196" y="156" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" fill="#64748B" letter-spacing="1">STUDENT FULL NAME</text>\n'
        f'  <text x="196" y="184" font-family="system-ui, -apple-system, sans-serif" font-size="22" font-weight="800" fill="#0F172A">{esc_name}</text>\n'
        '  <text x="196" y="218" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" fill="#64748B" letter-spacing="1">STUDENT ID / LRN</text>\n'
        f'  <text x="196" y="244" font-family="ui-monospace, SFMono-Regular, monospace" font-size="20" font-weight="800" fill="#003087">{esc_lrn}</text>\n'
        '  <text x="196" y="276" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" fill="#64748B" letter-spacing="1">INSTITUTIONAL EMAIL</text>\n'
        f'  <text x="196" y="298" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="600" fill="#334155">{esc_email}</text>\n'
        f'  <rect x="196" y="316" width="248" height="28" rx="14" fill="{badge_color}"/>\n'
        f'  <text x="320" y="335" text-anchor="middle" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="800" fill="#FFFFFF" letter-spacing="0.8">{esc_badge}</text>\n'
        '  <rect x="0" y="364" width="640" height="36" fill="#0F172A"/>\n'
        '  <text x="28" y="387" font-family="ui-monospace, SFMono-Regular, monospace" font-size="12" font-weight="600" fill="#E2E8F0">AU-JRC SCIENCE LABORATORY · LABGUARD+ VERIFIED CREDENTIAL</text>\n'
        "</svg>\n"
    )


def _resolve_safe_photo_path(filename: str) -> Optional[str]:
    """Resolve an ID photo filename strictly inside get_id_photos_dir() (no traversal)."""
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return None
    if os.path.basename(filename) != filename:
        return None
    photos_dir = os.path.realpath(get_id_photos_dir())
    target = os.path.realpath(os.path.join(photos_dir, filename))
    if not target.startswith(photos_dir + os.sep):
        return None
    return target


def _photo_file_exists(filename: str) -> bool:
    path = _resolve_safe_photo_path(filename)
    return bool(path and os.path.isfile(path))


def _delete_photo_file_safe(filename: Optional[str]) -> None:
    if not filename:
        return
    path = _resolve_safe_photo_path(filename)
    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _save_id_photo_from_data_url(
    student_id_lrn: str, data_url: str
) -> Tuple[Optional[str], Optional[str]]:
    """Validate and save a base64 image data URL into id_photos/ with a sanitized filename."""
    match = IMAGE_DATA_URL_RE.match((data_url or "").strip())
    if not match:
        return (
            None,
            "Please upload a valid School ID image (JPEG, PNG, WEBP, or SVG data URL required).",
        )
    mime_sub = match.group(1).lower()
    ext = MIME_TO_EXT.get(mime_sub)
    if not ext:
        return None, "Unsupported School ID image format."

    b64_clean = re.sub(r"\s+", "", match.group(2))
    try:
        raw_bytes = base64.b64decode(b64_clean, validate=True)
    except Exception:
        return None, "Invalid base64 image data for School ID photo."

    if not raw_bytes:
        return None, "Uploaded School ID image is empty."
    if len(raw_bytes) > MAX_ID_PHOTO_BYTES:
        return None, "School ID photo exceeds the 4 MB maximum file size."

    safe_lrn = re.sub(r"[^A-Z0-9_-]+", "_", student_id_lrn.upper()).strip("_")[:40] or "STUDENT"
    filename = f"{safe_lrn}_{secrets.token_hex(6)}.{ext}"
    full_path = _resolve_safe_photo_path(filename)
    if not full_path:
        return None, "Could not resolve a safe storage path for the School ID photo."

    with open(full_path, "wb") as fp:
        fp.write(raw_bytes)
    return filename, None


def _is_usable_lan_ip(ip: str) -> bool:
    if not ip:
        return False
    if ip.startswith("127.") or ip == "0.0.0.0" or ip.startswith("169.254."):
        return False
    return True


def detect_lan_ip() -> Optional[str]:
    """Detect the active non-loopback LAN IPv4 address for mobile QR scanning."""
    for target in (("8.8.8.8", 80), ("10.255.255.255", 1)):
        sock_udp = None
        try:
            sock_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock_udp.settimeout(0.5)
            sock_udp.connect(target)
            ip = sock_udp.getsockname()[0]
            if _is_usable_lan_ip(ip):
                return ip
        except OSError:
            pass
        finally:
            if sock_udp is not None:
                try:
                    sock_udp.close()
                except OSError:
                    pass

    try:
        host_ip = socket.gethostbyname(socket.gethostname())
        if _is_usable_lan_ip(host_ip):
            return host_ip
    except OSError:
        pass

    return None


def resolve_public_base_url(req: Any = None) -> str:
    """
    Resolve the phone-reachable base URL (e.g. http://192.168.1.42:5000).
    Priority:
      1. APP_URL or LABGUARD_PUBLIC_URL environment variable.
      2. If incoming request host is loopback/unspecified, substitute detected LAN IP.
      3. Otherwise preserve the incoming request host (LAN IP, .local mDNS, or domain).
    """
    env_url = (
        os.environ.get("APP_URL") or os.environ.get("LABGUARD_PUBLIC_URL") or ""
    ).strip().rstrip("/")
    if env_url:
        return env_url

    if req is None:
        lan_ip = detect_lan_ip() or "127.0.0.1"
        return f"http://{lan_ip}:{get_server_port()}"

    forwarded_proto = (req.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
    scheme = forwarded_proto or getattr(req, "scheme", None) or "http"

    forwarded_host = (req.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
    raw_host = forwarded_host or getattr(req, "host", "") or f"localhost:{get_server_port()}"

    parsed = urlsplit(f"{scheme}://{raw_host}")
    hostname = (parsed.hostname or "").lower()
    port = parsed.port

    if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        lan_ip = detect_lan_ip()
        if lan_ip:
            if port is not None:
                return f"{scheme}://{lan_ip}:{port}"
            return f"{scheme}://{lan_ip}"

    return f"{scheme}://{raw_host}".rstrip("/")


# ==============================================================================
# DATABASE & HARDWARE SYNC HELPERS
# ==============================================================================
def get_db() -> sqlite3.Connection:
    db_path = get_db_path()
    parent_dir = os.path.dirname(os.path.abspath(db_path))
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=15000;")
    return conn


def serialize_safety_status(row: Optional[sqlite3.Row]) -> Dict[str, Any]:
    if not row:
        return {
            "level": "SAFE",
            "headline": SAFETY_PRESETS["SAFE"]["headline"],
            "message": SAFETY_PRESETS["SAFE"]["message"],
            "updated_by": "Ms. Lara Marie Agustin Puertollano (Research Adviser / Lab Coordinator)",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    return {
        "level": row["level"],
        "headline": row["headline"],
        "message": row["message"],
        "updated_by": row["updated_by"],
        "updated_at": row["updated_at"],
    }


def get_current_safety_status(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    owns_conn = conn is None
    if conn is None:
        conn = get_db()
    try:
        row = conn.execute("SELECT * FROM safety_status WHERE id = 1").fetchone()
        return serialize_safety_status(row)
    finally:
        if owns_conn:
            conn.close()


def sync_led_from_db(*, beep_on_change: bool = False) -> Dict[str, Any]:
    status = get_current_safety_status()
    return led_controller.set_safety_level(status["level"], beep_on_change=beep_on_change)


def _seed_initial_transactions(cur: sqlite3.Cursor, now_dt: datetime) -> None:
    """Seed all 4 reference transactions (IDs 101..104) matching src/data/seedData.ts."""
    seed_rows = [
        (
            101,
            "LG-JRC-101",
            "One Enrique Sebastian G. Abalos",
            "AUJRC-2026-0101",
            "STEM",
            "one.abalos@arellano.edu.ph",
            "General Biology 1 — Microscopy & Cell Structure",
            "Ms. Lara Marie Agustin Puertollano",
            json.dumps([
                {
                    "equipment_id": 11,
                    "qr_code": "LG-EQ-011",
                    "name": "Compound Light Microscope",
                    "category": "Optical & Microscopy",
                    "image_url": "/images/equipment/LG-EQ-011.svg",
                    "storage_compartment": "3rd - 3rd Section",
                    "quantity": 2,
                    "unit": "unit",
                    "safety_level": "SAFE",
                    "prerequisites": [
                        "Carry microscope with two hands (one on arm, one under base)",
                        "Clean objective lenses with optical lens paper only",
                    ],
                },
                {
                    "equipment_id": 9,
                    "qr_code": "LG-EQ-009",
                    "name": "Laboratory Gown",
                    "category": "Safety & PPE",
                    "image_url": "/images/equipment/LG-EQ-009.svg",
                    "storage_compartment": "1st - 3rd Section",
                    "quantity": 2,
                    "unit": "pc",
                    "safety_level": "SAFE",
                    "prerequisites": [
                        "Button the laboratory gown completely from collar to hem before working",
                    ],
                },
            ]),
            4,
            json.dumps([
                "Wearing buttoned laboratory gown & closed-toe shoes",
                "Inspected apparatus condition prior to use",
                "Following AU-JRC Science Laboratory safety rules",
            ]),
            (now_dt - timedelta(hours=1.2)).isoformat(),
            (now_dt + timedelta(hours=1.8)).isoformat(),
            None,
            None,
            "",
            "Borrowed / In Lab",
        ),
        (
            102,
            "LG-JRC-102",
            "Christine S. Contreras",
            "AUJRC-2026-0102",
            "STEM",
            "christine.contreras@arellano.edu.ph",
            "General Chemistry 2 — Acid-Base Titration Lab",
            "Ms. Lara Marie Agustin Puertollano",
            json.dumps([
                {
                    "equipment_id": 1,
                    "qr_code": "LG-EQ-001",
                    "name": "Beaker",
                    "category": "Glassware & Measuring",
                    "image_url": "/images/equipment/LG-EQ-001.svg",
                    "storage_compartment": "1st - 1st Section",
                    "quantity": 2,
                    "unit": "pc",
                    "safety_level": "SAFE",
                    "prerequisites": [
                        "Inspect glassware for chips or hairline cracks before pouring liquids",
                    ],
                },
                {
                    "equipment_id": 5,
                    "qr_code": "LG-EQ-005",
                    "name": "Erlenmeyer Flask",
                    "category": "Glassware & Measuring",
                    "image_url": "/images/equipment/LG-EQ-005.svg",
                    "storage_compartment": "1st - 2nd Section",
                    "quantity": 2,
                    "unit": "pc",
                    "safety_level": "SAFE",
                    "prerequisites": [
                        "Swirl gently by holding the narrow neck to mix reagents without spilling",
                    ],
                },
                {
                    "equipment_id": 7,
                    "qr_code": "LG-EQ-007",
                    "name": "Tripod Stand",
                    "category": "Heating & Thermal",
                    "image_url": "/images/equipment/LG-EQ-007.svg",
                    "storage_compartment": "3rd - 2nd Section",
                    "quantity": 1,
                    "unit": "unit",
                    "safety_level": "CAUTION",
                    "prerequisites": [
                        "Allow iron frame to cool completely before returning to 3rd - 2nd Section",
                    ],
                },
            ]),
            5,
            json.dumps([
                "Wearing buttoned laboratory gown & chemical splash goggles",
                "Inspected glassware and stand stability",
                "Supervising Science Teacher present in laboratory",
            ]),
            (now_dt - timedelta(hours=0.8)).isoformat(),
            (now_dt + timedelta(hours=2.2)).isoformat(),
            None,
            None,
            "",
            "Borrowed / In Lab",
        ),
        (
            103,
            "LG-JRC-103",
            "Queen Hannah A. Dones",
            "AUJRC-2026-0103",
            "HUMSS",
            "queenhannah.dones@arellano.edu.ph",
            "General Science — Liquid Measurement & PPE Prep",
            "Ms. Lara Marie Agustin Puertollano",
            json.dumps([
                {
                    "equipment_id": 2,
                    "qr_code": "LG-EQ-002",
                    "name": "Graduated Cylinder",
                    "category": "Glassware & Measuring",
                    "image_url": "/images/equipment/LG-EQ-002.svg",
                    "storage_compartment": "2nd - 1st Section",
                    "quantity": 1,
                    "unit": "pc",
                    "safety_level": "SAFE",
                    "prerequisites": [
                        "Place on a level laboratory bench and read the bottom of the meniscus at eye level",
                    ],
                },
                {
                    "equipment_id": 10,
                    "qr_code": "LG-EQ-010",
                    "name": "Stirring Rod & PPE Kit (Glasses, Facemask, Gloves)",
                    "category": "Safety & PPE",
                    "image_url": "/images/equipment/LG-EQ-010.svg",
                    "storage_compartment": "2nd - 3rd Section",
                    "quantity": 1,
                    "unit": "kit",
                    "safety_level": "SAFE",
                    "prerequisites": [
                        "Put on PPE glasses, facemask, and gloves before handling any chemicals",
                    ],
                },
            ]),
            2,
            json.dumps([
                "Wearing buttoned laboratory gown & closed-toe shoes",
                "Inspected apparatus condition prior to use",
            ]),
            (now_dt - timedelta(hours=4.5)).isoformat(),
            (now_dt - timedelta(hours=0.5)).isoformat(),
            None,
            None,
            "",
            "Overdue",
        ),
        (
            104,
            "LG-JRC-104",
            "Collin Lenard M. Marcos",
            "AUJRC-2026-0104",
            "ABM",
            "collin.marcos@arellano.edu.ph",
            "General Chemistry 1 — Filtration & Solution Mixing",
            "Ms. Lara Marie Agustin Puertollano",
            json.dumps([
                {
                    "equipment_id": 4,
                    "qr_code": "LG-EQ-004",
                    "name": "Glass Funnel",
                    "category": "Glassware & Measuring",
                    "image_url": "/images/equipment/LG-EQ-004.svg",
                    "storage_compartment": "4th - 1st Section",
                    "quantity": 2,
                    "unit": "pc",
                    "safety_level": "SAFE",
                    "prerequisites": [
                        "Wash and dry after reagent transfer before returning to 4th - 1st Section",
                    ],
                },
            ]),
            2,
            json.dumps([
                "Wearing buttoned laboratory gown & closed-toe shoes",
                "Inspected apparatus condition prior to use",
            ]),
            (now_dt - timedelta(hours=6)).isoformat(),
            (now_dt - timedelta(hours=4)).isoformat(),
            (now_dt - timedelta(hours=4.2)).isoformat(),
            "Good",
            "Returned clean and dry in 4th - 1st Section.",
            "Returned / Logged Out",
        ),
    ]

    cur.executemany(
        """
        INSERT INTO student_transactions (
            id, transaction_code, student_name, student_id_lrn, grade_section,
            school_email, subject_activity, teacher_name, items_json,
            total_items_count, safety_checked_json, time_in, expected_return,
            time_out, return_condition, return_notes, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        seed_rows,
    )


SEED_STUDENT_ACCOUNTS = [
    (
        "AUJRC-2026-0101",
        "One Enrique Sebastian G. Abalos",
        "STEM",
        "one.abalos@arellano.edu.ph",
        "student123",
        "approved",
    ),
    (
        "AUJRC-2026-0102",
        "Christine S. Contreras",
        "STEM",
        "christine.contreras@arellano.edu.ph",
        "student123",
        "approved",
    ),
    (
        "AUJRC-2026-0103",
        "Queen Hannah A. Dones",
        "HUMSS",
        "queenhannah.dones@arellano.edu.ph",
        "student123",
        "approved",
    ),
    (
        "AUJRC-2026-0105",
        "Ashlyjicks B. Pangilinan",
        "STEM",
        "ashlyjicks.pangilinan@arellano.edu.ph",
        "student123",
        "pending",
    ),
]


def _ensure_seeded_school_id_svg(
    filename: str,
    full_name: str,
    student_id_lrn: str,
    grade_section: str,
    school_email: str,
    status: str,
) -> None:
    full_path = _resolve_safe_photo_path(filename)
    if not full_path:
        return
    if not os.path.isfile(full_path):
        svg_content = _build_sample_school_id_svg(
            full_name, student_id_lrn, grade_section, school_email, status
        )
        with open(full_path, "w", encoding="utf-8") as fp:
            fp.write(svg_content)


def _seed_initial_student_accounts(cur: sqlite3.Cursor, now_dt: datetime) -> None:
    """Seed 4 demo student accounts (3 approved, 1 pending) with sample AU-JRC SVG IDs."""
    admin_name = get_admin_name()
    for lrn, full_name, grade_section, email, raw_password, status in SEED_STUDENT_ACCOUNTS:
        safe_lrn = re.sub(r"[^A-Z0-9_-]+", "_", lrn.upper()).strip("_") or "STUDENT"
        filename = f"seed_{safe_lrn}.svg"
        svg_content = _build_sample_school_id_svg(
            full_name, lrn, grade_section, email, status
        )
        full_path = _resolve_safe_photo_path(filename)
        if full_path:
            with open(full_path, "w", encoding="utf-8") as fp:
                fp.write(svg_content)

        is_approved = status == "approved"
        created_at = (
            (now_dt - timedelta(days=3)).isoformat()
            if is_approved
            else (now_dt - timedelta(minutes=25)).isoformat()
        )
        updated_at = (
            (now_dt - timedelta(days=2)).isoformat()
            if is_approved
            else (now_dt - timedelta(minutes=25)).isoformat()
        )

        cur.execute(
            """
            INSERT INTO student_accounts (
                student_id_lrn, full_name, grade_section, school_email,
                password_hash, id_photo_filename, status, rejection_reason,
                reviewed_by, reviewed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?)
            """,
            (
                lrn.upper(),
                full_name,
                grade_section.upper(),
                email.lower(),
                hash_password(raw_password),
                filename,
                status,
                admin_name if is_approved else None,
                updated_at if is_approved else None,
                created_at,
                updated_at,
            ),
        )


def init_db(force_reset: bool = False, *, beep_on_sync: bool = False) -> None:
    global _db_initialized_path
    conn = get_db()
    cur = conn.cursor()

    if force_reset:
        try:
            old_photos = cur.execute(
                "SELECT id_photo_filename FROM student_accounts"
            ).fetchall()
            for r in old_photos:
                _delete_photo_file_safe(r["id_photo_filename"])
        except sqlite3.OperationalError:
            pass

        cur.execute("DROP TABLE IF EXISTS equipment")
        cur.execute("DROP TABLE IF EXISTS student_transactions")
        cur.execute("DROP TABLE IF EXISTS checkout_sessions")
        cur.execute("DROP TABLE IF EXISTS safety_status")
        cur.execute("DROP TABLE IF EXISTS student_accounts")
        cur.execute("DROP TABLE IF EXISTS student_sessions")
        # Preserve admin_sessions so active admin is not logged out on demo reset

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qr_code TEXT NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            image_url TEXT NOT NULL,
            description TEXT NOT NULL,
            storage_compartment TEXT NOT NULL,
            total_qty INTEGER NOT NULL,
            available_qty INTEGER NOT NULL,
            unit TEXT NOT NULL,
            condition TEXT NOT NULL,
            safety_level TEXT NOT NULL,
            prerequisites_json TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS checkout_sessions (
            session_token TEXT PRIMARY KEY,
            basket_json TEXT NOT NULL,
            qr_data_url TEXT NOT NULL,
            mobile_url TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            completed_transaction_json TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS student_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_code TEXT NOT NULL,
            student_name TEXT NOT NULL,
            student_id_lrn TEXT NOT NULL,
            grade_section TEXT NOT NULL,
            school_email TEXT NOT NULL,
            subject_activity TEXT NOT NULL,
            teacher_name TEXT NOT NULL,
            items_json TEXT NOT NULL,
            total_items_count INTEGER NOT NULL,
            safety_checked_json TEXT NOT NULL,
            time_in TEXT NOT NULL,
            expected_return TEXT NOT NULL,
            time_out TEXT,
            return_condition TEXT,
            return_notes TEXT,
            status TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS safety_status (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            level TEXT NOT NULL,
            headline TEXT NOT NULL,
            message TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS student_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id_lrn TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            grade_section TEXT NOT NULL,
            school_email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            id_photo_filename TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            rejection_reason TEXT NOT NULL DEFAULT '',
            reviewed_by TEXT,
            reviewed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS student_sessions (
            token TEXT PRIMARY KEY,
            student_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_sessions (
            token TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        """
    )

    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()

    cur.execute("SELECT COUNT(*) FROM equipment")
    if cur.fetchone()[0] == 0:
        for row in INITIAL_EQUIPMENT_SEED:
            cur.execute(
                """
                INSERT INTO equipment (
                    id, qr_code, name, category, image_url, description,
                    storage_compartment, total_qty, available_qty, unit,
                    condition, safety_level, prerequisites_json, is_active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (*row, now_iso),
            )

    cur.execute("SELECT COUNT(*) FROM safety_status")
    if cur.fetchone()[0] == 0:
        cur.execute(
            """
            INSERT INTO safety_status (id, level, headline, message, updated_by, updated_at)
            VALUES (1, 'SAFE', ?, ?, 'Ms. Lara Marie Agustin Puertollano (Research Adviser / Lab Coordinator)', ?)
            """,
            (
                SAFETY_PRESETS["SAFE"]["headline"],
                SAFETY_PRESETS["SAFE"]["message"],
                now_iso,
            ),
        )

    cur.execute("SELECT COUNT(*) FROM student_transactions")
    if cur.fetchone()[0] == 0:
        _seed_initial_transactions(cur, now_dt)

    cur.execute("SELECT COUNT(*) FROM student_accounts")
    if cur.fetchone()[0] == 0:
        _seed_initial_student_accounts(cur, now_dt)
    else:
        seeded_rows = cur.execute(
            "SELECT student_id_lrn, full_name, grade_section, school_email, id_photo_filename, status "
            "FROM student_accounts WHERE id_photo_filename LIKE 'seed_%.svg'"
        ).fetchall()
        for r in seeded_rows:
            _ensure_seeded_school_id_svg(
                r["id_photo_filename"],
                r["full_name"],
                r["student_id_lrn"],
                r["grade_section"],
                r["school_email"],
                r["status"],
            )

    conn.commit()
    safety_row = conn.execute("SELECT * FROM safety_status WHERE id = 1").fetchone()
    conn.close()

    _db_initialized_path = get_db_path()
    safety_level = safety_row["level"] if safety_row else "SAFE"
    led_controller.set_safety_level(safety_level, beep_on_change=beep_on_sync)


# ==============================================================================
# AUTHENTICATION HELPERS (ADMIN & STUDENT BEARER SESSIONS)
# ==============================================================================
def extract_bearer_token(req: Any, *, allow_query_token: bool = False) -> Optional[str]:
    auth_header = (req.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        tok = auth_header[7:].strip()
        if tok:
            return tok
    if allow_query_token:
        qtok = (req.args.get("token") or "").strip()
        if qtok:
            return qtok
    return None


def get_authenticated_admin(
    req: Any, *, allow_query_token: bool = False
) -> Optional[Dict[str, Any]]:
    token = extract_bearer_token(req, allow_query_token=allow_query_token)
    if not token:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM admin_sessions WHERE token = ?", (token,)
        ).fetchone()
        if not row:
            return None
        expires_dt = _parse_iso_utc(row["expires_at"])
        if expires_dt is None or expires_dt <= datetime.now(timezone.utc):
            conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
            conn.commit()
            return None
        return {
            "token": row["token"],
            "email": row["email"],
            "name": row["name"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }
    finally:
        conn.close()


def require_admin_auth(*, allow_query_token: bool = False):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            admin_session = get_authenticated_admin(
                request, allow_query_token=allow_query_token
            )
            if not admin_session:
                return jsonify({"error": "Administrator authentication required."}), 401
            g.admin_session = admin_session
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def serialize_student(row: sqlite3.Row) -> Dict[str, Any]:
    photo_filename = row["id_photo_filename"] or ""
    return {
        "id": row["id"],
        "student_id_lrn": row["student_id_lrn"],
        "full_name": row["full_name"],
        "grade_section": row["grade_section"],
        "school_email": row["school_email"],
        "status": row["status"],
        "rejection_reason": row["rejection_reason"] or "",
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "has_id_photo": bool(photo_filename) and _photo_file_exists(photo_filename),
        "id_photo_url": f"/api/admin/students/{row['id']}/id-photo",
    }


def ensure_db_initialized() -> None:
    current_path = get_db_path()
    if _db_initialized_path == current_path and os.path.exists(current_path):
        return
    with _db_init_lock:
        if _db_initialized_path != current_path or not os.path.exists(current_path):
            init_db(force_reset=False, beep_on_sync=False)


@app.before_request
def _before_request_init() -> None:
    ensure_db_initialized()


# ==============================================================================
# WEBSOCKET BROADCAST HELPERS & CHANNELS
# ==============================================================================
def broadcast_global_update(payload: Dict[str, Any]) -> None:
    message = json.dumps(payload)
    with _ws_lock:
        clients = list(_global_ws_clients)
    dead = []
    for ws in clients:
        try:
            ws.send(message)
        except Exception:
            dead.append(ws)
    if dead:
        with _ws_lock:
            for ws in dead:
                _global_ws_clients.discard(ws)


def broadcast_checkout_update(token: str, payload: Dict[str, Any]) -> None:
    message = json.dumps(payload)
    with _ws_lock:
        clients = list(_checkout_ws_clients.get(token, ()))
    dead = []
    for ws in clients:
        try:
            ws.send(message)
        except Exception:
            dead.append(ws)
    if dead:
        with _ws_lock:
            bucket = _checkout_ws_clients.get(token)
            if bucket is not None:
                for ws in dead:
                    bucket.discard(ws)
                if not bucket:
                    _checkout_ws_clients.pop(token, None)


def _handle_global_ws(ws: Any) -> None:
    ensure_db_initialized()
    with _ws_lock:
        _global_ws_clients.add(ws)
    try:
        ws.send(
            json.dumps({
                "event": "state_sync",
                "safety_status": get_current_safety_status(),
                "hardware": led_controller.get_status(),
            })
        )
        while True:
            data = ws.receive()
            if data is None:
                break
    except Exception:
        pass
    finally:
        with _ws_lock:
            _global_ws_clients.discard(ws)


def _handle_checkout_ws(ws: Any, token: str) -> None:
    ensure_db_initialized()
    token = token.strip()
    with _ws_lock:
        _checkout_ws_clients.setdefault(token, set()).add(ws)
    try:
        while True:
            data = ws.receive()
            if data is None:
                break
    except Exception:
        pass
    finally:
        with _ws_lock:
            bucket = _checkout_ws_clients.get(token)
            if bucket is not None:
                bucket.discard(ws)
                if not bucket:
                    _checkout_ws_clients.pop(token, None)


if sock is not None:
    @sock.route("/ws/kiosk")
    def ws_kiosk(ws):
        _handle_global_ws(ws)

    @sock.route("/ws/hardware")
    def ws_hardware(ws):
        _handle_global_ws(ws)

    @sock.route("/ws/checkout/<token>")
    def ws_checkout(ws, token: str):
        _handle_checkout_ws(ws, token)
else:
    logger.warning(
        "flask-sock is not installed; WebSocket endpoints (/ws/*) disabled (clients will use polling fallback)."
    )


def make_qr_data_url(url_text: str) -> str:
    if qrcode is not None:
        qr = qrcode.QRCode(version=1, box_size=8, border=2)
        qr.add_data(url_text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#003087", back_color="#FFFFFF")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    return ""


# ==============================================================================
# 3 SEPARATE HTML TEMPLATE ROUTES + STATIC ASSETS
# ==============================================================================
@app.route("/")
@app.route("/kiosk")
@app.route("/kiosk.html")
def kiosk_page():
    """Serves File 1: Student-only Inventory & Basket Kiosk UI (templates/kiosk.html)."""
    return render_template("kiosk.html")


@app.route("/student/checkout/<token>")
@app.route("/student_form.html")
def student_form_page(token: str = ""):
    """Serves File 2: QR-Redirected Student Information Form (templates/student_form.html)."""
    return render_template("student_form.html", session_token=token)


@app.route("/student/register")
@app.route("/student_register.html")
def student_register_page():
    """Serves Student Registration & School ID Upload page (templates/student_register.html)."""
    return render_template("student_register.html")


@app.route("/admin")
@app.route("/admin.html")
def admin_dashboard_page():
    """Serves File 3: Admin & Lab Personnel Dashboard (templates/admin.html)."""
    return render_template("admin.html")


@app.route("/images/<path:filename>")
def serve_public_images(filename: str):
    """Serves public/images/* including au_seal.jpg and equipment/*.svg."""
    return send_from_directory(os.path.join(PUBLIC_DIR, "images"), filename)


@app.route("/css/<path:filename>")
def serve_public_css(filename: str):
    """Serves offline compiled CSS assets from public/css/*."""
    return send_from_directory(os.path.join(PUBLIC_DIR, "css"), filename)


@app.route("/assets/<path:filename>")
def serve_public_assets(filename: str):
    """Serves additional static assets from public/assets/*."""
    return send_from_directory(os.path.join(PUBLIC_DIR, "assets"), filename)


# ==============================================================================
# REST API ENDPOINTS (SQLite3 + GPIO + WebSockets)
# ==============================================================================
def serialize_equipment(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "qr_code": row["qr_code"],
        "name": row["name"],
        "category": row["category"],
        "image_url": row["image_url"],
        "description": row["description"],
        "storage_compartment": row["storage_compartment"],
        "total_qty": row["total_qty"],
        "available_qty": row["available_qty"],
        "unit": row["unit"],
        "condition": row["condition"],
        "safety_level": row["safety_level"],
        "prerequisites": json.loads(row["prerequisites_json"] or "[]"),
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }


def serialize_transaction(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "transaction_code": row["transaction_code"],
        "student_name": row["student_name"],
        "student_id_lrn": row["student_id_lrn"],
        "grade_section": row["grade_section"],
        "school_email": row["school_email"],
        "subject_activity": row["subject_activity"],
        "teacher_name": row["teacher_name"],
        "items": json.loads(row["items_json"] or "[]"),
        "total_items_count": row["total_items_count"],
        "safety_prerequisites_checked": json.loads(row["safety_checked_json"] or "[]"),
        "time_in": row["time_in"],
        "expected_return": row["expected_return"],
        "time_out": row["time_out"],
        "return_condition": row["return_condition"],
        "return_notes": row["return_notes"] or "",
        "status": row["status"],
    }


@app.route("/api/health", methods=["GET"])
def api_health():
    base_url = resolve_public_base_url(request)
    return jsonify({
        "status": "ok",
        "system": "LabGuard+",
        "runtime": "python-flask",
        "lan_url": base_url,
        "kiosk_url": f"{base_url}/kiosk",
        "admin_url": f"{base_url}/admin",
        "hardware": led_controller.get_status(),
        "db_path": get_db_path(),
    })


@app.route("/api/hardware/status", methods=["GET"])
def api_hardware_status():
    base_url = resolve_public_base_url(request)
    return jsonify({
        "hardware": led_controller.get_status(),
        "lan_url": base_url,
        "kiosk_url": f"{base_url}/kiosk",
        "admin_url": f"{base_url}/admin",
    })


@app.route("/api/state", methods=["GET"])
def api_state():
    conn = get_db()
    try:
        eq_rows = conn.execute("SELECT * FROM equipment WHERE is_active = 1 ORDER BY id ASC").fetchall()
        tx_rows = conn.execute("SELECT * FROM student_transactions ORDER BY id DESC").fetchall()
        safety_row = conn.execute("SELECT * FROM safety_status WHERE id = 1").fetchone()
    finally:
        conn.close()

    return jsonify({
        "equipment": [serialize_equipment(r) for r in eq_rows],
        "transactions": [serialize_transaction(r) for r in tx_rows],
        "safety_status": serialize_safety_status(safety_row),
        "student_presets": STUDENT_PRESETS,
    })


@app.route("/api/kiosk/checkout-session", methods=["POST"])
def api_create_checkout_session():
    data = request.get_json(silent=True) or {}
    raw_items = data.get("basket_items") or []
    if not raw_items:
        return jsonify({"error": "Please pick at least one equipment item into your basket."}), 400

    conn = get_db()
    try:
        safety_row = conn.execute("SELECT * FROM safety_status WHERE id = 1").fetchone()
        if safety_row and safety_row["level"] == "UNSAFE":
            return jsonify({"error": "Laboratory LED Safety Status is RED (UNSAFE). Equipment checkout is paused."}), 403

        validated = []
        for item in raw_items:
            eq = conn.execute(
                "SELECT * FROM equipment WHERE id = ? AND is_active = 1",
                (int(item.get("equipment_id", 0)),),
            ).fetchone()
            if not eq:
                return jsonify({"error": "Equipment item not found."}), 404
            qty = max(1, int(item.get("quantity", 1)))
            if qty > eq["available_qty"]:
                return jsonify({"error": f"Insufficient stock for {eq['name']}."}), 400
            validated.append({
                "equipment_id": eq["id"],
                "qr_code": eq["qr_code"],
                "name": eq["name"],
                "category": eq["category"],
                "image_url": eq["image_url"],
                "storage_compartment": eq["storage_compartment"],
                "quantity": qty,
                "unit": eq["unit"],
                "safety_level": eq["safety_level"],
                "prerequisites": json.loads(eq["prerequisites_json"] or "[]"),
            })

        token = "CHK-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=15)

        base_url = resolve_public_base_url(request)
        mobile_url = f"{base_url}/student/checkout/{token}"
        qr_data_url = make_qr_data_url(mobile_url)

        session_obj = {
            "session_token": token,
            "basket_items": validated,
            "qr_data_url": qr_data_url,
            "mobile_url": mobile_url,
            "status": "pending_student_info",
            "created_at": now.isoformat(),
            "expires_at": expires.isoformat(),
        }

        conn.execute(
            """
            INSERT INTO checkout_sessions (
                session_token, basket_json, qr_data_url, mobile_url, status, created_at, expires_at
            ) VALUES (?, ?, ?, ?, 'pending_student_info', ?, ?)
            """,
            (
                token,
                json.dumps(validated),
                qr_data_url,
                mobile_url,
                now.isoformat(),
                expires.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"session": session_obj}), 201


@app.route("/api/kiosk/checkout-session/<token>", methods=["GET"])
def api_get_checkout_session(token: str):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM checkout_sessions WHERE session_token = ?", (token,)
        ).fetchone()
        safety_row = conn.execute("SELECT * FROM safety_status WHERE id = 1").fetchone()
    finally:
        conn.close()

    if not row:
        return jsonify({"error": "Checkout QR session not found or expired."}), 404

    completed_tx = (
        json.loads(row["completed_transaction_json"])
        if row["completed_transaction_json"]
        else None
    )
    return jsonify({
        "session": {
            "session_token": row["session_token"],
            "basket_items": json.loads(row["basket_json"] or "[]"),
            "qr_data_url": row["qr_data_url"],
            "mobile_url": row["mobile_url"],
            "status": row["status"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "completed_transaction": completed_tx,
        },
        "safety_status": serialize_safety_status(safety_row),
        "student_presets": STUDENT_PRESETS,
    })


@app.route("/api/kiosk/checkout-session/<token>/complete", methods=["POST"])
def api_complete_checkout_session(token: str):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        sess_row = conn.execute(
            "SELECT * FROM checkout_sessions WHERE session_token = ?", (token,)
        ).fetchone()

        if sess_row and sess_row["status"] == "completed" and sess_row["completed_transaction_json"]:
            return jsonify({
                "success": True,
                "transaction": json.loads(sess_row["completed_transaction_json"]),
            })

        basket_items = (
            json.loads(sess_row["basket_json"])
            if sess_row
            else (data.get("basket_items") or [])
        )
        if not basket_items:
            return jsonify({"error": "No equipment items found in checkout session."}), 400

        student_name = str(data.get("student_name") or "").strip()
        student_id_lrn = str(data.get("student_id_lrn") or "").strip()
        grade_section = str(data.get("grade_section") or "").strip()
        school_email = str(data.get("school_email") or "").strip().lower()
        subject_activity = str(data.get("subject_activity") or "").strip()
        teacher_name = str(data.get("teacher_name") or "").strip()
        expected_hours = float(data.get("expected_return_hours") or 2)
        raw_checked = data.get("safety_prerequisites_checked")
        safety_checked = (
            [str(x) for x in raw_checked if x]
            if isinstance(raw_checked, list) and len(raw_checked) > 0
            else [
                "Wearing buttoned laboratory gown & PPE",
                "Inspected apparatus condition prior to use",
                "Following AU-JRC Science Laboratory safety rules",
            ]
        )

        if not (student_name and student_id_lrn and grade_section and subject_activity and teacher_name):
            return jsonify({"error": "Please complete all required student information fields."}), 400

        # Validate stock for all items before mutating
        resolved_items = []
        for item in basket_items:
            eq = conn.execute(
                "SELECT * FROM equipment WHERE id = ?", (int(item["equipment_id"]),)
            ).fetchone()
            qty = max(1, int(item.get("quantity", 1)))
            if not eq or eq["available_qty"] < qty:
                return jsonify({"error": f"Insufficient stock for {item.get('name', 'equipment')}."}), 400
            resolved_items.append((eq, qty))

        total_units = 0
        has_caution = False
        for eq, qty in resolved_items:
            conn.execute(
                "UPDATE equipment SET available_qty = MAX(0, available_qty - ?) WHERE id = ?",
                (qty, eq["id"]),
            )
            total_units += qty
            if eq["safety_level"] == "CAUTION":
                has_caution = True

        max_id_row = conn.execute("SELECT MAX(id) FROM student_transactions").fetchone()
        next_id = max(100, (max_id_row[0] or 100)) + 1
        tx_code = f"LG-JRC-{next_id}"
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        exp_iso = (now_dt + timedelta(hours=max(0.5, expected_hours))).isoformat()

        conn.execute(
            """
            INSERT INTO student_transactions (
                id, transaction_code, student_name, student_id_lrn, grade_section,
                school_email, subject_activity, teacher_name, items_json,
                total_items_count, safety_checked_json, time_in, expected_return,
                time_out, return_condition, return_notes, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, '', 'Borrowed / In Lab')
            """,
            (
                next_id,
                tx_code,
                student_name,
                student_id_lrn,
                grade_section,
                school_email or f"{student_id_lrn.lower()}@arellano.edu.ph",
                subject_activity,
                teacher_name,
                json.dumps(basket_items),
                total_units,
                json.dumps(safety_checked),
                now_iso,
                exp_iso,
            ),
        )

        prev_safety_row = conn.execute("SELECT level FROM safety_status WHERE id = 1").fetchone()
        prev_level = prev_safety_row["level"] if prev_safety_row else "SAFE"

        if has_caution:
            conn.execute(
                """
                UPDATE safety_status
                SET level = 'CAUTION', headline = ?, message = ?, updated_by = 'LabGuard+ Automated Safety Monitor', updated_at = ?
                WHERE id = 1 AND level = 'SAFE'
                """,
                (
                    SAFETY_PRESETS["CAUTION"]["headline"],
                    f"Active checkout ({tx_code} · {student_name}) includes thermal or glassware apparatus. PPE and teacher supervision required.",
                    now_iso,
                ),
            )

        tx_row = conn.execute("SELECT * FROM student_transactions WHERE id = ?", (next_id,)).fetchone()
        tx_dict = serialize_transaction(tx_row)

        if sess_row:
            conn.execute(
                "UPDATE checkout_sessions SET status = 'completed', completed_transaction_json = ? WHERE session_token = ?",
                (json.dumps(tx_dict), token),
            )

        conn.commit()
        safety_row = conn.execute("SELECT * FROM safety_status WHERE id = 1").fetchone()
        safety_dict = serialize_safety_status(safety_row)
    finally:
        conn.close()

    if safety_dict["level"] != prev_level:
        hw_status = led_controller.set_safety_level(safety_dict["level"], beep_on_change=True)
    else:
        hw_status = led_controller.set_safety_level(safety_dict["level"], beep_on_change=False)
        led_controller.beep("confirm")

    if sess_row:
        broadcast_checkout_update(token, {
            "event": "checkout_completed",
            "transaction": tx_dict,
        })

    broadcast_global_update({
        "event": "data_updated",
        "transaction": tx_dict,
        "safety_status": safety_dict,
        "hardware": hw_status,
    })

    return jsonify({
        "success": True,
        "transaction": tx_dict,
        "safety_status": safety_dict,
    }), 201


@app.route("/api/kiosk/return", methods=["POST"])
def api_return_equipment():
    data = request.get_json(silent=True) or {}
    tx_id = int(data.get("transaction_id") or 0)
    tx_code = str(data.get("transaction_code") or "").strip().upper()
    raw_condition = data.get("return_condition")
    condition = raw_condition if raw_condition in ("Damaged", "Missing") else "Good"
    notes = str(data.get("return_notes") or "").strip() or f"Returned in {condition} condition."

    conn = get_db()
    try:
        row = None
        if tx_id:
            row = conn.execute("SELECT * FROM student_transactions WHERE id = ?", (tx_id,)).fetchone()
        if row is None and tx_code:
            row = conn.execute(
                "SELECT * FROM student_transactions WHERE UPPER(transaction_code) = ?",
                (tx_code,),
            ).fetchone()

        if not row:
            return jsonify({"error": "Borrow transaction record not found."}), 404

        if row["status"] == "Returned / Logged Out":
            return jsonify({"error": "This transaction has already been returned and logged out."}), 400

        resolved_tx_id = row["id"]
        now_iso = datetime.now(timezone.utc).isoformat()
        items = json.loads(row["items_json"] or "[]")

        if condition != "Missing":
            for item in items:
                conn.execute(
                    "UPDATE equipment SET available_qty = MIN(total_qty, available_qty + ?) WHERE id = ?",
                    (int(item["quantity"]), int(item["equipment_id"])),
                )
                if condition == "Damaged":
                    conn.execute(
                        "UPDATE equipment SET condition = 'Damaged' WHERE id = ?",
                        (int(item["equipment_id"]),),
                    )

        conn.execute(
            """
            UPDATE student_transactions
            SET time_out = ?, return_condition = ?, return_notes = ?, status = 'Returned / Logged Out'
            WHERE id = ?
            """,
            (now_iso, condition, notes, resolved_tx_id),
        )

        prev_safety_row = conn.execute("SELECT level FROM safety_status WHERE id = 1").fetchone()
        prev_level = prev_safety_row["level"] if prev_safety_row else "SAFE"

        if condition in ("Damaged", "Missing"):
            items_summary = ", ".join(
                f"{it.get('quantity', 1)}x {it.get('name', 'Item')}" for it in items
            )
            compartments = ", ".join(
                sorted({it.get("storage_compartment", "") for it in items if it.get("storage_compartment")})
            )
            msg = (
                f"Damaged apparatus returned ({row['transaction_code']}: {items_summary}). Inspect {compartments or 'compartment'} before next use."
                if condition == "Damaged"
                else f"Missing apparatus reported on return ({row['transaction_code']}: {items_summary}). Lab Coordinator verification required for {compartments or 'compartment'}."
            )
            conn.execute(
                """
                UPDATE safety_status
                SET level = CASE WHEN level = 'UNSAFE' THEN 'UNSAFE' ELSE 'CAUTION' END,
                    headline = CASE WHEN level = 'UNSAFE' THEN headline ELSE ? END,
                    message = ?,
                    updated_by = ?,
                    updated_at = ?
                WHERE id = 1
                """,
                (
                    SAFETY_PRESETS["CAUTION"]["headline"],
                    msg,
                    f"LabGuard+ Return Monitor ({condition})",
                    now_iso,
                ),
            )

        conn.commit()
        updated = conn.execute(
            "SELECT * FROM student_transactions WHERE id = ?", (resolved_tx_id,)
        ).fetchone()
        safety_row = conn.execute("SELECT * FROM safety_status WHERE id = 1").fetchone()
        tx_dict = serialize_transaction(updated)
        safety_dict = serialize_safety_status(safety_row)
    finally:
        conn.close()

    if safety_dict["level"] != prev_level:
        hw_status = led_controller.set_safety_level(safety_dict["level"], beep_on_change=True)
    else:
        hw_status = led_controller.set_safety_level(safety_dict["level"], beep_on_change=False)
        led_controller.beep("caution" if condition in ("Damaged", "Missing") else "confirm")

    broadcast_global_update({
        "event": "data_updated",
        "transaction": tx_dict,
        "safety_status": safety_dict,
        "hardware": hw_status,
    })

    return jsonify({
        "success": True,
        "transaction": tx_dict,
        "safety_status": safety_dict,
    })


# ==============================================================================
# SPEC-01: REGISTRATION QR, STUDENT AUTH & ADMIN APPROVAL ENDPOINTS
# ==============================================================================
@app.route("/api/kiosk/registration-qr", methods=["GET"])
def api_kiosk_registration_qr():
    base_url = resolve_public_base_url(request)
    register_url = f"{base_url}/student/register"
    account_url = f"{base_url}/student/account"
    return jsonify({
        "register_url": register_url,
        "account_url": account_url,
        "qr_data_url": make_qr_data_url(register_url),
        "account_qr_data_url": make_qr_data_url(account_url),
    })


@app.route("/api/students/register", methods=["POST"])
def api_student_register():
    data = request.get_json(silent=True) or {}
    full_name = str(data.get("full_name") or "").strip()
    student_id_lrn = str(data.get("student_id_lrn") or "").strip().upper()
    grade_section = str(data.get("grade_section") or "").strip().upper()
    school_email = str(data.get("school_email") or "").strip().lower()
    password = str(data.get("password") or "")
    id_photo_data_url = str(data.get("id_photo_data_url") or "").strip()

    if not (
        full_name
        and student_id_lrn
        and grade_section
        and school_email
        and password
        and id_photo_data_url
    ):
        return (
            jsonify({
                "error": (
                    "Please fill in Full Name, Student ID / LRN, Strand / Faculty, "
                    "School Email, Password, and upload your School ID photo."
                )
            }),
            400,
        )

    if grade_section not in VALID_GRADE_SECTIONS:
        return (
            jsonify({
                "error": "Strand / Faculty must be one of STEM, HUMSS, ABM, or FACULTY."
            }),
            400,
        )

    if not EMAIL_RE.match(school_email):
        return jsonify({"error": "Please enter a valid school email address."}), 400

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters long."}), 400

    conn = get_db()
    new_photo_filename: Optional[str] = None
    old_photo_to_delete: Optional[str] = None
    try:
        matches = conn.execute(
            "SELECT * FROM student_accounts WHERE student_id_lrn = ? OR school_email = ?",
            (student_id_lrn, school_email),
        ).fetchall()

        if len(matches) > 1 or (len(matches) == 1 and matches[0]["status"] != "rejected"):
            return (
                jsonify({
                    "error": "A student account with this Student ID / LRN or School Email already exists."
                }),
                409,
            )

        new_photo_filename, photo_err = _save_id_photo_from_data_url(
            student_id_lrn, id_photo_data_url
        )
        if not new_photo_filename:
            return jsonify({"error": photo_err or "Invalid School ID image."}), 400

        now_iso = datetime.now(timezone.utc).isoformat()
        password_hash = hash_password(password)

        try:
            if len(matches) == 1 and matches[0]["status"] == "rejected":
                existing = matches[0]
                old_photo_to_delete = existing["id_photo_filename"]
                conn.execute(
                    """
                    UPDATE student_accounts
                    SET student_id_lrn = ?, full_name = ?, grade_section = ?,
                        school_email = ?, password_hash = ?, id_photo_filename = ?,
                        status = 'pending', rejection_reason = '',
                        reviewed_by = NULL, reviewed_at = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        student_id_lrn,
                        full_name,
                        grade_section,
                        school_email,
                        password_hash,
                        new_photo_filename,
                        now_iso,
                        existing["id"],
                    ),
                )
                account_id = existing["id"]
            else:
                cur = conn.execute(
                    """
                    INSERT INTO student_accounts (
                        student_id_lrn, full_name, grade_section, school_email,
                        password_hash, id_photo_filename, status, rejection_reason,
                        reviewed_by, reviewed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending', '', NULL, NULL, ?, ?)
                    """,
                    (
                        student_id_lrn,
                        full_name,
                        grade_section,
                        school_email,
                        password_hash,
                        new_photo_filename,
                        now_iso,
                        now_iso,
                    ),
                )
                account_id = cur.lastrowid

            conn.commit()
        except sqlite3.IntegrityError:
            _delete_photo_file_safe(new_photo_filename)
            return (
                jsonify({
                    "error": "A student account with this Student ID / LRN or School Email already exists."
                }),
                409,
            )

        row = conn.execute(
            "SELECT * FROM student_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        student_dict = serialize_student(row)
    finally:
        conn.close()

    if old_photo_to_delete and old_photo_to_delete != new_photo_filename:
        _delete_photo_file_safe(old_photo_to_delete)

    broadcast_global_update({"event": "accounts_updated"})
    return jsonify({"success": True, "student": student_dict}), 201


@app.route("/api/students/status", methods=["GET"])
def api_student_status():
    identifier = str(request.args.get("identifier") or "").strip()
    if not identifier:
        return jsonify({"found": False})

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT student_id_lrn, status, rejection_reason, updated_at "
            "FROM student_accounts WHERE student_id_lrn = ? OR school_email = ?",
            (identifier.upper(), identifier.lower()),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return jsonify({"found": False})

    return jsonify({
        "found": True,
        "status": row["status"],
        "rejection_reason": row["rejection_reason"] or "",
        "student_id_lrn": row["student_id_lrn"],
        "updated_at": row["updated_at"],
    })


@app.route("/api/students/login", methods=["POST"])
def api_student_login():
    data = request.get_json(silent=True) or {}
    identifier = str(
        data.get("identifier") or data.get("email") or data.get("student_id_lrn") or ""
    ).strip()
    password = str(data.get("password") or "")

    if not identifier or not password:
        return jsonify({"error": "Invalid Student ID / Email or password."}), 401

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM student_accounts WHERE student_id_lrn = ? OR school_email = ?",
            (identifier.upper(), identifier.lower()),
        ).fetchone()

        if not row or not verify_password(password, row["password_hash"]):
            return jsonify({"error": "Invalid Student ID / Email or password."}), 401

        status = row["status"]
        if status == "pending":
            return (
                jsonify({
                    "error": "Your registration is pending Laboratory Admin verification of your School ID.",
                    "account_status": "pending",
                }),
                403,
            )
        if status == "rejected":
            return (
                jsonify({
                    "error": "Your registration was rejected by the Laboratory Admin.",
                    "account_status": "rejected",
                    "rejection_reason": row["rejection_reason"] or "",
                }),
                403,
            )
        if status == "suspended":
            return (
                jsonify({
                    "error": "Your student account is suspended. Please contact Laboratory Personnel.",
                    "account_status": "suspended",
                }),
                403,
            )

        token = f"STU-{secrets.token_urlsafe(24)}"
        now_dt = datetime.now(timezone.utc)
        expires_dt = now_dt + timedelta(days=STUDENT_SESSION_DAYS)
        conn.execute(
            """
            INSERT INTO student_sessions (token, student_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, row["id"], now_dt.isoformat(), expires_dt.isoformat()),
        )
        conn.commit()
        student_dict = serialize_student(row)
    finally:
        conn.close()

    return jsonify({"success": True, "token": token, "student": student_dict})


@app.route("/api/students/me", methods=["GET"])
def api_student_me():
    token = extract_bearer_token(request, allow_query_token=False)
    if not token:
        return jsonify({"error": "Student authentication required."}), 401

    conn = get_db()
    try:
        sess = conn.execute(
            "SELECT * FROM student_sessions WHERE token = ?", (token,)
        ).fetchone()
        if not sess:
            return jsonify({"error": "Student authentication required."}), 401
        expires_dt = _parse_iso_utc(sess["expires_at"])
        if expires_dt is None or expires_dt <= datetime.now(timezone.utc):
            conn.execute("DELETE FROM student_sessions WHERE token = ?", (token,))
            conn.commit()
            return jsonify({"error": "Student authentication required."}), 401

        row = conn.execute(
            "SELECT * FROM student_accounts WHERE id = ?", (sess["student_id"],)
        ).fetchone()
        if not row:
            conn.execute("DELETE FROM student_sessions WHERE token = ?", (token,))
            conn.commit()
            return jsonify({"error": "Student authentication required."}), 401

        if row["status"] != "approved":
            return (
                jsonify({
                    "error": "Your student account is not approved for active access.",
                    "account_status": row["status"],
                    "rejection_reason": row["rejection_reason"] or "",
                }),
                403,
            )
        student_dict = serialize_student(row)
    finally:
        conn.close()

    return jsonify({"student": student_dict})


@app.route("/api/students/logout", methods=["POST"])
def api_student_logout():
    token = extract_bearer_token(request, allow_query_token=False)
    if not token:
        return jsonify({"error": "Student authentication required."}), 401

    conn = get_db()
    try:
        sess = conn.execute(
            "SELECT * FROM student_sessions WHERE token = ?", (token,)
        ).fetchone()
        if not sess:
            return jsonify({"error": "Student authentication required."}), 401
        expires_dt = _parse_iso_utc(sess["expires_at"])
        conn.execute("DELETE FROM student_sessions WHERE token = ?", (token,))
        conn.commit()
        if expires_dt is None or expires_dt <= datetime.now(timezone.utc):
            return jsonify({"error": "Student authentication required."}), 401
    finally:
        conn.close()

    return jsonify({"success": True})


@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip().lower()
    password = str(data.get("password") or "")

    configured_email = get_admin_email()
    configured_password = get_admin_password()
    configured_name = get_admin_name()

    email_ok = hmac.compare_digest(
        email.encode("utf-8"), configured_email.lower().encode("utf-8")
    )
    password_ok = hmac.compare_digest(
        password.encode("utf-8"), configured_password.encode("utf-8")
    )
    if not (email_ok and password_ok):
        return jsonify({"error": "Invalid administrator email or password."}), 401

    token = f"ADM-{secrets.token_urlsafe(24)}"
    now_dt = datetime.now(timezone.utc)
    expires_dt = now_dt + timedelta(hours=ADMIN_SESSION_HOURS)

    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO admin_sessions (token, email, name, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                token,
                configured_email,
                configured_name,
                now_dt.isoformat(),
                expires_dt.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        "success": True,
        "token": token,
        "admin": {
            "email": configured_email,
            "name": configured_name,
        },
    })


@app.route("/api/admin/me", methods=["GET"])
@require_admin_auth()
def api_admin_me():
    admin = g.admin_session
    return jsonify({
        "admin": {
            "email": admin["email"],
            "name": admin["name"],
        }
    })


@app.route("/api/admin/logout", methods=["POST"])
@require_admin_auth()
def api_admin_logout():
    admin = g.admin_session
    conn = get_db()
    try:
        conn.execute("DELETE FROM admin_sessions WHERE token = ?", (admin["token"],))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"success": True})


@app.route("/api/admin/students", methods=["GET"])
@require_admin_auth()
def api_admin_list_students():
    status_filter = str(request.args.get("status") or "all").strip().lower()
    conn = get_db()
    try:
        all_rows = conn.execute(
            """
            SELECT * FROM student_accounts
            ORDER BY
                CASE status
                    WHEN 'pending' THEN 0
                    WHEN 'approved' THEN 1
                    WHEN 'suspended' THEN 2
                    ELSE 3
                END,
                id DESC
            """
        ).fetchall()
    finally:
        conn.close()

    counts = {
        "total": len(all_rows),
        "pending": 0,
        "approved": 0,
        "rejected": 0,
        "suspended": 0,
    }
    for r in all_rows:
        st = r["status"]
        if st in counts:
            counts[st] += 1

    if status_filter and status_filter != "all" and status_filter in VALID_STUDENT_STATUSES:
        filtered = [r for r in all_rows if r["status"] == status_filter]
    else:
        filtered = all_rows

    return jsonify({
        "students": [serialize_student(r) for r in filtered],
        "counts": counts,
    })


@app.route("/api/admin/students/<int:student_id>/id-photo", methods=["GET"])
@require_admin_auth(allow_query_token=True)
def api_admin_student_id_photo(student_id: int):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, id_photo_filename FROM student_accounts WHERE id = ?",
            (student_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return jsonify({"error": "Student account not found."}), 404

    filename = row["id_photo_filename"] or ""
    full_path = _resolve_safe_photo_path(filename)
    if not full_path or not os.path.isfile(full_path):
        return jsonify({"error": "School ID photo not found."}), 404

    _, ext = os.path.splitext(filename.lower())
    content_type = EXT_TO_MIME.get(ext, "application/octet-stream")
    with open(full_path, "rb") as fp:
        raw_bytes = fp.read()

    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if content_type == "image/svg+xml":
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"

    return Response(raw_bytes, status=200, mimetype=content_type, headers=headers)


@app.route("/api/admin/students/<int:student_id>/approve", methods=["POST"])
@require_admin_auth()
def api_admin_approve_student(student_id: int):
    admin = g.admin_session
    now_iso = datetime.now(timezone.utc).isoformat()
    reviewer = admin["name"] or admin["email"]

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM student_accounts WHERE id = ?", (student_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Student account not found."}), 404

        conn.execute(
            """
            UPDATE student_accounts
            SET status = 'approved', rejection_reason = '',
                reviewed_by = ?, reviewed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (reviewer, now_iso, now_iso, student_id),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM student_accounts WHERE id = ?", (student_id,)
        ).fetchone()
        student_dict = serialize_student(updated)
    finally:
        conn.close()

    broadcast_global_update({"event": "accounts_updated"})
    return jsonify({"success": True, "student": student_dict})


@app.route("/api/admin/students/<int:student_id>/reject", methods=["POST"])
@require_admin_auth()
def api_admin_reject_student(student_id: int):
    admin = g.admin_session
    data = request.get_json(silent=True) or {}
    reason = (
        str(data.get("reason") or "").strip()
        or "School ID photo could not be verified. Please re-submit with a clearer photo."
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    reviewer = admin["name"] or admin["email"]

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM student_accounts WHERE id = ?", (student_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Student account not found."}), 404

        conn.execute(
            """
            UPDATE student_accounts
            SET status = 'rejected', rejection_reason = ?,
                reviewed_by = ?, reviewed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (reason, reviewer, now_iso, now_iso, student_id),
        )
        conn.execute("DELETE FROM student_sessions WHERE student_id = ?", (student_id,))
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM student_accounts WHERE id = ?", (student_id,)
        ).fetchone()
        student_dict = serialize_student(updated)
    finally:
        conn.close()

    broadcast_global_update({"event": "accounts_updated"})
    return jsonify({"success": True, "student": student_dict})


@app.route("/api/admin/students/<int:student_id>/suspend", methods=["POST"])
@require_admin_auth()
def api_admin_suspend_student(student_id: int):
    admin = g.admin_session
    now_iso = datetime.now(timezone.utc).isoformat()
    reviewer = admin["name"] or admin["email"]

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM student_accounts WHERE id = ?", (student_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Student account not found."}), 404

        conn.execute(
            """
            UPDATE student_accounts
            SET status = 'suspended', reviewed_by = ?, reviewed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (reviewer, now_iso, now_iso, student_id),
        )
        conn.execute("DELETE FROM student_sessions WHERE student_id = ?", (student_id,))
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM student_accounts WHERE id = ?", (student_id,)
        ).fetchone()
        student_dict = serialize_student(updated)
    finally:
        conn.close()

    broadcast_global_update({"event": "accounts_updated"})
    return jsonify({"success": True, "student": student_dict})


@app.route("/api/admin/students/<int:student_id>", methods=["DELETE"])
@require_admin_auth()
def api_admin_delete_student(student_id: int):
    conn = get_db()
    photo_to_delete: Optional[str] = None
    try:
        row = conn.execute(
            "SELECT id, id_photo_filename FROM student_accounts WHERE id = ?",
            (student_id,),
        ).fetchone()
        if not row:
            return jsonify({"error": "Student account not found."}), 404

        photo_to_delete = row["id_photo_filename"]
        conn.execute("DELETE FROM student_sessions WHERE student_id = ?", (student_id,))
        conn.execute("DELETE FROM student_accounts WHERE id = ?", (student_id,))
        conn.commit()
    finally:
        conn.close()

    _delete_photo_file_safe(photo_to_delete)
    broadcast_global_update({"event": "accounts_updated"})
    return jsonify({"success": True})


@app.route("/api/admin/equipment", methods=["POST"])
@require_admin_auth()
def api_add_equipment():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Equipment name is required."}), 400

    conn = get_db()
    try:
        max_id = conn.execute("SELECT MAX(id) FROM equipment").fetchone()[0] or 0
        next_id = max_id + 1
        qr_code = str(data.get("qr_code") or "").strip().upper() or f"LG-EQ-{next_id:03d}"
        image_url = str(data.get("image_url") or "").strip() or "/images/equipment/LG-EQ-001.svg"
        category = data.get("category") or "Glassware & Measuring"
        description = (
            str(data.get("description") or "").strip()
            or f"{name} for AU-JRC Senior High School Science Laboratory."
        )
        compartment = str(data.get("storage_compartment") or "4th - 3rd Section").strip()
        total_qty = max(1, int(data.get("total_qty") or 1))
        unit = str(data.get("unit") or "unit").strip()
        safety_level = "CAUTION" if data.get("safety_level") == "CAUTION" else "SAFE"
        raw_prereqs = data.get("prerequisites")
        prereqs = (
            [str(p).strip() for p in raw_prereqs if str(p).strip()]
            if isinstance(raw_prereqs, list) and any(str(p).strip() for p in raw_prereqs)
            else ["Wear buttoned laboratory gown and follow AU-JRC safety rules"]
        )

        conn.execute(
            """
            INSERT INTO equipment (
                id, qr_code, name, category, image_url, description,
                storage_compartment, total_qty, available_qty, unit,
                condition, safety_level, prerequisites_json, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Good', ?, ?, 1, ?)
            """,
            (
                next_id,
                qr_code,
                name,
                category,
                image_url,
                description,
                compartment,
                total_qty,
                total_qty,
                unit,
                safety_level,
                json.dumps(prereqs),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM equipment WHERE id = ?", (next_id,)).fetchone()
        safety_dict = get_current_safety_status(conn)
        eq_dict = serialize_equipment(row)
    finally:
        conn.close()

    broadcast_global_update({
        "event": "data_updated",
        "safety_status": safety_dict,
        "hardware": led_controller.get_status(),
    })

    return jsonify({"equipment": eq_dict}), 201


@app.route("/api/admin/equipment/<int:item_id>", methods=["PATCH", "DELETE"])
@require_admin_auth()
def api_modify_equipment(item_id: int):
    conn = get_db()
    try:
        if request.method == "DELETE":
            conn.execute("DELETE FROM equipment WHERE id = ?", (item_id,))
            conn.commit()
            safety_dict = get_current_safety_status(conn)
            conn.close()
            broadcast_global_update({
                "event": "data_updated",
                "safety_status": safety_dict,
                "hardware": led_controller.get_status(),
            })
            return jsonify({"success": True})

        data = request.get_json(silent=True) or {}
        row = conn.execute("SELECT * FROM equipment WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return jsonify({"error": "Equipment not found."}), 404

        next_name = str(data["name"]).strip() if "name" in data and data["name"] is not None else row["name"]
        next_category = str(data["category"]).strip() if "category" in data and data["category"] is not None else row["category"]
        next_description = str(data["description"]).strip() if "description" in data and data["description"] is not None else row["description"]
        next_compartment = (
            str(data["storage_compartment"]).strip()
            if "storage_compartment" in data and data["storage_compartment"] is not None
            else row["storage_compartment"]
        )
        next_condition = (
            str(data["condition"]).strip()
            if "condition" in data and data["condition"] in ("Good", "Fair", "Damaged")
            else row["condition"]
        )
        next_safety_level = (
            data["safety_level"]
            if "safety_level" in data and data["safety_level"] in ("SAFE", "CAUTION")
            else row["safety_level"]
        )
        next_image_url = (
            str(data["image_url"]).strip()
            if "image_url" in data and data["image_url"] is not None
            else row["image_url"]
        )

        next_total = row["total_qty"]
        next_avail = row["available_qty"]
        if "total_qty" in data and data["total_qty"] is not None:
            next_total = max(0, int(data["total_qty"]))
            borrowed = max(0, row["total_qty"] - row["available_qty"])
            next_avail = max(0, next_total - borrowed)
        if "available_qty" in data and data["available_qty"] is not None:
            next_avail = max(0, min(next_total, int(data["available_qty"])))

        if "prerequisites" in data and isinstance(data["prerequisites"], list):
            next_prereqs_json = json.dumps(
                [str(p).strip() for p in data["prerequisites"] if str(p).strip()]
            )
        else:
            next_prereqs_json = row["prerequisites_json"]

        conn.execute(
            """
            UPDATE equipment
            SET name = ?, category = ?, description = ?, storage_compartment = ?,
                condition = ?, safety_level = ?, total_qty = ?, available_qty = ?,
                prerequisites_json = ?, image_url = ?
            WHERE id = ?
            """,
            (
                next_name,
                next_category,
                next_description,
                next_compartment,
                next_condition,
                next_safety_level,
                next_total,
                next_avail,
                next_prereqs_json,
                next_image_url,
                item_id,
            ),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM equipment WHERE id = ?", (item_id,)).fetchone()
        safety_dict = get_current_safety_status(conn)
        eq_dict = serialize_equipment(updated)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    broadcast_global_update({
        "event": "data_updated",
        "safety_status": safety_dict,
        "hardware": led_controller.get_status(),
    })
    return jsonify({"equipment": eq_dict})


@app.route("/api/admin/safety-status", methods=["POST"])
@require_admin_auth()
def api_update_safety_status():
    admin = g.admin_session
    data = request.get_json(silent=True) or {}
    level = data.get("level") if data.get("level") in ("SAFE", "CAUTION", "UNSAFE") else "SAFE"
    preset = SAFETY_PRESETS[level]
    message = str(data.get("message") or "").strip() or preset["message"]
    updated_by = (
        str(data.get("updated_by") or "").strip()
        or admin.get("name")
        or "AU-JRC Science Laboratory Personnel"
    )
    now_iso = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    try:
        conn.execute(
            """
            UPDATE safety_status
            SET level = ?, headline = ?, message = ?, updated_by = ?, updated_at = ?
            WHERE id = 1
            """,
            (level, preset["headline"], message, updated_by, now_iso),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM safety_status WHERE id = 1").fetchone()
        safety_dict = serialize_safety_status(row)
    finally:
        conn.close()

    hw_status = led_controller.set_safety_level(level, beep_on_change=True)

    broadcast_global_update({
        "event": "data_updated",
        "safety_status": safety_dict,
        "hardware": hw_status,
    })

    return jsonify({"safety_status": safety_dict})


@app.route("/api/reset", methods=["POST"])
@require_admin_auth()
def api_reset():
    init_db(force_reset=True, beep_on_sync=True)
    safety_dict = get_current_safety_status()
    broadcast_global_update({
        "event": "data_updated",
        "safety_status": safety_dict,
        "hardware": led_controller.get_status(),
    })
    broadcast_global_update({"event": "accounts_updated"})
    return jsonify({"success": True})


if __name__ == "__main__":
    init_db(force_reset=False, beep_on_sync=False)
    port = get_server_port()
    base_url = resolve_public_base_url(None)
    hw = led_controller.get_status()
    print(f"LabGuard+ Python Flask Server running on http://0.0.0.0:{port}")
    print(f"  -> LAN Base URL:        {base_url}")
    print(f"  -> Student Kiosk UI:    {base_url}/kiosk")
    print(f"  -> Student Register UI: {base_url}/student/register")
    print(f"  -> Admin Dashboard UI:  {base_url}/admin")
    print(f"  -> SQLite Database:     {get_db_path()}")
    print(f"  -> ID Photos Directory: {get_id_photos_dir()}")
    print(f"  -> Hardware LED Mode:   {hw['hardware_mode']} ({hw['note']})")
    print(f"  -> WebSockets:          {'enabled (flask-sock)' if sock is not None else 'disabled (polling fallback)'}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
