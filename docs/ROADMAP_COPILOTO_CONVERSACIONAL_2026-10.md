# Roadmap — Copiloto Conversacional de PCP (pivot de produto)

Data: 13/10/2026
Origem: sugestão do gerente de PCP da Papinha Baby, repassada por Marcos no mesmo dia.
Este documento **substitui** a parte de lead times da Sprint 5 e **promove** a Sprint 6
(`docs/REVISAO_FEEDBACK_GESTOR_2026-09.md`, Parte C) de "fase 2, depois que a 5 terminar" para
entregável principal. As correções de bugs da Sprint 5 (seções A3–A8 do documento anterior) continuam
de pé e valem como estão — não foram afetadas por este pivot.

---

## 0. O que o gerente disse, e o que isso muda

> "O mercado está mudando muito rapidamente. Agora recebemos pedidos com prazos bem menos elásticos e
> precisamos dar conta de demandas mais imprevisíveis. Os lead times de cada etapa estão cada vez mais
> fluidos — não faz mais tanto sentido ter um valor fixo cadastrado por setor. O próprio agente de IA
> pode perguntar ao analista o lead time de cada etapa do fluxo (puxando os fluxos corretos) e montar o
> cronograma em potencial daquele pedido. Cada artigo pode ter um lead time diferente, dependendo do
> pedido — isso a gente trata internamente."

Duas implicações diretas, nessa ordem de importância:

1. **Lead time deixa de ser dado de cadastro e passa a ser dado de conversa.** Em vez de uma tabela
   fixa `setor → dias`, o copiloto pergunta ao analista, pedido a pedido (ou artigo a artigo), qual a
   duração de cada etapa. Isso **elimina a dependência** da tabela completa de 28 setores que eu ia
   pedir ao gestor na Sprint 5 original — boa notícia, menos trabalho de cadastro, e o dado fica sempre
   atualizado porque vem de quem está decidindo naquele momento.
2. **O escopo do produto cresce.** De "analisar um pedido pelo número" para "copiloto que conversa sobre
   o PCP em geral, sempre consultando a API do Excia". A análise de pedido vira **uma das** coisas que o
   copiloto sabe fazer, não a única.

**O que NÃO muda:**
- A engine determinística (cronograma backward, capacidade, insumos/MRP) continua sendo a única fonte
  de cálculo. O copiloto nunca calcula data de cabeça — ele monta os parâmetros (lead times informados,
  overrides) e chama a mesma engine de sempre.
- As correções de bugs da Sprint 5 original (contagem de dias, sugestão explícita com semana de
  produção, aritmética de semanas na virada de ano, insumo em falta sem data inventada, malha duplicada
  em três linhas, "Cor Divergente" falso positivo) continuam necessárias e independentes deste pivot.
- O calendário (feriados, férias coletivas) **continua cadastro estático**, não vira pergunta de
  conversa — é dado da empresa como um todo, não varia por pedido/artigo. Mantém o plano original:
  `config/calendario.yaml`, cadastrado uma vez, revisado quando mudar.
- Os adapters da API do Excia (`api/pedido_adapter.py`, `mrp_adapter.py`, `capacidade_adapter.py`,
  `fluxo_adapter.py`, `setor_adapter.py`) continuam sendo a única porta de entrada aos dados reais —
  somente leitura, sem mudança de permissão necessária além do que já temos.
- A resposta de 08/10 sobre MCP vs tool use continua valendo: isto é tool use direto na API da
  Anthropic, não MCP (ver `REVISAO_FEEDBACK_GESTOR_2026-09.md`, seção C0).

---

## 1. Antes vs. depois

| | Antes (Sprint 4 em produção + Sprint 5 original) | Depois (este roadmap) |
|---|---|---|
| Interface | Formulário: campo de número de pedido → card de resultado | Chat: qualquer pergunta sobre PCP, com cards embutidos nas respostas |
| Lead time por etapa | Cadastro fixo (`lead_times.yaml`), um valor por setor, igual para todo artigo | Perguntado na conversa, por pedido/artigo, com sugestão de referência |
| Fonte da sequência de etapas | API (`Fluxo/:codigo` via `ParteProdutoLista`) — **sem mudança** | Igual |
| Calendário (feriados/férias) | Cadastro fixo (`calendario.yaml`) | Igual — continua cadastro fixo |
| Casos de uso | 1: analisar pedido por número | N: analisar pedido, simular cenário, consultar estoque, consultar capacidade, explicar uma regra, comparar dois artigos, etc. |
| Quem decide o lead time de cada etapa | Ninguém — vinha hardcoded | O analista, na hora, pelo chat — "isso a Papinha trata internamente" |
| Resultado do cronograma | Uma data única | Uma data única (se o analista der valores pontuais) **ou** uma janela [semana W, semana Z] (se der faixas) |

