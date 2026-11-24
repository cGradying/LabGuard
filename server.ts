/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import express from 'express';
import { createServer } from 'http';
import { WebSocketServer, WebSocket } from 'ws';
import QRCode from 'qrcode';
import crypto from 'crypto';
import os from 'os';
import path from 'path';
import fs from 'fs';
import {
  INITIAL_EQUIPMENT,
  INITIAL_TRANSACTIONS,
  INITIAL_SAFETY_STATUS,
  SAFETY_PRESET_MESSAGES,
  STUDENT_PRESETS,
} from './src/data/seedData.ts';
import { EQUIPMENT_SVG_MAP } from './src/data/equipmentImages.ts';
import type {
  Equipment,
  BasketItem,
  CheckoutSession,
  ReturnSession,
  StudentTransactionLog,
  SafetyStatusState,
  SafetyStatusLevel,
} from './src/types.ts';

const PORT = Number(process.env.PORT || 3000);

const DEFAULT_ADMIN_EMAIL = 'lara.puertollano@arellano.edu.ph';
const DEFAULT_ADMIN_PASSWORD = 'au-jrc-2026';
const DEFAULT_ADMIN_NAME = 'Ms. Lara Marie A. Puertollano';

const PBKDF2_ITERATIONS = 120000;
const MAX_ID_PHOTO_BYTES = 4 * 1024 * 1024;
const ADMIN_SESSION_MS = 24 * 60 * 60 * 1000;
const STUDENT_SESSION_MS = 7 * 24 * 60 * 60 * 1000;
const RETURN_SESSION_MS = 10 * 60 * 1000;
const VALID_GRADE_SECTIONS = new Set(['STEM', 'HUMSS', 'ABM', 'FACULTY']);
const VALID_STUDENT_STATUSES = new Set(['pending', 'approved', 'rejected', 'suspended']);
const IMAGE_DATA_URL_RE = /^data:image\/(jpeg|jpg|png|webp|svg\+xml);base64,([A-Za-z0-9+/=\s]+)$/i;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const MIME_TO_EXT: Record<string, string> = {
  jpeg: 'jpg',
  jpg: 'jpg',
  png: 'png',
  webp: 'webp',
  'svg+xml': 'svg',
};

const EXT_TO_MIME: Record<string, string> = {
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
};

type StudentAccountStatus = 'pending' | 'approved' | 'rejected' | 'suspended';

interface StudentAccountRecord {
  id: number;
  student_id_lrn: string;
  full_name: string;
  grade_section: string;
  school_email: string;
  password_hash: string;
  id_photo_filename: string;
  status: StudentAccountStatus;
  rejection_reason: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

interface StudentSessionRecord {
  token: string;
  student_id: number;
  created_at: string;
  expires_at: string;
}

interface AdminSessionRecord {
  token: string;
  email: string;
  name: string;
  created_at: string;
  expires_at: string;
}

interface StoredIdPhoto {
  data: Buffer;
  contentType: string;
}

function getAdminEmail(): string {
  return (process.env.LABGUARD_ADMIN_EMAIL || DEFAULT_ADMIN_EMAIL).trim();
}

function getAdminPassword(): string {
  return process.env.LABGUARD_ADMIN_PASSWORD || DEFAULT_ADMIN_PASSWORD;
}

function getAdminName(): string {
  return (process.env.LABGUARD_ADMIN_NAME || DEFAULT_ADMIN_NAME).trim();
}

function constantTimeStringEqual(a: string, b: string): boolean {
  const digestA = crypto.createHash('sha256').update(a, 'utf8').digest();
  const digestB = crypto.createHash('sha256').update(b, 'utf8').digest();
  return crypto.timingSafeEqual(digestA, digestB);
}

function hashPassword(password: string): string {
  const salt = crypto.randomBytes(16);
  const dk = crypto.pbkdf2Sync(password, salt, PBKDF2_ITERATIONS, 32, 'sha256');
  return `pbkdf2_sha256$${PBKDF2_ITERATIONS}$${salt.toString('hex')}$${dk.toString('hex')}`;
}

function verifyPassword(password: string, storedHash: string): boolean {
  try {
    const parts = storedHash.split('$');
    if (parts.length !== 4 || parts[0] !== 'pbkdf2_sha256') return false;
    const iterations = Number(parts[1]);
    if (!Number.isInteger(iterations) || iterations < 1) return false;
    const salt = Buffer.from(parts[2], 'hex');
    const expected = Buffer.from(parts[3], 'hex');
    if (salt.length === 0 || expected.length === 0) return false;
    const dk = crypto.pbkdf2Sync(password, salt, iterations, expected.length, 'sha256');
    return dk.length === expected.length && crypto.timingSafeEqual(dk, expected);
  } catch {
    return false;
  }
}

function escapeXml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function buildSampleSchoolIdSvg(
  fullName: string,
  lrn: string,
  gradeSection: string,
  schoolEmail: string,
  status: StudentAccountStatus
): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  const initials =
    parts.length >= 2
      ? `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase()
      : (fullName.slice(0, 2) || 'AU').toUpperCase();
  const badgeColor = status === 'approved' ? '#16A34A' : '#F5A623';
  const badgeLabel = status === 'approved' ? 'VERIFIED STUDENT ID' : 'SAMPLE ID · PENDING REVIEW';

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 400" width="640" height="400">
  <defs>
    <linearGradient id="auHdr" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#002366"/>
      <stop offset="100%" stop-color="#003087"/>
    </linearGradient>
  </defs>
  <rect width="640" height="400" rx="22" fill="#F8FAFC" stroke="#CBD5E1" stroke-width="4"/>
  <path d="M22 0 H618 A22 22 0 0 1 640 22 V102 H0 V22 A22 22 0 0 1 22 0 Z" fill="url(#auHdr)"/>
  <rect x="0" y="102" width="640" height="8" fill="#C8102E"/>
  <circle cx="58" cy="52" r="30" fill="#FFFFFF" stroke="#F5A623" stroke-width="4"/>
  <text x="58" y="59" text-anchor="middle" font-family="system-ui, -apple-system, sans-serif" font-size="22" font-weight="800" fill="#003087">AU</text>
  <text x="104" y="44" font-family="system-ui, -apple-system, sans-serif" font-size="22" font-weight="800" fill="#FFFFFF" letter-spacing="0.5">ARELLANO UNIVERSITY</text>
  <text x="104" y="68" font-family="system-ui, -apple-system, sans-serif" font-size="13" font-weight="600" fill="#DBEAFE">JOSE RIZAL CAMPUS · SENIOR HIGH SCHOOL DEPARTMENT</text>
  <text x="104" y="88" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" fill="#FDE68A" letter-spacing="1.2">OFFICIAL STUDENT IDENTIFICATION CARD · S.Y. 2025-2026</text>

  <rect x="28" y="132" width="142" height="174" rx="14" fill="#E2E8F0" stroke="#94A3B8" stroke-width="2"/>
  <circle cx="99" cy="190" r="34" fill="#003087"/>
  <path d="M52 288 C52 248 146 248 146 288 Z" fill="#003087"/>
  <text x="99" y="199" text-anchor="middle" font-family="system-ui, -apple-system, sans-serif" font-size="24" font-weight="800" fill="#FFFFFF">${escapeXml(initials)}</text>
  <rect x="28" y="316" width="142" height="28" rx="8" fill="#003087"/>
  <text x="99" y="335" text-anchor="middle" font-family="system-ui, -apple-system, sans-serif" font-size="13" font-weight="800" fill="#FFFFFF">${escapeXml(gradeSection)}</text>

  <text x="196" y="156" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" fill="#64748B" letter-spacing="1">STUDENT FULL NAME</text>
  <text x="196" y="184" font-family="system-ui, -apple-system, sans-serif" font-size="22" font-weight="800" fill="#0F172A">${escapeXml(fullName)}</text>

  <text x="196" y="218" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" fill="#64748B" letter-spacing="1">STUDENT ID / LRN</text>
  <text x="196" y="244" font-family="ui-monospace, SFMono-Regular, monospace" font-size="20" font-weight="800" fill="#003087">${escapeXml(lrn)}</text>

  <text x="196" y="276" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="700" fill="#64748B" letter-spacing="1">INSTITUTIONAL EMAIL</text>
  <text x="196" y="298" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="600" fill="#334155">${escapeXml(schoolEmail)}</text>

  <rect x="196" y="316" width="248" height="28" rx="14" fill="${badgeColor}"/>
  <text x="320" y="335" text-anchor="middle" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="800" fill="#FFFFFF" letter-spacing="0.8">${escapeXml(badgeLabel)}</text>

  <rect x="0" y="364" width="640" height="36" fill="#0F172A"/>
  <text x="28" y="387" font-family="ui-monospace, SFMono-Regular, monospace" font-size="12" font-weight="600" fill="#E2E8F0">AU-JRC SCIENCE LABORATORY · LABGUARD+ VERIFIED CREDENTIAL</text>
</svg>`;
}

// Ensure static SVG files exist in /public/images/equipment for both Python Flask and Express
const eqImgDir = path.resolve(process.cwd(), 'public', 'images', 'equipment');
try {
  fs.mkdirSync(eqImgDir, { recursive: true });
  for (const [qrCode, svgContent] of Object.entries(EQUIPMENT_SVG_MAP)) {
    fs.writeFileSync(path.join(eqImgDir, `${qrCode}.svg`), svgContent, 'utf-8');
  }
} catch {
  // ignore in read-only environments
}

