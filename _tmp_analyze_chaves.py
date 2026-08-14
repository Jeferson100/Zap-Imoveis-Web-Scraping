import re
import httpx

URLS = {
    "aluguel": "https://www.chavesnamao.com.br/imovel/sala-comercial-para-alugar-1-sala-com-garagem-sc-joinville-nova-brasilia-20m2-RS750/id-42554865/",
    "venda": "https://www.chavesnamao.com.br/imovel/apartamento-a-venda-2-quartos-com-garagem-sc-joinville-america-131m2-RS732300/id-30013466/",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    )
}


def analyze(tipo: str, url: str) -> None:
    r = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
    html = r.text
    print(f"\n===== {tipo.upper()} status={r.status_code} len={len(html)} =====")
    print("style_clamp__m7txb count:", html.count("style_clamp__m7txb"))

    clamp_classes = sorted(set(re.findall(r'class="([^"]*clamp[^"]*)"', html)))
    print("clamp classes:", clamp_classes[:15])

    for m in re.finditer(r'"price"\s*:\s*[^,}]+', html):
        print("price json:", m.group(0)[:100])

    for m in re.finditer(r'"offers"\s*:\s*\{[^}]+\}', html):
        print("offers json:", m.group(0)[:200])

    for b in re.findall(r".{0,80}R\$\s*[\d\.]+.{0,80}", html):
        print("R$ context:", re.sub(r"\s+", " ", b)[:160])

    # extract __NEXT_DATA__ or similar
    for pattern in [r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r'window\.__NUXT__\s*=\s*(.*?);</script>']:
        m = re.search(pattern, html, re.DOTALL)
        if m:
            print(f"found embedded data via {pattern[:30]}..., len={len(m.group(1))}")

    out = f"_tmp_chaves_{tipo}.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"saved {out}")


if __name__ == "__main__":
    for tipo, url in URLS.items():
        analyze(tipo, url)
