from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
import jwt
import datetime
import pymysql
import os
import requests
from dotenv import load_dotenv
from auth import token_requerido  

load_dotenv('mysql.env')

app = Flask(__name__)
CORS(app, supports_credentials=True, origins=["http://localhost:5173"])
app.config['SECRET_KEY'] = '8bf9485269a4ba37e6c37f918bf073932488be7a05a1bc3504aee4627b48aed1'

# ----- Configurações da API do Mercado Livre -----
CLIENT_ID = 'SEU_CLIENT_ID_AQUI'
CLIENT_SECRET = 'SEU_CLIENT_SECRET_AQUI'
REDIRECT_URI = 'http://localhost:5050/auth/callback'

# Função de conexão ao banco
def conectar():
    return pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        port=int(os.getenv('DB_PORT')),
        cursorclass=pymysql.cursors.DictCursor
    )

# ---------- INICIAR AUTENTICAÇÃO COM MERCADO LIVRE ----------
@app.route('/auth/login')
def auth_login():
    auth_url = (
        f'https://auth.mercadolivre.com.br/authorization'
        f'?response_type=code'
        f'&client_id={CLIENT_ID}'
        f'&redirect_uri={REDIRECT_URI}'
    )
    return redirect(auth_url)

# ---------- CALLBACK DO MERCADO LIVRE (troca o code por token) ----------
@app.route('/auth/callback')
def auth_callback():
    code = request.args.get('code')
    if not code:
        return jsonify({'erro': 'Código não fornecido'}), 400

    token_url = 'https://api.mercadolibre.com/oauth/token'
    payload = {
        'grant_type': 'authorization_code',
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'code': code,
        'redirect_uri': REDIRECT_URI
    }

    response = requests.post(token_url, json=payload)
    if response.status_code != 200:
        return jsonify({'erro': 'Erro ao obter token'}), 500

    tokens = response.json()
    access_token = tokens.get('access_token')
    refresh_token = tokens.get('refresh_token')

    # Aqui você pode salvar no banco se quiser associar ao usuário
    print("Token recebido:", tokens)

    return jsonify({
        'mensagem': 'Autenticação concluída com sucesso!',
        'access_token': access_token,
        'refresh_token': refresh_token
    })



@app.route('/register', methods=['POST'])
def cadastrar_usuario():
    dados = request.get_json()
    nome = dados.get('nome')
    email = dados.get('email')
    senha = dados.get('senha')
    tipo = dados.get('tipo')

    conexao = conectar()
    with conexao:
        with conexao.cursor() as cursor:
            sql = "INSERT INTO Usuario (nome, email, senha, tipo) VALUES (%s, %s, %s, %s)"
            cursor.execute(sql, (nome, email, senha, tipo))
        conexao.commit()

    return jsonify({'mensagem': 'Usuário cadastrado com sucesso!'}), 201


@app.route('/login', methods=['POST'])
def login():
    dados = request.get_json()
    email = dados.get('email')
    senha = dados.get('senha')

    conexao = conectar()
    with conexao:
        with conexao.cursor() as cursor:
            sql = "SELECT * FROM Usuario WHERE email = %s AND senha = %s"
            cursor.execute(sql, (email, senha))
            usuario = cursor.fetchone()

    if usuario:
        token = jwt.encode({
            'id': usuario['id'],
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=12)
        }, app.config['SECRET_KEY'], algorithm='HS256')

        # Retorna token e tipo de usuário
        return jsonify({
            'token': token,
            'tipo': usuario['tipo']
        }), 200

    return jsonify({'mensagem': 'Credenciais inválidas.'}), 401

# -------------------------BUSCAR produtos -----------------------------------------------

