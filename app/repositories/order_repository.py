from __future__ import annotations

from typing import Any, Optional

from bson import ObjectId
from pymongo.database import Database


class OrderRepository:
    def __init__(self, db: Database) -> None:
        self.collection = db["pedidos"]

    def find_by_id(self, order_id: ObjectId) -> Optional[dict[str, Any]]:
        return self.collection.find_one({"_id": order_id})

    def insert(self, order: dict[str, Any]) -> None:
        self.collection.insert_one(order)

    def update_status(self, order_id: ObjectId, current_status: str, new_status: str) -> bool:
        result = self.collection.update_one(
            {"_id": order_id, "status": current_status},
            {"$set": {"status": new_status}},
        )
        return result.matched_count > 0

    def delete(self, order_id: ObjectId) -> bool:
        result = self.collection.delete_one({"_id": order_id})
        return result.deleted_count > 0

    def get_revenue_report(self) -> list[dict[str, Any]]:
        """Executa agregação de faturamento por evento conforme Requisito 4."""
        pipeline = [
            {"$match": {"status": "confirmado"}},
            {"$group": {"_id": "$eventoId", "faturamento": {"$sum": "$valorTotal"}}},
            {
                "$lookup": {
                    "from": "eventos",
                    "localField": "_id",
                    "foreignField": "_id",
                    "as": "evento",
                }
            },
            {"$unwind": "$evento"},
            {
                "$project": {
                    "_id": 0,
                    "eventoId": {"$toString": "$_id"},
                    "nome": "$evento.nome",
                    "faturamento": 1,
                }
            },
            {"$sort": {"faturamento": -1}},
        ]
        return list(self.collection.aggregate(pipeline))
