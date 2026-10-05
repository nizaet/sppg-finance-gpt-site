import React, { useEffect, useState } from "react";
import { documentApi } from "./documentApi.js";

export const ASSET_FIELDS = [
  ["letterheadAssetId", "LETTERHEAD", "Logo / kop surat"],
  ["stampAssetId", "STAMP", "Stempel penerbit"],
  ["signatureAssetId", "SIGNATURE", "Tanda tangan penerbit"],
  ["recipientSignatureAssetId", "RECIPIENT_SIGNATURE", "Tanda tangan penerima (invoice saja)"],
];

function AssetField({ field, kind, label, id, site, disabled, onUpload, onRemove }) {
  const [asset, setAsset] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setAsset(null); setError("");
    if (id) documentApi.asset(id).then(value => { if (active) setAsset(value); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [id, site]);
  return <div className="doc-asset"><label className="doc-field"><span>{label}</span><input type="file" aria-label={`Unggah ${label}`} disabled={disabled} accept="image/png,image/jpeg,image/webp" onChange={e => { const file = e.target.files?.[0]; e.target.value = ""; if (file) onUpload(file, kind, field); }}/></label>
    {asset && <><img alt={label} src={`data:${asset.mimeType};base64,${asset.contentBase64}`}/><small>{asset.filename}</small></>}
    {error && <small role="alert">{error}</small>}
    {id && <button type="button" disabled={disabled} onClick={() => onRemove(field)}>Lepas dari isian ini</button>}
  </div>;
}

export default function DocumentAssets({ header, site, disabled, onUpload, onRemove }) {
  return <><p className="doc-hint">Gambar PNG/JPG/WebP maksimal 5 MB dan 16 megapiksel. Gunakan PNG transparan untuk stempel/TTD. Disimpan privat per dapur. TTD penerima tidak diterapkan ke kuitansi individu.</p><div className="doc-asset-grid">{ASSET_FIELDS.map(([field, kind, label]) => <AssetField key={field} field={field} kind={kind} label={label} id={header[field]} site={site} disabled={disabled} onUpload={onUpload} onRemove={onRemove}/>)}</div></>;
}
