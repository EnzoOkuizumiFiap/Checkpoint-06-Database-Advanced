from pymongo.database import Database


def create_indexes(database: Database) -> None:
    """Create the indexes required by the checkpoint."""
    database["usuarios"].create_index("email", unique=True)
    database["eventos"].create_index([("categoria", 1), ("data", 1)])
    database["pedidos"].create_index("usuarioId")
