# app.py
import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from collections import defaultdict
from sqlalchemy import func
import datetime

basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'produtos.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'chave_secreta_avarias'

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- MODELOS ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True)
    password = db.Column(db.String(100), nullable=False)
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    role = db.Column(db.String(20), default='operador')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    due_date = db.Column(db.Date, default=datetime.date.today)
    recurrence = db.Column(db.String(20)) 
    is_completed = db.Column(db.Boolean, default=False)
    completion_date = db.Column(db.Date, nullable=True) # Para sumir no dia seguinte
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    postpone_log = db.Column(db.Text)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    role_target = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

# --- TABELA DE ASSOCIAÇÃO DE PARTICIPANTES ---
ticket_participants = db.Table('ticket_participants',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('ticket_id', db.Integer, db.ForeignKey('ticket.id'), primary_key=True)
)

class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default='Aberto')
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    
    # Relações
    creator = db.relationship('User', foreign_keys=[created_by], backref='tickets_criados')
    participants = db.relationship('User', secondary=ticket_participants, backref='tickets_participando')
    messages = db.relationship('TicketMessage', backref='ticket', lazy=True, cascade="all, delete-orphan")

class TicketMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'))
    author = db.relationship('User', backref='messages_sent', lazy=True)

class Lote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fornecedor_nome = db.Column(db.String(100), nullable=False)
    tipo_lote = db.Column(db.String(50), nullable=False)
    data_criacao = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    status = db.Column(db.String(50), default='Em Andamento')
    tipo_resolucao = db.Column(db.String(100))
    nf_tipo = db.Column(db.String(50)) # Ex: Devolução, Remessa
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
    lote_id = db.Column(db.Integer, db.ForeignKey('lote.id'))
    pedido = db.Column(db.String(50))

@app.context_processor
def inject_unread():
    """Torna a variável 'unread' disponível em todos os templates automaticamente"""
    if current_user.is_authenticated:
        # Conta notificações não lidas para o usuário ou para o cargo (gestor)
        count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        if current_user.role == 'gestor':
            count += Notification.query.filter_by(role_target='gestor', is_read=False).count()
        return dict(unread=count)
    return dict(unread=0)

# --- PROCESSADOR DE CONTEXTO (CORRIGE O ERRO UNREAD) ---

@app.context_processor
def inject_unread():
    """Torna a variável 'unread' disponível em todos os templates"""
    if current_user.is_authenticated:
        count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        if current_user.role == 'gestor':
            count += Notification.query.filter_by(role_target='gestor', is_read=False).count()
        return dict(unread=count)
    return dict(unread=0)

# --- AUXILIARES ---

def calcular_proxima_data(data_atual, recorrencia):
    if recorrencia == 'diaria':
        proxima = data_atual + datetime.timedelta(days=1)
        while proxima.weekday() > 4: # Pula Sábado e Domingo
            proxima += datetime.timedelta(days=1)
        return proxima
    elif recorrencia == 'semanal':
        return data_atual + datetime.timedelta(weeks=1)
    elif recorrencia == 'mensal':
        return data_atual + datetime.timedelta(days=30)
    return None

# --- ROTAS ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user)
            return redirect(url_for('home'))
        flash('Login inválido!')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- ROTAS DE GESTÃO DE UTILIZADORES ---

@app.route('/usuarios', methods=['GET', 'POST'])
@login_required
def gerir_usuarios():
    if current_user.role != 'gestor':
        flash("Acesso negado!")
        return redirect(url_for('home'))

    if request.method == 'POST':
        hashed_pw = generate_password_hash(request.form.get('password'))
        novo_u = User(
            username=request.form.get('username'),
            email=request.form.get('email'), # Captura e-mail
            password=hashed_pw,
            first_name=request.form.get('first_name'),
            last_name=request.form.get('last_name'),
            role=request.form.get('role')
        )
        db.session.add(novo_u)
        db.session.commit()
        flash(f"Usuário {novo_u.first_name} cadastrado!")

    usuarios = User.query.all()
    return render_template('usuarios.html', usuarios=usuarios)

@app.route('/usuarios/editar/<int:user_id>', methods=['POST'])
@login_required
def editar_usuario(user_id):
    if current_user.role != 'gestor': return redirect(url_for('home'))
    
    u = User.query.get_or_404(user_id)
    u.first_name = request.form.get('first_name')
    u.last_name = request.form.get('last_name')
    u.email = request.form.get('email') # Atualiza e-mail
    u.role = request.form.get('role')
    
    nova_senha = request.form.get('password')
    if nova_senha:
        u.password = generate_password_hash(nova_senha)
        
    db.session.commit()
    flash("Dados atualizados com sucesso.")
    return redirect(url_for('gerir_usuarios'))

