var modeloJson = null;
var configPredicao = null;
var bairroStats = null;
var clusterData = null;
var targetTransform = 'none';
var topicModel = null;

// Método das features igual ao app: JSON oficial do treino primeiro,
// introspecção do pipeline (feature_names) como fallback
function getModelFeatures() {
    if (modeloJson && modeloJson.features_info && modeloJson.features_info.features
        && modeloJson.features_info.features.length) {
        return modeloJson.features_info.features;
    }
    return (modeloJson && modeloJson.feature_names) || [];
}

var CIDADES_ESTADO = {
    'joinville': 'SC', 'balneario_camboriu': 'SC', 'florianopolis': 'SC',
    'blumenau': 'SC', 'itajai': 'SC', 'itapema': 'SC',
    'itapoa': 'SC', 'jaragua': 'SC', 'curitiba': 'PR',
};

var CENTROS_CIDADES = {
    'joinville': [-26.3045, -48.8487],
    'balneario_camboriu': [-26.9908, -48.6355],
    'florianopolis': [-27.5954, -48.5480],
    'blumenau': [-26.9194, -49.0661],
    'itajai': [-26.9078, -48.6619],
    'itapema': [-27.0969, -48.6134],
    'itapoa': [-26.1833, -48.6167],
    'jaragua': [-26.4938, -49.0753],
    'curitiba': [-25.4284, -49.2733],
};

function carregarPredicao(cidade) {
    var pasta = 'data/';
    return Promise.all([
        fetch(pasta + 'modelo_' + cidade + '.json').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
        fetch(pasta + 'bairro_stats_' + cidade + '.json').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
        fetch(pasta + 'cluster_' + cidade + '.json').then(function(r) { return r.ok ? r.json() : null; }).catch(function() { return null; }),
    ]).then(function(results) {
        modeloJson = results[0];
        bairroStats = results[1];
        clusterData = results[2];

        if (Array.isArray(bairroStats)) {
            var dict = {};
            bairroStats.forEach(function(item) {
                dict[item.bairro] = item;
            });
            bairroStats = dict;
        }

        if (!modeloJson) {
            console.error('Modelo nao encontrado para', cidade);
            return false;
        }

        targetTransform = modeloJson.target_transform || 'none';
        configPredicao = {
            todas_features: getModelFeatures(),
            features_categoricas: ['tipo_imovel', 'bairro', 'tem_elevador', 'novo_lancamento', 'dist_centro_faixa', 'bairro_cluster'],
            features_tematicas: getModelFeatures().filter(function(f) { return f.indexOf('componente_') === 0; }),
        };

        topicModel = modeloJson.topics || null;

        console.log('Predicao JSON carregada:', cidade, '|', modeloJson.ensemble.type,
            '|', modeloJson.ensemble.n_estimators, 'trees');
        renderizarFormularioPredicao();
        popularBairrosPredicao();
        return true;
    });
}

function popularBairrosPredicao() {
    var sel = document.getElementById('pred-bairro');
    if (!sel || !bairroStats) return;
    sel.innerHTML = '';
    var bairros = Object.keys(bairroStats).sort();
    bairros.forEach(function(b) {
        var opt = document.createElement('option');
        opt.value = b;
        opt.textContent = b;
        sel.appendChild(opt);
    });
}

// ── Formulário dinâmico: só mostra inputs das features do modelo carregado ──
var DERIVADAS = ['lat', 'lng', 'dist_centro', 'dist_centro_faixa',
    'score_escola_privada', 'score_escola_publica', 'score_hospitais',
    'score_mercado', 'score_farmacia', 'score_parque', 'score_seguranca', 'score_educacao',
    'metro_quadrado_bairro_mean', 'metro_quadrado_bairro_median', 'valor_bairro_mean',
    'bairro_rank', 'bairro_cluster', 'quartos_por_metro', 'vagas_por_metro',
    'banheiros_por_quarto', 'sem_rua', 'componente_0', 'componente_1',
    'componente_2', 'componente_3'];

