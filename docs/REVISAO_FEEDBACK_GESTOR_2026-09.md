# Revisão pós-feedback do gestor (set/2026) + prompts de execução

Data da revisão: 17/09/2026
Pedido de referência do gestor: **107487** (entrega 25/01/2027, semana 2704)

Este documento tem três partes:

- **Parte A** — Revisão do código: o que causa cada ponto do feedback, com evidência (arquivo:linha).
- **Parte B** — `PROMPT 1`: correções (Sprint 5), pronto para colar num agente de código.
- **Parte C** — `PROMPT 2`: planejamento da camada conversacional (Sprint 6) + resposta à pergunta de esforço/complexidade.

---

## 0. Limitações desta revisão (leia antes)

1. **A API do Excia não foi chamada nesta sessão.** O host `vpn.papinhababy.com.br:2211` só responde de dentro da VPN/VM, e a VM (163.176.47.4) tem a porta 22 bloqueada a partir do sandbox de revisão. Toda a análise abaixo é estática, baseada no código, na documentação oficial da API (`Docs_Excia.txt`, 323 KB) e numa simulação numérica da engine com os dados do pedido 107487 citados pelo gestor. Os pontos que dependem de confirmação ao vivo estão marcados com **[VALIDAR NA VM]**.
2. **O repositório GitHub está atrasado em relação à pasta de trabalho local/VM.** O último commit no GitHub é de 17/08 (`5ad9707`). A pasta `G:\Meu Drive\...\papinha-pcp-copilot` tem alterações de 26/08 que não estão versionadas:
   - `api/setor_adapter.py` (novo) e `engine/cronograma.py` reescrito para usá-lo;
   - autenticação (`api/security.py`, `api/user_service.py`, `ui/login.html`, `ui/admin.html`, `data/users.db`);
   - cascata malha tinta → malha crua (`api/mrp_adapter.py`, `engine/models.py`, `engine/matching.py`, `ui/index.html`).

   O que o gestor testou é essa versão de 26/08. **Qualquer prompt de correção precisa rodar sobre a pasta local, e o primeiro passo é commitar essa pasta no GitHub**, senão as correções vão conflitar com o que está no ar.

---

## Parte A — Revisão: causa raiz de cada ponto do feedback

### A1. Lead times "20 / 10 / 4" em vez de "18 / 9 / 3" cadastrados no Excia

**Causa.** Na versão implantada, a duração de cada fase vem de um dicionário fixo em `api/setor_adapter.py` (`_LEAD_TIMES_PADRAO_SETORES`): `TINTURARIA: 20`, `LAVANDERIA: 10`, `EMBALAGEM: 4`. O método `obter_setores()` chama `SetorLista`, mas **nada usa o resultado**: `obter_lead_time_fase()` só consulta o dicionário fixo. O `config/regras.yaml` (`fases_dias`) também deixou de ser lido para as fases; só `PCP_MIN` ainda é usado. Existem, portanto, três fontes de verdade e nenhuma é o Excia.

**Agravante confirmado na documentação da API.** `GET /SetorLista` devolve apenas `codigo`, `descricao`, `tipo`; `GET /Fluxo/:codigo` devolve `setores[]` com `setor`, `descricao`, `ordem`. **Não há campo de dias/prazo por setor em nenhum endpoint documentado.** O "18 dias cadastrado no sistema" que o gestor vê numa tela do Excia não é exposto pela API (pelo menos não pela documentação que temos). **[VALIDAR NA VM]**: chamar `SetorLista` e `Fluxo/{fluxo do 107487}` e confirmar que não vem nenhum campo extra não documentado.

**Decisão (17/09, Marcos):** os lead times têm que vir do Excia via API, porque o PCP os cadastra lá. A documentação que temos não mostra o campo, então o passo 1 da Sprint 5 começa por uma exploração na VM com `scripts/explorar_lead_times.py`, que procura campos não documentados em `Setor/:codigo`, `Fluxo/:codigo`, `ParteProdutoLista` e `OPLista`, e testa `Pedido/Fluxo?numero=107487` (datas planejadas por setor). Se nenhum endpoint expuser os dias, há duas saídas, em ordem: (a) perguntar ao suporte da Excia qual endpoint devolve o prazo por setor do fluxo (o mesmo canal do e-mail da Sprint 3); (b) derivar os lead times do cronograma oficial da OF que o Excia calcula, quando `Pedido/Fluxo` ou `BuscarMovimentacaoOP` trouxerem as datas por setor. O arquivo `config/lead_times.yaml` vira cache/fallback com data de sincronização, não a fonte primária, e a tela de admin mostra "sincronizado do Excia em dd/mm" com botão de ressincronizar.

### A2. Feriados e férias coletivas ignorados

**Causa.** `parsers/comum.py:140` tem `FERIADOS_NACIONAIS` fixo (feriados nacionais 2025–2027, incluindo carnaval). Não há férias coletivas, pontes nem feriados municipais. `eh_dia_util()` (`comum.py:161`) só olha esse conjunto.

**Confirmado na documentação da API:** zero ocorrências de "feriado", "calendário" ou "férias" em `Docs_Excia.txt`. Como o PCP também cadastra isso no Excia, a mesma exploração do item A1 procura o calendário (o script registra qualquer chave com "feriad", "calend", "parada" ou "ferias" nas respostas) e, se o cronograma oficial da OF vier por `Pedido/Fluxo`, as paradas ficam visíveis como buracos entre `dt_prev` de um setor e `dt_inicio` do seguinte. Se nada vier, o calendário fica em `config/calendario.yaml` com tela de admin, e a pergunta vai para o suporte da Excia junto com a dos lead times.

