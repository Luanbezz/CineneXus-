import os, json, time, random, requests
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from functools import wraps
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "nexus_master_key_v5")

DATA_FILE = 'dados.json'
CHAVE_API = os.getenv("TMDB_API_KEY")
IDIOMA = "pt-BR"
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "cine123")

def carregar_dados():
    if not os.path.exists(DATA_FILE): return {"atores": {}, "filmes": {}}
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        try: return json.load(f)
        except: return {"atores": {}, "filmes": {}}

def salvar_dados(dados):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(dados, f, indent=4, ensure_ascii=False)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'): return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_globals():
    dados = carregar_dados()
    generos = sorted(list(set(f['genero'] for f in dados['filmes'].values())))
    return dict(generos=generos)

# --- ROTAS DE EXIBIÇÃO ---

@app.route('/')
def home():
    dados = carregar_dados()
    g_filtro = request.args.get('genero')
    filmes = dados['filmes']
    if g_filtro:
        filmes = {id: f for id, f in filmes.items() if f['genero'] == g_filtro}
    
    lista_f = list(reversed(list(filmes.items())))
    hero = None
    if lista_f and not g_filtro:
        h_id, h_data = lista_f[0]
        hero = {"id": h_id, **h_data}
    return render_template('index.html', hero=hero, g_ativo=g_filtro)

@app.route('/filme/<id>')
def detalhes(id):
    dados = carregar_dados()
    filme = dados['filmes'].get(str(id))
    if not filme: return render_template('404.html'), 404
    atores_f = {aid: dados['atores'][str(aid)] for aid in filme["atores_ids"] if str(aid) in dados['atores']}
    rel = {fid: f for fid, f in dados['filmes'].items() if f['genero'] == filme['genero'] and fid != str(id)}
    return render_template('detalhes.html', filme=filme, atores=atores_f, relacionados=dict(list(rel.items())[:6]))

@app.route('/ator/<id>')
def ator(id):
    dados = carregar_dados()
    ator_d = dados['atores'].get(str(id))
    if not ator_d:
        return render_template('404.html'), 404
        
    # Busca os filmes que esse ator participou
    filmes_at = {fid: dados['filmes'][str(fid)] for fid in ator_d["filmes_ids"] if str(fid) in dados['filmes']}
    
   
    return render_template('ator.html', ator=ator_d, filmes=filmes_at)

@app.route('/atores')
def todos_atores():
    dados = carregar_dados()
    atores_ord = dict(sorted(dados['atores'].items(), key=lambda x: x[1]['nome']))
    return render_template('atores.html', atores=atores_ord)

@app.route('/minha-lista')
def minha_lista(): return render_template('minha_lista.html')

# --- API ---

@app.route('/api/filmes_paginados')
def filmes_paginados():
    page = int(request.args.get('page', 1))
    genero = request.args.get('genero')
    limit = 18
    dados = carregar_dados()
    filmes = dados['filmes']
    if genero:
        filmes = {id: f for id, f in filmes.items() if f['genero'] == genero}
    lista_f = list(reversed(list(filmes.items())))
    start = (page - 1) * limit
    end = start + limit
    return jsonify({"filmes": [{"id": f[0], **f[1]} for f in lista_f[start:end]], "tem_mais": end < len(lista_f)})

@app.route('/api/sugestoes')
def sugestoes():
    q = request.args.get('q', '').lower()
    if not q: return jsonify([])
    dados = carregar_dados()
    res = [{"id": fid, "titulo": f['titulo'], "imagem": f['imagem']} for fid, f in dados['filmes'].items() if q in f['titulo'].lower()]
    return jsonify(res[:6])

@app.route('/pesquisa')
def pesquisa():
    q = request.args.get('q', '').lower()
    dados = carregar_dados()
    f_res = {id: f for id, f in dados['filmes'].items() if q in f['titulo'].lower()}
    a_res = {id: a for id, a in dados['atores'].items() if q in a['nome'].lower()}
    return render_template('pesquisa.html', filmes=f_res, atores=a_res, busca=q)

@app.route('/api/filmes_todos')
def api_filmes_todos(): return jsonify(carregar_dados()['filmes'])

# --- ADMIN ---

def executar_importacao(fid, qtd_atores, dados):
    fid = str(fid).strip()
    if fid in dados['filmes']: return False
    try:
        url_f = f"https://api.themoviedb.org/3/movie/{fid}?api_key={CHAVE_API}&language={IDIOMA}"
        res_f = requests.get(url_f).json()
        if 'title' not in res_f: return False
        bg = res_f.get('backdrop_path')
        backdrop = f"https://image.tmdb.org/t/p/original{bg}" if bg else ""
        url_v = f"https://api.themoviedb.org/3/movie/{fid}/videos?api_key={CHAVE_API}"
        videos = requests.get(url_v).json().get('results', [])
        trailer = next((v['key'] for v in videos if v['type'] == 'Trailer' and v['site'] == 'YouTube'), "")
        elenco = requests.get(f"https://api.themoviedb.org/3/movie/{fid}/credits?api_key={CHAVE_API}").json().get('cast', [])[:qtd_atores]
        a_ids = []
        for p in elenco:
            aid = str(p['id'])
            if aid not in dados['atores']:
                r_a = requests.get(f"https://api.themoviedb.org/3/person/{aid}?api_key={CHAVE_API}&language={IDIOMA}").json()
                dados['atores'][aid] = {"nome": r_a.get('name'), "foto": f"https://image.tmdb.org/t/p/w500{r_a.get('profile_path')}" if r_a.get('profile_path') else "https://via.placeholder.com/500x750", "bio": r_a.get('biography'), "filmes_ids": []}
            a_ids.append(aid)
            if fid not in dados['atores'][aid]['filmes_ids']: dados['atores'][aid]['filmes_ids'].append(fid)
        dados['filmes'][fid] = {"titulo": res_f.get('title'), "ano": res_f.get('release_date','0000')[:4], "nota": str(round(res_f.get('vote_average',0),1)), "genero": res_f.get('genres',[{}])[0].get('name','Geral'), "trailer": trailer, "imagem": f"https://image.tmdb.org/t/p/w500{res_f.get('poster_path')}", "backdrop": backdrop, "descricao": res_f.get('overview'), "atores_ids": a_ids}
        return True
    except: return False

@app.route('/admin/importar-tendencias')
@admin_required
def importar_tendencias():
    dados = carregar_dados()
    importados = 0
    for _ in range(8):
        pag = random.randint(1, 50)
        res = requests.get(f"https://api.themoviedb.org/3/movie/popular?api_key={CHAVE_API}&language={IDIOMA}&page={pag}").json()
        for f in res.get('results', []):
            if str(f['id']) not in dados['filmes'] and executar_importacao(f['id'], 6, dados):
                importados += 1
            if importados >= 15: break
        if importados >= 15: break
    salvar_dados(dados)
    flash(f'{importados} novos títulos sincronizados!')
    return redirect(url_for('home'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form.get('password') == ADMIN_PASS:
        session['logged_in'] = True
        return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.errorhandler(404)
def page_not_found(e): return render_template('404.html'), 404

if __name__ == '__main__':
    app.run(debug=True)
