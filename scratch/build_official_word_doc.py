"""
Official Document Generator for MYCOIN Cryptocurrency Platform.
Uses python-docx to generate an authentic, fully compliant Microsoft Word document (.docx).
"""

import os
import sys
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

def set_cell_background(cell, hex_color):
    """Sets background shading color for a table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    """Sets cell padding."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tcPr.append(tcMar)

def set_table_borders(table, color="CBD5E1"):
    """Sets clean subtle borders on a table."""
    tblPr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="6" w:space="0" w:color="{color}"/>'
        f'<w:bottom w:val="single" w:sz="8" w:space="0" w:color="0F2C59"/>'
        f'<w:left w:val="single" w:sz="6" w:space="0" w:color="{color}"/>'
        f'<w:right w:val="single" w:sz="6" w:space="0" w:color="{color}"/>'
        f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
        f'<w:insideV w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
        f'</w:tblBorders>'
    )
    tblPr.append(borders)

def add_callout(doc, text, title="NOTE / ARCHITECTURAL RULE"):
    """Creates a callout card with a left border and shaded background."""
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = tbl.cell(0, 0)
    set_cell_background(cell, "F0F4F8")
    set_cell_margins(cell, top=140, bottom=140, left=200, right=180)
    
    # Left border only
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:top w:val="none"/>'
        f'<w:bottom w:val="none"/>'
        f'<w:left w:val="single" w:sz="24" w:space="0" w:color="337CCF"/>'
        f'<w:right w:val="none"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)
    
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    
    r_title = p.add_run(f"📌 {title}: ")
    r_title.bold = True
    r_title.font.name = "Calibri"
    r_title.font.size = Pt(10.5)
    r_title.font.color.rgb = RGBColor(15, 44, 89)
    
    r_text = p.add_run(text)
    r_text.font.name = "Calibri"
    r_text.font.size = Pt(10)
    r_text.font.color.rgb = RGBColor(50, 50, 50)
    
    # Empty space after table
    p_after = doc.add_paragraph()
    p_after.paragraph_format.space_before = Pt(0)
    p_after.paragraph_format.space_after = Pt(6)

def add_code_block(doc, code_text):
    """Adds a shaded monospace code box."""
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = tbl.cell(0, 0)
    set_cell_background(cell, "F6F8FA")
    set_cell_margins(cell, top=100, bottom=100, left=150, right=150)
    
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        f'<w:bottom w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        f'<w:left w:val="single" w:sz="18" w:space="0" w:color="0F2C59"/>'
        f'<w:right w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)
    
    lines = code_text.strip().split("\n")
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.15
    
    for idx, line in enumerate(lines):
        if idx > 0:
            p = cell.add_paragraph()
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.15
        r = p.add_run(line)
        r.font.name = "Consolas"
        r.font.size = Pt(9)
        r.font.color.rgb = RGBColor(31, 35, 40)
        
    p_after = doc.add_paragraph()
    p_after.paragraph_format.space_before = Pt(0)
    p_after.paragraph_format.space_after = Pt(6)

