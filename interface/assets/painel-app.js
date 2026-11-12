/* NodeWatch — painel do analista: estado da página e fluxo principal (uma única página).
   Abrir a página só consulta o servidor e abre a sessão da interface; nenhuma análise começa sem o clique em Analisar. */
(function () {
  'use strict';
  const { h, f, api, consulta, useCarga, useIntervalo, useSessao, sessao, FILTROS_VAZIOS, Icone, Erro, Carregando, Vazio, Selo,
    SecaoDataset, SecaoFiltros, SecaoVisao, SecaoInvestigacao, SecaoTabela, DialogoDetalhes, PainelLateral, DialogoLegenda, Assistente,
    NOME_STATUS, TOM_STATUS } = window.NW;

  const TABELA_PADRAO = { pagina: 1, tamanho: 50, ordenar: 'id_exibicao', direcao: 'asc' };
  /* Filtros iniciais: o valor mínimo começa em 1 unidade da moeda de cada transação (sem conversão entre moedas).
     A visão geral informa quantas transações ficam fora por causa dele; apagar o campo inclui as de valor menor. */
  const filtrosIniciais = est => Object.assign({}, FILTROS_VAZIOS, { valor_min: String((est && est.valor_minimo_padrao) || 1) });
  /* O endereço guarda a análise aberta e a conta em foco (#analise=…&conta=…), para recarregar ou compartilhar a tela. */
  const analiseDoEndereco = () => { const m = /analise=([\w-]+)/.exec(location.hash); return m ? m[1] : ''; };
  const contaDoEndereco = () => { const m = /conta=([^&]+)/.exec(location.hash); try { return m ? decodeURIComponent(m[1]) : ''; } catch (e) { return ''; } };
  const irPara = id => { const el = document.getElementById(id); if (el) { el.scrollIntoView({ block: 'start' }); const t = document.getElementById(id + '-t'); if (t) { t.tabIndex = -1; t.focus({ preventScroll: true }); } } };

  /* Situação da sessão da interface, sempre com texto (nunca só a cor). */
  function SeloSessao() {
    const s = useSessao();
    const janela = s.politica ? Math.round(s.politica.ttl_s) : null;
    const dica = janela ? 'Enviar, validar e analisar exigem a sessão desta página. Sem sinal da aba por ' + janela + ' s, ela expira e a análise para num ponto seguro.' : '';
    if (s.estado === 'ativa') return h('span', { role: 'status', title: dica }, h(Selo, { tom: 'ok', vivo: true }, 'Sessão ativa'));
    if (s.estado === 'sem_servidor') return h('span', { role: 'status', title: dica }, h(Selo, { tom: 'alerta' }, '⚠ Sem conexão com o servidor'));
    return h('span', { role: 'status', title: dica }, h(Selo, { tom: 'atencao' }, s.estado === 'expirada' ? 'Sessão expirada: abrindo outra…' : 'Abrindo a sessão…'));
  }

  function App() {
    const [versaoEstado, setVersaoEstado] = React.useState(0);
    const estado = useCarga('/estado', versaoEstado);
    const [datasets, setDatasets] = React.useState([]);
    const [datasetId, setDatasetId] = React.useState('');
    const [dataset, setDataset] = React.useState(null);
    const [analises, setAnalises] = React.useState({ analises: [], retencao: { leitura: '' } });
    const [analiseId, setAnaliseId] = React.useState(analiseDoEndereco);
    const [manifesto, setManifesto] = React.useState(null);
    const [erroAnalise, setErroAnalise] = React.useState(null);
    const [rascunho, setRascunho] = React.useState(() => filtrosIniciais(null));
    const [aplicados, setAplicados] = React.useState(() => filtrosIniciais(null));
    const [tabela, setTabela] = React.useState(TABELA_PADRAO);
    const [focoPedido, setFocoPedido] = React.useState(contaDoEndereco);
    const [profundidade, setProfundidade] = React.useState(2);
    const [detalheId, setDetalheId] = React.useState(null);
    const [lateral, setLateral] = React.useState(false);
    const [legenda, setLegenda] = React.useState(false);
    const iniciais = filtrosIniciais(estado.dados);

    const carregarDatasets = () => api('/datasets').then(d => setDatasets(d.datasets)).catch(() => {});
    const carregarAnalises = () => api('/analises').then(setAnalises).catch(() => {});
    React.useEffect(() => { carregarDatasets(); carregarAnalises(); }, []);

    /* Dataset escolhido: acompanha a validação enquanto ela roda no servidor. */
    const lerDataset = () => { if (!datasetId) return; api('/datasets/' + datasetId).then(setDataset).catch(() => setDataset(null)); };
    React.useEffect(() => { setDataset(null); lerDataset(); }, [datasetId]);
    const validando = !!dataset && dataset.status === 'validando';
    useIntervalo(lerDataset, 700, validando);
    React.useEffect(() => { if (dataset && !validando) carregarDatasets(); }, [validando, dataset && dataset.status]);

    /* Análise aberta: acompanha o manifesto enquanto estiver em andamento (consulta: não inicia nem retoma nada). */
    const lerManifesto = () => {
      if (!analiseId) return;
      api('/analises/' + analiseId).then(m => { setManifesto(m); setErroAnalise(null); })
        .catch(e => { setManifesto(null); setErroAnalise(e); setAnaliseId(''); });
    };
    React.useEffect(() => { setManifesto(null); lerManifesto(); }, [analiseId]);
    React.useEffect(() => { if (analiseId) history.replaceState(null, '', '#analise=' + analiseId + (focoPedido ? '&conta=' + encodeURIComponent(focoPedido) : '')); }, [analiseId, focoPedido]);
    const emAndamento = !!manifesto && manifesto.status === 'em_andamento';
    useIntervalo(lerManifesto, 1000, emAndamento);
    React.useEffect(() => { if (manifesto && !emAndamento) { carregarAnalises(); setVersaoEstado(v => v + 1); } }, [emAndamento, manifesto && manifesto.id]);
    /* Ao abrir a página com uma análise já em andamento no servidor, mostra o progresso dela (não inicia nada). */
    React.useEffect(() => { if (!analiseId && estado.dados && estado.dados.analise_em_andamento) setAnaliseId(estado.dados.analise_em_andamento); }, [estado.dados]);

    const reiniciarRecorte = () => { setRascunho(iniciais); setAplicados(iniciais); setTabela(TABELA_PADRAO); setFocoPedido(''); setDetalheId(null); };
    const analisar = async did => {
      setErroAnalise(null);
      try { const m = await api('/analises', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dataset_id: did }) });
        reiniciarRecorte(); setManifesto(m); setAnaliseId(m.id); setVersaoEstado(v => v + 1); }
      catch (e) { setErroAnalise(e); }
    };
    const cancelar = () => api('/analises/' + analiseId + '/cancelar', { method: 'POST' }).then(setManifesto).catch(setErroAnalise);
    const assumir = () => api('/analises/' + analiseId + '/assumir', { method: 'POST' }).then(setManifesto).catch(setErroAnalise);
    const abrir = id => { reiniciarRecorte(); setErroAnalise(null); setAnaliseId(id); };

    const temResultados = !!manifesto && !emAndamento && manifesto.resultados.disponiveis;
    const base = temResultados ? '/analises/' + manifesto.id : null;
    const visao = useCarga(base ? base + '/visao' + consulta(aplicados) : null);
    const pagina = useCarga(base ? base + '/transacoes' + consulta(aplicados, tabela) : null);
    const grafo = useCarga(base ? base + '/grafo' + consulta(aplicados, { conta: focoPedido, profundidade }) : null);
    const erroFiltro = [visao.erro, pagina.erro, grafo.erro].find(e => e && e.campo) || null;

    const aplicar = () => {
      if (rascunho.conta_origem !== aplicados.conta_origem || rascunho.conta_destino !== aplicados.conta_destino) setFocoPedido('');
      setAplicados(rascunho); setTabela(Object.assign({}, tabela, { pagina: 1 }));
    };
    const limpar = () => { setRascunho(iniciais); setAplicados(iniciais); setTabela(Object.assign({}, tabela, { pagina: 1 })); setFocoPedido(''); };
    const filtrarTabela = parcial => {
      const novo = Object.assign({}, aplicados, parcial);
      setRascunho(novo); setAplicados(novo); setFocoPedido(''); setTabela(Object.assign({}, tabela, { pagina: 1 }));
      setTimeout(() => irPara('tabela'), 60);
    };
    const focar = conta => { setFocoPedido(conta); setTimeout(() => irPara('investigacao'), 60); };

    if (estado.erro && !estado.dados) return h('main', { id: 'conteudo' }, h(Erro, { erro: estado.erro }));
    if (!estado.dados) return h('main', { id: 'conteudo' }, h(Carregando, { texto: 'Abrindo o painel…' }));
    const est = estado.dados;
    const total = manifesto ? manifesto.contagens.pontuadas : 0;

    return h(React.Fragment, null,
      h('header', { className: 'topo' },
        h('button', { type: 'button', className: 'botao hamburguer', 'aria-expanded': lateral, 'aria-controls': 'painel-operacional',
          'aria-label': lateral ? 'Fechar o painel operacional' : 'Abrir o painel operacional (desempenho, logs e métricas)', onClick: () => setLateral(!lateral) }, h(Icone, { nome: 'menu' })),
        h('div', { className: 'marca' },
          h('img', { className: 'logo', src: 'assets/nodewatch-logo.png', alt: 'NodeWatch', width: 146, height: 40 }),
          h('img', { className: 'logo-simbolo', src: 'assets/nodewatch-simbolo.png', alt: 'NodeWatch', width: 38, height: 38 }),
          h('h1', null, 'Painel do analista', h('small', null, 'Prevenção à lavagem de dinheiro'))),
        h('div', { className: 'estado-analise', role: 'status' }, manifesto ? h(React.Fragment, null, h('span', { className: 'suave' }, 'Análise: '), h('strong', null, manifesto.dataset.nome), ' ',
          h(Selo, { tom: TOM_STATUS[manifesto.status] }, NOME_STATUS[manifesto.status])) : h('span', { className: 'suave' }, 'Nenhuma análise aberta')),
        h('div', { className: 'acoes' }, h(SeloSessao),
          h('button', { type: 'button', className: 'botao', onClick: () => setLegenda(true), 'aria-haspopup': 'dialog' }, h(Icone, { nome: 'legenda' }), h('span', { className: 'rotulo-botao' }, 'Legenda')),
          /* no topo fixo, o botão do assistente não cobre linhas nem controles; o painel abre logo abaixo do topo */
          h(Assistente, { analiseId: manifesto ? manifesto.id : '', filtros: aplicados, estado: est }))),
      h(PainelLateral, { aberto: lateral, aoFechar: () => { setLateral(false); const b = document.querySelector('.hamburguer'); if (b) b.focus(); }, analiseId: manifesto ? manifesto.id : '' }),
      h('main', { id: 'conteudo' },
        h(SecaoDataset, { estado: est, datasets, dataset, datasetId, aoEscolher: (id, forcar) => { if (forcar && id === datasetId) lerDataset(); else setDatasetId(id); }, aoRecarregar: carregarDatasets,
          manifesto, aoAnalisar: analisar, aoCancelar: cancelar, aoAssumir: assumir, analises, aoAbrir: abrir, analiseId: manifesto ? manifesto.id : '', erroAnalise }),
        temResultados ? h(React.Fragment, null,
          h(SecaoFiltros, { rascunho, setRascunho, aplicados, aoAplicar: aplicar, aoLimpar: limpar, moedas: manifesto.contagens.moedas || [], erro: erroFiltro }),
          h(SecaoVisao, { carga: visao, manifesto, estado: est }),
          h(SecaoInvestigacao, { visao, focoPedido, aoFocar: focar, cargaGrafo: grafo, analiseId: manifesto.id, filtros: aplicados, total, profundidade, aoProfundidade: setProfundidade, aoFiltrarTabela: filtrarTabela }),
          h(SecaoTabela, { carga: pagina, manifesto, tabela, setTabela, aoDetalhe: setDetalheId, selecionada: detalheId }),
          h(DialogoDetalhes, { analiseId: manifesto.id, id: detalheId, total, aoFechar: () => setDetalheId(null), aoFiltrarTabela: filtrarTabela, aoFocar: focar })) :
          h('section', { className: 'secao' }, h('div', { className: 'corpo' }, h(Vazio, null,
            emAndamento ? 'Os indicadores, as contas, o grafo e a tabela aparecem quando a análise terminar (ou for interrompida com transações já pontuadas).'
              : manifesto ? 'Esta análise não tem resultados gravados. Abra outra em Análises recentes ou inicie uma nova.'
                : 'Envie ou escolha um dataset e clique em Analisar, ou abra uma análise em Análises recentes. Os indicadores, as contas, o grafo e a tabela aparecem aqui.')))),
      h(DialogoLegenda, { aberto: legenda, aoFechar: () => setLegenda(false), estado: est }));
  }

  /* "Ir para o conteúdo": leva o foco ao conteúdo sem trocar o endereço (que guarda a análise aberta). */
  const pular = document.querySelector('.pular');
  if (pular) pular.addEventListener('click', ev => { ev.preventDefault(); const m = document.getElementById('conteudo'); if (m) { m.tabIndex = -1; m.focus(); m.scrollIntoView(); } });

  /* Aberto direto do disco (file://), o painel não alcança a API: em vez de "servidor indisponível", diz como abrir. */
  function AbertoComoArquivo() {
    return h('main', { id: 'conteudo' }, h('section', { className: 'secao' }, h('div', { className: 'corpo' },
      h(window.NW.Aviso, { tom: 'atencao', titulo: 'O painel não abre como arquivo do computador' },
        h('p', null, 'Ele precisa do servidor local do NodeWatch. Na pasta do projeto, rode ', h('code', { className: 'mono' }, 'python src/sentinel_ai.py'),
          ' e abra ', h('strong', { className: 'mono' }, 'http://127.0.0.1:5000/'), ' no navegador.')))));
  }

  /* A sessão é aberta (ou renovada, se a aba só foi recarregada) antes de a página aparecer. */
  if (location.protocol === 'file:') ReactDOM.createRoot(document.getElementById('raiz')).render(h(AbertoComoArquivo));
  else sessao.iniciar().then(() => ReactDOM.createRoot(document.getElementById('raiz')).render(h(App)));
})();
