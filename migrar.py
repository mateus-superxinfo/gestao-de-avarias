import sqlite3
import os

# Caminho do seu banco de dados
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'produtos.db')

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Adiciona as colunas que faltam na tabela existente
    cursor.execute("ALTER TABLE pendencia_logistica ADD COLUMN marketplace VARCHAR(100)")
    cursor.execute("ALTER TABLE pendencia_logistica ADD COLUMN protocolo VARCHAR(100)")
    cursor.execute("ALTER TABLE pendencia_logistica ADD COLUMN codigo_rastreio VARCHAR(100)")
    conn.commit()
    print("✅ Colunas adicionadas com sucesso!")
except sqlite3.OperationalError as e:
    print(f"⚠️ Aviso: {e} (Provavelmente as colunas já existem ou a tabela não foi encontrada)")
finally:
    conn.close()