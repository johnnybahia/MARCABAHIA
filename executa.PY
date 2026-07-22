import pdfplumber
import re
import os
import shutil
import requests
import json
from datetime import datetime

# ================= CONFIGURAÇÃO =================
URL_WEBAPP = "https://script.google.com/macros/s/AKfycbwYOBCSEwak53AA_eXIzubyi5dHSrKL2wpAeKvogzR3MHaxIsPDOuFuRaxTL3WwLHNX/exec"

PASTA_ENTRADA = './pedidos'
PASTA_LIDOS = './pedidos/lidos'
# =================================================

def limpar_valor_monetario(texto):
    if not texto: return 0.0
    texto = texto.lower().replace('r$', '').strip().replace('.', '').replace(',', '.')
    try: return float(texto)
    except: return 0.0

def identificar_unidade(texto):
    if re.search(r'\bPAR\b', texto, re.IGNORECASE): return "PAR"
    if re.search(r'\bM\b|\bMTS\b|\bMETRO\b', texto, re.IGNORECASE): return "METRO"
    return "UNID"

def extrair_local_entrega(texto):
    texto_upper = texto.upper()
    if "NE-03" in texto_upper or "SEST" in texto_upper: return "Santo Estêvão (NE-03)"
    if "NE-08" in texto_upper or "ITABERABA" in texto_upper: return "Itaberaba (NE-08)"
    if "NE-09" in texto_upper or "VDC" in texto_upper: return "Vitória da Conquista (NE-09)"

    matches = re.findall(r'Cidade:\s*([A-Z\s]+)', texto)
    for c in matches:
        if "CRUZ DAS ALMAS" not in c.upper(): return c.strip().upper()
    return "Local Não Identificado"

def rotular_unidade_dass(fragmento):
    """Converte um trecho do PDF (cabeçalho ou endereço) na sigla curta da unidade DASS."""
    if not fragmento: return ""
    t = fragmento.upper()
    if "NE-03" in t or "SEST" in t or "SANTO ESTEVAO" in t or "SANTO ESTÊVÃO" in t: return "SANTO ESTÊVÃO"
    if "NE-08" in t or "ITABERABA" in t: return "ITABERABA"
    if "NE-09" in t or "VDC" in t or "VITORIA DA CONQUISTA" in t or "VITÓRIA DA CONQUISTA" in t: return "VITÓRIA"
    if "SANTO ANTONIO DE JESUS" in t or "SANTO ANTÔNIO DE JESUS" in t or "FL 16" in t or "NE-16" in t or "SAJ" in t: return "SANTO ANTÔNIO DE JESUS"
    return ""

def extrair_tipo_faturamento(texto):
    """
    Lê o 'Tipo de faturamento' do PDF.
    Quando for 'Conta e ordem', monta a informação completa:
        CONTA E ORDEM {ORIGEM} X {DESTINO}
    Ex.: pedido 15939277 (feito pela DASS VITÓRIA para DASS ITABERABA)
         -> "CONTA E ORDEM VITÓRIA X ITABERABA"
    """
    match_tipo = re.search(r'Tipo de faturamento:\s*([^\n]+)', texto, re.IGNORECASE)
    if not match_tipo:
        return ""
    tipo_bruto = match_tipo.group(1).strip()

    # Se não for "Conta e ordem", devolve o tipo como veio (em maiúsculas)
    if "conta e ordem" not in tipo_bruto.lower():
        return tipo_bruto.upper()

    # ORIGEM = unidade emissora do pedido (cabeçalho / quem fez o pedido)
    primeira_linha = texto.split('\n', 1)[0]
    origem = rotular_unidade_dass(primeira_linha)

    # DESTINO = destinatário final do pedido (para quem o pedido foi feito).
    # Em "conta e ordem" o "Endereço de destino" é o destinatário FINAL; o
    # "Endereço de entrega" pode ser apenas um ponto intermediário (ex.: pedido
    # 15912541 entrega em ITABERABA mas o destino final é SANTO ANTÔNIO DE JESUS).
    match_destino = re.search(r'Endereço de destino:\s*([^\n]+)', texto, re.IGNORECASE)
    destino = rotular_unidade_dass(match_destino.group(1)) if match_destino else ""
    if not destino:
        # Fallback: se não houver "Endereço de destino", usa o "Endereço de entrega"
        match_entrega = re.search(r'Endereço de entrega:\s*(.*?)(?:Endereço de destino:|CNPJ|\n)', texto, re.IGNORECASE | re.DOTALL)
        destino = rotular_unidade_dass(match_entrega.group(1)) if match_entrega else ""

    if origem and destino:
        return f"CONTA E ORDEM {origem} X {destino}"
    if origem or destino:
        return ("CONTA E ORDEM " + (origem or destino)).strip()
    return "CONTA E ORDEM"

