import sys
sys.path.append("backend")
import database
import models
import auth
import traceback

try:
    print("Database collections:")
    print(database.mongo_db.list_collection_names())
    
    # Query user
    db = database.SessionLocal()
    user = db.query(models.User).filter(models.User.username == "admin").first()
    print("User queried:", user)
    if user:
        print("User dict:", user.to_dict())
        # Check password hashing
        pwd = "admin123"
        print("Hashed password in DB:", user.hashed_password)
        # Verify password directly
        verified = auth.pwd_context.verify(pwd, user.hashed_password)
        print("Verify password result:", verified)
    else:
        print("User 'admin' not found in database!")
except Exception as e:
    print("Error during direct auth test:")
    traceback.print_exc()
