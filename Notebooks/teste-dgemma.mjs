// Teste único da API classifier.dev (modelo dgemma) via Node.
// Uso: node Notebooks/teste-dgemma.mjs
// Lê: 1 foto da VivaReal -> base64 -> POST /v1/systemone -> imprime status + answers.
const IMG =
  "https://resizedimgs.vivareal.com/img/vr-listing/4e365777d7146a612c2e7a83e857f011/apartamento-com-1-quarto-a-venda-30m-no-america-joinville.webp?action=fit-in&dimension=400x400";

const dl = await fetch(IMG);
if (!dl.ok) {
  console.error("falha no download:", dl.status);
  process.exit(1);
}
const buf = Buffer.from(await dl.arrayBuffer());
const b64 = buf.toString("base64");
console.log("bytes:", buf.length, "| base64 chars:", b64.length);
if (b64.length > 900_000) {
  console.error("grande demais p/ 1 request (>900k chars); aborte");
  process.exit(1);
}

const res = await fetch("https://classifier.dev/v1/systemone", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({
    model: "dgemma",
    state: "Apartamento em Joinville. Avalie conservação.",
    images: ["data:image/webp;base64," + b64],
    questions: {
      conservacao: {
        type: "choice",
        instructions: "Qual o estado de conservação visível?",
        criteria: {
          "bem conservado": null,
          "desgaste leve": null,
          "desgastado": null,
          "precário": null,
        },
      },
    },
  }),
});
console.log("status:", res.status);
console.log(JSON.stringify(await res.json(), null, 1).slice(0, 600));
