from __future__ import annotations

from typing import Any, Optional

from bson import ObjectId
from pymongo.database import Database


class EventRepository:
    def __init__(self, db: Database) -> None:
        self.collection = db["eventos"]

    def create(self, document: dict[str, Any]) -> ObjectId:
        document.pop("_id", None)
        result = self.collection.insert_one(document)
        return result.inserted_id

    def find_all(
        self,
        categoria: Optional[str] = None,
        cidade: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        if categoria:
            query["categoria"] = categoria
        if cidade:
            query["local.cidade"] = cidade
        return list(self.collection.find(query).sort("data", 1))

    def find_by_id(self, event_id: ObjectId) -> Optional[dict[str, Any]]:
        return self.collection.find_one({"_id": event_id})

    def find_by_id_with_projection(
        self,
        event_id: ObjectId,
        projection: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        return self.collection.find_one({"_id": event_id}, projection)

    def find_sector_by_name(self, event_id: ObjectId, sector_name: str) -> Optional[dict[str, Any]]:
        doc = self.collection.find_one(
            {"_id": event_id, "setores.nome": sector_name},
            {"setores.$": 1},
        )
        if doc and doc.get("setores"):
            return doc["setores"][0]
        return None

    def update(self, event_id: ObjectId, document: dict[str, Any]) -> bool:
        document.pop("_id", None)
        result = self.collection.update_one({"_id": event_id}, {"$set": document})
        return result.matched_count > 0

    def delete(self, event_id: ObjectId) -> bool:
        result = self.collection.delete_one({"_id": event_id})
        return result.deleted_count > 0

    def get_occupancy_report(self, event_id: ObjectId) -> list[dict[str, Any]]:
        """Executa agregação de ocupação por setor conforme Requisito 4."""
        pipeline = [
            {"$match": {"_id": event_id}},
            {"$unwind": "$setores"},
            {
                "$project": {
                    "_id": 0,
                    "eventoId": {"$toString": "$_id"},
                    "setor": "$setores.nome",
                    "vendidos": "$setores.vendidos",
                    "capacidade": "$setores.capacidade",
                    "percentualVendido": {
                        "$cond": [
                            {"$gt": ["$setores.capacidade", 0]},
                            {
                                "$multiply": [
                                    {"$divide": ["$setores.vendidos", "$setores.capacidade"]},
                                    100,
                                ]
                            },
                            0,
                        ]
                    },
                }
            },
        ]
        return list(self.collection.aggregate(pipeline))

    def increment_sector_sold_atomic(
        self,
        event_id: ObjectId,
        sector_name: str,
        quantity: int,
    ) -> bool:
        """Incrementa vendidos atômica e condicionalmente (não ultrapassa capacidade)."""
        selected_sector = {
            "$arrayElemAt": [
                {
                    "$filter": {
                        "input": "$setores",
                        "as": "sector",
                        "cond": {"$eq": ["$$sector.nome", sector_name]},
                    }
                },
                0,
            ]
        }
        capacity_filter = {
            "_id": event_id,
            "setores": {"$elemMatch": {"nome": sector_name}},
            "$expr": {
                "$let": {
                    "vars": {"sector": selected_sector},
                    "in": {
                        "$lte": [
                            {"$add": [{"$ifNull": ["$$sector.vendidos", 0]}, quantity]},
                            "$$sector.capacidade",
                        ]
                    },
                }
            },
        }
        result = self.collection.update_one(
            capacity_filter,
            {"$inc": {"setores.$.vendidos": quantity}},
        )
        return result.matched_count > 0

    def rollback_sector_sold(
        self,
        event_id: ObjectId,
        sector_name: str,
        quantity: int,
    ) -> bool:
        """Compensa o incremento de ingressos vendidos em caso de falha posterior."""
        result = self.collection.update_one(
            {
                "_id": event_id,
                "setores": {"$elemMatch": {"nome": sector_name, "vendidos": {"$gte": quantity}}},
            },
            {"$inc": {"setores.$.vendidos": -quantity}},
        )
        return result.matched_count > 0
