export const OPERATION_TABS = ['today', 'po', 'receiving', 'inventory', 'calculator-data', 'menu-advisor', 'payments', 'accounting', 'vendors', 'review', 'hermes', 'chat'];
export const SITE_TABS = {
  po: ['MAJA', 'CEMPLANG'],
  inventory: ['MAJA', 'CEMPLANG', 'KOPERASI'],
  vendors: ['ALL', 'MAJA', 'CEMPLANG'],
};

export function normalizeOperationsRoute(tab, site) {
  const validTab = OPERATION_TABS.includes(tab) ? tab : 'today';
  const sites = SITE_TABS[validTab];
  return { tab: validTab, site: sites ? (sites.includes(site) ? site : sites[0]) : '' };
}

export function readOperationsRoute(location = window.location) {
  const tab = location.pathname.replace(/\/+$/, '').split('/')[2] || 'today';
  return normalizeOperationsRoute(tab, new URLSearchParams(location.search).get('site'));
}

export function operationsUrl(tab, site) {
  const route = normalizeOperationsRoute(tab, site);
  return `/operations${route.tab === 'today' ? '' : `/${route.tab}`}${route.site ? `?site=${route.site}` : ''}`;
}

export function operationsRouteKey(route) {
  return `${route.tab}:${route.site}`;
}
