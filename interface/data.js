// Dataset de exemplo (dados/exemplo_transacoes.csv)
// 10 contas, 10 transações, 2 fraudes rotuladas, 2 ciclos detectáveis
window.FRAUD_DATA = (() => {
  const transactions = [
    // Ciclo 1: C001 → C002 → C003 → C001
    { step: 1, type: 'TRANSFER',  amount: 10000.00, src: 'C001', dst: 'C002', isFraud: 0 },
    { step: 1, type: 'TRANSFER',  amount: 10000.00, src: 'C002', dst: 'C003', isFraud: 0 },
    { step: 2, type: 'TRANSFER',  amount:  9800.00, src: 'C003', dst: 'C001', isFraud: 1 },
    // Aresta solta entre clusters
    { step: 2, type: 'PAYMENT',   amount:  1250.50, src: 'C002', dst: 'C004', isFraud: 0 },
    { step: 3, type: 'CASH_OUT',  amount:  4500.00, src: 'C004', dst: 'C005', isFraud: 0 },
    // Ciclo 2: C006 → C007 → C008 → C006
    { step: 3, type: 'TRANSFER',  amount: 25000.00, src: 'C006', dst: 'C007', isFraud: 0 },
    { step: 4, type: 'TRANSFER',  amount: 24800.00, src: 'C007', dst: 'C008', isFraud: 0 },
    { step: 4, type: 'TRANSFER',  amount: 24500.00, src: 'C008', dst: 'C006', isFraud: 1 },
    // Periféricos
    { step: 5, type: 'PAYMENT',   amount:   880.00, src: 'C009', dst: 'C005', isFraud: 0 },
    { step: 6, type: 'CASH_OUT',  amount:  3200.00, src: 'C010', dst: 'C009', isFraud: 0 },
  ];

  // Vértices únicos
  const vertices = [...new Set(transactions.flatMap(t => [t.src, t.dst]))].sort();

  // Ciclos detectados pela DFS (ordem como aparece no CLI)
  const cycles = [
    {
      id: 1,
      path: ['C001', 'C002', 'C003', 'C001'],
      edges: [
        { src: 'C001', dst: 'C002', amount: 10000.00, type: 'TRANSFER', step: 1 },
        { src: 'C002', dst: 'C003', amount: 10000.00, type: 'TRANSFER', step: 1 },
        { src: 'C003', dst: 'C001', amount:  9800.00, type: 'TRANSFER', step: 2 },
      ],
      total: 29800.00,
      duration: 2, // steps
    },
    {
      id: 2,
      path: ['C006', 'C007', 'C008', 'C006'],
      edges: [
        { src: 'C006', dst: 'C007', amount: 25000.00, type: 'TRANSFER', step: 3 },
        { src: 'C007', dst: 'C008', amount: 24800.00, type: 'TRANSFER', step: 4 },
        { src: 'C008', dst: 'C006', amount: 24500.00, type: 'TRANSFER', step: 4 },
      ],
      total: 74300.00,
      duration: 2,
    },
  ];

  // Posições force-directed pré-calculadas (deterministicas, layout limpo)
  // Canvas conceitual 800x520
  const positions = {
    C001: { x: 220, y: 160 },
    C002: { x: 360, y: 100 },
    C003: { x: 360, y: 220 },
    C004: { x: 480, y:  60 },
    C005: { x: 600, y: 130 },
    C006: { x: 220, y: 380 },
    C007: { x: 360, y: 320 },
    C008: { x: 360, y: 440 },
    C009: { x: 600, y: 320 },
    C010: { x: 720, y: 380 },
  };

  // Posição hierárquica (top-down por step)
  const positionsHierarchical = {
    C001: { x: 140, y: 100 },
    C002: { x: 320, y: 100 },
    C003: { x: 500, y: 100 },
    C004: { x: 680, y: 100 },
    C005: { x: 140, y: 240 },
    C006: { x: 320, y: 240 },
    C007: { x: 500, y: 240 },
    C008: { x: 680, y: 240 },
    C009: { x: 230, y: 380 },
    C010: { x: 590, y: 380 },
  };

  // Posição circular
  const positionsCircular = (() => {
    const out = {};
    const cx = 400, cy = 270, r = 200;
    vertices.forEach((v, i) => {
      const a = (i / vertices.length) * Math.PI * 2 - Math.PI / 2;
      out[v] = { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
    });
    return out;
  })();

  // Score de risco por conta (0-100). Contas em ciclos = alto.
  const accountRisk = {
    C001: 92, C002: 88, C003: 95,
    C006: 91, C007: 86, C008: 94,
    C004: 18, C005: 12, C009:  9, C010:  6,
  };

  // Top contas por volume (saída)
  const topAccounts = (() => {
    const vol = {};
    transactions.forEach(t => { vol[t.src] = (vol[t.src] || 0) + t.amount; });
    return Object.entries(vol)
      .map(([id, v]) => ({ id, volume: v, risk: accountRisk[id] }))
      .sort((a, b) => b.volume - a.volume);
  })();

  // Histograma de valores (buckets log)
  const buckets = [
    { label: '< 1k',     min: 0,     max: 1000,    count: 0 },
    { label: '1k–5k',    min: 1000,  max: 5000,    count: 0 },
    { label: '5k–10k',   min: 5000,  max: 10000,   count: 0 },
    { label: '10k–25k',  min: 10000, max: 25000,   count: 0 },
    { label: '> 25k',    min: 25000, max: Infinity,count: 0 },
  ];
  transactions.forEach(t => {
    const b = buckets.find(b => t.amount >= b.min && t.amount < b.max);
    if (b) b.count++;
  });

  // Distribuição por step (timeline)
  const stepDist = {};
  transactions.forEach(t => {
    if (!stepDist[t.step]) stepDist[t.step] = { total: 0, fraud: 0 };
    stepDist[t.step].total++;
    if (t.isFraud) stepDist[t.step].fraud++;
  });

  return {
    transactions,
    vertices,
    cycles,
    positions,
    positionsHierarchical,
    positionsCircular,
    accountRisk,
    topAccounts,
    buckets,
    stepDist,
    stats: {
      vertexCount: vertices.length,
      edgeCount: transactions.length,
      fraudCount: transactions.filter(t => t.isFraud).length,
      cycleCount: cycles.length,
    },
  };
})();
