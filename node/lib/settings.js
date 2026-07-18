// Pricing settings + latest-sheet persistence.
//
// With MySQL configured (MYSQL_HOST set), settings live in `loaner_settings`
// (single JSON row) and generated sheets in `loaner_sheets` (newest = the
// current sheet; older rows are history, pruned past KEEP_SHEETS).
// Without MySQL (local dev), plain files under data/ are used.
// Either way the app boots seeded from seed/default_settings.json.

const fs = require('fs');
const path = require('path');
const { pool } = require('../db');

const SEED_PATH = path.join(__dirname, '..', 'seed', 'default_settings.json');
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, '..', 'data');
const KEEP_SHEETS = 90;

const CREATE_SETTINGS = `
  CREATE TABLE IF NOT EXISTS loaner_settings (
    id INT PRIMARY KEY,
    data MEDIUMTEXT NOT NULL,
    updated_at DATETIME NOT NULL
  )`;
const CREATE_SHEETS = `
  CREATE TABLE IF NOT EXISTS loaner_sheets (
    id INT PRIMARY KEY AUTO_INCREMENT,
    html MEDIUMTEXT NOT NULL,
    meta TEXT NOT NULL,
    created_at DATETIME NOT NULL
  )`;

let tablesReady = null;
function ensureTables() {
  if (!pool) return Promise.resolve();
  if (!tablesReady) {
    tablesReady = (async () => {
      await pool.query(CREATE_SETTINGS);
      await pool.query(CREATE_SHEETS);
    })();
  }
  return tablesReady;
}

function seedSettings() {
  return JSON.parse(fs.readFileSync(SEED_PATH, 'utf8'));
}

const now = () => new Date();

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

async function loadSettings() {
  if (pool) {
    await ensureTables();
    const [rows] = await pool.query('SELECT data FROM loaner_settings WHERE id = 1');
    if (rows.length) return JSON.parse(rows[0].data);
    return seedSettings();
  }
  const file = path.join(DATA_DIR, 'settings.json');
  if (fs.existsSync(file)) return JSON.parse(fs.readFileSync(file, 'utf8'));
  return seedSettings();
}

async function saveSettings(settings) {
  const payload = JSON.stringify(settings);
  if (pool) {
    await ensureTables();
    await pool.query(
      `INSERT INTO loaner_settings (id, data, updated_at) VALUES (1, ?, ?)
       ON DUPLICATE KEY UPDATE data = VALUES(data), updated_at = VALUES(updated_at)`,
      [payload, now()]);
    return;
  }
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(path.join(DATA_DIR, 'settings.json'), payload);
}

async function settingsUpdatedAt() {
  if (pool) {
    await ensureTables();
    const [rows] = await pool.query('SELECT updated_at FROM loaner_settings WHERE id = 1');
    return rows.length ? new Date(rows[0].updated_at) : null;
  }
  const file = path.join(DATA_DIR, 'settings.json');
  return fs.existsSync(file) ? fs.statSync(file).mtime : null;
}

// ---------------------------------------------------------------------------
// Latest sheet
// ---------------------------------------------------------------------------

async function saveSheet(html, meta) {
  if (pool) {
    await ensureTables();
    await pool.query(
      'INSERT INTO loaner_sheets (html, meta, created_at) VALUES (?, ?, ?)',
      [html, JSON.stringify(meta), now()]);
    const [old] = await pool.query(
      'SELECT id FROM loaner_sheets ORDER BY id DESC LIMIT 1 OFFSET ?', [KEEP_SHEETS]);
    if (old.length) {
      await pool.query('DELETE FROM loaner_sheets WHERE id <= ?', [old[0].id]);
    }
    return;
  }
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(path.join(DATA_DIR, 'latest_sheet.html'), html);
  fs.writeFileSync(path.join(DATA_DIR, 'latest_sheet.meta.json'), JSON.stringify(meta));
}

async function loadSheet() {
  if (pool) {
    await ensureTables();
    const [rows] = await pool.query(
      'SELECT html, meta FROM loaner_sheets ORDER BY id DESC LIMIT 1');
    if (!rows.length) return null;
    return { html: rows[0].html, meta: JSON.parse(rows[0].meta) };
  }
  const htmlFile = path.join(DATA_DIR, 'latest_sheet.html');
  const metaFile = path.join(DATA_DIR, 'latest_sheet.meta.json');
  if (!fs.existsSync(htmlFile) || !fs.existsSync(metaFile)) return null;
  return {
    html: fs.readFileSync(htmlFile, 'utf8'),
    meta: JSON.parse(fs.readFileSync(metaFile, 'utf8')),
  };
}

module.exports = { loadSettings, saveSettings, settingsUpdatedAt, saveSheet, loadSheet, seedSettings };
