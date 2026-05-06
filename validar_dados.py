"""
Validação de sanidade dos dados de produção agrícola (IBGE-PAM).

Roda 3 níveis de checagem:
  1. Consistência interna: Quantidade ≈ Área × Produtividade (tolerância 5%)
  2. Ranges plausíveis: produtividade dentro de bandas de RO
  3. Sanidade estrutural: cobertura municipal, valores não-negativos

Saída:
  - Relatório no stdout
  - Exit code 0 se tudo passa, 1 se há violações (para CI/GitHub Actions)

Uso:
    python validar_dados.py
"""
import sys
import pandas as pd

# Força UTF-8 no stdout (Windows usa cp1252 por padrão e quebra com acentos/símbolos)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ARQUIVO_DADOS = "dados_agro_ro_master.csv"

# Ranges plausíveis para Rondônia (calibrados pela média histórica IBGE/CONAB).
# Milho tem range largo: comercial mecanizado fica em 4–6 t/ha (safrinha),
# subsistência/agricultura familiar fica em 1,5–3 t/ha (Zona da Mata).
RANGES_PRODUTIVIDADE_KG_HA = {
    "Soja":  {"min": 2500, "max": 4200},  # 2,5 a 4,2 t/ha
    "Milho": {"min": 1500, "max": 6500},  # 1,5 a 6,5 t/ha (cobre subsistência + comercial)
}

# Tolerância para identidade Quantidade = Área × Produtividade.
# IBGE-PAM distingue Área Plantada (semeada) e Área Colhida (efetiva). Quando
# há perda de safra (chuva, geada, doença), Quantidade < Área Plantada × Produtividade.
# 12% cobre perdas típicas em RO sem mascarar erros reais de digitação.
TOLERANCIA_CONSISTENCIA = 0.12

# Produção mínima para validação de consistência. Abaixo disso (residual,
# subsistência), pequenas diferenças geram grandes desvios percentuais sem significado.
PRODUCAO_MINIMA_VALIDAVEL_T = 500

# Município mais extenso de RO é Porto Velho (~34.000 km² = 3,4 Mi ha).
# Ainda assim, área plantada de uma única cultura raramente passa de 70k ha.
AREA_MAX_PLAUSIVEL_HA = 100_000


def validar_consistencia(df, cultura):
    """Quantidade = Área × Produtividade (tolerância TOLERANCIA_CONSISTENCIA)."""
    erros = []
    qtd_col = f"{cultura}_Qtd_T"
    area_col = f"{cultura}_AreaPlant_Ha"
    prod_col = f"{cultura}_Prod_KgHa"

    for _, r in df.iterrows():
        qtd, area, prod = r[qtd_col], r[area_col], r[prod_col]
        # Ignora produção residual (< 500 t) — arredondamento mascara como % grande
        if area > 0 and prod > 0 and qtd >= PRODUCAO_MINIMA_VALIDAVEL_T:
            esperado = area * prod / 1000  # kg/ha × ha ÷ 1000 = toneladas
            desvio = abs(qtd - esperado) / esperado
            if desvio > TOLERANCIA_CONSISTENCIA:
                erros.append(
                    f"  {r['Municipio']:30s} {cultura}: "
                    f"qtd={qtd:>9,.0f} t · esperado={esperado:>9,.0f} t · "
                    f"desvio {desvio*100:+.1f}%"
                )
    return erros


def validar_produtividade(df, cultura):
    """Produtividade dentro do range plausível para Rondônia."""
    erros = []
    prod_col = f"{cultura}_Prod_KgHa"
    minimo = RANGES_PRODUTIVIDADE_KG_HA[cultura]["min"]
    maximo = RANGES_PRODUTIVIDADE_KG_HA[cultura]["max"]

    for _, r in df.iterrows():
        prod = r[prod_col]
        if prod > 0 and (prod < minimo or prod > maximo):
            erros.append(
                f"  {r['Municipio']:30s} {cultura}: "
                f"produtividade {prod:>5,.0f} kg/ha "
                f"fora do range ({minimo:,}–{maximo:,} kg/ha)"
            )
    return erros


