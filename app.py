# app.py
import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from collections import defaultdict
import datetime

basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'produtos.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'chave_secreta_para_mensagens'
db = SQLAlchemy(app)

class Lote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fornecedor_nome = db.Column(db.String(100), nullable=False)
    tipo_lote = db.Column(db.String(50), nullable=False)
    data_criacao = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    status = db.Column(db.String(50), default='Em Andamento')
    tipo_resolucao = db.Column(db.String(100))
    nf_tipo = db.Column(db.String(50))
    nf_numero = db.Column(db.String(200))
    produtos = db.relationship('ProdutoAvariado', backref='lote', lazy=True)

class ProdutoAvariado(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(80), nullable=False)
    nome_produto = db.Column(db.String(200), nullable=False)
    modelo = db.Column(db.String(100))
    fornecedor = db.Column(db.String(100), nullable=False)
    tipo = db.Column(db.String(50))
    descricao_avaria = db.Column(db.Text)
    data_entrada = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    status = db.Column(db.String(50), default='Pendente')
    etiqueta_impressa = db.Column(db.Boolean, default=False)
    lote_id = db.Column(db.Integer, db.ForeignKey('lote.id'), nullable=True)

@app.route('/')
def index():
    produtos_pendentes = defaultdict(list)
    pendentes_query = ProdutoAvariado.query.filter_by(status='Pendente').all()
    for p in pendentes_query:
        produtos_pendentes[(p.fornecedor, p.tipo)].append(p)
    
    lotes_andamento = Lote.query.filter_by(status='Em Andamento').all()
    lotes_aguardando = Lote.query.filter_by(status='Aguardando Resultado').all()
    lotes_finalizados = Lote.query.filter_by(status='Finalizado').all()
    
    return render_template('index.html', 
                           produtos_pendentes=produtos_pendentes, 
                           lotes_andamento=lotes_andamento,
                           lotes_aguardando=lotes_aguardando,
                           lotes_finalizados=lotes_finalizados)

@app.route('/adicionar', methods=['POST'])
def adicionar():
    novo = ProdutoAvariado(
        sku=request.form.get('sku'),
        nome_produto=request.form.get('nome_produto'),
        modelo=request.form.get('modelo'),
        fornecedor=request.form.get('fornecedor'),
        tipo=request.form.get('tipo'),
        descricao_avaria=request.form.get('descricao_avaria')
    )
    db.session.add(novo)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/criar_lote/<fornecedor_nome>/<tipo_lote>', methods=['POST'])
def criar_lote(fornecedor_nome, tipo_lote):
    novo_lote = Lote(fornecedor_nome=fornecedor_nome, tipo_lote=tipo_lote)
    db.session.add(novo_lote)
    db.session.flush()
    produtos = ProdutoAvariado.query.filter_by(fornecedor=fornecedor_nome, tipo=tipo_lote, status='Pendente').all()
    for p in produtos:
        p.lote_id = novo_lote.id
        p.status = 'Em Andamento'
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/resolver_lote/<int:lote_id>', methods=['POST'])
def resolver_lote(lote_id):
    lote = Lote.query.get_or_404(lote_id)
    lote.tipo_resolucao = request.form.get('tipo_resolucao')
    lote.nf_tipo = request.form.get('nf_tipo')
    lote.nf_numero = request.form.get('nf_numero')
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/enviar_para_resultado/<int:lote_id>', methods=['POST'])
def enviar_para_resultado(lote_id):
    lote = Lote.query.get_or_404(lote_id)
    if not lote.tipo_resolucao:
        flash("Erro: Defina a resolução do lote antes de enviar!")
        return redirect(url_for('index'))
    lote.status = 'Aguardando Resultado'
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/concluir_lote_final/<int:lote_id>', methods=['POST'])
def concluir_lote_final(lote_id):
    lote = Lote.query.get_or_404(lote_id)
    
    # Mapa de tradução para status final resolvido
    resolvido_map = {
        'Aguardando Pagamento': 'Crédito recebido',
        'Aguardando Troca': 'Troca realizada',
        'Aguardando Embalagem': 'Embalagens recebidas',
        'Sem Garantia / Descarte': 'Descartado / Colocado à venda'
    }
    lote.tipo_resolucao = resolvido_map.get(lote.tipo_resolucao, lote.tipo_resolucao)
    lote.status = 'Finalizado'
    for p in lote.produtos:
        p.status = 'Finalizado'
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/resetar_lote/<int:lote_id>', methods=['POST'])
def resetar_lote(lote_id):
    lote = Lote.query.get_or_404(lote_id)
    for p in lote.produtos:
        p.status = 'Pendente'
        p.lote_id = None
    db.session.delete(lote)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/imprimir_etiquetas', methods=['POST'])
def imprimir_etiquetas():
    ids_selecionados = request.form.getlist('produtos_ids')
    formato = request.form.get('formato', 'zebra_pequena')
    if not ids_selecionados:
        flash("Selecione pelo menos um produto!")
        return redirect(url_for('index'))
    produtos = ProdutoAvariado.query.filter(ProdutoAvariado.id.in_(ids_selecionados)).all()
    for p in produtos:
        p.etiqueta_impressa = True
    db.session.commit()
    return render_template('etiquetas_multiplas.html', produtos=produtos, formato=formato)

@app.route('/lote/<int:lote_id>')
def detalhes_lote(lote_id):
    lote = Lote.query.get_or_404(lote_id)
    return render_template('relatorio_lote.html', lote=lote)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)