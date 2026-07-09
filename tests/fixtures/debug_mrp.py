import sys
sys.path.insert(0, '.')
from pathlib import Path
from parsers.mrp_parser import parse_mrp, _extrair_linhas_com_coords, _e_cabecalho_colunas, _extrair_x_colunas_cabecalho

# Mostrar mapa de colunas
linhas = _extrair_linhas_com_coords(Path('tests/fixtures/mrp.pdf').read_bytes())
for l in linhas:
    if _e_cabecalho_colunas(l['texto']):
        mapa = _extrair_x_colunas_cabecalho(l['words'])
        print("Mapa de colunas:")
        for nome, (xmin, xmax) in sorted(mapa.items(), key=lambda kv: kv[1][0]):
            print(f"  {nome:12s}: x_min={xmin:7.1f}  x_max={xmax:7.1f}")
        break

# Golden values
blocos = parse_mrp(Path('tests/fixtures/mrp.pdf').read_bytes())
print(f'\nTotal blocos: {len(blocos)}, OK: {sum(1 for b in blocos if b.parse_ok)}')
for b in blocos:
    if b.cod_insumo == '03044079' and '021180' in b.cod_cor:
        print(f"\n03044079/021180: consumo={b.consumo:.3f} estoque={b.estoque:.3f} tinturaria={b.tinturaria:.3f} saldo={b.saldo:.3f} parse_ok={b.parse_ok}")
        print(f"  esperado: consumo=34.614 estoque=18.650 tinturaria=107.100 saldo=91.136")
        if b.avisos_reconciliacao:
            print(f"  avisos: {b.avisos_reconciliacao}")
        break