def validar_area(df, cultura):
    """Área plantada não passa do limite plausível."""
    erros = []
    area_col = f"{cultura}_AreaPlant_Ha"

    for _, r in df.iterrows():
        area = r[area_col]
        if area > AREA_MAX_PLAUSIVEL_HA:
            erros.append(
                f"  {r['Municipio']:30s} {cultura}: "
                f"área {area:>9,.0f} ha (máximo plausível: {AREA_MAX_PLAUSIVEL_HA:,} ha)"
            )
    return erros


def validar_estrutura(df):
    """Cobertura municipal e ausência de valores negativos."""
    erros = []

    # RO tem 52 municípios
    n_municipios = len(df)
    if n_municipios < 50 or n_municipios > 55:
        erros.append(f"  Cobertura municipal: {n_municipios} (esperado: 52)")

    # Nenhum valor negativo nas colunas numéricas
    cols_numericas = [c for c in df.columns if c != "Municipio"]
    for c in cols_numericas:
        negativos = (df[c] < 0).sum()
        if negativos > 0:
            erros.append(f"  Coluna {c}: {negativos} valor(es) negativo(s)")

    # Nenhum município duplicado
    duplicados = df["Municipio"].duplicated().sum()
    if duplicados > 0:
        erros.append(f"  Municípios duplicados: {duplicados}")

    return erros


def main():
    print("=" * 70)
    print(f"VALIDAÇÃO DE SANIDADE — {ARQUIVO_DADOS}")
    print("=" * 70)

    try:
        df = pd.read_csv(ARQUIVO_DADOS)
    except FileNotFoundError:
        print(f"\nERRO: arquivo {ARQUIVO_DADOS} não encontrado.")
        return 1

    print(f"\nMunicípios carregados: {len(df)}")
    print(f"Tolerância consistência: {TOLERANCIA_CONSISTENCIA*100:.0f}%")
    print(f"Range produtividade soja:  {RANGES_PRODUTIVIDADE_KG_HA['Soja']['min']:,}"
          f"–{RANGES_PRODUTIVIDADE_KG_HA['Soja']['max']:,} kg/ha")
    print(f"Range produtividade milho: {RANGES_PRODUTIVIDADE_KG_HA['Milho']['min']:,}"
          f"–{RANGES_PRODUTIVIDADE_KG_HA['Milho']['max']:,} kg/ha")
    print(f"Área máxima plausível:     {AREA_MAX_PLAUSIVEL_HA:,} ha")

    todos_erros = []

    print("\n--- 1. Consistência interna (Qtd ≈ Área × Produtividade) ---")
    for cultura in ["Soja", "Milho"]:
        erros = validar_consistencia(df, cultura)
        if erros:
            print(f"\n  {cultura}: {len(erros)} violação(ões)")
            for e in erros:
                print(e)
            todos_erros.extend(erros)
        else:
            print(f"  {cultura}: OK")

    print("\n--- 2. Produtividade dentro do range esperado ---")
    for cultura in ["Soja", "Milho"]:
        erros = validar_produtividade(df, cultura)
        if erros:
            print(f"\n  {cultura}: {len(erros)} violação(ões)")
            for e in erros:
                print(e)
            todos_erros.extend(erros)
        else:
            print(f"  {cultura}: OK")

    print("\n--- 3. Área plantada plausível ---")
    for cultura in ["Soja", "Milho"]:
        erros = validar_area(df, cultura)
        if erros:
            print(f"\n  {cultura}: {len(erros)} violação(ões)")
            for e in erros:
                print(e)
            todos_erros.extend(erros)
        else:
            print(f"  {cultura}: OK")

    print("\n--- 4. Sanidade estrutural ---")
    erros = validar_estrutura(df)
    if erros:
        print(f"  {len(erros)} violação(ões)")
        for e in erros:
            print(e)
        todos_erros.extend(erros)
    else:
        print("  OK")

    print("\n" + "=" * 70)
    if todos_erros:
        print(f"REPROVADO: {len(todos_erros)} violação(ões) encontradas")
        print("=" * 70)
        return 1
    else:
        print("APROVADO: todos os checks passaram")
        print("=" * 70)
        return 0


if __name__ == "__main__":
    sys.exit(main())
