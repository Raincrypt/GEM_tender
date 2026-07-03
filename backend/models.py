from database import Base, Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean, Enum, relationship, func
import enum


class TenderStatus(str, enum.Enum):
    DRAFT = "Draft"
    PUBLISHED = "Published"
    UNDER_EVALUATION = "Under Evaluation"
    AWARDED = "Awarded"
    CLOSED = "Closed"
    CANCELLED = "Cancelled"


class UserRole(str, enum.Enum):
    ADMIN = "Admin"
    EVALUATOR = "Evaluator"
    VIEWER = "Viewer"
    VENDOR = "Vendor"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(200), unique=True, nullable=False)
    full_name = Column(String(200))
    hashed_password = Column(String(300), nullable=False)
    role = Column(String(50), default=UserRole.VIEWER)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Vendor(Base):
    __tablename__ = "vendors"
    id = Column(Integer, primary_key=True, index=True)
    gem_reg_no = Column(String(100), unique=True, nullable=False)
    company_name = Column(String(300), nullable=False)
    contact_person = Column(String(200))
    email = Column(String(200))
    phone = Column(String(20))
    address = Column(Text)
    category = Column(String(200))
    msme = Column(Boolean, default=False)
    startup = Column(Boolean, default=False)
    make_in_india = Column(Boolean, default=False)
    performance_score = Column(Float, default=0.0)
    is_blacklisted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    @property
    def bids(self):
        from database import db
        import models
        cursor = db["bids"].find({"vendor_id": self.id})
        return [models.Bid(**doc) for doc in cursor]


