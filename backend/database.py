import os
import time
import logging
import re
import datetime
import sys
import functools
from types import ModuleType
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

logger = logging.getLogger("gem.database")

# ──────────────────────────────────────────────────────────────────────────────
#  MONGODB CONNECTION
# ──────────────────────────────────────────────────────────────────────────────
MONGO_URL = os.getenv("MONGO_URL", "mongodb://127.0.0.1:27017")

def _create_mongo_client(url: str, max_retries: int = 3, retry_delay: float = 2.0) -> MongoClient:
    import urllib.parse
    from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError, OperationFailure
    
    def quote_url(u: str) -> str:
        if not u.startswith("mongodb://") and not u.startswith("mongodb+srv://"):
            return u
        prefix = "mongodb://" if u.startswith("mongodb://") else "mongodb+srv://"
        rest = u[len(prefix):]
        if "@" not in rest:
            return u
        parts = rest.rsplit("@", 1)
        creds, hosts_options = parts[0], parts[1]
        if ":" not in creds:
            return f"{prefix}{urllib.parse.quote_plus(creds)}@{hosts_options}"
        user, password = creds.split(":", 1)
        if "%" not in password:
            password = urllib.parse.quote_plus(password)
        if "%" not in user:
            user = urllib.parse.quote_plus(user)
        return f"{prefix}{user}:{password}@{hosts_options}"

    def clean_url(u: str) -> str:
        return re.sub(r'mongodb://[^@]+@', 'mongodb://', u)

    # Auto-quote credentials in the provided url
    url = quote_url(url)
    
    # Establish URLs to try sequentially
    urls_to_try = [url]
    if "CHANGE_ME_MONGO_PASSWORD" in url:
        alt_url = url.replace("CHANGE_ME_MONGO_PASSWORD", urllib.parse.quote_plus("GemMongo@2024Secure"))
        urls_to_try.append(alt_url)
    
    fallback_url = clean_url(url)
    if fallback_url not in urls_to_try:
        urls_to_try.append(fallback_url)

    for current_url in urls_to_try:
        for attempt in range(1, max_retries + 1):
            try:
                client = MongoClient(
                    current_url,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                    socketTimeoutMS=10000,
                    maxPoolSize=100,
                    minPoolSize=10,
                    maxIdleTimeMS=30000,
                    waitQueueTimeoutMS=5000,
                    retryWrites=True,
                )
                client.admin.command("ping")
                logger.info(f"[database] MongoDB connected on attempt {attempt}: {clean_url(current_url)}")
                return client
            except OperationFailure as e:
                logger.warning(f"[database] MongoDB authentication failed with URL: {clean_url(current_url)} | Error: {e}")
                break  # Stop retrying this URL, advance to the next fallback URL configuration
            except (ConnectionFailure, ServerSelectionTimeoutError) as e:
                logger.warning(f"[database] MongoDB connection attempt {attempt}/{max_retries} failed for {clean_url(current_url)}: {e}")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                else:
                    break  # Try the next fallback URL configuration

    logger.error("[database] All MongoDB connection attempts failed. Running in degraded mode.")
    return MongoClient(
        clean_url(url),
        serverSelectionTimeoutMS=1000,
        maxPoolSize=100,
        minPoolSize=10,
        maxIdleTimeMS=30000,
        waitQueueTimeoutMS=5000
    )

mongo_client = _create_mongo_client(MONGO_URL)
mongo_db = mongo_client["gem_tender"]
db = mongo_db  # Export db directly
engine = None  # Mock engine for legacy SQL imports/setups

# ──────────────────────────────────────────────────────────────────────────────
#  SQLACHEMY COMPATIBILITY LAYER FOR MONGODB
# ──────────────────────────────────────────────────────────────────────────────

class MongoExpression:
    def __init__(self, op, left, right=None):
        self.op = op
        self.left = left
        self.right = right

    def __or__(self, other):
        if not isinstance(other, MongoExpression):
            return self
        return MongoExpression("or", [self, other])

    def __and__(self, other):
        if not isinstance(other, MongoExpression):
            return self
        return MongoExpression("and", [self, other])

