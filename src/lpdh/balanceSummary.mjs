const amount = value => Number.isFinite(Number(value)) ? Number(value) : 0;

// Same component equation as E_Saldo; expenditure uses the report preview.
export function balanceSummary(daily, preview) {
  const balance = daily.balance || {};
  const rows = [
    ['raw', 'Biaya Bahan Baku Pangan', 'openingRaw', 'rawAmount'],
    ['operational', 'Biaya Operasional', 'openingOperational', 'operationalAmount'],
    ['incentive', 'Insentif Ketersediaan dan Mutu Layanan', 'openingIncentive', 'incentiveAmount'],
  ].map(([key, label, openingField, topupField]) => {
    const opening = amount(balance[openingField]);
    const topup = (daily.topups || []).reduce((sum, row) => sum + amount(row[topupField]), 0);
    const expenditure = key === 'incentive' ? amount(daily.incentive?.paidAmount) : amount(preview?.balance?.expenditure?.[key]);
    return {key, label, opening, topup, expenditure, closing: opening + topup - expenditure};
  });
  const total = field => rows.reduce((sum, row) => sum + row[field], 0);
  const bankEntered = balance.bankBalance != null && String(balance.bankBalance).trim() !== '';
  return {rows, opening: total('opening'), topup: total('topup'), expenditure: total('expenditure'), closing: total('closing'), bankEntered,
    bank: amount(balance.bankBalance), difference: total('closing') - amount(balance.bankBalance)};
}
