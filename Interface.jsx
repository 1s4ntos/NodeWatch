// Variação C v2 — Dashboard redesenhado segundo auditoria heurística.
// Diferenças vs v1:
//  • F-pattern: alert bar → KPIs → grafo (hero) + ciclo ativo → risco → secundários colapsados
//  • Orçamento de vermelho ≤ 5 instâncias visíveis simultâneas; amber para "atenção"
//  • Tipografia +1 nível em todo o corpo, padding +50% nos painéis
//  • Progressive disclosure via <details> para log/histograma/transações
//  • Grafo: arestas normais a 35% opacidade, sem labels — só ciclos rotulados
//  • Top contas como cards horizontais mini, não barras verticais

const VariationCv2 = () => {
  const data = window.FRAUD_DATA;
  const [selectedCycle, setSelectedCycle] = React.useState(0);
  const [showEdgeAmounts, setShowEdgeAmounts] = React.useState(false);

  // Paleta semântica calibrada para WCAG AA+
  const c = {
    bg: '#131820',
    panel: '#1a2030',
    panelLow: '#161c28',
    panelHi: '#1f2638',
    border: '#2a3142',
    borderSoft: '#222a3a',
    text: '#e6e9ef',
    textBold: '#f4f6fa',
    muted: '#a4abbd',
    faint: '#6e7689',
    danger: '#ef5552',
    dangerSoft: '#2a1418',
    dangerBg: '#3a1a1d',
    amber: '#e6a82f',
    amberSoft: '#2a1f0a',
    success: '#4cb96b',
    primary: '#5a9cf2',
    primarySoft: '#1a2740'
  };

  const mono = '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace';
  const sans = '"Inter", -apple-system, sans-serif';

  const S = {
    page: {
      minHeight: '100%', background: c.bg, color: c.text,
      fontFamily: sans, fontSize: 14, lineHeight: 1.5
    },
    topbar: {
      display: 'flex', alignItems: 'center', gap: 20,
      padding: '14px 28px', borderBottom: `1px solid ${c.border}`,
      background: c.panelLow
    },
    brand: { display: 'flex', alignItems: 'center', gap: 10, fontWeight: 600 },
    brandMark: {
      width: 24, height: 24, borderRadius: 5, background: c.danger,
      display: 'grid', placeItems: 'center', color: '#fff', fontSize: 13, fontWeight: 700
    },
    // Alert bar — F-pattern entry. Grande, alta saturação, 1 só na tela.
    alertBar: {
      margin: '0 28px', marginTop: 20,
      padding: '16px 24px', borderRadius: 10,
      background: `linear-gradient(180deg, ${c.dangerSoft} 0%, ${c.panel} 100%)`,
      border: `1px solid ${c.danger}55`,
      display: 'flex', alignItems: 'center', gap: 20,
      boxShadow: `inset 0 0 0 1px ${c.danger}10`
    },
    alertIcon: {
      width: 40, height: 40, borderRadius: 8,
      background: c.danger, display: 'grid', placeItems: 'center',
      color: '#fff', fontSize: 20, fontWeight: 700,
      boxShadow: `0 0 20px ${c.danger}55`
    },
    body: { padding: '20px 28px 32px' },
    kpiRow: {
      display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16,
      marginBottom: 20
    },
    kpi: {
      background: c.panel, border: `1px solid ${c.border}`,
      borderRadius: 10, padding: '20px 24px'
    },
    kpiLabel: {
      fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase',
      color: c.muted, fontWeight: 600, marginBottom: 12
    },
    kpiValue: {
      fontFamily: mono, fontSize: 36, fontWeight: 600, lineHeight: 1,
      color: c.textBold, fontVariantNumeric: 'tabular-nums',
      letterSpacing: '-0.02em'
    },
    kpiSub: { fontSize: 12.5, color: c.muted, marginTop: 8 },
    hero: {
      display: 'grid', gridTemplateColumns: '1.55fr 1fr', gap: 16,
      marginBottom: 20
    },
    panel: {
      background: c.panel, border: `1px solid ${c.border}`,
      borderRadius: 10, overflow: 'hidden'
    },
    panelHead: {
      padding: '14px 20px', borderBottom: `1px solid ${c.borderSoft}`,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between'
    },
    panelTitle: {
      fontSize: 12, fontWeight: 600, letterSpacing: '0.08em',
      textTransform: 'uppercase', color: c.muted
    },
    pill: (kind) => ({
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '4px 10px', borderRadius: 14, fontSize: 11.5, fontWeight: 500,
      background: kind === 'danger' ? c.dangerSoft : kind === 'amber' ? c.amberSoft : c.primarySoft,
      color: kind === 'danger' ? c.danger : kind === 'amber' ? c.amber : c.primary,
      fontFamily: mono
    }),
    pillBtn: (active) => ({
      padding: '6px 12px', borderRadius: 6, fontSize: 12, fontWeight: 500,
      background: active ? c.primarySoft : 'transparent',
      color: active ? c.primary : c.muted,
      border: `1px solid ${active ? c.primary + '66' : c.borderSoft}`,
      cursor: 'pointer', fontFamily: mono
    }),
    details: {
      background: c.panel, border: `1px solid ${c.border}`, borderRadius: 10,
      marginBottom: 12, overflow: 'hidden'
    },
    summary: {
      padding: '14px 20px', cursor: 'pointer',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      listStyle: 'none', userSelect: 'none'
    },
    summaryTitle: {
      fontSize: 12, fontWeight: 600, letterSpacing: '0.08em',
      textTransform: 'uppercase', color: c.text,
      display: 'flex', alignItems: 'center', gap: 10
    },
    table: {
      width: '100%', borderCollapse: 'collapse', fontSize: 13
    },
    th: {
      textAlign: 'left', padding: '12px 16px',
      borderBottom: `1px solid ${c.border}`,
      fontWeight: 600, color: c.muted,
      fontSize: 11, letterSpacing: '0.08em', textTransform: 'uppercase',
      background: c.panelLow
    },
    td: {
      padding: '12px 16px',
      fontVariantNumeric: 'tabular-nums'
    }
  };

  const totalRisk = data.transactions.reduce((s, t) => s + t.amount, 0);
  const cyclesValue = data.cycles.reduce((s, cy) => s + cy.total, 0);
  const activeCycle = data.cycles[selectedCycle];
  const sortedAccounts = data.topAccounts.slice().sort((a, b) => b.risk - a.risk);
  const top5 = sortedAccounts.slice(0, 5);
  const stepEntries = Object.entries(data.stepDist).sort((a, b) => +a[0] - +b[0]);
  const maxStepTotal = Math.max(...stepEntries.map(([, v]) => v.total));

  return (
    <div style={S.page}>
      {/* TOPBAR — minimal, brand + dataset state */}
      <div style={S.topbar}>
        <div style={S.brand}>
          <div style={S.brandMark}>F</div>
          <span style={{ fontSize: 15 }}></span>
          <span style={{ fontFamily: mono, fontSize: 11.5, color: c.faint, marginLeft: 4 }}></span>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14, fontSize: 12.5, color: c.muted }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 7, height: 7, borderRadius: 4, background: c.success }} />
            online
          </span>
          <span style={{ color: c.faint }}>·</span>
          <span style={{ fontFamily: mono }}>exemplo_transacoes.csv</span>
          <span style={{ color: c.faint }}>·</span>
          <span style={{ fontFamily: mono }}>análise há 2min</span>
          <button style={{
            marginLeft: 12, padding: '7px 14px', borderRadius: 6,
            background: 'transparent', color: c.text, border: `1px solid ${c.border}`,
            fontSize: 12, fontFamily: sans, cursor: 'pointer'
          }}>Re-analisar</button>
        </div>
      </div>

      {/* ALERT BAR — única instância de alarme do topo */}
      <div style={S.alertBar}>
        <div style={S.alertIcon}>!</div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 16, fontWeight: 600, color: c.textBold, marginBottom: 4 }}>
            <span style={{ color: c.danger }}>2 ciclos suspeitos</span> detectados em 10 transações analisadas
          </div>
          <div style={{ fontSize: 13, color: c.muted }}>
            <span style={{ fontFamily: mono, color: c.text, fontWeight: 500 }}>{fmtBRL(cyclesValue)}</span> em circulação · 6 contas envolvidas · revisão recomendada
          </div>
        </div>
        <button style={{
          padding: '10px 18px', borderRadius: 7, background: c.danger, color: '#fff',
          border: 'none', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: sans
        }}>Revisar ciclos →</button>
      </div>

      <div style={S.body}>

        {/* KPI STRIP — neutros, sem cor exceto onde há ação */}
        <div style={S.kpiRow}>
          <div style={S.kpi}>
            <div style={S.kpiLabel}>Vértices</div>
            <div style={S.kpiValue}>{data.stats.vertexCount}</div>
            <div style={S.kpiSub}>contas no grafo</div>
          </div>
          <div style={S.kpi}>
            <div style={S.kpiLabel}>Arestas</div>
            <div style={S.kpiValue}>{data.stats.edgeCount}</div>
            <div style={S.kpiSub}>transações observadas</div>
          </div>
          <div style={S.kpi}>
            <div style={S.kpiLabel}>Volume total</div>
            <div style={S.kpiValue}>{fmtBRLshort(totalRisk)}</div>
            <div style={S.kpiSub}>movimentado · 6 steps</div>
          </div>
          <div style={{ ...S.kpi, borderColor: c.danger + '55', background: `linear-gradient(180deg, ${c.dangerSoft}, ${c.panel})` }}>
            <div style={{ ...S.kpiLabel, color: c.danger }}>Em risco</div>
            <div style={{ ...S.kpiValue, color: c.danger }}>{fmtBRLshort(cyclesValue)}</div>
            <div style={S.kpiSub}>{data.cycles.length} ciclos · {data.stats.fraudCount} labels</div>
          </div>
        </div>

        {/* HERO — grafo (foco) + ciclo ativo (contexto) */}
        <div style={S.hero}>
          {/* GRAFO */}
          <div style={S.panel}>
            <div style={S.panelHead}>
              <div style={S.panelTitle}>Grafo de transações</div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                {/* Toggle: exibir valores nas arestas */}
                <button
                  onClick={() => setShowEdgeAmounts((v) => !v)}
                  aria-pressed={showEdgeAmounts}
                  title="Exibir valores nas arestas do grafo"
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 8,
                    padding: '6px 10px 6px 12px', borderRadius: 6,
                    background: showEdgeAmounts ? c.primarySoft : 'transparent',
                    color: showEdgeAmounts ? c.primary : c.muted,
                    border: `1px solid ${showEdgeAmounts ? c.primary + '66' : c.borderSoft}`,
                    cursor: 'pointer', fontFamily: mono, fontSize: 11.5
                  }}>
                  Valores nas arestas
                  <span style={{
                    width: 26, height: 14, borderRadius: 8, position: 'relative',
                    background: showEdgeAmounts ? c.primary : c.borderSoft,
                    transition: 'background .15s'
                  }}>
                    <span style={{
                      position: 'absolute', top: 1, left: showEdgeAmounts ? 13 : 1,
                      width: 12, height: 12, borderRadius: 6, background: '#fff',
                      transition: 'left .15s'
                    }} />
                  </span>
                </button>
                <span style={{ width: 1, height: 18, background: c.borderSoft, margin: '0 4px' }} />
                {[
                ['force', 'Force'],
                ['hierarchical', 'Hierárquico'],
                ['circular', 'Circular']].
                map(([id, label]) =>
                <button key={id} style={S.pillBtn(id === 'force')}>{label}</button>
                )}
              </div>
            </div>
            <div style={{ padding: 16, height: 480, background: c.panelLow, position: 'relative' }}>
              <GraphViewClean data={data} layout="force" colors={c} hoveredCycle={selectedCycle} showAmounts={showEdgeAmounts} />
              {/* Legend overlay */}
              <div style={{
                position: 'absolute', bottom: 20, left: 20,
                background: c.panel + 'ee', border: `1px solid ${c.border}`,
                borderRadius: 8, padding: '10px 14px', fontSize: 12, color: c.muted,
                display: 'flex', flexDirection: 'column', gap: 6, backdropFilter: 'blur(8px)'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 5, background: c.danger }} />
                  <span>Conta em ciclo</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 5, background: 'transparent', border: `1.5px solid ${c.muted}` }} />
                  <span>Conta normal</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 18, height: 2, background: c.danger }} />
                  <span>Aresta de ciclo (com valor)</span>
                </div>
              </div>
            </div>
          </div>

          {/* CICLO ATIVO */}
          <div style={S.panel}>
            <div style={S.panelHead}>
              <div style={S.panelTitle}>Ciclo selecionado</div>
              <div style={{ display: 'flex', gap: 6 }}>
                {data.cycles.map((cy, i) =>
                <button key={cy.id}
                onClick={() => setSelectedCycle(i)}
                style={S.pillBtn(selectedCycle === i)}>
                    #{cy.id}
                  </button>
                )}
              </div>
            </div>

            <div style={{ padding: 24 }}>
              {/* Cabeçalho do ciclo */}
              <div style={{ marginBottom: 24 }}>
                <div style={{ fontSize: 12, color: c.muted, marginBottom: 6, fontWeight: 500 }}>caminho detectado</div>
                <div style={{ fontFamily: mono, fontSize: 17, color: c.textBold, fontWeight: 500, letterSpacing: '-0.01em' }}>
                  {activeCycle.path.join(' → ')}
                </div>
              </div>

              {/* Timeline vertical compacta */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                {activeCycle.path.map((node, ni) => {
                  const edge = ni < activeCycle.edges.length ? activeCycle.edges[ni] : null;
                  const isLast = ni === activeCycle.path.length - 1;
                  return (
                    <React.Fragment key={ni}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                        <div style={{
                          width: 36, height: 36, borderRadius: 18,
                          background: c.dangerBg, border: `1.5px solid ${c.danger}`,
                          display: 'grid', placeItems: 'center',
                          fontFamily: mono, fontSize: 11, fontWeight: 700, color: c.danger,
                          flexShrink: 0
                        }}>{node}</div>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 13, color: c.text, fontWeight: 500 }}>
                            {ni === 0 ? 'Origem' : isLast ? 'Retorno à origem' : `Intermediária ${ni}`}
                          </div>
                          <div style={{ fontSize: 11.5, color: c.muted, fontFamily: mono }}>
                            risk score {data.accountRisk[node] || '—'} / 100
                          </div>
                        </div>
                      </div>
                      {!isLast && edge &&
                      <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '4px 0', marginLeft: 17 }}>
                          <div style={{ width: 2, height: 32, background: c.danger, opacity: 0.4 }} />
                          <div style={{
                          background: c.dangerSoft, border: `1px solid ${c.danger}33`,
                          borderRadius: 6, padding: '6px 12px',
                          display: 'flex', alignItems: 'center', gap: 12,
                          flex: 1
                        }}>
                            <span style={{ fontFamily: mono, fontSize: 14, fontWeight: 600, color: c.danger, fontVariantNumeric: 'tabular-nums' }}>
                              {fmtBRL(edge.amount)}
                            </span>
                            <span style={{ fontFamily: mono, fontSize: 11, color: c.muted, marginLeft: 'auto' }}>
                              {edge.type} · t={edge.step}
                            </span>
                          </div>
                        </div>
                      }
                    </React.Fragment>);

                })}
              </div>

              {/* Stats do ciclo */}
              <div style={{
                marginTop: 24, paddingTop: 20, borderTop: `1px solid ${c.borderSoft}`,
                display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16
              }}>
                <div>
                  <div style={{ fontSize: 11, color: c.muted, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 4 }}>Total</div>
                  <div style={{ fontFamily: mono, fontSize: 16, fontWeight: 600, color: c.textBold }}>{fmtBRLshort(activeCycle.total)}</div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: c.muted, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 4 }}>Perda</div>
                  <div style={{ fontFamily: mono, fontSize: 16, fontWeight: 600, color: c.amber }}>
                    {fmtBRLshort(activeCycle.edges[0].amount - activeCycle.edges[activeCycle.edges.length - 1].amount)}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: c.muted, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 4 }}>Duração</div>
                  <div style={{ fontFamily: mono, fontSize: 16, fontWeight: 600, color: c.text }}>{activeCycle.duration} steps</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* RISK ROW — top 5 contas em cards horizontais (não barras verticais) */}
        <div style={{ ...S.panel, marginBottom: 12 }}>
          <div style={S.panelHead}>
            <div style={S.panelTitle}>Top contas por risco</div>
            <span style={{ fontSize: 12, color: c.muted, fontFamily: mono }}>
              {top5.length} de {sortedAccounts.length}
            </span>
          </div>
          <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
            {top5.map((a) => {
              const tone = a.risk >= 80 ? 'danger' : a.risk >= 40 ? 'amber' : null;
              const toneColor = tone === 'danger' ? c.danger : tone === 'amber' ? c.amber : c.success;
              return (
                <div key={a.id} style={{
                  background: c.panelLow,
                  border: `1px solid ${c.borderSoft}`,
                  borderLeft: `3px solid ${toneColor}`,
                  borderRadius: 8, padding: '12px 14px'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                    <span style={{ fontFamily: mono, fontSize: 13, fontWeight: 600, color: c.text }}>{a.id}</span>
                    <span style={{ fontFamily: mono, fontSize: 18, fontWeight: 600, color: toneColor, lineHeight: 1 }}>{a.risk}</span>
                  </div>
                  <div style={{ fontSize: 11, color: c.muted, marginBottom: 6 }}>
                    volume · <span style={{ color: c.text, fontFamily: mono }}>{fmtBRLshort(a.volume)}</span>
                  </div>
                  <div style={{ height: 4, background: c.borderSoft, borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ height: 4, width: `${a.risk}%`, background: toneColor, borderRadius: 2 }} />
                  </div>
                </div>);

            })}
          </div>
        </div>

        {/* PROGRESSIVE DISCLOSURE — secundários colapsados */}
        <details style={S.details}>
          <summary style={S.summary}>
            <div style={S.summaryTitle}>
              <span style={{ color: c.muted }}>▸</span>
              Tabela de transações
              <span style={{ ...S.pill('amber'), marginLeft: 4 }}>{data.transactions.length} registros</span>
            </div>
            <span style={{ fontSize: 12, color: c.muted }}>{data.stats.fraudCount} marcadas como fraude</span>
          </summary>
          <table style={S.table}>
            <thead><tr>
              <th style={S.th}>step</th>
              <th style={S.th}>tipo</th>
              <th style={{ ...S.th, textAlign: 'right' }}>amount</th>
              <th style={S.th}>origem</th>
              <th style={S.th}>destino</th>
              <th style={{ ...S.th, textAlign: 'center' }}>fraude</th>
              <th style={S.th}>flags</th>
            </tr></thead>
            <tbody>
              {data.transactions.map((t, i) => {
                const inCycle = data.cycles.some((cy) => cy.edges.some((e) => e.src === t.src && e.dst === t.dst));
                const zebra = i % 2 === 1 ? c.panelLow : 'transparent';
                return (
                  <tr key={i} style={{ background: zebra }}>
                    <td style={{ ...S.td, fontFamily: mono, color: c.muted }}>{t.step}</td>
                    <td style={{ ...S.td, fontFamily: mono, fontSize: 12 }}>{t.type}</td>
                    <td style={{ ...S.td, textAlign: 'right', fontFamily: mono, fontWeight: 500 }}>{fmtBRL(t.amount)}</td>
                    <td style={{ ...S.td, fontFamily: mono }}>{t.src}</td>
                    <td style={{ ...S.td, fontFamily: mono }}>{t.dst}</td>
                    <td style={{ ...S.td, textAlign: 'center' }}>
                      {t.isFraud ?
                      <span style={S.pill('danger')}>1</span> :
                      <span style={{ color: c.faint, fontFamily: mono }}>0</span>}
                    </td>
                    <td style={{ ...S.td, fontSize: 11.5 }}>
                      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                        {inCycle && <span style={S.pill('amber')}>EM CICLO</span>}
                        {t.isFraud && <span style={S.pill('danger')}>LABELED</span>}
                      </span>
                    </td>
                  </tr>);

              })}
            </tbody>
          </table>
        </details>

        <details style={S.details}>
          <summary style={S.summary}>
            <div style={S.summaryTitle}>
              <span style={{ color: c.muted }}>▸</span>
              Distribuição & valores
            </div>
            <span style={{ fontSize: 12, color: c.muted, fontFamily: mono }}>
              60% &gt; R$ 10k · spike no step 4
            </span>
          </summary>
          <div style={{ padding: '20px 24px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 32 }}>
            <div>
              <div style={{ fontSize: 12, color: c.muted, marginBottom: 12, fontWeight: 500 }}>Por valor</div>
              {data.buckets.map((b) => {
                const max = Math.max(...data.buckets.map((x) => x.count));
                const w = b.count / max * 100;
                const isHigh = b.min >= 10000;
                return (
                  <div key={b.label} style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
                    <span style={{ fontFamily: mono, fontSize: 12, color: c.muted, width: 64, textAlign: 'right' }}>{b.label}</span>
                    <div style={{ flex: 1, height: 22, background: c.panelLow, borderRadius: 4, overflow: 'hidden', position: 'relative' }}>
                      <div style={{
                        height: 22, width: `${w}%`,
                        background: isHigh ? c.amber : c.primary, opacity: 0.8
                      }} />
                      <span style={{
                        position: 'absolute', left: 10, top: 2,
                        fontSize: 12, color: c.text, fontFamily: mono, fontWeight: 500
                      }}>{b.count}</span>
                    </div>
                  </div>);

              })}
            </div>
            <div>
              <div style={{ fontSize: 12, color: c.muted, marginBottom: 12, fontWeight: 500 }}>Por step temporal</div>
              {stepEntries.map(([step, v]) => {
                const wTotal = v.total / maxStepTotal * 100;
                const wFraud = v.fraud / maxStepTotal * 100;
                return (
                  <div key={step} style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
                    <span style={{ fontFamily: mono, fontSize: 12, color: c.muted, width: 64, textAlign: 'right' }}>step {step}</span>
                    <div style={{ flex: 1, height: 22, background: c.panelLow, borderRadius: 4, overflow: 'hidden', position: 'relative' }}>
                      <div style={{ height: 22, width: `${wTotal}%`, background: c.primary, opacity: 0.7 }} />
                      {v.fraud > 0 &&
                      <div style={{
                        position: 'absolute', top: 0, left: 0,
                        height: 22, width: `${wFraud}%`, background: c.danger
                      }} />
                      }
                      <span style={{
                        position: 'absolute', left: 10, top: 2,
                        fontSize: 12, color: c.text, fontFamily: mono, fontWeight: 500
                      }}>
                        {v.fraud > 0 && <span style={{ color: c.danger }}>{v.fraud}/</span>}{v.total}
                      </span>
                    </div>
                  </div>);

              })}
            </div>
          </div>
        </details>

        <details style={S.details}>
          <summary style={S.summary}>
            <div style={S.summaryTitle}>
              <span style={{ color: c.muted }}>▸</span>
              Log de execução
            </div>
            <span style={{ fontSize: 12, color: c.muted, fontFamily: mono }}>DFS · 0.8ms</span>
          </summary>
          <div style={{ padding: '16px 24px 20px', fontFamily: mono, fontSize: 12.5, lineHeight: 1.8, color: c.muted }}>
            {[
            ['14:32:08', 'OK', 'CSV carregado · 10 linhas', c.success],
            ['14:32:08', 'OK', 'Grafo construído · V=10, E=10', c.success],
            ['14:32:08', '··', 'Iniciando DFS', c.primary],
            ['14:32:08', '!!', 'Ciclo encontrado · C001 → C002 → C003 → C001', c.danger],
            ['14:32:08', '!!', 'Ciclo encontrado · C006 → C007 → C008 → C006', c.danger],
            ['14:32:08', 'OK', 'DFS completo · 0.8ms · 2 ciclos detectados', c.success]].
            map(([ts, lvl, msg, col], i) =>
            <div key={i} style={{ display: 'flex', gap: 12 }}>
                <span style={{ color: c.faint, width: 80 }}>{ts}</span>
                <span style={{ color: col, width: 30, fontWeight: 700 }}>{lvl}</span>
                <span style={{ color: c.text }}>{msg}</span>
              </div>
            )}
          </div>
        </details>

        {/* Footer */}
        <div style={{
          marginTop: 24, paddingTop: 16, borderTop: `1px solid ${c.borderSoft}`,
          fontSize: 11.5, color: c.faint, fontFamily: mono,
          display: 'flex', justifyContent: 'space-between'
        }}>
          <span></span>
          <span></span>
        </div>
      </div>
    </div>);

};

// ─── Grafo redesenhado: arestas normais a 35% opacidade, sem labels ───
const GraphViewClean = ({ data, layout = 'force', colors, hoveredCycle = null, showAmounts = false }) => {
  const positions = layout === 'hierarchical' ? data.positionsHierarchical :
  layout === 'circular' ? data.positionsCircular :
  data.positions;
  const c = colors;

  const cycleEdgeSet = React.useMemo(() => {
    const s = new Set();
    data.cycles.forEach((cy, ci) => cy.edges.forEach((e) => s.add(`${e.src}->${e.dst}#${ci}`)));
    return s;
  }, [data]);

  const cycleVertexSet = React.useMemo(() => {
    const s = new Set();
    data.cycles.forEach((cy) => cy.path.forEach((v) => s.add(v)));
    return s;
  }, [data]);

  const isInCycle = (src, dst) => {
    for (let ci = 0; ci < data.cycles.length; ci++) {
      if (cycleEdgeSet.has(`${src}->${dst}#${ci}`)) return ci;
    }
    return -1;
  };

  const buildEdgePath = (a, b, dir = 1) => {
    const dx = b.x - a.x,dy = b.y - a.y;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const r = 22;
    const ux = dx / len,uy = dy / len;
    const sx = a.x + ux * r,sy = a.y + uy * r;
    const ex = b.x - ux * r,ey = b.y - uy * r;
    const mx = (sx + ex) / 2,my = (sy + ey) / 2;
    const offset = 28 * dir;
    const cx = mx - uy * offset,cy = my + ux * offset;
    return { d: `M ${sx} ${sy} Q ${cx} ${cy} ${ex} ${ey}`, mid: { x: cx, y: cy } };
  };

  const edgeIdx = {};
  const edges = data.transactions.map((t, i) => {
    const a = positions[t.src],b = positions[t.dst];
    if (!a || !b) return null;
    const k = `${t.src}-${t.dst}`;
    edgeIdx[k] = (edgeIdx[k] || 0) + 1;
    const dir = edgeIdx[k] % 2 === 0 ? -1 : 1;
    const ci = isInCycle(t.src, t.dst);
    const inCycle = ci >= 0;
    const isActive = hoveredCycle == null || ci === hoveredCycle;
    const { d, mid } = buildEdgePath(a, b, dir);
    return { id: i, d, mid, inCycle, isActive, amount: t.amount, type: t.type };
  }).filter(Boolean);

  return (
    <svg viewBox="0 0 800 480" width="100%" height="100%" style={{ display: 'block', overflow: 'visible' }}>
      <defs>
        <marker id="cv2-arr-norm" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill={c.muted} opacity="0.5" />
        </marker>
        <marker id="cv2-arr-cyc" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill={c.danger} />
        </marker>
        <filter id="cv2-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      {/* Halo ciclos (apenas ativo) */}
      {edges.filter((e) => e.inCycle && e.isActive).map((e) =>
      <path key={`h${e.id}`} d={e.d} fill="none" stroke={c.danger} strokeWidth="10" strokeOpacity="0.18" strokeLinecap="round" />
      )}

      {/* Arestas normais — opacidade baixa, sem labels */}
      {edges.filter((e) => !e.inCycle).map((e) =>
      <path key={`n${e.id}`} d={e.d} fill="none"
      stroke={c.muted}
      strokeWidth="1.25"
      strokeOpacity={hoveredCycle != null ? 0.18 : 0.35}
      markerEnd="url(#cv2-arr-norm)" />
      )}

      {/* Arestas de ciclo — destacadas; label de valor só quando showAmounts=true */}
      {edges.filter((e) => e.inCycle).map((e) =>
      <g key={`c${e.id}`} opacity={e.isActive ? 1 : 0.25}>
          <path d={e.d} fill="none" stroke={c.danger} strokeWidth="2.25" markerEnd="url(#cv2-arr-cyc)" />
          {showAmounts &&
        <g>
              <rect x={e.mid.x - 28} y={e.mid.y - 9} width="56" height="18" rx="9"
          fill={c.panel} stroke={c.danger} strokeWidth="1" />
              <text x={e.mid.x} y={e.mid.y + 4} fill={c.danger}
          fontSize="10.5" fontWeight="600" textAnchor="middle"
          style={{ fontFamily: '"JetBrains Mono", monospace' }}>
                {e.amount >= 1000 ? `R$${(e.amount / 1000).toFixed(1)}k` : `R$${e.amount.toFixed(0)}`}
              </text>
            </g>
        }
        </g>
      )}

      {/* Nós */}
      {data.vertices.map((v) => {
        const p = positions[v];
        if (!p) return null;
        const inC = cycleVertexSet.has(v);
        return (
          <g key={v}>
            {inC && <circle cx={p.x} cy={p.y} r="22" fill={c.danger} opacity="0.15" filter="url(#cv2-glow)" />}
            <circle cx={p.x} cy={p.y} r="22"
            fill={inC ? c.dangerBg : c.panel}
            stroke={inC ? c.danger : c.muted}
            strokeWidth={inC ? 2 : 1.25}
            strokeOpacity={inC ? 1 : 0.55} />
            <text x={p.x} y={p.y + 4}
            fill={inC ? c.danger : c.text}
            fontSize="11" fontWeight={inC ? 700 : 500}
            textAnchor="middle"
            style={{ fontFamily: '"JetBrains Mono", monospace', pointerEvents: 'none' }}>
              {v}
            </text>
          </g>);

      })}
    </svg>);

};

window.VariationCv2 = VariationCv2;