class SortSpec:
    def __init__(self, field_name, direction, model_class=None):
        self.field_name = field_name
        self.direction = direction
        self.model_class = model_class

class FieldSelector:
    def __init__(self, name):
        self.name = name
        self.model_class = None
        self._label = None

    def label(self, name):
        self._label = name
        return self

    def __eq__(self, other):
        return MongoExpression("eq", self, other)

    def __ne__(self, other):
        return MongoExpression("ne", self, other)

    def __gt__(self, other):
        return MongoExpression("gt", self, other)

    def __ge__(self, other):
        return MongoExpression("gte", self, other)

    def __lt__(self, other):
        return MongoExpression("lt", self, other)

    def __le__(self, other):
        return MongoExpression("lte", self, other)

    def is_(self, other):
        return MongoExpression("eq", self, other)

    def is_not(self, other):
        return MongoExpression("ne", self, other)

    def ilike(self, other):
        return MongoExpression("ilike", self, other)

    def in_(self, other):
        return MongoExpression("in", self, other)

    def contains(self, other):
        return MongoExpression("contains", self, other)

    def desc(self):
        return SortSpec(self.name, -1, self.model_class)

    def asc(self):
        return SortSpec(self.name, 1, self.model_class)

class CustomColumn(FieldSelector):
    def __init__(self, default=None):
        self.default = default
        super().__init__("")

class MetaModel(type):
    def __new__(mcs, name, bases, attrs):
        for k, v in attrs.items():
            if isinstance(v, CustomColumn):
                v.name = k
        return super().__new__(mcs, name, bases, attrs)

    def __getattribute__(cls, name):
        val = super().__getattribute__(name)
        if isinstance(val, FieldSelector):
            val.model_class = cls
        return val

    def __getattr__(cls, name):
        if name.startswith("_"):
            raise AttributeError(name)
        fs = FieldSelector(name)
        fs.model_class = cls
        return fs

class MetadataMock:
    def drop_all(self, *args, **kwargs):
        pass
    def create_all(self, *args, **kwargs):
        pass

class Base(metaclass=MetaModel):
    __tablename__ = ""
    metadata = MetadataMock()

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
            
        for k, v in self.__class__.__dict__.items():
            if isinstance(v, CustomColumn) and k not in self.__dict__:
                default_val = v.default
                if callable(default_val):
                    default_val = default_val()
                setattr(self, k, default_val)
                
        if "id" not in kwargs:
            self.id = getattr(self, "id", None)
            
        if "_id" in kwargs:
            self._id = str(kwargs["_id"])
        else:
            self._id = None

    def to_dict(self):
        data = {}
        for k, v in self.__dict__.items():
            if k.startswith("_"):
                continue
            data[k] = v
        return data

# ──────────────────────────────────────────────────────────────────────────────
#  EXPRESSION AND FUNCTION EVALUATOR
# ──────────────────────────────────────────────────────────────────────────────

def resolve_val(val, row_dict):
    if isinstance(val, FieldSelector):
        inst = row_dict.get(val.model_class)
        if inst is not None:
            return getattr(inst, val.name, None)
        return None
    return val

def eval_row_expr(expr, row_dict):
    if isinstance(expr, FieldSelector):
        return resolve_val(expr, row_dict)
        
    if isinstance(expr, FuncCall):
        if expr.func_name == "strftime":
            fmt = expr.args[0]
            dt_selector = expr.args[1]
            dt_val = resolve_val(dt_selector, row_dict)
            if isinstance(dt_val, datetime.datetime):
                return dt_val.strftime(fmt)
            elif isinstance(dt_val, str):
                try:
                    dt = datetime.datetime.fromisoformat(dt_val.replace("Z", "+00:00"))
                    return dt.strftime(fmt)
                except Exception:
                    pass
            return None
        return None
        
    return expr

