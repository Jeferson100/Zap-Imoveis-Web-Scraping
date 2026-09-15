let todosImoveis = [];
let mapa = null;
let markers = [];
let modoAtual = 'venda';
let cidadesComAluguel = [];
let cidadesComPredicao = ['joinville', 'balneario_camboriu'];

const CIDADES_NOMES = {
    'joinville': 'Joinville',
    'florianopolis': 'Florianópolis',
    'blumenau': 'Blumenau',
    'balneario_camboriu': 'Balneário Camboriú',
    'balneario_picaras': 'Balneário Picarras',
    'itajai': 'Itajaí',
    'itapema': 'Itapema',
    'itapoa': 'Itapoá',
    'jaragua': 'Jaraguá do Sul',
    'curitiba': 'Curitiba',
    'sao_paulo': 'São Paulo',
};

// ── Utilitários ──
function formatarMoeda(valor) {
    return 'R$ ' + Math.round(valor).toLocaleString('pt-BR');
}

function media(arr) {
    const validos = arr.filter(v => v !== null && v !== undefined && v !== '' && !isNaN(v) && isFinite(v));
    return validos.length ? validos.reduce((a, b) => a + b, 0) / validos.length : 0;
}

function mediana(arr) {
    const validos = arr.filter(v => v !== null && v !== undefined && v !== '' && !isNaN(v) && isFinite(v));
    if (!validos.length) return 0;
    const s = [...validos].sort((a, b) => a - b);
    const mid = Math.floor(s.length / 2);
    return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

function parseNum(val) {
    if (val === '' || val === null || val === undefined) return NaN;
    const n = parseFloat(val);
    return isNaN(n) ? NaN : n;
}

function removerPercentilSuperior(dados) {
    const coluna = 'preco_por_m2';
    const valores = dados.map(d => parseNum(d[coluna])).filter(v => !isNaN(v) && v > 0);
    if (valores.length < 10) return dados;
    const ordenados = [...valores].sort((a, b) => a - b);
    const limite = ordenados[Math.floor(ordenados.length * 0.996)];
    const filtrados = dados.filter(d => {
        const v = parseNum(d[coluna]);
        return isNaN(v) || v < limite;
    });
    const removidos = dados.length - filtrados.length;
    if (removidos > 0) {
        console.log('Percentil 99.6% removidos: ' + removidos + ' de ' + dados.length + ' (limite: R$ ' + Math.round(limite) + ')');
    }
    return filtrados;
}

function removerOutliersIQR(dados) {
    const coluna = 'preco_por_m2';
    const valores = dados.map(d => parseNum(d[coluna])).filter(v => !isNaN(v) && v > 0);
    if (valores.length < 10) return dados;
    const ordenados = [...valores].sort((a, b) => a - b);
    const q1 = ordenados[Math.floor(ordenados.length * 0.25)];
    const q3 = ordenados[Math.floor(ordenados.length * 0.75)];
    const iqr = q3 - q1;
    const lo = q1 - 1.5 * iqr;
    const hi = q3 + 1.5 * iqr;
    const filtrados = dados.filter(d => {
        const v = parseNum(d[coluna]);
        return isNaN(v) || v < lo || v > hi ? false : true;
    });
    const removidos = dados.length - filtrados.length;
    if (removidos > 0) {
        console.log('Outliers removidos: ' + removidos + ' de ' + dados.length +
            ' (IQR: ' + Math.round(lo) + ' - ' + Math.round(hi) + ')');
    }
    return filtrados;
}

// ── Inicialização ──
document.addEventListener('DOMContentLoaded', () => {
    const cidadeInicial = 'joinville';
    document.getElementById('cidade-select').value = cidadeInicial;

    fetch('data/config_aluguel.json')
        .then(r => r.json())
        .then(config => {
            cidadesComAluguel = config.cidades || [];
            console.log('Cidades com aluguel:', cidadesComAluguel);
            configurarModoAluguel(cidadeInicial);
            atualizarCabecalhoTabela();
        })
        .catch(() => {
            console.log('Sem dados de aluguel disponíveis');
            cidadesComAluguel = [];
            atualizarCabecalhoTabela();
        });

    carregarDados(cidadeInicial);

    document.getElementById('cidade-select').addEventListener('change', async (e) => {
        configurarModoAluguel(e.target.value);
        atualizarCabecalhoTabela();

        if (modoAtual === 'predicao') {
            modeloJson = null;
            configPredicao = null;
            if (typeof carregarPredicao === 'function') {
                await carregarPredicao(e.target.value);
            }
        } else {
            carregarDados(e.target.value);
        }
    });

    document.getElementById('modo-select').addEventListener('change', async (e) => {
        modoAtual = e.target.value;
        const cidade = document.getElementById('cidade-select').value;
        atualizarTitulo(cidade);
        atualizarCabecalhoTabela();

        const secaoPred = document.getElementById('secao-predicao');
        const secoesNormais = document.querySelectorAll('.main-content > section:not(#secao-predicao)');

        if (modoAtual === 'predicao') {
            secoesNormais.forEach(s => s.style.display = 'none');
            secaoPred.style.display = '';
            if (typeof carregarPredicao === 'function' && (!modeloJson || !configPredicao)) {
                await carregarPredicao(cidade);
            }
        } else {
            secaoPred.style.display = 'none';
            secoesNormais.forEach(s => s.style.display = '');
            carregarDados(cidade);
        }
    });

    document.getElementById('btn-limpar').addEventListener('click', limparFiltros);

    document.getElementById('remover-outliers').addEventListener('change', aplicarFiltros);

    const debounceTimer = {};
    document.querySelectorAll('.sidebar input[type=number]').forEach(input => {
        input.addEventListener('input', () => {
            clearTimeout(debounceTimer[input.id]);
            debounceTimer[input.id] = setTimeout(aplicarFiltros, 300);
        });
    });

    document.getElementById('busca-bairro').addEventListener('input', (e) => {
        const termo = e.target.value.toLowerCase();
        document.querySelectorAll('#filtro-bairro label').forEach(label => {
            const texto = label.textContent.toLowerCase();
            label.style.display = texto.includes(termo) ? '' : 'none';
        });
    });

    document.getElementById('busca-rua').addEventListener('input', (e) => {
        const termo = e.target.value.toLowerCase();
        document.querySelectorAll('#filtro-rua label').forEach(label => {
            const texto = label.textContent.toLowerCase();
            label.style.display = texto.includes(termo) ? '' : 'none';
        });
    });
});

function configurarModoAluguel(cidade) {
    const modoSelect = document.getElementById('modo-select');
    if (cidadesComAluguel.includes(cidade) || cidadesComPredicao.includes(cidade)) {
        modoSelect.classList.remove('hidden');
        const opts = modoSelect.options;
        for (let i = opts.length - 1; i >= 0; i--) {
            if (opts[i].value === 'aluguel') opts[i].disabled = !cidadesComAluguel.includes(cidade);
            if (opts[i].value === 'predicao') opts[i].disabled = !cidadesComPredicao.includes(cidade);
        }
    } else {
        modoSelect.classList.add('hidden');
        modoAtual = 'venda';
        modoSelect.value = 'venda';
    }
}

function atualizarTitulo(cidade) {
    const nome = CIDADES_NOMES[cidade] || cidade;
    let sufixo = 'Venda';
    if (modoAtual === 'aluguel') sufixo = 'Aluguéis';
    else if (modoAtual === 'predicao') sufixo = 'Predição';
    document.getElementById('titulo-app').textContent = '🏠 Análise de Imóveis ' + nome + ' - ' + sufixo;
    atualizarLabelsSidebar();
}

function atualizarLabelsSidebar() {
    const labelPreco = modoAtual === 'aluguel' ? 'Aluguel' : 'Preço';
    const labelValor = modoAtual === 'aluguel' ? 'Valor do Aluguel' : 'Valor do Imóvel';

    const filterGroups = document.querySelectorAll('.filter-group');
    filterGroups.forEach(group => {
        const label = group.querySelector('label');
        if (!label) return;
        const text = label.textContent.trim();
        if (text.includes('Preço/m²')) {
            label.textContent = labelPreco + '/m² (R$)';
        } else if (text.includes('Valor do Imóvel') || text.includes('Valor do Aluguel')) {
            label.textContent = labelValor + ' (R$)';
        }
    });
}

// ── Carregar Dados ──
function carregarDados(cidade) {
    atualizarTitulo(cidade);

    const fonte = modoAtual === 'aluguel' ? 'aluguel' : 'venda';
    const chaveDados = modoAtual === 'aluguel' ? 'DADOS_ALUGUEL' : 'DADOS_IMOVEIS';
    const prefixoJs = modoAtual === 'aluguel' ? 'dados_aluguel_' : 'dados_';

    if (window[chaveDados] && window[chaveDados][cidade]) {
        todosImoveis = window[chaveDados][cidade];
        console.log('Dados carregados: ' + todosImoveis.length + ' imóveis (' + cidade + ' - ' + fonte + ')');
        document.getElementById('data-atualizacao').textContent =
            (CIDADES_NOMES[cidade] || cidade) + ' — ' + todosImoveis.length.toLocaleString('pt-BR') + ' imóveis (' + fonte + ')';
        popularFiltros();
        aplicarFiltros();
        return;
    }

    const script = document.createElement('script');
    script.src = 'data/' + prefixoJs + cidade + '.js';
    script.onload = function() {
        if (window[chaveDados] && window[chaveDados][cidade]) {
            todosImoveis = window[chaveDados][cidade];
            console.log('Dados carregados via script: ' + todosImoveis.length + ' imóveis (' + cidade + ' - ' + fonte + ')');
        } else {
            todosImoveis = [];
            console.error('Dados não encontrados após carregar script: ' + cidade + ' (' + fonte + ')');
        }
        document.getElementById('data-atualizacao').textContent =
            (CIDADES_NOMES[cidade] || cidade) + ' — ' + todosImoveis.length.toLocaleString('pt-BR') + ' imóveis (' + fonte + ')';
        popularFiltros();
        aplicarFiltros();
    };
    script.onerror = function() {
        console.error('Erro ao carregar dados: ' + cidade + ' (' + fonte + ')');
        todosImoveis = [];
        document.getElementById('data-atualizacao').textContent = 'Erro ao carregar dados de ' + (CIDADES_NOMES[cidade] || cidade);
        renderizarResumo([]);
    };
    document.head.appendChild(script);
}

// ── Filtros (Checkboxes) ──
function popularFiltros() {
    const bairros = [...new Set(todosImoveis.map(i => i.bairro).filter(b => b && b !== '' && b !== 's/b'))].sort();
    const tipos = [...new Set(todosImoveis.map(i => i.tipo_imovel).filter(Boolean))].sort();
    const fontes = [...new Set(todosImoveis.map(i => i.fonte).filter(Boolean))].sort();
    const ruas = [...new Set(todosImoveis.map(i => i.rua).filter(r => r && r !== '' && r !== 's/r' && r !== 'nan'))].sort();

    popularCheckbox('filtro-bairro', bairros);
    popularCheckbox('filtro-tipo', tipos);
    popularCheckbox('filtro-fonte', fontes);
    popularCheckbox('filtro-rua', ruas);

    document.getElementById('busca-bairro').value = '';
    document.getElementById('busca-rua').value = '';
}

function popularCheckbox(containerId, opcoes) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';
    opcoes.forEach(op => {
        const label = document.createElement('label');
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.value = op;
        cb.addEventListener('change', aplicarFiltros);
        label.appendChild(cb);
        label.appendChild(document.createTextNode(' ' + op));
        container.appendChild(label);
    });
}

