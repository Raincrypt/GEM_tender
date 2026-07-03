# GEM Ecosystem Data Flow Diagrams (DFD)

Here is the complete data flow mapping for the GEM Tender Procurement Ecosystem.

## Level 0 Context Diagram
This diagram shows how external entities (Vendors, Indenting Officers, Finance, and AI Oracles) interact with the core GEM System.

```mermaid
graph TD
    %% External Entities
    Vendor([Vendors])
    IndentingOfficer([Indenting Officer])
    FinanceDept([Finance & PAC])
    AIOracle([External Market Oracle])
    SAP([SAP MM / FICO Module])

    %% Main System
    System(((GEM Tender\nEcosystem)))

    %% Data Flows
    Vendor -- Biometrics, Bids, Documents --> System
    System -- Tender Alerts, POs, Legal Notices --> Vendor
    
    IndentingOfficer -- Material Indents (PR) --> System
    System -- Approved NITs, Delivery Updates --> IndentingOfficer
    
    FinanceDept -- DoP Approval, Payment Auth --> System
    System -- MOM Hash, Audit Logs, Invoices --> FinanceDept
    
    System -- Price Queries --> AIOracle
    AIOracle -- Market Predictions --> System
    
    System -- PO Data, GRN, Invoices --> SAP
    SAP -- SAP PR, SAP PO Numbers --> System
```

---

## Level 1 Data Flow Diagram
This details the internal microservices, specific data transformations, and storage systems across the 9-stage IOCL pipeline.

```mermaid
graph TD
    %% Data Stores
    DB_Tender[(Tenders & Indents DB)]
    DB_Vendor[(Vendor Profiles & KYC DB)]
    DB_Bids[(Encrypted Bid Vault)]
    DB_Ledger[(Blockchain Ledger)]
    DB_Finance[(PO & Payments DB)]

    %% External Entities
    E_Vendor([Vendor])
    E_Officer([Indenting Dept])

    %% Processes (Stages)
    P1(1. Indent & NIT Generator)
    P2(2. Deepfake KYC Engine)
    P3(3. Secure Bid Vault)
    P4(4. AI Semantic Evaluation)
    P5(5. QCBS & Autopilot)
    P6(6. PAC Digital Meeting)
    P7(7. SAP PO & Delivery)
    P8(8. AI Arbitration Court)
    P9(9. 3-Way Match & Payment)

    %% Flow: Indent to NIT
    E_Officer -- PR Details --> P1
    P1 -- Read/Write --> DB_Tender
    P1 -- Published NIT --> E_Vendor

    %% Flow: Vendor KYC
    E_Vendor -- Webcam Stream --> P2
    P2 -- Liveness Score --> DB_Vendor

    %% Flow: Bidding
    E_Vendor -- Encrypted Bid & Docs --> P3
    P3 -- Store Sealed Bid --> DB_Bids

    %% Flow: Evaluation
    P3 -- Unlock Bids --> P4
    P4 -- Extract Text / NLP Rules --> DB_Tender
    P4 -- Pass/Fail Status --> P5

    %% Flow: Autopilot & Award
    P5 -- Calculate Composite Score --> DB_Bids
    P5 -- Rank L1 Vendor --> P6

    %% Flow: PAC & Blockchain
    P6 -- DoP Verification --> DB_Tender
    P6 -- Immutable Award Record --> DB_Ledger

    %% Flow: Delivery & Arbitration
    P6 -- Trigger Award --> P7
    P7 -- Store GRN/MRN --> DB_Finance
    P7 -- Failed MRN --> P8
    P8 -- Read LD Clause --> DB_Finance
    P8 -- Blacklist Status --> DB_Vendor
    P8 -- Send Legal Penalty --> E_Vendor

    %% Flow: Payment
    P7 -- Verified Invoice --> P9
    P9 -- Deduct 194C TDS --> DB_Finance
    P9 -- Release Escrow --> E_Vendor
```

## Explanation of Key Flows:
1. **The Indent Flow (`P1`):** An officer submits a requirement. The system writes it to `DB_Tender` and auto-publishes an NIT.
2. **The Security Flow (`P2`, `P3`):** Vendors must pass `P2` (Deepfake Biometrics). Approved vendors push AES-encrypted data to `P3` (Bid Vault).
3. **The Brain (`P4`, `P5`):** The AI NLP Engine evaluates the technical documents. The Autopilot handles QCBS math to determine the financial winner.
4. **The Closure Flow (`P7`, `P8`, `P9`):** Goods are received in `P7`. If defective, `P8` (Arbitration) automatically penalizes the vendor in `DB_Vendor`. If successful, `P9` calculates taxes and finalizes the ledger.
