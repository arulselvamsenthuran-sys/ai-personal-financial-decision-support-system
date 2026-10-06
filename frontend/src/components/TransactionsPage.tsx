import { useEffect, useState } from "react";
import { fetchTransactions, fetchAccounts, type Transaction, type FinancialAccount } from "../api/financial";

function fmt(v: string | null | undefined, currency?: string): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  if (isNaN(n)) return v;
  return currency
    ? `${currency} ${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function TransactionsPage() {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [accounts, setAccounts] = useState<FinancialAccount[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(accountId?: string) {
    setLoading(true);
    setError(null);
    try {
      const txns = await fetchTransactions(accountId || undefined);
      setTransactions(txns);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchAccounts().then(setAccounts).catch(() => {});
    load();
  }, []);

  function handleAccountFilter(e: React.ChangeEvent<HTMLSelectElement>) {
    const v = e.target.value;
    setSelectedAccount(v);
    load(v || undefined);
  }

  return (
    <div className="page-content" id="page-transactions">
      <div className="page-header-row">
        <h1 className="page-title">Transactions</h1>
        {accounts.length > 0 && (
          <select
            className="form-input form-input--select"
            value={selectedAccount}
            onChange={handleAccountFilter}
            id="txn-account-filter"
          >
            <option value="">All Accounts</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>{a.name} ({a.currency})</option>
            ))}
          </select>
        )}
      </div>

      {loading && <div className="page-loading"><div className="loading-spinner" /><p>Loading transactions…</p></div>}
      {error && <div className="alert-box alert-box--error">{error}</div>}

      {!loading && !error && transactions.length === 0 && (
        <div className="card"><p className="empty-text">No transactions found. Upload a CSV or PDF bank statement to import transactions.</p></div>
      )}

      {!loading && !error && transactions.length > 0 && (
        <div className="card">
          <div className="compact-table-wrap">
            <table className="data-table" id="transactions-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Description</th>
                  <th>Amount</th>
                  <th>Currency</th>
                  <th>Type</th>
                  <th>Category</th>
                  <th>Account</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((t) => {
                  const acctName = accounts.find((a) => a.id === t.financial_account_id)?.name ?? "—";
                  return (
                    <tr key={t.id}>
                      <td className="mono">{t.transaction_date}</td>
                      <td>{t.description || t.merchant || "—"}</td>
                      <td className={`mono ${t.transaction_type === "credit" ? "text-success" : "text-danger"}`}>
                        {fmt(t.amount, t.currency)}
                      </td>
                      <td>{t.currency}</td>
                      <td><span className={`tag tag--${t.transaction_type}`}>{t.transaction_type}</span></td>
                      <td>{t.category || "—"}</td>
                      <td className="text-muted">{acctName}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="table-footer-note">{transactions.length} transaction{transactions.length !== 1 ? "s" : ""}</p>
        </div>
      )}
    </div>
  );
}
