/* ============================================================
   Arena · Mutante vs. Caçador — painel ao vivo (SSE)
   ============================================================ */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const PAPEIS = ["mutante", "cacador"];
const NOME = { mutante: "Mutante", cacador: "Caçador" };
const ICONE = { mutante: "🧟", cacador: "🏹" };

const MOTIVOS = {
  linha_proibida: "Linha proibida",
  sem_mudanca: "Linha idêntica à original",
  multiplas_linhas: "Mais de uma linha",
  comentario_bloqueado: "Comentário bloqueado (anti-injeção)",
  string_bloqueada: "String bloqueada (anti-injeção)",
  erro_sintaxe: "Erro de sintaxe",
  import_bloqueado: "Import bloqueado",
  codigo_perigoso: "Código perigoso bloqueado",
  argumento_invalido: "Argumento inválido",
  trecho_nao_encontrado: "Trecho não existe no código",
  trecho_ambiguo: "Trecho ambíguo",
  mutante_equivalente: "Mutante equivalente",
  morto_pela_suite: "Morto pela suíte atual",
  expectativa_errada: "Expectativa alucinada",
  nao_detectou: "Não detectou o bug",
  sem_teste: "Nenhuma função test_",
};
// em qual etapa do árbitro cada motivo de rejeição acontece
const ETAPA_FALHA = {
  linha_proibida: "m2", sem_mudanca: "m2", multiplas_linhas: "m2", comentario_bloqueado: "m2",
  string_bloqueada: "m2", erro_sintaxe: "m2", import_bloqueado: "m2", codigo_perigoso: "m2",
  argumento_invalido: "m2", trecho_nao_encontrado: "m2", trecho_ambiguo: "m2", mutante_equivalente: "m3", morto_pela_suite: "m4",
};
const ETAPA_FALHA_C = {
  erro_sintaxe: "c2", import_bloqueado: "c2", codigo_perigoso: "c2", sem_teste: "c2",
  expectativa_errada: "c3", nao_detectou: "c4",
};

const cfg = { codigo: [], editaveis: [], testes_base: "", modelos: [], gravacoes: [] };
let st;              // estado da sessão atual
let relogio = null;  // intervalo do cronômetro
let gravacaoSel = null;

function estadoInicial() {
  return {
    modo: null, modelos: { mutante: "—", cacador: "—" }, rodada: 0, total: 0,
    placar: { mutante: 0, cacador: 0 }, vencedores: [], suite: 1,
    stats: {
      mutante: { tokens: 0, chamadas: 0, erros: 0, toks: [] },
      cacador: { tokens: 0, chamadas: 0, erros: 0, toks: [] },
    },
    linhas: [...cfg.codigo], mutacao: null, testeAtual: null, suiteTestes: [],
    inicio: null, fim: null, vez: null, ferramentas: {},
    evolucao: { defesa: false, ataque: false }, nivelDefesa: 1, nivelAtaque: 1, herdados: [],
  };
}

/* ============================================================ código */
const KW = new Set("def return if elif else for in and or not is None True False while import from as with try except raise lambda pass break continue class yield assert".split(" "));
const BI = new Set("round max min sum len abs range print int float str list dict set".split(" "));
const TOKEN = /("""|'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(#.*)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_]\w*)/g;

function realcar(linha) {
  let out = "", ultimo = 0, m;
  TOKEN.lastIndex = 0;
  while ((m = TOKEN.exec(linha))) {
    out += esc(linha.slice(ultimo, m.index));
    const [tok, str, com, num, id] = m;
    if (str) out += `<span class="s">${esc(tok)}</span>`;
    else if (com) out += `<span class="co">${esc(tok)}</span>`;
    else if (num) out += `<span class="nu">${esc(tok)}</span>`;
    else if (KW.has(id)) out += `<span class="k">${esc(tok)}</span>`;
    else if (BI.has(id)) out += `<span class="bi">${esc(tok)}</span>`;
    else if (linha.slice(m.index + tok.length).startsWith("(")) out += `<span class="f">${esc(tok)}</span>`;
    else out += esc(tok);
    ultimo = m.index + tok.length;
  }
  return out + esc(linha.slice(ultimo));
}

function linhasDocstring(linhas) {
  const doc = new Set();
  let dentro = false;
  linhas.forEach((l, i) => {
    const n = (l.match(/"""/g) || []).length;
    if (dentro || n > 0) doc.add(i + 1);
    if (n % 2 === 1) dentro = !dentro;
  });
  return doc;
}

function renderCodigo() {
  const el = $("#codigo");
  const doc = linhasDocstring(cfg.codigo);
  const mut = st.mutacao;
  let html = "";
  st.linhas.forEach((texto, i) => {
    const n = i + 1;
    if (mut && mut.linha === n) {
      html += `<div class="l fantasma"><span class="n">${n}</span><span class="t">${realcar(mut.antiga)}</span></div>`;
      html += `<div class="l mutada" id="linha-mutada"><span class="n">${n}</span><span class="t">${realcar(mut.nova)}</span></div>`;
      return;
    }
    const cls = ["l", doc.has(n) ? "doc" : "", st.proposta === n ? "proposta" : ""].join(" ");
    html += `<div class="${cls}" data-n="${n}"><span class="n">${n}</span><span class="t">${realcar(texto)}</span></div>`;
  });
  el.innerHTML = html;
}

function rolarPara(seletor, container) {
  const alvo = $(seletor, container);
  if (alvo) container.scrollTo({ top: alvo.offsetTop - container.clientHeight / 2, behavior: "smooth" });
}

function varrer(papel) {
  const el = $("#codigo");
  el.classList.remove("varredura", "por-m", "por-c");
  void el.offsetWidth;
  el.classList.add("varredura", papel === "mutante" ? "por-m" : "por-c");
  setTimeout(() => el.classList.remove("varredura"), 1200);
}