function pegarValoresCheckbox(containerId) {
    return [...document.querySelectorAll(`#${containerId} input:checked`)].map(cb => cb.value);
}

function pegarNumerico(id) {
    const val = document.getElementById(id).value;
    if (val === '' || val === null) return undefined;
    const n = parseFloat(val);
    return isNaN(n) ? undefined : n;
}

// ── Aplicar Filtros ──
function aplicarFiltros() {
    let filtrados = [...todosImoveis];

    const bairros = pegarValoresCheckbox('filtro-bairro');
    if (bairros.length) {
        filtrados = filtrados.filter(i => bairros.includes(i.bairro));
    }

    const tipos = pegarValoresCheckbox('filtro-tipo');
    if (tipos.length) {
        filtrados = filtrados.filter(i => tipos.includes(i.tipo_imovel));
    }

    const fontes = pegarValoresCheckbox('filtro-fonte');
    if (fontes.length) {
        filtrados = filtrados.filter(i => fontes.includes(i.fonte));
    }

    const ruas = pegarValoresCheckbox('filtro-rua');
    if (ruas.length) {
        filtrados = filtrados.filter(i => ruas.includes(i.rua));
    }

    const ppm2Min = pegarNumerico('preco-min');
    const ppm2Max = pegarNumerico('preco-max');
    if (ppm2Min !== undefined) filtrados = filtrados.filter(i => parseNum(i.preco_por_m2) >= ppm2Min);
    if (ppm2Max !== undefined) filtrados = filtrados.filter(i => parseNum(i.preco_por_m2) <= ppm2Max);

    const metMin = pegarNumerico('metragem-min');
    const metMax = pegarNumerico('metragem-max');
    if (metMin !== undefined) filtrados = filtrados.filter(i => parseNum(i.metragem) >= metMin);
    if (metMax !== undefined) filtrados = filtrados.filter(i => parseNum(i.metragem) <= metMax);

    const qMin = pegarNumerico('quartos-min');
    const qMax = pegarNumerico('quartos-max');
    if (qMin !== undefined) filtrados = filtrados.filter(i => parseNum(i.quartos) >= qMin);
    if (qMax !== undefined) filtrados = filtrados.filter(i => parseNum(i.quartos) <= qMax);

    const vagMin = pegarNumerico('vagas-min');
    const vagMax = pegarNumerico('vagas-max');
    if (vagMin !== undefined) filtrados = filtrados.filter(i => parseNum(i.vagas) >= vagMin);
    if (vagMax !== undefined) filtrados = filtrados.filter(i => parseNum(i.vagas) <= vagMax);

    const vMin = pegarNumerico('valor-min');
    const vMax = pegarNumerico('valor-max');
    if (vMin !== undefined) filtrados = filtrados.filter(i => parseNum(i.valor_imovel) >= vMin);
    if (vMax !== undefined) filtrados = filtrados.filter(i => parseNum(i.valor_imovel) <= vMax);

    const dMin = pegarNumerico('desvio-min');
    const dMax = pegarNumerico('desvio-max');
    if (dMin !== undefined) filtrados = filtrados.filter(i => parseNum(i.desvio_mediana) >= dMin);
    if (dMax !== undefined) filtrados = filtrados.filter(i => parseNum(i.desvio_mediana) <= dMax);

    const countEl = document.getElementById('count-filtrados');
    let antes = filtrados.length;
    filtrados = removerPercentilSuperior(filtrados);
    const outliersCheckbox = document.getElementById('remover-outliers');
    if (outliersCheckbox && outliersCheckbox.checked) {
        antes = filtrados.length;
        filtrados = removerOutliersIQR(filtrados);
    }
    if (filtrados.length < antes) {
        countEl.style.display = 'block';
        countEl.textContent = `${filtrados.length} de ${antes} imóveis`;
    } else if (filtrados.length < todosImoveis.length) {
        countEl.style.display = 'block';
        countEl.textContent = `${filtrados.length} de ${todosImoveis.length} imóveis`;
    } else {
        countEl.style.display = 'none';
    }

    renderizarTudo(filtrados);
}

