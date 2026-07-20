import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { format } from 'date-fns';
import { API_BASE_URL } from '../config';
import './LoanerSheet.css';
// While the loaner service runs standalone (before the bopchipboard merge),
// point these pages at it with REACT_APP_LOANER_API_BASE_URL; once merged,
// leave that unset and the chipboard API base is used.
const LOANER_API = process.env.REACT_APP_LOANER_API_BASE_URL || API_BASE_URL;

// The latest loaner payment sheet. The sheet HTML comes fully rendered from
// the backend (same document that can be pasted into an email); it is shown
// in a sandboxed iframe so its own sorting/brand-filter script can run
// without touching the app's DOM or styles.
function LoanerSheet() {
  const { auth } = useAuth();
  const [sheet, setSheet] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [noSheet, setNoSheet] = useState(false);
  const iframeRef = useRef(null);

  const isAdmin = auth?.user?.role === 'Admin';

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await axios.get(`${LOANER_API}/loaner-pricing/sheet`);
        if (!cancelled) setSheet(response.data);
      } catch (err) {
        if (cancelled) return;
        if (err.response?.status === 404) {
          setNoSheet(true);
        } else {
          setError(err.response?.data?.message || 'Failed to load the loaner sheet');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const resizeIframe = useCallback(() => {
    const frame = iframeRef.current;
    if (frame?.contentDocument?.body) {
      frame.style.height = `${frame.contentDocument.body.scrollHeight + 40}px`;
    }
  }, []);

  if (loading) {
    return <div className="loaner-sheet-loading">Loading loaner sheet...</div>;
  }

  if (noSheet) {
    return (
      <div className="loaner-sheet-empty">
        <h2>No loaner sheet yet</h2>
        <p>Upload the two daily exports to generate the first one.</p>
        <Link className="loaner-btn" to="/loaners/upload">Upload data</Link>
      </div>
    );
  }

  if (error) {
    return <div className="loaner-sheet-error">{error}</div>;
  }

  const { meta, staleRates, html } = sheet;

  return (
    <div className="loaner-sheet-page">
      <div className="loaner-sheet-toolbar">
        <div className="loaner-sheet-status">
          <span>
            <b>Data last uploaded:</b>{' '}
            {format(new Date(meta.generatedAt), "EEEE, MMMM d 'at' h:mm a")}
            {meta.generatedBy ? ` by ${meta.generatedBy}` : ''}
          </span>
          <span className="loaner-sheet-counts">
            {meta.priced} priced
            {meta.attention ? ` • ${meta.attention} need attention` : ''}
            {meta.mileageUpdates ? ` • ${meta.mileageUpdates} mileage updates` : ''}
          </span>
          {staleRates && (
            <div className="loaner-sheet-stale">
              ⚠ Rates were changed after this sheet was generated — upload fresh data to reprice.
            </div>
          )}
        </div>
        <div className="loaner-sheet-actions">
          <Link className="loaner-btn" to="/loaners/upload">Upload new data</Link>
          {isAdmin && (
            <Link className="loaner-btn loaner-btn-secondary" to="/loaners/settings">
              ⚙ Settings
            </Link>
          )}
        </div>
      </div>
      <iframe
        ref={iframeRef}
        className="loaner-sheet-frame"
        title="Loaner Payment Sheet"
        sandbox="allow-scripts allow-same-origin"
        srcDoc={html}
        onLoad={resizeIframe}
      />
    </div>
  );
}

export default LoanerSheet;
