var modeloJson = null;
var configPredicao = null;
var bairroStats = null;
var clusterData = null;
var targetTransform = 'none';
var topicModel = null;

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

        if (!modeloJson) {
            console.error('Modelo nao encontrado para', cidade);
            return false;
        }

        targetTransform = modeloJson.target_transform || 'none';
        configPredicao = {
            todas_features: modeloJson.feature_names,
            features_categoricas: ['tipo_imovel', 'bairro', 'tem_elevador', 'novo_lancamento', 'dist_centro_faixa', 'bairro_cluster'],
            features_tematicas: modeloJson.feature_names.filter(function(f) { return f.indexOf('componente_') === 0; }),
        };

        topicModel = modeloJson.topics || null;

        console.log('Predicao JSON carregada:', cidade, '|', modeloJson.ensemble.type,
            '|', modeloJson.ensemble.n_estimators, 'trees');
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
    var metragem = inputs.metragem;
    var quartos = inputs.quartos;
    var banheiros = inputs.banheiros;
    var vagas = inputs.vagas;

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
        sem_rua: 0,
        predicao_idade: inputs.idade || 0,
    };

    if (bairroStats && bairroStats[inputs.bairro]) {
        var bs = bairroStats[inputs.bairro];
        features.metro_quadrado_bairro_mean = bs.metro_quadrado_bairro_mean || 0;
        features.metro_quadrado_bairro_median = bs.metro_quadrado_bairro_median || 0;
        features.valor_bairro_mean = bs.valor_bairro_mean || 0;
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

    var metragem = parseInt(document.getElementById('pred-metragem').value) || 70;
    var quartos = parseInt(document.getElementById('pred-quartos').value) || 3;
    var banheiros = parseInt(document.getElementById('pred-banheiros').value) || 2;
    var vagas = parseInt(document.getElementById('pred-vagas').value) || 1;
    var tipoImovel = document.getElementById('pred-tipo').value || 'apartamento';
    var bairro = document.getElementById('pred-bairro').value;
    var novoLancamento = document.getElementById('pred-novo').checked || false;
    var temElevador = document.getElementById('pred-elevador').checked || false;
    var rua = document.getElementById('pred-rua').value || '';
    var numero = parseInt(document.getElementById('pred-numero').value) || 0;
    var descricao = document.getElementById('pred-descricao').value || '';
    var idade = parseInt(document.getElementById('pred-idade').value) || 0;

    var resultDiv = document.getElementById('pred-resultado');
    var btn = document.getElementById('pred-btn');
    btn.disabled = true;
    btn.textContent = 'Calculando...';
    resultDiv.innerHTML = '<p style="color:#666;text-align:center;padding:1rem;">Geocodificando endereco...</p>';

    geocodificar(rua, numero, bairro, cidade).then(function(coords) {
        resultDiv.innerHTML = '<p style="color:#666;text-align:center;padding:1rem;">Calculando predicao...</p>';

        var features = montarFeatures({
            metragem: metragem, quartos: quartos, banheiros: banheiros,
            vagas: vagas, tipo_imovel: tipoImovel, bairro: bairro,
            novo_lancamento: novoLancamento, tem_elevador: temElevador,
            lat: coords.lat, lng: coords.lng, descricao: descricao,
            cidade: cidade, idade: idade,
        });

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
