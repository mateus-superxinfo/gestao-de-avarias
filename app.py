# app.py
import os
import datetime
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import locale
try:
    locale.setlocale(locale.LC_TIME, "pt_BR.utf8")
except:
    locale.setlocale(locale.LC_TIME, "Portuguese_Brazil.1252")
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename 
from sqlalchemy import func
from collections import defaultdict

# 1. Primeiro defina as bases
basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)

# 2. Agora configure as pastas (UPLOAD_FOLDER agora reconhece o basedir)
UPLOAD_FOLDER = os.path.join(basedir, 'static/uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True) 

# 3. Restante das configurações
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'produtos.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'chave_secreta_avarias'

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'docx', 'xlsx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
    return db.session.get(User, int(user_id))

# Use o ID que aparece na URL da sua planilha (entre o /d/ e o /edit)
ID_PLANILHA_VENDAS = "11nUeM2qQE17qBqwOMONvpf3M58SGVBOvlhjQy0F8yzs"
ID_PLANILHA_DEV = "1XgMctfNN9nF9_5KczuWdRsv8-dD7Yf80cJ7__En6p-Y"

def get_sheets_data():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    client = gspread.authorize(creds)
    
    # Abrir pelo ID é muito mais seguro que pelo nome
    sheet_vendas = client.open_by_key(ID_PLANILHA_VENDAS).sheet1
    sheet_dev = client.open_by_key(ID_PLANILHA_DEV).sheet1
    
    return sheet_vendas, sheet_dev

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
    due_date = db.Column(db.Date, nullable=True) # Nova coluna
    
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
    attachment = db.Column(db.String(255), nullable=True)
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

class PendenciaLogistica(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50), nullable=False)
    pedido_id = db.Column(db.String(50), nullable=False)
    marketplace = db.Column(db.String(100))
    protocolo = db.Column(db.String(100))
    codigo_rastreio = db.Column(db.String(100)) # NOVO: Para remessas ou flex
    data_notificacao = db.Column(db.Date, default=datetime.date.today)
    prazo_limite = db.Column(db.Date) # Agora definido manualmente no cadastro
    status = db.Column(db.String(20), default='Pendente')
    observacao = db.Column(db.Text)

# 1. Primeiro CRIAMOS o admin (sem o template_mode para evitar o erro anterior)
admin = Admin(app, name='LogiControl Admin') 

# 2. Depois ADICIONAMOS as tabelas (Views)
admin.add_view(ModelView(User, db.session))
admin.add_view(ModelView(Task, db.session))
admin.add_view(ModelView(ProdutoAvariado, db.session))
admin.add_view(ModelView(Lote, db.session))
admin.add_view(ModelView(Ticket, db.session))

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

# Função auxiliar para limpar valores monetários brasileiros
def limpar_valor(valor):
    if not valor: return 0.0
    if isinstance(valor, (int, float)): return float(valor)
    # Remove R$, pontos de milhar e troca vírgula por ponto
    texto = str(valor).replace('R$', '').replace('.', '').replace(',', '.').strip()
    try:
        return float(texto)
    except:
        return 0.0