@app.route('/dashboard', methods=['GET'])
@token_requerido
def dashboard():
    user_id = request.usuario['id']  
    conexao = conectar()
    with conexao:
        with conexao.cursor() as cursor:
            cursor.execute("""
                SELECT
                  p.COD     AS cod,
                  p.nome    AS nome,
                  p.preco   AS preco,
                  p.descricao AS descricao,
                  p.categoria AS categoria,
                  p.imagem_url as imagem_url,
                  COALESCE(e.quantidade, 0) AS quantidade
                FROM Produto p
                LEFT JOIN Estoque e ON p.COD = e.fk_cod_prod
                WHERE p.user_id = %s
            """, (user_id,))
            dados = cursor.fetchall()
    return jsonify(dados), 200


@app.route('/novoproduto', methods=['POST'])
@token_requerido
def criar_produto():
    user_id     = request.usuario['id']
    dados       = request.get_json()
    nome        = dados.get('name')
    descricao   = dados.get('description')
    preco       = dados.get('price')
    categoria   = dados.get('category')
    quantidade  = dados.get('quantity')
    imagem_url  = dados.get('image_url')

    if not imagem_url or not isinstance(imagem_url, str) or not imagem_url.lower().endswith('.jpg'):
        return jsonify({'mensagem': 'A URL de imagem é obrigatória e deve terminar em .jpg'}), 400

    conn = conectar()
    with conn:
        with conn.cursor() as cursor:
            cursor.execute("""
              INSERT INTO Produto (nome, descricao, preco, categoria, imagem_url, user_id)
              VALUES (%s, %s, %s, %s, %s, %s)
            """, (nome, descricao, preco, categoria, imagem_url, user_id))
            novo_cod = cursor.lastrowid

            cursor.execute("""
              INSERT INTO Estoque (fk_cod_prod, quantidade)
              VALUES (%s, %s)
            """, (novo_cod, quantidade))

        conn.commit()

    return jsonify({'mensagem': 'Produto criado com sucesso!', 'cod': novo_cod}), 201

@app.route('/produto/<int:cod>', methods=['GET']) #-- Pega um produto especifico 
@token_requerido
def obter_produto(cod):
    user_id = request.usuario['id']
    conn = conectar()
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
              SELECT p.COD AS cod, p.nome, p.descricao, p.preco,
                     p.categoria, p.imagem_url,
                     COALESCE(e.quantidade,0) AS quantidade
              FROM Produto p
              LEFT JOIN Estoque e ON p.COD = e.fk_cod_prod
              WHERE p.COD = %s AND p.user_id = %s
            """, (cod, user_id))
            prod = cur.fetchone()
    if prod:
        return jsonify(prod), 200
    return jsonify({'mensagem':'Produto não encontrado'}), 404


@app.route('/produto/<int:cod>', methods=['PUT']) # Atualiza o produto 
@token_requerido
def atualizar_produto(cod):
    user_id = request.usuario['id']
    dados = request.get_json()
    conn = conectar()
    with conn:
        with conn.cursor() as cur:
            # verifica se o produto pertence ao usuário
            cur.execute("SELECT 1 FROM Produto WHERE COD = %s AND user_id = %s", (cod, user_id))
            if not cur.fetchone():
                return jsonify({'mensagem': 'Produto não encontrado ou não pertence a você.'}), 403

            cur.execute("""
              UPDATE Produto
              SET nome=%s, descricao=%s, preco=%s, categoria=%s, imagem_url=%s
              WHERE COD=%s
            """, (
              dados['name'], dados['description'], dados['price'],
              dados['category'], dados['image_url'], cod
            ))

            cur.execute("""
              UPDATE Estoque SET quantidade=%s
              WHERE fk_cod_prod=%s
            """, (dados['quantity'], cod))

        conn.commit()
    return jsonify({'mensagem':'Produto atualizado com sucesso!'}), 200


# ------------------------------------------------------------------------

@app.route('/finance', methods=['GET']) # ---- LISTAR todas as transações do usuário 
@token_requerido
def listar_financas():
    user_id = request.usuario['id']
    conn = conectar()
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
              SELECT id,
              descricao, 
              valor, 
              DATE_FORMAT(data,'%%Y-%%m-%%d') AS data
              FROM Financeiro WHERE user_id=%s
              ORDER BY data DESC
            """, (user_id,))
            rows = cur.fetchall()
    return jsonify(rows), 200