function limparFiltros() {
    document.querySelectorAll('.checkbox-list input:checked').forEach(cb => {
        cb.checked = false;
    });
    document.querySelectorAll('.sidebar input[type=number]').forEach(i => i.value = '');
    document.getElementById('busca-bairro').value = '';
    document.getElementById('busca-rua').value = '';
    document.querySelectorAll('#filtro-bairro label').forEach(l => l.style.display = '');
    document.querySelectorAll('#filtro-rua label').forEach(l => l.style.display = '');
    document.getElementById('count-filtrados').style.display = 'none';
    document.getElementById('remover-outliers').checked = false;
    aplicarFiltros();
}

// ── Renderização Principal ──
function renderizarTudo(dados) {
    try { renderizarResumo(dados); } catch(e) { console.error('Resumo:', e); }
    try { renderizarGraficos(dados); } catch(e) { console.error('Graficos:', e); }
    try { renderizarMapa(dados); } catch(e) { console.error('Mapa:', e); }
    try { renderizarTabela(dados); } catch(e) { console.error('Tabela:', e); }
}

// ── Resumo ──
function renderizarResumo(dados) {
    const n = dados.length;
    const ppm2 = dados.map(d => parseNum(d.preco_por_m2)).filter(v => !isNaN(v) && v > 0);
    const areas = dados.map(d => parseNum(d.metragem)).filter(v => !isNaN(v) && v > 0);
    const valores = dados.map(d => parseNum(d.valor_imovel)).filter(v => !isNaN(v) && v > 0);

    const unidade = modoAtual === 'aluguel' ? '/mês' : '';
    const labelPreco = modoAtual === 'aluguel' ? 'Aluguel' : 'Preço';
    const labelValor = modoAtual === 'aluguel' ? 'Valor do Aluguel' : 'Valor do Imóvel';

    document.querySelector('#metric-total').closest('.card').querySelector('h4').textContent = 'Total de Imóveis';
    document.querySelector('#metric-ppm2-media').closest('.card-group').querySelector('h4').textContent = '📍 ' + labelPreco + ' por m²';
    document.querySelector('#metric-valor-media').closest('.card-group').querySelector('h4').textContent = '💰 ' + labelValor;

    document.getElementById('metric-total').textContent = n.toLocaleString('pt-BR');
    document.getElementById('metric-ppm2-media').textContent = formatarMoeda(media(ppm2)) + unidade;
    document.getElementById('metric-ppm2-mediana').textContent = formatarMoeda(mediana(ppm2)) + unidade;
    document.getElementById('metric-valor-media').textContent = formatarMoeda(media(valores)) + unidade;
    document.getElementById('metric-valor-mediana').textContent = formatarMoeda(mediana(valores)) + unidade;
    document.getElementById('metric-area').textContent = Math.round(media(areas)) + ' m²';
    document.getElementById('metric-area-mediana').textContent = Math.round(mediana(areas)) + ' m²';
}