@app.route('/home')
@login_required
def home():
    hoje = datetime.date.today()
    mes_atual_str = hoje.strftime('%m/%Y')
    # Calcula o mês anterior (Jan/2026 se estivermos em Fev/2026)
    mes_anterior_data = hoje.replace(day=1) - datetime.timedelta(days=1)
    mes_anterior_str = mes_anterior_data.strftime('%m/%Y')
    
    fin = {}

    if current_user.role == 'gestor':
        try:
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
            client = gspread.authorize(creds)
            
            planilha_vendas = client.open_by_key(ID_PLANILHA_VENDAS)
            df_2026 = pd.DataFrame(planilha_vendas.worksheet("Diário 2026").get_all_records())
            df_2025 = pd.DataFrame(planilha_vendas.worksheet("Diário 2025").get_all_records())

            # Limpeza e conversão de colunas
            df_2026['Faturamento'] = df_2026['Faturamento'].apply(limpar_valor)
            df_2026['Quantidade'] = pd.to_numeric(df_2026['Quantidade'], errors='coerce').fillna(0)
            df_2025['Faturamento'] = df_2025['Faturamento'].apply(limpar_valor)
            df_2025['Quantidade'] = pd.to_numeric(df_2025['Quantidade'], errors='coerce').fillna(0)
            df_2026['Data'] = df_2026['Data'].astype(str)

            # --- PROCESSAMENTO DO MÊS ATUAL ---
            vendas_atual = df_2026[df_2026['Data'].str.contains(mes_atual_str, na=False)]
            fat_atual = vendas_atual['Faturamento'].sum()
            ped_atual = vendas_atual['Quantidade'].sum()

            # Previsão (Projeção para 30 dias com base no dia atual)
            dia_atual = hoje.day
            fat_previsto = (fat_atual / dia_atual) * 30 if dia_atual > 0 else 0
            ped_previsto = (ped_atual / dia_atual) * 30 if dia_atual > 0 else 0

            # --- PROCESSAMENTO DO MÊS ANTERIOR ---
            vendas_anterior = df_2026[df_2026['Data'].str.contains(mes_anterior_str, na=False)]
            fat_anterior = vendas_anterior['Faturamento'].sum()
            ped_anterior = vendas_anterior['Quantidade'].sum()

            # --- ACUMULADOS E COMPARATIVOS ---
            fat_acumulado_2026 = df_2026['Faturamento'].sum()
            ped_acumulado_2026 = df_2026['Quantidade'].sum()
            
            total_fat_2025 = df_2025['Faturamento'].sum()
            total_ped_2025 = df_2025['Quantidade'].sum()

            fin = {
                'faturamento': fat_atual,
                'fat_previsao': fat_previsto,
                'fat_anterior': fat_anterior,
                'fat_acumulado': fat_acumulado_2026,
                'fat_vs_2025': round((fat_acumulado_2026 / total_fat_2025 * 100), 1) if total_fat_2025 > 0 else 0,
                
                'pedidos': int(ped_atual),
                'ped_previsao': int(ped_previsto),
                'ped_anterior': int(ped_anterior),
                'ped_acumulado': int(ped_acumulado_2026),
                'ped_vs_2025': round((ped_acumulado_2026 / total_ped_2025 * 100), 1) if total_ped_2025 > 0 else 0
            }
        except Exception as e:
            print(f"Erro no processamento financeiro: {e}")

    # Consulta de tarefas (Filtro mantido)
    tarefas = Task.query.filter(
        Task.assigned_to == current_user.id,
        db.or_(
            db.and_(Task.is_completed == False, Task.due_date <= hoje),
            db.and_(Task.is_completed == True, Task.completion_date == hoje)
        )
    ).order_by(Task.is_completed, Task.due_date).all()

    # Busca contagem de alertas logísticos
    total_cancelados = PendenciaLogistica.query.filter_by(tipo='Cancelamento', status='Pendente').count()
    total_trocas = PendenciaLogistica.query.filter_by(tipo='Troca', status='Pendente').count()

    usuarios = User.query.all()

    # Lógica de verificação do backup
    last_backup_str = "Nunca"
    alerta_backup = "danger" # Cor padrão se nunca foi feito
    
    if os.path.exists("last_backup.txt"):
        with open("last_backup.txt", "r") as f:
            content = f.read().strip()
            dt_backup = datetime.datetime.strptime(content, '%Y-%m-%d %H:%M:%S')
            last_backup_str = dt_backup.strftime('%d/%m/%Y %H:%M')
            
            dias_passados = (datetime.datetime.now() - dt_backup).days
            
            if dias_passados < 3:
                alerta_backup = "success" # Verde (Recente)
            elif dias_passados < 7:
                alerta_backup = "warning" # Amarelo (Atenção)
            else:
                alerta_backup = "danger" # Vermelho (Crítico)
    
    return render_template('home.html', tarefas=tarefas, hoje=hoje, fin=fin, usuarios=usuarios, alertas_log={'cancelados': total_cancelados, 'trocas': total_trocas}, last_backup=last_backup_str, 
                           status_backup=alerta_backup)

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'gestor':
        return redirect(url_for('home'))

    hoje = datetime.date.today()
    total_avarias = ProdutoAvariado.query.count() or 1 # Evita divisão por zero
    
    # 1. KPIs Iniciais
    tarefas_concluidas = Task.query.filter_by(is_completed=True).count()
    itens_pendentes = ProdutoAvariado.query.filter_by(status='Pendente').count()

    # 2. Ranking de Operadores (Barra)
    ranking_ops = db.session.query(
        User.first_name, func.count(Task.id)
    ).join(Task, Task.assigned_to == User.id).filter(Task.is_completed == True).group_by(User.id).all()

    # 3. Ranking de Produtos com Porcentagem
    ranking_prod_raw = db.session.query(
        ProdutoAvariado.nome_produto, func.count(ProdutoAvariado.id)
    ).group_by(ProdutoAvariado.nome_produto).order_by(func.count(ProdutoAvariado.id).desc()).limit(5).all()
    
    ranking_prod = [
        {'nome': n, 'qtd': q, 'perc': round((q / total_avarias) * 100, 1)} 
        for n, q in ranking_prod_raw
    ]

    # 4. Ranking de Fornecedores com Porcentagem
    ranking_forn_raw = db.session.query(
        ProdutoAvariado.fornecedor, func.count(ProdutoAvariado.id)
    ).group_by(ProdutoAvariado.fornecedor).order_by(func.count(ProdutoAvariado.id).desc()).limit(5).all()
    
    ranking_forn = [
        {'forn': f, 'qtd': q, 'perc': round((q / total_avarias) * 100, 1)} 
        for f, q in ranking_forn_raw
    ]

    # 5. Status da Equipe (Rotinas)
    operadores = User.query.filter_by(role='operador').all()
    status_equipe = []
    for op in operadores:
        rotinas = Task.query.filter(Task.assigned_to == op.id, Task.recurrence == 'diaria', 
                                    db.or_(Task.due_date == hoje, Task.completion_date == hoje)).all()
        total = len(rotinas)
        concluidas = len([t for t in rotinas if t.is_completed])
        status_equipe.append({
            'nome': f"{op.first_name} {op.last_name}",
            'progresso': int((concluidas / total * 100)) if total > 0 else 0,
            'detalhes': rotinas
        })

    return render_template('dashboard.html', 
                           avarias_total=total_avarias, tarefas_concluidas=tarefas_concluidas,
                           itens_pendentes=itens_pendentes, ranking_ops=ranking_ops,
                           ranking_prod=ranking_prod, ranking_forn=ranking_forn,
                           status_equipe=status_equipe, hoje=hoje)

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
    subject = request.form.get('subject')
    content = request.form.get('content')
    due_date_str = request.form.get('due_date')
    
    # Converte a data se existir
    due_date = None
    if due_date_str:
        due_date = datetime.datetime.strptime(due_date_str, '%Y-%m-%d').date()

    novo_ticket = Ticket(subject=subject, created_by=current_user.id, due_date=due_date)
    
    # Participantes
    participantes_ids = request.form.getlist('participantes')
    for uid in participantes_ids:
        user_p = User.query.get(uid)
        if user_p:
            novo_ticket.participants.append(user_p)
            db.session.add(Notification(message=f"🎫 Novo chamado: {subject}", user_id=user_p.id))
    
    db.session.add(novo_ticket)
    db.session.flush() # Gera o ID do ticket antes de salvar o arquivo

    # --- LOGICA DE ANEXO (Faltava isto!) ---
    file = request.files.get('attachment')
    filename = None
    if file and allowed_file(file.filename):
        # Cria um nome único: t[ID_TICKET]_[NOME_ARQUIVO]
        filename = secure_filename(f"t{novo_ticket.id}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    # Guardamos a mensagem com a referência ao arquivo (attachment)
    msg = TicketMessage(
        content=content, 
        user_id=current_user.id, 
        ticket_id=novo_ticket.id, 
        attachment=filename # Agora salva o nome do arquivo no banco
    )
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
    hoje = datetime.date.today()
    # Mostra chamados onde o usuário é o criador OU um dos participantes
    todos = Ticket.query.join(Ticket.participants, isouter=True).filter(
        db.or_(Ticket.created_by == current_user.id, User.id == current_user.id)
    ).distinct().order_by(Ticket.created_at.desc()).all()
    
    usuarios = User.query.filter(User.id != current_user.id).all()
    return render_template('chamados.html', chamados=todos, ticket=None, usuarios=usuarios, hoje=hoje)

@app.route('/chamados/<int:ticket_id>')
@login_required
def ver_chamado(ticket_id):
    hoje = datetime.date.today()
    todos = Ticket.query.join(Ticket.participants, isouter=True).filter(
        db.or_(Ticket.created_by == current_user.id, User.id == current_user.id)
    ).distinct().order_by(Ticket.created_at.desc()).all()
    
    selecionado = Ticket.query.get_or_404(ticket_id)
    usuarios_sistema = User.query.filter(User.id != current_user.id).all()
    return render_template('chamados.html', chamados=todos, ticket=selecionado, usuarios=usuarios_sistema, hoje=hoje)

@app.route('/responder_chamado/<int:ticket_id>', methods=['POST'])
@login_required
def responder_chamado(ticket_id):
    conteudo = request.form.get('content')
    file = request.files.get('attachment')
    
    filename = None
    # Verifica se há arquivo na resposta
    if file and allowed_file(file.filename):
        timestamp = int(datetime.datetime.now().timestamp())
        filename = secure_filename(f"r{timestamp}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    if conteudo or filename:
        nova_msg = TicketMessage(
            content=conteudo, 
            user_id=current_user.id, 
            ticket_id=ticket_id, 
            attachment=filename # Associa o anexo à mensagem
        )
        db.session.add(nova_msg)
        db.session.commit()
    return redirect(url_for('ver_chamado', ticket_id=ticket_id))

@app.route('/alterar_prazo_chamado/<int:ticket_id>', methods=['POST'])
@login_required
def alterar_prazo_chamado(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    
    # Trava de segurança: apenas o dono ou um gestor pode alterar o prazo
    if ticket.created_by != current_user.id and current_user.role != 'gestor':
        flash("Apenas o dono do chamado pode alterar o prazo.")
        return redirect(url_for('ver_chamado', ticket_id=ticket_id))
    
    nova_data_str = request.form.get('due_date')
    if nova_data_str:
        ticket.due_date = datetime.datetime.strptime(nova_data_str, '%Y-%m-%d').date()
        # Adiciona uma mensagem automática no chat informando a alteração
        aviso = TicketMessage(
            content=f"🕒 Prazo alterado para: {ticket.due_date.strftime('%d/%m/%Y')}",
            user_id=current_user.id,
            ticket_id=ticket_id
        )
        db.session.add(aviso)
        db.session.commit()
        flash("Prazo atualizado!")
        
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

# Rota de cadastro atualizada
@app.route('/pendencias', methods=['GET', 'POST'])
@login_required
def gerenciar_pendencias():
    if request.method == 'POST':
        # Captura a data selecionada pelo usuário
        data_prazo = datetime.datetime.strptime(request.form.get('prazo_limite'), '%Y-%m-%d').date()
        
        nova_pendencia = PendenciaLogistica(
            tipo=request.form.get('tipo'),
            pedido_id=request.form.get('pedido_id'),
            marketplace=request.form.get('marketplace'), # Este captura o valor do <select>
            protocolo=request.form.get('protocolo'),
            codigo_rastreio=request.form.get('codigo_rastreio'),
            prazo_limite=data_prazo,
            observacao=request.form.get('observacao')
        )
        db.session.add(nova_pendencia)
        db.session.commit()
        flash("Pendência registrada!")
        return redirect(url_for('gerenciar_pendencias'))

    pendencias = PendenciaLogistica.query.filter_by(status='Pendente').order_by(PendenciaLogistica.prazo_limite).all()
    return render_template('pendencias.html', pendencias=pendencias, hoje=datetime.date.today())

# Rota para adiar a data de revisão
@app.route('/adiar_pendencia/<int:id>', methods=['POST'])
@login_required
def adiar_pendencia(id):
    p = PendenciaLogistica.query.get_or_404(id)
    nova_data = request.form.get('nova_data')
    if nova_data:
        p.prazo_limite = datetime.datetime.strptime(nova_data, '%Y-%m-%d').date()
        db.session.commit()
        flash("Data de revisão atualizada!")
    return redirect(url_for('gerenciar_pendencias'))

# Rota para marcar como resolvido
@app.route('/resolver_pendencia/<int:id>')
@login_required
def resolver_pendencia(id):
    p = PendenciaLogistica.query.get_or_404(id)
    p.status = 'Resolvido'
    db.session.commit()
    return redirect(url_for('gerenciar_pendencias'))

@app.route('/detalhes_lote/<int:lote_id>')
@login_required
def detalhes_lote(lote_id):
    # Gera o romaneio/relatório do lote em A4
    lote = Lote.query.get_or_404(lote_id)
    return render_template('relatorio_lote.html', lote=lote)

# app.py - Rota de Backup para Google Sheets
ID_PLANILHA_BACKUP = "15iIjdAsDNfQRmtU2aLbhjgfxEp8DWNkOcuby8xiHZVU"

def salvar_na_aba(planilha, nome_aba, df):
    if df.empty:
        return
    
    # TRATAMENTO DE ERRO: Substitui 'NaN' (nulos) por vazio para não dar erro no JSON
    df = df.fillna("") 
    
    try:
        ws = planilha.worksheet(nome_aba)
    except:
        ws = planilha.add_worksheet(title=nome_aba, rows="1000", cols="20")
    
    ws.clear()
    # Converte tudo para string ou números limpos antes de enviar
    dados = [df.columns.values.tolist()] + df.values.tolist()
    ws.update(dados)

# --- ROTA DE BACKUP COMPLETA ---
@app.route('/executar_backup')
@login_required
def executar_backup():
    if current_user.role != 'gestor':
        flash("Acesso restrito.")
        return redirect(url_for('home'))

    try:
        agora_str = datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        client = gspread.authorize(creds)
        sh = client.open_by_key(ID_PLANILHA_BACKUP)

        # 1. Pendências
        pendencias = PendenciaLogistica.query.all()
        df_pend = pd.DataFrame([{
            'ID': p.id, 'Tipo': p.tipo, 'Pedido': p.pedido_id, 'Marketplace': p.marketplace,
            'Status': p.status, 'Prazo': str(p.prazo_limite), 'Rastreio': p.codigo_rastreio,
            'Backup_Data': agora_str # Carimbo de tempo
        } for p in pendencias])
        salvar_na_aba(sh, "Pendencias", df_pend)
        time.sleep(1)

        # 2. Tarefas
        tarefas = Task.query.all()
        df_tarefas = pd.DataFrame([{
            'Tarefa': t.title, 'Status': 'Concluída' if t.is_completed else 'Pendente',
            'Data Limite': str(t.due_date), 'Responsável_ID': t.assigned_to,
            'Backup_Data': agora_str
        } for t in tarefas])
        salvar_na_aba(sh, "Tarefas", df_tarefas)
        time.sleep(1)

        # 3. Avarias (Garante que campos nulos não quebrem o código)
        produtos = ProdutoAvariado.query.all()
        df_prod = pd.DataFrame([{
            'ID': p.id, 
            'Produto': p.nome_produto or "Sem Nome", 
            'SKU': p.sku or "S/ SKU",
            'Status': p.status or "Pendente", 
            'Data Entrada': str(p.data_entrada) if p.data_entrada else "N/A", 
            'Lote_ID': p.lote_id if p.lote_id else "Avulso",
            'Pedido': p.pedido or "---"
        } for p in produtos])
        salvar_na_aba(sh, "Avarias_Produtos", df_prod)
        time.sleep(1)

        # 4. Lotes (Proteção contra lotes sem produtos)
        lotes = Lote.query.all()
        df_lotes = pd.DataFrame([{
            'Lote_ID': l.id, 
            'Fornecedor': l.fornecedor_nome or "Não Informado", 
            'Data': str(l.data_criacao) if l.data_criacao else "N/A", 
            'Status': l.status, 
            'Total Itens': len(l.produtos) if l.produtos else 0
        } for l in lotes])
        salvar_na_aba(sh, "Lotes", df_lotes)

        # 5. Equipe
        usuarios_lista = User.query.all()
        df_users = pd.DataFrame([{
            'ID': u.id, 'Nome': u.first_name, 'Email': u.email, 'Cargo': u.role,
            'Backup_Data': agora_str
        } for u in usuarios_lista])
        salvar_na_aba(sh, "Equipe", df_users)

        # AO FINAL DO SUCESSO, SALVA A DATA NUM ARQUIVO
        agora = datetime.datetime.now()
        with open("last_backup.txt", "w") as f:
            f.write(agora.strftime('%Y-%m-%d %H:%M:%S'))

        flash(f"✅ Backup TOTAL realizado com sucesso às {agora_str}!")
        
    except Exception as e:
        flash(f"❌ Erro no backup: {e}")
        print(f"ERRO DETALHADO: {e}")

    return redirect(url_for('home'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)