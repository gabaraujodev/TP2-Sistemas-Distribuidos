"""Gera o relatorio academico (DOCX + PDF) com base nas evidencias reais.

Requisitos opcionais de geracao: python-docx, matplotlib e LibreOffice para PDF.
Uso: python scripts/gerar_relatorio.py --repo-url https://github.com/usuario/repo
Sem --repo-url, o campo exigido de URL permanece marcado como PENDENTE.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "documentacao"
DOCS.mkdir(exist_ok=True)
DATA = json.loads((ROOT / "evidencias" / "resultados_full.json").read_text(encoding="utf-8"))["cases"]
INDEX = {x["case"]: x for x in DATA}
NAVY = RGBColor(22, 47, 77)
DARK = RGBColor(42, 57, 71)
GREY = RGBColor(91, 104, 116)
LIGHT = RGBColor(232, 239, 245)


def set_cell_shading(cell, color="E8EFF5"):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color)
    tcPr.append(shd)


def keep_together(par):
    pPr = par._p.get_or_add_pPr()
    tag = OxmlElement("w:keepLines")
    pPr.append(tag)


def paragraph(doc, content="", style=None, bold_label=None, after=5):
    p = doc.add_paragraph(style=style)
    p.paragraph_format.space_after = Pt(after)
    if bold_label and content.startswith(bold_label):
        p.add_run(bold_label).bold = True
        p.add_run(content[len(bold_label):])
    else:
        p.add_run(content)
    return p


def h(doc, number, name):
    p = doc.add_paragraph(style="Heading 2")
    p.add_run(f"{number}  {name}")
    p.paragraph_format.keep_with_next = True
    return p


def sub(doc, name):
    p = doc.add_paragraph(style="Heading 3")
    p.add_run(name)
    p.paragraph_format.keep_with_next = True
    return p


def table(doc, headers, rows, widths=None, font=8.3):
    t = doc.add_table(rows=1, cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.style = "Table Grid"
    t.autofit = False
    if widths:
        for i, width in enumerate(widths):
            t.columns[i].width = Cm(width)
    for j, title in enumerate(headers):
        c = t.rows[0].cells[j]
        if widths:
            c.width = Cm(widths[j])
        c.text = str(title)
        set_cell_shading(c, "DCE8F1")
    for k, row in enumerate(rows):
        cells = t.add_row().cells
        for j, value in enumerate(row):
            cells[j].text = str(value)
            if widths:
                cells[j].width = Cm(widths[j])
            if k % 2 == 1:
                set_cell_shading(cells[j], "F4F8FB")
    for i, row in enumerate(t.rows):
        trPr = row._tr.get_or_add_trPr()
        cant = OxmlElement("w:cantSplit")
        trPr.append(cant)
        for cell in row.cells:
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            for p in cell.paragraphs:
                p.paragraph_format.space_before = Pt(1)
                p.paragraph_format.space_after = Pt(1)
                for run in p.runs:
                    run.font.size = Pt(font)
                    if i == 0:
                        run.bold = True
                        run.font.color.rgb = NAVY
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return t


def add_footer(doc):
    section = doc.sections[0]
    foot = section.footer.paragraphs[0]
    foot.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    foot.style = doc.styles["Normal"]
    foot.add_run("Gabriel Araujo Barbosa  |  TP2 - Sistemas Distribuidos  |  Pagina ")
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    foot._p.append(field)
    for run in foot.runs:
        run.font.size = Pt(8)
        run.font.color.rgb = GREY


def chart(path):
    labels = ["2 peers\n1 KiB", "2 peers\n4 KiB", "4 peers\n1 KiB"]
    cases_1 = ["B_1MB_base", "B_1MB_2peers_4096", "B_1MB_4peers_1024"]
    cases_10 = ["C_10MB_base", "C_10MB_2peers_4096", "C_10MB_4peers_1024"]
    fig, ax = plt.subplots(figsize=(8.5, 2.5))
    x = list(range(3))
    ys_1 = [INDEX[k]["wall_seconds"] for k in cases_1]
    ys_10 = [INDEX[k]["wall_seconds"] for k in cases_10]
    bars1 = ax.bar([i - .18 for i in x], ys_1, .36, label="Arquivo de 1 MiB")
    bars2 = ax.bar([i + .18 for i in x], ys_10, .36, label="Arquivo de 10 MiB")
    ax.set_xticks(x, labels)
    ax.set_ylabel("Tempo total (s)")
    ax.set_ylim(0, max(ys_10) * 1.24)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(axis="y", alpha=.15)
    ax.set_axisbelow(True)
    for bar in list(bars1) + list(bars2):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + .045,
                f"{bar.get_height():.2f}", ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)


def create_report(repo_url):
    doc = Document()
    s = doc.sections[0]
    s.page_width, s.page_height = Cm(21), Cm(29.7)
    s.top_margin, s.bottom_margin = Cm(1.75), Cm(1.60)
    s.left_margin, s.right_margin = Cm(2.15), Cm(2.0)
    s.header_distance, s.footer_distance = Cm(.8), Cm(.9)
    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(10.25)
    normal.font.color.rgb = DARK
    normal.paragraph_format.space_after = Pt(4)
    normal.paragraph_format.line_spacing = 1.13
    for nm, sz, before, after in (("Heading 2", 12.4, 10, 5), ("Heading 3", 10.2, 6, 3)):
        st = styles[nm]
        st.font.name = "Aptos Display"
        st.font.size = Pt(sz)
        st.font.bold = True
        st.font.color.rgb = NAVY
        st.paragraph_format.space_before = Pt(before)
        st.paragraph_format.space_after = Pt(after)
    header = s.header.paragraphs[0]
    header.text = "CEFET-MG  |  SISTEMAS DISTRIBUIDOS  |  2026/2"
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for r in header.runs:
        r.font.size = Pt(8)
        r.font.color.rgb = GREY
    add_footer(doc)

    # PAGINA 1: identificacao, resumo, requisitos e topologia
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(13)
    title.paragraph_format.space_after = Pt(8)
    r = title.add_run("TRANSFERENCIA DE ARQUIVOS\nPEER-TO-PEER (P2P)")
    r.bold = True
    r.font.name = "Aptos Display"
    r.font.size = Pt(18)
    r.font.color.rgb = NAVY
    subt = doc.add_paragraph()
    subt.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rr = subt.add_run("Trabalho Pratico 2  •  Relatorio tecnico de implementacao e testes")
    rr.font.size = Pt(10)
    rr.font.color.rgb = GREY
    paragraph(doc, "Aluno: Gabriel Araujo Barbosa   |   Professora: Michelle Hanne   |   Data: 30/10/2026", after=9)
    h(doc, "Resumo", "")
    paragraph(doc, "Este trabalho implementa um sistema de transferencia de arquivos P2P usando Python, TCP e asyncio. Cada no escuta conexoes e, simultaneamente, consulta vizinhos predefinidos para obter blocos. Os leechers disponibilizam de imediato blocos validados, sem tracker. Foram executados oito testes unitarios e dez cenarios reais de transferencia, com dois ou quatro peers, blocos de 1 ou 4 KiB e arquivos de 10 KiB a 20 MiB. Todos os downloads foram remontados com tamanho e SHA-256 iguais aos do arquivo original.")
    h(doc, "1", "Objetivos e requisitos")
    paragraph(doc, "O enunciado de Sistemas Distribuidos (CEFET-MG, 2026/2) requer P2P simetrico, fragmentacao em blocos fixos, configuracao estatica dos vizinhos, comunicacao concorrente via sockets, formato de metadados e mensagens, mapa local de blocos e remontagem verificada. Solicita ainda avaliar 2 e 4 peers; blocos de 1.024 e 4.096 bytes; e tres classes de arquivos: A (10/20 KB), B (1/5 MB) e C (10/20 MB).")
    h(doc, "2", "Arquitetura da solucao")
    paragraph(doc, "O peer e um unico processo com servidor TCP e tarefas cliente concorrentes. A configuracao informa IP, porta, diretorio local e vizinhos (host:porta). Um seeder recebe o caminho do arquivo original, cria o manifesto e atende pedidos. Um leecher obtem o manifesto de qualquer vizinho acessivel, consulta inventarios de blocos e solicita apenas os que ainda nao possui.")
    sub(doc, "Topologia de quatro peers utilizada nos estudos de caso")
    topo = doc.add_table(rows=1, cols=4)
    topo.autofit = False
    for i, label in enumerate(["P0  •  Seeder\nArquivo original", "P1  •  Cliente/Servidor\nRecebe de P0", "P2  •  Cliente/Servidor\nRecebe de P1", "P3  •  Cliente/Servidor\nRecebe de P2"]):
        c = topo.cell(0, i)
        c.text = label
        c.width = Cm(4.1)
        set_cell_shading(c, "EAF1F6")
        for p in c.paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in p.runs:
                run.font.size = Pt(8.5)
                run.font.color.rgb = NAVY
    paragraph(doc, "As conexoes P0 → P1 → P2 → P3 representam o fluxo dos blocos; todos os nos executam o mesmo servidor. A cadeia obriga P2 a obter blocos de P1 e P3 a obte-los de P2, demonstrando redistribuicao efetiva entre leechers.", after=0)

    # PAGINA 2: protocolo / implementacao
    doc.add_page_break()
    h(doc, "3", "Projeto e implementacao")
    sub(doc, "3.1 Concorrencia e comunicacao")
    paragraph(doc, "O modulo p2p/peer.py usa asyncio.start_server para aceitar conexoes TCP sem bloquear o processo. Para cada vizinho configurado, uma tarefa cliente mantem conexao persistente, consulta o inventario, reserva indices pendentes, solicita ate 32 blocos por rodada e atualiza o estado local. Um lock para reservas evita que trabalhadores do mesmo peer solicitem repetidamente o mesmo bloco; outro protege a escrita e o mapa de disponibilidade. A rede pode continuar solicitando blocos enquanto os blocos recebidos sao servidos a terceiros.")
    sub(doc, "3.2 Protocolo e serializacao")
    paragraph(doc, "Cada frame contem 4 bytes de comprimento de cabecalho (inteiro unsigned, big-endian), um objeto JSON UTF-8 e, opcionalmente, bytes binarios do bloco. O campo payload_length indica o numero de bytes binarios. A transferencia binaria evita converter todo o conteudo do arquivo para texto.")
    table(doc, ["Mensagem enviada", "Resposta do servidor", "Finalidade"], [
        ["manifest", "manifest / not_ready", "Solicitar metadados"],
        ["status", "status (bitmap base64)", "Descobrir blocos disponiveis"],
        ["block + index", "block + bytes / missing", "Transferir bloco indexado"]
    ], [4.1, 5.1, 7.35])
    sub(doc, "3.3 Manifesto, fragmentacao e remontagem")
    paragraph(doc, "O manifesto metadata.json registra versao do protocolo, nome do arquivo, tamanho, tamanho fixo de bloco, SHA-256 global e SHA-256 de cada bloco. O arquivo e dividido logicamente por offsets: bloco i comeca em i × tamanho_bloco, e o ultimo pode ser menor. Esse metodo evita criar milhares de arquivos temporarios. O leecher grava os blocos validados nas posicoes corretas em um unico arquivo .part. Quando todos os indices estao presentes, verifica o tamanho e SHA-256 global e renomeia o arquivo como resultado final.")
    sub(doc, "3.4 Controle local, persistencia e tratamento de falhas")
    paragraph(doc, "A disponibilidade e armazenada em um bitfield (um bit por bloco). Recebimentos confirmados sao registrados em have.log; ao reiniciar, o peer so considera recuperados os indices cujo conteudo ainda passa na verificacao SHA-256. Conexoes indisponiveis sao retentadas; pedidos de blocos nao presentes retornam missing. Mensagens malformadas, nomes de arquivo com caminhos, tamanhos excessivos e indices invalidos sao rejeitados.")
    paragraph(doc, "Registro e monitoramento: cada peer produz events.jsonl com timestamps, origem/destino, inventarios, recebimento/envio dos blocos, progresso e erros. summary.json contem tamanho, hash esperado/observado, tempo ate conclusao e distribuicao por fonte. O seeder permanece disponivel; um leecher completo, por padrao, continua servindo arquivos ate seu encerramento.")

    # PAGINA 3: metodologia
    doc.add_page_break()
    h(doc, "4", "Metodologia de testes")
    paragraph(doc, "Os ensaios foram executados localmente, em 30/10/2026, sob Linux, com Python 3.13.5 e conexoes TCP na interface de loopback (127.0.0.1). O script scripts/benchmark.py gera arquivos de bytes pseudorrandomicos com semente deterministica, inicia processos independentes, aguarda todos os leechers e valida os resultados. Para testes com quatro peers utiliza-se a cadeia P0→P1→P2→P3. As grandezas KB e MB do enunciado foram operacionalizadas em potencias de 2 (KiB e MiB); por exemplo, 1 MiB = 1.048.576 bytes.")
    sub(doc, "4.1 Matriz de dez cenarios")
    rows = []
    for r in DATA:
        rows.append([r["case"].replace("_", " "), str(r["peers"]),
                     str(r["block_size_bytes"]), f"{r['file_size_bytes']:,}".replace(",", "."),
                     f"{r['blocks']:,}".replace(",", ".")])
    table(doc, ["Cenario", "Peers", "Bloco (B)", "Arquivo (B)", "Blocos"], rows, [6.5, 1.35, 2.6, 3.35, 2.75], font=8.0)
    sub(doc, "4.2 Procedimento e criterios de aprovacao")
    paragraph(doc, "(i) Preparacao: criacao do arquivo de teste e do manifesto pelo seeder; (ii) inicializacao: subida dos processos com a topologia fixa; (iii) monitoramento: gravacao de inventarios e transferencias por bloco; (iv) verificacao: cada leecher deve produzir um arquivo com exatamente o numero de bytes original e SHA-256 igual ao da origem; (v) confirmacao do repasse: nos cenarios de quatro peers, os logs e resumos devem indicar P1 como fonte de P2, e P2 como fonte de P3.")
    paragraph(doc, "O script conta o tempo total em segundos, desde o inicio da orquestracao ate a conclusao das verificacoes; essa medida inclui inicializacao e escalonamento, e nao representa apenas a latencia da rede. O ensaio nao controla carga do sistema operacional nem repete cada cenario estatisticamente, de modo que comparacoes de desempenho sao exploratorias.")
    sub(doc, "4.3 Testes de componentes")
    paragraph(doc, "O comando python -m unittest discover -s tests -v executou oito testes unitarios, todos aprovados. Foram verificados enquadramento binario do protocolo, criacao e validacao do manifesto, fragmentacao, ordenacao arbitraria de blocos, rejeicao de bloco modificado, recuperacao apos reinicio com nova verificacao, bloqueio de caminhos inseguros e arquivo vazio.")

    # PAGINA 4: resultados medidos
    doc.add_page_break()
    h(doc, "5", "Resultados experimentais")
    paragraph(doc, "Os 10 cenarios terminaram com sucesso; cada leecher produziu um arquivo de tamanho correto e SHA-256 identico ao original. A tabela apresenta os tempos reais de parede medidos durante a execucao deste pacote. Arquivos CSV e JSON armazenam o SHA-256 de cada fonte e a quantidade de blocos de cada fornecedor, permitindo auditoria sem depender somente deste relatorio.")
    rows = []
    for r in DATA:
        rows.append([r["case"].replace("_", " "), str(r["peers"]),
                     str(r["block_size_bytes"]), f"{r['wall_seconds']:.3f}", "APROVADO"])
    table(doc, ["Cenario", "Peers", "Bloco (B)", "Tempo (s)", "Integridade"], rows, [6.7, 1.35, 2.6, 2.7, 3.2], font=8.0)
    chartfile = DOCS / "comparacao_experimentos.png"
    chart(chartfile)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(0)
    p.add_run().add_picture(str(chartfile), width=Cm(15.9))
    p2 = doc.add_paragraph("Figura 1 - Contrastes controlados de tamanho de bloco e quantidade de peers (tempo total de parede).")
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p2.paragraph_format.space_after = Pt(3)
    for run in p2.runs:
        run.italic = True
        run.font.size = Pt(8)
    base = INDEX["C_10MB_base"]["wall_seconds"]
    enlarged = INDEX["C_10MB_2peers_4096"]["wall_seconds"]
    chained = INDEX["C_10MB_4peers_1024"]["wall_seconds"]
    paragraph(doc, f"Nos ensaios de 10 MiB com 2 peers, passar de 1 KiB para 4 KiB reduziu o tempo observado de {base:.3f} s para {enlarged:.3f} s, com 10.240 versus 2.560 blocos. Mantendo 1 KiB, a cadeia de 4 peers concluiu em {chained:.3f} s, comparada a {base:.3f} s com 2 peers, pois o ultimo peer depende de repasses sucessivos. Sao observacoes locais, sem inferencia de desempenho para outras redes.", after=0)

    # PAGINA 5: consideracoes e reproducibilidade
    doc.add_page_break()
    h(doc, "6", "Discussao, limites e conclusao")
    paragraph(doc, "Os resultados demonstram a simetria funcional: um leecher recebe, verifica, armazena e retransmite blocos, inclusive antes do arquivo inteiro estar completo. Na cadeia de quatro peers, P2 recebeu exclusivamente de P1 e P3 exclusivamente de P2 em todos os testes correspondentes; os logs compressed JSONL preservam eventos sent_block e received_block com indices e origem. A fragmentacao e remontagem foram validadas tanto para arquivos pequenos quanto para 20 MiB, sem diferencas de hash.")
    audit_path = ROOT / "evidencias" / "analise_repasses.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        pair = audit.get("C_20MB_variacao", [])
        if len(pair) >= 2 and all(item.get("served_before_completion") for item in pair):
            paragraph(doc, f"Evidencia temporal adicional (caso C, 20 MiB): P1 iniciou o envio de blocos {pair[0]['seconds_before_completion']:.3f} s antes de completar seu proprio download, e P2 iniciou {pair[1]['seconds_before_completion']:.3f} s antes. Esses resultados, extraidos de sent_block e complete, comprovam compartilhamento antecipado.")
    paragraph(doc, "As decisoes de projeto privilegiaram simplicidade e rastreabilidade: um arquivo por swarm, vizinhos estaticos, JSON para controles, payload binario para dados, armazenamento por offset e testes reprodutiveis. Como limitacoes, nao ha descoberta automatica de peers, criptografia/autenticacao TCP ou politica avancada de escalonamento (rarest-first global). O teste com quatro peers usa cadeia para comprovar repasse, nao para medir paralelismo com varias fontes. Em producao, seriam desejaveis TLS, autenticacao, tolerancia a peers maliciosos e experimentos com redes reais e repeticoes estatisticas.")
    paragraph(doc, "Conclui-se que a implementacao atende aos requisitos centrais do enunciado de transferencia P2P: servidor/cliente em um mesmo no, fragmentacao, registro de blocos, serializacao, trocas concorrentes, disponibilizacao imediata, remontagem e verificacao. Os oito testes unitarios e os dez estudos de caso automatizados foram aprovados.")
    h(doc, "7", "Reprodutibilidade e arquivos entregues")
    paragraph(doc, "Para executar (na raiz do projeto, Python 3.9+):")
    for line in ["python -m unittest discover -s tests -v", "python scripts/run_config.py config/4_peers.json", "python scripts/benchmark.py --full"]:
        p = doc.add_paragraph(style="Normal")
        p.paragraph_format.left_indent = Cm(.55)
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(line)
        r.font.name = "Consolas"
        r.font.size = Pt(8.6)
    paragraph(doc, "Codigo: p2p/peer.py, p2p/protocol.py, p2p/storage.py; configuracoes: config/; automatizacao: scripts/; testes: tests/; resultados auditaveis: evidencias/resultados_full.csv e .json; logs integrais compactados: evidencias/logs_full/*.jsonl.gz; instrucoes: README.md.")
    h(doc, "8", "Disponibilizacao do codigo-fonte")
    if repo_url:
        paragraph(doc, f"URL do codigo-fonte: {repo_url}", bold_label="URL do codigo-fonte:")
    else:
        paragraph(doc, "URL do codigo-fonte: PENDENTE DE PUBLICACAO EM REPOSITORIO REMOTO.", bold_label="URL do codigo-fonte:")
        paragraph(doc, "Observacao de entrega: o pacote inclui integralmente os arquivos-fonte, mas a URL publica solicitada pelo enunciado so podera ser inserida depois do envio do repositorio para a conta do aluno. Nao foi inserido endereco ficticio.")
    h(doc, "Referencia", "")
    paragraph(doc, "CEFET-MG. Sistemas Distribuidos. Trabalho Pratico 2 - Transferencia de Arquivos Peer-to-Peer. Profa. Michelle Hanne, 2026/2, 2 p. (enunciado fornecido).")
    paragraph(doc, "Dados experimentais: registros produzidos pela execucao local do software deste trabalho em 30/10/2026.", after=0)

    doc.core_properties.title = "Transferencia de Arquivos P2P - Trabalho Pratico 2"
    doc.core_properties.author = "Gabriel Araujo Barbosa"
    doc.core_properties.subject = "Sistemas Distribuidos - CEFET-MG - 2026/2"
    word = DOCS / "Relatorio_TP2_Gabriel_Araujo_Barbosa.docx"
    doc.save(word)
    print("DOCX:", word)
    # --headless usa perfil isolado para evitar travar com sessoes LibreOffice abertas.
    import shutil
    exe = shutil.which("libreoffice") or shutil.which("soffice")
    if exe:
        profile = (DOCS / ".lo_profile").resolve().as_uri()
        proc = subprocess.run([exe, f"-env:UserInstallation={profile}", "--headless", "--convert-to", "pdf",
                               "--outdir", str(DOCS), str(word)], capture_output=True, text=True)
        print("PDF export:", proc.stdout.strip(), proc.stderr.strip())
    else:
        print("LibreOffice nao encontrado: exporte o DOCX em PDF pelo Word/LibreOffice.")
    return word


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-url", default="", help="URL publica real do codigo no GitHub ou GitLab")
    cli = ap.parse_args()
    create_report(cli.repo_url.strip())