// ── Gráficos ──
function renderizarGraficos(dados) {
    const layoutBase = {
        font: { family: '-apple-system, BlinkMacSystemFont, sans-serif' },
        margin: { t: 40, b: 60, l: 60, r: 20 },
        paper_bgcolor: 'white',
        plot_bgcolor: 'white',
    };

    const labelPreco = modoAtual === 'aluguel' ? 'Aluguel' : 'Preço';
    const unidade = modoAtual === 'aluguel' ? '/mês' : '';

    // ── Barras por bairro ──
    const porBairro = {};
    dados.forEach(d => {
        const bairro = d.bairro;
        const ppm2 = parseNum(d.preco_por_m2);
        if (!bairro || isNaN(ppm2) || ppm2 <= 0) return;
        if (!porBairro[bairro]) porBairro[bairro] = [];
        porBairro[bairro].push(ppm2);
    });

    const bairrosNomes = Object.keys(porBairro)
        .filter(b => porBairro[b].length >= 3)
        .sort((a, b) => mediana(porBairro[b]) - mediana(porBairro[a]));

    if (bairrosNomes.length) {
        const top15 = bairrosNomes.slice(0, 15);
        Plotly.newPlot('chart-bairros', [
            {
                x: top15,
                y: top15.map(b => Math.round(media(porBairro[b]))),
                type: 'bar',
                name: 'Média',
                marker: { color: '#636EFA' },
            },
            {
                x: top15,
                y: top15.map(b => Math.round(mediana(porBairro[b]))),
                type: 'bar',
                name: 'Mediana',
                marker: { color: '#EF553B' },
            },
        ], {
            ...layoutBase,
            title: { text: labelPreco + '/m² por Bairro (Top 15)', font: { size: 14 } },
            barmode: 'group',
            xaxis: { tickangle: -45, tickfont: { size: 11 } },
            yaxis: { title: labelPreco + '/m² (R$)' + unidade, tickprefix: 'R$ ' },
            legend: { orientation: 'h', y: -0.25 },
            height: 420,
        }, { responsive: true });
    } else {
        Plotly.newPlot('chart-bairros', [], { ...layoutBase, title: { text: 'Sem dados suficientes' } });
    }

    // ── Histograma ──
    const ppm2Filtrados = dados
        .map(d => parseNum(d.preco_por_m2))
        .filter(v => !isNaN(v) && v > 0 && v < 50000);

    if (ppm2Filtrados.length > 10) {
        Plotly.newPlot('chart-histograma', [{
            x: ppm2Filtrados,
            type: 'histogram',
            nbinsx: 50,
            marker: { color: '#1565c0', line: { width: 1, color: 'white' } },
        }], {
            ...layoutBase,
            title: { text: 'Distribuição de ' + labelPreco + '/m²', font: { size: 14 } },
            xaxis: { title: labelPreco + '/m² (R$)' + unidade, tickprefix: 'R$ ' },
            yaxis: { title: 'Quantidade' },
            bargap: 0.05,
            height: 420,
        }, { responsive: true });
    } else {
        Plotly.newPlot('chart-histograma', [], { ...layoutBase, title: 'Sem dados suficientes' });
    }

    // ── Boxplot ──
    const topBairrosBox = bairrosNomes.slice(0, 12);
    if (topBairrosBox.length > 2) {
        const tracesBox = topBairrosBox.map(b => ({
            y: porBairro[b],
            type: 'box',
            name: b.length > 15 ? b.substring(0, 15) + '...' : b,
            boxpoints: 'outliers',
        }));

        Plotly.newPlot('chart-boxplot', tracesBox, {
            ...layoutBase,
            title: { text: 'Dispersão de ' + labelPreco + '/m² por Bairro', font: { size: 14 } },
            yaxis: { title: labelPreco + '/m² (R$)' + unidade, tickprefix: 'R$ ' },
            showlegend: false,
            height: 420,
        }, { responsive: true });
    } else {
        Plotly.newPlot('chart-boxplot', [], { ...layoutBase, title: 'Sem dados suficientes' });
    }

    // ── Composição por tipo ──
    const porTipo = {};
    dados.forEach(d => {
        const tipo = d.tipo_imovel;
        if (!tipo) return;
        porTipo[tipo] = (porTipo[tipo] || 0) + 1;
    });

    const tipoLabels = Object.keys(porTipo);
    if (tipoLabels.length > 0) {
        const cores = ['#636EFA', '#EF553B', '#00CC96', '#AB63FA', '#FFA15A', '#19D3F3'];
        Plotly.newPlot('chart-composicao', [{
            labels: tipoLabels,
            values: tipoLabels.map(t => porTipo[t]),
            type: 'pie',
            hole: 0.45,
            marker: { colors: cores.slice(0, tipoLabels.length) },
            textinfo: 'label+percent',
            textposition: 'outside',
        }], {
            ...layoutBase,
            title: { text: 'Composição por Tipo', font: { size: 14 } },
            showlegend: false,
            height: 420,
        }, { responsive: true });
    } else {
        Plotly.newPlot('chart-composicao', [], { ...layoutBase, title: 'Sem dados' });
    }
}