**Impacto no 107487.** A simulação da engine coloca COSTURA de 16/12/2026 a 04/01/2027, atravessando o fim de ano como se fossem dias úteis normais. Com férias coletivas (ex.: 21/12 a 04/01) todo o início do cronograma recua duas semanas. É exatamente "divergiu demais as datas de início da OF".

### A3. "Revisão (6d) mas 12→20 dá 7 dias úteis" e "Acab. Costura (4d) mas 5→11 dá 5"

**Causa.** Reproduzido com a engine atual (backward a partir de 29/01/2027):

| Fase | Início exibido | Fim exibido | Rótulo | Dias úteis inclusivos |
|---|---|---|---|---|
| ACAB. COSTURA | 05/01/2027 | 11/01/2027 | 4d | 5 |
| REVISAO | 12/01/2027 | 20/01/2027 | 6d | 7 |
| EMBALAGEM | 26/01/2027 | 29/01/2027 | 4d | 4 |

`recuar_dias_uteis_excia()` (`comum.py:165`) usa a convenção "a saída de uma etapa é a entrada da seguinte": para fases intermediárias os N dias contados são os **posteriores** à data de início exibida (o dia de início pertence à fase anterior). Só a última fase (`eh_ultima=True`) conta o próprio dia. Resultado: o rótulo diz N, mas quem lê o intervalo inclusivo conta N+1, exceto na Embalagem. O gestor contou inclusivo e está certo em apontar a inconsistência de apresentação.

**Decisão necessária [VALIDAR NA VM]:** comparar com o cronograma que o **Excia** calcula para a OF 270363 (não com o relatório da nossa aplicação, que reproduz a nossa própria convenção). A fonte preferida é `GET /Pedido/Fluxo?numero=107487` (campos `dt_inicio`, `dt_prev`, `dt_fim` por setor); se vier vazio, a tela de cronograma da OF no Excia, impressa pelo PCP. Se o Excia imprime "entrada 12/01 – saída 20/01" para Revisão com 6 dias, mantemos as datas e ajustamos a apresentação (rótulo "entrada → saída", coluna "1º dia trabalhado"). Se o Excia imprime 13/01–20/01, deslocamos o início exibido em um dia útil. Em ambos os casos o rótulo tem que bater com a contagem inclusiva entre as datas mostradas.

### A4. Sugestão de nova data não diz a semana de produção

**Causa.** `engine/analise.py:_montar_sugestao` (linha ~330) monta apenas: "Data inviável — sugerir ao comercial nova entrega na semana 2705 (05/02/2027)". A semana de produção (2704, fim 29/01/2027) só aparece no fim do cronograma. Além disso a nova entrega é calculada como `semana_sugerida + 1` (`aass_add(semana_sug, 1)`), enquanto a regra da casa é "produção = entrega − 2". Com a regra, a nova entrega seria **2706**, não 2705.

**Decisão (17/09, Marcos):** a regra é **entrega = produção + 1 semana**. O PCP tem margem para sugerir até produção + 2; acima disso precisa de autorização do gestor. Portanto o cálculo atual (+1) está certo; o que falta é o texto dizer a semana de produção e a data de término, e a UI destacar "Semana de produção". Registrar a regra em `regras.yaml` como `geral.semanas_entre_producao_e_entrega: 1` e `geral.semanas_maximo_sem_autorizacao: 2`.

### A5. Bug de virada de ano na zona do veredito (relevante agora, pedidos de jan/2027)

**Causa.** `engine/analise.py` linhas ~292–304 fazem aritmética inteira com semanas AASS:

```python
if (semana_alvo - autonomia) <= semana_sug <= semana_alvo:   # 2702 - 3 = 2699
    ...
motivos.append(f"Antecipação de {semana_alvo - semana_sug} sem., ...")  # 2702 - 2652 = 50
```

Para alvo 2702 e sugestão 2652 (2 semanas antes), a condição dá `False`, o veredito cai em "REQUER AUTORIZAÇÃO DA GESTÃO" e a mensagem diz "antecipação de 50 semanas". Reproduzido. A UI repete o erro em `index.html`: "Janela de autonomia: semanas `${p.semana_alvo - 3}` a ...". `engine/capacidade.py` já usa `aass_add` corretamente; `analise.py` e a UI não.

### A6. "FALTA — disponível 22/09": de onde vem essa data

**Causa.** `engine/insumos.py:95–99`: quando o insumo está em FALTA, `disponivel_em = hoje + lead_times.compra (7 dias)`. Em 15/09 isso dá 22/09. A UI (`index.html`, `dispStr`) imprime "disponível <data>" sempre que `disponivel_em` existe. Ou seja: é uma suposição de "compra em 7 dias" apresentada como previsão, inclusive para malha, que não se compra: passa por tecelagem + tinturaria. A própria versão de 26/08 já calcula a cascata (malha tinta → crua → fio) em `mrp_adapter.py` e sabe que "necessita ordem de tecelagem + tinturaria", mas a data exibida contradiz isso.

