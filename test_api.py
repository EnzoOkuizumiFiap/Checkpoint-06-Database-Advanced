"""Script de testes automatizados de integração de ponta a ponta."""

import json
import urllib.error
import urllib.request


def request(method, path, data=None):
    url = f"http://localhost:8000{path}"
    body = json.dumps(data).encode() if data else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode()
            return response.status, json.loads(res_body) if res_body else None
    except urllib.error.HTTPError as e:
        res_body = e.read().decode()
        return e.code, json.loads(res_body) if res_body else None


def main():
    print("Iniciando testes da API TicketFlash...")

    # 1. Health
    status_code, body = request("GET", "/health")
    assert status_code == 200 and body == {"status": "ok"}, f"Health falhou: {status_code}, {body}"
    print("[OK] 1. Health check OK")

    # 2. Eventos CRUD
    novo_evento = {
        "nome": "Show de Teste Automatizado",
        "categoria": "Música",
        "data": "2027-11-20T21:00:00Z",
        "local": {"cidade": "São Paulo", "endereço": "Rua dos Testes, 123"},
        "atrações": ["Banda Teste"],
        "setores": [{"nome": "Pista", "preço": 150.0, "capacidade": 50, "vendidos": 0}],
    }
    code, ev = request("POST", "/eventos", novo_evento)
    assert code == 201, f"Create failed: {code}, {ev}"
    ev_id = ev["_id"]
    print(f"[OK] 2. Evento criado com sucesso: {ev_id}")

    # List & Filter
    code, evs = request("GET", "/eventos?categoria=M%C3%BAsica&cidade=S%C3%A3o%20Paulo")
    assert code == 200 and any(e["_id"] == ev_id for e in evs), "Filtro falhou"
    print("[OK] 3. Listagem e filtros OK")

    # Cache-aside test (Req. 5)
    code, r1 = request("GET", f"/eventos/{ev_id}")
    assert code == 200 and r1["origem"] == "banco", f"Origem 1 falhou: {r1}"
    code, r2 = request("GET", f"/eventos/{ev_id}")
    assert code == 200 and r2["origem"] == "cache", f"Origem 2 falhou: {r2}"
    print("[OK] 4. Cache-aside (primeira leitura banco, segunda cache) OK")

    # Update & cache invalidation (Req. 9)
    novo_evento["nome"] = "Show de Teste Atualizado"
    code, r_up = request("PUT", f"/eventos/{ev_id}", novo_evento)
    assert code == 200 and r_up["nome"] == "Show de Teste Atualizado", "Update failed"
    code, r3 = request("GET", f"/eventos/{ev_id}")
    assert code == 200 and r3["origem"] == "banco", f"Invalidação de cache falhou: {r3}"
    print("[OK] 5. Invalidação de cache no UPDATE OK")

    # Relatórios MongoDB (Req. 4)
    code, faturamento = request("GET", "/relatorios/faturamento")
    assert code == 200 and len(faturamento) > 0, "Relatório faturamento falhou"
    code, ocupacao = request("GET", f"/relatorios/ocupacao/{ev_id}")
    assert code == 200 and len(ocupacao) > 0, "Relatório ocupação falhou"
    print("[OK] 6. Relatórios de faturamento ($lookup) e ocupação ($unwind) OK")

    # Ranking Redis (Req. 7)
    code, ranking = request("GET", "/eventos/ranking")
    assert code == 200 and "ranking" in ranking and len(ranking["ranking"]) > 0, "Ranking falhou"
    print(f"[OK] 7. Ranking Redis (Top {len(ranking['ranking'])}) OK")

    # Reserva temporária (Req. 6)
    user_id = "67f100000000000000000001"
    res_data = {"usuarioId": user_id, "eventoId": ev_id, "setor": "Pista", "quantidade": 2}
    code, res = request("POST", "/reservas", res_data)
    assert code == 201 and "reservaId" in res and res["ttlSegundos"] == 600, f"Reserva falhou: {code}, {res}"
    res_id = res["reservaId"]
    print(f"[OK] 8. Reserva criada no Redis com TTL 600s: {res_id}")

    # Confirmação atômica (Req. 10)
    code, pedido = request("POST", "/pedidos/confirmar", {"reservaId": res_id})
    assert code == 200 and pedido["status"] == "confirmado", f"Confirmação falhou: {code}, {pedido}"
    print(f"[OK] 9. Pedido confirmado com decremento atômico de vagas: {pedido['_id']}")

    # 410 Gone para reserva inexistente/expirada (Req. 10)
    code, exp = request("POST", "/pedidos/confirmar", {"reservaId": "67f999999999999999999999"})
    assert code == 410, f"Esperava 410 para reserva inexistente/expirada, obteve: {code}"
    print("[OK] 10. Erro 410 (Gone) para reserva inexistente/expirada OK")

    # Rate limit (Req. 8: 11 chamadas em menos de 1 minuto)
    limite_user = "67f100000000000000000009"
    res_limit = {"usuarioId": limite_user, "eventoId": ev_id, "setor": "Pista", "quantidade": 1}
    statuses = [request("POST", "/reservas", res_limit)[0] for _ in range(11)]
    assert statuses[-1] == 429, f"Rate limit não disparou 429 na 11ª chamada: {statuses}"
    print("[OK] 11. Rate Limit (429 após 10 requisições por minuto) OK")

    # Deleção & invalidação de cache (Req. 9)
    code, _ = request("DELETE", f"/eventos/{ev_id}")
    assert code == 204, "Delete falhou"
    code, _ = request("GET", f"/eventos/{ev_id}")
    assert code == 404, "Invalidação de cache no DELETE falhou"
    print("[OK] 12. Deleção de evento e invalidação de cache OK")

    print("\n" + "=" * 50)
    print("TODOS OS TESTES AUTOMATIZADOS PASSARAM COM 100% DE SUCESSO!")
    print("=" * 50)


if __name__ == "__main__":
    main()