// ── Mapa ──
function renderizarMapa(dados) {
    markers.forEach(m => {
        if (mapa) mapa.removeLayer(m);
    });
    markers = [];

    const comCoords = dados.filter(d => {
        const lat = parseNum(d.lat);
        const lng = parseNum(d.lng);
        return !isNaN(lat) && !isNaN(lng) && lat !== 0 && lng !== 0;
    });

    if (!comCoords.length) {
        const mapaDiv = document.getElementById('mapa');
        mapaDiv.innerHTML = '<p style="text-align:center;padding:2rem;color:#999;">Sem coordenadas disponíveis</p>';
        mapaDiv.style.height = '200px';
        return;
    }

    if (document.getElementById('mapa').querySelector('p')) {
        document.getElementById('mapa').innerHTML = '';
        document.getElementById('mapa').style.height = '500px';
    }

    const centroLat = comCoords.reduce((s, d) => s + parseNum(d.lat), 0) / comCoords.length;
    const centroLng = comCoords.reduce((s, d) => s + parseNum(d.lng), 0) / comCoords.length;

    if (!mapa) {
        mapa = L.map('mapa').setView([centroLat, centroLng], 12);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors',
            maxZoom: 18,
        }).addTo(mapa);
    } else {
        mapa.setView([centroLat, centroLng], 12);
    }

    const fragment = document.createDocumentFragment();
    const MAX_MARKERS = 2000;
    const comCoordsLimited = comCoords.slice(0, MAX_MARKERS);

    comCoordsLimited.forEach(d => {
        const lat = parseNum(d.lat);
        const lng = parseNum(d.lng);
        const ppm2 = parseNum(d.preco_por_m2);

        let cor = '#999';
        if (!isNaN(ppm2)) {
            if (ppm2 < 4000) cor = '#4caf50';
            else if (ppm2 < 6000) cor = '#2196f3';
            else if (ppm2 < 8000) cor = '#ff9800';
            else if (ppm2 < 12000) cor = '#f44336';
            else cor = '#9c27b0';
        }

        const marker = L.circleMarker([lat, lng], {
            radius: 5,
            fillColor: cor,
            color: '#333',
            weight: 1,
            fillOpacity: 0.85,
        }).addTo(mapa);
        const link = d.url ? `<a href="${d.url}" target="_blank" style="color:#1565c0;">Ver anúncio</a>` : '';
        const titulo = d.titulo || 'Sem título';
        const bairro = d.bairro || '-';
        const valor = d.valor_imovel ? formatarMoeda(d.valor_imovel) : '-';
        const ppm2Txt = ppm2 ? formatarMoeda(ppm2) + '/m²' : '-';
        const metragem = d.metragem ? d.metragem + ' m²' : '-';
        const quartos = d.quartos || '-';

        marker.bindPopup(`
            <div style="min-width:200px;">
                <b style="font-size:1rem;">${titulo}</b><br>
                <span style="color:#666;">${bairro}</span><br><br>
                <b>${valor}</b> &nbsp; <span style="color:#1565c0;">${ppm2Txt}</span><br>
                📐 ${metragem} &nbsp; 🛏️ ${quartos} qto<br>
                ${link}
            </div>
        `);

        markers.push(marker);
    });

    setTimeout(() => mapa.invalidateSize(), 150);
}

