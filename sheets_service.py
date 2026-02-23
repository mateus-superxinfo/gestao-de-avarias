import gspread
from oauth2client.service_account import ServiceAccountCredentials
import datetime

# Configuração da conexão
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
client = gspread.authorize(creds)

def registrar_no_sheets(nome_planilha, dados):
    """
    nome_planilha: O título exato da sua planilha no Google
    dados: Uma lista com os valores das colunas (ex: ['Mateus', 'Tarefa X', '23/02/2026'])
    """
    try:
        sheet = client.open(nome_planilha).sheet1
        sheet.append_row(dados)
        return True
    except Exception as e:
        print(f"Erro ao enviar para o Sheets: {e}")
        return False