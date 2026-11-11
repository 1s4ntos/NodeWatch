/* NodeWatch — grafo de transações da conta em foco (um único componente, em SVG).
   O servidor decide o que entra (limites, totais, tipologia e ordem temporal); aqui só se calcula a posição e o desenho. */
(function () {
  'use strict';
  const { h, f, api, consulta, Icone, Aviso, Legenda, Pares, Selo, Vazio, Erro, Carregando, SITUACAO_ALERTA } = window.NW;
  const L = 900, RAIO = 17;
  const MAX_ROTULOS = 16; // acima disso, os valores nas arestas ficam ocultos por legibilidade

  const PAPEL = { foco: 'conta em foco', recebeu: 'recebeu (direta ou indiretamente) da conta em foco',
    enviou: 'enviou (direta ou indiretamente) para a conta em foco' };

  /* Posições conforme a disposição indicada pelo servidor (derivada da tipologia registrada). */
  function posicionar(nos, disposicao) {
    const porNivel = new Map();
    nos.forEach(n => { if (!porNivel.has(n.nivel)) porNivel.set(n.nivel, []); porNivel.get(n.nivel).push(n); });
    porNivel.forEach(lista => lista.sort((a, b) => (b.alertas_relacionados - a.alertas_relacionados) || a.id.localeCompare(b.id)));
    const niveis = Array.from(porNivel.keys()).sort((a, b) => a - b);
    const maior = Math.max.apply(null, niveis.map(n => porNivel.get(n).length));
    const pos = {};
    if (disposicao === 'circular') {
      const ordem = nos.slice().sort((a, b) => (a.tipo === 'foco' ? -1 : b.tipo === 'foco' ? 1 : (a.nivel - b.nivel) || a.id.localeCompare(b.id)));
      const A = Math.max(460, Math.min(900, ordem.length * 44));
      const r = Math.min(L, A) / 2 - 74;
      ordem.forEach((n, i) => {
        const ang = -Math.PI / 2 + (2 * Math.PI * i) / ordem.length;
        pos[n.id] = { x: L / 2 + r * Math.cos(ang) * 1.25, y: A / 2 + r * Math.sin(ang) };
      });
      return { pos, altura: A };
    }
    // leque: os vizinhos diretos formam um arco em torno da conta em foco
    const lado = disposicao === 'leque_saida' ? 1 : disposicao === 'leque_entrada' ? -1 : 0;
    const foco = nos.find(n => n.tipo === 'foco');
    const vizinhos = lado ? (porNivel.get(lado) || []) : [];
    const emLeque = !!foco && vizinhos.length > 2;
    // 62 px por conta: círculo, rótulo e a linha "foco · alerta" sem sobreposição
    const A = Math.max(420, maior * 62 + 70, emLeque ? vizinhos.length * 66 + 90 : 0);
    const margem = 110;
    niveis.forEach((nv, i) => {
      const x = niveis.length === 1 ? L / 2 : margem + (i * (L - 2 * margem)) / (niveis.length - 1);
      const lista = porNivel.get(nv);
      lista.forEach((n, j) => { pos[n.id] = { x, y: ((j + 1) * A) / (lista.length + 1) }; });
    });
    if (emLeque) {
      const c = pos[foco.id];
      const passo = niveis.length > 1 ? (L - 2 * margem) / (niveis.length - 1) : 260;
      vizinhos.forEach((n, j) => {
        const ang = (-70 + (140 * j) / (vizinhos.length - 1)) * Math.PI / 180;
        pos[n.id] = { x: c.x + lado * passo * (0.5 + 0.5 * Math.cos(ang)), y: A / 2 + (A / 2 - 50) * (ang / (70 * Math.PI / 180)) };
      });
    }
    return { pos, altura: A };
  }

  /* Curva de cada aresta: paralelas (moedas diferentes) e sentidos opostos não se sobrepõem. */
  function tracar(arestas, pos) {
    const usados = {};
    return arestas.map(a => {
      const chave = a.origem + '\u0001' + a.destino, oposta = a.destino + '\u0001' + a.origem;
      const j = usados[chave] = (usados[chave] || 0) + 1;
      const temOposta = arestas.some(b => b.origem + '\u0001' + b.destino === oposta);
      const o = pos[a.origem], d = pos[a.destino];
      if (a.origem === a.destino) {
        const k = 34 + 14 * (j - 1);
        return { a, d: 'M ' + (o.x - 9) + ' ' + (o.y - 14) + ' C ' + (o.x - k) + ' ' + (o.y - 44 - k) + ', ' + (o.x + k) + ' ' + (o.y - 44 - k) + ', ' + (o.x + 9) + ' ' + (o.y - 14),
          mx: o.x, my: o.y - 40 - k * 0.72 };
      }
      const dx = d.x - o.x, dy = d.y - o.y, len = Math.hypot(dx, dy) || 1, ux = dx / len, uy = dy / len;
      const curva = (temOposta || j > 1) ? 26 + 24 * (j - 1) : 0;
      const sx = o.x + ux * RAIO, sy = o.y + uy * RAIO, ex = d.x - ux * (RAIO + 3), ey = d.y - uy * (RAIO + 3);
      const cx = (sx + ex) / 2 - uy * curva, cy = (sy + ey) / 2 + ux * curva;
      return { a, d: 'M ' + sx + ' ' + sy + ' Q ' + cx + ' ' + cy + ' ' + ex + ' ' + ey, mx: (sx + 2 * cx + ex) / 4, my: (sy + 2 * cy + ey) / 4 };
    });
  }

  const chaveAresta = a => a.origem + '\u0001' + a.destino + '\u0001' + a.moeda;
  const semOrdem = a => a.ordem === 'sem_ordem' || a.ordem === 'simultanea';
  const rotuloAresta = a => (a.alerta ? '⚠ ' : '') + (a.n > 1 ? f.inteiro(a.n) + ' transações: ' : '') + f.valor(a.total) + ' ' + a.moeda;
  const horarioAresta = a => a.n > 1 && a.primeiro !== a.ultimo ? f.diaHora(a.primeiro) + ' a ' + f.diaHora(a.ultimo) : f.diaHora(a.primeiro);
  const descricaoAresta = a => 'De ' + a.origem + ' (origem) para ' + a.destino + ' (destino): ' +
    (a.n > 1 ? f.inteiro(a.n) + ' transações agrupadas, total ' : '1 transação de ') + f.valor(a.total) + ' ' + a.moeda +
    ', ' + (a.n > 1 && a.primeiro !== a.ultimo ? 'de ' + f.dataHora(a.primeiro) + ' a ' + f.dataHora(a.ultimo) : 'em ' + f.dataHora(a.primeiro)) +
    (a.alerta ? ', ' + f.inteiro(a.alertas) + ' com alerta' : ', sem alerta') + '. ' + a.ordem_texto + '.';

  const ativar = fn => ({ onClick: fn, onKeyDown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn(); } } });

  /* Transações de uma aresta: carregadas só quando a aresta é selecionada. */
  function TransacoesDaAresta({ analiseId, filtros, aresta, total }) {
    const [estado, setEstado] = React.useState({ dados: null, erro: null });
    React.useEffect(() => {
      let vivo = true;
      setEstado({ dados: null, erro: null });
      const fl = Object.assign({}, filtros, { conta_origem: aresta.origem, conta_destino: aresta.destino, moeda: aresta.moeda });
      api('/analises/' + analiseId + '/transacoes' + consulta(fl, { tamanho: 50 }))
        .then(d => { if (vivo) setEstado({ dados: d, erro: null }); }).catch(e => { if (vivo) setEstado({ dados: null, erro: e }); });
      return () => { vivo = false; };
    }, [analiseId, chaveAresta(aresta), JSON.stringify(filtros)]);
    if (estado.erro) return h(Erro, { erro: estado.erro });
    if (!estado.dados) return h(Carregando, { texto: 'Carregando as transações da aresta…' });
    const d = estado.dados;
    return h('div', { className: 'rolagem' }, h('table', null,
      h('caption', null, 'Valores individuais desta aresta, em ordem de horário' + (d.total > d.linhas.length ? ' (primeiras ' + d.linhas.length + ' de ' + f.inteiro(d.total) + ')' : ' (' + f.inteiro(d.total) + ')')),
      h('thead', null, h('tr', null, ['ID de exibição', 'Data e hora', 'Valor pago', 'Moeda', 'Score', 'Alerta'].map(c => h('th', { key: c, scope: 'col' }, c)))),
      h('tbody', null, d.linhas.map(l => h('tr', { key: l.id_exibicao, className: l.alerta ? 'com-alerta' : '' },
        h('td', { className: 'mono' }, f.idExibicao(l.id_exibicao, total)), h('td', null, f.dataHora(l.data_hora)),
        h('td', { className: 'num' }, f.valor(l.valor_pago)), h('td', null, l.moeda_pagamento),
        h('td', { className: 'num' }, l.score), h('td', null, l.alerta ? h('strong', null, '⚠ Sim') : 'Não', ' (faixa ' + window.NW.NOME_FAIXA[l.faixa] + ')'))))));
  }

  function LegendaGrafo({ g }) {
    const lim = g.limites, tip = g.tipologias;
    const item = (desenho, texto) => h('li', null, h('svg', { viewBox: '0 0 48 24', 'aria-hidden': 'true' }, desenho), h('span', null, texto));
    const seta = (classe, marca, extra) => h('g', { className: 'g-aresta ' + classe }, h('path', { className: 'traco', d: 'M 3 12 L 38 12' }, extra || null), h('path', { className: marca, d: 'M 45 12 L 36 7 L 36 17 Z' }));
    return h('div', { className: 'bloco', role: 'group', 'aria-label': 'Legenda do grafo' },
      h('h3', null, h(Icone, { nome: 'legenda' }), 'Legenda do grafo'),
      h('ul', { className: 'legenda-grafo' },
        item(h('g', { className: 'g-no foco' }, h('circle', { className: 'anel', cx: 24, cy: 12, r: 11 }), h('circle', { className: 'corpo', cx: 24, cy: 12, r: 7 })),
          h(React.Fragment, null, h('strong', null, 'Conta em foco'), ': contorno duplo azul e a palavra "foco".')),
        item(h('g', { className: 'g-no' }, h('circle', { className: 'corpo', cx: 24, cy: 12, r: 8 })),
          h(React.Fragment, null, h('strong', null, 'Conta'), ' (vértice): o rótulo é o mesmo "banco-conta" da tabela.')),
        item(h('g', { className: 'g-no alerta' }, h('circle', { className: 'corpo', cx: 24, cy: 12, r: 8 }), h('text', { className: 'marca-alerta', x: 24, y: 16 }, '!')),
          h(React.Fragment, null, h('strong', null, 'Conta ligada a alerta'), ': vermelha, com "!" e a palavra "alerta".')),
        item(seta('', 'm-seta'),
          h(React.Fragment, null, h('strong', null, 'Seta'), ': aponta da conta de ', h('strong', null, 'origem'), ' para a conta de ', h('strong', null, 'destino'), ' do dinheiro.')),
        item(seta('alerta', 'm-seta-alerta'),
          h(React.Fragment, null, h('strong', null, 'Caminho com alerta'), ': vermelho, com "⚠" no rótulo; alguma transação da aresta tem alerta.')),
        item(h('g', { className: 'g-aresta agrupada' }, h('path', { className: 'traco', d: 'M 3 12 L 45 12' })),
          h(React.Fragment, null, h('strong', null, 'Aresta agrupada'), ': traço grosso; reúne transações de mesma origem, destino e moeda e mostra a quantidade e o total.')),
        item(seta('sem-ordem', 'm-seta'),
          h(React.Fragment, null, h('strong', null, 'Traço tracejado'), ': relação do recorte sem ordem temporal confirmada. Não é uma etapa seguinte do dinheiro.')),
        item(seta('na-sequencia', 'm-seta-seq'),
          h(React.Fragment, null, h('strong', null, 'Traço azul brilhante'), ': sequência selecionada, com horários compatíveis.'))),
      h(Legenda, null, h('strong', null, 'Valor, moeda e horário: '), 'cada aresta mostra o valor pago, a moeda de pagamento e o horário (ou o intervalo, se agrupada). Moedas diferentes ficam em arestas separadas e nunca são somadas. Selecione a aresta para ver cada transação.'),
      h(Legenda, null, h('strong', null, 'Ordem no tempo: '), g.ordem_temporal.regra),
      h(Legenda, null, h('strong', null, 'Limites ativos: '), 'até ' + lim.profundidade + ' salto(s) a partir da conta em foco, ' + lim.max_nos + ' vértices e ' + lim.max_arestas +
        ' arestas desenhadas (prioridade: mais perto do foco, depois com alerta, depois mais transações). ' +
        (lim.fronteira_truncada ? 'Havia mais de ' + lim.fronteira_por_salto + ' contas em um salto: só as primeiras foram expandidas, e os totais do salto seguinte são parciais.' : '')),
      h(Legenda, null, h('strong', null, 'Disposição: '), tip.disposicao.nome + '. Tipologia que orientou: ', h('span', { className: 'mono' }, tip.predominante),
        ' (' + tip.origem + '). A tipologia nunca é deduzida pela aparência do grafo.'),
      h(Legenda, null, g.nota_filtros));
  }

  /* Sequências com horários compatíveis: cada passo com origem → destino, valor, moeda e horário. */
  function Sequencias({ ordem, selecionada, aoSelecionar, total }) {
    const c = ordem.contagem, indiretas = c.sequencia + c.simultanea + c.sem_ordem;
    return h('div', { className: 'bloco' },
      h('h3', null, h(Icone, { nome: 'sequencia' }), 'Ordem no tempo'),
      h(Aviso, { tom: indiretas && c.sequencia < indiretas ? 'atencao' : (c.sequencia ? 'ok' : ''), titulo: !indiretas ? 'Só relações diretas' : c.sequencia === indiretas ? 'Horários compatíveis' : c.sequencia ? 'Ordem confirmada só em parte' : 'Sem ordem temporal confirmada', vivo: true },
        h('p', null, ordem.resumo),
        h('p', { className: 'legenda' }, f.plural(c.direta, 'aresta direta', 'arestas diretas') + ' · ' + f.plural(c.sequencia, 'em sequência', 'em sequência') + ' · ' +
          f.plural(c.sem_ordem + c.simultanea, 'sem ordem confirmada', 'sem ordem confirmada') + (c.simultanea ? ' (' + c.simultanea + ' no mesmo minuto)' : ''))),
      ordem.sequencias.length ? h(React.Fragment, null,
        h(Legenda, null, 'Sequências com horários compatíveis (' + ordem.sequencias.length + (ordem.sequencias_total > ordem.sequencias.length ? ' de ' + ordem.sequencias_total : '') + '). Selecione uma para destacá-la no grafo.'),
        h('ol', { className: 'sequencias' }, ordem.sequencias.map((s, i) => h('li', { key: i },
          h('button', { type: 'button', className: 'botao sequencia', 'aria-pressed': selecionada === i, onClick: () => aoSelecionar(selecionada === i ? null : i) },
            h('strong', null, (s.alerta ? '⚠ ' : '') + 'Sequência ' + (i + 1) + ' — ' + f.plural(s.passos.length, 'passo', 'passos') + (s.sentido === 'volta_ao_foco' ? ', volta à conta em foco' : '') + (s.alerta ? ' (tem alerta)' : '')),
            s.passos.map((p, j) => h('span', { key: j, className: 'passo' },
              h('span', { className: 'mono' }, p.origem + ' → ' + p.destino), ' · ' + f.valor(p.valor) + ' ' + p.moeda + ' · ',
              h('span', { className: 'hora' }, f.dataHora(p.data_hora) + ' · ' + f.idExibicao(p.id_exibicao, total) + (p.alerta ? ' · ⚠ alerta' : '')))))))),
        h(Legenda, null, 'Horário compatível não prova que é o mesmo dinheiro: é só a ordem em que as transações aconteceram.')) : null);
  }

  function Grafo({ g, analiseId, filtros, total, profundidade, aoProfundidade, aoFocar, aoFiltrarTabela }) {
    const [sel, setSel] = React.useState(null); // {tipo: 'no' | 'aresta', id}
    const [seq, setSeq] = React.useState(null); // índice da sequência destacada
    const [mostrarValores, setMostrarValores] = React.useState(true);
    React.useEffect(() => { setSel(null); setSeq(null); }, [g]);
    const { pos, altura } = React.useMemo(() => posicionar(g.nos, g.tipologias.disposicao.id), [g]);
    const tracos = React.useMemo(() => tracar(g.arestas, pos), [g, pos]);
    const muitos = g.arestas.length > MAX_ROTULOS;
    const comValores = mostrarValores && !muitos;
    const noSel = sel && sel.tipo === 'no' ? g.nos.find(n => n.id === sel.id) : null;
    const arSel = sel && sel.tipo === 'aresta' ? g.arestas.find(a => chaveAresta(a) === sel.id) : null;
    const naSeq = new Set(seq !== null && g.ordem_temporal.sequencias[seq] ? g.ordem_temporal.sequencias[seq].passos.map(chaveAresta) : []);
    const destacados = new Set();
    if (noSel) { destacados.add(noSel.id); g.arestas.forEach(a => { if (a.origem === noSel.id || a.destino === noSel.id) { destacados.add(a.origem); destacados.add(a.destino); } }); }
    if (arSel) { destacados.add(arSel.origem); destacados.add(arSel.destino); }
    if (naSeq.size) g.arestas.forEach(a => { if (naSeq.has(chaveAresta(a))) { destacados.add(a.origem); destacados.add(a.destino); } });
    const haDestaque = !!sel || naSeq.size > 0;
    const arestaDestacada = a => naSeq.size ? naSeq.has(chaveAresta(a)) : (!sel || (arSel ? chaveAresta(a) === sel.id : (a.origem === sel.id || a.destino === sel.id)));
    const selecionar = s => { setSeq(null); setSel(s); };
    const t = g.totais, tip = g.tipologias;
    const filtrosSemContas = Object.assign({}, filtros, { conta_origem: '', conta_destino: '' });

    return h('div', { className: 'grade' },
      h('div', { className: 'linha', style: { justifyContent: 'space-between' } },
        h('p', null, h('strong', null, 'Conta em foco: '), h('span', { className: 'mono' }, g.foco), g.escolha ? h('span', { className: 'suave' }, ' (' + g.escolha + ')') : null),
        h('div', { className: 'linha' },
          h('label', { htmlFor: 'grafo-saltos', style: { margin: 0 } }, 'Saltos a partir do foco'),
          h('select', { id: 'grafo-saltos', style: { width: 'auto' }, value: profundidade, onChange: e => aoProfundidade(+e.target.value) },
            Array.from({ length: g.limites.profundidade_max }, (_, i) => h('option', { key: i + 1, value: i + 1 }, i + 1))),
          h('label', { style: { margin: 0, fontWeight: 400 } },
            h('input', { type: 'checkbox', checked: comValores, disabled: muitos, onChange: e => setMostrarValores(e.target.checked) }), ' Valores e horários nas arestas'))),
      muitos ? h(Legenda, null, 'Há ' + g.arestas.length + ' arestas: valores e horários ficam ocultos por legibilidade. Selecione uma aresta, ou use a lista abaixo, para ver valor, moeda, horário e transações.') : null,
      h('div', { className: 'kpis' },
        h('div', { className: 'kpi' }, h('div', { className: 'nome' }, 'Vértices e arestas desenhados'),
          h('div', { className: 'valor menor' }, f.inteiro(t.vertices) + ' vértices · ' + f.inteiro(t.arestas) + ' arestas'),
          h(Legenda, null, 'De ' + f.inteiro(t.contas_relacionadas) + ' contas e ' + f.inteiro(t.arestas_relacionadas) + ' arestas relacionadas.')),
        h('div', { className: 'kpi' }, h('div', { className: 'nome' }, 'Transações exibidas'),
          h('div', { className: 'valor menor' }, 'exibindo ' + f.inteiro(t.exibidas) + ' de ' + f.inteiro(t.relacionadas) + ' transações relacionadas'),
          h(Legenda, null, 'Relacionadas: enviadas ou recebidas pela conta em foco e pelas contas ligadas a ela, até o limite de saltos. ' + f.inteiro(t.alertas_relacionadas) + ' com alerta.')),
        h('div', { className: 'kpi' }, h('div', { className: 'nome' }, 'Transações analisadas no recorte'),
          h('div', { className: 'valor menor' }, f.inteiro(t.transacoes_recorte)),
          h(Legenda, null, 'Transações que passam pelos filtros (sem os de conta).')),
        h('div', { className: 'kpi' }, h('div', { className: 'nome' }, 'Valor total transferido, por moeda'),
          h('ul', null, t.por_moeda.slice(0, 6).map(m => h('li', { key: m.moeda }, h('strong', null, f.valor(m.total) + ' ' + m.moeda), h('span', { className: 'suave' }, ' em ' + f.plural(m.n, 'transação', 'transações'))))),
          t.por_moeda.length > 6 ? h(Legenda, null, 'e mais ' + (t.por_moeda.length - 6) + ' moeda(s).') : null,
          h(Legenda, null, 'Soma de todas as transações relacionadas do recorte, não só das desenhadas. Moedas não são somadas entre si.'))),
      h('div', { className: 'grafo-moldura' },
        h('svg', { viewBox: '0 -48 ' + L + ' ' + (altura + 48), role: 'group',  // folga no topo para os laços de autotransferência
          'aria-label': 'Grafo de transações da conta ' + g.foco + ': ' + t.vertices + ' contas e ' + t.arestas + ' arestas. As setas vão da origem para o destino. ' + g.ordem_temporal.resumo },
          h('defs', null, [['seta', 'm-seta'], ['seta-alerta', 'm-seta-alerta'], ['seta-seq', 'm-seta-seq']].map(([id, classe]) =>
            h('marker', { key: id, id, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 9, markerHeight: 9, orient: 'auto-start-reverse', markerUnits: 'userSpaceOnUse' }, h('path', { className: classe, d: 'M 0 0 L 10 5 L 0 10 z' })))),
          tracos.map(tr => {
            const a = tr.a, k = chaveAresta(a), selecionada = arSel && k === sel.id, emSeq = naSeq.has(k);
            return h('g', Object.assign({ key: k, className: 'g-aresta' + (a.alerta ? ' alerta' : '') + (a.agrupada ? ' agrupada' : '') + (semOrdem(a) ? ' sem-ordem' : '') + (emSeq ? ' na-sequencia' : '') +
              (selecionada ? ' selecionada' : '') + (arestaDestacada(a) ? '' : ' apagada'),
              tabIndex: 0, role: 'button', 'aria-pressed': !!selecionada, 'aria-label': descricaoAresta(a) }, ativar(() => selecionar(selecionada ? null : { tipo: 'aresta', id: k }))),
              h('path', { className: 'alvo', d: tr.d }),
              h('path', { className: 'traco', d: tr.d, markerEnd: 'url(#' + (emSeq ? 'seta-seq' : a.alerta ? 'seta-alerta' : 'seta') + ')' }),
              (comValores || selecionada || emSeq) ? h('text', { x: tr.mx, y: tr.my - 9, textAnchor: 'middle' },
                h('tspan', { x: tr.mx }, rotuloAresta(a)), h('tspan', { className: 'hora', x: tr.mx, dy: 12 }, horarioAresta(a) + (semOrdem(a) ? ' · sem ordem confirmada' : ''))) : null);
          }),
          g.nos.map(n => {
            const p = pos[n.id], selecionado = noSel && n.id === sel.id;
            return h('g', Object.assign({ key: n.id, className: 'g-no ' + (n.tipo === 'foco' ? 'foco' : '') + (n.alerta ? ' alerta' : '') + (selecionado ? ' selecionado' : '') + (haDestaque && !destacados.has(n.id) ? ' apagado' : ''),
              transform: 'translate(' + p.x + ' ' + p.y + ')', tabIndex: 0, role: 'button', 'aria-pressed': !!selecionado,
              'aria-label': 'Conta ' + n.id + ', ' + PAPEL[n.tipo] + (n.alerta ? ', ligada a ' + n.alertas_relacionados + ' transações com alerta' : ', sem alerta') },
              ativar(() => selecionar(selecionado ? null : { tipo: 'no', id: n.id }))),
              n.tipo === 'foco' ? h('circle', { className: 'anel', r: RAIO + 5 }) : null,
              h('circle', { className: 'corpo', r: RAIO }),
              n.alerta ? h('text', { className: 'marca-alerta', y: 5, style: { fontSize: '15px' } }, '!') : null,
              h('text', { y: RAIO + 14 + (n.tipo === 'foco' ? 4 : 0) }, n.rotulo),
              h('text', { y: RAIO + 26 + (n.tipo === 'foco' ? 4 : 0) },
                n.tipo === 'foco' ? h('tspan', { className: 'marca-foco' }, 'foco') : null, n.tipo === 'foco' && n.alerta ? ' · ' : null,
                n.alerta ? h('tspan', { className: 'marca-alerta' }, 'alerta') : null));
          }))),
      h('div', { className: 'grade duas' },
        h(Sequencias, { ordem: g.ordem_temporal, selecionada: seq, aoSelecionar: i => { setSel(null); setSeq(i); }, total }),
        h('div', { className: 'bloco', 'aria-live': 'polite' },
          h('h3', null, h(Icone, { nome: 'info' }), 'Seleção no grafo'),
          !sel ? h(Legenda, null, 'Selecione uma conta (vértice) ou uma aresta para destacar as conexões e ver os detalhes. Teclado: Tab percorre arestas e contas; Enter seleciona.') : null,
          noSel ? h(React.Fragment, null,
            h(Pares, { itens: [['Conta (completa)', h('span', { className: 'mono' }, noSel.id)], ['Banco', noSel.banco], ['Número da conta', noSel.conta],
              ['Papel no grafo', PAPEL[noSel.tipo]], ['Transações relacionadas com alerta', noSel.alerta ? h(Selo, { tom: 'alerta' }, '⚠ ' + f.inteiro(noSel.alertas_relacionados)) : 'nenhuma']] }),
            h('div', { className: 'linha', style: { marginTop: 8 } },
              h('button', { type: 'button', className: 'botao pequeno', onClick: () => aoFiltrarTabela({ conta_origem: noSel.id, conta_destino: '' }) }, 'Filtrar tabela: esta conta como origem'),
              h('button', { type: 'button', className: 'botao pequeno', onClick: () => aoFiltrarTabela({ conta_origem: '', conta_destino: noSel.id }) }, 'Filtrar tabela: esta conta como destino'),
              noSel.tipo !== 'foco' ? h('button', { type: 'button', className: 'botao pequeno', onClick: () => aoFocar(noSel.id) }, 'Colocar esta conta em foco') : null)) : null,
          arSel ? h(React.Fragment, null,
            h(Pares, { itens: [['Origem', h('span', { className: 'mono' }, arSel.origem)], ['Destino', h('span', { className: 'mono' }, arSel.destino)],
              ['Moeda', arSel.moeda], ['Transações', f.inteiro(arSel.n) + (arSel.agrupada ? ' (agrupadas)' : '')], ['Valor total', f.valor(arSel.total) + ' ' + arSel.moeda],
              ['Com alerta', arSel.alerta ? h(Selo, { tom: 'alerta' }, '⚠ ' + f.inteiro(arSel.alertas)) : 'nenhuma'], ['Maior score', arSel.maior_score],
              ['Primeira e última', f.dataHora(arSel.primeiro) + ' — ' + f.dataHora(arSel.ultimo)],
              ['Ordem no tempo', h(Selo, { tom: semOrdem(arSel) ? 'atencao' : arSel.ordem === 'sequencia' ? 'ok' : '' }, arSel.ordem_texto)],
              arSel.passo && arSel.ordem === 'sequencia' ? ['Transação que confirma a sequência', f.idExibicao(arSel.passo.id_exibicao, total) + ' em ' + f.dataHora(arSel.passo.data_hora) + ', ' + f.valor(arSel.passo.valor) + ' ' + arSel.moeda] : null,
              ['Tipologias registradas', arSel.tipologias.length ? arSel.tipologias.join(', ') : (tip.disponivel ? 'padrao_nao_identificado' : 'o dataset não tem tipologias')]] }),
            h('div', { className: 'linha', style: { margin: '8px 0' } },
              h('button', { type: 'button', className: 'botao pequeno', onClick: () => aoFiltrarTabela({ conta_origem: arSel.origem, conta_destino: arSel.destino, moeda: arSel.moeda }) }, 'Ver estas transações na tabela')),
            h(TransacoesDaAresta, { analiseId, filtros: filtrosSemContas, aresta: arSel, total })) : null)),
      h(LegendaGrafo, { g }),
      h('details', null, h('summary', null, 'Lista das ' + g.arestas.length + ' arestas desenhadas (alternativa em texto ao grafo)'),
        h('div', { className: 'rolagem' }, h('table', null,
          h('thead', null, h('tr', null, ['Origem', 'Destino', 'Transações', 'Valor total', 'Moeda', 'Horário', 'Ordem no tempo', 'Com alerta', 'Ação'].map((c, i) => h('th', { key: i, scope: 'col' }, c)))),
          h('tbody', null, g.arestas.map(a => h('tr', { key: chaveAresta(a), className: a.alerta ? 'com-alerta' : '' },
            h('td', { className: 'mono' }, a.origem), h('td', { className: 'mono' }, a.destino), h('td', { className: 'num' }, f.inteiro(a.n)),
            h('td', { className: 'num' }, f.valor(a.total)), h('td', null, a.moeda), h('td', null, horarioAresta(a)), h('td', { style: { whiteSpace: 'normal' } }, a.ordem_texto),
            h('td', null, a.alerta ? h('strong', null, '⚠ Sim (' + a.alertas + ')') : 'Não'),
            h('td', null, h('button', { type: 'button', className: 'botao pequeno', onClick: () => selecionar({ tipo: 'aresta', id: chaveAresta(a) }),
              'aria-label': 'Selecionar a aresta de ' + a.origem + ' para ' + a.destino + ' em ' + a.moeda }, 'Selecionar')))))))),
      tip.disponivel && Object.keys(tip.contagem).length ? h(Legenda, null, h('strong', null, 'Tipologias registradas entre as transações relacionadas: '),
        Object.entries(tip.contagem).map(([k, v]) => k + ' (' + f.inteiro(v) + ')').join(', ') + '.') : null);
  }

  /* Estados do bloco do grafo: sem foco, ambíguo, vazio, erro ou o grafo em si. */
  function BlocoGrafo(props) {
    const { carga } = props;
    if (carga.erro) return h(Erro, { erro: carga.erro });
    if (!carga.dados) return carga.carregando ? h(Carregando, { texto: 'Montando o grafo…' }) : h(Vazio, null, 'Nenhuma conta em foco.');
    const g = carga.dados;
    if (g.ambiguo) return h(Vazio, null, h('p', null, g.motivo),
      h('div', { className: 'linha', style: { marginTop: 8 } }, g.candidatas.map(c => h('button', { key: c, type: 'button', className: 'botao pequeno mono', onClick: () => props.aoFocar(c) }, c))));
    if (g.sem_foco) return h(Vazio, null, g.motivo);
    if (g.vazio) return h(Vazio, null, h('p', null, h('strong', null, 'Conta em foco: '), h('span', { className: 'mono' }, g.foco)), h('p', null, g.motivo));
    return h(Grafo, Object.assign({ g }, props));
  }

  window.NW.BlocoGrafo = BlocoGrafo;
  window.NW.grafo = { posicionar, tracar, rotuloAresta, chaveAresta };
})();
