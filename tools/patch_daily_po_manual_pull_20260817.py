from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    a = text.find(start)
    if a < 0:
        raise SystemExit(f"{path}: start anchor not found: {start!r}")
    b = text.find(end, a)
    if b < 0:
        raise SystemExit(f"{path}: end anchor not found: {end!r}")
    p.write_text(text[:a] + replacement + text[b:], encoding="utf-8")


path = "src/operations/OperationsPoPlanner.jsx"

replace_once(
    path,
    '  const [planningSnapshot, setPlanningSnapshot] = useState(null);\n  const [draftItems, setDraftItems] = useState([]);',
    '  const [planningSnapshot, setPlanningSnapshot] = useState(null);\n  const [draftItems, setDraftItems] = useState([]);\n  const [dailyPulled, setDailyPulled] = useState(false);',
)

new_load_block = r'''  const loadBase = async () => {
    setLoading(true);
    setError("");
    try {
      // PO history, vendor contacts, and reminders remain live even before the
      // operator pulls a daily planning/stok working set.
      const [poData, vendorsData, reminderData] = await Promise.all([
        operationsApi.getPurchaseOrders({ site: activeSite, limit: 50 }),
        operationsApi.getReferenceVendors(activeSite),
        operationsApi.getPoReminders({ site: activeSite, date: today(), horizonDays: 21 }),
      ]);
      setPurchaseOrders(poData?.items || []);
      setReminders(reminderData?.items || []);

      const uniqueVendors = new Map(FALLBACK_VENDORS.map(([code, name]) => [code, { code, name }]));
      (vendorsData?.items || []).forEach((item) => {
        if (item?.code) uniqueVendors.set(String(item.code).toUpperCase(), { code: String(item.code).toUpperCase(), name: item.name || item.code });
      });
      setVendorOptions(Array.from(uniqueVendors.values()).sort((a, b) => a.name.localeCompare(b.name, "id")));
      const phones = {};
      (vendorsData?.items || []).forEach((item) => {
        if (item?.code && item?.metadata?.whatsapp_phone) phones[String(item.code).toUpperCase()] = String(item.metadata.whatsapp_phone);
      });
      setVendorPhones(phones);
      setPhoneValue(phones[phoneVendor] || "");
    } catch (err) {
      setError(err.message || "Gagal menarik daftar PO, vendor, atau pengingat");
    } finally {
      setLoading(false);
    }
  };

  const pullDailyData = async () => {
    setLoading(true);
    setDailyPulled(true);
    setError("");
    setMessage("");
    try {
      const [scheduleData, snapshotsData, inventoryData, cooperativeData] = await Promise.all([
        operationsApi.previewPoSchedule({ distributionDate, cookingDate, site: activeSite }),
        operationsApi.getPlanningSnapshots({ site: activeSite, distributionDate, activeOnly: true }),
        operationsApi.getInventoryBalances({ site: activeSite, search: "", limit: 1000, forDate: distributionDate }),
        operationsApi.getInventoryBalances({ site: "KOPERASI", search: "", limit: 1000, forDate: distributionDate }),
      ]);
      setSchedule(scheduleData?.items || []);
      const snapshots = snapshotsData?.items || [];
      if (!snapshots.length) {
        applyPlanningSnapshot(null, inventoryData?.items || [], cooperativeData?.items || []);
        setMessage(`Data ${activeSite} ${distributionDate} sudah ditarik, tetapi planning aktif belum tersedia.`);
        return;
      }
      const detail = await operationsApi.getPlanningSnapshot(snapshots[0].id);
      applyPlanningSnapshot(detail, inventoryData?.items || [], cooperativeData?.items || []);
      setMessage(`Planning + stok ${activeSite} untuk distribusi ${distributionDate} berhasil ditarik. Data ini hanya working set PO dan boleh dibersihkan tanpa menghapus PO tersimpan.`);
    } catch (planningError) {
      setSchedule([]);
      applyPlanningSnapshot(null, [], []);
      setError(`Rencana Kalkulator untuk tanggal ini belum tersedia. PO yang sudah tersimpan tetap ditampilkan. ${planningError.message || ""}`.trim());
    } finally {
      setLoading(false);
    }
  };

  const clearDailyPulledData = () => {
    setSchedule([]);
    setPlanningSnapshot(null);
    setDraftItems([]);
    setDailyPulled(false);
    setError("");
    setMessage("Semua hasil tarikan PO harian dibersihkan dari layar. PO yang sudah tersimpan tidak dihapus.");
  };

  const clearVendorPulledData = (vendor) => {
    setDraftItems((current) => current.filter((item) => (item.vendor_code || "UNASSIGNED") !== vendor));
    setMessage(`Hasil tarikan ${vendor} dibersihkan dari layar. PO vendor yang sudah tersimpan tetap aman.`);
  };

  useEffect(() => { loadBase(); }, [activeSite]);

  // Ganti tanggal/site tidak boleh otomatis menarik planning/stok. Operator harus
  // menekan Tarik Data, sama seperti alur PO gabungan beberapa hari.
  useEffect(() => {
    setSchedule([]);
    setPlanningSnapshot(null);
    setDraftItems([]);
    setDailyPulled(false);
  }, [distributionDate, cookingDate, activeSite]);

'''
replace_between(
    path,
    "  const load = async () => {\n",
    "  const groupedDrafts = useMemo(() => {\n",
    new_load_block + "  const groupedDrafts = useMemo(() => {\n",
)

