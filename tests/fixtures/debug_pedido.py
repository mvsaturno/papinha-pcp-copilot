import sys, re
sys.path.insert(0, '.')

_RE_LINHA_ITEM = re.compile(
    r"^(\d{1,3})\s+"          # ordem
    r"(\d{7})\s*/\s*"         # artigo (7 dígitos) + '/'
    r"(.+?)\s{2,}"            # descrição (dois ou mais espaços separam da cor)
    r"(\d{5})\s*[-\u2013]\s*"  # código cor (5 dígitos)
    r"(.+?)\s+"               # nome da cor
    r"((?:[\d.,]+\s*)+)$",   # números (tamanhos + total)
    re.IGNORECASE
)

linha = '1 4104040 / REGATA ANDREA 00088 - VERDE MUSGO 319 641 728 634 379 2.701'
m = _RE_LINHA_ITEM.match(linha)
print(f"Match: {bool(m)}")
if m:
    print(f"  ordem={m.group(1)}, artigo={m.group(2)}, desc={m.group(3)}, cor={m.group(4)}, nome={m.group(5)}, nums={m.group(6)}")

# Testar componentes
print("Teste componentes:")
print("  ordem:", bool(re.match(r"^(\d{1,3})\s+", linha)))
print("  artigo:", bool(re.match(r"^(\d{1,3})\s+(\d{7})\s*/\s*", linha)))
print("  ate desc:", bool(re.match(r"^(\d{1,3})\s+(\d{7})\s*/\s*(.+?)\s{2,}", linha)))

# A linha tem 2 espaços antes de "00088"?
idx = linha.index('00088')
print(f"  chars antes de 00088: {repr(linha[idx-5:idx])}")
