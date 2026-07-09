# NOTES.md — Decisões e ambiguidades registradas durante a implementação
# (conforme instrução 3 do ROADMAP — dúvidas aqui, nunca inventar regra)

## Decisões de Implementação

### Fase 1

- **Mapa de OF ausente**: O PDF "Mapa SEM 2637" não foi fornecido nos fixtures.
  Os valores de calibração (lead times, cronograma de 65 dias) já estão embutidos
  nos golden tests (seção 8 do ROADMAP) e nos defaults do regras.yaml.
  O campo de upload "Mapa de OF" ficará presente na UI como opcional.

### Simplificações documentadas (conforme ROADMAP seção 3.5)

- **Feriados/fins de semana**: não são tratados no MVP — cronograma em dias corridos.
  Registrar no README.

- **Pijama — trilhas paralelas**: o MVP modela apenas o caminho crítico (trilha superior:
  PCP → Encaixe → Corte → Entretela → Qual.Entretela → Costura → Qual.Costura →
  Caseado/Botão → Revisão → Embalagem). O pijama real tem 3 trilhas paralelas.

## Perguntas Abertas (seção 11 do ROADMAP — não bloqueiam o desenvolvimento)

1. Capacidade por família (magazine/coleção) — existe relatório filtrado?
   **Default atual**: modo agregado vs. limite 80k.

2. Malha principal ausente do MRP dos vestidos/regatas — é característica do relatório?
   **Default**: alerta + pcp_dias=21.

3. Mapeamento insumo→fase além do RFID (RIBANA, MALHA, ETIQ, TAG, PINO, CAIXA, etc.)
   **Default**: inferências parametrizadas no regras.yaml — validar com gestor.

4. Lead times reais por fase
   **Default**: derivados do Mapa SEM 2637 (65 dias para VESTIDO/REGATA).

5. Tabela de-para de códigos de cor
   **Default**: matching por artigo+quantidade com aviso de divergência de cor.
