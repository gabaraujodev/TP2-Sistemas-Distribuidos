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