function enrichEquipmentWithImages(list: Equipment[]): Equipment[] {
  return list.map((item) => ({
    ...item,
    image_url: item.image_url || `/images/equipment/${item.qr_code}.svg`,
    prerequisites: Array.isArray(item.prerequisites) ? [...item.prerequisites] : [],
    usage_instructions: Array.isArray(item.usage_instructions)
      ? [...item.usage_instructions]
      : [],
  }));
}

function enrichBasketItemsWithInstructions(items: BasketItem[]): BasketItem[] {
  const byId = new Map(equipmentList.map((e) => [e.id, e]));
  const byQr = new Map(equipmentList.map((e) => [e.qr_code.toUpperCase(), e]));
  return (items || []).map((item) => {
    const eq =
      byId.get(Number(item.equipment_id)) ||
      (item.qr_code ? byQr.get(String(item.qr_code).toUpperCase()) : undefined);
    const prereqs = Array.isArray(item.prerequisites)
      ? item.prerequisites.map((s) => String(s).trim()).filter(Boolean)
      : [];
    const usage = Array.isArray(item.usage_instructions)
      ? item.usage_instructions.map((s) => String(s).trim()).filter(Boolean)
      : [];
    return {
      ...item,
      image_url: item.image_url || eq?.image_url || `/images/equipment/${item.qr_code}.svg`,
      prerequisites: prereqs.length > 0 ? prereqs : [...(eq?.prerequisites || [])],
      usage_instructions: usage.length > 0 ? usage : [...(eq?.usage_instructions || [])],
    };
  });
}

function enrichTransactionWithInstructions(tx: StudentTransactionLog): StudentTransactionLog {
  return {
    ...tx,
    student_account_id: tx.student_account_id ?? null,
    returned_verified_by: tx.returned_verified_by ?? null,
    items: enrichBasketItemsWithInstructions(tx.items || []),
  };
}

function maskStudentName(fullName?: string | null): string {
  const cleaned = String(fullName || '').trim();
  if (!cleaned) return 'Student';
  return cleaned
    .split(/\s+/)
    .map((p) => {
      if (p.length <= 2) return p;
      return `${p[0]}${'*'.repeat(Math.max(1, p.length - 2))}${p[p.length - 1]}`;
    })
    .join(' ');
}

function maskStudentId(studentId?: string | null): string {
  const cleaned = String(studentId || '').trim();
  if (!cleaned) return '********';
  if (cleaned.length <= 4) return '****';
  return `${'*'.repeat(cleaned.length - 4)}${cleaned.slice(-4)}`;
}

function isTransactionOwner(
  tx: StudentTransactionLog,
  studentAcc: StudentAccountRecord
): boolean {
  if (
    tx.student_account_id !== null &&
    tx.student_account_id !== undefined &&
    tx.student_account_id === studentAcc.id
  ) {
    return true;
  }
  const txLrn = String(tx.student_id_lrn || '').trim().toUpperCase();
  const stuLrn = String(studentAcc.student_id_lrn || '').trim().toUpperCase();
  return Boolean(txLrn) && txLrn === stuLrn;
}

function buildTransactionPreview(tx: StudentTransactionLog) {
  const enriched = enrichTransactionWithInstructions(tx);
  return {
    id: enriched.id,
    transaction_code: enriched.transaction_code,
    masked_student_name: maskStudentName(enriched.student_name),
    masked_student_id: maskStudentId(enriched.student_id_lrn),
    grade_section: enriched.grade_section,
    time_in: enriched.time_in,
    expected_return: enriched.expected_return,
    items: enriched.items,
    status: enriched.status,
  };
}

// Server-authoritative database state
let equipmentList: Equipment[] = enrichEquipmentWithImages(structuredClone(INITIAL_EQUIPMENT));
let transactionLogs: StudentTransactionLog[] = structuredClone(INITIAL_TRANSACTIONS);
let safetyStatus: SafetyStatusState = structuredClone(INITIAL_SAFETY_STATUS);
const checkoutSessions: Map<string, CheckoutSession> = new Map();
const returnSessions: Map<string, ReturnSession> = new Map();
let studentAccounts: StudentAccountRecord[] = [];
let nextStudentAccountId = 1;
const studentSessions: Map<string, StudentSessionRecord> = new Map();
const adminSessions: Map<string, AdminSessionRecord> = new Map();
const studentPhotoStore: Map<string, StoredIdPhoto> = new Map();

function seedStudentAccounts(): void {
  studentAccounts = [];
  studentPhotoStore.clear();
  nextStudentAccountId = 1;
  const now = Date.now();
  const demoSeeds: Array<{
    student_id_lrn: string;
    full_name: string;
    grade_section: string;
    school_email: string;
    password: string;
    status: StudentAccountStatus;
  }> = [
    {
      student_id_lrn: 'AUJRC-2026-0101',
      full_name: 'One Enrique Sebastian G. Abalos',
      grade_section: 'STEM',
      school_email: 'one.abalos@arellano.edu.ph',
      password: 'student123',
      status: 'approved',
    },
    {
      student_id_lrn: 'AUJRC-2026-0102',
      full_name: 'Christine S. Contreras',
      grade_section: 'STEM',
      school_email: 'christine.contreras@arellano.edu.ph',
      password: 'student123',
      status: 'approved',
    },
    {
      student_id_lrn: 'AUJRC-2026-0103',
      full_name: 'Queen Hannah A. Dones',
      grade_section: 'HUMSS',
      school_email: 'queenhannah.dones@arellano.edu.ph',
      password: 'student123',
      status: 'approved',
    },
    {
      student_id_lrn: 'AUJRC-2026-0105',
      full_name: 'Ashlyjicks B. Pangilinan',
      grade_section: 'STEM',
      school_email: 'ashlyjicks.pangilinan@arellano.edu.ph',
      password: 'student123',
      status: 'pending',
    },
  ];

  const adminName = getAdminName();
  for (const seed of demoSeeds) {
    const id = nextStudentAccountId++;
    const safeLrn = seed.student_id_lrn.replace(/[^A-Z0-9_-]+/g, '_');
    const filename = `seed_${safeLrn}.svg`;
    const svg = buildSampleSchoolIdSvg(
      seed.full_name,
      seed.student_id_lrn,
      seed.grade_section,
      seed.school_email,
      seed.status
    );
    studentPhotoStore.set(filename, {
      data: Buffer.from(svg, 'utf-8'),
      contentType: 'image/svg+xml',
    });

    const isApproved = seed.status === 'approved';
    const createdAt = new Date(
      isApproved ? now - 3 * 24 * 3600 * 1000 : now - 25 * 60 * 1000
    ).toISOString();
    const updatedAt = new Date(
      isApproved ? now - 2 * 24 * 3600 * 1000 : now - 25 * 60 * 1000
    ).toISOString();

    studentAccounts.push({
      id,
      student_id_lrn: seed.student_id_lrn,
      full_name: seed.full_name,
      grade_section: seed.grade_section,
      school_email: seed.school_email,
      password_hash: hashPassword(seed.password),
      id_photo_filename: filename,
      status: seed.status,
      rejection_reason: '',
      reviewed_by: isApproved ? adminName : null,
      reviewed_at: isApproved ? updatedAt : null,
      created_at: createdAt,
      updated_at: updatedAt,
    });
  }
}

function linkSeededTransactionsToAccounts(): void {
  const accByLrn = new Map(
    studentAccounts.map((a) => [a.student_id_lrn.toUpperCase(), a.id])
  );
  transactionLogs = transactionLogs.map((tx) => ({
    ...tx,
    student_account_id:
      tx.student_account_id ?? accByLrn.get(tx.student_id_lrn.toUpperCase()) ?? null,
    returned_verified_by: tx.returned_verified_by ?? null,
    items: enrichBasketItemsWithInstructions(tx.items || []),
  }));
}

seedStudentAccounts();
linkSeededTransactionsToAccounts();

function serializeStudent(acc: StudentAccountRecord) {
  return {
    id: acc.id,
    student_id_lrn: acc.student_id_lrn,
    full_name: acc.full_name,
    grade_section: acc.grade_section,
    school_email: acc.school_email,
    status: acc.status,
    rejection_reason: acc.rejection_reason || '',
    reviewed_by: acc.reviewed_by,
    reviewed_at: acc.reviewed_at,
    created_at: acc.created_at,
    updated_at: acc.updated_at,
    has_id_photo: Boolean(acc.id_photo_filename && studentPhotoStore.has(acc.id_photo_filename)),
    id_photo_url: `/api/admin/students/${acc.id}/id-photo`,
  };
}

function extractBearerToken(req: express.Request, allowQueryToken = false): string | null {
  const authHeader = String(req.headers.authorization || '').trim();
  if (authHeader.toLowerCase().startsWith('bearer ')) {
    const token = authHeader.slice(7).trim();
    if (token) return token;
  }
  if (allowQueryToken && typeof req.query.token === 'string' && req.query.token.trim()) {
    return req.query.token.trim();
  }
  return null;
}

function getAuthenticatedStudent(
  req: express.Request
): { account: StudentAccountRecord; token: string } | null {
  const token = extractBearerToken(req, false);
  if (!token) return null;
  const sess = studentSessions.get(token);
  if (!sess) return null;
  if (Date.parse(sess.expires_at) <= Date.now()) {
    studentSessions.delete(token);
    return null;
  }
  const acc = studentAccounts.find((a) => a.id === sess.student_id);
  if (!acc) {
    studentSessions.delete(token);
    return null;
  }
  return { account: acc, token };
}