---

## 2. Princípios de design (mantidos + um novo)

Os quatro princípios da Parte C do documento anterior continuam valendo:

- A IA nunca calcula data, quantidade ou veredito — isso é sempre a engine Python.
- Somente leitura na API do Excia.
- Todo número exibido é rastreável a uma chamada de ferramenta.
- Overrides sempre visíveis ("Simulação: Lavanderia 6d — informado pelo analista nesta conversa").

**Princípio novo, decorrente do pivot:** *lead time é sempre perguntado antes de calcular, nunca
assumido em silêncio.* A engine se recusa a montar um cronograma completo se faltar a duração de
alguma etapa do fluxo real do artigo — ela devolve a lista do que falta, e é job do agente perguntar
isso ao analista em português antes de tentar de novo. Isso é o mesmo princípio de "não inventar
número" de antes, levado ao grão de cada etapa em vez de um cadastro inteiro.

---

## 3. O mecanismo central: montar cronograma perguntando o que falta

Este é o núcleo técnico do pivot — tudo o resto do roadmap depende de como isso funciona.

```
Analista: "Analisa o pedido 107487"
   │
   ▼
Agente chama ferramenta buscar_pedido(107487)
   → pedido, artigo, cor, entrega: 25/01/2027
   │
   ▼
Agente chama ferramenta obter_fluxo_do_artigo(codigo_artigo)
   → via API real (ParteProdutoLista → Fluxo/:codigo, já funciona hoje)
   → sequência real de 28 etapas: PCP, TECELAGEM, TINTURARIA, ..., EMBALAGEM
   │
   ▼
Agente chama ferramenta montar_cronograma(pedido, fluxo, lead_times_informados={})
   → a engine tenta montar com o que tem: nada informado ainda
   → devolve PendenciaLeadTime(faltantes=[
        {"setor": "TECELAGEM", "sugestao_dias": 5, "origem_sugestao": "último usado neste artigo, em 12/09"},
        {"setor": "TINTURARIA", "sugestao_dias": 18, "origem_sugestao": "genérico, nunca confirmado p/ este artigo"},
        ... (uma entrada por etapa do fluxo real)
     ])
   │
   ▼
Agente pergunta ao analista, em português, mostrando as sugestões:
   "Para este pedido, preciso da duração de cada etapa. Tenho sugestões de uso anterior/genéricas —
    pode confirmar ou ajustar:
    • Tecelagem: 5 dias (última vez usada neste artigo) — confirma?
    • Tinturaria: 18 dias (sugestão genérica, nunca confirmada para este artigo) — qual valor usar?
    • Lavanderia: 9 dias (última vez usada) — confirma?
    ... "
   │
   ▼
Analista responde (pode confirmar tudo de uma vez, ajustar só uma, ou dar todas de uma vez
na primeira pergunta — o agente aceita qualquer forma de resposta em linguagem natural)
   │
   ▼
Agente chama montar_cronograma(pedido, fluxo, lead_times_informados={TECELAGEM: 5, TINTURARIA: 20, ...})
   → agora completo → engine calcula o cronograma real (backward scheduling, igual a hoje)
   → cada etapa no card final é marcada: "informado pelo analista" ou "sugestão aceita sem alteração"
   │
   ▼
Agente mostra o card de resultado (igual ao de hoje: cronograma, capacidade, insumos, veredito),
com o rodapé "Lead times desta simulação: 6 informados, 2 sugestões aceitas — nenhum hardcoded."
```

**Sobre as sugestões (`sugestao_dias`):** elas não são "o cadastro disfarçado de pergunta". São só um
ponto de partida pra agilizar a conversa — o analista nunca é obrigado a aceitar. Duas fontes possíveis,
em ordem de prioridade:
1. **Último valor confirmado para este artigo específico**, se existir (ver seção 4 — persistência leve).
2. **Um valor genérico de referência**, vindo de um `lead_times_sugeridos.yaml` pequeno (os mesmos
   números que já temos hoje no código, recicláveis como ponto de partida — não precisam da tabela
   completa de 28 setores do gestor, só o que já está no `setor_adapter.py` atual serve de semente).

Isso resolve de forma elegante um problema que a Sprint 5 original ia enfrentar: não sabíamos os 28
valores reais do Excia, e agora nem precisamos saber — quem sabe é o analista, a cada pedido.

---

## 3.1. Faixas (min–max) por etapa → janela de produção

Extensão pedida por Marcos em 13/10: em vez de um valor único por etapa, o analista pode informar uma
**faixa** — "Tecelagem: de 4 a 6 dias". Faz sentido dado o motivo do pivot (lead times fluidos e
incertos): forçar um número único quando a realidade é "depende" é precisão falsa. A engine aceita as
duas formas na mesma pergunta: "5 dias" vira `min=max=5` (igual a hoje, caso particular); "de 4 a 6"
vira `min=4, max=6`.