Secundário: `insumos._e_bloqueante` compara `fase.nome == ins.fase_consumo`; os nomes das fases vindos da API ("QUAL. ESTAMPARIA", "ESTAMPA NUCA") não batem com as chaves de `_SETOR_PARA_FASE` ("QUAL_ESTAMPARIA", "ESTAMPARIA_NUCA"), então quase tudo cai no fallback conservador "bloqueante".

### A7. Outros achados (não citados pelo gestor)

- **Rota fixa por keyword está morta.** `_detectar_rota` só é usada se a API falhar; ok, mas `rotas`/`overrides_fases_por_rota` no yaml dão a impressão de configurar algo que não configura.
- **Testes:** 56 passam, 4 falham em `tests/test_capacidade_parser.py` (fixture com 17 períodos, teste espera 29). Pré-existente, sem relação com o feedback; ajustar fixture ou expectativa.
- **Ambiente:** no sandbox foi preciso `pip install cffi` para o `pdfplumber` importar (`cryptography` do sistema sem `_cffi_backend`). Não afeta a VM (Docker instala do `requirements.txt`).
- **Segurança:** o token do Excia está em texto puro no `.env` do Drive (fora do git, correto). A nota de segurança do ROADMAP Sprint 4 (rotacionar o token) continua pendente.
- **`OPLista` é carregada inteira a cada 30 min** (até 20 páginas) só para descobrir OFs por pedido e capacidade. Funciona, mas é o ponto de latência da análise; a camada conversacional vai precisar de cache mais fino (ver Parte C).

### A9. Achados novos no relatório impresso do 107487 (17/09/2026)

O PDF gerado pela aplicação para o pedido 107487 (OF 270363, semana 2704) mostra três problemas que o gestor não citou:

- **Malha duplicada em três linhas.** `[03008234] M/M TINTA PT 30/1 GREED` aparece três vezes, com "Necessário" 305, 12 e 0,25 kg, cada uma com "FALTA — disponível 24/09". É o mesmo insumo e a mesma cor, vindo de três linhas da ficha técnica (faixas/partes diferentes). `MrpAdapter` agrega o `BlocoInsumo` por insumo+cor, mas anexa um `ProdutoMRP` por linha da ficha, e `matching.casar_com_mrp` gera um `MatchInsumo` por `ProdutoMRP`. Deve ser uma linha só: 317,25 kg necessários.
- **"Cor Divergente ()" falso e motivo "pedido (00001 PRETO) vs MRP (0 )".** O código de cor do insumo (`cor_i`, domínio de materiais) está sendo comparado com o código de cor do produto (domínio do pedido). São tabelas diferentes, e o próprio Alexandre explicou que os códigos nunca coincidem. Via API a comparação é sem sentido: `_resolver_cor_insumo` já traduz cor do produto → cor do insumo pela ficha técnica. O sinal útil é outro: quando a cor do produto **não existe** na lista de cores da ficha e o adapter cai no fallback "primeira cor", isso sim deve virar aviso ("cor 00001 não cadastrada na ficha técnica deste insumo; usando cor X").
- **Sexta versus quarta.** A caixa verde diz "Produzir na semana 2704 (termina 29/01/2027)", mas o cronograma oficial termina em 27/01/2027, quarta-feira, que é a âncora usada para OF emitida (`quarta_da_semana`). `_montar_sugestao` sempre usa `sexta_da_semana`. Quando há OF, a data da sugestão tem que ser a mesma do cronograma.

Também confirma A6 ao vivo: cinco insumos em FALTA, todos com "disponível 24/09/2026" (17/09 + 7 dias), inclusive a malha cuja própria cascata diz "necessita ordem de tecelagem + tinturaria".

### A8. O que a API do Excia oferece e ainda não usamos (útil para A3 e para o chat)

- `GET /Pedido/Fluxo?numero=` — devolve, por setor, `dt_inicio`, `dt_prev`, `dt_fim`, `situacao`. O exemplo da doc mostra setores comerciais ("ENTRADA PEDIDO", "CADASTRO DE CORES"), mas pode incluir os setores produtivos. **[VALIDAR NA VM]** com `numero=107487`. Se vier o cronograma de produção, é a fonte oficial para calibrar A3 e para exibir "cronograma real do Excia" ao lado do draft.
- `GET /BuscarMovimentacaoOP?numero=&parte=&setor=` — movimentações reais por setor (`dt_entrada`). Serve para **calibrar lead times reais** a partir de OFs concluídas (média por setor) e propor ao gestor o valor a cadastrar.

---

## Parte B — PROMPT 1: correções (Sprint 5)

> Cole o bloco abaixo num agente de código com acesso à pasta local do projeto e à VM.