function getAuthenticatedAdmin(
  req: express.Request,
  allowQueryToken = false
): AdminSessionRecord | null {
  const token = extractBearerToken(req, allowQueryToken);
  if (!token) return null;
  const session = adminSessions.get(token);
  if (!session) return null;
  if (Date.parse(session.expires_at) <= Date.now()) {
    adminSessions.delete(token);
    return null;
  }
  return session;
}

function requireAdminAuth(
  req: express.Request,
  res: express.Response,
  allowQueryToken = false
): AdminSessionRecord | null {
  const session = getAuthenticatedAdmin(req, allowQueryToken);
  if (!session) {
    res.status(401).json({ error: 'Administrator authentication required.' });
    return null;
  }
  return session;
}

function saveIdPhotoFromDataUrl(
  studentIdLrn: string,
  dataUrl: string
): { filename?: string; error?: string } {
  const match = IMAGE_DATA_URL_RE.exec(dataUrl.trim());
  if (!match) {
    return {
      error:
        'Please upload a valid School ID image (JPEG, PNG, WEBP, or SVG data URL required).',
    };
  }
  const mimeSub = match[1].toLowerCase();
  const ext = MIME_TO_EXT[mimeSub];
  if (!ext) {
    return { error: 'Unsupported School ID image format.' };
  }
  const b64Clean = match[2].replace(/\s+/g, '');
  let decoded: Buffer;
  try {
    decoded = Buffer.from(b64Clean, 'base64');
  } catch {
    return { error: 'Invalid base64 image data for School ID photo.' };
  }
  if (!decoded || decoded.length === 0) {
    return { error: 'Uploaded School ID image is empty.' };
  }
  if (decoded.length > MAX_ID_PHOTO_BYTES) {
    return { error: 'School ID photo exceeds the 4 MB maximum file size.' };
  }
  const safeLrn =
    studentIdLrn
      .toUpperCase()
      .replace(/[^A-Z0-9_-]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 40) || 'STUDENT';
  const filename = `${safeLrn}_${crypto.randomBytes(6).toString('hex')}.${ext}`;
  const contentType = EXT_TO_MIME[`.${ext}`] || 'application/octet-stream';
  studentPhotoStore.set(filename, { data: decoded, contentType });
  return { filename };
}

// WebSocket channels
const checkoutSockets: Map<string, Set<WebSocket>> = new Map();
const returnSockets: Map<string, Set<WebSocket>> = new Map();
const globalSockets: Set<WebSocket> = new Set();

function broadcastToCheckoutSession(token: string, payload: unknown) {
  const clients = checkoutSockets.get(token);
  if (!clients) return;
  const msg = JSON.stringify(payload);
  for (const ws of clients) {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(msg);
    }
  }
}

function broadcastToReturnSession(token: string, payload: unknown) {
  const clients = returnSockets.get(token);
  if (!clients) return;
  const msg = JSON.stringify(payload);
  for (const ws of clients) {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(msg);
    }
  }
}

function broadcastGlobalUpdate(payload: unknown) {
  const msg = JSON.stringify(payload);
  for (const ws of globalSockets) {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(msg);
    }
  }
}