**O que a engine faz com a faixa:** roda o mesmo cálculo de cronograma (forward, a partir de hoje ou da
emissão da OF) **duas vezes** — uma com o mínimo de cada etapa, outra com o máximo:

- **Cenário otimista** (todos os mínimos): termina mais cedo → semana **W**.
- **Cenário pessimista** (todos os máximos): termina mais tarde → semana **Z**.
- **Janela de produção**: de W até Z. Se toda etapa tiver faixa de largura zero (valor único), `W = Z`
  e o resultado é idêntico ao de hoje — a faixa é uma generalização do mecanismo, não um modo à parte.

Exemplo ilustrativo (fluxo real do 107487, números fictícios):

| Etapa | Faixa informada | Usado no cenário otimista | Usado no cenário pessimista |
|---|---|---|---|
| Tecelagem | 4–6 dias | 4 | 6 |
| Tinturaria | 16–20 dias | 16 | 20 |
| Lavanderia | 9 dias (valor único) | 9 | 9 |

→ "Produção pode terminar entre a semana **2702** (cenário otimista) e a semana **2705** (pessimista)."

**Como isso entra na checagem de capacidade e no veredito** — comparado nos dois extremos, não só num
ponto:
- **Mesmo no cenário pessimista (Z) cabe na semana alvo** → verde, sem ressalva.
- **Cabe no cenário otimista (W) mas não no pessimista (Z)** → amarelo, com o motivo explícito: "Viável
  se os lead times reais ficarem perto do mínimo informado; no pior cenário estoura a semana alvo em N
  semanas — acompanhar de perto."
- **Nem o cenário otimista (W) cabe** → vermelho, como hoje; a nova data proposta ao comercial usa o
  cenário pessimista (Z) como base — mais conservador é mais seguro para prometer ao cliente.

Uma janela [W, Z] é uma resposta mais honesta do que uma data única: reflete a incerteza real que o
gerente descreveu, em vez de fingir uma precisão que a própria empresa diz não ter mais.

---

## 4. Decisão de design — resolvida em 13/10/2026

Confirmado por Marcos em 13/10: **persistir o que o analista responde, sempre como sugestão — nunca
aplicado automaticamente.** Dois ajustes fechados junto com a confirmação:

