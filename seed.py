"""Popula o TicketFlash com dados sintéticos e repetíveis para demonstração."""

import os
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pymongo import MongoClient

from app.database import create_indexes

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "ticketflash")
BASE_EVENT_ID = int("67f000000000000000000001", 16)
BASE_USER_ID = int("67f100000000000000000001", 16)
BASE_ORDER_ID = int("67f200000000000000000001", 16)

EVENT_NAMES = [
    ("Festival Aurora", "Música", "São Paulo"),
    ("Noite do Jazz", "Música", "Rio de Janeiro"),
    ("Tech Summit Brasil", "Tecnologia", "São Paulo"),
    ("Comédia no Centro", "Comédia", "Curitiba"),
    ("Orquestra das Estações", "Música", "Belo Horizonte"),
    ("Congresso de Dados", "Tecnologia", "Recife"),
    ("Festival de Cinema Livre", "Cinema", "Porto Alegre"),
    ("Stand-up de Quinta", "Comédia", "São Paulo"),
    ("Rock da Serra", "Música", "Curitiba"),
    ("Mostra Novos Olhares", "Cinema", "Salvador"),
]


def main() -> None:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    database = client[MONGO_DB]
    client.admin.command("ping")
    create_indexes(database)

    users = []
    cities = ["São Paulo", "Rio de Janeiro", "Curitiba", "Recife", "Salvador"]
    for index in range(20):
        users.append(
            {
                "_id": ObjectId(f"{BASE_USER_ID + index:024x}"),
                "nome": f"Usuário {index + 1:02d}",
                "email": f"usuario{index + 1:02d}@example.com",
                "cidade": cities[index % len(cities)],
                "dataCadastro": datetime(2026, 1, 1, tzinfo=timezone.utc)
                + timedelta(days=index),
            }
        )

    confirmed_sales: dict[tuple[int, str], int] = {}
    orders = []
    for index in range(50):
        event_index = index % len(EVENT_NAMES)
        sector_name = "Pista" if index % 2 == 0 else "VIP"
        quantity = 1 + (index % 2)
        confirmed = index % 5 != 0
        price = 120.0 if sector_name == "Pista" else 260.0
        if confirmed:
            key = (event_index, sector_name)
            confirmed_sales[key] = confirmed_sales.get(key, 0) + quantity
        orders.append(
            {
                "_id": ObjectId(f"{BASE_ORDER_ID + index:024x}"),
                "usuarioId": ObjectId(f"{BASE_USER_ID + (index % 20):024x}"),
                "eventoId": ObjectId(f"{BASE_EVENT_ID + event_index:024x}"),
                "setor": sector_name,
                "quantidade": quantity,
                "valorTotal": round(price * quantity, 2),
                "status": "confirmado" if confirmed else "cancelado",
                "criadoEm": datetime(2026, 3, 1, tzinfo=timezone.utc)
                + timedelta(days=index),
            }
        )

    events = []
    for index, (name, category, city) in enumerate(EVENT_NAMES):
        events.append(
            {
                "_id": ObjectId(f"{BASE_EVENT_ID + index:024x}"),
                "nome": name,
                "categoria": category,
                "data": datetime(2027, 2, 1, tzinfo=timezone.utc)
                + timedelta(days=index * 14),
                "local": {"cidade": city, "endereço": f"Avenida Principal, {100 + index}"},
                "atrações": [f"Atração {index + 1}", f"Participação {index + 1}"],
                "setores": [
                    {
                        "nome": "Pista",
                        "preço": 120.0,
                        "capacidade": 500,
                        "vendidos": confirmed_sales.get((index, "Pista"), 0),
                    },
                    {
                        "nome": "VIP",
                        "preço": 260.0,
                        "capacidade": 120,
                        "vendidos": confirmed_sales.get((index, "VIP"), 0),
                    },
                ],
            }
        )

    for collection_name, documents in (
        ("usuarios", users),
        ("eventos", events),
        ("pedidos", orders),
    ):
        collection = database[collection_name]
        for document in documents:
            identifier = document["_id"]
            collection.update_one(
                {"_id": identifier},
                {"$setOnInsert": document},
                upsert=True,
            )
        print(f"{collection_name}: {collection.count_documents({})} documentos")

    print("Seed concluído; documentos existentes foram preservados.")
    client.close()


if __name__ == "__main__":
    main()