var WIDGETS = {
    metragem:         { tipo: 'number',   rotulo: 'Metragem (m²)', min: 10, max: 10000, padrao: 70, grupo: 'imovel' },
    quartos:          { tipo: 'number',   rotulo: 'Quartos', min: 0, max: 20, padrao: 3, grupo: 'imovel' },
    banheiros:        { tipo: 'number',   rotulo: 'Banheiros', min: 0, max: 20, padrao: 2, grupo: 'imovel' },
    vagas:            { tipo: 'number',   rotulo: 'Vagas', min: 0, max: 20, padrao: 1, grupo: 'imovel' },
    suites:           { tipo: 'select',   rotulo: 'Suítes', opcoes: [['','Não informado'],['0','0'],['1','1'],['2','2'],['3','3'],['4','4'],['5','5+']], grupo: 'imovel' },
    tipo_imovel:      { tipo: 'select',   rotulo: 'Tipo', opcoes: [['apartamento','Apartamento'],['casa','Casa']], grupo: 'imovel' },
    predicao_idade:   { tipo: 'number',   rotulo: 'Idade do imóvel (anos)', min: 0, max: 200, padrao: 0, ajuda: '0 = novo', grupo: 'imovel' },
    bairro:           { tipo: 'select_bairro', rotulo: 'Bairro', grupo: 'local' },
    novo_lancamento:  { tipo: 'checkbox', rotulo: 'Novo lançamento', grupo: 'flags' },
    tem_elevador:     { tipo: 'checkbox', rotulo: 'Tem elevador', grupo: 'flags' },
    priv_churrasqueira: { tipo: 'checkbox', rotulo: 'Churrasqueira', grupo: 'priv' },
    priv_varanda:     { tipo: 'checkbox', rotulo: 'Varanda', grupo: 'priv' },
    priv_piscina:     { tipo: 'checkbox', rotulo: 'Piscina', grupo: 'priv' },
    priv_closet:      { tipo: 'checkbox', rotulo: 'Closet', grupo: 'priv' },
    comum_piscina:    { tipo: 'checkbox', rotulo: 'Piscina', grupo: 'comum' },
    comum_elevador:   { tipo: 'checkbox', rotulo: 'Elevador', grupo: 'comum' },
    comum_salao:      { tipo: 'checkbox', rotulo: 'Salão de festas', grupo: 'comum' },
    comum_churrasqueira: { tipo: 'checkbox', rotulo: 'Churrasqueira', grupo: 'comum' },
    comum_playground: { tipo: 'checkbox', rotulo: 'Playground', grupo: 'comum' },
    comum_academia:   { tipo: 'checkbox', rotulo: 'Academia/Fitness', grupo: 'comum' },
    comum_spa:        { tipo: 'checkbox', rotulo: 'Spa/Sauna', grupo: 'comum' },
};

var GRUPOS_PRED = [
    ['imovel', '🏠 Imóvel'],
    ['local', '📍 Localização'],
    ['flags', '⚙️ Características'],
    ['priv', '🛋️ Privativas'],
    ['comum', '🏢 Comuns'],
    ['extras', '➕ Outras variáveis do modelo'],
];

function idCampo(feature) {
    var mapa = { tipo_imovel: 'pred-tipo', bairro: 'pred-bairro',
        novo_lancamento: 'pred-novo', tem_elevador: 'pred-elevador',
        predicao_idade: 'pred-idade' };
    if (mapa[feature]) return mapa[feature];
    return 'pred-' + feature.replace(/_/g, '-');
}