def eval_expr(expr, row_dict):
    if isinstance(expr, bool):
        return expr
    if not isinstance(expr, MongoExpression):
        return bool(expr)

    op = expr.op
    if op == "or":
        return any(eval_expr(e, row_dict) for e in expr.left)
    if op == "and":
        return all(eval_expr(e, row_dict) for e in expr.left)

    val = resolve_val(expr.left, row_dict)
    other_val = resolve_val(expr.right, row_dict)

    if op == "eq":
        return val == other_val
    elif op == "ne":
        return val != other_val
    elif op == "gt":
        if val is None or other_val is None:
            return False
        return val > other_val
    elif op == "gte":
        if val is None or other_val is None:
            return False
        return val >= other_val
    elif op == "lt":
        if val is None or other_val is None:
            return False
        return val < other_val
    elif op == "lte":
        if val is None or other_val is None:
            return False
        return val <= other_val
    elif op == "in":
        if other_val is None:
            return False
        return val in other_val
    elif op == "ilike":
        if val is None or other_val is None:
            return False
        pat = str(other_val).replace("%", "").lower()
        return pat in str(val).lower()
    elif op == "contains":
        if val is None or other_val is None:
            return False
        return str(other_val) in str(val)
    return True

def eval_func(func_call, rows):
    func_name = func_call.func_name
    
    if func_name == "avg":
        arg = func_call.args[0]
        vals = []
        for r in rows:
            val = resolve_val(arg, r)
            if val is not None:
                try:
                    vals.append(float(val))
                except (ValueError, TypeError):
                    pass
        return sum(vals) / len(vals) if vals else 0.0

    elif func_name == "count":
        arg = func_call.args[0]
        count = 0
        for r in rows:
            val = resolve_val(arg, r)
            if val is not None:
                count += 1
        return count

    return None

class Row(tuple):
    def __new__(cls, values, keys=None):
        obj = super(Row, cls).__new__(cls, values)
        obj._keys = keys or []
        return obj

    def __getattr__(self, name):
        if name in self._keys:
            return self[self._keys.index(name)]
        for item in self:
            if hasattr(item, "__class__") and item.__class__.__name__ == name:
                return item
        raise AttributeError(f"Row has no attribute {name}")

    def __getitem__(self, item):
        if isinstance(item, str):
            if item in self._keys:
                return self[self._keys.index(item)]
            raise KeyError(item)
        return super().__getitem__(item)

def get_model_class_from_entity(entity):
    if hasattr(entity, "__tablename__"):
        return entity
    if hasattr(entity, "model_class"):
        return entity.model_class
    if hasattr(entity, "args"):
        for arg in entity.args:
            mc = get_model_class_from_entity(arg)
            if mc:
                return mc
    return None

# ──────────────────────────────────────────────────────────────────────────────
#  MONGODB QUERY TRANSLATOR FOR PUSH-DOWN OPTIMIZATION
# ──────────────────────────────────────────────────────────────────────────────
def translate_to_mongo_query(expr):
    if not isinstance(expr, MongoExpression):
        return None

    op = expr.op
    if op == "and":
        sub_queries = []
        for sub in expr.left:
            q = translate_to_mongo_query(sub)
            if q is None:
                return None
            sub_queries.append(q)
        return {"$and": sub_queries} if sub_queries else {}

    if op == "or":
        sub_queries = []
        for sub in expr.left:
            q = translate_to_mongo_query(sub)
            if q is None:
                return None
            sub_queries.append(q)
        return {"$or": sub_queries} if sub_queries else {}

    if not isinstance(expr.left, FieldSelector):
        return None

    field = expr.left.name
    val = expr.right
    if isinstance(val, (FieldSelector, FuncCall)):
        return None

    if op == "eq":
        return {field: val}
    elif op == "ne":
        return {field: {"$ne": val}}
    elif op == "gt":
        return {field: {"$gt": val}}
    elif op == "gte":
        return {field: {"$gte": val}}
    elif op == "lt":
        return {field: {"$lt": val}}
    elif op == "lte":
        return {field: {"$lte": val}}
    elif op == "in":
        return {field: {"$in": val}}
    elif op == "ilike":
        import re
        escaped = re.escape(str(val).replace("%", ""))
        return {field: {"$regex": escaped, "$options": "i"}}
    elif op == "contains":
        import re
        escaped = re.escape(str(val))
        return {field: {"$regex": escaped}}

    return None