```text
Você vai trabalhar no projeto "papinha-pcp-copilot" (FastAPI + engine Python, UI em ui/index.html,
integração com o ERP Excia via api/*_adapter.py). Leia docs/REVISAO_FEEDBACK_GESTOR_2026-09.md
inteiro antes de editar qualquer arquivo — ele tem a causa raiz de cada item abaixo com arquivo:linha.

REGRAS GERAIS
- Nenhum número mágico fora de config/*.yaml. Dúvida de regra de negócio → registrar em NOTES.md, não inventar.
- Toda mudança de cálculo vem com teste em tests/ usando datas fixas (nunca date.today()).
- Rodar `python -m pytest tests/ -q` antes e depois. Os 4 testes de test_capacidade_parser.py que já
  falham (fixture com 17 períodos vs 29 esperados) devem ser corrigidos no PASSO 0.
- Não alterar a lógica de autenticação (api/security.py, api/user_service.py) além do necessário para
  a tela de configuração.
- Commits pequenos, um por passo, em português, prefixo fix:/feat:/refactor:.

PASSO 0 — Sincronizar repositório
1. Na pasta local (G:\Meu Drive\Consultoria de IA\NEW\papinha-pcp-copilot), `git status` e commitar
   TODAS as alterações de 26/08 que não estão no GitHub (setor_adapter.py, security.py, user_service.py,
   login.html, admin.html, cascata de malha em mrp_adapter/models/matching/index.html). Confirmar que
   .env e data/users.db continuam no .gitignore. Push.
2. Corrigir a fixture/expectativa de tests/test_capacidade_parser.py. Suíte 100% verde.

PASSO 1 — Lead times por setor: Excia como fonte, yaml como cache
Contexto: api/setor_adapter.py usa um dicionário fixo (TINTURARIA 20, LAVANDERIA 10, EMBALAGEM 4) e ignora
o retorno de SetorLista; regras.yaml:fases_dias não é mais lido. O PCP cadastra os dias por setor NO EXCIA,
mas a documentação da API que temos não mostra esse campo (SetorLista/Setor/:codigo devolvem só
codigo/descricao/tipo; Fluxo/:codigo devolve setores sem prazo).
1. NA VM: `python scripts/explorar_lead_times.py 107487`. Ler o resumo e os JSON em
   scripts/output_exploratorio/lead_times/. Procurar: (a) campos numéricos não documentados por setor em
   Setor/:codigo, Fluxo/:codigo, ParteProdutoLista, OPLista; (b) datas por setor em Pedido/Fluxo e
   BuscarMovimentacaoOP para a OF 270363. Registrar o resultado em NOTES.md.
2. Se (a) existir: criar api/lead_time_adapter.py que lê esse campo e devolve {SETOR_NORMALIZADO: dias},
   com cache de 24 h e ressincronização manual.
   Se só (b) existir: o mesmo adapter deriva os dias por setor contando dias úteis entre dt_inicio e
   dt_prev de cada setor no cronograma oficial da OF (usar a OF mais recente por fluxo; mediana quando
   houver várias) e registra "derivado da OF nnnnnn em dd/mm".
   Se nem (a) nem (b): PARAR e perguntar ao usuário; ele leva a pergunta ao suporte da Excia
   ("qual endpoint devolve o prazo em dias cadastrado por setor no fluxo produtivo?"). Enquanto isso,
   seguir com o yaml semeado pelos valores que o gestor informar.
3. Criar config/lead_times.yaml como CACHE/FALLBACK, nunca como fonte primária:
     versao: 1
     sincronizado_em: "2026-09-17T10:00:00"
     fonte: "excia:Fluxo" | "excia:Pedido/Fluxo (derivado)" | "manual"
     setores: {PCP: 2, TECELAGEM: 5, TINTURARIA: 18, LAVANDERIA: 9, EMBALAGEM: 3, ...}
     aliases: {"ESTAMPA NUCA": ESTAMPARIA_NUCA, "QUAL. ESTAMPARIA": QUAL_ESTAMPARIA, "QUAL.": QUAL, ...}
4. Refatorar api/setor_adapter.py: remover _LEAD_TIMES_PADRAO_SETORES; resolver o nome da fase por alias +
   normalização (sem a cadeia de ifs por substring); ordem de resolução: adapter do Excia → yaml → aviso
   em log e 1 dia. Remover fases_dias de regras.yaml (manter só PCP_MIN/PCP_PADRAO, movidos para
   lead_times.yaml) e limpar cfg["fases_dias"] em engine/cronograma.py.
5. Tela de admin: aba "Lead times por setor" mostrando fonte e data de sincronização, botão
   "Ressincronizar do Excia", e edição manual permitida apenas com justificativa (grava usuario+data+motivo).
   Endpoints GET/POST /api/admin/lead-times e POST /api/admin/lead-times/sincronizar.
6. No card do cronograma: rodapé "Lead times: Excia, sincronizado em dd/mm/aaaa" (ou "manual, por X em dd/mm").
7. Testes: montar_cronograma com lead_times injetados; adapter com fixture JSON real salva no passo 1.

PASSO 2 — Calendário: feriados, férias coletivas e paradas
Contexto: parsers/comum.py tem FERIADOS_NACIONAIS fixo; não há endpoint de calendário na API do Excia.
0. Antes de criar o yaml, checar nos JSON do passo 1 se apareceu alguma chave de calendário
   (o script já grava tudo) e se o cronograma da OF em Pedido/Fluxo tem buracos entre setores que
   coincidam com feriados/férias. Se o Excia expuser o calendário, o adapter do passo 1 também o lê e o
   yaml abaixo vira cache, com a mesma tela de ressincronização.
1. Criar config/calendario.yaml:
     feriados:                # datas únicas (nacionais + municipais)
       - {data: "2026-11-02", descricao: "Finados"}
       ...
     paradas:                 # períodos inteiros sem produção
       - {inicio: "2026-12-21", fim: "2027-01-04", descricao: "Férias coletivas 2026/27", setores: TODOS}
   PERGUNTAR ao usuário as datas exatas das férias coletivas e feriados/pontes cadastrados no Excia.
2. parsers/comum.py: substituir FERIADOS_NACIONAIS por um módulo engine/calendario.py que carrega o yaml
   (cache em memória, recarregável) e expõe eh_dia_util(d), avancar_dias_uteis, recuar_dias_uteis,
   contar_dias_uteis. Manter os feriados nacionais 2025–2027 atuais como semente do yaml.
   Manter a assinatura das funções existentes para não quebrar cronograma.py.
3. Suporte a `setores:` nas paradas (TODOS ou lista): a engine aplica a parada só às fases daqueles setores.
   Na primeira versão, aceitar apenas TODOS e registrar em NOTES.md que paradas por setor ficam para depois.
4. Tela: aba "Calendário" em admin.html (listar/adicionar/remover feriados e paradas) com endpoints
   GET/PUT /api/admin/calendario.
5. UI do cronograma: quando uma fase atravessa uma parada, exibir marcador
   "⏸ inclui parada: Férias coletivas 21/12–04/01" abaixo da fase.
6. Testes: (a) fase de 5 dias começando 18/12/2026 termina depois de 04/01/2027 com a parada configurada;
   (b) backward a partir de 29/01/2027 recua o início de COSTURA para antes de 21/12.
7. Re-rodar o pedido 107487 na VM e comparar as datas de início com o cronograma da OF no Excia.

PASSO 3 — Contagem de dias coerente com as datas exibidas
Contexto: recuar_dias_uteis_excia usa "saída de uma fase = entrada da seguinte"; o rótulo (Nd) não bate
com a contagem inclusiva entre as datas mostradas (Revisão 12/01→20/01 rotulada 6d, são 7 inclusivos).
1. PRIMEIRO, usar a saída de scripts/explorar_lead_times.py (Pedido/Fluxo e BuscarMovimentacaoOP da
   OF 270363). Se vierem datas por setor, anotar em NOTES.md como o EXCIA apresenta entrada/saída de uma
   fase (mesma data de saída da anterior? dia seguinte?). Só se a API não trouxer, pedir ao usuário a tela
   de cronograma da OF no Excia (não o relatório da nossa aplicação, que reflete a nossa convenção).
2. Implementar conforme a resposta:
   - Se o Excia usa entrada = saída da anterior: manter as datas; renomear cabeçalhos para
     "Entrada → Saída" e mostrar entre parênteses "(N dias úteis)" calculando N a partir das datas
     exibidas com a MESMA convenção (dias úteis em (entrada, saída] para fases intermediárias e
     [entrada, saída] para a última). Explicar a convenção num tooltip "?" no cabeçalho do cronograma.
   - Se o Excia usa entrada = dia útil seguinte: em FaseCronograma adicionar `inicio_efetivo`
     (próximo dia útil após a entrada) e exibir inicio_efetivo → saída; o rótulo passa a ser a contagem
     inclusiva entre as duas datas.
3. Em qualquer caso: adicionar teste que garante rótulo == contagem de dias úteis entre as datas exibidas,
   para todas as fases, em três cenários (sem feriado, com feriado, com parada).

PASSO 4 — Sugestão explícita: semana de produção + nova entrega
Contexto: engine/analise.py:_montar_sugestao só diz "sugerir ao comercial nova entrega na semana X" e
calcula X = semana_sugerida + 1, enquanto a regra da casa é produção = entrega − 2.
1. Adicionar em regras.yaml: geral.semanas_entre_producao_e_entrega: 1 e
   geral.semanas_maximo_sem_autorizacao: 2 (regra confirmada em 17/09: entrega = produção + 1; o PCP pode
   sugerir até produção + 2; acima disso requer autorização do gestor). Usar esses valores em vez dos
   literais em _montar_sugestao e _decidir_veredito.
2. Reescrever _montar_sugestao para o caso inviável:
   "❌ Semana alvo 2702 não atende. Produção sugerida: semana 2704 (término 27/01/2027).
    Nova entrega a propor ao comercial: semana 2705 (05/02/2027)."
   e para o caso viável manter o formato atual, sempre citando a semana de produção e a data de término.
   A data de término tem que ser a MESMA do cronograma exibido: quarta-feira quando há OF emitida
   (quarta_da_semana), sexta na simulação pré-OF. Hoje a caixa diz 29/01 e o cronograma termina 27/01.
3. No cabeçalho do card (index.html), adicionar um quarto indicador "Semana de produção" (semana_sugerida)
   ao lado de "Semana Alvo", com cor do veredito.
4. Teste com o cenário do 107487: entrega 25/01/2027 → alvo 2702; sugerida 2704 → texto contém
   "2704", "29/01/2027" e a semana de nova entrega conforme a config.

PASSO 5 — Aritmética de semanas na virada de ano
Contexto: analise.py usa `semana_alvo - autonomia` e `semana_alvo - semana_sug` com inteiros AASS;
index.html usa `p.semana_alvo - 3`. Quebra em dezembro/janeiro (2702 − 3 = 2699).
1. Criar em parsers/comum.py: semanas_entre(aass_a, aass_b) -> int (diferença em semanas, sinal
   preservado) usando sexta_da_semana.
2. Substituir toda aritmética inteira de AASS em engine/analise.py (_decidir_veredito) por aass_add /
   semanas_entre. Grep por "semana_alvo -" e "- autonomia" no projeto inteiro.
3. Na UI, o backend passa a devolver `janela_autonomia: {inicio: 2651, fim: 2702}` em AnaliseCapacidade
   e index.html usa isso em vez de calcular.
4. Teste: alvo 2702, sugerida 2652 → veredito VERDE "Antecipação de 2 sem., dentro da autonomia";
   alvo 2702, sugerida 2650 → AMARELO "antecipação de 4 semanas".

PASSO 6 — Insumo em FALTA: parar de inventar "disponível em"
Contexto: insumos.py define disponivel_em = hoje + lead_time_compra (7 d) para todo insumo em FALTA e a
UI imprime "disponível dd/mm"; para malha isso é falso (precisa tecelagem + tinturaria).
1. Em MatchInsumo adicionar `previsao_tipo`: "ESTOQUE" | "A_CAMINHO" | "ESTIMATIVA" | "SEM_PREVISAO"
   e `previsao_detalhe: str`.
2. Regras em insumos.py:
   - OK_ESTOQUE → ESTOQUE, sem data.
   - OK_FUTURO → A_CAMINHO, data = hoje + lead time da coluna que cobre (já existe).
   - FALTA + malha/ribana (usar cascata_info): SEM_PREVISAO se não há malha crua; se há malha crua
     suficiente → ESTIMATIVA com data = hoje + lead time TINTURARIA (do lead_times.yaml) e detalhe
     "via tinturaria da malha crua em estoque"; se não há crua → detalhe "necessita tecelagem (X d) +
     tinturaria (Y d) = Z dias úteis" SEM data absoluta.
   - FALTA + aviamento → ESTIMATIVA com data = hoje + lead time de compra e detalhe "estimativa de compra".
3. UI: "✗ FALTA" + tag secundária com o detalhe; só exibir "disponível dd/mm" quando previsao_tipo for
   A_CAMINHO. ESTIMATIVA aparece como "estimativa: dd/mm (compra)".
4. Corrigir _e_bloqueante: normalizar nomes de fase (usar os mesmos aliases do lead_times.yaml) antes de
   comparar fase.nome com ins.fase_consumo; adicionar teste em que "QUAL. ESTAMPARIA" casa com
   QUAL_ESTAMPARIA.
5. Testes: malha com estoque 0 e crua 0 → SEM_PREVISAO e nenhuma data no JSON; malha com crua suficiente
   → ESTIMATIVA com data = hoje + TINTURARIA dias úteis.
6. Uma linha por insumo+cor: em engine/matching.casar_com_mrp, agrupar os ProdutoMRP do mesmo
   (cod_insumo, cod_cor) somando `consumo` antes de criar o MatchInsumo. Hoje a malha 03008234 aparece
   três vezes (305 + 12 + 0,25 kg) no relatório do 107487. Teste com fixture de ficha técnica com três
   faixas do mesmo insumo → um único MatchInsumo com necessario = soma.
7. "Cor Divergente" via API: remover a comparação bloco.cod_cor != linha.cor quando os dados vêm do
   MrpAdapter (são domínios diferentes: cor do material vs cor do produto). Substituir pelo aviso
   correto: MrpAdapter marca `cor_fallback=True` quando _resolver_cor_insumo não achou a cor do produto
   na ficha e usou a primeira; a UI mostra "⚠️ cor 00001 não cadastrada na ficha deste insumo (usando X)".
   Manter a checagem antiga apenas no caminho PDF (matching por OF do relatório MRP).

PASSO 7 — Validação de ponta a ponta na VM
1. Rodar /analisar-pedido para 107487 e para dois outros pedidos recentes; salvar o JSON em
   tests/fixtures/api/ (sem token) como fixture de regressão.
2. Conferir com o gestor: lead times exibidos = cadastro; datas respeitam férias coletivas; rótulos de
   dias batem com o calendário; sugestão cita semana de produção e nova entrega; nenhum "disponível"
   inventado para malha.
3. Atualizar README.md (seção "Configuração: lead times e calendário") e NOTES.md (decisões dos passos 3 e 4).
```