function generateSessionToken(): string {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let result = 'CHK-';
  for (let i = 0; i < 8; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return result;
}

function generateReturnSessionToken(): string {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  for (let attempt = 0; attempt < 16; attempt++) {
    let result = 'RET-';
    const bytes = crypto.randomBytes(8);
    for (let i = 0; i < 8; i++) {
      result += chars.charAt(bytes[i] % chars.length);
    }
    if (!returnSessions.has(result)) {
      return result;
    }
  }
  return `RET-${crypto.randomBytes(4).toString('hex').toUpperCase()}`;
}

function detectLanIp(): string | null {
  const interfaces = os.networkInterfaces();
  let fallbackIp: string | null = null;

  for (const entries of Object.values(interfaces)) {
    if (!entries) continue;
    for (const entry of entries) {
      if (entry.internal || entry.family !== 'IPv4') continue;
      const addr = entry.address;
      if (!addr || addr.startsWith('127.') || addr === '0.0.0.0') continue;
      if (addr.startsWith('169.254.')) {
        if (!fallbackIp) fallbackIp = addr;
        continue;
      }
      // Prefer RFC1918 private LAN addresses (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
      if (
        addr.startsWith('192.168.') ||
        addr.startsWith('10.') ||
        /^172\.(1[6-9]|2\d|3[01])\./.test(addr)
      ) {
        return addr;
      }
      if (!fallbackIp) fallbackIp = addr;
    }
  }

  return fallbackIp;
}

function resolvePublicBaseUrl(req?: express.Request): string {
  const envUrl = (process.env.APP_URL || process.env.LABGUARD_PUBLIC_URL || '')
    .trim()
    .replace(/\/$/, '');
  if (envUrl) {
    return envUrl;
  }

  if (!req) {
    const lanIp = detectLanIp() || '127.0.0.1';
    return `http://${lanIp}:${PORT}`;
  }

  const forwardedProtoHeader = req.headers['x-forwarded-proto'];
  const forwardedProto = Array.isArray(forwardedProtoHeader)
    ? forwardedProtoHeader[0]
    : forwardedProtoHeader?.split(',')[0]?.trim();
  const protocol = forwardedProto || req.protocol || 'http';

  const forwardedHostHeader = req.headers['x-forwarded-host'];
  const forwardedHost = Array.isArray(forwardedHostHeader)
    ? forwardedHostHeader[0]
    : forwardedHostHeader?.split(',')[0]?.trim();
  const rawHost = forwardedHost || req.headers.host || `localhost:${PORT}`;

  try {
    const parsed = new URL(`${protocol}://${rawHost}`);
    const hostname = parsed.hostname.toLowerCase();
    if (
      hostname === 'localhost' ||
      hostname === '127.0.0.1' ||
      hostname === '0.0.0.0' ||
      hostname === '::1' ||
      hostname === '[::1]'
    ) {
      const lanIp = detectLanIp();
      if (lanIp) {
        return `${protocol}://${lanIp}${parsed.port ? `:${parsed.port}` : ''}`;
      }
    }
  } catch {
    // Fall through to rawHost
  }

  return `${protocol}://${rawHost}`.replace(/\/$/, '');
}

function getHardwareStatus() {
  return {
    hardware_mode: 'simulation',
    is_raspberry_pi: false,
    gpio_active: false,
    active_high: true,
    current_level: safetyStatus.level,
    led_state: {
      green: safetyStatus.level === 'SAFE',
      yellow: safetyStatus.level === 'CAUTION',
      red: safetyStatus.level === 'UNSAFE',
    },
    pins: {
      green: 17,
      yellow: 27,
      red: 22,
      buzzer: 23,
    },
    note: 'Node.js Express runtime — LED status running in simulation mode (use Python Flask app.py for Raspberry Pi GPIO).',
  };
}

async function startServer() {
  const app = express();
  app.use(express.json({ limit: '8mb' }));

  const httpServer = createServer(app);
  const wss = new WebSocketServer({ noServer: true });

  httpServer.on('upgrade', (request, socket, head) => {
    const url = new URL(request.url || '/', `http://${request.headers.host}`);
    const pathname = url.pathname;

    if (pathname.startsWith('/ws/checkout/')) {
      const token = pathname.replace('/ws/checkout/', '').trim();
      wss.handleUpgrade(request, socket, head, (ws) => {
        if (!checkoutSockets.has(token)) {
          checkoutSockets.set(token, new Set());
        }
        checkoutSockets.get(token)!.add(ws);
        ws.on('close', () => {
          checkoutSockets.get(token)?.delete(ws);
        });
      });
    } else if (pathname.startsWith('/ws/return/')) {
      const token = pathname.replace('/ws/return/', '').trim();
      wss.handleUpgrade(request, socket, head, (ws) => {
        if (!returnSockets.has(token)) {
          returnSockets.set(token, new Set());
        }
        returnSockets.get(token)!.add(ws);
        ws.on('close', () => {
          const bucket = returnSockets.get(token);
          bucket?.delete(ws);
          if (bucket && bucket.size === 0) {
            returnSockets.delete(token);
          }
        });
      });
    } else if (pathname === '/ws/kiosk' || pathname === '/ws/hardware') {
      wss.handleUpgrade(request, socket, head, (ws) => {
        globalSockets.add(ws);
        ws.send(
          JSON.stringify({
            event: 'state_sync',
            safety_status: safetyStatus,
            hardware: getHardwareStatus(),
          })
        );
        ws.on('close', () => {
          globalSockets.delete(ws);
        });
      });
    } else {
      socket.destroy();
    }
  });

  // ============================================================================
  // Static Public Assets (/images/au_seal.jpg, /css/labguard.css, /images/equipment/*.svg)
  // Always mounted BEFORE Vite/production fallback so assets work in dev AND prod
  // ============================================================================
  app.use(express.static(path.resolve(process.cwd(), 'public')));

  // Fallback Equipment SVG Image Route (/images/equipment/:filename)
  app.get('/images/equipment/:filename', (req, res) => {
    const code = req.params.filename.replace(/\.svg$/i, '').toUpperCase();
    const svg = EQUIPMENT_SVG_MAP[code] || EQUIPMENT_SVG_MAP['LG-EQ-002'];
    res.setHeader('Content-Type', 'image/svg+xml');
    res.send(svg);
  });

  // ============================================================================
  // HTML TEMPLATE ROUTES (/kiosk, /student/checkout/:token, /student/return/:token, /student/register, /admin)
  // ============================================================================
  const templatesDir = path.resolve(process.cwd(), 'templates');

  app.get(['/', '/kiosk', '/kiosk.html'], (_req, res) => {
    res.sendFile(path.join(templatesDir, 'kiosk.html'));
  });

  app.get(['/student/checkout/:token', '/student_form.html'], (_req, res) => {
    res.sendFile(path.join(templatesDir, 'student_form.html'));
  });

  app.get(['/student/return/:token', '/student_return.html'], (_req, res) => {
    res.sendFile(path.join(templatesDir, 'student_return.html'));
  });

  app.get(['/student/register', '/student_register.html'], (_req, res) => {
    res.sendFile(path.join(templatesDir, 'student_register.html'));
  });

  app.get(['/student/account', '/student_account.html'], (_req, res) => {
    res.sendFile(path.join(templatesDir, 'student_account.html'));
  });

  app.get(['/admin', '/admin.html'], (_req, res) => {
    res.sendFile(path.join(templatesDir, 'admin.html'));
  });

  // ============================================================================
  // Health, Hardware Status & Unified State / Kiosk / Student / Admin API Endpoints
  // ============================================================================
  app.get('/api/health', (req, res) => {
    const baseUrl = resolvePublicBaseUrl(req);
    res.json({
      status: 'ok',
      system: 'LabGuard+',
      runtime: 'node-express',
      lan_url: baseUrl,
      kiosk_url: `${baseUrl}/kiosk`,
      admin_url: `${baseUrl}/admin`,
      hardware: getHardwareStatus(),
    });
  });

  app.get('/api/hardware/status', (req, res) => {
    const baseUrl = resolvePublicBaseUrl(req);
    res.json({
      hardware: getHardwareStatus(),
      lan_url: baseUrl,
      kiosk_url: `${baseUrl}/kiosk`,
      admin_url: `${baseUrl}/admin`,
    });
  });

  app.get('/api/state', (_req, res) => {
    res.json({
      equipment: equipmentList,
      transactions: transactionLogs,
      safety_status: safetyStatus,
      student_presets: STUDENT_PRESETS,
    });
  });

  app.get('/api/kiosk/registration-qr', async (req, res) => {
    try {
      const baseUrl = resolvePublicBaseUrl(req);
      const registerUrl = `${baseUrl}/student/register`;
      const accountUrl = `${baseUrl}/student/account`;
      const qrOpts = {
        width: 300,
        margin: 1,
        color: {
          dark: '#003087',
          light: '#FFFFFF',
        },
      };
      const [qrDataUrl, accountQrDataUrl] = await Promise.all([
        QRCode.toDataURL(registerUrl, qrOpts),
        QRCode.toDataURL(accountUrl, qrOpts),
      ]);
      res.json({
        register_url: registerUrl,
        account_url: accountUrl,
        qr_data_url: qrDataUrl,
        account_qr_data_url: accountQrDataUrl,
      });
    } catch (err) {
      res.status(500).json({ error: String(err) });
    }
  });

  // ============================================================================
  // SPEC-01: Student Registration, Status Check & Authentication
  // ============================================================================
  app.post('/api/students/register', (req, res) => {
    const fullName = String(req.body?.full_name || '').trim();
    const studentIdLrn = String(req.body?.student_id_lrn || '').trim().toUpperCase();
    const gradeSection = String(req.body?.grade_section || '').trim().toUpperCase();
    const schoolEmail = String(req.body?.school_email || '').trim().toLowerCase();
    const password = String(req.body?.password || '');
    const idPhotoDataUrl = String(req.body?.id_photo_data_url || '').trim();

    if (!fullName || !studentIdLrn || !gradeSection || !schoolEmail || !password || !idPhotoDataUrl) {
      res.status(400).json({
        error:
          'Please fill in Full Name, Student ID / LRN, Strand / Faculty, School Email, Password, and upload your School ID photo.',
      });
      return;
    }

    if (!VALID_GRADE_SECTIONS.has(gradeSection)) {
      res.status(400).json({
        error: 'Strand / Faculty must be one of STEM, HUMSS, ABM, or FACULTY.',
      });
      return;
    }

    if (!EMAIL_RE.test(schoolEmail)) {
      res.status(400).json({ error: 'Please enter a valid school email address.' });
      return;
    }

    if (password.length < 6) {
      res.status(400).json({ error: 'Password must be at least 6 characters long.' });
      return;
    }

    const matches = studentAccounts.filter(
      (a) => a.student_id_lrn === studentIdLrn || a.school_email === schoolEmail
    );

    if (matches.length > 1 || (matches.length === 1 && matches[0].status !== 'rejected')) {
      res.status(409).json({
        error: 'A student account with this Student ID / LRN or School Email already exists.',
      });
      return;
    }

    const saved = saveIdPhotoFromDataUrl(studentIdLrn, idPhotoDataUrl);
    if (!saved.filename) {
      res.status(400).json({ error: saved.error || 'Invalid School ID image.' });
      return;
    }

    const nowIso = new Date().toISOString();
    const passwordHash = hashPassword(password);

    let record: StudentAccountRecord;
    if (matches.length === 1 && matches[0].status === 'rejected') {
      record = matches[0];
      const oldPhoto = record.id_photo_filename;
      record.student_id_lrn = studentIdLrn;
      record.full_name = fullName;
      record.grade_section = gradeSection;
      record.school_email = schoolEmail;
      record.password_hash = passwordHash;
      record.id_photo_filename = saved.filename;
      record.status = 'pending';
      record.rejection_reason = '';
      record.reviewed_by = null;
      record.reviewed_at = null;
      record.updated_at = nowIso;
      if (oldPhoto && oldPhoto !== saved.filename) {
        studentPhotoStore.delete(oldPhoto);
      }
    } else {
      record = {
        id: nextStudentAccountId++,
        student_id_lrn: studentIdLrn,
        full_name: fullName,
        grade_section: gradeSection,
        school_email: schoolEmail,
        password_hash: passwordHash,
        id_photo_filename: saved.filename,
        status: 'pending',
        rejection_reason: '',
        reviewed_by: null,
        reviewed_at: null,
        created_at: nowIso,
        updated_at: nowIso,
      };
      studentAccounts.push(record);
    }

    broadcastGlobalUpdate({ event: 'accounts_updated' });
    res.status(201).json({
      success: true,
      student: serializeStudent(record),
    });
  });

  app.get('/api/students/status', (req, res) => {
    const identifier = String(req.query.identifier || '').trim();
    if (!identifier) {
      res.json({ found: false });
      return;
    }
    const upper = identifier.toUpperCase();
    const lower = identifier.toLowerCase();
    const acc = studentAccounts.find(
      (a) => a.student_id_lrn === upper || a.school_email === lower
    );
    if (!acc) {
      res.json({ found: false });
      return;
    }
    res.json({
      found: true,
      status: acc.status,
      rejection_reason: acc.rejection_reason || '',
      student_id_lrn: acc.student_id_lrn,
      updated_at: acc.updated_at,
    });
  });

  app.post('/api/students/login', (req, res) => {
    const identifier = String(
      req.body?.identifier || req.body?.email || req.body?.student_id_lrn || ''
    ).trim();
    const password = String(req.body?.password || '');

    if (!identifier || !password) {
      res.status(401).json({ error: 'Invalid Student ID / Email or password.' });
      return;
    }

    const upper = identifier.toUpperCase();
    const lower = identifier.toLowerCase();
    const acc = studentAccounts.find(
      (a) => a.student_id_lrn === upper || a.school_email === lower
    );

    if (!acc || !verifyPassword(password, acc.password_hash)) {
      res.status(401).json({ error: 'Invalid Student ID / Email or password.' });
      return;
    }

    if (acc.status === 'pending') {
      res.status(403).json({
        error: 'Your registration is pending Laboratory Admin verification of your School ID.',
        account_status: 'pending',
      });
      return;
    }

    if (acc.status === 'rejected') {
      res.status(403).json({
        error: 'Your registration was rejected by the Laboratory Admin.',
        account_status: 'rejected',
        rejection_reason: acc.rejection_reason || '',
      });
      return;
    }

    if (acc.status === 'suspended') {
      res.status(403).json({
        error: 'Your student account is suspended. Please contact Laboratory Personnel.',
        account_status: 'suspended',
      });
      return;
    }

    const token = `STU-${crypto.randomBytes(24).toString('base64url')}`;
    const now = Date.now();
    studentSessions.set(token, {
      token,
      student_id: acc.id,
      created_at: new Date(now).toISOString(),
      expires_at: new Date(now + STUDENT_SESSION_MS).toISOString(),
    });

    res.json({
      success: true,
      token,
      student: serializeStudent(acc),
    });
  });

  app.get('/api/students/me', (req, res) => {
    const auth = getAuthenticatedStudent(req);
    if (!auth) {
      res.status(401).json({ error: 'Student authentication required.' });
      return;
    }
    const { account: acc } = auth;
    if (acc.status !== 'approved') {
      res.status(403).json({
        error: 'Your student account is not approved for active access.',
        account_status: acc.status,
        rejection_reason: acc.rejection_reason || '',
      });
      return;
    }

    const upperLrn = acc.student_id_lrn.toUpperCase();
    const matching = transactionLogs
      .filter(
        (t) =>
          (t.student_account_id !== null &&
            t.student_account_id !== undefined &&
            t.student_account_id === acc.id) ||
          t.student_id_lrn.toUpperCase() === upperLrn
      )
      .sort((a, b) => Date.parse(b.time_in) - Date.parse(a.time_in) || b.id - a.id)
      .map(enrichTransactionWithInstructions);

    const active_transactions = matching.filter((t) => t.status !== 'Returned / Logged Out');
    const past_transactions = matching.filter((t) => t.status === 'Returned / Logged Out');

    res.json({
      student: serializeStudent(acc),
      active_transactions,
      past_transactions,
    });
  });

  app.post('/api/students/change-password', (req, res) => {
    const auth = getAuthenticatedStudent(req);
    if (!auth) {
      res.status(401).json({ error: 'Student authentication required.' });
      return;
    }
    const { account: acc } = auth;
    if (acc.status !== 'approved') {
      res.status(403).json({
        error: 'Your student account is not approved for active access.',
        account_status: acc.status,
        rejection_reason: acc.rejection_reason || '',
      });
      return;
    }

    const currentPassword = String(req.body?.current_password || '');
    const newPassword = String(req.body?.new_password || '');

    if (!currentPassword || !verifyPassword(currentPassword, acc.password_hash)) {
      res.status(400).json({ error: 'Current password is incorrect.' });
      return;
    }

    if (newPassword.length < 6) {
      res.status(400).json({ error: 'New password must be at least 6 characters long.' });
      return;
    }

    acc.password_hash = hashPassword(newPassword);
    acc.updated_at = new Date().toISOString();
    res.json({ success: true });
  });

  app.post('/api/students/logout', (req, res) => {
    const token = extractBearerToken(req, false);
    if (!token) {
      res.status(401).json({ error: 'Student authentication required.' });
      return;
    }
    const sess = studentSessions.get(token);
    if (!sess || Date.parse(sess.expires_at) <= Date.now()) {
      if (sess) studentSessions.delete(token);
      res.status(401).json({ error: 'Student authentication required.' });
      return;
    }
    studentSessions.delete(token);
    res.json({ success: true });
  });

  // ============================================================================
  // SPEC-01: Admin Authentication & Student Account Approval
  // ============================================================================
  app.post('/api/admin/login', (req, res) => {
    const email = String(req.body?.email || '').trim().toLowerCase();
    const password = String(req.body?.password || '');
    const configuredEmail = getAdminEmail();
    const configuredPassword = getAdminPassword();
    const configuredName = getAdminName();

    const emailOk = constantTimeStringEqual(email, configuredEmail.toLowerCase());
    const passwordOk = constantTimeStringEqual(password, configuredPassword);

    if (!emailOk || !passwordOk) {
      res.status(401).json({ error: 'Invalid administrator email or password.' });
      return;
    }

    const token = `ADM-${crypto.randomBytes(24).toString('base64url')}`;
    const now = Date.now();
    adminSessions.set(token, {
      token,
      email: configuredEmail,
      name: configuredName,
      created_at: new Date(now).toISOString(),
      expires_at: new Date(now + ADMIN_SESSION_MS).toISOString(),
    });

    res.json({
      success: true,
      token,
      admin: {
        email: configuredEmail,
        name: configuredName,
      },
    });
  });

  app.get('/api/admin/me', (req, res) => {
    const admin = requireAdminAuth(req, res);
    if (!admin) return;
    res.json({
      admin: {
        email: admin.email,
        name: admin.name,
      },
    });
  });

  app.post('/api/admin/logout', (req, res) => {
    const admin = requireAdminAuth(req, res);
    if (!admin) return;
    adminSessions.delete(admin.token);
    res.json({ success: true });
  });

  app.get('/api/admin/students', (req, res) => {
    const admin = requireAdminAuth(req, res);
    if (!admin) return;

    const statusFilter = String(req.query.status || 'all').trim().toLowerCase();
    const counts = {
      total: studentAccounts.length,
      pending: 0,
      approved: 0,
      rejected: 0,
      suspended: 0,
    };
    for (const acc of studentAccounts) {
      counts[acc.status] += 1;
    }

    const filtered =
      statusFilter && statusFilter !== 'all' && VALID_STUDENT_STATUSES.has(statusFilter)
        ? studentAccounts.filter((a) => a.status === statusFilter)
        : studentAccounts;

    const statusRank: Record<StudentAccountStatus, number> = {
      pending: 0,
      approved: 1,
      suspended: 2,
      rejected: 3,
    };

    const sorted = [...filtered].sort((a, b) => {
      const rankDiff = statusRank[a.status] - statusRank[b.status];
      if (rankDiff !== 0) return rankDiff;
      return b.id - a.id;
    });

    res.json({
      students: sorted.map(serializeStudent),
      counts,
    });
  });

  app.get('/api/admin/students/:id/id-photo', (req, res) => {
    const admin = requireAdminAuth(req, res, true);
    if (!admin) return;

    const id = Number(req.params.id);
    const acc = studentAccounts.find((a) => a.id === id);
    if (!acc) {
      res.status(404).json({ error: 'Student account not found.' });
      return;
    }
    const photo = acc.id_photo_filename ? studentPhotoStore.get(acc.id_photo_filename) : undefined;
    if (!photo) {
      res.status(404).json({ error: 'School ID photo not found.' });
      return;
    }
    res.setHeader('Content-Type', photo.contentType);
    res.setHeader('Cache-Control', 'private, no-store');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    if (photo.contentType === 'image/svg+xml') {
      res.setHeader('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'");
    }
    res.send(photo.data);
  });

  app.post('/api/admin/students/:id/approve', (req, res) => {
    const admin = requireAdminAuth(req, res);
    if (!admin) return;

    const id = Number(req.params.id);
    const acc = studentAccounts.find((a) => a.id === id);
    if (!acc) {
      res.status(404).json({ error: 'Student account not found.' });
      return;
    }

    const nowIso = new Date().toISOString();
    acc.status = 'approved';
    acc.rejection_reason = '';
    acc.reviewed_by = admin.name || admin.email;
    acc.reviewed_at = nowIso;
    acc.updated_at = nowIso;

    broadcastGlobalUpdate({ event: 'accounts_updated' });
    res.json({ success: true, student: serializeStudent(acc) });
  });

  app.post('/api/admin/students/:id/reject', (req, res) => {
    const admin = requireAdminAuth(req, res);
    if (!admin) return;

    const id = Number(req.params.id);
    const acc = studentAccounts.find((a) => a.id === id);
    if (!acc) {
      res.status(404).json({ error: 'Student account not found.' });
      return;
    }

    const reason =
      String(req.body?.reason || '').trim() ||
      'School ID photo could not be verified. Please re-submit with a clearer photo.';
    const nowIso = new Date().toISOString();
    acc.status = 'rejected';
    acc.rejection_reason = reason;
    acc.reviewed_by = admin.name || admin.email;
    acc.reviewed_at = nowIso;
    acc.updated_at = nowIso;

    for (const [tok, sess] of studentSessions.entries()) {
      if (sess.student_id === acc.id) {
        studentSessions.delete(tok);
      }
    }

    broadcastGlobalUpdate({ event: 'accounts_updated' });
    res.json({ success: true, student: serializeStudent(acc) });
  });

  app.post('/api/admin/students/:id/suspend', (req, res) => {
    const admin = requireAdminAuth(req, res);
    if (!admin) return;

    const id = Number(req.params.id);
    const acc = studentAccounts.find((a) => a.id === id);
    if (!acc) {
      res.status(404).json({ error: 'Student account not found.' });
      return;
    }

    const nowIso = new Date().toISOString();
    acc.status = 'suspended';
    acc.reviewed_by = admin.name || admin.email;
    acc.reviewed_at = nowIso;
    acc.updated_at = nowIso;

    for (const [tok, sess] of studentSessions.entries()) {
      if (sess.student_id === acc.id) {
        studentSessions.delete(tok);
      }
    }

    broadcastGlobalUpdate({ event: 'accounts_updated' });
    res.json({ success: true, student: serializeStudent(acc) });
  });

  app.delete('/api/admin/students/:id', (req, res) => {
    const admin = requireAdminAuth(req, res);
    if (!admin) return;

    const id = Number(req.params.id);
    const idx = studentAccounts.findIndex((a) => a.id === id);
    if (idx === -1) {
      res.status(404).json({ error: 'Student account not found.' });
      return;
    }

    const [removed] = studentAccounts.splice(idx, 1);
    for (const [tok, sess] of studentSessions.entries()) {
      if (sess.student_id === removed.id) {
        studentSessions.delete(tok);
      }
    }
    if (removed.id_photo_filename) {
      studentPhotoStore.delete(removed.id_photo_filename);
    }

    broadcastGlobalUpdate({ event: 'accounts_updated' });
    res.json({ success: true });
  });

  app.post('/api/kiosk/checkout-session', async (req, res) => {
    try {
      if (safetyStatus.level === 'UNSAFE') {
        res.status(403).json({
          error:
            'Laboratory LED Safety Status is currently RED (UNSAFE). Equipment checkout is paused.',
        });
        return;
      }

      const rawItems = Array.isArray(req.body?.basket_items) ? req.body.basket_items : [];
      if (rawItems.length === 0) {
        res
          .status(400)
          .json({ error: 'Please select at least one equipment item in your basket.' });
        return;
      }

      const validatedBasket: BasketItem[] = [];
      for (const item of rawItems) {
        const eq = equipmentList.find((e) => e.id === Number(item.equipment_id) && e.is_active);
        if (!eq) {
          res.status(404).json({ error: `Equipment item #${item.equipment_id} not found.` });
          return;
        }
        const qty = Math.max(1, Number(item.quantity || 1));
        if (qty > eq.available_qty) {
          res.status(400).json({
            error: `Insufficient stock for ${eq.name} (${eq.available_qty} available).`,
          });
          return;
        }
        validatedBasket.push({
          equipment_id: eq.id,
          qr_code: eq.qr_code,
          name: eq.name,
          category: eq.category,
          image_url: eq.image_url || `/images/equipment/${eq.qr_code}.svg`,
          storage_compartment: eq.storage_compartment,
          quantity: qty,
          unit: eq.unit,
          safety_level: eq.safety_level,
          prerequisites: [...(eq.prerequisites || [])],
          usage_instructions: [...(eq.usage_instructions || [])],
        });
      }

      const token = generateSessionToken();
      const createdAt = new Date();
      const expiresAt = new Date(createdAt.getTime() + 15 * 60 * 1000);

      const baseUrl = resolvePublicBaseUrl(req);
      const mobileUrl = `${baseUrl}/student/checkout/${token}`;

      const qrDataUrl = await QRCode.toDataURL(mobileUrl, {
        width: 300,
        margin: 1,
        color: {
          dark: '#003087',
          light: '#FFFFFF',
        },
      });

      const session: CheckoutSession = {
        session_token: token,
        basket_items: validatedBasket,
        qr_data_url: qrDataUrl,
        mobile_url: mobileUrl,
        status: 'pending_student_info',
        created_at: createdAt.toISOString(),
        expires_at: expiresAt.toISOString(),
      };

      checkoutSessions.set(token, session);
      res.status(201).json({ session });
    } catch (err) {
      res.status(500).json({ error: String(err) });
    }
  });

  app.get('/api/kiosk/checkout-session/:token', (req, res) => {
    const token = req.params.token;
    const session = checkoutSessions.get(token);
    if (!session) {
      res.status(404).json({ error: 'Checkout QR session not found or expired.' });
      return;
    }
    res.json({
      session: {
        ...session,
        basket_items: enrichBasketItemsWithInstructions(session.basket_items),
        completed_transaction: session.completed_transaction
          ? enrichTransactionWithInstructions(session.completed_transaction)
          : undefined,
      },
      safety_status: safetyStatus,
      student_presets: STUDENT_PRESETS,
    });
  });

  app.post('/api/kiosk/checkout-session/:token/complete', (req, res) => {
    const auth = getAuthenticatedStudent(req);
    if (!auth) {
      res.status(401).json({ error: 'Student login required to complete checkout.' });
      return;
    }
    const { account: studentAcc } = auth;
    if (studentAcc.status !== 'approved') {
      res.status(403).json({
        error: 'Your student account is not approved for equipment checkout.',
        account_status: studentAcc.status,
        rejection_reason: studentAcc.rejection_reason || '',
      });
      return;
    }

    const token = req.params.token;
    const session = checkoutSessions.get(token);

    if (session && session.status === 'completed' && session.completed_transaction) {
      const completedTx = session.completed_transaction;
      const ownsTx =
        (completedTx.student_account_id !== null &&
          completedTx.student_account_id !== undefined &&
          completedTx.student_account_id === studentAcc.id) ||
        (completedTx.student_account_id == null &&
          completedTx.student_id_lrn.toUpperCase() === studentAcc.student_id_lrn.toUpperCase());
      if (!ownsTx) {
        res.status(403).json({
          error: 'This checkout session was already completed by another student.',
        });
        return;
      }
      res.json({
        success: true,
        transaction: completedTx,
        safety_status: safetyStatus,
      });
      return;
    }

    if (safetyStatus.level === 'UNSAFE') {
      res.status(403).json({
        error:
          'Laboratory LED Safety Status is RED (UNSAFE). Equipment checkout is paused.',
      });
      return;
    }

    const basketItems: BasketItem[] = session
      ? session.basket_items
      : Array.isArray(req.body?.basket_items)
      ? req.body.basket_items
      : [];

    if (basketItems.length === 0) {
      res.status(400).json({ error: 'No equipment items found in checkout session.' });
      return;
    }

    // Anti-spoofing: strictly populate identity from verified student account
    const studentName = studentAcc.full_name;
    const studentIdLrn = studentAcc.student_id_lrn;
    const gradeSection = studentAcc.grade_section;
    const schoolEmail = studentAcc.school_email;

    const subjectActivity = String(req.body?.subject_activity || '').trim();
    const teacherName = String(req.body?.teacher_name || '').trim();
    const rawHours = Number(req.body?.expected_return_hours);
    const expectedReturnHours = Number.isFinite(rawHours) && rawHours > 0 ? rawHours : 2;
    const safetyChecked: string[] = Array.isArray(req.body?.safety_prerequisites_checked)
      ? req.body.safety_prerequisites_checked.map((x: unknown) => String(x)).filter(Boolean)
      : [];

    if (!subjectActivity || !teacherName) {
      res.status(400).json({
        error: 'Please enter the Science Subject / Lab Activity and Supervising Teacher.',
      });
      return;
    }

    // Validate stock (including duplicate equipment_id aggregation) before mutating
    const requestedTotals = new Map<number, number>();
    const resolvedItems: Array<{ eq: Equipment; qty: number }> = [];
    for (const item of basketItems) {
      const eqId = Number(item.equipment_id);
      const eq = equipmentList.find((e) => e.id === eqId && e.is_active);
      const qty = Math.max(1, Number(item.quantity || 1));
      const nextTotalReq = (requestedTotals.get(eqId) || 0) + qty;
      requestedTotals.set(eqId, nextTotalReq);
      if (!eq || eq.available_qty < nextTotalReq) {
        res.status(400).json({
          error: `${item.name || 'Equipment'} no longer has sufficient stock available.`,
        });
        return;
      }
      resolvedItems.push({ eq, qty });
    }

    let hasCautionItem = false;
    let totalItemsCount = 0;
    const snapshotItems: BasketItem[] = [];

    for (const { eq, qty } of resolvedItems) {
      eq.available_qty = Math.max(0, eq.available_qty - qty);
      totalItemsCount += qty;
      if (eq.safety_level === 'CAUTION') {
        hasCautionItem = true;
      }
      snapshotItems.push({
        equipment_id: eq.id,
        qr_code: eq.qr_code,
        name: eq.name,
        category: eq.category,
        image_url: eq.image_url || `/images/equipment/${eq.qr_code}.svg`,
        storage_compartment: eq.storage_compartment,
        quantity: qty,
        unit: eq.unit,
        safety_level: eq.safety_level,
        prerequisites: [...(eq.prerequisites || [])],
        usage_instructions: [...(eq.usage_instructions || [])],
      });
    }

    const nextId = transactionLogs.reduce((max, t) => Math.max(max, t.id), 100) + 1;
    const nowIso = new Date().toISOString();
    const expectedIso = new Date(
      Date.now() + Math.max(0.5, expectedReturnHours) * 3600 * 1000
    ).toISOString();

    const newTransaction: StudentTransactionLog = {
      id: nextId,
      transaction_code: `LG-JRC-${nextId}`,
      student_account_id: studentAcc.id,
      student_name: studentName,
      student_id_lrn: studentIdLrn,
      grade_section: gradeSection,
      school_email: schoolEmail,
      subject_activity: subjectActivity,
      teacher_name: teacherName,
      items: snapshotItems,
      total_items_count: totalItemsCount,
      safety_prerequisites_checked:
        safetyChecked.length > 0
          ? safetyChecked
          : [
              'Wearing buttoned laboratory gown & PPE',
              'Inspected apparatus condition prior to use',
              'Following AU-JRC Science Laboratory safety rules',
            ],
      time_in: nowIso,
      expected_return: expectedIso,
      time_out: null,
      return_condition: null,
      return_notes: '',
      returned_verified_by: null,
      status: 'Borrowed / In Lab',
    };

    transactionLogs.unshift(newTransaction);

    if (hasCautionItem && safetyStatus.level === 'SAFE') {
      safetyStatus = {
        level: 'CAUTION',
        headline: SAFETY_PRESET_MESSAGES.CAUTION.headline,
        message: `Active checkout (${newTransaction.transaction_code} · ${newTransaction.student_name}) includes thermal or glassware apparatus. PPE and teacher supervision required.`,
        updated_by: 'LabGuard+ Automated Safety Monitor',
        updated_at: nowIso,
      };
    }

    if (session) {
      session.status = 'completed';
      session.completed_transaction = newTransaction;
      broadcastToCheckoutSession(token, {
        event: 'checkout_completed',
        transaction: newTransaction,
      });
    }

    broadcastGlobalUpdate({
      event: 'data_updated',
      transaction: newTransaction,
      safety_status: safetyStatus,
      hardware: getHardwareStatus(),
    });

    res.status(201).json({
      success: true,
      transaction: newTransaction,
      safety_status: safetyStatus,
    });
  });

  function normalizeReturnCondition(raw: unknown): 'Good' | 'Damaged' | 'Missing' {
    const cleaned = String(raw || 'Good').trim().toLowerCase();
    if (cleaned === 'damaged') return 'Damaged';
    if (cleaned === 'missing') return 'Missing';
    return 'Good';
  }

  function executeTransactionReturn(
    record: StudentTransactionLog,
    condition: 'Good' | 'Damaged' | 'Missing',
    notes: string,
    verifiedBy: string
  ): StudentTransactionLog {
    const nowIso = new Date().toISOString();
    record.time_out = nowIso;
    record.return_condition = condition;
    record.return_notes = notes || `Returned in ${condition} condition.`;
    record.returned_verified_by = verifiedBy;
    record.status = 'Returned / Logged Out';

    if (condition !== 'Missing') {
      for (const item of record.items) {
        const eq = equipmentList.find((e) => e.id === item.equipment_id);
        if (eq) {
          eq.available_qty = Math.min(eq.total_qty, eq.available_qty + item.quantity);
          if (condition === 'Damaged') {
            eq.condition = 'Damaged';
          }
        }
      }
    }

    if (condition === 'Damaged' || condition === 'Missing') {
      const itemsSummary = record.items.map((i) => `${i.quantity}x ${i.name}`).join(', ');
      const compartmentsSummary = Array.from(
        new Set(record.items.map((i) => i.storage_compartment).filter(Boolean))
      ).join(', ');
      const nextLevel: SafetyStatusLevel = safetyStatus.level === 'UNSAFE' ? 'UNSAFE' : 'CAUTION';

      safetyStatus = {
        level: nextLevel,
        headline: SAFETY_PRESET_MESSAGES[nextLevel].headline,
        message:
          condition === 'Damaged'
            ? `Damaged apparatus returned (${record.transaction_code}: ${itemsSummary}). Inspect ${compartmentsSummary || 'compartment'} before next use.`
            : `Missing apparatus reported on return (${record.transaction_code}: ${itemsSummary}). Lab Coordinator verification required for ${compartmentsSummary || 'compartment'}.`,
        updated_by: `LabGuard+ Return Monitor (${condition})`,
        updated_at: nowIso,
      };
    }

    return enrichTransactionWithInstructions(record);
  }

  app.post('/api/kiosk/return-session', async (req, res) => {
    try {
      const txId = Number(req.body?.transaction_id || 0);
      const txCode = String(req.body?.transaction_code || '').trim().toUpperCase();

      const record = transactionLogs.find(
        (t) =>
          (Number.isFinite(txId) && txId > 0 && t.id === txId) ||
          (txCode && t.transaction_code.toUpperCase() === txCode)
      );

      if (!record) {
        res.status(404).json({ error: 'Borrow transaction record not found.' });
        return;
      }

      if (record.status === 'Returned / Logged Out') {
        res
          .status(400)
          .json({ error: 'This transaction has already been returned and logged out.' });
        return;
      }

      const enriched = enrichTransactionWithInstructions(record);
      const token = generateReturnSessionToken();
      const createdAt = new Date();
      const expiresAt = new Date(createdAt.getTime() + RETURN_SESSION_MS);
      const baseUrl = resolvePublicBaseUrl(req);
      const mobileUrl = `${baseUrl}/student/return/${token}`;
      const qrDataUrl = await QRCode.toDataURL(mobileUrl, {
        width: 300,
        margin: 1,
        color: {
          dark: '#003087',
          light: '#FFFFFF',
        },
      });

      const session: ReturnSession = {
        session_token: token,
        transaction_id: enriched.id,
        qr_data_url: qrDataUrl,
        mobile_url: mobileUrl,
        status: 'pending_verification',
        created_at: createdAt.toISOString(),
        expires_at: expiresAt.toISOString(),
        completed_transaction: null,
      };

      returnSessions.set(token, session);

      res.status(201).json({
        session: {
          session_token: token,
          transaction_id: enriched.id,
          transaction_code: enriched.transaction_code,
          mobile_url: mobileUrl,
          qr_data_url: qrDataUrl,
          status: 'pending_verification',
          created_at: session.created_at,
          expires_at: session.expires_at,
          items: enriched.items,
          masked_student_name: maskStudentName(enriched.student_name),
          masked_student_id: maskStudentId(enriched.student_id_lrn),
        },
      });
    } catch (err) {
      res.status(500).json({ error: String(err) });
    }
  });

  app.get('/api/kiosk/return-session/:token', (req, res) => {
    const cleanToken = String(req.params.token || '').trim();
    const session = returnSessions.get(cleanToken);
    if (!session) {
      res.status(404).json({ error: 'Return verification session not found.' });
      return;
    }

    const isExpired =
      session.status === 'expired' ||
      (session.status === 'pending_verification' && Date.parse(session.expires_at) <= Date.now());
    if (isExpired) {
      session.status = 'expired';
      res.status(410).json({
        error:
          'Return verification QR session has expired. Please generate a new return QR at the Kiosk.',
        expired: true,
        status: 'expired',
      });
      return;
    }

    const record = transactionLogs.find((t) => t.id === session.transaction_id);
    if (!record) {
      res.status(404).json({ error: 'Associated borrow transaction not found.' });
      return;
    }

    const enriched = enrichTransactionWithInstructions(record);
    const completedTx = session.completed_transaction
      ? enrichTransactionWithInstructions(session.completed_transaction)
      : session.status === 'completed'
      ? enriched
      : null;

    const payload: Record<string, unknown> = {
      session: {
        session_token: session.session_token,
        transaction_id: session.transaction_id,
        transaction_code: enriched.transaction_code,
        qr_data_url: session.qr_data_url,
        mobile_url: session.mobile_url,
        status: session.status,
        created_at: session.created_at,
        expires_at: session.expires_at,
        items: enriched.items,
        masked_student_name: maskStudentName(enriched.student_name),
        masked_student_id: maskStudentId(enriched.student_id_lrn),
        completed_transaction: completedTx,
      },
      transaction_preview: buildTransactionPreview(enriched),
      safety_status: safetyStatus,
    };

    const auth = getAuthenticatedStudent(req);
    if (auth && auth.account.status === 'approved') {
      const owner = isTransactionOwner(enriched, auth.account);
      payload.is_owner = owner;
      payload.transaction = owner ? enriched : null;
    }

    res.json(payload);
  });

  app.post('/api/kiosk/return-session/:token/complete', (req, res) => {
    const auth = getAuthenticatedStudent(req);
    if (!auth) {
      res.status(401).json({
        error: 'Student login required to verify and complete equipment return.',
      });
      return;
    }
    const { account: studentAcc } = auth;
    if (studentAcc.status !== 'approved') {
      res.status(403).json({
        error: 'Your student account is not approved for equipment return.',
        account_status: studentAcc.status,
        rejection_reason: studentAcc.rejection_reason || '',
      });
      return;
    }

    const cleanToken = String(req.params.token || '').trim();
    const isDirect = cleanToken.toUpperCase() === 'DIRECT';

    let session: ReturnSession | undefined;
    let record: StudentTransactionLog | undefined;

    if (isDirect) {
      const txId = Number(req.body?.transaction_id || 0);
      const txCode = String(req.body?.transaction_code || '').trim().toUpperCase();
      record = transactionLogs.find(
        (t) =>
          (Number.isFinite(txId) && txId > 0 && t.id === txId) ||
          (txCode && t.transaction_code.toUpperCase() === txCode)
      );
      if (!record) {
        res.status(404).json({ error: 'Borrow transaction record not found.' });
        return;
      }
    } else {
      session = returnSessions.get(cleanToken);
      if (!session) {
        res.status(404).json({ error: 'Return verification session not found.' });
        return;
      }

      if (session.status === 'completed') {
        const completedTx =
          session.completed_transaction ||
          transactionLogs.find((t) => t.id === session!.transaction_id);
        if (!completedTx) {
          res.status(404).json({ error: 'Borrow transaction record not found.' });
          return;
        }
        if (!isTransactionOwner(completedTx, studentAcc)) {
          res.status(403).json({
            error:
              'Verification Failed: This borrow record belongs to a different student account. You can only return equipment borrowed under your own account.',
            ownership_mismatch: true,
          });
          return;
        }
        res.json({
          success: true,
          transaction: enrichTransactionWithInstructions(completedTx),
          safety_status: safetyStatus,
        });
        return;
      }

      if (session.status === 'expired' || Date.parse(session.expires_at) <= Date.now()) {
        session.status = 'expired';
        res.status(410).json({
          error:
            'Return verification QR session has expired. Please generate a new return QR at the Kiosk.',
          expired: true,
        });
        return;
      }

      record = transactionLogs.find((t) => t.id === session!.transaction_id);
      if (!record) {
        res.status(404).json({ error: 'Borrow transaction record not found.' });
        return;
      }
    }

    if (!isTransactionOwner(record, studentAcc)) {
      res.status(403).json({
        error:
          'Verification Failed: This borrow record belongs to a different student account. You can only return equipment borrowed under your own account.',
        ownership_mismatch: true,
      });
      return;
    }

    if (record.status === 'Returned / Logged Out') {
      res
        .status(400)
        .json({ error: 'This transaction has already been returned and logged out.' });
      return;
    }

    const condition = normalizeReturnCondition(req.body?.return_condition);
    const notes = String(req.body?.return_notes || '').trim();
    const verifiedBy = `${studentAcc.full_name} (${studentAcc.student_id_lrn})`;
    const updatedTx = executeTransactionReturn(record, condition, notes, verifiedBy);

    if (session) {
      session.status = 'completed';
      session.completed_transaction = updatedTx;
      broadcastToReturnSession(cleanToken, {
        event: 'return_completed',
        transaction: updatedTx,
        safety_status: safetyStatus,
      });
    }

    broadcastGlobalUpdate({
      event: 'data_updated',
      transaction: updatedTx,
      safety_status: safetyStatus,
      hardware: getHardwareStatus(),
    });

    res.json({
      success: true,
      transaction: updatedTx,
      safety_status: safetyStatus,
    });
  });

  app.post('/api/kiosk/return', (req, res) => {
    const admin = requireAdminAuth(req, res);
    if (!admin) return;

    const txId = Number(req.body?.transaction_id || 0);
    const txCode = String(req.body?.transaction_code || '').trim().toUpperCase();
    const condition = normalizeReturnCondition(req.body?.return_condition);
    const notes = String(req.body?.return_notes || '').trim();
    const verifiedBy = `Admin: ${admin.name || admin.email || 'Administrator'}`;

    const record = transactionLogs.find(
      (t) =>
        (Number.isFinite(txId) && txId > 0 && t.id === txId) ||
        (txCode && t.transaction_code.toUpperCase() === txCode)
    );

    if (!record) {
      res.status(404).json({ error: 'Borrow transaction record not found.' });
      return;
    }

    if (record.status === 'Returned / Logged Out') {
      res
        .status(400)
        .json({ error: 'This transaction has already been returned and logged out.' });
      return;
    }

    const updatedTx = executeTransactionReturn(record, condition, notes, verifiedBy);

    broadcastGlobalUpdate({
      event: 'data_updated',
      transaction: updatedTx,
      safety_status: safetyStatus,
      hardware: getHardwareStatus(),
    });

    res.json({
      success: true,
      transaction: updatedTx,
      safety_status: safetyStatus,
    });
  });

  app.post('/api/admin/equipment', (req, res) => {
    const admin = requireAdminAuth(req, res);
    if (!admin) return;

    const name = String(req.body?.name || '').trim();
    const category = req.body?.category || 'Glassware & Measuring';
    const description = String(req.body?.description || '').trim();
    const compartment = String(req.body?.storage_compartment || '4th - 3rd Section').trim();
    const totalQty = Math.max(1, Number(req.body?.total_qty || 1));
    const unit = String(req.body?.unit || 'unit').trim();
    const safetyLevel = req.body?.safety_level === 'CAUTION' ? 'CAUTION' : 'SAFE';
    const rawPrereqs: string[] = Array.isArray(req.body?.prerequisites)
      ? req.body.prerequisites.map((p: unknown) => String(p).trim()).filter(Boolean)
      : [];
    const prerequisites =
      rawPrereqs.length > 0
        ? rawPrereqs
        : ['Wear buttoned laboratory gown and follow AU-JRC safety rules'];

    const rawUsage: string[] = Array.isArray(req.body?.usage_instructions)
      ? req.body.usage_instructions.map((u: unknown) => String(u).trim()).filter(Boolean)
      : [];
    const usageInstructions =
      rawUsage.length > 0
        ? rawUsage
        : [
            `Inspect ${name} carefully before starting your laboratory activity.`,
            'Operate properly under the guidance of your supervising science teacher.',
            `Clean and return to ${compartment} after use.`,
          ];

    if (!name) {
      res.status(400).json({ error: 'Equipment name is required.' });
      return;
    }

    const nextId = equipmentList.reduce((max, e) => Math.max(max, e.id), 0) + 1;
    const qrCode =
      String(req.body?.qr_code || '').trim().toUpperCase() ||
      `LG-EQ-${String(nextId).padStart(3, '0')}`;

    const newItem: Equipment = {
      id: nextId,
      qr_code: qrCode,
      name,
      category,
      image_url: String(req.body?.image_url || '').trim() || '/images/equipment/LG-EQ-001.svg',
      description: description || `${name} for AU-JRC Senior High School Science Laboratory.`,
      storage_compartment: compartment,
      total_qty: totalQty,
      available_qty: totalQty,
      unit,
      condition: 'Good',
      safety_level: safetyLevel,
      prerequisites,
      usage_instructions: usageInstructions,
      is_active: true,
      created_at: new Date().toISOString(),
    };

    equipmentList.push(newItem);
    broadcastGlobalUpdate({
      event: 'data_updated',
      safety_status: safetyStatus,
      hardware: getHardwareStatus(),
    });
    res.status(201).json({ equipment: newItem });
  });

  app.patch('/api/admin/equipment/:id', (req, res) => {
    const admin = requireAdminAuth(req, res);
    if (!admin) return;

    const id = Number(req.params.id);
    const eq = equipmentList.find((e) => e.id === id);
    if (!eq) {
      res.status(404).json({ error: 'Equipment not found.' });
      return;
    }

    if (req.body?.name !== undefined && req.body.name !== null) {
      const trimmed = String(req.body.name).trim();
      if (trimmed) eq.name = trimmed;
    }
    if (req.body?.category !== undefined && req.body.category !== null) {
      const trimmed = String(req.body.category).trim();
      if (trimmed) eq.category = trimmed as Equipment['category'];
    }
    if (req.body?.description !== undefined && req.body.description !== null) {
      eq.description = String(req.body.description).trim();
    }
    if (req.body?.storage_compartment !== undefined && req.body.storage_compartment !== null) {
      const trimmed = String(req.body.storage_compartment).trim();
      if (trimmed) eq.storage_compartment = trimmed;
    }
    if (
      req.body?.condition === 'Good' ||
      req.body?.condition === 'Fair' ||
      req.body?.condition === 'Damaged'
    ) {
      eq.condition = req.body.condition;
    }
    if (req.body?.safety_level === 'SAFE' || req.body?.safety_level === 'CAUTION') {
      eq.safety_level = req.body.safety_level;
    }
    if (req.body?.image_url !== undefined && req.body.image_url !== null) {
      const trimmed = String(req.body.image_url).trim();
      if (trimmed) eq.image_url = trimmed;
    }
    if (req.body?.total_qty !== undefined && req.body.total_qty !== null) {
      const nextTotal = Math.max(0, Number(req.body.total_qty));
      const borrowedCount = Math.max(0, eq.total_qty - eq.available_qty);
      eq.total_qty = nextTotal;
      eq.available_qty = Math.max(0, nextTotal - borrowedCount);
    }
    if (req.body?.available_qty !== undefined && req.body.available_qty !== null) {
      eq.available_qty = Math.max(0, Math.min(eq.total_qty, Number(req.body.available_qty)));
    }
    if (Array.isArray(req.body?.prerequisites)) {
      eq.prerequisites = req.body.prerequisites
        .map((p: unknown) => String(p).trim())
        .filter(Boolean);
    }
    if (Array.isArray(req.body?.usage_instructions)) {
      eq.usage_instructions = req.body.usage_instructions
        .map((u: unknown) => String(u).trim())
        .filter(Boolean);
    }

    broadcastGlobalUpdate({
      event: 'data_updated',
      safety_status: safetyStatus,
      hardware: getHardwareStatus(),
    });
    res.json({ equipment: eq });
  });

  app.delete('/api/admin/equipment/:id', (req, res) => {
    const admin = requireAdminAuth(req, res);
    if (!admin) return;

    const id = Number(req.params.id);
    equipmentList = equipmentList.filter((e) => e.id !== id);
    broadcastGlobalUpdate({
      event: 'data_updated',
      safety_status: safetyStatus,
      hardware: getHardwareStatus(),
    });
    res.json({ success: true });
  });

  app.post('/api/admin/safety-status', (req, res) => {
    const admin = requireAdminAuth(req, res);
    if (!admin) return;

    const level: SafetyStatusLevel =
      req.body?.level === 'CAUTION' || req.body?.level === 'UNSAFE' ? req.body.level : 'SAFE';
    const preset = SAFETY_PRESET_MESSAGES[level];
    const customMessage = String(req.body?.message || '').trim();
    const updatedBy =
      String(req.body?.updated_by || '').trim() ||
      admin.name ||
      'AU-JRC Science Laboratory Personnel';

    safetyStatus = {
      level,
      headline: preset.headline,
      message: customMessage || preset.message,
      updated_by: updatedBy,
      updated_at: new Date().toISOString(),
    };

    broadcastGlobalUpdate({
      event: 'data_updated',
      safety_status: safetyStatus,
      hardware: getHardwareStatus(),
    });

    res.json({ safety_status: safetyStatus });
  });

  app.post('/api/reset', (req, res) => {
    const admin = requireAdminAuth(req, res);
    if (!admin) return;

    equipmentList = enrichEquipmentWithImages(structuredClone(INITIAL_EQUIPMENT));
    transactionLogs = structuredClone(INITIAL_TRANSACTIONS);
    safetyStatus = structuredClone(INITIAL_SAFETY_STATUS);
    checkoutSessions.clear();
    returnSessions.clear();
    studentSessions.clear();
    seedStudentAccounts();
    linkSeededTransactionsToAccounts();
    // Preserve adminSessions so the active administrator stays signed in

    broadcastGlobalUpdate({
      event: 'data_updated',
      safety_status: safetyStatus,
      hardware: getHardwareStatus(),
    });
    broadcastGlobalUpdate({ event: 'accounts_updated' });
    res.json({ success: true });
  });

  // Mount Vite or Static Build for any remaining assets
  if (process.env.NODE_ENV !== 'production') {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.resolve(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (_req, res) => {
      res.sendFile(path.join(templatesDir, 'kiosk.html'));
    });
  }

  httpServer.listen(PORT, '0.0.0.0', () => {
    const baseUrl = resolvePublicBaseUrl();
    console.log(`LabGuard+ Kiosk Server running on http://0.0.0.0:${PORT}`);
    console.log(`  -> LAN Base URL:        ${baseUrl}`);
    console.log(`  -> Student Kiosk UI:    ${baseUrl}/kiosk`);
    console.log(`  -> Student Register UI: ${baseUrl}/student/register`);
    console.log(`  -> Student Account UI:  ${baseUrl}/student/account`);
    console.log(`  -> Admin Dashboard UI:  ${baseUrl}/admin`);
  });
}

startServer();
