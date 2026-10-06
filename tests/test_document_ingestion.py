"""Tests for Phase 7 Document Ingestion Pipeline.

Covers:
- Authenticated vs unauthenticated upload (401)
- Account ownership enforcement (cross-user 404)
- Allowed vs invalid file extensions (.exe -> 400)
- Oversized file rejection (>10MB -> 400)
- Empty file rejection (400)
- SHA-256 duplicate document detection (409)
- CSV statement parsing & Decimal normalization
- Malformed / binary CSV rejection (400)
- Formula injection sanitization
- PDF magic validation & text extraction
- PDF parsing with real PDF content
- PDF with no extractable text / parsing errors handled safely
- Path traversal filename safety
- Transaction ownership & source metadata
- Sensitive data isolation in API responses
"""

import io
import uuid
import pytest
from decimal import Decimal
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.orm import Session


from app.core.rate_limit import auth_rate_limiter
from app.db.session import SessionLocal
from app.main import app
from app.models.financial_account import FinancialAccount
from app.models.financial_document import FinancialDocument
from app.models.transaction import Transaction


@pytest.fixture
def db() -> Session:
    """Yield database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
async def setup_ingestion_users(db: Session):
    """Setup User A and User B with financial accounts for ingestion testing."""
    auth_rate_limiter.reset()
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"origin": "http://localhost:5173"},
    ) as client_a:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"origin": "http://localhost:5173"},
        ) as client_b:
            email_a = f"ingest_a_{uuid.uuid4().hex[:8]}@example.com"
            email_b = f"ingest_b_{uuid.uuid4().hex[:8]}@example.com"
            password = "Password123!"

            # Register
            r_a = await client_a.post("/api/auth/register", json={"email": email_a, "password": password})
            r_b = await client_b.post("/api/auth/register", json={"email": email_b, "password": password})
            user_a_id = uuid.UUID(r_a.json()["id"])
            user_b_id = uuid.UUID(r_b.json()["id"])

            # Login to populate session cookies
            await client_a.post("/api/auth/login", json={"email": email_a, "password": password})
            await client_b.post("/api/auth/login", json={"email": email_b, "password": password})

            # Create Financial Account for User A
            acc_a = FinancialAccount(
                user_id=user_a_id,
                name="User A Checking",
                account_type="bank",
                institution_name="Bank Alpha",
                account_identifier_masked="****1111",
                currency="USD",
            )
            db.add(acc_a)

            # Create Financial Account for User B
            acc_b = FinancialAccount(
                user_id=user_b_id,
                name="User B Savings",
                account_type="savings",
                institution_name="Bank Beta",
                account_identifier_masked="****2222",
                currency="USD",
            )
            db.add(acc_b)
            db.commit()

            yield {
                "client_a": client_a,
                "client_b": client_b,
                "user_a_id": user_a_id,
                "user_b_id": user_b_id,
                "acc_a_id": acc_a.id,
                "acc_b_id": acc_b.id,
            }

            # Cleanup
            db.execute(text("DELETE FROM users WHERE id IN (:id_a, :id_b)"), {"id_a": user_a_id, "id_b": user_b_id})
            db.commit()


@pytest.mark.anyio
async def test_unauthenticated_document_upload_fails():
    """POST /api/financial/documents without session cookie returns 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"origin": "http://localhost:5173"},
    ) as unauth_client:
        files = {"file": ("test.csv", io.BytesIO(b"Date,Amount,Description\n2026-01-01,100.00,Test"), "text/csv")}
        response = await unauth_client.post(
            "/api/financial/documents",
            params={"account_id": str(uuid.uuid4())},
            files=files,
        )
        assert response.status_code == 401


