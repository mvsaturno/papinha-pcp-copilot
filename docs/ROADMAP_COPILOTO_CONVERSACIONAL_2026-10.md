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

## 4. Decisão de design que preciso que você confirme: persistir o que o analista responde?

Minha recomendação, já assumida no desenho acima: **sim, mas só como sugestão, nunca aplicado
automaticamente.**

- Guardar em `data/lead_times_confirmados.sqlite` (ou JSON simples) uma linha por
  `(codigo_artigo, setor, dias, confirmado_por, confirmado_em)` toda vez que um cronograma é fechado.
- Na próxima vez que o mesmo artigo aparecer, a sugestão mostrada ao analista passa a ser "a última vez
  que você usou, foi X dias" em vez do genérico — mais útil, mas **continua sendo pergunta**, nunca vira
  cadastro fixo de novo pela porta dos fundos.
- Se você preferir que o agente **sempre** pergunte do zero, sem lembrar de pedidos anteriores (mais
  simples de construir, zero persistência além do histórico de chat), é só me dizer — é uma troca de
  poucas linhas no desenho acima, tiro a fonte 1 das sugestões e fica só a genérica.

Outras duas perguntas menores, que também assumo com uma resposta padrão abaixo mas vale confirmar:

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
   `lead_times_informados: dict[str, int]` (chave = nome normalizado do setor) em vez de instanciar
   `SetorAdapter()` internamente para resolver duração. Se uma etapa do fluxo real não está no dict,
   a função devolve um objeto `PendenciaLeadTime` (ver seção 3) em vez de calcular com um valor
   inventado. **Nenhum fallback silencioso.**
2. **`api/setor_adapter.py` muda de papel:** deixa de ser "a fonte do lead time" e vira
   `gerador_de_sugestao(codigo_artigo, setor) -> (dias_sugeridos, origem_sugestao)`, consultando primeiro
   `data/lead_times_confirmados` (se a decisão da seção 4 for "sim, persistir") e caindo para
   `config/lead_times_sugeridos.yaml` (os valores atuais do código, reaproveitados como semente) se não
   houver histórico. Esse arquivo eu já posso criar com os valores que já existem no `setor_adapter.py`
   de hoje — não preciso esperar nenhuma tabela do gestor.
3. **Calendário (sem mudança de plano):** `config/calendario.yaml` + `engine/calendario.py`, exatamente
   como descrito no `PROMPT 1` original (Parte B, PASSO 2) — ainda preciso das datas de férias coletivas
   com você/gestor, mas isso é independente do pivot de lead time.
4. **Bugs do feedback original (A3–A8), sem mudança:** contagem de dias coerente com as datas exibidas,
   sugestão com semana de produção explícita, correção da aritmética de semanas na virada de ano,
   insumo em falta sem data inventada, malha duplicada em três linhas no relatório, "Cor Divergente"
   falso positivo via API. Ver `PROMPT 1` original, PASSOs 3–6 — continuam valendo como estão.
5. Testes: `montar_cronograma` com `lead_times_informados` completo (calcula normal) e incompleto
   (devolve `PendenciaLeadTime` com a lista certa de setores faltantes).

Esforço: 3–4 dias (menor que a Sprint 5 original, porque elimina o trabalho de cadastro manual de 28
setores — agora é só refatorar a engine para receber parâmetro em vez de ler de um arquivo).

### Sprint 6 (entregável principal) — Copiloto Conversacional

Reaproveita quase integralmente o `PROMPT 2` da Parte C do documento anterior (Fases 1–5), com dois
ajustes:

- **Fase 1 (Contexto/Simulação):** `engine/simulacao.py` passa a expor o mecanismo da seção 3 deste
  documento (`montar_cronograma` devolvendo `PendenciaLeadTime`) como a interação padrão, não como um
  "modo avançado de override". É o caminho principal, não uma exceção.
- **Fase 2 (Ferramentas):** adicionar a ferramenta que falta: a própria `montar_cronograma` já descrita,
  mais `sugerir_lead_time(codigo_artigo, setor)` caso o agente precise mostrar a sugestão antes de
  perguntar. As demais ferramentas da lista original (`buscar_pedido`, `consultar_estoque`,
  `consultar_capacidade`, `consultar_calendario`, `listar_ofs`, `explicar_regra`) continuam exatamente
  como estavam — são genéricas e já cobrem o "copiloto que responde outras coisas também".
- **System prompt (Fase 3):** adicionar a instrução central do pivot: "Antes de montar qualquer
  cronograma, você precisa da duração de CADA etapa do fluxo real do artigo. Se a ferramenta devolver
  `PendenciaLeadTime`, pergunte ao analista as etapas faltantes, mostrando a sugestão (se houver) e
  deixando claro que é só sugestão. Nunca assuma um valor que não foi confirmado pelo analista ou pela
  engine (dado de estoque/capacidade/calendário)."
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

Com a sua confirmação da seção 4 (ou "pode seguir com a recomendação"), o próximo passo é eu preparar
o `PROMPT` consolidado (Sprint 5 revisada + Sprint 6) pronto para colar num agente de código, nos
mesmos moldes dos prompts anteriores — só que agora como uma entrega só, já que as duas sprints estão
tecnicamente entrelaçadas pelo mecanismo da seção 3.
