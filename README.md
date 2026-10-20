# TicketFlash — MongoDB + Redis com Python

API REST em FastAPI para o Checkpoint 3 da disciplina Mastering Relational and Non-Relational Database (FIAP, turma 2TDSPG).

## Integrantes

- RM: `566422` | Nome: `Lucas Barros Gouveia`
- RM: `561432` | Nome: `Enzo Okuizumi`
- RM: `564836` | Nome: `Milton Marcelino`
- RM: `562290` | Nome: `Luna Guimarães`
- RM: `563428` | Nome: `Gustavo Okada`

## Arquitetura e modelagem

O MongoDB guarda os eventos, usuários e pedidos. `local`, `atrações` e `setores` ficam embutidos em `eventos`: são dados consultados junto com o evento, e cada evento pode ter suas próprias atrações e setores. Um pedido referencia usuário e evento por `ObjectId`; essas entidades são independentes e podem ser reutilizadas por muitos pedidos. O Redis mantém somente o cache, as reservas temporárias, o ranking e a janela do limite de requisições.

| Coleção | Campos usados |
| --- | --- |
| `eventos` | `nome`, `categoria`, `data`, `local.cidade`, `local.endereço`, `atrações[]`, `setores[]` com `nome`, `preço`, `capacidade` e `vendidos` |
| `usuarios` | `nome`, `email`, `cidade`, `dataCadastro` |
| `pedidos` | `usuarioId`, `eventoId`, `setor`, `quantidade`, `valorTotal`, `status`, `criadoEm` |

No início da API são criados os índices `usuarios.email` (único), `eventos.categoria + eventos.data` (composto) e `pedidos.usuarioId`.

### `explain()` do índice composto

A consulta abaixo filtra por categoria e intervalo de data, os campos do índice composto. O `hint` deixa explícito qual índice está sendo demonstrado:

```javascript
db.eventos.find({
  categoria: "Música",
  data: { $gte: ISODate("2027-01-01T00:00:00Z") }
}).sort({ data: 1 }).hint("categoria_1_data_1")
  .explain("executionStats").queryPlanner.winningPlan
```

Saída obtida no MongoDB 7 do Compose após o seed:

```text
{
  stage: 'FETCH',
  inputStage: {
    stage: 'IXSCAN',
    keyPattern: {
      categoria: 1,
      data: 1
    },
    indexName: 'categoria_1_data_1',
    isMultiKey: false,
    multiKeyPaths: {
      categoria: [],
      data: []
    },
    isUnique: false,
    isSparse: false,
    isPartial: false,
    indexVersion: 2,
    direction: 'forward',
    indexBounds: {
      categoria: [
        '["Música", "Música"]'
      ],
      data: [
        '[new Date(1798761600000), new Date(9223372036854775807)]'
      ]
    }
  }
}
```

Para imprimir a saída completa do servidor do Compose após o seed: `docker compose exec mongo mongosh ticketflash --quiet --eval 'printjson(db.eventos.find({categoria:"Música",data:{$gte:ISODate("2027-01-01T00:00:00Z")}}).sort({data:1}).hint("categoria_1_data_1").explain("executionStats").queryPlanner.winningPlan)'`. A saída completa depende da versão do MongoDB; a etapa `IXSCAN` confirma o uso do índice composto.

O plano mostra `IXSCAN` no índice composto `categoria_1_data_1`, em vez de `COLLSCAN`.

## Executar

Requer Docker Desktop com Docker Compose. Na raiz do projeto:

```bash
docker compose up
```

Em outro terminal, popular o banco (o script é repetível e preserva documentos já existentes):

```bash
docker compose exec api python seed.py
```

Abra `http://localhost:8000/docs` para a documentação interativa do FastAPI. Para parar os serviços, use `Ctrl+C` no terminal do Compose.

O seed inclui 10 eventos, 20 usuários e 50 pedidos sintéticos. Os IDs determinísticos dos registros de demonstração são:

- Evento Festival Aurora: `67f000000000000000000001`
- Usuário 01: `67f100000000000000000001`

## Endpoints

| Método e caminho | Descrição |
| --- | --- |
| `POST /eventos` | Cria evento com os campos mínimos da modelagem |
| `GET /eventos?categoria=...&cidade=...` | Lista e filtra eventos; os filtros podem ser usados separadamente |
| `GET /eventos/{eventoId}` | Busca com cache-aside e retorna `origem: "banco"` ou `"cache"`; incrementa o ranking |
| `PUT /eventos/{eventoId}` | Atualiza os campos do evento e invalida o cache |
| `DELETE /eventos/{eventoId}` | Remove o evento e invalida o cache |
| `GET /eventos/ranking` | Retorna os cinco eventos mais consultados |
| `GET /relatorios/faturamento` | Soma os pedidos confirmados por evento, do maior faturamento ao menor |
| `GET /relatorios/ocupacao/{eventoId}` | Calcula percentual vendido por setor |
| `POST /reservas` | Recebe `usuarioId`, `eventoId`, `setor` e `quantidade`; limita a 10 requisições por usuário por minuto e cria reserva Redis de 600 segundos |
| `POST /pedidos/confirmar` | Recebe `reservaId`, confirma a reserva, atualiza vendidos com `$inc` condicional e publica no canal bônus |

O arquivo [`requisicoes.http`](requisicoes.http) contém chamadas para cada fluxo. Para confirmar uma reserva, copie o `reservaId` retornado por `POST /reservas` para a variável `@reservaId` do arquivo. A reserva expira após 10 minutos; para demonstrar o `410`, aguarde a expiração antes de enviar a confirmação. Cada bloco do limite no arquivo usa o mesmo usuário de demonstração; envie onze blocos em até um minuto para ver `429` na 11ª chamada. O TTL de uma reserva pode ser conferido com `docker compose exec redis redis-cli TTL reserva:<reservaId>`.

## Relatórios e operações MongoDB

O faturamento é calculado em pipeline no MongoDB com `$match`, `$group`, `$lookup`, `$unwind`, `$project` e `$sort`. A ocupação usa `$match`, `$unwind` e `$project`. O cálculo não percorre pedidos ou setores em laços Python.

`POST /reservas` verifica usuário, evento, setor e disponibilidade atual, aplica o limite Redis e cria uma chave `reserva:{reservaId}` por 600 segundos com `SET NX EX`. Na confirmação, uma trava temporária evita confirmações simultâneas da mesma reserva. O pedido é inserido como `processando`, o estoque é incrementado somente se a capacidade ainda permitir a quantidade e, então, o pedido recebe status `confirmado`. Se o incremento não puder ocorrer, o pedido provisório é removido. Erros conhecidos após o incremento tentam reverter o estoque e remover o pedido provisório. Os bancos Redis e MongoDB não compartilham uma transação; uma interrupção abrupta do processo entre operações não pode ser compensada automaticamente.

## Bônus Pub/Sub

Em um segundo terminal, inicie o assinante antes de confirmar pedidos:

```bash
docker compose exec api python subscriber.py
```

Cada pedido confirmado publica seu documento no canal Redis `pedidos:confirmados`; o assinante imprime as mensagens recebidas.

## Entrega

- Link do repositório: `________________________________________`
- Link do vídeo (até 5 minutos): `________________________________________`
- Observações do grupo: `____________________________________________________________________`

O PDF original acompanha o código no ZIP de entrega. Preencha nele os integrantes e links do grupo antes de enviar o ZIP ao Portal do Aluno. O vídeo, a publicação do repositório e o envio no portal são realizados pelo grupo.
