export function savedDailyMatches(daily, saved) {
  return Boolean(saved) && JSON.stringify(daily) === saved;
}

export function pendingReview(preview) {
  if (!preview) return preview;
  return { ...preview, ready: false, awaitingDailySave: true, incentiveCalculated: 0,
    production: { ...preview.production, incentivePm: 0 },
    topup: { ...preview.topup, requiredIncentive: 0,
      proposalTotal: Number(preview.topup?.requiredRaw || 0) + Number(preview.topup?.requiredOperational || 0),
      requiredTotal: Number(preview.topup?.requiredRaw || 0) + Number(preview.topup?.requiredOperational || 0) } };
}

