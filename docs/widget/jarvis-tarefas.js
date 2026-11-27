// Widget "Tarefas do Jarvis" para o app Scriptable (iPhone). Veja docs/CELULAR.md.
//
// Na primeira execução (tocando em Play dentro do Scriptable) ele pede o ENDEREÇO do Jarvis
// (ex.: https://meu-pc.minha-rede.ts.net) e o TOKEN, e guarda os dois no Keychain do iPhone.
// Nada disso fica neste arquivo. Para trocar depois, rode o script de novo dentro do app e escolha "Trocar".
// O widget lê só GET /api/tarefas e mostra o último resultado salvo quando o Tailscale está desligado.

const CHAVE_URL = "jarvis_url";
const CHAVE_TOKEN = "jarvis_token";
const ARQUIVO = "jarvis_tarefas_cache.json";
const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

const COR = { fundoA: "#0e1726", fundoB: "#090d16", texto: "#eaf1fb", mudo: "#8fa1ba", ciano: "#4dd5ff",
              aviso: "#fbbf24", ruim: "#fb7185", ok: "#34d399" };

// Aceita o que o teclado do iPhone costuma estragar: espaços, "https://" duplicado, maiúsculas e "/" no final.
function limparUrl(bruto) {
  let u = String(bruto || "").trim().replace(/\s+/g, "");
  u = u.replace(/^(https?:\/\/)+/i, "https://");
  if (!/^https?:\/\//i.test(u)) u = "https://" + u;
  return u.replace(/\/+$/, "").toLowerCase();
}

async function perguntar(titulo, msg, atual, segredo) {
  const a = new Alert();
  a.title = titulo; a.message = msg;
  a.addTextField("", atual || "").isSecure = !!segredo;
  a.addAction("Salvar"); a.addCancelAction("Cancelar");
  const r = await a.presentAlert();
  return r === 0 ? a.textFieldValue(0).trim() : null;
}

async function configurar(forcar) {
  if (!forcar && Keychain.contains(CHAVE_URL) && Keychain.contains(CHAVE_TOKEN)) return true;
  const url = await perguntar("Endereço do Jarvis", "Ex.: https://meu-pc.minha-rede.ts.net (sem / no final)",
                              Keychain.contains(CHAVE_URL) ? Keychain.get(CHAVE_URL) : "https://", false);
  if (!url) return false;
  const token = await perguntar("Token do celular", "Em config.json > celular > token, no PC.", "", true);
  if (!token) return false;
  Keychain.set(CHAVE_URL, limparUrl(url));
  Keychain.set(CHAVE_TOKEN, token);
  return true;
}

function arquivoCache() {
  const fm = FileManager.local();
  return { fm, caminho: fm.joinPath(fm.documentsDirectory(), ARQUIVO) };
}
function lerCache() {
  try { const { fm, caminho } = arquivoCache(); return fm.fileExists(caminho) ? JSON.parse(fm.readString(caminho)) : null; }
  catch (e) { return null; }
}
function gravarCache(dados) {
  try { const { fm, caminho } = arquivoCache(); fm.writeString(caminho, JSON.stringify({ quando: Date.now(), dados })); } catch (e) { /* sem cache */ }
}

async function buscar() {
  const req = new Request(Keychain.get(CHAVE_URL) + "/api/tarefas");
  req.headers = { Authorization: "Bearer " + Keychain.get(CHAVE_TOKEN) };
  req.timeoutInterval = 12;
  const dados = await req.loadJSON();
  const status = req.response && req.response.statusCode;
  if (status === 401) throw new Error("Token recusado");
  if (!dados || dados.ok === false) throw new Error("Jarvis não respondeu");
  gravarCache(dados);
  return { dados, velho: false };
}

function rotuloPrazo(prazo) {
  if (!prazo) return null;
  const hoje = new Date(); hoje.setHours(0, 0, 0, 0);
  const [a, m, d] = prazo.split("-").map(Number);
  const dias = Math.round((new Date(a, m - 1, d) - hoje) / 864e5);
  if (dias < 0) return { texto: "venceu " + d + " " + MESES[m - 1], cor: COR.ruim };
  if (dias === 0) return { texto: "hoje", cor: COR.aviso };
  if (dias === 1) return { texto: "amanhã", cor: COR.mudo };
  return { texto: d + " " + MESES[m - 1], cor: COR.mudo };
}

function limite(familia) {
  return { small: 3, medium: 4, large: 9, extraLarge: 9 }[familia] || 4;
}

function montar(estado, familia) {
  const w = new ListWidget();
  const g = new LinearGradient();
  g.colors = [new Color(COR.fundoA), new Color(COR.fundoB)]; g.locations = [0, 1];
  w.backgroundGradient = g;
  w.setPadding(14, 14, 12, 14);
  w.url = Keychain.get(CHAVE_URL) + "/";

  const topo = w.addStack(); topo.centerAlignContent();
  const t = topo.addText("TAREFAS"); t.font = Font.boldSystemFont(11); t.textColor = new Color(COR.ciano);
  topo.addSpacer();

  if (estado.erro && !estado.dados) {
    w.addSpacer(8);
    const e = w.addText(estado.erro); e.font = Font.systemFont(13); e.textColor = new Color(COR.ruim);
    const dica = w.addText("Confira o Tailscale e o endereço: " + Keychain.get(CHAVE_URL)); dica.font = Font.systemFont(10); dica.textColor = new Color(COR.mudo);
    return w;
  }

  const abertas = (estado.dados && estado.dados.abertas) || [];
  const n = topo.addText(String(abertas.length)); n.font = Font.boldSystemFont(13); n.textColor = new Color(COR.texto);
  w.addSpacer(6);

  if (!abertas.length) {
    const v = w.addText("Nenhuma tarefa aberta"); v.font = Font.systemFont(13); v.textColor = new Color(COR.ok);
  }
  const maximo = limite(familia);
  abertas.slice(0, maximo).forEach(tarefa => {
    const linha = w.addStack(); linha.centerAlignContent(); linha.spacing = 6;
    const r = rotuloPrazo(tarefa.prazo);
    const ponto = linha.addText("●"); ponto.font = Font.systemFont(7);
    ponto.textColor = new Color(r ? r.cor : COR.ciano);
    const txt = linha.addText(tarefa.texto); txt.font = Font.systemFont(familia === "small" ? 12 : 13);
    txt.textColor = new Color(COR.texto); txt.lineLimit = 1;
    if (r && familia !== "small") { linha.addSpacer(); const p = linha.addText(r.texto); p.font = Font.systemFont(11); p.textColor = new Color(r.cor); }
    w.addSpacer(familia === "small" ? 3 : 4);
  });
  if (abertas.length > maximo) {
    const mais = w.addText("+" + (abertas.length - maximo) + " mais"); mais.font = Font.systemFont(11); mais.textColor = new Color(COR.mudo);
  }
  w.addSpacer();
  if (estado.velho) {
    const q = estado.quando ? new Date(estado.quando) : null;
    const hh = q ? q.getHours().toString().padStart(2, "0") + ":" + q.getMinutes().toString().padStart(2, "0") : "";
    const aviso = w.addText("sem conexão" + (hh ? " · dados das " + hh : "")); aviso.font = Font.systemFont(10); aviso.textColor = new Color(COR.aviso);
  }
  return w;
}

async function carregar() {
  try {
    const r = await buscar();
    return { dados: r.dados, velho: false };
  } catch (e) {
    const c = lerCache();
    if (c) return { dados: c.dados, velho: true, quando: c.quando, erro: String(e.message || e) };
    return { dados: null, erro: String(e.message || e) };
  }
}

async function principal() {
  if (config.runsInWidget) {
    if (!(Keychain.contains(CHAVE_URL) && Keychain.contains(CHAVE_TOKEN))) {
      const w = new ListWidget(); w.backgroundColor = new Color(COR.fundoB);
      const t = w.addText("Abra o script no Scriptable e toque em Play para configurar."); t.font = Font.systemFont(12); t.textColor = new Color(COR.texto);
      Script.setWidget(w); Script.complete(); return;
    }
    const estado = await carregar();
    const w = montar(estado, config.widgetFamily);
    w.refreshAfterDate = new Date(Date.now() + 15 * 60 * 1000);
    Script.setWidget(w);
    Script.complete();
    return;
  }
  // Dentro do app: configura (ou troca) e mostra uma prévia
  if (Keychain.contains(CHAVE_URL)) {
    const m = new Alert(); m.title = "Widget de tarefas"; m.message = "Já configurado.";
    m.addAction("Ver prévia"); m.addAction("Trocar endereço e token"); m.addCancelAction("Fechar");
    const r = await m.presentSheet();
    if (r === 1) { if (!(await configurar(true))) return; } else if (r !== 0) return;
  } else if (!(await configurar(false))) return;
  const estado = await carregar();
  const w = montar(estado, "medium");
  await w.presentMedium();
  Script.complete();
}

await principal();
