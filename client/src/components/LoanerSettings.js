import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import { API_BASE_URL } from '../config';
import './LoanerSettings.css';
// While the loaner service runs standalone (before the bopchipboard merge),
// point these pages at it with REACT_APP_LOANER_API_BASE_URL; once merged,
// leave that unset and the chipboard API base is used.
const LOANER_API = process.env.REACT_APP_LOANER_API_BASE_URL || API_BASE_URL;

// Admin-only editor for the loaner pricing settings: model programs (money
// factor, residual, incentive, term), the mileage discount chart, and every
// formula setting the old Simple Calculator spreadsheet hardcoded.
// Routed behind <PrivateRoute roles={['Admin']}> — the backend enforces the
// same rule on every write.

const CONFIG_FIELDS = [
  ['dealership', 'Dealership name', 'text'],
  ['program_mileage_limit', 'Program mileage limit', 1],
  ['avp_min_miles', 'AVP applies above (miles)', 1],
  ['invoice_markup', 'Sale price markup ($ over invoice)', 1],
  ['invoice_pct_under_break', 'Invoice % of MSRP (low miles)', 0.0001],
  ['invoice_pct_over_break', 'Invoice % of MSRP (high miles)', 0.0001],
  ['invoice_mileage_break', 'Invoice low/high mileage break', 1],
  ['avp_base_deduction', 'AVP: MSRP deduction ($)', 1],
  ['avp_pct', 'AVP: percent of (MSRP − deduction)', 0.0001],
  ['avp_flat_credit', 'AVP: flat credit ($)', 1],
  ['residual_mile_charge', 'Residual charge per mile ($)', 0.01],
  ['residual_free_miles', 'Residual free miles', 1],
  ['acquisition_fee', 'Acquisition fee ($)', 1],
  ['disposition_fee', 'Disposition fee ($)', 1],
  ['excess_mileage_rate', 'Excess mileage rate ($/mi)', 0.01],
  ['annual_mileage_allowance', 'Annual mileage allowance', 1],
];