/* ============================================================ testes */
function blocosDeTeste(codigo) {
  // quebra o arquivo em: cabeçalho + um bloco por função test_
  const linhas = codigo.replace(/\r/g, "").split("\n");
  const blocos = [{ nome: null, linhas: [] }];
  for (const l of linhas) {
    const m = l.match(/^def\s+(test\w*)\s*\(/);
    if (m) blocos.push({ nome: m[1], linhas: [] });
    blocos[blocos.length - 1].linhas.push(l);
  }
  return blocos.filter((b) => b.nome || b.linhas.some((l) => l.trim()));
}

function renderTeste(container, codigo, status = {}) {
  let html = "", n = 0;
  for (const b of blocosDeTeste(codigo)) {
    const s = b.nome ? status[b.nome] : null;
    const etiqueta = { valido: "✓ válido", "valido-nao": "válido · não detecta", alucinado: "✗ alucinação" }[s];
    html += `<div class="teste-bloco ${s || ""}">${etiqueta ? `<span class="etiqueta">${etiqueta}</span>` : ""}`;
    for (const l of b.linhas) {
      n++;
      html += `<div class="l"><span class="n">${n}</span><span class="t">${realcar(l)}</span></div>`;
    }
    html += `</div>`;
  }
  container.innerHTML = html;
}

function renderSuite() {
  const el = $("#suite-codigo");
  let html = `<div class="suite-titulo">test_base.py · suíte inicial</div><div id="suite-base"></div>`;
  st.herdados.forEach((t, i) => { html += `<div class="suite-titulo">🛡️ ${esc(t.nome)} · herdado de partida anterior</div><div id="herdado-${i}"></div>`; });
  st.suiteTestes.forEach((t, i) => { html += `<div class="suite-titulo">🏹 ${esc(t.nome)} · matou o mutante da rodada ${t.rodada}</div><div id="suite-${i}"></div>`; });
  el.innerHTML = html;
  renderTeste($("#suite-base"), cfg.testes_base);
  st.herdados.forEach((t, i) => renderTeste($(`#herdado-${i}`), t.codigo));
  st.suiteTestes.forEach((t, i) => renderTeste($(`#suite-${i}`), t.codigo, Object.fromEntries(t.validos.map((v) => [v, "valido"]))));
}

function mostrarAba(nome) {
  $$(".aba").forEach((a) => a.classList.toggle("ativa", a.dataset.aba === nome));
  $$(".aba-conteudo").forEach((c) => c.classList.toggle("ativa", c.id === `aba-${nome}`));
  if (nome === "teste") $("#bolinha-teste").classList.remove("on");
}

/* ============================================================ placar e lutadores */
function renderPlacar() {
  for (const p of PAPEIS) {
    $(`#pontos-${p}`).textContent = st.placar[p];
    $(`#modelo-${p}`).textContent = st.modelos[p] || "—";
    const s = st.stats[p];
    $(`#tokens-${p}`).textContent = s.tokens.toLocaleString("pt-BR");
    $(`#chamadas-${p}`).textContent = s.chamadas;
    $(`#erros-${p}`).textContent = s.erros;
    const media = s.toks.length ? s.toks.reduce((a, b) => a + b, 0) / s.toks.length : 0;
    $(`#tk-${p}`).textContent = media ? media.toFixed(1) : "0";
    const max = Math.max(30, ...s.toks);
    $(`#barras-${p}`).innerHTML = s.toks.slice(-28).map((v) => `<i style="height:${Math.max(8, (v / max) * 100)}%"></i>`).join("");
  }
  const pips = [];
  for (let i = 1; i <= Math.max(st.total, 1); i++) {
    const v = st.vencedores[i - 1];
    const cls = v === "mutante" ? "m" : v === "cacador" ? "c" : i === st.rodada ? "atual" : "";
    pips.push(`<div class="pip ${cls}" title="Rodada ${i}">${v ? ICONE[v] : i}</div>`);
  }
  $("#pips").innerHTML = pips.join("");
  $("#suite-contagem").textContent = st.suite;
  $("#nivel-num").textContent = st.evolucao.defesa ? st.nivelDefesa : "—";
  $("#nivel").classList.toggle("desligado", !st.evolucao.defesa);
  $("#nivel-ataque-num").textContent = st.evolucao.ataque ? st.nivelAtaque : "—";
  $("#nivel-ataque").classList.toggle("desligado", !st.evolucao.ataque);
  $("#rotulo-rodada").textContent = st.rodada ? `RODADA ${st.rodada}/${st.total}` : "—";
}

function vez(papel, estado = "na vez") {
  st.vez = papel;
  for (const p of PAPEIS) {
    const el = $(`#lutador-${p}`);
    el.classList.toggle("ativo", p === papel);
    el.classList.toggle("inativo", !!papel && p !== papel);
    if (p !== papel) { el.classList.remove("pensando"); $(`#estado-${p}`).textContent = papel ? "aguardando a vez" : "aguardando"; }
  }
  if (papel) $(`#estado-${papel}`).textContent = estado;
}

function pensando(papel, sim, texto) {
  $(`#lutador-${papel}`).classList.toggle("pensando", sim);
  if (texto) $(`#estado-${papel}`).textContent = texto;
}

function pontuar(papel) {
  const el = $(`#pontos-${papel}`);
  el.classList.remove("pula"); void el.offsetWidth; el.classList.add("pula");
}

function subirNivel(lado, novo) {
  if (novo == null) return;
  const chave = lado === "defesa" ? "nivelDefesa" : "nivelAtaque";
  if (!st.evolucao[lado] || novo <= st[chave]) { st[chave] = Math.max(st[chave], novo || 1); return; }
  st[chave] = novo;
  const el = lado === "defesa" ? $("#nivel") : $("#nivel-ataque");
  el.classList.remove("sobe"); void el.offsetWidth; el.classList.add("sobe");
  registrar(lado === "defesa" ? "c" : "m", "⬆️", lado === "defesa"
    ? `<b>Defesa sobe para o nível ${novo}</b>: o teste vencedor foi salvo e vale para as próximas partidas`
    : `<b>Ataque sobe para o nível ${novo}</b>: brecha nova descoberta e guardada na memória do Mutante`);
}

function renderFerramentas() {
  for (const p of PAPEIS) {
    const lista = st.ferramentas[p] || [];
    $(`#ferr-${p}`).innerHTML = lista.map((f) => `<span class="ferramenta" data-f="${f}">${f}</span>`).join("");
  }
}

function acender(papel, nome) {
  const el = $(`#ferr-${papel} [data-f="${nome}"]`);
  if (!el) return;
  el.classList.add("acesa");
  setTimeout(() => el.classList.remove("acesa"), 1500);
}

/* ============================================================ mente (stream + feed) */
const streamAtual = { mutante: null, cacador: null };

function novoPasso(papel, passo) {
  const box = $(`#stream-${papel}`);
  box.innerHTML = `<span class="txt"></span><span class="cursor"></span>`;
  streamAtual[papel] = $(".txt", box);
  $(`#passo-${papel}`).textContent = `passo ${passo}`;
}

function anexarStream(papel, texto) {
  if (!streamAtual[papel]) novoPasso(papel, "?");
  const el = streamAtual[papel];
  el.dataset.bruto = (el.dataset.bruto || "") + texto;
  // o modelo escreve código dentro de strings JSON: mostra \n e \" de forma legível
  el.textContent = el.dataset.bruto.replace(/\\n/g, "\n").replace(/\\"/g, '"').replace(/\\t/g, "  ");
  const box = $(`#stream-${papel}`);
  box.scrollTop = box.scrollHeight;
}

function fecharStream(papel, ev) {
  const box = $(`#stream-${papel}`);
  $(".cursor", box)?.remove();
  const origem = { nativa: "tool call nativa", texto_json: "tool call via texto (fallback)", nenhuma: "sem tool call" }[ev.origem];
  box.insertAdjacentHTML("beforeend",
    `<span class="meta"><b>${ev.tokens}</b> tokens · <b>${ev.tok_s}</b> tok/s · ${ev.segundos}s · ${origem}</span>`);
  box.scrollTop = box.scrollHeight;
}

function cartao(papel, { tipo = "acao", nome = "", corpo = "", just = "", selo = null }) {
  const feed = $(`#feed-${papel}`);
  const hora = cronoTexto();
  const classe = tipo === "acao" ? `acao ${papel}-c` : tipo;
  feed.insertAdjacentHTML("beforeend", `
    <div class="cartao ${classe}">
      <div class="cab"><span class="nome">${selo ? `<span class="selo ${selo[0]}">${esc(selo[1])}</span>` : ""}${esc(nome)}</span><span class="quando">${hora}</span></div>
      ${corpo ? `<div class="corpo">${corpo}</div>` : ""}
      ${just ? `<div class="just">“${esc(just)}”</div>` : ""}
    </div>`);
  feed.scrollTop = feed.scrollHeight;
}

/* ============================================================ árbitro */
function etapas(prefixo, estado = "") {
  $$(`.etapa[data-etapa^="${prefixo}"]`).forEach((e) => { e.className = `etapa ${estado}`; });
}
function etapa(id, estado) { const e = $(`.etapa[data-etapa="${id}"]`); if (e) e.className = `etapa ${estado}`; }
function etapasAte(prefixo, ultima, estadoUltima) {
  const ordem = [1, 2, 3, 4].map((i) => `${prefixo}${i}`);
  for (const id of ordem) {
    if (id === ultima) { etapa(id, estadoUltima); break; }
    etapa(id, "ok");
  }
}

/* ============================================================ registro, splash, toasts */
function registrar(classe, icone, html) {
  const ol = $("#registro");
  ol.insertAdjacentHTML("afterbegin", `<li><span class="h">${cronoTexto()}</span><span>${icone}</span><span class="${classe}">${html}</span></li>`);
  while (ol.children.length > 200) ol.lastChild.remove();
}

let filaSplash = [], splashAtivo = false;
function splash(html, fresco = true) {
  if (!fresco) return;
  filaSplash.push(html);
  if (!splashAtivo) proximoSplash();
}
function proximoSplash() {
  const html = filaSplash.shift();
  if (!html) { splashAtivo = false; return; }
  splashAtivo = true;
  $("#splash").innerHTML = `<div class="conteudo">${html}</div>`;
  setTimeout(() => { $("#splash").innerHTML = ""; proximoSplash(); }, 2400);
}

function toast(html, tipo = "info", fresco = true) {
  if (!fresco) return;
  const el = document.createElement("div");
  el.className = `toast ${tipo}`;
  el.innerHTML = html;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 4300);
}

/* ============================================================ cronômetro e status */
function cronoTexto() {
  if (!st?.inicio) return "00:00";
  const s = Math.max(0, Math.floor(((st.fim || Date.now()) - st.inicio) / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
function iniciarRelogio() {
  clearInterval(relogio);
  relogio = setInterval(() => { $("#cronometro").textContent = cronoTexto(); }, 500);
}
function status(texto, classe) {
  const el = $("#status");
  el.textContent = texto;
  el.className = `chip-status ${classe}`;
}

/* ============================================================ sessão */
function resetar() {
  st = estadoInicial();
  filaSplash = []; $("#splash").innerHTML = "";
  for (const p of PAPEIS) {
    $(`#feed-${p}`).innerHTML = "";
    $(`#stream-${p}`).innerHTML = `<div class="vazio">O raciocínio do modelo aparece aqui, token a token.</div>`;
    $(`#passo-${p}`).textContent = "";
    $(`#lutador-${p}`).classList.remove("pensando", "ativo", "inativo");
    $(`#estado-${p}`).textContent = "aguardando";
    streamAtual[p] = null;
  }
  $("#registro").innerHTML = "";
  $("#gabarito").classList.add("oculto");
  $("#teste-codigo").innerHTML = ""; $("#teste-vazio").style.display = "";
  etapas("m"); etapas("c");
  renderCodigo(); renderSuite(); renderPlacar(); renderFerramentas();
  mostrarAba("codigo");
}

/* ============================================================ eventos */
function tratar(ev) {
  const fresco = (Date.now() / 1000 - ev.ts) < 4;  // eventos antigos (recarregou a página) não animam
  const p = ev.papel;

  switch (ev.tipo) {
    case "sessao_inicio":
      resetar();
      st.modo = ev.modo;
      if (ev.modelos) st.modelos = ev.modelos;
      st.inicio = ev.ts * 1000;
      iniciarRelogio();
      status(ev.modo === "replay" ? `REPLAY ${ev.velocidade}×` : "AO VIVO", ev.modo === "replay" ? "replay" : "aovivo");
      $("#btn-parar").disabled = false;
      fecharModais();
      renderPlacar();
      break;

    case "partida_inicio":
      st.modelos = ev.modelos; st.total = ev.rodadas;
      renderPlacar();
      registrar("a", "🏟️", `Partida iniciada · ${ev.rodadas} rodada(s) · ${ev.tentativas} tentativas por turno · limite de ${ev.max_passos} passos`);
      break;

    case "carregando":
      if (st.modo !== "replay") status("CARREGANDO", "carregando");
      registrar("s", "⏳", `Carregando modelo(s) na GPU: ${ev.modelos.map(esc).join(", ")}`);
      break;

    case "progresso":
      st.evolucao = ev.evolucao || { defesa: !!ev.persistir, ataque: false };
      st.nivelDefesa = ev.nivel || 1; st.nivelAtaque = ev.nivel_ataque || 1; st.herdados = ev.herdados || [];
      renderSuite(); renderPlacar();
      registrar("a", "🛡️", st.evolucao.defesa
        ? `Defesa evolui · <b>nível ${st.nivelDefesa}</b> · ${st.herdados.length} teste(s) herdado(s) de ${ev.partidas_anteriores} partida(s)`
        : "Evolução da defesa desligada: a suíte começa só com test_base.py");
      registrar("m", "⚔️", st.evolucao.ataque
        ? `Ataque evolui · <b>nível ${st.nivelAtaque}</b> · o Mutante usa a memória de ataques anteriores`
        : "Evolução do ataque desligada: o Mutante joga sem memória");
      if (st.evolucao.defesa || st.evolucao.ataque)
        toast(`⚔️ Ataque nível <b>${st.evolucao.ataque ? st.nivelAtaque : "—"}</b> · 🛡️ Defesa nível <b>${st.evolucao.defesa ? st.nivelDefesa : "—"}</b>`, "info", fresco);
      break;

    case "memoria":
      if (ev.linhas && ev.linhas.length) {
        cartao("mutante", { tipo: "memoria-c", nome: "📚 memória de ataques", selo: ["info", `ataque nível ${ev.nivel_ataque}`],
          corpo: `<div class="memoria">${esc(ev.linhas.join("\n"))}</div>` });
        registrar("m", "📚", `O Mutante consultou sua memória: ${ev.linhas.filter((l) => l.startsWith("  -")).length} ataque(s) lembrado(s)`);
      } else {
        cartao("mutante", { tipo: "memoria-c", nome: "📚 memória vazia", selo: ["info", "primeira vez"], corpo: "nenhum ataque anterior registrado ainda" });
      }
      break;

    case "mcp_conectado":
      if (st.modo !== "replay") status("AO VIVO", "aovivo");
      st.ferramentas = ev.por_papel;
      renderFerramentas();
      registrar("a", "🔌", `Servidor MCP conectado · ${ev.ferramentas.length} ferramentas expostas: <code>${ev.ferramentas.map(esc).join(", ")}</code>`);
      toast(`🔌 <b>MCP conectado</b><br>${ev.ferramentas.length} ferramentas · cada agente só enxerga as suas`, "info", fresco);
      break;

    case "rodada_inicio":
      st.rodada = ev.rodada; st.total = ev.total; st.suite = ev.testes_na_suite;
      st.linhas = [...cfg.codigo]; st.mutacao = null; st.proposta = null; st.testeAtual = null;
      $("#gabarito").classList.add("oculto");
      $("#teste-codigo").innerHTML = ""; $("#teste-vazio").style.display = "";
      etapas("m"); etapas("c");
      for (const q of PAPEIS) $(`#feed-${q}`).insertAdjacentHTML("beforeend", `<div class="cartao"><div class="cab"><span class="nome">— Rodada ${ev.rodada} —</span></div></div>`);
      renderCodigo(); renderPlacar(); mostrarAba("codigo");
      registrar("a", "🔔", `<b>Rodada ${ev.rodada}</b> · suíte com ${ev.testes_na_suite} arquivo(s) de teste`);
      splash(`<span class="grande a">RODADA ${ev.rodada}</span><div class="menor">🧟 o Mutante ataca primeiro${st.evolucao.ataque || st.evolucao.defesa ? ` · ⚔️ ataque ${st.nivelAtaque} × 🛡️ defesa ${st.nivelDefesa}` : ""}</div>`, fresco);
      break;

    case "turno":
      vez(p, "na vez");
      registrar(p === "mutante" ? "m" : "c", ICONE[p], `Vez do <b>${NOME[p]}</b> (${esc(ev.modelo)})`);
      if (p === "cacador") { etapas("c"); mostrarAba("codigo"); }
      break;

    case "pensando":
      vez(p, "pensando");
      pensando(p, true, "pensando");
      novoPasso(p, ev.passo);
      break;

    case "llm_delta":
      anexarStream(p, ev.texto);
      break;

    case "llm_fim": {
      pensando(p, false, "agindo");
      fecharStream(p, ev);
      const s = st.stats[p];
      s.tokens += ev.tokens || 0; s.chamadas += 1; if (ev.tok_s) s.toks.push(ev.tok_s);
      renderPlacar();
      break;
    }

    case "ferramenta":
      acender(p, ev.nome);
      tratarFerramenta(p, ev, fresco);
      break;

    case "resultado":
      tratarResultado(p, ev, fresco);
      break;

    case "mutante_vivo": {
      st.mutacao = ev; st.proposta = null;
      renderCodigo();
      setTimeout(() => rolarPara("#linha-mutada", $("#codigo")), 50);
      $("#gabarito-linha").innerHTML = `linha ${ev.linha}: <del>${esc(ev.antiga.trim())}</del> → <ins>${esc(ev.nova.trim())}</ins>`;
      $("#gabarito-prova").innerHTML = `🔀 prova do oráculo: <b>${esc(ev.evidencia)}</b>`;
      $("#gabarito").classList.remove("oculto");
      registrar("m", "🧬", `Bug inserido na linha ${ev.linha}: <code>${esc(ev.nova.trim())}</code>`);
      splash(`<span class="emoji">🧬</span><span class="grande m">BUG INSERIDO</span><div class="menor">linha ${ev.linha}: <code>${esc(ev.antiga.trim())}</code> → <code>${esc(ev.nova.trim())}</code></div>`, fresco);
      break;
    }

    case "sem_ferramenta":
      st.stats[p].erros += 1; renderPlacar();
      if (ev.cortada) {
        cartao(p, { tipo: "alerta", nome: "chamada cortada (JSON incompleto)", selo: ["alerta", "protocolo"], corpo: "a resposta estourou o limite de tokens antes de fechar o JSON; o agente será orientado a enviar menos testes" });
        registrar("s", "✂️", `${NOME[p]} tentou chamar uma ferramenta, mas o JSON veio cortado`);
      } else {
        cartao(p, { tipo: "alerta", nome: "respondeu sem chamar ferramenta", selo: ["alerta", "protocolo"], corpo: esc(ev.texto) });
        registrar("s", "⚠️", `${NOME[p]} respondeu em texto livre, sem usar ferramenta`);
      }
      break;

    case "bloqueio":
      st.stats[p].erros += 1; renderPlacar();
      cartao(p, { tipo: "falha", nome: `tentou usar ${ev.nome}`, selo: ["falha", "bloqueado"], corpo: "Ferramenta fora da lista de permissões do seu papel." });
      registrar("a", "⛔", `${NOME[p]} tentou usar <code>${esc(ev.nome)}</code>: bloqueado pela lista de permissões`);
      toast(`⛔ <b>${NOME[p]}</b> tentou usar uma ferramenta proibida`, "falha", fresco);
      break;

    case "limite":
      cartao(p, { tipo: "falha", nome: `limite de ${ev.max_passos} passos`, selo: ["falha", "autonomia"] });
      registrar("a", "⏱️", `${NOME[p]} estourou o limite de autonomia (${ev.max_passos} passos)`);
      break;

    case "rodada_fim": {
      const v = ev.vencedor;
      st.placar = ev.placar; st.vencedores[ev.rodada - 1] = v;
      subirNivel("defesa", ev.nivel_defesa); subirNivel("ataque", ev.nivel_ataque);
      vez(null); renderPlacar(); if (v) pontuar(v);
      registrar(v === "mutante" ? "m" : "c", "🏁", `<b>${NOME[v] || "?"}</b> vence a rodada ${ev.rodada}: ${esc(ev.motivo || "")}`);
      if (v === "cacador") splash(`<span class="emoji">🏹</span><span class="grande c">MUTANTE ABATIDO!</span><div class="menor">${esc(ev.motivo || "")}</div>`, fresco);
      else splash(`<span class="emoji">🧟</span><span class="grande m">MUTANTE SOBREVIVEU!</span><div class="menor">${esc(ev.motivo || "")}</div>`, fresco);
      break;
    }

    case "partida_fim":
      st.fim = Date.now();
      mostrarFinal(ev.resumo, fresco);
      break;

    case "interrompida":
      registrar("s", "■", "Partida interrompida");
      toast("■ Partida interrompida", "info", fresco);
      break;

    case "erro":
      registrar("s", "💥", `Erro: ${esc(ev.mensagem)}`);
      toast(`💥 <b>Erro</b><br>${esc(ev.mensagem)}`, "falha", true);
      break;

    case "sessao_fim":
      st.fim = st.fim || Date.now();
      status("FIM", "fim");
      $("#btn-parar").disabled = true;
      vez(null);
      for (const q of PAPEIS) pensando(q, false);
      break;
  }
}

function tratarFerramenta(p, ev, fresco) {
  const a = ev.argumentos || {};
  if (ev.nome === "ler_codigo") {
    varrer(p);
    cartao(p, { nome: "📖 ler_codigo()", corpo: "lendo <code>descontos.py</code>" });
  } else if (ev.nome === "ler_testes") {
    cartao(p, { nome: "🛡️ ler_testes()", corpo: "lendo a suíte de testes atual" });
  } else if (ev.nome === "propor_mutacao") {
    st.proposta = Number(a.numero_linha) || null;
    renderCodigo();
    if (st.proposta) setTimeout(() => rolarPara(`.l[data-n="${st.proposta}"]`, $("#codigo")), 30);
    etapas("m"); etapa("m1", "ativa");
    cartao(p, {
      nome: "🧬 propor_mutacao()",
      corpo: `linha <b>${esc(a.numero_linha)}</b>: <code>${esc(a.trecho_original)}</code> → <code>${esc(a.trecho_novo)}</code>`,
      just: a.justificativa,
    });
    registrar("m", "🧬", `Mutante propõe na linha ${esc(a.numero_linha)}: <code>${esc(a.trecho_original)}</code> → <code>${esc(a.trecho_novo)}</code>`);
  } else if (ev.nome === "enviar_teste") {
    let codigo = String(a.codigo ?? "");
    // mesmo tratamento do servidor para JSON escapado duas vezes
    if ((codigo.match(/\\n/g) || []).length > (codigo.match(/\n/g) || []).length)
      codigo = codigo.replace(/\\r/g, "").replace(/\\n/g, "\n").replace(/\\t/g, "    ").replace(/\\"/g, '"');
    st.testeAtual = { codigo, rodada: st.rodada };
    $("#teste-vazio").style.display = "none";
    renderTeste($("#teste-codigo"), codigo);
    mostrarAba("teste");
    etapas("c"); etapa("c1", "ativa");
    const n = blocosDeTeste(codigo).filter((b) => b.nome).length;
    cartao(p, { nome: "🧪 enviar_teste()", corpo: `${n} função(ões) de teste`, just: a.justificativa });
    registrar("c", "🧪", `Caçador envia ${n} função(ões) de teste`);
  } else {
    cartao(p, { nome: `🔧 ${esc(ev.nome)}()` });
  }
}

function tratarResultado(p, ev, fresco) {
  const d = ev.dados || {};
  if (ev.nome === "ler_codigo" || ev.nome === "ler_testes") {
    if (ev.repetida) cartao(p, { tipo: "alerta", nome: `releitura de ${ev.nome}`, selo: ["info", "contexto"], corpo: "conteúdo idêntico: não repetido no contexto (economia de tokens)" });
    return;
  }
  if (d.erro && !("aceita" in d) && !("matou" in d)) {
    cartao(p, { tipo: "falha", nome: "erro", selo: ["falha", "erro"], corpo: esc(d.erro) });
    return;
  }

  if (ev.nome === "propor_mutacao") {
    if (d.aceita) {
      etapasAte("m", "m4", "ok");
      cartao(p, { tipo: "ok", nome: "mutação aceita", selo: ["ok", "vivo"], corpo: "sobreviveu à suíte atual: o mutante está vivo" });
    } else {
      st.stats.mutante.erros += 1; renderPlacar();
      const falha = ETAPA_FALHA[d.motivo] || "m2";
      etapasAte("m", falha, "falha");
      st.proposta = null; renderCodigo();
      const rotulo = MOTIVOS[d.motivo] || d.motivo;
      cartao(p, { tipo: "falha", nome: rotulo, selo: ["falha", "rejeitada"], corpo: `${esc(d.detalhe || "")}<br><small>tentativas restantes: ${d.tentativas_restantes ?? "?"}</small>` });
      registrar("a", "⚖️", `Árbitro rejeita a mutação: <b>${esc(rotulo)}</b>`);
      toast(`⚖️ <b>Mutação rejeitada</b><br>${esc(rotulo)}`, "falha", fresco);
    }
  }

  if (ev.nome === "enviar_teste") {
    const status = {};
    (d.funcoes_alucinadas || []).forEach((f) => (status[f] = "alucinado"));
    (d.funcoes_validas || []).forEach((f) => (status[f] = d.matou ? "valido" : "valido-nao"));
    if (st.testeAtual) renderTeste($("#teste-codigo"), st.testeAtual.codigo, status);
    const nAluc = (d.funcoes_alucinadas || []).length;
    const nVal = (d.funcoes_validas || []).length;
    if (nAluc) {
      st.stats.cacador.erros += nAluc; renderPlacar();
      registrar("a", "🧠", `Filtro de alucinação: <b>${nAluc}</b> teste(s) contradizem a especificação e foram descartados`);
    }
    if (d.matou) {
      etapasAte("c", "c4", "ok");
      st.suiteTestes.push({ nome: `test_cacador_r${st.rodada}.py`, rodada: st.rodada, codigo: st.testeAtual?.codigo || "", validos: d.funcoes_validas || [] });
      renderSuite();
      const s = $(".suite"); s.classList.remove("cresce"); void s.offsetWidth; s.classList.add("cresce");
      cartao(p, { tipo: "ok", nome: "mutante abatido!", selo: ["ok", "kill"], corpo: `${nVal} teste(s) válido(s) entram na suíte${nAluc ? ` · ${nAluc} alucinado(s) descartado(s)` : ""}` });
    } else {
      const falha = ETAPA_FALHA_C[d.motivo] || "c2";
      etapasAte("c", falha, "falha");
      const rotulo = MOTIVOS[d.motivo] || d.motivo;
      cartao(p, { tipo: "falha", nome: rotulo, selo: ["falha", "errou"], corpo: `${nVal} válido(s) · ${nAluc} alucinado(s)<br><small>tentativas restantes: ${d.tentativas_restantes ?? "?"}</small>` });
      registrar("a", "⚖️", `Árbitro: <b>${esc(rotulo)}</b> (${nVal} válidos, ${nAluc} alucinados)`);
      toast(`⚖️ <b>${esc(rotulo)}</b><br>${nVal} teste(s) válido(s) · ${nAluc} alucinado(s)`, "falha", fresco);
    }
  }
}

/* ============================================================ tela final */
function mostrarFinal(r, fresco) {
  if (!r) return;
  const pm = r.placar.mutante, pc = r.placar.cacador;
  const venc = pm > pc ? "mutante" : pc > pm ? "cacador" : null;
  $("#final-trofeu").textContent = venc ? ICONE[venc] + "🏆" : "🤝";
  $("#final-titulo").innerHTML = venc ? `<span class="${venc === "mutante" ? "c-m" : "c-c"}">${NOME[venc].toUpperCase()}</span> VENCE A PARTIDA` : "EMPATE";
  $("#final-pm").textContent = pm; $("#final-pc").textContent = pc;
  const ga = (r.nivel_ataque_fim ?? 1) - (r.nivel_ataque_inicio ?? 1), gd = (r.nivel_fim ?? 1) - (r.nivel_inicio ?? 1);
  const evo = $("#final-evolucao");
  if (r.evolucao && (r.evolucao.ataque || r.evolucao.defesa)) {
    evo.innerHTML = ga > gd ? `<span class="c-m">⚔️ O ATAQUE evoluiu mais nesta partida</span> (+${ga} × +${gd})`
      : gd > ga ? `<span class="c-c">🛡️ A DEFESA evoluiu mais nesta partida</span> (+${gd} × +${ga})`
      : `Evolução empatada nesta partida (+${ga} × +${gd})`;
  } else evo.innerHTML = "";
  const min = Math.floor(r.duracao_s / 60), seg = Math.round(r.duracao_s % 60);
  $("#final-destaques").innerHTML = [
    [r.rodadas, "rodadas"],
    [`${min}m${String(seg).padStart(2, "0")}s`, "duração (100% local)"],
    [r.testes_alucinados_descartados, "testes alucinados barrados"],
    [r.evolucao?.ataque ? `${r.nivel_ataque_inicio} → ${r.nivel_ataque_fim}` : "—", "⚔️ nível do ataque"],
    [r.evolucao?.defesa || r.persistir ? `${r.nivel_inicio} → ${r.nivel_fim}` : "—", "🛡️ nível da defesa"],
  ].map(([v, t]) => `<div class="destaque"><b>${esc(v)}</b><span>${t}</span></div>`).join("");
  const m = r.agentes.mutante, c = r.agentes.cacador;
  const linhas = [
    ["Modelo", m.modelo, c.modelo],
    ["Chamadas ao LLM", m.chamadas_llm, c.chamadas_llm],
    ["Tokens gerados", m.tokens_gerados, c.tokens_gerados],
    ["Tokens/s (média)", m.tokens_por_s_medio, c.tokens_por_s_medio],
    ["Tempo pensando (s)", m.segundos_pensando ?? "—", c.segundos_pensando ?? "—"],
    ["Tool calls nativas", m.chamadas_nativas, c.chamadas_nativas],
    ["Tool calls via texto (fallback)", m.chamadas_via_texto_json, c.chamadas_via_texto_json],
    ["Respostas sem ferramenta", m.respostas_sem_ferramenta, c.respostas_sem_ferramenta],
  ];
  $("#final-tabela").innerHTML = `<tr><th>Métrica</th><th style="text-align:right" class="c-m">🧟 Mutante</th><th style="text-align:right" class="c-c">🏹 Caçador</th></tr>` +
    linhas.map(([k, a, b]) => `<tr><td>${k}</td><td>${esc(a)}</td><td>${esc(b)}</td></tr>`).join("");
  const rej = Object.entries(r.rejeicoes_do_arbitro || {}).sort((a, b) => b[1] - a[1])
    .map(([k, v]) => { const [ev, mot] = k.split(":"); return `<li><b>${v}×</b> ${ev.startsWith("mutacao") ? "🧟" : "🏹"} ${esc(MOTIVOS[mot] || mot)}</li>`; }).join("") || "<li>nenhuma</li>";
  const muts = (r.mutacoes_aceitas || []).map((x) => `<li><code>${esc(x)}</code></li>`).join("") || "<li>nenhuma</li>";
  $("#final-listas").innerHTML = `<div><h4>⚖️ Erros barrados pelo árbitro</h4><ul>${rej}</ul></div><div><h4>🧬 Mutações que nasceram</h4><ul>${muts}</ul></div>`;
  setTimeout(() => abrir("#modal-final"), fresco ? 2600 : 0);
}

/* ============================================================ modais e controles */
function abrir(sel) { fecharModais(); $(sel).classList.add("aberto"); }
function fecharModais() { $$(".modal").forEach((m) => m.classList.remove("aberto")); }

function graficoNiveis(hist) {
  // duas linhas: nível do ataque (magenta) e da defesa (ciano) ao fim de cada partida
  const pts = [{ a: 1, d: 1 }, ...hist.map((h) => ({ a: h.nivel_ataque_fim ?? 1, d: h.nivel_fim ?? 1 }))];
  const max = Math.max(2, ...pts.map((p) => Math.max(p.a, p.d)));
  const W = 300, H = 70;
  const px = (i) => 6 + i * ((W - 12) / Math.max(1, pts.length - 1));
  const py = (v) => H - 6 - ((v - 1) / (max - 1)) * (H - 14);
  const linha = (k, cor) => `<polyline fill="none" stroke="${cor}" stroke-width="2.5" stroke-linejoin="round" points="${pts.map((p, i) => `${px(i)},${py(p[k])}`).join(" ")}"/>` +
    pts.map((p, i) => `<circle cx="${px(i)}" cy="${py(p[k])}" r="3" fill="${cor}"><title>${k === "a" ? "ataque" : "defesa"}: nível ${p[k]}</title></circle>`).join("");
  return `<svg class="grafico-niveis" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${linha("d", "var(--c)")}${linha("a", "var(--m)")}</svg>`;
}

function renderProgresso(pr) {
  const caixa = $("#progresso-caixa");
  if (!pr) { caixa.innerHTML = ""; return; }
  const hist = pr.historico || [];
  const ga = (pr.nivel_ataque || 1) - 1, gd = (pr.nivel || 1) - 1;
  const lider = !hist.length ? "" : ga > gd ? `<span class="c-m">⚔️ o ataque está evoluindo mais</span>`
    : gd > ga ? `<span class="c-c">🛡️ a defesa está evoluindo mais</span>` : "empate na evolução";
  const colunas = hist.map((h) => {
    const tot = Math.max(1, h.rodadas || 1);
    const pm = (h.placar?.mutante || 0) / tot * 100, pc = (h.placar?.cacador || 0) / tot * 100;
    return `<div class="col" title="${esc(h.data)} · ⚔️ ${h.nivel_ataque_inicio ?? 1}→${h.nivel_ataque_fim ?? 1} · 🛡️ ${h.nivel_inicio}→${h.nivel_fim} · 🧟 ${h.placar?.mutante} × ${h.placar?.cacador} 🏹"><i class="gm" style="height:${pm}%"></i><i class="gc" style="height:${pc}%"></i></div>`;
  }).join("");
  caixa.innerHTML = `
    <div class="topo-prog"><span><b class="c-m">⚔️ ataque nível ${pr.nivel_ataque || 1}</b> × <b class="c-c">🛡️ defesa nível ${pr.nivel}</b> · ${pr.partidas} partida(s)</span>
      <button class="zerar" id="btn-zerar" ${pr.testes_herdados || pr.partidas || pr.licoes ? "" : "disabled"}>↺ zerar</button></div>
    ${hist.length ? `<div class="quem-evoluiu">${lider}</div>
      ${graficoNiveis(hist)}
      <div class="legenda-prog"><span><i style="background:var(--m)"></i>nível do ataque</span><span><i style="background:var(--c)"></i>nível da defesa</span><span>(por partida)</span></div>
      <div class="grafico-prog">${colunas}</div>
      <div class="legenda-prog"><span><i style="background:var(--m)"></i>rodadas do Mutante</span><span><i style="background:var(--c)"></i>rodadas do Caçador</span></div>`
      : `<div class="sutil pequeno" style="margin-top:6px">Nenhuma partida registrada ainda. A defesa sobe a cada mutante abatido; o ataque sobe a cada brecha descoberta.</div>`}`;
  $("#btn-zerar")?.addEventListener("click", async () => {
    if (!confirm("Apagar a suíte herdada, a memória do Mutante e o histórico? Os dois lados voltam ao nível 1.")) return;
    const r = await fetch("/api/progresso/zerar", { method: "POST" }).then((x) => x.json()).catch(() => null);
    if (r?.ok) { toast(`↺ Progresso zerado (${r.removidos} teste(s) removido(s))`, "info"); renderProgresso(r.progresso); }
  });
}

async function carregarConfig() {
  const r = await fetch("/api/config").then((x) => x.json());
  Object.assign(cfg, r);
  const opts = (sel) => r.modelos.map((m) => `<option ${m === sel ? "selected" : ""}>${esc(m)}</option>`).join("") || `<option>qwen2.5-coder:7b</option>`;
  $("#sel-mutante").innerHTML = opts("qwen2.5-coder:7b");
  $("#sel-cacador").innerHTML = opts("qwen2.5-coder:7b");
  const lista = $("#lista-gravacoes");
  lista.innerHTML = r.gravacoes.map((g, i) => `
    <button class="gravacao ${i === 0 ? "sel" : ""}" data-id="${esc(g.id)}">
      <b>${esc(g.nome)}</b>${g.origem === "exemplos" ? `<span class="tag">EXEMPLO</span>` : ""}
      <div class="det">🧟 ${g.placar?.mutante ?? "?"} × ${g.placar?.cacador ?? "?"} 🏹 · ${g.rodadas} rodada(s) · ${Math.round(g.duracao_s || 0)}s · ${esc(g.modelos?.mutante || "")}</div>
    </button>`).join("") || `<p class="sutil pequeno">Nenhuma gravação ainda. Rode uma partida ao vivo para gerar uma.</p>`;
  renderProgresso(r.progresso);
  gravacaoSel = r.gravacoes[0]?.id || null;
  $("#btn-replay").disabled = !gravacaoSel;
  $$(".gravacao", lista).forEach((b) => b.addEventListener("click", () => {
    $$(".gravacao", lista).forEach((x) => x.classList.remove("sel"));
    b.classList.add("sel"); gravacaoSel = b.dataset.id; $("#btn-replay").disabled = false;
  }));
  return r;
}

async function post(url, corpo) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo || {}) });
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    toast(`💥 ${esc(e.detail || r.statusText)}`, "falha");
    return false;
  }
  return true;
}

