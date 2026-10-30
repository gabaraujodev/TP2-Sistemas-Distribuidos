# Ficha do trabalho e entrega

**Aluno:** Gabriel Araujo Barbosa  
**Instituicao:** Centro Federal de Educacao Tecnologica de Minas Gerais (CEFET-MG)  
**Disciplina:** Sistemas Distribuidos  
**Atividade:** Trabalho Pratico 2 - Transferencia de Arquivos Peer-to-Peer  
**Professora:** Michelle Hanne  
**Semestre:** 2026/2

## O que esta pronto

- Codigo Python executavel de um sistema P2P por TCP/asyncio, com peers clientes e servidores.
- Dois exemplos de topologias de testes, mais exemplo adicional de vizinhos multiplo.
- Gerador de arquivos de ensaio, testes unitarios e dez cenarios de transferencia real.
- Resultados JSON/CSV e logs integrais compactados dos peers de cada cenario.
- Relatorio academico com cinco paginas em PDF e DOCX, e grafico de resultados.
- Instrucoes de execucao, arquitetura, protocolo e verificacao de integridade no README.

## Unica pendencia externa

O enunciado exige que o relatorio contenha uma URL para o codigo-fonte. Como nenhum repositorio remoto foi fornecido e nao existe autorizacao/acesso para publicar na conta do aluno, o relatorio identifica explicitamente **URL do codigo-fonte: PENDENTE DE PUBLICACAO EM REPOSITORIO REMOTO**.

Para finalizar este requisito, publique este projeto no GitHub/GitLab e execute:

```bash
python -m pip install -r requirements-docs.txt
python scripts/gerar_relatorio.py --repo-url https://github.com/USUARIO/REPOSITORIO
```

Substitua a URL de exemplo pela URL **real**; se nao puder gerar PDF automaticamente, edite o arquivo DOCX e exporte em PDF.

## Checklist sugerido antes de enviar

- [x] Implementacao, testes e evidencias incluidos no pacote.
- [x] 8 testes unitarios aprovados.
- [x] 10 cenarios completos de transferencia aprovados.
- [x] Tamanhos e SHA-256 de todos os downloads conferidos.
- [x] Relatorio PDF com 5 paginas e arquivo editavel DOCX.
- [ ] Publicar o codigo-fonte e atualizar a URL publica no relatorio.
- [ ] Conferir as instrucoes especificas de submissao na disciplina (plataforma, prazo e nomes de arquivos).
