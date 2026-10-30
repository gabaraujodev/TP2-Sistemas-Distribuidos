# Trabalho Pratico 2 - Transferencia de Arquivos Peer-to-Peer

**Sistemas Distribuidos | CEFET-MG | 2026/2**  
**Professora:** Michelle Hanne  
**Aluno:** Gabriel Araujo Barbosa

Projeto de transferencia P2P por sockets TCP com Python, biblioteca padrao e `asyncio`. Cada processo abre um servidor e pode solicitar blocos a vizinhos estaticos. O primeiro peer e o **seeder** (possui arquivo completo) e os demais sao **leechers**. Quando um leecher recebe um bloco, ele passa a disponibiliza-lo imediatamente a outros peers.

## 1. Requisitos de ambiente

- Python 3.9 ou superior (testado nesta entrega com Python 3.x em Linux).
- Nao precisa instalar pacotes com `pip`; apenas biblioteca padrao.
- Funciona em Linux, Windows e macOS; as demonstracoes locais usam `127.0.0.1`.
- Em computadores distintos, use os IPs acessiveis na rede e libere as portas TCP no firewall.

## 2. Rodar uma demonstracao completa com um comando

Abra o terminal **na pasta raiz deste projeto**, onde estao `p2p/`, `config/` e `scripts/`:

```bash
python scripts/run_config.py config/2_peers.json
python scripts/run_config.py config/4_peers.json
```

No Windows, voce tambem pode usar `INICIAR_2_PEERS_WINDOWS.bat` ou `INICIAR_4_PEERS_WINDOWS.bat` por duplo clique. No Linux existe `INICIAR_4_PEERS_LINUX.sh`. Alternativamente, `py` pode substituir `python`:

```powershell
py scripts/run_config.py config/4_peers.json
```

Os arquivos remontados ficam em `execucoes/demonstracao_4_peers/leecher_*/downloads/amostra.txt`. Em cada peer sao criados `metadata.json`, `have.log`, `events.jsonl` e `summary.json`. O `summary.json` indica SHA-256 calculado e origem de cada grupo de blocos. O script encerra todos os processos ao verificar os downloads.

**Importante:** para repetir a demonstracao do zero, remova `execucoes/` previamente. Se os arquivos ja foram baixados, o peer os reconhecera e nao precisara transferir os blocos novamente.

## 3. Executar peers manualmente

No diretorio raiz, coloque qualquer arquivo de origem na maquina do seeder. Em um terminal execute:

```bash
python -m p2p.peer --host 127.0.0.1 --port 5000 --directory seeder_local --seed data/amostra.txt --block-size 1024
```

Em outro terminal execute o leecher:

```bash
python -m p2p.peer --host 127.0.0.1 --port 5001 --directory leecher_local --peer 127.0.0.1:5000
```

Para um terceiro peer que obtem blocos do segundo:

```bash
python -m p2p.peer --host 127.0.0.1 --port 5002 --directory leecher2_local --peer 127.0.0.1:5001
```

Para adicionar multiplos vizinhos, repita `--peer HOST:PORTA`. Cada peer fica atendendo os demais apos completar o download ate receber Ctrl+C, favorecendo o compartilhamento. Para sair automaticamente apos concluir, use `--exit-when-complete` **somente quando nao houver outros peers dependendo dele**. O seeder permanece ativo ate Ctrl+C.

O leecher requisita `manifest` aos vizinhos, portanto nao precisa de tracker nem de copia previa de metadados; um vizinho que ainda esta baixando ja pode fornecer o manifesto e blocos. O seeder salva o arquivo `metadata.json` ao iniciar.

## 4. Executar os testes

### Testes unitarios

```bash
python -m unittest discover -s tests -v
```

Incluem empacotamento binario, divisao em blocos, hash por bloco, remontagem fora de ordem, recuperacao apos reinicio, validacao de entrada, arquivo vazio e integridade.

### Estudos de caso de ponta a ponta

```bash
python scripts/benchmark.py --quick
python scripts/benchmark.py --full
```

`--quick` executa 4 cenarios, enquanto `--full` executa **10 cenarios** de transferencia real, incluindo valores 2/4 peers, 1024/4096 bytes, File A (10/20 KiB), File B (1/5 MiB) e File C (10/20 MiB), com contrastes controlados para o efeito do numero de peers e do tamanho do bloco. Os arquivos de teste sao criados com bytes pseudorrandomicos reproduziveis e os downloads de todos os leechers sao comparados ao original por **tamanho e SHA-256**.

A auditoria temporal dos repasses pode ser refeita com `python scripts/analisar_repasses.py` depois do benchmark completo.

As saidas ficam em:

- `evidencias/resultados_full.csv` e `.json`: medidas e hashes por cenario.
- `evidencias/logs_full/*.jsonl.gz`: logs integrais de eventos de cada peer, compactados com gzip, incluindo `sent_block`, `received_block`, `inventory` e `progress`.
- `evidencias/resultados_quick.*` e `evidencias/logs_quick/`: execucao de verificacao rapida.
- `evidencias/analise_repasses.json`: comprovacao temporal de envio de blocos antes da conclusao do download.
- `evidencias/testes_unitarios.txt`: saida dos 8 testes unitarios executados.

Para guardar tambem os arquivos binarios da execucao, use `--keep-work`. Nesse modo os testes ocupam mais espaco em disco em `.benchmark_work/`. O tempo `wall_seconds` cobre orquestracao, inicializacao, transferencia e verificacao; **nao e somente tempo de rede**. Os resultados medidos nesta entrega sao locais, e nao uma previsao de desempenho em computadores remotos.

## 5. Arquitetura e protocolo