function ligarControles() {
  $("#btn-nova").addEventListener("click", async () => { await carregarConfig(); abrir("#modal-inicio"); });
  $("#btn-final-nova").addEventListener("click", async () => { await carregarConfig(); abrir("#modal-inicio"); });
  $("#btn-como").addEventListener("click", () => abrir("#modal-como"));
  $("#btn-parar").addEventListener("click", () => post("/api/parar"));
  $("#btn-tela").addEventListener("click", telaCheia);
  $$("[data-fechar]").forEach((b) => b.addEventListener("click", fecharModais));
  $$(".modal").forEach((m) => m.addEventListener("click", (e) => { if (e.target === m) fecharModais(); }));
  $$(".aba").forEach((a) => a.addEventListener("click", () => mostrarAba(a.dataset.aba)));

  $("#btn-iniciar").addEventListener("click", () => post("/api/partida", {
    rodadas: Number($("#inp-rodadas").value) || 2,
    tentativas: Number($("#inp-tentativas").value) || 3,
    modelo_mutante: $("#sel-mutante").value,
    modelo_cacador: $("#sel-cacador").value,
    evoluir_ataque: $("#chk-evo-ataque").checked,
    evoluir_defesa: $("#chk-evo-defesa").checked,
  }));
  $("#btn-replay").addEventListener("click", () => gravacaoSel && post("/api/replay", {
    id: gravacaoSel, velocidade: Number($("#sel-velocidade").value) || 2,
  }));

  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, select")) return;
    if (e.key === "Escape") fecharModais();
    if (e.key.toLowerCase() === "f") telaCheia();
    if (e.key.toLowerCase() === "n") $("#btn-nova").click();
    if (e.key.toLowerCase() === "c") abrir("#modal-como");
    if (e.key === "1") mostrarAba("codigo");
    if (e.key === "2") mostrarAba("teste");
    if (e.key === "3") mostrarAba("suite");
  });
}

function telaCheia() {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen?.();
}

function conectar() {
  const es = new EventSource("/api/eventos");
  es.onmessage = (m) => {
    try { tratar(JSON.parse(m.data)); } catch (e) { console.error(e, m.data); }
  };
  es.onerror = () => { status("RECONECTANDO", "carregando"); };
  es.onopen = () => { if ($("#status").textContent === "RECONECTANDO") status("AGUARDANDO", "aguardando"); };
}

(async function iniciar() {
  const r = await carregarConfig();
  resetar();
  ligarControles();
  conectar();
  if (!r.ativa) setTimeout(() => { if (!st.modo) abrir("#modal-inicio"); }, 400);
})();
