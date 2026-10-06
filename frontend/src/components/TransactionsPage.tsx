import { useEffect, useState } from "react";
import {
  fetchTransactions,
  fetchAccounts,
  createTransaction,
  type Transaction,
  type FinancialAccount,
  type TransactionCreateRequest,
} from "../api/financial";

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

  /* Add Transaction modal state */
  const [showAddModal, setShowAddModal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  /* Form fields */
  const [accountId, setAccountId] = useState("");
  const [txnType, setTxnType] = useState<"debit" | "credit">("debit");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("LKR");
  const [txnDate, setTxnDate] = useState(new Date().toISOString().split("T")[0]);
  const [description, setDescription] = useState("");
  const [merchant, setMerchant] = useState("");
  const [category, setCategory] = useState("");

  async function load(accId?: string) {
    setLoading(true);
    setError(null);
    try {
      const txns = await fetchTransactions(accId || undefined);
      setTransactions(txns);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchAccounts()
      .then((accts) => {
        setAccounts(accts);
        if (accts.length > 0) {
          setAccountId(accts[0].id);
          setCurrency(accts[0].currency || "LKR");
        }
      })
      .catch(() => {});
    load();
  }, []);

  function handleAccountFilter(e: React.ChangeEvent<HTMLSelectElement>) {
    const v = e.target.value;
    setSelectedAccount(v);
    load(v || undefined);
  }

  function handleAccountChange(accId: string) {
    setAccountId(accId);
    const found = accounts.find((a) => a.id === accId);
    if (found) {
      setCurrency(found.currency);
    }
  }

  async function handleAddTransaction(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSuccessMsg(null);

    if (!accountId) {
      setFormError("Please select a financial account.");
      return;
    }
    const numAmount = Number(amount);
    if (isNaN(numAmount) || numAmount <= 0) {
      setFormError("Amount must be a positive number.");
      return;
    }
    if (!txnDate) {
      setFormError("Please select a valid transaction date.");
      return;
    }
    if (!currency || currency.trim().length !== 3) {
      setFormError("Currency must be a 3-letter ISO code (e.g. LKR, USD).");
      return;
    }

    const payload: TransactionCreateRequest = {
      financial_account_id: accountId,
      transaction_type: txnType,
      amount: numAmount,
      currency: currency.trim().toUpperCase(),
      transaction_date: txnDate,
      description: description.trim() || undefined,
      merchant: merchant.trim() || undefined,
      category: category.trim() || undefined,
    };

    setSubmitting(true);
    try {
      await createTransaction(payload);
      setSuccessMsg("Transaction added successfully!");
      setShowAddModal(false);
      // Reset form
      setAmount("");
      setDescription("");
      setMerchant("");
      setCategory("");
      // Refresh list
      load(selectedAccount || undefined);
    } catch (err: any) {
      setFormError(err.message || "Failed to add transaction.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page-content" id="page-transactions">
      <div className="page-header-row">
        <h1 className="page-title">Transactions</h1>
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          {accounts.length > 0 && (
            <select
              className="form-input form-input--select"
              value={selectedAccount}
              onChange={handleAccountFilter}
              id="txn-account-filter"
            >
              <option value="">All Accounts</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.currency})
                </option>
              ))}
            </select>
          )}
          <button
            className="btn btn--primary"
            onClick={() => {
              setShowAddModal(true);
              setFormError(null);
            }}
            id="btn-add-transaction"
          >
            + Add Transaction
          </button>
        </div>
      </div>

      {successMsg && (
        <div className="alert-box alert-box--success" style={{ marginBottom: "1rem" }}>
          {successMsg}
        </div>
      )}

      {/* ── Add Transaction Modal / Form ── */}
      {showAddModal && (
        <div className="card" id="add-transaction-modal" style={{ marginBottom: "1.5rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 className="card__title">Add New Transaction</h2>
            <button
              className="btn btn--secondary"
              onClick={() => setShowAddModal(false)}
              style={{ padding: "0.25rem 0.5rem", fontSize: "0.85rem" }}
            >
              ✕ Close
            </button>
          </div>
          {formError && <div className="alert-box alert-box--error">{formError}</div>}
          <form onSubmit={handleAddTransaction} style={{ marginTop: "1rem" }}>
            {/* Type selector: Income vs Expense */}
            <div className="form-group" style={{ marginBottom: "1rem" }}>
              <label className="form-label">Transaction Type</label>
              <div style={{ display: "flex", gap: "1rem" }}>
                <button
                  type="button"
                  className={`btn ${txnType === "debit" ? "btn--primary" : "btn--secondary"}`}
                  style={{ flex: 1, backgroundColor: txnType === "debit" ? "#ef4444" : undefined, borderColor: txnType === "debit" ? "#ef4444" : undefined }}
                  onClick={() => setTxnType("debit")}
                >
                  🔴 Expense (Debit)
                </button>
                <button
                  type="button"
                  className={`btn ${txnType === "credit" ? "btn--primary" : "btn--secondary"}`}
                  style={{ flex: 1, backgroundColor: txnType === "credit" ? "#10b981" : undefined, borderColor: txnType === "credit" ? "#10b981" : undefined }}
                  onClick={() => setTxnType("credit")}
                >
                  🟢 Income (Credit)
                </button>
              </div>
            </div>

            <div className="form-grid-2">
              <div className="form-group">
                <label className="form-label" htmlFor="txn-account-select">Account</label>
                <select
                  id="txn-account-select"
                  className="form-input"
                  value={accountId}
                  onChange={(e) => handleAccountChange(e.target.value)}
                  required
                >
                  <option value="" disabled>Select Account</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} ({a.currency})
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="txn-date">Date</label>
                <input
                  id="txn-date"
                  type="date"
                  className="form-input"
                  value={txnDate}
                  onChange={(e) => setTxnDate(e.target.value)}
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="txn-amount">Amount</label>
                <input
                  id="txn-amount"
                  type="number"
                  step="0.01"
                  min="0.01"
                  className="form-input"
                  placeholder="e.g. 1500.00"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="txn-currency">Currency</label>
                <input
                  id="txn-currency"
                  type="text"
                  maxLength={3}
                  className="form-input"
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value)}
                  required
                />
              </div>
            </div>

            <div className="form-grid-2">
              <div className="form-group">
                <label className="form-label" htmlFor="txn-description">Description</label>
                <input
                  id="txn-description"
                  type="text"
                  maxLength={1000}
                  className="form-input"
                  placeholder="e.g. Monthly grocery shopping"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="txn-merchant">Merchant (optional)</label>
                <input
                  id="txn-merchant"
                  type="text"
                  className="form-input"
                  placeholder="e.g. Supermarket"
                  value={merchant}
                  onChange={(e) => setMerchant(e.target.value)}
                />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="txn-category">Category (optional)</label>
              <input
                id="txn-category"
                type="text"
                className="form-input"
                placeholder="e.g. Groceries, Salary, Utilities"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              />
            </div>

            <div className="form-actions" style={{ marginTop: "1rem" }}>
              <button type="submit" className="btn btn--primary" disabled={submitting}>
                {submitting ? "Saving..." : "Save Transaction"}
              </button>
              <button
                type="button"
                className="btn btn--secondary"
                onClick={() => setShowAddModal(false)}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {loading && <div className="page-loading"><div className="loading-spinner" /><p>Loading transactions…</p></div>}
      {error && <div className="alert-box alert-box--error">{error}</div>}

      {!loading && !error && transactions.length === 0 && (
        <div className="card"><p className="empty-text">No transactions found. Add a transaction or upload a statement to get started.</p></div>
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