@app.route('/finance', methods=['POST']) # ---- CRIAR nova transação 
@token_requerido
def criar_financa():
    dados = request.get_json()
    conn = conectar()
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
              INSERT INTO Financeiro (descricao, valor, data, user_id)
              VALUES (%s,%s,%s,%s)
            """, (
              dados['descricao'], dados['valor'],
              dados['data'], request.usuario['id']
            ))
        conn.commit()
    return jsonify({'mensagem':'Transação criada!'}), 201

@app.route('/finance/<int:fid>', methods=['PUT']) # --- ATUALIZAR 
@token_requerido
def atualizar_financa(fid):
    dados = request.get_json()
    conn = conectar()
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
              UPDATE Financeiro
              SET descricao=%s, valor=%s, data=%s
              WHERE id=%s AND user_id=%s
            """, (
              dados['descricao'], dados['valor'],
              dados['data'], fid, request.usuario['id']
            ))
        conn.commit()
    return jsonify({'mensagem':'Atualizado!'}), 200

@app.route('/finance/<int:fid>', methods=['DELETE']) # --- REMOVER 
@token_requerido
def remover_financa(fid):
    conn = conectar()
    with conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM Financeiro WHERE id=%s AND user_id=%s",
                        (fid, request.usuario['id']))
        conn.commit()
    return jsonify({'mensagem':'Deletado!'}), 200

#-----------------------------DASHBOARD COMPRAS------------
# helper: devolve id do produto; cria se não existir

def get_or_create_produto(nome, fornecedor_id, cur, categoria='Outros', user_id=None):
    # 1) tenta achar o produto
    cur.execute("SELECT COD, id_fornecedor FROM Produto WHERE nome=%s AND user_id=%s", (nome, user_id))
    row = cur.fetchone()
    if row:
        if row['id_fornecedor'] is None:
            cur.execute("UPDATE Produto SET id_fornecedor=%s WHERE COD=%s", (fornecedor_id, row['COD']))
        cur.execute("UPDATE Produto SET categoria=%s WHERE COD=%s", (categoria, row['COD']))
        return row['COD']

    # 2) não existe → insere incluindo o fornecedor_id e categoria
    cur.execute("""
        INSERT INTO Produto (nome, descricao, preco, categoria, id_fornecedor, user_id)
        VALUES (%s, '', 0, %s, %s, %s)
    """, (nome, categoria, fornecedor_id, user_id))
    return cur.lastrowid


def get_or_create_fornecedor(nome, cur):
    cur.execute("SELECT id FROM Fornecedor WHERE nome=%s", (nome,))
    row = cur.fetchone()
    if row:
        return row['id']
    cur.execute("INSERT INTO Fornecedor (nome) VALUES (%s)", (nome,))
    return cur.lastrowid

@app.route('/comprasdashboard', methods=['GET'])
@token_requerido
def listar_compras():
    uid = request.usuario['id']
    con = conectar()
    with con, con.cursor() as cur:
        cur.execute("""
          SELECT c.id, p.nome AS produto, c.quantidade, p.categoria,
                 c.preco_unit AS preco_unit, DATE_FORMAT(c.data,'%%Y-%%m-%%d') AS data,
                 f.nome AS fornecedor
          FROM Compras c
          JOIN Produto p ON c.produto_id = p.COD
          JOIN Fornecedor f ON c.fornecedor_id = f.id
          WHERE c.user_id = %s
          ORDER BY c.data DESC
        """, (uid,))
        rows = cur.fetchall()
    return jsonify(rows), 200

@app.route('/comprasdashboard', methods=['POST'])
@token_requerido
def criar_compra():
    d   = request.get_json()
    uid = request.usuario['id']
    con = conectar()
    with con:
        with con.cursor() as cur:
            fornecedor_id = get_or_create_fornecedor(d['fornecedor_nome'], cur)
            produto_id    = get_or_create_produto(d['produto_nome'], fornecedor_id, cur, d['categoria'], uid)

            cur.execute("""
              INSERT INTO Compras (produto_id, fornecedor_id, quantidade, preco_unit, data, user_id)
              VALUES (%s, %s, %s, %s, %s, %s)
            """, (produto_id, fornecedor_id, d['quantidade'], d['preco_unit'], d['data'], uid))

            cur.execute("""
              INSERT INTO Estoque (fk_cod_prod, data, quantidade)
              VALUES (%s, %s, %s)
            """, (produto_id, d['data'], d['quantidade']))

        con.commit()

    return jsonify({'mensagem': 'Compra criada e estoque atualizado!'}), 201



# ---------- ATUALIZAR --------------------------------------

@app.route('/comprasdashboard/<int:cid>', methods=['PUT'])
@token_requerido
def atualizar_compra(cid):
    d   = request.get_json()
    uid = request.usuario['id']
    con = conectar()
    with con:
        with con.cursor() as cur:
            fornecedor_id = get_or_create_fornecedor(d['fornecedor_nome'], cur)
            produto_id    = get_or_create_produto(d['produto_nome'], fornecedor_id, cur, d['categoria'])

            cur.execute("""
              UPDATE Compras SET
                produto_id    = %s,
                fornecedor_id = %s,
                quantidade    = %s,
                preco_unit    = %s,
                data          = %s
              WHERE id=%s AND user_id=%s
            """, (
              produto_id, fornecedor_id,
              d['quantidade'], d['preco_unit'], d['data'],
              cid, uid
            ))
        con.commit()
    return jsonify({'mensagem': 'Atualizada!'}), 200


# ---------- REMOVER ----------------------------------------

@app.route('/comprasdashboard/<int:cid>', methods=['DELETE'])
@token_requerido
def remover_compra(cid):
    uid = request.usuario['id']
    con = conectar()
    with con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM Compras WHERE id=%s AND user_id=%s", (cid, uid))
        con.commit()
    return jsonify({'mensagem':'Removida!'}), 200


#----------- LISTAR as Vendas ----------------
@app.route('/vendas', methods=['GET'])
@token_requerido
def listar_vendas():
    uid = request.usuario['id']
    con = conectar()
    with con:
        with con.cursor() as cur:
            cur.execute("""
              SELECT p.id, pr.nome AS produto, c.nome AS cliente,
                     p.quantidade, p.valor_final AS preco,
                     DATE_FORMAT(p.data, '%%Y-%%m-%%d') AS data,
                     p.status
              FROM Pedido p
              JOIN Produto pr ON pr.COD = p.id_produto
              JOIN Cliente c ON c.id = p.id_cliente
              WHERE p.status = 'finalizado' AND pr.user_id = %s
              ORDER BY p.data DESC
            """, (uid,))
            vendas = cur.fetchall()
    return jsonify(vendas), 200
#---------------EDITAR as Vendas------------------
@app.route('/vendas/<int:id>', methods=['PUT'])
@token_requerido
def atualizar_venda(id):
    d = request.get_json()
    con = conectar()
    with con:
        with con.cursor() as cur:
            cur.execute("SELECT COD FROM Produto WHERE nome = %s", (d['produto_nome'],))
            prod = cur.fetchone()
            if not prod:
                return jsonify({'mensagem': 'Produto não encontrado'}), 404
            produto_id = prod['COD']

            cur.execute("""
                UPDATE Pedido
                SET id_produto=%s, data=%s, quantidade=%s, valor_final=%s, status=%s
                WHERE id=%s
            """, (
                produto_id,
                d['data'],
                d['quantidade'],
                d['preco'],
                d['status'],
                id
            ))

            cur.execute("SELECT id_cliente FROM Pedido WHERE id = %s", (id,))
            pedido = cur.fetchone()
            if pedido:
                id_cliente = pedido['id_cliente']
                cur.execute("""
                    UPDATE Cliente
                    SET nome=%s
                    WHERE id=%s
                """, (
                    d['cliente_nome'],  # nome novo
                    id_cliente
                ))

        con.commit()
    return jsonify({'mensagem': 'Venda atualizada com sucesso'}), 200



#-------------------EXCLUIR as Vendas---------------------
@app.route('/vendas/<int:id>', methods=['DELETE'])
@token_requerido
def remover_venda(id):
    uid = request.usuario['id']
    con = conectar()
    with con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM Pedido WHERE id=%s", (id,))
        con.commit()
    return jsonify({'mensagem': 'Venda removida com sucesso'}), 200


#---------------CRIAR Venda------------------------------
@app.route('/vendas', methods=['POST'])
@token_requerido
def criar_venda():
    d = request.get_json()
    con = conectar()
    try:
        with con:
            with con.cursor() as cur:
                # 1. Buscar produto
                cur.execute("SELECT COD FROM Produto WHERE nome = %s", (d['produto_nome'],))
                produto = cur.fetchone()
                if not produto:
                    return jsonify({'mensagem': 'Produto não encontrado'}), 400
                produto_id = produto['COD']

                # 2. Verificar estoque disponível
                cur.execute("SELECT quantidade FROM Estoque WHERE fk_cod_prod = %s", (produto_id,))
                estoque = cur.fetchone()
                if not estoque or estoque['quantidade'] < d['quantidade']:
                    return jsonify({'mensagem': 'Estoque insuficiente'}), 400

                # 3. Buscar ou criar cliente
                cur.execute("SELECT id FROM Cliente WHERE nome = %s", (d['cliente_nome'],))
                cliente = cur.fetchone()
                if cliente:
                    cliente_id = cliente['id']
                else:
                    cur.execute("INSERT INTO Cliente (nome) VALUES (%s)", (d['cliente_nome'],))
                    cliente_id = cur.lastrowid

                # 4. Inserir o pedido
                cur.execute("""
                    INSERT INTO Pedido (data, quantidade, valor_final, status, id_produto, id_cliente, marketplace)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    d['data'],
                    d['quantidade'],
                    d['valor_final'],
                    d['status'],
                    produto_id,
                    cliente_id,
                    'avulso'
                ))

                # 5. Se o status for finalizado, descontar do estoque
                if d['status'].lower() == 'finalizado':
                    nova_qtd = estoque['quantidade'] - d['quantidade']
                    cur.execute("""
                        UPDATE Estoque SET quantidade = %s WHERE fk_cod_prod = %s
                    """, (nova_qtd, produto_id))

            con.commit()
        return jsonify({'mensagem': 'Venda criada com sucesso'}), 201

    except Exception as e:
        print("Erro:", e)
        return jsonify({'erro': 'Erro ao criar venda'}), 500

# ----------- RELATÓRIO: Lucro mensal por mes ---------------
@app.route('/relatorios/lucro-produto/<string:nome>', methods=['GET'])
@token_requerido
def relatorio_lucro_por_produto(nome):
    uid = request.usuario['id']
    con = conectar()
    with con:
        with con.cursor() as cur:
            cur.execute("""
                SELECT mes, lucro_total
                FROM lucro_produto_mensal
                WHERE produto = %s AND user_id = %s
                ORDER BY mes
            """, (nome, uid))
            dados = cur.fetchall()
    return jsonify(dados), 200

#-------------- LUCRO GERAL por mes --------------------------
@app.route('/relatorios/lucro-mensal', methods=['GET'])
@token_requerido
def relatorio_lucro_mensal():
    uid = request.usuario['id']
    con = conectar()
    with con:
        with con.cursor() as cur:
            cur.execute("SELECT * FROM lucro_mensal WHERE user_id = %s", (uid,))
            dados = cur.fetchall()
    return jsonify(dados), 200

@app.route('/produtos', methods=['GET'])
@token_requerido
def listar_produtos():
    uid = request.usuario['id']
    con = conectar()
    with con:
        with con.cursor() as cur:
            cur.execute("SELECT DISTINCT nome FROM Produto WHERE user_id = %s", (uid,))
            produtos = cur.fetchall()
    return jsonify(produtos), 200



if __name__ == '__main__':
    app.run(debug=True, port=5050)