---

## Parte C — PROMPT 2: camada conversacional (Sprint 6) e resposta sobre esforço

### C1. Resposta direta à pergunta do gestor ("é possível? é muito trabalhoso?")

**É possível, e a parte difícil já está feita.** O que ele descreve ("recalcule com lavanderia em 6 dias em vez de 9") é uma camada de conversa em cima de um motor que já existe e é determinístico: a engine calcula cronograma, capacidade e insumos a partir de parâmetros. O que falta é (1) deixar esses parâmetros injetáveis por chamada, (2) expor a engine e os adapters do Excia como "ferramentas" para um modelo de linguagem, e (3) uma interface de chat.

O que a IA **não** deve fazer: calcular datas, somar estoque ou decidir veredito. Ela interpreta o pedido do analista, escolhe a ferramenta certa, passa os parâmetros e explica o resultado. Todo número que aparece na tela continua vindo da engine. Isso é o que torna o produto vendável: auditável e repetível.

Ordem de grandeza de esforço (uma pessoa, após a Sprint 5 concluída):

| Etapa | Escopo | Esforço |
|---|---|---|
| Sprint 5 (Parte B) | correções do feedback | 3 a 5 dias |
| Chat MVP | 1 pedido por conversa, 6 ferramentas, simulação com overrides de lead time/calendário/quebra, streaming, histórico da sessão | 2 a 3 semanas |
| Versão comercializável | multiempresa/multiusuário, histórico persistido, permissões, avaliação automática de qualidade (evals), observabilidade de custo, onboarding de outro ERP | mais 4 a 6 semanas |

