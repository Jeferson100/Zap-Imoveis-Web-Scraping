// Cálculo de scores de localização 100% client-side.
// Espelho JS de CriandoIndicesIndividuais.calcular_scores (pesos e raios idênticos)
// + BallTree/haversine via força bruta (708 POIs × 7 categorias = milissegundos).
//
// Uso:
//   fetch('data/pois_joinville.json').then(r => r.ok ? r.json() : null)
//     .then(j => { POIS = j; });
//   calcularScores(-26.3045, -48.8487) // -> {score_escola_privada, ..., score_educacao}
var POIS = null; // {categoria: [[lat, lng], ...]}, carregado via fetch
var POIS_RAIOS = {
    escolas_privadas: [500],
    escolas_publicas: [500],
    hospital: [1000],
    mercado: [500],
    farmacia: [300],
    parque: [1000],
    policia: [500],
};

function haversineKm(lat1, lng1, lat2, lng2) {
    var R = 6371, t = Math.PI / 180;
    var dLa = (lat2 - lat1) * t, dLn = (lng2 - lng1) * t;
    var a = Math.sin(dLa / 2) * Math.sin(dLa / 2) +
        Math.cos(lat1 * t) * Math.cos(lat2 * t) *
        Math.sin(dLn / 2) * Math.sin(dLn / 2);
    return 2 * R * Math.asin(Math.sqrt(a));
}

function distEQtd(lat, lng, pontos, raioM) {
    var menor = Infinity, qtd = 0;
    for (var i = 0; i < pontos.length; i++) {
        var dM = haversineKm(lat, lng, pontos[i][0], pontos[i][1]) * 1000;
        if (dM < menor) menor = dM;
        if (dM <= raioM) qtd++;
    }
    // Sem POI por perto: distância gigante -> exp() ~= 0,
    // igual ao Python quando a distância é NaN e imputada a jusante.
    return { dist: menor === Infinity ? 1e9 : menor, qtd: qtd };
}

function calcularScores(lat, lng) {
    function feat(cat, raio) {
        return distEQtd(lat, lng, (POIS && POIS[cat]) || [], raio);
    }
    var dp = feat('escolas_privadas', 500);
    var de = feat('escolas_publicas', 500);
    var ho = feat('hospital', 1000);
    var me = feat('mercado', 500);
    var fa = feat('farmacia', 300);
    var pa = feat('parque', 1000);
    var po = feat('policia', 500);
    var sPriv = 1.2 * Math.exp(-dp.dist / 600) + 0.6 * dp.qtd;
    var sPub = 0.6 * Math.exp(-de.dist / 600) + 0.2 * de.qtd;
    return {
        score_escola_privada: sPriv,
        score_escola_publica: sPub,
        score_hospitais: 0.8 * Math.exp(-ho.dist / 1200) + 0.4 * ho.qtd,
        score_mercado: 1.0 * Math.exp(-me.dist / 400) + 0.4 * me.qtd,
        score_farmacia: 0.6 * Math.exp(-fa.dist / 300) + 0.2 * fa.qtd,
        score_parque: 1.2 * Math.exp(-pa.dist / 1200) + 0.8 * pa.qtd,
        score_seguranca: 1.0 * Math.exp(-po.dist / 1500) + 0.3 * po.qtd,
        score_educacao: sPriv - 0.2 * sPub,
    };
}