@app.route('/usuarios/excluir/<int:user_id>', methods=['POST'])
@login_required
def excluir_usuario(user_id):
    if current_user.role != 'gestor': return redirect(url_for('home'))
    
    # Impede que o usuário se exclua acidentalmente
    if user_id == current_user.id:
        flash("Você não pode excluir sua própria conta!")
        return redirect(url_for('gerir_usuarios'))
        
    u = User.query.get_or_404(user_id)
    db.session.delete(u)
    db.session.commit()
    flash("Usuário removido do sistema.")
    return redirect(url_for('gerir_usuarios'))

@app.route('/home')
@login_required
def home():
    hoje = datetime.date.today()
    # Mostra pendentes de hoje/atrasadas OU as que foram concluídas HOJE
    tarefas = Task.query.filter(
        Task.assigned_to == current_user.id,
        db.or_(
            db.and_(Task.is_completed == False, Task.due_date <= hoje),
            db.and_(Task.is_completed == True, Task.completion_date == hoje)
        )
    ).order_by(Task.is_completed, Task.due_date).all()
    
    usuarios = User.query.all() if current_user.role == 'gestor' else []
    return render_template('home.html', tarefas=tarefas, hoje=hoje, usuarios=usuarios)

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'gestor':
        return redirect(url_for('home'))

    # KPIs Gerais
    total_tarefas = Task.query.count()
    tarefas_concluidas = Task.query.filter_by(is_completed=True).count()
    total_avarias = ProdutoAvariado.query.count()
    itens_pendentes = ProdutoAvariado.query.filter_by(status='Pendente').count()

    # 1. Ranking de Operadores (Tarefas Concluídas)
    ranking_operadores = db.session.query(
        User.first_name, func.count(Task.id)
    ).join(Task, Task.assigned_to == User.id).filter(Task.is_completed == True).group_by(User.id).all()

    # 2. Ranking de Fornecedores
    ranking_fornecedores = db.session.query(
        ProdutoAvariado.fornecedor, func.count(ProdutoAvariado.id)
    ).group_by(ProdutoAvariado.fornecedor).order_by(func.count(ProdutoAvariado.id).desc()).limit(5).all()

    # 3. Produtos com Maior % de Problemas
    ranking_produtos = db.session.query(
        ProdutoAvariado.nome_produto, func.count(ProdutoAvariado.id)
    ).group_by(ProdutoAvariado.sku).order_by(func.count(ProdutoAvariado.id).desc()).limit(5).all()

    return render_template('dashboard.html', 
                           tarefas_total=total_tarefas,
                           tarefas_concluidas=tarefas_concluidas,
                           avarias_total=total_avarias,
                           itens_pendentes=itens_pendentes,
                           ranking_ops=ranking_operadores,
                           ranking_forn=ranking_fornecedores,
                           ranking_prod=ranking_produtos)

# --- ÁREA DE GESTÃO DE DADOS (EXCLUSÃO) ---

@app.route('/limpeza_dados')
@login_required
def limpeza_dados():
    if current_user.role != 'gestor':
        return redirect(url_for('home'))
    
    # Agora buscamos TODAS as tarefas (pendentes e concluídas)
    tarefas = Task.query.order_by(Task.is_completed, Task.due_date).all()
    # Buscamos TODOS os chamados
    chamados = Ticket.query.order_by(Ticket.created_at.desc()).all()
    lotes_finalizados = Lote.query.filter_by(status='Finalizado').all()
    usuarios = User.query.filter(User.id != current_user.id).all()
    
    return render_template('limpeza_dados.html', 
                           usuarios=usuarios, 
                           tarefas=tarefas, 
                           chamados=chamados,
                           lotes=lotes_finalizados)

@app.route('/excluir_tarefa_geral/<int:id>', methods=['POST'])
@login_required
def excluir_tarefa_geral(id):
    if current_user.role == 'gestor':
        t = Task.query.get_or_404(id)
        nome = t.title
        db.session.delete(t)
        db.session.commit()
        flash(f"Tarefa '{nome}' e suas recorrências futuras foram removidas.")
    return redirect(url_for('limpeza_dados'))

@app.route('/excluir_chamado_definitivo/<int:id>', methods=['POST'])
@login_required
def excluir_chamado_definitivo(id):
    if current_user.role == 'gestor':
        chamado = Ticket.query.get_or_404(id)
        # O SQLAlchemy cuidará de remover mensagens e participantes associados
        db.session.delete(chamado)
        db.session.commit()
        flash(f"Chamado #{id} excluído permanentemente.")
    return redirect(url_for('limpeza_dados'))