class MongoQuery:
    def __init__(self, database_conn, *entities):
        self.database_conn = database_conn
        self.entities = list(entities)
        
        self.model_class = get_model_class_from_entity(self.entities[0])
        if self.model_class is None:
            raise ValueError(f"Could not determine model class for entities {entities}")
            
        self.collection_name = self.model_class.__tablename__
        self._filters = []
        self._limit = None
        self._skip = 0
        self._sort_specs = []
        self._joins = []
        self._group_by = None

    def filter(self, *expressions):
        for expr in expressions:
            if expr is not None:
                self._filters.append(expr)
        return self

    def outerjoin(self, model, clause=None):
        self._joins.append((model, clause, "outer"))
        return self

    def join(self, model, clause=None):
        self._joins.append((model, clause, "inner"))
        return self

    def group_by(self, *fields):
        self._group_by = fields
        return self

    def order_by(self, *fields):
        for field in fields:
            if isinstance(field, str):
                self._sort_specs.append(field)
            elif isinstance(field, SortSpec):
                self._sort_specs.append(field)
            elif isinstance(field, FieldSelector):
                self._sort_specs.append(field)
        return self

    def offset(self, skip):
        self._skip = skip
        return self

    def limit(self, limit):
        self._limit = limit
        return self

    def options(self, *args):
        return self

    def all(self):
        # 1. Build mongo filter and check if we can push down filters, sorting, offset, and limit
        mongo_filter = {}
        fallback_filters = []
        has_aggregates = any(isinstance(ent, FuncCall) and ent.func_name in ("avg", "count") for ent in self.entities)
        
        if not self._joins:
            for expr in self._filters:
                q = translate_to_mongo_query(expr)
                if q is not None:
                    # Merge q into mongo_filter
                    for k, v in q.items():
                        if k in mongo_filter:
                            if "$and" not in mongo_filter:
                                mongo_filter = {"$and": [{k: mongo_filter[k]}, {k: v}]}
                            else:
                                mongo_filter["$and"].append({k: v})
                        else:
                            mongo_filter[k] = v
                else:
                    fallback_filters.append(expr)
        else:
            fallback_filters = list(self._filters)

        sort_list = []
        can_sort_in_mongo = not self._joins and not self._group_by and not has_aggregates
        if can_sort_in_mongo and self._sort_specs:
            for spec in self._sort_specs:
                if isinstance(spec, SortSpec):
                    sort_list.append((spec.field_name, spec.direction))
                elif isinstance(spec, FieldSelector):
                    sort_list.append((spec.name, 1))
                elif isinstance(spec, str):
                    sort_list.append((spec, 1))
                else:
                    can_sort_in_mongo = False
                    break

        mongo_limit = None
        mongo_skip = 0
        can_limit_skip_in_mongo = not self._joins and not self._group_by and not has_aggregates and not fallback_filters
        if can_limit_skip_in_mongo:
            mongo_limit = self._limit
            mongo_skip = self._skip

        # Execute find query on MongoDB
        cursor = self.database_conn[self.collection_name].find(mongo_filter)
        if can_sort_in_mongo and sort_list:
            cursor = cursor.sort(sort_list)
        if mongo_skip:
            cursor = cursor.skip(mongo_skip)
        if mongo_limit is not None:
            cursor = cursor.limit(mongo_limit)

        row_dicts = []
        for doc in cursor:
            inst = self.model_class(**doc)
            row_dicts.append({self.model_class: inst})

        # 2. Process Joins
        for join_model, clause, join_type in self._joins:
            join_cursor = self.database_conn[join_model.__tablename__].find()
            join_instances = [join_model(**doc) for doc in join_cursor]
            
            new_row_dicts = []
            for row in row_dicts:
                matched = False
                for join_inst in join_instances:
                    candidate_row = dict(row)
                    candidate_row[join_model] = join_inst
                    if clause is None or eval_expr(clause, candidate_row):
                        new_row_dicts.append(candidate_row)
                        matched = True
                
                if not matched and join_type == "outer":
                    candidate_row = dict(row)
                    candidate_row[join_model] = None
                    new_row_dicts.append(candidate_row)
            row_dicts = new_row_dicts

        # 3. Process Filters (Remaining in-memory fallback filters)
        for expr in fallback_filters:
            row_dicts = [r for r in row_dicts if eval_expr(expr, r)]

        def resolve_field_value(field, row_dict):
            if isinstance(field, str):
                for ent in self.entities:
                    if getattr(ent, "_label", None) == field:
                        return eval_row_expr(ent, row_dict)
                return None
            return eval_row_expr(field, row_dict)

        # 4. Process Grouping and Aggregation
        if self._group_by or has_aggregates:
            groups = {}
            if self._group_by:
                for r in row_dicts:
                    key = tuple(resolve_field_value(f, r) for f in self._group_by)
                    groups.setdefault(key, []).append(r)
            else:
                groups = {(): row_dicts}

            results = []
            for key, group_rows in groups.items():
                row_values = []
                keys = []
                for ent in self.entities:
                    label = getattr(ent, "_label", None)
                    if not label and isinstance(ent, FieldSelector):
                        label = ent.name
                    keys.append(label)

                    if isinstance(ent, FuncCall) and ent.func_name in ("avg", "count"):
                        val = eval_func(ent, group_rows)
                    else:
                        val = eval_row_expr(ent, group_rows[0] if group_rows else {})
                    row_values.append(val)
                results.append(Row(row_values, keys))
        else:
            results = []
            is_single_model = len(self.entities) == 1 and hasattr(self.entities[0], "__tablename__")
            
            for r in row_dicts:
                if is_single_model:
                    results.append(r[self.model_class])
                else:
                    row_values = []
                    keys = []
                    for ent in self.entities:
                        label = getattr(ent, "_label", None)
                        if not label and isinstance(ent, FieldSelector):
                            label = ent.name
                        keys.append(label)
                        
                        if hasattr(ent, "__tablename__"):
                            row_values.append(r.get(ent))
                        else:
                            row_values.append(eval_row_expr(ent, r))
                    results.append(Row(row_values, keys))

        # 5. Sorting (Remaining in-memory fallback sorting if not done in MongoDB)
        if self._sort_specs and not can_sort_in_mongo:
            def get_sort_val_and_dir(row, sort_item):
                field_name = None
                direction = 1
                model_class = None
                
                if isinstance(sort_item, SortSpec):
                    field_name = sort_item.field_name
                    direction = sort_item.direction
                    model_class = sort_item.model_class
                elif isinstance(sort_item, FieldSelector):
                    field_name = sort_item.name
                    model_class = sort_item.model_class
                elif isinstance(sort_item, str):
                    field_name = sort_item
                
                if not isinstance(row, Row) and hasattr(row, "__tablename__"):
                    val = getattr(row, field_name, None)
                else:
                    if model_class is not None:
                        inst = row.__getattr__(model_class.__name__)
                        val = getattr(inst, field_name, None) if inst else None
                    else:
                        val = getattr(row, field_name, None)
                return val, direction

            def compare_rows(r1, r2):
                for sort_item in self._sort_specs:
                    v1, dir1 = get_sort_val_and_dir(r1, sort_item)
                    v2, dir2 = get_sort_val_and_dir(r2, sort_item)
                    if v1 is None and v2 is not None:
                        res = -1
                    elif v1 is not None and v2 is None:
                        res = 1
                    elif v1 is None and v2 is None:
                        res = 0
                    else:
                        if v1 < v2:
                            res = -1
                        elif v1 > v2:
                            res = 1
                        else:
                            res = 0
                    if res != 0:
                        return res * dir1
                return 0

            results.sort(key=functools.cmp_to_key(compare_rows))

        # 6. Skip and Limit (Remaining in-memory fallback offset/limit if not done in MongoDB)
        if self._skip and not can_limit_skip_in_mongo:
            results = results[self._skip:]
        if self._limit is not None and not can_limit_skip_in_mongo:
            results = results[:self._limit]

        return results

    def first(self):
        self.limit(1)
        results = self.all()
        return results[0] if results else None

    def count(self):
        if not self._joins:
            mongo_filter = {}
            fallback_filters = []
            for expr in self._filters:
                q = translate_to_mongo_query(expr)
                if q is not None:
                    # Merge q into mongo_filter
                    for k, v in q.items():
                        if k in mongo_filter:
                            if "$and" not in mongo_filter:
                                mongo_filter = {"$and": [{k: mongo_filter[k]}, {k: v}]}
                            else:
                                mongo_filter["$and"].append({k: v})
                        else:
                            mongo_filter[k] = v
                else:
                    fallback_filters.append(expr)
            if not fallback_filters:
                return self.database_conn[self.collection_name].count_documents(mongo_filter)
        
        self._limit = None
        self._skip = 0
        return len(self.all())

    def scalar(self):
        self.limit(1)
        results = self.all()
        if results and len(results) > 0:
            row = results[0]
            if isinstance(row, Row):
                return row[0]
            return row
        return None

    def delete(self, synchronize_session=False):
        mongo_filter = {}
        fallback_filters = []
        for expr in self._filters:
            q = translate_to_mongo_query(expr)
            if q is not None:
                for k, v in q.items():
                    if k in mongo_filter:
                        if "$and" not in mongo_filter:
                            mongo_filter = {"$and": [{k: mongo_filter[k]}, {k: v}]}
                        else:
                            mongo_filter["$and"].append({k: v})
                    else:
                        mongo_filter[k] = v
            else:
                fallback_filters.append(expr)
        
        if not fallback_filters and not self._joins:
            res = self.database_conn[self.collection_name].delete_many(mongo_filter)
            return res.deleted_count
        else:
            to_delete = self.all()
            ids = [getattr(doc, "id") for doc in to_delete if hasattr(doc, "id")]
            if ids:
                res = self.database_conn[self.collection_name].delete_many({"id": {"$in": ids}})
                return res.deleted_count
            return 0

