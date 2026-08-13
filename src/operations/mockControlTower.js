export const mockControlTower = {
  date: new Date().toISOString().slice(0, 10),
  sites: [
    {
      siteId: "sppg-maja-gpt-site",
      siteLabel: "SPPG MAJA BARU",
      summary: {
        poDueToday: 0,
        poOverdue: 0,
        deliveriesExpected: 0,
        unresolvedRejects: 0,
        paymentsDue: 0,
        reviewQueue: 0,
      },
      lanes: {
        procurement: [],
        receiving: [],
        payments: [],
        costing: [],
        accountant: [],
        bgn: [],
      },
    },
    {
      siteId: "sppg-cemplang2-gpt-site",
      siteLabel: "SPPG CEMPLANG 2",
      summary: {
        poDueToday: 0,
        poOverdue: 0,
        deliveriesExpected: 0,
        unresolvedRejects: 0,
        paymentsDue: 0,
        reviewQueue: 0,
      },
      lanes: {
        procurement: [],
        receiving: [],
        payments: [],
        costing: [],
        accountant: [],
        bgn: [],
      },
    },
  ],
};
