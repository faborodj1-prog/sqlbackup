"""
SqlBackup Monitor — Servidor Flask
Deploy gratuito no Render.com
Recebe eventos do SqlBackup.exe e exibe painel web.
"""
import os
import sqlite3
import secrets
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template_string, abort

app = Flask(__name__)

# ── Configuração ──────────────────────────────────────────────────────
# No Render.com: defina a variável de ambiente API_KEY com um valor secreto
# Ex: openssl rand -hex 32
API_KEY  = os.environ.get("API_KEY", "troque-esta-chave-agora")
DB_PATH  = os.environ.get("DB_PATH", "monitor.db")

# ── Banco de dados ────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS eventos (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente   TEXT    NOT NULL,
                banco     TEXT    NOT NULL,
                estado    TEXT    NOT NULL,  -- Iniciado | OK | Erro | Alerta
                mensagem  TEXT,
                ciclo     TEXT,
                tamanho   TEXT,
                criado_em TEXT    NOT NULL
            )
        """)
        db.commit()

init_db()

# ── Helpers ───────────────────────────────────────────────────────────
ESTADO_COR = {
    "Iniciado": "#0078d4",   # azul
    "OK":       "#107c10",   # verde
    "Erro":     "#c42b1c",   # vermelho
    "Alerta":   "#ca5010",   # laranja
}
ESTADO_ICONE = {
    "Iniciado": "🔵",
    "OK":       "✅",
    "Erro":     "❌",
    "Alerta":   "⚠️",
}

def verificar_chave():
    # Tenta os dois formatos de header (case-insensitive pelo Flask, mas garantindo)
    chave = (
        request.headers.get("X-Api-Key") or
        request.headers.get("x-api-key") or
        request.args.get("key") or
        ""
    ).strip()
    chave_servidor = API_KEY.strip()
    
    # Log para debug (remover em produção)
    import sys
    print(f"[AUTH] recebida={repr(chave[:8])}... servidor={repr(chave_servidor[:8])}...", file=sys.stderr)
    
    if not chave or not secrets.compare_digest(chave, chave_servidor):
        abort(401)

# ── Endpoints ─────────────────────────────────────────────────────────

@app.route("/evento", methods=["POST"])
def receber_evento():
    """SqlBackup.exe chama este endpoint após cada operação."""
    verificar_chave()
    data = request.get_json(force=True, silent=True) or {}

    cliente  = (data.get("cliente")  or "desconhecido")[:100]
    banco    = (data.get("banco")    or "?")[:100]
    estado   = (data.get("estado")   or "?")[:50]
    mensagem = (data.get("mensagem") or "")[:500]
    ciclo    = (data.get("ciclo")    or "")[:50]
    tamanho  = (data.get("tamanho")  or "")[:50]
    criado   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as db:
        db.execute(
            "INSERT INTO eventos (cliente,banco,estado,mensagem,ciclo,tamanho,criado_em) "
            "VALUES (?,?,?,?,?,?,?)",
            (cliente, banco, estado, mensagem, ciclo, tamanho, criado)
        )
        # Mantém apenas os 500 eventos mais recentes por cliente
        db.execute(
            "DELETE FROM eventos WHERE id NOT IN ("
            "  SELECT id FROM eventos WHERE cliente=? ORDER BY id DESC LIMIT 500"
            ")", (cliente,)
        )
        db.commit()

    return jsonify({"ok": True}), 200


@app.route("/status")
def status_json():
    """Retorna JSON com último evento de cada cliente (para integrações)."""
    verificar_chave()
    with get_db() as db:
        rows = db.execute("""
            SELECT e.*
            FROM eventos e
            INNER JOIN (
                SELECT cliente, MAX(id) as max_id FROM eventos GROUP BY cliente
            ) ult ON e.id = ult.max_id
            ORDER BY e.criado_em DESC
        """).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/")
def painel():
    """Painel HTML — atualiza automaticamente a cada 30s."""
    with get_db() as db:
        # Último evento por cliente
        ultimos = db.execute("""
            SELECT e.*
            FROM eventos e
            INNER JOIN (
                SELECT cliente, MAX(id) as max_id FROM eventos GROUP BY cliente
            ) ult ON e.id = ult.max_id
            ORDER BY e.criado_em DESC
        """).fetchall()

        # Histórico geral (últimos 100)
        historico = db.execute("""
            SELECT * FROM eventos ORDER BY id DESC LIMIT 100
        """).fetchall()

    agora = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")

    html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>SqlBackup Monitor</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; }

    header {
      background: #16213e;
      padding: 18px 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 2px solid #0f3460;
    }
    header h1 { font-size: 1.4rem; color: #e94560; letter-spacing: 1px; }
    header small { color: #888; font-size: 0.8rem; }

    .container { max-width: 1100px; margin: 0 auto; padding: 28px 20px; }

    h2 { font-size: 1rem; color: #888; text-transform: uppercase;
         letter-spacing: 2px; margin-bottom: 14px; margin-top: 28px; }

    /* Cards de status */
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px,1fr)); gap: 16px; }
    .card {
      background: #16213e;
      border-radius: 10px;
      padding: 20px;
      border-left: 5px solid #555;
      transition: transform .15s;
    }
    .card:hover { transform: translateY(-2px); }
    .card.OK     { border-left-color: #107c10; }
    .card.Erro   { border-left-color: #c42b1c; }
    .card.Alerta { border-left-color: #ca5010; }
    .card.Iniciado { border-left-color: #0078d4; }

    .card-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
    .card-icone  { font-size: 1.6rem; }
    .card-cliente { font-size: 1rem; font-weight: 700; color: #fff; }
    .card-banco  { font-size: 0.8rem; color: #aaa; }
    .card-estado {
      display: inline-block; padding: 2px 10px;
      border-radius: 20px; font-size: 0.75rem; font-weight: 700;
      margin-bottom: 8px;
    }
    .card.OK .card-estado     { background: #107c10; color: #fff; }
    .card.Erro .card-estado   { background: #c42b1c; color: #fff; }
    .card.Alerta .card-estado { background: #ca5010; color: #fff; }
    .card.Iniciado .card-estado { background: #0078d4; color: #fff; }
    .card-msg  { font-size: 0.85rem; color: #ccc; margin-bottom: 6px; }
    .card-hora { font-size: 0.75rem; color: #666; }

    /* Tabela histórico */
    .tabela-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    thead th {
      background: #0f3460; color: #aac; text-align: left;
      padding: 10px 12px; font-weight: 600; font-size: 0.75rem;
      text-transform: uppercase; letter-spacing: 1px;
    }
    tbody tr { border-bottom: 1px solid #1e2a4a; }
    tbody tr:hover { background: #1e2a4a; }
    tbody td { padding: 9px 12px; }

    .badge {
      padding: 2px 8px; border-radius: 20px; font-size: 0.72rem;
      font-weight: 700; white-space: nowrap;
    }
    .badge-OK      { background: #0d5c0d; color: #7eff7e; }
    .badge-Erro    { background: #5c0d0d; color: #ff8080; }
    .badge-Alerta  { background: #5c380d; color: #ffcc80; }
    .badge-Iniciado{ background: #0d2e5c; color: #80c8ff; }

    .sem-dados { color: #555; padding: 32px; text-align: center; }
    footer { text-align: center; color: #444; font-size: 0.75rem; padding: 24px; }
    .atualiza { color: #e94560; font-size: 0.75rem; }
  </style>
</head>
<body>

<header>
  <h1>🛡️ SqlBackup Monitor</h1>
  <div>
    <div><small>Atualizado: {{ agora }}</small></div>
    <div><small class="atualiza">⟳ Atualiza a cada 30s</small></div>
  </div>
</header>

<div class="container">

  <h2>Status Atual por Cliente</h2>
  {% if ultimos %}
  <div class="cards">
    {% for r in ultimos %}
    <div class="card {{ r['estado'] }}">
      <div class="card-header">
        <span class="card-icone">{{ icone(r['estado']) }}</span>
        <div>
          <div class="card-cliente">{{ r['cliente'] }}</div>
          <div class="card-banco">🗄 {{ r['banco'] }}</div>
        </div>
      </div>
      <span class="card-estado">{{ r['estado'].upper() }}</span>
      <div class="card-msg">{{ r['mensagem'] or '—' }}</div>
      {% if r['ciclo'] %}<div class="card-hora">📅 Ciclo: {{ r['ciclo'] }}</div>{% endif %}
      {% if r['tamanho'] %}<div class="card-hora">💾 {{ r['tamanho'] }}</div>{% endif %}
      <div class="card-hora">🕐 {{ r['criado_em'][:16] }} UTC</div>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <div class="sem-dados">Nenhum dado recebido ainda. Aguardando eventos do SqlBackup.exe...</div>
  {% endif %}

  <h2>Histórico de Eventos</h2>
  {% if historico %}
  <div class="tabela-wrap">
  <table>
    <thead>
      <tr>
        <th>Data/Hora (UTC)</th>
        <th>Cliente</th>
        <th>Banco</th>
        <th>Estado</th>
        <th>Ciclo</th>
        <th>Tamanho</th>
        <th>Mensagem</th>
      </tr>
    </thead>
    <tbody>
    {% for r in historico %}
      <tr>
        <td>{{ r['criado_em'][:16] }}</td>
        <td>{{ r['cliente'] }}</td>
        <td>{{ r['banco'] }}</td>
        <td><span class="badge badge-{{ r['estado'] }}">{{ r['estado'] }}</span></td>
        <td>{{ r['ciclo'] or '—' }}</td>
        <td>{{ r['tamanho'] or '—' }}</td>
        <td>{{ r['mensagem'] or '—' }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  </div>
  {% else %}
  <div class="sem-dados">Sem histórico.</div>
  {% endif %}

</div>

<footer>SqlBackup Monitor &nbsp;|&nbsp; Render.com Free Tier</footer>
</body>
</html>"""

    def icone(estado):
        return ESTADO_ICONE.get(estado, "❓")

    from jinja2 import Environment
    env = Environment()
    env.globals['icone'] = icone
    tmpl = env.from_string(html)
    return tmpl.render(ultimos=ultimos, historico=historico, agora=agora)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