Custo de uso (estimativa, modelo Claude Opus 5 a US$ 5/1M tokens de entrada e US$ 25/1M de saída, com cache do prompt de sistema e das ferramentas): uma conversa típica de 10 perguntas sobre um pedido fica na casa de **US$ 0,10 a 0,40**. Com Claude Sonnet 5 (US$ 2/10) cai para menos da metade. É irrelevante frente ao valor de uma OF cancelada.

### C2. Arquitetura proposta (resumo)

```
UI (chat + cards atuais)  ──SSE──▶  FastAPI /chat
                                       │
                                       ▼
                             Agente (Claude, tool use)
                             system prompt = glossário PCP + regras.yaml + convenções
                                       │  chama ferramentas (JSON estrito)
                                       ▼
        ┌──────────────────────────────────────────────────────────┐
        │ ferramentas (Python puro, sem LLM dentro)                 │
        │  buscar_pedido(numero)            → PedidoAdapter         │
        │  analisar_pedido(numero)          → orquestrador (cache)  │
        │  simular(numero, overrides)       → engine sobre snapshot │
        │  consultar_estoque(insumo, cor)   → Estoque / cascata     │
        │  consultar_capacidade(semanas)    → CapacidadeAdapter     │
        │  consultar_calendario(...)        → calendario.yaml       │
        │  listar_ofs(pedido | artigo)      → OPLista (índice)      │
        └──────────────────────────────────────────────────────────┘
                                       │
                          ContextoPedido (snapshot em cache por sessão):
                          pedido + ficha técnica + estoque + OFs + capacidade
                          → "recalcule com lavanderia 6" NÃO refaz chamadas ao Excia
```

