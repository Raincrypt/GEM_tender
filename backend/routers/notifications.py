from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
import models, schemas, auth
from database import get_db

router = APIRouter(prefix="/notifications", tags=["Notifications"])

@router.get("/", response_model=List[schemas.NotificationOut])
def get_notifications(db: Session = Depends(get_db), current_user = Depends(auth.get_current_user)):
    """Fetch notifications for current user, including global ones (user_id is Null/None)."""
    return db.query(models.Notification).filter(
        (models.Notification.user_id == current_user.id) | (models.Notification.user_id == None)
    ).order_by(models.Notification.created_at.desc()).all()

@router.get("/unread-count")
def get_unread_count(db: Session = Depends(get_db), current_user = Depends(auth.get_current_user)):
    """Get unread notifications count."""
    count = db.query(models.Notification).filter(
        ((models.Notification.user_id == current_user.id) | (models.Notification.user_id == None)) &
        (models.Notification.is_read == False)
    ).count()
    return {"count": count}

@router.post("/read/{notification_id}")
def mark_read(notification_id: int, db: Session = Depends(get_db), current_user = Depends(auth.get_current_user)):
    """Mark a notification as read."""
    notif = db.query(models.Notification).filter(models.Notification.id == notification_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notif.user_id and notif.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    notif.is_read = True
    db.commit()
    return {"message": "Notification marked as read"}

@router.post("/read-all")
def mark_all_read(db: Session = Depends(get_db), current_user = Depends(auth.get_current_user)):
    """Mark all notifications for the user as read."""
    notifs = db.query(models.Notification).filter(
        ((models.Notification.user_id == current_user.id) | (models.Notification.user_id == None)) &
        (models.Notification.is_read == False)
    ).all()
    for notif in notifs:
        notif.is_read = True
    db.commit()
    return {"message": f"Marked {len(notifs)} notifications as read"}

@router.post("/create-alert")
def create_notification(
    title: str,
    message: str,
    severity: str = "info",
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user = Depends(auth.require_role("Admin"))
):
    """Admin-only: Create a notification alert."""
    notif = models.Notification(
        user_id=user_id,
        title=title,
        message=message,
        severity=severity,
        is_read=False
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif
