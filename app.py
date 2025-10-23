# app.py (versão completa com Fase 2)

import os
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from collections import defaultdict
import datetime

# --- Configuração e Modelos (como na Fase 1) ---
basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'produtos.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Lote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fornecedor_nome = db.Column(db.String(100), nullable=False)
    data_criacao = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    status = db.Column(db.String(50), default='Em Andamento')
    produtos = db.relationship('ProdutoAvariado', backref='lote', lazy=True)

class ProdutoAvariado(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(80), nullable=False)
    nome_produto = db.Column(db.String(200), nullable=False)
    modelo = db.Column(db.String(100), nullable=True)
    fornecedor = db.Column(db.String(100), nullable=False)
    ean = db.Column(db.String(50), nullable=True)
    descricao_avaria = db.Column(db.Text, nullable=False)
    data_entrada = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    status = db.Column(db.String(50), default='Pendente')
    lote_id = db.Column(db.Integer, db.ForeignKey('lote.id'), nullable=True)

# --- Rotas da Aplicação ---

# MODIFICADA: Rota principal agora separa por status
@app.route('/')
def index():
    # Dicionários para guardar os produtos e lotes separados por status
    produtos_pendentes = defaultdict(list)
    lotes_em_andamento = Lote.query.filter_by(status='Em Andamento').order_by(Lote.data_criacao.desc()).all()
    lotes_finalizados = Lote.query.filter_by(status='Finalizado').order_by(Lote.data_criacao.desc()).all()
    
    # Busca apenas produtos com status 'Pendente' para agrupar por fornecedor
    pendentes_query = ProdutoAvariado.query.filter_by(status='Pendente').order_by(ProdutoAvariado.data_entrada).all()
    for produto in pendentes_query:
        produtos_pendentes[produto.fornecedor].append(produto)

    return render_template(
        'index.html',
        produtos_pendentes=produtos_pendentes,
        lotes_em_andamento=lotes_em_andamento,
        lotes_finalizados=lotes_finalizados
    )

# Rota de adicionar produto (sem alterações da Fase 1)
@app.route('/adicionar', methods=['POST'])
def adicionar_produto():
    # ... (código igual ao da Fase 1) ...
    sku = request.form.get('sku')
    nome_produto = request.form.get('nome_produto')
    modelo = request.form.get('modelo')
    fornecedor = request.form.get('fornecedor')
    ean = request.form.get('ean')
    descricao_avaria = request.form.get('descricao_avaria')
    novo_produto = ProdutoAvariado(
        sku=sku, nome_produto=nome_produto, modelo=modelo, fornecedor=fornecedor,
        ean=ean, descricao_avaria=descricao_avaria
    )
    db.session.add(novo_produto)
    db.session.commit()
    return redirect(url_for('index'))


# NOVA ROTA: Para criar um lote de garantia
@app.route('/criar_lote/<fornecedor_nome>', methods=['POST'])
def criar_lote(fornecedor_nome):
    # 1. Cria um novo lote para o fornecedor especificado
    novo_lote = Lote(fornecedor_nome=fornecedor_nome)
    db.session.add(novo_lote)
    
    # 2. Encontra todos os produtos pendentes daquele fornecedor
    produtos_para_o_lote = ProdutoAvariado.query.filter_by(
        fornecedor=fornecedor_nome, status='Pendente'
    ).all()
    
    # 3. Associa cada produto ao novo lote e muda o seu status
    for produto in produtos_para_o_lote:
        produto.lote = novo_lote
        produto.status = 'Em Andamento'
        
    # 4. Salva todas as alterações na base de dados
    db.session.commit()
    
    return redirect(url_for('index'))

# Rota para gerar etiqueta (sem alterações da Fase 1)
@app.route('/etiqueta/<int:id_produto>')
def gerar_etiqueta(id_produto):
    produto = ProdutoAvariado.query.get_or_404(id_produto)
    return render_template('etiqueta.html', produto=produto)

# --- Execução da Aplicação ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)