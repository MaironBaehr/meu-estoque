import os
import json
import requests
import hashlib
from flask import Flask, render_template, request, redirect, url_for, session
import pandas as pd
from datetime import datetime

app = Flask(__name__)
app.secret_key = "chave_secreta_muito_segura"

# --- CONFIGURAÇÃO DO FIREBASE ---
# Lembre-se de manter a barra "/" no final!
URL_BASE = os.getenv("FIREBASE_URL", "")

def gerar_hash(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario'].lower().strip()
        senha = request.form['senha']
        
        usuarios_db = requests.get(f"{URL_BASE}usuarios.json").json() or {}
        
        if usuario in usuarios_db and usuarios_db[usuario]["senha"] == gerar_hash(senha):
            session['usuario'] = usuario
            return redirect(url_for('estoque'))
        return "Login ou senha incorretos!"
    
    return render_template('login.html')

@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    if 'usuario' not in session or session['usuario'] != 'admin':
        return "Acesso negado! Apenas o administrador pode criar contas."
        
    if request.method == 'POST':
        novo_usuario = request.form['usuario'].lower().strip()
        senha = request.form['senha']
        
        usuarios_db = requests.get(f"{URL_BASE}usuarios.json").json() or {}
        if novo_usuario in usuarios_db:
            return "Erro: Esse usuário já existe!"
        
        usuarios_db[novo_usuario] = {"senha": gerar_hash(senha)}
        requests.put(f"{URL_BASE}usuarios.json", data=json.dumps(usuarios_db))
        return redirect(url_for('estoque'))
    
    return render_template('cadastro.html')

@app.route('/estoque', methods=['GET', 'POST'])
def estoque():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    usuario = session['usuario']
    estoque_geral = requests.get(f"{URL_BASE}estoque.json").json() or {}
    usuarios_db = requests.get(f"{URL_BASE}usuarios.json").json() or {}
    meus_favoritos = requests.get(f"{URL_BASE}favoritos/{usuario}.json").json() or {}

    if request.method == 'POST':
        if 'acao' in request.form:
            item = request.form.get('produto') if usuario == 'admin' else request.form.get('produto_selecionado')
            item = item.replace("/", "-").replace(".", "") # Limpeza de nome
            quantidade_informada = int(request.form['quantidade'])
            acao = request.form['acao']

            if usuario not in estoque_geral: estoque_geral[usuario] = {}
            if item not in estoque_geral[usuario]: estoque_geral[usuario][item] = 0

            if acao == 'somar':
                estoque_geral[usuario][item] += quantidade_informada
                if usuario == 'admin':
                    for u in usuarios_db.keys():
                        if u not in estoque_geral: estoque_geral[u] = {}
                        if item not in estoque_geral[u]: estoque_geral[u][item] = 0
            
            elif acao == 'subtrair':
                if estoque_geral[usuario][item] >= quantidade_informada:
                    estoque_geral[usuario][item] -= quantidade_informada
                else:
                    return "Erro: Quantidade insuficiente!"

            # Salva Estoque
            requests.put(f"{URL_BASE}estoque.json", data=json.dumps(estoque_geral))
            
            # REGISTRA HISTÓRICO
            registro = {
                "data": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "usuario": usuario,
                "produto": item,
                "acao": acao,
                "quantidade": quantidade_informada
            }
            requests.post(f"{URL_BASE}historico.json", data=json.dumps(registro))
            
            return redirect(url_for('estoque'))

    # Filtros de exibição
    busca = request.args.get('q', '').lower()
    so_disponivel = request.args.get('disponivel') == 'true'
    filtro_adm = request.args.get('filtro_usuario', 'todos')

    if usuario == 'admin' and filtro_adm != 'todos':
        meu_estoque = {filtro_adm: estoque_geral.get(filtro_adm, {})}
    else:
        meu_estoque = estoque_geral if usuario == 'admin' else {usuario: estoque_geral.get(usuario, {})}

    catalogo = sorted(estoque_geral.get('admin', {}).keys())
    return render_template('estoque.html', usuario=usuario, estoque=meu_estoque, 
                           catalogo=catalogo, lista_usuarios=usuarios_db.keys(),
                           favoritos=meus_favoritos, busca=busca, so_disponivel=so_disponivel)

@app.route('/importar_excel', methods=['POST'])
def importar_excel():
    if 'usuario' not in session or session['usuario'] != 'admin':
        return "Acesso negado"
    arquivo = request.files.get('file')
    if arquivo:
        df = pd.read_excel(arquivo)
        estoque_geral = requests.get(f"{URL_BASE}estoque.json").json() or {}
        usuarios_db = requests.get(f"{URL_BASE}usuarios.json").json() or {}
        for _, linha in df.iterrows():
            item = str(linha.get('produto', linha.get('Produto'))).strip().replace("/", "-")
            qtd = int(linha.get('quantidade', linha.get('Quantidade')))
            for u in usuarios_db.keys():
                if u not in estoque_geral: estoque_geral[u] = {}
                if u == 'admin': estoque_geral[u][item] = qtd
                elif item not in estoque_geral[u]: estoque_geral[u][item] = 0
        requests.put(f"{URL_BASE}estoque.json", data=json.dumps(estoque_geral))
    return redirect(url_for('estoque'))

@app.route('/favoritar/<path:item>')
def favoritar(item):
    if 'usuario' not in session: return redirect(url_for('login'))
    usuario = session['usuario']
    favs_db = requests.get(f"{URL_BASE}favoritos/{usuario}.json").json() or {}
    if item in favs_db: del favs_db[item]
    else: favs_db[item] = True
    requests.put(f"{URL_BASE}favoritos/{usuario}.json", data=json.dumps(favs_db))
    return redirect(url_for('estoque'))

@app.route('/relatorio')
def relatorio():
    if 'usuario' not in session or session['usuario'] != 'admin':
        return redirect(url_for('login'))
    historico_db = requests.get(f"{URL_BASE}historico.json").json() or {}
    registros = list(historico_db.values()) if historico_db else []
    registros.sort(key=lambda x: x.get('data', ''), reverse=True)
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')
    if data_inicio and data_fim:
        registros = [r for r in registros if data_inicio <= r.get('data', '')[:10] <= data_fim]
    return render_template('relatorio.html', registros=registros, data_inicio=data_inicio, data_fim=data_fim)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