function renderizarFormularioPredicao() {
    var box = document.getElementById('pred-form-dinamico');
    if (!box || !modeloJson) return;
    box.innerHTML = '';
    var feats = getModelFeatures();
    var temTopicos = feats.some(function(f) { return f.indexOf('componente_') === 0; });

    function criarCampo(feature, cfg) {
        var wrap = document.createElement('div');
        var id = idCampo(feature);
        if (cfg.tipo === 'checkbox') {
            var lab = document.createElement('label');
            lab.className = 'checkbox-inline';
            var inp = document.createElement('input');
            inp.type = 'checkbox'; inp.id = id;
            inp.setAttribute('data-feature', feature);
            lab.appendChild(inp);
            lab.appendChild(document.createTextNode(' ' + cfg.rotulo));
            wrap.appendChild(lab);
        } else if (cfg.tipo === 'select' || cfg.tipo === 'select_bairro') {
            var lab2 = document.createElement('label');
            lab2.textContent = cfg.rotulo;
            var sel = document.createElement('select');
            sel.id = id;
            sel.setAttribute('data-feature', feature);
            (cfg.opcoes || []).forEach(function(op) {
                var o = document.createElement('option');
                o.value = op[0]; o.textContent = op[1];
                sel.appendChild(o);
            });
            lab2.appendChild(sel);
            wrap.appendChild(lab2);
        } else {
            var lab3 = document.createElement('label');
            lab3.textContent = cfg.rotulo;
            var num = document.createElement('input');
            num.type = 'number'; num.id = id;
            num.setAttribute('data-feature', feature);
            if (cfg.min !== undefined) num.min = cfg.min;
            if (cfg.max !== undefined) num.max = cfg.max;
            if (cfg.padrao !== undefined) num.value = cfg.padrao;
            if (cfg.ajuda) num.placeholder = cfg.ajuda;
            lab3.appendChild(num);
            wrap.appendChild(lab3);
        }
        return wrap;
    }

    GRUPOS_PRED.forEach(function(g) {
        var col = document.createElement('div');
        col.className = 'pred-form-col';
        var titulo = document.createElement('h4');
        titulo.textContent = g[1];
        col.appendChild(titulo);
        var tem = false;
        feats.forEach(function(f) {
            if (DERIVADAS.indexOf(f) !== -1) return;
            var cfg = WIDGETS[f] ||
                { tipo: 'number', rotulo: f, padrao: 0, grupo: 'extras' };
            if ((cfg.grupo || 'extras') !== g[0]) return;
            col.appendChild(criarCampo(f, cfg));
            tem = true;
        });
        if (g[0] === 'local') {
            [['pred-rua', 'text', 'Rua (opcional)', 'Rua...'],
             ['pred-numero', 'number', 'Número (opcional)', 'Nº']].forEach(function(c) {
                var lab = document.createElement('label');
                lab.textContent = c[2];
                var inp = document.createElement('input');
                inp.type = c[1]; inp.id = c[0]; inp.placeholder = c[3] || '';
                if (c[1] === 'number') inp.min = 0;
                lab.appendChild(inp);
                col.appendChild(lab);
            });
            tem = true;
            if (temTopicos) {
                var labd = document.createElement('label');
                labd.textContent = 'Descrição (opcional)';
                var ta = document.createElement('textarea');
                ta.id = 'pred-descricao'; ta.rows = 3;
                ta.placeholder = 'Detalhes do imóvel...';
                labd.appendChild(ta);
                col.appendChild(labd);
            }
        }
        if (tem) box.appendChild(col);
    });
}

function geocodificar(rua, numero, bairro, cidade) {
    var estado = CIDADES_ESTADO[cidade] || 'SC';
    var query;
    if (rua && numero) {
        query = numero + ' ' + rua + ', ' + bairro + ', ' + cidade + ', ' + estado + ', Brasil';
    } else if (rua) {
        query = rua + ', ' + bairro + ', ' + cidade + ', ' + estado + ', Brasil';
    } else {
        query = bairro + ', ' + cidade + ', ' + estado + ', Brasil';
    }

    return fetch(
        'https://nominatim.openstreetmap.org/search?q=' + encodeURIComponent(query) + '&format=json&limit=1',
        { headers: { 'User-Agent': 'analise_imoveis_site_v1' } }
    )
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.length > 0) {
            return { lat: parseFloat(data[0].lat), lng: parseFloat(data[0].lon) };
        }
        return fallbackCoordenadas(bairro);
    })
    .catch(function() {
        return fallbackCoordenadas(bairro);
    });
}

