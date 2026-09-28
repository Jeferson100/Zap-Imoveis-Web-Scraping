// Formato igual ao Python: "%(asctime)s - %(levelname)s - %(message)s"
function ts() {
  return new Date().toISOString().replace('T', ' ').slice(0, 19);
}
function info(msg) { console.log(`${ts()} - INFO - ${msg}`); }
function warning(msg) { console.warn(`${ts()} - WARNING - ${msg}`); }
function error(msg) { console.error(`${ts()} - ERROR - ${msg}`); }
// Progresso estilo log com % (sem nova dependência, funciona em qualquer terminal)
// Se t0 (Date.now() do início) for passado, mostra decorrido + ETA.
function fmtDur(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  const h = String(Math.floor(s / 3600)).padStart(2, '0');
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return h === '00' ? `${m}:${ss}` : `${h}:${m}:${ss}`;
}
function progress(atual, total, rotulo, t0) {
  const pct = total > 0 ? ((atual / total) * 100).toFixed(1) : '0.0';
  if (!t0 || atual <= 0) {
    info(`[${pct}%] ${rotulo} ${atual}/${total}`);
    return;
  }
  const dec = Date.now() - t0;
  const taxa = atual / Math.max(dec, 1); // itens por ms
  const rest = taxa > 0 ? (total - atual) / taxa : 0;
  info(`[${pct}%] ${rotulo} ${atual}/${total} | dec ${fmtDur(dec)} | faltam ~${fmtDur(rest)}`);
}
module.exports = { info, warning, error, progress, fmtDur };
