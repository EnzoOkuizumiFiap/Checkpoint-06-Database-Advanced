"""Assina o canal de pedidos confirmados e imprime as mensagens recebidas."""

import os

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CHANNEL = "pedidos:confirmados"


def main() -> None:
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    pubsub = client.pubsub()
    pubsub.subscribe(CHANNEL)
    print(f"Aguardando mensagens no canal {CHANNEL}. Ctrl+C para encerrar.")
    try:
        for message in pubsub.listen():
            if message["type"] == "message":
                print(message["data"], flush=True)
    except KeyboardInterrupt:
        print("Assinante encerrado.")
    finally:
        pubsub.close()
        client.close()


if __name__ == "__main__":
    main()