Pontos de decisão que o prompt abaixo já assume (mude se discordar):

- **Somente leitura.** Nenhuma ferramenta escreve no Excia. Se um dia for gravar a OF, é uma ação explícita com confirmação, fora do chat.
- **Snapshot por sessão.** A primeira pergunta sobre um pedido carrega tudo (pode levar os mesmos 10–30 s de hoje); as seguintes são simulações locais em milissegundos.
- **Overrides sempre visíveis.** Toda resposta simulada mostra um banner "Simulação: LAVANDERIA 6d (cadastro: 9d)" e um botão "salvar como cadastro" que leva à tela de admin, nunca grava sozinho.
- **Trilha de auditoria.** Cada resposta guarda quais ferramentas foram chamadas e com quais parâmetros; o analista pode expandir.

### C3. PROMPT 2 (colar num agente de código, só depois da Sprint 5)

```text
Você vai adicionar uma camada conversacional ao projeto "papinha-pcp-copilot" (FastAPI, Python 3.11).
Leia docs/REVISAO_FEEDBACK_GESTOR_2026-09.md (Parte C) antes de começar. Pré-requisito: Sprint 5 concluída
(lead_times.yaml, calendario.yaml, sugestão explícita, aritmética de semanas corrigida).

PRINCÍPIOS (não negociáveis)
- A IA nunca calcula: datas, quantidades, semanas e vereditos vêm SEMPRE de ferramentas Python.
- Somente leitura no Excia. Nenhuma ferramenta chama POST/PATCH/DELETE.
- Todo número exibido é rastreável a uma chamada de ferramenta (trilha visível na UI).
- Português do Brasil, vocabulário do PCP (OF, semana AASS, quebra, lead time, malha crua/tinta).
- Sem números mágicos fora de config/. Dúvidas de regra → NOTES.md.

FASE 1 — Refatorar a engine para ser injetável (sem mudar resultados)
1. Criar engine/contexto.py com a dataclass ContextoPedido: pedido, linhas, fichas técnicas, estoques,
   ordens de tinturaria, OFs vinculadas, capacidade semanal, lead_times (dict), calendario (obj),
   parametros (buffer_pct, semanas_antes, autonomia...), carregado_em.
2. Criar engine/carregador.py: carregar_contexto(numero_pedido) -> ContextoPedido. É a ÚNICA função que
   fala com o Excia. Reaproveita os adapters existentes. Cache em memória por numero_pedido com TTL 30 min
   e invalidação manual.
3. montar_cronograma / avaliar_insumos / verificar_capacidade_pedido / analisar passam a receber o
   ContextoPedido (ou seus campos) em vez de instanciar FluxoAdapter()/SetorAdapter() internamente.
   Nenhuma função da engine pode importar api/* depois desta fase (adicionar teste que garante isso via
   inspeção de imports).
4. Criar engine/simulacao.py: simular(ctx, overrides) -> ResultadoAnalise, onde overrides é um dict
   validado por pydantic: lead_times: {SETOR: dias}, calendario_extra: [paradas], quebra_pct, qtde_por_cor,
   semana_alvo, semana_fim_producao, ignorar_capacidade: bool. Aplica os overrides numa CÓPIA do contexto
   e roda a mesma analisar(). Retorna também `diff` (o que mudou vs. resultado base: datas de início,
   semana sugerida, veredito, insumos bloqueantes).
5. Teste de equivalência: analisar_pedido_por_numero(numero) == simular(carregar_contexto(numero), {})
   usando as fixtures JSON de tests/fixtures/api/.

FASE 2 — Ferramentas
Criar chat/ferramentas.py com funções puras, cada uma com docstring em PT-BR (vira a descrição da
ferramenta) e schema de entrada estrito (pydantic → JSON Schema com additionalProperties=false):
  buscar_pedido(numero) → resumo do pedido (cliente, entrega, linhas, OFs existentes)
  analisar_pedido(numero, forcar_recarga=False) → ResultadoAnalise resumido (cards) + id_contexto
  simular(numero, overrides) → resultado + diff (ver Fase 1.4)
  consultar_estoque(cod_insumo, cod_cor=None) → estoque tinta, crua, ordens de tinturaria, cascata
  consultar_capacidade(semana_ini, semana_fim) → pendente por semana vs limite, semanas com folga
  consultar_calendario(data_ini, data_fim) → feriados e paradas no período
  listar_ofs(numero_pedido=None, codigo_artigo=None) → OFs com semana, situação, quantidades
  explicar_regra(nome) → texto de regras.yaml/lead_times.yaml (para "por que 2 semanas antes?")
Cada ferramenta devolve dicts pequenos (< 4 k tokens); listas longas são resumidas com contagem + top N
e um parâmetro `detalhar=True` para ver tudo.

FASE 3 — Agente
1. pip install anthropic (SDK oficial). Modelo: claude-opus-5 (padrão). Chave em ANTHROPIC_API_KEY no
   .env (nunca no código).
2. chat/agente.py usando client.beta.messages.tool_runner com as ferramentas da Fase 2 decoradas com
   @beta_tool. thinking={"type": "adaptive"}; output_config={"effort": "medium"} (subir para "high" se as
   avaliações da Fase 5 pedirem). Streaming ligado.
3. System prompt (chat/prompt_sistema.md, versionado) contendo: papel ("assistente do PCP da Papinha
   Baby"), glossário, as regras de negócio lidas de regras.yaml/lead_times.yaml em tempo de carga, a
   convenção de contagem de dias decidida na Sprint 5, o que a IA não faz (não calcula, não grava), e
   o formato de resposta (resumo em 2–4 frases + tabela quando houver datas + linha "Fontes: ferramentas
   chamadas"). Colocar cache_control ephemeral no system prompt e manter a lista de ferramentas em ordem
   fixa (prompt caching — verificar usage.cache_read_input_tokens > 0 a partir da 2ª mensagem).
4. Estado da conversa por sessão de usuário (já existe cookie de sessão): histórico de mensagens
   (limitar a 40 turnos, compactar os anteriores) + id_contexto ativo. Guardar em data/chat.db (sqlite)
   para sobreviver a reinício.
5. Guardrails no código (não confiar só no prompt): overrides de simulação só aceitam setores existentes
   em lead_times.yaml e dias entre 0 e 60; qualquer ferramenta que falhe devolve tool_result com
   is_error=true e mensagem em PT-BR; timeout de 90 s por turno.

FASE 4 — Interface
1. Novo painel lateral "Copiloto" em ui/index.html (ou ui/chat.html): caixa de mensagem, respostas em
   streaming (SSE via endpoint POST /chat/mensagem → GET /chat/stream/{id}), chips de sugestão
   ("Analisar pedido 107487", "E se lavanderia for 6 dias?", "Tem malha crua para esse pedido?",
   "Qual a primeira semana com folga de 3.000 peças?").
2. Quando a IA chama simular(), a UI re-renderiza o card do pedido com o resultado simulado, banner
   "SIMULAÇÃO — LAVANDERIA 6d (cadastro 9d)" e botão "Voltar ao cadastro". Botão "Aplicar no cadastro"
   abre a tela de admin com o valor pré-preenchido (não grava sozinho).
3. Cada resposta tem um expansor "Como cheguei nisso" listando ferramentas + parâmetros + tempo.
4. Impressão: o relatório comercial atual passa a aceitar a versão simulada, com marca d'água "SIMULAÇÃO".

FASE 5 — Qualidade e custo
1. tests/chat/cenarios.yaml com 20 perguntas reais (as do feedback do gestor + variações) e a resposta
   esperada em termos de ferramentas chamadas e números-chave. Rodar contra as fixtures (sem Excia).
2. Registrar por turno: tokens de entrada/saída/cache, custo estimado, ferramentas chamadas, latência.
   Endpoint /api/admin/chat-uso com totais por dia e por usuário.
3. Documentar em README.md: como configurar a chave, custo esperado, o que a IA faz e não faz.

ENTREGA MÍNIMA (MVP) = Fases 1, 2, 3 e 4.1–4.2. Fases 4.3–4.4 e 5 fecham a versão comercializável.
```

---

## Pendências (atualizado 17/09 após respostas do Marcos)

Resolvidas: regra de nova entrega (+1, máximo +2 sem autorização); token da API já rotacionado; cronograma
da aplicação para o 107487 já em mãos (PDF de 17/09, OF 270363).

1. **Rodar `scripts/explorar_lead_times.py 107487` na VM** e me enviar a pasta
   `scripts/output_exploratorio/lead_times/`. Isso decide se lead times e calendário vêm da API (caminho A)
   ou se a pergunta vai para o suporte da Excia (caminho B).
2. **Ao gestor, enquanto isso:** a tabela completa de dias por setor e as datas das férias coletivas/pontes,
   para semear o cache mesmo no caminho A (serve de conferência).
3. **Se o caminho B se confirmar:** e-mail ao suporte da Excia perguntando qual endpoint devolve (a) o prazo
   em dias cadastrado por setor no fluxo produtivo e (b) o calendário de feriados/paradas.