function LoanerSettings() {
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [message, setMessage] = useState(null);
  const [saving, setSaving] = useState(false);
  const [workbookFile, setWorkbookFile] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await axios.get(`${LOANER_API}/loaner-pricing/settings`);
        if (!cancelled) setSettings(response.data.settings);
      } catch (err) {
        if (!cancelled) setError(err.response?.data?.message || 'Failed to load settings');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const setField = (name, value) =>
    setSettings((s) => ({ ...s, [name]: value }));

  const setProgram = (index, name, value) =>
    setSettings((s) => {
      const programs = s.programs.map((p, i) => (i === index ? { ...p, [name]: value } : p));
      return { ...s, programs };
    });

  const addProgram = () =>
    setSettings((s) => ({
      ...s,
      programs: [...s.programs, {
        model: '', money_factor: null, residual_pct: null,
        lease_incentive: 0, lease_39_month: false,
      }],
    }));

  const removeProgram = (index) =>
    setSettings((s) => ({ ...s, programs: s.programs.filter((_, i) => i !== index) }));

  const setChartCell = (index, cell, value) =>
    setSettings((s) => {
      const chart = s.discount_chart.map((row, i) =>
        (i === index ? [cell === 0 ? value : row[0], cell === 1 ? value : row[1]] : row));
      return { ...s, discount_chart: chart };
    });

  const addChartRow = () =>
    setSettings((s) => ({ ...s, discount_chart: [...s.discount_chart, ['', '']] }));

  const removeChartRow = (index) =>
    setSettings((s) => ({ ...s, discount_chart: s.discount_chart.filter((_, i) => i !== index) }));

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const payload = {
        ...settings,
        program_date: settings.program_date || null,
        discount_chart: settings.discount_chart
          .filter(([m]) => m !== '' && m !== null)
          .map(([m, d]) => [Number(m), Number(d) || 0]),
        programs: settings.programs
          .filter((p) => p.model && p.model.trim())
          .map((p) => ({
            ...p,
            model: p.model.trim(),
            money_factor: Number(p.money_factor),
            residual_pct: Number(p.residual_pct),
            lease_incentive: Number(p.lease_incentive) || 0,
            lease_39_month: Boolean(p.lease_39_month),
          })),
      };
      for (const [name, , step] of CONFIG_FIELDS) {
        if (step !== 'text') payload[name] = Number(payload[name]);
      }
      const response = await axios.put(`${LOANER_API}/loaner-pricing/settings`, payload);
      setSettings(response.data.settings);
      setMessage('Settings saved. New uploads will price with these rates.');
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const handleImport = async (event) => {
    event.preventDefault();
    if (!workbookFile) return;
    setError(null);
    setMessage(null);
    try {
      const formData = new FormData();
      formData.append('workbook', workbookFile);
      const response = await axios.post(
        `${LOANER_API}/loaner-pricing/settings/import`, formData);
      setSettings(response.data.settings);
      setMessage(response.data.message);
    } catch (err) {
      setError(err.response?.data?.message || 'Import failed');
    }
  };

  const handleExport = async () => {
    const response = await axios.get(
      `${LOANER_API}/loaner-pricing/settings/export`, { responseType: 'blob' });
    const url = URL.createObjectURL(response.data);
    const link = document.createElement('a');
    link.href = url;
    link.download = `loaner_settings_${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  if (loading) return <div className="loaner-settings-loading">Loading settings...</div>;
  if (!settings) return <div className="loaner-settings-error">{error}</div>;

  return (
    <div className="loaner-settings-page">
      <div className="loaner-settings-header">
        <div>
          <h2>Loaner pricing settings</h2>
          <p>The live rate sheet — changes apply to every sheet generated after saving.</p>
        </div>
        <Link className="loaner-btn loaner-btn-secondary" to="/loaners">← Loaner sheet</Link>
      </div>

      {message && <div className="loaner-settings-ok">{message}</div>}
      {error && <div className="loaner-settings-error">{error}</div>}

      <h3>Program settings</h3>
      <div className="loaner-settings-grid">
        {CONFIG_FIELDS.map(([name, label, step]) => (
          <div key={name}>
            <label>{label}</label>
            <input
              type={step === 'text' ? 'text' : 'number'}
              step={step === 'text' ? undefined : step}
              value={settings[name] ?? ''}
              onChange={(e) => setField(name,
                step === 'text' ? e.target.value : e.target.value)}
            />
          </div>
        ))}
        <div>
          <label>Programs valid through</label>
          <input
            type="date"
            value={settings.program_date || ''}
            onChange={(e) => setField('program_date', e.target.value)}
          />
        </div>
      </div>

      <h3>Mileage discount chart</h3>
      <p className="loaner-settings-hint">
        Discount applied once a unit reaches the breakpoint (largest breakpoint ≤ miles wins).
      </p>
      <table className="loaner-settings-table loaner-settings-chart">
        <thead>
          <tr><th>Miles ≥</th><th>Discount $</th><th /></tr>
        </thead>
        <tbody>
          {settings.discount_chart.map(([miles, discount], i) => (
            <tr key={i}>
              <td>
                <input type="number" value={miles}
                  onChange={(e) => setChartCell(i, 0, e.target.value)} />
              </td>
              <td>
                <input type="number" value={discount}
                  onChange={(e) => setChartCell(i, 1, e.target.value)} />
              </td>
              <td>
                <button className="loaner-row-remove" type="button"
                  onClick={() => removeChartRow(i)}>✕</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="loaner-row-add" type="button" onClick={addChartRow}>
        + Add breakpoint
      </button>

      <h3>Rates, residuals &amp; incentives ({settings.programs.length} models)</h3>
      <p className="loaner-settings-hint">
        Money factor and residual use the spreadsheet's format (e.g. 0.00095 and 0.57).
        The model name must match the vAuto export exactly.
      </p>
      <table className="loaner-settings-table">
        <thead>
          <tr>
            <th>Model</th><th>Money Factor</th><th>Residual</th>
            <th>Incentive $</th><th>39-mo</th><th />
          </tr>
        </thead>
        <tbody>
          {settings.programs.map((p, i) => (
            <tr key={i}>
              <td>
                <input type="text" value={p.model}
                  onChange={(e) => setProgram(i, 'model', e.target.value)} />
              </td>
              <td>
                <input type="number" step="0.00001" value={p.money_factor ?? ''}
                  onChange={(e) => setProgram(i, 'money_factor', e.target.value)} />
              </td>
              <td>
                <input type="number" step="0.01" value={p.residual_pct ?? ''}
                  onChange={(e) => setProgram(i, 'residual_pct', e.target.value)} />
              </td>
              <td>
                <input type="number" step="1" value={p.lease_incentive ?? 0}
                  onChange={(e) => setProgram(i, 'lease_incentive', e.target.value)} />
              </td>
              <td className="loaner-settings-center">
                <input type="checkbox" checked={Boolean(p.lease_39_month)}
                  onChange={(e) => setProgram(i, 'lease_39_month', e.target.checked)} />
              </td>
              <td>
                <button className="loaner-row-remove" type="button"
                  onClick={() => removeProgram(i)}>✕</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="loaner-row-add" type="button" onClick={addProgram}>
        + Add model
      </button>

      <div className="loaner-settings-save">
        <button className="loaner-btn" type="button" disabled={saving} onClick={handleSave}>
          {saving ? 'Saving…' : 'Save all settings'}
        </button>
      </div>

      <h3>Import / backup</h3>
      <div className="loaner-settings-io">
        <form onSubmit={handleImport}>
          <label>Import a Simple Calculator workbook (.xlsx)</label>
          <input type="file" accept=".xlsx"
            onChange={(e) => setWorkbookFile(e.target.files[0] || null)} />
          <button className="loaner-btn" type="submit" disabled={!workbookFile}>
            Import workbook
          </button>
        </form>
        <div>
          <label>Download a backup</label>
          <button className="loaner-btn loaner-btn-secondary" type="button" onClick={handleExport}>
            Export settings.json
          </button>
        </div>
      </div>
    </div>
  );
}

export default LoanerSettings;