class MongoSession:
    def __init__(self, database_conn):
        self.database_conn = database_conn
        self._to_save = []
        self._to_delete = []

    def query(self, *entities):
        return MongoQuery(self.database_conn, *entities)

    def add(self, instance):
        if instance not in self._to_save:
            self._to_save.append(instance)

    def delete(self, instance):
        if instance not in self._to_delete:
            self._to_delete.append(instance)

    def commit(self):
        for inst in self._to_save:
            collection = self.database_conn[inst.__tablename__]
            if getattr(inst, "id", None) is None:
                last_doc = collection.find_one(sort=[("id", -1)])
                new_id = (last_doc["id"] + 1) if last_doc and "id" in last_doc else 1
                inst.id = new_id
            doc_data = inst.to_dict()
            collection.update_one(
                {"id": inst.id},
                {"$set": doc_data},
                upsert=True
            )
            updated_doc = collection.find_one({"id": inst.id})
            if updated_doc:
                inst._id = str(updated_doc["_id"])
        self._to_save.clear()

        for inst in self._to_delete:
            collection = self.database_conn[inst.__tablename__]
            collection.delete_one({"id": inst.id})
        self._to_delete.clear()

    def flush(self):
        self.commit()

    def refresh(self, instance):
        collection = self.database_conn[instance.__tablename__]
        doc = collection.find_one({"id": instance.id})
        if doc:
            for k, v in doc.items():
                setattr(instance, k, v)
            instance._id = str(doc["_id"])

    def close(self):
        pass

