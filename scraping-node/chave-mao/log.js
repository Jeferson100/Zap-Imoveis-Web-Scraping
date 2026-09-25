// Formato igual ao Python: "%(asctime)s - %(levelname)s - %(message)s"
function ts() {
  return new Date().toISOString().replace('T', ' ').slice(0, 19);
}
function info(msg) { console.log(`${ts()} - INFO - ${msg}`); }
function warning(msg) { console.warn(`${ts()} - WARNING - ${msg}`); }
function error(msg) { console.error(`${ts()} - ERROR - ${msg}`); }
module.exports = { info, warning, error };
