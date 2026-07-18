// Loaner pricing API — designed to mount into bopchipboard's server.js as
//   app.use('/api/loaner-pricing', require('./routes/loanerPricing'));
//
// Endpoints (all JWT-authenticated; settings writes are Admin only):
//   GET  /sheet            latest sheet: { html, meta } (404 until first generate)
//   POST /generate         multipart: inventory + vauto files -> regenerates
//   GET  /settings         current ratebook settings
//   PUT  /settings         replace ratebook settings            [Admin]
//   POST /settings/import  multipart: Simple Calculator .xlsx   [Admin]
//   GET  /settings/export  settings JSON as a download          [Admin]

const express = require('express');
const multer = require('multer');
const router = express.Router();

const { authenticate, requireAdmin } = require('../middleware/auth');
const { parseInventory, parseVauto } = require('../lib/parsers');
const { processFleet } = require('../lib/fleet');
const { renderSheet } = require('../lib/report');
const store = require('../lib/settings');
const { parseCalculatorWorkbook } = require('../lib/calculatorImport');

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 20 * 1024 * 1024 },
});

router.get('/sheet', authenticate, async (req, res) => {
  try {
    const sheet = await store.loadSheet();
    if (!sheet) {
      return res.status(404).json({ message: 'No sheet generated yet' });
    }
    const updatedAt = await store.settingsUpdatedAt();
    const staleRates = Boolean(
      updatedAt && sheet.meta.generatedAt
      && new Date(updatedAt) > new Date(sheet.meta.generatedAt));
    res.json({ html: sheet.html, meta: sheet.meta, staleRates });
  } catch (error) {
    console.error('Error loading sheet:', error);
    res.status(500).json({ message: 'Failed to load sheet' });
  }
});

router.post(
  '/generate',
  authenticate,
  upload.fields([{ name: 'inventory', maxCount: 1 }, { name: 'vauto', maxCount: 1 }]),
  async (req, res) => {
    try {
      const inventoryFile = req.files?.inventory?.[0];
      const vautoFile = req.files?.vauto?.[0];
      if (!inventoryFile || !vautoFile) {
        return res.status(400).json({ message: 'Both inventory and vauto files are required' });
      }
      const inventory = parseInventory(inventoryFile.buffer);
      const vauto = parseVauto(vautoFile.buffer);
      const settings = await store.loadSettings();
      const report = processFleet(inventory, vauto, settings);
      const html = renderSheet(report, settings, {
        includeDisclosures: req.body.disclosures === 'true' || req.body.disclosures === 'on',
      });
      const meta = {
        generatedAt: new Date().toISOString(),
        generatedBy: req.auth.name || null,
        priced: report.priced.length,
        attention: report.needsAttention.length,
        mileageUpdates: report.mileageUpdates.length,
        duplicatesRemoved: report.duplicatesRemoved,
        missingFromVauto: report.missingFromVauto.length,
      };
      await store.saveSheet(html, meta);
      res.json({ html, meta, staleRates: false });
    } catch (error) {
      console.error('Error generating sheet:', error);
      res.status(400).json({ message: error.message || 'Failed to generate sheet' });
    }
  }
);

router.get('/settings', authenticate, async (req, res) => {
  try {
    const settings = await store.loadSettings();
    const updatedAt = await store.settingsUpdatedAt();
    res.json({ settings, updatedAt });
  } catch (error) {
    console.error('Error loading settings:', error);
    res.status(500).json({ message: 'Failed to load settings' });
  }
});

function validateSettings(settings) {
  if (!settings || typeof settings !== 'object') return 'Settings body is required';
  if (!Array.isArray(settings.programs) || settings.programs.length === 0) {
    return 'At least one model program is required';
  }
  for (const p of settings.programs) {
    if (!p.model || typeof p.model !== 'string') return 'Every program needs a model name';
    if (!Number.isFinite(p.money_factor)) return `'${p.model}': money factor is required`;
    if (!Number.isFinite(p.residual_pct)) return `'${p.model}': residual is required`;
  }
  if (!Array.isArray(settings.discount_chart) || settings.discount_chart.length === 0) {
    return 'The discount chart needs at least one row (0 miles / $0 works)';
  }
  const numeric = [
    'avp_min_miles', 'program_mileage_limit', 'invoice_markup', 'acquisition_fee',
    'disposition_fee', 'excess_mileage_rate', 'annual_mileage_allowance',
    'invoice_pct_under_break', 'invoice_pct_over_break', 'invoice_mileage_break',
    'avp_base_deduction', 'avp_pct', 'avp_flat_credit',
    'residual_mile_charge', 'residual_free_miles',
  ];
  for (const key of numeric) {
    if (!Number.isFinite(settings[key])) return `Setting '${key}' must be a number`;
  }
  return null;
}

router.put('/settings', authenticate, requireAdmin, async (req, res) => {
  try {
    const settings = req.body;
    const problem = validateSettings(settings);
    if (problem) {
      return res.status(400).json({ message: problem });
    }
    settings.discount_chart = settings.discount_chart
      .map(([m, d]) => [Math.round(Number(m)), Number(d)])
      .sort((a, b) => a[0] - b[0]);
    await store.saveSettings(settings);
    res.json({ message: 'Settings saved', settings });
  } catch (error) {
    console.error('Error saving settings:', error);
    res.status(500).json({ message: 'Failed to save settings' });
  }
});

router.post(
  '/settings/import',
  authenticate,
  requireAdmin,
  upload.single('workbook'),
  async (req, res) => {
    try {
      if (!req.file) {
        return res.status(400).json({ message: 'No workbook uploaded' });
      }
      const current = await store.loadSettings();
      const settings = parseCalculatorWorkbook(req.file.buffer, current);
      await store.saveSettings(settings);
      res.json({
        message: `Imported ${settings.programs.length} model programs from the workbook`,
        settings,
      });
    } catch (error) {
      console.error('Error importing workbook:', error);
      res.status(400).json({ message: error.message || 'Import failed' });
    }
  }
);

router.get('/settings/export', authenticate, requireAdmin, async (req, res) => {
  try {
    const settings = await store.loadSettings();
    const stamp = new Date().toISOString().slice(0, 10);
    res.setHeader('Content-Disposition', `attachment; filename=loaner_settings_${stamp}.json`);
    res.json(settings);
  } catch (error) {
    console.error('Error exporting settings:', error);
    res.status(500).json({ message: 'Failed to export settings' });
  }
});

module.exports = router;