@app.route('/tarefas_futuras')
@login_required
def tarefas_futuras():
    hoje = datetime.date.today()
    proxima_semana = hoje + datetime.timedelta(days=7)
    tarefas = Task.query.filter(
        Task.assigned_to == current_user.id,
        Task.is_completed == False,
        Task.due_date > hoje,
        Task.due_date <= proxima_semana
    ).order_by(Task.due_date).all()
    return render_template('tarefas_futuras.html', tarefas=tarefas)

@app.route('/notificacoes')
@login_required
def notificacoes():
    avisos = Notification.query.filter(
        db.or_(Notification.user_id == current_user.id, Notification.role_target == current_user.role)
    ).order_by(Notification.created_at.desc()).all()
    # Marca como lidas ao abrir a página
    for n in avisos:
        n.is_read = True
    db.session.commit()
    return render_template('notificacoes.html', avisos=avisos)

@app.route('/ticar_tarefa/<int:task_id>')
@login_required
def ticar_tarefa(task_id):
    tarefa = Task.query.get_or_404(task_id)
    hoje = datetime.date.today()
    if tarefa.assigned_to == current_user.id:
        tarefa.is_completed = True
        tarefa.completion_date = hoje
        
        # Gerar recorrência
        if tarefa.recurrence != 'nenhuma':
            proxima = calcular_proxima_data(tarefa.due_date, tarefa.recurrence)
            nova = Task(title=tarefa.title, description=tarefa.description, due_date=proxima,
                        recurrence=tarefa.recurrence, assigned_to=tarefa.assigned_to, created_by=current_user.id)
            db.session.add(nova)
            
        # Notificar gestor da conclusão total do dia
        restantes = Task.query.filter_by(assigned_to=current_user.id, is_completed=False, due_date=hoje).count()
        if restantes == 0:
            aviso = Notification(message=f"✅ {current_user.username} concluiu as tarefas de hoje.", role_target='gestor')
            db.session.add(aviso)
            
        db.session.commit()
    return redirect(url_for('home'))

@app.route('/criar_tarefa', methods=['POST'])
@login_required
def criar_tarefa():
    nova_tarefa = Task(
        title=request.form.get('title'),
        description=request.form.get('description'),
        due_date=datetime.datetime.strptime(request.form.get('due_date'), '%Y-%m-%d').date(),
        recurrence=request.form.get('recurrence'),
        assigned_to=request.form.get('assigned_to'),
        created_by=current_user.id
    )
    db.session.add(nova_tarefa)
    # Notifica se não for diária
    if nova_tarefa.recurrence != 'diaria':
        aviso = Notification(message=f"🆕 Tarefa: {nova_tarefa.title}", user_id=nova_tarefa.assigned_to)
        db.session.add(aviso)
    db.session.commit()
    return redirect(url_for('home'))

@app.route('/prorrogar_tarefa/<int:task_id>', methods=['POST'])
@login_required
def prorrogar_tarefa(task_id):
    tarefa = Task.query.get_or_404(task_id)
    nova_data_str = request.form.get('nova_data')
    motivo = request.form.get('motivo')
    
    if nova_data_str:
        # Converte a string da data para objeto date do Python
        tarefa.due_date = datetime.datetime.strptime(nova_data_str, '%Y-%m-%d').date()
        
        # Registra o motivo no histórico de adiamentos
        data_hoje = datetime.date.today().strftime('%d/%m/%Y')
        log_entry = f"Adiado em {data_hoje}: {motivo}\n"
        
        if tarefa.postpone_log:
            tarefa.postpone_log += log_entry
        else:
            tarefa.postpone_log = log_entry
            
        db.session.commit()
        flash(f"Tarefa '{tarefa.title}' adiada com sucesso!")
    
    return redirect(url_for('home'))

@app.route('/abrir_chamado', methods=['POST'])
@login_required
def abrir_chamado():
    novo_ticket = Ticket(
        subject=request.form.get('subject'),
        created_by=current_user.id
    )
    # Adiciona os participantes selecionados
    participantes_ids = request.form.getlist('participantes')
    for uid in participantes_ids:
        user_p = User.query.get(uid)
        if user_p:
            novo_ticket.participants.append(user_p)
            # Notifica cada participante
            db.session.add(Notification(message=f"🎫 Novo chamado: {novo_ticket.subject}", user_id=user_p.id))
    
    db.session.add(novo_ticket)
    db.session.flush()
    
    msg = TicketMessage(content=request.form.get('content'), user_id=current_user.id, ticket_id=novo_ticket.id)
    db.session.add(msg)
    db.session.commit()
    return redirect(url_for('ver_chamado', ticket_id=novo_ticket.id))