- **"Guardar e informar o usuário":** toda vez que o copiloto for perguntar o lead time de uma etapa
  para um artigo que já teve resposta antes, ele **mostra explicitamente** a última definição ("da
  última vez, em 28/09, você informou 4–6 dias para Tecelagem neste artigo") — nunca aplica em
  silêncio. `data/lead_times_confirmados` guarda `(codigo_artigo, setor, dias_min, dias_max,
  confirmado_por, confirmado_em)` — um valor único fica `dias_min = dias_max`; a sugestão da próxima
  vez já sai no mesmo formato que o analista deu (ponto ou faixa).
- **"A decisão dele no chat é soberana":** a resposta do analista nesta conversa **sempre** prevalece
  sobre sugestão, histórico ou valor genérico — sem exceção, sem segunda confirmação pedida pelo
  agente. Isso vira regra explícita no system prompt (seção 8, PASSO 5): o agente nunca questiona nem
  tenta "corrigir" uma resposta comparando com o histórico. No máximo, se o valor for muito diferente
  do último usado, pode mencionar isso uma vez — mas segue com o que o analista confirmar.

Outras duas perguntas menores, que assumo com uma resposta padrão abaixo (sem bloquear o início):

- **Quem usa o chat:** assumo que é uso interno do PCP (os mesmos usuários que hoje têm login no
  admin), não comercial nem cliente final. Se isso mudar, a trilha de auditoria e as permissões mudam.
- **Uma conversa, um pedido, ou vários:** assumo que o copiloto deve aguentar trocar de assunto na mesma
  conversa ("agora olha o pedido 94736") sem precisar abrir um chat novo — já é o desenho natural de um
  agente com tool use (cada chamada de ferramenta leva o número do pedido), só estou deixando explícito
  porque muda um pouco a lógica de cache por sessão da Parte C original (que assumia "1 pedido por
  conversa" como contexto único).

---

## 5. Sprints revisadas

### Sprint 5 (revisada e reduzida) — Fundação: engine parametrizável + correções de bugs

Objetivo: a engine para de ler lead time de qualquer cadastro fixo e passa a recebê-lo como parâmetro
explícito, sempre. Isso é pré-requisito técnico para a Sprint 6 — sem isso, não tem como o chat
"perguntar e usar a resposta".

1. **Refatorar `engine/cronograma.py`:** `montar_cronograma()` passa a receber um dict
   `lead_times_informados: dict[str, tuple[int, int]]` (chave = nome normalizado do setor, valor =
   `(dias_min, dias_max)` — um valor único é `(N, N)`) em vez de instanciar `SetorAdapter()`
   internamente para resolver duração. Se uma etapa do fluxo real não está no dict, a função devolve um
   objeto `PendenciaLeadTime` (ver seção 3) em vez de calcular com um valor inventado. **Nenhum
   fallback silencioso.**
2. **Nova função `engine/cronograma.py:montar_janela_producao()`:** recebe o mesmo
   `lead_times_informados` (com faixas) e chama `montar_cronograma()` duas vezes internamente — uma
   com `dias_min` de cada etapa, outra com `dias_max` — devolvendo
   `JanelaProducao(cenario_otimista: Cronograma, cenario_pessimista: Cronograma, semana_w: int,
   semana_z: int)`. Quando todas as faixas são degeneradas (`min == max`), `semana_w == semana_z` e o
   comportamento é idêntico ao `montar_cronograma()` único de hoje — ver seção 3.1.
3. **`api/setor_adapter.py` muda de papel:** deixa de ser "a fonte do lead time" e vira
   `gerador_de_sugestao(codigo_artigo, setor) -> SugestaoLeadTime(dias_min, dias_max, origem)`,
   consultando primeiro `data/lead_times_confirmados` e caindo para `config/lead_times_sugeridos.yaml`
   (os valores atuais do código, reaproveitados como semente de `(N, N)`) se não houver histórico. Esse
   arquivo eu já posso criar com os valores que já existem no `setor_adapter.py` de hoje — não preciso
   esperar nenhuma tabela do gestor.
4. **Calendário (sem mudança de plano):** `config/calendario.yaml` + `engine/calendario.py`, exatamente
   como descrito no `PROMPT 1` original (Parte B, PASSO 2) — ainda preciso das datas de férias coletivas
   com você/gestor, mas isso é independente do pivot de lead time.
5. **Bugs do feedback original (A3–A8), sem mudança:** contagem de dias coerente com as datas exibidas,
   sugestão com semana de produção explícita, correção da aritmética de semanas na virada de ano,
   insumo em falta sem data inventada, malha duplicada em três linhas no relatório, "Cor Divergente"
   falso positivo via API. Ver `PROMPT 1` original, PASSOs 3–6 — continuam valendo como estão.
6. Testes: `montar_cronograma`/`montar_janela_producao` com `lead_times_informados` completo (calcula
   normal, inclusive faixas não degeneradas) e incompleto (devolve `PendenciaLeadTime` com a lista certa
   de setores faltantes).

Esforço: 3–4 dias (menor que a Sprint 5 original, porque elimina o trabalho de cadastro manual de 28
setores — agora é só refatorar a engine para receber parâmetro em vez de ler de um arquivo).

### Sprint 6 (entregável principal) — Copiloto Conversacional

Reaproveita quase integralmente o `PROMPT 2` da Parte C do documento anterior (Fases 1–5), com dois
ajustes:

- **Fase 1 (Contexto/Simulação):** `engine/simulacao.py` passa a expor `montar_janela_producao()` (com
  `PendenciaLeadTime` quando faltar etapa) como a interação padrão, não como um "modo avançado de
  override". É o caminho principal, não uma exceção.
- **Fase 2 (Ferramentas):** a ferramenta principal é `montar_cronograma(pedido, lead_times_informados)`,
  aceitando ponto ou faixa por etapa (ver seção 3.1) e devolvendo cronograma único **ou** janela
  [W, Z] conforme o que foi informado; mais `sugerir_lead_time(codigo_artigo, setor)` para o agente
  mostrar a sugestão (com histórico, se houver) antes de perguntar. As demais ferramentas da lista
  original (`buscar_pedido`, `consultar_estoque`, `consultar_capacidade`, `consultar_calendario`,
  `listar_ofs`, `explicar_regra`) continuam exatamente como estavam.
- **System prompt (Fase 3):** instrução central do pivot: "Antes de montar qualquer cronograma, você
  precisa da duração de CADA etapa do fluxo real do artigo — um valor único ou uma faixa (min–max). Se
  a ferramenta devolver `PendenciaLeadTime`, pergunte ao analista as etapas faltantes, mostrando a
  sugestão/histórico quando houver e deixando claro que é só sugestão. A resposta do analista nesta
  conversa é sempre soberana — nunca questione ou substitua por conta própria. Se o resultado vier como
  janela (W a Z), apresente os dois extremos, nunca só um número escondendo a incerteza."
- Fases 4 (interface) e 5 (qualidade/custo) seguem como estavam.

Esforço: 2–3 semanas para o MVP (igual à estimativa original — o mecanismo de pergunta de lead time
é só mais um fluxo de ferramenta dentro do que já estava desenhado, não um módulo à parte).

---

## 6. Pendências, atualizadas pelo pivot

**Caiu da lista** (não precisa mais, boa notícia): a tabela completa de dias por setor que eu ia pedir
ao gestor para os 28 setores do fluxo L13. Isso agora é dado de conversa, não de cadastro.

**Continua de pé:**
1. Datas das férias coletivas 2026/27 e demais paradas/pontes — ainda necessário para
   `config/calendario.yaml` (Sprint 5, item 3 acima). Isso não mudou com o pivot.
2. E-mail ao suporte oficial da Excia sobre endpoint de calendário (a pergunta sobre lead time por setor
   pode ser retirada do e-mail — não faz mais sentido perguntar, já que decidimos não depender da API
   pra isso).
3. Cronograma impresso da OF 270363 no Excia — ainda ajuda a fechar a convenção de contagem de dias
   (Sprint 5, item 4), independente do pivot.
4. **Nova, decorrente deste documento:** sua confirmação sobre a seção 4 (persistir sugestão por artigo
   ou sempre perguntar do zero) antes de eu travar o desenho da Fase 1 da Sprint 6.

---

## 7. Próximo passo

Decisões fechadas (seção 4) e mecanismo de faixas especificado (seção 3.1) — nada mais bloqueia o
início. O `PROMPT` consolidado está na seção 8, pronto para colar num agente de código.

---

## 8. PROMPT consolidado — Sprint 5 revisada + Sprint 6, pronto para colar num agente de código

```text
Você vai trabalhar no projeto "papinha-pcp-copilot" (FastAPI + engine Python, UI em ui/index.html,
integração com o ERP Excia via api/*_adapter.py). ANTES de editar qualquer arquivo, leia nesta ordem:
  1. docs/ROADMAP_COPILOTO_CONVERSACIONAL_2026-10.md (este documento) — inteiro, é o plano vigente.
  2. docs/REVISAO_FEEDBACK_GESTOR_2026-09.md — Parte A (causa raiz dos bugs A3-A8) e Parte B, PASSOs
     3-6 (correções que continuam valendo sem mudança) e Parte C, seção C0 (por que isto é tool use,
     não MCP).

PRINCÍPIOS (não negociáveis, do documento acima)
- A IA nunca calcula data, quantidade ou veredito — sempre a engine Python.
- Lead time nunca é assumido em silêncio: se faltar a duração de alguma etapa do fluxo real do
  artigo, a engine devolve PendenciaLeadTime e é o agente quem pergunta ao analista — nunca um
  fallback automático vira resposta final sem o analista ter visto e aceitado.
- A resposta do analista na conversa é SEMPRE soberana sobre sugestão, histórico ou valor genérico.
- Lead time pode ser ponto (N dias) ou faixa (min-max dias) — ponto é o caso particular min=max.
- Somente leitura na API do Excia. Nenhuma ferramenta chama POST/PATCH/DELETE.
- Todo número exibido é rastreável a uma chamada de ferramenta, com a trilha visível na UI.
- Sem números mágicos fora de config/. Dúvida de regra de negócio -> NOTES.md, nunca inventar.
- Commits pequenos, um por passo, em português, prefixo fix:/feat:/refactor:. Rodar
  `python -m pytest tests/ -q` antes e depois de cada passo.

PASSO 0 — Sincronizar e confirmar estado
1. `git status`, `git pull` — confirmar que está em cima do commit mais recente da branch de trabalho.
2. Rodar a suíte de testes; deve estar 100% verde antes de começar (era o estado em 13/10/2026).

PASSO 1 — Modelos novos (engine/models.py)
Adicionar, sem remover nada existente:
  @dataclass
  class SugestaoLeadTime:
      dias_min: int
      dias_max: int
      origem: str          # "ultimo_confirmado" | "generico" | "sem_sugestao"
      confirmado_em: Optional[date] = None   # quando origem == ultimo_confirmado

  @dataclass
  class PendenciaLeadTime:
      setores_faltantes: list[str]           # nomes normalizados, na ordem do fluxo real
      sugestoes: dict[str, SugestaoLeadTime]  # chave = mesmo nome; pode estar vazio p/ um setor

  @dataclass
  class JanelaProducao:
      cenario_otimista: Cronograma
      cenario_pessimista: Cronograma
      semana_w: int   # AASS, fim do cenário otimista
      semana_z: int   # AASS, fim do cenário pessimista (semana_w == semana_z se não há faixa real)

PASSO 2 — engine/cronograma.py parametrizável (substitui a leitura de SetorAdapter)
1. `montar_cronograma(linha, match, hoje, cfg, lead_times_informados: dict[str, tuple[int,int]])`:
   para cada etapa do fluxo real (via FluxoAdapter, sem mudança), resolver a duração a partir de
   `lead_times_informados[nome_normalizado]`. Se a chave não existir, NÃO usar fallback (remover a
   leitura de SetorAdapter.obter_lead_time_fase daqui) — em vez disso, acumular o nome do setor que
   falta e, ao final, se houver algum faltante, retornar PendenciaLeadTime em vez de Cronograma
   (mudar o tipo de retorno para `Cronograma | PendenciaLeadTime`, ajustar os chamadores).
   Quando o valor informado for uma faixa não degenerada (min != max), usar `min` para este cálculo
   (ele é sempre chamado uma vez internamente por `montar_janela_producao`, nunca direto com faixa).
2. Nova função `montar_janela_producao(linha, match, hoje, cfg, lead_times_informados) ->
   JanelaProducao | PendenciaLeadTime`: monta dois dicts auxiliares (`{k: v[0] for k,v in ...}` e
   `{k: v[1] for k,v in ...}`), chama `montar_cronograma` com cada um (reaproveitando
   `ajustar_cronograma_backward` como hoje, se aplicável a cada cenário), e devolve `JanelaProducao`
   com `semana_w = cenario_otimista.semana_fim_aass`, `semana_z = cenario_pessimista.semana_fim_aass`.
   Testar explicitamente o caso degenerado (todas as faixas min=max) -> semana_w == semana_z e os dois
   cronogramas idênticos.
3. `api/setor_adapter.py`: renomear/reescrever para expor
   `gerar_sugestao(codigo_artigo: str, setor: str) -> SugestaoLeadTime`, consultando primeiro
   `data/lead_times_confirmados` (PASSO 3) e caindo para `config/lead_times_sugeridos.yaml` (semear
   com os valores hoje hardcoded em `_LEAD_TIMES_PADRAO_SETORES`, como `(N, N)` cada) se não houver
   histórico; se nem isso existir, `origem="sem_sugestao"` com `dias_min=dias_max=0` e a UI/agente
   tratam isso como "sem sugestão, preciso do valor do zero".

PASSO 3 — Persistência leve de confirmações (nova)
1. `data/lead_times_confirmados.sqlite` (schema mínimo: codigo_artigo, setor, dias_min, dias_max,
   confirmado_por, confirmado_em — chave única em codigo_artigo+setor, UPSERT a cada confirmação).
   Adicionar ao .gitignore (mesmo padrão de data/*.db já existente).
2. `engine/persistencia_lead_time.py`: `buscar_ultimo(codigo_artigo, setor) -> Optional[SugestaoLeadTime]`
   e `confirmar(codigo_artigo, setor, dias_min, dias_max, confirmado_por)`.
3. Testes com um sqlite temporário (tmp_path do pytest) — não usar o arquivo real nos testes.

PASSO 4 — Calendário (sem mudança de desenho; ver PROMPT 1 original, Parte B PASSO 2)
Implementar config/calendario.yaml + engine/calendario.py exatamente como especificado lá. Datas de
férias coletivas: usar o que o Marcos já tiver fornecido; se ainda não tiver, deixar uma parada de
exemplo claramente marcada "PLACEHOLDER - substituir" e registrar em NOTES.md.

PASSO 5 — Bugs do feedback (A3-A8), sem mudança de desenho
Implementar PROMPT 1 original (docs/REVISAO_FEEDBACK_GESTOR_2026-09.md, Parte B), PASSOs 3, 4, 5, 6 —
contagem de dias coerente, sugestão com semana de produção explícita, aritmética de semanas na virada
de ano, insumo em falta sem data inventada, malha duplicada em três linhas, "Cor Divergente" falso
positivo via API. Esses passos não dependem do pivot de lead time e podem ser feitos em paralelo ao
PASSO 1-3 acima se o agente trabalhar em arquivos diferentes.

PASSO 6 — Camada conversacional (reaproveita Parte C do PROMPT 2 original, Fases 1-5, com os ajustes
abaixo — ler a Parte C inteira primeiro, este passo só lista o que MUDA em relação a ela)
1. Fase 1 (contexto/simulação): engine/contexto.py e engine/simulacao.py como já especificados lá,
   mas `simular()` usa `montar_janela_producao` (PASSO 2) em vez de `montar_cronograma` direto.
2. Fase 2 (ferramentas) — lista revisada:
     buscar_pedido(numero)
     obter_fluxo_do_artigo(codigo_artigo)          # NOVA: expõe FluxoAdapter como ferramenta de 1a classe
     sugerir_lead_time(codigo_artigo, setor)       # NOVA: chama gerar_sugestao (PASSO 2.3)
     montar_cronograma(numero_pedido, lead_times_informados)
       # NOVA assinatura: lead_times_informados: dict[str, {"min": int, "max": int}]
       # devolve: {"status": "pendente", "faltantes": [...], "sugestoes": {...}}
       #       ou {"status": "ok", "semana_w": int, "semana_z": int, "cronograma_otimista": {...},
       #           "cronograma_pessimista": {...}, "veredito": "...", "motivos": [...]}
     consultar_estoque(cod_insumo, cod_cor=None)
     consultar_capacidade(semana_ini, semana_fim)
     consultar_calendario(data_ini, data_fim)
     listar_ofs(numero_pedido=None, codigo_artigo=None)
     explicar_regra(nome)
   Confirmar_lead_time(codigo_artigo, setor, dias_min, dias_max)  # NOVA: grava via PASSO 3.2, chamada
     pelo agente depois que o analista responde, ANTES de rechamar montar_cronograma
3. Fase 3 (system prompt): usar o texto da seção 5 (Sprint 6) deste roadmap como base da instrução
   central, mais o glossário/regras já especificados na Parte C original.
4. Fases 4 (interface) e 5 (qualidade/custo): como na Parte C original, com um ajuste na Fase 4.2 — a
   UI do card de resultado precisa saber renderizar tanto um cronograma único (semana_w == semana_z)
   quanto uma janela (duas datas de término, duas timelines ou uma timeline com faixa visual).

PASSO 7 — Validação de ponta a ponta
1. Rodar o fluxo completo com o pedido 107487: pedir ao chat para analisá-lo, responder com faixas
   propositalmente diferentes em pelo menos duas etapas, confirmar que a janela [W, Z] sai coerente e
   que o veredito reflete os dois cenários (ver seção 3.1 para os três casos: verde/amarelo/vermelho).
2. Repetir a mesma pergunta para o mesmo artigo em uma nova conversa e confirmar que a sugestão mostrada
   agora reflete o que foi confirmado na primeira rodada (PASSO 3), e que uma resposta diferente do
   analista nesta segunda rodada prevalece sem o agente questionar.
3. Atualizar README.md e NOTES.md com o novo fluxo (lead time por conversa, não por cadastro).
```

---

## 9. Revisão do Bloco 1 (commit `3e5d815`, 13/10/2026) — correções obrigatórias antes do Bloco 2

Revisão feita puxando o diff real (`git diff a2f0469 3e5d815`), não o resumo reportado pelo agente.
`engine/models.py` está correto, igual ao especificado no PASSO 1. Mas `engine/cronograma.py` e
`engine/analise.py` têm três problemas — um deles quebra a aplicação em produção hoje. **Bloco 2
(PASSO 4 calendário / PASSO 5 bugs A3-A8) só deve começar depois desses três pontos corrigidos e
testados.**

### PROMPT — colar no Antigravity

```text
Revisão do Bloco 1 (commit 3e5d815) encontrou 3 problemas em engine/cronograma.py e
engine/analise.py. Corrigir os três, nesta ordem, antes de iniciar qualquer tarefa do Bloco 2.

PROBLEMA 1 (CRÍTICO — quebra a produção agora) — app.py e engine/orquestrador.py NÃO foram
alterados neste commit: a chamada em produção continua sendo
analisar(pedidos, mrp, cap, hoje, CONFIG, resultado), sem passar lead_times_informados. Como esse
parâmetro é opcional e hoje ninguém o preenche (o chat ainda não existe), montar_cronograma()
recebe lts_norm vazio, todo setor de todo fluxo cai em setores_faltantes, e TODO pedido analisado
hoje — incluindo o 107487 que o Alexandre está testando — devolve PendenciaLeadTime. Resultado:
veredito fixo "AMARELO", sem semana sugerida, sem cronograma algum, para 100% dos pedidos. Isso é
uma regressão total do caso de uso que está em uso real agora, não um caso de borda.

Correção exigida: enquanto o chat (PASSO 6) não existir, montar_cronograma() precisa continuar
produzindo um cronograma utilizável mesmo sem lead_times_informados completo, usando
automaticamente o valor de gerar_sugestao() (api/setor_adapter.py, já implementado no PASSO 2)
como valor efetivo para qualquer etapa que não veio no dict informado — min e max da sugestão,
nunca um fallback diferente. Ajustar também engine/analise.py: quando QUALQUER etapa foi resolvida
via sugestão automática (não por um valor vindo de lead_times_informados), marcar o card
resultante com um aviso explícito e visível (ex.: flag "lead_time_sugerido_nao_confirmado": true,
e incluir nos motivos/avisos do veredito algo como "Lead time de N etapa(s) ainda não confirmado
pelo analista — usando sugestão: <origem>"). O veredito não precisa virar AMARELO automaticamente
por isso (mantém a lógica normal de _decidir_veredito), mas o aviso tem que aparecer no card e na
UI atual, para o gestor sempre saber que aquele cronograma usa valor sugerido, não confirmado — é
isso que cumpre o princípio "lead time nunca é assumido em silêncio" sem derrubar o uso diário da
aplicação. PendenciaLeadTime só deve ser devolvida quando gerar_sugestao() também não tiver
nenhuma sugestão (origem="sem_sugestao", dias_min=dias_max=0) para aquela etapa — nesse caso sim,
não há nenhum número para usar, e cai no fluxo de pendência real.

PROBLEMA 2 — a função _calcular_pcp_dias() (cálculo da duração da etapa PCP a partir do status do
insumo: OK_ESTOQUE→2d, via tinturaria→14d, via tecelagem→21d, via compra/FALTA→28d) foi apagada
inteiramente, e o parâmetro match de montar_cronograma() ficou sem uso (pcp_dias virou um valor
fixo "= 2"). Essa lógica é independente do pivot de lead-time-por-conversa — ela decide a duração
de UMA etapa (PCP) a partir da disponibilidade real do insumo no MRP, não de um cadastro estático,
e segue necessária. Restaurar _calcular_pcp_dias() (pode ter outro nome) e voltar a usá-la para
resolver a duração da etapa PCP a partir de match/match.insumos, exatamente como antes do commit
3e5d815 — a única mudança deve ser que as OUTRAS etapas (não-PCP) agora vêm de
lead_times_informados/sugestão em vez do cadastro YAML antigo. Se o analista informar
explicitamente um valor para "PCP" no chat (lead_times_informados), esse valor informado prevalece
sobre o cálculo automático — a sovereignty da resposta do analista (seção 4 do ROADMAP) vale também
para PCP.

PROBLEMA 3 — em montar_cronograma(), o bloco de matching por substring:
    for k in lts_norm:
        if k == f_norm or k in f_norm or f_norm in k:
            matched_key = k
é perigoso porque normalizar_nome_setor() (api/setor_adapter.py) só remove acento/caixa, sem
tabela de aliases. Isso pode copiar o lead time confirmado de uma etapa (ex. "COSTURA") para outra
etapa totalmente diferente cujo nome normalizado contém ou é contido pelo primeiro (ex.
"QUAL_COSTURA", "SUB_COSTURA") — sem nunca sinalizar pendência nem perguntar nada ao analista.
Isso viola diretamente o princípio "nunca assumir lead time em silêncio" do projeto.
Correção exigida: remover o matching por substring. Cada etapa do fluxo real (todos_setores) só é
considerada resolvida se normalizar_nome_setor(etapa) tiver uma correspondência EXATA em lts_norm
(ou, com a correção do Problema 1, em gerar_sugestao()). Qualquer etapa sem correspondência exata
usa a sugestão (Problema 1) ou cai em setores_faltantes/pendência real, nunca herda o valor de uma
etapa de nome parecido. Se no futuro houver necessidade real de tratar sinônimos de nome de setor
(ex.: a API da Excia usar grafias diferentes para a mesma etapa), isso deve ser uma tabela explícita
de aliases, revisada por nós, nunca um match heurístico por substring.

VALIDAÇÃO OBRIGATÓRIA antes de reportar o Bloco 1 como concluído:
1. Teste de regressão cobrindo exatamente o cenário de produção atual: chamar
   analisar_pedido_por_numero(numero, CONFIG) SEM nenhum lead_times_informados (como app.py faz
   hoje) para um pedido real (ex. equivalente ao 107487) e assertar que o resultado tem um
   cronograma válido (não None) e o aviso de "sugestão não confirmada" presente — nunca
   PendenciaLeadTime nesse caminho, a menos que genuinamente não haja nenhuma sugestão disponível.
2. Teste cobrindo o Problema 2: um match com insumo em status "FALTA" (ou outro status não-estoque)
   deve produzir pcp_dias igual ao valor calculado por via de compra+tecelagem+tinturaria, igual ao
   comportamento anterior ao commit 3e5d815 — não o valor fixo 2.
3. Teste cobrindo o Problema 3: dois setores cujo nome normalizado é substring um do outro (ex.
   "COSTURA" e "QUAL_COSTURA") devem ser tratados como pendências/sugestões independentes — nunca
   um herdando o lead time informado do outro.
4. Rodar a suíte completa (76 testes atuais + os novos) e confirmar 100% verde antes do push.
5. No push, descrever exatamente o que mudou nos 3 pontos acima — não basta dizer "ajustes finos".

Só depois dessa validação o Bloco 2 (PASSO 4 — calendário, PASSO 5 — bugs A3-A8) deve começar.
```