def processar_pdf_dass(caminho_arquivo, nome_arquivo):
    try:
        with pdfplumber.open(caminho_arquivo) as pdf:
            texto_completo = ""
            for page in pdf.pages:
                texto_completo += page.extract_text() or ""

            if "DASS" not in texto_completo and "01287588" not in texto_completo:
                return None

            # --- 1. DATA DE RECEBIMENTO ---
            match_emissao = re.search(r'Data da emissão:\s*(\d{2}/\d{2}/\d{4})', texto_completo, re.IGNORECASE)
            if match_emissao:
                data_recebimento = match_emissao.group(1)
            else:
                match_header = re.search(r'Hora.*?Data\s*(\d{2}/\d{2}/\d{4})', texto_completo, re.DOTALL)
                data_recebimento = match_header.group(1) if match_header else datetime.now().strftime("%d/%m/%Y")

            # --- 2. DATA DO PEDIDO ---
            idx_inicio_tabela = texto_completo.find("Prev. Ent.")
            if idx_inicio_tabela == -1: idx_inicio_tabela = 0
            texto_para_busca = texto_completo[idx_inicio_tabela:]
            match_entrega = re.search(r'\d{8}.*?(\d{2}/\d{2}/\d{4})', texto_para_busca, re.DOTALL)
            data_pedido = match_entrega.group(1) if match_entrega else data_recebimento

            # --- 3. ORDEM DE COMPRA / ADQUISICIÓN (ATUALIZADO) ---
            # Procura por "Ordem de compra" OU "Adquisición" seguido de espaço e números
            match_ordem = re.search(r'(Ordem de compra|Adquisición)\s+(\d+)', texto_completo, re.IGNORECASE)
            ordem_compra = match_ordem.group(2) if match_ordem else "N/D"

            # --- DADOS GERAIS ---
            match_marca = re.search(r'Marca:\s*([^\n]+)', texto_completo)
            marca_geral = "N/D"
            if match_marca:
                marca_temp = match_marca.group(1).strip()
                if "Seq" in marca_temp or "Código" in marca_temp or "Descrição" in marca_temp:
                    marca_geral = ""
                else:
                    marca_geral = marca_temp
            
            if not marca_geral or marca_geral == "N/D":
                match_obs = re.search(r'Obs\.\s*de\s*entrega:\s*([^\n-]+)', texto_completo, re.IGNORECASE)
                if match_obs:
                    obs_texto = match_obs.group(1).strip().rstrip('-').strip()
                    marca_geral = f"Obs: {obs_texto}" if obs_texto else "N/D"

            local_geral = extrair_local_entrega(texto_completo)
            unidade_geral = identificar_unidade(texto_completo)
            tipo_faturamento = extrair_tipo_faturamento(texto_completo)

            # --- TOTAIS ---
            valor_total_doc = 0.0
            qtd_total_doc = 0
            match_valor_tot = re.search(r'Total valor:\s*([\d\.,]+)', texto_completo)
            if match_valor_tot: valor_total_doc = limpar_valor_monetario(match_valor_tot.group(1))
            match_qtd_tot = re.search(r'Total peças:\s*([\d\.,]+)', texto_completo)
            if match_qtd_tot: qtd_total_doc = int(limpar_valor_monetario(match_qtd_tot.group(1)))

            valor_formatado = f"R$ {valor_total_doc:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

            pedido_unico = {
                "dataPedido": data_pedido,
                "dataRecebimento": data_recebimento,
                "arquivo": nome_arquivo,
                "cliente": "Grupo DASS",
                "marca": marca_geral,
                "local": local_geral,
                "qtd": qtd_total_doc,
                "unidade": unidade_geral,
                "valor": valor_formatado,
                "ordemCompra": ordem_compra,
                "tipoFaturamento": tipo_faturamento
            }
            return [pedido_unico]
    except Exception as e:
        print(f"Erro ao abrir {nome_arquivo}: {e}")
        return []

def mover_arquivos_processados(lista_arquivos):
    if not os.path.exists(PASTA_LIDOS): os.makedirs(PASTA_LIDOS)
    for arquivo in set(lista_arquivos):
        try:
            caminho_origem = os.path.join(PASTA_ENTRADA, arquivo)
            caminho_destino = os.path.join(PASTA_LIDOS, arquivo)
            if os.path.exists(caminho_destino): os.remove(caminho_destino)
            shutil.move(caminho_origem, caminho_destino)
        except: pass

def main():
    if not os.path.exists(PASTA_ENTRADA):
        os.makedirs(PASTA_ENTRADA)
        print(f"Pasta criada. Coloque PDFs em '{PASTA_ENTRADA}'.")
        return

    todos_pedidos_para_envio = []
    arquivos_para_mover = []
    arquivos = [f for f in os.listdir(PASTA_ENTRADA) if f.lower().endswith('.pdf')]

    print(f"📂 Processando {len(arquivos)} arquivos...")
    print("-" * 120)
    print(f"{'EMISSÃO':<12} | {'ENTREGA':<12} | {'OC':<10} | {'MARCA':<15} | {'VALOR':<14} | {'TIPO DE FATURAMENTO'}")
    print("-" * 120)

    for arq in arquivos:
        lista_pedidos = processar_pdf_dass(os.path.join(PASTA_ENTRADA, arq), arq)
        if lista_pedidos:
            for p in lista_pedidos:
                todos_pedidos_para_envio.append(p)
                print(f"✅ {p['dataRecebimento']:<12} | {p['dataPedido']:<12} | {p['ordemCompra']:<10} | {p['marca']:<15} | {p['valor']:<14} | {p.get('tipoFaturamento','')}")
            arquivos_para_mover.append(arq)
        else:
            print(f"⚠️ Ignorado: {arq}")

    if todos_pedidos_para_envio:
        try:
            response = requests.post(URL_WEBAPP, json={"pedidos": todos_pedidos_para_envio}, timeout=30)
            if response.status_code == 200:
                print(f"\n☁️ SUCESSO! Google recebeu os dados.")
                mover_arquivos_processados(arquivos_para_mover)
            else:
                print(f"\n❌ Erro HTTP {response.status_code}: {response.text}")
        except Exception as e:
            print(f"\n❌ Erro de conexão: {e}")
    else:
        print("\n⚠️ Nenhum pedido válido encontrado.")
    input("\nPressione ENTER para fechar...")

if __name__ == "__main__":
    main()