// ── Tabela ──
let tabelaPagina = 1;
const TABELA_POR_PAGINA = 25;
let tabelaDados = [];
let tabelaOrdemColuna = null;
let tabelaOrdemAsc = true;

const COLUNAS_VENDA = [
    { titulo: 'Link', campo: null, tipo: 'link' },
    { titulo: 'Título', campo: 'titulo', tipo: 'texto' },
    { titulo: 'Bairro', campo: 'bairro', tipo: 'texto' },
    { titulo: 'Tipo', campo: 'tipo_imovel', tipo: 'texto' },
    { titulo: 'Preço', campo: 'valor_imovel', tipo: 'numero' },
    { titulo: 'Preço/m²', campo: 'preco_por_m2', tipo: 'numero' },
    { titulo: 'Área', campo: 'metragem', tipo: 'numero' },
    { titulo: 'Quartos', campo: 'quartos', tipo: 'numero' },
    { titulo: 'Banheiros', campo: 'banheiros', tipo: 'numero' },
    { titulo: 'Vagas', campo: 'vagas', tipo: 'numero' },
    { titulo: 'Preço Predit.', campo: 'valor_predito', tipo: 'numero' },
    { titulo: 'Pred. Min', campo: 'valor_predito_lo', tipo: 'numero' },
    { titulo: 'Pred. Max', campo: 'valor_predito_hi', tipo: 'numero' },
    { titulo: 'Dias Pub.', campo: 'dias_publicacao', tipo: 'numero' },
];

