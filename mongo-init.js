// MongoDB Initialization Script
// Runs automatically on first container start
// Creates the gem_tender database with indexes

db = db.getSiblingDB('gem_tender');

// Create application user (separate from root)
db.createUser({
  user: 'gem_app',
  pwd: process.env.MONGO_APP_PASS || 'GemApp@2024',
  roles: [{ role: 'readWrite', db: 'gem_tender' }]
});

// Audit logs collection with TTL (auto-delete logs after 365 days)
db.createCollection('audit_logs');
db.audit_logs.createIndex({ "timestamp": 1 }, { expireAfterSeconds: 31536000 });
db.audit_logs.createIndex({ "user_id": 1 });
db.audit_logs.createIndex({ "action": 1 });

// RAG document chunks collection
db.createCollection('rag_chunks');
db.rag_chunks.createIndex({ "tender_id": 1 });
db.rag_chunks.createIndex({ "embedding_hash": 1 });

// LLM conversation logs
db.createCollection('llm_logs');
db.llm_logs.createIndex({ "created_at": 1 }, { expireAfterSeconds: 604800 }); // 7 days

print('MongoDB gem_tender database initialized successfully.');
