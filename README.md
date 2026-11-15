# 📦 Revenda RJ

Robô que procura **eletrônicos usados abaixo do preço de mercado** no Rio de Janeiro e em Niterói, para você ir ver, comprar e revender com margem. Ele também acompanha o **preço novo em lojas** e **passagens aéreas**. Tudo aparece num painel com cards e fotos, publicado no GitHub Pages.

## Como funciona

A cada 2 horas, das 7h às 23h, o GitHub Actions executa estas etapas:

1. **Coleta** anúncios na OLX (região do Rio) para cada produto de `config/catalogo.yaml`.
2. **Classifica** cada anúncio. O robô identifica o modelo (por exemplo, iPhone 13 é diferente de iPhone 13 Pro) e o armazenamento. Saem da conta acessórios ("Capa iPhone 13"), peças, defeitos, aparelhos bloqueados, trocas e anúncios fora das regiões aceitas. Termos negados não excluem o anúncio: "sem defeito" passa.
3. **Calcula o preço de referência**, que é a mediana dos anúncios parecidos dos últimos 30 dias (pessoa física, mesmo modelo e armazenamento, sem os extremos).
4. **Faz a conta da margem:**
   `venda estimada = mediana × (1 − 7% de negociação)`
   `lucro = venda estimada − preço pedido − R$ 40 de custos`
   - **🔔 Oportunidade:** margem de 20% ou mais, lucro de R$ 100 ou mais e preço até R$ 3.000.
   - **👀 Em observação:** margem entre 10% e 20%, ou produto ainda com poucos anúncios para comparar.
5. **Triagem com IA (Claude Haiku 5.5).** O robô abre o anúncio, lê a descrição e as fotos, e a IA confere se é mesmo o produto. Ela também avalia o estado, aponta sinais de golpe ou risco, sugere perguntas para o vendedor e um valor de oferta. Anúncios com recomendação "evitar" saem da lista.
6. **Checagem de venda.** O robô reabre as oportunidades para saber quando somem. Isso mostra quantas horas um achado dura.
7. **Pesquisa na web (Claude Sonnet 5.5 + busca da Anthropic).** Busca o **preço novo** de cada produto em lojas (Amazon, Magalu, Kabum…) a cada 7 dias e as **passagens** das suas rotas cerca de 1 vez por dia.
8. **Caçador de promoções (a cada ~6 h).** Para cada produto, o robô calcula o preço máximo de compra que ainda dá 20% de lucro revendendo no Rio. O Claude procura ofertas de produtos **novos** abaixo desse teto em **lojas confiáveis** (Amazon, Mercado Livre, Magalu, Kabum, Casas Bahia, Fast Shop…) e no Pelando/Promobit. Links de sites fora da lista são descartados no código.
9. Gera `docs/index.html` e faz o commit do banco (`data/revenda.db`).

## Painel

| Aba | O que mostra |
|---|---|
| 🔔 Oportunidades | Cards com foto, preço, lucro estimado, faixa de preço do mercado, bairro/zona, análise da IA, perguntas ao vendedor e checklist do que conferir na hora. Também mostra os achados que já sumiram e em quanto tempo. |
| 👀 Em observação | Anúncios quase lá: bons para negociar ou acompanhar. |
| 🛒 Promoções em lojas | Produtos novos em promoção em sites confiáveis que dão lucro na revenda, com loja, cupom, "vendido por", lucro estimado e a tabela "compre até R$ X" de cada produto. |
| 📦 Produtos | Um card por produto com a mediana de usado, preços por armazenamento, as melhores ofertas de novo com link e um aviso quando o usado está perto do preço do novo. |
| ✈️ Passagens | Melhores voos de cada rota, histórico de preço e alerta abaixo do preço-alvo. |
| 💰 Minhas operações | Botões 🛒 Comprei e 💰 Vendi, lucro realizado e ranking por categoria. Fica salvo no navegador, com opção de exportar e importar. |
| ⚙️ Execuções | Histórico das execuções, custo e erros. |

## Configuração (uma vez só)

1. **Secret da API:** em Settings → Secrets and variables → Actions → *New repository secret*, crie `ANTHROPIC_API_KEY` com a sua chave.
2. **GitHub Pages:** em Settings → Pages, escolha *Deploy from a branch*, branch `main`, pasta `/docs`.
3. **Primeira execução:** em Actions → *Monitor de revenda RJ* → *Run workflow*.

## Personalizar

- `config/regras.yaml`: orçamento, margem, custos, regiões, termos excluídos, limites da IA e teto de gasto mensal.
- `config/catalogo.yaml`: produtos monitorados. Copie um bloco para adicionar um produto.
- `config/regras.yaml` → `promocoes`: frequência e lista de **lojas confiáveis** aceitas.
- `config/passagens.yaml`: rotas aéreas. **As que vêm no arquivo são exemplos; troque pelas suas.**

## Custos estimados

- **Triagem (Haiku 5.5):** só roda nos anúncios que passaram na conta de margem. Fica em centavos por dia.
- **Pesquisa web (Sonnet 5.5):** cerca de US$ 0,10 a 0,20 por pesquisa (buscas a US$ 0,01 cada, mais os tokens das páginas lidas). Na configuração padrão, com 23 produtos a cada 7 dias e 2 rotas por dia, dá uns US$ 15 a 25 por mês sem limite.
- **Caçador de promoções (Sonnet 5.5):** 3 a 4 procuras por dia, cerca de US$ 0,15 a 0,30 cada. Entra no mesmo teto mensal.
- **Teto mensal** (`teto_mensal_usd`, padrão US$ 25): ao ser atingido, as pesquisas param até o mês virar.
- **GitHub Actions:** grátis em repositório público.

## Limitações honestas

- **A OLX pode bloquear robôs.** Isso acontece com mais frequência a partir de servidores, como os do GitHub Actions. Quando ocorre, o painel mostra um aviso e o erro aparece em ⚙️ Execuções. Se virar regra, a alternativa é rodar o robô no seu computador.
- **O preço de referência é o preço *pedido*.** Na prática se vende um pouco abaixo dele, e por isso existe o desconto de negociação (7%).
- **Preços da pesquisa web são aproximados,** sobretudo os de passagens, que mudam a toda hora. Sempre confirme no link.
- **Promoções acabam rápido** e podem ter estoque limitado. Confira o preço final e quem vende ("vendido e entregue por") antes de comprar. Para produto novo lacrado, a conta usa como preço de revenda a mediana dos **usados**, o que é conservador.
- **Segurança na compra:** encontre o vendedor em local público, confira o IMEI em celularseguro.mj.gov.br e nunca pague adiantado.

## Rodar localmente

```bash
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # coloque sua ANTHROPIC_API_KEY
python -m pytest
python -m src.main            # execução completa
python -m src.main --sem-ia   # sem custo de IA
python -m src.main --so-painel
```