const COLUNAS_ALUGUEL = [
    { titulo: 'Link', campo: null, tipo: 'link' },
    { titulo: 'Título', campo: 'titulo', tipo: 'texto' },
    { titulo: 'Bairro', campo: 'bairro', tipo: 'texto' },
    { titulo: 'Tipo', campo: 'tipo_imovel', tipo: 'texto' },
    { titulo: 'Aluguel', campo: 'valor_imovel', tipo: 'numero' },
    { titulo: 'Aluguel/m²', campo: 'preco_por_m2', tipo: 'numero' },
    { titulo: 'Área', campo: 'metragem', tipo: 'numero' },
    { titulo: 'Quartos', campo: 'quartos', tipo: 'numero' },
    { titulo: 'Banheiros', campo: 'banheiros', tipo: 'numero' },
    { titulo: 'Vagas', campo: 'vagas', tipo: 'numero' },
    { titulo: 'Condomínio', campo: 'condominio', tipo: 'numero' },
    { titulo: 'IPTU', campo: 'iptu', tipo: 'numero' },
    { titulo: 'Dias Pub.', campo: 'dias_publicacao', tipo: 'numero' },
];

function getColunasAtuais() {
    return modoAtual === 'aluguel' ? COLUNAS_ALUGUEL : COLUNAS_VENDA;
}

function atualizarCabecalhoTabela() {
    const colunas = getColunasAtuais();
    const thead = document.querySelector('#tabela-imoveis thead tr');
    thead.innerHTML = '';
    colunas.forEach(col => {
        const th = document.createElement('th');
        th.textContent = col.titulo;
        thead.appendChild(th);
    });
}

function tabelaOrdenar(campo) {
    if (tabelaOrdemColuna === campo) {
        tabelaOrdemAsc = !tabelaOrdemAsc;
    } else {
        tabelaOrdemColuna = campo;
        tabelaOrdemAsc = true;
    }
    aplicarFiltros();
}

function tabelaAplicarOrdem(dados) {
    if (!tabelaOrdemColuna) return dados;
    const colunas = getColunasAtuais();
    const col = colunas.find(c => c.campo === tabelaOrdemColuna);
    if (!col) return dados;
    const dir = tabelaOrdemAsc ? 1 : -1;
    const copia = [...dados];
    copia.sort((a, b) => {
        const va = a[col.campo];
        const vb = b[col.campo];
        if (va === null || va === undefined || va === '') return 1;
        if (vb === null || vb === undefined || vb === '') return -1;
        if (col.tipo === 'numero') {
            return (parseFloat(va) - parseFloat(vb)) * dir;
        }
        return String(va).localeCompare(String(vb), 'pt-BR') * dir;
    });
    return copia;
}

function renderizarTabela(dados) {
    tabelaPagina = 1;
    tabelaDados = tabelaAplicarOrdem(dados);
    _renderizarTabelaPagina();
}

