# Papinha PCP Copilot

O **Papinha PCP Copilot** é um assistente tático desenvolvido para o setor de Planejamento e Controle de Produção (PCP).
Seu objetivo é conciliar arquivos em PDF extraídos diretamente dos relatórios legados do ERP, transformando-os em dados acionáveis que garantem entregas pontuais e zero acúmulo de estoque desnecessário.

## Recursos Principais

### 1. Motor Just-in-Time (Backward Scheduling)
Para evitar que a fábrica produza com muita antecedência (o que gera gargalos de armazenamento e ociosidade precoce), a *engine* calcula as datas de trás para frente ("Backward Scheduling").
- **Semana Alvo**: Determinada como `Entrega do Cliente - 2 semanas`.
- O cronograma deduz a duração das fases (Corte, Costura, etc.) a partir da data final, gerando a data de **Início Mais Tarde Possível**.
- **Janela de Autonomia**: O PCP possui flexibilidade de até **3 semanas** antes da Semana Alvo para iniciar a produção de forma autônoma. Iniciar antes dessa janela exige alçada superior.

### 2. Leitura de PDFs Ultra-Precisa (Bucketing)
O ERP gera relatórios de MRP onde as colunas não possuem divisões tabulares e frequentemente os números grandes se aglutinam (ex: `11.460,00052.955,000`).
- O Copilot utiliza um **parser por bucketing espacial de caracteres**.
- Os caracteres são distribuídos em baldes (*buckets*) que mapeiam milimetricamente as coordenadas de cada coluna, garantindo extração 100% fiel ao layout do PDF.
- A reconciliação inclui cálculos automáticos de *Saldo = Estoque + Compra + ... - Consumo*.

### 3. Divergências de Cor e Setup
O sistema avalia os parâmetros de engenharia do *Pedido* vs as alocações da *Engenharia (MRP)*.
- O motor infere "Possível Conjunto/2 peças" quando os consumos são duplicados.
- Divergências de codificação de cor levantam flags amigáveis: `⚠️ Cor Divergente`.

## Arquitetura e Como Rodar

O projeto é servido utilizando Flask.

### Instalação

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Executar Localmente

```bash
python app.py
```
A UI estará disponível em `http://localhost:5000`.

### Rodar a Suíte de Testes
O projeto possui +60 *Golden Tests* para garantir que o parser lide corretamente com formatações obscuras, PDFs de ERP e cálculo seguro de datas reversas.

```bash
python -m pytest tests/
```

## Visão de Futuro (V2 via API)

Na **Fase 2 (V2)**, o Copilot deixará de ser apenas uma interface de upload de PDFs (Jinja/HTML) para se conectar de forma profunda com o banco de dados via API.
- **Microserviço Autônomo**: A lógica consolidada nas pastas `engine/` e `parsers/` será empacotada em uma API RESTful corporativa.
- **Webhook de Eventos ERP**: Quando um novo Pedido for faturado no ERP, um webhook enviará um JSON limpo (substituindo o parser de PDF) diretamente para o Copilot.
- **Retroalimentação de PCP**: As sugestões e vereditos de alocação de semana e divergência (ex: alerta de Cores e Janela de Autonomia excedida) retornarão automaticamente via endpoint para atualizar os status diretamente no painel interno do ERP.

---
*Desenvolvido sob arquitetura escalável (Python, PDFPlumber, Flask, Engine Tática).*
