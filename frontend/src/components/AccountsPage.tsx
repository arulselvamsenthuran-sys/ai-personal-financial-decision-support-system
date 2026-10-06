import { useEffect, useState } from "react";
import { fetchAccounts, type FinancialAccount } from "../api/financial";

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<FinancialAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAccounts()
      .then(setAccounts)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page-loading"><div className="loading-spinner" /><p>Loading accounts…</p></div>;
  if (error) return <div className="alert-box alert-box--error">{error}</div>;

  return (
    <div className="page-content" id="page-accounts">
      <h1 className="page-title">Financial Accounts</h1>

      {accounts.length === 0 ? (
        <div className="card"><p className="empty-text">No financial accounts found. Upload a bank statement to create an account automatically.</p></div>
      ) : (
        <div className="accounts-grid">
          {accounts.map((a) => (
            <div key={a.id} className="card account-card">
              <div className="account-card__header">
                <h3 className="account-card__name">{a.name}</h3>
                <span className={`status-pill ${a.is_active ? "status-pill--active" : "status-pill--inactive"}`}>
                  {a.is_active ? "Active" : "Inactive"}
                </span>
              </div>
              <div className="account-card__details">
                <DetailRow label="Type" value={a.account_type} />
                <DetailRow label="Institution" value={a.institution_name ?? "—"} />
                <DetailRow label="Currency" value={a.currency} />
                <DetailRow label="Account №" value={a.account_identifier_masked ?? "—"} mono />
                {a.opening_balance !== null && (
                  <DetailRow label="Opening Balance" value={`${a.currency} ${Number(a.opening_balance).toLocaleString(undefined, { minimumFractionDigits: 2 })}`} />
                )}
              </div>
              <div className="account-card__footer">
                <span className="text-dim">Created {new Date(a.created_at).toLocaleDateString()}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DetailRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="detail-row">
      <span className="detail-row__label">{label}</span>
      <span className={`detail-row__value${mono ? " mono" : ""}`}>{value}</span>
    </div>
  );
}
