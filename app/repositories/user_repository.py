from __future__ import annotations

from typing import Any, Optional

from bson import ObjectId
from pymongo.database import Database


class UserRepository:
    def __init__(self, db: Database) -> None:
        self.collection = db["usuarios"]

    def find_by_id(self, user_id: ObjectId, projection: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        return self.collection.find_one({"_id": user_id}, projection)

    def exists(self, user_id: ObjectId) -> bool:
        return self.collection.find_one({"_id": user_id}, {"_id": 1}) is not None