def get_db():
    session = MongoSession(mongo_db)
    try:
        yield session
    finally:
        pass

SessionLocal = lambda: MongoSession(mongo_db)

# ──────────────────────────────────────────────────────────────────────────────
#  MOCK EXPORTS FOR MODELS
# ──────────────────────────────────────────────────────────────────────────────
def Column(*args, **kwargs):
    default = kwargs.get("default", None)
    if default is None:
        default = kwargs.get("server_default", None)
    return CustomColumn(default)

Integer = "Integer"
String = lambda *args, **kwargs: "String"
Float = "Float"
DateTime = lambda *args, **kwargs: "DateTime"
ForeignKey = lambda *args, **kwargs: "ForeignKey"
Text = "Text"
Boolean = "Boolean"
Enum = lambda *args, **kwargs: "Enum"

def relationship(*args, **kwargs):
    return None

class FuncCall:
    def __init__(self, func_name, *args):
        self.func_name = func_name
        self.args = args
        self._label = None

    def label(self, name):
        self._label = name
        return self

class FuncMock:
    def __getattr__(self, name):
        if name == "now":
            return datetime.datetime.utcnow
        def _call(*args, **kwargs):
            return FuncCall(name, *args)
        return _call

func = FuncMock()

# ──────────────────────────────────────────────────────────────────────────────
#  SYS.MODULES INJECTION MOCKS
# ──────────────────────────────────────────────────────────────────────────────
sqlalchemy_mock = ModuleType("sqlalchemy")
sqlalchemy_mock.func = func
sqlalchemy_mock.extract = lambda *args, **kwargs: None
sqlalchemy_mock.create_engine = lambda *args, **kwargs: None