@app.route('/chamados/<int:ticket_id>/gerir_participante', methods=['POST'])
@login_required
def gerir_participante(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    user_id = request.form.get('user_id')
    acao = request.form.get('acao') # 'add' ou 'remove'
    
    user = User.query.get(user_id)
    if user:
        if acao == 'add' and user not in ticket.participants:
            ticket.participants.append(user)
            db.session.add(Notification(message=f"📌 Adicionado ao chamado: {ticket.subject}", user_id=user.id))
        elif acao == 'remove' and user in ticket.participants:
            ticket.participants.remove(user)
            
    db.session.commit()
    return redirect(url_for('ver_chamado', ticket_id=ticket_id))

@app.route('/chamados')
@login_required
def chamados():
    # Mostra chamados onde o usuário é o criador OU um dos participantes
    todos = Ticket.query.join(Ticket.participants, isouter=True).filter(
        db.or_(Ticket.created_by == current_user.id, User.id == current_user.id)
    ).distinct().order_by(Ticket.created_at.desc()).all()
    
    usuarios = User.query.filter(User.id != current_user.id).all()
    return render_template('chamados.html', chamados=todos, ticket=None, usuarios=usuarios)

@app.route('/chamados/<int:ticket_id>')
@login_required
def ver_chamado(ticket_id):
    todos = Ticket.query.join(Ticket.participants, isouter=True).filter(
        db.or_(Ticket.created_by == current_user.id, User.id == current_user.id)
    ).distinct().order_by(Ticket.created_at.desc()).all()
    
    selecionado = Ticket.query.get_or_404(ticket_id)
    usuarios_sistema = User.query.filter(User.id != current_user.id).all()
    return render_template('chamados.html', chamados=todos, ticket=selecionado, usuarios=usuarios_sistema)

@app.route('/responder_chamado/<int:ticket_id>', methods=['POST'])
@login_required
def responder_chamado(ticket_id):
    conteudo = request.form.get('content')
    if conteudo:
        nova_msg = TicketMessage(content=conteudo, user_id=current_user.id, ticket_id=ticket_id)
        db.session.add(nova_msg)
        db.session.commit()
    return redirect(url_for('ver_chamado', ticket_id=ticket_id))

@app.route('/fechar_chamado/<int:ticket_id>', methods=['POST'])
@login_required
def fechar_chamado(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    ticket.status = 'Fechado'
    db.session.commit()
    return redirect(url_for('chamados'))

@app.route('/avarias')
@login_required
def avarias():
    agora = datetime.datetime.utcnow()
    def calcular_dias(data_ref):
        return (agora - data_ref).days if data_ref else 0
    produtos_pendentes = defaultdict(list)
    pendentes_query = ProdutoAvariado.query.filter_by(status='Pendente').all()
    for p in pendentes_query:
        produtos_pendentes[(p.fornecedor, p.tipo)].append(p)
    lotes_andamento = Lote.query.filter_by(status='Em Andamento').all()
    lotes_aguardando = Lote.query.filter_by(status='Aguardando Resultado').all()
    lotes_finalizados = Lote.query.filter_by(status='Finalizado').all()
    return render_template('avarias.html', produtos_pendentes=produtos_pendentes, lotes_andamento=lotes_andamento,
                           lotes_aguardando=lotes_aguardando, lotes_finalizados=lotes_finalizados, calcular_dias=calcular_dias)

@app.route('/adicionar', methods=['POST'])
@login_required
def adicionar():
    # Captura o fornecedor e aplica a blindagem (Maiúsculas + Limpeza de espaços)
    fornecedor_raw = request.form.get('fornecedor')
    fornecedor_blindado = fornecedor_raw.strip().upper() if fornecedor_raw else ""

    novo = ProdutoAvariado(
        sku=request.form.get('sku'),
        nome_produto=request.form.get('nome_produto'),
        modelo=request.form.get('modelo'),
        fornecedor=fornecedor_blindado, # Salva sempre padronizado
        tipo=request.form.get('tipo'), 
        descricao_avaria=request.form.get('descricao_avaria'),
        pedido=request.form.get('pedido')
    )
    db.session.add(novo)
    db.session.commit()
    flash("Item registado com sucesso!")
    return redirect(url_for('avarias'))

@app.route('/excluir_produto/<int:produto_id>', methods=['POST'])
@login_required
def excluir_produto(produto_id):
    # Trava de segurança: apenas gestores podem excluir
    if current_user.role != 'gestor':
        flash("Erro: Apenas gestores podem excluir produtos.")
        return redirect(url_for('avarias'))
    
    produto = ProdutoAvariado.query.get_or_404(produto_id)
    db.session.delete(produto)
    db.session.commit()
    
    flash(f"Produto {produto.sku} excluído com sucesso.")
    return redirect(url_for('avarias'))

@app.route('/concluir_lote_final/<int:lote_id>', methods=['POST'])
@login_required
def concluir_lote_final(lote_id):
    lote = Lote.query.get_or_404(lote_id)
    resolvido_map = {'Aguardando Pagamento': 'Crédito recebido', 'Aguardando Troca': 'Troca realizada',
                     'Aguardando Embalagem': 'Embalagens recebidas', 'Sem Garantia / Descarte': 'Descartado / Colocado à venda'}
    lote.tipo_resolucao = resolvido_map.get(lote.tipo_resolucao, lote.tipo_resolucao)
    lote.status = 'Finalizado'
    for p in lote.produtos: p.status = 'Finalizado'
    db.session.commit()
    return redirect(url_for('avarias'))

@app.route('/')
def index():
    return redirect(url_for('home'))

# --- ROTAS DE GESTÃO DE AVARIAS (RESTAURAÇÃO) ---

@app.route('/criar_lote/<fornecedor_nome>/<tipo_lote>', methods=['POST'])
@login_required
def criar_lote(fornecedor_nome, tipo_lote):
    # Agrupa produtos pendentes em um novo lote para tratativa
    novo_lote = Lote(fornecedor_nome=fornecedor_nome, tipo_lote=tipo_lote)
    db.session.add(novo_lote)
    db.session.flush()
    
    produtos = ProdutoAvariado.query.filter_by(
        fornecedor=fornecedor_nome, tipo=tipo_lote, status='Pendente'
    ).all()
    
    for p in produtos:
        p.lote_id = novo_lote.id
        p.status = 'Em Andamento'
    
    db.session.commit()
    flash(f"Lote de {fornecedor_nome} criado com sucesso!")
    return redirect(url_for('avarias'))

@app.route('/resolver_lote/<int:lote_id>', methods=['POST'])
@login_required
def resolver_lote(lote_id):
    lote = Lote.query.get_or_404(lote_id)
    lote.nf_tipo = request.form.get('nf_tipo')
    lote.nf_numero = request.form.get('nf_numero')
    lote.tipo_resolucao = request.form.get('tipo_resolucao')
    db.session.commit()
    flash("Informações do Lote #{} atualizadas!".format(lote_id))
    return redirect(url_for('avarias'))

@app.route('/enviar_para_resultado/<int:lote_id>', methods=['POST'])
@login_required
def enviar_para_resultado(lote_id):
    lote = Lote.query.get_or_404(lote_id)
    if not lote.tipo_resolucao or not lote.nf_numero:
        flash("Preencha a NF e a Resolução antes de enviar!")
        return redirect(url_for('avarias'))
    
    lote.status = 'Aguardando Resultado'
    db.session.commit()
    flash("Lote #{} enviado para aguardar resultado.".format(lote_id))
    return redirect(url_for('avarias'))

@app.route('/resetar_lote/<int:lote_id>', methods=['POST'])
@login_required
def resetar_lote(lote_id):
    # Desmancha o lote e devolve os itens para pendentes
    lote = Lote.query.get_or_404(lote_id)
    for p in lote.produtos:
        p.status = 'Pendente'
        p.lote_id = None
    db.session.delete(lote)
    db.session.commit()
    return redirect(url_for('avarias'))

@app.route('/imprimir_etiquetas', methods=['POST'])
@login_required
def imprimir_etiquetas():
    # Captura os produtos selecionados e o formato escolhido
    ids_selecionados = request.form.getlist('produtos_ids')
    formato = request.form.get('formato')
    
    if not ids_selecionados:
        flash("Selecione itens para imprimir!")
        return redirect(url_for('avarias'))
        
    produtos = ProdutoAvariado.query.filter(ProdutoAvariado.id.in_(ids_selecionados)).all()
    
    # Passamos o formato para o template decidir o layout
    return render_template('etiquetas_multiplas.html', produtos=produtos, formato=formato)

@app.route('/detalhes_lote/<int:lote_id>')
@login_required
def detalhes_lote(lote_id):
    # Gera o romaneio/relatório do lote em A4
    lote = Lote.query.get_or_404(lote_id)
    return render_template('relatorio_lote.html', lote=lote)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)