replace_once(
    path,
    "      await load();\n      setMessage(result?.message || \"Stok dapur dikoreksi dan reminder dihitung ulang.\");",
    "      await refreshReminders();\n      if (dailyPulled) await pullDailyData();\n      setMessage(result?.message || \"Stok dapur dikoreksi dan reminder dihitung ulang.\");",
)

replace_once(
    path,
    '''          <button type="button" onClick={load} disabled={loading}><RefreshCw size={15} /> {loading ? "Menarik..." : "Tarik Data Kalkulator + Stok"}</button>''',
    '''          <div className="ops-row-actions">\n            <button className="ops-button-primary" type="button" onClick={pullDailyData} disabled={loading}><RefreshCw size={15} /> {loading ? "Menarik..." : "Tarik Data Kalkulator + Stok"}</button>\n            {dailyPulled && <button type="button" onClick={clearDailyPulledData} disabled={loading}><Trash2 size={15} /> Bersihkan Semua</button>}\n          </div>''',
)

replace_once(
    path,
    '''        {!loading && !planningSnapshot && (\n          <div className="ops-notice">\n            Belum ada planning snapshot Kalkulator untuk <strong>{activeSite}</strong> tanggal {distributionDate}. PO tidak dibuat dari tebakan.\n          </div>\n        )}''',
    '''        {!loading && !dailyPulled && (\n          <div className="ops-notice">\n            Data PO harian belum ditarik. Pilih site/tanggal lalu tekan <strong>Tarik Data Kalkulator + Stok</strong>. Mengganti tanggal tidak akan menarik data otomatis.\n          </div>\n        )}\n        {!loading && dailyPulled && !planningSnapshot && (\n          <div className="ops-notice">\n            Belum ada planning snapshot Kalkulator untuk <strong>{activeSite}</strong> tanggal {distributionDate}. PO tidak dibuat dari tebakan.\n          </div>\n        )}''',
)

replace_once(
    path,
    '''                  {existingPo && <button type="button" onClick={() => existingStatus === "DRAFT" ? beginEditPo(existingPo) : viewPoDetail(existingPo)} disabled={actionId === existingPo.id}>\n                    {existingStatus === "DRAFT" ? <Pencil size={15} /> : <Eye size={15} />} {existingStatus === "DRAFT" ? "Buka & Edit PO" : "Lihat PO"}\n                  </button>}''',
    '''                  {existingPo && <div className="ops-row-actions">\n                    <button type="button" onClick={() => existingStatus === "DRAFT" ? beginEditPo(existingPo) : viewPoDetail(existingPo)} disabled={actionId === existingPo.id}>\n                      {existingStatus === "DRAFT" ? <Pencil size={15} /> : <Eye size={15} />} {existingStatus === "DRAFT" ? "Buka & Edit PO" : "Lihat PO"}\n                    </button>\n                    <button type="button" onClick={() => clearVendorPulledData(group.vendor)} title="Bersihkan hanya hasil tarikan vendor ini; PO tersimpan tidak dihapus"><Trash2 size={15} /> Bersihkan Vendor</button>\n                  </div>}''',
)

print("daily PO manual pull + clear patch applied")