class Tender(Base):
    __tablename__ = "tenders"
    id = Column(Integer, primary_key=True, index=True)
    bid_number = Column(String(100), unique=True, nullable=False)
    title = Column(String(500), nullable=False)
    department = Column(String(300))
    ministry = Column(String(300))
    category = Column(String(200))
    estimated_value = Column(Float)
    emd_amount = Column(Float)
    bid_validity = Column(Integer)  # days
    delivery_period = Column(Integer)  # days
    technical_weightage = Column(Float, default=70.0)
    financial_weightage = Column(Float, default=30.0)
    technical_threshold = Column(Float, default=70.0) # Min score required to open financial bid
    is_financial_opened = Column(Boolean, default=False) # Two-Packet system lock
    is_auction_active = Column(Boolean, default=False) # Reverse Auction
    auction_end_time = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), default=TenderStatus.DRAFT, index=True)
    description = Column(Text)
    published_date = Column(DateTime(timezone=True))
    closing_date = Column(DateTime(timezone=True), index=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    @property
    def bids(self):
        from database import db
        import models
        cursor = db["bids"].find({"tender_id": self.id})
        return [models.Bid(**doc) for doc in cursor]

    @property
    def criteria(self):
        from database import db
        import models
        cursor = db["evaluation_criteria"].find({"tender_id": self.id})
        return [models.EvaluationCriteria(**doc) for doc in cursor]


class EvaluationCriteria(Base):
    __tablename__ = "evaluation_criteria"
    id = Column(Integer, primary_key=True, index=True)
    tender_id = Column(Integer, ForeignKey("tenders.id"), nullable=False)
    name = Column(String(300), nullable=False)
    description = Column(Text)
    criteria_type = Column(String(50))  # Technical / Financial
    weight = Column(Float, nullable=False)
    max_score = Column(Float, default=100.0)

    @property
    def tender(self):
        from database import db
        import models
        doc = db["tenders"].find_one({"id": self.tender_id})
        return models.Tender(**doc) if doc else None

    @property
    def scores(self):
        from database import db
        import models
        cursor = db["bid_scores"].find({"criteria_id": self.id})
        return [models.BidScore(**doc) for doc in cursor]


class Bid(Base):
    __tablename__ = "bids"
    id = Column(Integer, primary_key=True, index=True)
    tender_id = Column(Integer, ForeignKey("tenders.id"), index=True, nullable=False)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), index=True, nullable=False)
    bid_amount = Column(Float, nullable=False)
    taxes = Column(Float, default=0.0)
    total_amount = Column(Float)
    delivery_period = Column(Integer)
    technical_score = Column(Float, default=0.0)
    financial_score = Column(Float, default=0.0)
    composite_score = Column(Float, default=0.0)
    composite_esg_score = Column(Float, default=0.0)
    rank = Column(Integer)
    is_disqualified = Column(Boolean, default=False)
    disqualification_reason = Column(Text)
    status = Column(String(50), default="Submitted", index=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    evaluated_at = Column(DateTime(timezone=True))

    @property
    def tender(self):
        from database import db
        import models
        doc = db["tenders"].find_one({"id": self.tender_id})
        return models.Tender(**doc) if doc else None

    @property
    def vendor(self):
        from database import db
        import models
        doc = db["vendors"].find_one({"id": self.vendor_id})
        return models.Vendor(**doc) if doc else None

    @property
    def scores(self):
        from database import db
        import models
        cursor = db["bid_scores"].find({"bid_id": self.id})
        return [models.BidScore(**doc) for doc in cursor]

    @property
    def documents(self):
        from database import db
        import models
        cursor = db["bid_documents"].find({"bid_id": self.id})
        return [models.BidDocument(**doc) for doc in cursor]


class BidScore(Base):
    __tablename__ = "bid_scores"
    id = Column(Integer, primary_key=True, index=True)
    bid_id = Column(Integer, ForeignKey("bids.id"), index=True, nullable=False)
    criteria_id = Column(Integer, ForeignKey("evaluation_criteria.id"), index=True, nullable=False)
    score = Column(Float, default=0.0)
    remarks = Column(Text)
    evaluated_by = Column(Integer, ForeignKey("users.id"))
    evaluated_at = Column(DateTime(timezone=True), server_default=func.now())

    @property
    def bid(self):
        from database import db
        import models
        doc = db["bids"].find_one({"id": self.bid_id})
        return models.Bid(**doc) if doc else None

    @property
    def criteria(self):
        from database import db
        import models
        doc = db["evaluation_criteria"].find_one({"id": self.criteria_id})
        return models.EvaluationCriteria(**doc) if doc else None


class BidDocument(Base):
    __tablename__ = "bid_documents"
    id = Column(Integer, primary_key=True, index=True)
    bid_id = Column(Integer, ForeignKey("bids.id"), index=True, nullable=False)
    document_type = Column(String(100)) # e.g. "GST Certificate", "MSME Certificate"
    file_path = Column(String(500))
    ocr_extracted_text = Column(Text)
    verified = Column(Boolean, default=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    esg_score = Column(Float, default=0.0)
    esg_highlights = Column(String(1000), default="[]")

    @property
    def bid(self):
        from database import db
        import models
        doc = db["bids"].find_one({"id": self.bid_id})
        return models.Bid(**doc) if doc else None


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String(200), index=True)
    entity_type = Column(String(100))
    entity_id = Column(Integer, index=True)
    details = Column(Text)
    ip_address = Column(String(50))
    timestamp = Column(DateTime(timezone=True), index=True, server_default=func.now())
    # Blockchain / Anti-Tampering fields
    previous_hash = Column(String(64), nullable=True)
    current_hash = Column(String(64), nullable=True)


# =============================================
# IOCL PROCUREMENT LIFECYCLE MODELS
# =============================================

class IndentStatus(str, enum.Enum):
    DRAFT = "Draft"
    SUBMITTED = "Submitted"
    APPROVED = "Approved"
    CONVERTED = "Converted to Tender"
    REJECTED = "Rejected"


class IndentUrgency(str, enum.Enum):
    ROUTINE = "Routine"
    URGENT = "Urgent"
    EMERGENCY = "Emergency"


class Indent(Base):
    """IOCL Stage 1: Material Indent / Purchase Requisition"""
    __tablename__ = "indents"
    id = Column(Integer, primary_key=True, index=True)
    indent_number = Column(String(100), unique=True, nullable=False)  # IOCL/PR/2026/001
    sap_pr_number = Column(String(50), nullable=True)  # SAP MM PR Number
    material_code = Column(String(50), nullable=False)  # SAP Material Code
    material_description = Column(String(500), nullable=False)
    quantity = Column(Float, nullable=False)
    unit_of_measurement = Column(String(20), default="NOS")  # NOS, KG, LTR, MT, KL
    estimated_unit_rate = Column(Float, default=0.0)
    estimated_total_value = Column(Float, default=0.0)
    budget_head = Column(String(200))  # Capital / Revenue
    cost_center = Column(String(100))  # IOCL Cost Center code
    plant_code = Column(String(50))  # Refinery / Pipeline / Marketing
    indenting_department = Column(String(200))
    indenting_officer = Column(String(200))
    technical_specification = Column(Text)  # SOR / SOW
    justification = Column(Text)  # Why is this procurement needed
    urgency = Column(String(20), default=IndentUrgency.ROUTINE)
    status = Column(String(30), default=IndentStatus.DRAFT)
    approved_by = Column(String(200), nullable=True)
    approval_date = Column(DateTime(timezone=True), nullable=True)
    tender_id = Column(Integer, ForeignKey("tenders.id"), nullable=True)  # Link after conversion
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PurchaseOrder(Base):
    """IOCL Stage 7: Purchase Order Generation"""
    __tablename__ = "purchase_orders"
    id = Column(Integer, primary_key=True, index=True)
    po_number = Column(String(100), unique=True, nullable=False)  # IOCL/PO/2026/001
    sap_po_number = Column(String(50), nullable=True)
    tender_id = Column(Integer, ForeignKey("tenders.id"), nullable=False)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    bid_id = Column(Integer, ForeignKey("bids.id"), nullable=False)
    po_value = Column(Float, nullable=False)
    taxes_amount = Column(Float, default=0.0)
    total_po_value = Column(Float, nullable=False)
    delivery_address = Column(Text)
    inspection_clause = Column(String(200), default="IOCL Standard Inspection")
    payment_terms = Column(String(200), default="30 Days from Invoice")
    ld_clause = Column(String(500), default="0.5% per week, max 5%")
    warranty_period = Column(Integer, default=12)  # months
    is_accepted_by_vendor = Column(Boolean, default=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), default="Issued")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DeliveryRecord(Base):
    """IOCL Stage 8: Delivery & Inspection"""
    __tablename__ = "delivery_records"
    id = Column(Integer, primary_key=True, index=True)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    grn_number = Column(String(100))  # Goods Receipt Note
    delivery_date = Column(DateTime(timezone=True))
    received_quantity = Column(Float)
    inspection_status = Column(String(50), default="Pending")  # Pending / Passed / Failed
    tpi_required = Column(Boolean, default=False)
    tpi_report_uploaded = Column(Boolean, default=False)
    quality_remarks = Column(Text)
    mrn_number = Column(String(100))  # Material Receipt Note
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PaymentRecord(Base):
    """IOCL Stage 9: Payment Processing"""
    __tablename__ = "payment_records"
    id = Column(Integer, primary_key=True, index=True)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    invoice_number = Column(String(100))
    invoice_amount = Column(Float)
    tds_deduction = Column(Float, default=0.0)  # Section 194C
    ld_deduction = Column(Float, default=0.0)
    net_payable = Column(Float)
    three_way_match = Column(Boolean, default=False)  # PO vs GRN vs Invoice
    payment_status = Column(String(50), default="Pending")  # Pending / Released / Held
    payment_date = Column(DateTime(timezone=True), nullable=True)
    utr_number = Column(String(100), nullable=True)  # Bank UTR
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AIDecisionLog(Base):
    """Tracks AI recommendations vs human decisions for accuracy measurement"""
    __tablename__ = "ai_decision_logs"
    id = Column(Integer, primary_key=True, index=True)
    bid_id = Column(Integer, ForeignKey("bids.id"), index=True, nullable=False)
    criteria_id = Column(Integer, ForeignKey("evaluation_criteria.id"), index=True, nullable=True)
    tender_id = Column(Integer, ForeignKey("tenders.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    ai_score = Column(Float, nullable=False)
    ai_confidence = Column(Float, default=0.0)
    ai_rationale = Column(Text)
    ai_model_version = Column(String(50), default="v3.0")
    human_score = Column(Float, nullable=True)  # filled when evaluator acts
    human_action = Column(String(20), nullable=True)  # accepted / rejected / modified
    deviation = Column(Float, nullable=True)  # abs(ai_score - human_score)
    feedback_rating = Column(Integer, nullable=True)  # 1-5 rating from evaluator
    feedback_comment = Column(Text, nullable=True)
    context_snapshot = Column(Text, nullable=True)  # JSON snapshot of data used
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class DisputeCase(Base):
    __tablename__ = "dispute_cases"
    id = Column(Integer, primary_key=True, index=True)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), index=True, nullable=False)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), index=True, nullable=False)
    case_number = Column(String(100), unique=True, nullable=False) # e.g. ARB-2026-001
    dispute_type = Column(String(100), default="LD Penalty") # e.g. "LD Penalty", "Payment Delay", "Scope Change"
    disputed_amount = Column(Float, default=0.0)
    vendor_statement = Column(Text, nullable=False)
    meteorological_context = Column(Text, nullable=True) # weather reports, monsoon, flood data
    evidence_links = Column(String(1000), default="[]") # JSON list of links or titles
    status = Column(String(50), default="Open") # Open / Under Hearing / Resolved
    arbitrator_ruling = Column(Text, nullable=True)
    refund_percentage = Column(Float, default=0.0) # refund of penalties (0 to 100)
    ruling_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    @property
    def po(self):
        from database import db
        import models
        doc = db["purchase_orders"].find_one({"id": self.po_id})
        return models.PurchaseOrder(**doc) if doc else None

    @property
    def vendor(self):
        from database import db
        import models
        doc = db["vendors"].find_one({"id": self.vendor_id})
        return models.Vendor(**doc) if doc else None


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    severity = Column(String(50), default="info")
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


