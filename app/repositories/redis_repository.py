from __future__ import annotations

import json
import logging
from typing import Any, Optional

# pyrefly: ignore[missing-import]
import redis

from app.config import settings

logger = logging.getLogger("ticketflash.redis_repository")

# ==============================================================================
# SCRIPTS LUA (Executados de forma 100% atômica dentro do próprio Redis)
# ==============================================================================

# Script para Rate Limiting (Requisito 8):
# 1. 'INCR' soma +1 na chave do usuário (ex: limite:usuario123).
# 2. Se for a primeira requisição (count == 1), define o tempo de expiração (EXPIRE) de 60 segundos.
# 3. Retorna a contagem atual.
# Por que Lua? Porque une o incremento e a definição da expiração em UMA ÚNICA operação atômica,
# evitando que duas requisições simultâneas criem contadores sem tempo de vida.
RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""

# Script para Liberação Segura de Trava / Lock Distribuído:
# Só deleta a chave da trava se o valor armazenado nela for exatamente o token do processo atual.
# Isso impede que um processo lento apague por engano o lock criado por outro processo posterior.
RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisRepository:
    """Camada de repositório que isola todos os comandos e estruturas de dados do Redis.
    
    O Redis é um banco em memória chave-valor ultra-rápido. Aqui usamos 4 estruturas principais:
    1. Strings simples com expiração (TTL): para cache de eventos.
    2. Strings com 'SET NX EX': para travas e reservas temporárias que expiram sozinhas.
    3. Sorted Sets (ZSET): para o ranking dos eventos mais visualizados.
    4. Pub/Sub: para transmissão em tempo real de mensagens de pedidos confirmados.
    """

    def __init__(self, client: redis.Redis) -> None:
        self.client = client

    # --------------------------------------------------------------------------
    # 1. CACHE DE EVENTOS (Requisitos 5 e 9)
    # --------------------------------------------------------------------------
    def get_event_cache(self, event_id: str) -> Optional[dict[str, Any]]:
        """Busca o JSON do evento na memória do Redis pela chave 'evento:{id}'."""
        cached = self.client.get(f"evento:{event_id}")
        if cached:
            try:
                return json.loads(cached)
            except json.JSONDecodeError:
                return None
        return None

    def set_event_cache(self, event_id: str, data: dict[str, Any], ttl: int = settings.EVENT_CACHE_TTL) -> None:
        """Salva o JSON do evento no Redis com TTL (Time To Live).
        
        O parâmetro 'ex=ttl' faz o Redis apagar essa chave automaticamente após 60 segundos.
        Passado esse tempo, a próxima requisição buscará os dados frescos do MongoDB.
        """
        self.client.set(f"evento:{event_id}", json.dumps(data, ensure_ascii=False), ex=ttl)

    def invalidate_event_cache(self, event_id: str) -> None:
        """Invalidação de Cache (Requisito 9):
        
        Quando um evento é alterado (PUT) ou removido (DELETE) no MongoDB, apagamos
        imediatamente a chave no Redis para não servir dados desatualizados (stale data).
        """
        self.client.delete(f"evento:{event_id}")

    # --------------------------------------------------------------------------
    # 2. RANKING DE VISUALIZAÇÕES (Requisito 7)
    # --------------------------------------------------------------------------
    def increment_event_view(self, event_id: str) -> None:
        """Incrementa as visualizações de um evento usando Sorted Set (ZSET).
        
        O que é um Sorted Set? É uma coleção de itens únicos onde cada item possui uma pontuação (score).
        O comando ZINCRBY soma +1 no score do 'event_id'.
        O próprio Redis mantém os eventos ordenados pelo número de acessos em memória.
        """
        self.client.zincrby(settings.RANKING_KEY, 1, event_id)

    def get_top_ranking(self, top_n: int = 5) -> list[tuple[str, int]]:
        """Retorna os top N eventos mais visualizados.
        
        ZREVRANGE lê o Sorted Set em ordem reversa (do maior score para o menor).
        0 a 4 pega as 5 primeiras posições.
        'withscores=True' devolve tanto o ID do evento quanto o total de visualizações.
        """
        entries = self.client.zrevrange(settings.RANKING_KEY, 0, top_n - 1, withscores=True)
        return [(str(event_id), int(score)) for event_id, score in entries]

    # --------------------------------------------------------------------------
    # 3. LIMITE DE REQUISIÇÕES / RATE LIMITING (Requisito 8)
    # --------------------------------------------------------------------------
    def check_rate_limit(
        self,
        user_id: str,
        limit: int = settings.RATE_LIMIT,
        window_seconds: int = settings.RATE_WINDOW_SECONDS,
    ) -> tuple[int, int]:
        """Executa o script Lua atômico que conta requisições por minuto por usuário.
        
        Retorna (quantidade_de_requisicoes, tempo_restante_da_janela_em_segundos).
        Se a quantidade passar de 10, a API responde HTTP 429 com o tempo para tentar novamente.
        """
        counter_key = f"limite:{user_id}"
        request_count = int(self.client.eval(RATE_LIMIT_SCRIPT, 1, counter_key, window_seconds))
        ttl = self.client.ttl(counter_key)
        return request_count, max(ttl, 1)

    # --------------------------------------------------------------------------
    # 4. RESERVAS TEMPORÁRIAS (Requisito 6)
    # --------------------------------------------------------------------------
    def create_reservation(
        self,
        reservation_id: str,
        data: dict[str, Any],
        ttl: int = settings.RESERVATION_TTL,
    ) -> bool:
        """Cria reserva temporária no Redis com 'SET NX EX'.
        
        - 'nx=True' (Not eXists): só cria a chave se ela AINDA NÃO EXISTIR.
        - 'ex=600' (Expire): expira automaticamente em 10 minutos (600s).
        
        Vantagem: se o usuário reservar e fechar o navegador sem comprar, o ingresso
        deixa de estar reservado sozinho assim que o tempo expira, sem precisar de cron jobs.
        """
        created = self.client.set(
            f"reserva:{reservation_id}",
            json.dumps(data, ensure_ascii=False),
            nx=True,
            ex=ttl,
        )
        return bool(created)

    def get_reservation(self, reservation_id: str) -> Optional[dict[str, Any]]:
        """Busca os dados da reserva ativa. Se a reserva expirou (TTL acabou), o Redis retorna None."""
        raw = self.client.get(f"reserva:{reservation_id}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def delete_reservation(self, reservation_id: str) -> bool:
        """Remove a reserva do Redis quando o pedido for confirmado com sucesso."""
        deleted = self.client.delete(f"reserva:{reservation_id}")
        return deleted > 0

    # --------------------------------------------------------------------------
    # 5. LOCK DISTRIBUÍDO (Evitar concorrência dupla no mesmo pedido)
    # --------------------------------------------------------------------------
    def acquire_lock(self, lock_key: str, token: str, ttl: int = 60) -> bool:
        """Adquire uma trava rápida para impedir que dois cliques no botão de compra confirmem a mesma reserva."""
        acquired = self.client.set(lock_key, token, nx=True, ex=ttl)
        return bool(acquired)

    def release_lock(self, lock_key: str, token: str) -> None:
        """Libera a trava com segurança usando o script Lua de verificação de token."""
        self.client.eval(RELEASE_LOCK_SCRIPT, 1, lock_key, token)

    # --------------------------------------------------------------------------
    # 6. PUB/SUB (Bônus +0,5)
    # --------------------------------------------------------------------------
    def publish(self, channel: str, message: dict[str, Any]) -> None:
        """Publica mensagem em um canal Redis (padrão Publish/Subscribe).
        
        Funciona como uma estação de rádio: a API transmite uma mensagem no canal 'pedidos:confirmados'
        e qualquer consumidor 'sintonizado' (como o script subscriber.py) recebe instantaneamente.
        Diferente do RabbitMQ (que guarda em filas persistentes), o Pub/Sub do Redis é voltado para
        notificações rápidas e eventos em tempo real.
        """
        try:
            self.client.publish(channel, json.dumps(message, ensure_ascii=False))
        except redis.RedisError:
            logger.exception("Falha ao publicar mensagem no canal %s", channel)