function _renderizarTabelaPagina() {
    const colunas = getColunasAtuais();
    const tbody = document.querySelector('#tabela-imoveis tbody');
    tbody.innerHTML = '';

    const container = document.getElementById('tabela-imoveis').parentElement;
    const avisoExistente = container.querySelector('.tabela-aviso');
    if (avisoExistente) avisoExistente.remove();

    const ths = document.querySelectorAll('#tabela-imoveis thead th');
    ths.forEach((th, i) => {
        if (i >= colunas.length) return;
        const col = colunas[i];
        if (col.campo) {
            th.classList.add('sortable');
            th.onclick = function() { tabelaOrdenar(col.campo); };
        } else {
            th.classList.remove('sortable');
            th.onclick = null;
        }
        const seta = tabelaOrdemColuna === col.campo ? (tabelaOrdemAsc ? ' ▲' : ' ▼') : '';
        th.innerHTML = col.titulo + (seta ? '<span class="sort-seta">' + seta + '</span>' : '');
    });

    const MAX_TABELA = 1000;
    const dadosLimitados = tabelaDados.slice(0, MAX_TABELA);

    if (tabelaDados.length > MAX_TABELA) {
        const aviso = document.createElement('p');
        aviso.className = 'tabela-aviso';
        aviso.textContent = 'Mostrando ' + MAX_TABELA + ' de ' + tabelaDados.length.toLocaleString('pt-BR') + ' imóveis — use os filtros para refinar';
        container.insertBefore(aviso, document.getElementById('tabela-imoveis'));
    }

    const totalPaginas = Math.ceil(dadosLimitados.length / TABELA_POR_PAGINA);
    if (tabelaPagina > totalPaginas) tabelaPagina = totalPaginas || 1;
    const inicio = (tabelaPagina - 1) * TABELA_POR_PAGINA;
    const fim = inicio + TABELA_POR_PAGINA;
    const paginaDados = dadosLimitados.slice(inicio, fim);

    function esc(val) {
        if (val === null || val === undefined) return '-';
        var s = String(val);
        s = s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        return s;
    }

    var html = '';
    for (var i = 0; i < paginaDados.length; i++) {
        var d = paginaDados[i];
        html += '<tr>';
        html += '<td>' + (d.url ? '<a href="' + esc(d.url) + '" target="_blank">Abrir</a>' : '-') + '</td>';
        html += '<td>' + esc(d.titulo) + '</td>';
        html += '<td>' + esc(d.bairro) + '</td>';
        html += '<td>' + esc(d.tipo_imovel) + '</td>';
        html += '<td>' + (d.valor_imovel ? formatarMoeda(d.valor_imovel) : '-') + '</td>';
        html += '<td>' + (d.preco_por_m2 ? formatarMoeda(d.preco_por_m2) : '-') + '</td>';
        html += '<td>' + (d.metragem ? d.metragem + ' m²' : '-') + '</td>';
        html += '<td>' + (d.quartos ?? '-') + '</td>';
        html += '<td>' + (d.banheiros ?? '-') + '</td>';
        html += '<td>' + (d.vagas ?? '-') + '</td>';
        if (modoAtual === 'aluguel') {
            html += '<td>' + (d.condominio ? formatarMoeda(d.condominio) : '-') + '</td>';
            html += '<td>' + (d.iptu ? formatarMoeda(d.iptu) : '-') + '</td>';
        } else {
            html += '<td>' + (d.valor_predito ? formatarMoeda(d.valor_predito) : '-') + '</td>';
            html += '<td>' + (d.valor_predito_lo ? formatarMoeda(d.valor_predito_lo) : '-') + '</td>';
            html += '<td>' + (d.valor_predito_hi ? formatarMoeda(d.valor_predito_hi) : '-') + '</td>';
        }
        html += '<td>' + (d.dias_publicacao ?? '-') + '</td>';
        html += '</tr>';
    }
    tbody.innerHTML = html;

    var paginacao = document.getElementById('tabela-paginacao');
    if (!paginacao) {
        paginacao = document.createElement('div');
        paginacao.id = 'tabela-paginacao';
        container.appendChild(paginacao);
    }

    if (totalPaginas <= 1) {
        paginacao.innerHTML = '<span class="pag-info">Mostrando ' + dadosLimitados.length + ' imóveis</span>';
        return;
    }

    var pHtml = '';
    pHtml += '<button class="pag-btn" ' + (tabelaPagina <= 1 ? 'disabled' : '') + ' onclick="irPaginaTabela(' + (tabelaPagina - 1) + ')">← Anterior</button>';
    pHtml += '<span class="pag-info">Página ' + tabelaPagina + ' de ' + totalPaginas + ' (' + dadosLimitados.length + ' imóveis)</span>';
    pHtml += '<button class="pag-btn" ' + (tabelaPagina >= totalPaginas ? 'disabled' : '') + ' onclick="irPaginaTabela(' + (tabelaPagina + 1) + ')">Próxima →</button>';
    paginacao.innerHTML = pHtml;
}

window.irPaginaTabela = function(pag) {
    tabelaPagina = pag;
    _renderizarTabelaPagina();
    document.getElementById('tabela-imoveis').scrollIntoView({ behavior: 'smooth', block: 'start' });
};