def add_styled_table(doc, headers, data_rows, col_widths=None):
    """Adds a beautifully styled table with header row and zebra stripes."""
    table = doc.add_table(rows=len(data_rows) + 1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(table)
    
    # Header Row
    hdr_cells = table.rows[0].cells
    for i, title in enumerate(headers):
        hdr_cells[i].text = title
        set_cell_background(hdr_cells[i], "0F2C59")
        set_cell_margins(hdr_cells[i], top=100, bottom=100, left=120, right=120)
        p = hdr_cells[i].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in p.runs:
            run.font.bold = True
            run.font.name = "Segoe UI"
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor(255, 255, 255)
            
    # Data Rows
    for r_idx, row in enumerate(data_rows):
        row_cells = table.rows[r_idx + 1].cells
        bg_color = "F8FAFC" if (r_idx % 2 == 1) else "FFFFFF"
        for c_idx, val in enumerate(row):
            row_cells[c_idx].text = str(val)
            set_cell_background(row_cells[c_idx], bg_color)
            set_cell_margins(row_cells[c_idx], top=80, bottom=80, left=120, right=120)
            p = row_cells[c_idx].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            for run in p.runs:
                run.font.name = "Calibri"
                run.font.size = Pt(9.5)
                run.font.color.rgb = RGBColor(38, 38, 38)
                
    if col_widths:
        for row in table.rows:
            for idx, w in enumerate(col_widths):
                row.cells[idx].width = Inches(w)
                
    p_after = doc.add_paragraph()
    p_after.paragraph_format.space_before = Pt(0)
    p_after.paragraph_format.space_after = Pt(6)

def add_custom_heading(doc, text, level):
    """Adds a heading with custom typography and color."""
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = True
    if level == 1:
        p.paragraph_format.space_before = Pt(18)
        p.paragraph_format.space_after = Pt(8)
        r.font.name = "Segoe UI"
        r.font.size = Pt(18)
        r.font.color.rgb = RGBColor(15, 44, 89)
    elif level == 2:
        p.paragraph_format.space_before = Pt(14)
        p.paragraph_format.space_after = Pt(6)
        r.font.name = "Segoe UI"
        r.font.size = Pt(14)
        r.font.color.rgb = RGBColor(20, 66, 114)
    elif level == 3:
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(4)
        r.font.name = "Segoe UI"
        r.font.size = Pt(12)
        r.font.color.rgb = RGBColor(51, 124, 207)
    return p

def add_body_p(doc, text, bold_prefix=None):
    """Adds body text with standard formatting."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(5)
    p.paragraph_format.line_spacing = 1.15
    if bold_prefix:
        r_b = p.add_run(bold_prefix + " ")
        r_b.bold = True
        r_b.font.name = "Calibri"
        r_b.font.size = Pt(11)
        r_b.font.color.rgb = RGBColor(15, 44, 89)
    r = p.add_run(text)
    r.font.name = "Calibri"
    r.font.size = Pt(11)
    r.font.color.rgb = RGBColor(38, 38, 38)
    return p

def add_bullet_p(doc, text, bold_prefix=None):
    """Adds a bullet paragraph."""
    p = doc.add_paragraph(style='List Bullet')
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.15
    if bold_prefix:
        r_b = p.add_run(bold_prefix + " ")
        r_b.bold = True
        r_b.font.name = "Calibri"
        r_b.font.size = Pt(11)
        r_b.font.color.rgb = RGBColor(15, 44, 89)
    r = p.add_run(text)
    r.font.name = "Calibri"
    r.font.size = Pt(11)
    r.font.color.rgb = RGBColor(38, 38, 38)
    return p

print("Loaded builder helper functions.")


def generate_mycoin_word_document():
    doc = Document()
    
    # Page Margins: 1 inch (72 pt) all around
    sections = doc.sections
    for sec in sections:
        sec.top_margin = Inches(1.0)
        sec.bottom_margin = Inches(1.0)
        sec.left_margin = Inches(1.0)
        sec.right_margin = Inches(1.0)
        sec.page_width = Inches(8.5)
        sec.page_height = Inches(11.0)
        
    # =========================================================================
    # COVER / TITLE HEADER
    # =========================================================================
    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(12)
    p_title.paragraph_format.space_after = Pt(4)
    r_title = p_title.add_run("MYCOIN PLATFORM ARCHITECTURE & FLOW DOCUMENTATION")
    r_title.bold = True
    r_title.font.name = "Segoe UI"
    r_title.font.size = Pt(24)
    r_title.font.color.rgb = RGBColor(15, 44, 89)
    
    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_before = Pt(0)
    p_sub.paragraph_format.space_after = Pt(8)
    r_sub = p_sub.add_run("Complete End-to-End Technical Workflow from User Registration to Block Creation")
    r_sub.font.name = "Calibri"
    r_sub.font.size = Pt(14)
    r_sub.font.color.rgb = RGBColor(51, 124, 207)
    
    p_meta = doc.add_paragraph()
    p_meta.paragraph_format.space_before = Pt(0)
    p_meta.paragraph_format.space_after = Pt(16)
    r_meta = p_meta.add_run("Project: MYCOIN (MYC)  |  Architecture: Clean Architecture (DDD) with Django & DRF  |  Version: 1.0 (Implemented)")
    r_meta.italic = True
    r_meta.font.name = "Calibri"
    r_meta.font.size = Pt(9.5)
    r_meta.font.color.rgb = RGBColor(100, 100, 100)
    
    # =========================================================================
    # SECTION 1: EXECUTIVE SUMMARY
    # =========================================================================
    add_custom_heading(doc, "1. Executive Summary & Architectural Overview", level=1)
    add_body_p(
        doc,
        "MYCOIN is a high-integrity, decentralized cryptocurrency ledger designed according to Clean Architecture and "
        "Domain-Driven Design (DDD) principles. The platform enforces strict cryptographic signing (ECDSA secp256k1), "
        "multi-stage state validation, atomic database transactions (ACID compliance), and continuous block production "
        "without external broker dependencies such as Celery or Redis."
    )
    add_callout(
        doc,
        "Primary Ledger Invariant: Total coin supply is strictly conserved. No balance can ever be minted, deducted, or transferred "
        "without an immutable transaction receipt and inclusion in a finalized block.",
        title="PRIMARY SUPPLY CONSERVATION INVARIANT"
    )
    
    add_styled_table(
        doc,
        headers=["Core Parameter", "Specification", "Architectural Role"],
        data_rows=[
            ["Native Token Symbol", "MYC", "Primary native currency identifier."],
            ["Decimals", "8 Decimals (10^8)", "1 MYC = 100,000,000 smallest base units (fits BigIntegerField)."],
            ["Total Initial Supply", "1,000,000 MYC", "100,000,000,000,000 base units minted strictly at Genesis."],
            ["Target Block Time", "5 Seconds", "Configured target slot interval between consecutive blocks."],
            ["Maximum Block Gas", "30,000,000 Gas", "Upper gas ceiling permitted per single proposed block."],
            ["Base Transfer Gas", "21,000 Gas", "Standard gas units consumed for a native coin transfer."],
            ["Cryptographic Curve", "ECDSA secp256k1", "Elliptic curve cryptography for keypairs and signing."],
            ["Address Format", "0x + 40 hex chars", "Standard 42-character address derived via SHA-256 public key hash."],
            ["Consensus Quorum", "2/3 Majority (> 66.7%)", "Finality numerator (2) and denominator (3) for PoS validator voting."]
        ],
        col_widths=[1.8, 1.8, 2.9]
    )
    
    add_custom_heading(doc, "1.1 Clean Architecture Layers", level=2)
    add_bullet_p(doc, "Domain Layer: Encapsulates pure business entities, value objects, and domain invariants without framework dependencies.", bold_prefix="Domain:")
    add_bullet_p(doc, "Application Layer: Implements discrete use cases (e.g. RegisterAccountUseCase, ValidateTransactionUseCase, InitializeGenesisUseCase) orchestrating workflows.", bold_prefix="Application:")
    add_bullet_p(doc, "Infrastructure Layer: Concrete database repositories, cryptographic adapters, and external communication services.", bold_prefix="Infrastructure:")
    add_bullet_p(doc, "Presentation Layer: Django REST Framework APIViews exposing versioned, camelCase RESTful endpoints with consistent success/reason JSON payloads.", bold_prefix="Presentation:")
    
    # =========================================================================
    # SECTION 2: BLOCKCHAIN CREATION, NODE CREATION & GENESIS
    # =========================================================================
    doc.add_page_break()
    add_custom_heading(doc, "2. Blockchain Bootstrap, Node Creation & Genesis Block", level=1)
    add_body_p(
        doc,
        "Before any user transactions can take place, the blockchain network must be bootstrapped from an uninitialized state. "
        "The genesis bootstrapping workflow establishes protocol parameters, creates deterministic system reserves, mints the initial coin supply, "
        "and binds Genesis Block #0 as the root anchor of the cryptographic chain."
    )
    
    add_custom_heading(doc, "2.1 Deterministic System Accounts & Supply Allocations", level=2)
    add_body_p(
        doc,
        "To eliminate arbitrary inflation and guarantee that every coin is traceable to the exact block of creation, "
        "MYCOIN defines four immutable deterministic system accounts using standard 42-character hexadecimal addresses:"
    )
    add_styled_table(
        doc,
        headers=["System Account", "Address", "Initial Supply (MYC)", "Allocation Purpose"],
        data_rows=[
            ["Genesis Mint", "0x0000000000000000000000000000000000000000", "0 MYC (Nonce: 3)", "Zero-address mint origin. Executes 3 audit transfers then zeroed."],
            ["Treasury Reserve", "0x0000000000000000000000000000000000000001", "600,000 MYC", "Funds user registration bonuses (100 MYC each) and network incentives."],
            ["Validator Reserve", "0x0000000000000000000000000000000000000002", "300,000 MYC", "Funds initial staking collateral for validator node bootstrapping."],
            ["Development Reserve", "0x0000000000000000000000000000000000000003", "100,000 MYC", "Allocated for core infrastructure development and maintenance."]
        ],
        col_widths=[1.6, 2.3, 1.4, 2.2]
    )
    add_callout(
        doc,
        "Conservation Guarantee: Sum of allocations (600,000 + 300,000 + 100,000 = 1,000,000 MYC) exactly matches the 1,000,000 MYC initial supply. "
        "No floating-point math is used; all operations are executed in integer base units (1 MYC = 100,000,000 units).",
        title="SUPPLY CONSERVATION GUARANTEE"
    )
    
    add_custom_heading(doc, "2.2 Genesis Block (Height 0) Creation", level=2)
    add_body_p(doc, "The Genesis Block represents Block #0. Unlike subsequent blocks, Genesis follows unique consensus rules:")
    add_bullet_p(doc, "Height: Strictly 0.")
    add_bullet_p(doc, "Parent Reference: Null (no parent block exists).")
    add_bullet_p(doc, "Previous Hash: Exactly 64 zeros ('0000000000000000000000000000000000000000000000000000000000000000').")
    add_bullet_p(doc, "Proposer: Null (protocol minting, not proposed by an individual validator).")
    add_bullet_p(doc, "Audit Transactions: Encapsulates 3 finalized mint transactions allocating funds from Genesis Mint to Treasury, Validator Reserve, and Development Reserve.")
    add_bullet_p(doc, "Status: Persisted directly in FINALIZED status and set as Blockchain.latestFinalizedBlock.")
    
    add_custom_heading(doc, "2.3 Node Architecture & Validator Node Seeding", level=2)
    add_body_p(doc, "Nodes represent active network participants. The Node model supports three structural roles:")
    add_bullet_p(doc, "Operates an active Validator instance with pledged stake, eligible to propose and finalize blocks.", bold_prefix="VALIDATOR Node:")
    add_bullet_p(doc, "Maintains full blockchain ledger history and mempool, validates incoming transactions, but does not propose blocks.", bold_prefix="FULL Node:")
    add_bullet_p(doc, "Read-only network participant for auditing, explorers, and API consumers.", bold_prefix="OBSERVER Node:")
    
    add_body_p(doc, "During node seeding (seed_validator_node), the system executes an automated workflow:")
    add_bullet_p(doc, "1. Creates an operator User and active keystore Wallet.")
    add_bullet_p(doc, "2. Deducts the required validator stake (1,000 MYC) directly from VALIDATOR_RESERVE_ADDRESS.")
    add_bullet_p(doc, "3. Creates a finalized ledger transaction and block recording the stake allocation.")
    add_bullet_p(doc, "4. Creates and activates the Validator model with totalStake and commission percentage.")
    add_bullet_p(doc, "5. Deploys the Node record with nodeType=VALIDATOR, status=ONLINE, and assigns its P2P endpoint.")
    
    # =========================================================================
    # SECTION 3: USER REGISTRATION & CRYPTOGRAPHIC KEYS
    # =========================================================================
    doc.add_page_break()
    add_custom_heading(doc, "3. User Registration, Cryptographic Keys & Wallets", level=1)
    add_body_p(
        doc,
        "MYCOIN implements an off-chain/on-chain dual abstraction: a Wallet is an off-chain cryptographic keypair container, "
        "while an Account is an on-chain ledger state entity tracking finalized spendable balances and sequential nonces."
    )
    
    add_custom_heading(doc, "3.1 Registration Workflow (OTP-based)", level=2)
    add_bullet_p(doc, "Step 1 (Request): User submits firstName, lastName, email to POST /api/accounts/register/. The backend validates email uniqueness, generates a 6-digit OTP with a 10-minute expiry, and records the audit log.")
    add_bullet_p(doc, "Step 2 (Verification): User submits OTP to POST /api/accounts/register/verify-otp/. The system validates attempts (< 5), verifies OTP match, creates the User model, and triggers automated wallet provisioning.")
    
    add_custom_heading(doc, "3.2 ECDSA secp256k1 Keypair Generation", level=2)
    add_body_p(
        doc,
        "Key generation adheres to industry-standard Bitcoin and Ethereum cryptographic algorithms:"
    )
    add_code_block(
        doc,
        "# Cryptographic Generation in wallets/services/wallet_service.py:\n"
        "1. Private Key (Signing Key):\n"
        "   sk = ecdsa.SigningKey.generate(curve=ecdsa.SECP256k1)\n"
        "   private_key_hex = sk.to_string().hex().lower()  # 64 lowercase hex characters (32 bytes)\n\n"
        "2. Public Key (Verifying Key):\n"
        "   vk = sk.get_verifying_key()\n"
        "   public_key_hex = ('04' + vk.to_string().hex()).lower()  # 130 hex chars ('04' prefix + 64 bytes)\n\n"
        "3. Address Derivation:\n"
        "   address_hash = hashlib.sha256(vk.to_string()).hexdigest().lower()\n"
        "   address = '0x' + address_hash[-40:]  # 42 lowercase hex chars ('0x' + last 40 hex chars)"
    )
    add_body_p(
        doc,
        "Keystore Storage Model: The generated private key hex is stored in Wallet.keyReference. "
        "This enables the backend prototype to sign transactions securely on behalf of authenticated users without requiring an external browser wallet."
    )
    
    add_custom_heading(doc, "3.3 Automated Registration Bonus (100 MYC)", level=2)
    add_body_p(doc, "Upon successful OTP confirmation, the system automatically initializes the user's on-chain presence:")
    add_bullet_p(doc, "Provisions an on-chain Account record (accountType=EOA, address=wallet.address).")
    add_bullet_p(doc, "Transfers 100 MYC (10,000,000,000 base units) from TREASURY_ADDRESS to the user's address.")
    add_bullet_p(doc, "Generates a finalized REG_BONUS transaction, packages it into a new Block at height parent.height + 1, and updates the blockchain tip.")
    add_bullet_p(doc, "User immediately receives a spendable balance of 100 MYC and an initial nonce of 0.")
    
    # =========================================================================
    # SECTION 4: TRANSACTION SIGNING & BROADCAST
    # =========================================================================
    doc.add_page_break()
    add_custom_heading(doc, "4. Transaction Construction & Cryptographic Signing", level=1)
    add_body_p(
        doc,
        "To prevent transaction tampering, replay attacks, and man-in-the-middle exploits, every state-changing transaction "
        "must be formatted into a deterministic canonical string, digested, and cryptographically signed using the sender's private key."
    )
    
    add_custom_heading(doc, "4.1 Canonical Payload Serialization", level=2)
    add_body_p(
        doc,
        "Both the signing module and the validation node must produce the exact same byte digest from transaction parameters. "
        "The canonical format is defined as a colon-delimited string incorporating the network chain ID for replay protection:"
    )
    add_code_block(
        doc,
        'Canonical Payload Format:\n'
        '"{chainId}:{senderAddress.lower()}:{receiverAddress.lower()}:{amount}:{nonce}:{gasLimit}:{gasPrice}"\n\n'
        'Example Payload String:\n'
        '"1001:0x3a4b9c1e7f82d05a91438b6d8e20f1a5c4e7b890:0x5e2a1b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a:5000000000:0:21000:1"\n\n'
        'SHA-256 Digest:\n'
        'payload_digest = hashlib.sha256(canonical_payload.encode("utf-8")).digest()'
    )
    
    add_custom_heading(doc, "4.2 Deterministic ECDSA Signature Generation", level=2)
    add_body_p(
        doc,
        "The payload digest is signed using deterministic ECDSA (RFC 6979) over secp256k1, avoiding random nonce vulnerabilities:"
    )
    add_code_block(
        doc,
        '# Deterministic Signing in wallets/services/transaction_signer.py:\n'
        'raw_signature_bytes = signing_key.sign_deterministic(\n'
        '    payload_digest,\n'
        '    hashfunc=hashlib.sha256,\n'
        '    sigencode=ecdsa.util.sigencode_string  # Generates 64 raw bytes: r (32 bytes) + s (32 bytes)\n'
        ')\n'
        'signature_hex = "0x" + raw_signature_bytes.hex().lower()  # 130 characters (\'0x\' + 128 hex chars)'
    )
    
    add_custom_heading(doc, "4.3 Transaction Hash Derivation", level=2)
    add_body_p(
        doc,
        "The unique Transaction Hash (TxHash) identifies the transaction globally across the blockchain. "
        "It is computed by hashing the canonical payload digest concatenated with the raw signature bytes:"
    )
    add_code_block(
        doc,
        'tx_hash = hashlib.sha256(payload_digest + raw_signature_bytes).hexdigest().lower()\n'
        '# Output: 64-character lowercase hex string (e.g. "a9f1b2c3d4e5...89f0")'
    )
    
    # =========================================================================
    # SECTION 5: NODE VALIDATION PIPELINE & MEMPOOL
    # =========================================================================
    doc.add_page_break()
    add_custom_heading(doc, "5. Node Validation Pipeline & Mempool Ingestion", level=1)
    add_body_p(
        doc,
        "When a signed transaction is submitted to POST /api/ledger/transactions/validate/, the receiving node "
        "subjects it to a strict 10-step validation engine before admitting it to the memory pool (mempool)."
    )
    
    add_styled_table(
        doc,
        headers=["Step", "Validation Gate", "Enforcement Rule & Failure Condition"],
        data_rows=[
            ["Step 0", "Blockchain Active", "Verifies an active Blockchain network exists. Fails if halted or uninitialized."],
            ["Step 1", "Sender Check", "Sender account must exist on-chain with status=ACTIVE. Fails with CHECK_SENDER."],
            ["Step 2", "Receiver Check", "Receiver address must be valid hex; sender != receiver. Fails with CHECK_RECEIVER."],
            ["Step 3", "Public Key Derivation", "SHA-256(publicKey) must derive sender.address. Fails with CHECK_PUBLIC_KEY."],
            ["Step 4", "Signature Verification", "Verifies ECDSA signature against canonical payload digest. Fails with CHECK_SIGNATURE."],
            ["Step 5", "Nonce Continuity", "Nonce must equal sender.nonce + count(pending mempool txs). Fails with CHECK_NONCE."],
            ["Step 6", "Spendable Balance", "Sender balance >= amount + (gasLimit * gasPrice) + pending costs. Fails with INSUFFICIENT_BALANCE."],
            ["Step 7", "Gas Limit Range", "gasLimit >= 21,000 and <= maxBlockGas. Fails with CHECK_GAS."],
            ["Step 8", "Gas Price Floor", "gasPrice >= minGasPrice (1 base unit). Fails with CHECK_GAS."],
            ["Step 9", "Replay / Duplicate Hash", "Transaction hash must not exist in ledger or mempool. Fails with DUPLICATE_TRANSACTION."]
        ],
        col_widths=[0.9, 1.8, 4.2]
    )
    
    add_custom_heading(doc, "5.1 What Happens When a Transaction is Rejected?", level=2)
    add_bullet_p(doc, "The transaction is NOT admitted to the Mempool and will NEVER be mined into a block.")
    add_bullet_p(doc, "The API immediately responds with HTTP 400 Bad Request, returning a structured JSON error body identifying the failure reason and failed step.")
    add_bullet_p(doc, "If a pre-existing draft record existed, its status is permanently marked as REJECTED.")
    add_bullet_p(doc, "Sender balances and nonces remain completely unaffected.")
    
    add_code_block(
        doc,
        '# Rejection API Response Example:\n'
        '{\n'
        '    "success": false,\n'
        '    "reason": "Insufficient balance. Required: 5000021000 base units, Available: 2000000000 base units.",\n'
        '    "step": "INSUFFICIENT_BALANCE"\n'
        '}'
    )
    
    add_custom_heading(doc, "5.2 What Happens When a Transaction Passes Validation?", level=2)
    add_bullet_p(doc, "Creates the Transaction record in the ledger with status=PENDING (block foreign key is NULL).")
    add_bullet_p(doc, "Creates a MempoolTransaction entry with status=ACTIVE, assigned to the receiving Node, with priority=gasPrice, arrivalTime=now, and expiresAt=now + 2 hours.")
    add_bullet_p(doc, "Returns HTTP 201 Created containing full transaction and mempool metadata.")
    
    add_code_block(
        doc,
        '# Successful Mempool Ingestion Response Example:\n'
        '{\n'
        '    "success": true,\n'
        '    "message": "Transaction validated and enqueued into mempool successfully.",\n'
        '    "data": {\n'
        '        "txHash": "9b12a8f0e34c5678910abcdef1234567890abcdef1234567890abcdef1234567",\n'
        '        "senderAddress": "0x3a4b9c1e7f82d05a91438b6d8e20f1a5c4e7b890",\n'
        '        "receiverAddress": "0x5e2a1b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a",\n'
        '        "amount": "5000000000",\n'
        '        "nonce": 0,\n'
        '        "gasLimit": 21000,\n'
        '        "gasPrice": "1",\n'
        '        "fee": 21000,\n'
        '        "status": "PENDING",\n'
        '        "mempoolStatus": "ACTIVE",\n'
        '        "nodeId": "myc-val-node-001",\n'
        '        "arrivalTime": "2026-11-20T07:45:00.000Z",\n'
        '        "expiresAt": "2026-11-20T09:45:00.000Z"\n'
        '    }\n'
        '}'
    )
    
    # =========================================================================
    # SECTION 6: MEMPOOL PROCESSOR & BLOCK PRODUCTION
    # =========================================================================
    doc.add_page_break()
    add_custom_heading(doc, "6. Mempool Processor & Block Generation Pipeline", level=1)
    add_body_p(
        doc,
        "Blocks are produced by the Mempool Processor service. It can run as a persistent background daemon "
        "(via python manage.py run_mempool_processor) or be triggered on-demand via management parameters."
    )
    
    add_custom_heading(doc, "6.1 Background Processing & Concurrency Protection", level=2)
    add_body_p(
        doc,
        "To ensure that multiple parallel processes or cluster nodes never mine conflicting blocks or double-spend transactions, "
        "the processor uses PostgreSQL transaction-level advisory locks:"
    )
    add_code_block(
        doc,
        '# Concurrency Control in ledger/services/mempool_processor.py:\n'
        'SELECT pg_try_advisory_xact_lock(1001001);\n'
        '# If another process is currently packaging a block, the lock fails gracefully\n'
        '# and the worker safely skips the cycle without deadlocks or race conditions.'
    )
    add_body_p(
        doc,
        "Expired Transaction Cleanup: In each processing cycle, any active mempool transaction whose expiresAt <= now "
        "is automatically updated to status=EXPIRED, and its ledger transaction is marked as DROPPED."
    )
    
    add_custom_heading(doc, "6.2 Batch Selection Algorithm (Stage 4)", level=2)
    add_bullet_p(doc, "1. Filters for MempoolTransaction.status == ACTIVE, unexpired, and Transaction.status == PENDING.")
    add_bullet_p(doc, "2. Groups candidates by sender address.")
    add_bullet_p(doc, "3. Prioritizes senders by highest gas price (priority ordering).")
    add_bullet_p(doc, "4. Enforces continuous nonce ordering: for any sender, transaction nonce N cannot be selected unless nonce N-1 has already been finalized or selected earlier in the same block.")
    add_bullet_p(doc, "5. Performs in-memory simulated balance deductions to ensure the sender has sufficient balance for amount + gas fee across all chained transactions.")
    add_bullet_p(doc, "6. Enforces cumulative block gas limits (sum of tx gas limits <= maxBlockGas).")
    
    # =========================================================================
    # SECTION 7: MERKLE ROOT & BLOCK HASH
    # =========================================================================
    doc.add_page_break()
    add_custom_heading(doc, "7. Merkle Root Construction & Block Hash Derivation", level=1)
    add_body_p(
        doc,
        "Every block header contains cryptographic commitments summarizing all transactions and state transitions inside that block. "
        "This allows lightweight clients to verify transaction inclusion without downloading the entire ledger."
    )
    
    add_custom_heading(doc, "7.1 Merkle Root Calculation (compute_merkle_root)", level=2)
    add_bullet_p(doc, "Leaf Nodes: The 64-character hexadecimal transaction hashes are converted into 32-byte binary representations.")
    add_bullet_p(doc, "Odd Leaf Duplication: If a level contains an odd number of nodes, the last node is duplicated to complete the final pair.")
    add_bullet_p(doc, "Pairwise Hashing: Consecutive pairs (left, right) are concatenated and hashed with SHA-256: combined = sha256(left + right).digest().")
    add_bullet_p(doc, "Tree Reduction: The process repeats recursively until a single 32-byte root remains, formatted as a 64-character lowercase hex string.")
    add_bullet_p(doc, "Empty Block Rule: If a block contains 0 transactions, the Merkle root is defined as hashlib.sha256(b'empty_block').hexdigest().")
    
    add_code_block(
        doc,
        '# Merkle Tree Implementation in ledger/services/block_producer.py:\n'
        'def compute_merkle_root(tx_hashes: List[str]) -> str:\n'
        '    if not tx_hashes:\n'
        '        return hashlib.sha256(b"empty_block").hexdigest().lower()\n\n'
        '    current_level = [bytes.fromhex(h) for h in tx_hashes]\n'
        '    while len(current_level) > 1:\n'
        '        if len(current_level) % 2 == 1:\n'
        '            current_level.append(current_level[-1])  # Duplicate last element\n'
        '        next_level = []\n'
        '        for i in range(0, len(current_level), 2):\n'
        '            combined = hashlib.sha256(current_level[i] + current_level[i + 1]).digest()\n'
        '            next_level.append(combined)\n'
        '        current_level = next_level\n\n'
        '    return current_level[0].hex().lower()'
    )
    
    add_custom_heading(doc, "7.2 State Root Placeholder (compute_state_root)", level=2)
    add_body_p(
        doc,
        "The state root commits to account balances after the block's execution. "
        "In the current prototype, it is derived deterministically from the parent state root, the block Merkle root, and the block height:"
    )
    add_code_block(
        doc,
        'state_root = hashlib.sha256(\n'
        '    f"{parent_state_root or \'0\'*64}:{merkle_root}:{block_height}".encode()\n'
        ').hexdigest().lower()'
    )
    
    add_custom_heading(doc, "7.3 Block Header Hash Generation (compute_block_hash)", level=2)
    add_code_block(
        doc,
        '# Block Hash Derivation:\n'
        'material = f"{chainId}:{height}:{previousHash}:{merkleRoot}:{stateRoot}:{timestampInt}:{roundNum}"\n'
        'block_hash = hashlib.sha256(material.encode("utf-8")).hexdigest().lower()\n\n'
        '# Properties:\n'
        '1. Deterministic: Recalculating with identical header facts yields the exact same hash.\n'
        '2. Tamper-Proof: Altering even 1 bit of a single transaction invalidates the Merkle root and block hash.\n'
        '3. Cryptographically Linked: Every block incorporates previousHash, forming an immutable chain.'
    )
    
    # =========================================================================
    # SECTION 8: CONSENSUS & ATOMIC FINALIZATION
    # =========================================================================
    doc.add_page_break()
    add_custom_heading(doc, "8. Consensus, Validation & Atomic Block Finalization", level=1)
    add_body_p(
        doc,
        "Once a block proposal is assembled, it must be independently validated, approved by consensus, and atomically executed."
    )
    
    add_custom_heading(doc, "8.1 Proposed Block Validation", level=2)
    add_bullet_p(doc, "Checks that block.parent exists and block.height == parent.height + 1.")
    add_bullet_p(doc, "Checks that block.previousHash matches parent.blockHash.")
    add_bullet_p(doc, "Checks proposer eligibility and active validator status.")
    add_bullet_p(doc, "Re-computes the Merkle root from the included transactions and asserts an exact match.")
    add_bullet_p(doc, "Verifies individual transaction cryptographic signatures, continuous nonces, and sender balances.")
    add_bullet_p(doc, "Verifies total block gas limits.")
    
    add_custom_heading(doc, "8.2 Atomic State Execution & Balance Settlement", level=2)
    add_body_p(doc, "All state transitions execute inside a single atomic database transaction (transaction.atomic()):")
    add_bullet_p(doc, "1. Sender Balance Deduction: The sender's balance is deducted by amount + fee (where fee = gasLimit * gasPrice).")
    add_bullet_p(doc, "2. Sender Nonce Increment: The sender's nonce is incremented by 1 (preventing replay).")
    add_bullet_p(doc, "3. Receiver Credit: The receiver is credited with amount. If the receiver does not exist on-chain, an EOA Account is created dynamically.")
    add_bullet_p(doc, "4. Validator Fee Reward: The proposer validator's account is credited with the transaction fee (feePaid).")
    add_bullet_p(doc, "5. Transaction Receipt Generation: An immutable TransactionReceipt is written with status=SUCCESS, gasUsed=gasLimit, and effectiveGasPrice=gasPrice.")
    add_bullet_p(doc, "6. Event Logs: Structured TransactionEvent records are emitted (TRANSFER and FEE_PAID).")
    add_bullet_p(doc, "7. Transaction Status: Updated to FINALIZED.")
    add_bullet_p(doc, "8. Block Finalization: Block status set to FINALIZED, finalizedAt recorded, and Blockchain.latestFinalizedBlock is advanced.")
    
    add_custom_heading(doc, "8.3 Mempool Reconciliation", level=2)
    add_bullet_p(doc, "Included transactions are updated to MempoolTransaction.status = INCLUDED.")
    add_bullet_p(doc, "Competing transactions from the same sender that shared the finalized nonce are evicted with status = REPLACED, and their ledger records marked DROPPED.")
    add_bullet_p(doc, "Stale transactions with lower nonces (nonce < sender.nonce) are marked EXPIRED and DROPPED.")
    
    # =========================================================================
    # SECTION 9: DATA MODELS & SCHEMA REFERENCE
    # =========================================================================
    doc.add_page_break()
    add_custom_heading(doc, "9. Data Models & Database Schema Reference", level=1)
    add_body_p(doc, "Below is the architectural reference for the primary models governing the MYCOIN ledger.")
    
    add_custom_heading(doc, "9.1 Block Model (ledger.Block)", level=2)
    add_styled_table(
        doc,
        headers=["Field Name", "Type", "Null / Blank", "Description & Constraints"],
        data_rows=[
            ["id", "UUIDField", "No / No", "Primary key (BaseModel)."],
            ["blockchain", "ForeignKey", "No / No", "Points to chain.Blockchain. Protected on delete."],
            ["height", "PositiveBigIntegerField", "No / No", "Sequential block height. Genesis = 0."],
            ["blockHash", "CharField(64)", "No / No", "Deterministic SHA-256 header hash. Unique per blockchain."],
            ["parent", "ForeignKey('self')", "Yes / Yes", "Link to preceding block. NULL only for Genesis."],
            ["previousHash", "CharField(64)", "No / No", "Parent block hash; 64 zeros for Genesis."],
            ["merkleRoot", "CharField(64)", "No / No", "Pairwise SHA-256 binary Merkle root of transactions."],
            ["stateRoot", "CharField(64)", "No / Yes", "Cryptographic state commitment placeholder."],
            ["timestamp", "DateTimeField", "No / No", "Slot timestamp when the block was created."],
            ["proposer", "ForeignKey", "Yes / Yes", "Points to staking.Validator. NULL only for Genesis."],
            ["status", "CharField(16)", "No / No", "Choices: PROPOSED, FINALIZED, REJECTED. Default: PROPOSED."],
            ["transactionCount", "PositiveIntegerField", "No / No", "Number of transactions contained in this block."],
            ["gasUsed", "BigIntegerField", "No / No", "Total gas consumed by transactions in this block."],
            ["blockReward", "BigIntegerField", "No / No", "Protocol block reward minted for the proposer."],
            ["finalizedAt", "DateTimeField", "Yes / Yes", "Timestamp when finality quorum was achieved."]
        ],
        col_widths=[1.5, 1.6, 1.1, 2.7]
    )
    
    add_custom_heading(doc, "9.2 Transaction Model (ledger.Transaction)", level=2)
    add_styled_table(
        doc,
        headers=["Field Name", "Type", "Null / Blank", "Description & Constraints"],
        data_rows=[
            ["id", "UUIDField", "No / No", "Primary key (BaseModel)."],
            ["hash", "CharField(64)", "No / No", "Deterministic SHA-256(canonical_digest + signature). Unique."],
            ["blockchain", "ForeignKey", "No / No", "Points to chain.Blockchain. Protected on delete."],
            ["sender", "ForeignKey", "No / No", "Sender on-chain Account (chain.Account). Protected on delete."],
            ["receiverAddress", "CharField(42)", "No / No", "Standard 42-character '0x' recipient address."],
            ["receiver", "ForeignKey", "Yes / Yes", "Filled at execution time when on-chain account is resolved."],
            ["txType", "CharField(16)", "No / No", "Choices: TRANSFER, REG_BONUS, STAKE, UNSTAKE."],
            ["amount", "BigIntegerField", "No / No", "Amount transferred in smallest base units (> 0)."],
            ["nonce", "BigIntegerField", "No / No", "Sender's sequential transaction nonce (>= 0)."],
            ["gasLimit", "BigIntegerField", "No / No", "Maximum gas units sender authorizes (>= 21,000)."],
            ["gasPrice", "BigIntegerField", "No / No", "Gas price offered in smallest units per gas."],
            ["feePaid", "BigIntegerField", "Yes / Yes", "Actual fee paid (gasUsed * gasPrice). Set at finalization."],
            ["signature", "CharField(200)", "No / Yes", "130-char hex ECDSA signature ('0x' + r + s)."],
            ["publicKey", "CharField(130)", "No / Yes", "130-char uncompressed ECDSA public key ('04' + x + y)."],
            ["status", "CharField(16)", "No / No", "Choices: PENDING, INCLUDED, FINALIZED, FAILED, REJECTED, DROPPED."],
            ["block", "ForeignKey", "Yes / Yes", "Block containing this transaction. NULL while PENDING."]
        ],
        col_widths=[1.5, 1.6, 1.1, 2.7]
    )
    
    add_custom_heading(doc, "9.3 Supporting Models Summary", level=2)
    add_bullet_p(doc, "Implements ordered, one-to-one mapping between a Block and Transaction (txIndex position). Immutable once block is finalized.", bold_prefix="BlockTransaction:")
    add_bullet_p(doc, "Tracks pending transaction admission on a specific network Node. Stores priority (gas price), arrivalTime, and expiresAt.", bold_prefix="MempoolTransaction:")
    add_bullet_p(doc, "Generated upon block finalization. Documents execution status (SUCCESS / FAILED), gasUsed, effectiveGasPrice, and resultMessage.", bold_prefix="TransactionReceipt:")
    add_bullet_p(doc, "Emits machine-readable structured JSON event logs (e.g. TRANSFER, FEE_PAID, ACCOUNT_CREATED) during block finalization.", bold_prefix="TransactionEvent:")
    add_bullet_p(doc, "Tracks finalized on-chain spendable balance and nonce for an address. Balance and nonce change ONLY upon block finalization.", bold_prefix="Account:")
    add_bullet_p(doc, "Off-chain cryptographic keypair container for user authentication, address ownership, and transaction signing.", bold_prefix="Wallet:")
    
    # =========================================================================
    # SECTION 10: PUBLIC BLOCKCHAIN APIS
    # =========================================================================
    doc.add_page_break()
    add_custom_heading(doc, "10. Public Blockchain APIs & Explorer Endpoints", level=1)
    add_body_p(
        doc,
        "MYCOIN exposes standard RESTful endpoints enabling anyone to inspect the blockchain, query blocks, "
        "inspect included transactions, check balances, and track network health."
    )
    
    add_custom_heading(doc, "10.1 List of Blocks (GET /api/ledger/blocks/)", level=2)
    add_body_p(doc, "Returns a paginated list of all blocks produced on the blockchain, ordered from newest to oldest (-height).")
    add_bullet_p(doc, "Endpoint: GET /api/ledger/blocks/?page=1&pageSize=10")
    add_bullet_p(doc, "Permission: AllowAny (Public Access)")
    
    add_code_block(
        doc,
        '# Sample Response: GET /api/ledger/blocks/\n'
        '{\n'
        '    "success": true,\n'
        '    "data": {\n'
        '        "blocksData": [\n'
        '            {\n'
        '                "id": "e8d7a123-b456-4c89-a012-3456789abcde",\n'
        '                "height": 2,\n'
        '                "blockHash": "f3b89012abcdef34567890abcdef1234567890abcdef1234567890abcdef1234",\n'
        '                "previousHash": "c2a78901abcdef234567890abcdef1234567890abcdef1234567890abcdef1234",\n'
        '                "merkleRoot": "a1b2c3d4e5f67890abcdef1234567890abcdef1234567890abcdef1234567890",\n'
        '                "stateRoot": "d4e5f6a1b2c37890abcdef1234567890abcdef1234567890abcdef1234567890",\n'
        '                "transactionCount": 1,\n'
        '                "gasUsed": 21000,\n'
        '                "blockReward": 0,\n'
        '                "status": "FINALIZED",\n'
        '                "timestamp": "2026-11-20T07:45:05.123Z",\n'
        '                "finalizedAt": "2026-11-20T07:45:05.250Z"\n'
        '            }\n'
        '        ],\n'
        '        "paginationData": {\n'
        '            "count": 3,\n'
        '            "totalPages": 1,\n'
        '            "currentPage": 1,\n'
        '            "pageSize": 10,\n'
        '            "next": null,\n'
        '            "previous": null\n'
        '        }\n'
        '    }\n'
        '}'
    )
    
    add_custom_heading(doc, "10.2 Block Transactions API (GET /api/ledger/blocks/<block_hash>/transactions/)", level=2)
    add_body_p(
        doc,
        "Returns complete header details for a specific block along with the full list of transactions included in that block, "
        "ordered by their txIndex position, including their execution receipts."
    )
    add_bullet_p(doc, "Endpoint: GET /api/ledger/blocks/{block_hash}/transactions/ (also alias GET /api/ledger/blocks/{block_hash}/)")
    add_bullet_p(doc, "Permission: AllowAny (Public Access)")
    
    add_code_block(
        doc,
        '# Sample Response: GET /api/ledger/blocks/{block_hash}/transactions/\n'
        '{\n'
        '    "success": true,\n'
        '    "data": {\n'
        '        "blockHash": "f3b89012abcdef34567890abcdef1234567890abcdef1234567890abcdef1234",\n'
        '        "blockHeight": 2,\n'
        '        "chainId": 1001,\n'
        '        "transactionCount": 1,\n'
        '        "transactions": [\n'
        '            {\n'
        '                "txHash": "9b12a8f0e34c5678910abcdef1234567890abcdef1234567890abcdef1234567",\n'
        '                "txIndex": 0,\n'
        '                "senderAddress": "0x3a4b9c1e7f82d05a91438b6d8e20f1a5c4e7b890",\n'
        '                "receiverAddress": "0x5e2a1b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a",\n'
        '                "txType": "TRANSFER",\n'
        '                "amount": "5000000000",\n'
        '                "nonce": 0,\n'
        '                "gasLimit": 21000,\n'
        '                "gasPrice": "1",\n'
        '                "feePaid": 21000,\n'
        '                "status": "FINALIZED",\n'
        '                "receiptStatus": "SUCCESS",\n'
        '                "gasUsed": 21000,\n'
        '                "createdAt": "2026-11-20T07:45:00.000Z"\n'
        '            }\n'
        '        ]\n'
        '    }\n'
        '}'
    )
    
    add_custom_heading(doc, "10.3 Single Transaction Detail API (GET /api/ledger/transactions/<tx_hash>/)", level=2)
    add_bullet_p(doc, "Inspects a single transaction by its 64-character hash. Returns execution status, gas used, fee paid, block inclusion height, and receipt outcome.")
    add_bullet_p(doc, "Endpoint: GET /api/ledger/transactions/{tx_hash}/")
    
    add_custom_heading(doc, "10.4 User Transaction History API (GET /api/ledger/transactions/)", level=2)
    add_bullet_p(doc, "Returns the paginated transaction history (both incoming and outgoing) across all wallets registered to the authenticated user.")
    add_bullet_p(doc, "Endpoint: GET /api/ledger/transactions/?page=1&pageSize=10&direction=all (Requires JWT Bearer token).")
    
    add_custom_heading(doc, "10.5 Account Balance & Nonce API (GET /api/ledger/balance/<address>/)", level=2)
    add_bullet_p(doc, "Queries real-time balance metrics for any on-chain address or for the authenticated user.")
    add_bullet_p(doc, "Endpoint: GET /api/ledger/balance/{address}/ (or GET /api/ledger/balance/ for logged-in user).")
    
    # =========================================================================
    # SECTION 11: SUMMARY TABLE
    # =========================================================================
    doc.add_page_break()
    add_custom_heading(doc, "11. Implementation Verification & Milestone Status", level=1)
    add_body_p(doc, "The table below outlines completed capabilities and the immediate roadmap for multi-node decentralized clustering.")
    
    add_styled_table(
        doc,
        headers=["Component / Milestone", "Implementation Status", "Verification Method"],
        data_rows=[
            ["Genesis Bootstrapping", "Completed & Verified", "POST /api/chain/genesis/ seeds supply and Block #0."],
            ["ECDSA Key Generation", "Completed & Verified", "SECP256k1 keypair & SHA-256 address derivation verified."],
            ["Keystore & Reg Bonus", "Completed & Verified", "Auto-grants 100 MYC from Treasury upon OTP verification."],
            ["Transaction Signing", "Completed & Verified", "Deterministic RFC 6979 canonical payload signing verified."],
            ["10-Step Node Validation", "Completed & Verified", "Evaluates sender, balance, nonces, signatures, and gas."],
            ["Mempool Queueing", "Completed & Verified", "Stores active transactions with gas price priority and expiry."],
            ["Mempool Processor", "Completed & Verified", "PostgreSQL advisory-locked batch selection and processor daemon."],
            ["Merkle Tree Calculation", "Completed & Verified", "Pairwise SHA-256 reduction with odd leaf duplication verified."],
            ["Block Hash Derivation", "Completed & Verified", "Canonical header hash links sequentially to parent block."],
            ["Atomic State Finalization", "Completed & Verified", "ACID database updates: balances, nonces, receipts, and events."],
            ["Public Explorer APIs", "Completed & Verified", "Paginated block and transaction inspection endpoints verified."],
            ["P2P Network Gossip", "Planned (Phase 2)", "Real-time transaction broadcasting across distributed peer nodes."],
            ["Multi-Node PoS Voting", "Planned (Phase 2)", "2/3 voting power quorum collection before block finalization."]
        ],
        col_widths=[1.8, 1.8, 3.3]
    )
    
    add_callout(
        doc,
        "Documentation Complete: This document reflects the exact models, services, views, and algorithms currently implemented "
        "and running in the MYCOIN codebase.",
        title="DOCUMENT STATUS"
    )
    
    # Save both files
    file_1 = os.path.abspath("MYCOIN_Architecture_and_Flow_Documentation.docx")
    file_2 = os.path.abspath("MYCOIN_Documentation.docx")
    
    doc.save(file_1)
    doc.save(file_2)
    
    print(f"Generated Word Document 1: {file_1} ({os.path.getsize(file_1):,} bytes)")
    print(f"Generated Word Document 2: {file_2} ({os.path.getsize(file_2):,} bytes)")

if __name__ == "__main__":
    generate_mycoin_word_document()
