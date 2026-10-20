
## Roteiro de Demonstração em Vídeo (até 5 minutos)

O vídeo de apresentação deve seguir o roteiro estabelecido no documento da prova:

1. **Subir o ambiente:** Executar `docker compose up` e demonstrar os 3 serviços (`api`, `mongo`, `redis`) saudáveis e prontos.
2. **Cache-aside:** Executar `GET /eventos/67f000000000000000000001` duas vezes seguidas:
   - 1ª chamada: exibe `"origem": "banco"`.
   - 2ª chamada: exibe `"origem": "cache"`.
3. **Invalidação de cache:** Executar `PUT /eventos/67f000000000000000000001` atualizando um dado e chamar o `GET` novamente para mostrar que a leitura voltou a `"origem": "banco"`.
4. **Reserva e confirmação:** 
   - Criar uma reserva com `POST /reservas`.
   - Demonstrar a chave criada no Redis com TTL de 10 min (`docker compose exec redis redis-cli TTL reserva:<reservaId>`).
   - Confirmar o pedido com `POST /pedidos/confirmar` informando o `reservaId`.
5. **Tratamento de expiração (410):** Chamar `POST /pedidos/confirmar` com uma reserva inexistente/expirada e mostrar o retorno `HTTP 410 Gone`.
6. **Rate limiting (429):** Disparar 11 requisições de reserva seguidas para o mesmo usuário e mostrar a 11ª retornando `HTTP 429 Too Many Requests`.
7. **Ranking e agregações:** Consultar `GET /eventos/ranking` (Sorted Set no Redis), `GET /relatorios/faturamento` ($lookup no Mongo) e `GET /relatorios/ocupacao/{eventoId}` ($unwind no Mongo).
8. *(Bônus Pub/Sub):* Deixar o `subscriber.py` rodando em um terminal e mostrar o evento sendo recebido em tempo real na confirmação do pedido.

---

## 💡 Guia Explicativo dos Conceitos (Para a Apresentação Oral)

Este guia resume os conceitos e decisões técnicas de forma simples e direta, ideal para consultas e explicações durante a avaliação:

### 1. Por que embutir vs referenciar no MongoDB? (Requisito 1)
- **Embutidos (`local`, `atrações`, `setores` dentro de `eventos`):** São dados altamente coesos e consultados sempre juntos. Como cada evento tem seus próprios setores e atrações (relação `1:N` pequena e delimitada), embutir elimina a necessidade de *joins*, trazendo todas as informações do show em uma única leitura atômica.
- **Referenciados (`usuarioId` e `eventoId` dentro de `pedidos`):** Usuários e eventos são entidades independentes com ciclo de vida próprio e reutilizadas por dezenas ou milhares de compras (relação `1:N` ilimitada). Se embutíssemos pedidos dentro do evento ou do usuário, o documento cresceria indefinidamente, estourando o limite de 16 MB do BSON no MongoDB. Por isso, usamos referências por `ObjectId`.

### 2. O que é o Redis e para que serve cada comando? (Requisitos 5 a 8)
O **Redis** é um banco de dados em memória (RAM) ultra-rápido do tipo chave-valor. Ele atende tudo que precisa de resposta em milissegundos ou que tem tempo de vida temporário:

- **Cache-aside com TTL (`GET` e `SET ... EX 60`):**
  - A API primeiro pergunta ao Redis (`GET evento:<id>`). Se encontrar, retorna imediatamente com `"origem": "cache"`.
  - Se não encontrar (cache miss), busca no MongoDB, devolve com `"origem": "banco"` e grava no Redis com **TTL (Time-To-Live)** de 60 segundos (`EX 60`).
  - Após 60 segundos, o Redis descarta o valor da memória automaticamente para que a próxima leitura busque dados atualizados.
- **Invalidação de Cache (`DEL evento:<id>`):**
  - Sempre que um evento é alterado (`PUT`) ou deletado (`DELETE`), o Redis apaga a chave correspondente. Isso impede que usuários continuem lendo dados velhos em cache.
- **Reserva temporária (`SET NX EX 600`):**
  - **`NX` (*Not eXists*):** só cria a reserva se a chave ainda não existir.
  - **`EX 600` (*Expire*):** define que a reserva dura exatamente 10 minutos (600 segundos).
  - *Vantagem:* se o usuário reservar o ingresso e fechar a aba sem pagar, o Redis descarta a reserva sozinho quando o tempo acabar. Não precisamos de cron jobs ou tarefas em segundo plano para liberar ingressos abandonados!
- **Ranking com Sorted Set (`ZINCRBY` e `ZREVRANGE`):**
  - Um **Sorted Set (ZSET)** no Redis funciona como uma tabela de pontuação (placar) mantida em memória: cada elemento possui um *score* associado.
  - **`ZINCRBY eventos:ranking 1 <eventoId>`:** Toda vez que alguém consulta um evento, o Redis soma +1 no score daquele evento.
  - **`ZREVRANGE eventos:ranking 0 4 WITHSCORES`:** Lê os 5 eventos com maiores pontuações em ordem decrescente instantaneamente, sem precisar fazer `COUNT()` ou `GROUP BY` pesados no MongoDB.
- **Limite de Requisições / Rate Limiting (`INCR` + `EXPIRE` via Script Lua):**
  - **`INCR limite:<usuarioId>`:** Cria ou incrementa um contador numérico no Redis.
  - **`EXPIRE limite:<usuarioId> 60`:** Na primeira chamada, ativa um cronômetro de 60 segundos.
  - Se o contador ultrapassar 10 requisições dentro desse 1 minuto, a API rejeita a chamada retornando `HTTP 429 (Too Many Requests)` e informa quantos segundos faltam para tentar de novo no header `Retry-After`.
  - *Por que Script Lua?* O script executa de forma 100% atômica no servidor do Redis, evitando condições de corrida (duas chamadas no mesmo milissegundo criarem contadores paralelos).
- **Pub/Sub no Redis vs Mensageria (RabbitMQ):**
  - O **Pub/Sub do Redis** é um modelo de transmissão em tempo real (*broadcast* ou "estação de rádio"): a API publica a confirmação no canal `pedidos:confirmados` e qualquer serviço sintonizado (como o `subscriber.py`) recebe na hora.
  - *Diferença para o RabbitMQ:* O RabbitMQ enfileira e persiste mensagens em disco para garantir entrega futura mesmo se o consumidor estiver offline. O Pub/Sub do Redis é focado em alta velocidade e baixo consumo de memória para notificações efêmeras e em tempo real.

### 3. Como funciona o Estoque Atômico com `$inc` e `$expr` no MongoDB? (Requisito 10)
- No MongoDB, filtros de consulta convencionais não conseguem comparar campos do próprio documento entre si (por exemplo, testar se `vendidos + quantidade <= capacidade`).
- Por isso, utilizamos o operador **`$expr`**: ele permite aplicar uma expressão condicional dentro do filtro do `update_one`.
- O MongoDB só incrementa `vendidos` (`$inc`) se a capacidade do setor não tiver sido atingida. Se todos os ingressos já foram vendidos, o filtro não bate, nenhuma linha é modificada (`matched_count == 0`) e a API responde `HTTP 409 (Capacidade esgotada)`. Isso impede *overbooking* de ingressos mesmo com milhares de compras concorrentes!