function fallbackCoordenadas(bairro) {
    if (bairroStats && bairroStats[bairro]) {
        return {
            lat: bairroStats[bairro].lat_centroide || 0,
            lng: bairroStats[bairro].lng_centroide || 0,
        };
    }
    return { lat: 0, lng: 0 };
}

function calcularCluster(scores) {
    if (!clusterData) return 0;
    var clusterCols = ['score_escola_privada', 'score_escola_publica', 'score_hospitais',
        'score_mercado', 'score_farmacia', 'score_parque', 'score_seguranca'];
    var x = clusterCols.map(function(c) { return scores[c] || 0; });

    var scaled = x.map(function(v, i) {
        var mean = clusterData.scaler_mean[i] || 0;
        var scale = clusterData.scaler_scale[i] || 1;
        return (v - mean) / scale;
    });

    var bestCluster = 0;
    var bestDist = Infinity;
    clusterData.centroids.forEach(function(centroid, idx) {
        var dist = 0;
        scaled.forEach(function(v, i) {
            dist += (v - centroid[i]) * (v - centroid[i]);
        });
        if (dist < bestDist) {
            bestDist = dist;
            bestCluster = idx;
        }
    });
    return bestCluster;
}

function calcularDistCentro(lat, lng, cidade) {
    var centro = CENTROS_CIDADES[cidade] || [-26.3045, -48.8487];
    var toRad = function(x) { return x * Math.PI / 180; };
    var dLat = toRad(lat - centro[0]);
    var dLng = toRad(lng - centro[1]);
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(toRad(centro[0])) * Math.cos(toRad(lat)) *
        Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function aplicarTopicos(descricao) {
    if (!topicModel || !descricao) return [0, 0, 0, 0];

    var t = descricao
        .replace(/código\s+do\s+anúncio[\s:\d\-]+|código:\s*\d+|ref\.?:?\s*\d+|\b(creci|whatsapp|telefone|contato|celular)\b[\s\d\-\\(\\)]+|\d{7,}|https?\:\/\/\S+|www\.\S+/gi, ' ')
        .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
        .replace(/\b\d+\b/g, ' ')
        .replace(/[^a-zA-Z\s]/g, ' ')
        .replace(/\s+/g, ' ').trim();

    var tokens = t.toLowerCase().split(/\s+/).filter(function(w) { return w.length > 2; });
    t = tokens.join(' ');

    var vocab = topicModel.vocabulary;
    var tfidf = new Array(topicModel.max_features).fill(0);
    var idf = topicModel.idf;
    var wordCounts = {};
    t.split(/\s+/).forEach(function(w) { wordCounts[w] = (wordCounts[w] || 0) + 1; });

    Object.keys(wordCounts).forEach(function(word) {
        if (word in vocab) {
            var idx = vocab[word];
            if (idx < tfidf.length) {
                tfidf[idx] = wordCounts[word] * idf[idx];
            }
        }
    });

    var norm = 0;
    for (var i = 0; i < tfidf.length; i++) norm += tfidf[i] * tfidf[i];
    norm = Math.sqrt(norm);
    if (norm > 0) {
        for (var i = 0; i < tfidf.length; i++) tfidf[i] /= norm;
    }

    var components = topicModel.nmf_components;
    var nTopics = topicModel.n_topics;
    var result = [];
    for (var k = 0; k < nTopics; k++) {
        var val = 0;
        for (var j = 0; j < tfidf.length; j++) {
            val += tfidf[j] * (components[k][j] || 0);
        }
        result.push(Math.max(0, val));
    }
    while (result.length < 4) result.push(0);
    return result;
}

function montarFeatures(inputs) {
    var metragem = inputs.metragem || 70;
    var quartos = (inputs.quartos !== undefined && inputs.quartos !== null && inputs.quartos !== '') ? inputs.quartos : 3;
    var banheiros = (inputs.banheiros !== undefined && inputs.banheiros !== null && inputs.banheiros !== '') ? inputs.banheiros : 2;
    var vagas = inputs.vagas || 0;

    var features = {
        metragem: metragem,
        quartos: quartos,
        banheiros: banheiros,
        vagas: vagas,
        lat: inputs.lat,
        lng: inputs.lng,
        tipo_imovel: inputs.tipo_imovel,
        bairro: inputs.bairro,
        novo_lancamento: inputs.novo_lancamento ? 1 : 0,
        tem_elevador: inputs.tem_elevador ? 1 : 0,
        quartos_por_metro: quartos / (metragem + 1),
        vagas_por_metro: vagas / (metragem + 1),
        banheiros_por_quarto: banheiros / (quartos + 1),
        sem_rua: inputs.rua ? 0 : 1,
        predicao_idade: inputs.idade || 0,
    };

    // Amenities + qualquer feature futura: merge genérico de inputs.extras
    if (inputs.extras) {
        Object.keys(inputs.extras).forEach(function(k) {
            if (features[k] === undefined) features[k] = inputs.extras[k];
        });
    }

    if (bairroStats && bairroStats[inputs.bairro]) {
        var bs = bairroStats[inputs.bairro];
        features.metro_quadrado_bairro_mean = bs.media_ppm2 || bs.metro_quadrado_bairro_mean || 0;
        features.metro_quadrado_bairro_median = bs.mediana_ppm2 || bs.metro_quadrado_bairro_median || 0;
        features.valor_bairro_mean = bs.mediana_valor || bs.valor_bairro_mean || 0;
        features.bairro_rank = bs.bairro_rank || 0;
        features.bairro_cluster = bs.bairro_cluster !== undefined ? bs.bairro_cluster : 0;
    } else {
        features.metro_quadrado_bairro_mean = 0;
        features.metro_quadrado_bairro_median = 0;
        features.valor_bairro_mean = 0;
        features.bairro_rank = 0;
        features.bairro_cluster = 0;
    }

    var scoreFeatures = ['score_escola_privada', 'score_escola_publica', 'score_hospitais',
        'score_mercado', 'score_farmacia', 'score_parque', 'score_seguranca', 'score_educacao'];
    var scores = {};
    scoreFeatures.forEach(function(sf) {
        features[sf] = (bairroStats && bairroStats[inputs.bairro] && bairroStats[inputs.bairro][sf] !== undefined)
            ? bairroStats[inputs.bairro][sf] : 0;
        scores[sf] = features[sf];
    });

    if (bairroStats && bairroStats[inputs.bairro] && bairroStats[inputs.bairro].bairro_cluster !== undefined) {
        features.bairro_cluster = bairroStats[inputs.bairro].bairro_cluster;
    } else {
        features.bairro_cluster = calcularCluster(scores);
    }

    var distCentro = calcularDistCentro(inputs.lat, inputs.lng, inputs.cidade);
    features.dist_centro = Math.round(distCentro * 100) / 100;
    if (distCentro <= 5) features.dist_centro_faixa = 'centro';
    else if (distCentro <= 10) features.dist_centro_faixa = 'proximo';
    else if (distCentro <= 15) features.dist_centro_faixa = 'distante';
    else features.dist_centro_faixa = 'longe';

    if (topicModel) {
        var topicos = aplicarTopicos(inputs.descricao || '');
        features.componente_0 = topicos[0];
        features.componente_1 = topicos[1];
        features.componente_2 = topicos[2];
        features.componente_3 = topicos[3];
    }

    return features;
}

function preverValor(features) {
    if (!modeloJson) throw new Error('Modelo nao carregado');
    var ensemble = modeloJson.ensemble;
    var preproc = modeloJson.preprocessor;

    var featureNames = modeloJson.feature_names;
    var catFeatures = configPredicao.features_categoricas;

    var numValues = [];
    var numNames = [];
    featureNames.forEach(function(f) {
        if (catFeatures.indexOf(f) === -1) {
            var val = features[f];
            if (val === undefined || val === null || val === '') val = 0;
            numValues.push(parseFloat(val) || 0);
            numNames.push(f);
        }
    });

    var numProc = preprocessNumeric(numValues, numNames, preproc.numeric);

    var catEncoded = preprocessCategorical(features, catFeatures, preproc.categorical);

    var x = [];
    numProc.forEach(function(v) { x.push(v); });
    catEncoded.forEach(function(v) { x.push(v); });

    var pred = ensemble.init;
    var lr = ensemble.learning_rate;

    for (var t = 0; t < ensemble.n_estimators; t++) {
        pred += lr * predictTree(ensemble.trees[t], x);
    }

    if (targetTransform === 'log') {
        pred = Math.expm1(pred);
    } else if (targetTransform === 'sqrt') {
        pred = pred * pred;
    }

    return Math.max(0, pred);
}

function preprocessNumeric(values, names, numConfig) {
    var lambdas = numConfig.yeo_lambdas || {};
    var median = numConfig.imputer_median || {};
    var center = numConfig.scaler_center || numConfig.scaler_mean || {};
    var scale = numConfig.scaler_scale || {};
    var yjMean = numConfig.yj_standardize_mean || {};
    var yjScale = numConfig.yj_standardize_scale || {};

    return values.map(function(v, i) {
        var name = names[i];
        if (isNaN(v) || v === null || v === undefined) {
            v = median[name] || 0;
        }
        if (lambdas[name] !== undefined) {
            v = yeoJohnson(v, lambdas[name]);
        }
        if (yjMean[name] !== undefined && yjScale[name] !== undefined) {
            v = (v - yjMean[name]) / yjScale[name];
        }
        var c = center[name] || 0;
        var s = scale[name] || 1;
        return (v - c) / s;
    });
}

function yeoJohnson(x, lam) {
    if (x >= 0) {
        if (Math.abs(lam) < 1e-10) return Math.log(x + 1);
        return (Math.pow(x + 1, lam) - 1) / lam;
    } else {
        if (Math.abs(lam - 2) < 1e-10) return -Math.log(1 - x);
        return -(Math.pow(1 - x, 2 - lam) - 1) / (2 - lam);
    }
}

function preprocessCategorical(features, catFeatures, catConfig) {
    var categories = catConfig.categories || {};
    var encoded = [];

    catFeatures.forEach(function(f) {
        var val = String(features[f]);
        var cats = categories[f] || [];

        cats.forEach(function(c) {
            encoded.push(val === c ? 1 : 0);
        });
    });

    return encoded;
}

function predictTree(tree, x) {
    var node = 0;
    while (true) {
        var left = tree.children_left[node];
        var right = tree.children_right[node];
        if (left === right) {
            return tree.value[node];
        }
        var feat = tree.feature[node];
        var thresh = tree.threshold[node];
        if (x[feat] <= thresh) {
            node = left;
        } else {
            node = right;
        }
    }
}

function calcularIntervalo(features, valorPredito) {
    var desvio = valorPredito * 0.15;
    return {
        lo: Math.max(0, valorPredito - desvio),
        hi: valorPredito + desvio,
    };
}

function formatarMoedaPred(valor) {
    return 'R$ ' + Math.round(valor).toLocaleString('pt-BR');
}

function executarPredicao() {
    var cidade = document.getElementById('cidade-select').value;
    if (!modeloJson) {
        alert('Modelo de predicao nao carregado para esta cidade.');
        return;
    }

    // Coleta genérica: lê todo [data-feature] renderizado pelo modelo da vez
    var inputs = { cidade: cidade };
    var catFeats = (configPredicao && configPredicao.features_categoricas) || [];
    Array.prototype.forEach.call(
        document.querySelectorAll('#pred-form-dinamico [data-feature]'),
        function(el) {
            var f = el.getAttribute('data-feature');
            if (el.type === 'checkbox') { inputs[f] = el.checked ? 1 : 0; return; }
            if (catFeats.indexOf(f) !== -1 || el.tagName === 'SELECT') {
                if (f === 'suites') inputs[f] = el.value || 0;
                else inputs[f] = el.value;
                return;
            }
            inputs[f] = parseFloat(el.value);
            if (isNaN(inputs[f])) inputs[f] = 0;
        }
    );
    // Helpers de geocoding (não são features do modelo)
    var ruaEl = document.getElementById('pred-rua');
    var numeroEl = document.getElementById('pred-numero');
    var descEl = document.getElementById('pred-descricao');
    var rua = (ruaEl && ruaEl.value) || '';
    var numero = (numeroEl && parseInt(numeroEl.value)) || 0;
    var descricao = (descEl && descEl.value) || '';
    inputs.rua = rua; inputs.numero = numero; inputs.descricao = descricao;
    // Aliases que montarFeatures espera
    inputs.idade = inputs.predicao_idade || 0;
    inputs.tipo_imovel = inputs.tipo_imovel || 'apartamento';
    inputs.novo_lancamento = inputs.novo_lancamento ? 1 : 0;
    inputs.tem_elevador = inputs.tem_elevador ? 1 : 0;
    // Extras genéricos (amenities + features futuras desconhecidas)
    var baseKeys = { cidade: 1, rua: 1, numero: 1, descricao: 1, idade: 1,
        lat: 1, lng: 1, metragem: 1, quartos: 1, banheiros: 1, vagas: 1,
        tipo_imovel: 1, bairro: 1, novo_lancamento: 1, tem_elevador: 1,
        predicao_idade: 1 };
    inputs.extras = {};
    Object.keys(inputs).forEach(function(k) {
        if (k !== 'extras' && !baseKeys[k]) inputs.extras[k] = inputs[k];
    });
    var metragem = inputs.metragem || 70;
    var bairro = inputs.bairro || '';

    var resultDiv = document.getElementById('pred-resultado');
    var btn = document.getElementById('pred-btn');
    btn.disabled = true;
    btn.textContent = 'Calculando...';
    resultDiv.innerHTML = '<p style="color:#666;text-align:center;padding:1rem;">Geocodificando endereco...</p>';

    geocodificar(rua, numero, bairro, cidade).then(function(coords) {
        resultDiv.innerHTML = '<p style="color:#666;text-align:center;padding:1rem;">Calculando predicao...</p>';

        inputs.lat = coords.lat; inputs.lng = coords.lng;
        var features = montarFeatures(inputs);

        try {
            var valorPredito = preverValor(features);
            var intervalo = calcularIntervalo(features, valorPredito);

            resultDiv.innerHTML =
                '<div class="pred-card pred-card-principal">' +
                    '<div class="pred-label">Valor Previsto</div>' +
                    '<div class="pred-valor">' + formatarMoedaPred(valorPredito) + '</div>' +
                    '<div class="pred-intervalo">Intervalo 90%: ' + formatarMoedaPred(intervalo.lo) + ' ~ ' + formatarMoedaPred(intervalo.hi) + '</div>' +
                '</div>' +
                '<div class="pred-cards-row">' +
                    '<div class="pred-card">' +
                        '<div class="pred-label">Metragem</div>' +
                        '<div class="pred-valor-sm">' + metragem + ' m²</div>' +
                    '</div>' +
                    '<div class="pred-card">' +
                        '<div class="pred-label">Bairro</div>' +
                        '<div class="pred-valor-sm">' + bairro + '</div>' +
                    '</div>' +
                    '<div class="pred-card">' +
                        '<div class="pred-label">Preço/m²</div>' +
                        '<div class="pred-valor-sm">' + formatarMoedaPred(valorPredito / metragem) + '</div>' +
                    '</div>' +
                '</div>' +
                '<details class="pred-detalhes">' +
                    '<summary>Detalhes das features utilizadas</summary>' +
                    '<pre>' + JSON.stringify(features, null, 2) + '</pre>' +
                '</details>';
        } catch (e) {
            resultDiv.innerHTML = '<p style="color:red;">Erro na predicao: ' + e.message + '</p>';
            console.error(e);
        }

        btn.disabled = false;
        btn.textContent = 'Prever Valor';
    });
}
