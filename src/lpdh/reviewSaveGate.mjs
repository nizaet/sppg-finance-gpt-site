export function savedDailyMatches(daily, saved) {
  return Boolean(saved) && JSON.stringify(daily) === saved;
}

export function pendingReview(preview) {
  if (!preview) return preview;
  const source=preview.balance;
  const balance=source ? {...source,expenditure:{...source.expenditure,incentive:0}} : undefined;
  if(balance){
    balance.closing=Object.fromEntries(['raw','operational','incentive'].map(key=>[key,
      Number(balance.opening?.[key]||0)+Number(balance.topups?.[key]||0)-Number(balance.expenditure?.[key]||0)]));
    balance.closingTotal=Object.values(balance.closing).reduce((sum,value)=>sum+value,0);
    balance.bankDifference=balance.closingTotal-Number(balance.bankBalance||0);
  }
  const proposalTotal=Number(preview.topup?.requiredRaw||0)+Number(preview.topup?.requiredOperational||0);
  return { ...preview, ready: false, awaitingDailySave: true, incentiveCalculated: 0,
    balance,
    production: { ...preview.production, incentivePm: 0 },
    topup: { ...preview.topup, requiredIncentive: 0,
      proposalTotal, requiredTotal:proposalTotal,
      withinMax: proposalTotal<=Number(preview.topup?.roomToMax||0) } };
}

