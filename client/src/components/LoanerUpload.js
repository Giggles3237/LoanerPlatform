import React, { useState } from 'react';
import axios from 'axios';
import { Link, useNavigate } from 'react-router-dom';
import { API_BASE_URL } from '../config';
import './LoanerUpload.css';
// While the loaner service runs standalone (before the bopchipboard merge),
// point these pages at it with REACT_APP_LOANER_API_BASE_URL; once merged,
// leave that unset and the chipboard API base is used.
const LOANER_API = process.env.REACT_APP_LOANER_API_BASE_URL || API_BASE_URL;

// Upload the two daily exports and regenerate the loaner payment sheet.
function LoanerUpload() {
  const navigate = useNavigate();
  const [inventoryFile, setInventoryFile] = useState(null);
  const [vautoFile, setVautoFile] = useState(null);
  const [disclosures, setDisclosures] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!inventoryFile || !vautoFile) {
      setError('Both files are required.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append('inventory', inventoryFile);
      formData.append('vauto', vautoFile);
      formData.append('disclosures', disclosures ? 'true' : 'false');
      await axios.post(`${LOANER_API}/loaner-pricing/generate`, formData);
      navigate('/loaners');
    } catch (err) {
      setError(err.response?.data?.message || 'Failed to generate the sheet');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="loaner-upload-page">
      <div className="loaner-upload-header">
        <h2>Upload fresh loaner data</h2>
        <Link className="loaner-upload-back" to="/loaners">← Current sheet</Link>
      </div>
      <p className="loaner-upload-sub">
        The two daily exports — rates come from the app's settings.
      </p>
      {error && <div className="loaner-upload-error">{error}</div>}
      <form onSubmit={handleSubmit}>
        <label className="loaner-upload-label">
          Full Inventory Report <small>(.xlsx from the fleet software — current miles)</small>
        </label>
        <input
          type="file"
          accept=".xlsx"
          onChange={(e) => setInventoryFile(e.target.files[0] || null)}
        />
        <label className="loaner-upload-label">
          Payment Calculator export <small>(.xls/.xlsx from vAuto — the loaner list)</small>
        </label>
        <input
          type="file"
          accept=".xls,.xlsx"
          onChange={(e) => setVautoFile(e.target.files[0] || null)}
        />
        <div className="loaner-upload-actions">
          <button className="loaner-btn" type="submit" disabled={submitting}>
            {submitting ? 'Generating…' : 'Generate payment sheet'}
          </button>
          <label className="loaner-upload-check">
            <input
              type="checkbox"
              checked={disclosures}
              onChange={(e) => setDisclosures(e.target.checked)}
            />{' '}
            include per-unit disclosures
          </label>
        </div>
      </form>
    </div>
  );
}

export default LoanerUpload;
