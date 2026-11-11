/* NodeWatch — seções do painel do analista. Cada bloco responde a uma pergunta do analista (mostrada no cabeçalho). */
(function () {
  'use strict';
  const { h, f, api, consulta, useCarga, useIntervalo, Icone, Aviso, Erro, Carregando, Vazio, Legenda, Selo, Secao, Pares, Dialogo, Barra, BarraProgresso,
    NOME_FAIXA, SITUACAO_ALERTA, BlocoGrafo } = window.NW;

  const NOME_STATUS = { em_andamento: 'Em andamento', concluida: 'Concluída', cancelada: 'Cancelada', parcial: 'Parcial', erro: 'Erro' };
  const TOM_STATUS = { concluida: 'ok', cancelada: 'atencao', parcial: 'atencao', erro: 'alerta', em_andamento: '' };
  const NOME_ETAPA = { pendente: 'Pendente', em_andamento: 'Em andamento', concluida: 'Concluída', pulada: 'Pulada (não se aplica)',
    erro: 'Erro', cancelada: 'Cancelada', interrompida: 'Interrompida' };
  const MARCA_ETAPA = { concluida: '✓', em_andamento: '▶', erro: '!', cancelada: '×', interrompida: '×', pulada: '–' };
  const NOME_DATASET = { validando: 'Validando…', valido: 'Válido', valido_com_recusas: 'Válido, com linhas recusadas', invalido: 'Inválido',
    erro: 'Erro na validação', nao_validado: 'Ainda não validado' };

  /* ═══ 1. Dataset e análise ═══════════════════════════════════════════ */
  function TabelaProblemas({ problemas }) {
    if (!problemas || !problemas.length) return null;
    return h('div', { className: 'rolagem' }, h('table', null,
      h('caption', null, 'Problemas encontrados: coluna, linha de exemplo e o que corrigir. O cabeçalho é a linha 1 do arquivo.'),
      h('thead', null, h('tr', null, ['Coluna', 'Linha de exemplo', 'Valor encontrado', 'Problema', 'Como corrigir', 'Linhas afetadas'].map(c => h('th', { key: c, scope: 'col' }, c)))),
      h('tbody', null, problemas.map((p, i) => h('tr', { key: i },
        h('td', { className: 'mono' }, p.coluna || '—'), h('td', { className: 'num' }, f.vazio(p.linha_exemplo) ? '—' : f.inteiro(p.linha_exemplo)),
        h('td', { className: 'mono' }, f.vazio(p.valor_exemplo) ? '—' : (p.valor_exemplo === '' ? '(vazio)' : p.valor_exemplo)),
        h('td', { style: { whiteSpace: 'normal' } }, p.problema), h('td', { style: { whiteSpace: 'normal' } }, p.como_corrigir),
        h('td', { className: 'num' }, f.vazio(p.linhas_afetadas) ? '—' : f.inteiro(p.linhas_afetadas)))))));
  }

  function ResumoDataset({ d }) {
    if (!d) return null;
    const v = d.validacao;
    const cabecalho = h('div', { className: 'linha' }, h('h3', { style: { margin: 0 } }, d.nome),
      h(Selo, { tom: d.status === 'valido' ? 'ok' : d.status === 'invalido' || d.status === 'erro' ? 'alerta' : d.status === 'valido_com_recusas' ? 'atencao' : '' }, NOME_DATASET[d.status] || d.status),
      h('span', { className: 'suave' }, f.bytes(d.bytes) + ' · ' + (d.origem === 'enviado' ? 'enviado em ' + f.instante(d.enviado_em) : 'disponível no servidor (' + d.procedencia + ')')));
    if (d.status === 'validando') {
      const p = d.progresso || {};
      return h('div', { className: 'bloco' }, cabecalho,
        h('p', { role: 'status', style: { marginTop: 8 } }, 'Validando no servidor: ' + (p.bytes_total ? f.bytes(p.bytes_lidos) + ' de ' + f.bytes(p.bytes_total) + ' lidos, ' + f.inteiro(p.linhas_lidas) + ' linhas conferidas.' : 'abrindo o arquivo…')),
        p.bytes_total ? h(BarraProgresso, { feito: p.bytes_lidos, total: p.bytes_total, rotulo: 'Validação do arquivo',
          texto: f.bytes(p.bytes_lidos) + ' de ' + f.bytes(p.bytes_total) + ' lidos' }) : null);
    }
    if (d.status === 'nao_validado') return h('div', { className: 'bloco' }, cabecalho, h(Legenda, null, 'Este dataset ainda não foi validado. Clique em Validar para conferir o arquivo antes de analisar.'));
    if (d.status === 'invalido' || d.status === 'erro') return h('div', { className: 'bloco' }, cabecalho,
      h(Aviso, { tom: 'erro', titulo: 'Este dataset não pode ser analisado' }, 'Corrija o arquivo conforme a tabela abaixo e envie de novo.'),
      h('div', { style: { marginTop: 8 } }, h(TabelaProblemas, { problemas: (d.erro || {}).problemas })));
    const cat = lista => lista.map(x => x.valor + ' (' + f.inteiro(x.n) + ')').join(', ');
    return h('div', { className: 'bloco grade' }, cabecalho,
      h(Pares, { itens: [
        ['Formato reconhecido', v.formato_nome],
        ['Linhas', f.inteiro(v.linhas.lidas) + ' lidas · ' + f.inteiro(v.linhas.validas) + ' válidas · ' + f.inteiro(v.linhas.recusadas) + ' recusadas'],
        ['Período', v.periodo ? f.dataHora(v.periodo.inicio) + ' a ' + f.dataHora(v.periodo.fim) + ' — ' + v.periodo.fuso : null],
        ['Contas distintas', f.inteiro(v.contas_distintas)],
        ['Moedas de pagamento', cat(v.moedas_pagamento)],
        ['Formatos de pagamento', cat(v.formatos_pagamento)],
        ['Rótulo do dataset', v.rotulo.disponivel ? 'coluna "' + v.rotulo.coluna + '": ' + f.inteiro(v.rotulo.positivos) + ' transações rotuladas como lavagem' : 'não há (' + v.rotulo.motivo + ')'],
        ['Tipologias registradas', v.tipologias.disponivel ? f.inteiro(v.tipologias.tentativas) + ' tentativas e ' + f.inteiro(v.tipologias.transacoes_listadas) + ' transações no arquivo de padrões "' + (d.padroes || {}).nome + '"' : 'não há (' + v.tipologias.motivo + ')'],
        ['Hash do arquivo (SHA-256)', h('span', { className: 'mono' }, v.sha256.slice(0, 16) + '…')],
      ] }),
      h('details', null, h('summary', null, 'Colunas reconhecidas (' + v.colunas.length + ')' + (v.colunas_nao_reconhecidas.length ? ' e ' + v.colunas_nao_reconhecidas.length + ' fora do contrato' : '')),
        h('ul', null, v.colunas.map(c => h('li', { key: c.original }, h('span', { className: 'mono' }, c.original), ' → ' + c.papel))),
        v.colunas_nao_reconhecidas.length ? h(Legenda, null, 'Colunas fora do contrato (guardadas e exibíveis na tabela, mas não usadas pelo modelo): ' + v.colunas_nao_reconhecidas.join(', ') + '.') : null),
      v.avisos.map((a, i) => h(Aviso, { key: i, tom: 'atencao' }, a)),
      v.linhas.recusadas ? h(Aviso, { tom: 'atencao', titulo: f.inteiro(v.linhas.recusadas) + ' linha(s) recusada(s) ficam fora da análise' },
        'Serão analisadas as ' + f.inteiro(v.linhas.validas) + ' linhas válidas. Nada é corrigido nem preenchido automaticamente.') : null,
      h(TabelaProblemas, { problemas: v.problemas }));
  }

  function Progresso({ m, aoCancelar, aoAssumir }) {
    const atual = m.etapas.find(e => e.status === 'em_andamento');
    const ss = m.sessao || {};
    return h('div', { className: 'grade' },
      h('p', { className: 'sr', role: 'status', 'aria-live': 'polite' }, m.status === 'em_andamento' ? (atual ? 'Etapa atual: ' + atual.nome : 'Preparando a análise') : 'Análise ' + NOME_STATUS[m.status]),
      h('ol', { className: 'etapas', 'aria-label': 'Etapas da análise' }, m.etapas.map((e, i) => {
        const p = e.progresso;
        let volume = null;
        if (p && p.total) {
          volume = e.unidade === 'bytes' ? f.bytes(p.feito) + ' de ' + f.bytes(p.total) + ' lidos' + (p.linhas_lidas ? ' · ' + f.inteiro(p.linhas_lidas) + ' linhas' : '')
            : f.inteiro(p.feito) + ' de ' + f.inteiro(p.total) + ' ' + e.unidade + (p.alertas_ate_agora !== undefined ? ' · ' + f.inteiro(p.alertas_ate_agora) + ' alertas até agora' : '');
        }
        return h('li', { key: e.id, className: 'etapa ' + e.status, 'aria-current': e.status === 'em_andamento' ? 'step' : undefined },
          h('span', { className: 'marca', 'aria-hidden': 'true' }, MARCA_ETAPA[e.status] || (i + 1)),
          h('div', null,
            h('div', { className: 'linha', style: { justifyContent: 'space-between' } }, h('span', { className: 'nome' }, (i + 1) + '. ' + e.nome),
              h('span', { className: 'situacao' }, NOME_ETAPA[e.status] + (e.duracao_s !== null && e.duracao_s !== undefined ? ' · ' + f.duracao(e.duracao_s) : ''))),
            e.status === 'em_andamento' && p && p.total ? h(BarraProgresso, { feito: p.feito, total: p.total, rotulo: e.nome, texto: volume + ' (' + f.pct(p.fracao, 0) + ')' }) : null,
            volume ? h('div', { className: 'situacao' }, volume + (e.status === 'em_andamento' && p.fracao !== null ? ' · ' + f.pct(p.fracao, 0) : '')) : null,
            e.status === 'em_andamento' && p && p.estimativa_restante_s !== undefined ? h('div', { className: 'situacao' },
              'Tempo restante (estimativa): cerca de ' + f.duracao(p.estimativa_restante_s) + ' — calculada pela vazão observada nesta etapa: ' +
              (e.unidade === 'bytes' ? f.bytes(p.vazao_por_s) : f.inteiro(p.vazao_por_s) + ' ' + e.unidade) + ' por segundo em ' + f.duracao(p.decorrido_s) + '.') : null,
            e.detalhe ? h('div', { className: 'situacao' }, e.detalhe) : null));
      })),
      m.status === 'em_andamento' && ss.exigida ? h(Aviso, { tom: ss.desta_sessao ? '' : 'atencao', titulo: ss.desta_sessao ? 'Esta aba mantém a análise em andamento' : 'Outra aba é a responsável por esta análise', vivo: true },
        h('p', null, ss.desta_sessao ? 'Mantenha esta página aberta (pode minimizar ou trocar de aba). Sem sinal dela por ' + f.inteiro(ss.janela_s) + ' s, a análise para num ponto seguro e fica parcial; não é retomada sozinha.'
          : (ss.responsavel_ativa ? 'A sessão que iniciou a análise continua ativa em outra aba.' : 'A sessão que iniciou a análise não dá sinal: a análise vai parar no próximo ponto seguro.') + ' Para que esta aba passe a mantê-la, use o botão abaixo.'),
        ss.desta_sessao ? null : h('div', null, h('button', { type: 'button', className: 'botao pequeno', onClick: aoAssumir }, h(Icone, { nome: 'sessao' }), 'Manter a análise nesta aba'))) : null,
      m.status === 'em_andamento' ? h('div', { className: 'linha' },
        h('button', { type: 'button', className: 'botao perigo', onClick: aoCancelar, disabled: m.cancelamento_solicitado }, h(Icone, { nome: 'fechar' }), m.cancelamento_solicitado ? 'Cancelamento pedido…' : 'Cancelar análise'),
        h(Legenda, null, m.cancelamento_solicitado ? 'A análise para no fim do bloco atual; o que já foi pontuado fica gravado.' : 'O cancelamento é seguro: para no fim do bloco atual e mantém o que já foi pontuado.')) : null);
  }

  function SituacaoAnalise({ m }) {
    if (!m || m.status === 'em_andamento') return null;
    const c = m.contagens, tom = m.status === 'concluida' ? 'ok' : m.status === 'erro' ? 'erro' : 'atencao';
    return h(Aviso, { tom, titulo: 'Análise ' + NOME_STATUS[m.status].toLowerCase() + ' — ' + m.dataset.nome, vivo: true },
      h('p', null, m.descricao_status),
      m.motivo ? h('p', null, m.motivo) : null,
      (m.erros || []).map((e, i) => h('p', { key: i }, h('strong', null, 'Causa: '), e.causa + ' ', h('strong', null, 'O que fazer: '), e.acao)),
      m.resultados.disponiveis ? h('p', null, f.inteiro(c.pontuadas) + ' transações pontuadas' + (m.resultados.parciais ? ' de ' + f.inteiro(c.validas) + ' válidas (resultado parcial)' : '') +
        ', ' + f.inteiro(c.alertas) + ' com alerta · duração ' + f.duracao(m.duracao_s) + ' · modelo ' + (m.modelo ? m.modelo.versao : '—')) : h('p', null, 'Não há resultados para consultar.'),
      (m.avisos || []).length ? h('details', null, h('summary', null, 'Avisos da análise (' + m.avisos.length + ')'), h('ul', null, m.avisos.map((a, i) => h('li', { key: i }, '• ' + a)))) : null);
  }

  function SecaoDataset({ estado, datasets, dataset, datasetId, aoEscolher, aoRecarregar, manifesto, aoAnalisar, aoCancelar, aoAssumir, analises, aoAbrir, analiseId, erroAnalise }) {
    const [enviando, setEnviando] = React.useState(false);
    const [erro, setErro] = React.useState(null);
    const refArq = React.useRef(null), refPad = React.useRef(null);
    const lim = estado.limites;
    const enviar = async ev => {
      ev.preventDefault();
      const arq = refArq.current.files[0];
      if (!arq) { setErro({ erro: 'Escolha um arquivo.', acao: 'Selecione um .csv ou .zip no campo Arquivo de transações.' }); refArq.current.focus(); return; }
      const fd = new FormData();
      fd.append('arquivo', arq);
      if (refPad.current.files[0]) fd.append('padroes', refPad.current.files[0]);
      setEnviando(true); setErro(null);
      try {
        const reg = await api('/datasets', { method: 'POST', body: fd });
        refArq.current.value = ''; refPad.current.value = '';
        await aoRecarregar();
        aoEscolher(reg.id);
      } catch (e) { setErro(e); }
      setEnviando(false);
    };
    const validar = async () => { setErro(null); try { await api('/datasets/' + datasetId + '/validar', { method: 'POST' }); aoEscolher(datasetId, true); } catch (e) { setErro(e); } };
    const ocupado = manifesto && manifesto.status === 'em_andamento';
    const podeAnalisar = dataset && (dataset.status === 'valido' || dataset.status === 'valido_com_recusas') && !ocupado && !estado.analise_em_andamento;
    return h(Secao, { id: 'dataset', icone: 'dataset', titulo: 'Dataset e análise', pergunta: 'O que estou analisando e qual é o estado da análise?' },
      estado.modelo.disponivel ? null : h(Aviso, { tom: 'erro', titulo: 'Modelo não encontrado no servidor' }, (estado.modelo.motivo || '') + ' Sem o modelo, a análise não pode ser iniciada.'),
      h('div', { className: 'grade duas' },
        h('form', { className: 'bloco grade', onSubmit: enviar, 'aria-labelledby': 'enviar-t' },
          h('h3', { id: 'enviar-t' }, h(Icone, { nome: 'enviar' }), 'Enviar um arquivo'),
          h('div', null, h('label', { htmlFor: 'arq' }, 'Arquivo de transações'),
            h('input', { id: 'arq', type: 'file', accept: '.csv,.zip', ref: refArq, 'aria-describedby': 'arq-a' }),
            h('p', { className: 'ajuda', id: 'arq-a' }, 'CSV em UTF-8 (ou ZIP com um CSV), até ' + f.bytes(lim.envio_bytes) + '. O arquivo fica só neste servidor.')),
          h('div', null, h('label', { htmlFor: 'pad' }, 'Arquivo de padrões (opcional)'),
            h('input', { id: 'pad', type: 'file', accept: '.txt', ref: refPad, 'aria-describedby': 'pad-a' }),
            h('p', { className: 'ajuda', id: 'pad-a' }, 'Arquivo .txt com as tipologias registradas do dataset (por exemplo, HI-Small_Patterns.txt). Sem ele, o dataset não tem tipologias.')),
          h('div', { className: 'linha' }, h('button', { type: 'submit', className: 'botao', disabled: enviando }, h(Icone, { nome: 'enviar' }), enviando ? 'Enviando o arquivo…' : 'Enviar e validar'),
            enviando ? h('span', { role: 'status', className: 'suave' }, 'Enviando; a validação começa quando o envio terminar.') : null)),
        h('div', { className: 'bloco grade' },
          h('h3', null, h(Icone, { nome: 'dataset' }), 'Ou escolher um dataset disponível'),
          h('div', null, h('label', { htmlFor: 'ds' }, 'Dataset'),
            h('select', { id: 'ds', value: datasetId || '', onChange: e => aoEscolher(e.target.value), 'aria-describedby': 'ds-a' },
              h('option', { value: '' }, datasets.length ? 'Selecione…' : 'Nenhum dataset disponível'),
              datasets.map(d => h('option', { key: d.id, value: d.id }, d.nome + ' — ' + (d.origem === 'enviado' ? 'enviado' : 'do servidor') + ' — ' + (NOME_DATASET[d.status] || d.status)))),
            h('p', { className: 'ajuda', id: 'ds-a' }, 'Datasets enviados (os ' + lim.datasets_enviados_guardados + ' mais recentes ficam guardados) e arquivos já presentes no servidor. O dataset escolhido define o conjunto analisado.')),
          dataset && (dataset.status === 'nao_validado' || dataset.status === 'erro' || (dataset.origem === 'servidor' && dataset.status === 'invalido')) ?
            h('div', null, h('button', { type: 'button', className: 'botao', onClick: validar }, 'Validar este dataset')) : null)),
      h(Erro, { erro }),
      erro && erro.problemas ? h(TabelaProblemas, { problemas: erro.problemas }) : null,
      h(ResumoDataset, { d: dataset }),
      h('div', { className: 'linha' },
        h('button', { type: 'button', className: 'botao primario', disabled: !podeAnalisar || !estado.modelo.disponivel, onClick: () => aoAnalisar(datasetId), 'aria-describedby': 'analisar-a' }, h(Icone, { nome: 'analisar' }), 'Analisar'),
        h('p', { className: 'ajuda', id: 'analisar-a', style: { margin: 0 } },
          ocupado || estado.analise_em_andamento ? 'Há uma análise em andamento: espere terminar ou cancele-a.'
            : !dataset ? 'Envie ou escolha um dataset. Nada é analisado antes de você clicar em Analisar.'
              : podeAnalisar ? 'Pontua as ' + f.inteiro(dataset.validacao.linhas.validas) + ' linhas válidas com o modelo salvo. Nada é treinado. A análise roda enquanto esta página estiver aberta.'
                : 'O botão é liberado quando o dataset escolhido estiver válido.')),
      h(Erro, { erro: erroAnalise }),
      manifesto ? h('div', { className: 'bloco grade' },
        h('div', { className: 'linha' }, h('h3', { style: { margin: 0 } }, 'Processamento — ' + manifesto.dataset.nome),
          h(Selo, { tom: TOM_STATUS[manifesto.status] }, NOME_STATUS[manifesto.status]), h('span', { className: 'suave' }, 'iniciada em ' + f.instante(manifesto.iniciada_em))),
        h(SituacaoAnalise, { m: manifesto }),
        manifesto.status === 'em_andamento' ? h(Progresso, { m: manifesto, aoCancelar, aoAssumir }) :
          h('details', null, h('summary', null, 'Etapas executadas'), h(Progresso, { m: manifesto, aoCancelar, aoAssumir }))) : null,
      h('details', { open: !manifesto }, h('summary', null, 'Análises recentes (' + analises.analises.length + ')'),
        analises.analises.length ? h('div', { className: 'rolagem' }, h('table', null,
          h('caption', null, 'Abrir uma análise carrega os resultados gravados, sem reprocessar. ' + analises.retencao.leitura),
          h('thead', null, h('tr', null, ['Dataset', 'Data', 'Status', 'Registros', 'Alertas', ''].map((c, i) => h('th', { key: i, scope: 'col', className: i === 3 || i === 4 ? 'num' : '' }, c)))),
          h('tbody', null, analises.analises.map(a => h('tr', { key: a.id, className: a.id === analiseId ? 'selecionada' : '' },
            h('td', null, a.dataset.nome), h('td', null, f.instante(a.criada_em)),
            h('td', null, h(Selo, { tom: TOM_STATUS[a.status] }, NOME_STATUS[a.status] + (a.resultados.parciais && a.status !== 'parcial' ? ' (parcial)' : ''))),
            h('td', { className: 'num' }, f.inteiro(a.registros)), h('td', { className: 'num' }, f.inteiro(a.alertas)),
            h('td', null, a.id === analiseId ? h('span', { className: 'suave' }, 'aberta') :
              h('button', { type: 'button', className: 'botao pequeno', onClick: () => aoAbrir(a.id), 'aria-label': 'Abrir a análise de ' + a.dataset.nome + ' de ' + f.instante(a.criada_em) }, 'Abrir'))))))) :
          h(Vazio, null, 'Nenhuma análise foi feita ainda.')));
  }

  /* ═══ 2. Filtros ═════════════════════════════════════════════════════ */
  const CAMPOS_FILTRO = [
    { id: 'de', rotulo: 'De', tipo: 'datetime-local', ajuda: 'Data e hora iniciais (inclusive), no horário do dataset.' },
    { id: 'ate', rotulo: 'Até', tipo: 'datetime-local', ajuda: 'Data e hora finais (inclusive), no horário do dataset.' },
    { id: 'moeda', rotulo: 'Moeda', tipo: 'moeda', ajuda: 'Moeda de pagamento da transação.' },
    { id: 'alerta', rotulo: 'Alerta', tipo: 'alerta', ajuda: 'Com alerta = score 701 ou mais.' },
    { id: 'valor_min', rotulo: 'Valor mínimo', tipo: 'number', min: 1, step: 'any', ajuda: 'Valor pago mínimo, na moeda de cada transação (sem conversão entre moedas). Começa em 1; o menor valor aceito é 1. Apague o campo para incluir valores abaixo de 1.' },
    { id: 'banco_origem', rotulo: 'Banco de origem', tipo: 'text', modo: 'numeric', ajuda: 'Código numérico do banco que enviou (exato).' },
    { id: 'banco_destino', rotulo: 'Banco de destino', tipo: 'text', modo: 'numeric', ajuda: 'Código numérico do banco que recebeu (exato).' },
    { id: 'conta_origem', rotulo: 'Conta de origem', tipo: 'text', ajuda: 'Conta que enviou: número da conta ou banco-conta (exato). Também escolhe a conta do grafo.' },
    { id: 'conta_destino', rotulo: 'Conta de destino', tipo: 'text', ajuda: 'Conta que recebeu: número da conta ou banco-conta (exato). Também escolhe a conta do grafo.' },
    { id: 'score_min', rotulo: 'Score mínimo', tipo: 'number', min: 0, max: 1000, step: 1, ajuda: 'Inteiro de 0 a 1000 (inclusive).' },
    { id: 'score_max', rotulo: 'Score máximo', tipo: 'number', min: 0, max: 1000, step: 1, ajuda: 'Inteiro de 0 a 1000 (inclusive).' },
  ];
  const ROTULO_FILTRO = Object.fromEntries(CAMPOS_FILTRO.map(c => [c.id, c.rotulo]));

  function SecaoFiltros({ rascunho, setRascunho, aplicados, aoAplicar, aoLimpar, moedas, erro }) {
    const mudar = (k, v) => setRascunho(Object.assign({}, rascunho, { [k]: v }));
    const pendente = JSON.stringify(rascunho) !== JSON.stringify(aplicados);
    const ativos = Object.entries(aplicados).filter(([k, v]) => !f.vazio(v) && !(k === 'alerta' && v === 'todos'));
    const campo = c => {
      const invalido = erro && erro.campo === c.id;
      const comum = { id: 'f-' + c.id, value: rascunho[c.id], onChange: e => mudar(c.id, e.target.value), 'aria-describedby': 'f-' + c.id + '-a' + (invalido ? ' f-' + c.id + '-e' : ''), 'aria-invalid': invalido ? 'true' : undefined };
      let controle;
      if (c.tipo === 'moeda') controle = h('select', comum, h('option', { value: '' }, 'Todas'), moedas.map(m => h('option', { key: m, value: m }, m)));
      else if (c.tipo === 'alerta') controle = h('select', comum, h('option', { value: 'todos' }, 'Todos'), h('option', { value: 'sim' }, 'Com alerta'), h('option', { value: 'nao' }, 'Sem alerta'));
      else controle = h('input', Object.assign({ type: c.tipo, min: c.min, max: c.max, step: c.step, inputMode: c.modo, autoComplete: 'off' }, comum));
      return h('div', { key: c.id }, h('label', { htmlFor: 'f-' + c.id }, c.rotulo), controle,
        h('p', { className: 'ajuda', id: 'f-' + c.id + '-a' }, c.ajuda),
        invalido ? h('p', { className: 'erro-campo', id: 'f-' + c.id + '-e', role: 'alert' }, erro.mensagem) : null);
    };
    return h(Secao, { id: 'filtros', icone: 'filtro', titulo: 'Filtros do recorte', pergunta: 'Os filtros valem ao mesmo tempo para os indicadores, as contas, o grafo e a tabela.' },
      h('form', { className: 'grade', noValidate: true, onSubmit: e => { e.preventDefault(); aoAplicar(); } },  // a mensagem de erro vem do servidor, junto do campo
        h('div', { className: 'grade campos' }, CAMPOS_FILTRO.map(campo)),
        h('div', { className: 'linha' },
          h('button', { type: 'submit', className: 'botao primario' }, h(Icone, { nome: 'filtro' }), 'Aplicar filtros'),
          h('button', { type: 'button', className: 'botao', onClick: aoLimpar }, h(Icone, { nome: 'limpar' }), 'Voltar aos filtros iniciais'),
          pendente ? h('span', { role: 'status', className: 'selo atencao' }, 'Há alterações não aplicadas') : null),
        h('p', { className: 'legenda', role: 'status' }, h('strong', null, 'Filtros aplicados: '),
          ativos.length ? ativos.map(([k, v]) => ROTULO_FILTRO[k] + ' = ' + (k === 'alerta' ? (v === 'sim' ? 'Com alerta' : 'Sem alerta') : (k === 'de' || k === 'ate') ? f.dataHora(v) : v)).join(' · ') : 'nenhum (dataset inteiro).')));
  }

  /* ═══ 3. Visão geral do recorte ══════════════════════════════════════ */
  /* Como ler o score: original 0–1 (não calibrado) → índice 0–1000, com o limiar original e a relação com as faixas. */
  function ComoLerScore({ estado, manifesto }) {
    const conv = (manifesto && manifesto.conversao_score) || {}, leg = estado.score || {};
    const limiar = conv.limiar_bruto || leg.limiar_original;
    if (!limiar) return null;
    const inicioInter = limiar * 301 / 701;
    const orig = v => f.numero(v, 4);
    const ev = leg.evidencia_de_nao_calibracao;
    return h('div', { className: 'bloco' },
      h('h3', null, h(Icone, { nome: 'score' }), 'Como ler o score'),
      h('p', null, leg.natureza || 'O score de 0 a 1000 é um índice de prioridade, não uma probabilidade.'),
      h('div', { className: 'escala', role: 'img', 'aria-label': 'Escala do score: de 0 a 300, faixa baixa, score original de 0 a ' + orig(inicioInter) + '; de 301 a 700, faixa intermediária, score original de ' + orig(inicioInter) + ' a ' + orig(limiar) +
        '; de 701 a 1000, faixa alta com alerta, score original de ' + orig(limiar) + ' a 1. O limiar original do modelo, ' + orig(limiar) + ', corresponde ao score 701.' },
        h('div', { className: 'faixas' }, h('div', { className: 'f-baixa' }, 'Baixa · 0–300'), h('div', { className: 'f-intermediaria' }, 'Intermediária · 301–700'), h('div', { className: 'f-alta' }, '⚠ Alta · 701–1000')),
        h('div', { className: 'marcas' },
          h('div', null, h('span', null, 'original 0'), h('span', null, orig(inicioInter))),
          h('div', null, h('span', null, ''), h('strong', null, orig(limiar) + ' (limiar)')),
          h('div', null, h('span', null, ''), h('span', null, 'original 1')))),
      h(Legenda, null, h('strong', null, 'Limiar original do modelo: '), orig(limiar) + ' (cerca de ' + f.numero(limiar, 3) + '), na escala de 0 a 1. Ele vira o score 701: tudo a partir dele é alerta e faixa alta. A faixa intermediária é o trecho logo abaixo do limiar (score original de ' +
        orig(inicioInter) + ' a ' + orig(limiar) + '); a faixa baixa é o que fica abaixo de ' + orig(inicioInter) + '.'),
      h(Legenda, null, h('strong', null, 'Conversão: '), leg.conversao || conv.tipo || ''),
      ev ? h('details', null, h('summary', null, 'Por que o score original não é uma probabilidade'),
        h(Legenda, null, ev.leitura + ' Origem: ' + ev.origem + '.'),
        h('div', { className: 'rolagem' }, h('table', null,
          h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'Score original'), h('th', { scope: 'col', className: 'num' }, 'Transações'), h('th', { scope: 'col', className: 'num' }, 'Score médio'), h('th', { scope: 'col', className: 'num' }, 'Rotuladas como lavagem'))),
          h('tbody', null, ev.caixas.map((c, i) => h('tr', { key: i }, h('td', null, f.numero(c.de, 1) + ' a ' + f.numero(c.ate, 1)), h('td', { className: 'num' }, f.inteiro(c.transacoes)),
            h('td', { className: 'num' }, f.numero(c.score_medio, 3)), h('td', { className: 'num' }, f.pct(c.fracao_rotulada_lavagem, 1)))))))) :
        h(Legenda, null, 'A avaliação histórica com a comparação entre score e rótulo não está disponível neste servidor.'),
      h(Legenda, null, estado.aviso_faixas));
  }

  const faixaOriginal = (manifesto, estado, id) => {
    const limiar = ((manifesto && manifesto.conversao_score) || {}).limiar_bruto || (estado.score || {}).limiar_original;
    if (!limiar) return '—';
    const a = limiar * 301 / 701, n = v => f.numero(v, 4);
    return id === 'baixa' ? '0 a ' + n(a) : id === 'intermediaria' ? n(a) + ' a ' + n(limiar) : n(limiar) + ' a 1';
  };

  function SecaoVisao({ carga, manifesto, estado }) {
    const v = carga.dados;
    let corpo;
    if (carga.erro) corpo = h(Erro, { erro: carga.erro });
    else if (!v) corpo = h(Carregando, { texto: 'Calculando os indicadores do recorte…' });
    else {
      const n = v.registros.recorte;
      corpo = h(React.Fragment, null,
        manifesto.resultados.parciais ? h(Aviso, { tom: 'atencao', titulo: 'Resultado parcial' },
          'Os números abaixo cobrem só as ' + f.inteiro(manifesto.contagens.pontuadas) + ' transações pontuadas antes da interrupção, de ' + f.inteiro(manifesto.contagens.validas) + ' válidas.') : null,
        h('div', { className: 'kpis', 'aria-busy': carga.carregando },
          h('div', { className: 'kpi' }, h('div', { className: 'nome' }, 'Registros de transação'),
            h('div', { className: 'valor' }, f.inteiro(n)), h('div', null, 'no recorte, de ' + f.inteiro(v.registros.dataset) + ' no dataset'), h(Legenda, null, v.registros.legenda)),
          h('div', { className: 'kpi alerta' }, h('div', { className: 'nome' }, h(Icone, { nome: 'alerta' }), 'Alertas de lavagem'),
            h('div', { className: 'valor' }, '⚠ ' + f.inteiro(v.alertas.n)), h('div', null, n ? f.pct(v.alertas.proporcao, 2) + ' das ' + f.inteiro(n) + ' transações do recorte' : '—'), h(Legenda, null, v.alertas.legenda)),
          h('div', { className: 'kpi' }, h('div', { className: 'nome' }, 'Período coberto'),
            h('div', { className: 'valor menor' }, v.periodo ? f.dataHora(v.periodo.inicio) + ' a ' + f.dataHora(v.periodo.fim) : 'Sem transações no recorte'),
            h(Legenda, null, v.periodo ? v.periodo.legenda : 'Ajuste os filtros.')),
          h('div', { className: 'kpi' }, h('div', { className: 'nome' }, 'Score (0 a 1000)'),
            h('div', { className: 'valor menor' }, v.score ? 'mín. ' + v.score.min + ' · mediano ' + f.numero(v.score.mediana, Number.isInteger(v.score.mediana) ? 0 : 1) + ' · máx. ' + v.score.max : '—'),
            h(Legenda, null, v.score ? v.score.legenda : 'Sem transações no recorte.'))),
        v.valor_minimo && v.valor_minimo.fora ? h(Aviso, { tom: 'atencao', titulo: 'O valor mínimo de ' + f.numero(v.valor_minimo.aplicado, 0) + ' deixa ' + f.plural(v.valor_minimo.fora, 'transação', 'transações') + ' fora do recorte' },
          h('p', null, 'Por moeda: ' + v.valor_minimo.por_moeda.map(m => m.moeda + ' ' + f.inteiro(m.n)).join(', ') + '. ' +
            (v.valor_minimo.alertas_fora ? f.plural(v.valor_minimo.alertas_fora, 'delas tem alerta', 'delas têm alerta') + '. ' : 'Nenhuma delas tem alerta. ') + v.valor_minimo.legenda)) : null,
        h(ComoLerScore, { estado, manifesto }),
        h('div', { className: 'grade duas' },
          h('div', { className: 'bloco' }, h('h3', null, h(Icone, { nome: 'score' }), 'Faixas do score'),
            h('div', { className: 'rolagem' }, h('table', null,
              h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'Faixa'), h('th', { scope: 'col' }, 'Score original'), h('th', { scope: 'col' }, 'Recomendação'), h('th', { scope: 'col', className: 'num' }, 'Transações'), h('th', { scope: 'col', className: 'num' }, '% do recorte'))),
              h('tbody', null, v.faixas.map(x => h('tr', { key: x.id, className: x.id === 'alta' && x.n ? 'com-alerta' : '' },
                h('td', null, h('strong', null, (x.id === 'alta' ? '⚠ ' : '') + x.nome), ' (' + x.de + '–' + x.ate + ')'), h('td', { className: 'mono' }, faixaOriginal(manifesto, estado, x.id)), h('td', { style: { whiteSpace: 'normal' } }, x.recomendacao),
                h('td', { className: 'num' }, f.inteiro(x.n)), h('td', { className: 'num' }, f.pct(x.proporcao, 2))))))),
            h(Legenda, null, estado.aviso_faixas)),
          h('div', { className: 'bloco' }, h('h3', null, h(Icone, { nome: 'visao' }), 'Formato de pagamento'),
            v.formatos.itens.length ? h('div', { className: 'rolagem' }, h('table', null,
              h('caption', null, v.formatos.legenda + '. Formato vazio ou desconhecido aparece como "Não informado".'),
              h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'Formato'), h('th', { scope: 'col', className: 'num' }, 'Transações'), h('th', { scope: 'col', className: 'num' }, '% das ' + f.inteiro(n)), h('th', { scope: 'col' }, 'Proporção'))),
              h('tbody', null, v.formatos.itens.map(x => h('tr', { key: x.formato },
                h('td', null, x.nao_informado ? h('em', null, x.formato) : x.formato), h('td', { className: 'num' }, f.inteiro(x.n)), h('td', { className: 'num' }, f.pct(x.proporcao, 1)),
                h('td', { style: { minWidth: 90 } }, h(Barra, { fracao: x.proporcao, rotulo: f.pct(x.proporcao, 1) + ' das transações do recorte' }))))))) : h(Vazio, null, 'Nenhuma transação no recorte.'))),
        h('div', { className: 'grade duas' },
          h('div', { className: 'bloco' }, h('h3', null, h(Icone, { nome: 'sequencia' }), 'Tipologias de lavagem — registradas no dataset'),
            v.tipologias.disponivel ? h(React.Fragment, null, h('div', { className: 'rolagem' }, h('table', null,
              h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'Tipologia'), h('th', { scope: 'col' }, 'O que é'), h('th', { scope: 'col', className: 'num' }, 'Transações'), h('th', { scope: 'col', className: 'num' }, 'Com alerta'))),
              h('tbody', null, v.tipologias.itens.map(x => h('tr', { key: x.tipologia },
                h('td', { className: 'mono' }, x.tipologia), h('td', { style: { whiteSpace: 'normal', minWidth: 190 } }, x.descricao), h('td', { className: 'num' }, f.inteiro(x.n)), h('td', { className: 'num' }, f.inteiro(x.alertas))))))),
              h(Legenda, null, h('strong', null, 'Origem: '), v.tipologias.origem + '. ' + v.tipologias.legenda)) : h(Vazio, null, v.tipologias.motivo)),
          h('div', { className: 'bloco' }, h('h3', null, h(Icone, { nome: 'info' }), 'Rótulo do dataset — separado da previsão'),
            v.rotulo.disponivel ? h(React.Fragment, null,
              h(Pares, { itens: [['Rotuladas como lavagem no recorte', f.inteiro(v.rotulo.rotuladas_lavagem)], ['Dessas, com alerta do modelo', f.inteiro(v.rotulo.rotuladas_com_alerta)]] }),
              h(Legenda, null, v.rotulo.legenda)) : h(Vazio, null, v.rotulo.motivo))));
    }
    return h(Secao, { id: 'visao', icone: 'visao', titulo: 'Visão geral do recorte', pergunta: 'Quantas transações e alertas existem no recorte, em que período e com que scores?' }, corpo);
  }

  /* ═══ 4. Contas de maior risco e grafo ═══════════════════════════════ */
  function SecaoInvestigacao({ visao, focoPedido, aoFocar, cargaGrafo, analiseId, filtros, total, profundidade, aoProfundidade, aoFiltrarTabela }) {
    const cr = visao.dados ? visao.dados.contas_risco : null;
    const focoAtual = cargaGrafo.dados && cargaGrafo.dados.foco;
    return h(Secao, { id: 'investigacao', icone: 'grafo', titulo: 'Contas de maior risco e grafo de transações', pergunta: 'Quais contas devo investigar primeiro, e para onde o dinheiro foi?' },
      h('div', { className: 'grade', style: { gridTemplateColumns: 'minmax(260px, 340px) minmax(0, 1fr)' }, id: 'grade-investigacao' },
        h('div', { className: 'bloco' }, h('h3', null, h(Icone, { nome: 'contas' }), 'Contas de maior risco' + (cr ? ' (até ' + cr.limite + ')' : '')),
          !cr ? h(Carregando, null) : cr.contas.length ? h('ol', { className: 'contas' }, cr.contas.map((c, i) =>
            h('li', { key: c.conta }, h('button', { type: 'button', className: 'botao conta', 'aria-pressed': focoAtual === c.conta, onClick: () => aoFocar(c.conta) },
              h('span', { className: 'id' }, (i + 1) + '. ' + c.conta),
              h('span', { className: 'dados risco' }, '⚠ ' + f.plural(c.alertas, 'transação com alerta', 'transações com alerta') + ' (' + f.inteiro(c.alertas_como_origem) + ' como origem, ' + f.inteiro(c.alertas_como_destino) + ' como destino)'),
              h('span', { className: 'dados' }, 'maior score ' + c.maior_score + ' · ' + f.plural(c.transacoes_no_recorte, 'transação no recorte', 'transações no recorte')))))) :
            h(Vazio, null, 'Nenhuma conta tem transação com alerta no recorte.'),
          cr ? h(Legenda, null, h('strong', null, 'Regra: '), cr.regra) : null,
          h(Legenda, null, 'Selecionar uma conta abre o grafo dela, uma de cada vez. Banco e conta aparecem juntos (banco-conta), como na tabela.')),
        h('div', { className: 'bloco', style: { minWidth: 0 } }, h('h3', null, h(Icone, { nome: 'grafo' }), 'Grafo de transações financeiras'),
          h(BlocoGrafo, { carga: cargaGrafo, analiseId, filtros, total, profundidade, aoProfundidade, aoFocar, aoFiltrarTabela }))));
  }

  /* ═══ 5. Tabela de registros ═════════════════════════════════════════ */
  const COLUNAS = [
    { id: 'posicao', nome: 'Posição', padrao: true, num: true, dica: 'lugar na lista atual, a partir de 1' },
    { id: 'id_exibicao', nome: 'ID de exibição', padrao: true, dica: 'ordem cronológica no dataset inteiro' },
    { id: 'data_hora', nome: 'Data e hora', padrao: true },
    { id: 'banco_origem', nome: 'Banco de origem', padrao: true }, { id: 'conta_origem', nome: 'Conta de origem', padrao: true },
    { id: 'banco_destino', nome: 'Banco de destino', padrao: true }, { id: 'conta_destino', nome: 'Conta de destino', padrao: true },
    { id: 'valor_pago', nome: 'Valor pago', padrao: true, num: true }, { id: 'moeda_pagamento', nome: 'Moeda', padrao: true },
    { id: 'formato', nome: 'Formato de pagamento', padrao: true },
    { id: 'score', nome: 'Score', padrao: true, num: true }, { id: 'alerta', nome: 'Alerta', padrao: true },
    { id: 'valor_recebido', nome: 'Valor recebido', num: true }, { id: 'moeda_recebimento', nome: 'Moeda recebida' },
    { id: 'rotulo', nome: 'Rótulo do dataset' }, { id: 'tipologias', nome: 'Tipologias registradas' },
    { id: 'linha_arquivo', nome: 'Linha no arquivo', num: true }, { id: 'id_original', nome: 'ID original do arquivo' },
  ];
  const celula = (c, l, total) => {
    switch (c.id) {
      case 'posicao': return f.inteiro(l.posicao);
      case 'id_exibicao': return f.idExibicao(l.id_exibicao, total);
      case 'data_hora': return f.dataHora(l.data_hora);
      case 'valor_pago': case 'valor_recebido': return f.valor(l[c.id]);
      case 'alerta': return h('span', null, l.alerta ? h('strong', null, '⚠ Sim') : 'Não', ' (faixa ' + NOME_FAIXA[l.faixa] + ')');
      case 'rotulo': return l.rotulo === null ? 'sem rótulo' : l.rotulo === 1 ? 'lavagem' : 'não lavagem';
      case 'tipologias': return l.tipologias.length ? l.tipologias.join(', ') : '—';
      case 'linha_arquivo': return f.inteiro(l.linha_arquivo);
      default: if (c.extra) return f.vazio(l.extras[c.extra]) ? '—' : l.extras[c.extra];
        return f.vazio(l[c.id]) ? '—' : l[c.id];
    }
  };

  function SecaoTabela({ carga, manifesto, tabela, setTabela, aoDetalhe, selecionada }) {
    const extras = (manifesto.dataset.colunas_nao_reconhecidas || []).map(c => ({ id: 'x:' + c, nome: c + ' (coluna original)', extra: c }));
    const todas = COLUNAS.concat(extras);
    const [visiveis, setVisiveis] = React.useState(() => {
      try { const g = JSON.parse(localStorage.getItem('nw.colunas') || 'null'); if (Array.isArray(g) && g.length) return g; } catch (e) { /* preferência ausente */ }
      return COLUNAS.filter(c => c.padrao).map(c => c.id);
    });
    const alternar = id => {
      const novo = visiveis.includes(id) ? visiveis.filter(x => x !== id) : visiveis.concat(id);
      setVisiveis(novo);
      try { localStorage.setItem('nw.colunas', JSON.stringify(novo)); } catch (e) { /* sem armazenamento local */ }
    };
    const cols = todas.filter(c => visiveis.includes(c.id));
    const total = manifesto.contagens.pontuadas;
    const d = carga.dados;
    return h(Secao, { id: 'tabela', icone: 'tabela', titulo: 'Registros de transação', pergunta: 'Quais transações devo investigar primeiro, e por quê?' },
      h('div', { className: 'linha', style: { justifyContent: 'space-between' } },
        h('p', { role: 'status' }, d ? h(React.Fragment, null, h('strong', null, f.inteiro(d.total)), ' registros no recorte · página ' + d.pagina + ' de ' + f.inteiro(d.paginas)) : 'Carregando…'),
        h('div', { className: 'linha' },
          h('label', { htmlFor: 't-ord', style: { margin: 0 } }, 'Ordenar por'),
          h('select', { id: 't-ord', style: { width: 'auto' }, value: tabela.ordenar + ':' + tabela.direcao,
            onChange: e => { const [o, dr] = e.target.value.split(':'); setTabela(Object.assign({}, tabela, { ordenar: o, direcao: dr, pagina: 1 })); } },
            h('option', { value: 'id_exibicao:asc' }, 'Data e hora (mais antigas primeiro)'), h('option', { value: 'id_exibicao:desc' }, 'Data e hora (mais recentes primeiro)'),
            h('option', { value: 'score:desc' }, 'Score (maior primeiro)'), h('option', { value: 'score:asc' }, 'Score (menor primeiro)'),
            h('option', { value: 'valor_pago:desc' }, 'Valor pago (maior primeiro, sem converter moeda)')),
          h('label', { htmlFor: 't-tam', style: { margin: 0 } }, 'Linhas por página'),
          h('select', { id: 't-tam', style: { width: 'auto' }, value: tabela.tamanho, onChange: e => setTabela(Object.assign({}, tabela, { tamanho: +e.target.value, pagina: 1 })) },
            [25, 50, 100, 200].map(n => h('option', { key: n, value: n }, n))))),
      h('details', null, h('summary', null, 'Colunas (' + cols.length + ' de ' + todas.length + ' visíveis)'),
        h('fieldset', { style: { border: 0, padding: 0 } }, h('legend', { className: 'legenda' }, 'Marque as colunas a exibir. A lista inclui todas as colunas originais do dataset.'),
          h('div', { className: 'grade campos' }, todas.map(c => h('label', { key: c.id, style: { fontWeight: 400 } },
            h('input', { type: 'checkbox', checked: visiveis.includes(c.id), onChange: () => alternar(c.id) }), ' ' + c.nome + (c.dica ? ' — ' + c.dica : '')))))),
      carga.erro ? h(Erro, { erro: carga.erro }) : !d ? h(Carregando, null) : !d.linhas.length ? h(Vazio, null, 'Nenhuma transação passa pelos filtros atuais.') :
        h('div', { className: 'rolagem', 'aria-busy': carga.carregando }, h('table', { className: 'tabela-registros' },
          h('caption', null, 'Selecione o ID de exibição para ver os detalhes da transação.'),
          h('thead', null, h('tr', null, cols.map(c => h('th', { key: c.id, scope: 'col', className: c.num ? 'num' : '' }, c.nome)))),
          h('tbody', null, d.linhas.map(l => h('tr', { key: l.id_exibicao, className: (l.alerta ? 'com-alerta ' : '') + (selecionada === l.id_exibicao ? 'selecionada' : '') },
            cols.map(c => h('td', { key: c.id, className: (c.num ? 'num ' : '') + (['conta_origem', 'conta_destino', 'id_exibicao'].includes(c.id) ? 'mono' : '') },
              c.id === 'id_exibicao' ? h('button', { type: 'button', className: 'botao texto mono', onClick: () => aoDetalhe(l.id_exibicao),
                'aria-label': 'Detalhes da transação ' + f.idExibicao(l.id_exibicao, total) + (l.alerta ? ', com alerta' : '') }, f.idExibicao(l.id_exibicao, total)) : celula(c, l, total)))))))),
      d && d.paginas > 1 ? h('nav', { className: 'paginacao', 'aria-label': 'Páginas da tabela' },
        h('button', { type: 'button', className: 'botao pequeno', disabled: d.pagina <= 1, onClick: () => setTabela(Object.assign({}, tabela, { pagina: 1 })) }, 'Primeira'),
        h('button', { type: 'button', className: 'botao pequeno', disabled: d.pagina <= 1, onClick: () => setTabela(Object.assign({}, tabela, { pagina: d.pagina - 1 })) }, 'Anterior'),
        h('span', null, 'Página ' + d.pagina + ' de ' + f.inteiro(d.paginas)),
        h('button', { type: 'button', className: 'botao pequeno', disabled: d.pagina >= d.paginas, onClick: () => setTabela(Object.assign({}, tabela, { pagina: d.pagina + 1 })) }, 'Próxima'),
        h('button', { type: 'button', className: 'botao pequeno', disabled: d.pagina >= d.paginas, onClick: () => setTabela(Object.assign({}, tabela, { pagina: d.paginas })) }, 'Última')) : null,
      h(Legenda, null, h('strong', null, 'Legenda: '), 'faixa vermelha no início da linha e "⚠ Sim" = transação com alerta (score 701 ou mais). ',
        h('strong', null, 'Posição'), ' = lugar na lista atual. ', h('strong', null, 'ID de exibição'), ' = ordem cronológica no dataset inteiro (empates pela ordem da linha); não muda com filtros. ',
        'Valores na moeda de pagamento, sem conversão. Datas no horário do dataset, formato dia/mês/ano.'));
  }

  function DialogoDetalhes({ analiseId, id, total, aoFechar, aoFiltrarTabela, aoFocar }) {
    const carga = useCarga(id ? '/analises/' + analiseId + '/transacoes/' + id : null);
    const d = carga.dados;
    let corpo = h(Carregando, null);
    if (carga.erro) corpo = h(Erro, { erro: carga.erro });
    else if (d) {
      const t = d.transacao, mod = d.modelo || {}, conv = d.conversao_score || {};
      const fx = d.faixas.find(x => x.id === t.faixa);
      const cartao = (titulo, conteudo) => h('div', { className: 'bloco' }, h('h3', null, titulo), conteudo);
      const conta = (papel, no, banco, numero) => cartao(papel, h(React.Fragment, null,
        h(Pares, { itens: [['Banco', banco], ['Conta', h('span', { className: 'mono' }, numero)], ['Identificador (banco-conta)', h('span', { className: 'mono' }, no)]] }),
        h('div', { className: 'linha', style: { marginTop: 8 } },
          h('button', { type: 'button', className: 'botao pequeno', onClick: () => { aoFocar(no); aoFechar(); } }, 'Ver no grafo'),
          h('button', { type: 'button', className: 'botao pequeno', onClick: () => { aoFiltrarTabela(papel === 'Origem' ? { conta_origem: no, conta_destino: '' } : { conta_origem: '', conta_destino: no }); aoFechar(); } }, 'Filtrar tabela por esta conta'))));
      corpo = h(React.Fragment, null,
        h('div', { className: 'cartoes' },
          conta('Origem', t.no_origem, t.banco_origem, t.conta_origem),
          conta('Destino', t.no_destino, t.banco_destino, t.conta_destino),
          cartao('Transação observada', h(Pares, { itens: [['Data e hora', f.dataHora(t.data_hora) + ' (horário do dataset)'], ['Valor pago', f.valor(t.valor_pago) + ' ' + t.moeda_pagamento],
            ['Valor recebido', f.valor(t.valor_recebido) + ' ' + t.moeda_recebimento], ['Formato de pagamento', t.formato], ['ID de exibição', f.idExibicao(t.id_exibicao, total)],
            ['ID original do arquivo', t.id_original || 'o arquivo não tem coluna de identificador'], ['Linha no arquivo', f.inteiro(t.linha_arquivo) + ' (o cabeçalho é a linha 1)']].concat(
            Object.entries(t.extras || {}).map(([k, v]) => [k + ' (coluna original)', v])) })),
          cartao('Previsão de lavagem (modelo)', h(React.Fragment, null,
            h(Pares, { itens: [['Score', h('strong', null, t.score + ' de 1000')], ['Faixa', h(Selo, { tom: t.alerta ? 'alerta' : t.faixa === 'intermediaria' ? 'atencao' : '' }, fx.nome + ' (' + fx.de + '–' + fx.ate + ')')],
              ['Recomendação', fx.recomendacao], ['Alerta', t.alerta ? '⚠ Sim' : 'Não'], ['Limiar de alerta', 'score 701 = score original ' + f.numero(mod.limiar_alerta, 4) + ' (limiar do modelo, escala de 0 a 1)'],
              ['Score original do modelo', f.numero(t.score_bruto, 4) + ' (0 a 1, não calibrado)'], ['Versão do modelo', mod.versao], ['Histórico da conta', t.historico_incompleto ? 'incompleto: menos de 72 h observadas antes desta transação' : 'ao menos 72 h observadas']] }),
            h(Legenda, null, conv.leitura + ' ' + d.aviso_faixas))),
          cartao('Rótulo do dataset', d.rotulo_disponivel ? h(React.Fragment, null, h('p', null, h('strong', null, t.rotulo === 1 ? 'Lavagem (rótulo 1)' : 'Não lavagem (rótulo 0)')),
            h(Legenda, null, 'Valor que já veio no arquivo. Não é previsão e não entra no cálculo do score.')) : h(Legenda, null, 'Este dataset não tem rótulo de lavagem.')),
          cartao('Tipologias registradas', d.tipologias_disponiveis ? h(React.Fragment, null,
            h('p', { className: 'mono' }, t.tipologias.length ? t.tipologias.join(', ') : 'padrao_nao_identificado'),
            h(Legenda, null, t.tipologias.length ? 'Registrada no arquivo de padrões do dataset (tentativa nº ' + t.tentativas.join(', ') + '). Não é previsão do modelo.' : 'Esta transação não aparece no arquivo de padrões do dataset.')) :
            h(Legenda, null, d.motivo_sem_tipologias || 'Este dataset não tem tipologias registradas.')),
          cartao('Motivos verificáveis', t.motivos.length ? h(React.Fragment, null, h('ul', null, t.motivos.map((m, i) => h('li', { key: i }, '• ' + m))),
            h(Legenda, null, 'Fatos conferíveis nos dados, calculados com regras fixas sobre o treino. Não explicam a decisão do modelo.')) :
            h(Legenda, null, t.alerta ? 'Não há motivo verificável para esta transação.' : 'Não há motivo verificável: os motivos só são calculados para transações com alerta.'))));
    }
    return h(Dialogo, { id: 'dlg-detalhes', aberto: !!id, titulo: 'Detalhes da transação' + (id ? ' ' + f.idExibicao(id, total) : ''), aoFechar }, corpo);
  }

  /* ═══ Painel lateral operacional ═════════════════════════════════════ */
  function Desempenho({ aberto }) {
    const [d, setD] = React.useState(null);
    const [erro, setErro] = React.useState(null);
    const ler = () => api('/operacao/desempenho').then(x => { setD(x); setErro(null); }).catch(setErro);
    React.useEffect(() => { if (aberto) ler(); }, [aberto]);
    useIntervalo(ler, 3000, aberto);
    if (erro) return h(Erro, { erro });
    if (!d) return h(Carregando, null);
    const mp = d.memoria.processo, mm = d.memoria.maquina, a = d.analise;
    const ind = v => f.vazio(v) ? 'indisponível neste sistema' : v;
    return h('div', { className: 'grade' },
      h('h3', null, h(Icone, { nome: 'operacao' }), ' Desempenho'),
      h(Pares, { itens: [
        ['RAM — processo do NodeWatch', f.vazio(mp.bytes) ? ind(null) : f.bytes(mp.bytes) + ' (' + f.numero(mp.percentual_da_maquina, 1) + '% da memória da máquina) · pico ' + f.bytes(mp.pico_bytes)],
        ['RAM — máquina', f.vazio(mm.em_uso_bytes) ? ind(null) : f.bytes(mm.em_uso_bytes) + ' em uso de ' + f.bytes(mm.total_bytes) + ' (' + f.numero(mm.percentual, 1) + '%)'],
        ['CPU — processo do NodeWatch', f.vazio(d.cpu.processo_pct) ? ind(null) : f.numero(d.cpu.processo_pct, 1) + '%'],
        ['CPU — máquina', f.vazio(d.cpu.maquina_pct) ? ind(null) : f.numero(d.cpu.maquina_pct, 1) + '%'],
      ] }),
      h(Legenda, null, 'CPU: ' + d.cpu.leitura + ' (' + d.cpu.nucleos_logicos + ' núcleos; janela de ' + f.numero(d.cpu.janela_s, 1) + ' s). Lido em ' + f.instante(d.medido_em) + '; atualiza a cada 3 s.'),
      h('h4', null, 'Latência das consultas'),
      d.latencias.length ? h('div', { className: 'rolagem' }, h('table', null,
        h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'Operação medida'), h('th', { scope: 'col', className: 'num' }, 'Última (ms)'), h('th', { scope: 'col', className: 'num' }, 'Mediana (ms)'), h('th', { scope: 'col', className: 'num' }, 'Amostras'))),
        h('tbody', null, d.latencias.map(l => h('tr', { key: l.operacao }, h('td', null, l.operacao), h('td', { className: 'num' }, f.numero(l.ultima_ms, 0)), h('td', { className: 'num' }, f.numero(l.mediana_ms, 0)), h('td', { className: 'num' }, l.amostras)))))) :
        h(Legenda, null, 'Nenhuma consulta medida ainda.'),
      h(Legenda, null, 'Latência = tempo de processamento de cada consulta no servidor, em milissegundos (não inclui a rede nem o navegador).'),
      h('h4', null, 'Análise'),
      a ? h(React.Fragment, null, h(Pares, { itens: [
        ['Qual', a.qual + ' — ' + a.dataset + ' (' + NOME_STATUS[a.status] + ')'],
        ['Duração total', f.vazio(a.duracao_total_s) ? (a.etapa_atual ? 'em andamento: ' + a.etapa_atual : '—') : f.duracao(a.duracao_total_s)],
        ['Vazão da análise inteira', f.vazio(a.vazao_total_por_s) ? 'ainda não medida' : f.inteiro(a.vazao_total_por_s) + ' transações por segundo (' + f.inteiro(a.transacoes_pontuadas) + ' ÷ ' + f.duracao(a.duracao_total_s) + ')'],
        ['Vazão só da pontuação', f.vazio(a.vazao_pontuacao_por_s) ? 'ainda não medida' : f.inteiro(a.vazao_pontuacao_por_s) + ' transações por segundo (' + f.inteiro(a.transacoes_pontuadas) + ' ÷ ' + f.duracao(a.tempo_pontuacao_s) + ')'],
        ['Pico de memória', f.vazio(a.pico_memoria_bytes) ? 'ainda não medido' : f.bytes(a.pico_memoria_bytes)],
        ['Tempo por atividade', ['atributos ' + f.duracao(a.tempos.tempo_atributos_s), 'inferência ' + f.duracao(a.tempos.tempo_inferencia_s), 'gravação ' + f.duracao(a.tempos.tempo_gravacao_s)].join(' · ')],
        ['Transações pontuadas', f.inteiro(a.transacoes_pontuadas)],
      ] }), h(Legenda, null, 'Vazão da análise inteira: ' + a.vazao_total_formula + '. Vazão só da pontuação: ' + a.vazao_pontuacao_formula + '. Pico de memória: ' + a.pico_escopo + '.')) : h(Legenda, null, 'Nenhuma análise foi feita ainda.'));
  }

  function ListaLogs({ tipo, aberto }) {
    const [d, setD] = React.useState(null);
    const ler = () => api('/operacao/logs?tipo=' + tipo + '&limite=150').then(setD).catch(() => {});
    React.useEffect(() => { if (aberto) ler(); }, [aberto, tipo]);
    useIntervalo(ler, 5000, aberto);
    if (!d) return h(Carregando, null);
    const NIVEL = { info: 'Informação', aviso: 'Aviso', erro: 'Erro' };
    return h('div', { className: 'grade' },
      h(Legenda, null, tipo === 'sistema' ? 'Envios, validações, início, fim, cancelamento e erros de análise.' : 'Modelo e versão carregados, limiar, transações pontuadas, tempo de inferência e avisos de atributos ou de esquema.', ' ' + d.privacidade),
      d.entradas.length ? h('ul', { className: 'log' }, d.entradas.map((e, i) => h('li', { key: i, className: e.nivel === 'erro' ? 'erro-log' : e.nivel === 'aviso' ? 'aviso-log' : '' },
        h('div', { className: 'quando' }, f.instante(e.quando) + ' · ' + (NIVEL[e.nivel] || e.nivel) + ' · ' + e.evento),
        h('div', null, e.mensagem),
        Object.keys(e.contexto || {}).length ? h('div', { className: 'ctx' }, Object.entries(e.contexto).map(([k, v]) => k + '=' + (typeof v === 'object' && v !== null ? JSON.stringify(v) : v)).join(' · ')) : null))) :
        h(Vazio, null, 'Nenhum registro ainda.'));
  }

  function MetricasML({ analiseId, aberto }) {
    const carga = useCarga(aberto ? '/operacao/metricas' + (analiseId ? '?analise=' + analiseId : '') : null);
    if (carga.erro) return h(Erro, { erro: carga.erro });
    if (!carga.dados) return h(Carregando, null);
    const { historicas: hi, do_dataset: dd, legendas } = carga.dados;
    const linhaMetricas = x => [['Precisão', x.precisao, legendas.precisao], ['Recall', x.recall, legendas.recall], ['F1', x.f1, legendas.f1], ['Average Precision', x.average_precision, legendas.average_precision]];
    const tabela = x => h('div', { className: 'rolagem' }, h('table', null,
      h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'Métrica'), h('th', { scope: 'col', className: 'num' }, 'Valor'), h('th', { scope: 'col' }, 'O que mede'))),
      h('tbody', null, linhaMetricas(x).map(([n, v, l]) => h('tr', { key: n }, h('td', null, n), h('td', { className: 'num' }, f.vazio(v) ? 'indisponível' : f.pct(v, 1)), h('td', { style: { whiteSpace: 'normal' } }, l))))));
    return h('div', { className: 'grade' },
      h('h4', null, 'Métricas históricas do modelo (avaliação anterior)'),
      hi.disponivel ? h(React.Fragment, null,
        h(Pares, { itens: [['Modelo', hi.versao_modelo], ['Dados', hi.dados], ['Origem', h('span', { className: 'mono' }, hi.origem)], ['Arquivo gravado em', f.instante(hi.arquivo_gravado_em)]] }),
        hi.conjuntos.map(c => h('div', { key: c.id, className: 'bloco' }, h('h4', { style: { marginTop: 0 } }, 'Conjunto de avaliação: ' + c.nome),
          h(Legenda, null, 'Período: ' + c.periodo + ' · ' + f.inteiro(c.transacoes) + ' transações, ' + f.inteiro(c.rotuladas_lavagem) + ' rotuladas como lavagem.'), tabela(c))),
        h(Aviso, { tom: 'atencao' }, hi.ressalva)) : h(Vazio, null, hi.motivo),
      h('h4', null, 'Neste dataset (análise aberta)'),
      dd.disponivel ? h(React.Fragment, null,
        h(Pares, { itens: [['Dataset', dd.dataset], ['Transações com rótulo', f.inteiro(dd.transacoes_com_rotulo)], ['Rotuladas como lavagem', f.inteiro(dd.rotuladas_lavagem)],
          ['Alertas', f.inteiro(dd.alertas) + ' (' + f.inteiro(dd.verdadeiros_positivos) + ' rotulados como lavagem, ' + f.inteiro(dd.falsos_positivos) + ' não)']] }),
        tabela(dd), h(Legenda, null, dd.origem + '. ' + dd.leitura + (dd.parcial ? ' Resultado parcial.' : ''))) : h(Vazio, null, dd.motivo),
      h(Legenda, null, 'As métricas históricas e as contagens da análise atual são coisas diferentes: as primeiras descrevem o modelo num conjunto com rótulo; as segundas contam alertas no dataset analisado.'));
  }

  function PainelLateral({ aberto, aoFechar, analiseId }) {
    const [aba, setAba] = React.useState('sistema');
    const ref = React.useRef(null);
    React.useEffect(() => { if (aberto && ref.current) ref.current.focus(); }, [aberto]);
    const ABAS = [['sistema', 'Logs do sistema'], ['ml', 'Logs de ML'], ['metricas', 'Métricas de ML']];
    const tecla = e => {
      if (e.key === 'Escape') { aoFechar(); return; }
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      const i = ABAS.findIndex(a => a[0] === aba), j = (i + (e.key === 'ArrowRight' ? 1 : ABAS.length - 1)) % ABAS.length;
      setAba(ABAS[j][0]);
      const b = document.getElementById('aba-' + ABAS[j][0]); if (b) b.focus();
    };
    return h('aside', { id: 'painel-operacional', className: 'lateral', hidden: !aberto, 'aria-labelledby': 'lateral-t', onKeyDown: e => { if (e.key === 'Escape') aoFechar(); } },
      h('header', null, h('h2', { id: 'lateral-t', tabIndex: -1, ref }, h(Icone, { nome: 'operacao' }), 'Painel operacional'), h('button', { type: 'button', className: 'botao', onClick: aoFechar }, h(Icone, { nome: 'fechar' }), 'Fechar')),
      h('div', { className: 'conteudo' },
        h('p', { className: 'legenda' }, 'O sistema e o modelo estão saudáveis?'),
        h(Desempenho, { aberto }),
        h('div', { role: 'tablist', className: 'abas', 'aria-label': 'Logs e métricas', onKeyDown: tecla },
          ABAS.map(([id, nome]) => h('button', { key: id, id: 'aba-' + id, role: 'tab', type: 'button', 'aria-selected': aba === id, 'aria-controls': 'painel-aba', tabIndex: aba === id ? 0 : -1, onClick: () => setAba(id) }, nome))),
        h('div', { role: 'tabpanel', id: 'painel-aba', 'aria-labelledby': 'aba-' + aba, tabIndex: 0 },
          aba === 'metricas' ? h(MetricasML, { analiseId, aberto }) : h(ListaLogs, { tipo: aba, aberto }))));
  }

  /* ═══ Legenda geral ══════════════════════════════════════════════════ */
  function DialogoLegenda({ aberto, aoFechar, estado }) {
    const grupo = (titulo, itens) => h('div', { className: 'bloco' }, h('h3', null, titulo), h(Pares, { itens }));
    return h(Dialogo, { id: 'dlg-legenda', aberto, titulo: 'Legenda geral', aoFechar },
      h(Legenda, null, 'Os mesmos termos valem em todas as áreas da tela. Nenhuma informação depende só de cor: há sempre um texto ou ícone junto.'),
      h('div', { className: 'cartoes' },
        grupo('Score e faixas', estado.faixas.map(x => [x.nome + ' (' + x.de + '–' + x.ate + ')', x.recomendacao]).concat([
          ['Score', 'Índice inteiro de 0 a 1000 que ordena as transações por prioridade. Não é probabilidade de lavagem nem de fraude.'],
          ['Score original', 'Valor de 0 a 1 que o modelo devolve. Não é calibrado. O limiar original (' + f.numero((estado.score || {}).limiar_original, 4) + ') corresponde ao score 701.'],
          ['Alerta', 'Score ' + estado.score_alerta + ' ou mais. Sinal para investigação, não prova de lavagem.'],
          ['Aviso', estado.aviso_faixas]])),
        grupo('Cores e ícones', [
          ['⚠ e vermelho', 'Transação, conta ou caminho com alerta. Na tabela, faixa vermelha no início da linha e o texto "⚠ Sim".'],
          ['Amarelo', 'Atenção: resultado parcial, linhas recusadas ou aviso.'],
          ['Verde e ✓', 'Etapa ou análise concluída; dataset válido.'],
          ['Azul', 'Ação disponível, item selecionado, conta em foco ou etapa em andamento (▶).'],
          ['Contorno amarelo', 'Elemento com o foco do teclado.'],
          ['Vermelho da logo', 'É a cor da marca NodeWatch, usada só na logo e na linha do topo. Alerta é sempre o vermelho-coral acompanhado de ⚠ e texto.']]),
        grupo('Estados da análise', Object.entries(estado.status_analise).map(([k, v]) => [NOME_STATUS[k], v.replace(/^[^:]+:\s*/, '')])),
        grupo('Estados do dataset', [['Válido', 'Todas as linhas passaram na validação.'], ['Válido, com linhas recusadas', 'Há linhas com problema; elas ficam fora da análise e são listadas.'],
          ['Inválido', 'O arquivo não pode ser analisado; a tabela de problemas diz o que corrigir.']]),
        grupo('Tabela', [['Posição', 'Lugar da linha na lista atual (muda com filtros e ordenação).'], ['ID de exibição', 'Ordem cronológica no dataset inteiro; empates pela ordem da linha. Nunca muda.'],
          ['Rótulo do dataset', 'Marcação de lavagem que já veio no arquivo; separada da previsão.'], ['Não informado', 'Formato de pagamento vazio ou desconhecido no arquivo.'],
          ['Recorte', 'Conjunto de transações que passa pelos filtros aplicados.']]),
        grupo('Sessão da interface', [['Sessão ativa', estado.sessao.leitura], ['Sem retomada', 'Reabrir a página mostra o que ficou gravado. Nenhuma análise recomeça sozinha.']]),
        grupo('Grafo', [['Vértice', 'Uma conta (banco-conta). A conta em foco tem contorno duplo.'], ['Seta', 'Vai da conta de origem para a conta de destino do dinheiro.'],
          ['Traço tracejado', 'Relação do recorte sem ordem temporal confirmada: não é uma etapa seguinte do dinheiro.'], ['Sequência', 'Relações cujos horários são compatíveis, uma depois da outra. Não prova que é o mesmo dinheiro.'],
          ['Aresta agrupada', 'Traço grosso: várias transações de mesma origem, destino e moeda, com quantidade e total.'], ['Valor na aresta', 'Valor pago e moeda; moedas diferentes nunca são somadas.'],
          ['Disposição', 'Segue a tipologia registrada no dataset; sem tipologia, usa padrao_nao_identificado.']]),
        grupo('Tipologias (registradas no dataset, não previstas)', estado.tipologias.map(t => [h('span', { className: 'mono' }, t.tipologia), t.descricao]))));
  }

  /* ═══ Assistente de dúvidas ══════════════════════════════════════════ */
  function Assistente({ analiseId, filtros, estado }) {
    const [aberto, setAberto] = React.useState(false);
    const [msgs, setMsgs] = React.useState([]);
    const [texto, setTexto] = React.useState('');
    const [ocupado, setOcupado] = React.useState(false);
    const refEntrada = React.useRef(null), refFim = React.useRef(null);
    React.useEffect(() => { if (aberto && refEntrada.current) refEntrada.current.focus(); }, [aberto]);
    React.useEffect(() => { if (refFim.current) refFim.current.scrollIntoView({ block: 'nearest' }); }, [msgs]);
    const perguntar = async p => {
      p = (p || '').trim();
      if (!p || ocupado) return;
      setTexto(''); setOcupado(true);
      setMsgs(m => m.concat([{ de: 'voce', texto: p }]));
      try {
        const r = await api('/assistente', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pergunta: p, analise_id: analiseId || '', filtros }) });
        setMsgs(m => m.concat([{ de: 'assistente', texto: r.resposta, titulo: r.titulo, base: r.base }]));
      } catch (e) { setMsgs(m => m.concat([{ de: 'assistente', texto: (e.erro || 'Erro') + ' ' + (e.acao || ''), base: [] }])); }
      setOcupado(false);
    };
    const SUGESTOES = ['Quantos alertas há no recorte?', 'O que é o score?', 'Qual é o período do recorte?', 'O que é FAN-OUT?'];
    return h('div', { className: 'assistente' },
      aberto ? h('section', { className: 'painel', id: 'assistente-painel', 'aria-labelledby': 'assistente-t' },
        h('div', null, h('div', { className: 'linha', style: { justifyContent: 'space-between' } }, h('h2', { id: 'assistente-t', style: { fontSize: '1rem' } }, 'Assistente de dúvidas'),
          h('button', { type: 'button', className: 'botao pequeno', onClick: () => setAberto(false) }, 'Recolher')),
          h(Legenda, null, estado.assistente.leitura + ' Não conclui se houve fraude ou lavagem.')),
        h('div', { className: 'mensagens', role: 'log', 'aria-live': 'polite', 'aria-label': 'Conversa com o assistente' },
          msgs.length ? msgs.map((m, i) => h('div', { key: i, className: 'msg ' + (m.de === 'voce' ? 'pergunta' : '') },
            h('span', { className: 'sr' }, m.de === 'voce' ? 'Você: ' : 'Assistente: '), m.titulo ? h('strong', null, m.titulo + '. ') : null, m.texto,
            m.de === 'assistente' ? h('div', { className: 'base' }, 'Base: ' + (m.base && m.base.length ? m.base.join('; ') : 'nenhuma (pergunta fora da base)')) : null)) :
            h(Legenda, null, 'Pergunte sobre termos da tela, como usar o painel ou números da análise aberta.'),
          h('div', { ref: refFim })),
        h('div', { className: 'linha' }, SUGESTOES.map(s => h('button', { key: s, type: 'button', className: 'botao pequeno', onClick: () => perguntar(s) }, s))),
        h('form', { className: 'linha', onSubmit: e => { e.preventDefault(); perguntar(texto); } },
          h('label', { htmlFor: 'assistente-p', className: 'sr' }, 'Sua pergunta'),
          h('input', { id: 'assistente-p', type: 'text', ref: refEntrada, value: texto, maxLength: 300, onChange: e => setTexto(e.target.value), placeholder: 'Escreva a pergunta', style: { flex: 1, width: 'auto' } }),
          h('button', { type: 'submit', className: 'botao primario', disabled: ocupado || !texto.trim() }, 'Perguntar'))) : null,
      h('button', { type: 'button', className: 'botao abrir', 'aria-expanded': aberto, 'aria-controls': 'assistente-painel', onClick: () => setAberto(!aberto) }, h(Icone, { nome: 'assistente' }), aberto ? 'Recolher assistente' : h(React.Fragment, null, h('span', { className: 'rotulo-longo' }, 'Assistente de dúvidas'), h('span', { className: 'rotulo-curto' }, 'Dúvidas'))));
  }

  Object.assign(window.NW, { SecaoDataset, SecaoFiltros, SecaoVisao, SecaoInvestigacao, SecaoTabela, DialogoDetalhes, PainelLateral, DialogoLegenda, Assistente, NOME_STATUS, TOM_STATUS });
})();
