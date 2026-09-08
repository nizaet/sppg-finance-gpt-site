import React from 'react';

export default function OperationsSiteSwitcher({ title, label, sites, activeSite, onChange }) {
  return (
    <section className="ops-site-switcher" aria-label={label}>
      <strong>{title}</strong>
      <div className="ops-po-site-tabs" role="group" aria-label={label}>
        {sites.map(([site, name]) => (
          <button key={site} type="button" aria-pressed={activeSite === site}
            className={activeSite === site ? 'active' : ''} onClick={() => onChange(site)}>
            {name}
          </button>
        ))}
      </div>
    </section>
  );
}