class JoinedLoadMock:
    def __init__(self, *args, **kwargs):
        pass
    def joinedload(self, *args, **kwargs):
        return self

class SessionMakerMock:
    def __init__(self, *args, **kwargs):
        pass
    def __call__(self, *args, **kwargs):
        return MongoSession(mongo_db)

sqlalchemy_orm_mock = ModuleType("sqlalchemy.orm")
sqlalchemy_orm_mock.Session = MongoSession
sqlalchemy_orm_mock.joinedload = lambda *args, **kwargs: JoinedLoadMock()
sqlalchemy_orm_mock.sessionmaker = lambda *args, **kwargs: SessionMakerMock

sys.modules["sqlalchemy"] = sqlalchemy_mock
sys.modules["sqlalchemy.orm"] = sqlalchemy_orm_mock


# ──────────────────────────────────────────────────────────────────────────────
#  AUTOMATIC DATABASE INDEX INITIALIZATION
# ──────────────────────────────────────────────────────────────────────────────
def initialize_mongodb_indexes():
    """
    Ensure all critical unique, compound, and single indexes are
    registered in MongoDB to optimize query push-downs.
    """
    logger.info("[database] Initializing MongoDB database indexes...")
    try:
        # Unique Primary Key Lookups
        collections_with_ids = [
            "users", "vendors", "tenders", "evaluation_criteria", "bids",
            "bid_scores", "bid_documents", "audit_logs", "indents",
            "purchase_orders", "delivery_records", "payment_records",
            "ai_decision_logs", "dispute_cases"
        ]
        for coll in collections_with_ids:
            mongo_db[coll].create_index([("id", 1)], unique=True)

        # Unique Business Identifiers
        mongo_db["users"].create_index([("username", 1)], unique=True)
        mongo_db["users"].create_index([("email", 1)], unique=True)
        mongo_db["vendors"].create_index([("gem_reg_no", 1)], unique=True)
        mongo_db["tenders"].create_index([("bid_number", 1)], unique=True)
        mongo_db["indents"].create_index([("indent_number", 1)], unique=True)
        mongo_db["purchase_orders"].create_index([("po_number", 1)], unique=True)
        mongo_db["dispute_cases"].create_index([("case_number", 1)], unique=True)

        # Foreign Key & Filtering Indexes
        mongo_db["tenders"].create_index([("status", 1)])
        mongo_db["tenders"].create_index([("closing_date", 1)])
        
        mongo_db["bids"].create_index([("tender_id", 1), ("vendor_id", 1)])
        mongo_db["bids"].create_index([("status", 1)])
        
        mongo_db["bid_scores"].create_index([("bid_id", 1), ("criteria_id", 1)])
        mongo_db["bid_documents"].create_index([("bid_id", 1)])
        
        mongo_db["audit_logs"].create_index([("timestamp", -1)])
        mongo_db["audit_logs"].create_index([("entity_id", 1), ("action", 1)])

        mongo_db["indents"].create_index([("tender_id", 1)])
        mongo_db["purchase_orders"].create_index([("tender_id", 1), ("vendor_id", 1)])
        mongo_db["delivery_records"].create_index([("po_id", 1)])
        mongo_db["payment_records"].create_index([("po_id", 1)])
        mongo_db["dispute_cases"].create_index([("po_id", 1)])

        logger.info("[database] MongoDB database indexes initialized successfully.")
    except Exception as e:
        logger.error(f"[database] Failed to initialize database indexes: {e}")

