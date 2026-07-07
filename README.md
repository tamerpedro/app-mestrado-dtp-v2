# MVP Matriz de Riscos TIC

Protótipo local para apoiar a elaboração, padronização, justificativa e revisão humana de matrizes de risco em contratações de TIC.

## Escopo do MVP

- cadastro estruturado da contratação;
- biblioteca curada de riscos;
- cálculo de nível de risco por probabilidade x impacto;
- sugestão automatizada simples por tipo de contratação, palavras-chave e criticidade;
- revisão humana;
- exportação em CSV, Excel, LaTeX ou Word.

## Acesso local

Configure pelo menos um usuário antes de iniciar o app.

Via `.streamlit/secrets.toml`:

```toml
[auth.users]
pedro = "sua-senha"
```

Ou via variáveis de ambiente:

```powershell
$env:APP_USERNAME = "pedro"
$env:APP_PASSWORD = "sua-senha"
```

## Como rodar

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Estrutura

```text
app.py                  Interface Streamlit
data/riscos_base.csv    Biblioteca inicial de riscos
src/                    Regras, modelos e exportadores
tests/                  Testes simples da lógica central
```