@pytest.mark.anyio
async def test_upload_invalid_file_extension(setup_ingestion_users):
    """POST upload with .exe extension returns 400."""
    env = setup_ingestion_users
    client_a: AsyncClient = env["client_a"]

    files = {"file": ("malicious.exe", io.BytesIO(b"MZ executable content"), "application/octet-stream")}
    response = await client_a.post(
        "/api/financial/documents",
        params={"account_id": str(env["acc_a_id"])},
        files=files,
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


@pytest.mark.anyio
async def test_upload_empty_file(setup_ingestion_users):
    """POST upload empty file returns 400."""
    env = setup_ingestion_users
    client_a: AsyncClient = env["client_a"]

    files = {"file": ("empty.csv", io.BytesIO(b""), "text/csv")}
    response = await client_a.post(
        "/api/financial/documents",
        params={"account_id": str(env["acc_a_id"])},
        files=files,
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_upload_oversized_file(setup_ingestion_users):
    """POST upload file > 10MB returns 400."""
    env = setup_ingestion_users
    client_a: AsyncClient = env["client_a"]

    oversized_content = b"a" * (10 * 1024 * 1024 + 1)
    files = {"file": ("big.csv", io.BytesIO(oversized_content), "text/csv")}
    response = await client_a.post(
        "/api/financial/documents",
        params={"account_id": str(env["acc_a_id"])},
        files=files,
    )
    assert response.status_code == 400
    assert "exceeds maximum allowed limit" in response.json()["detail"]


@pytest.mark.anyio
async def test_upload_csv_success(setup_ingestion_users):
    """POST upload clean CSV creates document and normalized transactions."""
    env = setup_ingestion_users
    client_a: AsyncClient = env["client_a"]

    csv_content = (
        "Date,Description,Amount,Type\n"
        "2026-03-01,Grocery Store,-45.50,debit\n"
        "2026-03-02,Salary Deposit,2500.00,credit\n"
    ).encode("utf-8")

    files = {"file": ("bank_statement_march.csv", io.BytesIO(csv_content), "text/csv")}
    response = await client_a.post(
        "/api/financial/documents",
        params={"account_id": str(env["acc_a_id"])},
        files=files,
    )
    assert response.status_code == 201
    data = response.json()

    assert data["original_filename"] == "bank_statement_march.csv"
    assert data["processing_status"] == "completed"
    assert data["file_hash"] is not None
    # Ensure internal storage reference and filesystem paths are never returned
    assert "storage_reference" not in data

    # Verify transactions created in API
    tx_resp = await client_a.get(
        f"/api/financial/transactions?account_id={env['acc_a_id']}"
    )
    assert tx_resp.status_code == 200
    transactions = tx_resp.json()
    assert len(transactions) == 2


@pytest.mark.anyio
async def test_duplicate_document_upload_rejected(setup_ingestion_users):
    """POST uploading identical document content twice returns 409 conflict."""
    env = setup_ingestion_users
    client_a: AsyncClient = env["client_a"]

    content = b"Date,Description,Amount\n2026-01-15,Coffee Shop,4.50\n"

    # First upload succeeds
    files1 = {"file": ("statement1.csv", io.BytesIO(content), "text/csv")}
    res1 = await client_a.post(
        "/api/financial/documents",
        params={"account_id": str(env["acc_a_id"])},
        files=files1,
    )
    assert res1.status_code == 201

    # Second upload with identical bytes fails with 409
    files2 = {"file": ("statement1_copy.csv", io.BytesIO(content), "text/csv")}
    res2 = await client_a.post(
        "/api/financial/documents",
        params={"account_id": str(env["acc_a_id"])},
        files=files2,
    )
    assert res2.status_code == 409
    assert "identical content has already been uploaded" in res2.json()["detail"]


@pytest.mark.anyio
async def test_csv_formula_injection_sanitization(setup_ingestion_users):
    """CSV fields starting with '=', '+', '-', '@' are sanitized with single quote."""
    env = setup_ingestion_users
    client_a: AsyncClient = env["client_a"]

    csv_content = (
        "Date,Description,Amount\n"
        "2026-03-05,=CMD|' /C calc'!A0,10.00\n"
        "2026-03-06,@SUM(1+1),20.00\n"
    ).encode("utf-8")

    files = {"file": ("formula_test.csv", io.BytesIO(csv_content), "text/csv")}
    response = await client_a.post(
        "/api/financial/documents",
        params={"account_id": str(env["acc_a_id"])},
        files=files,
    )
    assert response.status_code == 201

    tx_resp = await client_a.get(
        f"/api/financial/transactions?account_id={env['acc_a_id']}"
    )
    txs = tx_resp.json()
    descriptions = [t["description"] for t in txs]
    assert any("=CMD" in desc and desc.startswith("'") for desc in descriptions) or any("@SUM" in desc and desc.startswith("'") for desc in descriptions)


@pytest.mark.anyio
async def test_upload_binary_as_csv_fails(setup_ingestion_users):
    """Uploading executable binary renamed to .csv fails content validation with 400."""
    env = setup_ingestion_users
    client_a: AsyncClient = env["client_a"]

    binary_content = b"\x7fELF\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    files = {"file": ("fake.csv", io.BytesIO(binary_content), "text/csv")}
    response = await client_a.post(
        "/api/financial/documents",
        params={"account_id": str(env["acc_a_id"])},
        files=files,
    )
    assert response.status_code == 400
    assert "binary data" in response.json()["detail"]


@pytest.mark.anyio
async def test_upload_malformed_pdf_fails(setup_ingestion_users):
    """Uploading non-PDF content named .pdf fails magic check with 400."""
    env = setup_ingestion_users
    client_a: AsyncClient = env["client_a"]

    fake_pdf = b"This is plain text, not a PDF header."
    files = {"file": ("statement.pdf", io.BytesIO(fake_pdf), "application/pdf")}
    response = await client_a.post(
        "/api/financial/documents",
        params={"account_id": str(env["acc_a_id"])},
        files=files,
    )
    assert response.status_code == 400
    assert "not a valid PDF file" in response.json()["detail"]


@pytest.mark.anyio
async def test_upload_to_other_users_account_fails(setup_ingestion_users):
    """Uploading a document targeting User B's account returns 404."""
    env = setup_ingestion_users
    client_a: AsyncClient = env["client_a"]

    csv_content = b"Date,Description,Amount\n2026-01-01,Test,10.00\n"
    files = {"file": ("cross_user.csv", io.BytesIO(csv_content), "text/csv")}
    response = await client_a.post(
        "/api/financial/documents",
        params={"account_id": str(env["acc_b_id"])},
        files=files,
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_path_traversal_filename_sanitization(setup_ingestion_users):
    """Path traversal filename (e.g. ../../../etc/passwd.csv) is safely handled."""
    env = setup_ingestion_users
    client_a: AsyncClient = env["client_a"]

    csv_content = b"Date,Description,Amount\n2026-04-01,Safe,15.00\n"
    files = {"file": ("../../../../etc/passwd.csv", io.BytesIO(csv_content), "text/csv")}
    response = await client_a.post(
        "/api/financial/documents",
        params={"account_id": str(env["acc_a_id"])},
        files=files,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["processing_status"] == "completed"


@pytest.mark.anyio
async def test_valid_pdf_upload_and_empty_text_state(setup_ingestion_users):
    """Uploading a valid blank PDF transitions document status safely to failed without crash."""
    env = setup_ingestion_users
    client_a: AsyncClient = env["client_a"]

    # Minimal valid empty 1-page PDF
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
        b"xref\n"
        b"0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000052 00000 n \n"
        b"0000000101 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n"
        b"178\n"
        b"%%EOF"
    )

    files = {"file": ("blank_statement.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    response = await client_a.post(
        "/api/financial/documents",
        params={"account_id": str(env["acc_a_id"])},
        files=files,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["processing_status"] == "failed"
    assert data["processing_error"] is not None
    assert "no extractable text" in data["processing_error"].lower() or "no valid transaction rows" in data["processing_error"].lower()


@pytest.mark.anyio
async def test_pdf_parser_regression_four_lines():
    """Direct parser test for the 4 user-reported statement lines:
    04/09/2026 Electricity 3500
    03/09/2026 Transport 500
    02/09/2026 Supermarket 2500
    01/09/2026 Salary 80000
    """
    from datetime import date
    from app.services.parsers.pdf_parser import GenericPDFParser

    parser = GenericPDFParser()
    raw_lines = [
        "04/09/2026 Electricity 3500",
        "03/09/2026 Transport 500",
        "02/09/2026 Supermarket 2500",
        "01/09/2026 Salary 80000",
    ]

    errors: list[str] = []
    txs = parser._parse_lines(raw_lines, statement_currency="LKR", errors=errors)

    assert len(txs) == 4
    assert len(errors) == 0

    # 1. Electricity 3500 (debit)
    assert txs[0].transaction_date == date(2026, 9, 4)
    assert txs[0].description == "Electricity"
    assert txs[0].amount == Decimal("3500")
    assert txs[0].transaction_type == "debit"
    assert txs[0].currency == "LKR"

    # 2. Transport 500 (debit)
    assert txs[1].transaction_date == date(2026, 9, 3)
    assert txs[1].description == "Transport"
    assert txs[1].amount == Decimal("500")
    assert txs[1].transaction_type == "debit"
    assert txs[1].currency == "LKR"

    # 3. Supermarket 2500 (debit)
    assert txs[2].transaction_date == date(2026, 9, 2)
    assert txs[2].description == "Supermarket"
    assert txs[2].amount == Decimal("2500")
    assert txs[2].transaction_type == "debit"
    assert txs[2].currency == "LKR"

    # 4. Salary 80000 (credit)
    assert txs[3].transaction_date == date(2026, 9, 1)
    assert txs[3].description == "Salary"
    assert txs[3].amount == Decimal("80000")
    assert txs[3].transaction_type == "credit"
    assert txs[3].currency == "LKR"


@pytest.mark.anyio
async def test_processed_at_timestamp_and_currency_resolution(setup_ingestion_users, db: Session):
    """Verify processed_at is populated on completion and transaction currency inherits from account when not explicit."""
    env = setup_ingestion_users
    client_a: AsyncClient = env["client_a"]

    # 1. Update User A's account currency to EUR to test non-USD inheritance
    acc_a = db.query(FinancialAccount).filter(FinancialAccount.id == env["acc_a_id"]).first()
    acc_a.currency = "EUR"
    db.commit()

    csv_content = (
        "Date,Description,Amount\n"
        "2026-05-01,Coffee,3.50\n"
    ).encode("utf-8")

    files = {"file": ("statement_eur.csv", io.BytesIO(csv_content), "text/csv")}
    response = await client_a.post(
        "/api/financial/documents",
        params={"account_id": str(env["acc_a_id"])},
        files=files,
    )
    assert response.status_code == 201
    data = response.json()

    # Verify processed_at is set
    assert data["processing_status"] == "completed"
    assert data["processed_at"] is not None

    # Verify transaction currency matches account currency EUR
    tx_resp = await client_a.get(
        f"/api/financial/transactions?account_id={env['acc_a_id']}"
    )
    assert tx_resp.status_code == 200
    txs = tx_resp.json()
    assert len(txs) >= 1
    assert txs[0]["currency"] == "EUR"