```text
                      rede TCP (asyncio)
    +-----------+         +-----------+         +-----------+         +-----------+
    | Seeder P0 | ------> | Leecher P1| ------> | Leecher P2| ------> | Leecher P3|
    |   fonte   |  blocos | cliente + |  blocos | cliente + |  blocos | cliente + |
    | servidor  |         | servidor  |         | servidor  |         | servidor  |
    +-----------+         +-----------+         +-----------+         +-----------+
```

Todos os processos inicializam um servidor TCP nao bloqueante, descobrem o manifesto e gerenciam um mapa de bits de blocos. Cada vizinho tem uma tarefa cliente `asyncio` com conexao TCP persistente e execucao concorrente com o servidor local. Para cada rodada, o cliente consulta inventario, reserva indices faltantes, solicita blocos, confere hash e escreve em offset determinado. A reserva impede downloads duplicados entre trabalhadores do mesmo peer. No ultimo bloco o cliente verifica tamanho e hash global, e renomeia `.part` para o nome final.

**Enquadramento de mensagens (big endian):**

```text
4 bytes           N bytes de JSON UTF-8            L bytes opcionais
+----------------+--------------------------------+-------------------+
| len_json (u32) | {"type": ..., "payload_length":L} | payload binario    |
+----------------+--------------------------------+-------------------+
```

Operacoes:

| Requisicao | Resposta | Uso |
|---|---|---|
| `manifest` | `manifest` / `not_ready` | Obter metadados do arquivo |
| `status` | `status` / `not_ready` | Obter bitmap base64 e contagem de blocos |
| `block` + `index` | `block` + payload / `missing` | Transferir conteudo binario do bloco |

O manifesto JSON inclui `protocol_version`, `file_name`, `size`, `block_size`, `sha256`, `block_hashes`. Hash de cada bloco evita aceitar conteudo corrompido; hash SHA-256 global protege a remontagem. O servidor limita comprimentos das mensagens e nao usa caminhos de arquivo enviados diretamente pela rede. O registro `have.log` permite retomar blocos existentes, desde que os hashes sejam novamente validados.

## 6. Estrutura de arquivos

```text
TP2_P2P_Gabriel_Araujo_Barbosa/
  p2p/
    protocol.py        # frames JSON + dados binarios
    storage.py         # manifesto, blocos, bitfield, SHA-256, retomada
    peer.py            # servidor e workers clientes concorrentes
  config/
    2_peers.json       # topologia estatica basica
    4_peers.json       # topologia estatica em cadeia
    4_peers_malha.json # cada leecher pode ter varios vizinhos
  data/amostra.txt     # entrada da demonstracao
  scripts/
    run_config.py      # demonstra por configuracao
    benchmark.py       # 10 estudos de caso com verificacao automatica
    gerar_relatorio.py # gera DOCX e PDF a partir das medidas
    analisar_repasses.py # audita envio de blocos antes da conclusao
  tests/test_core.py   # testes unitarios
  evidencias/          # logs completos e indicadores medidos
  documentacao/
    Relatorio_TP2_Gabriel_Araujo_Barbosa.pdf
    Relatorio_TP2_Gabriel_Araujo_Barbosa.docx
  requirements.txt
  .gitignore
  README.md
```

## 7. Decisoes, limites e boas praticas

- A rede implementa um **swarm de um arquivo por processo**, sem tracker e sem descoberta automatica de peers: a lista vem de `--peer`/configuracao.
- Suporta arquivos de ate 50.000 blocos; tamanho maximo de bloco e 1 MiB; maximo de cabecalho e 4 MiB. Limites tornam o protocolo mais previsivel.
- O peer **nao autentica vizinhos nem criptografa** a conexao. Use somente em ambiente de laboratorio/rede confiavel; nao exponha os servidores diretamente a Internet.
- Os testes de 4 peers usam topologia em **cadeia**, para verificar compartilhamento de blocos por leechers: P2 recebe de P1 e P3 recebe de P2, em vez de todos copiarem do seeder.
- As metricas de parede dependem de escalonamento de processos, armazenamento, CPU e rede locais; nao permitem afirmar ganho de desempenho universal.

## 8. Publicar o codigo-fonte (etapa manual obrigatoria)

O enunciado exige uma **URL para o codigo-fonte no relatorio**. Nao foi fornecida uma URL de repositorio remoto, e o pacote foi criado localmente. Antes de entregar a professora, publique esta pasta no GitHub/GitLab e **substitua o campo 'URL do codigo-fonte: PENDENTE'** no relatorio DOCX; depois exporte novamente para PDF. Nunca use um endereco inventado como se o codigo estivesse publicado.

Exemplo de sequencia (crie primeiro um repositorio vazio na sua conta):

```bash
git init
git add .
git commit -m "TP2 Sistemas Distribuidos - P2P"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git
git push -u origin main
```

Se ja existe um repositorio Git no diretorio, nao repita `git init`. Substitua o endereco de exemplo pelo **link real** criado na plataforma.

## 9. Atualizar a URL e regenerar o relatorio

O relatorio entregue possui 5 paginas e esta disponivel em PDF e DOCX. Quando publicar o repositorio, voce pode atualizar o campo da URL no Word/LibreOffice e reexportar em PDF. Para **regenerar automaticamente os dois formatos**, instale as dependencias opcionais da documentacao:

```bash
python -m pip install -r requirements-docs.txt
python scripts/gerar_relatorio.py --repo-url https://github.com/USUARIO/REPOSITORIO
```

O segundo comando usa a **URL real que voce informar**, e nao cria repositorios remotamente. Requer LibreOffice para exportar o PDF automaticamente; se nao estiver instalado, use o DOCX no Word ou LibreOffice. O codigo de transferencia e os testes continuam sem dependencias externas.
