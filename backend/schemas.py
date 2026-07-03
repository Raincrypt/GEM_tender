from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr


# ---- Auth ----
class Token(BaseModel):
    access_token: str
    token_type: str
    user: dict

class LoginRequest(BaseModel):
    username: str
    password: str


# ---- User ----
class UserCreate(BaseModel):
    username: str
    email: str
    full_name: str
    password: str
    role: str = "Viewer"

class UserOut(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True


# ---- Vendor ----
class VendorCreate(BaseModel):
    gem_reg_no: str
    company_name: str
    contact_person: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    category: Optional[str] = None
    msme: bool = False
    startup: bool = False
    make_in_india: bool = False

class VendorUpdate(VendorCreate):
    pass

class VendorOut(VendorCreate):
    id: int
    performance_score: float
    is_blacklisted: bool
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True


# ---- Criteria ----
class CriteriaCreate(BaseModel):
    name: str
    description: Optional[str] = None
    criteria_type: str
    weight: float
    max_score: float = 100.0

class CriteriaOut(CriteriaCreate):
    id: int
    tender_id: int
    class Config:
        from_attributes = True


# ---- Tender ----
class TenderCreate(BaseModel):
    bid_number: str
    title: str
    department: Optional[str] = None
    ministry: Optional[str] = None
    category: Optional[str] = None
    estimated_value: Optional[float] = None
    emd_amount: Optional[float] = None
    bid_validity: Optional[int] = None
    delivery_period: Optional[int] = None
    technical_weightage: float = 70.0
    financial_weightage: float = 30.0
    description: Optional[str] = None
    closing_date: Optional[datetime] = None

class TenderUpdate(TenderCreate):
    status: Optional[str] = None

class TenderOut(TenderCreate):
    id: int
    status: str
    published_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    bid_count: Optional[int] = 0
    class Config:
        from_attributes = True


# ---- Bid ----
class BidCreate(BaseModel):
    tender_id: int
    vendor_id: int
    bid_amount: float
    taxes: float = 0.0
    delivery_period: Optional[int] = None

class BidScoreInput(BaseModel):
    criteria_id: int
    score: float
    remarks: Optional[str] = None

class BidDocumentOut(BaseModel):
    id: int
    document_type: Optional[str] = None
    ocr_extracted_text: Optional[str] = None
    verified: bool
    uploaded_at: Optional[datetime] = None
    esg_score: Optional[float] = None
    esg_highlights: Optional[str] = None
    class Config:
        from_attributes = True

class BidEvaluationInput(BaseModel):
    bid_id: int
    scores: List[BidScoreInput]
    is_disqualified: bool = False
    disqualification_reason: Optional[str] = None

class BidOut(BaseModel):
    id: int
    tender_id: int
    vendor_id: int
    bid_amount: float
    taxes: float
    total_amount: Optional[float] = None
    delivery_period: Optional[int] = None
    technical_score: float
    financial_score: float
    composite_score: float
    composite_esg_score: Optional[float] = None
    rank: Optional[int] = None
    is_disqualified: bool
    disqualification_reason: Optional[str] = None
    status: str
    submitted_at: Optional[datetime] = None
    vendor: Optional[VendorOut] = None
    documents: Optional[List[BidDocumentOut]] = []
    class Config:
        from_attributes = True


# ---- Dashboard ----
class DashboardStats(BaseModel):
    total_tenders: int
    active_tenders: int
    total_bids: int
    total_vendors: int
    avg_bid_score: float
    pending_evaluations: int
    awarded_tenders: int
    cancelled_tenders: int


# ---- AI Audit ----
class AIDecisionLogCreate(BaseModel):
    bid_id: int
    criteria_id: Optional[int] = None
    tender_id: int
    ai_score: float
    ai_confidence: float = 0.0
    ai_rationale: Optional[str] = None
    ai_model_version: str = "v3.0"
    context_snapshot: Optional[str] = None

class AIFeedbackSubmit(BaseModel):
    human_score: float
    human_action: str  # accepted / rejected / modified
    feedback_rating: Optional[int] = None  # 1-5
    feedback_comment: Optional[str] = None

class AIAccuracyReport(BaseModel):
    total_decisions: int
    resolved_decisions: int
    acceptance_rate: float
    rejection_rate: float
    modification_rate: float
    accepted: int = 0
    rejected: int = 0
    modified: int = 0
    avg_deviation: Optional[float] = None
    avg_confidence: float
    avg_feedback_rating: Optional[float] = None
    per_criteria_accuracy: List[dict]
    accuracy_trend: List[dict]
    confidence_calibration: List[dict]

class AIDecisionLogOut(BaseModel):
    id: int
    bid_id: int
    criteria_id: Optional[int] = None
    tender_id: int
    user_id: Optional[int] = None
    ai_score: float
    ai_confidence: float
    ai_rationale: Optional[str] = None
    ai_model_version: Optional[str] = None
    human_score: Optional[float] = None
    human_action: Optional[str] = None
    deviation: Optional[float] = None
    feedback_rating: Optional[int] = None
    feedback_comment: Optional[str] = None
    context_snapshot: Optional[str] = None
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    class Config:
        from_attributes = True


# ---- Disputes ----
class DisputeCreate(BaseModel):
    po_id: int
    vendor_id: int
    dispute_type: str = "LD Penalty"
    disputed_amount: float
    vendor_statement: str
    meteorological_context: Optional[str] = None
    evidence_links: Optional[str] = "[]"

class DisputeOut(BaseModel):
    id: int
    po_id: int
    vendor_id: int
    case_number: str
    dispute_type: str
    disputed_amount: float
    vendor_statement: str
    meteorological_context: Optional[str] = None
    evidence_links: Optional[str] = "[]"
    status: str
    arbitrator_ruling: Optional[str] = None
    refund_percentage: float
    ruling_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class DisputeResolveResult(BaseModel):
    refund_percentage: float
    arbitrator_ruling: str


# ---- Notifications ----
class NotificationOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    title: str
    message: str
    severity: str
    is_read: bool
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

